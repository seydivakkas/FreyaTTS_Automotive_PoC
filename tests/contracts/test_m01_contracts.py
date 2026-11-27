"""M01 Core Data Contracts test suite covering CT01-CT36."""
from __future__ import annotations

import json
import math
import subprocess
import sys
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from backend.core.adapters import (
    asr_result_from_legacy_text,
    asr_result_to_legacy_text,
    audio_chunk_from_legacy_waveform,
    audio_frame_from_legacy_pcm,
    audio_frame_to_legacy_pcm,
    dialogue_response_from_legacy,
    playback_event_from_legacy,
    rendered_frame_from_legacy_pcm,
    synthesis_plan_from_legacy,
    tool_receipt_from_legacy_outcome,
)
from backend.core.contracts import (
    CONTRACT_SCHEMA_VERSION,
    ASROutcome,
    ASRResult,
    ASRStatus,
    AudioChunk,
    AudioEncoding,
    AudioFormat,
    AudioFrame,
    CacheStatus,
    CancellationReference,
    CatalogStatus,
    ChunkPlan,
    ConfidenceEstimate,
    ConfirmationReference,
    ConfirmationStatus,
    ContractVersion,
    DialogueOutcome,
    DialogueResponse,
    EntityCandidate,
    ErrorCategory,
    ErrorInfo,
    EventEnvelope,
    GenerationRef,
    MetricSample,
    MetricStatus,
    ObservationScope,
    PlanValidationStatus,
    PlaybackEventKind,
    PlaybackProfile,
    ProviderMode,
    QualityStatus,
    RenderedFrame,
    Retryability,
    SessionIdentity,
    SpeechEvent,
    SpeechEventKind,
    StreamDirection,
    StreamRef,
    SynthesisPlan,
    ToolReceipt,
    ToolReceiptStatus,
    TurnRef,
    UnicodeSpan,
    Utterance,
    metadata_to_json,
    safe_telemetry_projection,
    validate_plan_chunk_consistency,
)


def _env(session_id: str = "test-session-a", turn_id: int | None = 1, generation_id: int | None = 1, seq: int = 0) -> EventEnvelope:
    return EventEnvelope(
        schema_version=CONTRACT_SCHEMA_VERSION,
        event_type="test.event",
        session_id=session_id,
        trace_id="trace-1",
        turn_id=turn_id,
        generation_id=generation_id,
        sequence=seq,
        monotonic_ns=1000,
        clock_domain="test.clock",
        producer="test.suite",
        utc_timestamp="2026-11-26T00:00:00Z",
    )


def test_ct01_safe_isolated_import():
    proc = subprocess.run(
        [sys.executable, "-c", "import sys, backend.core.contracts, backend.core.adapters; assert 'torch' not in sys.modules and 'faster_whisper' not in sys.modules"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr


def test_ct02_version_parse_and_reject():
    v = ContractVersion.parse("2.0")
    assert str(v) == "2.0"
    for bad in ("1.0", "3.0", "2", "2.0.1", "x.y", ""):
        with pytest.raises(ValueError):
            ContractVersion.parse(bad)


def test_ct03_ids_and_strict_integers():
    SessionIdentity("test-session-a", trace_id="trace-a")
    for bad_id in ("", " ", "../escape", "05321112233"):
        with pytest.raises(ValueError):
            SessionIdentity(bad_id)
    for bad_int in (-1, True, False, "1", 1.5, 2**63):
        with pytest.raises(ValueError):
            TurnRef("test-session-a", bad_int)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            GenerationRef("test-session-a", 0, bad_int)  # type: ignore[arg-type]


def test_ct04_optional_metric_and_nan_rejection():
    zero = MetricSample("latency", 0.0, "ms", "SERVER", MetricStatus.MEASURED)
    assert zero.value == 0.0
    unavail = MetricSample("mos", None, "score", "ENDPOINT", MetricStatus.UNAVAILABLE, reason="no_listener")
    assert unavail.value is None
    with pytest.raises(ValueError):
        MetricSample("bad", float("nan"), "ms", "SERVER", MetricStatus.MEASURED)
    with pytest.raises(ValueError):
        MetricSample("bad", float("inf"), "ms", "SERVER", MetricStatus.MEASURED)


def test_ct05_timestamp_and_clock_domain():
    e = _env()
    assert e.utc_timestamp == "2026-11-26T00:00:00Z"
    with pytest.raises(ValueError):
        EventEnvelope(
            schema_version="2.0",
            event_type="x",
            session_id="s-1",
            trace_id=None,
            turn_id=None,
            generation_id=None,
            sequence=0,
            monotonic_ns=1,
            clock_domain="c",
            producer="p",
            utc_timestamp="2026-11-26T00:00:00",
        )
    with pytest.raises(ValueError):
        AudioFrame(
            schema_version="2.0",
            stream_ref=StreamRef("s-1", "in", StreamDirection.INPUT, 0),
            sequence=0,
            format=AudioFormat(8000, 1, AudioEncoding.PCM_S16LE),
            sample_count=160,
            sample_offset=0,
            payload=b"\x00" * 320,
            captured_monotonic_ns=10,
            clock_domain="",
        )


def test_ct06_ct07_ct08_ct09_audio_formats():
    f8 = AudioFrame("2.0", StreamRef("s-1", "in", StreamDirection.INPUT), 0, AudioFormat(8000, 1, AudioEncoding.PCM_S16LE), 160, 0, b"\x00" * 320)
    assert len(f8.payload) == 320
    f16 = AudioFrame("2.0", StreamRef("s-1", "in", StreamDirection.INPUT), 1, AudioFormat(16000, 1, AudioEncoding.PCM_S16LE), 320, 0, b"\x00" * 640)
    assert len(f16.payload) == 640
    vad_block = AudioFrame("2.0", StreamRef("s-1", "in", StreamDirection.INPUT), 2, AudioFormat(16000, 1, AudioEncoding.PCM_S16LE), 512, 0, b"\x00" * 1024)
    assert vad_block.sample_count == 512
    f48 = AudioFrame("2.0", StreamRef("s-1", "out", StreamDirection.OUTPUT), 0, AudioFormat(48000, 1, AudioEncoding.FLOAT32_LE), 960, 0, np.zeros(960, dtype="<f4").tobytes())
    assert len(f48.payload) == 3840


def test_ct10_ct11_malformed_payload_and_ownership():
    fmt = AudioFormat(16000, 1, AudioEncoding.PCM_S16LE)
    sr = StreamRef("s-1", "in", StreamDirection.INPUT)
    with pytest.raises(ValueError):
        AudioFrame("2.0", sr, 0, fmt, 10, 0, b"\x00" * 19)
    with pytest.raises(ValueError):
        AudioFrame("2.0", sr, 0, fmt, 10, 0, b"\x00" * 20, valid_sample_count=11)
    arr = np.array([0.1, -0.2, 0.3], dtype=np.float32)
    res = audio_frame_from_legacy_pcm(session_id="s-1", stream_id="mic", sample_rate_hz=16000, data=arr)
    assert res.ok and res.value is not None
    arr[0] = 0.99
    assert np.frombuffer(res.value.payload, dtype="<f4")[0] == pytest.approx(0.1)
    assert "payload=" not in repr(res.value)


def test_ct12_ct13_utterance_and_speech_event():
    sr = StreamRef("s-1", "in", StreamDirection.INPUT, 1)
    utt = Utterance("utt-1", sr, TurnRef("s-1", 1), 0, 5120, True, "ACOUSTIC_SILENCE", frame_refs=("f0",))
    assert utt.end_sample_exclusive == 5120
    with pytest.raises(ValueError):
        Utterance("utt-2", sr, TurnRef("s-2", 1), 0, 100, True, "SILENCE", frame_refs=("f0",))
    with pytest.raises(ValueError):
        SpeechEvent(_env("s-1"), SpeechEventKind.COMMIT_INTERRUPT, sr, 0, "barge", target_generation=GenerationRef("s-2", 1, 1))


def test_ct14_ct15_ct16_ct17_ct18_asr_result():
    partial = ASRResult(_env(turn_id=None), "utt-1", 0, ASRStatus.PARTIAL, "Nisan kaş kay", ASROutcome.OK)
    assert not partial.is_write_eligible
    with pytest.raises(ValueError):
        ASRResult(_env(), "utt-1", 0, ASRStatus.FINAL, "", ASROutcome.OK)
    no_speech = ASRResult(_env(), "utt-1", 0, ASRStatus.FINAL, "", ASROutcome.NO_SPEECH, confidence=None)
    assert not no_speech.is_write_eligible and no_speech.confidence is None
    with pytest.raises(ValueError):
        ConfidenceEstimate(avg_logprob=0.5)
    with pytest.raises(ValueError):
        ConfidenceEstimate(calibrated_prob=0.9, calibration_version=None)
    raw = "Nisan kaş kay iki bin yirmi"
    ent = EntityCandidate("ent-1", "MODEL", "kaş kay", canonical_value="Qashqai", source_span=UnicodeSpan(6, 13, "RAW"))
    final_res = ASRResult(_env(), "utt-1", 1, ASRStatus.FINAL, raw, ASROutcome.OK, entities=(ent,))
    assert final_res.is_write_eligible
    assert raw[ent.source_span.start:ent.source_span.end_exclusive] == "kaş kay"
    assert ent.catalog_status == CatalogStatus.UNVERIFIED
    assert ent.confirmation_status == ConfirmationStatus.CANDIDATE


def test_ct19_ct20_tool_receipt_and_confirmation():
    for st in (ToolReceiptStatus.UNKNOWN, ToolReceiptStatus.FAILED, ToolReceiptStatus.PENDING, ToolReceiptStatus.BLOCKED):
        rec = ToolReceipt("op-1", "create_booking", st, ProviderMode.REAL)
        assert not rec.is_committed_real
    mock_commit = ToolReceipt("op-2", "create_booking", ToolReceiptStatus.COMMITTED, ProviderMode.MOCK, verified_result=False)
    assert not mock_commit.is_committed_real
    with pytest.raises(ValueError):
        ToolReceipt("op-3", "create_booking", ToolReceiptStatus.COMMITTED, ProviderMode.MOCK, verified_result=True)
    cref = ConfirmationReference(state_revision=3, operation_digest="0123456789abcdef", confirmation_source_id="ch-1", expires_at_utc="2026-11-26T01:00:00Z")
    assert cref.state_revision == 3


def test_ct21_ct22_ct23_ct24_ct25_ct26_synthesis_plan_and_chunk():
    gen = GenerationRef("s-1", 1, 2)
    chunks_in = [ChunkPlan("c0", 0, "Merhaba dünya", post_pause_ms=150)]
    plan = SynthesisPlan("2.0", gen, "p-1", 0, "resp-1", "Merhaba.", "Merhaba dünya", "tr", "leyla", 42, chunks=tuple(chunks_in), normalization_passes=1, validation_status=PlanValidationStatus.VALID)
    chunks_in.append(ChunkPlan("c1", 1, "Ek"))
    assert len(plan.chunks) == 1
    assert plan.seed == 42
    with pytest.raises(FrozenInstanceError):
        plan.seed = 9  # type: ignore[misc]
    with pytest.raises(ValueError):
        ChunkPlan("c0", 0, "test", post_pause_ms=-1)
    with pytest.raises(ValueError):
        ChunkPlan("c0", 0, "test", requested_speed=float("nan"))

    leg_plan = synthesis_plan_from_legacy(
        session_id="s-1", turn_id=1, generation_id=2, plan_id="p-leg", response_id="r-1",
        source_text="Merhaba", normalized_text="Merhaba", chunks_text=[("Merhaba", 0.25)], seed=77,
    )
    assert leg_plan.ok and leg_plan.value.normalization_passes is None and leg_plan.value.seed == 77

    pcm_f32 = np.ones(4800, dtype=np.float32) * 0.1
    ac = AudioChunk(gen, "p-1", 0, "c0", 0, AudioFormat(48000, 1, AudioEncoding.FLOAT32_LE), 4800, pcm_f32.tobytes(), "leyla", 42, cache_status=CacheStatus.MISS, quality_status=QualityStatus.PENDING)
    assert ac.actual_duration_ms == pytest.approx(100.0)
    validate_plan_chunk_consistency(plan, ac)
    bad_ac = AudioChunk(GenerationRef("s-1", 1, 99), "p-1", 0, "c0", 0, AudioFormat(48000, 1, AudioEncoding.FLOAT32_LE), 4800, pcm_f32.tobytes(), "leyla", 42)
    with pytest.raises(ValueError):
        validate_plan_chunk_consistency(plan, bad_ac)


def test_ct27_ct28_playback_frames_and_scopes():
    gen = GenerationRef("s-1", 1, 1)
    rf = rendered_frame_from_legacy_pcm(generation_ref=gen, stream_id="out-1", sequence=0, sample_offset=0, output_rate_hz=8000, pcm16_bytes=b"\x00" * 320)
    assert rf.profile == PlaybackProfile.AUDIOSOCKET_8K_PCM16 and rf.sample_count == 160
    ev = playback_event_from_legacy(generation_ref=gen, kind=PlaybackEventKind.FLUSHED, sequence=1, monotonic_ns=500, observation_scope=ObservationScope.SERVER)
    assert not ev.confirms_endpoint_audible


def test_ct29_ct30_json_and_safe_projection():
    raw_secret = "SECRET-TOKEN-999"
    res = ASRResult(_env(), "utt-1", 0, ASRStatus.FINAL, f"plakam {raw_secret}", ASROutcome.OK)
    proj = safe_telemetry_projection(res)
    dumped = metadata_to_json(proj)
    assert raw_secret not in dumped
    assert "raw_transcript" not in proj
    parsed = json.loads(dumped)
    assert parsed["outcome"] == "OK"


def test_ct31_ct32_ct33_ct34_ct35_ct36_legacy_and_isolation():
    legacy_asr = asr_result_from_legacy_text(session_id="s-a", utterance_id="u-a", raw_text="Merhaba", sequence=0, monotonic_ns=10)
    assert legacy_asr.ok and asr_result_to_legacy_text(legacy_asr.value) == "Merhaba"
    rec = tool_receipt_from_legacy_outcome(operation_id="op-1", tool_id="create_booking", legacy_outcome="timeout")
    assert rec.status == ToolReceiptStatus.UNKNOWN and not rec.is_committed_real
    raw_pcm = b"\x01\x00" * 160
    fr = audio_frame_from_legacy_pcm(session_id="s-a", stream_id="in", sample_rate_hz=8000, data=raw_pcm)
    assert fr.ok and audio_frame_to_legacy_pcm(fr.value) == raw_pcm
    d1 = dialogue_response_from_legacy(session_id="s-a", response_id="r-1", speech_text="Tamam", sequence=0, monotonic_ns=10)
    d2 = dialogue_response_from_legacy(session_id="s-b", response_id="r-2", speech_text="Evet", sequence=0, monotonic_ns=20)
    assert d1.value.envelope.session_id != d2.value.envelope.session_id
    CancellationReference(GenerationRef("s-a", 1, 1), "barge_in")
    assert math.isfinite(audio_chunk_from_legacy_waveform(
        generation_ref=GenerationRef("s-a", 1, 1), plan_id="p", plan_revision=0, chunk_id="c0", chunk_index=0,
        waveform_48k=np.ones(480, dtype=np.float32) * 0.2, seed=9,
    ).value.actual_duration_ms)
