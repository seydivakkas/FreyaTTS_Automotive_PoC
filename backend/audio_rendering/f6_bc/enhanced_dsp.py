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
from dataclasses import dataclass

import numpy as np
from scipy import signal


@dataclass(frozen=True, slots=True)
class EnhancedDSPProfile:
    """Opt-in F6-C DSP profile. Disabled (OFF) by default to preserve F6-A baseline."""

    enabled: bool = False
    deesser_enabled: bool = False
    eq_enabled: bool = False
    loudness_enabled: bool = False
    limiter_enabled: bool = False
    limiter_ceiling_dbfs: float = -1.0
    max_deess_db: float = 3.0
    max_loudness_db: float = 3.0
    target_rms_dbfs: float = -18.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.limiter_ceiling_dbfs) or self.limiter_ceiling_dbfs > 0.0:
            raise ValueError("limiter_ceiling_dbfs must be finite and <= 0.0")
        if not math.isfinite(self.max_deess_db) or not (0.0 <= self.max_deess_db <= 12.0):
            raise ValueError("max_deess_db must be in [0.0, 12.0]")
        if not math.isfinite(self.max_loudness_db) or not (0.0 <= self.max_loudness_db <= 6.0):
            raise ValueError("max_loudness_db must be in [0.0, 6.0]")


class EnhancedDSPProcessor:
    """
    Single-owner causal per-generation F6-C DSP processor:
    - Pre-resample 48 kHz: optional bounded de-esser (5-10 kHz), causal EQ (120 Hz HPF + 3.2 kHz presence),
      bounded speech-gated loudness gain (+-3 dB).
    - Post-resample target rate: final-rate -1 dBFS sample-peak limiter (ceiling ~0.89125).
    """

    def __init__(self, profile: EnhancedDSPProfile | None = None, *, input_rate_hz: int = 48000) -> None:
        self.profile = profile or EnhancedDSPProfile()
        self.input_rate_hz = input_rate_hz
        nyq = input_rate_hz / 2.0

        # De-esser bandpass (5-10 kHz at 48 kHz)
        self._sos_sibilant = signal.butter(2, [5000.0 / nyq, min(10000.0, nyq * 0.9) / nyq], btype="bandpass", output="sos")
        self._sos_hp = signal.butter(2, 120.0 / nyq, btype="highpass", output="sos")
        self._b_peak, self._a_peak = signal.iirpeak(3200.0 / nyq, Q=1.5)

        self._sib_zi = np.zeros((self._sos_sibilant.shape[0], 2), dtype=np.float64)
        self._hp_zi = np.zeros((self._sos_hp.shape[0], 2), dtype=np.float64)
        self._peak_zi = np.zeros(max(len(self._a_peak), len(self._b_peak)) - 1, dtype=np.float64)
        self._deess_env = 0.0
        self._loudness_gain = 1.0

    def reset(self) -> None:
        self._sib_zi = np.zeros((self._sos_sibilant.shape[0], 2), dtype=np.float64)
        self._hp_zi = np.zeros((self._sos_hp.shape[0], 2), dtype=np.float64)
        self._peak_zi = np.zeros(max(len(self._a_peak), len(self._b_peak)) - 1, dtype=np.float64)
        self._deess_env = 0.0
        self._loudness_gain = 1.0

    def process_pre_resample_48k(self, samples_48k: np.ndarray) -> np.ndarray:
        arr = np.asarray(samples_48k, dtype=np.float32)
        if arr.ndim != 1:
            raise ValueError("EnhancedDSP input must be 1D float32 array")
        if arr.size == 0:
            return np.zeros(0, dtype=np.float32)
        if not bool(np.isfinite(arr).all()):
            raise ValueError("EnhancedDSP input contains non-finite samples")
        if not self.profile.enabled:
            return np.array(arr, dtype=np.float32, copy=True)

        y = np.array(arr, dtype=np.float32, copy=True)

        if self.profile.deesser_enabled:
            sib, self._sib_zi = signal.sosfilt(self._sos_sibilant, y, zi=self._sib_zi)
            sib_rms = float(np.sqrt(np.mean(np.square(sib)) + 1e-12))
            self._deess_env = 0.7 * self._deess_env + 0.3 * sib_rms
            if self._deess_env > 0.05:
                over_db = 20.0 * math.log10(self._deess_env / 0.05)
                red_db = min(self.profile.max_deess_db, over_db * 0.5)
                gain = 10.0 ** (-red_db / 20.0)
                y = (y - (1.0 - gain) * sib.astype(np.float32)).astype(np.float32)

        if self.profile.eq_enabled:
            y_hp, self._hp_zi = signal.sosfilt(self._sos_hp, y, zi=self._hp_zi)
            y_hp32 = y_hp.astype(np.float32, copy=False)
            y_pk, self._peak_zi = signal.lfilter(self._b_peak, self._a_peak, y_hp32, zi=self._peak_zi)
            y = (y_hp32 + 0.35 * y_pk).astype(np.float32)

        if self.profile.loudness_enabled:
            rms = float(np.sqrt(np.mean(np.square(y)) + 1e-12))
            if rms > 0.005:  # Freeze on silence
                rms_dbfs = 20.0 * math.log10(rms)
                delta_db = max(-self.profile.max_loudness_db, min(self.profile.max_loudness_db, self.profile.target_rms_dbfs - rms_dbfs))
                target_gain = 10.0 ** (delta_db / 20.0)
                self._loudness_gain = 0.8 * self._loudness_gain + 0.2 * target_gain
            y = (y * self._loudness_gain).astype(np.float32)

        return y

    def process_post_resample_limiter(self, samples_out: np.ndarray) -> tuple[np.ndarray, int]:
        arr = np.asarray(samples_out, dtype=np.float32)
        if arr.size == 0:
            return np.zeros(0, dtype=np.float32), 0
        if not bool(np.isfinite(arr).all()):
            raise ValueError("EnhancedDSP limiter input contains non-finite samples")
        if not (self.profile.enabled and self.profile.limiter_enabled):
            return np.array(arr, dtype=np.float32, copy=True), 0

        ceiling = 10.0 ** (self.profile.limiter_ceiling_dbfs / 20.0)
        pre_over = int(np.count_nonzero(np.abs(arr) > ceiling))
        # Soft saturation scaled to ceiling so sample peak <= ceiling
        limited = (ceiling * np.tanh(arr / ceiling)).astype(np.float32)
        limited = np.clip(limited, -ceiling, ceiling).astype(np.float32)
        return limited, pre_over
