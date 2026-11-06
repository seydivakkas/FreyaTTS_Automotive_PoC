"""Only mock frames; NOT a voice model or acoustic test."""
from automotive_voice.ports.contracts import AudioChunk, AudioFormat
import struct

class FakeTTS:
    async def synthesize(self, text: str, generation_id: int):
        fmt = AudioFormat(sample_rate=48000,channels=1,sample_width_bits=32,encoding="float32")
        for seq, _token in enumerate(text.split()):
            # Exactly 10 ms of synthetic silence. No model inference and no speech.
            payload = struct.pack("<" + "f" * 480, *([0.0] * 480))
            yield AudioChunk(generation_id=generation_id,seq=seq,payload=payload,audio_format=fmt)

class FakeMediaOutput:
    def __init__(self):
        self.items: list[AudioChunk] = []
        self.flush_count = 0

    async def enqueue(self, chunk: AudioChunk) -> None:
        self.items.append(chunk)

    async def flush(self) -> None:
        self.items.clear()
        self.flush_count += 1
