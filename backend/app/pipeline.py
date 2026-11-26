import sys
from collections.abc import Awaitable, Callable
from datetime import date, datetime

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import (
    PipelineParams,
    PipelineWorker,
    ProcessorUnusablePolicy,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments, SmallWebRTCRunnerArguments
from pipecat.services.elevenlabs.stt import (
    CommitStrategy,
    ElevenLabsRealtimeSTTService,
)
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from backend.app.appointment_service import AppointmentService
from backend.app.config import ConfigurationError, load_settings
from backend.app.json_store import JsonClinicRepository
from backend.app.tools import AppointmentToolAdapter, CallConfirmationState


SYSTEM_INSTRUCTION = """\
You are a concise, friendly clinic appointment assistant. You can only help with
doctor availability, booking, and cancelling. Do not give medical advice.

Use the appointment tools for all availability and appointment facts. Never
invent doctors, times, appointments, or successful changes. A tool result with
ok=false is not success.

The caller is identified only by the phone number they speak. Ask them to say
their number if it is missing. Before booking or cancelling, the tool will
return a confirmation_required result. Read the phone number exactly as digits,
repeat the selected doctor's name and appointment time, then ask a clear yes-or-no
question. Do not call the mutation tool again until the caller answers. Never
claim a booking or cancellation succeeded unless the tool returns ok=true.

For cancellation, look up appointments using the spoken phone number. If the
tool returns appointment_selection_required, describe the options and ask which
one the caller means; pass the selected appointment_id on the next tool call.
Do not disclose appointment details before the caller supplies the spoken
phone-number lookup key.

Your spoken responses should be brief and natural. Do not expose internal IDs
unless needed to resolve an appointment selection.
"""


def build_system_instruction(clinic_date: date) -> str:
    return (
        f"{SYSTEM_INSTRUCTION}\n"
        f"Current clinic-local date: {clinic_date.isoformat()}. Resolve relative "
        "dates such as today and tomorrow from this date; do not infer a different "
        "year. Pass dates to availability tools as YYYY-MM-DD."
    )


def configure_runtime_logging() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")


def create_appointment_tools(
    adapter: AppointmentToolAdapter,
) -> list[Callable[..., Awaitable[None]]]:
    async def check_doctor_availability(
        params: FunctionCallParams,
        doctor_id: str | None = None,
        specialty_id: str | None = None,
        on_date: str | None = None,
    ) -> None:
        """Find real available appointment slots.

        Args:
            doctor_id: Optional doctor ID returned by a previous availability result.
            specialty_id: Optional specialty ID returned by the clinic data.
            on_date: Optional requested clinic date in YYYY-MM-DD format.
        """
        arguments = {
            key: value
            for key, value in (
                ("doctor_id", doctor_id),
                ("specialty_id", specialty_id),
                ("on_date", on_date),
            )
            if value is not None
        }
        await params.result_callback(
            adapter.execute("check_doctor_availability", arguments)
        )

    async def book_appointment(
        params: FunctionCallParams,
        slot_id: str,
        phone_number: str,
    ) -> None:
        """Book a selected slot after the caller confirms the read-back.

        Args:
            slot_id: ID of an available slot returned by the availability tool.
            phone_number: Phone number spoken by the caller.
        """
        await params.result_callback(
            adapter.execute(
                "book_appointment",
                {"slot_id": slot_id, "phone_number": phone_number},
            )
        )

    async def cancel_appointment(
        params: FunctionCallParams,
        phone_number: str,
        appointment_id: str | None = None,
    ) -> None:
        """Cancel an active appointment after selection and caller confirmation.

        Args:
            phone_number: Phone number spoken by the caller.
            appointment_id: Selected appointment ID, if the caller chose one.
        """
        arguments = {"phone_number": phone_number}
        if appointment_id is not None:
            arguments["appointment_id"] = appointment_id
        await params.result_callback(
            adapter.execute("cancel_appointment", arguments)
        )

    return [
        check_doctor_availability,
        book_appointment,
        cancel_appointment,
    ]


async def bot(runner_args: RunnerArguments) -> None:
    configure_runtime_logging()
    if not isinstance(runner_args, SmallWebRTCRunnerArguments):
        raise ConfigurationError(
            "This development entry point currently supports the local WebRTC transport. "
            "Start it with -t webrtc."
        )

    settings = load_settings(require_voice_credentials=True)
    if (
        settings.google_api_key is None
        or settings.elevenlabs_api_key is None
        or settings.elevenlabs_voice_id is None
    ):
        raise ConfigurationError("Voice provider configuration is incomplete.")

    repository = JsonClinicRepository(settings.state_path, settings.seed_path)
    service = AppointmentService(repository, settings.clinic_timezone)
    adapter = AppointmentToolAdapter(service, CallConfirmationState())

    transport = SmallWebRTCTransport(
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
        webrtc_connection=runner_args.webrtc_connection,
    )
    stt = ElevenLabsRealtimeSTTService(
        api_key=settings.elevenlabs_api_key,
        commit_strategy=CommitStrategy.VAD,
        settings=ElevenLabsRealtimeSTTService.Settings(
            model=settings.elevenlabs_stt_model,
        ),
    )
    llm = GoogleLLMService(
        api_key=settings.google_api_key,
        settings=GoogleLLMService.Settings(
            model=settings.gemini_model,
            system_instruction=build_system_instruction(
                datetime.now(settings.clinic_timezone).date()
            ),
        ),
    )
    tts = ElevenLabsTTSService(
        api_key=settings.elevenlabs_api_key,
        settings=ElevenLabsTTSService.Settings(
            model=settings.elevenlabs_tts_model,
            voice=settings.elevenlabs_voice_id,
        ),
    )

    context = LLMContext(tools=create_appointment_tools(adapter))
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        processor_unusable_policy=ProcessorUnusablePolicy.END,
    )
    runner = WorkerRunner()
    await runner.add_workers(worker)

    @user_aggregator.event_handler("on_user_turn_message_added")
    async def on_user_turn_message_added(_aggregator, message) -> None:
        adapter.observe_caller_turn(message.content)

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def on_assistant_turn_stopped(_aggregator, message) -> None:
        if not message.interrupted:
            adapter.mark_confirmation_prompt_presented(message.content)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(_transport, _webrtc_connection) -> None:
        logger.info("Browser voice client connected")
        context.add_message(
            {
                "role": "developer",
                "content": "Greet the caller and ask how you can help with an appointment.",
            }
        )
        await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport, _webrtc_connection) -> None:
        logger.info("Browser voice client disconnected")
        adapter.end_call()
        await runner.cancel()

    await runner.run()


if __name__ == "__main__":
    from pipecat.runner.run import app, main

    settings = load_settings()
    repository = JsonClinicRepository(settings.state_path, settings.seed_path)
    from backend.app.dashboard_api import create_dashboard_router

    app.include_router(
        create_dashboard_router(repository, settings.clinic_timezone)
    )

    main()
