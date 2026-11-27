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
import struct
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from backend.core.contracts.audio import AudioEncoding, AudioFormat, AudioFrame
from backend.core.contracts.common import (
    ErrorCategory,
    ErrorInfo,
    Retryability,
    StreamRef,
)

MAX_SAFE_INT_SAMPLES = 192000 * 60
DEFAULT_MAX_BYTES_PER_FRAME = 192000
DEFAULT_MAX_SAMPLES_PER_FRAME = 96000


class InputOutcomeStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    BUFFERED = "BUFFERED"
    INVALID = "INVALID"
    UNSUPPORTED = "UNSUPPORTED"
    STALE = "STALE"
    BACKPRESSURE = "BACKPRESSURE"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class InputProfile:
    """Approved ingress validation and processing profile for an F0-A stream."""

    profile_id: str
    source_kind: str
    supported_rates_hz: frozenset[int] = frozenset({8000, 16000, 48000})
    supported_encodings: frozenset[AudioEncoding] = frozenset(
        {AudioEncoding.PCM_S16LE, AudioEncoding.FLOAT32_LE}
    )
    supported_channels: frozenset[int] = frozenset({1})
    allow_stereo_downmix: bool = False
    overrange_policy: Literal["reject", "saturate"] = "saturate"
    max_bytes_per_frame: int = DEFAULT_MAX_BYTES_PER_FRAME
    max_samples_per_frame: int = DEFAULT_MAX_SAMPLES_PER_FRAME
    output_sample_rate_hz: int = 16000
    output_encoding: AudioEncoding = AudioEncoding.FLOAT32_LE
    dsp_enabled: bool = True
    bypass: bool = False
    already_processed: bool = False
    hpf_enabled: bool = True
    spectral_enabled: bool = True
    agc_gate_enabled: bool = True
    resampler_backend: str = "soxr"
    resampler_quality: str = "HQ"
    gap_policy: Literal["record_discontinuity", "reject"] = "record_discontinuity"
    config_revision: str = ""

    def __post_init__(self) -> None:
        if not self.profile_id:
            raise ValueError("profile_id required")
        if self.output_sample_rate_hz != 16000:
            raise ValueError("F0-A output_sample_rate_hz must be 16000")
        if self.max_bytes_per_frame < 1 or self.max_samples_per_frame < 1:
            raise ValueError("Frame caps must be positive")
        if self.allow_stereo_downmix and 2 not in self.supported_channels:
            raise ValueError("allow_stereo_downmix requires channel 2 in supported_channels")


PHONE_8K_PROFILE = InputProfile(
    profile_id="phone_8k_pcm16",
    source_kind="phone",
    supported_rates_hz=frozenset({8000}),
    supported_encodings=frozenset({AudioEncoding.PCM_S16LE}),
    supported_channels=frozenset({1}),
)

WEB_16K_48K_PROFILE = InputProfile(
    profile_id="web_16k_48k",
    source_kind="web",
    supported_rates_hz=frozenset({16000, 48000}),
    supported_encodings=frozenset({AudioEncoding.PCM_S16LE, AudioEncoding.FLOAT32_LE}),
    supported_channels=frozenset({1}),
)

LEGACY_WEB_EXTENDED_PROFILE = InputProfile(
    profile_id="legacy_web_extended",
    source_kind="web",
    supported_rates_hz=frozenset({8000, 16000, 24000, 44100, 48000}),
    supported_encodings=frozenset({AudioEncoding.PCM_S16LE, AudioEncoding.FLOAT32_LE}),
    supported_channels=frozenset({1}),
)


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    ok: bool
    status: InputOutcomeStatus
    reason: str
    error_info: ErrorInfo | None = None
    expected_bytes: int | None = None
    audio_format: AudioFormat | None = None


def _reject(
    status: InputOutcomeStatus,
    code: str,
    reason: str,
    *,
    field_name: str | None = None,
    category: ErrorCategory = ErrorCategory.VALIDATION,
) -> ValidationOutcome:
    return ValidationOutcome(
        ok=False,
        status=status,
        reason=reason,
        error_info=ErrorInfo(
            code=code,
            category=category,
            retryable=Retryability.NO,
            safe_message=reason,
            field_name=field_name,
        ),
    )


def bytes_per_sample(encoding: AudioEncoding) -> int:
    if encoding == AudioEncoding.PCM_S16LE:
        return 2
    if encoding == AudioEncoding.FLOAT32_LE:
        return 4
    raise ValueError(f"Unsupported encoding: {encoding}")


def normalize_encoding(raw: AudioEncoding | str) -> AudioEncoding | None:
    if isinstance(raw, AudioEncoding):
        return raw
    if not isinstance(raw, str):
        return None
    norm = raw.strip().upper()
    if norm in ("PCM_S16LE", "PCM16", "SLIN16"):
        return AudioEncoding.PCM_S16LE
    if norm in ("FLOAT32_LE", "FLOAT32", "F32LE"):
        return AudioEncoding.FLOAT32_LE
    return None


def validate_raw_input(
    *,
    payload: Any,
    sample_rate_hz: Any,
    channels: Any,
    encoding: AudioEncoding | str,
    sample_count: Any,
    profile: InputProfile,
    valid_sample_count: Any = None,
    endian: str = "little",
    captured_monotonic_ns: Any = None,
    clock_domain: str | None = None,
    stream_ref: StreamRef | None = None,
) -> ValidationOutcome:
    """Validate raw input metadata and byte bounds BEFORE allocating or decoding buffers."""
    if stream_ref is not None and not isinstance(stream_ref, StreamRef):
        return _reject(InputOutcomeStatus.INVALID, "F0_INVALID_STREAM_REF", "stream_ref must be StreamRef", field_name="stream_ref")

    if not isinstance(endian, str) or endian.strip().lower() != "little":
        return _reject(
            InputOutcomeStatus.UNSUPPORTED,
            "F0_UNSUPPORTED_ENDIAN",
            "Only little-endian audio payloads are supported",
            field_name="endian",
        )

    enc = normalize_encoding(encoding)
    if enc is None or enc not in profile.supported_encodings:
        return _reject(
            InputOutcomeStatus.UNSUPPORTED,
            "F0_UNSUPPORTED_ENCODING",
            "Unsupported or unapproved audio encoding",
            field_name="encoding",
        )

    if type(sample_rate_hz) is not int or sample_rate_hz <= 0:
        return _reject(
            InputOutcomeStatus.INVALID,
            "F0_INVALID_SAMPLE_RATE",
            "sample_rate_hz must be positive int",
            field_name="sample_rate_hz",
        )
    if sample_rate_hz not in profile.supported_rates_hz:
        return _reject(
            InputOutcomeStatus.UNSUPPORTED,
            "F0_UNSUPPORTED_SAMPLE_RATE",
            f"Unsupported sample_rate_hz: {sample_rate_hz}",
            field_name="sample_rate_hz",
        )

    if type(channels) is not int or channels < 1:
        return _reject(
            InputOutcomeStatus.INVALID,
            "F0_INVALID_CHANNELS",
            "channels must be positive int",
            field_name="channels",
        )
    if channels not in profile.supported_channels:
        return _reject(
            InputOutcomeStatus.UNSUPPORTED,
            "F0_UNSUPPORTED_CHANNELS",
            f"Unsupported channel count: {channels}",
            field_name="channels",
        )
    if channels == 2 and not profile.allow_stereo_downmix:
        return _reject(
            InputOutcomeStatus.UNSUPPORTED,
            "F0_STEREO_NOT_APPROVED",
            "Stereo input requires explicit approved downmix profile",
            field_name="channels",
        )

    if type(sample_count) is not int:
        return _reject(
            InputOutcomeStatus.INVALID,
            "F0_INVALID_SAMPLE_COUNT_TYPE",
            "sample_count must be strict int (not bool or float)",
            field_name="sample_count",
        )
    if sample_count <= 0:
        return _reject(
            InputOutcomeStatus.INVALID,
            "F0_NONPOSITIVE_SAMPLE_COUNT",
            "sample_count must be positive; use typed EOS control event instead of zero-length audio",
            field_name="sample_count",
        )
    if sample_count > profile.max_samples_per_frame or sample_count > MAX_SAFE_INT_SAMPLES:
        return _reject(
            InputOutcomeStatus.INVALID,
            "F0_SAMPLE_COUNT_EXCEEDS_CAP",
            "sample_count exceeds configured safety cap",
            field_name="sample_count",
        )

    bps = bytes_per_sample(enc)
    # Overflow-safe cap check before examining or copying payload
    max_allowed_samples_by_bytes = profile.max_bytes_per_frame // (channels * bps)
    if sample_count > max_allowed_samples_by_bytes:
        return _reject(
            InputOutcomeStatus.INVALID,
            "F0_PAYLOAD_EXCEEDS_BYTE_CAP",
            "Expected payload bytes exceed configured byte cap",
            field_name="sample_count",
        )
    expected_bytes = sample_count * channels * bps

    if not isinstance(payload, (bytes, bytearray, memoryview)):
        return _reject(
            InputOutcomeStatus.INVALID,
            "F0_INVALID_PAYLOAD_TYPE",
            "payload must be bytes-like object",
            field_name="payload",
        )

    actual_bytes = len(payload)
    if actual_bytes == 0:
        return _reject(
            InputOutcomeStatus.INVALID,
            "F0_EMPTY_PAYLOAD",
            "Empty audio payload rejected; use explicit EOS event",
            field_name="payload",
        )
    if enc == AudioEncoding.PCM_S16LE and actual_bytes % 2 != 0:
        return _reject(
            InputOutcomeStatus.INVALID,
            "F0_ODD_PCM16_BYTES",
            "PCM_S16LE payload cannot have odd byte length",
            field_name="payload",
        )
    if actual_bytes != expected_bytes:
        return _reject(
            InputOutcomeStatus.INVALID,
            "F0_PAYLOAD_LENGTH_MISMATCH",
            f"Payload byte length {actual_bytes} does not match expected {expected_bytes}",
            field_name="payload",
        )

    if valid_sample_count is not None:
        if type(valid_sample_count) is not int or valid_sample_count < 0 or valid_sample_count > sample_count:
            return _reject(
                InputOutcomeStatus.INVALID,
                "F0_INVALID_VALID_SAMPLE_COUNT",
                "valid_sample_count must be int in [0, sample_count]",
                field_name="valid_sample_count",
            )

    if captured_monotonic_ns is not None:
        if type(captured_monotonic_ns) is not int or captured_monotonic_ns < 0:
            return _reject(
                InputOutcomeStatus.INVALID,
                "F0_INVALID_TIMESTAMP",
                "captured_monotonic_ns must be non-negative int",
                field_name="captured_monotonic_ns",
            )
        if not isinstance(clock_domain, str) or not clock_domain.strip():
            return _reject(
                InputOutcomeStatus.INVALID,
                "F0_MISSING_CLOCK_DOMAIN",
                "clock_domain is required when captured_monotonic_ns is provided",
                field_name="clock_domain",
            )

    if enc == AudioEncoding.FLOAT32_LE:
        float_count = actual_bytes // 4
        values = struct.unpack(f"<{float_count}f", payload)
        for v in values:
            if not math.isfinite(v):
                return _reject(
                    InputOutcomeStatus.INVALID,
                    "F0_NONFINITE_FLOAT32",
                    "FLOAT32_LE payload contains NaN or Inf",
                    field_name="payload",
                )
            if profile.overrange_policy == "reject" and abs(v) > 1.0:
                return _reject(
                    InputOutcomeStatus.INVALID,
                    "F0_FLOAT32_OVERRANGE",
                    "FLOAT32_LE sample exceeds [-1.0, 1.0] under reject policy",
                    field_name="payload",
                )

    try:
        fmt = AudioFormat(sample_rate_hz=sample_rate_hz, channels=channels, encoding=enc)
    except Exception as exc:
        return _reject(InputOutcomeStatus.UNSUPPORTED, "F0_INVALID_FORMAT", str(exc), field_name="format")

    return ValidationOutcome(
        ok=True,
        status=InputOutcomeStatus.ACCEPTED,
        reason="validated",
        expected_bytes=expected_bytes,
        audio_format=fmt,
    )


def validate_audio_frame(frame: AudioFrame, profile: InputProfile) -> ValidationOutcome:
    """Validate an M01 AudioFrame against an approved F0-A InputProfile."""
    if not isinstance(frame, AudioFrame):
        return _reject(InputOutcomeStatus.INVALID, "F0_NOT_AUDIO_FRAME", "Input must be M01 AudioFrame")
    return validate_raw_input(
        payload=frame.payload,
        sample_rate_hz=frame.format.sample_rate_hz,
        channels=frame.format.channels,
        encoding=frame.format.encoding,
        sample_count=frame.sample_count,
        profile=profile,
        valid_sample_count=frame.valid_sample_count,
        captured_monotonic_ns=frame.captured_monotonic_ns,
        clock_domain=frame.clock_domain,
        stream_ref=frame.stream_ref,
    )
