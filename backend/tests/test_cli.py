import contextlib
import io
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app import main
from backend.app.appointment_service import (
    ActionConfirmation,
    AppointmentAction,
    AppointmentService,
)
from backend.app.json_store import JsonClinicRepository
from backend.app.tools import AppointmentToolAdapter, CallConfirmationState


SEED_PATH = Path(__file__).parents[1] / "data" / "seed.json"
PHONE_NUMBER = "+91 98765 43210"


class ManualCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        state_path = Path(self.temporary_directory.name) / "state.json"
        repository = JsonClinicRepository(state_path, SEED_PATH)
        service = AppointmentService(repository, timezone(timedelta(hours=5, minutes=30)))
        self.adapter = AppointmentToolAdapter(service, CallConfirmationState())
        self.service = service
        self.state_path = state_path

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_booking_cli_requires_interactive_confirmation(self) -> None:
        output = io.StringIO()
        with patch("builtins.input", return_value="yes"), contextlib.redirect_stdout(output):
            exit_code = main._run_mutation(
                self.adapter,
                "book_appointment",
                {"slot_id": "slot-201", "phone_number": PHONE_NUMBER},
            )

        self.assertEqual(0, exit_code)
        self.assertIn("Confirmation read-back:", output.getvalue())
        self.assertEqual(1, len(self.service.list_appointments()))

    def test_booking_cli_rejects_non_exact_affirmation(self) -> None:
        output = io.StringIO()
        with patch(
            "builtins.input",
            return_value="yes, but book a different time",
        ), contextlib.redirect_stdout(output):
            exit_code = main._run_mutation(
                self.adapter,
                "book_appointment",
                {"slot_id": "slot-201", "phone_number": PHONE_NUMBER},
            )

        self.assertEqual(1, exit_code)
        self.assertIn("No change was made.", output.getvalue())
        self.assertFalse(self.state_path.exists())

    def test_cancellation_cli_confirms_the_selected_appointment(self) -> None:
        appointment = self.service.book_appointment(
            "slot-201",
            PHONE_NUMBER,
            ActionConfirmation(AppointmentAction.BOOK, "slot-201", PHONE_NUMBER),
        )
        output = io.StringIO()
        with patch("builtins.input", return_value="yes"), contextlib.redirect_stdout(output):
            exit_code = main._run_mutation(
                self.adapter,
                "cancel_appointment",
                {
                    "phone_number": PHONE_NUMBER,
                    "appointment_id": appointment.id,
                },
            )

        self.assertEqual(0, exit_code)
        self.assertIn("Confirmation read-back:", output.getvalue())
        self.assertEqual("cancelled", self.service.list_appointments()[0].status.value)

    def test_availability_parser_accepts_filters_after_subcommand(self) -> None:
        arguments = main.build_parser().parse_args(
            ["availability", "--specialty", "cardiology", "--date", "2026-12-01"]
        )

        self.assertEqual("cardiology", arguments.specialty)
        self.assertEqual("2026-12-01", arguments.date)


if __name__ == "__main__":
    unittest.main()
