import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.appointment_service import (
    ActionConfirmation,
    AppointmentAction,
    AppointmentService,
)
from backend.app.dashboard_api import create_dashboard_router
from backend.app.json_store import JsonClinicRepository


SEED_PATH = Path(__file__).parents[1] / "data" / "seed.json"
CLINIC_TIMEZONE = ZoneInfo("Asia/Kolkata")
PHONE_NUMBER = "+919876543210"


class DashboardApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        repository = JsonClinicRepository(
            Path(self.temporary_directory.name) / "state.json",
            SEED_PATH,
        )
        self.service = AppointmentService(repository, CLINIC_TIMEZONE)
        app = FastAPI()
        app.include_router(create_dashboard_router(repository, CLINIC_TIMEZONE))
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temporary_directory.cleanup()

    def test_dashboard_returns_clinic_data_without_caller_phone_numbers(self) -> None:
        response = self.client.get("/api/clinic")

        self.assertEqual(200, response.status_code)
        snapshot = response.json()
        self.assertEqual("Asia/Kolkata", snapshot["timezone"])
        self.assertEqual(3, len(snapshot["doctors"]))
        self.assertEqual(4, len(snapshot["availableSlots"]))
        self.assertEqual([], snapshot["appointments"])
        self.assertNotIn("callerPhone", response.text)

    def test_dashboard_reflects_booking_and_does_not_expose_phone_number(self) -> None:
        self.service.book_appointment(
            "slot-203",
            PHONE_NUMBER,
            ActionConfirmation(
                AppointmentAction.BOOK,
                "slot-203",
                PHONE_NUMBER,
            ),
        )

        response = self.client.get("/api/clinic")

        self.assertEqual(200, response.status_code)
        snapshot = response.json()
        self.assertNotIn("slot-203", {slot["id"] for slot in snapshot["availableSlots"]})
        self.assertEqual("booked", snapshot["appointments"][0]["status"])
        self.assertNotIn(PHONE_NUMBER, response.text)


if __name__ == "__main__":
    unittest.main()
