import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { PipecatClient } from "@pipecat-ai/client-js";

import { fetchClinicSnapshot } from "./api";
import type {
  AvailableSlot,
  ClinicSnapshot,
  TranscriptMessage,
} from "./types";

type CallStatus = "idle" | "connecting" | "connected" | "ended" | "error";

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : "An unexpected error occurred.";
}

function describeRtviError(data: unknown): string {
  if (
    typeof data === "object" &&
    data !== null &&
    "error" in data &&
    typeof data.error === "string"
  ) {
    return data.error;
  }
  return "The voice session reported an error.";
}

function initials(name: string): string {
  return name
    .replace(/^Dr\.\s*/i, "")
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0] ?? "")
    .join("")
    .toUpperCase();
}

function formatDateTime(value: string, timezone: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: timezone,
  }).format(new Date(value));
}

function App() {
  const [callStatus, setCallStatus] = useState<CallStatus>("idle");
  const [callError, setCallError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptMessage[]>([]);
  const [clinic, setClinic] = useState<ClinicSnapshot | null>(null);
  const [clinicError, setClinicError] = useState<string | null>(null);
  const [loadingClinic, setLoadingClinic] = useState(true);
  const [selectedSpecialty, setSelectedSpecialty] = useState("all");
  const audioRef = useRef<HTMLAudioElement>(null);
  const clientRef = useRef<PipecatClient | null>(null);

  const addTranscript = useCallback(
    (role: TranscriptMessage["role"], text: string) => {
      const cleanText = text.trim();
      if (!cleanText) return;
      setTranscript((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role,
          text: cleanText,
          timestamp: Date.now(),
        },
      ]);
    },
    [],
  );

  const createVoiceClient = useCallback(async () => {
    const [{ PipecatClient: Client }, { SmallWebRTCTransport }] =
      await Promise.all([
        import("@pipecat-ai/client-js"),
        import("@pipecat-ai/small-webrtc-transport"),
      ]);

    const voiceClient = new Client({
      transport: new SmallWebRTCTransport(),
      enableMic: true,
      enableCam: false,
      callbacks: {
        onConnected: () => {
          setCallError(null);
          setCallStatus("connected");
        },
        onDisconnected: () => {
          setCallStatus((current) =>
            current === "connecting" ? "idle" : "ended",
          );
        },
        onError: (message) => {
          setCallError(describeRtviError(message.data));
        },
        onUserTranscript: (data) => {
          if (data.final) addTranscript("caller", data.text);
        },
        onBotTranscript: (data) => {
          addTranscript("assistant", data.text);
        },
        onTrackStarted: (track, participant) => {
          if (participant?.local || track.kind !== "audio") return;
          const audio = audioRef.current;
          if (!audio) return;
          audio.srcObject = new MediaStream([track]);
          void audio.play().catch(() => {
            setCallError("Browser audio playback was blocked. Allow sound and retry.");
          });
        },
        onTrackStopped: (track) => {
          const audio = audioRef.current;
          if (!audio) return;
          const stream = audio.srcObject;
          if (!(stream instanceof MediaStream)) return;
          stream.removeTrack(track);
          if (stream.getTracks().length === 0) audio.srcObject = null;
        },
      },
    });
    clientRef.current = voiceClient;
    return voiceClient;
  }, [addTranscript]);

  useEffect(
    () => () => {
      const activeClient = clientRef.current;
      clientRef.current = null;
      void activeClient?.disconnect().catch(() => {});
    },
    [],
  );

  const refreshClinic = useCallback(async () => {
    try {
      const snapshot = await fetchClinicSnapshot();
      setClinic(snapshot);
      setClinicError(null);
    } catch (error) {
      setClinicError(describeError(error));
    } finally {
      setLoadingClinic(false);
    }
  }, []);

  useEffect(() => {
    void refreshClinic();
  }, [refreshClinic]);

  useEffect(() => {
    if (callStatus === "ended") void refreshClinic();
    if (callStatus !== "connected") return;

    const timer = window.setInterval(() => {
      void refreshClinic();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [callStatus, refreshClinic]);

  const availableSlots = useMemo(() => {
    if (!clinic) return [];
    if (selectedSpecialty === "all") return clinic.availableSlots;
    return clinic.availableSlots.filter((slot: AvailableSlot) =>
      slot.specialties.includes(selectedSpecialty),
    );
  }, [clinic, selectedSpecialty]);

  const startCall = async () => {
    if (callStatus === "connecting" || callStatus === "connected") {
      return;
    }

    setTranscript([]);
    setCallError(null);
    setCallStatus("connecting");
    try {
      const activeClient =
        clientRef.current ?? (await createVoiceClient());
      await activeClient.startBotAndConnect({
        endpoint: "/start",
        requestData: {
          transport: "webrtc",
          enableDefaultIceServers: true,
        },
      });
      setCallStatus("connected");
    } catch (error) {
      await clientRef.current?.disconnect().catch(() => {});
      setCallError(describeError(error));
      setCallStatus("error");
    }
  };

  const endCall = async () => {
    const activeClient = clientRef.current;
    if (!activeClient) return;
    try {
      await activeClient.disconnect();
      setCallStatus("ended");
    } catch (error) {
      setCallError(`Could not end the voice session: ${describeError(error)}`);
      setCallStatus("error");
    }
  };

  const statusText: Record<CallStatus, string> = {
    idle: "Ready to call",
    connecting: "Connecting",
    connected: "Call in progress",
    ended: "Call ended",
    error: "Connection issue",
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">+</span>
          <span>Careline <span className="brand-light">Clinic</span></span>
        </div>
        <div className="topbar-right">
          <span>Appointment operations</span>
          <div className="status-pill" aria-live="polite">
            <span className={`status-dot ${callStatus}`} />
            {statusText[callStatus]}
          </div>
        </div>
      </header>

      <main className="dashboard">
        <section className="page-intro">
          <div>
            <p className="eyebrow">Clinic workspace</p>
            <h1>Your voice desk</h1>
            <p>Talk naturally to check availability and manage appointments.</p>
          </div>
          <button
            className="refresh-button"
            type="button"
            onClick={() => void refreshClinic()}
            disabled={loadingClinic}
          >
            {loadingClinic ? "Loading…" : "Refresh clinic data"}
          </button>
        </section>

        <div className="main-grid">
          <section className="panel call-panel" aria-label="Voice assistant">
            <div className="call-banner">
              <p className="eyebrow">Pipecat voice assistant</p>
              <h2>How can we help today?</h2>
              <p>
                Start a browser call to ask about doctors, available
                times, or an existing appointment.
              </p>
              <div className="call-actions">
                {callStatus === "connected" ? (
                  <button
                    className="call-button end"
                    type="button"
                    onClick={() => void endCall()}
                  >
                    <span aria-hidden="true">■</span> End call
                  </button>
                ) : (
                  <button
                    className="call-button"
                    type="button"
                    onClick={() => void startCall()}
                    disabled={callStatus === "connecting"}
                  >
                    <span aria-hidden="true">●</span>
                    {callStatus === "connecting" ? "Connecting…" : "Start voice call"}
                  </button>
                )}
              </div>
            </div>
            {callError && (
              <p className="call-error" role="alert">{callError}</p>
            )}
            <div className="transcript">
              <div className="transcript-heading">
                <h3>Live transcript</h3>
                <span className="transcript-label">
                  {callStatus === "connected" ? "Live · current call only" : "Current call only"}
                </span>
              </div>
              <div className="transcript-list" aria-live="polite" aria-relevant="additions">
                {transcript.length === 0 ? (
                  <div className="transcript-empty">
                    Your conversation will appear here when the call starts.
                  </div>
                ) : (
                  transcript.map((message) => (
                    <div
                      className={`transcript-message ${message.role}`}
                      key={message.id}
                    >
                      <span className="message-role">
                        {message.role === "caller" ? "You" : "Assistant"}
                      </span>
                      {message.text}
                    </div>
                  ))
                )}
              </div>
            </div>
          </section>

          <div className="side-column">
            <section className="panel data-panel">
              <div className="section-heading">
                <h2>Care team</h2>
                <span className="count-badge">
                  {clinic ? clinic.doctors.length : 0} doctors
                </span>
              </div>
              {clinicError ? (
                <p className="empty-state" role="alert">{clinicError}</p>
              ) : clinic?.doctors.length ? (
                <div className="doctor-list">
                  {clinic.doctors.map((doctor) => (
                    <article className="doctor-card" key={doctor.id}>
                      <div className="doctor-heading">
                        <span className="doctor-avatar">{initials(doctor.name)}</span>
                        <div>
                          <p className="doctor-name">{doctor.name}</p>
                          <p className="doctor-specialty">
                            {doctor.specialties.join(" · ")}
                          </p>
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <p className="empty-state">
                  {loadingClinic ? "Loading care team…" : "No doctors are available."}
                </p>
              )}
            </section>

            <section className="panel data-panel">
              <div className="section-heading">
                <h2>Available times</h2>
                <div className="filter-row">
                  <span className="count-badge">{availableSlots.length} open</span>
                  <label>
                    <span className="visually-hidden">Filter by specialty</span>
                    <select
                      value={selectedSpecialty}
                      onChange={(event) => setSelectedSpecialty(event.target.value)}
                      disabled={!clinic}
                    >
                      <option value="all">All specialties</option>
                      {clinic?.specialties.map((specialty) => (
                        <option key={specialty.id} value={specialty.name}>
                          {specialty.name}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>
              {clinicError ? (
                <p className="empty-state" role="alert">{clinicError}</p>
              ) : availableSlots.length ? (
                <div className="slot-list">
                  {availableSlots.map((slot) => (
                    <div className="slot-row" key={slot.id}>
                      <div className="slot-info">
                        <p className="slot-doctor">{slot.doctorName}</p>
                        <p className="slot-date">
                          {formatDateTime(slot.startsAt, clinic?.timezone ?? "UTC")}
                        </p>
                      </div>
                      <span className="availability-tag">Available</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="empty-state">
                  {loadingClinic ? "Loading appointment times…" : "No matching times are open."}
                </p>
              )}
            </section>

            <section className="panel data-panel">
              <div className="section-heading">
                <h2>Appointments</h2>
                <span className="count-badge">
                  {clinic?.appointments.length ?? 0} total
                </span>
              </div>
              {clinicError ? (
                <p className="empty-state" role="alert">{clinicError}</p>
              ) : clinic?.appointments.length ? (
                <div className="appointment-list">
                  {clinic.appointments.map((appointment) => (
                    <div className="appointment-row" key={appointment.id}>
                      <div className="appointment-info">
                        <p className="appointment-doctor">{appointment.doctorName}</p>
                        <p className="appointment-date">
                          {formatDateTime(appointment.startsAt, clinic.timezone)}
                        </p>
                      </div>
                      <span className={`appointment-status ${appointment.status}`}>
                        {appointment.status}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="empty-state">
                  {loadingClinic ? "Loading appointments…" : "No appointments yet."}
                </p>
              )}
            </section>
          </div>
        </div>

        <p className="footer-note">
          Appointments update from the clinic service. Caller phone numbers are not shown here.
        </p>
      </main>

      <audio ref={audioRef} autoPlay />
    </div>
  );
}

export default App;
