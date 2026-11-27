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

from backend.observability.event_bus import BoundedEventBus, BusStats, DropPolicy, Subscription
from backend.observability.event_catalog import (
    DEFAULT_SAFE_METADATA_KEYS,
    EVENT_CATALOG,
    EventPriority,
    EventSpec,
    allowed_metadata_keys_for,
    get_event_spec,
    is_known_event_type,
    priority_for_event,
)
from backend.observability.evidence import EvidenceKind, EvidenceRecord, EvidenceRecorder
from backend.observability.legacy_adapter import (
    AdaptedLegacyTelemetry,
    adapt_legacy_event,
    legacy_event_to_safe_projection,
)
from backend.observability.local_store import LocalObservabilityStore, LocalStoreStats
from backend.observability.metrics import HistogramSummary, MetricsRegistry
from backend.observability.projection import (
    FORBIDDEN_TELEMETRY_KEYS,
    Projection,
    ProjectionStats,
    contains_sentinel,
    redact_sentinels,
)
from backend.observability.trace_store import (
    ClockDomainMismatchError,
    SpanRecord,
    SpanStatus,
    TraceRecord,
    TraceStore,
)

__all__ = [
    "AdaptedLegacyTelemetry",
    "BoundedEventBus",
    "BusStats",
    "ClockDomainMismatchError",
    "DEFAULT_SAFE_METADATA_KEYS",
    "DropPolicy",
    "EVENT_CATALOG",
    "EventPriority",
    "EventSpec",
    "EvidenceKind",
    "EvidenceRecord",
    "EvidenceRecorder",
    "FORBIDDEN_TELEMETRY_KEYS",
    "HistogramSummary",
    "LocalObservabilityStore",
    "LocalStoreStats",
    "MetricsRegistry",
    "Projection",
    "ProjectionStats",
    "SpanRecord",
    "SpanStatus",
    "Subscription",
    "TraceRecord",
    "TraceStore",
    "adapt_legacy_event",
    "allowed_metadata_keys_for",
    "contains_sentinel",
    "get_event_spec",
    "is_known_event_type",
    "legacy_event_to_safe_projection",
    "priority_for_event",
    "redact_sentinels",
]
