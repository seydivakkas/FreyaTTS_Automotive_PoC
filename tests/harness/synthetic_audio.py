"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
amaçlı olarak paylaşılmıştır.

YASAKLAR:
  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.
  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.
  3. Alt lisanslanamaz, satılamaz veya devredilemez.
  4. Tersine mühendislik yapılamaz.

İZİN VERİLEN KULLANIM:
  - GitHub üzerinde görüntüleme ve okuma.
  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).

YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.
İzin talepleri için: GitHub @seydivakkas
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from enum import StrEnum

from backend.core.contracts.audio import AudioEncoding, AudioFormat, AudioFrame
from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, StreamRef
from backend.observability.evidence import EvidenceKind
from tests.harness.fixture_registry import FixtureCapExceededError, FixtureLimits, local_rng


class AnalyticSignalKind(StrEnum):
    SILENCE = "silence"
    IMPULSE = "impulse"
    SINE = "sine"
    CHIRP = "chirp"
    WHITE_NOISE = "white_noise"
    PINK_NOISE = "pink_noise"
    SPEECH_ENVELOPE = "speech_envelope"
    MOTOR_FAN = "motor_fan"
    CLIPPED = "clipped"
    LOW_LEVEL = "low_level"
    ECHO_SURROGATE = "echo_surrogate"


@dataclass(frozen=True, slots=True)
class SyntheticAudioSegment:
    signal_kind: AnalyticSignalKind
    format: AudioFormat
    sample_count: int
    sample_offset: int
    valid_sample_count: int
    padding_samples: int
    has_gap: bool
    has_overlap: bool
    payload: bytes
    seed: int
    duration_sec: float
    source_class: EvidenceKind = EvidenceKind.SYNTHETIC_FIXTURE
    is_human_speech: bool = False
    acoustic_benchmark_eligible: bool = False
    label_note: str = "ANALYTIC_SYNTHETIC_SIGNAL_NOT_HUMAN_SPEECH"

    def to_audio_frame(
        self,
        stream_ref: StreamRef,
        *,
        sequence: int,
        captured_monotonic_ns: int | None = None,
        clock_domain: str | None = None,
    ) -> AudioFrame:
        flags: set[str] = {"SYNTHETIC_FIXTURE", f"SIGNAL:{self.signal_kind.value}"}
        if self.has_gap:
            flags.add("DISCONTINUITY_GAP")
        if self.has_overlap:
            flags.add("DISCONTINUITY_OVERLAP")
        if self.padding_samples > 0:
            flags.add("FINAL_PADDING")
        return AudioFrame(
            schema_version=CONTRACT_SCHEMA_VERSION,
            stream_ref=stream_ref,
            sequence=sequence,
            format=self.format,
            sample_count=self.sample_count,
            sample_offset=self.sample_offset,
            payload=self.payload,
            captured_monotonic_ns=captured_monotonic_ns,
            clock_domain=clock_domain,
            valid_sample_count=self.valid_sample_count,
            flags=frozenset(flags),
        )


def _generate_normalized_samples(
    kind: AnalyticSignalKind,
    sample_rate_hz: int,
    sample_count: int,
    *,
    seed: int,
    freq_hz: float,
    amplitude: float,
) -> list[float]:
    rng = local_rng(seed)
    samples: list[float] = [0.0] * sample_count
    if kind == AnalyticSignalKind.SILENCE:
        return samples
    if kind == AnalyticSignalKind.IMPULSE:
        samples[0] = amplitude
        return samples
    if kind == AnalyticSignalKind.SINE:
        for i in range(sample_count):
            samples[i] = amplitude * math.sin(2.0 * math.pi * freq_hz * (i / sample_rate_hz))
        return samples
    if kind == AnalyticSignalKind.CHIRP:
        f0 = max(80.0, freq_hz * 0.5)
        f1 = min(sample_rate_hz * 0.45, freq_hz * 3.0)
        dur = sample_count / float(sample_rate_hz)
        for i in range(sample_count):
            t = i / float(sample_rate_hz)
            inst_f = f0 + (f1 - f0) * (t / max(dur, 1e-9)) * 0.5
            samples[i] = amplitude * math.sin(2.0 * math.pi * inst_f * t)
        return samples
    if kind == AnalyticSignalKind.WHITE_NOISE:
        for i in range(sample_count):
            samples[i] = amplitude * (rng.random() * 2.0 - 1.0)
        return samples
    if kind == AnalyticSignalKind.PINK_NOISE:
        # Voss-McCartney style 3-pole leaky integrator approximation
        b0 = b1 = b2 = 0.0
        for i in range(sample_count):
            w = rng.random() * 2.0 - 1.0
            b0 = 0.997 * b0 + w * 0.029
            b1 = 0.985 * b1 + w * 0.032
            b2 = 0.950 * b2 + w * 0.048
            samples[i] = max(-1.0, min(1.0, amplitude * (b0 + b1 + b2 + w * 0.18)))
        return samples
    if kind == AnalyticSignalKind.SPEECH_ENVELOPE:
        for i in range(sample_count):
            t = i / float(sample_rate_hz)
            env = 0.5 * (1.0 - math.cos(2.0 * math.pi * 4.0 * t))
            carrier = 0.65 * math.sin(2.0 * math.pi * 165.0 * t) + 0.35 * math.sin(2.0 * math.pi * 330.0 * t)
            samples[i] = amplitude * env * carrier
        return samples
    if kind == AnalyticSignalKind.MOTOR_FAN:
        for i in range(sample_count):
            t = i / float(sample_rate_hz)
            samples[i] = amplitude * (
                0.7 * math.sin(2.0 * math.pi * 68.0 * t)
                + 0.3 * math.sin(2.0 * math.pi * 136.0 * t)
            )
        return samples
    if kind == AnalyticSignalKind.CLIPPED:
        for i in range(sample_count):
            raw = 1.8 * math.sin(2.0 * math.pi * freq_hz * (i / sample_rate_hz))
            samples[i] = max(-1.0, min(1.0, raw))
        return samples
    if kind == AnalyticSignalKind.LOW_LEVEL:
        low_amp = min(amplitude, 0.005)
        for i in range(sample_count):
            samples[i] = low_amp * math.sin(2.0 * math.pi * freq_hz * (i / sample_rate_hz))
        return samples
    if kind == AnalyticSignalKind.ECHO_SURROGATE:
        delay = max(1, int(0.01 * sample_rate_hz))
        dry = [amplitude * math.sin(2.0 * math.pi * freq_hz * (i / sample_rate_hz)) for i in range(sample_count)]
        for i in range(sample_count):
            echo = 0.45 * dry[i - delay] if i >= delay else 0.0
            samples[i] = max(-1.0, min(1.0, dry[i] + echo))
        return samples
    raise ValueError(f"Unsupported signal kind: {kind}")


def encode_samples(samples: list[float], encoding: AudioEncoding) -> bytes:
    if encoding == AudioEncoding.PCM_S16LE:
        ints = [max(-32768, min(32767, int(round(s * 32767.0)))) for s in samples]
        return struct.pack(f"<{len(ints)}h", *ints)
    if encoding == AudioEncoding.FLOAT32_LE:
        return struct.pack(f"<{len(samples)}f", *samples)
    raise ValueError(f"Unsupported encoding: {encoding}")


def decode_pcm16_le(payload: bytes) -> tuple[int, ...]:
    if len(payload) % 2 != 0:
        raise ValueError("PCM_S16LE payload cannot have odd byte length")
    return struct.unpack(f"<{len(payload) // 2}h", payload)


def decode_float32_le(payload: bytes) -> tuple[float, ...]:
    if len(payload) % 4 != 0:
        raise ValueError("FLOAT32_LE payload must be multiple of 4 bytes")
    vals = struct.unpack(f"<{len(payload) // 4}f", payload)
    if not all(math.isfinite(v) for v in vals):
        raise ValueError("FLOAT32_LE payload contains NaN or Inf")
    return vals


class SyntheticAudioGenerator:
    """Deterministic analytic mono audio fixture generator (never labeled human speech)."""

    def __init__(self, *, limits: FixtureLimits | None = None) -> None:
        self.limits = limits or FixtureLimits()

    def generate(
        self,
        kind: AnalyticSignalKind,
        *,
        sample_rate_hz: int,
        sample_count: int,
        encoding: AudioEncoding = AudioEncoding.PCM_S16LE,
        channels: int = 1,
        seed: int = 0,
        freq_hz: float = 440.0,
        amplitude: float = 0.5,
        sample_offset: int = 0,
        valid_sample_count: int | None = None,
        has_gap: bool = False,
        has_overlap: bool = False,
    ) -> SyntheticAudioSegment:
        fmt = AudioFormat(sample_rate_hz=sample_rate_hz, channels=channels, encoding=encoding)
        if channels != 1:
            raise ValueError("SyntheticAudioGenerator supports mono fixtures only")
        if type(sample_count) is not int or sample_count < 1:
            raise ValueError("sample_count must be positive int")
        if sample_count > self.limits.max_samples_per_fixture:
            raise FixtureCapExceededError(f"sample_count {sample_count} exceeds {self.limits.max_samples_per_fixture}")
        valid_n = sample_count if valid_sample_count is None else valid_sample_count
        if valid_n < 0 or valid_n > sample_count:
            raise ValueError("valid_sample_count out of range")
        padding = sample_count - valid_n
        raw_samples = _generate_normalized_samples(
            kind, sample_rate_hz, valid_n, seed=seed, freq_hz=freq_hz, amplitude=amplitude
        )
        if padding > 0:
            raw_samples.extend([0.0] * padding)
        payload = encode_samples(raw_samples, encoding)
        if len(payload) > self.limits.max_bytes_per_fixture:
            raise FixtureCapExceededError(f"payload bytes {len(payload)} exceeds {self.limits.max_bytes_per_fixture}")
        return SyntheticAudioSegment(
            signal_kind=kind,
            format=fmt,
            sample_count=sample_count,
            sample_offset=sample_offset,
            valid_sample_count=valid_n,
            padding_samples=padding,
            has_gap=has_gap,
            has_overlap=has_overlap,
            payload=payload,
            seed=seed,
            duration_sec=sample_count / float(sample_rate_hz),
        )

    def frame_20ms(
        self,
        kind: AnalyticSignalKind,
        *,
        sample_rate_hz: int,
        encoding: AudioEncoding = AudioEncoding.PCM_S16LE,
        seed: int = 0,
        sample_offset: int = 0,
    ) -> SyntheticAudioSegment:
        samples = (sample_rate_hz * 20) // 1000
        return self.generate(
            kind,
            sample_rate_hz=sample_rate_hz,
            sample_count=samples,
            encoding=encoding,
            seed=seed,
            sample_offset=sample_offset,
        )

    def silero_vad_window_16k(self, kind: AnalyticSignalKind, *, seed: int = 0, sample_offset: int = 0) -> SyntheticAudioSegment:
        """Explicit 512-sample (32 ms) Silero VAD window at 16 kHz, distinct from 20 ms media frames."""
        return self.generate(
            kind,
            sample_rate_hz=16000,
            sample_count=512,
            encoding=AudioEncoding.FLOAT32_LE,
            seed=seed,
            sample_offset=sample_offset,
        )


def validate_audio_frame_contract(
    *,
    sample_rate_hz: int,
    channels: int,
    encoding: AudioEncoding,
    sample_count: int,
    payload: bytes,
    sample_offset: int = 0,
) -> AudioFrame:
    fmt = AudioFormat(sample_rate_hz=sample_rate_hz, channels=channels, encoding=encoding)
    return AudioFrame(
        schema_version=CONTRACT_SCHEMA_VERSION,
        stream_ref=StreamRef("contract-check", "in-0", "INPUT", 0),  # type: ignore[arg-type]
        sequence=0,
        format=fmt,
        sample_count=sample_count,
        sample_offset=sample_offset,
        payload=payload,
    )
