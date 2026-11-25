from dataclasses import dataclass, replace
from datetime import date, datetime, timezone, tzinfo
from enum import Enum
from threading import RLock
from uuid import uuid4

from backend.app.json_store import ClinicRepository
from backend.app.models import (
    Appointment,
    AppointmentStatus,
    Doctor,
    Slot,
    SlotStatus,
    Specialty,
)


class AppointmentError(Exception):
    """Base class for expected appointment-domain failures."""


class InvalidPhoneNumberError(AppointmentError):
    pass


class ConfirmationRequiredError(AppointmentError):
    pass


class ConfirmationMismatchError(AppointmentError):
    pass


class DoctorNotFoundError(AppointmentError):
    pass


class SpecialtyNotFoundError(AppointmentError):
    pass


class SlotNotFoundError(AppointmentError):
    pass


class SlotUnavailableError(AppointmentError):
    pass


class AppointmentNotFoundError(AppointmentError):
    pass


class AppointmentAction(str, Enum):
    BOOK = "book"
    CANCEL = "cancel"


@dataclass(frozen=True)
class ActionConfirmation:
    """Trusted application evidence that one caller confirmed one target action."""

    action: AppointmentAction
    target_id: str
    phone_number: str


class AppointmentService:
    def __init__(
        self,
        repository: ClinicRepository,
        clinic_timezone: tzinfo,
    ) -> None:
        self._repository = repository
        self._clinic_timezone = clinic_timezone
        self._lock = RLock()

    def list_specialties(self) -> tuple[Specialty, ...]:
        with self._lock:
            data = self._repository.load()
            return tuple(sorted(data.specialties.values(), key=lambda item: item.name.casefold()))

    def list_doctors(self) -> tuple[Doctor, ...]:
        with self._lock:
            data = self._repository.load()
            return tuple(sorted(data.doctors.values(), key=lambda item: item.name.casefold()))

    def find_available_slots(
        self,
        doctor_id: str | None = None,
        specialty_id: str | None = None,
        on_date: date | None = None,
    ) -> tuple[Slot, ...]:
        with self._lock:
            data = self._repository.load()
            if doctor_id is not None and doctor_id not in data.doctors:
                raise DoctorNotFoundError(f"Doctor {doctor_id} was not found")
            if specialty_id is not None and specialty_id not in data.specialties:
                raise SpecialtyNotFoundError(f"Specialty {specialty_id} was not found")

            available = []
            for slot in data.slots.values():
                if slot.status != SlotStatus.AVAILABLE:
                    continue
                doctor = data.doctors[slot.doctor_id]
                if doctor_id is not None and doctor.id != doctor_id:
                    continue
                if specialty_id is not None and specialty_id not in doctor.specialty_ids:
                    continue
                if (
                    on_date is not None
                    and slot.starts_at.astimezone(self._clinic_timezone).date() != on_date
                ):
                    continue
                available.append(slot)
            return tuple(sorted(available, key=lambda item: (item.starts_at, item.id)))

    def list_appointments(self) -> tuple[Appointment, ...]:
        with self._lock:
            data = self._repository.load()
            return tuple(
                sorted(
                    data.appointments.values(),
                    key=lambda item: (item.created_at, item.id),
                    reverse=True,
                )
            )

    def find_active_appointments_for_phone(
        self, phone_number: str
    ) -> tuple[Appointment, ...]:
        normalized_phone = self._normalize_phone(phone_number)
        with self._lock:
            data = self._repository.load()
            matches = [
                appointment
                for appointment in data.appointments.values()
                if appointment.status == AppointmentStatus.BOOKED
                and appointment.caller_phone == normalized_phone
            ]
            return tuple(
                sorted(matches, key=lambda item: (item.created_at, item.id), reverse=True)
            )

    def book_appointment(
        self,
        slot_id: str,
        phone_number: str,
        confirmation: ActionConfirmation | None,
    ) -> Appointment:
        normalized_phone = self._normalize_phone(phone_number)
        with self._lock:
            data = self._repository.load()
            slot = data.slots.get(slot_id)
            if slot is None:
                raise SlotNotFoundError(f"Slot {slot_id} was not found")
            self._require_confirmation(
                confirmation, AppointmentAction.BOOK, slot_id, normalized_phone
            )
            if slot.status != SlotStatus.AVAILABLE:
                raise SlotUnavailableError(f"Slot {slot_id} is no longer available")

            appointment = Appointment(
                id=uuid4().hex,
                slot_id=slot.id,
                doctor_id=slot.doctor_id,
                caller_phone=normalized_phone,
                status=AppointmentStatus.BOOKED,
                created_at=datetime.now(timezone.utc),
            )
            data.slots[slot.id] = replace(slot, status=SlotStatus.BOOKED)
            data.appointments[appointment.id] = appointment
            self._repository.save(data)
            return appointment

    def cancel_appointment(
        self,
        appointment_id: str,
        phone_number: str,
        confirmation: ActionConfirmation | None,
    ) -> Appointment:
        normalized_phone = self._normalize_phone(phone_number)
        with self._lock:
            data = self._repository.load()
            self._require_confirmation(
                confirmation,
                AppointmentAction.CANCEL,
                appointment_id,
                normalized_phone,
            )
            appointment = data.appointments.get(appointment_id)
            if (
                appointment is None
                or appointment.status != AppointmentStatus.BOOKED
                or appointment.caller_phone != normalized_phone
            ):
                raise AppointmentNotFoundError(
                    "No active appointment matching that number and selection was found"
                )

            cancelled_at = datetime.now(timezone.utc)
            cancelled = replace(
                appointment,
                status=AppointmentStatus.CANCELLED,
                cancelled_at=cancelled_at,
            )
            data.appointments[appointment.id] = cancelled
            slot = data.slots[appointment.slot_id]
            data.slots[slot.id] = replace(slot, status=SlotStatus.AVAILABLE)
            self._repository.save(data)
            return cancelled

    @staticmethod
    def _normalize_phone(phone_number: str) -> str:
        allowed_characters = set("0123456789+ -().")
        candidate = phone_number.strip()
        if (
            not candidate
            or any(character not in allowed_characters for character in candidate)
            or candidate.count("+") > 1
            or ("+" in candidate and not candidate.startswith("+"))
        ):
            raise InvalidPhoneNumberError("Enter a phone number using digits and common separators")

        digits = "".join(character for character in candidate if character.isdigit())
        if not 7 <= len(digits) <= 15:
            raise InvalidPhoneNumberError("Phone number must contain between 7 and 15 digits")
        prefix = "+" if candidate.startswith("+") else ""
        return prefix + digits

    @classmethod
    def _require_confirmation(
        cls,
        confirmation: ActionConfirmation | None,
        action: AppointmentAction,
        target_id: str,
        normalized_phone: str,
    ) -> None:
        if confirmation is None:
            raise ConfirmationRequiredError("Caller confirmation is required")
        try:
            confirmation_phone = cls._normalize_phone(confirmation.phone_number)
        except InvalidPhoneNumberError as exc:
            raise ConfirmationMismatchError(
                "Confirmation does not match the requested action"
            ) from exc
        if (
            confirmation.action != action
            or confirmation.target_id != target_id
            or confirmation_phone != normalized_phone
        ):
            raise ConfirmationMismatchError(
                "Confirmation does not match the requested action"
            )
