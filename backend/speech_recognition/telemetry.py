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

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, EventEnvelope, MetricSample, MetricStatus
from backend.observability.event_bus import BoundedEventBus
from backend.observability.metrics import MetricsRegistry
from backend.observability.projection import Projection
from backend.speech_recognition.errors import ASRDeliveryStatus, ASRDispatchStatus

ASR_TELEMETRY_ALLOWLIST: frozenset[str] = frozenset({
    "utterance_id",
    "revision",
    "model_revision",
    "config_revision",
    "lexicon_revision",
    "dispatch_status",
    "delivery_status",
    "admission_status",
    "priority",
    "lease_state",
    "route_mode",
    "segment_count",
})


def compute_clock_safe_delta_ms(
    start_ns: int | None,
    start_domain: str | None,
    end_ns: int | None,
    end_domain: str | None,
    *,
    metric_name: str,
    observation_scope: str = "SERVER",
    source_ref: str = "backend.speech_recognition.telemetry",
) -> MetricSample:
    """
    Compute elapsed milliseconds only when both timestamps share the same monotonic clock domain.

    Cross-domain deltas return `value=None` with `MetricStatus.UNKNOWN` instead of
    fabricating a bogus latency number.
    """
    if start_ns is None or end_ns is None or not start_domain or not end_domain:
        return MetricSample(
            name=metric_name,
            value=None,
            unit="ms",
            observation_scope=observation_scope,
            status=MetricStatus.UNAVAILABLE,
            reason="missing_timestamp",
            source_ref=source_ref,
        )
    if start_domain != end_domain:
        return MetricSample(
            name=metric_name,
            value=None,
            unit="ms",
            observation_scope=observation_scope,
            status=MetricStatus.UNKNOWN,
            reason=f"clock_domain_mismatch:{start_domain}!={end_domain}",
            source_ref=source_ref,
        )
    if end_ns < start_ns:
        return MetricSample(
            name=metric_name,
            value=None,
            unit="ms",
            observation_scope=observation_scope,
            status=MetricStatus.UNKNOWN,
            reason="negative_monotonic_delta",
            source_ref=source_ref,
        )
    return MetricSample(
        name=metric_name,
        value=(end_ns - start_ns) / 1_000_000.0,
        unit="ms",
        observation_scope=observation_scope,
        status=MetricStatus.MEASURED,
        source_ref=source_ref,
    )


class ASRTelemetryBridge:
    """
    Side-channel M04 event and metric emitter for F2-A.

    - Strictly strips/redacts transcripts, raw audio, PII, and secret paths.
    - Isolates bus overflow or projection failures so ASR lifecycle never breaks.
    """

    def __init__(
        self,
        *,
        event_bus: BoundedEventBus | None = None,
        metrics: MetricsRegistry | None = None,
        projection: Projection | None = None,
    ) -> None:
        self.event_bus = event_bus or BoundedEventBus()
        self.metrics = metrics or MetricsRegistry()
        self.projection = projection or Projection(extra_allowlist=ASR_TELEMETRY_ALLOWLIST)
        self.isolated_errors: int = 0
        self.dropped_events: int = 0

    def emit_event(
        self,
        *,
        event_type: str,
        session_id: str,
        turn_id: int | None,
        sequence: int,
        monotonic_ns: int,
        clock_domain: str,
        trace_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> bool:
        try:
            raw_meta = dict(metadata or {})
            raw_env = EventEnvelope(
                schema_version=CONTRACT_SCHEMA_VERSION,
                event_type=event_type,
                session_id=session_id,
                trace_id=trace_id,
                turn_id=turn_id,
                generation_id=None,
                sequence=sequence,
                monotonic_ns=monotonic_ns,
                clock_domain=clock_domain,
                producer="backend.speech_recognition",
                metadata=raw_meta,
            )
            projected = self.projection.project(raw_env)
            if projected is None:
                self.dropped_events += 1
                return False
            safe_env = EventEnvelope(
                schema_version=CONTRACT_SCHEMA_VERSION,
                event_type=str(projected.get("event_type", event_type)),
                session_id=str(projected.get("session_id", session_id)),
                trace_id=projected.get("trace_id"),
                turn_id=projected.get("turn_id"),
                generation_id=projected.get("generation_id"),
                sequence=int(projected.get("sequence", sequence)),
                monotonic_ns=int(projected.get("monotonic_ns", monotonic_ns)),
                clock_domain=str(projected.get("clock_domain", clock_domain)),
                producer=str(projected.get("producer", "backend.speech_recognition")),
                metadata=projected.get("metadata", {}),
            )
            status = self.event_bus.try_publish(safe_env)
            if str(status.value) != "ACCEPTED":
                self.dropped_events += 1
                return False
            return True
        except Exception:
            self.isolated_errors += 1
            return False

    def inc_counter(self, name: str, amount: float = 1.0) -> None:
        try:
            # Never pass session_id as high-cardinality metric label
            self.metrics.inc(
                name,
                amount,
                unit="count",
                observation_scope="SERVER",
                labels=None,
                source_ref="backend.speech_recognition",
            )
        except Exception:
            self.isolated_errors += 1

    def observe_latency(self, name: str, sample: MetricSample) -> None:
        try:
            self.metrics.observe_histogram(
                name,
                sample.value,
                unit=sample.unit,
                observation_scope=sample.observation_scope,
                labels=None,
                reason=sample.reason,
            )
        except Exception:
            self.isolated_errors += 1

    def record_timings(
        self,
        *,
        admitted_ns: int | None,
        admitted_domain: str | None,
        started_ns: int | None,
        started_domain: str | None,
        completed_ns: int | None,
        completed_domain: str | None,
        built_ns: int | None,
        built_domain: str | None,
        delivered_ns: int | None,
        delivered_domain: str | None,
        audio_duration_sec: float | None,
        succeeded: bool,
    ) -> tuple[MetricSample, ...]:
        samples: list[MetricSample] = []

        q_wait = compute_clock_safe_delta_ms(
            admitted_ns, admitted_domain, started_ns, started_domain, metric_name="f2.queue_wait_ms"
        )
        inf_ms = compute_clock_safe_delta_ms(
            started_ns, started_domain, completed_ns, completed_domain, metric_name="f2.inference_ms"
        )
        build_ms = compute_clock_safe_delta_ms(
            completed_ns, completed_domain, built_ns, built_domain, metric_name="f2.result_build_ms"
        )
        deliv_ms = compute_clock_safe_delta_ms(
            built_ns, built_domain, delivered_ns, delivered_domain, metric_name="f2.delivery_wait_ms"
        )
        samples.extend([q_wait, inf_ms, build_ms, deliv_ms])
        self.observe_latency("f2.queue_wait_ms", q_wait)
        self.observe_latency("f2.inference_ms", inf_ms)
        self.observe_latency("f2.result_build_ms", build_ms)
        if delivered_ns is not None:
            self.observe_latency("f2.delivery_wait_ms", deliv_ms)

        if succeeded:
            final_lat = compute_clock_safe_delta_ms(
                admitted_ns,
                admitted_domain,
                delivered_ns if delivered_ns is not None else built_ns,
                delivered_domain if delivered_ns is not None else built_domain,
                metric_name="f2.final_latency_ms",
            )
            samples.append(final_lat)
            self.observe_latency("f2.final_latency_ms", final_lat)

        if inf_ms.status == MetricStatus.MEASURED and inf_ms.value is not None and audio_duration_sec and audio_duration_sec > 0.0:
            rtf_val = (inf_ms.value / 1000.0) / audio_duration_sec
            rtf_sample = MetricSample(
                name="f2.rtf",
                value=rtf_val,
                unit="ratio",
                observation_scope="SERVER",
                status=MetricStatus.MEASURED,
                source_ref="backend.speech_recognition.telemetry",
            )
        else:
            rtf_sample = MetricSample(
                name="f2.rtf",
                value=None,
                unit="ratio",
                observation_scope="SERVER",
                status=MetricStatus.UNAVAILABLE,
                reason="missing_inference_or_duration",
                source_ref="backend.speech_recognition.telemetry",
            )
        samples.append(rtf_sample)
        return tuple(samples)

    def record_outcome_counters(
        self,
        *,
        dispatch_status: ASRDispatchStatus,
        delivery_status: ASRDeliveryStatus,
        is_duplicate: bool = False,
        is_no_speech: bool = False,
        is_error: bool = False,
    ) -> None:
        if is_duplicate:
            self.inc_counter("f2.duplicate_utterance_total")
        if delivery_status == ASRDeliveryStatus.FENCED_STALE:
            self.inc_counter("f2.stale_result_total")
        if is_no_speech:
            self.inc_counter("f2.no_speech_total")
        if is_error or dispatch_status == ASRDispatchStatus.UNKNOWN:
            self.inc_counter("f2.error_total")
