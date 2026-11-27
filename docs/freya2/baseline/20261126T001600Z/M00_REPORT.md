# M00 Baseline & Feature Inventory Report (20261126T001600Z)

- **Overall:** PASS (`m01_ready: true`)
- **Baseline Commit:** `6273981e1684686ae85f9458b608764e85a4552c` (branch `master`, dirty working tree preserved)
- **Bundle Checksum Verification:** 91/91 SHA-256 entries PASS
- **Scope:** 678 hashed source/config/doc/test files; secrets/DBs/binaries excluded
- **API Inventory:** 243 registered HTTP/WS endpoints (with OpenAPI schemas & auth dependencies)
- **UI Inventory:** 29 nav views, 130 TSX API binding sites (`tsc --noEmit && vite build` PASS)
- **DB Schema:** 33 SQLAlchemy ORM tables verified in isolated temp SQLite
- **Config & Models:** 81 entries (77 Settings + 4 model descriptors; Silero SHA-256 verified)
- **Baseline Tests:** `pytest -q` -> 1594 passed, 4 failed, 44 subtests passed (`229.44s`); 4 failures recorded in `RISK_REGISTER.md` for owner remediation.
