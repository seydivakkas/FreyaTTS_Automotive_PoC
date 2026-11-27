"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from backend.core.contracts.common import EventEnvelope, GenerationRef, StreamRef, TurnRef
from backend.core.contracts.validation import freeze_value, require_finite, require_safe_id, require_strict_int


class SpeechEventKind(StrEnum):
    SPEECH_CANDIDATE = "SPEECH_CANDIDATE"
    SPEECH_START = "SPEECH_START"
    SPEECH_END = "SPEECH_END"
    UTTERANCE_FINALIZED = "UTTERANCE_FINALIZED"
    SOFT_PAUSE = "SOFT_PAUSE"
    RESUME = "RESUME"
    COMMIT_INTERRUPT = "COMMIT_INTERRUPT"


@dataclass(frozen=True, slots=True)
class SpeechEvent:
    envelope: EventEnvelope
    kind: SpeechEventKind
    stream_ref: StreamRef
    sample_offset: int
    reason: str
    vad_score: float | None = None
    target_generation: GenerationRef | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, EventEnvelope):
            raise TypeError("envelope must be EventEnvelope")
        if not isinstance(self.kind, SpeechEventKind):
            raise ValueError("kind must be SpeechEventKind")
        if not isinstance(self.stream_ref, StreamRef):
            raise TypeError("stream_ref must be StreamRef")
        if self.stream_ref.session_id != self.envelope.session_id:
            raise ValueError("stream_ref.session_id mismatch with envelope")
        require_strict_int(self.sample_offset, "sample_offset", minimum=0)
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason required")
        if self.vad_score is not None:
            require_finite(self.vad_score, "vad_score", minimum=0.0, maximum=1.0)
        if self.target_generation is not None:
            if not isinstance(self.target_generation, GenerationRef):
                raise TypeError("target_generation must be GenerationRef")
            if self.target_generation.session_id != self.envelope.session_id:
                raise ValueError("target_generation.session_id mismatch with envelope")


@dataclass(frozen=True, slots=True)
class Utterance:
    utterance_id: str
    stream_ref: StreamRef
    turn_ref: TurnRef | None
    start_sample: int
    end_sample_exclusive: int
    finalized: bool
    finalization_reason: str | None
    frame_refs: tuple[str, ...] = ()
    actual_pre_roll_samples: int = 0
    actual_post_roll_samples: int = 0
    has_discontinuity: bool = False
    payload: bytes | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.utterance_id, "utterance_id")
        if not isinstance(self.stream_ref, StreamRef):
            raise TypeError("stream_ref must be StreamRef")
        if self.turn_ref is not None:
            if not isinstance(self.turn_ref, TurnRef):
                raise TypeError("turn_ref must be TurnRef")
            if self.turn_ref.session_id != self.stream_ref.session_id:
                raise ValueError("turn_ref.session_id mismatch with stream_ref")
        require_strict_int(self.start_sample, "start_sample", minimum=0)
        require_strict_int(self.end_sample_exclusive, "end_sample_exclusive", minimum=self.start_sample)
        if self.finalized and (not isinstance(self.finalization_reason, str) or not self.finalization_reason.strip()):
            raise ValueError("finalized utterance requires finalization_reason")
        if self.finalized and not self.frame_refs and self.payload is None:
            raise ValueError("finalized utterance requires frame_refs or payload")
        require_strict_int(self.actual_pre_roll_samples, "actual_pre_roll_samples", minimum=0)
        require_strict_int(self.actual_post_roll_samples, "actual_post_roll_samples", minimum=0)
        if self.payload is not None and not isinstance(self.payload, bytes):
            raise TypeError("payload must be immutable bytes")
        object.__setattr__(self, "frame_refs", freeze_value(tuple(self.frame_refs)))

    def __repr__(self) -> str:
        return (
            f"Utterance(id={self.utterance_id!r}, interval=[{self.start_sample},{self.end_sample_exclusive}), "
            f"finalized={self.finalized})"
        )
