"""Konuşma sahte DTMF tuşu üretmemeli; sahte tuş randevu onaylayabilir."""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from backend.audio import resample
from backend.dtmf import DIGIT_TO_FREQS, GoertzelDetector, generate_dtmf_tone

RATE = 16000
ROOT = Path(__file__).resolve().parents[1]
# Eski eşiklerle sahte tuş üreten gerçek TTS kayıtları (A, 2A, *, A).
SPEECH_CLIPS = ["XCA03", "XCA15", "XCA17", "XCL12"]


def _detect(wave):
    digits, _ = GoertzelDetector(sample_rate=RATE).process_samples(wave.astype(np.float32))
    return digits


@pytest.mark.parametrize("clip", SPEECH_CLIPS)
def test_recorded_speech_produces_no_digits(clip):
    path = ROOT / "data" / "acoustic" / "audio" / f"{clip}_48k.wav"
    if not path.exists():
        pytest.skip("Ölçüm kaydı yok; scripts.acoustic_benchmark --all üretir")
    wave, rate = sf.read(path, dtype="float32")
    assert _detect(resample(wave, rate, RATE)) == []


def test_harmonic_voice_like_signal_produces_no_digits():
    t = np.arange(RATE) / RATE
    wave = sum(0.25 / k * np.sin(2 * np.pi * 280.0 * k * t) for k in range(1, 8))
    assert _detect(wave) == []


@pytest.mark.parametrize("digit", sorted(DIGIT_TO_FREQS))
@pytest.mark.parametrize("duration_ms", [40, 80, 120])
@pytest.mark.parametrize("amplitude", [0.05, 0.5])
def test_real_tones_are_still_detected(digit, duration_ms, amplitude):
    tone = generate_dtmf_tone(digit, duration_ms / 1000, RATE, amplitude)
    silence = np.zeros(320, dtype=np.float32)
    assert _detect(np.concatenate([silence, tone, silence, silence])) == [digit]
