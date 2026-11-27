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

import hashlib
import math
import struct
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from backend.core.contracts.audio import AudioEncoding, AudioFormat, AudioFrame
from backend.core.contracts.common import StreamDirection, StreamRef, TurnRef
from backend.core.contracts.speech import SpeechEvent, Utterance
from backend.core.contracts.validation import require_strict_int
from backend.speech_recognition.errors import ASRInputError

REQUIRED_SAMPLE_RATE_HZ = 16_000
REQUIRED_CHANNELS = 1
DEFAULT_MAX_DURATION_SEC = 20
DEFAULT_MAX_AUDIO_SAMPLES = REQUIRED_SAMPLE_RATE_HZ * DEFAULT_MAX_DURATION_SEC
DEFAULT_MAX_PCM_BYTES = DEFAULT_MAX_AUDIO_SAMPLES * 4  # float32 ceiling


@dataclass(slots=True)
class MaterializedAudio:
    """
    Single-copy immutable float32 mono 16 kHz audio handle owned for native inference.

    Caller buffer mutations after creation cannot alter `samples_f32` because
    the backing buffer is copied once and marked read-only (`writeable=False`).
    """

    sample_rate_hz: int
    channels: int
    source_encoding: AudioEncoding
    sample_count: int
    start_sample: int
    end_sample_exclusive: int
    pre_roll_samples: int
    post_roll_samples: int
    payload_sha256: str
    _array: np.ndarray = field(repr=False)
    _released: bool = False
    _borrowed_by_native: bool = False

    @property
    def is_released(self) -> bool:
        return self._released

    @property
    def borrowed_by_native(self) -> bool:
        return self._borrowed_by_native

    @property
    def duration_sec(self) -> float:
        return self.sample_count / float(self.sample_rate_hz)

    def acquire_native_borrow(self) -> None:
        if self._released:
            raise RuntimeError("Cannot borrow already-released MaterializedAudio")
        self._borrowed_by_native = True

    def release_native_borrow(self) -> None:
        self._borrowed_by_native = False

    def samples_view(self) -> np.ndarray:
        """Return a read-only float32 numpy view without exposing writable memory."""
        if self._released:
            raise RuntimeError("MaterializedAudio has been released")
        return self._array

    def rms_energy(self) -> float:
        if self._released:
            raise RuntimeError("MaterializedAudio has been released")
        if self.sample_count == 0:
            return 0.0
        arr = self._array
        return float(np.sqrt(np.mean(np.square(arr, dtype=np.float64))))

    def release(self) -> bool:
        """Release reference once safe; refuses release while native work still borrows it."""
        if self._released:
            return False
        if self._borrowed_by_native:
            return False
        self._released = True
        self._array = np.empty(0, dtype=np.float32)
        self._array.setflags(write=False)
        return True


@dataclass(frozen=True, slots=True)
class ValidatedUtteranceInput:
    """Validated immutable F1-A utterance paired with materialized audio."""

    utterance: Utterance
    stream_ref: StreamRef
    turn_ref: TurnRef
    audio_format: AudioFormat
    audio: MaterializedAudio
    payload_digest: str
    empty_audio: bool


def _pcm16le_bytes_to_float32(raw_bytes: bytes) -> np.ndarray:
    if len(raw_bytes) % 2 != 0:
        raise ASRInputError("ASR_ODD_PCM_BYTES", "PCM_S16LE byte length must be even", field_name="payload")
    if not raw_bytes:
        arr = np.empty(0, dtype=np.float32)
        arr.setflags(write=False)
        return arr
    int16_view = np.frombuffer(raw_bytes, dtype="<i2")
    # Exact scaling: -32768 -> -1.0, 0 -> 0.0, 32767 -> 32767/32768 (< 1.0)
    f32 = (int16_view.astype(np.float32) / np.float32(32768.0)).copy()
    f32.setflags(write=False)
    return f32


def _float32le_bytes_to_float32(raw_bytes: bytes) -> np.ndarray:
    if len(raw_bytes) % 4 != 0:
        raise ASRInputError("ASR_INVALID_FLOAT32_BYTES", "FLOAT32_LE byte length must be divisible by 4", field_name="payload")
    if not raw_bytes:
        arr = np.empty(0, dtype=np.float32)
        arr.setflags(write=False)
        return arr
    count = len(raw_bytes) // 4
    # Validate finiteness explicitly before creating numpy view
    unpacked = struct.unpack(f"<{count}f", raw_bytes)
    if not all(math.isfinite(v) for v in unpacked):
        raise ASRInputError("ASR_NONFINITE_AUDIO", "FLOAT32_LE audio contains NaN or Inf", field_name="payload")
    f32 = np.frombuffer(raw_bytes, dtype="<f4").copy()
    f32.setflags(write=False)
    return f32


def _validate_format(audio_format: AudioFormat) -> None:
    if not isinstance(audio_format, AudioFormat):
        raise ASRInputError("ASR_INVALID_FORMAT", "audio_format must be M01 AudioFormat", field_name="audio_format")
    if audio_format.sample_rate_hz != REQUIRED_SAMPLE_RATE_HZ:
        raise ASRInputError(
            "ASR_UNSUPPORTED_SAMPLE_RATE",
            f"F2-A requires 16000 Hz mono input (no F2 resampler); got {audio_format.sample_rate_hz}",
            field_name="sample_rate_hz",
        )
    if audio_format.channels != REQUIRED_CHANNELS:
        raise ASRInputError(
            "ASR_UNSUPPORTED_CHANNELS",
            f"F2-A requires mono (1 channel) input (no F2 downmix); got {audio_format.channels}",
            field_name="channels",
        )
    if audio_format.encoding not in {AudioEncoding.PCM_S16LE, AudioEncoding.FLOAT32_LE}:
        raise ASRInputError(
            "ASR_UNSUPPORTED_ENCODING",
            f"Unsupported audio encoding: {audio_format.encoding}",
            field_name="encoding",
        )


def validate_and_materialize_utterance(
    utterance: Utterance | SpeechEvent,
    audio_format: AudioFormat,
    *,
    frames: Sequence[AudioFrame] | None = None,
    max_samples: int = DEFAULT_MAX_AUDIO_SAMPLES,
    max_bytes: int = DEFAULT_MAX_PCM_BYTES,
    allow_discontinuity: bool = False,
) -> ValidatedUtteranceInput:
    """
    Validate an M01 finalized Utterance and materialize a single immutable float32 buffer.

    Rejects non-final utterances, SpeechEvent candidates, wrong sample rate/channels,
    odd byte counts, frame/interval mismatches, NaN/Inf, unapproved discontinuities,
    and oversized buffers before any GPU admission occurs.
    """
    if isinstance(utterance, SpeechEvent):
        raise ASRInputError("ASR_NONFINAL_SPEECH_EVENT", "SpeechEvent is not a finalized Utterance", field_name="utterance")
    if not isinstance(utterance, Utterance):
        raise ASRInputError("ASR_INVALID_UTTERANCE_TYPE", "utterance must be M01 Utterance", field_name="utterance")

    require_strict_int(max_samples, "max_samples", minimum=1)
    require_strict_int(max_bytes, "max_bytes", minimum=1)

    if not utterance.finalized:
        raise ASRInputError("ASR_UTTERANCE_NOT_FINAL", "Only finalized=True utterances enter F2-A", field_name="finalized")
    if utterance.stream_ref.direction != StreamDirection.INPUT:
        raise ASRInputError("ASR_WRONG_STREAM_DIRECTION", "Utterance stream_ref must be INPUT", field_name="stream_ref")
    if utterance.turn_ref is None:
        raise ASRInputError("ASR_MISSING_TURN_REF", "Utterance requires an admitted M02 turn_ref", field_name="turn_ref")
    if utterance.turn_ref.session_id != utterance.stream_ref.session_id:
        raise ASRInputError("ASR_SESSION_MISMATCH", "turn_ref session_id mismatches stream_ref", field_name="turn_ref")
    if utterance.has_discontinuity and not allow_discontinuity:
        raise ASRInputError(
            "ASR_UNAPPROVED_DISCONTINUITY",
            "Utterance contains unapproved sample discontinuity; refusing silent stitching",
            field_name="has_discontinuity",
        )

    _validate_format(audio_format)

    expected_samples = utterance.end_sample_exclusive - utterance.start_sample
    if expected_samples < 0:
        raise ASRInputError("ASR_INVALID_SAMPLE_INTERVAL", "end_sample_exclusive < start_sample", field_name="end_sample_exclusive")
    if expected_samples > max_samples:
        raise ASRInputError(
            "ASR_DURATION_LIMIT_EXCEEDED",
            f"Utterance sample count {expected_samples} exceeds bound {max_samples}",
            field_name="end_sample_exclusive",
        )

    expected_bytes = expected_samples * audio_format.bytes_per_frame
    if expected_bytes > max_bytes:
        raise ASRInputError(
            "ASR_BYTE_LIMIT_EXCEEDED",
            f"Expected payload bytes {expected_bytes} exceeds bound {max_bytes}",
            field_name="payload",
        )

    raw_bytes: bytes
    if frames is not None:
        if len(frames) == 0 and expected_samples > 0:
            raise ASRInputError("ASR_FRAME_COUNT_MISMATCH", "Empty frames sequence for non-empty interval", field_name="frames")
        if utterance.frame_refs and len(frames) != len(utterance.frame_refs):
            raise ASRInputError(
                "ASR_FRAME_REF_COUNT_MISMATCH",
                f"Provided {len(frames)} frames != {len(utterance.frame_refs)} frame_refs",
                field_name="frame_refs",
            )
        cursor = utterance.start_sample
        chunks: list[bytes] = []
        total_raw_bytes = 0
        for idx, frame in enumerate(frames):
            if not isinstance(frame, AudioFrame):
                raise ASRInputError("ASR_INVALID_FRAME", f"Frame {idx} is not M01 AudioFrame", field_name="frames")
            if frame.stream_ref != utterance.stream_ref:
                raise ASRInputError("ASR_FRAME_STREAM_MISMATCH", "Frame stream_ref mismatches utterance", field_name="frames")
            if frame.format != audio_format:
                raise ASRInputError("ASR_FRAME_FORMAT_MISMATCH", "Frame AudioFormat mismatches utterance format", field_name="frames")
            if frame.sample_offset != cursor:
                raise ASRInputError(
                    "ASR_NONCONTIGUOUS_FRAME_OFFSET",
                    f"Frame sample_offset {frame.sample_offset} != expected {cursor}",
                    field_name="frames",
                )
            total_raw_bytes += len(frame.payload)
            if total_raw_bytes > max_bytes:
                raise ASRInputError("ASR_BYTE_LIMIT_EXCEEDED", "Accumulated frame bytes exceed bound", field_name="frames")
            chunks.append(frame.payload)
            cursor += frame.sample_count
        if cursor != utterance.end_sample_exclusive:
            raise ASRInputError(
                "ASR_FRAME_INTERVAL_MISMATCH",
                f"Accumulated frame end {cursor} != end_sample_exclusive {utterance.end_sample_exclusive}",
                field_name="frames",
            )
        raw_bytes = b"".join(chunks)
    elif utterance.payload is not None:
        raw_bytes = utterance.payload
        if len(raw_bytes) > max_bytes:
            raise ASRInputError("ASR_BYTE_LIMIT_EXCEEDED", "Utterance payload exceeds max_bytes", field_name="payload")
        if audio_format.encoding == AudioEncoding.PCM_S16LE and len(raw_bytes) % 2 != 0:
            raise ASRInputError("ASR_ODD_PCM_BYTES", "PCM_S16LE payload cannot have odd byte count", field_name="payload")
        if len(raw_bytes) != expected_bytes:
            raise ASRInputError(
                "ASR_PAYLOAD_LENGTH_MISMATCH",
                f"Payload bytes {len(raw_bytes)} != expected {expected_bytes} for interval [{utterance.start_sample},{utterance.end_sample_exclusive})",
                field_name="payload",
            )
    else:
        raise ASRInputError("ASR_MISSING_PAYLOAD", "Utterance requires materialized payload or frames", field_name="payload")

    if audio_format.encoding == AudioEncoding.PCM_S16LE:
        samples_f32 = _pcm16le_bytes_to_float32(raw_bytes)
    else:
        samples_f32 = _float32le_bytes_to_float32(raw_bytes)

    digest = hashlib.sha256(raw_bytes).hexdigest()
    materialized = MaterializedAudio(
        sample_rate_hz=audio_format.sample_rate_hz,
        channels=audio_format.channels,
        source_encoding=audio_format.encoding,
        sample_count=expected_samples,
        start_sample=utterance.start_sample,
        end_sample_exclusive=utterance.end_sample_exclusive,
        pre_roll_samples=utterance.actual_pre_roll_samples,
        post_roll_samples=utterance.actual_post_roll_samples,
        payload_sha256=digest,
        _array=samples_f32,
    )
    return ValidatedUtteranceInput(
        utterance=utterance,
        stream_ref=utterance.stream_ref,
        turn_ref=utterance.turn_ref,
        audio_format=audio_format,
        audio=materialized,
        payload_digest=digest,
        empty_audio=(expected_samples == 0),
    )
