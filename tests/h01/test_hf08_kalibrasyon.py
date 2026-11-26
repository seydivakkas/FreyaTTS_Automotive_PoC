# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz
import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from backend.session import VoiceSession


@pytest.mark.asyncio
@pytest.mark.parametrize("calibration_finishes", [False, True])
async def test_HF08_calibration_does_not_drop_pcm(calibration_finishes):
    """Sentetik PCM, kalibrasyon sürerken ve biterken bölüm/STT yoluna ulaşır."""
    session = VoiceSession.__new__(VoiceSession)
    session.closed = False
    session.input_buffer = b""
    session.is_calibrating = True
    session._calibration_event = asyncio.Event()
    session.task = None
    session.recording = None
    collected, events, processed = [], [], []
    audio = np.full(1600, 4096, dtype="<i2")

    class Denoiser:
        enabled = True

        def feed_calibration_bytes(self, raw, sample_rate):
            collected.append(raw)
            return calibration_finishes

        def finish_calibration(self):
            return {"calibrated": True}

        def process_bytes(self, raw, sample_rate):
            return raw

    class Resampler:
        def resample_chunk(self, samples):
            return samples

    class Endpoint:
        last_voice_at = 0.0

        def feed(self, samples):
            return False, [samples]

    async def emit(event):
        events.append(event)

    async def process(samples, speech_end):
        processed.append(samples.copy())

    session.car_denoiser = Denoiser()
    session.resampler = Resampler()
    session.endpoint = Endpoint()
    session.emit = emit
    session.process = process
    await session.input(audio.tobytes(), 16000)
    assert collected == [audio.tobytes()]
    assert session.task is not None
    await asyncio.wait_for(session.task, timeout=1)
    np.testing.assert_array_equal(processed[0], audio.astype(np.float32) / 32768)
    assert session.is_calibrating is not calibration_finishes
    assert session._calibration_event.is_set() is calibration_finishes
    assert bool(events) is calibration_finishes
