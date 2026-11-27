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

import threading
from typing import Any, Mapping

from backend.audio_frontend.quality_analyzer import AudioQualityMetrics
from backend.core.contracts.common import (
    CONTRACT_SCHEMA_VERSION,
    ErrorInfo,
    EventEnvelope,
    MetricSample,
    MetricStatus,
)
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock
from backend.observability.event_bus import BoundedEventBus
from backend.observability.evidence import EvidenceKind, EvidenceRecorder
from backend.observability.metrics import MetricsRegistry
from backend.observability.projection import Projection

_SAFE_F0_ALLOWLIST = frozenset({
    "stage",
    "status",
    "source",
    "duration_ms",
    "error_code",
    "reason",
    "outcome",
    "sample_rate_hz",
    "output_rate_hz",
    "encoding",
    "valid_sample_count",
    "padding_samples",
    "config_revision",
    "observation_scope",
    "route",
    "queue_depth",
    "block_duration_ms",
    "queue_delay_ms",
    "group_delay_samples",
    "dtmf_detected",
    "dtmf_source",
    "dtmf_deduped",
    "format_epoch",
    "stream_id",
})


class AudioFrontendTelemetry:
    """
    Safe M04 observability bridge for F0-A audio input pipeline.

    - Publishes only allowlisted, redacted metadata through BoundedEventBus & Projection.
    - Never stores raw audio bytes, waveforms, transcripts, DTMF digit values, or PII.
    - Isolates observer/bus/metrics exceptions so telemetry never stalls audio.
    """

    def __init__(
        self,
        *,
        event_bus: BoundedEventBus | None = None,
        metrics: MetricsRegistry | None = None,
        evidence: EvidenceRecorder | None = None,
        clock: Clock | None = None,
        observation_scope: str = "SERVER",
        evidence_kind: EvidenceKind = EvidenceKind.SYNTHETIC_FIXTURE,
    ) -> None:
        self.event_bus = event_bus or BoundedEventBus()
        self.metrics = metrics or MetricsRegistry()
        self.evidence = evidence
        self.clock: Clock = clock or SystemMonotonicClock()
        self.observation_scope = observation_scope
        self.evidence_kind = evidence_kind
        self.projector = Projection(extra_allowlist=_SAFE_F0_ALLOWLIST)
        self._lock = threading.Lock()
        self._seq = -1
        self.observer_error_count = 0
        self.dropped_events_count = 0

    def _next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    def emit_event(
        self,
        *,
        event_type: str,
        session_id: str,
        trace_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Emit a sanitized EventEnvelope to M04 BoundedEventBus; never raises into caller."""
        try:
            raw_meta = dict(metadata or {})
            projected_meta = self.projector.project(raw_meta, extra_allowlist=_SAFE_F0_ALLOWLIST)
            safe_meta = projected_meta if projected_meta is not None else {}

            env = EventEnvelope(
                schema_version=CONTRACT_SCHEMA_VERSION,
                event_type=event_type,
                session_id=session_id,
                trace_id=trace_id,
                turn_id=None,
                generation_id=None,
                sequence=self._next_seq(),
                monotonic_ns=self.clock.monotonic_ns(),
                clock_domain=self.clock.clock_domain,
                producer="f0_a.audio_frontend",
                metadata=safe_meta,
            )
            status = self.event_bus.try_publish(env)
            if status.value != "ACCEPTED":
                with self._lock:
                    self.dropped_events_count += 1
            return self.projector.project(env, extra_allowlist=_SAFE_F0_ALLOWLIST)
        except Exception:
            with self._lock:
                self.observer_error_count += 1
            return None

    def record_frame_processed(
        self,
        *,
        session_id: str,
        trace_id: str | None,
        stream_id: str,
        format_epoch: int,
        input_rate_hz: int,
        encoding: str,
        valid_sample_count: int,
        padding_samples: int,
        config_revision: str,
        route: str,
        processing_ms: float,
        block_duration_ms: float,
        queue_delay_ms: float,
        group_delay_samples: float,
        quality: AudioQualityMetrics | None,
    ) -> dict[str, Any] | None:
        """Record F0-A latency, signal quality metrics, and pipeline stage event safely."""
        try:
            self.metrics.inc("f0.frames_processed", 1.0, observation_scope=self.observation_scope)
            self.metrics.observe(
                "f0.processing_ms",
                processing_ms,
                unit="ms",
                observation_scope=self.observation_scope,
            )
            self.metrics.observe(
                "f0.block_duration_ms",
                block_duration_ms,
                unit="ms",
                observation_scope=self.observation_scope,
            )
            self.metrics.observe(
                "f0.queue_delay_ms",
                queue_delay_ms,
                unit="ms",
                observation_scope=self.observation_scope,
            )
            self.metrics.set_gauge(
                "f0.group_delay_samples",
                group_delay_samples,
                unit="samples",
                observation_scope=self.observation_scope,
            )
            if quality is not None:
                self.metrics.set_gauge(
                    "f0.rms_linear",
                    quality.linear_rms,
                    unit="linear",
                    observation_scope=self.observation_scope,
                )
                self.metrics.set_gauge(
                    "f0.rms_dbfs",
                    quality.rms_dbfs,
                    unit="dBFS",
                    observation_scope=self.observation_scope,
                    status=quality.rms_dbfs_status,
                    reason=quality.rms_dbfs_reason,
                )
                self.metrics.set_gauge(
                    "f0.peak",
                    quality.peak,
                    unit="linear",
                    observation_scope=self.observation_scope,
                )
                self.metrics.inc(
                    "f0.clipped_samples",
                    float(quality.clipped_samples),
                    unit="samples",
                    observation_scope=self.observation_scope,
                    labels={"stage": quality.clip_stage},
                )
        except Exception:
            with self._lock:
                self.observer_error_count += 1

        return self.emit_event(
            event_type="pipeline.stage.f0",
            session_id=session_id,
            trace_id=trace_id,
            metadata={
                "stage": "F0",
                "status": "completed",
                "source": self.evidence_kind.value,
                "duration_ms": round(processing_ms, 4),
                "sample_rate_hz": input_rate_hz,
                "output_rate_hz": 16000,
                "encoding": encoding,
                "valid_sample_count": valid_sample_count,
                "padding_samples": padding_samples,
                "config_revision": config_revision,
                "observation_scope": self.observation_scope,
                "route": route,
                "block_duration_ms": round(block_duration_ms, 4),
                "queue_delay_ms": round(queue_delay_ms, 4),
                "group_delay_samples": round(group_delay_samples, 3),
                "format_epoch": format_epoch,
                "stream_id": stream_id,
            },
        )

    def record_rejection(
        self,
        *,
        session_id: str,
        trace_id: str | None,
        reason: str,
        error_info: ErrorInfo | None = None,
        backpressure: bool = False,
    ) -> dict[str, Any] | None:
        try:
            metric_name = "f0.backpressure_rejects" if backpressure else "f0.validation_rejects"
            self.metrics.inc(metric_name, 1.0, observation_scope=self.observation_scope)
        except Exception:
            with self._lock:
                self.observer_error_count += 1

        event_type = "buffer.backpressure" if backpressure else "result.rejected"
        meta: dict[str, Any] = {
            "reason": reason,
            "observation_scope": self.observation_scope,
        }
        if error_info is not None:
            meta["error_code"] = error_info.code
        return self.emit_event(
            event_type=event_type,
            session_id=session_id,
            trace_id=trace_id,
            metadata=meta,
        )

    def record_dtmf_observed(
        self,
        *,
        session_id: str,
        trace_id: str | None,
        source: str,
        deduped: bool,
    ) -> dict[str, Any] | None:
        """Record safe DTMF metadata ONLY (never emits raw digit character)."""
        try:
            self.metrics.inc("f0.dtmf_events", 1.0, observation_scope=self.observation_scope)
        except Exception:
            with self._lock:
                self.observer_error_count += 1
        return self.emit_event(
            event_type="pipeline.stage.f0",
            session_id=session_id,
            trace_id=trace_id,
            metadata={
                "stage": "F0",
                "status": "dtmf_observed",
                "dtmf_detected": True,
                "dtmf_source": source,
                "dtmf_deduped": deduped,
                "observation_scope": self.observation_scope,
            },
        )

    def record_evidence(
        self,
        *,
        claim: str,
        subject: str,
        trace_id: str | None = None,
        metrics: tuple[MetricSample, ...] = (),
        details: Mapping[str, Any] | None = None,
    ) -> None:
        if self.evidence is None:
            return
        try:
            self.evidence.record(
                kind=self.evidence_kind,
                claim=claim,
                subject=subject,
                recorded_monotonic_ns=self.clock.monotonic_ns(),
                clock_domain=self.clock.clock_domain,
                observation_scope=self.observation_scope,
                trace_id=trace_id,
                metrics=metrics,
                details=details,
            )
        except Exception:
            with self._lock:
                self.observer_error_count += 1
