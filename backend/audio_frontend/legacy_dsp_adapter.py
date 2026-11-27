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
from typing import Any

import numpy as np

from backend.audio_frontend.config_adapter import AudioFrontendConfig
from backend.car_denoiser import (
    CarNoiseFilter,
    SoftAGC,
    SpectralNoiseSuppressor,
)


class DspStageError(RuntimeError):
    """Explicit typed failure raised when an isolated legacy DSP stage fails."""

    def __init__(self, stage_name: str, message: str) -> None:
        super().__init__(f"{stage_name}: {message}")
        self.stage_name = stage_name
        self.safe_message = message


@dataclass(frozen=True, slots=True)
class DspProcessingResult:
    """Result of executing the per-stream legacy DSP chain."""

    samples: np.ndarray
    route: str
    hpf_applied: bool
    spectral_applied: bool
    agc_gate_applied: bool
    is_speech: bool
    last_applied_gain_db: float
    estimated_snr_db: float


class LegacyHpfStage:
    """Per-stream adapter around legacy CarNoiseFilter (120 Hz 4th-order Butterworth HPF)."""

    def __init__(self, *, sample_rate_hz: int, cutoff_hz: float = 120.0, order: int = 4) -> None:
        self.sample_rate_hz = int(sample_rate_hz)
        self.cutoff_hz = float(cutoff_hz)
        self.order = int(order)
        self._filter = CarNoiseFilter(
            cutoff_hz=self.cutoff_hz,
            sample_rate=self.sample_rate_hz,
            order=self.order,
        )

    def reset(self) -> None:
        self._filter.reset()

    def process(self, samples: np.ndarray) -> np.ndarray:
        try:
            out = self._filter.process(samples)
        except Exception as exc:
            raise DspStageError("hpf", f"HPF stage failed: {type(exc).__name__}") from exc
        if len(out) > 0 and not np.isfinite(out).all():
            raise DspStageError("hpf", "HPF stage produced non-finite output")
        return np.ascontiguousarray(out, dtype=np.float32)


class LegacySpectralStage:
    """Per-stream adapter around legacy SpectralNoiseSuppressor (overlap-add spectral subtraction)."""

    def __init__(
        self,
        *,
        sample_rate_hz: int,
        suppression_db: float = 18.0,
        n_fft: int = 256,
        hop_size: int = 128,
        over_subtraction: float = 1.5,
    ) -> None:
        self.sample_rate_hz = int(sample_rate_hz)
        self.suppression_db = float(suppression_db)
        self._suppressor = SpectralNoiseSuppressor(
            sample_rate=self.sample_rate_hz,
            n_fft=n_fft,
            hop_size=hop_size,
            suppression_db=self.suppression_db,
            over_subtraction=over_subtraction,
        )

    @property
    def last_snr_db(self) -> float:
        return float(self._suppressor.last_snr_db)

    def reset(self) -> None:
        self._suppressor.reset()

    def process(self, samples: np.ndarray) -> np.ndarray:
        try:
            out = self._suppressor.process(samples)
        except Exception as exc:
            raise DspStageError("spectral", f"Spectral stage failed: {type(exc).__name__}") from exc
        if len(out) > 0 and not np.isfinite(out).all():
            raise DspStageError("spectral", "Spectral stage produced non-finite output")
        return np.ascontiguousarray(out, dtype=np.float32)


class LegacyAgcGateStage:
    """Per-stream adapter around legacy SoftAGC (noise-gated soft AGC + tanh limiter)."""

    def __init__(
        self,
        *,
        sample_rate_hz: int,
        target_dbfs: float = -16.0,
        noise_gate_dbfs: float = -42.0,
        max_boost_db: float = 12.0,
        max_cut_db: float = 6.0,
        gate_attenuation_db: float = 30.0,
    ) -> None:
        self.sample_rate_hz = int(sample_rate_hz)
        self._agc = SoftAGC(
            target_dbfs=target_dbfs,
            noise_gate_dbfs=noise_gate_dbfs,
            max_boost_db=max_boost_db,
            max_cut_db=max_cut_db,
            sample_rate=self.sample_rate_hz,
            gate_attenuation_db=gate_attenuation_db,
        )

    @property
    def is_speech(self) -> bool:
        return bool(self._agc.is_speech)

    @property
    def last_applied_gain_db(self) -> float:
        return float(self._agc.last_applied_gain_db)

    def reset(self) -> None:
        self._agc.reset()

    def process(self, samples: np.ndarray) -> np.ndarray:
        try:
            out = self._agc.process(samples)
        except Exception as exc:
            raise DspStageError("agc_gate", f"AGC/gate stage failed: {type(exc).__name__}") from exc
        if len(out) > 0 and not np.isfinite(out).all():
            raise DspStageError("agc_gate", "AGC/gate stage produced non-finite output")
        return np.ascontiguousarray(out, dtype=np.float32)


class LegacyDspChain:
    """
    Isolated per-stream legacy DSP orchestrator preserving exact stage ordering:
    120 Hz HPF -> Overlap-Add Spectral Suppression -> Noise-Gated Soft AGC & Limiter.

    Supports explicit bypass, already-processed skip, and per-stage toggles without
    sharing mutable state across sessions, directions, or epochs.
    """

    def __init__(
        self,
        *,
        sample_rate_hz: int,
        config: AudioFrontendConfig,
        hpf_enabled: bool = True,
        spectral_enabled: bool = True,
        agc_gate_enabled: bool = True,
        bypass: bool = False,
        already_processed: bool = False,
    ) -> None:
        self.sample_rate_hz = int(sample_rate_hz)
        self.config = config
        self.bypass = bool(bypass or config.bypass_dsp or not config.car_denoiser_enabled)
        self.already_processed = bool(already_processed)
        self.hpf_enabled = bool(hpf_enabled)
        self.spectral_enabled = bool(spectral_enabled)
        self.agc_gate_enabled = bool(agc_gate_enabled)

        self.hpf = LegacyHpfStage(
            sample_rate_hz=self.sample_rate_hz,
            cutoff_hz=config.hpf_cutoff_hz,
            order=4,
        )
        self.spectral = LegacySpectralStage(
            sample_rate_hz=self.sample_rate_hz,
            suppression_db=config.suppression_db,
        )
        self.agc_gate = LegacyAgcGateStage(
            sample_rate_hz=self.sample_rate_hz,
            target_dbfs=config.target_dbfs,
            noise_gate_dbfs=config.noise_gate_dbfs,
            max_boost_db=config.max_boost_db,
            gate_attenuation_db=config.gate_attenuation_db,
        )

        self.is_calibrating: bool = False
        self.calibrated: bool = False
        self.ambient_noise_dbfs: float = -90.0
        self._calib_frames: list[np.ndarray] = []
        self._target_calib_frames: int = 75
        self._calib_total_samples: int = 0
        self._max_calib_samples: int = self.sample_rate_hz * 5

    def reset(self) -> None:
        """Reset all per-stream DSP filter/FFT/AGC states cleanly."""
        self.hpf.reset()
        self.spectral.reset()
        self.agc_gate.reset()

    def start_calibration(self, duration_sec: float = 1.5, target_frames: int | None = None) -> None:
        self.is_calibrating = True
        self._calib_frames = []
        self._calib_total_samples = 0
        self._target_calib_frames = target_frames or max(int(duration_sec / 0.020), 25)

    def feed_calibration(self, samples: np.ndarray) -> bool:
        if not self.is_calibrating:
            return True
        if len(samples) > 0:
            if self._calib_total_samples + len(samples) <= self._max_calib_samples:
                self._calib_frames.append(np.ascontiguousarray(samples, dtype=np.float32))
                self._calib_total_samples += len(samples)
        return len(self._calib_frames) >= self._target_calib_frames

    def finish_calibration(self) -> dict[str, Any]:
        self.is_calibrating = False
        if not self._calib_frames:
            return {
                "calibrated": False,
                "ambient_dbfs": self.ambient_noise_dbfs,
                "noise_gate_dbfs": self.agc_gate._agc.noise_gate_dbfs,
                "suppression_db": self.spectral._suppressor.suppression_db,
            }

        filtered_rms_list: list[float] = []
        all_samples: list[np.ndarray] = []
        # Use a temporary HPF so live stream filter history is not perturbed by batch calibration replay
        calib_hpf = LegacyHpfStage(
            sample_rate_hz=self.sample_rate_hz,
            cutoff_hz=self.config.hpf_cutoff_hz,
            order=4,
        )
        for frame in self._calib_frames:
            hpf_frame = calib_hpf.process(frame)
            mean_sq = float(np.mean(hpf_frame**2))
            filtered_rms_list.append(math.sqrt(max(mean_sq, 1e-12)))
            all_samples.append(hpf_frame)

        ambient_rms = float(np.percentile(filtered_rms_list, 85))
        ambient_dbfs = 20.0 * math.log10(max(ambient_rms, 1e-6))
        self.ambient_noise_dbfs = ambient_dbfs

        dynamic_gate_dbfs = round(min(max(ambient_dbfs + 4.5, -52.0), -24.0), 2)
        self.agc_gate._agc.noise_gate_dbfs = dynamic_gate_dbfs

        if all_samples:
            flat_samples = np.concatenate(all_samples)
            self.spectral.reset()
            self.spectral.process(flat_samples)
            if ambient_dbfs > -38.0:
                boosted = min(24.0, 18.0 + (ambient_dbfs + 38.0) * 0.75)
                self.spectral._suppressor.suppression_db = boosted
                self.spectral._suppressor.g_floor = float(10.0 ** (-boosted / 20.0))
                self.spectral._suppressor.g_floor_sq = self.spectral._suppressor.g_floor**2

        self.calibrated = True
        self._calib_frames.clear()
        return {
            "calibrated": True,
            "ambient_dbfs": round(ambient_dbfs, 2),
            "noise_gate_dbfs": round(dynamic_gate_dbfs, 2),
            "suppression_db": round(self.spectral._suppressor.suppression_db, 2),
        }

    def process(self, samples: np.ndarray) -> DspProcessingResult:
        """Execute selected DSP route on finite mono float32 samples at native rate."""
        arr = np.ascontiguousarray(samples, dtype=np.float32)
        if len(arr) > 0 and not np.isfinite(arr).all():
            raise DspStageError("input", "Non-finite input samples rejected before DSP")

        if self.already_processed:
            return DspProcessingResult(
                samples=arr.copy(),
                route="already_processed",
                hpf_applied=False,
                spectral_applied=False,
                agc_gate_applied=False,
                is_speech=False,
                last_applied_gain_db=0.0,
                estimated_snr_db=0.0,
            )

        if self.bypass or len(arr) == 0:
            return DspProcessingResult(
                samples=arr.copy(),
                route="bypass",
                hpf_applied=False,
                spectral_applied=False,
                agc_gate_applied=False,
                is_speech=False,
                last_applied_gain_db=0.0,
                estimated_snr_db=0.0,
            )

        current = arr
        hpf_done = False
        spectral_done = False
        agc_done = False

        if self.hpf_enabled:
            current = self.hpf.process(current)
            hpf_done = True

        if self.spectral_enabled:
            current = self.spectral.process(current)
            spectral_done = True

        if self.agc_gate_enabled:
            current = self.agc_gate.process(current)
            agc_done = True

        return DspProcessingResult(
            samples=current,
            route="legacy_dsp",
            hpf_applied=hpf_done,
            spectral_applied=spectral_done,
            agc_gate_applied=agc_done,
            is_speech=self.agc_gate.is_speech if agc_done else False,
            last_applied_gain_db=self.agc_gate.last_applied_gain_db if agc_done else 0.0,
            estimated_snr_db=self.spectral.last_snr_db if spectral_done else 0.0,
        )
