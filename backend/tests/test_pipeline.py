import asyncio
import tempfile
import unittest
from datetime import date, timedelta, timezone
from pathlib import Path
from typing import Any

from pipecat.processors.aggregators.llm_context import LLMContext

from backend.app.appointment_service import AppointmentService
from backend.app.json_store import JsonClinicRepository
from backend.app.pipeline import build_system_instruction, create_appointment_tools
from backend.app.tools import AppointmentToolAdapter, CallConfirmationState


SEED_PATH = Path(__file__).parents[1] / "data" / "seed.json"


class _FunctionCallParams:
    def __init__(self) -> None:
        self.result: dict[str, Any] | None = None

    async def result_callback(self, result: dict[str, Any]) -> None:
        self.result = result


class PipelineToolRegistrationTests(unittest.TestCase):
    def test_system_instruction_includes_clinic_local_date(self) -> None:
        instruction = build_system_instruction(date(2026, 11, 25))

        self.assertIn("Current clinic-local date: 2026-11-25.", instruction)
        self.assertIn("Resolve relative dates such as today and tomorrow", instruction)

    def test_direct_functions_register_with_pipecat_and_return_adapter_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = JsonClinicRepository(
                Path(temporary_directory) / "state.json",
                SEED_PATH,
            )
            service = AppointmentService(
                repository,
                timezone(timedelta(hours=5, minutes=30)),
            )
            adapter = AppointmentToolAdapter(service, CallConfirmationState())
            functions = create_appointment_tools(adapter)
            context = LLMContext(tools=functions)

            self.assertEqual(
                [
                    "check_doctor_availability",
                    "book_appointment",
                    "cancel_appointment",
                ],
                [tool.name for tool in context.tools.standard_tools],
            )
            self.assertEqual(3, len(context.tools.direct_functions))

            params = _FunctionCallParams()
            asyncio.run(functions[0](params, specialty_id="cardiology"))

            result = params.result
            if result is None:
                self.fail("Pipecat function callback did not return a tool result.")
            self.assertTrue(result["ok"])
            self.assertEqual(
                {"slot-201", "slot-202", "slot-204"},
                {slot["id"] for slot in result["slots"]},
            )


if __name__ == "__main__":
    unittest.main()
