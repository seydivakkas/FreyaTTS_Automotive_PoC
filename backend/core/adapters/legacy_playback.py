"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from backend.core.contracts.audio import AudioEncoding, AudioFormat
from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, EventEnvelope, GenerationRef, StreamDirection, StreamRef
from backend.core.contracts.playback import ObservationScope, PlaybackEvent, PlaybackEventKind, PlaybackProfile, RenderedFrame


def rendered_frame_from_legacy_pcm(
    *,
    generation_ref: GenerationRef,
    stream_id: str,
    sequence: int,
    sample_offset: int,
    output_rate_hz: int,
    pcm16_bytes: bytes,
    terminal: bool = False,
) -> RenderedFrame:
    if output_rate_hz == 8000:
        profile = PlaybackProfile.AUDIOSOCKET_8K_PCM16
        expected_samples, expected_bytes = 160, 320
    elif output_rate_hz == 16000:
        profile = PlaybackProfile.WEB_16K_PCM16
        expected_samples, expected_bytes = 320, 640
    else:
        raise ValueError(f"Unsupported legacy output_rate_hz for RenderedFrame: {output_rate_hz}")

    if len(pcm16_bytes) % 2 != 0:
        raise ValueError("Odd PCM16 payload length")
    valid_samples = len(pcm16_bytes) // 2
    if not terminal and len(pcm16_bytes) != expected_bytes:
        raise ValueError(f"Non-terminal frame must be {expected_bytes} bytes")
    if len(pcm16_bytes) > expected_bytes:
        raise ValueError(f"Frame exceeds {expected_bytes} bytes")
    padded = pcm16_bytes.ljust(expected_bytes, b"\x00")
    return RenderedFrame(
        generation_ref=generation_ref,
        stream_ref=StreamRef(generation_ref.session_id, stream_id, StreamDirection.OUTPUT, 0),
        sequence=sequence,
        sample_offset=sample_offset,
        profile=profile,
        format=AudioFormat(output_rate_hz, 1, AudioEncoding.PCM_S16LE),
        frame_duration_ms=20.0,
        sample_count=expected_samples,
        valid_sample_count=valid_samples,
        payload=padded,
        terminal=terminal,
    )


def playback_event_from_legacy(
    *,
    generation_ref: GenerationRef,
    kind: PlaybackEventKind,
    sequence: int,
    monotonic_ns: int,
    observation_scope: ObservationScope = ObservationScope.SERVER,
    queue_depth: int | None = None,
    sample_progress: int | None = None,
) -> PlaybackEvent:
    env = EventEnvelope(
        schema_version=CONTRACT_SCHEMA_VERSION,
        event_type=f"playback.{kind.value.lower()}",
        session_id=generation_ref.session_id,
        trace_id=None,
        turn_id=generation_ref.turn_id,
        generation_id=generation_ref.generation_id,
        sequence=sequence,
        monotonic_ns=monotonic_ns,
        clock_domain="legacy.local",
        producer="backend.session.playback",
    )
    return PlaybackEvent(
        envelope=env,
        kind=kind,
        generation_ref=generation_ref,
        observation_scope=observation_scope,
        queue_depth=queue_depth,
        sample_progress=sample_progress,
    )
