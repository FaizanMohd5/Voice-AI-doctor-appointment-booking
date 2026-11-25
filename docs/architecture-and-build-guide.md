# Architecture and Build Guide

This guide describes how to build the assignment from the system boundary down to its core components. The first implementation milestone is the working Pipecat voice pipeline and its appointment tools. Build the dashboard afterward as a thin client of the same capabilities; React is a reasonable choice, but it is not a prerequisite for proving the core workflow.

## 1. Scope and decisions

### Required

- A real-time voice agent built with Pipecat (Python).
- Speech-to-text (STT) and text-to-speech (TTS) using ElevenLabs.
- Gemini is the selected LLM for the planned voice pipeline.
- Tools to check doctor availability, book an appointment, and cancel an appointment.
- Caller identity based only on the phone number the caller says aloud. Read the number back and get confirmation before booking or cancelling.
- A dashboard that can start/end a browser call, show a live transcript, list doctors and slots, and reflect appointment changes.

Doctors, specialties, slots, and appointments may start as mock data in memory, JSON, or SQLite. The implemented first slice uses JSON-backed local data behind a small repository boundary, so the prototype stays simple and persistence can be replaced later.

### Not a first milestone

The assignment's bonus items (VAD, a phone-style call screen, waveform, sounds, animations, richer responsive behavior, and other polish) are optional. Keep integration seams for them, but do not let them delay the required voice workflow.

## 2. System at a glance

The browser is a caller and an observer of the session. Pipecat owns the real-time conversation; appointment tools call domain services, which read and mutate the same data source shown by the dashboard.

```mermaid
flowchart LR
    Caller[Caller in browser]
    UI[Dashboard - later client]
    Transport[Browser-compatible audio transport]
    Session[Pipecat session and pipeline]
    VAD[Optional VAD]
    STT[ElevenLabs STT]
    LLM[LLM and conversation context]
    Tools[Appointment tool adapter]
    Domain[Appointment domain services]
    Repo[Repository boundary]
    JSON[(JSON data)]
    TTS[ElevenLabs TTS]

    Caller <--> UI
    UI <--> Transport
    Transport --> Session
    Session --> VAD
    VAD --> STT
    Session --> STT
    STT --> LLM
    LLM <--> Tools
    Tools --> Domain
    Domain <--> Repo
    Repo <--> JSON
    LLM --> TTS
    TTS --> Session
    Session --> Transport
    Session -. transcript, state, and tool events .-> UI
```

VAD is an optional audio-processing stage, not a second conversation path. When it is disabled, audio proceeds directly to STT. The exact browser transport and Pipecat transport implementation can be selected when the application is scaffolded; keep audio transport concerns out of appointment logic.

## 3. One conversation, end to end

```mermaid
sequenceDiagram
    actor Caller
    participant Browser as Browser transport
    participant Pipe as Pipecat pipeline
    participant STT as ElevenLabs STT
    participant LLM as LLM / conversation context
    participant Tool as Appointment tool
    participant Domain as Domain service
    participant Data as JSON repository
    participant TTS as ElevenLabs TTS

    Caller->>Browser: Speaks a request
    Browser->>Pipe: Audio frames
    Pipe->>STT: Audio
    STT-->>Pipe: Transcript
    Pipe->>LLM: User turn + conversation state
    LLM->>TTS: Ask for missing details or confirmation
    TTS-->>Pipe: Prompt audio
    Pipe->>Browser: Prompt audio
    Browser-->>Caller: Spoken prompt
    Caller->>Browser: Replies
    Browser->>Pipe: Audio frames
    Pipe->>STT: Audio
    STT-->>Pipe: Confirmed transcript
    Pipe->>LLM: Updated user turn
    LLM->>Tool: Structured tool arguments
    Tool->>Domain: Validated operation
    Domain->>Data: Read / check / mutate
    Data-->>Domain: Result
    Domain-->>Tool: Explicit success or recoverable error
    Tool-->>LLM: Structured result
    LLM->>TTS: Natural-language response
    TTS-->>Pipe: Generated speech
    Pipe-->>Browser: Audio + transcript/state events
    Browser-->>Caller: Spoken result and updated dashboard
```

The diagram omits repeated turns for brevity. A tool call may require more than one caller turn: gather details, read back the phone number and requested appointment action, obtain confirmation, then invoke the mutation.

## 4. Build from the core outward

| Order | Component | Responsibility and completion check |
| --- | --- | --- |
| 1 | Appointment data and domain services | Define doctors, specialties, slots, and appointment rules. Test availability, successful booking, duplicate booking prevention, and cancellation without any audio or LLM dependency. |
| 2 | Pipecat session and transport | Start/end one browser voice session and connect its audio input/output to the pipeline. Keep the transport replaceable and report connection state. |
| 3 | STT and TTS adapters | Connect ElevenLabs STT/TTS to the pipeline; verify a caller turn can be transcribed and an agent response can be heard. |
| 4 | Conversation context and LLM | Handle intent, collect missing details, select a doctor/specialty/slot from tool results, and request confirmation before mutations. |
| 5 | Registered appointment tools | Connect the three required tools to domain services. Verify all three end-to-end and ensure failures never sound like success. |
| 6 | Dashboard client | Add call controls, live transcript/status, doctors and slots, and appointments that refresh after tool results. React can be used here without coupling the backend to React. |
| 7 | Optional improvements | Add bonus features through the extension seams below only after the required workflow is reliable. |

Keep the data/domain tests and tool tests runnable without calling paid or network speech/LLM services. Add a small number of full integration checks with provider calls enabled only when credentials and network access are available.

## 5. Pipecat pipeline components

| Component | Input → output | Keep this responsibility here |
| --- | --- | --- |
| Browser transport | Browser microphone audio → pipeline audio frames; pipeline audio/events → browser | Connection lifecycle, audio framing, and transport-level errors. Do not book appointments in transport handlers. |
| Optional VAD | Audio frames → speech/start/stop boundaries or filtered frames | Improve turn detection or reduce unnecessary STT work. It must be possible to disable it without changing business logic. |
| ElevenLabs STT | Caller audio → recognized text | Transcription only. Treat uncertain or empty transcription as something to clarify, not as a reliable phone number or consent. |
| Conversation context | Current turn + bounded session state → LLM input | Track the selected doctor/slot and confirmation state for this call. Do not use prior calls or caller-ID as identity. |
| LLM | Context → response or structured function call | Converse naturally and choose among real tool results. It must not invent doctors, availability, booking IDs, or successful mutations. |
| Tool adapter | Structured arguments → validated result | Define narrow schemas, validate required fields, call a domain service, and return a predictable result to the LLM. |
| Domain service/repository | Operation → authoritative result | Apply availability and appointment rules to the data source. This is the source of truth, not the LLM or the transcript. |
| ElevenLabs TTS | Agent response text → audio | Speak the response. A TTS failure is a call failure/degradation, not evidence that the underlying operation failed or succeeded. |
| Browser event client | Session events → visible status/transcript/data refresh | Render session state and refresh lists from the same authoritative backend data. It must not infer a booking from an LLM sentence alone. |

Use the Pipecat pipeline for streaming and turn orchestration. Keep provider-specific setup behind small adapters/configuration so a provider can later be swapped without rewriting tool or appointment rules.

## 6. Appointment tools and conversation rules

The assignment requires these three tools. Names below match the assignment; argument names are illustrative and should become explicit typed schemas in the implementation.

| Tool | Purpose | Important behavior |
| --- | --- | --- |
| `check_doctor_availability` | Return real available slots, optionally narrowed by doctor, specialty, and date. | If the caller has not given enough information, ask a follow-up. Offer only slots returned by the repository. Return stable slot/doctor IDs alongside readable labels and time-zone-aware timestamps. |
| `book_appointment` | Reserve a selected slot for the spoken phone number. | Before calling it, read the number back and obtain clear confirmation of both the number and selected slot. Recheck availability and reserve atomically; return a booking ID only after the write succeeds. |
| `cancel_appointment` | Cancel an existing appointment associated with the spoken phone number. | Read the number and target appointment back and obtain confirmation. If the number matches multiple appointments and the caller has not selected one, ask which one; do not cancel an arbitrary match. |

### Trust and mutation boundary

The caller's spoken phone number is the only identity source required by the assignment: do not substitute browser identity, caller-ID, login, or OTP. A spoken number is not proof of legal identity; use it only as the assignment's lookup key. Normalize a number carefully while retaining the caller's original form for read-back. Avoid putting full phone numbers in routine logs or dashboard rows.

Make the confirmation gate explicit in session/application state. Do not rely only on an LLM-generated `confirmed: true` argument: the application should record the caller's affirmative response to a specific number and specific booking/cancellation target, and invalidate that confirmation if either changes. Require the confirmation state at the domain/tool boundary before mutation.

Keep tool outputs machine-readable, for example:

```json
{
  "ok": true,
  "operation": "check_doctor_availability",
  "slots": [
    {
      "id": "slot-203",
      "doctorId": "doctor-12",
      "doctorName": "Dr. Example",
      "specialty": "Cardiology",
      "startsAt": "2026-12-01T10:30:00+05:30"
    }
  ]
}
```

Errors should also have a stable shape, such as `ok: false`, a safe `code` (`slot_unavailable`, `not_found`, `confirmation_required`, `temporarily_unavailable`), and a short user-safe message. The LLM can phrase the message naturally, but must preserve its meaning.

## 7. JSON data model

Start with explicit, small records. Store references by stable IDs rather than copying names into every relationship.

```json
{
  "specialties": [
    { "id": "cardiology", "name": "Cardiology" }
  ],
  "doctors": [
    {
      "id": "doctor-12",
      "name": "Dr. Example",
      "specialtyIds": ["cardiology"]
    }
  ],
  "slots": [
    {
      "id": "slot-203",
      "doctorId": "doctor-12",
      "startsAt": "2026-12-01T10:30:00+05:30",
      "status": "available"
    }
  ],
  "appointments": []
}
```

- Store timestamps with an explicit UTC offset or as UTC plus a separately defined display time zone; never interpret an ambiguous local time silently.
- A booking links to a slot and stores only the caller phone number needed by the assignment. A minimal appointment record can include `id`, `slotId`, `doctorId`, `callerPhone`, `status`, and `createdAt`.
- Keep repository operations small, for example `list_doctors`, `find_available_slots`, `book_slot`, and `cancel_appointment`. Tool adapters should not parse or write JSON files directly.
- For a local prototype, load seed records from JSON and serialize mutations through one repository. If writing JSON back to disk, use an atomic replacement and serialize writes; this is a single-process demo strategy, not multi-instance production storage.
- If durability, multiple workers, or concurrent callers become important, replace the repository implementation with SQLite or a service database. Preserve tool and domain contracts.

## 8. Failure handling and fallback paths

Fail explicitly and preserve data correctness. A fallback must never make an unavailable or failed operation look successful.

| Failure | Expected behavior | Extension point |
| --- | --- | --- |
| Browser permission, device, or transport failure | Show a clear connection/microphone state and allow retry or a clean end-call. Do not fabricate a transcript. | Swap or extend the browser transport independently of appointment logic. |
| VAD disabled or unavailable | Continue through the normal STT path if the selected transport supports it. | Add/replace a VAD processor without changing tools. |
| STT timeout, empty result, or provider error | Ask the caller to repeat once when appropriate; otherwise explain that the call cannot continue and end gracefully. Do not guess phone digits. | Configure a compatible secondary STT adapter only if deliberately supported and tested. |
| LLM timeout or malformed tool arguments | Do not execute a mutation. Give a brief recovery message, retry only within a bounded policy, or end the call. | Change LLM provider through the model adapter/configuration. |
| Slot was taken after it was offered | Recheck and reject the stale selection; offer newly available slots. | Repository transaction/locking policy. |
| JSON/data read or write failure | Return a safe tool error, leave the appointment unchanged, and do not announce success. Log diagnostic details without secrets or full phone numbers. | Replace local repository with SQLite/database. |
| TTS failure | Surface the degraded/failed call state in the dashboard if available; do not claim the caller heard a response. Preserve a completed data operation and report its result honestly through any remaining channel. | Alternate TTS adapter or text-visible status channel. |
| Duplicate/retried tool request | Prevent a second booking/cancellation where possible; return the existing operation result or a clear conflict. | Add an idempotency key and durable transaction support when moving beyond the local demo. |

Never silently fall back to hard-coded availability, mock a provider response after a live request fails, or mark a booking complete before the repository confirms it.

## 9. Dashboard boundary (later milestone)

The dashboard should consume session status/transcript events and appointment/doctor data; it should not contain appointment rules or connect directly to the JSON file. Its first required version needs:

- Start and end browser voice calls.
- Show connecting/connected/ended or failed call states.
- Render a live transcript.
- List doctors and their available slots.
- List appointments and refresh/highlight them after a confirmed booking or cancellation.

React is a practical option for this UI, but the backend should expose framework-neutral session and data boundaries. Choose the exact API/event channel when wiring up the selected Pipecat transport; keep audio on a suitable real-time media transport and use a separate event/control channel if the transport requires one.

## 10. Optional bonus extension seams

These are not required for the first working submission. Add them as independent capabilities:

- **VAD:** optional processor before STT; enable/disable through pipeline configuration.
- **Phone-style call screen, timer, mute, waveform, sounds, transitions, mobile layout:** dashboard presentation layered over session state, without changing booking rules.
- **Persistence upgrade:** new repository adapter (SQLite/database) implementing the same domain operations.
- **Provider alternatives:** adapters/configuration for compatible STT, LLM, or TTS providers; preserve the same tool contracts.
- **Observability:** structured session/tool events, provider latency/error metrics, and redacted logs. Do not log API keys, raw audio, or full phone numbers by default.
- **Additional specialties, doctors, appointment policies, or workflows:** add data/configuration and domain operations first; expose new tool capabilities deliberately rather than embedding policy in a prompt.

## 11. Configuration and local setup checklist

When implementing the application, keep credentials outside source control. Add a local environment file from a checked-in `.env.example`, and document the selected provider/model and exact run commands after the repository's backend and frontend tooling have been chosen.

Plan for configuration equivalent to:

- ElevenLabs API credential and selected STT/TTS model IDs.
- Selected LLM provider, model ID, and its credential (Gemini if chosen).
- Pipeline/session host and port.
- JSON seed-data path or repository location.
- Optional VAD enablement.

Validate required configuration at startup and report which setting is missing without printing secret values. Never commit API keys.

## 12. Running the current implementation

The current repository implements the appointment domain/data slice only. It is not yet a running voice agent or browser dashboard. Google Calendar is not required by the assignment: doctor, specialty, and slot data may be mocked in memory, JSON, or SQLite. This prototype uses JSON.

Requirements: Python 3.10 or later; the current domain/data slice uses only the Python standard library.

From the repository root, display the sample specialties, doctors, and available slots:

```powershell
python -m backend.app.main
```

Optional filters:

```powershell
python -m backend.app.main --date 2026-12-01
python -m backend.app.main --doctor doctor-101
python -m backend.app.main --specialty cardiology
```

The sample times use the fixed UTC+05:30 clinic timezone. Date filtering interprets the requested date in that timezone. To restore the original sample after local booking data has been generated, remove only `backend/data/state.json`; the next run will load `backend/data/seed.json`.

Run the domain and repository tests:

```powershell
python -m unittest discover -s backend\tests -t . -v
```

The CLI is intentionally read-only; booking and cancellation are exposed through the service and covered by tests, but no interactive command-line, Pipecat, Gemini, or web interface exists yet. The next implementation step is the Pipecat tool adapter and its caller-confirmation conversation flow.
