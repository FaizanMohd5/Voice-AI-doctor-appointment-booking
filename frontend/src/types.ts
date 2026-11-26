export interface Specialty {
  id: string;
  name: string;
}

export interface Doctor {
  id: string;
  name: string;
  specialties: string[];
}

export interface AvailableSlot {
  id: string;
  doctorId: string;
  doctorName: string;
  specialties: string[];
  startsAt: string;
}

export interface Appointment {
  id: string;
  doctorId: string;
  doctorName: string;
  slotId: string;
  startsAt: string;
  status: "booked" | "cancelled";
  createdAt: string;
}

interface CalendarEventBase {
  id: string;
  doctorId: string;
  doctorName: string;
  specialties: string[];
  startsAt: string;
  dateKey: string;
}

export type CalendarEvent =
  | (CalendarEventBase & {
      kind: "available";
      status: "available";
    })
  | (CalendarEventBase & {
      kind: "appointment";
      status: "booked" | "cancelled";
    });

export interface ClinicSnapshot {
  timezone: string;
  specialties: Specialty[];
  doctors: Doctor[];
  availableSlots: AvailableSlot[];
  appointments: Appointment[];
}

export interface TranscriptMessage {
  id: string;
  role: "caller" | "assistant";
  text: string;
  timestamp: number;
}
