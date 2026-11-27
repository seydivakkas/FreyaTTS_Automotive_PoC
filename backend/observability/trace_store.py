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
from collections import OrderedDict, deque
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from backend.core.contracts.common import ErrorInfo
from backend.core.contracts.validation import freeze_value, require_safe_id, require_strict_int
from backend.observability.projection import Projection


class SpanStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    OK = "OK"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"
    EVICTED = "EVICTED"


class ClockDomainMismatchError(ValueError):
    """Raised when attempting duration calculation across different clock domains."""


@dataclass(frozen=True, slots=True)
class SpanRecord:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    session_id: str
    turn_id: int | None
    generation_id: int | None
    clock_domain: str
    start_monotonic_ns: int
    end_monotonic_ns: int | None
    duration_ns: int | None
    status: SpanStatus
    attributes: Mapping[str, Any]
    error: ErrorInfo | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.duration_ns is None:
            return None
        return self.duration_ns / 1_000_000.0


@dataclass(frozen=True, slots=True)
class TraceRecord:
    trace_id: str
    session_id: str
    clock_domain: str
    spans: tuple[SpanRecord, ...]
    partial: bool
    evicted_span_count: int
    created_monotonic_ns: int
    last_updated_monotonic_ns: int


class _MutableTrace:
    __slots__ = (
        "trace_id",
        "session_id",
        "clock_domain",
        "spans",
        "partial",
        "evicted_span_count",
        "created_monotonic_ns",
        "last_updated_monotonic_ns",
    )

    def __init__(
        self,
        trace_id: str,
        session_id: str,
        clock_domain: str,
        created_ns: int,
        *,
        partial: bool = False,
    ) -> None:
        self.trace_id = trace_id
        self.session_id = session_id
        self.clock_domain = clock_domain
        self.spans: OrderedDict[str, SpanRecord] = OrderedDict()
        self.partial = partial
        self.evicted_span_count = 0
        self.created_monotonic_ns = created_ns
        self.last_updated_monotonic_ns = created_ns

    def snapshot(self) -> TraceRecord:
        return TraceRecord(
            trace_id=self.trace_id,
            session_id=self.session_id,
            clock_domain=self.clock_domain,
            spans=tuple(self.spans.values()),
            partial=self.partial,
            evicted_span_count=self.evicted_span_count,
            created_monotonic_ns=self.created_monotonic_ns,
            last_updated_monotonic_ns=self.last_updated_monotonic_ns,
        )


class TraceStore:
    """Bounded in-memory trace & span store with same-clock-domain monotonic duration checks."""

    def __init__(
        self,
        *,
        max_traces: int = 256,
        max_spans_per_trace: int = 64,
        max_total_spans: int = 4096,
        max_evicted_history: int = 256,
        projector: Projection | None = None,
    ) -> None:
        if max_traces < 1 or max_spans_per_trace < 1 or max_total_spans < 1:
            raise ValueError("TraceStore capacities must be positive")
        self.max_traces = max_traces
        self.max_spans_per_trace = max_spans_per_trace
        self.max_total_spans = max_total_spans
        self._projector = projector or Projection()
        self._lock = threading.Lock()
        self._traces: OrderedDict[str, _MutableTrace] = OrderedDict()
        self._total_spans = 0
        self._evicted_traces_count = 0
        self._evicted_spans_count = 0
        self._evicted_trace_ids: deque[str] = deque(maxlen=max_evicted_history)
        self._evicted_summaries: deque[TraceRecord] = deque(maxlen=max_evicted_history)

    def _sanitize_attributes(self, attributes: Mapping[str, Any] | None) -> Mapping[str, Any]:
        if not attributes:
            return MappingProxyType({})
        allow = frozenset(str(k) for k in attributes.keys())
        projected = self._projector.project(dict(attributes), extra_allowlist=allow)
        if projected is None:
            return MappingProxyType({})
        return freeze_value(projected)

    def _evict_oldest_trace(self) -> None:
        tid, evicted = self._traces.popitem(last=False)
        self._total_spans -= len(evicted.spans)
        self._evicted_traces_count += 1
        self._evicted_spans_count += len(evicted.spans)
        evicted.partial = True
        evicted.evicted_span_count += len(evicted.spans)
        self._evicted_trace_ids.append(tid)
        self._evicted_summaries.append(evicted.snapshot())

    def _evict_oldest_span_in_trace(self, trace: _MutableTrace) -> None:
        _, _ = trace.spans.popitem(last=False)
        trace.partial = True
        trace.evicted_span_count += 1
        self._total_spans -= 1
        self._evicted_spans_count += 1

    def _ensure_span_capacity(self, target_trace: _MutableTrace) -> None:
        while len(target_trace.spans) >= self.max_spans_per_trace:
            self._evict_oldest_span_in_trace(target_trace)
        while self._total_spans >= self.max_total_spans:
            victim = next((t for t in self._traces.values() if t.spans), None)
            if victim is None:
                break
            self._evict_oldest_span_in_trace(victim)

    def start_span(
        self,
        *,
        trace_id: str,
        span_id: str,
        name: str,
        session_id: str,
        start_monotonic_ns: int,
        clock_domain: str,
        parent_span_id: str | None = None,
        turn_id: int | None = None,
        generation_id: int | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> SpanRecord:
        require_safe_id(trace_id, "trace_id")
        require_safe_id(span_id, "span_id")
        require_safe_id(session_id, "session_id")
        require_strict_int(start_monotonic_ns, "start_monotonic_ns", minimum=0)
        if not isinstance(name, str) or not name.strip():
            raise ValueError("span name required")
        if not isinstance(clock_domain, str) or not clock_domain.strip():
            raise ValueError("clock_domain required")
        if parent_span_id is not None:
            require_safe_id(parent_span_id, "parent_span_id")
        if turn_id is not None:
            require_strict_int(turn_id, "turn_id", minimum=0)
        if generation_id is not None:
            require_strict_int(generation_id, "generation_id", minimum=0)

        safe_attrs = self._sanitize_attributes(attributes)

        with self._lock:
            trace = self._traces.get(trace_id)
            if trace is None:
                if len(self._traces) >= self.max_traces:
                    self._evict_oldest_trace()
                was_evicted = trace_id in self._evicted_trace_ids
                trace = _MutableTrace(
                    trace_id,
                    session_id,
                    clock_domain,
                    start_monotonic_ns,
                    partial=was_evicted,
                )
                self._traces[trace_id] = trace
            else:
                if trace.clock_domain != clock_domain:
                    raise ClockDomainMismatchError(
                        f"Trace {trace_id} clock_domain {trace.clock_domain!r} != {clock_domain!r}"
                    )
                if span_id in trace.spans:
                    raise ValueError(f"Duplicate span_id {span_id!r} in trace {trace_id!r}")
                self._traces.move_to_end(trace_id)

            self._ensure_span_capacity(trace)

            span = SpanRecord(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                name=name,
                session_id=session_id,
                turn_id=turn_id,
                generation_id=generation_id,
                clock_domain=clock_domain,
                start_monotonic_ns=start_monotonic_ns,
                end_monotonic_ns=None,
                duration_ns=None,
                status=SpanStatus.IN_PROGRESS,
                attributes=safe_attrs,
                error=None,
            )
            trace.spans[span_id] = span
            trace.last_updated_monotonic_ns = max(trace.last_updated_monotonic_ns, start_monotonic_ns)
            self._total_spans += 1
            return span

    def finish_span(
        self,
        *,
        trace_id: str,
        span_id: str,
        end_monotonic_ns: int,
        clock_domain: str,
        status: SpanStatus = SpanStatus.OK,
        error: ErrorInfo | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> SpanRecord | None:
        require_strict_int(end_monotonic_ns, "end_monotonic_ns", minimum=0)
        if not isinstance(clock_domain, str) or not clock_domain.strip():
            raise ValueError("clock_domain required")
        if not isinstance(status, SpanStatus) or status == SpanStatus.IN_PROGRESS:
            raise ValueError("finish_span requires a terminal SpanStatus")
        if error is not None and not isinstance(error, ErrorInfo):
            raise TypeError("error must be ErrorInfo")

        extra_attrs = self._sanitize_attributes(attributes)

        with self._lock:
            trace = self._traces.get(trace_id)
            if trace is None:
                return None
            if trace.clock_domain != clock_domain:
                raise ClockDomainMismatchError(
                    f"Trace {trace_id} clock_domain {trace.clock_domain!r} != {clock_domain!r}"
                )
            existing = trace.spans.get(span_id)
            if existing is None:
                # Span was evicted while in-flight; mark trace partial honestly.
                trace.partial = True
                return None
            if existing.clock_domain != clock_domain:
                raise ClockDomainMismatchError(
                    f"Span {span_id} clock_domain {existing.clock_domain!r} != {clock_domain!r}"
                )
            if end_monotonic_ns < existing.start_monotonic_ns:
                raise ValueError(
                    f"Monotonic duration check failed: end {end_monotonic_ns} < start {existing.start_monotonic_ns}"
                )

            merged_attrs = dict(existing.attributes)
            merged_attrs.update(extra_attrs)
            finished = SpanRecord(
                trace_id=existing.trace_id,
                span_id=existing.span_id,
                parent_span_id=existing.parent_span_id,
                name=existing.name,
                session_id=existing.session_id,
                turn_id=existing.turn_id,
                generation_id=existing.generation_id,
                clock_domain=existing.clock_domain,
                start_monotonic_ns=existing.start_monotonic_ns,
                end_monotonic_ns=end_monotonic_ns,
                duration_ns=end_monotonic_ns - existing.start_monotonic_ns,
                status=status,
                attributes=freeze_value(merged_attrs),
                error=error,
            )
            trace.spans[span_id] = finished
            trace.last_updated_monotonic_ns = max(trace.last_updated_monotonic_ns, end_monotonic_ns)
            return finished

    def get_trace(self, trace_id: str) -> TraceRecord | None:
        with self._lock:
            trace = self._traces.get(trace_id)
            return trace.snapshot() if trace is not None else None

    def evicted_summaries(self) -> tuple[TraceRecord, ...]:
        with self._lock:
            return tuple(self._evicted_summaries)

    @property
    def trace_count(self) -> int:
        with self._lock:
            return len(self._traces)

    @property
    def total_span_count(self) -> int:
        with self._lock:
            return self._total_spans

    @property
    def evicted_traces_count(self) -> int:
        with self._lock:
            return self._evicted_traces_count

    @property
    def evicted_spans_count(self) -> int:
        with self._lock:
            return self._evicted_spans_count
