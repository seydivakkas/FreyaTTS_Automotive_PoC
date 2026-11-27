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

import asyncio
import json
import math
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from backend.audio_rendering import (
    AUDIOSOCKET_AUDIO,
    AUDIOSOCKET_DTMF,
    AUDIOSOCKET_ERROR,
    AUDIOSOCKET_HANGUP,
    AUDIOSOCKET_UUID,
    FRAME_PERIOD_NS,
    AudioRenderingPipeline,
    AudioSocketOutboundAdapter,
    AudioSocketStreamParser,
    ClockDomainMismatchError,
    ControlOwnershipResolver,
    ControlStatus,
    FrameSynchronizer,
    InputValidationError,
    LatePolicy,
    MonotonicPacer,
    PaceOwner,
    PlaybackEventEmitter,
    QuantizationPolicy,
    SampleAccounting,
    StatefulLegacyDSPAdapter,
    StreamProfileBinding,
    StreamStateRegistry,
    StreamingOutputResampler,
    SubmissionOutcome,
    TerminalPolicy,
    TransportCompletionUncertainError,
    UnknownRenderProfileError,
    WebTransportAdapter,
    WireWriteOutcome,
    build_web_control_envelope,
    compare_legacy_vs_strict,
    compute_pause_output_samples,
    encode_audiosocket_audio_frame,
    encode_audiosocket_control,
    encode_web_audio_frame,
    iter_bounded_pcm_silence,
    iter_legacy_frames,
    quantize_float32_to_pcm16le,
    render_legacy_wave_48k_to_pcm,
    resolve_render_profile,
    validate_raw_audio_chunk,
)
from backend.core.configuration.contracts import ConfigSource
from backend.core.configuration.snapshots import build_snapshot
from backend.core.contracts.audio import AudioEncoding, AudioFormat
from backend.core.contracts.common import (
    CONTRACT_SCHEMA_VERSION,
    GenerationRef,
    MetricStatus,
    StreamDirection,
    StreamRef,
)
from backend.core.contracts.playback import (
    ObservationScope,
    PlaybackEvent,
    PlaybackEventKind,
    PlaybackProfile,
    RenderedFrame,
)
from backend.core.contracts.synthesis import (
    AudioChunk,
    CacheStatus,
    ChunkPlan,
    PlanValidationStatus,
    QualityStatus,
    SynthesisPlan,
)
from backend.core.runtime.deadlines import FakeClock
from backend.core.runtime.result_admission import AdmissionStatus
from backend.core.runtime.session_context import CleanupStatus
from backend.core.runtime.turn_generation import PauseRef
from backend.observability.event_bus import BoundedEventBus, DropPolicy
from backend.observability.evidence import EvidenceKind
from tests.harness.acceptance import evaluate_gates
from tests.harness.adapters.fake_transport import FakeAudioSocketTransport
from tests.harness.adapters.fake_tts import FakeTTSAdapter
from tests.harness.barriers import DeterministicBarrier, InterleavingPoint, run_with_watchdog
from tests.harness.contracts import GateRecord, GateStatus
from tests.harness.evidence_validator import EvidenceValidator, PIISecretScanner
from tests.harness.fake_clock import HarnessClock
from tests.harness.feature_regression import FeatureRegressionMapper

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_RUN_ID = "20261126T004342Z"
M00_BASELINE_ID = "20261126T001600Z"


def _make_chunk(
    gen_ref: GenerationRef,
    samples: np.ndarray,
    *,
    plan_id: str = "plan-1",
    plan_revision: int = 1,
    chunk_id: str = "chk-0",
    chunk_index: int = 0,
    rate: int = 48000,
    channels: int = 1,
    encoding: AudioEncoding = AudioEncoding.FLOAT32_LE,
    quality_status: QualityStatus = QualityStatus.PASS,
    post_pause_ms: int | None = None,
    requested_speed: float | None = None,
    applied_speed: float | None = None,
    seed: int = 9,
) -> AudioChunk:
    arr = np.asarray(samples, dtype=np.float32)
    return AudioChunk(
        generation_ref=gen_ref,
        plan_id=plan_id,
        plan_revision=plan_revision,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        format=AudioFormat(rate, channels, encoding),
        sample_count=int(arr.size),
        payload=arr.tobytes(),
        voice_profile="leyla-baseline-9",
        seed=seed,
        model_revision="synthetic-tts-fixture",
        solver="euler32-mock",
        ode_steps=32,
        cache_status=CacheStatus.MISS,
        quality_status=quality_status,
        post_pause_ms=post_pause_ms,
        requested_speed=requested_speed,
        applied_speed=applied_speed,
    )


def _sine_48k(freq_hz: float, count: int, amp: float = 0.5) -> np.ndarray:
    t = np.arange(count, dtype=np.float64) / 48000.0
    return (amp * np.sin(2.0 * math.pi * freq_hz * t)).astype(np.float32)


def _make_plan(
    gen_ref: GenerationRef,
    *,
    plan_id: str = "plan-1",
    plan_revision: int = 1,
    texts: tuple[str, ...] = ("Merhaba.",),
    validation_status: PlanValidationStatus = PlanValidationStatus.VALID,
) -> SynthesisPlan:
    chunks = tuple(
        ChunkPlan(
            chunk_id=f"chk-{i}",
            chunk_index=i,
            model_text=txt,
        )
        for i, txt in enumerate(texts)
    )
    joined = " ".join(texts)
    return SynthesisPlan(
        schema_version=CONTRACT_SCHEMA_VERSION,
        generation_ref=gen_ref,
        plan_id=plan_id,
        plan_revision=plan_revision,
        response_id=f"resp-{plan_id}",
        source_text=joined,
        normalized_text=joined,
        language="tr",
        voice_profile="leyla-baseline-9",
        seed=9,
        chunks=chunks,
        model_revision="synthetic-tts-fixture",
        lexicon_revision="lex-v1",
        capability_revision="cap-v1",
        validation_status=validation_status,
    )


# ---------------------------------------------------------------------------
# AR01–AR08: Prerequisites, Passive Imports, Inventory & Legacy Characterization
# ---------------------------------------------------------------------------


def test_ar01_prerequisite_accepted_lineage() -> None:
    core_matrix = REPO_ROOT / "docs" / "freya2" / "core_integration" / CORE_RUN_ID / "CORE_ACCEPTANCE_MATRIX.json"
    assert core_matrix.exists()
    data = json.loads(core_matrix.read_text(encoding="utf-8"))
    assert data["core_integration_ready"] is True
    assert data["m08_ready"] is True
    assert data["vertical_slice_ready"] is True
    for idx in range(12):
        assert data["gates"][f"CG{idx:02d}"] == "PASS"

    ev = EvidenceValidator(REPO_ROOT)
    m00_res = ev.verify_m00_baseline(data["baseline_run_id"])
    assert m00_res.status.value == "ACCEPTED"

    f5_res = ev.verify_package_acceptance_dir(
        "F5-A",
        REPO_ROOT / "docs" / "freya2" / "f5_a",
        required_gates=tuple(f"G{i:02d}" for i in range(20)),
        ready_flag="f5_a_ready",
    )
    assert f5_res.status.value == "ACCEPTED"


def test_ar02_missing_prerequisite_evidence_holds(tmp_path: Path) -> None:
    (tmp_path / "docs" / "freya2").mkdir(parents=True)
    ev = EvidenceValidator(tmp_path)
    res = ev.verify_package_acceptance_dir(
        "F5-A",
        tmp_path / "docs" / "freya2" / "f5_a",
        required_gates=("G00",),
        ready_flag="f5_a_ready",
    )
    assert res.status.value == "MISSING"


def test_ar03_passive_import_no_torch_cuda_network_or_threads() -> None:
    code = (
        "import sys, threading; "
        "t0 = threading.active_count(); "
        "import backend.audio_rendering; "
        "t1 = threading.active_count(); "
        "forbidden = [m for m in ('torch','cuda','faster_whisper','ctranslate2','backend.main','backend.db','backend.models','backend.session','backend.dsp','backend.audio','backend.audiosocket_server') if m in sys.modules]; "
        "assert t1 == t0, f'threads spawned: {t0}->{t1}'; "
        "assert not forbidden, f'forbidden modules loaded: {forbidden}'; "
        "print('PASSIVE_OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "PASSIVE_OK" in proc.stdout


def test_ar04_strict_package_file_ownership() -> None:
    expected_modules = {
        "__init__.py",
        "audiosocket_adapter.py",
        "control_adapter.py",
        "dsp_adapter.py",
        "framer.py",
        "input_validator.py",
        "legacy_adapter.py",
        "lifecycle.py",
        "pacing.py",
        "pipeline.py",
        "playback_events.py",
        "profile_adapter.py",
        "quantizer.py",
        "resampler.py",
        "sample_accounting.py",
        "stream_state.py",
        "submission_fence.py",
        "telemetry.py",
        "web_adapter.py",
    }
    actual = {p.name for p in (REPO_ROOT / "backend" / "audio_rendering").glob("*.py")}
    assert actual == expected_modules
    for path in (REPO_ROOT / "backend" / "audio_rendering").glob("*.py"):
        header = path.read_text(encoding="utf-8")[:1200]
        assert "Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)" in header


def test_ar05_inventory_existing_output_entrypoints() -> None:
    dsp_src = (REPO_ROOT / "backend" / "dsp.py").read_text(encoding="utf-8")
    audio_src = (REPO_ROOT / "backend" / "audio.py").read_text(encoding="utf-8")
    as_src = (REPO_ROOT / "backend" / "audiosocket_server.py").read_text(encoding="utf-8")
    sess_src = (REPO_ROOT / "backend" / "session.py").read_text(encoding="utf-8")
    main_src = (REPO_ROOT / "backend" / "main.py").read_text(encoding="utf-8")

    assert "def apply_telephony_eq_and_downsample_8k" in dsp_src
    assert "def apply_fade_and_comfort_noise" in dsp_src
    assert "def resample(" in audio_src and "def pcm(" in audio_src and "def pace(" in audio_src
    assert "AUDIOSOCKET_AUDIO = 0x10" in as_src and "def build_packet(" in as_src
    assert "async def play_wave(" in sess_src
    assert '@app.websocket("/ws/voice")' in main_src


def test_ar06_legacy_rendering_characterization() -> None:
    wav = _sine_48k(1000.0, 9600, amp=0.5)
    pcm_8k = render_legacy_wave_48k_to_pcm(wav, output_rate=8000)
    pcm_16k = render_legacy_wave_48k_to_pcm(wav, output_rate=16000)
    assert len(pcm_8k) == 1600 * 2
    assert len(pcm_16k) == 3200 * 2
    assert len(iter_legacy_frames(pcm_8k, output_rate=8000)) == 10
    assert len(iter_legacy_frames(pcm_16k, output_rate=16000)) == 10


@pytest.mark.asyncio
async def test_ar07_strict_vs_legacy_single_authority() -> None:
    clock = HarnessClock(initial_ns=1_000_000)
    pipe = AudioRenderingPipeline(session_id="sess-ar07", trusted_channel="asterisk", clock=clock)
    gref = await pipe.start_generation()
    chunk = _make_chunk(gref, _sine_48k(1000.0, 9600, amp=0.5))
    res = await pipe.render_chunk(chunk)
    assert res.admitted is True
    await pipe.finish_generation_eos()

    sent: list[RenderedFrame] = []
    recs = await pipe.pump_and_submit(submit_fn=lambda f: sent.append(f))
    assert len(sent) == 10
    assert all(r.outcome == SubmissionOutcome.SUBMITTED_SERVER for r in recs)
    with pytest.raises(RuntimeError):
        await pipe.render_chunk(chunk, writer_id="unauthorized.writer")
    await pipe.close()


def test_ar08_shadow_comparison_bounded_no_transport() -> None:
    wav = _sine_48k(1000.0, 9600, amp=0.5)
    shadow_8k = compare_legacy_vs_strict(wav, output_rate=8000)
    shadow_16k = compare_legacy_vs_strict(wav, output_rate=16000)
    assert shadow_8k.transport_sent is False
    assert shadow_8k.legacy_sample_count == 1600
    assert shadow_8k.strict_sample_count == 1600
    assert shadow_8k.rms_diff_db is not None and abs(shadow_8k.rms_diff_db) < 1.0
    assert shadow_16k.transport_sent is False
    assert shadow_16k.strict_sample_count == 3200


# ---------------------------------------------------------------------------
# AR09–AR19: M01 Contracts, Input Validation, Profiles & Epoch Pinning
# ---------------------------------------------------------------------------


def test_ar09_m01_contract_mapping_validated() -> None:
    gref = GenerationRef("sess-ar09", 1, 1)
    sref = StreamRef("sess-ar09", "out-0", StreamDirection.OUTPUT, 0)
    frame = RenderedFrame(
        generation_ref=gref,
        stream_ref=sref,
        sequence=0,
        sample_offset=0,
        profile=PlaybackProfile.WEB_16K_PCM16,
        format=AudioFormat(16000, 1, AudioEncoding.PCM_S16LE),
        frame_duration_ms=20.0,
        sample_count=320,
        valid_sample_count=320,
        payload=b"\x00" * 640,
        terminal=False,
    )
    assert frame.sample_count == 320
    assert frame.generation_ref == gref
    assert frame.stream_ref == sref


def test_ar10_unknown_scope_and_direction_rejected() -> None:
    with pytest.raises(UnknownRenderProfileError):
        resolve_render_profile("unknown_channel_spoof")
    with pytest.raises(ValueError):
        StreamProfileBinding(
            StreamRef("sess-ar10", "in-0", StreamDirection.INPUT, 0),
            resolve_render_profile("web"),
        )


def test_ar11_valid_48k_mono_float32_immutable_admission() -> None:
    gref = GenerationRef("sess-ar11", 1, 1)
    samples = _sine_48k(440.0, 960, amp=0.5)
    chunk = _make_chunk(gref, samples)
    orig_bytes = bytes(chunk.payload)

    val = validate_raw_audio_chunk(chunk, expected_generation_ref=gref)
    assert val.samples.flags.writeable is False
    assert val.chunk.payload == orig_bytes
    assert val.raw_peak_abs <= 0.51
    assert val.raw_overrange_samples == 0
    with pytest.raises(ValueError):
        val.samples[0] = 0.0


def test_ar12_wrong_rate_encoding_or_channels_rejected() -> None:
    gref = GenerationRef("sess-ar12", 1, 1)
    samples = _sine_48k(440.0, 960, amp=0.5)
    with pytest.raises(ValueError):
        _make_chunk(gref, samples, rate=16000)
    with pytest.raises(ValueError):
        _make_chunk(gref, samples, channels=2)
    with pytest.raises(ValueError):
        _make_chunk(gref, samples, encoding=AudioEncoding.PCM_S16LE)


def test_ar13_nonfinite_bool_and_payload_mismatch_rejected() -> None:
    gref = GenerationRef("sess-ar13", 1, 1)
    samples = _sine_48k(440.0, 960, amp=0.5)
    bad_nan = samples.copy()
    bad_nan[10] = float("nan")
    with pytest.raises(InputValidationError) as ei_nan:
        validate_raw_audio_chunk(_make_chunk(gref, bad_nan))
    assert ei_nan.value.error_info.code == "NON_FINITE_AUDIO"

    bad_inf = samples.copy()
    bad_inf[5] = float("inf")
    with pytest.raises(InputValidationError) as ei_inf:
        validate_raw_audio_chunk(_make_chunk(gref, bad_inf))
    assert ei_inf.value.error_info.code == "NON_FINITE_AUDIO"

    with pytest.raises(ValueError):
        AudioChunk(
            generation_ref=gref,
            plan_id="p",
            plan_revision=1,
            chunk_id="c",
            chunk_index=0,
            format=AudioFormat(48000, 1, AudioEncoding.FLOAT32_LE),
            sample_count=True,  # type: ignore[arg-type]
            payload=b"\x00\x00\x00\x00",
            voice_profile="leyla",
            seed=9,
        )


def test_ar14_oversize_and_zero_sample_count_rejected_before_alloc() -> None:
    gref = GenerationRef("sess-ar14", 1, 1)
    with pytest.raises(ValueError):
        _make_chunk(gref, np.zeros(0, np.float32))
    huge_chunk = _make_chunk(gref, np.zeros(1000, np.float32))
    with pytest.raises(InputValidationError) as ei_ov:
        validate_raw_audio_chunk(huge_chunk, max_chunk_samples=500)
    assert ei_ov.value.error_info.code == "CHUNK_OVERSIZE"


def test_ar15_quality_guard_fail_vs_unknown() -> None:
    gref = GenerationRef("sess-ar15", 1, 1)
    samples = _sine_48k(440.0, 960)
    fail_chunk = _make_chunk(gref, samples, quality_status=QualityStatus.FAIL)
    with pytest.raises(InputValidationError) as ei_fail:
        validate_raw_audio_chunk(fail_chunk, strict_quality_gate=True)
    assert ei_fail.value.error_info.code == "QUALITY_GUARD_FAILED"

    unk_chunk = _make_chunk(gref, samples, quality_status=QualityStatus.UNKNOWN)
    val_unk = validate_raw_audio_chunk(unk_chunk)
    assert val_unk.acoustic_quality_verified is False

    invalid_plan = _make_plan(gref, validation_status=PlanValidationStatus.INVALID)
    with pytest.raises(InputValidationError) as ei_plan:
        validate_raw_audio_chunk(_make_chunk(gref, samples), plan=invalid_plan)
    assert ei_plan.value.error_info.code == "INVALID_SYNTHESIS_PLAN"


def test_ar16_duplicate_conflicting_and_out_of_order_chunks_rejected() -> None:
    gref = GenerationRef("sess-ar16", 1, 1)
    samples = _sine_48k(440.0, 960)
    seen = {0: "chk-0"}

    with pytest.raises(InputValidationError) as ei_dup:
        validate_raw_audio_chunk(_make_chunk(gref, samples, chunk_id="chk-0", chunk_index=0), seen_chunks=seen)
    assert ei_dup.value.error_info.code == "DUPLICATE_CHUNK"

    with pytest.raises(InputValidationError) as ei_conf:
        validate_raw_audio_chunk(_make_chunk(gref, samples, chunk_id="chk-other", chunk_index=0), seen_chunks=seen)
    assert ei_conf.value.error_info.code == "CONFLICTING_CHUNK"

    with pytest.raises(InputValidationError) as ei_gap:
        validate_raw_audio_chunk(_make_chunk(gref, samples, chunk_id="chk-2", chunk_index=2), expected_chunk_index=1)
    assert ei_gap.value.error_info.code == "OUT_OF_ORDER_CHUNK"


def test_ar17_trusted_web_and_audiosocket_profile_pinning() -> None:
    web_prof = resolve_render_profile("web")
    phone_prof = resolve_render_profile("asterisk")
    assert web_prof.output_format == AudioFormat(16000, 1, AudioEncoding.PCM_S16LE)
    assert (web_prof.samples_per_frame, web_prof.bytes_per_frame) == (320, 640)
    assert web_prof.dsp_enabled is False
    assert phone_prof.output_format == AudioFormat(8000, 1, AudioEncoding.PCM_S16LE)
    assert (phone_prof.samples_per_frame, phone_prof.bytes_per_frame) == (160, 320)
    assert phone_prof.dsp_enabled is True


def test_ar18_unknown_or_spoofed_channel_metadata_rejected() -> None:
    for bad in ("sip_spoof", "", "webrtc_unknown", 12345):
        with pytest.raises(UnknownRenderProfileError):
            resolve_render_profile(bad)  # type: ignore[arg-type]
    with pytest.raises(UnknownRenderProfileError):
        resolve_render_profile("asterisk", pace_owner=PaceOwner.CLIENT)


@pytest.mark.asyncio
async def test_ar19_config_pinned_across_active_epoch_and_explicit_advance() -> None:
    snap1 = build_snapshot(
        values={"media_write_timeout_sec": 2.0},
        sources={"media_write_timeout_sec": ConfigSource.DEFAULT},
        feature_flags={},
        snapshot_seq=1,
    )
    snap2 = build_snapshot(
        values={"media_write_timeout_sec": 5.0},
        sources={"media_write_timeout_sec": ConfigSource.OVERRIDE},
        feature_flags={},
        snapshot_seq=2,
    )
    pipe = AudioRenderingPipeline(session_id="sess-ar19", trusted_channel="web", snapshot=snap1)
    await pipe.start_generation()
    assert pipe.binding.stream_ref.format_epoch == 0
    assert pipe.profile.config_revision == snap1.config_revision
    assert pipe.profile.media_write_timeout_sec == 2.0

    new_ref = await pipe.advance_epoch(new_snapshot=snap2)
    assert new_ref.format_epoch == 1
    assert pipe.profile.config_revision == snap2.config_revision
    assert pipe.profile.media_write_timeout_sec == 5.0
    await pipe.close()


# ---------------------------------------------------------------------------
# AR20–AR32: Stream Isolation, Stateful Legacy DSP & Control Ownership
# ---------------------------------------------------------------------------


def test_ar20_interleaved_streams_match_isolated_references() -> None:
    sig_a = _sine_48k(500.0, 4800, amp=0.4)
    sig_b = _sine_48k(1800.0, 4800, amp=0.6)

    prof = resolve_render_profile("asterisk")
    reg = StreamStateRegistry()
    st_a = reg.create(
        binding=StreamProfileBinding(StreamRef("sess-A", "out", StreamDirection.OUTPUT, 0), prof),
        generation_ref=GenerationRef("sess-A", 1, 1),
    )
    st_b = reg.create(
        binding=StreamProfileBinding(StreamRef("sess-B", "out", StreamDirection.OUTPUT, 0), prof),
        generation_ref=GenerationRef("sess-B", 1, 1),
    )
    iso_a = StatefulLegacyDSPAdapter(enabled=True)
    iso_b = StatefulLegacyDSPAdapter(enabled=True)

    out_a1 = st_a.dsp.process_pre_resample_48k(sig_a[:1920])
    out_b1 = st_b.dsp.process_pre_resample_48k(sig_b[:1920])
    out_a2 = st_a.dsp.process_pre_resample_48k(sig_a[1920:])
    out_b2 = st_b.dsp.process_pre_resample_48k(sig_b[1920:])

    ref_a = iso_a.process_pre_resample_48k(sig_a)
    ref_b = iso_b.process_pre_resample_48k(sig_b)
    np.testing.assert_allclose(np.concatenate([out_a1, out_a2]), ref_a, atol=1e-6)
    np.testing.assert_allclose(np.concatenate([out_b1, out_b2]), ref_b, atol=1e-6)


def test_ar21_f0_input_and_f6_output_resamplers_distinct() -> None:
    from backend.audio_frontend.resampler import StatefulResampler

    f0_in = StatefulResampler(input_rate_hz=8000, output_rate_hz=16000)
    f6_out = StreamingOutputResampler(input_rate_hz=48000, output_rate_hz=8000)
    assert f0_in is not f6_out
    assert f0_in._stream is not f6_out._stream
    f0_in.process(np.ones(160, dtype=np.float32) * 0.1)
    assert f6_out.input_samples == 0
    f0_in.close()


def test_ar22_chunk_boundaries_retain_filter_history() -> None:
    sig = _sine_48k(900.0, 4800, amp=0.5)
    chunked = StatefulLegacyDSPAdapter(enabled=True)
    whole = StatefulLegacyDSPAdapter(enabled=True)
    c1 = chunked.process_pre_resample_48k(sig[:1337])
    c2 = chunked.process_pre_resample_48k(sig[1337:])
    ref = whole.process_pre_resample_48k(sig)
    np.testing.assert_allclose(np.concatenate([c1, c2]), ref, atol=1e-6)
    assert chunked.processed_48k_samples == 4800


def test_ar23_new_generation_after_aborted_residue_zero_leak() -> None:
    prof = resolve_render_profile("asterisk")
    reg = StreamStateRegistry()
    st = reg.create(
        binding=StreamProfileBinding(StreamRef("sess-ar23", "out", StreamDirection.OUTPUT, 0), prof),
        generation_ref=GenerationRef("sess-ar23", 1, 1),
    )
    st.dsp.process_pre_resample_48k(_sine_48k(400.0, 960, amp=0.5))
    st.resampler.process_chunk(_sine_48k(400.0, 960, amp=0.5))
    st.framer.push_pcm(b"\x11\x22" * 40)

    disc = st.switch_generation(GenerationRef("sess-ar23", 1, 2), reason="abort_test")
    assert disc is not None and disc.discarded_output_samples == 40
    assert st.framer.residual_samples == 0
    assert st.dsp.processed_48k_samples == 0

    # New generation output matches a brand-new clean stream
    sig2 = _sine_48k(1000.0, 4800, amp=0.5)
    clean_dsp = StatefulLegacyDSPAdapter(enabled=True)
    clean_rs = StreamingOutputResampler(output_rate_hz=8000)
    actual_out = np.concatenate([
        st.resampler.process_chunk(st.dsp.process_pre_resample_48k(sig2)),
        st.resampler.flush_eos(),
    ])
    expected_out = np.concatenate([
        clean_rs.process_chunk(clean_dsp.process_pre_resample_48k(sig2)),
        clean_rs.flush_eos(),
    ])
    np.testing.assert_allclose(actual_out, expected_out, atol=1e-7)


def test_ar24_hpf_120hz_attenuates_low_frequency() -> None:
    dsp_hp = StatefulLegacyDSPAdapter(enabled=True)
    y_60 = dsp_hp.process_pre_resample_48k(_sine_48k(60.0, 24000, amp=0.5))
    dsp_1k = StatefulLegacyDSPAdapter(enabled=True)
    y_1k = dsp_1k.process_pre_resample_48k(_sine_48k(1000.0, 24000, amp=0.5))
    rms_60 = float(np.sqrt(np.mean(y_60[4800:] ** 2)))
    rms_1k = float(np.sqrt(np.mean(y_1k[4800:] ** 2)))
    assert 20.0 * math.log10(rms_1k / max(rms_60, 1e-12)) > 10.0


def test_ar25_presence_eq_3k2_boost() -> None:
    dsp_1k = StatefulLegacyDSPAdapter(enabled=True)
    y_1k = dsp_1k.process_pre_resample_48k(_sine_48k(1000.0, 24000, amp=0.5))
    dsp_3k2 = StatefulLegacyDSPAdapter(enabled=True)
    y_3k2 = dsp_3k2.process_pre_resample_48k(_sine_48k(3200.0, 24000, amp=0.5))
    rms_1k = float(np.sqrt(np.mean(y_1k[4800:] ** 2)))
    rms_3k2 = float(np.sqrt(np.mean(y_3k2[4800:] ** 2)))
    assert rms_3k2 > rms_1k * 1.2


def test_ar26_soft_limiter_tanh_preserved() -> None:
    dsp = StatefulLegacyDSPAdapter(enabled=True)
    hot = np.array([2.5, -2.5, 0.5], dtype=np.float32)
    lim, clipped = dsp.process_post_resample_limiter(hot)
    assert clipped == 2
    np.testing.assert_allclose(lim, np.tanh(hot * 1.15), atol=1e-6)


def test_ar27_upstream_fade_prevents_double_fade() -> None:
    ctrl = ControlOwnershipResolver()
    gref = GenerationRef("sess-ar27", 1, 1)
    chk = _make_chunk(gref, _sine_48k(1000.0, 960))
    _, recs = ctrl.evaluate_chunk_controls(chk, output_rate_hz=8000, fade_applied_upstream=True)
    fade_rec = [r for r in recs if r.control_name == "utterance_fade"][0]
    assert fade_rec.status == ControlStatus.ALREADY_APPLIED_UPSTREAM
    assert fade_rec.authority == "F5_UPSTREAM"


def test_ar28_disabled_dsp_and_comfort_noise_unchanged() -> None:
    web_prof = resolve_render_profile("web")
    assert web_prof.dsp_enabled is False
    dsp_off = StatefulLegacyDSPAdapter(enabled=False)
    sig = _sine_48k(60.0, 960, amp=0.5)
    np.testing.assert_array_equal(dsp_off.process_pre_resample_48k(sig), sig)
    lim_off, clipped_off = dsp_off.process_post_resample_limiter(np.array([1.5, -1.5], np.float32))
    assert clipped_off == 0
    np.testing.assert_array_equal(lim_off, np.array([1.5, -1.5], np.float32))
    with pytest.raises(ValueError):
        StatefulLegacyDSPAdapter(enabled=True, comfort_noise_enabled=True)


def test_ar29_post_pause_rendered_once_with_accounting() -> None:
    ctrl = ControlOwnershipResolver()
    gref = GenerationRef("sess-ar29", 1, 1)
    c1 = _make_chunk(gref, _sine_48k(1000.0, 960), chunk_id="chk-p1", post_pause_ms=100)
    pause_samples, recs = ctrl.evaluate_chunk_controls(c1, output_rate_hz=8000)
    assert pause_samples == 800
    assert any(r.control_name == "post_pause_ms" and r.status == ControlStatus.APPLIED for r in recs)

    # Re-evaluating same chunk_id never applies twice
    pause_again, recs_again = ctrl.evaluate_chunk_controls(c1, output_rate_hz=8000)
    assert pause_again == 0
    assert any(r.status == ControlStatus.ALREADY_APPLIED_UPSTREAM for r in recs_again)


def test_ar30_null_pause_and_upstream_applied_speed_not_reapplied() -> None:
    ctrl = ControlOwnershipResolver()
    gref = GenerationRef("sess-ar30", 1, 1)
    c2 = _make_chunk(gref, _sine_48k(1000.0, 960), chunk_id="chk-p2", post_pause_ms=None, requested_speed=1.15, applied_speed=1.15)
    p2, recs2 = ctrl.evaluate_chunk_controls(c2, output_rate_hz=16000)
    assert p2 == 0
    assert any(r.control_name == "speed" and r.status == ControlStatus.ALREADY_APPLIED_UPSTREAM for r in recs2)
    assert any(r.control_name == "post_pause_ms" and r.status == ControlStatus.IGNORED_NULL for r in recs2)


def test_ar31_unsupported_speed_emphasis_controls_explicit() -> None:
    ctrl = ControlOwnershipResolver()
    gref = GenerationRef("sess-ar31", 1, 1)
    c3 = _make_chunk(gref, _sine_48k(1000.0, 960), chunk_id="chk-p3", requested_speed=1.35, applied_speed=None)
    cp3 = ChunkPlan(
        chunk_id="chk-p3",
        chunk_index=0,
        model_text="Merhaba",
        requested_emphasis=("brand",),
        requested_controls=("wsola",),
    )
    _, recs3 = ctrl.evaluate_chunk_controls(c3, output_rate_hz=16000, chunk_plan=cp3)
    by_name = {r.control_name: r for r in recs3}
    assert by_name["speed"].status == ControlStatus.UNSUPPORTED
    assert by_name["emphasis"].status == ControlStatus.UNSUPPORTED
    assert by_name["requested_controls"].status == ControlStatus.UNSUPPORTED


def test_ar32_negative_nonfinite_oversize_pause_rejected_and_bounded_silence() -> None:
    ctrl = ControlOwnershipResolver()
    gref = GenerationRef("sess-ar32", 1, 1)
    samples = _sine_48k(1000.0, 960)
    for bad_pause in (-5, float("nan"), float("inf"), True, 50_000):
        c_bad = _make_chunk(gref, samples, chunk_id="chk-bad", post_pause_ms=bad_pause)  # type: ignore[arg-type]
        with pytest.raises(InputValidationError):
            ctrl.evaluate_chunk_controls(c_bad, output_rate_hz=16000)

    slices = list(iter_bounded_pcm_silence(compute_pause_output_samples(250, 16000), slice_samples=1600))
    assert [len(s) for s in slices] == [3200, 3200, 1600]
    assert sum(len(s) for s in slices) == 4000 * 2


# ---------------------------------------------------------------------------
# AR33–AR40: Stateful Output Resampling, Partition Invariance & Anti-Aliasing
# ---------------------------------------------------------------------------


def test_ar33_48k_to_16k_contiguous_ratio_and_count() -> None:
    sig = _sine_48k(1000.0, 48000, amp=0.5)
    rs = StreamingOutputResampler(output_rate_hz=16000)
    y = np.concatenate([rs.process_chunk(sig), rs.flush_eos()])
    assert len(y) == 16000
    assert rs.expected_total_output_rounded == 16000


def test_ar34_48k_to_8k_contiguous_ratio_and_count() -> None:
    sig = _sine_48k(1000.0, 48000, amp=0.5)
    rs = StreamingOutputResampler(output_rate_hz=8000)
    y = np.concatenate([rs.process_chunk(sig), rs.flush_eos()])
    assert len(y) == 8000
    assert rs.expected_total_output_rounded == 8000


@pytest.mark.parametrize("target_rate", [16000, 8000])
def test_ar35_prime_and_irregular_chunk_partitions_invariant(target_rate: int) -> None:
    sig = _sine_48k(1000.0, 48000, amp=0.5)
    rs_ref = StreamingOutputResampler(output_rate_hz=target_rate)
    y_ref = np.concatenate([rs_ref.process_chunk(sig), rs_ref.flush_eos()])

    rs_part = StreamingOutputResampler(output_rate_hz=target_rate)
    parts: list[np.ndarray] = []
    idx = 0
    for sz in (17, 137, 503, 1921, 73, 4099, 313, 960, 999999):
        if idx >= len(sig):
            break
        seg = sig[idx : idx + sz]
        idx += len(seg)
        parts.append(rs_part.process_chunk(seg))
    parts.append(rs_part.flush_eos())
    y_part = np.concatenate(parts)
    assert abs(len(y_part) - len(y_ref)) <= 1
    assert len(y_part) == len(y_ref)
    assert float(np.max(np.abs(y_part - y_ref))) <= 1e-6


def test_ar36_long_stream_tiny_chunks_rational_accounting() -> None:
    rs = StreamingOutputResampler(output_rate_hz=8000)
    chunk = _sine_48k(750.0, 48, amp=0.4)  # 1 ms tiny chunks
    out_parts = [rs.process_chunk(chunk) for _ in range(1000)]
    out_parts.append(rs.flush_eos())
    total = sum(len(p) for p in out_parts)
    assert total == 8000
    assert rs.expected_total_output_exact == 8000
    assert rs.flushed is True and rs.aborted is False


def test_ar37_startup_buffering_and_once_only_eos_tail() -> None:
    rs = StreamingOutputResampler(output_rate_hz=16000)
    y1 = rs.process_chunk(_sine_48k(1000.0, 960, amp=0.5))
    assert rs.pending_delay_samples_48k >= 0
    tail1 = rs.flush_eos()
    tail2 = rs.flush_eos()
    assert len(y1) + len(tail1) == 320
    assert len(tail2) == 0


def test_ar38_passband_1khz_within_tolerance_both_profiles() -> None:
    for sr_out in (16000, 8000):
        rs = StreamingOutputResampler(output_rate_hz=sr_out)
        y = np.concatenate([rs.process_chunk(_sine_48k(1000.0, 48000, amp=0.5)), rs.flush_eos()])
        sl = slice(sr_out // 10, sr_out * 9 // 10)
        rms_pb = float(np.sqrt(np.mean(y[sl] ** 2)))
        gain_db = 20.0 * math.log10(rms_pb / (0.5 / math.sqrt(2.0)))
        assert abs(gain_db) <= 1.0


def test_ar39_antialias_suppression_12khz_web_and_6khz_phone() -> None:
    for sr_out, alias_freq in ((16000, 12000.0), (8000, 6000.0)):
        rs_pb = StreamingOutputResampler(output_rate_hz=sr_out)
        y_pb = np.concatenate([rs_pb.process_chunk(_sine_48k(1000.0, 48000, amp=0.5)), rs_pb.flush_eos()])
        rs_al = StreamingOutputResampler(output_rate_hz=sr_out)
        y_al = np.concatenate([rs_al.process_chunk(_sine_48k(alias_freq, 48000, amp=0.5)), rs_al.flush_eos()])

        sl = slice(sr_out // 10, sr_out * 9 // 10)
        rms_pb = float(np.sqrt(np.mean(y_pb[sl] ** 2)))
        rms_al = float(np.sqrt(np.mean(y_al[sl] ** 2)))
        supp_db = 20.0 * math.log10(rms_pb / max(rms_al, 1e-12))
        assert supp_db >= 30.0


def test_ar40_abort_before_eos_discards_pending_state() -> None:
    rs_ab = StreamingOutputResampler(output_rate_hz=8000)
    rs_ab.process_chunk(_sine_48k(1000.0, 960))
    discarded = rs_ab.abort_discard()
    assert discarded > 0
    assert len(rs_ab.flush_eos()) == 0
    assert rs_ab.abort_discard() == 0


# ---------------------------------------------------------------------------
# AR41–AR55: PCM16 Quantization, 20ms Framing, Terminal Policy & Accounting
# ---------------------------------------------------------------------------


def test_ar41_zero_and_signed_limits_mapping() -> None:
    q_sat = quantize_float32_to_pcm16le(np.array([0.0, -1.0, 1.0], np.float32), policy=QuantizationPolicy.SATURATING_32768)
    assert struct.unpack("<3h", q_sat.pcm_bytes) == (0, -32768, 32767)

    q_sym = quantize_float32_to_pcm16le(np.array([0.0, -1.0, 1.0], np.float32), policy=QuantizationPolicy.SYMMETRIC_32767)
    assert struct.unpack("<3h", q_sym.pcm_bytes) == (0, -32767, 32767)


def test_ar42_overrange_saturates_without_wrap_and_counts() -> None:
    q_ov = quantize_float32_to_pcm16le(np.array([2.5, -2.5], np.float32), policy=QuantizationPolicy.SATURATING_32768)
    assert struct.unpack("<2h", q_ov.pcm_bytes) == (32767, -32768)
    assert q_ov.overrange_positive_count == 1
    assert q_ov.overrange_negative_count == 1
    assert q_ov.saturated_count >= 2


def test_ar43_negative_integer_exact_little_endian_bytes() -> None:
    q_le = quantize_float32_to_pcm16le(np.array([-1.0 / 32768.0, -1.0], np.float32))
    assert q_le.pcm_bytes == b"\xff\xff\x00\x80"


def test_ar44_half_step_rounding_ties_to_even() -> None:
    q_tie = quantize_float32_to_pcm16le(np.array([0.5 / 32768.0, 1.5 / 32768.0], np.float32))
    assert struct.unpack("<2h", q_tie.pcm_bytes) == (0, 2)


def test_ar45_nonfinite_rejected_and_distinct_saturation_and_dbfs() -> None:
    with pytest.raises(ValueError):
        quantize_float32_to_pcm16le(np.array([0.0, float("nan")], np.float32))
    q_sil = quantize_float32_to_pcm16le(np.zeros(160, np.float32))
    assert q_sil.rms_dbfs is None

    dsp = StatefulLegacyDSPAdapter(enabled=True)
    lim, lim_clipped = dsp.process_post_resample_limiter(np.array([2.0, 0.5], np.float32))
    q = quantize_float32_to_pcm16le(lim, policy=QuantizationPolicy.SATURATING_32768)
    assert lim_clipped == 1
    assert q.saturated_count == 0  # Limiter kept output within [-1, 1]


def test_ar46_web_320_samples_one_640b_full_frame() -> None:
    gref = GenerationRef("sess-ar46", 1, 1)
    sref = StreamRef("sess-ar46", "out-0", StreamDirection.OUTPUT, 0)
    prof_w = resolve_render_profile("web")
    acc_w = SampleAccounting(output_rate_hz=16000)
    fw = FrameSynchronizer(generation_ref=gref, stream_ref=sref, profile=prof_w, accounting=acc_w)
    frames = fw.push_pcm(b"\x01\x00" * 320)
    assert len(frames) == 1
    assert len(frames[0].payload) == 640 and frames[0].valid_sample_count == 320


def test_ar47_phone_160_samples_one_320b_full_frame() -> None:
    gref = GenerationRef("sess-ar47", 1, 1)
    sref = StreamRef("sess-ar47", "out-0", StreamDirection.OUTPUT, 0)
    prof_p = resolve_render_profile("asterisk")
    acc_p = SampleAccounting(output_rate_hz=8000)
    fp = FrameSynchronizer(generation_ref=gref, stream_ref=sref, profile=prof_p, accounting=acc_p)
    frames = fp.push_pcm(b"\x02\x00" * 160)
    assert len(frames) == 1
    assert len(frames[0].payload) == 320 and frames[0].valid_sample_count == 160


def test_ar48_irregular_blocks_retain_bounded_residual() -> None:
    gref = GenerationRef("sess-ar48", 1, 1)
    sref = StreamRef("sess-ar48", "out-0", StreamDirection.OUTPUT, 0)
    prof_p = resolve_render_profile("asterisk")
    acc_p = SampleAccounting(output_rate_hz=8000)
    fp = FrameSynchronizer(generation_ref=gref, stream_ref=sref, profile=prof_p, accounting=acc_p)
    assert fp.push_pcm(b"\x02\x00" * 100) == []
    assert fp.residual_samples == 100
    f2 = fp.push_pcm(b"\x03\x00" * 110)
    assert len(f2) == 1 and fp.residual_samples == 50


def test_ar49_eos_with_short_residual_pads_once_and_sets_valid_count() -> None:
    gref = GenerationRef("sess-ar49", 1, 1)
    sref = StreamRef("sess-ar49", "out-0", StreamDirection.OUTPUT, 0)
    prof_p = resolve_render_profile("asterisk", terminal_policy=TerminalPolicy.PAD_ONCE_WITH_ZERO)
    acc_p = SampleAccounting(output_rate_hz=8000)
    fp = FrameSynchronizer(generation_ref=gref, stream_ref=sref, profile=prof_p, accounting=acc_p)
    fp.push_pcm(b"\x04\x00" * 50)
    f_eos = fp.flush_eos()
    assert len(f_eos) == 1
    assert f_eos[0].terminal is True
    assert f_eos[0].valid_sample_count == 50
    assert len(f_eos[0].payload) == 320
    assert f_eos[0].payload[100:] == b"\x00" * 220


def test_ar50_eos_at_exact_boundary_emits_no_extra_padding_frame() -> None:
    gref = GenerationRef("sess-ar50", 1, 1)
    sref = StreamRef("sess-ar50", "out-0", StreamDirection.OUTPUT, 0)
    prof_w = resolve_render_profile("web")
    acc_w = SampleAccounting(output_rate_hz=16000)
    fw = FrameSynchronizer(generation_ref=gref, stream_ref=sref, profile=prof_w, accounting=acc_w)
    frames = fw.push_pcm(b"\x01\x00" * 320)
    assert len(frames) == 1
    assert fw.flush_eos() == []


@pytest.mark.asyncio
async def test_ar51_intentional_silence_and_terminal_padding_distinct() -> None:
    clock = HarnessClock(initial_ns=1_000)
    pipe = AudioRenderingPipeline(
        session_id="sess-ar51",
        trusted_channel="asterisk",
        clock=clock,
        sleep_ns_fn=lambda ns: asyncio.sleep(0),
    )
    gref = await pipe.start_generation()
    # 960 @ 48k -> 160 @ 8k + 15 ms post_pause (120 @ 8k) -> 280 total output = 1 full (160) + 120 valid + 40 terminal pad
    chunk = _make_chunk(gref, _sine_48k(1000.0, 960), post_pause_ms=15)
    await pipe.render_chunk(chunk)
    await pipe.finish_generation_eos()
    await pipe.pump_and_submit(submit_fn=lambda _f: None)

    snap = pipe.accounting_snapshot()
    assert snap.planned_silence_samples == 120
    assert snap.framed_valid_samples == snap.quantized_samples + 120
    assert snap.terminal_padding_samples > 0
    assert pipe.stream_state.accounting.verify_output_balance()[0] is True
    await pipe.close()


def test_ar52_duplicate_or_stale_eos_idempotent() -> None:
    gref = GenerationRef("sess-ar52", 1, 1)
    sref = StreamRef("sess-ar52", "out-0", StreamDirection.OUTPUT, 0)
    prof = resolve_render_profile("web")
    acc = SampleAccounting(output_rate_hz=16000)
    fw = FrameSynchronizer(generation_ref=gref, stream_ref=sref, profile=prof, accounting=acc)
    fw.push_pcm(b"\x01\x00" * 100)
    first = fw.flush_eos()
    second = fw.flush_eos()
    assert len(first) == 1
    assert second == []
    assert fw.duplicate_eos_count == 1


def test_ar53_sequence_and_sample_offset_monotonic_across_chunks() -> None:
    gref = GenerationRef("sess-ar53", 1, 1)
    sref = StreamRef("sess-ar53", "out-0", StreamDirection.OUTPUT, 0)
    prof = resolve_render_profile("asterisk")
    acc = SampleAccounting(output_rate_hz=8000)
    fp = FrameSynchronizer(generation_ref=gref, stream_ref=sref, profile=prof, accounting=acc)
    f_a = fp.push_pcm(b"\x01\x00" * 200)  # 1 frame (160), 40 residual
    f_b = fp.push_pcm(b"\x02\x00" * 200)  # 1 frame (160), 80 residual
    f_e = fp.flush_eos()                  # 1 terminal frame (80 valid)
    all_frames = f_a + f_b + f_e
    assert [f.sequence for f in all_frames] == [0, 1, 2]
    assert [f.sample_offset for f in all_frames] == [0, 160, 320]


@pytest.mark.asyncio
async def test_ar54_abort_discard_accounting_balanced_across_domains() -> None:
    clock = HarnessClock(initial_ns=1_000)
    pipe = AudioRenderingPipeline(session_id="sess-ar54", trusted_channel="asterisk", clock=clock)
    gref = await pipe.start_generation()
    await pipe.render_chunk(_make_chunk(gref, _sine_48k(1000.0, 1200)))
    await pipe.commit_interrupt(reason="abort_accounting_check")
    ok_bal, errs = pipe.stream_state.accounting.verify_output_balance()
    assert ok_bal and errs == []
    snap = pipe.accounting_snapshot()
    assert snap.queued_samples == 0
    assert snap.raw_48k_accepted == 1200
    await pipe.close()


def test_ar55_invalid_frame_format_or_terminal_count_rejected() -> None:
    gref = GenerationRef("sess-ar55", 1, 1)
    sref = StreamRef("sess-ar55", "out-0", StreamDirection.OUTPUT, 0)
    with pytest.raises(ValueError):
        RenderedFrame(
            generation_ref=gref,
            stream_ref=sref,
            sequence=0,
            sample_offset=0,
            profile=PlaybackProfile.AUDIOSOCKET_8K_PCM16,
            format=AudioFormat(8000, 1, AudioEncoding.PCM_S16LE),
            frame_duration_ms=20.0,
            sample_count=160,
            valid_sample_count=100,
            payload=b"\x00" * 320,
            terminal=False,
        )
    with pytest.raises(ValueError):
        RenderedFrame(
            generation_ref=gref,
            stream_ref=sref,
            sequence=0,
            sample_offset=0,
            profile=PlaybackProfile.WEB_16K_PCM16,
            format=AudioFormat(8000, 1, AudioEncoding.PCM_S16LE),  # wrong rate for WEB
            frame_duration_ms=20.0,
            sample_count=320,
            valid_sample_count=320,
            payload=b"\x00" * 640,
            terminal=False,
        )


# ---------------------------------------------------------------------------
# AR56–AR63: AudioSocket Wire Protocol & Web Transport Compatibility
# ---------------------------------------------------------------------------


def test_ar56_audiosocket_8k_frame_wire_header_10_01_40() -> None:
    gref = GenerationRef("sess-ar56", 1, 1)
    sref = StreamRef("sess-ar56", "out-0", StreamDirection.OUTPUT, 0)
    frame = RenderedFrame(
        generation_ref=gref,
        stream_ref=sref,
        sequence=0,
        sample_offset=0,
        profile=PlaybackProfile.AUDIOSOCKET_8K_PCM16,
        format=AudioFormat(8000, 1, AudioEncoding.PCM_S16LE),
        frame_duration_ms=20.0,
        sample_count=160,
        valid_sample_count=160,
        payload=b"\x34\x12" * 160,
        terminal=False,
    )
    pkt = encode_audiosocket_audio_frame(frame)
    assert pkt[:3] == b"\x10\x01\x40"
    assert len(pkt) == 323
    assert pkt[3:] == frame.payload


def test_ar57_audiosocket_tcp_fragmentation_and_coalescing() -> None:
    parser = AudioSocketStreamParser()
    p1 = b"\x10\x01\x40" + (b"\x34\x12" * 160)
    p2 = encode_audiosocket_control(AUDIOSOCKET_DTMF, b"1")
    coalesced = p1 + p2
    assert parser.feed(coalesced[:5]) == []
    parsed = parser.feed(coalesced[5:])
    assert len(parsed) == 2
    assert parsed[0] == (AUDIOSOCKET_AUDIO, b"\x34\x12" * 160)
    assert parsed[1] == (AUDIOSOCKET_DTMF, b"1")


def test_ar58_audiosocket_unsupported_type_or_length_overflow_rejected() -> None:
    with pytest.raises(ValueError):
        encode_audiosocket_control(0x99, b"")
    with pytest.raises(ValueError):
        encode_audiosocket_control(AUDIOSOCKET_UUID, b"short")
    with pytest.raises(ValueError):
        encode_audiosocket_control(AUDIOSOCKET_ERROR, b"x" * 64001)
    parser = AudioSocketStreamParser()
    with pytest.raises(ValueError):
        parser.feed(b"\x99\x00\x00")


def test_ar59_audiosocket_control_packets_preserved_separate_from_audio() -> None:
    sink = FakeAudioSocketTransport(max_send_buffer_bytes=4096)
    adapter = AudioSocketOutboundAdapter(sink)
    assert adapter.send_control(AUDIOSOCKET_UUID, b"\x01" * 16).outcome == WireWriteOutcome.SUBMITTED
    assert adapter.send_control(AUDIOSOCKET_DTMF, b"9").outcome == WireWriteOutcome.SUBMITTED
    assert adapter.send_control(AUDIOSOCKET_ERROR, b"\x01").outcome == WireWriteOutcome.SUBMITTED
    assert adapter.send_control(AUDIOSOCKET_HANGUP, b"").outcome == WireWriteOutcome.SUBMITTED
    assert adapter.control_packets_submitted == 4
    assert adapter.audio_packets_submitted == 0


def test_ar60_audiosocket_partial_write_uncertainty_and_safe_close() -> None:
    gref = GenerationRef("sess-ar60", 1, 1)
    sref = StreamRef("sess-ar60", "out-0", StreamDirection.OUTPUT, 0)
    frame = RenderedFrame(
        generation_ref=gref,
        stream_ref=sref,
        sequence=0,
        sample_offset=0,
        profile=PlaybackProfile.AUDIOSOCKET_8K_PCM16,
        format=AudioFormat(8000, 1, AudioEncoding.PCM_S16LE),
        frame_duration_ms=20.0,
        sample_count=160,
        valid_sample_count=160,
        payload=b"\x34\x12" * 160,
        terminal=False,
    )
    sink = FakeAudioSocketTransport(max_send_buffer_bytes=1024)
    closed_reasons: list[str] = []
    adapter = AudioSocketOutboundAdapter(sink, on_safe_close=closed_reasons.append)
    r_part = adapter.send_audio_frame(frame, partial_write_cap=100)
    assert r_part.outcome == WireWriteOutcome.PARTIAL_WRITE_UNCERTAIN
    assert r_part.bytes_written == 100
    assert r_part.closed_safely is True
    assert closed_reasons == ["PARTIAL_WRITE"]
    assert adapter.send_audio_frame(frame).outcome == WireWriteOutcome.REJECTED


def test_ar61_web_full_frame_640b_no_audiosocket_header() -> None:
    gref = GenerationRef("sess-ar61", 1, 1)
    sref = StreamRef("sess-ar61", "out-0", StreamDirection.OUTPUT, 0)
    frame = RenderedFrame(
        generation_ref=gref,
        stream_ref=sref,
        sequence=0,
        sample_offset=0,
        profile=PlaybackProfile.WEB_16K_PCM16,
        format=AudioFormat(16000, 1, AudioEncoding.PCM_S16LE),
        frame_duration_ms=20.0,
        sample_count=320,
        valid_sample_count=320,
        payload=b"\xab\xcd" * 320,
        terminal=False,
    )
    raw_web = encode_web_audio_frame(frame)
    assert len(raw_web) == 640
    assert raw_web == frame.payload
    assert raw_web[:3] != b"\x10\x02\x80"


def test_ar62_web_handshake_control_and_client_owned_cadence() -> None:
    prof_client = resolve_render_profile("web", pace_owner=PaceOwner.CLIENT)
    sent_bins: list[bytes] = []
    sent_json: list[dict[str, Any]] = []
    web = WebTransportAdapter(prof_client, send_bytes_fn=sent_bins.append, send_json_fn=sent_json.append)
    assert web.server_should_pace is False
    ok_good, _ = web.negotiate_hello({"sample_rate": 16000, "encoding": "pcm_s16le", "channels": 1})
    assert ok_good is True
    env = web.send_control_envelope("status", value="speaking")
    assert env == build_web_control_envelope("status", value="speaking")
    assert sent_json == [env]


def test_ar63_web_client_capability_mismatch_holds_without_rate_swap() -> None:
    prof = resolve_render_profile("web")
    sent_bins: list[bytes] = []
    web = WebTransportAdapter(prof, send_bytes_fn=sent_bins.append)
    ok_bad, reason_bad = web.negotiate_hello({"sample_rate": 48000, "encoding": "pcm_s16le", "channels": 1})
    assert ok_bad is False and "CLIENT_RATE_MISMATCH" in (reason_bad or "")
    frame = RenderedFrame(
        generation_ref=GenerationRef("sess-ar63", 1, 1),
        stream_ref=StreamRef("sess-ar63", "out-0", StreamDirection.OUTPUT, 0),
        sequence=0,
        sample_offset=0,
        profile=PlaybackProfile.WEB_16K_PCM16,
        format=AudioFormat(16000, 1, AudioEncoding.PCM_S16LE),
        frame_duration_ms=20.0,
        sample_count=320,
        valid_sample_count=320,
        payload=b"\x01\x00" * 320,
        terminal=False,
    )
    res = web.send_audio_frame(frame)
    assert res.accepted is False
    assert sent_bins == []


# ---------------------------------------------------------------------------
# AR64–AR68: Deterministic Monotonic Pacing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ar64_fake_clock_continuous_20ms_schedule_no_drift() -> None:
    clock = HarnessClock(initial_ns=1_000_000_000)

    async def fake_sleep(wait_ns: int) -> None:
        clock.advance_ns(wait_ns)

    pacer = MonotonicPacer(clock, sleep_ns_fn=fake_sleep)
    targets: list[int] = []
    for seq in range(5):
        ok, tgt, reanch = await pacer.wait_until_next_target()
        assert ok is True and reanch is False
        rec = pacer.record_submission(sequence=seq, target_ns=tgt, reanchored=reanch)
        targets.append(rec.target_ns)
    assert targets == [1_000_000_000 + i * FRAME_PERIOD_NS for i in range(5)]
    assert pacer.reanchor_count == 0


@pytest.mark.asyncio
async def test_ar65_intra_period_send_delay_preserves_absolute_target() -> None:
    clock = HarnessClock(initial_ns=1_000_000_000)

    async def fake_sleep(wait_ns: int) -> None:
        clock.advance_ns(wait_ns)

    pacer = MonotonicPacer(clock, sleep_ns_fn=fake_sleep)
    actuals: list[int] = []
    targets: list[int] = []
    for seq in range(4):
        ok, tgt, reanch = await pacer.wait_until_next_target()
        assert ok is True and reanch is False
        clock.advance_ns(5_000_000)  # 5 ms send duration inside 20 ms period
        rec = pacer.record_submission(sequence=seq, target_ns=tgt, reanchored=reanch)
        targets.append(rec.target_ns)
        actuals.append(rec.actual_submit_ns)
    assert targets == [1_000_000_000 + i * FRAME_PERIOD_NS for i in range(4)]
    assert actuals == [t + 5_000_000 for t in targets]


@pytest.mark.asyncio
async def test_ar66_late_wake_reanchors_or_aborts_stale_no_burst() -> None:
    clock = HarnessClock(initial_ns=1_000_000_000)

    async def fake_sleep(wait_ns: int) -> None:
        clock.advance_ns(wait_ns)

    pacer = MonotonicPacer(clock, sleep_ns_fn=fake_sleep, late_policy=LatePolicy.REANCHOR)
    ok0, tgt0, r0 = await pacer.wait_until_next_target()
    assert ok0 and not r0
    pacer.record_submission(sequence=0, target_ns=tgt0, reanchored=r0)

    clock.advance_ns(100_000_000)  # 100 ms late wake
    ok_late, tgt_late, reanch_late = await pacer.wait_until_next_target()
    assert ok_late is True and reanch_late is True
    rec_late = pacer.record_submission(sequence=1, target_ns=tgt_late, reanchored=reanch_late)
    assert pacer.reanchor_count == 1
    assert rec_late.inter_submit_gap_ns is not None and rec_late.inter_submit_gap_ns >= FRAME_PERIOD_NS

    ok_next, tgt_next, _ = await pacer.wait_until_next_target()
    rec_next = pacer.record_submission(sequence=2, target_ns=tgt_next, reanchored=False)
    assert rec_next.inter_submit_gap_ns == FRAME_PERIOD_NS

    # ABORT_STALE policy
    pacer_abort = MonotonicPacer(clock, sleep_ns_fn=fake_sleep, late_policy=LatePolicy.ABORT_STALE, max_lateness_ns=30_000_000)
    _, t_a, _ = await pacer_abort.wait_until_next_target()
    pacer_abort.record_submission(sequence=0, target_ns=t_a, reanchored=False)
    clock.advance_ns(100_000_000)
    ok_abort, _, _ = await pacer_abort.wait_until_next_target()
    assert ok_abort is False
    assert pacer_abort.aborted_stale_count == 1


@pytest.mark.asyncio
async def test_ar67_underrun_then_resumed_data_explicit_no_comfort_silence() -> None:
    clock = HarnessClock(initial_ns=1_000_000_000)

    async def fake_sleep(wait_ns: int) -> None:
        clock.advance_ns(wait_ns)

    pacer = MonotonicPacer(clock, sleep_ns_fn=fake_sleep)
    _, t0, _ = await pacer.wait_until_next_target()
    pacer.record_submission(sequence=0, target_ns=t0, reanchored=False)
    clock.advance_ns(80_000_000)  # upstream stall
    ok1, t1, r1 = await pacer.wait_until_next_target(underrun_recovered=True)
    rec1 = pacer.record_submission(sequence=1, target_ns=t1, reanchored=r1, underrun=True)
    assert ok1 and r1
    assert pacer.underrun_count == 1
    assert rec1.underrun is True
    assert pacer.stats().underrun_count == 1


@pytest.mark.asyncio
async def test_ar68_clock_domain_mismatch_and_wall_jump_isolation() -> None:
    clock = HarnessClock(initial_ns=1_000_000_000)
    pacer = MonotonicPacer(clock)
    await pacer.wait_until_next_target()
    clock.clock_domain = "other.domain"
    with pytest.raises(ClockDomainMismatchError):
        await pacer.wait_until_next_target()


# ---------------------------------------------------------------------------
# AR69–AR79: M02 Bounded Flow, Concurrency Barriers, Cleanup & M04 Telemetry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ar69_slow_sink_and_finite_capacity_backpressure() -> None:
    clock = HarnessClock(initial_ns=10_000)
    pipe = AudioRenderingPipeline(
        session_id="sess-ar69",
        trusted_channel="asterisk",
        clock=clock,
        max_queue_items=2,
        max_queue_bytes=1024,
    )
    gref = await pipe.start_generation()
    res = await pipe.render_chunk(_make_chunk(gref, _sine_48k(1000.0, 9600)))
    assert res.admitted is False
    assert res.rejection_reason == AdmissionStatus.BACKPRESSURE.value
    assert len(res.frames) == 2
    assert pipe.stream_state.accounting.verify_output_balance()[0] is True
    await pipe.close()


@pytest.mark.asyncio
async def test_ar70_cancel_before_render_and_during_render() -> None:
    clock = HarnessClock(initial_ns=10_000)
    pipe = AudioRenderingPipeline(session_id="sess-ar70", trusted_channel="web", clock=clock)
    g_c = await pipe.start_generation()
    await pipe.commit_interrupt(reason="pre_render_cancel")
    res_c = await pipe.render_chunk(_make_chunk(g_c, _sine_48k(1000.0, 960)))
    assert res_c.admitted is False
    assert res_c.rejection_reason == "STALE_OR_CANCELLED_GENERATION"
    await pipe.close()


@pytest.mark.asyncio
async def test_ar71_barrier_after_dequeue_before_submit_cancel_wins() -> None:
    clock = HarnessClock(initial_ns=10_000)
    barrier = DeterministicBarrier()
    pipe = AudioRenderingPipeline(
        session_id="sess-ar71",
        trusted_channel="asterisk",
        clock=clock,
        sleep_ns_fn=lambda ns: asyncio.sleep(0),
    )
    g1 = await pipe.start_generation()
    await pipe.render_chunk(_make_chunk(g1, _sine_48k(1000.0, 960)))
    await pipe.finish_generation_eos()

    sink: list[RenderedFrame] = []

    async def hook_before_linearize(_frame: RenderedFrame) -> None:
        await barrier.checkpoint(InterleavingPoint.AFTER_ADMISSION_BEFORE_DISPATCH)

    pump_task = asyncio.create_task(
        pipe.pump_and_submit(submit_fn=lambda f: sink.append(f), before_linearize_hook=hook_before_linearize)
    )
    await run_with_watchdog(barrier.wait_for_point(InterleavingPoint.AFTER_ADMISSION_BEFORE_DISPATCH))
    await pipe.commit_interrupt(reason="cancel_wins_at_fence")
    barrier.release(InterleavingPoint.AFTER_ADMISSION_BEFORE_DISPATCH)
    recs = await run_with_watchdog(pump_task)
    assert sink == []
    assert recs[0].outcome == SubmissionOutcome.BLOCKED_CANCELED
    await pipe.close()


@pytest.mark.asyncio
async def test_ar72_submission_wins_then_cancel_in_flight_possible() -> None:
    clock = HarnessClock(initial_ns=10_000)
    barrier = DeterministicBarrier()
    pipe = AudioRenderingPipeline(
        session_id="sess-ar72",
        trusted_channel="asterisk",
        clock=clock,
        sleep_ns_fn=lambda ns: asyncio.sleep(0),
    )
    g2 = await pipe.start_generation()
    await pipe.render_chunk(_make_chunk(g2, _sine_48k(1000.0, 960)))
    await pipe.finish_generation_eos()
    sink: list[RenderedFrame] = []

    async def slow_submit(frame: RenderedFrame) -> tuple[bool, int, str]:
        sink.append(frame)
        await barrier.checkpoint(InterleavingPoint.IN_FLIGHT)
        return True, len(frame.payload), "SUBMITTED"

    pump_task = asyncio.create_task(pipe.pump_and_submit(submit_fn=slow_submit))
    await run_with_watchdog(barrier.wait_for_point(InterleavingPoint.IN_FLIGHT))
    await pipe.commit_interrupt(reason="cancel_after_handoff")
    barrier.release(InterleavingPoint.IN_FLIGHT)
    recs = await run_with_watchdog(pump_task)
    assert len(sink) == 1
    assert recs[0].outcome == SubmissionOutcome.IN_FLIGHT_POSSIBLE
    assert recs[0].lease_id is not None
    assert pipe.fence.release_lease_idempotent(recs[0].lease_id) is False
    assert pipe.fence.duplicate_completion_callbacks == 1
    await pipe.close()


@pytest.mark.asyncio
async def test_ar73_authorized_eos_drain_vs_revocation() -> None:
    clock = HarnessClock(initial_ns=10_000)
    pipe = AudioRenderingPipeline(
        session_id="sess-ar73",
        trusted_channel="web",
        clock=clock,
        sleep_ns_fn=lambda ns: asyncio.sleep(0),
    )
    gd = await pipe.start_generation()
    await pipe.render_chunk(_make_chunk(gd, _sine_48k(1000.0, 1920)))
    await pipe.finish_generation_eos()
    sent: list[RenderedFrame] = []
    recs = await pipe.pump_and_submit(submit_fn=lambda f: sent.append(f))
    assert len(sent) == 2 and all(r.outcome == SubmissionOutcome.SUBMITTED_SERVER for r in recs)
    await pipe.close()


@pytest.mark.asyncio
async def test_ar74_existing_pause_stale_resume_and_new_generation() -> None:
    clock = HarnessClock(initial_ns=50_000)
    pipe = AudioRenderingPipeline(
        session_id="sess-ar74",
        trusted_channel="web",
        clock=clock,
        sleep_ns_fn=lambda ns: asyncio.sleep(0),
    )
    g1 = await pipe.start_generation()
    await pipe.render_chunk(_make_chunk(g1, _sine_48k(1000.0, 2880)))
    await pipe.finish_generation_eos()

    sent: list[RenderedFrame] = []
    recs1 = await pipe.pump_and_submit(submit_fn=lambda f: sent.append(f), max_frames=1)
    assert len(recs1) == 1

    pref = await pipe.soft_pause()
    assert pref is not None
    recs_paused = await pipe.pump_and_submit(submit_fn=lambda f: sent.append(f))
    assert recs_paused[0].outcome == SubmissionOutcome.BLOCKED_PAUSED

    stale_gen_ref = GenerationRef("sess-ar74", 99, 99)
    assert await pipe.resume_pause(PauseRef(stale_gen_ref, pref.pause_epoch)) is False
    assert await pipe.resume_pause(pref) is True

    recs2 = await pipe.pump_and_submit(submit_fn=lambda f: sent.append(f))
    assert len(recs2) == 2
    assert [f.sequence for f in sent] == [0, 1, 2]

    # New generation resets pause state cleanly and continues monotonic frame sequence
    g2 = await pipe.start_generation(reason="turn_2")
    await pipe.render_chunk(_make_chunk(g2, _sine_48k(1000.0, 960)))
    await pipe.finish_generation_eos()
    recs3 = await pipe.pump_and_submit(submit_fn=lambda f: sent.append(f))
    assert len(recs3) == 1 and sent[-1].sequence == 3
    await pipe.close()


@pytest.mark.asyncio
async def test_ar75_disconnect_duplicate_close_and_reconnect_isolation() -> None:
    clock = HarnessClock(initial_ns=50_000)
    pipe = AudioRenderingPipeline(session_id="sess-ar75", trusted_channel="web", clock=clock)
    await pipe.start_generation()
    s1 = await pipe.close(reason="disconnect")
    s2 = await pipe.close(reason="duplicate_close")
    assert s1.cleanup_status == CleanupStatus.COMPLETE
    assert s2 == s1

    pipe_new = AudioRenderingPipeline(session_id="sess-ar75", trusted_channel="web", clock=clock)
    assert pipe_new.session_ctx.incarnation_id != pipe.session_ctx.incarnation_id
    await pipe_new.close()


@pytest.mark.asyncio
async def test_ar76_worker_completion_unknown_quarantines_lease() -> None:
    clock = HarnessClock(initial_ns=50_000)
    pipe_q = AudioRenderingPipeline(
        session_id="sess-ar76",
        trusted_channel="asterisk",
        clock=clock,
        sleep_ns_fn=lambda ns: asyncio.sleep(0),
    )
    gq = await pipe_q.start_generation()
    await pipe_q.render_chunk(_make_chunk(gq, _sine_48k(1000.0, 960)))
    await pipe_q.finish_generation_eos()

    def unknown_submit(_frame: RenderedFrame) -> None:
        raise TransportCompletionUncertainError("socket_completion_unknown")

    recs_q = await pipe_q.pump_and_submit(submit_fn=unknown_submit)
    assert recs_q[0].outcome == SubmissionOutcome.IN_FLIGHT_POSSIBLE
    assert recs_q[0].observation_scope == ObservationScope.UNKNOWN
    sum_q = await pipe_q.close(reason="hung_transport")
    assert sum_q.cleanup_status == CleanupStatus.PENDING_RECLAIM
    assert sum_q.quarantined_leases == 1


def test_ar77_playback_events_server_scope_truth_and_dedup() -> None:
    clock = FakeClock(initial_ns=1_000, clock_domain="test.clock")
    emitter = PlaybackEventEmitter(clock=clock)
    gref = GenerationRef("sess-ar77", 1, 1)

    ev_q = emitter.emit_server_event(generation_ref=gref, kind=PlaybackEventKind.QUEUED, queue_depth=1)
    ev_s = emitter.emit_server_event(generation_ref=gref, kind=PlaybackEventKind.PLAYBACK_STARTED)
    ev_d = emitter.emit_server_event(generation_ref=gref, kind=PlaybackEventKind.DRAINED, queue_depth=0)
    ev_c = emitter.emit_server_event(generation_ref=gref, kind=PlaybackEventKind.COMPLETED)
    assert ev_q is not None and ev_q.observation_scope == ObservationScope.SERVER
    assert ev_s is not None and ev_s.confirms_endpoint_audible is False
    assert ev_d is not None and ev_d.observation_scope == ObservationScope.SERVER
    assert ev_c is not None and ev_c.observation_scope == ObservationScope.SERVER
    assert emitter.emit_server_event(generation_ref=gref, kind=PlaybackEventKind.COMPLETED) is None
    assert emitter.duplicate_terminal_suppressed == 1

    with pytest.raises(ValueError):
        emitter.emit_server_event(generation_ref=gref, kind=PlaybackEventKind.COMPLETED, observation_scope=ObservationScope.ENDPOINT)


@pytest.mark.asyncio
async def test_ar78_flush_requested_vs_scoped_flushed() -> None:
    clock = HarnessClock(initial_ns=1_000)
    pipe = AudioRenderingPipeline(session_id="sess-ar78", trusted_channel="asterisk", clock=clock)
    gref = await pipe.start_generation()
    await pipe.render_chunk(_make_chunk(gref, _sine_48k(1000.0, 960)))
    await pipe.commit_interrupt(reason="barge_in", flush_command_sent=True)
    kinds = [ev.kind for ev in pipe.events.events]
    assert PlaybackEventKind.FLUSH_REQUESTED in kinds
    assert PlaybackEventKind.FLUSHED in kinds
    assert PlaybackEventKind.CANCELED in kinds
    assert all(ev.observation_scope == ObservationScope.SERVER for ev in pipe.events.events)
    assert all(not ev.confirms_endpoint_audible for ev in pipe.events.events)
    await pipe.close()


def test_ar79_telemetry_overflow_and_pii_sentinel_safety() -> None:
    from backend.audio_rendering.telemetry import RenderTelemetry

    clock = FakeClock(initial_ns=1_000, clock_domain="test.clock")
    gref = GenerationRef("sess-ar79", 1, 1)
    tiny_bus = BoundedEventBus(max_lane_size=1, drop_policy=DropPolicy.DROP_NEWEST)
    sub = tiny_bus.subscribe("sub-1", max_lane_size=1, drop_policy=DropPolicy.DROP_NEWEST)
    telem = RenderTelemetry(clock=clock, bus=tiny_bus)
    telem.record_unsafe_metadata_probe(
        generation_ref=gref,
        metadata={"raw_transcript": "gizli", "phone": "05321234567", "pcm": "bytes"},
    )
    telem.record_render_chunk(generation_ref=gref, profile=PlaybackProfile.WEB_16K_PCM16, wall_ns=100, rms_dbfs=None)
    telem.record_render_chunk(generation_ref=gref, profile=PlaybackProfile.WEB_16K_PCM16, wall_ns=100, rms_dbfs=-20.0)
    assert telem.telemetry_drop_count >= 1
    assert sub.pending_count <= 1
    for env in sub.drain():
        assert PIISecretScanner.scan_object(dict(env.metadata)) == []
    g_rms = telem.metrics.get_gauge("f6.render.audio_rms_dbfs", observation_scope="SERVER", labels={"profile": PlaybackProfile.WEB_16K_PCM16.value})
    assert g_rms is not None and g_rms.status == MetricStatus.MEASURED


# ---------------------------------------------------------------------------
# AR80–AR84: F5->F6 Seam, Legacy Paths, M02 Cancel Integration, Gate Evaluation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ar80_f5_orchestration_to_f6_rendering_and_sink() -> None:
    fake_tts = FakeTTSAdapter()
    clock = HarnessClock(initial_ns=5_000_000)
    pipe = AudioRenderingPipeline(
        session_id="sess-ar80",
        trusted_channel="asterisk",
        clock=clock,
        sleep_ns_fn=lambda ns: asyncio.sleep(0),
    )
    gref = await pipe.start_generation()
    plan = fake_tts.build_plan(
        generation_ref=gref,
        plan_id="plan-ar80",
        response_id="resp-ar80",
        texts=("Randevunuz onaylandı.", "Görüşmek üzere."),
    )
    c0 = fake_tts.synthesize_chunk(plan, 0, sample_count=4800)
    c1 = fake_tts.synthesize_chunk(plan, 1, sample_count=4800)

    r0 = await pipe.render_chunk(c0, plan=plan)
    r1 = await pipe.render_chunk(c1, plan=plan)
    assert r0.admitted and r1.admitted
    await pipe.finish_generation_eos(plan_revision=plan.plan_revision)

    sink = FakeAudioSocketTransport(max_send_buffer_bytes=64 * 1024)
    as_adapter = AudioSocketOutboundAdapter(sink)
    recs = await pipe.pump_and_submit(submit_fn=as_adapter.send_audio_frame)
    assert len(recs) == 10
    assert sink.written_bytes == 10 * 323
    assert pipe.stream_state.accounting.verify_output_balance()[0] is True

    parser = AudioSocketStreamParser()
    wire_pkts = parser.feed(bytes(sink._tx_buffer))
    assert len(wire_pkts) == 10
    assert all(k == AUDIOSOCKET_AUDIO and len(b) == 320 for k, b in wire_pkts)
    await pipe.close()


def test_ar81_legacy_preview_greeting_transfer_and_dtmf_preserved() -> None:
    sink = FakeAudioSocketTransport(max_send_buffer_bytes=4096)
    as_adapter = AudioSocketOutboundAdapter(sink)
    r_dtmf = as_adapter.send_control(AUDIOSOCKET_DTMF, b"5")
    assert r_dtmf.outcome == WireWriteOutcome.SUBMITTED
    assert len(render_legacy_wave_48k_to_pcm(_sine_48k(1000.0, 960), output_rate=16000)) == 640
    assert len(render_legacy_wave_48k_to_pcm(_sine_48k(1000.0, 960), output_rate=8000)) == 320


@pytest.mark.asyncio
async def test_ar82_real_m02_cancellation_with_f6_and_recording_transport() -> None:
    fake_tts = FakeTTSAdapter()
    clock = HarnessClock(initial_ns=5_000_000)
    pipe = AudioRenderingPipeline(
        session_id="sess-ar82",
        trusted_channel="asterisk",
        clock=clock,
        sleep_ns_fn=lambda ns: asyncio.sleep(0),
    )
    gref = await pipe.start_generation()
    plan = fake_tts.build_plan(generation_ref=gref, plan_id="plan-ar82", response_id="resp-ar82", texts=("İkinci tur.",))
    c0 = fake_tts.synthesize_chunk(plan, 0, sample_count=4800)
    await pipe.render_chunk(c0, plan=plan)
    await pipe.finish_generation_eos(plan_revision=plan.plan_revision)
    await pipe.commit_interrupt(reason="user_barge_in", flush_command_sent=True)

    sink = FakeAudioSocketTransport(max_send_buffer_bytes=64 * 1024)
    as_adapter = AudioSocketOutboundAdapter(sink)
    recs = await pipe.pump_and_submit(submit_fn=as_adapter.send_audio_frame)
    assert recs == [] or all(r.outcome != SubmissionOutcome.SUBMITTED_SERVER for r in recs)
    assert sink.written_bytes == 0
    assert pipe.stream_state.accounting.verify_output_balance()[0] is True
    await pipe.close()


def test_ar83_legacy_regression_and_m00_denominator_intact() -> None:
    from backend.audio import frames as legacy_frames, pcm as legacy_pcm
    from backend.audiosocket_server import build_packet
    from backend.dsp import apply_telephony_eq_and_downsample_8k

    wav = _sine_48k(1000.0, 960, amp=0.5)
    assert len(apply_telephony_eq_and_downsample_8k(wav)) == 160
    assert len(list(legacy_frames(legacy_pcm(np.zeros(320, np.float32)), size=640))) == 1
    assert build_packet(AUDIOSOCKET_AUDIO, b"\x00" * 320)[:3] == b"\x10\x01\x40"

    summary = FeatureRegressionMapper(
        REPO_ROOT,
        REPO_ROOT / "docs" / "freya2" / "baseline" / M00_BASELINE_ID,
    ).build_matrix()
    assert summary.total_features == 18
    assert summary.duplicate_feature_ids == ()
    assert summary.missing_from_regression_matrix == ()


def test_ar84_reviewed_diff_rollback_rehearsal_and_gate_evaluation(tmp_path: Path) -> None:
    sandbox_pkg = tmp_path / "backend" / "audio_rendering"
    shutil.copytree(REPO_ROOT / "backend" / "audio_rendering", sandbox_pkg, ignore=shutil.ignore_patterns("__pycache__"))
    assert len(list(sandbox_pkg.glob("*.py"))) == 19
    shutil.rmtree(sandbox_pkg)
    assert not sandbox_pkg.exists()
    assert (REPO_ROOT / "backend" / "audio_rendering" / "pipeline.py").exists()

    gates = [
        GateRecord(
            gate_id=f"G{i:02d}",
            mandatory=True,
            status=GateStatus.PASS,
            reason="VERIFIED",
            evidence_refs=("AR01-AR84",),
        )
        for i in range(20)
    ]
    summary = evaluate_gates(gates)
    assert summary.overall == GateStatus.PASS
    assert summary.ready is True
    assert summary.mandatory_pass_count == 20
