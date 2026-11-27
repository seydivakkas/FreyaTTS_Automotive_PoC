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
from enum import StrEnum

import numpy as np


class DelayStatus(StrEnum):
    """Validity state of causal echo-path delay estimation."""

    CONFIDENT = "CONFIDENT"
    UNCERTAIN = "UNCERTAIN"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class DelayEstimate:
    """
    Bounded causal delay estimate between reference and microphone capture.

    Sign convention: positive lag_samples d means reference precedes captured echo by d samples,
    i.e. mic[n] correlates with ref[n - d] (or aligned_ref[k] = ref_history[-window - d : -d]).
    """

    lag_samples: int | None
    lag_ms: float | None
    sample_rate_hz: int
    valid_overlap: int
    score_kind: str
    score: float | None
    margin: float | None
    coverage_fraction: float
    status: DelayStatus
    reason: str
    age_samples: int = 0


class NccDelayEstimator:
    """
    Bounded Normalized Cross-Correlation (NCC) delay estimator with energy,
    overlap, ambiguity-margin, slew, and staleness gates.

    Never falls back to arbitrary lag 0 on insufficient energy or ambiguity.
    """

    def __init__(
        self,
        *,
        sample_rate_hz: int = 16000,
        max_lag_ms: float = 240.0,
        corr_window_ms: float = 80.0,
        min_overlap_samples: int = 160,
        energy_floor: float = 1e-6,
        min_score: float = 0.45,
        min_margin: float = 0.08,
        max_slew_samples: int = 64,
        stale_after_samples: int = 16000,
    ) -> None:
        self.sample_rate_hz = int(sample_rate_hz)
        self.max_lag_samples = max(0, int(round(max_lag_ms * self.sample_rate_hz / 1000.0)))
        self.corr_window_samples = max(32, int(round(corr_window_ms * self.sample_rate_hz / 1000.0)))
        self.min_overlap_samples = max(32, int(min_overlap_samples))
        self.energy_floor = float(energy_floor)
        self.min_score = float(min_score)
        self.min_margin = float(min_margin)
        self.max_slew_samples = max(1, int(max_slew_samples))
        self.stale_after_samples = max(1, int(stale_after_samples))

        self._last_lag: int | None = None
        self._last_score: float | None = None
        self._age_samples: int = 0

    def reset(self) -> None:
        """Reset tracked delay state on discontinuity or route change."""
        self._last_lag = None
        self._last_score = None
        self._age_samples = 0

    def estimate(
        self,
        mic_window: np.ndarray,
        ref_history: np.ndarray,
        *,
        freeze: bool = False,
        stride: int = 1,
    ) -> DelayEstimate:
        """
        Estimate causal lag d >= 0 where mic_window aligns with ref_history[end - len(mic) - d : end - d].

        Both arrays are at self.sample_rate_hz, 1D float32, aligned at their trailing edge (latest sample).
        """
        mic = np.asarray(mic_window, dtype=np.float32)
        ref = np.asarray(ref_history, dtype=np.float32)

        if mic.ndim != 1 or ref.ndim != 1:
            raise ValueError("mic_window and ref_history must be 1D")

        if freeze:
            self._age_samples += len(mic)
            if self._last_lag is not None and self._age_samples <= self.stale_after_samples:
                return DelayEstimate(
                    lag_samples=self._last_lag,
                    lag_ms=(self._last_lag * 1000.0) / self.sample_rate_hz,
                    sample_rate_hz=self.sample_rate_hz,
                    valid_overlap=len(mic),
                    score_kind="NCC",
                    score=self._last_score,
                    margin=None,
                    coverage_fraction=1.0,
                    status=DelayStatus.CONFIDENT,
                    reason="frozen_held_lag",
                    age_samples=self._age_samples,
                )
            return DelayEstimate(
                lag_samples=None,
                lag_ms=None,
                sample_rate_hz=self.sample_rate_hz,
                valid_overlap=len(mic),
                score_kind="NCC",
                score=None,
                margin=None,
                coverage_fraction=0.0,
                status=DelayStatus.STALE if self._last_lag is not None else DelayStatus.UNKNOWN,
                reason="frozen_stale_or_uninitialized",
                age_samples=self._age_samples,
            )

        win_len = min(len(mic), self.corr_window_samples)
        if win_len < self.min_overlap_samples or len(ref) < win_len:
            self._age_samples += len(mic)
            return DelayEstimate(
                lag_samples=None,
                lag_ms=None,
                sample_rate_hz=self.sample_rate_hz,
                valid_overlap=min(len(mic), len(ref)),
                score_kind="NCC",
                score=None,
                margin=None,
                coverage_fraction=min(1.0, len(ref) / max(1, win_len)),
                status=DelayStatus.UNAVAILABLE,
                reason="insufficient_history",
                age_samples=self._age_samples,
            )

        x = mic[-win_len:].astype(np.float64)
        x_energy = float(np.dot(x, x))
        if x_energy < self.energy_floor * win_len:
            self._age_samples += len(mic)
            return DelayEstimate(
                lag_samples=None,
                lag_ms=None,
                sample_rate_hz=self.sample_rate_hz,
                valid_overlap=win_len,
                score_kind="NCC",
                score=None,
                margin=None,
                coverage_fraction=1.0,
                status=DelayStatus.UNKNOWN,
                reason="mic_energy_below_floor",
                age_samples=self._age_samples,
            )

        max_searchable_lag = min(self.max_lag_samples, len(ref) - win_len)
        if max_searchable_lag < 0:
            self._age_samples += len(mic)
            return DelayEstimate(
                lag_samples=None,
                lag_ms=None,
                sample_rate_hz=self.sample_rate_hz,
                valid_overlap=win_len,
                score_kind="NCC",
                score=None,
                margin=None,
                coverage_fraction=0.0,
                status=DelayStatus.UNAVAILABLE,
                reason="insufficient_lag_history",
                age_samples=self._age_samples,
            )

        step = max(1, int(stride))
        lags = list(range(0, max_searchable_lag + 1, step))
        scores: list[tuple[int, float]] = []
        ref_f64 = ref.astype(np.float64)
        ref_end = len(ref_f64)

        for d in lags:
            end_idx = ref_end - d
            start_idx = end_idx - win_len
            r_seg = ref_f64[start_idx:end_idx]
            r_energy = float(np.dot(r_seg, r_seg))
            if r_energy < self.energy_floor * win_len:
                continue
            denom = np.sqrt(x_energy * r_energy) + 1e-12
            ncc = float(np.dot(x, r_seg) / denom)
            scores.append((d, ncc))

        if not scores:
            self._age_samples += len(mic)
            return DelayEstimate(
                lag_samples=None,
                lag_ms=None,
                sample_rate_hz=self.sample_rate_hz,
                valid_overlap=win_len,
                score_kind="NCC",
                score=None,
                margin=None,
                coverage_fraction=1.0,
                status=DelayStatus.UNKNOWN,
                reason="reference_energy_below_floor",
                age_samples=self._age_samples,
            )

        scores.sort(key=lambda item: item[1], reverse=True)
        best_lag, best_score = scores[0]

        # Runner-up outside a small neighborhood around best_lag to avoid main-lobe width
        neighborhood = max(4, int(round(0.002 * self.sample_rate_hz)))
        runner_up_score = 0.0
        for d, sc in scores[1:]:
            if abs(d - best_lag) > neighborhood:
                runner_up_score = max(0.0, sc)
                break
        margin = best_score - runner_up_score

        if best_score < self.min_score:
            self._age_samples += len(mic)
            return DelayEstimate(
                lag_samples=None,
                lag_ms=None,
                sample_rate_hz=self.sample_rate_hz,
                valid_overlap=win_len,
                score_kind="NCC",
                score=best_score,
                margin=margin,
                coverage_fraction=1.0,
                status=DelayStatus.UNCERTAIN,
                reason="ncc_score_below_threshold",
                age_samples=self._age_samples,
            )

        if len(scores) > 1 and margin < self.min_margin:
            self._age_samples += len(mic)
            return DelayEstimate(
                lag_samples=None,
                lag_ms=None,
                sample_rate_hz=self.sample_rate_hz,
                valid_overlap=win_len,
                score_kind="NCC",
                score=best_score,
                margin=margin,
                coverage_fraction=1.0,
                status=DelayStatus.UNCERTAIN,
                reason="ambiguous_periodic_peak",
                age_samples=self._age_samples,
            )

        if self._last_lag is not None and abs(best_lag - self._last_lag) > self.max_slew_samples:
            # Large jump: clamp or reacquire cautiously
            self._last_lag = best_lag
            self._last_score = best_score
            self._age_samples = 0
            return DelayEstimate(
                lag_samples=best_lag,
                lag_ms=(best_lag * 1000.0) / self.sample_rate_hz,
                sample_rate_hz=self.sample_rate_hz,
                valid_overlap=win_len,
                score_kind="NCC",
                score=best_score,
                margin=margin,
                coverage_fraction=1.0,
                status=DelayStatus.CONFIDENT,
                reason="reacquired_lag_jump",
                age_samples=0,
            )

        self._last_lag = best_lag
        self._last_score = best_score
        self._age_samples = 0
        return DelayEstimate(
            lag_samples=best_lag,
            lag_ms=(best_lag * 1000.0) / self.sample_rate_hz,
            sample_rate_hz=self.sample_rate_hz,
            valid_overlap=win_len,
            score_kind="NCC",
            score=best_score,
            margin=margin,
            coverage_fraction=1.0,
            status=DelayStatus.CONFIDENT,
            reason="ncc_peak_confident",
            age_samples=0,
        )
