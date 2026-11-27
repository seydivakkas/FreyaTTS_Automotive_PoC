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

from backend.core.contracts.common import (
    CONTRACT_SCHEMA_VERSION,
    EventEnvelope,
    GenerationRef,
    MetricSample,
    MetricStatus,
)
from backend.core.contracts.synthesis import CacheStatus
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock
from backend.core.runtime.result_admission import AdmissionStatus
from backend.observability.event_bus import BoundedEventBus
from backend.observability.metrics import MetricsRegistry
from backend.observability.projection import Projection
from backend.observability.trace_store import TraceStore

F5_ALLOWLISTED_META_KEYS: frozenset[str] = frozenset({
    "plan_id",
    "plan_revision",
    "chunk_id",
    "chunk_index",
    "sample_count",
    "actual_duration_ms",
    "cache_status",
    "quality_status",
    "solver",
    "ode_steps",
    "model_revision",
    "voice_profile",
    "observation_scope",
    "status",
    "reason",
    "code",
    "category",
})


class SynthesisTelemetry:
    """
    Non-blocking M04 observability bridge for F5-A.

    Guarantees:
    - Same-clock-domain monotonic durations only (never subtracts cross-domain clocks).
    - Preserves null vs zero (MetricStatus.UNAVAILABLE when denominator/sample absent).
    - Strict Projection allowlist + sentinel scrubbing; zero raw text/latents/audio/PII.
    - Observer errors or bus overflow never block audio, grant delivery, or release leases.
    """

    def __init__(
        self,
        *,
        clock: Clock | None = None,
        metrics: MetricsRegistry | None = None,
        event_bus: BoundedEventBus | None = None,
        trace_store: TraceStore | None = None,
        projection: Projection | None = None,
    ) -> None:
        self.clock: Clock = clock or SystemMonotonicClock()
        self.metrics = metrics or MetricsRegistry()
        self.event_bus = event_bus
        self.trace_store = trace_store
        self.projection = projection or Projection(extra_allowlist=F5_ALLOWLISTED_META_KEYS)
        self._seq = -1
        self._lock = threading.Lock()
        self._observation_loss_count = 0

    @property
    def observation_loss_count(self) -> int:
        with self._lock:
            return self._observation_loss_count

    def _record_observation_loss(self) -> None:
        with self._lock:
            self._observation_loss_count += 1
        try:
            self.metrics.inc("f5.observation_loss_count", 1.0, unit="count", observation_scope="SERVER")
        except Exception:
            pass

    def elapsed_ms(self, start_ns: int | None, end_ns: int | None, *, clock_domain: str | None = None) -> float | None:
        if start_ns is None or end_ns is None:
            return None
        dom = clock_domain or self.clock.clock_domain
        if dom != self.clock.clock_domain:
            self._record_observation_loss()
            return None
        if end_ns < start_ns:
            self._record_observation_loss()
            return None
        return (end_ns - start_ns) / 1_000_000.0

    def observe_duration(
        self,
        name: str,
        duration_ms: float | None,
        *,
        observation_scope: str = "SERVER",
        reason: str | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> MetricSample:
        try:
            if duration_ms is None:
                self.metrics.observe(name, None, unit="ms", observation_scope=observation_scope, reason=reason or "unavailable", labels=labels)
                return MetricSample(
                    name=name,
                    value=None,
                    unit="ms",
                    observation_scope=observation_scope,
                    status=MetricStatus.UNAVAILABLE,
                    reason=reason or "unavailable",
                )
            self.metrics.observe(name, duration_ms, unit="ms", observation_scope=observation_scope, labels=labels)
            return MetricSample(
                name=name,
                value=float(duration_ms),
                unit="ms",
                observation_scope=observation_scope,
                status=MetricStatus.MEASURED,
            )
        except Exception:
            self._record_observation_loss()
            return MetricSample(
                name=name,
                value=None,
                unit="ms",
                observation_scope=observation_scope,
                status=MetricStatus.UNAVAILABLE,
                reason="telemetry_error",
            )

    def compute_rtf(
        self,
        *,
        inference_ms: float | None,
        audio_duration_ms: float | None,
        observation_scope: str = "SERVER",
        labels: Mapping[str, str] | None = None,
    ) -> MetricSample:
        """Compute RTF using actual decoded waveform duration as denominator (null when unavailable)."""
        if inference_ms is None or audio_duration_ms is None or audio_duration_ms <= 0.0:
            try:
                self.metrics.set_gauge(
                    "f5.rtf",
                    None,
                    unit="ratio",
                    observation_scope=observation_scope,
                    status=MetricStatus.UNAVAILABLE,
                    reason="missing_denominator_or_inference",
                    labels=labels,
                )
            except Exception:
                self._record_observation_loss()
            return MetricSample(
                name="f5.rtf",
                value=None,
                unit="ratio",
                observation_scope=observation_scope,
                status=MetricStatus.UNAVAILABLE,
                reason="missing_denominator_or_inference",
            )
        rtf_val = inference_ms / audio_duration_ms
        try:
            self.metrics.observe("f5.rtf", rtf_val, unit="ratio", observation_scope=observation_scope, labels=labels)
        except Exception:
            self._record_observation_loss()
        return MetricSample(
            name="f5.rtf",
            value=rtf_val,
            unit="ratio",
            observation_scope=observation_scope,
            status=MetricStatus.MEASURED,
        )

    def inc_counter(self, name: str, amount: float = 1.0, *, labels: Mapping[str, str] | None = None) -> None:
        try:
            self.metrics.inc(name, amount, unit="count", observation_scope="SERVER", labels=labels)
        except Exception:
            self._record_observation_loss()

    def emit_safe_event(
        self,
        *,
        event_type: str,
        generation_ref: GenerationRef,
        trace_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Project and publish a sanitized M04 EventEnvelope without ever raising or leaking PII."""
        try:
            with self._lock:
                self._seq += 1
                seq = self._seq
            raw_meta = dict(metadata or {})
            env = EventEnvelope(
                schema_version=CONTRACT_SCHEMA_VERSION,
                event_type=event_type,
                session_id=generation_ref.session_id,
                trace_id=trace_id,
                turn_id=generation_ref.turn_id,
                generation_id=generation_ref.generation_id,
                sequence=seq,
                monotonic_ns=self.clock.monotonic_ns(),
                clock_domain=self.clock.clock_domain,
                producer="f5.neural_synthesis",
                metadata=raw_meta,
            )
            projected = self.projection.project(env, extra_allowlist=F5_ALLOWLISTED_META_KEYS)
            if projected is None:
                self._record_observation_loss()
                return None

            safe_meta = projected.get("metadata", {})
            safe_env = EventEnvelope(
                schema_version=CONTRACT_SCHEMA_VERSION,
                event_type=event_type,
                session_id=generation_ref.session_id,
                trace_id=trace_id,
                turn_id=generation_ref.turn_id,
                generation_id=generation_ref.generation_id,
                sequence=seq,
                monotonic_ns=env.monotonic_ns,
                clock_domain=env.clock_domain,
                producer="f5.neural_synthesis",
                metadata=safe_meta,
            )
            if self.event_bus is not None:
                status = self.event_bus.try_publish(safe_env)
                if status != AdmissionStatus.ACCEPTED:
                    self._record_observation_loss()
                else:
                    # Dispatch callbacks safely inside isolation wrapper
                    try:
                        self.event_bus.dispatch_all()
                    except Exception:
                        self._record_observation_loss()
            return projected
        except Exception:
            self._record_observation_loss()
            return None

    def record_chunk_metrics(
        self,
        *,
        generation_ref: GenerationRef,
        plan_id: str,
        plan_revision: int,
        chunk_id: str,
        chunk_index: int,
        cache_status: CacheStatus,
        sample_count: int | None,
        actual_duration_ms: float | None,
        queue_wait_ms: float | None,
        encoder_ms: float | None,
        duration_guard_ms: float | None,
        ode_ms: float | None,
        decoder_ms: float | None,
        inference_ms: float | None,
        dispatch_wait_ms: float | None,
        ttfa_ms: float | None,
        solver: str,
        ode_steps: int,
        voice_profile: str,
        model_revision: str,
        trace_id: str | None = None,
    ) -> tuple[MetricSample, ...]:
        labels = {
            "solver": solver,
            "ode_steps": str(ode_steps),
            "voice_profile": voice_profile,
            "cache_status": cache_status.value,
        }
        samples: list[MetricSample] = [
            self.observe_duration("f5.queue_wait_ms", queue_wait_ms, labels=labels),
            self.observe_duration("f5.encoder_ms", encoder_ms, labels=labels),
            self.observe_duration("f5.duration_guard_ms", duration_guard_ms, labels=labels),
            self.observe_duration("f5.ode_ms", ode_ms, labels=labels),
            self.observe_duration("f5.decoder_ms", decoder_ms, labels=labels),
            self.observe_duration("f5.inference_ms", inference_ms, labels=labels),
            self.observe_duration("f5.dispatch_wait_ms", dispatch_wait_ms, labels=labels),
            self.observe_duration(
                "f5.ttfa_ms",
                ttfa_ms,
                observation_scope="SERVER_RAW_READY",
                reason="not_first_chunk" if chunk_index > 0 else None,
                labels=labels,
            ),
            self.compute_rtf(
                inference_ms=inference_ms,
                audio_duration_ms=actual_duration_ms,
                labels=labels,
            ),
        ]
        if sample_count is not None:
            samples.append(
                MetricSample(
                    name="f5.sample_count",
                    value=float(sample_count),
                    unit="samples",
                    observation_scope="SERVER",
                    status=MetricStatus.MEASURED,
                )
            )
        self.emit_safe_event(
            event_type="tts.chunk",
            generation_ref=generation_ref,
            trace_id=trace_id,
            metadata={
                "plan_id": plan_id,
                "plan_revision": plan_revision,
                "chunk_id": chunk_id,
                "chunk_index": chunk_index,
                "cache_status": cache_status.value,
                "model_revision": model_revision,
                "voice_profile": voice_profile,
                "solver": solver,
                "ode_steps": ode_steps,
                "observation_scope": "SERVER_RAW_READY",
            },
        )
        return tuple(samples)


__all__ = [
    "F5_ALLOWLISTED_META_KEYS",
    "SynthesisTelemetry",
]
