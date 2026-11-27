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

from dataclasses import dataclass

from backend.audio_rendering.playback_events import PlaybackEventEmitter
from backend.audio_rendering.stream_state import RenderStreamState, StreamStateRegistry
from backend.audio_rendering.telemetry import RenderTelemetry
from backend.core.contracts.common import GenerationRef, TurnRef
from backend.core.contracts.playback import ObservationScope, PlaybackEventKind
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.session_context import CleanupStatus, SessionContext
from backend.core.runtime.turn_generation import PauseRef


@dataclass(frozen=True, slots=True)
class CloseSummary:
    session_id: str
    incarnation_id: str
    cleanup_status: CleanupStatus
    quarantined_leases: int
    closed_streams: int
    reason: str


class RenderLifecycleManager:
    """
    Coordinates M02 SessionContext lifecycle (open, turn/generation transitions,
    soft pause/resume, commit interrupt, idempotent close, and incarnation isolation)
    with F6-A stream states and truthful SERVER PlaybackEvents.
    """

    def __init__(
        self,
        *,
        session_ctx: SessionContext,
        registry: StreamStateRegistry,
        events: PlaybackEventEmitter,
        telemetry: RenderTelemetry,
    ) -> None:
        self.session_ctx = session_ctx
        self.registry = registry
        self.events = events
        self.telemetry = telemetry
        self._close_summary: CloseSummary | None = None

    async def ensure_open(self) -> None:
        from backend.core.runtime.legacy_bridge import ensure_active

        await ensure_active(self.session_ctx)

    async def begin_turn_and_generation(
        self,
        *,
        stream_state: RenderStreamState | None = None,
        reason: str = "new_turn_generation",
    ) -> tuple[TurnRef, GenerationRef, CancellationScope]:
        tref, _ = await self.session_ctx.begin_turn()
        gref, gscope = await self.session_ctx.begin_generation(tref)
        if stream_state is not None and stream_state.active_generation_ref != gref:
            stream_state.switch_generation(gref, reason=reason)
        return tref, gref, gscope

    async def soft_pause(self, *, generation_ref: GenerationRef) -> PauseRef | None:
        pref = await self.session_ctx.soft_pause()
        if pref is not None:
            self.events.emit_server_event(
                generation_ref=generation_ref,
                kind=PlaybackEventKind.PAUSE_REQUESTED,
                metadata={"pause_epoch": pref.pause_epoch},
            )
            ev = self.events.emit_server_event(
                generation_ref=generation_ref,
                kind=PlaybackEventKind.PAUSED,
                metadata={"pause_epoch": pref.pause_epoch},
            )
            if ev is not None:
                self.telemetry.publish_playback_event(ev)
        return pref

    async def resume_pause(self, pause_ref: PauseRef, *, generation_ref: GenerationRef) -> bool:
        ok = await self.session_ctx.resume_pause(pause_ref)
        if ok:
            ev = self.events.emit_server_event(
                generation_ref=generation_ref,
                kind=PlaybackEventKind.RESUMED,
                metadata={"pause_epoch": pause_ref.pause_epoch},
            )
            if ev is not None:
                self.telemetry.publish_playback_event(ev)
        return ok

    async def commit_interrupt(
        self,
        *,
        stream_state: RenderStreamState | None,
        generation_ref: GenerationRef,
        reason: str = "barge_in_commit",
        flush_command_sent: bool = False,
    ) -> bool:
        if flush_command_sent:
            self.events.emit_server_event(
                generation_ref=generation_ref,
                kind=PlaybackEventKind.FLUSH_REQUESTED,
                metadata={"reason": reason},
            )
        changed = await self.session_ctx.commit_interrupt(reason=reason)
        if stream_state is not None:
            stream_state.abort_generation(reason=reason)
        self.events.emit_server_event(
            generation_ref=generation_ref,
            kind=PlaybackEventKind.FLUSHED,
            metadata={"reason": reason, "scope_detail": "SERVER_LOCAL_BUFFERS_PURGED"},
        )
        ev = self.events.emit_server_event(
            generation_ref=generation_ref,
            kind=PlaybackEventKind.CANCELED,
            metadata={"reason": reason},
        )
        if ev is not None:
            self.telemetry.publish_playback_event(ev)
        return changed

    async def close(self, *, reason: str = "normal_close", drain_timeout_sec: float = 0.5) -> CloseSummary:
        if self._close_summary is not None:
            return self._close_summary
        closed_streams = self.registry.close_session(self.session_ctx.identity.session_id)
        cleanup_status = await self.session_ctx.close(reason=reason, drain_timeout_sec=drain_timeout_sec)
        snap = self.session_ctx.snapshot_nowait()
        self._close_summary = CloseSummary(
            session_id=snap.session_id,
            incarnation_id=snap.incarnation_id,
            cleanup_status=cleanup_status,
            quarantined_leases=snap.quarantined_leases,
            closed_streams=closed_streams,
            reason=reason,
        )
        return self._close_summary
