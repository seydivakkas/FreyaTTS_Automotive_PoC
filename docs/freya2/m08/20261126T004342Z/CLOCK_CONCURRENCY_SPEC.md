# Clock & Concurrency Specification (20261126T004342Z)
- `HarnessClock`: inherits M02 `FakeClock`, adds scheduled wakeups, rejects backward time and cross-clock elapsed calculation.
- `DeterministicBarrier` + `run_with_watchdog`: deterministic interleaving checkpoints without sleep-based race assertions.
