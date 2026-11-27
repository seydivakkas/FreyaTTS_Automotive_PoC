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
    EventEnvelope,
    MetricSample,
    MetricStatus,
    StreamRef,
    TurnRef,
)
from backend.core.contracts.speech import SpeechEvent, SpeechEventKind
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock
from backend.observability.event_bus import BoundedEventBus
from backend.observability.event_catalog import EventPriority
from backend.observability.projection import Projection
from backend.voice_activity.deadlines import compute_same_domain_duration_ms

F1_ALLOWLISTED_META_KEYS: frozenset[str] = frozenset({
    "reason",
    "status",
    "outcome",
    "stage",
    "source",
    "duration_ms",
    "sample_offset",
    "sample_count",
    "valid_samples",
    "window_index",
    "utterance_id",
    "actual_pre_roll_samples",
    "actual_post_roll_samples",
    "gap_samples",
    "model_revision",
    "config_revision",
    "route_mode",
    "observation_scope",
    "error_code",
})


class F1Telemetry:
    """
    M04-backed safe telemetry & SpeechEvent emitter for F1-A.
    - Sanitizes all metadata through M04 Projection (redacting/dropping PII, raw PCM, transcripts).
    - Isolates bus overflow and subscriber failures so acoustic control is never blocked or altered.
    """

    def __init__(
        self,
        stream_ref: StreamRef,
        *,
        trace_id: str | None = None,
        clock: Clock | None = None,
        bus: BoundedEventBus | None = None,
        projection: Projection | None = None,
        producer: str = "f1.voice_activity",
    ) -> None:
        self._stream_ref = stream_ref
        self._trace_id = trace_id
        self._clock: Clock = clock or SystemMonotonicClock()
        self._bus = bus
        self._projection = projection or Projection(extra_allowlist=F1_ALLOWLISTED_META_KEYS)
        self._producer = producer
        self._seq = -1
        self._events: list[EventEnvelope] = []
        self._speech_events: list[SpeechEvent] = []
        self._metrics: list[MetricSample] = []

    @property
    def events(self) -> tuple[EventEnvelope, ...]:
        return tuple(self._events)

    @property
    def speech_events(self) -> tuple[SpeechEvent, ...]:
        return tuple(self._speech_events)

    @property
    def metrics(self) -> tuple[MetricSample, ...]:
        return tuple(self._metrics)

    def update_stream_ref(self, stream_ref: StreamRef) -> None:
        self._stream_ref = stream_ref

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _safe_metadata(self, extras: Mapping[str, Any] | None) -> dict[str, Any]:
        if not extras:
            return {}
        projected = self._projection.project(dict(extras), extra_allowlist=F1_ALLOWLISTED_META_KEYS)
        if projected is None:
            return {"projection_dropped": True}
        return projected

    def emit_event(
        self,
        event_type: str,
        *,
        turn_ref: TurnRef | None = None,
        extras: Mapping[str, Any] | None = None,
        priority: EventPriority = EventPriority.NORMAL,
    ) -> EventEnvelope:
        safe_meta = self._safe_metadata(extras)
        env = EventEnvelope(
            schema_version=CONTRACT_SCHEMA_VERSION,
            event_type=event_type,
            session_id=self._stream_ref.session_id,
            trace_id=self._trace_id,
            turn_id=turn_ref.turn_id if turn_ref is not None else None,
            generation_id=None,
            sequence=self._next_seq(),
            monotonic_ns=self._clock.monotonic_ns(),
            clock_domain=self._clock.clock_domain,
            producer=self._producer,
            metadata=safe_meta,
        )
        self._events.append(env)
        if self._bus is not None:
            try:
                self._bus.try_publish(env, priority=priority)
            except Exception:
                # Telemetry subscriber/bus failure must never alter acoustic segmentation.
                pass
        return env

    def emit_speech_event(
        self,
        kind: SpeechEventKind,
        *,
        sample_offset: int,
        reason: str,
        vad_score: float | None = None,
        turn_ref: TurnRef | None = None,
        extras: Mapping[str, Any] | None = None,
    ) -> SpeechEvent:
        env = self.emit_event(
            f"speech.{kind.value.lower()}",
            turn_ref=turn_ref,
            extras=extras,
            priority=EventPriority.HIGH,
        )
        se = SpeechEvent(
            envelope=env,
            kind=kind,
            stream_ref=self._stream_ref,
            sample_offset=sample_offset,
            reason=reason,
            vad_score=vad_score,
            target_generation=None,
        )
        self._speech_events.append(se)
        return se

    def record_metric(self, sample: MetricSample) -> MetricSample:
        self._metrics.append(sample)
        return sample

    def record_vad_inference_duration(
        self,
        *,
        start_ns: int | None,
        start_domain: str | None,
        end_ns: int | None,
        end_domain: str | None,
    ) -> MetricSample:
        sample = compute_same_domain_duration_ms(
            start_ns=start_ns,
            start_clock_domain=start_domain,
            end_ns=end_ns,
            end_clock_domain=end_domain,
            metric_name="f1.vad_inference_ms",
            observation_scope="SERVER",
        )
        return self.record_metric(sample)

    def record_unavailable_metric(self, name: str, reason: str, *, unit: str = "ms") -> MetricSample:
        sample = MetricSample(
            name=name,
            value=None,
            unit=unit,
            observation_scope="SERVER",
            status=MetricStatus.UNAVAILABLE,
            reason=reason,
        )
        return self.record_metric(sample)
