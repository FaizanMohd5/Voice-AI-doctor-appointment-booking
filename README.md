# Voice AI Doctor Appointment Assistant

## Overview

A Pipecat voice assistant for checking doctor availability, booking appointments, and cancelling appointments. The current pipeline uses Gemini for tool selection and conversation, and ElevenLabs for realtime speech-to-text and text-to-speech. Clinic records are stored in JSON; Google Calendar is not required.

The appointment domain and tool adapter are provider-neutral. A per-call confirmation gate requires the caller to hear the phone number and target appointment read back, then give a clear affirmative before a mutation can happen.

## Project status

- Implemented: JSON-backed doctor/specialty/slot/appointment domain, provider-neutral appointment tools, and an argument-driven manual CLI.
- Implemented: Pipecat SmallWebRTC voice pipeline using Gemini and ElevenLabs, with confirmation state scoped to each call.
- Not implemented yet: the custom React dashboard. Pipecat's local development client is only for testing microphone/audio connectivity.
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

## Run the voice pipeline

```powershell
.\.venv\Scripts\python -m backend.app.pipeline -t webrtc
```

Open the Pipecat development client at `http://localhost:7860/client`, allow microphone access, and connect. A live voice session requires valid Google and ElevenLabs credentials. The built-in client validates the voice pipeline but is not the eventual product dashboard.

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
  data/
    seed.json                 # Tracked sample data
    state.json                # Generated mutable state; ignored by Git
  tests/                      # Domain, tool, CLI, and configuration tests
docs/
  architecture-and-build-guide.md
  ignore/                     # Local-only implementation explanations (Git-ignored)
```

Build the custom dashboard as a later, thin client: it should display call state/transcript and clinic data without implementing appointment rules itself. For the architecture, data flow, component responsibilities, and fallback paths, see [docs/architecture-and-build-guide.md](docs/architecture-and-build-guide.md).
