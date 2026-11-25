import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from backend.app.models import (
    Appointment,
    AppointmentStatus,
    ClinicData,
    Doctor,
    Slot,
    SlotStatus,
    Specialty,
)


class RepositoryError(Exception):
    """Raised when clinic data cannot be read, validated, or persisted."""


class ClinicRepository(Protocol):
    def load(self) -> ClinicData: ...

    def save(self, data: ClinicData) -> None: ...


def _required_string(record: dict[str, Any], key: str, record_name: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{record_name}.{key} must be a non-empty string")
    return value


def _required_list(record: dict[str, Any], key: str, record_name: str) -> list[Any]:
    value = record.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{record_name}.{key} must be a list")
    return value


def _parse_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO 8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    return parsed


def _unique_records(records: list[Any], record_name: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError(f"Each {record_name} must be an object")
        record_id = _required_string(record, "id", record_name)
        if record_id in indexed:
            raise ValueError(f"Duplicate {record_name} id: {record_id}")
        indexed[record_id] = record
    return indexed


def clinic_data_from_dict(raw: Any) -> ClinicData:
    if not isinstance(raw, dict):
        raise ValueError("Clinic data must be a JSON object")

    specialty_records = _unique_records(
        _required_list(raw, "specialties", "clinic_data"), "specialty"
    )
    doctor_records = _unique_records(
        _required_list(raw, "doctors", "clinic_data"), "doctor"
    )
    slot_records = _unique_records(_required_list(raw, "slots", "clinic_data"), "slot")
    appointment_records = _unique_records(
        _required_list(raw, "appointments", "clinic_data"), "appointment"
    )

    specialties = {
        record_id: Specialty(
            id=record_id,
            name=_required_string(record, "name", f"specialty[{record_id}]"),
        )
        for record_id, record in specialty_records.items()
    }

    doctors: dict[str, Doctor] = {}
    for record_id, record in doctor_records.items():
        specialty_ids = _required_list(record, "specialtyIds", f"doctor[{record_id}]")
        if not all(isinstance(specialty_id, str) and specialty_id for specialty_id in specialty_ids):
            raise ValueError(f"doctor[{record_id}].specialtyIds must contain non-empty strings")
        if len(set(specialty_ids)) != len(specialty_ids):
            raise ValueError(f"doctor[{record_id}].specialtyIds must not contain duplicates")
        doctors[record_id] = Doctor(
            id=record_id,
            name=_required_string(record, "name", f"doctor[{record_id}]"),
            specialty_ids=tuple(specialty_ids),
        )

    slots: dict[str, Slot] = {}
    for record_id, record in slot_records.items():
        status_value = _required_string(record, "status", f"slot[{record_id}]")
        try:
            status = SlotStatus(status_value)
        except ValueError as exc:
            raise ValueError(f"slot[{record_id}].status is not supported") from exc
        slots[record_id] = Slot(
            id=record_id,
            doctor_id=_required_string(record, "doctorId", f"slot[{record_id}]"),
            starts_at=_parse_datetime(
                _required_string(record, "startsAt", f"slot[{record_id}]"),
                f"slot[{record_id}].startsAt",
            ),
            status=status,
        )

    appointments: dict[str, Appointment] = {}
    for record_id, record in appointment_records.items():
        status_value = _required_string(record, "status", f"appointment[{record_id}]")
        try:
            status = AppointmentStatus(status_value)
        except ValueError as exc:
            raise ValueError(f"appointment[{record_id}].status is not supported") from exc

        cancelled_at_value = record.get("cancelledAt")
        if cancelled_at_value is not None and not isinstance(cancelled_at_value, str):
            raise ValueError(f"appointment[{record_id}].cancelledAt must be a string or null")

        appointments[record_id] = Appointment(
            id=record_id,
            slot_id=_required_string(record, "slotId", f"appointment[{record_id}]"),
            doctor_id=_required_string(record, "doctorId", f"appointment[{record_id}]"),
            caller_phone=_required_string(record, "callerPhone", f"appointment[{record_id}]"),
            status=status,
            created_at=_parse_datetime(
                _required_string(record, "createdAt", f"appointment[{record_id}]"),
                f"appointment[{record_id}].createdAt",
            ),
            cancelled_at=(
                _parse_datetime(
                    cancelled_at_value, f"appointment[{record_id}].cancelledAt"
                )
                if cancelled_at_value is not None
                else None
            ),
        )

    data = ClinicData(
        specialties=specialties,
        doctors=doctors,
        slots=slots,
        appointments=appointments,
    )
    validate_clinic_data(data)
    return data


def validate_clinic_data(data: ClinicData) -> None:
    for specialty_id, specialty in data.specialties.items():
        if specialty_id != specialty.id or not specialty.name.strip():
            raise ValueError("Specialty keys and values must have matching IDs and names")

    for doctor_id, doctor in data.doctors.items():
        if doctor_id != doctor.id or not doctor.name.strip():
            raise ValueError("Doctor keys and values must have matching IDs and names")
        if not doctor.specialty_ids:
            raise ValueError(f"Doctor {doctor_id} must have at least one specialty")
        if any(specialty_id not in data.specialties for specialty_id in doctor.specialty_ids):
            raise ValueError(f"Doctor {doctor_id} references an unknown specialty")

    for slot_id, slot in data.slots.items():
        if slot_id != slot.id or slot.doctor_id not in data.doctors:
            raise ValueError(f"Slot {slot_id} references an unknown doctor or has an invalid ID")
        if slot.starts_at.tzinfo is None or slot.starts_at.utcoffset() is None:
            raise ValueError(f"Slot {slot_id} must have a timezone-aware start time")

    active_by_slot: dict[str, str] = {}
    for appointment_id, appointment in data.appointments.items():
        if appointment_id != appointment.id:
            raise ValueError(f"Appointment {appointment_id} has an invalid ID")
        slot = data.slots.get(appointment.slot_id)
        if slot is None or appointment.doctor_id not in data.doctors:
            raise ValueError(f"Appointment {appointment_id} references an unknown record")
        if slot.doctor_id != appointment.doctor_id:
            raise ValueError(f"Appointment {appointment_id} doctor does not match its slot")
        if appointment.created_at.tzinfo is None or appointment.created_at.utcoffset() is None:
            raise ValueError(f"Appointment {appointment_id} must have a timezone-aware creation time")
        if not appointment.caller_phone.strip():
            raise ValueError(f"Appointment {appointment_id} must have a caller phone number")

        if appointment.status == AppointmentStatus.BOOKED:
            if appointment.cancelled_at is not None:
                raise ValueError(f"Booked appointment {appointment_id} cannot have cancelledAt")
            if appointment.slot_id in active_by_slot:
                raise ValueError(f"Slot {appointment.slot_id} has multiple active appointments")
            active_by_slot[appointment.slot_id] = appointment_id
        elif appointment.cancelled_at is None:
            raise ValueError(f"Cancelled appointment {appointment_id} must have cancelledAt")
        elif appointment.cancelled_at.tzinfo is None or appointment.cancelled_at.utcoffset() is None:
            raise ValueError(f"Appointment {appointment_id} cancellation time must include a UTC offset")

    for slot_id, slot in data.slots.items():
        has_active_appointment = slot_id in active_by_slot
        if (slot.status == SlotStatus.BOOKED) != has_active_appointment:
            raise ValueError(f"Slot {slot_id} status does not match its active appointment")


def clinic_data_to_dict(data: ClinicData) -> dict[str, Any]:
    validate_clinic_data(data)
    return {
        "specialties": [
            {"id": item.id, "name": item.name}
            for item in sorted(data.specialties.values(), key=lambda value: value.id)
        ],
        "doctors": [
            {
                "id": item.id,
                "name": item.name,
                "specialtyIds": list(item.specialty_ids),
            }
            for item in sorted(data.doctors.values(), key=lambda value: value.id)
        ],
        "slots": [
            {
                "id": item.id,
                "doctorId": item.doctor_id,
                "startsAt": item.starts_at.isoformat(),
                "status": item.status.value,
            }
            for item in sorted(data.slots.values(), key=lambda value: value.id)
        ],
        "appointments": [
            {
                "id": item.id,
                "slotId": item.slot_id,
                "doctorId": item.doctor_id,
                "callerPhone": item.caller_phone,
                "status": item.status.value,
                "createdAt": item.created_at.isoformat(),
                "cancelledAt": (
                    item.cancelled_at.isoformat() if item.cancelled_at is not None else None
                ),
            }
            for item in sorted(data.appointments.values(), key=lambda value: value.id)
        ],
    }


class JsonClinicRepository:
    """Loads a mutable state file, falling back to tracked seed data on first use."""

    def __init__(self, state_path: Path, seed_path: Path) -> None:
        self._state_path = Path(state_path)
        self._seed_path = Path(seed_path)

    def load(self) -> ClinicData:
        source_path = self._state_path if self._state_path.exists() else self._seed_path
        try:
            with source_path.open("r", encoding="utf-8") as source:
                raw_data = json.load(source)
        except json.JSONDecodeError as exc:
            raise RepositoryError(
                f"Invalid JSON in {source_path} at line {exc.lineno}, column {exc.colno}"
            ) from exc
        except OSError as exc:
            raise RepositoryError(f"Could not read clinic data from {source_path}") from exc

        try:
            return clinic_data_from_dict(raw_data)
        except (TypeError, ValueError) as exc:
            raise RepositoryError(f"Invalid clinic data in {source_path}: {exc}") from exc

    def save(self, data: ClinicData) -> None:
        try:
            serialized = json.dumps(clinic_data_to_dict(data), indent=2, ensure_ascii=False) + "\n"
        except (TypeError, ValueError) as exc:
            raise RepositoryError("Clinic data could not be serialized") from exc

        temporary_path: Path | None = None
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._state_path.parent,
                prefix=f".{self._state_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(serialized)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self._state_path)
        except OSError as exc:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
            raise RepositoryError(f"Could not persist clinic data to {self._state_path}") from exc
