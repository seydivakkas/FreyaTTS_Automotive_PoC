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

from backend.core.contracts.validation import require_strict_int


class PauseTargetKind(StrEnum):
    TOTAL_BOUNDARY = "TOTAL_BOUNDARY"
    ADDITIONAL_LEGACY = "ADDITIONAL_LEGACY"


@dataclass(frozen=True, slots=True)
class SilenceObservation:
    rate_hz: int
    left_trailing_samples: int
    right_leading_samples: int
    threshold_amp: float


@dataclass(frozen=True, slots=True)
class PauseLedgerEntry:
    boundary_id: str
    target_kind: PauseTargetKind
    requested_ms: int
    target_samples: int
    left_credited_samples: int
    right_credited_samples: int
    inserted_samples: int
    owner: str
    consumed: bool = True
    reason: str = "APPLIED"


def observe_boundary_silence(
    left_tail: np.ndarray | None,
    right_head: np.ndarray | None,
    *,
    rate_hz: int = 48000,
    threshold_amp: float = 0.003,
) -> SilenceObservation:
    """
    Conservative edge-silence measurement on post-rate, post-assembly audio.
    Never trims or mutates audio; counts contiguous below-threshold samples at each edge.
    """
    left_count = 0
    if left_tail is not None and left_tail.size > 0:
        arr = np.abs(np.asarray(left_tail, dtype=np.float32))
        above = np.flatnonzero(arr > threshold_amp)
        left_count = int(arr.size - 1 - above[-1]) if above.size > 0 else int(arr.size)

    right_count = 0
    if right_head is not None and right_head.size > 0:
        arr = np.abs(np.asarray(right_head, dtype=np.float32))
        above = np.flatnonzero(arr > threshold_amp)
        right_count = int(above[0]) if above.size > 0 else int(arr.size)

    return SilenceObservation(
        rate_hz=rate_hz,
        left_trailing_samples=left_count,
        right_leading_samples=right_count,
        threshold_amp=threshold_amp,
    )


class SemanticPauseLedger:
    """
    Net semantic pause accounting ledger.
    - TOTAL_BOUNDARY: credits observed natural edge silence so total pause >= target
      without shortening natural silence or double-inserting.
    - ADDITIONAL_LEGACY: preserves F6-A additive post_pause_ms semantics.
    - Enforces per-boundary and per-plan caps and idempotent consume-once per boundary_id.
    """

    def __init__(
        self,
        *,
        rate_hz: int = 48000,
        max_per_boundary_ms: int = 320,
        max_total_plan_ms: int = 1200,
    ) -> None:
        require_strict_int(rate_hz, "rate_hz", minimum=8000, maximum=48000)
        require_strict_int(max_per_boundary_ms, "max_per_boundary_ms", minimum=0, maximum=10_000)
        require_strict_int(max_total_plan_ms, "max_total_plan_ms", minimum=0, maximum=60_000)
        self.rate_hz = rate_hz
        self.max_per_boundary_ms = max_per_boundary_ms
        self.max_total_plan_ms = max_total_plan_ms
        self._entries: dict[str, PauseLedgerEntry] = {}
        self._total_inserted_ms = 0

    def reset(self) -> None:
        self._entries.clear()
        self._total_inserted_ms = 0

    def plan_and_consume(
        self,
        *,
        boundary_id: str,
        requested_ms: int | None,
        target_kind: PauseTargetKind = PauseTargetKind.TOTAL_BOUNDARY,
        observation: SilenceObservation | None = None,
    ) -> PauseLedgerEntry:
        if boundary_id in self._entries:
            # Idempotent: never insert twice for same logical boundary
            prev = self._entries[boundary_id]
            return PauseLedgerEntry(
                boundary_id=prev.boundary_id,
                target_kind=prev.target_kind,
                requested_ms=prev.requested_ms,
                target_samples=prev.target_samples,
                left_credited_samples=prev.left_credited_samples,
                right_credited_samples=prev.right_credited_samples,
                inserted_samples=0,
                owner=prev.owner,
                consumed=True,
                reason="DUPLICATE_BOUNDARY_ID_NO_OP",
            )

        if requested_ms is None or requested_ms <= 0:
            entry = PauseLedgerEntry(
                boundary_id=boundary_id,
                target_kind=target_kind,
                requested_ms=0 if requested_ms is None else int(requested_ms),
                target_samples=0,
                left_credited_samples=0,
                right_credited_samples=0,
                inserted_samples=0,
                owner="F6",
                consumed=True,
                reason="ZERO_OR_NULL_PAUSE",
            )
            self._entries[boundary_id] = entry
            return entry

        capped_ms = min(int(requested_ms), self.max_per_boundary_ms)
        remaining_plan_ms = max(0, self.max_total_plan_ms - self._total_inserted_ms)
        effective_ms = min(capped_ms, remaining_plan_ms)
        target_samples = int(round((effective_ms * self.rate_hz) / 1000.0))

        if target_kind == PauseTargetKind.ADDITIONAL_LEGACY:
            inserted = target_samples
            left_cred = 0
            right_cred = 0
            reason = "ADDITIONAL_LEGACY_APPLIED"
        else:
            left_nat = observation.left_trailing_samples if observation is not None else 0
            right_nat = observation.right_leading_samples if observation is not None else 0
            left_cred = min(target_samples, left_nat)
            right_cred = min(max(0, target_samples - left_cred), right_nat)
            credited = left_cred + right_cred
            inserted = max(0, target_samples - credited)
            reason = "TOTAL_BOUNDARY_CREDITED" if credited > 0 else "TOTAL_BOUNDARY_INSERTED"

        inserted_ms = int(round((inserted * 1000.0) / self.rate_hz))
        self._total_inserted_ms += inserted_ms
        entry = PauseLedgerEntry(
            boundary_id=boundary_id,
            target_kind=target_kind,
            requested_ms=int(requested_ms),
            target_samples=target_samples,
            left_credited_samples=left_cred,
            right_credited_samples=right_cred,
            inserted_samples=inserted,
            owner="F6",
            consumed=True,
            reason=reason,
        )
        self._entries[boundary_id] = entry
        return entry
