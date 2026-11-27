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
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TypeVar

T = TypeVar("T")


class InterleavingPoint(StrEnum):
    BEFORE_ADMISSION = "before_admission"
    AFTER_ADMISSION_BEFORE_DISPATCH = "after_admission_before_dispatch"
    IN_FLIGHT = "in_flight"
    AFTER_CANCEL_BEFORE_COMPLETION = "after_cancel_before_completion"
    CONCURRENT_CLOSE = "concurrent_close"
    LATE_CALLBACK = "late_callback"


class WatchdogTimeoutError(TimeoutError):
    """Raised when a deterministic safety watchdog bounds a hung test operation."""


class PhaseGate:
    """Two-step deterministic coordination gate (arrived -> released) without sleep."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._arrived = asyncio.Event()
        self._release = asyncio.Event()
        self.arrived_count = 0

    async def arrive_and_wait(self, *, watchdog_sec: float = 2.0) -> None:
        self.arrived_count += 1
        self._arrived.set()
        await asyncio.wait_for(self._release.wait(), timeout=watchdog_sec)

    async def wait_arrived(self, *, watchdog_sec: float = 2.0) -> None:
        await asyncio.wait_for(self._arrived.wait(), timeout=watchdog_sec)

    def release(self) -> None:
        self._release.set()

    def reset(self) -> None:
        self._arrived.clear()
        self._release.clear()
        self.arrived_count = 0


class DeterministicBarrier:
    """Registry of named PhaseGates for repeatable concurrency interleavings."""

    def __init__(self, *, watchdog_sec: float = 2.0) -> None:
        if watchdog_sec <= 0:
            raise ValueError("watchdog_sec must be positive")
        self.watchdog_sec = watchdog_sec
        self._gates: dict[str, PhaseGate] = {}

    def gate(self, point: InterleavingPoint | str) -> PhaseGate:
        key = point.value if isinstance(point, InterleavingPoint) else str(point)
        if key not in self._gates:
            self._gates[key] = PhaseGate(key)
        return self._gates[key]

    async def checkpoint(self, point: InterleavingPoint | str) -> None:
        await self.gate(point).arrive_and_wait(watchdog_sec=self.watchdog_sec)

    async def wait_for_point(self, point: InterleavingPoint | str) -> None:
        await self.gate(point).wait_arrived(watchdog_sec=self.watchdog_sec)

    def release(self, point: InterleavingPoint | str) -> None:
        self.gate(point).release()

    def release_all(self) -> None:
        for g in self._gates.values():
            g.release()


async def run_with_watchdog(
    coro_or_fn: Awaitable[T] | Callable[[], Awaitable[T]],
    *,
    timeout_sec: float = 2.0,
    label: str = "operation",
) -> T:
    """Bound an async operation with a safety watchdog and clean cancellation."""
    coro = coro_or_fn() if callable(coro_or_fn) else coro_or_fn
    task = asyncio.ensure_future(coro)
    try:
        return await asyncio.wait_for(task, timeout=timeout_sec)
    except asyncio.TimeoutError as exc:
        if not task.done():
            task.cancel()
            try:
                await task
            except BaseException:
                pass
        raise WatchdogTimeoutError(f"Watchdog expired after {timeout_sec}s on {label}") from exc
