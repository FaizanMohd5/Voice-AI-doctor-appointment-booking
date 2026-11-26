from datetime import tzinfo
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.json_store import ClinicRepository, RepositoryError
from backend.app.models import SlotStatus


def build_dashboard_snapshot(
    repository: ClinicRepository,
    clinic_timezone: tzinfo,
) -> dict[str, Any]:
    data = repository.load()
    specialties = {
        specialty_id: specialty.name
        for specialty_id, specialty in data.specialties.items()
    }
    doctors = {
        doctor_id: doctor
        for doctor_id, doctor in data.doctors.items()
    }

    return {
        "timezone": str(clinic_timezone),
        "specialties": [
            {"id": specialty.id, "name": specialty.name}
            for specialty in sorted(data.specialties.values(), key=lambda item: item.name.casefold())
        ],
        "doctors": [
            {
                "id": doctor.id,
                "name": doctor.name,
                "specialties": [
                    specialties[specialty_id] for specialty_id in doctor.specialty_ids
                ],
            }
            for doctor in sorted(data.doctors.values(), key=lambda item: item.name.casefold())
        ],
        "availableSlots": [
            {
                "id": slot.id,
                "doctorId": slot.doctor_id,
                "doctorName": doctors[slot.doctor_id].name,
                "specialties": [
                    specialties[specialty_id]
                    for specialty_id in doctors[slot.doctor_id].specialty_ids
                ],
                "startsAt": slot.starts_at.astimezone(clinic_timezone).isoformat(),
            }
            for slot in sorted(data.slots.values(), key=lambda item: (item.starts_at, item.id))
            if slot.status == SlotStatus.AVAILABLE
        ],
        "appointments": [
            {
                "id": appointment.id,
                "doctorId": appointment.doctor_id,
                "doctorName": doctors[appointment.doctor_id].name,
                "slotId": appointment.slot_id,
                "startsAt": data.slots[appointment.slot_id]
                .starts_at.astimezone(clinic_timezone)
                .isoformat(),
                "status": appointment.status.value,
                "createdAt": appointment.created_at.isoformat(),
            }
            for appointment in sorted(
                data.appointments.values(),
                key=lambda item: (item.created_at, item.id),
                reverse=True,
            )
        ],
    }


def create_dashboard_router(
    repository: ClinicRepository,
    clinic_timezone: tzinfo,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/clinic")
    def get_clinic_dashboard() -> dict[str, Any]:
        try:
            return build_dashboard_snapshot(repository, clinic_timezone)
        except RepositoryError as exc:
            raise HTTPException(
                status_code=503,
                detail="Clinic data is temporarily unavailable.",
            ) from exc

    return router
