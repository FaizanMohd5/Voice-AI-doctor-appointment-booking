import type {
  Appointment,
  AvailableSlot,
  ClinicSnapshot,
  Doctor,
  Specialty,
} from "./types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(isString);
}

function isSpecialty(value: unknown): value is Specialty {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.name)
  );
}

function isDoctor(value: unknown): value is Doctor {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.name) &&
    isStringArray(value.specialties)
  );
}

function isAvailableSlot(value: unknown): value is AvailableSlot {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.doctorId) &&
    isString(value.doctorName) &&
    isStringArray(value.specialties) &&
    isString(value.startsAt)
  );
}

function isAppointment(value: unknown): value is Appointment {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.doctorId) &&
    isString(value.doctorName) &&
    isString(value.slotId) &&
    isString(value.startsAt) &&
    (value.status === "booked" || value.status === "cancelled") &&
    isString(value.createdAt)
  );
}

function isClinicSnapshot(value: unknown): value is ClinicSnapshot {
  return (
    isRecord(value) &&
    isString(value.timezone) &&
    Array.isArray(value.specialties) &&
    value.specialties.every(isSpecialty) &&
    Array.isArray(value.doctors) &&
    value.doctors.every(isDoctor) &&
    Array.isArray(value.availableSlots) &&
    value.availableSlots.every(isAvailableSlot) &&
    Array.isArray(value.appointments) &&
    value.appointments.every(isAppointment)
  );
}

export async function fetchClinicSnapshot(
  signal?: AbortSignal,
): Promise<ClinicSnapshot> {
  const response = await fetch("/api/clinic", { signal });
  if (!response.ok) {
    throw new Error(`Clinic data request failed (${response.status}).`);
  }

  const result: unknown = await response.json();
  if (!isClinicSnapshot(result)) {
    throw new Error("Clinic data response has an unexpected shape.");
  }
  return result;
}
