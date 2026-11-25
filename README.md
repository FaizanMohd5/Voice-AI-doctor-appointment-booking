# Voice AI Doctor Appointment Assistant

## Overview

A browser-based voice assistant for checking doctor availability, booking appointments, and cancelling appointments. The planned voice pipeline uses Pipecat (Python), ElevenLabs for speech-to-text and text-to-speech, and Gemini as the selected LLM.

The caller identifies themself only by the phone number they speak. The assistant must read the number back and get confirmation before booking or cancelling. A dashboard will start/end calls, show the live transcript, and display doctors, available slots, and appointments.

## Project status

The first domain/data slice is implemented: doctor, specialty, slot, and appointment models; availability, booking, and cancellation rules; JSON persistence; and focused tests. The Pipecat pipeline, Gemini integration, and dashboard have not been implemented yet.

## Run the implemented slice

Requires Python 3.10+ and no third-party packages.

From the repository root, list the sample clinic data and available slots:

```powershell
python -m backend.app.main
```

Filter the displayed slots by clinic date, doctor ID, or specialty ID:

```powershell
python -m backend.app.main --date 2026-12-01
python -m backend.app.main --doctor doctor-101
python -m backend.app.main --specialty cardiology
```

Run the domain and JSON repository tests:

```powershell
python -m unittest discover -s backend\tests -t . -v
```

This is a read-only command-line view of the implemented domain/data layer, not yet the complete voice or web application. There is no Google Calendar integration; the assignment allows local mock data, and this prototype uses JSON.

## Recommended build order

1. Connect the existing appointment services to the required Pipecat tools.
2. Add browser audio transport, ElevenLabs STT/TTS, and Gemini; verify complete booking and cancellation conversations.
3. Build the dashboard as a thin client after the core voice workflow is reliable. React is a suitable choice, but the backend should not depend on it.
4. Add optional assignment bonus features only after the required flow works.

## Simplest starting structure

Keep the first version small and split files by responsibility rather than introducing extra layers or frameworks:

```text
backend/
  app/
    models.py                 # Doctor, specialty, slot, and appointment records
    appointment_service.py    # Availability, booking, cancellation rules
    json_store.py             # Repository boundary and JSON-backed implementation
    main.py                   # Read-only CLI preview of clinic data
    tools.py                  # Pipecat function-tool adapters (next)
    pipeline.py               # Pipecat voice pipeline (later)
  data/
    seed.json                 # Tracked sample data; remains unchanged at runtime
    state.json                # Generated mutable state; ignored by Git
  tests/
    test_appointment_service.py
```

Run the domain tests from the repository root with:

```powershell
python -m unittest discover -s backend\tests -t . -v
```

## Initial data decisions

- Use JSON seed data and a small repository interface for the local, single-process prototype. Runtime mutations are written to ignored `backend/data/state.json`; the tracked seed remains unchanged. Keep appointment rules in `appointment_service.py`, not in Pipecat prompts or JSON file handling.
- Represent doctors and specialties by stable IDs; slots reference doctor IDs and use timestamps with explicit time zones.
- Pick one clinic time zone in configuration. Ask for clarification rather than silently interpreting an ambiguous date or time.
- Recheck slot availability when booking and only report success after the JSON write succeeds. Treat a simultaneous multi-process deployment as out of scope for this first storage choice; move to SQLite or a database if concurrent callers or stronger durability are needed.
- Keep secrets in local environment files. Commit `.env.example` with placeholder setting names, never real API keys.
- Gemini is selected, but no Gemini credential is needed until the LLM integration is implemented.

## Planned request flow

```text
Browser audio
    -> Pipecat session
    -> STT -> conversation/LLM
    -> appointment tool -> domain service -> JSON repository
    -> LLM response -> TTS -> browser audio

Dashboard <- call state and transcript events
Dashboard <- doctors, slots, and appointment data
```

The JSON repository is the source of truth for appointment outcomes. The LLM selects and explains actions; it does not invent availability or decide that a write succeeded.
