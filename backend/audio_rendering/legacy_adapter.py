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

from dataclasses import dataclass

import numpy as np

from backend.audio_rendering.dsp_adapter import StatefulLegacyDSPAdapter
from backend.audio_rendering.profile_adapter import QuantizationPolicy
from backend.audio_rendering.quantizer import quantize_float32_to_pcm16le
from backend.audio_rendering.resampler import StreamingOutputResampler


@dataclass(frozen=True, slots=True)
class ShadowComparisonResult:
    """Side-effect-free CPU-only comparison between legacy and strict F6-A rendering."""

    output_rate_hz: int
    legacy_sample_count: int
    strict_sample_count: int
    legacy_rms: float
    strict_rms: float
    rms_diff_db: float | None
    transport_sent: bool = False


def render_legacy_wave_48k_to_pcm(wav_48k: np.ndarray, *, output_rate: int = 8000) -> bytes:
    """
    Preserve exact legacy `VoiceSession.play_wave` PCM conversion without modifying
    `backend/session.py`, `backend/dsp.py`, or `backend/audio.py`.
    """
    from backend.audio import pcm as legacy_pcm
    from backend.audio import resample as legacy_resample
    from backend.dsp import apply_telephony_eq_and_downsample_8k

    arr = np.asarray(wav_48k, dtype=np.float32)
    if output_rate == 8000:
        return apply_telephony_eq_and_downsample_8k(arr).tobytes()
    if output_rate == 16000:
        return legacy_pcm(legacy_resample(arr, 48000, 16000))
    raise ValueError(f"Unsupported legacy output_rate: {output_rate}")


def iter_legacy_frames(pcm_bytes: bytes, *, output_rate: int = 8000) -> list[bytes]:
    """Preserve `backend/audio.py:frames` 20 ms chunking and zero padding."""
    from backend.audio import frames as legacy_frames

    frame_size = 320 if output_rate == 8000 else 640
    return list(legacy_frames(pcm_bytes, size=frame_size))


def build_legacy_audiosocket_packet(frame_bytes: bytes) -> bytes:
    """Preserve `backend/audiosocket_server.py:build_packet(0x10, frame)`."""
    from backend.audiosocket_server import AUDIOSOCKET_AUDIO, build_packet as legacy_build_packet

    return legacy_build_packet(AUDIOSOCKET_AUDIO, frame_bytes)


def compare_legacy_vs_strict(
    wav_48k: np.ndarray,
    *,
    output_rate: int = 8000,
) -> ShadowComparisonResult:
    """
    Bounded CPU-only shadow comparison between legacy rendering and strict F6-A rendering.
    Never writes to any transport, DB, or LLM.
    """
    arr = np.asarray(wav_48k, dtype=np.float32)
    if arr.ndim != 1 or arr.size == 0 or not bool(np.isfinite(arr).all()):
        raise ValueError("Shadow comparison requires non-empty finite 1D float32 array")

    legacy_bytes = render_legacy_wave_48k_to_pcm(arr, output_rate=output_rate)
    legacy_i16 = np.frombuffer(legacy_bytes, dtype="<i2").astype(np.float64) / 32768.0

    dsp = StatefulLegacyDSPAdapter(enabled=(output_rate == 8000))
    resampler = StreamingOutputResampler(input_rate_hz=48000, output_rate_hz=output_rate)
    pre = dsp.process_pre_resample_48k(arr)
    out = np.concatenate([resampler.process_chunk(pre), resampler.flush_eos()])
    if output_rate == 8000:
        out, _ = dsp.process_post_resample_limiter(out)
    q = quantize_float32_to_pcm16le(
        out,
        policy=QuantizationPolicy.SYMMETRIC_32767 if output_rate == 8000 else QuantizationPolicy.SATURATING_32768,
    )
    strict_i16 = np.frombuffer(q.pcm_bytes, dtype="<i2").astype(np.float64) / 32768.0

    l_rms = float(np.sqrt(np.mean(legacy_i16 * legacy_i16))) if legacy_i16.size else 0.0
    s_rms = float(np.sqrt(np.mean(strict_i16 * strict_i16))) if strict_i16.size else 0.0
    diff_db = None
    if l_rms > 1e-12 and s_rms > 1e-12:
        diff_db = float(20.0 * np.log10(s_rms / l_rms))

    return ShadowComparisonResult(
        output_rate_hz=output_rate,
        legacy_sample_count=int(legacy_i16.size),
        strict_sample_count=int(strict_i16.size),
        legacy_rms=l_rms,
        strict_rms=s_rms,
        rms_diff_db=diff_db,
        transport_sent=False,
    )
