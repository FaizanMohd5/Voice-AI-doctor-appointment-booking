import argparse
import json
from typing import Sequence

from backend.app.appointment_service import AppointmentService
from backend.app.config import Settings, load_settings
from backend.app.json_store import JsonClinicRepository
from backend.app.tools import AppointmentToolAdapter, CallConfirmationState


def _add_filter_arguments(
    parser: argparse.ArgumentParser,
    default: object = None,
) -> None:
    parser.add_argument("--date", default=default, help="clinic date in YYYY-MM-DD format")
    parser.add_argument("--doctor", default=default, help="filter by doctor ID")
    parser.add_argument("--specialty", default=default, help="filter by specialty ID")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview clinic data or manually exercise appointment tools."
    )
    _add_filter_arguments(parser)
    subparsers = parser.add_subparsers(dest="command")

    availability_parser = subparsers.add_parser(
        "availability",
        aliases=["check"],
        help="check available appointment slots",
    )
    _add_filter_arguments(availability_parser, argparse.SUPPRESS)

    book_parser = subparsers.add_parser("book", help="manually test booking a slot")
    book_parser.add_argument("--slot-id", required=True, help="ID of an available slot")
    book_parser.add_argument(
        "--phone-number",
        required=True,
        help="phone number spoken by the test caller",
    )

    cancel_parser = subparsers.add_parser(
        "cancel",
        help="manually test cancellation by spoken phone number",
    )
    cancel_parser.add_argument(
        "--phone-number",
        required=True,
        help="phone number spoken by the test caller",
    )
    cancel_parser.add_argument(
        "--appointment-id",
        help="selected appointment ID (needed if multiple appointments match)",
    )
    return parser


def _create_adapter(settings: Settings) -> AppointmentToolAdapter:
    repository = JsonClinicRepository(settings.state_path, settings.seed_path)
    service = AppointmentService(repository, settings.clinic_timezone)
    return AppointmentToolAdapter(service, CallConfirmationState())


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _preview(
    settings: Settings,
    adapter: AppointmentToolAdapter,
    filters: dict[str, str],
) -> int:
    service = AppointmentService(
        JsonClinicRepository(settings.state_path, settings.seed_path),
        settings.clinic_timezone,
    )
    result = adapter.execute("check_doctor_availability", filters)
    if not result.get("ok"):
        _print_json(result)
        return 1

    specialties = {item.id: item for item in service.list_specialties()}
    doctors = {item.id: item for item in service.list_doctors()}
    print("Clinic specialties:")
    for specialty in specialties.values():
        print(f"  {specialty.id}: {specialty.name}")
    print("\nDoctors:")
    for doctor in doctors.values():
        specialty_names = ", ".join(
            specialties[specialty_id].name for specialty_id in doctor.specialty_ids
        )
        print(f"  {doctor.id}: {doctor.name} ({specialty_names})")
    print(f"\nAvailable slots ({settings.clinic_timezone}):")
    slots = result["slots"]
    if not slots:
        print("  No available slots.")
        return 0
    for slot in slots:
        print(f"  {slot['id']}: {slot['doctor_name']} - {slot['starts_at']}")
    return 0


def _run_mutation(
    adapter: AppointmentToolAdapter,
    tool_name: str,
    arguments: dict[str, str],
) -> int:
    result = adapter.execute(tool_name, arguments)
    if result.get("code") == "appointment_selection_required":
        _print_json(result)
        print("Rerun the cancel command with --appointment-id set to the caller's choice.")
        return 2

    if result.get("code") == "confirmation_required":
        confirmation = result["confirmation"]
        target = confirmation.get("slot", confirmation.get("appointment"))
        action = "book" if tool_name == "book_appointment" else "cancel"
        prompt = (
            f"I heard {confirmation['phone_number']}. The appointment is with "
            f"{target['doctor_name']} at {target['starts_at']}. "
            f"Should I {action} it?"
        )
        print(f"Confirmation read-back: {prompt}")
        if not adapter.mark_confirmation_prompt_presented(prompt):
            _print_json(
                {
                    "ok": False,
                    "code": "confirmation_prompt_not_verified",
                    "message": (
                        "The confirmation read-back did not include the expected number, "
                        "doctor, and question. No change was made."
                    ),
                }
            )
            return 1

        try:
            caller_response = input("Caller response (type a clear yes to continue): ")
        except EOFError:
            adapter.end_call()
            print("No confirmation received. No change was made.")
            return 1
        if not adapter.observe_caller_turn(caller_response):
            print("Confirmation was not clear. No change was made.")
            return 1
        result = adapter.execute(tool_name, arguments)

    _print_json(result)
    return 0 if result.get("ok") else 1


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    settings = load_settings()
    adapter = _create_adapter(settings)

    if arguments.command in ("availability", "check"):
        filters = {
            key: value
            for key, value in (
                ("doctor_id", arguments.doctor),
                ("specialty_id", arguments.specialty),
                ("on_date", arguments.date),
            )
            if value is not None
        }
        result = adapter.execute("check_doctor_availability", filters)
        _print_json(result)
        return 0 if result.get("ok") else 1
    if arguments.command == "book":
        return _run_mutation(
            adapter,
            "book_appointment",
            {
                "slot_id": arguments.slot_id,
                "phone_number": arguments.phone_number,
            },
        )
    if arguments.command == "cancel":
        cancellation_arguments = {"phone_number": arguments.phone_number}
        if arguments.appointment_id is not None:
            cancellation_arguments["appointment_id"] = arguments.appointment_id
        return _run_mutation(
            adapter,
            "cancel_appointment",
            cancellation_arguments,
        )
    filters = {
        key: value
        for key, value in (
            ("doctor_id", arguments.doctor),
            ("specialty_id", arguments.specialty),
            ("on_date", arguments.date),
        )
        if value is not None
    }
    return _preview(settings, adapter, filters)


if __name__ == "__main__":
    raise SystemExit(main())
