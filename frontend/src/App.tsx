import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import type { PipecatClient } from "@pipecat-ai/client-js";

import { fetchClinicSnapshot } from "./api";
import {
  calendarEventsFromSnapshot,
  clinicDateKey,
  formatDateKey,
  formatMonthKey,
  initialCalendarDate,
  monthGridDateKeys,
  monthKey,
  shiftDateKey,
  shiftDateKeyByMonths,
} from "./calendar";
import type {
  CalendarEvent,
  ClinicSnapshot,
  TranscriptMessage,
} from "./types";

type CallStatus = "idle" | "connecting" | "connected" | "ended" | "error";
type IconName = "calendar" | "microphone" | "refresh" | "voice" | "end";

const iconShapes: Record<IconName, ReactNode> = {
  calendar: (
    <>
      <rect x="3.5" y="5" width="17" height="16" rx="2.5" />
      <path d="M7.5 3.5v3M16.5 3.5v3M4 9.5h16M8 13h3m-3 4h3m3-4h3" />
    </>
  ),
  microphone: (
    <>
      <rect x="9" y="3" width="6" height="12" rx="3" />
      <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3m-4 0h8" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 7v5h-5M4 17v-5h5" />
      <path d="M5.5 9a7 7 0 0 1 11.6-2.6L20 12M4 12l2.9 5.6A7 7 0 0 0 18.5 15" />
    </>
  ),
  voice: (
    <>
      <path d="M4 13v-2m4 6V7m4 12V5m4 13V6m4 7v-2" />
    </>
  ),
  end: <rect x="6" y="6" width="12" height="12" rx="2" />,
};

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {iconShapes[name]}
    </svg>
  );
}

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

function formatTime(value: string, timezone: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: timezone,
  }).format(new Date(value));
}

function formatTranscriptTime(timestamp: number): string {
  return new Intl.DateTimeFormat("en-IN", {
    hour: "numeric",
    minute: "2-digit",
  }).format(timestamp);
}

function eventStatusLabel(event: CalendarEvent): string {
  if (event.status === "available") return "Open time";
  return event.status === "booked" ? "Booked" : "Cancelled";
}

function eventCountLabel(count: number): string {
  return `${count} ${count === 1 ? "entry" : "entries"}`;
}

function eventSummary(event: CalendarEvent, timezone: string): string {
  return `${formatTime(event.startsAt, timezone)} ${eventStatusLabel(event)} with ${event.doctorName}`;
}

function App() {
  const [callStatus, setCallStatus] = useState<CallStatus>("idle");
  const [callError, setCallError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<TranscriptMessage[]>([]);
  const [clinic, setClinic] = useState<ClinicSnapshot | null>(null);
  const [clinicError, setClinicError] = useState<string | null>(null);
  const [loadingClinic, setLoadingClinic] = useState(true);
  const [refreshingClinic, setRefreshingClinic] = useState(false);
  const [selectedSpecialty, setSelectedSpecialty] = useState("all");
  const [visibleMonth, setVisibleMonth] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [voiceDrawerOpen, setVoiceDrawerOpen] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const clientRef = useRef<PipecatClient | null>(null);
  const voiceTriggerRef = useRef<HTMLButtonElement>(null);
  const voiceCloseRef = useRef<HTMLButtonElement>(null);
  const voiceDrawerRef = useRef<HTMLElement>(null);
  const wasVoiceDrawerOpenRef = useRef(false);
  const calendarButtonsRef = useRef(new Map<string, HTMLButtonElement>());

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
            setCallError(
              "Browser audio playback was blocked. Allow sound and retry.",
            );
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

  useEffect(() => {
    if (voiceDrawerOpen) {
      voiceCloseRef.current?.focus();
    } else if (wasVoiceDrawerOpenRef.current) {
      voiceTriggerRef.current?.focus();
    }
    wasVoiceDrawerOpenRef.current = voiceDrawerOpen;
  }, [voiceDrawerOpen]);

  useEffect(() => {
    if (!voiceDrawerOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [voiceDrawerOpen]);

  useEffect(() => {
    if (!voiceDrawerOpen) return;
    transcriptEndRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [transcript, voiceDrawerOpen]);

  const refreshClinic = useCallback(async () => {
    setRefreshingClinic(true);
    try {
      const snapshot = await fetchClinicSnapshot();
      setClinic(snapshot);
      setClinicError(null);
    } catch (error) {
      setClinicError(describeError(error));
    } finally {
      setLoadingClinic(false);
      setRefreshingClinic(false);
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

  const calendarEvents = useMemo(
    () => (clinic ? calendarEventsFromSnapshot(clinic) : []),
    [clinic],
  );

  useEffect(() => {
    if (!clinic || selectedDate) return;
    const initialDate = initialCalendarDate(calendarEvents, clinic.timezone);
    setSelectedDate(initialDate);
    setVisibleMonth(monthKey(initialDate));
  }, [calendarEvents, clinic, selectedDate]);

  const filteredEvents = useMemo(
    () =>
      selectedSpecialty === "all"
        ? calendarEvents
        : calendarEvents.filter((event) =>
            event.specialties.includes(selectedSpecialty),
          ),
    [calendarEvents, selectedSpecialty],
  );

  const eventsByDate = useMemo(() => {
    const grouped = new Map<string, CalendarEvent[]>();
    for (const event of filteredEvents) {
      const dayEvents = grouped.get(event.dateKey) ?? [];
      dayEvents.push(event);
      grouped.set(event.dateKey, dayEvents);
    }
    return grouped;
  }, [filteredEvents]);

  const clinicToday = clinic
    ? clinicDateKey(new Date().toISOString(), clinic.timezone)
    : null;
  const activeMonth =
    visibleMonth ??
    (selectedDate
      ? monthKey(selectedDate)
      : clinicToday
        ? monthKey(clinicToday)
        : null);
  const dateKeys = activeMonth ? monthGridDateKeys(activeMonth) : [];
  const monthEvents = activeMonth
    ? filteredEvents.filter((event) => monthKey(event.dateKey) === activeMonth)
    : [];
  const selectedEvents = selectedDate
    ? eventsByDate.get(selectedDate) ?? []
    : [];

  const statusText: Record<CallStatus, string> = {
    idle: "Ready to connect",
    connecting: "Connecting",
    connected: "On a call",
    ended: "Call ended",
    error: "Connection issue",
  };

  const callHeadline: Record<CallStatus, string> = {
    idle: "A more human way to book care.",
    connecting: "Making a connection.",
    connected: "We’re here with you.",
    ended: "Whenever you need us.",
    error: "Let’s get you reconnected.",
  };

  const callDescription: Record<CallStatus, string> = {
    idle: "Talk through availability, appointments, or your next visit with our clinic assistant.",
    connecting: "Please allow microphone access while we prepare your voice session.",
    connected:
      "Speak naturally. Your assistant can help with availability and appointment changes.",
    ended:
      "Your conversation has ended. You can start another call whenever you’re ready.",
    error:
      "The voice session could not be completed. Check your connection and try again.",
  };

  const selectCalendarDate = (dateKey: string) => {
    setSelectedDate(dateKey);
    setVisibleMonth(monthKey(dateKey));
  };

  const navigateMonth = (offset: number) => {
    if (!activeMonth) return;
    const dateToShift = selectedDate ?? `${activeMonth}-01`;
    selectCalendarDate(shiftDateKeyByMonths(dateToShift, offset));
  };

  const goToToday = () => {
    if (!clinic) return;
    selectCalendarDate(clinicDateKey(new Date().toISOString(), clinic.timezone));
  };

  const handleCalendarKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    dateKey: string,
  ) => {
    let nextDate: string | null = null;
    switch (event.key) {
      case "ArrowLeft":
        nextDate = shiftDateKey(dateKey, -1);
        break;
      case "ArrowRight":
        nextDate = shiftDateKey(dateKey, 1);
        break;
      case "ArrowUp":
        nextDate = shiftDateKey(dateKey, -7);
        break;
      case "ArrowDown":
        nextDate = shiftDateKey(dateKey, 7);
        break;
      case "Home": {
        const weekday = new Date(`${dateKey}T12:00:00Z`).getUTCDay();
        nextDate = shiftDateKey(dateKey, -((weekday + 6) % 7));
        break;
      }
      case "End": {
        const weekday = new Date(`${dateKey}T12:00:00Z`).getUTCDay();
        nextDate = shiftDateKey(dateKey, 6 - ((weekday + 6) % 7));
        break;
      }
      case "PageUp":
        nextDate = shiftDateKeyByMonths(dateKey, -1);
        break;
      case "PageDown":
        nextDate = shiftDateKeyByMonths(dateKey, 1);
        break;
      default:
        return;
    }
    event.preventDefault();
    selectCalendarDate(nextDate);
    window.requestAnimationFrame(() => {
      calendarButtonsRef.current.get(nextDate)?.focus();
    });
  };

  const startCall = async () => {
    if (callStatus === "connecting" || callStatus === "connected") return;

    setTranscript([]);
    setCallError(null);
    setCallStatus("connecting");
    try {
      const activeClient = clientRef.current ?? (await createVoiceClient());
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

  const startOrReturnToCall = () => {
    setVoiceDrawerOpen(true);
    if (callStatus === "connecting" || callStatus === "connected") return;
    void startCall();
  };

  const closeVoiceDrawer = () => setVoiceDrawerOpen(false);

  const handleVoiceDrawerKeyDown = (
    event: KeyboardEvent<HTMLElement>,
  ) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeVoiceDrawer();
      return;
    }
    if (event.key !== "Tab") return;

    const focusable = voiceDrawerRef.current?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), select:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])',
    );
    if (!focusable?.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const monthCounts = {
    available: monthEvents.filter((event) => event.status === "available").length,
    booked: monthEvents.filter((event) => event.status === "booked").length,
    cancelled: monthEvents.filter((event) => event.status === "cancelled").length,
  };
  const primaryCallLabel: Record<CallStatus, string> = {
    idle: "Start a call",
    connecting: "Call connecting…",
    connected: "Return to your call",
    ended: "Start another call",
    error: "Try the call again",
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#calendar"
          aria-label="Careline Clinic schedule"
        >
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" fill="none">
              <path d="M13.2 6.5h5.6v6.7h6.7v5.6h-6.7v6.7h-5.6v-6.7H6.5v-5.6h6.7V6.5Z" />
            </svg>
          </span>
          <span className="brand-copy">
            <strong>Careline</strong>
            <small>CLINIC OPERATIONS</small>
          </span>
        </a>

        <p className="sidebar-label">YOUR WORKSPACE</p>
        <nav className="workspace-nav" aria-label="Workspace navigation">
          <a className="nav-link is-current" href="#calendar" aria-current="page">
            <Icon name="calendar" />
            <span>Clinic calendar</span>
          </a>
          <a className="nav-link" href="#agenda">
            <Icon name="voice" />
            <span>Selected day</span>
          </a>
          <button
            className="nav-link nav-link--button"
            type="button"
            onClick={() => setVoiceDrawerOpen(true)}
          >
            <Icon name="microphone" />
            <span>Voice assistant</span>
            {callStatus === "connected" && (
              <span className="nav-live-dot" aria-label="Call in progress" />
            )}
          </button>
        </nav>

        <div className="sidebar-spacer" />
        <div className="sidebar-note">
          <span className="sidebar-note-mark" aria-hidden="true">
            +
          </span>
          <p className="sidebar-note-kicker">CARE, MADE CLEARER</p>
          <p>One calm view of the clinic day, from open time to confirmed visit.</p>
        </div>
        <div className="sidebar-footer">
          <span
            className={`data-status-dot ${clinicError ? "is-error" : clinic ? "is-ready" : "is-loading"}`}
            aria-hidden="true"
          />
          <span>
            {clinicError
              ? "Clinic data needs attention"
              : clinic
                ? "Clinic records connected"
                : "Connecting to clinic data"}
          </span>
        </div>
      </aside>

      <div className="main-area">
        <header className="topbar">
          <div className="breadcrumb">
            <span>CARELINE CLINIC</span>
            <span className="breadcrumb-divider">/</span>
            <span>SCHEDULE</span>
          </div>
          <div className="topbar-actions">
            <div className={`status-pill status-pill--${callStatus}`} aria-live="polite">
              <span className={`status-dot ${callStatus}`} />
              {statusText[callStatus]}
            </div>
            <button
              className="refresh-button"
              type="button"
              onClick={() => void refreshClinic()}
              disabled={refreshingClinic}
              aria-label={
                refreshingClinic ? "Refreshing clinic data" : "Refresh clinic data"
              }
              title="Refresh clinic data"
            >
              <Icon name="refresh" size={17} />
              <span>{refreshingClinic ? "Syncing" : "Refresh"}</span>
            </button>
            <button
              className="voice-trigger"
              type="button"
              onClick={() => setVoiceDrawerOpen(true)}
              ref={voiceTriggerRef}
              aria-label={
                callStatus === "connected"
                  ? "Open your active call"
                  : "Open voice assistant controls"
              }
              aria-haspopup="dialog"
              aria-expanded={voiceDrawerOpen}
            >
              <Icon name="microphone" size={17} />
              <span>{callStatus === "connected" ? "On a call" : "Voice assistant"}</span>
              {callStatus === "connected" && <span className="voice-trigger-live" />}
            </button>
          </div>
        </header>

        <main className="dashboard" id="calendar">
          <section className="workspace-intro">
            <div className="workspace-intro-copy">
              <p className="eyebrow">THE CLINIC, IN RHYTHM</p>
              <h1>
                A clearer view of <em>care.</em>
              </h1>
              <p className="intro-copy">
                Browse the calendar for open times and appointments, or start a call
                for help with availability, booking, or cancellation.
              </p>
            </div>
            <div className="workspace-intro-actions">
              <button
                className={`primary-call-cta primary-call-cta--${callStatus}`}
                type="button"
                onClick={startOrReturnToCall}
                aria-label={primaryCallLabel[callStatus]}
                aria-busy={callStatus === "connecting"}
              >
                <span className="primary-call-icon">
                  <Icon name="microphone" size={19} />
                </span>
                <span className="primary-call-copy">
                  <strong>{primaryCallLabel[callStatus]}</strong>
                  <small>Availability · booking · cancellations</small>
                </span>
                <span className="primary-call-arrow" aria-hidden="true">
                  →
                </span>
              </button>
              <div className="clinic-time">
                <span>CLINIC TIME</span>
                <strong>{clinic?.timezone ?? "Syncing schedule"}</strong>
              </div>
            </div>
          </section>

          {clinicError && (
            <div className="data-alert" role="alert">
              <span className="data-alert-mark">!</span>
              <div>
                <strong>
                  {clinic
                    ? "The latest clinic update could not be loaded."
                    : "Clinic information is unavailable."}
                </strong>
                <p>{clinicError}</p>
              </div>
              <button type="button" onClick={() => void refreshClinic()}>
                Try again
              </button>
            </div>
          )}

          <section className="calendar-workspace" aria-label="Clinic calendar">
            <div className="calendar-toolbar">
              <div className="month-navigation" aria-label="Calendar month controls">
                <div className="month-switcher">
                  <button
                    className="month-arrow"
                    type="button"
                    onClick={() => navigateMonth(-1)}
                    disabled={!activeMonth}
                    aria-label="Previous month"
                  >
                    <span aria-hidden="true">‹</span>
                  </button>
                  <h2 aria-live="polite">
                    {activeMonth ? formatMonthKey(activeMonth) : "Clinic calendar"}
                  </h2>
                  <button
                    className="month-arrow"
                    type="button"
                    onClick={() => navigateMonth(1)}
                    disabled={!activeMonth}
                    aria-label="Next month"
                  >
                    <span aria-hidden="true">›</span>
                  </button>
                </div>
                <button
                  className="today-button"
                  type="button"
                  onClick={goToToday}
                  disabled={!clinic}
                >
                  Today
                </button>
              </div>

              <label className="specialty-filter">
                <span>View specialty</span>
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

            <div className="calendar-legend" aria-label="Calendar event legend">
              <span className="legend-intro">
                {activeMonth ? `${monthEvents.length} entries` : "Schedule"}
              </span>
              <span className="legend-item legend-item--available">
                <span className="legend-dot" />
                <span>Open</span>
                <strong>{monthCounts.available}</strong>
              </span>
              <span className="legend-item legend-item--booked">
                <span className="legend-dot" />
                <span>Booked</span>
                <strong>{monthCounts.booked}</strong>
              </span>
              <span className="legend-item legend-item--cancelled">
                <span className="legend-dot" />
                <span>Cancelled</span>
                <strong>{monthCounts.cancelled}</strong>
              </span>
            </div>

            {loadingClinic && !clinic ? (
              <div className="calendar-loading" aria-label="Loading clinic schedule" aria-busy="true">
                <div className="calendar-loading-grid">
                  {Array.from({ length: 42 }, (_, index) => (
                    <span className="calendar-loading-cell" key={index} />
                  ))}
                </div>
                <div className="calendar-loading-agenda">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            ) : !clinic ? (
              <div className="calendar-unavailable">
                <span className="empty-calendar" aria-hidden="true">
                  <Icon name="calendar" size={23} />
                </span>
                <h3>The schedule could not load.</h3>
                <p>Reconnect to clinic records to see availability and appointments.</p>
                <button type="button" onClick={() => void refreshClinic()}>
                  Try again
                </button>
              </div>
            ) : (
              <div className="schedule-layout">
                <section className="month-panel" aria-label={formatMonthKey(activeMonth ?? "")}>
                  {monthEvents.length === 0 && (
                    <p className="month-empty-note">
                      No entries for this month and specialty. The calendar remains
                      available for browsing.
                    </p>
                  )}
                  <div className="calendar-grid" role="grid" aria-label="Month view">
                    <div className="calendar-week calendar-week--head" role="row">
                      {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map(
                        (weekday) => (
                          <div
                            className="weekday-heading"
                            role="columnheader"
                            key={weekday}
                          >
                            {weekday}
                          </div>
                        ),
                      )}
                    </div>
                    {Array.from({ length: 6 }, (_, weekIndex) => (
                      <div className="calendar-week" role="row" key={weekIndex}>
                        {dateKeys
                          .slice(weekIndex * 7, weekIndex * 7 + 7)
                          .map((dateKey) => {
                            const dayEvents = eventsByDate.get(dateKey) ?? [];
                            const isCurrentMonth = monthKey(dateKey) === activeMonth;
                            const isSelected = selectedDate === dateKey;
                            const isToday = clinicToday === dateKey;
                            const dateLabel = formatDateKey(dateKey, {
                              weekday: "long",
                              month: "long",
                              day: "numeric",
                              year: "numeric",
                            });
                            const spokenSummary = dayEvents
                              .map((event) => eventSummary(event, clinic.timezone))
                              .join("; ");
                            const visibleEvents = dayEvents.slice(0, 2);
                            const accessibleCount = eventCountLabel(dayEvents.length);

                            return (
                              <div
                                className="calendar-cell"
                                role="gridcell"
                                aria-selected={isSelected}
                                key={dateKey}
                              >
                                <button
                                  className={[
                                    "calendar-day",
                                    isCurrentMonth ? "" : "is-outside-month",
                                    isSelected ? "is-selected" : "",
                                    isToday ? "is-today" : "",
                                  ]
                                    .filter(Boolean)
                                    .join(" ")}
                                  type="button"
                                  data-date={dateKey}
                                  ref={(element) => {
                                    if (element) {
                                      calendarButtonsRef.current.set(dateKey, element);
                                    } else {
                                      calendarButtonsRef.current.delete(dateKey);
                                    }
                                  }}
                                  tabIndex={isSelected ? 0 : -1}
                                  aria-label={`${dateLabel}${dayEvents.length ? `, ${accessibleCount}: ${spokenSummary}` : ", no entries"}${isToday ? ", today" : ""}`}
                                  aria-pressed={isSelected}
                                  aria-current={isToday ? "date" : undefined}
                                  onClick={() => selectCalendarDate(dateKey)}
                                  onKeyDown={(event) =>
                                    handleCalendarKeyDown(event, dateKey)
                                  }
                                >
                                  <span className="calendar-day-number">
                                    <span>{formatDateKey(dateKey, { day: "numeric" })}</span>
                                    {isToday && <small>Today</small>}
                                  </span>
                                  <span className="calendar-event-list" aria-hidden="true">
                                    {visibleEvents.map((calendarEvent) => (
                                      <span
                                        className={`calendar-event calendar-event--${calendarEvent.status}`}
                                        key={`${calendarEvent.kind}:${calendarEvent.id}`}
                                      >
                                        <span className="event-time">
                                          {formatTime(calendarEvent.startsAt, clinic.timezone)}
                                        </span>
                                        <span className="event-doctor">
                                          {calendarEvent.doctorName}
                                        </span>
                                      </span>
                                    ))}
                                    {dayEvents.length > visibleEvents.length && (
                                      <span className="more-events">
                                        +{dayEvents.length - visibleEvents.length} more
                                      </span>
                                    )}
                                  </span>
                                </button>
                              </div>
                            );
                          })}
                      </div>
                    ))}
                  </div>
                </section>

                <aside className="agenda-panel" id="agenda" aria-labelledby="agenda-title">
                  <div className="agenda-heading">
                    <p className="eyebrow">DAY AT A GLANCE</p>
                    <h2 id="agenda-title">
                      {selectedDate
                        ? formatDateKey(selectedDate, {
                            weekday: "long",
                            month: "long",
                            day: "numeric",
                          })
                        : "Choose a day"}
                    </h2>
                    <p>
                      {selectedEvents.length
                        ? eventCountLabel(selectedEvents.length)
                        : "The clinic, hour by hour"}
                    </p>
                  </div>
                  <div className="agenda-events" aria-live="polite">
                    {selectedEvents.length ? (
                      selectedEvents.map((event) => (
                        <article
                          className={`agenda-event agenda-event--${event.status}`}
                          key={`${event.kind}:${event.id}`}
                        >
                          <time dateTime={event.startsAt}>
                            {formatTime(event.startsAt, clinic.timezone)}
                          </time>
                          <span className="agenda-event-rule" aria-hidden="true" />
                          <div className="agenda-event-copy">
                            <strong>{event.doctorName}</strong>
                            <span>
                              {event.specialties.length
                                ? event.specialties.join(" · ")
                                : "Clinic visit"}
                            </span>
                          </div>
                          <span className={`event-status event-status--${event.status}`}>
                            <span />
                            {eventStatusLabel(event)}
                          </span>
                        </article>
                      ))
                    ) : (
                      <div className="agenda-empty">
                        <span className="agenda-empty-mark" aria-hidden="true">
                          <Icon name="calendar" size={20} />
                        </span>
                        <strong>No entries on this day.</strong>
                        <p>
                          {selectedSpecialty === "all"
                            ? "Choose another date to explore the clinic schedule."
                            : `No ${selectedSpecialty.toLowerCase()} entries here. Try another date or specialty.`}
                        </p>
                      </div>
                    )}
                  </div>
                  <p className="agenda-note">
                    Booking and cancellation are handled by the voice assistant.
                  </p>
                </aside>
              </div>
            )}
          </section>

          <footer className="dashboard-footer">
            <span>CARELINE CLINIC</span>
            <span>
              {clinic
                ? `Schedule shown in ${clinic.timezone}.`
                : "Clinic schedule"}
            </span>
            <span>Read-only schedule · Caller numbers stay private</span>
          </footer>
        </main>
      </div>

      {voiceDrawerOpen && (
        <div className="drawer-layer">
          <button
            className="drawer-scrim"
            type="button"
            aria-label="Close voice assistant"
            onClick={closeVoiceDrawer}
          />
          <section
            className="voice-drawer"
            role="dialog"
            aria-modal="true"
            aria-labelledby="voice-drawer-title"
            ref={voiceDrawerRef}
            onKeyDown={handleVoiceDrawerKeyDown}
          >
            <header className="drawer-header">
              <div className="drawer-heading">
                <span className="drawer-icon" aria-hidden="true">
                  <Icon name="voice" size={18} />
                </span>
                <div>
                  <p className="eyebrow">CARELINE VOICE</p>
                  <h2 id="voice-drawer-title">Talk it through.</h2>
                </div>
              </div>
              <div className="drawer-header-actions">
                <span className={`status-pill status-pill--${callStatus}`} aria-live="polite">
                  <span className={`status-dot ${callStatus}`} />
                  {statusText[callStatus]}
                </span>
                <button
                  className="drawer-close"
                  type="button"
                  onClick={closeVoiceDrawer}
                  ref={voiceCloseRef}
                  aria-label="Close voice assistant"
                >
                  ×
                </button>
              </div>
            </header>

            <div className={`voice-drawer-content voice-drawer-content--${callStatus}`}>
              <div className="voice-intro">
                <div>
                  <p className="voice-kicker">
                    <span className={`status-dot ${callStatus}`} />
                    {callStatus === "connected"
                      ? "HERE WITH YOU"
                      : callStatus === "connecting"
                        ? "PREPARING YOUR CALL"
                        : "YOUR CLINIC, IN CONVERSATION"}
                  </p>
                  <h3>{callHeadline[callStatus]}</h3>
                  <p>{callDescription[callStatus]}</p>
                </div>
                <div className="voice-orb" aria-hidden="true">
                  <span className="voice-orb-ring voice-orb-ring--outer" />
                  <span className="voice-orb-ring voice-orb-ring--inner" />
                  <span className="voice-orb-core">
                    <Icon name="microphone" size={26} />
                  </span>
                  <span className={`voice-wave ${callStatus === "connected" ? "is-active" : ""}`}>
                    {Array.from({ length: 9 }, (_, index) => (
                      <span key={index} />
                    ))}
                  </span>
                </div>
              </div>

              <div className="call-actions">
                {callStatus === "connected" ? (
                  <button
                    className="call-button call-button--end"
                    type="button"
                    onClick={() => void endCall()}
                  >
                    <Icon name="end" size={16} />
                    End voice call
                  </button>
                ) : (
                  <button
                    className="call-button"
                    type="button"
                    onClick={() => void startCall()}
                    disabled={callStatus === "connecting"}
                    aria-busy={callStatus === "connecting"}
                  >
                    {callStatus === "connecting" ? (
                      <span className="button-spinner" aria-hidden="true" />
                    ) : callStatus === "error" ? (
                      <Icon name="refresh" size={17} />
                    ) : (
                      <Icon name="microphone" size={17} />
                    )}
                    {callStatus === "connecting"
                      ? "Connecting…"
                      : callStatus === "ended"
                        ? "Start another call"
                        : callStatus === "error"
                          ? "Try again"
                          : "Start a voice call"}
                  </button>
                )}
                <span className="call-microphone-note">
                  <Icon name="microphone" size={14} />
                  Microphone access required
                </span>
              </div>

              {callError && (
                <div className="call-error" role="alert">
                  <span className="call-error-mark">!</span>
                  <span>{callError}</span>
                </div>
              )}

              <section className="transcript-panel" aria-label="Call transcript">
                <div className="transcript-heading">
                  <div>
                    <p className="eyebrow">YOUR CONVERSATION</p>
                    <h3>Call notes</h3>
                  </div>
                  <span
                    className={`transcript-state ${callStatus === "connected" ? "is-live" : ""}`}
                    aria-live="polite"
                  >
                    <span />
                    {callStatus === "connected"
                      ? "Live"
                      : callStatus === "connecting"
                        ? "Connecting"
                        : "This call only"}
                  </span>
                </div>
                <div
                  className="transcript-list"
                  aria-live="polite"
                  aria-relevant="additions"
                  aria-busy={callStatus === "connecting"}
                >
                  {transcript.length === 0 ? (
                    <div className="transcript-empty">
                      <div className="transcript-empty-art" aria-hidden="true">
                        <span />
                        <span />
                        <span />
                        <span />
                        <span />
                      </div>
                      <div>
                        <strong>
                          {callStatus === "connected"
                            ? "You’re connected."
                            : callStatus === "connecting"
                              ? "Getting the conversation ready…"
                              : "A little help is one call away."}
                        </strong>
                        <p>
                          {callStatus === "connected"
                            ? "Start by telling us what you need."
                            : "Start a call and your conversation will appear here."}
                        </p>
                      </div>
                    </div>
                  ) : (
                    transcript.map((message) => (
                      <article
                        className={`transcript-message transcript-message--${message.role}`}
                        key={message.id}
                      >
                        <div className="message-meta">
                          <span className="message-role">
                            {message.role === "caller" ? "You" : "Careline assistant"}
                          </span>
                          <time>{formatTranscriptTime(message.timestamp)}</time>
                        </div>
                        <p>{message.text}</p>
                      </article>
                    ))
                  )}
                  <div ref={transcriptEndRef} />
                </div>
              </section>
              <p className="drawer-privacy-note">
                This schedule is read-only. Changes are confirmed through the voice
                conversation.
              </p>
            </div>
          </section>
        </div>
      )}
      <audio ref={audioRef} autoPlay />
    </div>
  );
}

export default App;
