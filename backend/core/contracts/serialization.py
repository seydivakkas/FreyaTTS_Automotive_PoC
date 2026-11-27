"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import json
from dataclasses import is_dataclass
from enum import Enum
from typing import Any

from backend.core.contracts.validation import thaw_value

_SAFE_SCALAR_KEYS = frozenset({
    "schema_version",
    "event_type",
    "session_id",
    "trace_id",
    "turn_id",
    "generation_id",
    "sequence",
    "monotonic_ns",
    "clock_domain",
    "utc_timestamp",
    "producer",
    "utterance_id",
    "revision",
    "status",
    "outcome",
    "response_id",
    "speech_act",
    "state_revision",
    "plan_id",
    "plan_revision",
    "chunk_id",
    "chunk_index",
    "sample_count",
    "sample_offset",
    "valid_sample_count",
    "actual_duration_ms",
    "cache_status",
    "quality_status",
    "observation_scope",
    "kind",
    "profile",
    "queue_depth",
    "sample_progress",
    "reason",
    "code",
    "category",
    "retryable",
})


def _to_plain(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_plain(getattr(obj, k)) for k in obj.__dataclass_fields__ if k != "payload"}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(x) for x in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(_to_plain(x) for x in obj)
    if isinstance(obj, dict):
        return {str(k): _to_plain(v) for k, v in obj.items() if k != "payload"}
    return thaw_value(obj)


def metadata_to_json(obj: Any) -> str:
    """Strict UTF-8 JSON serializer rejecting NaN/Inf and omitting binary payload fields."""
    return json.dumps(_to_plain(obj), ensure_ascii=False, sort_keys=True, allow_nan=False)


def safe_telemetry_projection(record: Any) -> dict[str, Any]:
    """Allowlisted projection omitting transcripts, raw audio, customer identifiers, and secrets."""
    plain = _to_plain(record)
    if not isinstance(plain, dict):
        return {"value_type": type(record).__name__}
    projected: dict[str, Any] = {}
    for k, v in plain.items():
        if k in _SAFE_SCALAR_KEYS and isinstance(v, (str, int, float, bool, type(None))):
            projected[k] = v
        elif k in {"envelope", "generation_ref", "stream_ref", "turn_ref", "error"} and isinstance(v, dict):
            projected[k] = safe_telemetry_projection(v)
    return projected
