"""Versioned, JSON-safe event envelopes and wire decoding.

Datetime = UTC wall clock for audit; monotonic ns = elapsed-time ordering within
one process. Monotonic values are not comparable across process restarts.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import time
from uuid import UUID, uuid4
from typing import Any, Mapping
from types import MappingProxyType
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId

SCHEMA_VERSION = "1.0"

class EventType(str, Enum):
    SESSION_STARTED = "session_started"
    TURN_STARTED = "turn_started"
    USER_SPEECH_STARTED = "user_speech_started"
    TRANSCRIPT_FINAL = "transcript_final"
    RESPONSE_STARTED = "response_started"
    AUDIO_CHUNK_ENQUEUED = "audio_chunk_enqueued"
    PLAYOUT_FINISHED = "playout_finished"
    INTERRUPTED = "interrupted"
    INTERRUPTION_COMPLETED = "interruption_completed"
    HANDOFF_REQUESTED = "handoff_requested"
    SESSION_ENDED = "session_ended"
    SESSION_FAILED = "session_failed"
    STATE_CHANGED = "state_changed"
    ERROR = "error"

_FIELDS = {"schema_version", "event_id", "event_type", "session_id", "turn_id", "generation_id", "sequence", "occurred_at_utc", "occurred_mono_ns", "payload"}

def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value

def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(v) for v in value]
    return value

def _json_payload(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError("payload must be an object with string keys")
    try:
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
        return json.loads(encoded)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("payload must be strictly JSON serializable") from exc

@dataclass(frozen=True, slots=True)
class EventEnvelope:
    schema_version: str
    event_id: str
    event_type: EventType
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    sequence: int
    occurred_at_utc: str
    occurred_mono_ns: int
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported schema_version")
        try:
            UUID(self.event_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Invalid event_id UUID") from exc
        if not isinstance(self.event_type, EventType):
            raise ValueError("event_type must be EventType")
        SessionId(self.session_id); TurnId(self.turn_id); GenerationId(self.generation_id)
        if type(self.sequence) is not int or self.sequence < 0 or self.sequence > 2**63-1:
            raise ValueError("sequence must be a non-negative integer")
        if type(self.occurred_mono_ns) is not int or self.occurred_mono_ns < 0:
            raise ValueError("occurred_mono_ns must be non-negative")
        try:
            ts = datetime.fromisoformat(self.occurred_at_utc.replace('Z','+00:00'))
            if ts.utcoffset() is None or ts.utcoffset().total_seconds() != 0:
                raise ValueError()
        except (TypeError, ValueError) as exc:
            raise ValueError("occurred_at_utc must be an offset-aware UTC ISO timestamp") from exc
        object.__setattr__(self, "payload", _freeze(_json_payload(dict(self.payload))))

    @classmethod
    def create(cls, event_type: EventType, session_id: SessionId, turn_id: TurnId,
               generation_id: GenerationId, sequence: int,
               payload: dict[str, Any] | None = None) -> "EventEnvelope":
        return cls(SCHEMA_VERSION, str(uuid4()), event_type, SessionId(session_id),
                   TurnId(turn_id), GenerationId(generation_id), sequence,
                   datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
                   time.monotonic_ns(), payload or {})

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "event_id": self.event_id,
                "event_type": self.event_type.value, "session_id": str(self.session_id),
                "turn_id": int(self.turn_id), "generation_id": int(self.generation_id),
                "sequence": self.sequence, "occurred_at_utc": self.occurred_at_utc,
                "occurred_mono_ns": self.occurred_mono_ns, "payload": _thaw(self.payload)}

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> "EventEnvelope":
        if not isinstance(obj, dict) or set(obj) != _FIELDS:
            raise ValueError("Event envelope field set mismatch")
        return cls(obj['schema_version'], obj['event_id'], EventType(obj['event_type']),
                   SessionId(obj['session_id']), TurnId(obj['turn_id']),
                   GenerationId(obj['generation_id']), obj['sequence'],
                   obj['occurred_at_utc'], obj['occurred_mono_ns'], obj['payload'])
