"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field

from backend.core.runtime.deadlines import Clock, SystemMonotonicClock


class StaleScopeError(RuntimeError):
    pass


@dataclass(slots=True)
class CancellationScope:
    scope_id: str
    clock: Clock = field(default_factory=SystemMonotonicClock)
    parent: "CancellationScope | None" = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cancelled: bool = False
    _reason: str | None = None
    _cancelled_at_ns: int | None = None
    _children: list["CancellationScope"] = field(default_factory=list, repr=False)
    _async_event: asyncio.Event | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.parent is not None:
            self.parent._attach_child(self)

    def _attach_child(self, child: "CancellationScope") -> None:
        with self._lock:
            if self._cancelled:
                child.request_cancel(self._reason or "parent_cancelled")
            else:
                self._children.append(child)

    def child_scope(self, scope_id: str) -> "CancellationScope":
        return CancellationScope(scope_id=scope_id, clock=self.clock, parent=self)

    @property
    def is_cancel_requested(self) -> bool:
        with self._lock:
            return self._cancelled

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason

    @property
    def cancelled_at_ns(self) -> int | None:
        with self._lock:
            return self._cancelled_at_ns

    def request_cancel(self, reason: str) -> bool:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("cancel reason must be non-empty")
        children_to_cancel: list[CancellationScope]
        ev: asyncio.Event | None
        with self._lock:
            if self._cancelled:
                return False
            self._cancelled = True
            self._reason = reason
            self._cancelled_at_ns = self.clock.monotonic_ns()
            children_to_cancel = list(self._children)
            ev = self._async_event
        if ev is not None:
            ev.set()
        for child in children_to_cancel:
            child.request_cancel(reason)
        return True

    def check_active(self) -> None:
        if self.is_cancel_requested:
            raise StaleScopeError(f"Scope {self.scope_id} cancelled: {self.reason}")

    async def wait_cancelled(self) -> None:
        with self._lock:
            if self._cancelled:
                return
            if self._async_event is None:
                self._async_event = asyncio.Event()
            ev = self._async_event
        await ev.wait()
