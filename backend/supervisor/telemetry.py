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
from typing import Any, Mapping

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, EventEnvelope, MetricStatus
from backend.core.contracts.validation import require_safe_id
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock
from backend.observability.event_bus import BoundedEventBus
from backend.observability.metrics import MetricsRegistry
from backend.observability.projection import Projection, contains_sentinel, redact_sentinels
from backend.observability.trace_store import TraceStore

_ALLOWED_METRIC_LABELS: frozenset[str] = frozenset({
    "mode",
    "intent_category",
    "outcome",
    "provider_mode",
    "reason_code",
    "source_class",
    "state_revision",
    "channel",
})


@dataclass(frozen=True, slots=True)
class DialogueSpanTiming:
    """Monotonic clock-domain-verified latency spans for F3-A."""

    clock_domain: str
    routing_ms: float | None = None
    llm_ms: float | None = None
    tool_ms: float | None = None
    response_ms: float | None = None

    @classmethod
    def compute_ms(
        cls,
        *,
        start_ns: int | None,
        start_domain: str | None,
        end_ns: int | None,
        end_domain: str | None,
    ) -> float | None:
        if start_ns is None or end_ns is None or not start_domain or not end_domain:
            return None
        if start_domain != end_domain or end_ns < start_ns:
            return None
        return (end_ns - start_ns) / 1_000_000.0


class DialogueTelemetryBridge:
    """
    Safe, loss-isolated M04 observability adapter for F3-A.

    Never leaks PII/secrets/transcripts, never writes to M07 SecurityAuditLog,
    records missing spans as None (UNAVAILABLE) instead of 0.0, and isolates
    subscriber failures so control/audit paths remain completely unaffected.
    """

    def __init__(
        self,
        *,
        bus: BoundedEventBus | None = None,
        metrics: MetricsRegistry | None = None,
        traces: TraceStore | None = None,
        clock: Clock | None = None,
        observation_scope: str = "LOCAL_RUNTIME_MEASURED",
    ) -> None:
        self.bus = bus or BoundedEventBus()
        self.metrics = metrics or MetricsRegistry()
        self.traces = traces or TraceStore()
        self.clock: Clock = clock or SystemMonotonicClock()
        self.observation_scope = observation_scope
        self._projection = Projection()
        self.observation_loss_count = 0
        self._seq = 0

    def _sanitize_labels(self, labels: Mapping[str, Any] | None) -> dict[str, str]:
        safe: dict[str, str] = {}
        if not labels:
            return safe
        for k, v in labels.items():
            ks = str(k)
            if ks not in _ALLOWED_METRIC_LABELS:
                continue
            vs = str(v)
            if contains_sentinel(vs):
                redacted, _ = redact_sentinels(vs)
                safe[ks] = redacted
            else:
                safe[ks] = vs[:64]
        return safe

    def emit_event(
        self,
        *,
        event_type: str,
        session_id: str,
        trace_id: str | None,
        turn_id: int | None,
        metadata: Mapping[str, Any] | None = None,
    ) -> bool:
        """Project through M04 allowlist+redactor and publish non-blocking; returns False on loss."""
        require_safe_id(session_id, "session_id")
        self._seq += 1
        raw_meta = dict(metadata or {})
        clean_meta: dict[str, Any] = {}
        for k, v in raw_meta.items():
            if isinstance(v, str):
                red, _ = redact_sentinels(v)
                clean_meta[str(k)] = red
            else:
                clean_meta[str(k)] = v

        env = EventEnvelope(
            schema_version=CONTRACT_SCHEMA_VERSION,
            event_type=event_type,
            session_id=session_id,
            trace_id=trace_id,
            turn_id=turn_id,
            generation_id=None,
            sequence=self._seq,
            monotonic_ns=self.clock.monotonic_ns(),
            clock_domain=self.clock.clock_domain,
            producer="f3.dialogue.telemetry",
            metadata=clean_meta,
        )
        projected = self._projection.project(env)
        if projected is None:
            self.observation_loss_count += 1
            return False
        safe_env = EventEnvelope(
            schema_version=env.schema_version,
            event_type=env.event_type,
            session_id=env.session_id,
            trace_id=env.trace_id,
            turn_id=env.turn_id,
            generation_id=env.generation_id,
            sequence=env.sequence,
            monotonic_ns=env.monotonic_ns,
            clock_domain=env.clock_domain,
            producer=env.producer,
            metadata=projected.get("metadata", {}),
        )
        try:
            status = self.bus.try_publish(safe_env)
            if hasattr(status, "name") and status.name != "ACCEPTED":
                self.observation_loss_count += 1
                return False
            return True
        except Exception:
            self.observation_loss_count += 1
            return False

    def record_turn_metrics(
        self,
        *,
        timing: DialogueSpanTiming,
        labels: Mapping[str, Any] | None = None,
        outcome: str = "OK",
    ) -> None:
        safe_labels = self._sanitize_labels({**(labels or {}), "outcome": outcome})
        try:
            self.metrics.increment(
                "f3.turns.total",
                1.0,
                unit="count",
                observation_scope=self.observation_scope,
                labels=safe_labels,
            )
            for metric_name, val in (
                ("f3.routing_ms", timing.routing_ms),
                ("f3.llm_ms", timing.llm_ms),
                ("f3.tool_ms", timing.tool_ms),
                ("f3.response_ms", timing.response_ms),
            ):
                self.metrics.observe(
                    metric_name,
                    val,
                    unit="ms",
                    observation_scope=self.observation_scope,
                    labels=safe_labels,
                    reason="not_executed" if val is None else None,
                )
        except Exception:
            self.observation_loss_count += 1

    def get_metric_status(self, metric_name: str, labels: Mapping[str, Any] | None = None) -> MetricStatus:
        safe_labels = self._sanitize_labels(labels)
        summary = self.metrics.get_histogram_summary(
            metric_name,
            observation_scope=self.observation_scope,
            labels=safe_labels,
        )
        if summary is None:
            return MetricStatus.UNAVAILABLE
        return summary.status
