# Özellik envanteri

- F0 Input DSP | backend/car_denoiser.py, backend/dsp.py
- F1 VAD and interruption | backend/audio.py, backend/session.py, backend/semantic_turn_detector.py
- F2 ASR and terminology | backend/models.py, backend/automotive_terminology.py, backend/turkish_plate.py
- F3 Dialogue and workflows | backend/dialogue.py, backend/appointment_reschedule.py, backend/automotive_dispatch.py, backend/queue_lift.py, backend/caller_memory.py, backend/transfer.py, backend/dtmf.py
- F4 Text normalization | backend/text.py, backend/normalizer_rules.py, backend/automotive_frontend.py
- F5 Synthesis | backend/models.py, backend/batched_ode.py
- F6 Media transport | backend/main.py, backend/audiosocket_server.py, backend/telephony.py, backend/websocket_adapter.py

API ve UI aday kayıtları ayrı JSON dosyalarında.

## Verified source bindings

The acceptance panel (`frontend/src/AcceptanceProtocolPanel.tsx:121–124,155–213`) reads prerequisites, scenarios, runs and terminology audit data. The same panel calls POST handlers for fixture preparation, run creation, run verification and terminology testing. Its mask control re-reads a run with a query parameter. Server authorization and all other panel controls require reconciliation before closing the action coverage check.
