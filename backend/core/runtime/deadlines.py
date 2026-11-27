"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


class Clock(Protocol):
    clock_domain: str

    def monotonic_ns(self) -> int: ...


class SystemMonotonicClock:
    clock_domain: str = "process.monotonic"

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()


class FakeClock:
    def __init__(self, initial_ns: int = 0, clock_domain: str = "fake.clock") -> None:
        if type(initial_ns) is not int or initial_ns < 0:
            raise ValueError("initial_ns must be non-negative int")
        self._now = initial_ns
        self.clock_domain = clock_domain

    def monotonic_ns(self) -> int:
        return self._now

    def advance_ns(self, delta_ns: int) -> int:
        if type(delta_ns) is not int or delta_ns < 0:
            raise ValueError("Monotonic clock cannot move backwards")
        self._now += delta_ns
        return self._now

    def advance_ms(self, delta_ms: int) -> int:
        return self.advance_ns(delta_ms * 1_000_000)


@dataclass(frozen=True, slots=True)
class DeadlineBudget:
    deadline_ns: int
    clock_domain: str

    @classmethod
    def from_now(cls, clock: Clock, timeout_ms: int) -> "DeadlineBudget":
        if type(timeout_ms) is not int or timeout_ms < 0:
            raise ValueError("timeout_ms must be non-negative int")
        return cls(clock.monotonic_ns() + timeout_ms * 1_000_000, clock.clock_domain)

    def remaining_ns(self, clock: Clock) -> int:
        if clock.clock_domain != self.clock_domain:
            raise ValueError(f"Clock domain mismatch: {clock.clock_domain} != {self.clock_domain}")
        return self.deadline_ns - clock.monotonic_ns()

    def is_expired(self, clock: Clock) -> bool:
        return self.remaining_ns(clock) <= 0
