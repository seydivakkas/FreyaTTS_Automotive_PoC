"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import asyncio
from typing import Callable

from backend.core.contracts.common import EventEnvelope, SessionIdentity
from backend.core.runtime.deadlines import Clock
from backend.core.runtime.session_context import CleanupStatus, SessionContext


class SessionRegistry:
    """Authoritative active session registry with incarnation and tombstone isolation."""

    def __init__(self, *, clock: Clock | None = None, event_sink: Callable[[EventEnvelope], None] | None = None) -> None:
        self._lock = asyncio.Lock()
        self._active: dict[str, SessionContext] = {}
        self._external_map: dict[str, str] = {}
        self._tombstones: set[str] = set()
        self._clock = clock
        self._event_sink = event_sink

    async def create(
        self,
        session_id: str,
        *,
        external_id: str | None = None,
        trace_id: str | None = None,
        max_queue_items: int = 64,
        max_queue_bytes: int = 256 * 1024,
    ) -> SessionContext:
        ident = SessionIdentity(session_id=session_id, trace_id=trace_id)
        async with self._lock:
            if session_id in self._active:
                raise ValueError(f"Active session already exists: {session_id}")
            if session_id in self._tombstones:
                raise ValueError(f"Session ID {session_id} retired; create new incarnation ID")
            if external_id and external_id in self._external_map:
                old_sid = self._external_map[external_id]
                if old_sid in self._active:
                    raise ValueError(f"External ID {external_id} already bound to active session")
            ctx = SessionContext(
                ident,
                clock=self._clock,
                max_queue_items=max_queue_items,
                max_queue_bytes=max_queue_bytes,
                event_sink=self._event_sink,
            )
            self._active[session_id] = ctx
            if external_id:
                self._external_map[external_id] = session_id
            return ctx

    def get(self, session_id: str, *, incarnation_id: str | None = None) -> SessionContext | None:
        ctx = self._active.get(session_id)
        if ctx is None:
            return None
        if incarnation_id is not None and ctx.incarnation_id != incarnation_id:
            return None
        return ctx

    async def close_session(self, session_id: str, reason: str = "normal_close") -> CleanupStatus:
        async with self._lock:
            ctx = self._active.get(session_id)
        if ctx is None:
            return CleanupStatus.COMPLETE
        status = await ctx.close(reason=reason)
        async with self._lock:
            self._active.pop(session_id, None)
            self._tombstones.add(session_id)
        return status
