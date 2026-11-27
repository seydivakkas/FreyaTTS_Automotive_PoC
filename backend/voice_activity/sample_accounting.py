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

from backend.core.contracts.validation import require_strict_int


class RejectionReason(StrEnum):
    SCHEMA_VERSION = "SCHEMA_VERSION"
    WRONG_STREAM = "WRONG_STREAM"
    WRONG_FORMAT = "WRONG_FORMAT"
    NONFINITE_OR_LENGTH = "NONFINITE_OR_LENGTH"
    EMPTY_FRAME = "EMPTY_FRAME"
    DUPLICATE = "DUPLICATE"
    OVERLAP = "OVERLAP"
    STALE_EPOCH = "STALE_EPOCH"
    BACKPRESSURE = "BACKPRESSURE"
    CLOSED = "CLOSED"


@dataclass(frozen=True, slots=True)
class SampleAccountingSnapshot:
    accepted_real_samples: int
    processed_windows: int
    processed_real_samples: int
    buffered_remainder_samples: int
    unclassified_tail_samples: int
    model_padding_samples: int
    transferred_utterance_samples: int
    transferred_pre_roll_samples: int
    transferred_post_roll_samples: int
    retained_history_samples: int
    excluded_gap_samples: int
    discarded_candidate_samples: int
    discarded_abort_samples: int
    rejected_samples: int
    rejected_by_reason: dict[str, int]
    conservation_balanced: bool


class SampleAccountingLedger:
    """Single-stream real sample conservation and exclusion accounting ledger."""

    def __init__(self) -> None:
        self.accepted_real_samples: int = 0
        self.processed_windows: int = 0
        self.processed_real_samples: int = 0
        self.buffered_remainder_samples: int = 0
        self.unclassified_tail_samples: int = 0
        self.model_padding_samples: int = 0
        self.transferred_utterance_samples: int = 0
        self.transferred_pre_roll_samples: int = 0
        self.transferred_post_roll_samples: int = 0
        self.retained_history_samples: int = 0
        self.excluded_gap_samples: int = 0
        self.discarded_candidate_samples: int = 0
        self.discarded_abort_samples: int = 0
        self.rejected_samples: int = 0
        self.rejected_by_reason: dict[str, int] = {r.value: 0 for r in RejectionReason}

    def record_accepted(self, real_samples: int) -> None:
        require_strict_int(real_samples, "real_samples", minimum=0)
        self.accepted_real_samples += real_samples

    def record_window_processed(self, real_samples: int, *, model_padding_samples: int = 0) -> None:
        require_strict_int(real_samples, "real_samples", minimum=0)
        require_strict_int(model_padding_samples, "model_padding_samples", minimum=0)
        self.processed_windows += 1
        self.processed_real_samples += real_samples
        self.model_padding_samples += model_padding_samples

    def set_buffered_remainder(self, remainder_samples: int) -> None:
        require_strict_int(remainder_samples, "remainder_samples", minimum=0)
        self.buffered_remainder_samples = remainder_samples

    def record_unclassified_tail(self, tail_samples: int) -> None:
        require_strict_int(tail_samples, "tail_samples", minimum=0)
        self.unclassified_tail_samples += tail_samples

    def record_rejected(self, reason: RejectionReason, sample_count: int) -> None:
        require_strict_int(sample_count, "sample_count", minimum=0)
        self.rejected_samples += sample_count
        self.rejected_by_reason[reason.value] = self.rejected_by_reason.get(reason.value, 0) + sample_count

    def record_gap_excluded(self, gap_samples: int) -> None:
        require_strict_int(gap_samples, "gap_samples", minimum=0)
        self.excluded_gap_samples += gap_samples

    def record_remainder_discarded_on_gap_or_abort(self, remainder_samples: int) -> None:
        require_strict_int(remainder_samples, "remainder_samples", minimum=0)
        self.discarded_abort_samples += remainder_samples
        self.buffered_remainder_samples = 0

    def record_candidate_discarded(self, sample_count: int) -> None:
        require_strict_int(sample_count, "sample_count", minimum=0)
        self.discarded_candidate_samples += sample_count

    def record_abort_discarded(self, sample_count: int) -> None:
        require_strict_int(sample_count, "sample_count", minimum=0)
        self.discarded_abort_samples += sample_count

    def record_transferred_utterance(
        self,
        *,
        total_samples: int,
        pre_roll_samples: int,
        post_roll_samples: int,
    ) -> None:
        require_strict_int(total_samples, "total_samples", minimum=0)
        require_strict_int(pre_roll_samples, "pre_roll_samples", minimum=0)
        require_strict_int(post_roll_samples, "post_roll_samples", minimum=0)
        self.transferred_utterance_samples += total_samples
        self.transferred_pre_roll_samples += pre_roll_samples
        self.transferred_post_roll_samples += post_roll_samples

    def set_retained_history(self, retained_samples: int) -> None:
        require_strict_int(retained_samples, "retained_samples", minimum=0)
        self.retained_history_samples = retained_samples

    def is_conserved(self) -> bool:
        """Verify accepted real input equals processed + remainder + unclassified + abort-discarded remainder."""
        accounted = (
            self.processed_real_samples
            + self.buffered_remainder_samples
            + self.unclassified_tail_samples
        )
        # Note: if an active remainder was discarded on gap/abort before processing,
        # accepted_real_samples includes those bytes; we keep strict conservation on active pipeline.
        return self.accepted_real_samples == accounted or (
            self.accepted_real_samples == accounted + self.discarded_abort_samples
        )

    def snapshot(self) -> SampleAccountingSnapshot:
        return SampleAccountingSnapshot(
            accepted_real_samples=self.accepted_real_samples,
            processed_windows=self.processed_windows,
            processed_real_samples=self.processed_real_samples,
            buffered_remainder_samples=self.buffered_remainder_samples,
            unclassified_tail_samples=self.unclassified_tail_samples,
            model_padding_samples=self.model_padding_samples,
            transferred_utterance_samples=self.transferred_utterance_samples,
            transferred_pre_roll_samples=self.transferred_pre_roll_samples,
            transferred_post_roll_samples=self.transferred_post_roll_samples,
            retained_history_samples=self.retained_history_samples,
            excluded_gap_samples=self.excluded_gap_samples,
            discarded_candidate_samples=self.discarded_candidate_samples,
            discarded_abort_samples=self.discarded_abort_samples,
            rejected_samples=self.rejected_samples,
            rejected_by_reason=dict(self.rejected_by_reason),
            conservation_balanced=self.is_conserved(),
        )
