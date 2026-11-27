"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable


class LeaseState(StrEnum):
    OWNED = "OWNED"
    BORROWED = "BORROWED"
    IN_FLIGHT = "IN_FLIGHT"
    RELEASE_REQUESTED = "RELEASE_REQUESTED"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"


@dataclass(slots=True)
class ResourceLease:
    lease_id: str
    kind: str
    state: LeaseState
    release_fn: Callable[[], None] | None = None


class ResourceLedger:
    """Tracks owned/borrowed/quarantined resources with bounded quarantine capacity."""

    def __init__(self, max_quarantined: int = 16) -> None:
        self.max_quarantined = max_quarantined
        self._leases: dict[str, ResourceLease] = {}

    @property
    def quarantined_count(self) -> int:
        return sum(1 for l in self._leases.values() if l.state == LeaseState.QUARANTINED)

    @property
    def active_count(self) -> int:
        return sum(1 for l in self._leases.values() if l.state != LeaseState.RELEASED)

    def acquire(self, lease_id: str, kind: str, *, borrowed: bool = False, release_fn: Callable[[], None] | None = None) -> ResourceLease:
        if lease_id in self._leases and self._leases[lease_id].state != LeaseState.RELEASED:
            raise ValueError(f"Lease already active: {lease_id}")
        if self.quarantined_count >= self.max_quarantined:
            raise RuntimeError("Quarantine budget exhausted; refusing new lease")
        lease = ResourceLease(
            lease_id=lease_id,
            kind=kind,
            state=LeaseState.BORROWED if borrowed else LeaseState.OWNED,
            release_fn=release_fn,
        )
        self._leases[lease_id] = lease
        return lease

    def mark_in_flight(self, lease_id: str) -> None:
        lease = self._leases[lease_id]
        if lease.state == LeaseState.RELEASED:
            raise RuntimeError("Cannot mark released lease in-flight")
        lease.state = LeaseState.IN_FLIGHT

    def quarantine(self, lease_id: str) -> None:
        lease = self._leases[lease_id]
        if lease.state != LeaseState.RELEASED:
            lease.state = LeaseState.QUARANTINED

    def release(self, lease_id: str) -> bool:
        lease = self._leases.get(lease_id)
        if lease is None or lease.state == LeaseState.RELEASED:
            return False
        if lease.state == LeaseState.BORROWED:
            # Borrowed shared handles (like global model singletons) are detached, never destroyed.
            lease.state = LeaseState.RELEASED
            return True
        if lease.release_fn is not None:
            lease.release_fn()
        lease.state = LeaseState.RELEASED
        return True

    def close_all(self) -> tuple[int, int, list[str]]:
        released = 0
        quarantined = 0
        errors: list[str] = []
        for lid, lease in list(self._leases.items()):
            if lease.state == LeaseState.RELEASED:
                continue
            if lease.state == LeaseState.IN_FLIGHT:
                lease.state = LeaseState.QUARANTINED
                quarantined += 1
                continue
            if lease.state == LeaseState.QUARANTINED:
                quarantined += 1
                continue
            try:
                if self.release(lid):
                    released += 1
            except Exception as exc:
                lease.state = LeaseState.QUARANTINED
                quarantined += 1
                errors.append(f"{lid}:{type(exc).__name__}")
        return released, quarantined, errors


class TaskRegistry:
    """Strong task tracking with exception observation and bounded shutdown."""

    def __init__(self, max_tasks: int = 32) -> None:
        self.max_tasks = max_tasks
        self._tasks: set[asyncio.Task] = set()
        self.exceptions: list[str] = []

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    def track(self, task: asyncio.Task) -> asyncio.Task:
        if len(self._tasks) >= self.max_tasks:
            task.cancel()
            raise RuntimeError("TaskRegistry capacity reached")
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    def _on_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                self.exceptions.append(type(exc).__name__)

    async def cancel_and_drain(self, timeout_sec: float = 0.5) -> tuple[int, int]:
        pending = [t for t in self._tasks if not t.done()]
        for t in pending:
            t.cancel()
        if not pending:
            return 0, 0
        done, still_pending = await asyncio.wait(pending, timeout=timeout_sec)
        for t in done:
            if not t.cancelled():
                _ = t.exception()
        return len(done), len(still_pending)
