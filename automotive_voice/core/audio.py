"""Strictly typed audio metadata; no codec decode, resampling or real audio."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
from automotive_voice.core.identifiers import SessionId, GenerationId

AudioEncoding = Literal["pcm_s16le", "float32", "alaw", "mulaw"]
_WIDTH = {"pcm_s16le": 16, "float32": 32, "alaw": 8, "mulaw": 8}

@dataclass(frozen=True, slots=True)
class AudioFormat:
    sample_rate: int
    channels: int
    sample_width_bits: int
    encoding: AudioEncoding

    def __post_init__(self) -> None:
        if type(self.sample_rate) is not int or self.sample_rate not in (8000, 16000, 48000):
            raise ValueError("Unsupported sample rate; explicit conversion required")
        if type(self.channels) is not int or self.channels != 1:
            raise ValueError("Only explicit mono audio is supported in M01")
        if self.encoding not in _WIDTH or type(self.sample_width_bits) is not int or self.sample_width_bits != _WIDTH[self.encoding]:
            raise ValueError("Encoding and sample width mismatch")
        if self.encoding in ("alaw", "mulaw") and self.sample_rate != 8000:
            raise ValueError("G.711 A-law/µ-law telephony requires 8 kHz in this contract")

    @property
    def bytes_per_sample(self) -> int:
        return self.sample_width_bits // 8

    def assert_compatible(self, other: "AudioFormat") -> None:
        if self != other:
            raise ValueError("Audio formats differ; caller must explicitly convert")

@dataclass(frozen=True, slots=True)
class AudioFrame:
    session_id: SessionId
    stream_id: str
    generation_id: GenerationId
    seq: int
    sample_count: int
    timestamp_mono_ns: int
    audio_format: AudioFormat
    payload: bytes

    def __post_init__(self) -> None:
        SessionId(self.session_id)
        if not isinstance(self.stream_id, str) or not (1 <= len(self.stream_id) <= 128):
            raise ValueError("stream_id required (<=128 characters)")
        GenerationId(self.generation_id)
        for name in ("seq", "sample_count", "timestamp_mono_ns"):
            val = getattr(self, name)
            if type(val) is not int or val < 0 or (name == "sample_count" and val == 0):
                raise ValueError(f"{name} invalid")
        if not isinstance(self.audio_format, AudioFormat):
            raise TypeError("audio_format must be AudioFormat")
        if not isinstance(self.payload, bytes):
            raise TypeError("payload must be immutable bytes")
        if len(self.payload) != self.sample_count * self.audio_format.channels * self.audio_format.bytes_per_sample:
            raise ValueError("sample_count/payload length mismatch")
