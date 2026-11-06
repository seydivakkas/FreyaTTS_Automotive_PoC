"""Backward-compatible mock TTS ports; M01 canonical AudioFormat lives in core."""
from dataclasses import dataclass
from typing import AsyncIterator, Protocol
from automotive_voice.core.audio import AudioFormat

@dataclass(frozen=True)
class AudioChunk:
    generation_id: int
    seq: int
    payload: bytes
    audio_format: AudioFormat

class TTSPort(Protocol):
    async def synthesize(self, text: str, generation_id: int) -> AsyncIterator[AudioChunk]: ...

class MediaOutput(Protocol):
    async def enqueue(self, chunk: AudioChunk) -> None: ...
    async def flush(self) -> None: ...
