"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from backend.core.contracts.common import SessionIdentity
from backend.core.runtime.session_context import SessionContext, SessionLifecycleState


def attach_runtime_context(session_id: str, *, trace_id: str | None = None) -> SessionContext:
    """Create a standalone M02 SessionContext for legacy VoiceSession integration."""
    return SessionContext(SessionIdentity(session_id=session_id, trace_id=trace_id))


async def ensure_active(ctx: SessionContext) -> SessionContext:
    if ctx.lifecycle_state == SessionLifecycleState.NEW:
        await ctx.open()
    return ctx
