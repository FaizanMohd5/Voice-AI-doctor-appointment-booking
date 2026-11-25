from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SlotStatus(str, Enum):
    AVAILABLE = "available"
    BOOKED = "booked"


class AppointmentStatus(str, Enum):
    BOOKED = "booked"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Specialty:
    id: str
    name: str


@dataclass(frozen=True)
class Doctor:
    id: str
    name: str
    specialty_ids: tuple[str, ...]


@dataclass(frozen=True)
class Slot:
    id: str
    doctor_id: str
    starts_at: datetime
    status: SlotStatus


@dataclass(frozen=True)
class Appointment:
    id: str
    slot_id: str
    doctor_id: str
    caller_phone: str
    status: AppointmentStatus
    created_at: datetime
    cancelled_at: datetime | None = None


@dataclass
class ClinicData:
    specialties: dict[str, Specialty] = field(default_factory=dict)
    doctors: dict[str, Doctor] = field(default_factory=dict)
    slots: dict[str, Slot] = field(default_factory=dict)
    appointments: dict[str, Appointment] = field(default_factory=dict)
