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

import math
import threading
from collections import deque
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from backend.core.contracts.common import MetricSample, MetricStatus
from backend.core.contracts.validation import require_finite, require_safe_id, require_strict_int

_SeriesKey = tuple[str, str, tuple[tuple[str, str], ...]]


def _normalize_labels(labels: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        raise ValueError("Cannot compute percentile of empty list")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return sorted_vals[lo]
    frac = rank - lo
    return sorted_vals[lo] + frac * (sorted_vals[hi] - sorted_vals[lo])


@dataclass(frozen=True, slots=True)
class HistogramSummary:
    """Immutable bounded histogram statistics preserving null vs zero distinction."""

    name: str
    unit: str
    observation_scope: str
    labels: Mapping[str, str]
    status: MetricStatus
    count: int
    total_observed: int
    null_count: int
    evicted_count: int
    capacity: int
    min_value: float | None
    max_value: float | None
    mean_value: float | None
    p50: float | None
    p95: float | None
    p99: float | None
    reason: str | None = None


@dataclass(slots=True)
class _CounterEntry:
    name: str
    unit: str
    observation_scope: str
    labels: tuple[tuple[str, str], ...]
    value: float = 0.0
    source_ref: str | None = None


@dataclass(slots=True)
class _GaugeEntry:
    name: str
    unit: str
    observation_scope: str
    labels: tuple[tuple[str, str], ...]
    value: float | None
    status: MetricStatus
    reason: str | None = None
    source_ref: str | None = None


class _BoundedHistogram:
    __slots__ = (
        "name",
        "unit",
        "observation_scope",
        "labels",
        "capacity",
        "samples",
        "total_observed",
        "null_count",
        "evicted_count",
        "last_reason",
    )

    def __init__(
        self,
        name: str,
        unit: str,
        observation_scope: str,
        labels: tuple[tuple[str, str], ...],
        capacity: int,
    ) -> None:
        self.name = name
        self.unit = unit
        self.observation_scope = observation_scope
        self.labels = labels
        self.capacity = capacity
        self.samples: deque[float] = deque(maxlen=capacity)
        self.total_observed = 0
        self.null_count = 0
        self.evicted_count = 0
        self.last_reason: str | None = None

    def observe(self, value: float | None, *, reason: str | None = None) -> None:
        if value is None:
            self.null_count += 1
            if reason:
                self.last_reason = reason
            return
        finite_val = require_finite(value, self.name)
        assert finite_val is not None
        if len(self.samples) >= self.capacity:
            self.evicted_count += 1
        self.samples.append(finite_val)
        self.total_observed += 1

    def summary(self) -> HistogramSummary:
        label_map = MappingProxyType(dict(self.labels))
        if not self.samples:
            return HistogramSummary(
                name=self.name,
                unit=self.unit,
                observation_scope=self.observation_scope,
                labels=label_map,
                status=MetricStatus.UNAVAILABLE,
                count=0,
                total_observed=self.total_observed,
                null_count=self.null_count,
                evicted_count=self.evicted_count,
                capacity=self.capacity,
                min_value=None,
                max_value=None,
                mean_value=None,
                p50=None,
                p95=None,
                p99=None,
                reason=self.last_reason or "no_measured_samples",
            )
        ordered = sorted(self.samples)
        count = len(ordered)
        mean_val = sum(ordered) / count
        return HistogramSummary(
            name=self.name,
            unit=self.unit,
            observation_scope=self.observation_scope,
            labels=label_map,
            status=MetricStatus.MEASURED,
            count=count,
            total_observed=self.total_observed,
            null_count=self.null_count,
            evicted_count=self.evicted_count,
            capacity=self.capacity,
            min_value=ordered[0],
            max_value=ordered[-1],
            mean_value=mean_val,
            p50=_percentile(ordered, 50.0),
            p95=_percentile(ordered, 95.0),
            p99=_percentile(ordered, 99.0),
            reason=None,
        )


class MetricsRegistry:
    """Thread-safe bounded metrics registry with strict null vs zero semantics."""

    def __init__(
        self,
        *,
        max_series: int = 1024,
        default_histogram_capacity: int = 256,
    ) -> None:
        require_strict_int(max_series, "max_series", minimum=1)
        require_strict_int(default_histogram_capacity, "default_histogram_capacity", minimum=1)
        self.max_series = max_series
        self.default_histogram_capacity = default_histogram_capacity
        self._lock = threading.Lock()
        self._counters: dict[_SeriesKey, _CounterEntry] = {}
        self._gauges: dict[_SeriesKey, _GaugeEntry] = {}
        self._histograms: dict[_SeriesKey, _BoundedHistogram] = {}
        self._dropped_series_count = 0

    def _total_series(self) -> int:
        return len(self._counters) + len(self._gauges) + len(self._histograms)

    def inc(
        self,
        name: str,
        amount: float = 1.0,
        *,
        unit: str = "count",
        observation_scope: str = "SERVER",
        labels: Mapping[str, str] | None = None,
        source_ref: str | None = None,
    ) -> MetricSample | None:
        require_safe_id(name, "name")
        finite_amount = require_finite(amount, "amount", minimum=0.0)
        assert finite_amount is not None
        norm_labels = _normalize_labels(labels)
        key: _SeriesKey = (name, observation_scope, norm_labels)

        with self._lock:
            entry = self._counters.get(key)
            if entry is None:
                if self._total_series() >= self.max_series:
                    self._dropped_series_count += 1
                    return None
                entry = _CounterEntry(
                    name=name,
                    unit=unit,
                    observation_scope=observation_scope,
                    labels=norm_labels,
                    value=0.0,
                    source_ref=source_ref,
                )
                self._counters[key] = entry
            entry.value += finite_amount
            if source_ref is not None:
                entry.source_ref = source_ref
            return MetricSample(
                name=entry.name,
                value=entry.value,
                unit=entry.unit,
                observation_scope=entry.observation_scope,
                status=MetricStatus.MEASURED,
                source_ref=entry.source_ref,
            )

    def set_gauge(
        self,
        name: str,
        value: float | None,
        *,
        unit: str = "unit",
        observation_scope: str = "SERVER",
        status: MetricStatus | None = None,
        reason: str | None = None,
        labels: Mapping[str, str] | None = None,
        source_ref: str | None = None,
    ) -> MetricSample | None:
        require_safe_id(name, "name")
        if value is None:
            resolved_status = status if status in {MetricStatus.UNAVAILABLE, MetricStatus.UNKNOWN} else MetricStatus.UNAVAILABLE
            resolved_value: float | None = None
            resolved_reason = reason or "unavailable"
        else:
            resolved_value = require_finite(value, "value")
            if status is not None and status != MetricStatus.MEASURED:
                raise ValueError("non-null gauge value requires status=MEASURED")
            resolved_status = MetricStatus.MEASURED
            resolved_reason = reason

        norm_labels = _normalize_labels(labels)
        key: _SeriesKey = (name, observation_scope, norm_labels)

        with self._lock:
            entry = self._gauges.get(key)
            if entry is None:
                if self._total_series() >= self.max_series:
                    self._dropped_series_count += 1
                    return None
                entry = _GaugeEntry(
                    name=name,
                    unit=unit,
                    observation_scope=observation_scope,
                    labels=norm_labels,
                    value=resolved_value,
                    status=resolved_status,
                    reason=resolved_reason,
                    source_ref=source_ref,
                )
                self._gauges[key] = entry
            else:
                entry.unit = unit
                entry.value = resolved_value
                entry.status = resolved_status
                entry.reason = resolved_reason
                if source_ref is not None:
                    entry.source_ref = source_ref
            return MetricSample(
                name=entry.name,
                value=entry.value,
                unit=entry.unit,
                observation_scope=entry.observation_scope,
                status=entry.status,
                reason=entry.reason,
                source_ref=entry.source_ref,
            )

    def observe(
        self,
        name: str,
        value: float | None,
        *,
        unit: str = "ms",
        observation_scope: str = "SERVER",
        max_samples: int | None = None,
        reason: str | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> HistogramSummary | None:
        require_safe_id(name, "name")
        cap = max_samples if max_samples is not None else self.default_histogram_capacity
        require_strict_int(cap, "max_samples", minimum=1)
        if value is not None:
            require_finite(value, "value")

        norm_labels = _normalize_labels(labels)
        key: _SeriesKey = (name, observation_scope, norm_labels)

        with self._lock:
            hist = self._histograms.get(key)
            if hist is None:
                if self._total_series() >= self.max_series:
                    self._dropped_series_count += 1
                    return None
                hist = _BoundedHistogram(name, unit, observation_scope, norm_labels, cap)
                self._histograms[key] = hist
            hist.observe(value, reason=reason)
            return hist.summary()

    def record_sample(self, sample: MetricSample, *, labels: Mapping[str, str] | None = None) -> MetricSample | None:
        if not isinstance(sample, MetricSample):
            raise TypeError("sample must be MetricSample")
        return self.set_gauge(
            sample.name,
            sample.value,
            unit=sample.unit,
            observation_scope=sample.observation_scope,
            status=sample.status,
            reason=sample.reason,
            labels=labels,
            source_ref=sample.source_ref,
        )

    def get_counter(
        self,
        name: str,
        *,
        unit: str = "count",
        observation_scope: str = "SERVER",
        labels: Mapping[str, str] | None = None,
    ) -> MetricSample:
        norm_labels = _normalize_labels(labels)
        key: _SeriesKey = (name, observation_scope, norm_labels)
        with self._lock:
            entry = self._counters.get(key)
            if entry is None:
                return MetricSample(
                    name=name,
                    value=None,
                    unit=unit,
                    observation_scope=observation_scope,
                    status=MetricStatus.UNAVAILABLE,
                    reason="not_recorded",
                )
            return MetricSample(
                name=entry.name,
                value=entry.value,
                unit=entry.unit,
                observation_scope=entry.observation_scope,
                status=MetricStatus.MEASURED,
                source_ref=entry.source_ref,
            )

    def get_gauge(
        self,
        name: str,
        *,
        unit: str = "unit",
        observation_scope: str = "SERVER",
        labels: Mapping[str, str] | None = None,
    ) -> MetricSample:
        norm_labels = _normalize_labels(labels)
        key: _SeriesKey = (name, observation_scope, norm_labels)
        with self._lock:
            entry = self._gauges.get(key)
            if entry is None:
                return MetricSample(
                    name=name,
                    value=None,
                    unit=unit,
                    observation_scope=observation_scope,
                    status=MetricStatus.UNAVAILABLE,
                    reason="not_recorded",
                )
            return MetricSample(
                name=entry.name,
                value=entry.value,
                unit=entry.unit,
                observation_scope=entry.observation_scope,
                status=entry.status,
                reason=entry.reason,
                source_ref=entry.source_ref,
            )

    def get_histogram_summary(
        self,
        name: str,
        *,
        observation_scope: str = "SERVER",
        labels: Mapping[str, str] | None = None,
    ) -> HistogramSummary | None:
        norm_labels = _normalize_labels(labels)
        key: _SeriesKey = (name, observation_scope, norm_labels)
        with self._lock:
            hist = self._histograms.get(key)
            return hist.summary() if hist is not None else None

    def to_metric_samples(self) -> tuple[MetricSample, ...]:
        """Export counters, gauges, and histogram summaries as M01 MetricSample tuples."""
        samples: list[MetricSample] = []
        with self._lock:
            for entry in self._counters.values():
                samples.append(
                    MetricSample(
                        name=entry.name,
                        value=entry.value,
                        unit=entry.unit,
                        observation_scope=entry.observation_scope,
                        status=MetricStatus.MEASURED,
                        source_ref=entry.source_ref,
                    )
                )
            for entry in self._gauges.values():
                samples.append(
                    MetricSample(
                        name=entry.name,
                        value=entry.value,
                        unit=entry.unit,
                        observation_scope=entry.observation_scope,
                        status=entry.status,
                        reason=entry.reason,
                        source_ref=entry.source_ref,
                    )
                )
            for hist in self._histograms.values():
                s = hist.summary()
                samples.append(
                    MetricSample(
                        name=s.name,
                        value=s.p95 if s.status == MetricStatus.MEASURED else None,
                        unit=s.unit,
                        observation_scope=s.observation_scope,
                        status=s.status,
                        reason=s.reason,
                    )
                )
        return tuple(samples)

    @property
    def dropped_series_count(self) -> int:
        with self._lock:
            return self._dropped_series_count
