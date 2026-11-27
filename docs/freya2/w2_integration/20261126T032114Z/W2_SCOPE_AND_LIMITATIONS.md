# W2 Vertical Slice Scope and Limitations (20261126T032114Z)

## Verified Structural Scope (`T0_T1_STRUCTURAL_OFFLINE_WINDOWS`)
- Composes real `backend.audio_frontend`, `backend.voice_activity`, `backend.speech_recognition`, `backend.supervisor.dialogue_facade` + M07 security/persistence, `backend.linguistic_frontend`, `backend.neural_synthesis`, and `backend.audio_rendering` end-to-end across Web 16 kHz PCM16 (`640 B`) and Phone AudioSocket 8 kHz PCM16 (`0x10 01 40` + `320 B` = `323 B`) profiles.
- Uses deterministic M08 boundaries (`HarnessClock`, `SyntheticAudioGenerator`, `_ScriptedVADModel`, `_FakeWhisperModel`, `FakeOllamaWorker`, `FakeIdentityProvider`, isolated SQLite `crm.db`, `_FakeDiT`/`_FakeVAE`, `FakeAudioSocketTransport`).
- Passive import hygiene verified (`THREADS_DELTA=0`, `torch` not loaded at import time).
- All 742 foundation, layer, core gate, and W2 gate tests passed (`0 failed`, `0 skipped`).

## Explicitly Deferred (`NOT_RUN`)
- `synthetic_product_acceptance_status`: `NOT_RUN` (no real Faster-Whisper, Qwen, Silero TorchScript, or FreyaTTS/AudioVAE weights loaded).
- `hardware_acceptance_status`: `NOT_RUN` (no GPU/CPU RTF, real OS timer jitter, or measured TTFA latency benchmark).
- `human_sip_status`: `NOT_RUN` (no live Asterisk PBX, SIP/RTP, browser microphone/AudioContext playback, or audible endpoint cut measurement).
- Legacy pre-existing baseline failures (4 cases in `tests/test_madde3_customer_experience.py` and `tests/test_voice_path_honesty.py`) remain documented in M00 `RISK_REGISTER.md` with `new_regression_count = 0`.
