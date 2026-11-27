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

from backend.audio_frontend.f0_b.profiles import EnhancementProfile


@dataclass(frozen=True, slots=True)
class AdaptiveDenoiseResult:
    """Output of AdaptiveDenoiserStage with safe bounded estimator metadata."""

    samples: np.ndarray
    noise_calibrated: bool
    noise_floor_dbfs: float | None
    estimated_snr_db: float | None
    wind_turbulence_detected: bool
    clipped_input_samples: int


class AdaptiveDenoiserStage:
    """
    F0-B adaptive noise PSD estimator and Wiener-style spectral suppressor.

    - Uses 50% overlap-add Sine window (exact MDCT unity reconstruction).
    - Updates noise PSD P_N[k, t] = alpha * P_N[k, t-1] + (1 - alpha) * |X[k, t]|^2
      only on eligible non-speech / non-double-talk observations.
    - Preserves speech onsets and tails with bounded gain floor and attack/release slew.
    - Detects low-frequency wind turbulence / saturation without fabricating recovery.
    - Maintains exact sample count across arbitrary chunk sizes.
    """

    def __init__(
        self,
        *,
        sample_rate_hz: int,
        profile: EnhancementProfile,
        n_fft: int | None = None,
        hop_size: int | None = None,
    ) -> None:
        self.sample_rate_hz = int(sample_rate_hz)
        self.profile = profile
        default_fft = 256 if self.sample_rate_hz <= 8000 else 512
        self.n_fft = int(n_fft or default_fft)
        self.hop_size = int(hop_size or (self.n_fft // 2))
        self.n_bins = self.n_fft // 2 + 1

        n = np.arange(self.n_fft, dtype=np.float32)
        self.window = np.sin(np.pi * (n + 0.5) / self.n_fft).astype(np.float32)

        hop_sec = self.hop_size / float(self.sample_rate_hz)
        self.alpha = float(math.exp(-hop_sec / max(profile.noise_tau_s, 1e-3)))
        self.g_floor = float(profile.gain_floor)
        self.over_sub = float(profile.over_subtraction)

        self.freqs = np.fft.rfftfreq(self.n_fft, 1.0 / self.sample_rate_hz)
        self._low_band_end = int(np.searchsorted(self.freqs, 250.0))
        self._speech_start = int(np.searchsorted(self.freqs, 300.0))
        self._speech_end = max(self._speech_start + 1, int(np.searchsorted(self.freqs, 3400.0)))

        self.reset()

    def reset(self) -> None:
        """Reset overlap-add buffers and adaptive noise PSD state."""
        self._in_fifo = np.zeros(0, dtype=np.float32)
        self._out_buffer = np.zeros(self.n_fft, dtype=np.float32)
        self._out_fifo = np.zeros(0, dtype=np.float32)
        self._noise_psd = np.full(self.n_bins, 1e-6, dtype=np.float64)
        self._prev_gain = np.ones(self.n_bins, dtype=np.float64)
        self._eligible_frames = 0
        self._total_frames = 0
        self._min_calib_frames = 6
        self._last_snr_db: float | None = None

    @property
    def is_calibrated(self) -> bool:
        return self._eligible_frames >= self._min_calib_frames

    def noise_floor_dbfs(self) -> float | None:
        if not self.is_calibrated:
            return None
        mean_psd = float(np.mean(self._noise_psd[self._speech_start : self._speech_end]))
        if mean_psd <= 1e-12:
            return -120.0
        # Convert FFT power bin estimate to approximate per-sample dBFS
        norm_power = mean_psd / float(self.n_fft)
        return 10.0 * math.log10(max(norm_power, 1e-12))

    def process(
        self,
        samples: np.ndarray,
        *,
        freeze_noise_update: bool = False,
        dtmf_active: bool = False,
    ) -> AdaptiveDenoiseResult:
        """Process 1D float32 block, returning exact same sample count."""
        arr = np.ascontiguousarray(samples, dtype=np.float32)
        if len(arr) == 0:
            return AdaptiveDenoiseResult(
                samples=arr.copy(),
                noise_calibrated=self.is_calibrated,
                noise_floor_dbfs=self.noise_floor_dbfs(),
                estimated_snr_db=self._last_snr_db,
                wind_turbulence_detected=False,
                clipped_input_samples=0,
            )

        if not np.isfinite(arr).all():
            raise ValueError("Non-finite samples passed to AdaptiveDenoiserStage")

        clipped_in = int(np.count_nonzero(np.abs(arr) >= 1.0 - 1e-6))
        wind_detected = False

        self._in_fifo = np.concatenate((self._in_fifo, arr))
        while len(self._in_fifo) >= self.n_fft:
            frame = self._in_fifo[: self.n_fft]
            self._in_fifo = self._in_fifo[self.hop_size :]

            win_frame = frame * self.window
            spec = np.fft.rfft(win_frame)
            mag_sq = (spec.real.astype(np.float64) ** 2) + (spec.imag.astype(np.float64) ** 2)
            self._total_frames += 1

            # Check low-frequency turbulence (<250 Hz dominance)
            low_energy = float(np.sum(mag_sq[: max(1, self._low_band_end)]))
            speech_energy = float(np.sum(mag_sq[self._speech_start : self._speech_end]))
            if low_energy > 4.0 * max(speech_energy, 1e-8) and low_energy > 1e-2:
                wind_detected = True

            # Speech-band ratio vs current noise estimate to gate PSD update
            noise_speech_e = float(np.sum(self._noise_psd[self._speech_start : self._speech_end]))
            speech_likely = speech_energy > 2.5 * max(noise_speech_e, 1e-9)

            if not freeze_noise_update and not dtmf_active and (
                not speech_likely or self._eligible_frames < self._min_calib_frames
            ):
                self._noise_psd = self.alpha * self._noise_psd + (1.0 - self.alpha) * mag_sq
                self._noise_psd = np.maximum(self._noise_psd, 1e-9)
                self._eligible_frames += 1

            if not self.is_calibrated:
                # Conservative low suppression during initial uncalibrated frames
                gain = np.ones(self.n_bins, dtype=np.float64)
            else:
                post_snr_e = np.maximum(mag_sq - self._noise_psd, 0.0)
                wiener = post_snr_e / (post_snr_e + self.over_sub * self._noise_psd + 1e-9)
                target_gain = np.maximum(self.g_floor, wiener)
                # Fast attack (0.35), slower release (0.70) to preserve speech tails
                alpha_g = np.where(target_gain >= self._prev_gain, 0.35, 0.70)
                gain = alpha_g * self._prev_gain + (1.0 - alpha_g) * target_gain
                self._prev_gain = gain

                if noise_speech_e > 1e-12 and speech_energy > noise_speech_e:
                    self._last_snr_db = 10.0 * math.log10((speech_energy - noise_speech_e) / noise_speech_e)
                elif noise_speech_e > 1e-12:
                    self._last_snr_db = None

            clean_spec = spec * gain.astype(np.float32)
            recon = np.fft.irfft(clean_spec, n=self.n_fft).astype(np.float32) * self.window
            self._out_buffer += recon
            self._out_fifo = np.concatenate((self._out_fifo, self._out_buffer[: self.hop_size]))
            self._out_buffer[: self.n_fft - self.hop_size] = self._out_buffer[self.hop_size :]
            self._out_buffer[self.n_fft - self.hop_size :] = 0.0

        # Emit exact sample count; pad startup latency with zeros only until FIFO fills
        out_len = len(arr)
        if len(self._out_fifo) >= out_len:
            out = self._out_fifo[:out_len]
            self._out_fifo = self._out_fifo[out_len:]
        else:
            missing = out_len - len(self._out_fifo)
            out = np.concatenate((np.zeros(missing, dtype=np.float32), self._out_fifo))
            self._out_fifo = np.zeros(0, dtype=np.float32)

        return AdaptiveDenoiseResult(
            samples=np.ascontiguousarray(out, dtype=np.float32),
            noise_calibrated=self.is_calibrated,
            noise_floor_dbfs=self.noise_floor_dbfs(),
            estimated_snr_db=self._last_snr_db,
            wind_turbulence_detected=wind_detected,
            clipped_input_samples=clipped_in,
        )
