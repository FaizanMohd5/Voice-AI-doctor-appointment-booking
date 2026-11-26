import type { CalendarEvent, ClinicSnapshot } from "./types";

export function clinicDateKey(value: string, timezone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: timezone,
  }).formatToParts(new Date(value));
  const part = (type: string) => parts.find((item) => item.type === type)?.value;
  const year = part("year");
  const month = part("month");
  const day = part("day");
  if (!year || !month || !day) {
    throw new Error("Could not format the appointment date.");
  }
  return `${year}-${month}-${day}`;
}

function dateKeyToUtcDate(dateKey: string): Date {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateKey);
  if (!match) {
    throw new Error(`Invalid calendar date: ${dateKey}`);
  }
  const [, year, month, day] = match;
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day), 12));
  if (
    date.getUTCFullYear() !== Number(year) ||
    date.getUTCMonth() !== Number(month) - 1 ||
    date.getUTCDate() !== Number(day)
  ) {
    throw new Error(`Invalid calendar date: ${dateKey}`);
  }
  return date;
}

export function monthKey(dateKey: string): string {
  dateKeyToUtcDate(dateKey);
  return dateKey.slice(0, 7);
}

export function shiftDateKey(dateKey: string, days: number): string {
  const date = dateKeyToUtcDate(dateKey);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function shiftDateKeyByMonths(dateKey: string, months: number): string {
  const date = dateKeyToUtcDate(dateKey);
  const day = date.getUTCDate();
  const targetMonth = new Date(
    Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + months, 1, 12),
  );
  const lastDay = new Date(
    Date.UTC(
      targetMonth.getUTCFullYear(),
      targetMonth.getUTCMonth() + 1,
      0,
      12,
    ),
  ).getUTCDate();
  targetMonth.setUTCDate(Math.min(day, lastDay));
  return targetMonth.toISOString().slice(0, 10);
}

export function monthGridDateKeys(month: string): string[] {
  const firstDate = dateKeyToUtcDate(`${month}-01`);
  const mondayOffset = (firstDate.getUTCDay() + 6) % 7;
  const gridStart = shiftDateKey(`${month}-01`, -mondayOffset);
  return Array.from({ length: 42 }, (_, index) =>
    shiftDateKey(gridStart, index),
  );
}

export function calendarEventsFromSnapshot(
  snapshot: ClinicSnapshot,
): CalendarEvent[] {
  const specialtiesByDoctor = new Map(
    snapshot.doctors.map((doctor) => [doctor.id, doctor.specialties]),
  );
  const events: CalendarEvent[] = [
    ...snapshot.availableSlots.map((slot) => ({
      id: slot.id,
      kind: "available" as const,
      status: "available" as const,
      doctorId: slot.doctorId,
      doctorName: slot.doctorName,
      specialties: slot.specialties,
      startsAt: slot.startsAt,
      dateKey: clinicDateKey(slot.startsAt, snapshot.timezone),
    })),
    ...snapshot.appointments.map((appointment) => ({
      id: appointment.id,
      kind: "appointment" as const,
      status: appointment.status,
      doctorId: appointment.doctorId,
      doctorName: appointment.doctorName,
      specialties: specialtiesByDoctor.get(appointment.doctorId) ?? [],
      startsAt: appointment.startsAt,
      dateKey: clinicDateKey(appointment.startsAt, snapshot.timezone),
    })),
  ];
  return events.sort(
    (first, second) =>
      Date.parse(first.startsAt) - Date.parse(second.startsAt) ||
      first.id.localeCompare(second.id),
  );
}

export function initialCalendarDate(
  events: CalendarEvent[],
  timezone: string,
  now = new Date(),
): string {
  const nowTimestamp = now.getTime();
  const nearestUpcoming = events
    .filter(
      (event) =>
        event.status !== "cancelled" &&
        Date.parse(event.startsAt) >= nowTimestamp,
    )
    .sort(
      (first, second) =>
        Date.parse(first.startsAt) - Date.parse(second.startsAt),
    )[0];
  return nearestUpcoming?.dateKey ?? clinicDateKey(now.toISOString(), timezone);
}

export function formatDateKey(
  dateKey: string,
  options: Intl.DateTimeFormatOptions,
): string {
  return new Intl.DateTimeFormat("en-IN", {
    ...options,
    timeZone: "UTC",
  }).format(dateKeyToUtcDate(dateKey));
}

export function formatMonthKey(month: string): string {
  return formatDateKey(`${month}-01`, { month: "long", year: "numeric" });
}
