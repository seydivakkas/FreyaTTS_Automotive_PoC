"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backend.core.contracts.audio import AudioEncoding, AudioFormat
from backend.core.contracts.common import ErrorInfo, EventEnvelope, GenerationRef, StreamRef
from backend.core.contracts.validation import require_finite, require_strict_int


class PlaybackProfile(StrEnum):
    WEB_16K_PCM16 = "WEB_16K_PCM16"
    AUDIOSOCKET_8K_PCM16 = "AUDIOSOCKET_8K_PCM16"


class ObservationScope(StrEnum):
    SERVER = "SERVER"
    CLIENT = "CLIENT"
    PBX = "PBX"
    ENDPOINT = "ENDPOINT"
    UNKNOWN = "UNKNOWN"


class PlaybackEventKind(StrEnum):
    QUEUED = "QUEUED"
    PLAYBACK_STARTED = "PLAYBACK_STARTED"
    PAUSE_REQUESTED = "PAUSE_REQUESTED"
    PAUSED = "PAUSED"
    RESUMED = "RESUMED"
    FLUSH_REQUESTED = "FLUSH_REQUESTED"
    FLUSHED = "FLUSHED"
    DRAINED = "DRAINED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    FAILED = "FAILED"


_PROFILE_SPEC = {
    PlaybackProfile.WEB_16K_PCM16: (16000, 320, 640),
    PlaybackProfile.AUDIOSOCKET_8K_PCM16: (8000, 160, 320),
}


@dataclass(frozen=True, slots=True)
class RenderedFrame:
    generation_ref: GenerationRef
    stream_ref: StreamRef
    sequence: int
    sample_offset: int
    profile: PlaybackProfile
    format: AudioFormat
    frame_duration_ms: float
    sample_count: int
    valid_sample_count: int
    payload: bytes
    terminal: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.generation_ref, GenerationRef):
            raise TypeError("generation_ref must be GenerationRef")
        if not isinstance(self.stream_ref, StreamRef):
            raise TypeError("stream_ref must be StreamRef")
        if self.generation_ref.session_id != self.stream_ref.session_id:
            raise ValueError("generation_ref.session_id mismatch with stream_ref")
        require_strict_int(self.sequence, "sequence", minimum=0)
        require_strict_int(self.sample_offset, "sample_offset", minimum=0)
        if not isinstance(self.profile, PlaybackProfile):
            raise ValueError("profile must be PlaybackProfile")
        rate, expected_samples, expected_bytes = _PROFILE_SPEC[self.profile]
        if self.format != AudioFormat(rate, 1, AudioEncoding.PCM_S16LE):
            raise ValueError(f"format does not match profile {self.profile.value}")
        require_finite(self.frame_duration_ms, "frame_duration_ms", minimum=0.01)
        require_strict_int(self.sample_count, "sample_count", minimum=expected_samples, maximum=expected_samples)
        require_strict_int(self.valid_sample_count, "valid_sample_count", minimum=0, maximum=self.sample_count)
        if not self.terminal and self.valid_sample_count != expected_samples:
            raise ValueError("Non-terminal frame must contain full valid samples")
        if not isinstance(self.payload, bytes) or len(self.payload) != expected_bytes:
            raise ValueError(f"RenderedFrame payload must be {expected_bytes} immutable bytes")

    def __repr__(self) -> str:
        return (
            f"RenderedFrame(profile={self.profile.value}, seq={self.sequence}, "
            f"valid={self.valid_sample_count}/{self.sample_count}, terminal={self.terminal})"
        )


@dataclass(frozen=True, slots=True)
class PlaybackEvent:
    envelope: EventEnvelope
    kind: PlaybackEventKind
    generation_ref: GenerationRef
    observation_scope: ObservationScope = ObservationScope.UNKNOWN
    queue_depth: int | None = None
    sample_progress: int | None = None
    error: ErrorInfo | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, EventEnvelope):
            raise TypeError("envelope must be EventEnvelope")
        if not isinstance(self.kind, PlaybackEventKind):
            raise ValueError("kind must be PlaybackEventKind")
        if not isinstance(self.generation_ref, GenerationRef):
            raise TypeError("generation_ref must be GenerationRef")
        if not isinstance(self.observation_scope, ObservationScope):
            raise ValueError("observation_scope must be ObservationScope")
        if self.queue_depth is not None:
            require_strict_int(self.queue_depth, "queue_depth", minimum=0)
        if self.sample_progress is not None:
            require_strict_int(self.sample_progress, "sample_progress", minimum=0)

    @property
    def confirms_endpoint_audible(self) -> bool:
        return self.observation_scope == ObservationScope.ENDPOINT and self.kind in {
            PlaybackEventKind.PLAYBACK_STARTED,
            PlaybackEventKind.COMPLETED,
        }
