# ADR-0006 — M02 Signal Reducer, Media Flush ACK Barrier

**Status:** Accepted for in-memory architecture mock (2026-10-31)

**Context:** M01 only offers imperative session transitions and in-memory event fanout. A future telephony adapter must not be able to resume playback/listening while old audio is still queued.

**Decision:** Introduce typed input control signals with independent per-session input sequence, single reducer lock per session, M01 as the only session state authority, and separate bounded effect outbox. Establish `INTERRUPTING` as an ACK barrier. Allow deferred transcript + atomic ACK/new-turn or ACK/handoff. Inject watchdog timeout only through explicit scheduled polling. Keep terminal-safe emergency closure in case M01 event outbox is full.

**Alternatives rejected:** Reducer directly mutating `Session`, using audio callbacks as flush ACK without correlation ID, ACK-free listening transition, directly invoking network callbacks from inside state lock, pretending the RAM outbox is persistent.

**Consequences:** More stringent events and adapter responsibility. No real speaker or telecom validation until M11. M09–M10 must add durable event processing and transport-level delivery confirmation.
