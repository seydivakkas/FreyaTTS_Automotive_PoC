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
import random
from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class CodecKind(StrEnum):
    PCM16_8K = "PCM16_8K"
    PCM16_16K = "PCM16_16K"
    G711_PCMA = "G711_PCMA"
    G711_PCMU = "G711_PCMU"
    G722_64K = "G722_64K"
    OPUS_MONO = "OPUS_MONO"


class CodecCapabilityStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNSUPPORTED = "UNSUPPORTED"
    HOLD = "HOLD"


@dataclass(frozen=True, slots=True)
class CodecCapability:
    codec: CodecKind
    pcm_rate_hz: int
    rtp_clock_hz: int | None
    frame_duration_ms: float
    pcm_samples_per_frame: int
    status: CodecCapabilityStatus
    reason: str


@dataclass(frozen=True, slots=True)
class CodecTrialSpec:
    trial_id: str
    codec: CodecKind
    loss_rate: float = 0.0
    seed: int = 9


@dataclass(frozen=True, slots=True)
class CodecTrialResult:
    trial_id: str
    codec: CodecKind
    capability_status: CodecCapabilityStatus
    input_samples: int
    encoded_bytes: int | None
    decoded_samples: int | None
    dropped_frames: int
    total_frames: int
    snr_db: float | None
    rms_dbfs: float | None
    live_transport_untouched: bool = True
    reason: str = "OK"


_CAPABILITIES: dict[CodecKind, CodecCapability] = {
    CodecKind.PCM16_8K: CodecCapability(
        codec=CodecKind.PCM16_8K,
        pcm_rate_hz=8000,
        rtp_clock_hz=None,
        frame_duration_ms=20.0,
        pcm_samples_per_frame=160,
        status=CodecCapabilityStatus.VERIFIED,
        reason="AUDIOSOCKET_LINEAR_PCM16_BASELINE",
    ),
    CodecKind.PCM16_16K: CodecCapability(
        codec=CodecKind.PCM16_16K,
        pcm_rate_hz=16000,
        rtp_clock_hz=None,
        frame_duration_ms=20.0,
        pcm_samples_per_frame=320,
        status=CodecCapabilityStatus.VERIFIED,
        reason="WEB_LINEAR_PCM16_BASELINE",
    ),
    CodecKind.G711_PCMA: CodecCapability(
        codec=CodecKind.G711_PCMA,
        pcm_rate_hz=8000,
        rtp_clock_hz=8000,
        frame_duration_ms=20.0,
        pcm_samples_per_frame=160,
        status=CodecCapabilityStatus.VERIFIED,
        reason="ITUT_G711_ALAW_NUMPY",
    ),
    CodecKind.G711_PCMU: CodecCapability(
        codec=CodecKind.G711_PCMU,
        pcm_rate_hz=8000,
        rtp_clock_hz=8000,
        frame_duration_ms=20.0,
        pcm_samples_per_frame=160,
        status=CodecCapabilityStatus.VERIFIED,
        reason="ITUT_G711_ULAW_NUMPY",
    ),
    CodecKind.G722_64K: CodecCapability(
        codec=CodecKind.G722_64K,
        pcm_rate_hz=16000,
        rtp_clock_hz=8000,  # RFC 3551 section 4.5.2
        frame_duration_ms=20.0,
        pcm_samples_per_frame=320,
        status=CodecCapabilityStatus.UNSUPPORTED,
        reason="NATIVE_G722_CODEC_NOT_INSTALLED",
    ),
    CodecKind.OPUS_MONO: CodecCapability(
        codec=CodecKind.OPUS_MONO,
        pcm_rate_hz=48000,
        rtp_clock_hz=48000,  # RFC 7587 section 4.1
        frame_duration_ms=20.0,
        pcm_samples_per_frame=960,
        status=CodecCapabilityStatus.UNSUPPORTED,
        reason="NATIVE_OPUS_CODEC_NOT_INSTALLED",
    ),
}


def get_codec_capability(codec: CodecKind) -> CodecCapability:
    return _CAPABILITIES[codec]


def encode_ulaw_pcm16(pcm16: np.ndarray) -> bytes:
    """ITU-T G.711 mu-law encoding from int16 PCM."""
    samples = np.asarray(pcm16, dtype=np.int16).astype(np.int32)
    bias = 0x84
    clip = 32635
    sign = np.where(samples < 0, 0x80, 0x00)
    mag = np.minimum(np.abs(samples), clip) + bias
    exp = np.zeros_like(mag)
    for e in range(7, 0, -1):
        mask = mag >= (1 << (e + 7))
        exp = np.where((exp == 0) & mask, e, exp)
    mant = (mag >> (exp + 3)) & 0x0F
    ulaw = (~(sign | (exp << 4) | mant)) & 0xFF
    return ulaw.astype(np.uint8).tobytes()


def decode_ulaw_pcm16(data: bytes) -> np.ndarray:
    """ITU-T G.711 mu-law decoding to int16 PCM."""
    u = (~np.frombuffer(data, dtype=np.uint8)).astype(np.int32)
    sign = u & 0x80
    exp = (u >> 4) & 0x07
    mant = u & 0x0F
    mag = ((mant << 3) + 0x84) << exp
    mag -= 0x84
    pcm = np.where(sign != 0, -mag, mag)
    return np.clip(pcm, -32768, 32767).astype(np.int16)


def encode_alaw_pcm16(pcm16: np.ndarray) -> bytes:
    """ITU-T G.711 A-law encoding from int16 PCM."""
    samples = np.asarray(pcm16, dtype=np.int16).astype(np.int32)
    sign = np.where(samples >= 0, 0x80, 0x00)
    mag = np.minimum(np.abs(samples), 32767)
    exp = np.zeros_like(mag)
    for e in range(7, 0, -1):
        mask = mag >= (1 << (e + 7))
        exp = np.where((exp == 0) & mask, e, exp)
    mant = np.where(exp == 0, (mag >> 4) & 0x0F, (mag >> (exp + 3)) & 0x0F)
    alaw = (sign | (exp << 4) | mant) ^ 0x55
    return (alaw & 0xFF).astype(np.uint8).tobytes()


def decode_alaw_pcm16(data: bytes) -> np.ndarray:
    """ITU-T G.711 A-law decoding to int16 PCM."""
    a = (np.frombuffer(data, dtype=np.uint8).astype(np.int32)) ^ 0x55
    sign = a & 0x80
    exp = (a >> 4) & 0x07
    mant = a & 0x0F
    mag = np.where(exp == 0, (mant << 4) + 8, ((mant << 3) + 0x84) << (exp - 1))
    pcm = np.where(sign != 0, mag, -mag)
    return np.clip(pcm, -32768, 32767).astype(np.int16)


class CodecTrial:
    """
    Isolated offline codec evaluation seam.
    Never writes to live AudioSocket or Web transports and never emits PlaybackEvents.
    """

    def run(self, pcm16_samples: np.ndarray, spec: CodecTrialSpec) -> CodecTrialResult:
        cap = get_codec_capability(spec.codec)
        arr = np.asarray(pcm16_samples, dtype=np.int16)
        if cap.status != CodecCapabilityStatus.VERIFIED:
            return CodecTrialResult(
                trial_id=spec.trial_id,
                codec=spec.codec,
                capability_status=cap.status,
                input_samples=int(arr.size),
                encoded_bytes=None,
                decoded_samples=None,
                dropped_frames=0,
                total_frames=0,
                snr_db=None,
                rms_dbfs=None,
                live_transport_untouched=True,
                reason=cap.reason,
            )

        spf = cap.pcm_samples_per_frame
        n_frames = arr.size // spf
        trimmed = arr[: n_frames * spf]
        rng = random.Random(spec.seed)
        encoded_total = 0
        decoded_chunks: list[np.ndarray] = []
        dropped = 0

        for idx in range(n_frames):
            frame = trimmed[idx * spf : (idx + 1) * spf]
            if spec.codec == CodecKind.G711_PCMU:
                enc = encode_ulaw_pcm16(frame)
            elif spec.codec == CodecKind.G711_PCMA:
                enc = encode_alaw_pcm16(frame)
            else:
                enc = frame.astype("<i2").tobytes()
            encoded_total += len(enc)

            if spec.loss_rate > 0.0 and rng.random() < spec.loss_rate:
                dropped += 1
                decoded_chunks.append(np.zeros(spf, dtype=np.int16))
            else:
                if spec.codec == CodecKind.G711_PCMU:
                    decoded_chunks.append(decode_ulaw_pcm16(enc))
                elif spec.codec == CodecKind.G711_PCMA:
                    decoded_chunks.append(decode_alaw_pcm16(enc))
                else:
                    decoded_chunks.append(np.frombuffer(enc, dtype="<i2"))

        decoded = np.concatenate(decoded_chunks) if decoded_chunks else np.zeros(0, dtype=np.int16)
        ref_f = trimmed.astype(np.float64) / 32768.0
        dec_f = decoded.astype(np.float64) / 32768.0
        sig_pow = float(np.mean(np.square(ref_f))) if ref_f.size else 0.0
        err_pow = float(np.mean(np.square(ref_f - dec_f))) if ref_f.size else 0.0
        snr_db = 10.0 * math.log10((sig_pow + 1e-12) / (err_pow + 1e-12)) if ref_f.size else None
        rms_dbfs = 10.0 * math.log10(float(np.mean(np.square(dec_f))) + 1e-12) if dec_f.size else None

        return CodecTrialResult(
            trial_id=spec.trial_id,
            codec=spec.codec,
            capability_status=cap.status,
            input_samples=int(trimmed.size),
            encoded_bytes=encoded_total,
            decoded_samples=int(decoded.size),
            dropped_frames=dropped,
            total_frames=n_frames,
            snr_db=snr_db,
            rms_dbfs=rms_dbfs,
            live_transport_untouched=True,
            reason="TRIAL_COMPLETED",
        )
