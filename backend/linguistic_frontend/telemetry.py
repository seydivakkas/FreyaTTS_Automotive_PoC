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
from typing import Any

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, EventEnvelope, MetricSample, MetricStatus
from backend.core.runtime.deadlines import Clock, SystemMonotonicClock
from backend.observability.event_bus import BoundedEventBus
from backend.observability.metrics import MetricsRegistry
from backend.observability.projection import Projection


@dataclass(frozen=True, slots=True)
class F4TelemetrySnapshot:
    observer_errors: int
    dropped_projections: int
    bus_dropped_events: int


class LinguisticTelemetry:
    """
    Safe M04 telemetry wrapper for F4-A.

    Emits only low-cardinality scalar metadata and never logs raw/normalized speech text,
    customer phone/plate/VIN values, or prompts. Observer failures never fail or grant delivery.
    """

    def __init__(
        self,
        *,
        bus: BoundedEventBus | None = None,
        metrics: MetricsRegistry | None = None,
        projection: Projection | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._bus = bus
        self._metrics = metrics or MetricsRegistry()
        self._projection = projection or Projection()
        self._clock = clock or SystemMonotonicClock()
        self._seq = -1
        self._observer_errors = 0

    @property
    def metrics(self) -> MetricsRegistry:
        return self._metrics

    @property
    def projection(self) -> Projection:
        return self._projection

    @property
    def observer_errors(self) -> int:
        return self._observer_errors

    def monotonic_ns(self) -> int:
        return self._clock.monotonic_ns()

    @property
    def clock_domain(self) -> str:
        return self._clock.clock_domain

    def record_plan_outcome(
        self,
        *,
        session_id: str,
        trace_id: str | None,
        turn_id: int | None,
        generation_id: int | None,
        plan_id: str | None,
        plan_revision: int | None,
        status: str,
        reason_code: str,
        start_ns: int,
        start_clock_domain: str,
        normalization_passes: int | None,
        stage_count: int,
        atom_count: int,
        unresolved_count: int,
        chunk_count: int,
        vocab_rejections: int,
        stale_or_duplicate: bool,
    ) -> tuple[MetricSample, ...]:
        """Record F4-A metrics & safe M04 event without exposing private text."""
        samples: list[MetricSample] = []
        end_ns = self._clock.monotonic_ns()
        if start_clock_domain == self._clock.clock_domain and end_ns >= start_ns:
            plan_ms: float | None = (end_ns - start_ns) / 1_000_000.0
            plan_sample = MetricSample(
                name="f4.plan_ms",
                value=plan_ms,
                unit="ms",
                observation_scope="SERVER",
                status=MetricStatus.MEASURED,
            )
        else:
            plan_ms = None
            plan_sample = MetricSample(
                name="f4.plan_ms",
                value=None,
                unit="ms",
                observation_scope="SERVER",
                status=MetricStatus.UNAVAILABLE,
                reason="clock_domain_mismatch",
            )
        samples.append(plan_sample)

        try:
            self._metrics.observe("f4.plan_ms", plan_ms, unit="ms", observation_scope="SERVER", reason=plan_sample.reason)
            if normalization_passes is not None:
                self._metrics.inc("f4.normalization_invocations", normalization_passes)
            self._metrics.inc("f4.normalization_stages", stage_count)
            self._metrics.inc("f4.protected_atoms", atom_count)
            self._metrics.inc("f4.unresolved_atoms", unresolved_count)
            self._metrics.inc("f4.chunks_total", chunk_count)
            self._metrics.inc("f4.vocab_rejections", vocab_rejections)
            if stale_or_duplicate:
                self._metrics.inc("f4.stale_or_duplicate", 1)

            if self._bus is not None:
                self._seq += 1
                meta: dict[str, Any] = {
                    "stage": "F4",
                    "status": status,
                    "reason": reason_code,
                }
                if plan_id is not None:
                    meta["plan_id"] = plan_id
                if plan_revision is not None:
                    meta["plan_revision"] = plan_revision
                if plan_ms is not None:
                    meta["duration_ms"] = round(plan_ms, 3)

                env = EventEnvelope(
                    schema_version=CONTRACT_SCHEMA_VERSION,
                    event_type="tts.plan",
                    session_id=session_id,
                    trace_id=trace_id,
                    turn_id=turn_id,
                    generation_id=generation_id,
                    sequence=self._seq,
                    monotonic_ns=end_ns,
                    clock_domain=self._clock.clock_domain,
                    producer="f4.linguistic",
                    metadata=meta,
                )
                projected = self._projection.project(env)
                if projected is not None:
                    self._bus.try_publish(env)
        except Exception:
            self._observer_errors += 1

        return tuple(samples)

    def stats(self) -> F4TelemetrySnapshot:
        pstats = self._projection.stats
        bstats = self._bus.stats if self._bus is not None else None
        return F4TelemetrySnapshot(
            observer_errors=self._observer_errors,
            dropped_projections=pstats.dropped_count,
            bus_dropped_events=bstats.dropped_count if bstats is not None else 0,
        )
