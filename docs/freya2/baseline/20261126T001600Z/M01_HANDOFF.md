# M01 Handoff (20261126T001600Z)

- **M00 Overall:** PASS (`m01_ready: true`)
- **Baseline Commit:** `6273981e1684686ae85f9458b608764e85a4552c` (dirty working tree preserved; hashes recorded in `INTEGRITY_BEFORE.json`)
- **Existing Contract Surfaces to Reuse/Wrap:**
  - `automotive_voice/core/identifiers.py` (`SessionId`, `TurnId`, `GenerationId`)
  - `automotive_voice/core/events.py` (`EventEnvelope` v1.0, `EventType`)
  - `automotive_voice/core/audio.py` (`AudioFormat`, `AudioFrame`)
  - `backend/supervisor/contracts.py` (`Intent`, `IntentCandidate`, `IntentDecision`, `Slot`, `ConversationContext`, `ExecutionPlan`)
  - `backend/morphology/contracts.py` (`LexiconEntry`, `WordPhoneticHint`, `NormalizedUtterance`, `ExtendedProsodyPlan`)
  - `backend/pipeline_telemetry.py` (`make_pipeline_event` v3.0)
- **M01 Scope:** Introduce `backend/core/contracts/` (internal `schema_version = "2.0"`) + `backend/core/adapters/` mapping existing `automotive_voice.core`, `backend.supervisor.contracts`, `backend.session`, `backend.audio`, `backend.dialogue`, `backend.text`, `backend.models`, `backend.dsp`, and `backend.audiosocket_server` without altering any public API or breaking existing `tests/milestones/`.
