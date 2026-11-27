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

from collections import deque
from dataclasses import dataclass

import numpy as np

from backend.core.contracts.validation import require_strict_int


class LookbackCapacityExceededError(RuntimeError):
    """Raised when pinned audio + history would exceed configured sample/byte bounds."""


@dataclass(frozen=True, slots=True)
class PinResult:
    utterance_start_sample: int
    candidate_onset_sample: int
    actual_pre_roll_samples: int


@dataclass(slots=True)
class _HistoryChunk:
    start_sample: int
    samples_f32: np.ndarray

    @property
    def end_sample_exclusive(self) -> int:
        return self.start_sample + int(self.samples_f32.shape[0])


class LookbackBuffer:
    """
    Single unified sample-bounded audio history owner (16 kHz mono float32).

    Owns pre-roll history, candidate confirmation retention, and active utterance audio
    without duplicating LookbackBuffer/Endpoint.pre or creating mutable ndarray aliases.
    """

    def __init__(
        self,
        *,
        pre_roll_samples: int = 5120,
        history_capacity_samples: int = 6656,
        max_utterance_samples: int = 320000,
        overlap_consecutive_utterances: bool = False,
        epoch_start_sample: int = 0,
        strict_pinned_capacity: bool = False,
    ) -> None:
        require_strict_int(pre_roll_samples, "pre_roll_samples", minimum=0)
        require_strict_int(history_capacity_samples, "history_capacity_samples", minimum=1)
        require_strict_int(max_utterance_samples, "max_utterance_samples", minimum=1)
        require_strict_int(epoch_start_sample, "epoch_start_sample", minimum=0)

        self.pre_roll_samples = pre_roll_samples
        self.history_capacity_samples = history_capacity_samples
        self.max_utterance_samples = max_utterance_samples
        self.overlap_consecutive_utterances = overlap_consecutive_utterances
        self.strict_pinned_capacity = strict_pinned_capacity

        self._chunks: deque[_HistoryChunk] = deque()
        self._total_samples: int = 0
        self._epoch_start_sample: int = epoch_start_sample
        self._min_eligible_offset: int = epoch_start_sample
        self._pinned_start_sample: int | None = None
        self._candidate_onset_sample: int | None = None

    @property
    def total_samples(self) -> int:
        return self._total_samples

    @property
    def total_bytes(self) -> int:
        return self._total_samples * 4

    @property
    def buffer_start_sample(self) -> int | None:
        return self._chunks[0].start_sample if self._chunks else None

    @property
    def buffer_end_sample(self) -> int | None:
        return self._chunks[-1].end_sample_exclusive if self._chunks else None

    @property
    def pinned_start_sample(self) -> int | None:
        return self._pinned_start_sample

    @property
    def min_eligible_offset(self) -> int:
        return self._min_eligible_offset

    @property
    def max_retained_samples(self) -> int:
        if self.strict_pinned_capacity:
            return self.history_capacity_samples
        return max(self.history_capacity_samples, self.max_utterance_samples + self.history_capacity_samples)

    def append_samples(self, start_sample: int, samples_f32: np.ndarray) -> None:
        """Append immutable real samples to the unified history ring."""
        require_strict_int(start_sample, "start_sample", minimum=0)
        if samples_f32.ndim != 1 or samples_f32.dtype != np.float32:
            raise ValueError("samples_f32 must be 1D float32")
        n = int(samples_f32.shape[0])
        if n == 0:
            return

        if self._chunks:
            expected = self._chunks[-1].end_sample_exclusive
            if start_sample < expected:
                raise ValueError(f"Overlapping append: start_sample={start_sample} < expected={expected}")
            if start_sample > expected:
                # Gap boundary must reset history explicitly; cannot silently bridge gap.
                self.reset_for_gap(start_sample)

        owned = samples_f32.copy()
        owned.setflags(write=False)

        if self._pinned_start_sample is not None:
            projected = self._total_samples + n
            if projected > self.max_retained_samples:
                raise LookbackCapacityExceededError(
                    f"Pinned history capacity exceeded: {projected} > {self.max_retained_samples}"
                )

        self._chunks.append(_HistoryChunk(start_sample=start_sample, samples_f32=owned))
        self._total_samples += n
        self._evict_unpinned()

    def _evict_unpinned(self) -> None:
        if self._pinned_start_sample is None:
            limit = self.history_capacity_samples
            while self._total_samples > limit and self._chunks:
                excess = self._total_samples - limit
                head = self._chunks[0]
                head_len = int(head.samples_f32.shape[0])
                if head_len <= excess:
                    self._chunks.popleft()
                    self._total_samples -= head_len
                else:
                    trimmed = head.samples_f32[excess:].copy()
                    trimmed.setflags(write=False)
                    self._chunks[0] = _HistoryChunk(
                        start_sample=head.start_sample + excess,
                        samples_f32=trimmed,
                    )
                    self._total_samples -= excess
            return

        # When pinned, evict only samples strictly older than pinned_start_sample.
        while self._chunks and self._chunks[0].end_sample_exclusive <= self._pinned_start_sample:
            head = self._chunks.popleft()
            self._total_samples -= int(head.samples_f32.shape[0])
        if self._chunks and self._chunks[0].start_sample < self._pinned_start_sample:
            drop = self._pinned_start_sample - self._chunks[0].start_sample
            head = self._chunks[0]
            trimmed = head.samples_f32[drop:].copy()
            trimmed.setflags(write=False)
            self._chunks[0] = _HistoryChunk(start_sample=self._pinned_start_sample, samples_f32=trimmed)
            self._total_samples -= drop

    def pin_candidate(self, candidate_onset_sample: int) -> PinResult:
        """
        Pin pre-roll + candidate onset at first qualifying window.
        Never invents leading zeros if available history is shorter than pre_roll_samples.
        """
        require_strict_int(candidate_onset_sample, "candidate_onset_sample", minimum=0)
        desired_start = max(
            self._epoch_start_sample,
            self._min_eligible_offset,
            candidate_onset_sample - self.pre_roll_samples,
        )
        buf_start = self.buffer_start_sample
        if buf_start is None:
            actual_start = candidate_onset_sample
        else:
            actual_start = max(desired_start, buf_start)
        actual_start = min(actual_start, candidate_onset_sample)
        actual_pre_roll = candidate_onset_sample - actual_start
        self._pinned_start_sample = actual_start
        self._candidate_onset_sample = candidate_onset_sample
        self._evict_unpinned()
        return PinResult(
            utterance_start_sample=actual_start,
            candidate_onset_sample=candidate_onset_sample,
            actual_pre_roll_samples=actual_pre_roll,
        )

    def release_candidate_pin(self) -> None:
        """Unpin a rejected candidate while keeping eligible history bounded."""
        self._pinned_start_sample = None
        self._candidate_onset_sample = None
        self._evict_unpinned()

    def extract_slice(self, start_sample: int, end_sample_exclusive: int) -> bytes:
        """
        Return immutable FLOAT32_LE bytes for exact half-open interval [start_sample, end_sample_exclusive).
        Guarantees zero duplicate samples and zero mutable ndarray aliasing.
        """
        require_strict_int(start_sample, "start_sample", minimum=0)
        require_strict_int(end_sample_exclusive, "end_sample_exclusive", minimum=start_sample)
        if start_sample == end_sample_exclusive:
            return b""
        buf_start = self.buffer_start_sample
        buf_end = self.buffer_end_sample
        if buf_start is None or buf_end is None or start_sample < buf_start or end_sample_exclusive > buf_end:
            raise ValueError(
                f"Requested slice [{start_sample}, {end_sample_exclusive}) outside retained history [{buf_start}, {buf_end})"
            )

        parts: list[np.ndarray] = []
        cursor = start_sample
        for chunk in self._chunks:
            c_start = chunk.start_sample
            c_end = chunk.end_sample_exclusive
            if c_end <= cursor:
                continue
            if c_start >= end_sample_exclusive:
                break
            if c_start > cursor:
                raise ValueError(f"Non-contiguous gap inside history between {cursor} and {c_start}")
            s_idx = cursor - c_start
            e_idx = min(c_end, end_sample_exclusive) - c_start
            parts.append(chunk.samples_f32[s_idx:e_idx])
            cursor += e_idx - s_idx
            if cursor >= end_sample_exclusive:
                break

        if cursor != end_sample_exclusive:
            raise ValueError(f"Incomplete slice: reached {cursor}, expected {end_sample_exclusive}")

        joined = parts[0] if len(parts) == 1 else np.concatenate(parts)
        return np.ascontiguousarray(joined, dtype=np.float32).tobytes()

    def commit_finalized(self, finalized_end_sample: int) -> None:
        """
        Unpin finalized utterance and advance non-overlap floor (when overlap is disabled),
        retaining only eligible post-cut history for subsequent utterances.
        """
        require_strict_int(finalized_end_sample, "finalized_end_sample", minimum=0)
        self._pinned_start_sample = None
        self._candidate_onset_sample = None
        if not self.overlap_consecutive_utterances:
            self._min_eligible_offset = max(self._min_eligible_offset, finalized_end_sample)
            # Drop audio strictly prior to min_eligible_offset so consecutive utterances never overlap.
            while self._chunks and self._chunks[0].end_sample_exclusive <= self._min_eligible_offset:
                head = self._chunks.popleft()
                self._total_samples -= int(head.samples_f32.shape[0])
            if self._chunks and self._chunks[0].start_sample < self._min_eligible_offset:
                drop = self._min_eligible_offset - self._chunks[0].start_sample
                head = self._chunks[0]
                trimmed = head.samples_f32[drop:].copy()
                trimmed.setflags(write=False)
                self._chunks[0] = _HistoryChunk(start_sample=self._min_eligible_offset, samples_f32=trimmed)
                self._total_samples -= drop
        self._evict_unpinned()

    def reset_for_gap(self, new_epoch_start_sample: int) -> int:
        """Atomically clear history on discontinuity/gap or format_epoch advance."""
        require_strict_int(new_epoch_start_sample, "new_epoch_start_sample", minimum=0)
        discarded = self._total_samples
        self._chunks.clear()
        self._total_samples = 0
        self._epoch_start_sample = new_epoch_start_sample
        self._min_eligible_offset = new_epoch_start_sample
        self._pinned_start_sample = None
        self._candidate_onset_sample = None
        return discarded

    def clear(self) -> int:
        discarded = self._total_samples
        self._chunks.clear()
        self._total_samples = 0
        self._pinned_start_sample = None
        self._candidate_onset_sample = None
        return discarded
