# W2 Rollback and Remediation Reference (20261126T032114Z)

- **Integrated Snapshot Reference:** `head_sha=6273981e1684686ae85f9458b608764e85a4552c`, `source_scope_hash=bddb7ac19267e378dcdbbddb4abc45e9674d8aefa39d31adc4ee831eb701a254`, `core_integration_run_id=20261126T004342Z`.
- **Gate Scope Boundary:** `W2_GATE` only created/modified `tests/integration/test_w2_gate.py`, `docs/freya2/w2_integration/20261126T032114Z/`, and `evidence/w2_integration/20261126T032114Z/`. Zero `backend/*`, `frontend/*`, or prior evidence artifacts were altered.
- **Remediation Routing:** Any regression discovered post-W2 must be routed to the owning package (`F0-A`..`F6-A` or `M01`..`M08`) under a separate authorized fix scope and re-verified across impacted suites plus a fresh W2 run ID.
- **Safe Rollback:** Revert strict experimental route flags (`f1_vad_route_mode`, `asr_route_mode`, `supervisor_mode`) at session boundary via M03 `ConfigSnapshot` without altering accepted evidence bundles.
