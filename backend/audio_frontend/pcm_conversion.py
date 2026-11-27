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
from typing import Literal

import numpy as np

from backend.core.contracts.audio import AudioEncoding, AudioFormat


@dataclass(frozen=True, slots=True)
class ConversionStats:
    """Accounting of input/output clipping, overrange saturation, and channel downmix."""

    input_clipped_samples: int = 0
    output_clipped_samples: int = 0
    overrange_samples: int = 0
    downmixed_from_channels: int = 1


def copy_ingress_bytes(data: bytes | bytearray | memoryview | np.ndarray) -> bytes:
    """Copy mutable ingress buffers into immutable owned bytes at the ownership seam."""
    if isinstance(data, bytes):
        return data
    if isinstance(data, (bytearray, memoryview)):
        return bytes(data)
    if isinstance(data, np.ndarray):
        return np.ascontiguousarray(data).tobytes()
    raise TypeError(f"Unsupported ingress buffer type: {type(data).__name__}")


def decode_to_float32(
    payload: bytes,
    fmt: AudioFormat,
    *,
    overrange_policy: Literal["reject", "saturate"] = "saturate",
) -> tuple[np.ndarray, ConversionStats]:
    """
    Decode validated little-endian audio bytes into an owned mono float32 array in [-1.0, 1.0].

    PCM_S16LE uses exact x / 32768.0 scaling:
      -32768 -> -1.0, 32767 -> 32767/32768.0, 0 -> 0.0.
    Stereo downmix (when fmt.channels == 2) computes saturation-safe float32 mean (L + R) * 0.5.
    """
    if not isinstance(payload, bytes):
        raise TypeError("payload must be immutable bytes")

    if fmt.encoding == AudioEncoding.PCM_S16LE:
        if len(payload) % 2 != 0:
            raise ValueError("Odd PCM_S16LE payload byte length")
        i16 = np.frombuffer(payload, dtype="<i2")
        input_clipped = int(np.count_nonzero((i16 == -32768) | (i16 == 32767)))
        arr = i16.astype(np.float32) / np.float32(32768.0)
        overrange = 0
        output_clipped = 0
    elif fmt.encoding == AudioEncoding.FLOAT32_LE:
        if len(payload) % 4 != 0:
            raise ValueError("FLOAT32_LE payload must be multiple of 4 bytes")
        raw = np.frombuffer(payload, dtype="<f4").copy()
        if not np.isfinite(raw).all():
            raise ValueError("FLOAT32_LE payload contains NaN or Inf")
        overrange_mask = np.abs(raw) > 1.0
        overrange = int(np.count_nonzero(overrange_mask))
        if overrange > 0 and overrange_policy == "reject":
            raise ValueError("FLOAT32_LE sample exceeds [-1.0, 1.0] under reject policy")
        arr = np.clip(raw, -1.0, 1.0).astype(np.float32)
        input_clipped = int(np.count_nonzero(np.abs(raw) >= (1.0 - 1e-6)))
        output_clipped = overrange
    else:
        raise ValueError(f"Unsupported encoding: {fmt.encoding}")

    if fmt.channels == 1:
        return np.ascontiguousarray(arr, dtype=np.float32), ConversionStats(
            input_clipped_samples=input_clipped,
            output_clipped_samples=output_clipped,
            overrange_samples=overrange,
            downmixed_from_channels=1,
        )

    if fmt.channels == 2:
        if len(arr) % 2 != 0:
            raise ValueError("Stereo sample count must be even interleaved")
        stereo = arr.reshape(-1, 2)
        mono = np.clip((stereo[:, 0] + stereo[:, 1]) * np.float32(0.5), -1.0, 1.0).astype(np.float32)
        return np.ascontiguousarray(mono, dtype=np.float32), ConversionStats(
            input_clipped_samples=input_clipped,
            output_clipped_samples=output_clipped,
            overrange_samples=overrange,
            downmixed_from_channels=2,
        )

    raise ValueError(f"Unsupported channel count for decode: {fmt.channels}")


def encode_from_float32(
    samples: np.ndarray,
    target_encoding: AudioEncoding,
) -> tuple[bytes, int]:
    """
    Encode finite mono float32 samples into immutable target bytes.

    Documented quantization for PCM_S16LE:
      - Finite check before conversion.
      - Saturate float samples to [-1.0, 1.0].
      - Deterministic round-to-nearest-even via np.rint(clipped * 32768.0),
        clamped strictly to [-32768, 32767] so no integer wrap occurs and
        all 65,536 int16 codes round-trip cleanly with decode_to_float32.
    Returns (immutable_bytes, output_clipped_samples).
    """
    arr = np.asarray(samples, dtype=np.float32)
    if arr.ndim != 1:
        raise ValueError("encode_from_float32 expects 1D mono array")
    if len(arr) > 0 and not np.isfinite(arr).all():
        raise ValueError("Non-finite float32 samples cannot be encoded")

    clipped_mask = np.abs(arr) > 1.0
    clipped_count = int(np.count_nonzero(clipped_mask))

    if target_encoding == AudioEncoding.FLOAT32_LE:
        out_arr = np.clip(arr, -1.0, 1.0).astype("<f4")
        return np.ascontiguousarray(out_arr).tobytes(), clipped_count

    if target_encoding == AudioEncoding.PCM_S16LE:
        sat = np.clip(arr, -1.0, 1.0)
        scaled = np.rint(sat * np.float32(32768.0))
        i16 = np.clip(scaled, -32768.0, 32767.0).astype("<i2")
        return np.ascontiguousarray(i16).tobytes(), clipped_count

    raise ValueError(f"Unsupported target encoding: {target_encoding}")
