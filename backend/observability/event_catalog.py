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
from enum import IntEnum
from types import MappingProxyType
from typing import Mapping


class EventPriority(IntEnum):
    """Priority lanes ordered from highest urgency (0) to lowest (3)."""

    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass(frozen=True, slots=True)
class EventSpec:
    """Catalog specification for a recognized observability event type."""

    event_type: str
    priority: EventPriority
    category: str
    allowlisted_metadata_keys: frozenset[str] = frozenset()
    description: str = ""


_BASE_LIFECYCLE_KEYS = frozenset({"reason", "cleanup_status", "pause_epoch"})
_PIPELINE_STAGE_KEYS = frozenset({"stage", "status", "source", "duration_ms", "error_code"})

_SPECS: tuple[EventSpec, ...] = (
    # M02 session & cancellation lifecycle
    EventSpec("session.opening", EventPriority.HIGH, "lifecycle", _BASE_LIFECYCLE_KEYS, "Session opening"),
    EventSpec("session.opened", EventPriority.HIGH, "lifecycle", _BASE_LIFECYCLE_KEYS, "Session opened"),
    EventSpec("session.closing", EventPriority.CRITICAL, "lifecycle", _BASE_LIFECYCLE_KEYS, "Session closing"),
    EventSpec("session.closed", EventPriority.CRITICAL, "lifecycle", _BASE_LIFECYCLE_KEYS, "Session closed"),
    EventSpec("turn.started", EventPriority.HIGH, "lifecycle", frozenset({"turn_id"}), "Turn started"),
    EventSpec("generation.started", EventPriority.HIGH, "lifecycle", frozenset({"generation_id"}), "Generation started"),
    EventSpec("generation.revoked", EventPriority.CRITICAL, "lifecycle", _BASE_LIFECYCLE_KEYS, "Generation revoked"),
    EventSpec("buffer.backpressure", EventPriority.CRITICAL, "admission", frozenset({"queue_depth"}), "Media queue backpressure"),
    EventSpec("result.rejected", EventPriority.HIGH, "admission", frozenset({"reason"}), "Media item rejected"),
    EventSpec("pause.requested", EventPriority.HIGH, "playback", frozenset({"pause_epoch"}), "Soft pause requested"),
    EventSpec("pause.resumed", EventPriority.HIGH, "playback", frozenset({"pause_epoch"}), "Playback resumed"),
    # Playback events
    EventSpec("playback.queued", EventPriority.NORMAL, "playback", frozenset({"queue_depth", "observation_scope"}), "Playback queued"),
    EventSpec("playback.playback_started", EventPriority.HIGH, "playback", frozenset({"observation_scope", "sample_progress"}), "Playback started"),
    EventSpec("playback.completed", EventPriority.HIGH, "playback", frozenset({"observation_scope", "sample_progress"}), "Playback completed"),
    EventSpec("playback.canceled", EventPriority.CRITICAL, "playback", frozenset({"reason", "observation_scope"}), "Playback canceled"),
    EventSpec("playback.failed", EventPriority.CRITICAL, "playback", frozenset({"code", "category", "retryable"}), "Playback failed"),
    # Legacy F0-F6 pipeline stage bridges
    EventSpec("pipeline.stage.f0", EventPriority.NORMAL, "pipeline", _PIPELINE_STAGE_KEYS, "F0 audio ingress"),
    EventSpec("pipeline.stage.f1", EventPriority.HIGH, "pipeline", _PIPELINE_STAGE_KEYS, "F1 VAD / barge-in"),
    EventSpec("pipeline.stage.f2", EventPriority.HIGH, "pipeline", _PIPELINE_STAGE_KEYS, "F2 ASR"),
    EventSpec("pipeline.stage.f3", EventPriority.HIGH, "pipeline", _PIPELINE_STAGE_KEYS, "F3 supervisor / LLM"),
    EventSpec("pipeline.stage.f4", EventPriority.NORMAL, "pipeline", _PIPELINE_STAGE_KEYS, "F4 normalization"),
    EventSpec("pipeline.stage.f5", EventPriority.HIGH, "pipeline", _PIPELINE_STAGE_KEYS, "F5 TTS synthesis"),
    EventSpec("pipeline.stage.f6", EventPriority.HIGH, "pipeline", _PIPELINE_STAGE_KEYS, "F6 playback pacing"),
    # ASR / Dialogue / TTS
    EventSpec("asr.partial", EventPriority.LOW, "asr", frozenset({"utterance_id", "revision", "status", "outcome"}), "Partial ASR update"),
    EventSpec("asr.final", EventPriority.HIGH, "asr", frozenset({"utterance_id", "revision", "status", "outcome"}), "Final ASR result"),
    EventSpec("dialogue.response", EventPriority.HIGH, "dialogue", frozenset({"response_id", "speech_act", "state_revision", "outcome"}), "Dialogue response"),
    EventSpec("tts.plan", EventPriority.NORMAL, "tts", frozenset({"plan_id", "plan_revision", "status"}), "Synthesis plan"),
    EventSpec("tts.chunk", EventPriority.NORMAL, "tts", frozenset({"plan_id", "plan_revision", "chunk_id", "chunk_index", "cache_status", "quality_status"}), "Synthesized audio chunk"),
    # Observability internal health
    EventSpec("observability.trace.evicted", EventPriority.NORMAL, "observability", frozenset({"reason"}), "Trace evicted"),
    EventSpec("observability.projection.dropped", EventPriority.CRITICAL, "observability", frozenset({"reason"}), "Projection dropped"),
    EventSpec("observability.bus.overflow", EventPriority.CRITICAL, "observability", frozenset({"queue_depth", "reason"}), "Bus overflow"),
)

EVENT_CATALOG: Mapping[str, EventSpec] = MappingProxyType({spec.event_type: spec for spec in _SPECS})

DEFAULT_SAFE_METADATA_KEYS: frozenset[str] = frozenset({
    "reason",
    "status",
    "outcome",
    "stage",
    "source",
    "duration_ms",
    "queue_depth",
    "observation_scope",
    "pause_epoch",
    "cleanup_status",
    "code",
    "category",
    "retryable",
})


def get_event_spec(event_type: str) -> EventSpec | None:
    """Return the catalog specification for an event_type, or None if unregistered."""
    return EVENT_CATALOG.get(event_type)


def is_known_event_type(event_type: str) -> bool:
    """Return True if event_type is registered in the M04 event catalog."""
    return event_type in EVENT_CATALOG


def priority_for_event(
    event_type: str,
    *,
    default: EventPriority = EventPriority.NORMAL,
) -> EventPriority:
    """Resolve priority lane for an event_type, inferring critical errors safely."""
    spec = EVENT_CATALOG.get(event_type)
    if spec is not None:
        return spec.priority
    lowered = event_type.lower()
    if any(token in lowered for token in ("error", "fail", "critical", "revoked", "overflow", "dropped")):
        return EventPriority.CRITICAL
    if any(token in lowered for token in ("debug", "partial", "trace", "diagnostic")):
        return EventPriority.LOW
    return default


def allowed_metadata_keys_for(event_type: str) -> frozenset[str]:
    """Return allowlisted metadata scalar keys for the given event_type."""
    spec = EVENT_CATALOG.get(event_type)
    if spec is None:
        return DEFAULT_SAFE_METADATA_KEYS
    return spec.allowlisted_metadata_keys | DEFAULT_SAFE_METADATA_KEYS
