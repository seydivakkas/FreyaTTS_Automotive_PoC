"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from enum import StrEnum

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, ContractVersion, StreamRef
from backend.core.contracts.validation import freeze_value, require_strict_int


class AudioEncoding(StrEnum):
    PCM_S16LE = "PCM_S16LE"
    FLOAT32_LE = "FLOAT32_LE"


_BYTES_PER_SAMPLE = {
    AudioEncoding.PCM_S16LE: 2,
    AudioEncoding.FLOAT32_LE: 4,
}
_SUPPORTED_RATES = frozenset({8000, 16000, 24000, 44100, 48000})


@dataclass(frozen=True, slots=True)
class AudioFormat:
    sample_rate_hz: int
    channels: int
    encoding: AudioEncoding

    def __post_init__(self) -> None:
        require_strict_int(self.sample_rate_hz, "sample_rate_hz", minimum=1, maximum=192000)
        if self.sample_rate_hz not in _SUPPORTED_RATES:
            raise ValueError(f"Unsupported sample_rate_hz: {self.sample_rate_hz}")
        require_strict_int(self.channels, "channels", minimum=1, maximum=8)
        if not isinstance(self.encoding, AudioEncoding):
            raise ValueError("encoding must be AudioEncoding")

    @property
    def bytes_per_sample(self) -> int:
        return _BYTES_PER_SAMPLE[self.encoding]

    @property
    def bytes_per_frame(self) -> int:
        return self.channels * self.bytes_per_sample


@dataclass(frozen=True, slots=True)
class AudioFrame:
    schema_version: str
    stream_ref: StreamRef
    sequence: int
    format: AudioFormat
    sample_count: int
    sample_offset: int
    payload: bytes
    captured_monotonic_ns: int | None = None
    clock_domain: str | None = None
    valid_sample_count: int | None = None
    flags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        ContractVersion.parse(self.schema_version)
        if not isinstance(self.stream_ref, StreamRef):
            raise TypeError("stream_ref must be StreamRef")
        require_strict_int(self.sequence, "sequence", minimum=0)
        if not isinstance(self.format, AudioFormat):
            raise TypeError("format must be AudioFormat")
        require_strict_int(self.sample_count, "sample_count", minimum=1, maximum=192000 * 60)
        require_strict_int(self.sample_offset, "sample_offset", minimum=0)
        if not isinstance(self.payload, bytes):
            raise TypeError("payload must be immutable bytes")
        if self.format.encoding == AudioEncoding.PCM_S16LE and len(self.payload) % 2 != 0:
            raise ValueError("PCM_S16LE payload cannot have odd byte length")
        expected_bytes = self.sample_count * self.format.bytes_per_frame
        if len(self.payload) != expected_bytes:
            raise ValueError(f"payload bytes {len(self.payload)} != expected {expected_bytes}")
        if self.format.encoding == AudioEncoding.FLOAT32_LE:
            count = len(self.payload) // 4
            values = struct.unpack(f"<{count}f", self.payload)
            if not all(math.isfinite(v) for v in values):
                raise ValueError("FLOAT32_LE payload contains non-finite values")
        if self.captured_monotonic_ns is not None:
            require_strict_int(self.captured_monotonic_ns, "captured_monotonic_ns", minimum=0)
            if not isinstance(self.clock_domain, str) or not self.clock_domain.strip():
                raise ValueError("clock_domain required when captured_monotonic_ns is supplied")
        if self.valid_sample_count is not None:
            require_strict_int(self.valid_sample_count, "valid_sample_count", minimum=0, maximum=self.sample_count)
        object.__setattr__(self, "flags", freeze_value(frozenset(self.flags)))

    def __repr__(self) -> str:
        return (
            f"AudioFrame(stream={self.stream_ref.stream_id!r}, seq={self.sequence}, "
            f"rate={self.format.sample_rate_hz}, samples={self.sample_count}, bytes={len(self.payload)})"
        )
