# G2 Integrated Feature Gate Report (20261126T064418Z)

- **Overall Verdict:** `PASS` (`G2_01`–`G2_11` all `PASS`)
- **`g2_accepted`:** `true`
- **`g3_ready`:** `true`
- **Deferred Benchmarks:** `synthetic_product_acceptance_status=NOT_RUN`, `hardware_acceptance_status=NOT_RUN`, `human_sip_status=NOT_RUN`
- **Integrated Pytest Verification:** `919 passed in 136.42s (0:02:16)` (`exit_code=0`, `0 failed`, `0 skipped`):
  - `tests/integration/test_g2_gate.py`: `12 passed`
  - `tests/integration/test_w2_gate.py`: `25 passed`
  - `tests/integration/test_core_gate.py`: `25 passed`
  - `tests/harness_tests/test_m08_harness.py`: `80 passed`
  - Foundation (`M01`–`M07`): `79 passed` (`14 + 8 + 11 + 10 + 11 + 11 + 14`)
  - Layer Packages (`F0`–`F6` A+B+C + `intent_prosody`): `698 passed` (`79 + 82 + 80 + 92 + 176 + 89 + 100`)
- **Passive Imports & Privacy:** `THREADS_DELTA=0`, zero `torch`/`librosa`/`backend.models` imports, `PIISecretScanner` clean, `EvidenceValidator` noncircular SHA-256 bundle valid.
- **Evidence Bundle:** `evidence/g2_integration/20261126T064418Z/{manifest.json, artifact_hashes.json, logs/pytest_g2.log}`.
