"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import numpy as np

from backend.core.contracts.audio import AudioEncoding, AudioFormat, AudioFrame
from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, StreamDirection, StreamRef
from backend.core.contracts.validation import ConversionResult


def audio_frame_from_legacy_pcm(
    *,
    session_id: str,
    stream_id: str,
    sample_rate_hz: int,
    data: bytes | bytearray | np.ndarray,
    sequence: int = 0,
    sample_offset: int = 0,
    direction: StreamDirection = StreamDirection.INPUT,
    format_epoch: int = 0,
    captured_monotonic_ns: int | None = None,
    clock_domain: str | None = None,
    source_ref: str = "legacy_audio",
) -> ConversionResult[AudioFrame]:
    missing: list[str] = []
    warnings: list[str] = []
    if captured_monotonic_ns is None:
        missing.append("captured_monotonic_ns")
    if isinstance(data, np.ndarray):
        arr = np.ascontiguousarray(data, dtype=np.float32)
        if arr.ndim != 1:
            return ConversionResult(None, tuple(missing), tuple(warnings), error="Only mono 1D arrays supported", source_ref=source_ref)
        if not np.isfinite(arr).all():
            return ConversionResult(None, tuple(missing), tuple(warnings), error="Non-finite float samples", source_ref=source_ref)
        encoding = AudioEncoding.FLOAT32_LE
        payload = arr.astype("<f4").tobytes()
        sample_count = int(arr.shape[0])
    elif isinstance(data, (bytes, bytearray)):
        payload = bytes(data)
        if len(payload) % 2 != 0:
            return ConversionResult(None, tuple(missing), tuple(warnings), error="Odd PCM16 byte length", source_ref=source_ref)
        encoding = AudioEncoding.PCM_S16LE
        sample_count = len(payload) // 2
    else:
        return ConversionResult(None, tuple(missing), tuple(warnings), error=f"Unsupported buffer type: {type(data).__name__}", source_ref=source_ref)

    if sample_count == 0:
        return ConversionResult(None, tuple(missing), tuple(warnings), error="Empty audio data cannot form AudioFrame", source_ref=source_ref)

    try:
        frame = AudioFrame(
            schema_version=CONTRACT_SCHEMA_VERSION,
            stream_ref=StreamRef(session_id=session_id, stream_id=stream_id, direction=direction, format_epoch=format_epoch),
            sequence=sequence,
            format=AudioFormat(sample_rate_hz=sample_rate_hz, channels=1, encoding=encoding),
            sample_count=sample_count,
            sample_offset=sample_offset,
            payload=payload,
            captured_monotonic_ns=captured_monotonic_ns,
            clock_domain=clock_domain,
        )
        return ConversionResult(frame, tuple(missing), tuple(warnings), lossy=bool(missing), source_ref=source_ref)
    except Exception as exc:
        return ConversionResult(None, tuple(missing), tuple(warnings), error=str(exc), source_ref=source_ref)


def audio_frame_to_legacy_pcm(frame: AudioFrame) -> bytes:
    if frame.format.encoding == AudioEncoding.PCM_S16LE:
        return frame.payload
    arr = np.frombuffer(frame.payload, dtype="<f4")
    return (np.clip(arr, -1.0, 1.0) * 32767.0).round().astype("<i2").tobytes()
