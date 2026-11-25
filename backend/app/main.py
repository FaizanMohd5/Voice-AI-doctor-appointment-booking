import argparse
from datetime import date, timedelta, timezone
from pathlib import Path

from backend.app.appointment_service import AppointmentService
from backend.app.json_store import JsonClinicRepository


CLINIC_TIMEZONE = timezone(timedelta(hours=5, minutes=30))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview clinic specialties, doctors, and available appointment slots."
    )
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        help="filter slots by clinic date in YYYY-MM-DD format",
    )
    parser.add_argument("--doctor", help="filter slots by doctor ID")
    parser.add_argument("--specialty", help="filter slots by specialty ID")
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    project_root = Path(__file__).resolve().parents[2]
    data_directory = project_root / "backend" / "data"
    repository = JsonClinicRepository(
        state_path=data_directory / "state.json",
        seed_path=data_directory / "seed.json",
    )
    service = AppointmentService(repository, CLINIC_TIMEZONE)

    specialties = {item.id: item for item in service.list_specialties()}
    doctors = {item.id: item for item in service.list_doctors()}
    slots = service.find_available_slots(
        doctor_id=arguments.doctor,
        specialty_id=arguments.specialty,
        on_date=arguments.date,
    )

    print("Clinic specialties:")
    for specialty in specialties.values():
        print(f"  {specialty.id}: {specialty.name}")

    print("\nDoctors:")
    for doctor in doctors.values():
        specialty_names = ", ".join(
            specialties[specialty_id].name for specialty_id in doctor.specialty_ids
        )
        print(f"  {doctor.id}: {doctor.name} ({specialty_names})")

    print("\nAvailable slots (clinic timezone UTC+05:30):")
    if not slots:
        print("  No available slots match these filters.")
        return

    for slot in slots:
        doctor = doctors[slot.doctor_id]
        print(f"  {slot.id}: {doctor.name} - {slot.starts_at.isoformat()}")


if __name__ == "__main__":
    main()
