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
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from backend.core.contracts.common import MetricSample
from backend.core.contracts.validation import freeze_value, require_safe_id, require_strict_int, require_utc_iso
from backend.observability.projection import Projection


class EvidenceKind(StrEnum):
    """Epistemic provenance classification for runtime and verification claims."""

    STATIC_CODE = "STATIC_CODE"
    HISTORICAL_RECORD = "HISTORICAL_RECORD"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"
    MOCK_RUNTIME = "MOCK_RUNTIME"
    LOCAL_RUNTIME_MEASURED = "LOCAL_RUNTIME_MEASURED"
    REAL_ENDPOINT_MEASURED = "REAL_ENDPOINT_MEASURED"


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """Immutable, sanitized record proving what kind of evidence supports a claim."""

    evidence_id: str
    kind: EvidenceKind
    claim: str
    subject: str
    clock_domain: str
    recorded_monotonic_ns: int
    observation_scope: str = "SERVER"
    utc_timestamp: str | None = None
    trace_id: str | None = None
    source_ref: str | None = None
    metrics: tuple[MetricSample, ...] = ()
    details: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    details_dropped: bool = False

    def __post_init__(self) -> None:
        require_safe_id(self.evidence_id, "evidence_id")
        if not isinstance(self.kind, EvidenceKind):
            raise ValueError("kind must be EvidenceKind")
        if not isinstance(self.claim, str) or not self.claim.strip():
            raise ValueError("claim must be non-empty")
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise ValueError("subject must be non-empty")
        if not isinstance(self.clock_domain, str) or not self.clock_domain.strip():
            raise ValueError("clock_domain required")
        require_strict_int(self.recorded_monotonic_ns, "recorded_monotonic_ns", minimum=0)
        if not isinstance(self.observation_scope, str) or not self.observation_scope.strip():
            raise ValueError("observation_scope required")
        if self.kind == EvidenceKind.REAL_ENDPOINT_MEASURED and self.observation_scope.upper() in {
            "MOCK",
            "SYNTHETIC",
            "STATIC",
        }:
            raise ValueError("REAL_ENDPOINT_MEASURED cannot carry MOCK/SYNTHETIC/STATIC observation_scope")
        if self.utc_timestamp is not None:
            require_utc_iso(self.utc_timestamp, "utc_timestamp")
        if self.trace_id is not None:
            require_safe_id(self.trace_id, "trace_id")
        for m in self.metrics:
            if not isinstance(m, MetricSample):
                raise TypeError("metrics must contain MetricSample")
        object.__setattr__(self, "metrics", tuple(self.metrics))
        object.__setattr__(self, "details", freeze_value(dict(self.details)))

    @property
    def is_live_measured(self) -> bool:
        return self.kind in {EvidenceKind.LOCAL_RUNTIME_MEASURED, EvidenceKind.REAL_ENDPOINT_MEASURED}

    @property
    def proves_real_endpoint(self) -> bool:
        return self.kind == EvidenceKind.REAL_ENDPOINT_MEASURED


class EvidenceRecorder:
    """Bounded, projection-guarded recorder separating static/mock/synthetic vs live evidence."""

    def __init__(
        self,
        *,
        max_records: int = 512,
        projector: Projection | None = None,
    ) -> None:
        require_strict_int(max_records, "max_records", minimum=1)
        self.max_records = max_records
        self._projector = projector or Projection()
        self._lock = threading.Lock()
        self._records: OrderedDict[str, EvidenceRecord] = OrderedDict()
        self._evicted_count = 0
        self._total_recorded = 0

    def record(
        self,
        *,
        kind: EvidenceKind,
        claim: str,
        subject: str,
        recorded_monotonic_ns: int,
        clock_domain: str,
        evidence_id: str | None = None,
        observation_scope: str = "SERVER",
        utc_timestamp: str | None = None,
        trace_id: str | None = None,
        source_ref: str | None = None,
        metrics: tuple[MetricSample, ...] = (),
        details: Mapping[str, Any] | None = None,
    ) -> EvidenceRecord:
        eid = evidence_id or f"ev-{uuid4().hex[:16]}"
        sanitized_details: dict[str, Any] = {}
        details_dropped = False
        if details:
            allow = frozenset(str(k) for k in details.keys())
            projected = self._projector.project(dict(details), extra_allowlist=allow)
            if projected is None:
                details_dropped = True
            else:
                sanitized_details = projected

        rec = EvidenceRecord(
            evidence_id=eid,
            kind=kind,
            claim=claim,
            subject=subject,
            clock_domain=clock_domain,
            recorded_monotonic_ns=recorded_monotonic_ns,
            observation_scope=observation_scope,
            utc_timestamp=utc_timestamp,
            trace_id=trace_id,
            source_ref=source_ref,
            metrics=metrics,
            details=sanitized_details,
            details_dropped=details_dropped,
        )

        with self._lock:
            if eid in self._records:
                raise ValueError(f"Duplicate evidence_id: {eid}")
            if len(self._records) >= self.max_records:
                self._records.popitem(last=False)
                self._evicted_count += 1
            self._records[eid] = rec
            self._total_recorded += 1
            return rec

    def get(self, evidence_id: str) -> EvidenceRecord | None:
        with self._lock:
            return self._records.get(evidence_id)

    def list_records(
        self,
        *,
        kind: EvidenceKind | None = None,
        subject: str | None = None,
    ) -> tuple[EvidenceRecord, ...]:
        with self._lock:
            items = list(self._records.values())
        if kind is not None:
            items = [r for r in items if r.kind == kind]
        if subject is not None:
            items = [r for r in items if r.subject == subject]
        return tuple(items)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            items = list(self._records.values())
            evicted = self._evicted_count
            total = self._total_recorded
        counts = {k.value: 0 for k in EvidenceKind}
        for r in items:
            counts[r.kind.value] += 1
        return {
            "active_count": len(items),
            "total_recorded": total,
            "evicted_count": evicted,
            "counts_by_kind": counts,
        }

    def export_safe(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for rec in self.list_records():
            projected_metrics: list[dict[str, Any]] = []
            for m in rec.metrics:
                pm = self._projector.project(m)
                if pm is not None:
                    projected_metrics.append(pm)
            out.append({
                "evidence_id": rec.evidence_id,
                "kind": rec.kind.value,
                "claim": rec.claim,
                "subject": rec.subject,
                "clock_domain": rec.clock_domain,
                "recorded_monotonic_ns": rec.recorded_monotonic_ns,
                "observation_scope": rec.observation_scope,
                "utc_timestamp": rec.utc_timestamp,
                "trace_id": rec.trace_id,
                "source_ref": rec.source_ref,
                "metrics": projected_metrics,
                "details": dict(rec.details),
                "details_dropped": rec.details_dropped,
            })
        return out
