import re
from dataclasses import dataclass
from datetime import date
from threading import RLock
from typing import Any

from backend.app.appointment_service import (
    ActionConfirmation,
    AppointmentAction,
    AppointmentError,
    AppointmentNotFoundError,
    AppointmentService,
    ConfirmationMismatchError,
    ConfirmationRequiredError,
    DoctorNotFoundError,
    InvalidPhoneNumberError,
    SlotNotFoundError,
    SlotUnavailableError,
    SpecialtyNotFoundError,
)
from backend.app.json_store import RepositoryError
from backend.app.models import Appointment, Doctor, Slot, Specialty


TOOL_DECLARATIONS: tuple[dict[str, Any], ...] = (
    {
        "name": "check_doctor_availability",
        "description": "Find available appointment slots. Only offer returned slots.",
        "parameters": {
            "type": "object",
            "properties": {
                "doctor_id": {"type": "string", "description": "Doctor ID, if known."},
                "specialty_id": {
                    "type": "string",
                    "description": "Specialty ID, if the caller requested one.",
                },
                "on_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Requested clinic date in YYYY-MM-DD format.",
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "book_appointment",
        "description": (
            "Book an available slot for the phone number the caller spoke. "
            "The application requires a separate caller confirmation before booking."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "slot_id": {"type": "string", "description": "ID of a returned available slot."},
                "phone_number": {
                    "type": "string",
                    "description": "Phone number spoken by the caller.",
                },
            },
            "required": ["slot_id", "phone_number"],
            "additionalProperties": False,
        },
    },
    {
        "name": "cancel_appointment",
        "description": (
            "Cancel an active appointment belonging to the phone number the caller spoke. "
            "If several appointments match, ask the caller to select one. "
            "The application requires a separate caller confirmation before cancellation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone_number": {
                    "type": "string",
                    "description": "Phone number spoken by the caller.",
                },
                "appointment_id": {
                    "type": "string",
                    "description": (
                        "Selected appointment ID. Omit only to find appointments for the number."
                    ),
                },
            },
            "required": ["phone_number"],
            "additionalProperties": False,
        },
    },
)


@dataclass(frozen=True)
class _ConfirmationIntent:
    action: AppointmentAction
    target_id: str
    phone_number: str
    target_readback: str


class CallConfirmationState:
    """One-call, one-use confirmation state kept outside model-controlled arguments."""

    _AFFIRMATIVE_TURNS = {
        "yes",
        "yes please",
        "yeah",
        "yeah please",
        "yep",
        "yep please",
        "correct",
        "thats correct",
        "that is correct",
        "i confirm",
        "i do confirm",
        "go ahead",
        "please do",
        "sure",
        "okay",
        "ok",
        "proceed",
    }

    def __init__(self) -> None:
        self._pending: _ConfirmationIntent | None = None
        self._confirmed: _ConfirmationIntent | None = None
        self._prompt_presented = False
        self._lock = RLock()

    def observe_caller_turn(self, transcript: str) -> bool:
        """Confirm only a clear affirmative turn after a tool requested confirmation."""
        with self._lock:
            if self._pending is None:
                self._clear()
                return False
            if not self._prompt_presented:
                return False

            normalized_turn = " ".join(
                re.sub(r"[^a-z0-9\s]", "", transcript.casefold()).split()
            )
            if normalized_turn not in self._AFFIRMATIVE_TURNS:
                self._clear()
                return False

            self._confirmed = self._pending
            self._pending = None
            self._prompt_presented = False
            return True

    def mark_confirmation_prompt_presented(self, spoken_text: str) -> bool:
        """Mark a prompt delivered only when it reads back the phone, target, and asks."""
        with self._lock:
            if self._pending is None:
                return False
            expected_phone = self._pending.phone_number
            phone_match = next(
                (
                    match
                    for match in re.finditer(
                        r"(?<!\w)\+?\d(?:[\d\s().-]*\d)?(?!\w)",
                        spoken_text,
                    )
                    if self._matches_phone(match.group(), expected_phone)
                ),
                None,
            )
            target_phrase = self._normalize_words(self._pending.target_readback)
            if target_phrase.startswith("dr "):
                target_phrase = target_phrase[3:]
            target_pattern = r"(?<!\w)" + r"[\W_]+".join(
                re.escape(word) for word in target_phrase.split()
            ) + r"(?!\w)"
            target_match = re.search(target_pattern, spoken_text, re.IGNORECASE)
            if (
                phone_match is None
                or not target_phrase
                or target_match is None
                or spoken_text.find("?", max(phone_match.end(), target_match.end())) < 0
            ):
                return False
            self._prompt_presented = True
            return True

    def invalidate(self) -> None:
        with self._lock:
            self._clear()

    def authorize_or_request(
        self,
        action: AppointmentAction,
        target_id: str,
        phone_number: str,
        target_readback: str,
    ) -> ActionConfirmation | None:
        normalized_phone = AppointmentService.normalize_phone_number(phone_number)
        intent = _ConfirmationIntent(action, target_id, normalized_phone, target_readback)
        with self._lock:
            if self._confirmed == intent:
                self._clear()
                return ActionConfirmation(action, target_id, normalized_phone)

            self._clear()
            self._pending = intent
            return None

    @staticmethod
    def _normalize_words(value: str) -> str:
        return " ".join(re.sub(r"[^a-z0-9\s]", " ", value.casefold()).split())

    @staticmethod
    def _matches_phone(candidate: str, expected_phone: str) -> bool:
        try:
            return AppointmentService.normalize_phone_number(candidate) == expected_phone
        except InvalidPhoneNumberError:
            return False

    def _clear(self) -> None:
        self._pending = None
        self._confirmed = None
        self._prompt_presented = False


class AppointmentToolAdapter:
    """Provider-neutral tool handlers for a single caller session."""

    _ARGUMENTS = {
        "check_doctor_availability": (
            frozenset({"doctor_id", "specialty_id", "on_date"}),
            frozenset(),
        ),
        "book_appointment": (
            frozenset({"slot_id", "phone_number"}),
            frozenset({"slot_id", "phone_number"}),
        ),
        "cancel_appointment": (
            frozenset({"phone_number", "appointment_id"}),
            frozenset({"phone_number"}),
        ),
    }

    def __init__(
        self,
        service: AppointmentService,
        confirmation_state: CallConfirmationState,
    ) -> None:
        self._service = service
        self._confirmation_state = confirmation_state

    def observe_caller_turn(self, transcript: str) -> bool:
        """Forward a caller turn into the gate before invoking the next model turn."""
        return self._confirmation_state.observe_caller_turn(transcript)

    def mark_confirmation_prompt_presented(self, spoken_text: str) -> bool:
        """Call with delivered assistant text after the read-back and confirmation question."""
        return self._confirmation_state.mark_confirmation_prompt_presented(spoken_text)

    def end_call(self) -> None:
        self._confirmation_state.invalidate()

    def execute(self, name: str, arguments: Any) -> dict[str, Any]:
        if not isinstance(name, str) or name not in self._ARGUMENTS:
            self._confirmation_state.invalidate()
            return self._error("unknown_tool", "That action is not available.")
        if not isinstance(arguments, dict):
            self._confirmation_state.invalidate()
            return self._error("invalid_arguments", "The action arguments were invalid.")

        allowed, required = self._ARGUMENTS[name]
        supplied = frozenset(arguments)
        if not required.issubset(supplied) or not supplied.issubset(allowed):
            self._confirmation_state.invalidate()
            return self._error("invalid_arguments", "The action arguments were invalid.")
        if any(not isinstance(value, str) for value in arguments.values()):
            self._confirmation_state.invalidate()
            return self._error("invalid_arguments", "The action arguments were invalid.")

        try:
            if name == "check_doctor_availability":
                self._confirmation_state.invalidate()
                return self._check_availability(arguments)
            if name == "book_appointment":
                return self._book_appointment(arguments)
            return self._cancel_appointment(arguments)
        except InvalidPhoneNumberError:
            self._confirmation_state.invalidate()
            return self._error(
                "invalid_phone_number",
                "Please ask the caller to repeat their phone number.",
            )
        except DoctorNotFoundError:
            return self._error("doctor_not_found", "That doctor could not be found.")
        except SpecialtyNotFoundError:
            return self._error("specialty_not_found", "That specialty could not be found.")
        except SlotNotFoundError:
            return self._error("slot_not_found", "That appointment slot could not be found.")
        except SlotUnavailableError:
            self._confirmation_state.invalidate()
            return self._error(
                "slot_unavailable",
                "That slot is no longer available. Please check availability again.",
            )
        except AppointmentNotFoundError:
            self._confirmation_state.invalidate()
            return self._error(
                "appointment_not_found",
                "No active appointment matching that number and selection was found.",
            )
        except (ConfirmationRequiredError, ConfirmationMismatchError):
            self._confirmation_state.invalidate()
            return self._error(
                "confirmation_required",
                "The caller must confirm this exact action before it can proceed.",
            )
        except RepositoryError:
            self._confirmation_state.invalidate()
            return self._error(
                "appointment_data_unavailable",
                "Appointment data is temporarily unavailable. Do not report the action as complete.",
            )
        except AppointmentError:
            self._confirmation_state.invalidate()
            return self._error(
                "appointment_action_failed",
                "The appointment action could not be completed.",
            )

    def _check_availability(self, arguments: dict[str, str]) -> dict[str, Any]:
        on_date = None
        if "on_date" in arguments:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", arguments["on_date"]) is None:
                return self._error(
                    "invalid_date",
                    "The requested date must use YYYY-MM-DD format.",
                )
            try:
                on_date = date.fromisoformat(arguments["on_date"])
            except ValueError:
                return self._error(
                    "invalid_date",
                    "The requested date must use YYYY-MM-DD format.",
                )

        slots = self._service.find_available_slots(
            doctor_id=arguments.get("doctor_id"),
            specialty_id=arguments.get("specialty_id"),
            on_date=on_date,
        )
        doctors = {doctor.id: doctor for doctor in self._service.list_doctors()}
        specialties = {
            specialty.id: specialty for specialty in self._service.list_specialties()
        }
        return {
            "ok": True,
            "tool": "check_doctor_availability",
            "slots": [
                self._slot_result(slot, doctors[slot.doctor_id], specialties)
                for slot in slots
            ],
        }

    def _book_appointment(self, arguments: dict[str, str]) -> dict[str, Any]:
        slot_id = arguments["slot_id"]
        phone_number = arguments["phone_number"]
        AppointmentService.normalize_phone_number(phone_number)
        available_slots = self._service.find_available_slots()
        slot = next((item for item in available_slots if item.id == slot_id), None)
        if slot is None:
            self._confirmation_state.invalidate()
            return self._error(
                "slot_unavailable",
                "That slot is no longer available. Please check availability again.",
            )

        doctors = {doctor.id: doctor for doctor in self._service.list_doctors()}
        specialties = {
            specialty.id: specialty for specialty in self._service.list_specialties()
        }
        confirmation = self._confirmation_state.authorize_or_request(
            AppointmentAction.BOOK,
            slot_id,
            phone_number,
            doctors[slot.doctor_id].name,
        )
        if confirmation is None:
            return {
                "ok": False,
                "tool": "book_appointment",
                "code": "confirmation_required",
                "message": (
                    "Read the phone number and appointment details back to the caller, "
                    "then ask for a clear yes or no. Do not claim the appointment is booked."
                ),
                "confirmation": {
                    "phone_number": AppointmentService.normalize_phone_number(phone_number),
                    "slot": self._slot_result(slot, doctors[slot.doctor_id], specialties),
                },
            }

        appointment = self._service.book_appointment(
            slot_id,
            phone_number,
            confirmation,
        )
        return {
            "ok": True,
            "tool": "book_appointment",
            "appointment": self._appointment_result(
                appointment,
                doctors[appointment.doctor_id],
                slot,
            ),
        }

    def _cancel_appointment(self, arguments: dict[str, str]) -> dict[str, Any]:
        phone_number = arguments["phone_number"]
        appointments = self._service.find_active_appointments_for_phone(phone_number)
        if not appointments:
            self._confirmation_state.invalidate()
            return self._error(
                "appointment_not_found",
                "No active appointment was found for that phone number.",
            )

        appointment_id = arguments.get("appointment_id")
        if appointment_id is None:
            if len(appointments) > 1:
                self._confirmation_state.invalidate()
                doctors = {doctor.id: doctor for doctor in self._service.list_doctors()}
                all_slots = {
                    slot.id: slot
                    for slot in self._all_slots_for_appointments(appointments)
                }
                return {
                    "ok": False,
                    "tool": "cancel_appointment",
                    "code": "appointment_selection_required",
                    "message": "Ask the caller which appointment they want to cancel.",
                    "appointments": [
                        self._appointment_summary(
                            appointment,
                            doctors[appointment.doctor_id],
                            all_slots[appointment.slot_id],
                        )
                        for appointment in appointments
                    ],
                }
            appointment = appointments[0]
        else:
            appointment = next(
                (item for item in appointments if item.id == appointment_id),
                None,
            )
            if appointment is None:
                self._confirmation_state.invalidate()
                return self._error(
                    "appointment_not_found",
                    "No active appointment matching that number and selection was found.",
                )

        all_slots = {slot.id: slot for slot in self._all_slots_for_appointments([appointment])}
        slot = all_slots[appointment.slot_id]
        doctors = {doctor.id: doctor for doctor in self._service.list_doctors()}
        confirmation = self._confirmation_state.authorize_or_request(
            AppointmentAction.CANCEL,
            appointment.id,
            phone_number,
            doctors[appointment.doctor_id].name,
        )
        if confirmation is None:
            return {
                "ok": False,
                "tool": "cancel_appointment",
                "code": "confirmation_required",
                "message": (
                    "Read the phone number and selected appointment details back to the caller, "
                    "then ask for a clear yes or no. Do not claim it is cancelled."
                ),
                "confirmation": {
                    "phone_number": AppointmentService.normalize_phone_number(phone_number),
                    "appointment": self._appointment_summary(
                        appointment,
                        doctors[appointment.doctor_id],
                        slot,
                    ),
                },
            }

        cancelled = self._service.cancel_appointment(
            appointment.id,
            phone_number,
            confirmation,
        )
        return {
            "ok": True,
            "tool": "cancel_appointment",
            "appointment": self._appointment_result(
                cancelled,
                doctors[cancelled.doctor_id],
                slot,
            ),
        }

    def _all_slots_for_appointments(self, appointments: list[Appointment]) -> list[Slot]:
        return [self._service.get_slot(appointment.slot_id) for appointment in appointments]

    @staticmethod
    def _slot_result(
        slot: Slot,
        doctor: Doctor,
        specialties: dict[str, Specialty],
    ) -> dict[str, Any]:
        return {
            "id": slot.id,
            "doctor_id": doctor.id,
            "doctor_name": doctor.name,
            "specialties": [
                specialties[specialty_id].name for specialty_id in doctor.specialty_ids
            ],
            "starts_at": slot.starts_at.isoformat(),
        }

    @staticmethod
    def _appointment_summary(
        appointment: Appointment,
        doctor: Doctor,
        slot: Slot,
    ) -> dict[str, Any]:
        return {
            "id": appointment.id,
            "doctor_name": doctor.name,
            "starts_at": slot.starts_at.isoformat(),
        }

    @classmethod
    def _appointment_result(
        cls,
        appointment: Appointment,
        doctor: Doctor,
        slot: Slot,
    ) -> dict[str, Any]:
        return {
            **cls._appointment_summary(appointment, doctor, slot),
            "status": appointment.status.value,
        }

    @staticmethod
    def _error(code: str, message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "code": code,
            "message": message,
        }
