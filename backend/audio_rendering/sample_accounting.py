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
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class SampleAccountingSnapshot:
    """Immutable stage- and rate-separated sample accounting snapshot."""

    input_rate_hz: int
    output_rate_hz: int
    raw_48k_accepted: int
    raw_48k_consumed: int
    raw_48k_rejected: int
    raw_48k_discarded: int
    dsp_48k_processed: int
    resampler_in_48k: int
    resampler_out_samples: int
    resampler_flushed_tail_samples: int
    resampler_discarded_48k: int
    expected_out_rational_num: int
    expected_out_rational_den: int
    planned_silence_samples: int
    quantized_samples: int
    raw_peak_clipped_samples: int
    limiter_saturated_samples: int
    quantizer_saturated_samples: int
    framed_valid_samples: int
    terminal_padding_samples: int
    residual_pending_samples: int
    residual_discarded_samples: int
    queued_samples: int
    submitted_samples: int
    in_flight_uncertain_samples: int
    canceled_unsent_samples: int
    frames_emitted: int
    terminal_frames_emitted: int

    @property
    def expected_output_exact(self) -> Fraction:
        return Fraction(self.expected_out_rational_num, self.expected_out_rational_den)


class SampleAccounting:
    """
    Stage-specific sample accounting ledger keeping 48 kHz input domain strictly
    separate from 16 kHz / 8 kHz output domain.
    """

    def __init__(self, *, input_rate_hz: int = 48000, output_rate_hz: int = 16000) -> None:
        if input_rate_hz != 48000:
            raise ValueError("input_rate_hz must be 48000")
        if output_rate_hz not in (8000, 16000):
            raise ValueError("output_rate_hz must be 8000 or 16000")
        self.input_rate_hz = input_rate_hz
        self.output_rate_hz = output_rate_hz

        # 48 kHz input domain
        self.raw_48k_accepted = 0
        self.raw_48k_consumed = 0
        self.raw_48k_rejected = 0
        self.raw_48k_discarded = 0
        self.dsp_48k_processed = 0

        # Resampler rational domain
        self.resampler_in_48k = 0
        self.resampler_out_samples = 0
        self.resampler_flushed_tail_samples = 0
        self.resampler_discarded_48k = 0

        # Output domain (8k or 16k)
        self.planned_silence_samples = 0
        self.quantized_samples = 0
        self.raw_peak_clipped_samples = 0
        self.limiter_saturated_samples = 0
        self.quantizer_saturated_samples = 0
        self.framed_valid_samples = 0
        self.terminal_padding_samples = 0
        self.residual_pending_samples = 0
        self.residual_discarded_samples = 0
        self.queued_samples = 0
        self.submitted_samples = 0
        self.in_flight_uncertain_samples = 0
        self.canceled_unsent_samples = 0
        self.frames_emitted = 0
        self.terminal_frames_emitted = 0

    def record_raw_accepted(self, sample_count: int, raw_clipped: int = 0) -> None:
        self.raw_48k_accepted += sample_count
        self.raw_peak_clipped_samples += raw_clipped

    def record_raw_rejected(self, sample_count: int) -> None:
        self.raw_48k_rejected += max(0, sample_count)

    def record_raw_discarded(self, sample_count: int) -> None:
        self.raw_48k_discarded += max(0, sample_count)

    def record_dsp_processed(self, sample_count: int) -> None:
        self.dsp_48k_processed += sample_count

    def record_resample_step(self, in_48k: int, out_samples: int, *, is_eos_flush: bool = False) -> None:
        self.raw_48k_consumed += in_48k
        self.resampler_in_48k += in_48k
        self.resampler_out_samples += out_samples
        if is_eos_flush:
            self.resampler_flushed_tail_samples += out_samples

    def record_resampler_discarded(self, discarded_48k: int) -> None:
        self.resampler_discarded_48k += max(0, discarded_48k)

    def record_quantized(self, sample_count: int, *, limiter_saturated: int = 0, quantizer_saturated: int = 0) -> None:
        self.quantized_samples += sample_count
        self.limiter_saturated_samples += limiter_saturated
        self.quantizer_saturated_samples += quantizer_saturated

    def record_planned_silence(self, sample_count: int) -> None:
        self.planned_silence_samples += sample_count

    def record_frame_emitted(
        self,
        *,
        valid_samples: int,
        padding_samples: int,
        is_terminal: bool,
        new_residual_pending: int,
    ) -> None:
        self.framed_valid_samples += valid_samples
        self.terminal_padding_samples += padding_samples
        self.residual_pending_samples = new_residual_pending
        self.frames_emitted += 1
        if is_terminal:
            self.terminal_frames_emitted += 1

    def record_residual_updated(self, new_residual_pending: int) -> None:
        self.residual_pending_samples = new_residual_pending

    def record_residual_discarded(self, discarded_samples: int) -> None:
        self.residual_discarded_samples += discarded_samples
        self.residual_pending_samples = 0

    def record_queued(self, valid_samples: int) -> None:
        self.queued_samples += valid_samples

    def record_submitted(self, valid_samples: int, *, in_flight_uncertain: bool = False) -> None:
        self.queued_samples = max(0, self.queued_samples - valid_samples)
        if in_flight_uncertain:
            self.in_flight_uncertain_samples += valid_samples
        else:
            self.submitted_samples += valid_samples

    def record_canceled_from_queue(self, valid_samples: int) -> None:
        self.queued_samples = max(0, self.queued_samples - valid_samples)
        self.canceled_unsent_samples += valid_samples

    def record_unenqueued_frame_discarded(self, valid_samples: int) -> None:
        """Account framed samples rejected before queue admission (backpressure/cancel)."""
        self.canceled_unsent_samples += valid_samples

    def verify_output_balance(self) -> tuple[bool, list[str]]:
        """Verify same-rate output-domain sample conservation invariants."""
        errors: list[str] = []
        lhs = self.quantized_samples + self.planned_silence_samples
        rhs = self.framed_valid_samples + self.residual_pending_samples + self.residual_discarded_samples
        if lhs != rhs:
            errors.append(f"OUTPUT_SAMPLE_IMBALANCE:produced={lhs}!=accounted={rhs}")

        delivery_total = (
            self.submitted_samples
            + self.queued_samples
            + self.in_flight_uncertain_samples
            + self.canceled_unsent_samples
        )
        if delivery_total != self.framed_valid_samples:
            errors.append(
                f"DELIVERY_SAMPLE_IMBALANCE:delivered_ledger={delivery_total}!=framed_valid={self.framed_valid_samples}"
            )
        return len(errors) == 0, errors

    def snapshot(self) -> SampleAccountingSnapshot:
        return SampleAccountingSnapshot(
            input_rate_hz=self.input_rate_hz,
            output_rate_hz=self.output_rate_hz,
            raw_48k_accepted=self.raw_48k_accepted,
            raw_48k_consumed=self.raw_48k_consumed,
            raw_48k_rejected=self.raw_48k_rejected,
            raw_48k_discarded=self.raw_48k_discarded,
            dsp_48k_processed=self.dsp_48k_processed,
            resampler_in_48k=self.resampler_in_48k,
            resampler_out_samples=self.resampler_out_samples,
            resampler_flushed_tail_samples=self.resampler_flushed_tail_samples,
            resampler_discarded_48k=self.resampler_discarded_48k,
            expected_out_rational_num=self.resampler_in_48k * self.output_rate_hz,
            expected_out_rational_den=self.input_rate_hz,
            planned_silence_samples=self.planned_silence_samples,
            quantized_samples=self.quantized_samples,
            raw_peak_clipped_samples=self.raw_peak_clipped_samples,
            limiter_saturated_samples=self.limiter_saturated_samples,
            quantizer_saturated_samples=self.quantizer_saturated_samples,
            framed_valid_samples=self.framed_valid_samples,
            terminal_padding_samples=self.terminal_padding_samples,
            residual_pending_samples=self.residual_pending_samples,
            residual_discarded_samples=self.residual_discarded_samples,
            queued_samples=self.queued_samples,
            submitted_samples=self.submitted_samples,
            in_flight_uncertain_samples=self.in_flight_uncertain_samples,
            canceled_unsent_samples=self.canceled_unsent_samples,
            frames_emitted=self.frames_emitted,
            terminal_frames_emitted=self.terminal_frames_emitted,
        )
