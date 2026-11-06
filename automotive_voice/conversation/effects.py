"""Transport-independent effects. No network or audio side effects in reducer."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from uuid import uuid5, NAMESPACE_URL
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId


class EffectKind(str, Enum):
    REQUEST_LLM = "request_llm"
    START_TTS = "start_tts"
    QUEUE_AUDIO = "queue_audio"
    CANCEL_GENERATION = "cancel_generation"
    FLUSH_MEDIA = "flush_media"
    START_HANDOFF = "start_handoff"
    TERMINATE_CALL = "terminate_call"


@dataclass(frozen=True, slots=True)
class Effect:
    effect_id: str
    kind: EffectKind
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    related_event_id: str
    reference: str | None = None

    @classmethod
    def from_signal(cls, signal, kind: EffectKind, turn_id: int, generation_id: int,
                    reference: str | None = None) -> 'Effect':
        uid = str(uuid5(NAMESPACE_URL, f"freya-m02:{signal.session_id}:{signal.event_id}:{kind.value}"))
        return cls(uid, kind, signal.session_id, TurnId(turn_id), GenerationId(generation_id), signal.event_id, reference)
