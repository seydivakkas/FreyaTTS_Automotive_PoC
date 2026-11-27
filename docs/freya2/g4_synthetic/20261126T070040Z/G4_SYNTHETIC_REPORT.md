# G4 Deterministic Synthetic Acceptance Report (20261126T070040Z)

- **Run ID:** `20261126T070040Z`
- **Lineage:** `G2=20261126T064418Z (PASS)`, `G3=20261126T064550Z (build PASS, UG17=HOLD)`, `HEAD=6273981e1684686ae85f9458b608764e85a4552c` (`master`)
- **Synthetic Lanes Verdict:** `T0=PASS`, `T1=PASS`, `T3-mock=PASS`, `T4-fault=PASS`
- **Deferred / Unexecuted Lanes:**
  - `T2-native`: `NOT_RUN` (offline synthetic acceptance grant only; no real GPU/native model execution)
  - `T3-native`: `NOT_RUN` (native Whisper/Qwen/FreyaTTS E2E not executed)
  - `T4-load`: `NOT_RUN` (separate resource/soak grant required)
  - `T4-PBX-lab`: `NOT_RUN` (no isolated Asterisk/PBX lab endpoint authorized)
  - `T5-human-sip`: `NOT_RUN` (G5 only; no real human callers or public SIP/PSTN)
  - `MOS/ABX`: `NOT_RUN` (G5 only; requires independent consented human listeners)
  - `F5-D/LoRA`: `HOLD` (not a G4 prerequisite; synthetic residuals cannot authorize LoRA)

## G4 Synthetic Acceptance Suite (`tests/integration/test_g4_synthetic_acceptance.py`)
- **Result:** `8 passed in 11.11s` (`0 failed`, `0 skipped`)
- **Coverage:**
  - `test_g4_01_entry_lineage_g2_g3_and_passive_imports`: Verified G2/G3 lineage and passive imports (`THREADS_DELTA=0`, zero `torch`/`librosa`/`backend.models` loads).
  - `test_g4_02_t3_mock_e2e_web_16k_and_audiosocket_8k`: Full F0–F6 synthetic E2E across Web 16k (`640B` PCM16) and AudioSocket 8k (`0x10` `320B` PCM16) with `PlaybackReferenceTap` -> `PlaybackReferenceReader`.
  - `test_g4_03_multi_turn_slot_correction_and_m07_challenge_receipt`: Anonymous mutation denied, multi-turn slot/vehicle correction invalidating prior challenge digest, explicit M07 confirmation yielding single `COMMITTED` `MOCK` receipt (`verified_result=False`), and idempotent replay with 1 DB `Appointment` row.
  - `test_g4_04_barge_in_soft_pause_resume_and_confirmed_commit`: Two-stage barge-in (`SOFT_PAUSED` -> `RESUMED` on rejected candidate; `PAUSE_REQUESTED` -> `COMMITTED` with `CancellationScope` cancellation, `BoundedMediaQueue` flush, and `SERVER FLUSHED` vs `PBX UNSUPPORTED` receipt).
  - `test_g4_05_31_intent_prosody_table_and_advisory_routing`: All 31 intents in `INTENT_PROSODY_TABLE` verified with `plan_f4c_prosody_and_chunks` advisory binding and zero `model_text` mutation.
  - `test_g4_06_t4_fault_injection_quarantine_acl_backpressure_and_cleanup`: M06 `uncertain_device_state` quarantine & reclaim (`active_count == 0`), F5 `QualityGuard` silent rejection & PII cache rejection, F0-B browser AEC `BYPASS`, F3-C RAG `WORKSHOP_INTERNAL` ACL isolation & `CONFLICT` abstention, and F6-B `BoundedPlaybackQueue` capacity backpressure.
  - `test_g4_07_privacy_projection_and_honest_scope_disposition`: `TraceStore`, `Projection`, `PIISecretScanner` clean, and `evaluate_gates` honest disposition.

## Full Repository Pytest Suite
- **Command:** `.venv\Scripts\python.exe -m pytest -q --basetemp=data/temp_pytest_g4`
- **Result:** `2523 passed, 2 failed, 0 skipped, 44 subtests passed in 571.43s (0:09:31)` (`exit_code=1`)
- **Observed Failures (existing repo tests, untouched per strict ownership):**
  1. `tests/configuration/test_m03_config_registry.py::test_offline_preflight_read_only_without_loading_weights`: `AssertionError: assert 'torch' not in sys.modules` (earlier legacy tests in the combined pytest process imported `torch`).
  2. `tests/test_api.py::test_teardown_failure_releases_single_call_capacity`: `Failed: DID NOT RAISE RuntimeError`.
- **Evidence Bundle:** `evidence/g4_synthetic/20261126T070040Z/{manifest.json, artifact_hashes.json, logs/pytest_full.log}`.
