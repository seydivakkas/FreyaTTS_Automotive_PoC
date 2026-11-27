# F0–F6 kaynak haritası

- F0 Input DSP | backend/car_denoiser.py, backend/dsp.py
- F1 VAD and interruption | backend/audio.py, backend/session.py, backend/semantic_turn_detector.py
- F2 ASR and terminology | backend/models.py, backend/automotive_terminology.py, backend/turkish_plate.py
- F3 Dialogue and workflows | backend/dialogue.py, backend/appointment_reschedule.py, backend/automotive_dispatch.py, backend/queue_lift.py, backend/caller_memory.py, backend/transfer.py, backend/dtmf.py
- F4 Text normalization | backend/text.py, backend/normalizer_rules.py, backend/automotive_frontend.py
- F5 Synthesis | backend/models.py, backend/batched_ode.py
- F6 Media transport | backend/main.py, backend/audiosocket_server.py, backend/telephony.py, backend/websocket_adapter.py

Dal ve format izleme kısmi.

## Confirmed entry edges

- Web `backend/main.py:198` opens the WebSocket and constructs `VoiceSession("web", emit, audio)` at line 236.
- AudioSocket `backend/audiosocket_server.py:425` builds its pacer and creates a separate `VoiceSession` at line 492.
- `backend/session.py:410` feeds samples to the endpoint detector. The dialogue calls at lines 567 and 694 are separate entry points to map before changing the final-turn contract.
- `backend/session.py:1061–1072` cancels several tasks during teardown. The WebSocket and AudioSocket greeting tasks each have their own cancellation sites.
