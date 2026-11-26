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
