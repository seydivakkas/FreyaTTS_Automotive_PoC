# ADR-0007: Deterministic automotive business policy

**Status:** Accepted for mock architectural implementation (2026-10-31).

- M02 transport/control plane and M03 business policy are separated.
- `REQUEST_LLM` is an M02 backwards-compatible effect name, not permission for an LLM to commit or confirm bookings.
- Business facts must originate from verified domain ports. Only backend receipt with a reference authorizes confirmed booking wording.
- All text/PII-like material stays behind per-session opaque references; no raw transcript or speech in reducer audit.
- Confirmed booking idempotency and uncertain transaction recheck are first-class design requirements.
- A distributed transaction and persistent audit outbox are **not** implemented; mock pass does not imply production readiness.
