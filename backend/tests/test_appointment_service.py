import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, timezone
from pathlib import Path

from backend.app.appointment_service import (
    ActionConfirmation,
    AppointmentAction,
    AppointmentNotFoundError,
    AppointmentService,
    ConfirmationMismatchError,
    ConfirmationRequiredError,
    InvalidPhoneNumberError,
    SlotUnavailableError,
)
from backend.app.json_store import JsonClinicRepository, RepositoryError
from backend.app.models import AppointmentStatus, SlotStatus


SEED_PATH = Path(__file__).parents[1] / "data" / "seed.json"
CLINIC_TIMEZONE = timezone(timedelta(hours=5, minutes=30))


class AppointmentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temporary_directory.name) / "state.json"
        self.repository = JsonClinicRepository(self.state_path, SEED_PATH)
        self.service = AppointmentService(self.repository, CLINIC_TIMEZONE)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def confirmation(
        self,
        action: AppointmentAction,
        target_id: str,
        phone_number: str = "+91 98765 43210",
    ) -> ActionConfirmation:
        return ActionConfirmation(action, target_id, phone_number)

    def test_availability_filters_by_doctor_specialty_and_clinic_date(self) -> None:
        slots = self.service.find_available_slots(
            specialty_id="cardiology",
            on_date=date(2026, 12, 1),
        )

        self.assertEqual(["slot-201", "slot-202"], [slot.id for slot in slots])
        self.assertEqual(
            ["cardiology", "dermatology", "family-medicine"],
            [specialty.id for specialty in self.service.list_specialties()],
        )

    def test_booking_persists_and_marks_the_slot_unavailable(self) -> None:
        appointment = self.service.book_appointment(
            "slot-201",
            "+91 (98765) 43210",
            self.confirmation(AppointmentAction.BOOK, "slot-201"),
        )

        self.assertEqual(AppointmentStatus.BOOKED, appointment.status)
        self.assertEqual("+919876543210", appointment.caller_phone)
        self.assertTrue(self.state_path.exists())
        available_slot_ids = [
            slot.id for slot in self.service.find_available_slots(doctor_id="doctor-101")
        ]
        self.assertNotIn("slot-201", available_slot_ids)
        seed_data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        self.assertEqual([], seed_data["appointments"])
        self.assertIn(
            appointment,
            AppointmentService(self.repository, CLINIC_TIMEZONE).list_appointments(),
        )

    def test_duplicate_booking_and_confirmation_mismatch_do_not_mutate_data(self) -> None:
        with self.assertRaises(ConfirmationMismatchError):
            self.service.book_appointment(
                "slot-201",
                "+919876543210",
                self.confirmation(AppointmentAction.BOOK, "slot-202"),
            )
        with self.assertRaises(ConfirmationRequiredError):
            self.service.book_appointment("slot-201", "+919876543210", None)
        self.assertFalse(self.state_path.exists())

        self.service.book_appointment(
            "slot-201",
            "+919876543210",
            self.confirmation(AppointmentAction.BOOK, "slot-201"),
        )
        with self.assertRaises(SlotUnavailableError):
            self.service.book_appointment(
                "slot-201",
                "+919876543210",
                self.confirmation(AppointmentAction.BOOK, "slot-201"),
            )

    def test_phone_number_must_match_before_cancellation(self) -> None:
        appointment = self.service.book_appointment(
            "slot-201",
            "+919876543210",
            self.confirmation(AppointmentAction.BOOK, "slot-201"),
        )
        with self.assertRaises(AppointmentNotFoundError):
            self.service.cancel_appointment(
                appointment.id,
                "+919876543211",
                self.confirmation(
                    AppointmentAction.CANCEL,
                    appointment.id,
                    "+919876543211",
                ),
            )

    def test_cancellation_reopens_slot_and_retains_history(self) -> None:
        appointment = self.service.book_appointment(
            "slot-201",
            "+919876543210",
            self.confirmation(AppointmentAction.BOOK, "slot-201"),
        )
        cancelled = self.service.cancel_appointment(
            appointment.id,
            "+919876543210",
            self.confirmation(AppointmentAction.CANCEL, appointment.id),
        )

        self.assertEqual(AppointmentStatus.CANCELLED, cancelled.status)
        available_slot_ids = [
            slot.id for slot in self.service.find_available_slots(doctor_id="doctor-101")
        ]
        self.assertIn("slot-201", available_slot_ids)
        appointments = self.service.list_appointments()
        self.assertEqual(1, len(appointments))
        self.assertEqual(AppointmentStatus.CANCELLED, appointments[0].status)
        with self.assertRaises(AppointmentNotFoundError):
            self.service.cancel_appointment(
                appointment.id,
                "+919876543210",
                self.confirmation(AppointmentAction.CANCEL, appointment.id),
            )

    def test_concurrent_booking_attempts_cannot_reserve_the_same_slot(self) -> None:
        def book() -> str:
            try:
                appointment = self.service.book_appointment(
                    "slot-201",
                    "+919876543210",
                    self.confirmation(AppointmentAction.BOOK, "slot-201"),
                )
                return appointment.id
            except SlotUnavailableError:
                return "unavailable"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: book(), range(2)))

        self.assertEqual(1, sum(result != "unavailable" for result in results))
        self.assertEqual(1, len(self.service.list_appointments()))

    def test_invalid_phone_and_corrupt_json_fail_explicitly(self) -> None:
        with self.assertRaises(InvalidPhoneNumberError):
            self.service.find_active_appointments_for_phone("call me")

        self.state_path.write_text("{", encoding="utf-8")
        with self.assertRaises(RepositoryError):
            self.repository.load()

    def test_cli_lists_seed_slots_and_applies_date_filter(self) -> None:
        project_root = Path(__file__).parents[2]
        command = [sys.executable, "-m", "backend.app.main"]
        default_run = subprocess.run(
            command,
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
        filtered_run = subprocess.run(
            command + ["--date", "2026-12-02"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("slot-201", default_run.stdout)
        self.assertIn("slot-204", filtered_run.stdout)
        self.assertNotIn("slot-201", filtered_run.stdout)


if __name__ == "__main__":
    unittest.main()
