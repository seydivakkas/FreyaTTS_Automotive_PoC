"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
amaçlı olarak paylaşılmıştır.

YASAKLAR:
  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.
  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.
  3. Alt lisanslanamaz, satılamaz veya devredilemez.
  4. Tersine mühendislik yapılamaz.

İZİN VERİLEN KULLANIM:
  - GitHub üzerinde görüntüleme ve okuma.
  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).

YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.
İzin talepleri için: GitHub @seydivakkas
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Callable

from backend.core.runtime.deadlines import FakeClock


class CrossClockComparisonError(ValueError):
    """Raised when comparing timestamps across unsynchronized clock domains."""


@dataclass(order=True, frozen=True, slots=True)
class _ScheduledWakeup:
    trigger_ns: int
    seq: int
    callback: Callable[[int], None] = field(compare=False)


class HarnessClock(FakeClock):
    """
    Injectable deterministic monotonic clock compatible with M02 FakeClock.

    Supports deterministic scheduled wakeups and rejects cross-clock comparisons
    or backwards monotonic updates without mutating Python's global clock or event loop.
    """

    def __init__(
        self,
        initial_ns: int = 0,
        *,
        clock_domain: str = "harness.fake.clock",
        wall_utc_epoch_ns: int | None = None,
    ) -> None:
        super().__init__(initial_ns=initial_ns, clock_domain=clock_domain)
        if wall_utc_epoch_ns is not None and (type(wall_utc_epoch_ns) is not int or wall_utc_epoch_ns < 0):
            raise ValueError("wall_utc_epoch_ns must be non-negative int")
        self._wall_utc_epoch_ns = wall_utc_epoch_ns
        self._wakeups: list[_ScheduledWakeup] = []
        self._seq = 0

    def schedule_after_ms(self, delay_ms: int, callback: Callable[[int], None]) -> int:
        if type(delay_ms) is not int or delay_ms < 0:
            raise ValueError("delay_ms must be non-negative int")
        return self.schedule_after_ns(delay_ms * 1_000_000, callback)

    def schedule_after_ns(self, delay_ns: int, callback: Callable[[int], None]) -> int:
        if type(delay_ns) is not int or delay_ns < 0:
            raise ValueError("delay_ns must be non-negative int")
        trigger_ns = self._now + delay_ns
        self._seq += 1
        heapq.heappush(self._wakeups, _ScheduledWakeup(trigger_ns=trigger_ns, seq=self._seq, callback=callback))
        return trigger_ns

    def advance_ns(self, delta_ns: int) -> int:
        if type(delta_ns) is not int or delta_ns < 0:
            raise ValueError("Monotonic clock cannot move backwards")
        target = self._now + delta_ns
        while self._wakeups and self._wakeups[0].trigger_ns <= target:
            item = heapq.heappop(self._wakeups)
            self._now = item.trigger_ns
            item.callback(self._now)
        self._now = target
        return self._now

    def advance_ms(self, delta_ms: int) -> int:
        if type(delta_ms) is not int or delta_ms < 0:
            raise ValueError("Monotonic clock cannot move backwards")
        return self.advance_ns(delta_ms * 1_000_000)

    def wall_ns(self) -> int | None:
        if self._wall_utc_epoch_ns is None:
            return None
        return self._wall_utc_epoch_ns + self._now

    @staticmethod
    def elapsed_ns(
        *,
        start_ns: int,
        start_domain: str,
        end_ns: int,
        end_domain: str,
    ) -> int:
        if not start_domain or not end_domain or start_domain != end_domain:
            raise CrossClockComparisonError(
                f"Cannot compute elapsed across unsynchronized clock domains: {start_domain!r} vs {end_domain!r}"
            )
        if end_ns < start_ns:
            raise ValueError(f"Negative elapsed duration prohibited: {end_ns} < {start_ns}")
        return end_ns - start_ns
