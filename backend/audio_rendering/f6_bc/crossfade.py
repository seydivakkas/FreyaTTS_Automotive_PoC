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


@dataclass(frozen=True, slots=True)
class BoundaryRef:
    boundary_id: str
    left_chunk_id: str
    right_chunk_id: str
    protected_group: bool = False
    hard_semantic_pause: bool = False
    epoch_boundary: bool = False


@dataclass(frozen=True, slots=True)
class CrossfadeDecision:
    boundary_id: str
    candidate_overlap_samples: int
    actual_overlap_samples: int
    correlation: float | None
    shape: str
    applied: bool
    reason: str


@dataclass(frozen=True, slots=True)
class CrossfadeConfig:
    sample_rate_hz: int = 48000
    max_overlap_samples: int = 480  # 10 ms at 48 kHz
    min_chunk_samples: int = 960  # 20 ms at 48 kHz


class AdaptiveCrossfadeAssembler:
    """
    Bounded adaptive crossfade assembler at 48 kHz.
    Uses complementary raised-cosine constant-sum windowing:
      y = (1 - w) * a + w * b
    Never crossfades across protected groups, hard semantic pauses, or epoch boundaries.
    """

    def __init__(self, config: CrossfadeConfig | None = None) -> None:
        self.config = config or CrossfadeConfig()
        self._consumed_boundaries: set[str] = set()

    def reset(self) -> None:
        self._consumed_boundaries.clear()

    def assemble_boundary(
        self,
        left: np.ndarray,
        right: np.ndarray,
        boundary: BoundaryRef,
    ) -> tuple[np.ndarray, CrossfadeDecision]:
        left_arr = np.asarray(left, dtype=np.float32)
        right_arr = np.asarray(right, dtype=np.float32)
        if not (bool(np.isfinite(left_arr).all()) and bool(np.isfinite(right_arr).all())):
            raise ValueError("Crossfade input contains non-finite samples")

        if boundary.boundary_id in self._consumed_boundaries:
            raise ValueError(f"Duplicate boundary_id consumed: {boundary.boundary_id}")
        self._consumed_boundaries.add(boundary.boundary_id)

        if boundary.epoch_boundary:
            return np.concatenate([left_arr, right_arr]), CrossfadeDecision(
                boundary_id=boundary.boundary_id,
                candidate_overlap_samples=0,
                actual_overlap_samples=0,
                correlation=None,
                shape="NONE",
                applied=False,
                reason="EPOCH_BOUNDARY_BYPASS",
            )
        if boundary.protected_group:
            return np.concatenate([left_arr, right_arr]), CrossfadeDecision(
                boundary_id=boundary.boundary_id,
                candidate_overlap_samples=0,
                actual_overlap_samples=0,
                correlation=None,
                shape="NONE",
                applied=False,
                reason="PROTECTED_GROUP_BYPASS",
            )
        if boundary.hard_semantic_pause:
            return np.concatenate([left_arr, right_arr]), CrossfadeDecision(
                boundary_id=boundary.boundary_id,
                candidate_overlap_samples=0,
                actual_overlap_samples=0,
                correlation=None,
                shape="NONE",
                applied=False,
                reason="HARD_SEMANTIC_PAUSE_BYPASS",
            )

        max_ov = min(
            self.config.max_overlap_samples,
            left_arr.size // 4,
            right_arr.size // 4,
        )
        if left_arr.size < self.config.min_chunk_samples or right_arr.size < self.config.min_chunk_samples or max_ov < 2:
            return np.concatenate([left_arr, right_arr]), CrossfadeDecision(
                boundary_id=boundary.boundary_id,
                candidate_overlap_samples=max_ov,
                actual_overlap_samples=0,
                correlation=None,
                shape="NONE",
                applied=False,
                reason="INSUFFICIENT_SAFE_LENGTH",
            )

        a = left_arr[-max_ov:]
        b = right_arr[:max_ov]
        norm_a = float(np.sqrt(np.dot(a, a)))
        norm_b = float(np.sqrt(np.dot(b, b)))
        corr = float(np.dot(a, b)) / (norm_a * norm_b + 1e-12) if (norm_a > 1e-6 and norm_b > 1e-6) else 0.0

        # Complementary raised-cosine constant-sum window w in [0, 1]
        n = np.arange(max_ov, dtype=np.float32)
        w = 0.5 * (1.0 - np.cos(math.pi * n / float(max_ov - 1)))
        blended = ((1.0 - w) * a + w * b).astype(np.float32)
        assembled = np.concatenate([left_arr[:-max_ov], blended, right_arr[max_ov:]])

        return assembled, CrossfadeDecision(
            boundary_id=boundary.boundary_id,
            candidate_overlap_samples=max_ov,
            actual_overlap_samples=max_ov,
            correlation=corr,
            shape="RAISED_COSINE_CONSTANT_SUM",
            applied=True,
            reason="APPLIED",
        )
