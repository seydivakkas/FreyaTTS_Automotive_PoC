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
from scipy import signal


@dataclass(frozen=True, slots=True)
class TelephonyFilterCoefficients:
    """Immutable shared DSP filter coefficients matching `backend/dsp.py`."""

    sample_rate_hz: int
    hp_cutoff_hz: float
    sos_hp: np.ndarray
    b_peak: np.ndarray
    a_peak: np.ndarray
    presence_gain: float
    limiter_drive: float


def build_telephony_coefficients(
    *,
    sample_rate_hz: int = 48000,
    hp_cutoff_hz: float = 120.0,
    presence_freq_hz: float = 3200.0,
    presence_q: float = 1.5,
    presence_gain: float = 0.35,
    limiter_drive: float = 1.15,
) -> TelephonyFilterCoefficients:
    """Build immutable filter coefficients preserving `backend/dsp.py` baseline."""
    nyquist = sample_rate_hz / 2.0
    sos_hp = signal.butter(2, hp_cutoff_hz / nyquist, btype="highpass", output="sos")
    sos_hp.flags.writeable = False
    b_peak, a_peak = signal.iirpeak(presence_freq_hz / nyquist, Q=presence_q)
    b_peak.flags.writeable = False
    a_peak.flags.writeable = False
    return TelephonyFilterCoefficients(
        sample_rate_hz=sample_rate_hz,
        hp_cutoff_hz=hp_cutoff_hz,
        sos_hp=sos_hp,
        b_peak=b_peak,
        a_peak=a_peak,
        presence_gain=presence_gain,
        limiter_drive=limiter_drive,
    )


_DEFAULT_TELEPHONY_COEFFS = build_telephony_coefficients()


class StatefulLegacyDSPAdapter:
    """
    Single-writer per-stream/generation stateful adapter for `backend/dsp.py` stages:
    1. Pre-resample 48 kHz: 2nd-order Butterworth 120 Hz HPF + 3.2 kHz presence boost (+0.35 * iirpeak)
    2. Post-resample 8 kHz: soft peak limiter `tanh(x * 1.15)`

    Preserves exact stage order and defaults of `backend/dsp.py:apply_telephony_eq_and_downsample_8k`.
    Never applies a second fade (upstream F5 `apply_fade_and_comfort_noise` owns utterance boundary fade)
    and never injects comfort noise unless explicitly enabled (disabled by default matching `dsp.py`).
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        coeffs: TelephonyFilterCoefficients = _DEFAULT_TELEPHONY_COEFFS,
        comfort_noise_enabled: bool = False,
    ) -> None:
        if comfort_noise_enabled:
            raise ValueError("F6-A forbids silent/new comfort noise activation; reserved for F6-C")
        self.enabled = enabled
        self.coeffs = coeffs
        self.comfort_noise_enabled = False
        self._hp_zi: np.ndarray = np.zeros((coeffs.sos_hp.shape[0], 2), dtype=np.float64)
        self._peak_zi: np.ndarray = np.zeros(max(len(coeffs.a_peak), len(coeffs.b_peak)) - 1, dtype=np.float64)
        self._processed_48k_samples = 0

    @property
    def processed_48k_samples(self) -> int:
        return self._processed_48k_samples

    def reset(self) -> None:
        """Reset filter history on generation revocation or new epoch."""
        self._hp_zi = np.zeros((self.coeffs.sos_hp.shape[0], 2), dtype=np.float64)
        self._peak_zi = np.zeros(
            max(len(self.coeffs.a_peak), len(self.coeffs.b_peak)) - 1,
            dtype=np.float64,
        )
        self._processed_48k_samples = 0

    def process_pre_resample_48k(self, samples_48k: np.ndarray) -> np.ndarray:
        """
        Apply 48 kHz telephony HPF + 3.2 kHz presence boost while retaining filter history
        across contiguous chunks in the same generation.
        """
        arr = np.asarray(samples_48k, dtype=np.float32)
        if arr.ndim != 1:
            raise ValueError("DSP input must be 1D float32 array")
        if arr.size == 0:
            return np.zeros(0, dtype=np.float32)
        if not bool(np.isfinite(arr).all()):
            raise ValueError("DSP input contains non-finite samples")
        self._processed_48k_samples += int(arr.size)
        if not self.enabled:
            # Copy to detached float32 array without mutating caller read-only buffer
            return np.array(arr, dtype=np.float32, copy=True)

        arr_w = np.array(arr, dtype=np.float32, copy=True)
        sos_w = np.array(self.coeffs.sos_hp, dtype=np.float64, copy=True)
        b_w = np.array(self.coeffs.b_peak, dtype=np.float64, copy=True)
        a_w = np.array(self.coeffs.a_peak, dtype=np.float64, copy=True)

        y_hp, self._hp_zi = signal.sosfilt(sos_w, arr_w, zi=self._hp_zi)
        y_hp_f32 = y_hp.astype(np.float32, copy=False)
        y_peak, self._peak_zi = signal.lfilter(
            b_w,
            a_w,
            y_hp_f32,
            zi=self._peak_zi,
        )
        out = (y_hp_f32 + self.coeffs.presence_gain * y_peak).astype(np.float32)
        return out

    def process_post_resample_limiter(self, samples_out: np.ndarray) -> tuple[np.ndarray, int]:
        """
        Apply `backend/dsp.py` soft peak limiter `tanh(x * 1.15)` at output rate when enabled.
        Returns `(limited_samples, samples_exceeding_unit_before_limiter)`.
        """
        arr = np.asarray(samples_out, dtype=np.float32)
        if arr.size == 0 or not self.enabled:
            return np.array(arr, dtype=np.float32, copy=True), 0
        pre_overrange = int(np.count_nonzero(np.abs(arr) > 1.0))
        limited = np.tanh(arr * self.coeffs.limiter_drive).astype(np.float32)
        return limited, pre_overrange
