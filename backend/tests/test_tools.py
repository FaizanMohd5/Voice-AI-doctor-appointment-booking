import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path

from backend.app.appointment_service import (
    ActionConfirmation,
    AppointmentAction,
    AppointmentService,
)
from backend.app.json_store import JsonClinicRepository
from backend.app.models import AppointmentStatus
from backend.app.tools import (
    AppointmentToolAdapter,
    CallConfirmationState,
    TOOL_DECLARATIONS,
)


SEED_PATH = Path(__file__).parents[1] / "data" / "seed.json"
CLINIC_TIMEZONE = timezone(timedelta(hours=5, minutes=30))
PHONE_NUMBER = "+91 98765 43210"


class AppointmentToolAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temporary_directory.name) / "state.json"
        repository = JsonClinicRepository(self.state_path, SEED_PATH)
        self.service = AppointmentService(repository, CLINIC_TIMEZONE)
        self.confirmation_state = CallConfirmationState()
        self.adapter = AppointmentToolAdapter(self.service, self.confirmation_state)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def book_directly(self, slot_id: str) -> str:
        appointment = self.service.book_appointment(
            slot_id,
            PHONE_NUMBER,
            ActionConfirmation(AppointmentAction.BOOK, slot_id, PHONE_NUMBER),
        )
        return appointment.id

    def present_confirmation(self, result: dict[str, object]) -> bool:
        confirmation = result["confirmation"]
        target = confirmation.get("slot", confirmation.get("appointment"))
        prompt = (
            f"I heard {confirmation['phone_number']}. Your appointment is with "
            f"{target['doctor_name']}. Should I proceed?"
        )
        return self.adapter.mark_confirmation_prompt_presented(prompt)

    def test_tool_schemas_do_not_allow_model_supplied_confirmation(self) -> None:
        schemas = {declaration["name"]: declaration for declaration in TOOL_DECLARATIONS}
        book_properties = schemas["book_appointment"]["parameters"]["properties"]
        cancel_properties = schemas["cancel_appointment"]["parameters"]["properties"]

        self.assertNotIn("confirmed", book_properties)
        self.assertNotIn("confirmation", book_properties)
        self.assertNotIn("confirmed", cancel_properties)
        self.assertNotIn("confirmation", cancel_properties)

    def test_availability_tool_returns_real_slots_and_rejects_bad_dates(self) -> None:
        result = self.adapter.execute(
            "check_doctor_availability",
            {"specialty_id": "cardiology", "on_date": "2026-12-01"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(["slot-201", "slot-202"], [slot["id"] for slot in result["slots"]])
        invalid_date = self.adapter.execute(
            "check_doctor_availability",
            {"on_date": "tomorrow"},
        )
        self.assertEqual("invalid_date", invalid_date["code"])

    def test_booking_waits_for_explicit_confirmation_and_confirmation_is_one_time(self) -> None:
        untrusted_confirmation = self.adapter.execute(
            "book_appointment",
            {"slot_id": "slot-201", "phone_number": PHONE_NUMBER, "confirmed": True},
        )
        self.assertEqual("invalid_arguments", untrusted_confirmation["code"])
        self.assertFalse(self.state_path.exists())

        pending = self.adapter.execute(
            "book_appointment",
            {"slot_id": "slot-201", "phone_number": PHONE_NUMBER},
        )
        self.assertEqual("confirmation_required", pending["code"])
        self.assertEqual("slot-201", pending["confirmation"]["slot"]["id"])
        self.assertFalse(self.state_path.exists())

        self.assertTrue(self.present_confirmation(pending))
        self.assertTrue(self.adapter.observe_caller_turn("Yes, please."))
        booked = self.adapter.execute(
            "book_appointment",
            {"slot_id": "slot-201", "phone_number": PHONE_NUMBER},
        )
        self.assertTrue(booked["ok"])
        self.assertEqual("booked", booked["appointment"]["status"])
        self.assertEqual(1, len(self.service.list_appointments()))

        unavailable = self.adapter.execute(
            "book_appointment",
            {"slot_id": "slot-201", "phone_number": PHONE_NUMBER},
        )
        self.assertEqual("slot_unavailable", unavailable["code"])

    def test_unclear_or_negative_response_does_not_authorize_booking(self) -> None:
        arguments = {"slot_id": "slot-201", "phone_number": PHONE_NUMBER}
        self.adapter.execute("book_appointment", arguments)
        pending = self.adapter.execute("book_appointment", arguments)
        self.assertTrue(self.present_confirmation(pending))
        self.assertFalse(self.adapter.observe_caller_turn("Yes, but change it to tomorrow."))

        result = self.adapter.execute("book_appointment", arguments)
        self.assertEqual("confirmation_required", result["code"])
        self.assertTrue(self.present_confirmation(result))
        self.adapter.observe_caller_turn("No.")
        self.assertFalse(self.state_path.exists())

    def test_affirmative_before_readback_is_not_confirmation(self) -> None:
        arguments = {"slot_id": "slot-201", "phone_number": PHONE_NUMBER}
        pending = self.adapter.execute("book_appointment", arguments)

        self.assertFalse(self.adapter.observe_caller_turn("Yes."))
        self.assertTrue(self.present_confirmation(pending))
        result = self.adapter.execute("book_appointment", arguments)
        self.assertEqual("confirmation_required", result["code"])
        self.assertFalse(self.state_path.exists())

    def test_question_before_readback_preserves_pending_confirmation(self) -> None:
        arguments = {"slot_id": "slot-201", "phone_number": PHONE_NUMBER}
        pending = self.adapter.execute("book_appointment", arguments)

        self.assertFalse(self.adapter.observe_caller_turn("Is it booked?"))
        self.assertTrue(self.present_confirmation(pending))
        self.assertTrue(self.adapter.observe_caller_turn("Yes."))

        booked = self.adapter.execute("book_appointment", arguments)
        self.assertTrue(booked["ok"])
        self.assertEqual(1, len(self.service.list_appointments()))

    def test_phone_change_invalidates_confirmation(self) -> None:
        self.adapter.execute(
            "book_appointment",
            {"slot_id": "slot-201", "phone_number": PHONE_NUMBER},
        )
        pending = self.adapter.execute(
            "book_appointment",
            {"slot_id": "slot-201", "phone_number": PHONE_NUMBER},
        )
        self.assertTrue(self.present_confirmation(pending))
        self.adapter.observe_caller_turn("Correct.")

        result = self.adapter.execute(
            "book_appointment",
            {"slot_id": "slot-201", "phone_number": "+91 98765 43211"},
        )

        self.assertEqual("confirmation_required", result["code"])
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.adapter.observe_caller_turn("I think yes."))

    def test_intervening_tool_call_invalidates_prior_confirmation(self) -> None:
        booking_arguments = {"slot_id": "slot-201", "phone_number": PHONE_NUMBER}
        pending = self.adapter.execute("book_appointment", booking_arguments)
        self.assertTrue(self.present_confirmation(pending))
        self.adapter.observe_caller_turn("Yes.")
        self.adapter.execute("check_doctor_availability", {})

        result = self.adapter.execute("book_appointment", booking_arguments)

        self.assertEqual("confirmation_required", result["code"])
        self.assertFalse(self.state_path.exists())

    def test_cancellation_requires_phone_match_and_confirmation(self) -> None:
        appointment_id = self.book_directly("slot-201")
        pending = self.adapter.execute(
            "cancel_appointment",
            {"phone_number": PHONE_NUMBER, "appointment_id": appointment_id},
        )
        self.assertEqual("confirmation_required", pending["code"])
        self.assertEqual(appointment_id, pending["confirmation"]["appointment"]["id"])

        self.assertTrue(self.present_confirmation(pending))
        self.assertFalse(self.adapter.observe_caller_turn("No, not that one."))
        still_pending = self.adapter.execute(
            "cancel_appointment",
            {"phone_number": PHONE_NUMBER, "appointment_id": appointment_id},
        )
        self.assertEqual("confirmation_required", still_pending["code"])

        self.assertTrue(self.present_confirmation(still_pending))
        self.adapter.observe_caller_turn("Go ahead.")
        cancelled = self.adapter.execute(
            "cancel_appointment",
            {"phone_number": PHONE_NUMBER, "appointment_id": appointment_id},
        )
        self.assertTrue(cancelled["ok"])
        self.assertEqual("cancelled", cancelled["appointment"]["status"])
        self.assertEqual(AppointmentStatus.CANCELLED, self.service.list_appointments()[0].status)

    def test_multiple_matching_appointments_require_selection(self) -> None:
        self.book_directly("slot-201")
        self.book_directly("slot-202")

        result = self.adapter.execute(
            "cancel_appointment",
            {"phone_number": PHONE_NUMBER},
        )

        self.assertEqual("appointment_selection_required", result["code"])
        self.assertEqual(2, len(result["appointments"]))

    def test_unknown_tools_and_unexpected_arguments_fail_closed(self) -> None:
        unknown = self.adapter.execute("delete_everything", {})
        self.assertEqual("unknown_tool", unknown["code"])
        malformed = self.adapter.execute(
            "cancel_appointment",
            {"phone_number": PHONE_NUMBER, "force": True},
        )
        self.assertEqual("invalid_arguments", malformed["code"])

    def test_ending_call_clears_confirmation_state(self) -> None:
        self.adapter.execute(
            "book_appointment",
            {"slot_id": "slot-201", "phone_number": PHONE_NUMBER},
        )
        pending = self.adapter.execute(
            "book_appointment",
            {"slot_id": "slot-201", "phone_number": PHONE_NUMBER},
        )
        self.assertTrue(self.present_confirmation(pending))
        self.adapter.observe_caller_turn("Yes.")
        self.adapter.end_call()

        result = self.adapter.execute(
            "book_appointment",
            {"slot_id": "slot-201", "phone_number": PHONE_NUMBER},
        )

        self.assertEqual("confirmation_required", result["code"])
        self.assertFalse(self.state_path.exists())


if __name__ == "__main__":
    unittest.main()
