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

from backend.audio_frontend.format_validator import (
    LEGACY_WEB_EXTENDED_PROFILE,
    PHONE_8K_PROFILE,
    WEB_16K_48K_PROFILE,
    InputOutcomeStatus,
    InputProfile,
    ValidationOutcome,
    bytes_per_sample,
    normalize_encoding,
    validate_raw_input,
)
from backend.audio_frontend.pcm_conversion import copy_ingress_bytes
from backend.core.contracts.audio import AudioEncoding, AudioFrame
from backend.core.contracts.common import (
    CONTRACT_SCHEMA_VERSION,
    StreamDirection,
    StreamRef,
)


@dataclass(frozen=True, slots=True)
class AdaptedIngressChunk:
    """Validated, ownership-safe M01 AudioFrame produced by an ingress adapter."""

    ok: bool
    status: InputOutcomeStatus
    reason: str
    frame: AudioFrame | None = None
    validation: ValidationOutcome | None = None


def adapt_ingress_to_frame(
    *,
    session_id: str,
    stream_id: str,
    data: Any,
    sample_rate_hz: Any,
    channels: Any = 1,
    encoding: AudioEncoding | str = AudioEncoding.PCM_S16LE,
    sequence: int = 0,
    sample_offset: int = 0,
    format_epoch: int = 0,
    valid_sample_count: int | None = None,
    endian: str = "little",
    captured_monotonic_ns: int | None = None,
    clock_domain: str | None = None,
    profile: InputProfile | None = None,
    flags: frozenset[str] = frozenset(),
) -> AdaptedIngressChunk:
    """
    Validate raw web/phone/fixture audio and copy mutable buffers into an owned M01 AudioFrame.

    Never infers sample rate from payload byte length.
    """
    active_profile = profile or LEGACY_WEB_EXTENDED_PROFILE
    enc = normalize_encoding(encoding)
    if enc is None:
        val = validate_raw_input(
            payload=data,
            sample_rate_hz=sample_rate_hz,
            channels=channels,
            encoding=encoding,
            sample_count=0,
            profile=active_profile,
            endian=endian,
        )
        return AdaptedIngressChunk(False, val.status, val.reason, validation=val)

    bps = bytes_per_sample(enc)
    if isinstance(data, np.ndarray):
        if data.ndim != 1:
            return AdaptedIngressChunk(False, InputOutcomeStatus.INVALID, "Only 1D mono numpy arrays supported")
        sample_count = int(data.shape[0])
        raw_bytes_or_buf: Any = data.tobytes() if sample_count <= active_profile.max_samples_per_frame else b""
    elif isinstance(data, (bytes, bytearray, memoryview)):
        if type(channels) is not int or channels < 1:
            sample_count = 0
        else:
            stride = channels * bps
            if len(data) % stride != 0:
                val = validate_raw_input(
                    payload=data,
                    sample_rate_hz=sample_rate_hz,
                    channels=channels,
                    encoding=enc,
                    sample_count=max(1, len(data) // stride),
                    profile=active_profile,
                    valid_sample_count=valid_sample_count,
                    endian=endian,
                    captured_monotonic_ns=captured_monotonic_ns,
                    clock_domain=clock_domain,
                )
                return AdaptedIngressChunk(False, val.status, val.reason, validation=val)
            sample_count = len(data) // stride
        raw_bytes_or_buf = data
    else:
        return AdaptedIngressChunk(False, InputOutcomeStatus.INVALID, f"Unsupported payload type: {type(data).__name__}")

    stream_ref = StreamRef(
        session_id=session_id,
        stream_id=stream_id,
        direction=StreamDirection.INPUT,
        format_epoch=format_epoch,
    )
    validation = validate_raw_input(
        payload=raw_bytes_or_buf,
        sample_rate_hz=sample_rate_hz,
        channels=channels,
        encoding=enc,
        sample_count=sample_count,
        profile=active_profile,
        valid_sample_count=valid_sample_count,
        endian=endian,
        captured_monotonic_ns=captured_monotonic_ns,
        clock_domain=clock_domain,
        stream_ref=stream_ref,
    )
    if not validation.ok or validation.audio_format is None:
        return AdaptedIngressChunk(False, validation.status, validation.reason, validation=validation)

    owned_payload = copy_ingress_bytes(raw_bytes_or_buf)
    frame = AudioFrame(
        schema_version=CONTRACT_SCHEMA_VERSION,
        stream_ref=stream_ref,
        sequence=sequence,
        format=validation.audio_format,
        sample_count=sample_count,
        sample_offset=sample_offset,
        payload=owned_payload,
        captured_monotonic_ns=captured_monotonic_ns,
        clock_domain=clock_domain,
        valid_sample_count=valid_sample_count,
        flags=flags,
    )
    return AdaptedIngressChunk(True, InputOutcomeStatus.ACCEPTED, "ok", frame=frame, validation=validation)


def adapt_audiosocket_chunk(
    *,
    session_id: str,
    payload: bytes | bytearray | memoryview,
    sequence: int,
    sample_offset: int,
    stream_id: str = "audiosocket-in",
    format_epoch: int = 0,
    captured_monotonic_ns: int | None = None,
    clock_domain: str | None = None,
    profile: InputProfile = PHONE_8K_PROFILE,
) -> AdaptedIngressChunk:
    """Adapt validated AudioSocket 8 kHz mono PCM16 payload into M01 AudioFrame."""
    return adapt_ingress_to_frame(
        session_id=session_id,
        stream_id=stream_id,
        data=payload,
        sample_rate_hz=8000,
        channels=1,
        encoding=AudioEncoding.PCM_S16LE,
        sequence=sequence,
        sample_offset=sample_offset,
        format_epoch=format_epoch,
        captured_monotonic_ns=captured_monotonic_ns,
        clock_domain=clock_domain,
        profile=profile,
        flags=frozenset({"INGRESS:AUDIOSOCKET"}),
    )


def adapt_web_ws_chunk(
    *,
    session_id: str,
    data: bytes | bytearray | memoryview,
    sample_rate_hz: int,
    encoding: AudioEncoding | str = AudioEncoding.PCM_S16LE,
    channels: int = 1,
    sequence: int = 0,
    sample_offset: int = 0,
    stream_id: str = "web-mic-in",
    format_epoch: int = 0,
    valid_sample_count: int | None = None,
    captured_monotonic_ns: int | None = None,
    clock_domain: str | None = None,
    profile: InputProfile = WEB_16K_48K_PROFILE,
) -> AdaptedIngressChunk:
    """Adapt validated WebSocket audio chunk into M01 AudioFrame."""
    return adapt_ingress_to_frame(
        session_id=session_id,
        stream_id=stream_id,
        data=data,
        sample_rate_hz=sample_rate_hz,
        channels=channels,
        encoding=encoding,
        sequence=sequence,
        sample_offset=sample_offset,
        format_epoch=format_epoch,
        valid_sample_count=valid_sample_count,
        captured_monotonic_ns=captured_monotonic_ns,
        clock_domain=clock_domain,
        profile=profile,
        flags=frozenset({"INGRESS:WEB_WS"}),
    )
