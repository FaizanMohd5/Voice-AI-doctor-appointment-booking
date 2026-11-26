# Voice AI Doctor Appointment Assistant

## Overview

A Pipecat voice assistant for checking doctor availability, booking appointments, and cancelling appointments. The current pipeline uses Gemini for tool selection and conversation, and ElevenLabs for realtime speech-to-text and text-to-speech. Clinic records are stored in JSON; Google Calendar is not required.

The appointment domain and tool adapter are provider-neutral. A per-call confirmation gate requires the caller to hear the phone number and target appointment read back, then give a clear affirmative before a mutation can happen.

## Project status

- Implemented: JSON-backed doctor/specialty/slot/appointment domain, provider-neutral appointment tools, and an argument-driven manual CLI.
- Implemented: Pipecat SmallWebRTC voice pipeline using Gemini and ElevenLabs, with confirmation state scoped to each call.
- Implemented: a React dashboard with Pipecat voice controls, live transcript, doctor/slot lists, and appointment status.
- Not production-hardened: JSON persistence is intended for a single-process demo, not multiple workers or concurrent deployment.

## Setup (Windows PowerShell)

Use Python 3.11 or later. These commands use Python 3.12:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -e .
Copy-Item .env.example .env
```

Edit `.env` and set your own `GOOGLE_API_KEY`, `ELEVENLABS_API_KEY`, and `ELEVENLABS_VOICE_ID`. The app reads local environment variables or `.env`; do not commit real credentials. The non-voice CLI does not need provider credentials.

## Run and manually test

Preview the sample clinic records and available slots:

```powershell
.\.venv\Scripts\python -m backend.app.main
```

Check availability, optionally filtered by doctor, specialty, or clinic date:

```powershell
.\.venv\Scripts\python -m backend.app.main availability --doctor doctor-101 --date 2026-12-01
.\.venv\Scripts\python -m backend.app.main availability --specialty cardiology
```

Book and cancel commands use the same tool adapter and confirmation gate as the voice pipeline. They print a read-back and require an interactive, clear affirmative; there is no `--yes` bypass:

```powershell
.\.venv\Scripts\python -m backend.app.main book --slot-id slot-201 --phone-number "+91 98765 43210"
.\.venv\Scripts\python -m backend.app.main cancel --phone-number "+91 98765 43210"
```

Cancellation prints the matching appointment choices if more than one exists. Select one by rerunning with `--appointment-id`.

## Run the dashboard and voice pipeline

Install frontend dependencies once (Node.js 22.14+):

```powershell
Set-Location frontend
npm install
```

In one PowerShell terminal, start the Pipecat server:

```powershell
.\.venv\Scripts\python -m backend.app.pipeline -t webrtc
```

In another terminal, start the dashboard:

```powershell
Set-Location frontend
npm run dev
```

Open `http://localhost:5173` and allow microphone access to start a call. The Vite development server proxies voice startup, WebRTC session negotiation, and the read-only clinic API to the Pipecat server on port 7860. Live calls require valid Google and ElevenLabs credentials. The dashboard API is intended for local development; do not expose the runner publicly.

## Tests

Run the domain, tool, CLI, and configuration tests from the repository root:

```powershell
.\.venv\Scripts\python -m unittest discover -s backend\tests -t . -v
```

These tests do not make paid provider calls. They verify the app-side logic, not the quality of live STT, Gemini responses, or TTS.

## Structure and next steps

```text
backend/
  app/
    models.py                 # Doctor, specialty, slot, and appointment records
    appointment_service.py    # Availability, booking, cancellation rules
    json_store.py             # Repository boundary and JSON-backed implementation
    config.py                 # Environment and local settings
    tools.py                  # Provider-neutral tool schemas and handlers
    main.py                   # Read-only preview and interactive manual tool tester
    pipeline.py               # Pipecat, Gemini, ElevenLabs, and browser audio
    dashboard_api.py          # Read-only, phone-redacted clinic snapshot API
  data/
    seed.json                 # Tracked sample data
    state.json                # Generated mutable state; ignored by Git
  tests/                      # Domain, tool, CLI, and configuration tests
frontend/
  src/                        # React dashboard and Pipecat browser client
docs/
  architecture-and-build-guide.md
  ignore/                     # Local-only implementation explanations (Git-ignored)
```

The dashboard is a thin client: it displays call state/transcript and clinic data without implementing appointment rules. For the architecture, data flow, component responsibilities, and fallback paths, see [docs/architecture-and-build-guide.md](docs/architecture-and-build-guide.md).
