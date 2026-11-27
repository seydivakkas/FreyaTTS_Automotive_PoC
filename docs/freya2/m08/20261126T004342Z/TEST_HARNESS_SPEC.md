# Test Harness Specification (20261126T004342Z)
- Contracts: `tests/harness/contracts.py` (`TestCaseSpec`, `FixtureManifest`, `TestRunManifest`, `CaseResult`, `GateRecord`).
- Runner: `tests/harness/runner.py` (`HarnessRunner` allowlisted profiles, shell-free `subprocess.run`, count/exit reconciliation).
- Replay & Faults: `tests/harness/replay.py`, `tests/harness/failure_injection.py` (test-only, `PRODUCTION_REACHABLE = False`).
