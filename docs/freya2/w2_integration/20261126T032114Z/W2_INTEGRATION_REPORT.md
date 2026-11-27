# W2 Vertical Slice Integration Gate Report (20261126T032114Z)

- **Overall Verdict:** `PASS` (`WG00`–`WG11` all `PASS`)
- **`w2_vertical_slice_accepted`:** `true`
- **`f1_b_ready`:** `true` (awaits separate owner authorization)
- **Full Pytest Run:** `742 passed, 0 failed, 0 skipped` in `63.66s` (`exit_code=0`) across `M01`–`M08`, `CORE_INTEGRATION`, `F0_A`–`F6_A`, and `W2_GATE` (`tests/integration/test_w2_gate.py`: `25 passed`).
- **Passive Imports:** `THREADS_DELTA=0`, `TORCH_LOADED=False`.
- **Deferred Benchmarks:** `synthetic_product_acceptance_status=NOT_RUN`, `hardware_acceptance_status=NOT_RUN`, `human_sip_status=NOT_RUN`.
- **Evidence Bundle:** `evidence/w2_integration/20261126T032114Z/{manifest.json, artifact_hashes.json, logs/pytest_w2_gate.log}`.
