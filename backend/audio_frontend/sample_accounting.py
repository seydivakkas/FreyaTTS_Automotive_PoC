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

from dataclasses import dataclass, field
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class OffsetMapping:
    """Explicit mapping between native source [start, end) and 16 kHz output [start, end)."""

    input_sequence: int
    input_start_sample: int
    input_end_sample_exclusive: int
    output_sequence: int | None
    output_start_sample: int | None
    output_end_sample_exclusive: int | None
    padding_samples: int = 0
    has_gap_before: bool = False


@dataclass(slots=True)
class SampleLedger:
    """
    Integer-sample and rational-duration accounting ledger for one audio stream/epoch.

    Tracks native input counters and 16 kHz output counters separately without
    conflating counts across sample rates or allowing negative counters.
    """

    native_sample_rate_hz: int
    output_sample_rate_hz: int = 16000
    input_received_samples: int = 0
    input_accepted_samples: int = 0
    input_rejected_samples: int = 0
    input_consumed_samples: int = 0
    pending_input_samples: int = 0
    output_emitted_samples: int = 0
    pending_output_samples: int = 0
    explicit_discard_samples: int = 0
    padding_samples: int = 0
    gap_samples: int = 0
    overlap_rejected_samples: int = 0
    next_input_sequence: int = 0
    next_input_offset: int = 0
    next_output_sequence: int = 0
    next_output_offset: int = 0
    eos_received: bool = False
    eos_flushed: bool = False
    mappings: list[OffsetMapping] = field(default_factory=list)

    @property
    def rate_ratio(self) -> Fraction:
        return Fraction(self.output_sample_rate_hz, self.native_sample_rate_hz)

    @property
    def valid_input_accepted_samples(self) -> int:
        return max(0, self.input_accepted_samples - self.padding_samples)

    @property
    def native_duration_seconds(self) -> Fraction:
        return Fraction(self.valid_input_accepted_samples, self.native_sample_rate_hz)

    @property
    def output_duration_seconds(self) -> Fraction:
        return Fraction(self.output_emitted_samples, self.output_sample_rate_hz)

    @property
    def expected_output_samples_exact(self) -> Fraction:
        return Fraction(self.valid_input_accepted_samples) * self.rate_ratio

    def record_rejected(self, sample_count: int, *, is_overlap: bool = False) -> None:
        if sample_count > 0:
            self.input_received_samples += sample_count
            self.input_rejected_samples += sample_count
            if is_overlap:
                self.overlap_rejected_samples += sample_count

    def check_ordering(
        self,
        *,
        sequence: int,
        sample_offset: int,
        sample_count: int,
        allow_gap: bool = True,
    ) -> tuple[bool, str, int]:
        """
        Verify sequence and half-open [sample_offset, sample_offset + sample_count) continuity.

        Returns (ok, reason, gap_samples).
        """
        if sequence < self.next_input_sequence:
            if sample_offset < self.next_input_offset:
                return False, "duplicate_or_overlapping_sequence", 0
            return False, "out_of_order_sequence", 0
        if sample_offset < self.next_input_offset:
            return False, "overlapping_sample_range", 0
        if sequence > self.next_input_sequence and not allow_gap:
            return False, "sequence_gap_rejected", 0
        gap = sample_offset - self.next_input_offset
        if gap > 0 and not allow_gap:
            return False, "sample_offset_gap_rejected", gap
        return True, "ok", gap

    def record_accepted(
        self,
        *,
        sequence: int,
        sample_offset: int,
        sample_count: int,
        valid_sample_count: int | None,
        gap_samples: int = 0,
    ) -> int:
        valid_n = sample_count if valid_sample_count is None else valid_sample_count
        pad_n = sample_count - valid_n
        self.input_received_samples += sample_count
        self.input_accepted_samples += sample_count
        self.padding_samples += pad_n
        self.pending_input_samples += valid_n
        if gap_samples > 0:
            self.gap_samples += gap_samples
        self.next_input_sequence = sequence + 1
        self.next_input_offset = sample_offset + sample_count
        return valid_n

    def record_consumed_and_emitted(
        self,
        *,
        input_sequence: int,
        input_start_sample: int,
        input_end_sample_exclusive: int,
        consumed_valid_samples: int,
        emitted_output_samples: int,
        padding_samples: int = 0,
        has_gap_before: bool = False,
        pending_output_samples: int = 0,
    ) -> int | None:
        self.input_consumed_samples += consumed_valid_samples
        self.pending_input_samples = max(0, self.pending_input_samples - consumed_valid_samples)
        self.pending_output_samples = max(0, pending_output_samples)

        out_seq: int | None = None
        out_start: int | None = None
        out_end: int | None = None
        if emitted_output_samples > 0:
            out_seq = self.next_output_sequence
            out_start = self.next_output_offset
            out_end = out_start + emitted_output_samples
            self.output_emitted_samples += emitted_output_samples
            self.next_output_sequence += 1
            self.next_output_offset = out_end

        if len(self.mappings) < 4096:
            self.mappings.append(
                OffsetMapping(
                    input_sequence=input_sequence,
                    input_start_sample=input_start_sample,
                    input_end_sample_exclusive=input_end_sample_exclusive,
                    output_sequence=out_seq,
                    output_start_sample=out_start,
                    output_end_sample_exclusive=out_end,
                    padding_samples=padding_samples,
                    has_gap_before=has_gap_before,
                )
            )
        return out_seq

    def record_eos_flush(self, emitted_output_samples: int) -> int | None:
        self.eos_received = True
        self.eos_flushed = True
        self.pending_output_samples = 0
        if emitted_output_samples <= 0:
            return None
        out_seq = self.next_output_sequence
        out_start = self.next_output_offset
        out_end = out_start + emitted_output_samples
        self.output_emitted_samples += emitted_output_samples
        self.next_output_sequence += 1
        self.next_output_offset = out_end
        return out_seq

    def record_explicit_discard(self, discarded_input_samples: int, discarded_output_samples: int = 0) -> None:
        if discarded_input_samples > 0:
            self.explicit_discard_samples += discarded_input_samples
            self.pending_input_samples = max(0, self.pending_input_samples - discarded_input_samples)
        if discarded_output_samples > 0:
            self.explicit_discard_samples += discarded_output_samples
            self.pending_output_samples = max(0, self.pending_output_samples - discarded_output_samples)

    def assert_invariants(self) -> None:
        counters = (
            self.input_received_samples,
            self.input_accepted_samples,
            self.input_rejected_samples,
            self.input_consumed_samples,
            self.pending_input_samples,
            self.output_emitted_samples,
            self.pending_output_samples,
            self.explicit_discard_samples,
            self.padding_samples,
            self.gap_samples,
            self.overlap_rejected_samples,
        )
        if any(c < 0 for c in counters):
            raise AssertionError(f"Negative counter in SampleLedger: {counters}")
        if self.input_accepted_samples + self.input_rejected_samples != self.input_received_samples:
            raise AssertionError("Received samples != accepted + rejected")

    def summary_dict(self) -> dict[str, int | str | bool]:
        return {
            "native_sample_rate_hz": self.native_sample_rate_hz,
            "output_sample_rate_hz": self.output_sample_rate_hz,
            "input_received_samples": self.input_received_samples,
            "input_accepted_samples": self.input_accepted_samples,
            "input_rejected_samples": self.input_rejected_samples,
            "input_consumed_samples": self.input_consumed_samples,
            "pending_input_samples": self.pending_input_samples,
            "output_emitted_samples": self.output_emitted_samples,
            "pending_output_samples": self.pending_output_samples,
            "explicit_discard_samples": self.explicit_discard_samples,
            "padding_samples": self.padding_samples,
            "gap_samples": self.gap_samples,
            "overlap_rejected_samples": self.overlap_rejected_samples,
            "native_duration_ratio": str(self.native_duration_seconds),
            "output_duration_ratio": str(self.output_duration_seconds),
            "eos_received": self.eos_received,
            "eos_flushed": self.eos_flushed,
        }
