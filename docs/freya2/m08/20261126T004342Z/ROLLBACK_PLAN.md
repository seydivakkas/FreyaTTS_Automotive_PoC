# M08 Rollback Plan (20261126T004342Z)
- Revert only M08-owned directories (`tests/harness/`, `tests/harness_tests/`, `tests/integration/`, `docs/freya2/m08/20261126T004342Z/`, `evidence/m08/20261126T004342Z/`, `docs/freya2/core_integration/20261126T004342Z/`, `evidence/core_integration/20261126T004342Z/`).
- Never run blanket `git reset --hard` or touch `backend/`, `frontend/`, or `docs/freya2/baseline/`.
