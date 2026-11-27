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


class StreamingOutputResampler:
    """
    Stateful per-stream/epoch/generation CPU output resampler (48000 -> 16000 or 8000 Hz)
    backed by `soxr.ResampleStream` with rational phase/count accounting and once-only EOS flush.

    Never shares mutable state across sessions or with F0 input resamplers.
    """

    def __init__(self, *, input_rate_hz: int = 48000, output_rate_hz: int = 16000, quality: str = "HQ") -> None:
        if input_rate_hz != 48000:
            raise ValueError("Output resampler input_rate_hz must be 48000")
        if output_rate_hz not in (8000, 16000):
            raise ValueError("Output resampler output_rate_hz must be 8000 or 16000")
        self.input_rate_hz = input_rate_hz
        self.output_rate_hz = output_rate_hz
        self.quality = quality
        self.ratio = Fraction(output_rate_hz, input_rate_hz)
        self._stream = soxr.ResampleStream(
            input_rate_hz,
            output_rate_hz,
            num_channels=1,
            dtype="float32",
            quality=quality,
        )
        self._input_samples = 0
        self._emitted_samples = 0
        self._flushed = False
        self._aborted = False

    @property
    def input_samples(self) -> int:
        return self._input_samples

    @property
    def emitted_samples(self) -> int:
        return self._emitted_samples

    @property
    def flushed(self) -> bool:
        return self._flushed

    @property
    def aborted(self) -> bool:
        return self._aborted

    @property
    def expected_total_output_exact(self) -> Fraction:
        return self._input_samples * self.ratio

    @property
    def expected_total_output_rounded(self) -> int:
        # Rational round-half-to-even over the full continuous span
        return int(round(self.expected_total_output_exact))

    @property
    def pending_delay_samples_48k(self) -> int:
        """Approximate buffered 48k input samples not yet reflected in emitted output."""
        accounted_in = int(Fraction(self._emitted_samples, 1) / self.ratio)
        return max(0, self._input_samples - accounted_in)

    def process_chunk(self, samples_48k: np.ndarray) -> np.ndarray:
        """Process a contiguous 48 kHz float32 chunk preserving internal filter history."""
        if self._aborted:
            raise RuntimeError("Cannot push samples into aborted StreamingOutputResampler")
        if self._flushed:
            raise RuntimeError("Cannot push samples after EOS flush on StreamingOutputResampler")
        arr = np.asarray(samples_48k, dtype=np.float32)
        if arr.ndim != 1:
            raise ValueError("Resampler input must be 1D float32 array")
        if arr.size == 0:
            return np.zeros(0, dtype=np.float32)
        if not bool(np.isfinite(arr).all()):
            raise ValueError("Resampler input contains non-finite values")
        self._input_samples += int(arr.size)
        out = self._stream.resample_chunk(arr, last=False)
        out_f32 = np.asarray(out, dtype=np.float32).reshape(-1)
        self._emitted_samples += int(out_f32.size)
        return out_f32

    def flush_eos(self) -> np.ndarray:
        """Flush buffered resampler tail exactly once at authorized EOS."""
        if self._aborted:
            return np.zeros(0, dtype=np.float32)
        if self._flushed:
            return np.zeros(0, dtype=np.float32)
        self._flushed = True
        tail = self._stream.resample_chunk(np.zeros(0, dtype=np.float32), last=True)
        tail_f32 = np.asarray(tail, dtype=np.float32).reshape(-1)
        self._emitted_samples += int(tail_f32.size)
        return tail_f32

    def abort_discard(self) -> int:
        """Abort resampler without flushing stale tail; returns discarded input-domain sample estimate."""
        if self._aborted:
            return 0
        discarded = self.pending_delay_samples_48k if not self._flushed else 0
        self._aborted = True
        self._flushed = True
        return discarded

    def reset(self) -> None:
        """Allocate a fresh internal resampler state for a new generation/epoch."""
        self._stream = soxr.ResampleStream(
            self.input_rate_hz,
            self.output_rate_hz,
            num_channels=1,
            dtype="float32",
            quality=self.quality,
        )
        self._input_samples = 0
        self._emitted_samples = 0
        self._flushed = False
        self._aborted = False
