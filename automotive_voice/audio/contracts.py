"""M06 metadata-only media contracts. No audio synthesis, decoding, or sockets.

RTP clock for G.722 is 8000 but decoded sample rate is 16000. G.722 is
negotiation metadata only: packetization/byte validation requires a real codec
implementation in the final acceptance phase.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from uuid import UUID
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId
from automotive_voice.core.audio import AudioFormat

class Codec(str, Enum):
    PCM_S16LE = 'pcm_s16le'
    ALAW = 'alaw'
    MULAW = 'mulaw'
    G722 = 'g722'

@dataclass(frozen=True, slots=True)
class MediaFormat:
    codec: Codec
    sample_rate_hz: int
    channels: int = 1
    rtp_clock_hz: int | None = None

    def __post_init__(self):
        if not isinstance(self.codec, Codec) or type(self.sample_rate_hz) is not int or self.channels != 1 or type(self.channels) is not int:
            raise ValueError('invalid media format')
        if self.codec == Codec.G722:
            if self.sample_rate_hz != 16000 or self.rtp_clock_hz != 8000:
                raise ValueError('G.722 requires 16k decoded / 8k RTP clock; metadata-only')
        else:
            encoding = self.codec.value
            AudioFormat(self.sample_rate_hz, self.channels, 16 if encoding == 'pcm_s16le' else 8, encoding)
            if self.rtp_clock_hz is not None and self.rtp_clock_hz != self.sample_rate_hz:
                raise ValueError('RTP clock mismatch')

    @property
    def payload_supported(self) -> bool:
        return self.codec != Codec.G722

    def expected_bytes(self, sample_count: int) -> int | None:
        if type(sample_count) is not int or sample_count <= 0:
            raise ValueError('sample_count must be positive')
        return None if not self.payload_supported else sample_count * (2 if self.codec == Codec.PCM_S16LE else 1)

    def safe_metadata(self) -> dict:
        return dict(codec=self.codec.value, sample_rate_hz=self.sample_rate_hz,
                    channels=self.channels, rtp_clock_hz=self.rtp_clock_hz)

@dataclass(frozen=True, slots=True)
class AudioChunkMetadata:
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    stream_id: str
    seq: int
    sample_count: int
    duration_ms: int
    timestamp_mono_ns: int
    fmt: MediaFormat
    clause_index: int

    def __post_init__(self):
        if not all((isinstance(self.session_id, SessionId), isinstance(self.turn_id, TurnId),
                    isinstance(self.generation_id, GenerationId), isinstance(self.fmt, MediaFormat))):
            raise TypeError('strong ids and MediaFormat required')
        if not isinstance(self.stream_id, str) or not (1 <= len(self.stream_id) <= 128) or not self.stream_id.isascii() or not all(c.isalnum() or c in '._:-' for c in self.stream_id):
            raise ValueError('unsafe stream ID')
        for name in ('seq','sample_count','duration_ms','timestamp_mono_ns','clause_index'):
            v = getattr(self,name)
            if type(v) is not int or v < (1 if name in ('sample_count','duration_ms') else 0):
                raise ValueError('invalid '+name)
        if self.duration_ms > 2000 or self.sample_count * 1000 != self.fmt.sample_rate_hz * self.duration_ms:
            raise ValueError('inconsistent chunk sample_count/duration; no fractional samples')

    def safe_metadata(self) -> dict:
        return {'session_id':str(self.session_id), 'turn_id':int(self.turn_id),
                'generation_id':int(self.generation_id), 'stream_id':self.stream_id,
                'seq':self.seq,'sample_count':self.sample_count,'duration_ms':self.duration_ms,
                'timestamp_mono_ns':self.timestamp_mono_ns,'clause_index':self.clause_index,
                'media_format':self.fmt.safe_metadata()}

@dataclass(frozen=True, slots=True)
class FlushRequest:
    flush_request_id: str
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId  # NEW generation after M02 interrupt

    def __post_init__(self):
        try: UUID(self.flush_request_id)
        except (TypeError, ValueError, AttributeError) as exc: raise ValueError('flush_request_id must be UUID') from exc
        if not (isinstance(self.session_id,SessionId) and isinstance(self.turn_id,TurnId) and isinstance(self.generation_id,GenerationId)):
            raise TypeError('strong identifiers required')

@dataclass(frozen=True, slots=True)
class FlushAck:
    flush_request_id: str
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    adapter_id: str
    confirmed_by_adapter: bool
    adapter_kind: str = 'fake'  # 'fake' NEVER means PBX confirmed

    def __post_init__(self):
        try: UUID(self.flush_request_id)
        except (ValueError, TypeError, AttributeError) as exc: raise ValueError('invalid ACK UUID') from exc
        if not (isinstance(self.session_id, SessionId) and isinstance(self.turn_id,TurnId) and isinstance(self.generation_id,GenerationId)):
            raise TypeError('strong identifiers required')
        if not self.adapter_id or not self.adapter_id.isascii() or len(self.adapter_id) > 64:
            raise ValueError('invalid adapter identifier')
        if type(self.confirmed_by_adapter) is not bool or self.adapter_kind not in ('fake','asterisk'):
            raise ValueError('invalid ACK provenance')

    @property
    def real_pbx_proven(self) -> bool:
        return False  # No real network in M06, not even for a fake 'asterisk' claim
