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

from typing import Any, Mapping

from backend.core.contracts.common import (
    CONTRACT_SCHEMA_VERSION,
    ErrorInfo,
    EventEnvelope,
    GenerationRef,
)
from backend.core.contracts.playback import (
    ObservationScope,
    PlaybackEvent,
    PlaybackEventKind,
)
from backend.core.runtime.deadlines import Clock

_TERMINAL_KINDS = frozenset({
    PlaybackEventKind.COMPLETED,
    PlaybackEventKind.CANCELED,
    PlaybackEventKind.FAILED,
    PlaybackEventKind.DRAINED,
})


class PlaybackEventEmitter:
    """
    Constructs truthful M01 PlaybackEvent records without reinterpreting local
    server queue/writer actions as remote CLIENT, PBX, or audible ENDPOINT proof.

    Deduplicates terminal events per `(generation_ref, kind)` so duplicate callbacks
    cannot emit duplicate terminal events.
    """

    def __init__(self, *, clock: Clock, producer: str = "backend.audio_rendering") -> None:
        self._clock = clock
        self._producer = producer
        self._seq = -1
        self._events: list[PlaybackEvent] = []
        self._emitted_terminal_keys: set[tuple[str, int, int, PlaybackEventKind]] = set()
        self.duplicate_terminal_suppressed = 0

    @property
    def events(self) -> tuple[PlaybackEvent, ...]:
        return tuple(self._events)

    def emit_server_event(
        self,
        *,
        generation_ref: GenerationRef,
        kind: PlaybackEventKind,
        trace_id: str | None = None,
        queue_depth: int | None = None,
        sample_progress: int | None = None,
        error: ErrorInfo | None = None,
        metadata: Mapping[str, Any] | None = None,
        observation_scope: ObservationScope = ObservationScope.SERVER,
    ) -> PlaybackEvent | None:
        """
        Emit a server-observed PlaybackEvent.
        Server emitters are strictly prohibited from claiming ENDPOINT audible proof.
        """
        if observation_scope not in {ObservationScope.SERVER, ObservationScope.UNKNOWN}:
            raise ValueError(
                f"Server emitter cannot fabricate {observation_scope.value} scope; "
                "use emit_validated_external_event for verified CLIENT/PBX fixtures"
            )
        return self._emit_internal(
            generation_ref=generation_ref,
            kind=kind,
            observation_scope=observation_scope,
            trace_id=trace_id,
            queue_depth=queue_depth,
            sample_progress=sample_progress,
            error=error,
            metadata=metadata,
        )

    def emit_validated_external_event(
        self,
        *,
        generation_ref: GenerationRef,
        kind: PlaybackEventKind,
        observation_scope: ObservationScope,
        provider_source: str,
        trace_id: str | None = None,
        queue_depth: int | None = None,
        sample_progress: int | None = None,
        error: ErrorInfo | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> PlaybackEvent | None:
        """
        Emit CLIENT or PBX event only from a validated provider/fixture source.
        ENDPOINT audible events remain disallowed in F6-A (deferred to T5 real endpoint).
        """
        if observation_scope == ObservationScope.ENDPOINT:
            raise ValueError("ObservationScope.ENDPOINT is deferred to T5 real endpoint measurement")
        if not isinstance(provider_source, str) or not provider_source.strip():
            raise ValueError("provider_source is required for external scope events")
        meta = dict(metadata or {})
        meta["provider_source"] = provider_source
        return self._emit_internal(
            generation_ref=generation_ref,
            kind=kind,
            observation_scope=observation_scope,
            trace_id=trace_id,
            queue_depth=queue_depth,
            sample_progress=sample_progress,
            error=error,
            metadata=meta,
        )

    def _emit_internal(
        self,
        *,
        generation_ref: GenerationRef,
        kind: PlaybackEventKind,
        observation_scope: ObservationScope,
        trace_id: str | None,
        queue_depth: int | None,
        sample_progress: int | None,
        error: ErrorInfo | None,
        metadata: Mapping[str, Any] | None,
    ) -> PlaybackEvent | None:
        if kind in _TERMINAL_KINDS:
            tkey = (
                generation_ref.session_id,
                generation_ref.turn_id,
                generation_ref.generation_id,
                kind,
            )
            if tkey in self._emitted_terminal_keys:
                self.duplicate_terminal_suppressed += 1
                return None
            self._emitted_terminal_keys.add(tkey)

        self._seq += 1
        meta = dict(metadata or {})
        meta["observation_scope"] = observation_scope.value
        if queue_depth is not None:
            meta["queue_depth"] = queue_depth
        if sample_progress is not None:
            meta["sample_progress"] = sample_progress

        env = EventEnvelope(
            schema_version=CONTRACT_SCHEMA_VERSION,
            event_type=f"playback.{kind.value.lower()}",
            session_id=generation_ref.session_id,
            trace_id=trace_id,
            turn_id=generation_ref.turn_id,
            generation_id=generation_ref.generation_id,
            sequence=self._seq,
            monotonic_ns=self._clock.monotonic_ns(),
            clock_domain=self._clock.clock_domain,
            producer=self._producer,
            metadata=meta,
        )
        ev = PlaybackEvent(
            envelope=env,
            kind=kind,
            generation_ref=generation_ref,
            observation_scope=observation_scope,
            queue_depth=queue_depth,
            sample_progress=sample_progress,
            error=error,
        )
        self._events.append(ev)
        return ev
