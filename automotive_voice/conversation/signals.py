"""M02 external control signals; no raw audio or personal transcripts in events."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import time
from uuid import UUID, uuid4
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId


class SignalKind(str, Enum):
    SESSION_OPENED = "session_opened"
    VAD_SPEECH_STARTED = "vad_speech_started"
    TRANSCRIPT_FINAL = "transcript_final"
    LLM_RESPONSE_READY = "llm_response_ready"
    AUDIO_CHUNK_READY = "audio_chunk_ready"
    PLAYOUT_FINISHED = "playout_finished"
    MEDIA_FLUSH_ACK = "media_flush_ack"
    MEDIA_FLUSH_TIMEOUT = "media_flush_timeout"
    HANDOFF_REQUESTED = "handoff_requested"
    HANGUP = "hangup"


_REF_KINDS = {SignalKind.TRANSCRIPT_FINAL, SignalKind.LLM_RESPONSE_READY, SignalKind.AUDIO_CHUNK_READY}
_FLUSH_KINDS = {SignalKind.MEDIA_FLUSH_ACK, SignalKind.MEDIA_FLUSH_TIMEOUT}


@dataclass(frozen=True, slots=True)
class ConversationSignal:
    event_id: str
    kind: SignalKind
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    sequence: int
    occurred_at_utc: str
    occurred_mono_ns: int
    reference: str | None = None
    flush_request_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SignalKind):
            raise ValueError("Unsupported signal kind")
        try:
            UUID(self.event_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("event_id must be UUID") from exc
        SessionId(self.session_id); TurnId(self.turn_id); GenerationId(self.generation_id)
        for key in ("sequence", "occurred_mono_ns"):
            v = getattr(self, key)
            if type(v) is not int or v < 0 or v > 2**63-1:
                raise ValueError(f"Invalid {key}")
        try:
            dt = datetime.fromisoformat(self.occurred_at_utc.replace('Z', '+00:00'))
            if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
                raise ValueError("not UTC")
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("occurred_at_utc must be UTC") from exc
        if self.kind in _REF_KINDS:
            if not isinstance(self.reference, str) or not (1 <= len(self.reference) <= 128) or not self.reference.isascii() or not all(c.isalnum() or c in "_-.:/" for c in self.reference):
                raise ValueError("A non-PII safe reference is required")
        elif self.reference is not None:
            raise ValueError("Reference is unexpected for this signal")
        if self.kind in _FLUSH_KINDS:
            try:
                UUID(self.flush_request_id)
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError("Flush ack/timeout requires UUID flush_request_id") from exc
        elif self.flush_request_id is not None:
            raise ValueError("Unexpected flush_request_id")

    @classmethod
    def create(cls, kind: SignalKind, session_id: str, turn_id: int, generation_id: int,
               sequence: int, *, reference: str | None = None, flush_request_id: str | None = None,
               event_id: str | None = None, mono_ns: int | None = None) -> 'ConversationSignal':
        return cls(str(uuid4()) if event_id is None else event_id, kind, SessionId(session_id),
                   TurnId(turn_id), GenerationId(generation_id), sequence,
                   datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                   time.monotonic_ns() if mono_ns is None else mono_ns,
                   reference, flush_request_id)
