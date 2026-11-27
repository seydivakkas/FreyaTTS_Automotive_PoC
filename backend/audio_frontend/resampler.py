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

from fractions import Fraction
import numpy as np
import soxr


class StatefulResampler:
    """
    Per-stream stateful anti-aliased streaming resampler adapter using SoXR.

    - Supports identity-rate pass-through without redundant filtering.
    - Preserves filter delay/history across arbitrary partition sizes (including 1-sample).
    - Guarantees exact-once EOS flush semantics and zero shared mutable state across instances.
    - Designed as a reusable adapter seam for both F0-A input and future F6 outbound paths.
    """

    def __init__(
        self,
        input_rate_hz: int,
        output_rate_hz: int = 16000,
        *,
        quality: str = "HQ",
    ) -> None:
        if type(input_rate_hz) is not int or input_rate_hz <= 0:
            raise ValueError("input_rate_hz must be positive int")
        if type(output_rate_hz) is not int or output_rate_hz <= 0:
            raise ValueError("output_rate_hz must be positive int")
        self.input_rate_hz = input_rate_hz
        self.output_rate_hz = output_rate_hz
        self.quality = quality
        self.ratio = Fraction(output_rate_hz, input_rate_hz)
        self.is_identity = input_rate_hz == output_rate_hz
        self.backend_name = "identity" if self.is_identity else "soxr"

        self._stream: soxr.ResampleStream | None = None
        if not self.is_identity:
            self._stream = soxr.ResampleStream(
                float(input_rate_hz),
                float(output_rate_hz),
                1,
                dtype="float32",
                quality=quality,
            )

        self.input_samples: int = 0
        self.output_samples: int = 0
        self.flushed: bool = False
        self.closed: bool = False

    def delay_samples(self) -> float:
        """Current approximate output delay samples reported by backend (0.0 for identity)."""
        if self._stream is None:
            return 0.0
        try:
            return float(self._stream.delay())
        except Exception:
            return 0.0

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Resample a finite 1D float32 block without flushing EOS."""
        if self.closed:
            raise RuntimeError("StatefulResampler is closed")
        if self.flushed:
            raise RuntimeError("Cannot push samples after EOS flush without reset")

        arr = np.asarray(samples, dtype=np.float32)
        if arr.ndim != 1:
            raise ValueError("StatefulResampler expects 1D mono array")
        if len(arr) == 0:
            return np.zeros(0, dtype=np.float32)
        if not np.isfinite(arr).all():
            raise ValueError("StatefulResampler received non-finite samples")

        self.input_samples += int(arr.shape[0])
        if self.is_identity:
            out = np.ascontiguousarray(arr.copy(), dtype=np.float32)
            self.output_samples += int(out.shape[0])
            return out

        assert self._stream is not None
        out = self._stream.resample_chunk(np.ascontiguousarray(arr, dtype=np.float32), last=False)
        out_f32 = np.ascontiguousarray(out, dtype=np.float32)
        if len(out_f32) > 0 and not np.isfinite(out_f32).all():
            raise RuntimeError("Resampler produced non-finite output")
        self.output_samples += int(out_f32.shape[0])
        return out_f32

    def flush(self) -> np.ndarray:
        """Flush buffered resampler tail exactly once (idempotent on repeat calls)."""
        if self.closed or self.flushed:
            return np.zeros(0, dtype=np.float32)
        self.flushed = True
        if self.is_identity or self._stream is None:
            return np.zeros(0, dtype=np.float32)
        tail = self._stream.resample_chunk(np.zeros(0, dtype=np.float32), last=True)
        tail_f32 = np.ascontiguousarray(tail, dtype=np.float32)
        if len(tail_f32) > 0 and not np.isfinite(tail_f32).all():
            raise RuntimeError("Resampler EOS flush produced non-finite output")
        self.output_samples += int(tail_f32.shape[0])
        return tail_f32

    def reset(self) -> None:
        """Reset filter delay/state for a new format epoch."""
        if self.closed:
            raise RuntimeError("Cannot reset closed StatefulResampler")
        if not self.is_identity:
            self._stream = soxr.ResampleStream(
                float(self.input_rate_hz),
                float(self.output_rate_hz),
                1,
                dtype="float32",
                quality=self.quality,
            )
        self.input_samples = 0
        self.output_samples = 0
        self.flushed = False

    def close(self) -> None:
        """Release resampler resources."""
        self.closed = True
        self._stream = None
