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

import asyncio
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Awaitable, Callable

from backend.core.runtime.deadlines import Clock

FRAME_PERIOD_NS = 20_000_000  # 20 ms exact integer nanoseconds


class ClockDomainMismatchError(ValueError):
    """Raised when comparing or mixing monotonic timestamps across different clock domains."""


class LatePolicy(StrEnum):
    REANCHOR = "REANCHOR"
    ABORT_STALE = "ABORT_STALE"


@dataclass(frozen=True, slots=True)
class PacingRecord:
    sequence: int
    target_ns: int
    actual_submit_ns: int
    clock_domain: str
    signed_error_ns: int
    abs_error_ns: int
    inter_submit_gap_ns: int | None
    reanchored: bool
    underrun: bool
    aborted_stale: bool = False


@dataclass(frozen=True, slots=True)
class PacingStats:
    n: int
    clock_domain: str
    reanchor_count: int
    underrun_count: int
    aborted_stale_count: int
    total_lateness_ns: int
    p50_abs_error_ns: float | None
    p95_abs_error_ns: float | None
    p99_abs_error_ns: float | None
    min_inter_submit_gap_ns: int | None


def _percentile(sorted_vals: list[int], pct: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = rank - lo
    return float(sorted_vals[lo]) + frac * float(sorted_vals[hi] - sorted_vals[lo])


class MonotonicPacer:
    """
    Deterministic absolute-deadline 20 ms monotonic nanosecond pacer.

    - Schedules ideal targets `t0 + n * 20_000_000` within a continuous segment.
    - Compensates intra-period send duration without appending an extra 20 ms sleep after send.
    - Prevents catch-up bursts on late wakes or slow drains via bounded re-anchoring or abort.
    - Rejects cross-clock-domain timestamps; never uses wall-clock time for interval scheduling.
    """

    def __init__(
        self,
        clock: Clock,
        *,
        frame_period_ns: int = FRAME_PERIOD_NS,
        late_policy: LatePolicy = LatePolicy.REANCHOR,
        max_lateness_ns: int = 500_000_000,
        sleep_ns_fn: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        if type(frame_period_ns) is not int or frame_period_ns <= 0:
            raise ValueError("frame_period_ns must be positive int")
        if type(max_lateness_ns) is not int or max_lateness_ns < 0:
            raise ValueError("max_lateness_ns must be non-negative int")
        self.clock = clock
        self.clock_domain = clock.clock_domain
        self.frame_period_ns = frame_period_ns
        self.late_policy = late_policy
        self.max_lateness_ns = max_lateness_ns
        self._sleep_ns_fn = sleep_ns_fn or self._default_sleep_ns

        self._next_target_ns: int | None = None
        self._last_submit_ns: int | None = None
        self._records: list[PacingRecord] = []
        self.reanchor_count = 0
        self.underrun_count = 0
        self.aborted_stale_count = 0
        self.total_lateness_ns = 0

    @staticmethod
    async def _default_sleep_ns(wait_ns: int) -> None:
        if wait_ns > 0:
            await asyncio.sleep(wait_ns / 1_000_000_000.0)

    def _assert_clock_domain(self) -> int:
        if self.clock.clock_domain != self.clock_domain:
            raise ClockDomainMismatchError(
                f"Clock domain mismatch: expected {self.clock_domain!r}, got {self.clock.clock_domain!r}"
            )
        return self.clock.monotonic_ns()

    def notify_underrun(self) -> None:
        """Record an upstream producer gap/underrun explicitly without generating hidden comfort silence."""
        self.underrun_count += 1

    def reset_segment(self) -> None:
        """Clear schedule anchor for a new segment/generation while preserving cumulative counters."""
        self._next_target_ns = None
        self._last_submit_ns = None

    async def wait_until_next_target(self, *, underrun_recovered: bool = False) -> tuple[bool, int, bool]:
        """
        Await outside any lock until the next absolute 20 ms target.

        Returns `(proceed, target_ns, reanchored)`.
        If `proceed=False`, `late_policy == ABORT_STALE` triggered due to exceeding `max_lateness_ns`.
        """
        now_ns = self._assert_clock_domain()
        if underrun_recovered:
            self.underrun_count += 1

        if self._next_target_ns is None:
            self._next_target_ns = now_ns
            return True, self._next_target_ns, False

        target_ns = self._next_target_ns
        if now_ns < target_ns:
            await self._sleep_ns_fn(target_ns - now_ns)
            now_ns = self._assert_clock_domain()

        lateness = now_ns - target_ns
        if lateness > self.frame_period_ns:
            self.total_lateness_ns += lateness
            if self.late_policy == LatePolicy.ABORT_STALE and lateness > self.max_lateness_ns:
                self.aborted_stale_count += 1
                return False, target_ns, False
            # Re-anchor schedule to avoid bursting overdue frames
            self.reanchor_count += 1
            return True, target_ns, True

        return True, target_ns, False

    def record_submission(
        self,
        *,
        sequence: int,
        target_ns: int,
        reanchored: bool,
        underrun: bool = False,
        aborted_stale: bool = False,
    ) -> PacingRecord:
        """Record actual submission timestamp and compute next absolute schedule target."""
        actual_ns = self._assert_clock_domain()
        gap_ns = None if self._last_submit_ns is None else (actual_ns - self._last_submit_ns)
        signed_err = actual_ns - target_ns
        abs_err = abs(signed_err)

        if not aborted_stale:
            self._last_submit_ns = actual_ns
            if reanchored or actual_ns > target_ns + self.frame_period_ns:
                # Re-anchor from actual submission + 20 ms to enforce minimum inter-submit gap & no burst
                self._next_target_ns = actual_ns + self.frame_period_ns
                if not reanchored:
                    self.reanchor_count += 1
                    self.total_lateness_ns += max(0, actual_ns - target_ns)
                    reanchored = True
            else:
                # Preserve exact t0 + n * 20_000_000 cadence across within-period send delays
                self._next_target_ns = target_ns + self.frame_period_ns

        rec = PacingRecord(
            sequence=sequence,
            target_ns=target_ns,
            actual_submit_ns=actual_ns,
            clock_domain=self.clock_domain,
            signed_error_ns=signed_err,
            abs_error_ns=abs_err,
            inter_submit_gap_ns=gap_ns,
            reanchored=reanchored,
            underrun=underrun,
            aborted_stale=aborted_stale,
        )
        self._records.append(rec)
        return rec

    def stats(self) -> PacingStats:
        abs_errs = sorted(r.abs_error_ns for r in self._records if not r.aborted_stale)
        gaps = [r.inter_submit_gap_ns for r in self._records if r.inter_submit_gap_ns is not None and not r.aborted_stale]
        return PacingStats(
            n=len(abs_errs),
            clock_domain=self.clock_domain,
            reanchor_count=self.reanchor_count,
            underrun_count=self.underrun_count,
            aborted_stale_count=self.aborted_stale_count,
            total_lateness_ns=self.total_lateness_ns,
            p50_abs_error_ns=_percentile(abs_errs, 50.0),
            p95_abs_error_ns=_percentile(abs_errs, 95.0),
            p99_abs_error_ns=_percentile(abs_errs, 99.0),
            min_inter_submit_gap_ns=min(gaps) if gaps else None,
        )
