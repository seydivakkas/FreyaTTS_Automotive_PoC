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
from typing import Any

import numpy as np

from backend.core.contracts.audio import AudioEncoding, AudioFrame
from backend.core.contracts.common import ContractVersion, StreamDirection, StreamRef
from backend.voice_activity.sample_accounting import RejectionReason, SampleAccountingLedger

VAD_WINDOW_SAMPLES = 512
SUPPORTED_SAMPLE_RATE_HZ = 16000


@dataclass(frozen=True, slots=True)
class VADWindow:
    """512-sample 16 kHz analysis window aligned to accepted source sample offsets."""

    stream_ref: StreamRef
    window_index: int
    start_sample: int
    end_sample_exclusive: int
    valid_samples: int
    samples_f32: np.ndarray
    model_input_f32: np.ndarray
    padded_for_inference: bool
    config_revision: str

    def __post_init__(self) -> None:
        if not (1 <= self.valid_samples <= VAD_WINDOW_SAMPLES):
            raise ValueError(f"valid_samples must be in 1..{VAD_WINDOW_SAMPLES}, got {self.valid_samples}")
        if self.end_sample_exclusive != self.start_sample + self.valid_samples:
            raise ValueError("end_sample_exclusive must equal start_sample + valid_samples")
        if self.model_input_f32.shape != (VAD_WINDOW_SAMPLES,) or self.model_input_f32.dtype != np.float32:
            raise ValueError("model_input_f32 must be 1D float32 of length 512")
        if self.samples_f32.shape != (self.valid_samples,) or self.samples_f32.dtype != np.float32:
            raise ValueError("samples_f32 must match valid_samples float32")


@dataclass(frozen=True, slots=True)
class FrameAdmissionResult:
    """Outcome of admitting one AudioFrame into the 512-sample synchronizer."""

    accepted: bool
    rejection_reason: RejectionReason | None
    windows: tuple[VADWindow, ...]
    discontinuity_gap_samples: int = 0
    accepted_real_samples: int = 0
    error_detail: str = ""


def decode_audio_frame_to_f32(frame: AudioFrame) -> np.ndarray:
    """Decode validated 16 kHz mono PCM_S16LE or FLOAT32_LE AudioFrame once into immutable float32."""
    real_count = frame.sample_count if frame.valid_sample_count is None else frame.valid_sample_count
    if real_count <= 0:
        raise ValueError("AudioFrame contains zero valid samples")

    if frame.format.encoding == AudioEncoding.PCM_S16LE:
        arr = np.frombuffer(frame.payload, dtype="<i2", count=real_count).astype(np.float32) / np.float32(32768.0)
    elif frame.format.encoding == AudioEncoding.FLOAT32_LE:
        arr = np.frombuffer(frame.payload, dtype="<f4", count=real_count).astype(np.float32, copy=True)
        if not np.all(np.isfinite(arr)):
            raise ValueError("FLOAT32_LE payload contains NaN or Inf")
    else:
        raise ValueError(f"Unsupported AudioEncoding: {frame.format.encoding}")

    arr.setflags(write=False)
    return arr


class FrameSynchronizer:
    """
    Validates M01 AudioFrame admission, enforces monotonic offsets/epochs,
    buffers <512 remainder samples, and emits exact 512-sample 16 kHz VADWindows.
    """

    def __init__(
        self,
        stream_ref: StreamRef,
        *,
        config_revision: str = "default-local",
        max_pending_input_samples: int = 16000,
        max_pending_bytes: int = 64000,
        allow_eos_model_padding: bool = True,
        accounting: SampleAccountingLedger | None = None,
    ) -> None:
        if stream_ref.direction != StreamDirection.INPUT:
            raise ValueError("FrameSynchronizer requires StreamDirection.INPUT")
        self._stream_ref = stream_ref
        self._config_revision = config_revision
        self._max_pending_input_samples = max_pending_input_samples
        self._max_pending_bytes = max_pending_bytes
        self._allow_eos_model_padding = allow_eos_model_padding
        self._accounting = accounting or SampleAccountingLedger()

        self._remainder = np.zeros(0, dtype=np.float32)
        self._remainder_start_sample: int = 0
        self._expected_next_offset: int | None = None
        self._last_sequence: int | None = None
        self._next_window_index: int = 0
        self._eos_flushed: bool = False
        self._closed: bool = False

    @property
    def stream_ref(self) -> StreamRef:
        return self._stream_ref

    @property
    def accounting(self) -> SampleAccountingLedger:
        return self._accounting

    @property
    def remainder_samples(self) -> int:
        return int(self._remainder.shape[0])

    @property
    def expected_next_offset(self) -> int | None:
        return self._expected_next_offset

    @property
    def eos_flushed(self) -> bool:
        return self._eos_flushed

    def reset_for_new_epoch(self, new_stream_ref: StreamRef) -> int:
        """Atomically reset synchronizer for a newer format_epoch; returns discarded remainder count."""
        if new_stream_ref.session_id != self._stream_ref.session_id or new_stream_ref.stream_id != self._stream_ref.stream_id:
            raise ValueError("Cannot change session_id or stream_id during epoch reset")
        if new_stream_ref.direction != StreamDirection.INPUT:
            raise ValueError("New stream_ref must have INPUT direction")
        if new_stream_ref.format_epoch <= self._stream_ref.format_epoch:
            raise ValueError("new format_epoch must strictly advance")
        discarded = int(self._remainder.shape[0])
        if discarded > 0:
            self._accounting.record_remainder_discarded_on_gap_or_abort(discarded)
        self._stream_ref = new_stream_ref
        self._remainder = np.zeros(0, dtype=np.float32)
        self._remainder_start_sample = 0
        self._expected_next_offset = None
        self._last_sequence = None
        self._eos_flushed = False
        return discarded

    def close(self) -> int:
        self._closed = True
        discarded = int(self._remainder.shape[0])
        if discarded > 0:
            self._accounting.record_remainder_discarded_on_gap_or_abort(discarded)
        self._remainder = np.zeros(0, dtype=np.float32)
        return discarded

    def admit_frame(self, frame: Any) -> FrameAdmissionResult:
        """Validate and synchronize an incoming AudioFrame into 512-sample VADWindows."""
        if self._closed or self._eos_flushed:
            return FrameAdmissionResult(False, RejectionReason.CLOSED, (), error_detail="stream_closed_or_eos")

        if not isinstance(frame, AudioFrame):
            self._accounting.record_rejected(RejectionReason.NONFINITE_OR_LENGTH, 0)
            return FrameAdmissionResult(False, RejectionReason.NONFINITE_OR_LENGTH, (), error_detail="not_audio_frame")

        try:
            ContractVersion.parse(frame.schema_version)
        except ValueError as exc:
            self._accounting.record_rejected(RejectionReason.SCHEMA_VERSION, frame.sample_count)
            return FrameAdmissionResult(False, RejectionReason.SCHEMA_VERSION, (), error_detail=str(exc))

        if (
            frame.stream_ref.session_id != self._stream_ref.session_id
            or frame.stream_ref.stream_id != self._stream_ref.stream_id
            or frame.stream_ref.direction != StreamDirection.INPUT
        ):
            self._accounting.record_rejected(RejectionReason.WRONG_STREAM, frame.sample_count)
            return FrameAdmissionResult(False, RejectionReason.WRONG_STREAM, (), error_detail="stream_ref_mismatch")

        if frame.stream_ref.format_epoch < self._stream_ref.format_epoch:
            self._accounting.record_rejected(RejectionReason.STALE_EPOCH, frame.sample_count)
            return FrameAdmissionResult(False, RejectionReason.STALE_EPOCH, (), error_detail="stale_format_epoch")

        if frame.stream_ref.format_epoch > self._stream_ref.format_epoch:
            self.reset_for_new_epoch(frame.stream_ref)

        if (
            frame.format.sample_rate_hz != SUPPORTED_SAMPLE_RATE_HZ
            or frame.format.channels != 1
            or frame.format.encoding not in (AudioEncoding.PCM_S16LE, AudioEncoding.FLOAT32_LE)
        ):
            self._accounting.record_rejected(RejectionReason.WRONG_FORMAT, frame.sample_count)
            return FrameAdmissionResult(False, RejectionReason.WRONG_FORMAT, (), error_detail="unsupported_format")

        real_count = frame.sample_count if frame.valid_sample_count is None else frame.valid_sample_count
        if real_count <= 0 or len(frame.payload) == 0:
            self._accounting.record_rejected(RejectionReason.EMPTY_FRAME, frame.sample_count)
            return FrameAdmissionResult(False, RejectionReason.EMPTY_FRAME, (), error_detail="empty_valid_samples")

        if self._last_sequence is not None and frame.sequence <= self._last_sequence:
            self._accounting.record_rejected(RejectionReason.DUPLICATE, real_count)
            return FrameAdmissionResult(False, RejectionReason.DUPLICATE, (), error_detail="duplicate_or_reordered_sequence")

        if self._expected_next_offset is not None and frame.sample_offset < self._expected_next_offset:
            self._accounting.record_rejected(RejectionReason.OVERLAP, real_count)
            return FrameAdmissionResult(False, RejectionReason.OVERLAP, (), error_detail="overlapping_sample_offset")

        gap_samples = 0
        if self._expected_next_offset is not None and (
            frame.sample_offset > self._expected_next_offset or "DISCONTINUITY_GAP" in frame.flags
        ):
            gap_samples = max(0, frame.sample_offset - self._expected_next_offset)
            self._accounting.record_gap_excluded(gap_samples)
            if len(self._remainder) > 0:
                self._accounting.record_remainder_discarded_on_gap_or_abort(int(len(self._remainder)))
                self._remainder = np.zeros(0, dtype=np.float32)
            self._remainder_start_sample = frame.sample_offset

        pending_after = int(len(self._remainder)) + real_count
        if pending_after > self._max_pending_input_samples or (pending_after * 4) > self._max_pending_bytes:
            self._accounting.record_rejected(RejectionReason.BACKPRESSURE, real_count)
            return FrameAdmissionResult(False, RejectionReason.BACKPRESSURE, (), error_detail="synchronizer_pending_cap")

        try:
            decoded = decode_audio_frame_to_f32(frame)
        except ValueError as exc:
            self._accounting.record_rejected(RejectionReason.NONFINITE_OR_LENGTH, real_count)
            return FrameAdmissionResult(False, RejectionReason.NONFINITE_OR_LENGTH, (), error_detail=str(exc))

        if self._expected_next_offset is None:
            self._remainder_start_sample = frame.sample_offset
        elif len(self._remainder) == 0 and gap_samples == 0:
            self._remainder_start_sample = frame.sample_offset

        combined = decoded if len(self._remainder) == 0 else np.concatenate((self._remainder, decoded))
        self._last_sequence = frame.sequence
        self._expected_next_offset = frame.sample_offset + real_count
        self._accounting.record_accepted(real_count)

        windows: list[VADWindow] = []
        cursor = 0
        total_len = int(combined.shape[0])
        while total_len - cursor >= VAD_WINDOW_SAMPLES:
            chunk = combined[cursor : cursor + VAD_WINDOW_SAMPLES].copy()
            chunk.setflags(write=False)
            start_sample = self._remainder_start_sample + cursor
            win = VADWindow(
                stream_ref=self._stream_ref,
                window_index=self._next_window_index,
                start_sample=start_sample,
                end_sample_exclusive=start_sample + VAD_WINDOW_SAMPLES,
                valid_samples=VAD_WINDOW_SAMPLES,
                samples_f32=chunk,
                model_input_f32=chunk,
                padded_for_inference=False,
                config_revision=self._config_revision,
            )
            windows.append(win)
            self._next_window_index += 1
            self._accounting.record_window_processed(VAD_WINDOW_SAMPLES, model_padding_samples=0)
            cursor += VAD_WINDOW_SAMPLES

        rem = combined[cursor:].copy()
        rem.setflags(write=False)
        self._remainder = rem
        self._remainder_start_sample += cursor
        self._accounting.set_buffered_remainder(int(rem.shape[0]))

        return FrameAdmissionResult(
            accepted=True,
            rejection_reason=None,
            windows=tuple(windows),
            discontinuity_gap_samples=gap_samples,
            accepted_real_samples=real_count,
        )

    def flush_eos(self) -> tuple[VADWindow | None, int]:
        """
        Handle explicit graceful EOS once.
        Returns (optional terminal padded VADWindow, unclassified_tail_samples).
        """
        if self._eos_flushed or self._closed:
            return None, 0
        self._eos_flushed = True
        rem_len = int(self._remainder.shape[0])
        if rem_len == 0:
            return None, 0

        rem = self._remainder
        start_sample = self._remainder_start_sample
        self._remainder = np.zeros(0, dtype=np.float32)
        self._accounting.set_buffered_remainder(0)

        if not self._allow_eos_model_padding:
            self._accounting.record_unclassified_tail(rem_len)
            return None, rem_len

        pad_len = VAD_WINDOW_SAMPLES - rem_len
        model_in = np.zeros(VAD_WINDOW_SAMPLES, dtype=np.float32)
        model_in[:rem_len] = rem
        model_in.setflags(write=False)
        real_slice = rem.copy()
        real_slice.setflags(write=False)

        win = VADWindow(
            stream_ref=self._stream_ref,
            window_index=self._next_window_index,
            start_sample=start_sample,
            end_sample_exclusive=start_sample + rem_len,
            valid_samples=rem_len,
            samples_f32=real_slice,
            model_input_f32=model_in,
            padded_for_inference=True,
            config_revision=self._config_revision,
        )
        self._next_window_index += 1
        self._accounting.record_window_processed(rem_len, model_padding_samples=pad_len)
        return win, 0
