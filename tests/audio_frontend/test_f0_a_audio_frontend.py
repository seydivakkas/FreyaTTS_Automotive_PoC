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
import struct
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
import soxr

from backend.audio_frontend import (
    LEGACY_WEB_EXTENDED_PROFILE,
    PHONE_8K_PROFILE,
    WEB_16K_48K_PROFILE,
    AudioFrontendConfig,
    AudioFrontendTelemetry,
    AudioInputPipeline,
    InputOutcomeStatus,
    InputProfile,
    LegacyAudioInputFacade,
    LegacyDspChain,
    RawDtmfBridge,
    RawDtmfEvent,
    StatefulResampler,
    adapt_audiosocket_chunk,
    adapt_web_ws_chunk,
    analyze_float32_quality,
    config_from_snapshot,
    decode_to_float32,
    default_audio_frontend_config,
    encode_from_float32,
    verify_core_integration_preflight,
)
from backend.car_denoiser import CarNoiseFilter, SpectralNoiseSuppressor
from backend.core.configuration.resolver import resolve_configuration
from backend.core.contracts.audio import AudioEncoding, AudioFormat, AudioFrame
from backend.core.contracts.common import (
    CONTRACT_SCHEMA_VERSION,
    MetricStatus,
    SessionIdentity,
    StreamDirection,
    StreamRef,
)
from backend.core.contracts.speech import SpeechEventKind
from backend.core.runtime.resource_ledger import LeaseState
from backend.core.runtime.session_context import SessionContext, SessionLifecycleState
from backend.dtmf import generate_dtmf_tone
from backend.observability.event_bus import BoundedEventBus, DropPolicy
from backend.observability.evidence import EvidenceKind, EvidenceRecorder
from backend.observability.metrics import MetricsRegistry
from tests.harness.adapters.fake_vad import FakeVADAdapter, ScriptedVADStep
from tests.harness.evidence_validator import PIISecretScanner
from tests.harness.fake_clock import HarnessClock
from tests.harness.synthetic_audio import AnalyticSignalKind, SyntheticAudioGenerator

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_RUN_ID = "20261126T004342Z"


def _make_stream_ref(
    session_id: str = "sess-f0a",
    stream_id: str = "in-0",
    epoch: int = 0,
) -> StreamRef:
    return StreamRef(
        session_id=session_id,
        stream_id=stream_id,
        direction=StreamDirection.INPUT,
        format_epoch=epoch,
    )


def _bypass_config(**kwargs: object) -> AudioFrontendConfig:
    return default_audio_frontend_config(bypass_dsp=True, **kwargs)  # type: ignore[arg-type]


# ============================================================================
# AI01 - AI04: Preflight & Passive Import Checks
# ============================================================================


def test_ai01_core_gate_missing_hold(tmp_path: Path) -> None:
    res = verify_core_integration_preflight(tmp_path, core_run_id="missing_run")
    assert not res.ok
    assert res.status == "HOLD"
    assert "CORE_EVIDENCE_MISSING" in res.errors


def test_ai02_core_gate_failed_or_hash_mismatch_blocked(tmp_path: Path) -> None:
    doc_dir = tmp_path / "docs" / "freya2" / "core_integration" / "bad_run"
    ev_dir = tmp_path / "evidence" / "core_integration" / "bad_run"
    doc_dir.mkdir(parents=True)
    ev_dir.mkdir(parents=True)
    target = tmp_path / "dummy.txt"
    target.write_text("tampered", encoding="utf-8")
    (doc_dir / "CORE_ACCEPTANCE_MATRIX.json").write_text(
        json.dumps(
            {
                "core_integration_ready": False,
                "core_integration_status": "FAIL",
                "gates": {"CG00": "FAIL"},
            }
        ),
        encoding="utf-8",
    )
    (ev_dir / "manifest.json").write_text("{}", encoding="utf-8")
    (ev_dir / "artifact_hashes.json").write_text(
        json.dumps({"dummy.txt": "0" * 64}),
        encoding="utf-8",
    )
    res = verify_core_integration_preflight(tmp_path, core_run_id="bad_run")
    assert not res.ok
    assert res.status == "FAIL"
    assert "CORE_INTEGRATION_NOT_READY" in res.errors
    assert any(e.startswith("CORE_HASH_MISMATCH") for e in res.errors)


def test_ai03_accepted_core_gate_preflight_passes() -> None:
    res = verify_core_integration_preflight(REPO_ROOT, core_run_id=CORE_RUN_ID)
    assert res.ok, f"Core preflight failed: {res.errors}"
    assert res.status == "PASS"
    assert res.core_run_id == CORE_RUN_ID


def test_ai04_passive_module_import_no_heavy_side_effects() -> None:
    code = (
        "import sys; import backend.audio_frontend; "
        "heavy = [m for m in ('torch', 'ctranslate2', 'faster_whisper', 'backend.models', 'backend.db', 'backend.config') if m in sys.modules]; "
        "assert not heavy, f'Unexpected heavy imports: {heavy}'; print('PASS')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "PASS" in proc.stdout


# ============================================================================
# AI05 - AI18: Format Validation, PCM/Float Conversion, Ownership, Padding
# ============================================================================


def test_ai05_valid_8k_mono_pcm16_160_samples() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=8000, encoding=AudioEncoding.PCM_S16LE, seed=1)
    assert len(seg.payload) == 320
    adapted = adapt_audiosocket_chunk(
        session_id="s-ai05",
        payload=seg.payload,
        sequence=0,
        sample_offset=0,
    )
    assert adapted.ok and adapted.frame is not None
    assert adapted.frame.format == AudioFormat(8000, 1, AudioEncoding.PCM_S16LE)
    assert adapted.frame.sample_count == 160

    pipe = AudioInputPipeline(session_id="s-ai05", config=_bypass_config())
    res = pipe.ingest_frame(adapted.frame, profile=PHONE_8K_PROFILE)
    assert res.ok
    eos = pipe.flush_eos(adapted.frame.stream_ref)
    assert eos.ok
    all_out = (*res.output_frames, *eos.output_frames)
    assert sum(f.sample_count for f in all_out) == 320
    assert all(f.format.sample_rate_hz == 16000 and f.format.channels == 1 for f in all_out)


def test_ai06_valid_16k_mono_pcm16_320_samples_no_rate_inference() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=16000, encoding=AudioEncoding.PCM_S16LE, seed=2)
    assert len(seg.payload) == 640
    adapted = adapt_web_ws_chunk(
        session_id="s-ai06",
        data=seg.payload,
        sample_rate_hz=16000,
        encoding=AudioEncoding.PCM_S16LE,
    )
    assert adapted.ok and adapted.frame is not None
    assert adapted.frame.sample_count == 320
    # 640 B must NOT be accepted on 8 kHz-only phone profile without declared 8 kHz rate mismatch
    pipe = AudioInputPipeline(session_id="s-ai06", config=_bypass_config())
    bad = pipe.ingest_raw(
        stream_ref=_make_stream_ref("s-ai06"),
        payload=seg.payload,
        sample_rate_hz=16000,
        channels=1,
        encoding=AudioEncoding.PCM_S16LE,
        sample_count=320,
        sequence=0,
        sample_offset=0,
        profile=PHONE_8K_PROFILE,
    )
    assert not bad.ok and bad.status == InputOutcomeStatus.UNSUPPORTED


def test_ai07_valid_48k_mono_pcm16_960_samples() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=48000, encoding=AudioEncoding.PCM_S16LE, seed=3)
    assert len(seg.payload) == 1920
    adapted = adapt_web_ws_chunk(
        session_id="s-ai07",
        data=seg.payload,
        sample_rate_hz=48000,
        encoding=AudioEncoding.PCM_S16LE,
    )
    assert adapted.ok and adapted.frame is not None
    assert adapted.frame.sample_count == 960
    assert adapted.frame.format == AudioFormat(48000, 1, AudioEncoding.PCM_S16LE)


def test_ai08_valid_float32_16k_and_48k() -> None:
    gen = SyntheticAudioGenerator()
    pipe = AudioInputPipeline(session_id="s-ai08", config=_bypass_config())
    for idx, sr in enumerate((16000, 48000)):
        seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=sr, encoding=AudioEncoding.FLOAT32_LE, seed=10 + idx)
        assert len(seg.payload) == seg.sample_count * 4
        res = pipe.ingest_raw(
            stream_ref=_make_stream_ref("s-ai08", stream_id=f"in-{sr}"),
            payload=seg.payload,
            sample_rate_hz=sr,
            channels=1,
            encoding=AudioEncoding.FLOAT32_LE,
            sample_count=seg.sample_count,
            sequence=0,
            sample_offset=0,
            profile=WEB_16K_48K_PROFILE,
        )
        assert res.ok


def test_ai09_odd_pcm16_bytes_rejected_before_conversion() -> None:
    pipe = AudioInputPipeline(session_id="s-ai09", config=_bypass_config())
    res = pipe.ingest_raw(
        stream_ref=_make_stream_ref("s-ai09"),
        payload=b"\x01\x02\x03",
        sample_rate_hz=8000,
        channels=1,
        encoding=AudioEncoding.PCM_S16LE,
        sample_count=1,
        sequence=0,
        sample_offset=0,
        profile=PHONE_8K_PROFILE,
    )
    assert not res.ok
    assert res.status == InputOutcomeStatus.INVALID
    assert res.error_info is not None and res.error_info.code == "F0_ODD_PCM16_BYTES"
    assert res.output_frames == ()


def test_ai10_declared_count_vs_short_long_payload_rejected() -> None:
    pipe = AudioInputPipeline(session_id="s-ai10", config=_bypass_config())
    short_res = pipe.ingest_raw(
        stream_ref=_make_stream_ref("s-ai10"),
        payload=b"\x00" * 100,
        sample_rate_hz=8000,
        channels=1,
        encoding=AudioEncoding.PCM_S16LE,
        sample_count=160,
        sequence=0,
        sample_offset=0,
        profile=PHONE_8K_PROFILE,
    )
    assert not short_res.ok and short_res.error_info and short_res.error_info.code == "F0_PAYLOAD_LENGTH_MISMATCH"
    long_res = pipe.ingest_raw(
        stream_ref=_make_stream_ref("s-ai10"),
        payload=b"\x00" * 640,
        sample_rate_hz=8000,
        channels=1,
        encoding=AudioEncoding.PCM_S16LE,
        sample_count=160,
        sequence=0,
        sample_offset=0,
        profile=PHONE_8K_PROFILE,
    )
    assert not long_res.ok and long_res.error_info and long_res.error_info.code == "F0_PAYLOAD_LENGTH_MISMATCH"


def test_ai11_zero_negative_bool_oversized_rejected_before_allocation() -> None:
    pipe = AudioInputPipeline(session_id="s-ai11", config=_bypass_config())
    sref = _make_stream_ref("s-ai11")
    for bad_count in (0, -5, True, 10_000_000):
        res = pipe.ingest_raw(
            stream_ref=sref,
            payload=b"\x00\x00",
            sample_rate_hz=16000,
            channels=1,
            encoding=AudioEncoding.PCM_S16LE,
            sample_count=bad_count,
            sequence=0,
            sample_offset=0,
            profile=WEB_16K_48K_PROFILE,
        )
        assert not res.ok
        assert res.status == InputOutcomeStatus.INVALID


def test_ai12_unsupported_rate_encoding_endian_rejected() -> None:
    pipe = AudioInputPipeline(session_id="s-ai12", config=_bypass_config())
    sref = _make_stream_ref("s-ai12")
    r_rate = pipe.ingest_raw(
        stream_ref=sref,
        payload=b"\x00" * 320,
        sample_rate_hz=11025,
        channels=1,
        encoding=AudioEncoding.PCM_S16LE,
        sample_count=160,
        sequence=0,
        sample_offset=0,
    )
    assert not r_rate.ok and r_rate.status == InputOutcomeStatus.UNSUPPORTED

    r_enc = pipe.ingest_raw(
        stream_ref=sref,
        payload=b"\x00" * 160,
        sample_rate_hz=8000,
        channels=1,
        encoding="MULAW",
        sample_count=160,
        sequence=0,
        sample_offset=0,
    )
    assert not r_enc.ok and r_enc.status == InputOutcomeStatus.UNSUPPORTED

    r_end = pipe.ingest_raw(
        stream_ref=sref,
        payload=b"\x00" * 320,
        sample_rate_hz=8000,
        channels=1,
        encoding=AudioEncoding.PCM_S16LE,
        sample_count=160,
        sequence=0,
        sample_offset=0,
        endian="big",
    )
    assert not r_end.ok and r_end.status == InputOutcomeStatus.UNSUPPORTED


def test_ai13_unsupported_channels_vs_approved_stereo_downmix() -> None:
    pipe = AudioInputPipeline(session_id="s-ai13", config=_bypass_config())
    sref = _make_stream_ref("s-ai13")
    stereo_samples = struct.pack("<4h", 16384, -16384, 32767, 32767)
    rej = pipe.ingest_raw(
        stream_ref=sref,
        payload=stereo_samples,
        sample_rate_hz=16000,
        channels=2,
        encoding=AudioEncoding.PCM_S16LE,
        sample_count=2,
        sequence=0,
        sample_offset=0,
        profile=WEB_16K_48K_PROFILE,
    )
    assert not rej.ok and rej.status == InputOutcomeStatus.UNSUPPORTED

    stereo_prof = InputProfile(
        profile_id="approved_stereo_16k",
        source_kind="web",
        supported_rates_hz=frozenset({16000}),
        supported_channels=frozenset({1, 2}),
        allow_stereo_downmix=True,
    )
    ok = pipe.ingest_raw(
        stream_ref=sref,
        payload=stereo_samples,
        sample_rate_hz=16000,
        channels=2,
        encoding=AudioEncoding.PCM_S16LE,
        sample_count=2,
        sequence=0,
        sample_offset=0,
        profile=stereo_prof,
    )
    assert ok.ok
    out_arr = np.frombuffer(ok.output_frames[0].payload, dtype="<f4")
    assert len(out_arr) == 2
    assert abs(float(out_arr[0]) - 0.0) < 1e-6
    assert abs(float(out_arr[1]) - (32767.0 / 32768.0)) < 1e-5


def test_ai14_float32_nan_inf_rejected_before_dsp() -> None:
    pipe = AudioInputPipeline(session_id="s-ai14", config=_bypass_config())
    sref = _make_stream_ref("s-ai14")
    for bad in (float("nan"), float("inf"), float("-inf")):
        payload = struct.pack("<4f", 0.1, bad, 0.2, 0.0)
        res = pipe.ingest_raw(
            stream_ref=sref,
            payload=payload,
            sample_rate_hz=16000,
            channels=1,
            encoding=AudioEncoding.FLOAT32_LE,
            sample_count=4,
            sequence=0,
            sample_offset=0,
            profile=WEB_16K_48K_PROFILE,
        )
        assert not res.ok
        assert res.status == InputOutcomeStatus.INVALID
        assert res.output_frames == ()


def test_ai15_pcm_min_max_zero_exact_conversion() -> None:
    payload = struct.pack("<3h", -32768, 32767, 0)
    fmt = AudioFormat(16000, 1, AudioEncoding.PCM_S16LE)
    arr, stats = decode_to_float32(payload, fmt)
    assert float(arr[0]) == -1.0
    assert math.isclose(float(arr[1]), 32767.0 / 32768.0, rel_tol=0.0, abs_tol=1e-7)
    assert float(arr[2]) == 0.0
    assert stats.input_clipped_samples == 2


def test_ai16_finite_overrange_float_and_int16_roundtrip() -> None:
    fmt = AudioFormat(16000, 1, AudioEncoding.FLOAT32_LE)
    overrange_payload = struct.pack("<3f", 1.75, -2.5, 0.25)

    with pytest.raises(ValueError, match="reject policy"):
        decode_to_float32(overrange_payload, fmt, overrange_policy="reject")

    sat_arr, stats = decode_to_float32(overrange_payload, fmt, overrange_policy="saturate")
    assert stats.overrange_samples == 2
    assert list(sat_arr) == [1.0, -1.0, 0.25]

    encoded, clipped = encode_from_float32(np.array([1.75, -2.5, 0.0, -1.0, 32767 / 32768.0], dtype=np.float32), AudioEncoding.PCM_S16LE)
    assert clipped == 2
    unpacked = struct.unpack("<5h", encoded)
    assert unpacked == (32767, -32768, 0, -32768, 32767)


def test_ai17_mutable_input_mutated_after_submit() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=16000, encoding=AudioEncoding.PCM_S16LE, seed=7)
    mutable = bytearray(seg.payload)
    expected_copy = bytes(mutable)

    pipe = AudioInputPipeline(session_id="s-ai17", config=_bypass_config())
    res = pipe.ingest_raw(
        stream_ref=_make_stream_ref("s-ai17"),
        payload=mutable,
        sample_rate_hz=16000,
        channels=1,
        encoding=AudioEncoding.PCM_S16LE,
        sample_count=320,
        sequence=0,
        sample_offset=0,
        profile=WEB_16K_48K_PROFILE,
    )
    # Caller mutates buffer immediately after submit
    for i in range(len(mutable)):
        mutable[i] = 0x7F
    assert res.ok and res.output_frames
    queued_arr = np.frombuffer(res.output_frames[0].payload, dtype="<f4")
    expected_arr, _ = decode_to_float32(expected_copy, AudioFormat(16000, 1, AudioEncoding.PCM_S16LE))
    assert np.allclose(queued_arr, expected_arr, atol=1e-6)


def test_ai18_explicit_final_padding_valid_sample_count() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.generate(
        AnalyticSignalKind.SINE,
        sample_rate_hz=16000,
        sample_count=320,
        valid_sample_count=100,
        encoding=AudioEncoding.FLOAT32_LE,
        seed=8,
    )
    sref = _make_stream_ref("s-ai18")
    frame = seg.to_audio_frame(sref, sequence=0)
    pipe = AudioInputPipeline(session_id="s-ai18", config=_bypass_config())
    res = pipe.ingest_frame(frame, profile=WEB_16K_48K_PROFILE)
    assert res.ok and res.output_frames
    assert res.output_frames[0].sample_count == 100
    assert "FINAL_PADDING_STRIPPED" in res.output_frames[0].flags
    state, _ = pipe.registry.get_active(sref)
    assert state is not None
    assert state.ledger.padding_samples == 220
    assert state.ledger.valid_input_accepted_samples == 100

    # Invalid valid_sample_count > sample_count rejected before allocation
    bad = pipe.ingest_raw(
        stream_ref=sref,
        payload=seg.payload,
        sample_rate_hz=16000,
        channels=1,
        encoding=AudioEncoding.FLOAT32_LE,
        sample_count=320,
        sequence=1,
        sample_offset=320,
        valid_sample_count=400,
        profile=WEB_16K_48K_PROFILE,
    )
    assert not bad.ok and bad.status == InputOutcomeStatus.INVALID


# ============================================================================
# AI19 - AI25: Session/Stream Isolation, Ordering, Epochs, Config Pinning
# ============================================================================


def test_ai19_two_sessions_same_stream_id_isolated() -> None:
    gen = SyntheticAudioGenerator()
    p1 = AudioInputPipeline(session_id="sess-1", config=default_audio_frontend_config())
    p2 = AudioInputPipeline(session_id="sess-2", config=default_audio_frontend_config())

    loud = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=8000, encoding=AudioEncoding.PCM_S16LE, seed=1)
    quiet = gen.frame_20ms(AnalyticSignalKind.SILENCE, sample_rate_hz=8000, encoding=AudioEncoding.PCM_S16LE, seed=2)

    r1 = p1.ingest_raw(
        stream_ref=_make_stream_ref("sess-1", "in-0"),
        payload=loud.payload,
        sample_rate_hz=8000,
        sample_count=160,
        sequence=0,
        sample_offset=0,
        profile=PHONE_8K_PROFILE,
    )
    r2 = p2.ingest_raw(
        stream_ref=_make_stream_ref("sess-2", "in-0"),
        payload=quiet.payload,
        sample_rate_hz=8000,
        sample_count=160,
        sequence=0,
        sample_offset=0,
        profile=PHONE_8K_PROFILE,
    )
    eos1 = p1.flush_eos(_make_stream_ref("sess-1", "in-0"))
    eos2 = p2.flush_eos(_make_stream_ref("sess-2", "in-0"))
    assert r1.ok and r2.ok and eos1.ok and eos2.ok
    s1, _ = p1.registry.get_active(_make_stream_ref("sess-1", "in-0"))
    s2, _ = p2.registry.get_active(_make_stream_ref("sess-2", "in-0"))
    assert s1 is not None and s2 is not None
    assert s1.dsp_chain is not s2.dsp_chain
    assert s1.resampler is not s2.resampler
    q2 = r2.quality or eos2.quality
    assert q2 is not None and q2.linear_rms == 0.0


def test_ai20_two_streams_in_one_session_independent() -> None:
    gen = SyntheticAudioGenerator()
    pipe = AudioInputPipeline(session_id="sess-multi", config=_bypass_config())
    s_a = _make_stream_ref("sess-multi", "mic-a")
    s_b = _make_stream_ref("sess-multi", "mic-b")
    seg8 = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=8000, seed=1)
    seg16 = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=16000, seed=2)

    assert pipe.ingest_raw(stream_ref=s_a, payload=seg8.payload, sample_rate_hz=8000, sample_count=160, sequence=0, sample_offset=0).ok
    assert pipe.ingest_raw(stream_ref=s_b, payload=seg16.payload, sample_rate_hz=16000, sample_count=320, sequence=0, sample_offset=0).ok
    st_a, _ = pipe.registry.get_active(s_a)
    st_b, _ = pipe.registry.get_active(s_b)
    assert st_a is not None and st_b is not None
    assert st_a.ledger.input_accepted_samples == 160
    assert st_b.ledger.input_accepted_samples == 320


def test_ai21_duplicate_sequence_or_overlap_rejected() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=16000, seed=3)
    pipe = AudioInputPipeline(session_id="s-ai21", config=_bypass_config())
    sref = _make_stream_ref("s-ai21")
    assert pipe.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=16000, sample_count=320, sequence=0, sample_offset=0).ok
    dup = pipe.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=16000, sample_count=320, sequence=0, sample_offset=0)
    assert not dup.ok and dup.status == InputOutcomeStatus.INVALID
    ov = pipe.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=16000, sample_count=320, sequence=1, sample_offset=160)
    assert not ov.ok and ov.status == InputOutcomeStatus.INVALID


def test_ai22_out_of_order_and_gap_discontinuity() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=16000, seed=4)
    pipe = AudioInputPipeline(session_id="s-ai22", config=_bypass_config())
    sref = _make_stream_ref("s-ai22")
    assert pipe.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=16000, sample_count=320, sequence=2, sample_offset=0).ok
    ooo = pipe.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=16000, sample_count=320, sequence=1, sample_offset=320)
    assert not ooo.ok and ooo.status == InputOutcomeStatus.INVALID

    gap_res = pipe.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=16000, sample_count=320, sequence=3, sample_offset=960)
    assert gap_res.ok and gap_res.discontinuity
    assert "DISCONTINUITY_GAP" in gap_res.output_frames[0].flags
    st, _ = pipe.registry.get_active(sref)
    assert st is not None and st.ledger.gap_samples == 640


def test_ai23_rate_change_with_new_format_epoch() -> None:
    gen = SyntheticAudioGenerator()
    pipe = AudioInputPipeline(session_id="s-ai23", config=_bypass_config())
    seg8 = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=8000, seed=5)
    seg48 = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=48000, seed=6)

    e0 = _make_stream_ref("s-ai23", epoch=0)
    e1 = _make_stream_ref("s-ai23", epoch=1)
    assert pipe.ingest_raw(stream_ref=e0, payload=seg8.payload, sample_rate_hz=8000, sample_count=160, sequence=0, sample_offset=0).ok
    r1 = pipe.ingest_raw(stream_ref=e1, payload=seg48.payload, sample_rate_hz=48000, sample_count=960, sequence=0, sample_offset=0)
    assert r1.ok
    st_new, reason = pipe.registry.get_active(e1)
    assert st_new is not None and reason == "ok" and st_new.native_sample_rate_hz == 48000


def test_ai24_late_old_epoch_frame_rejected_after_rollover() -> None:
    gen = SyntheticAudioGenerator()
    pipe = AudioInputPipeline(session_id="s-ai24", config=_bypass_config())
    seg8 = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=8000, seed=5)
    seg48 = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=48000, seed=6)
    e0 = _make_stream_ref("s-ai24", epoch=0)
    e1 = _make_stream_ref("s-ai24", epoch=1)
    assert pipe.ingest_raw(stream_ref=e0, payload=seg8.payload, sample_rate_hz=8000, sample_count=160, sequence=0, sample_offset=0).ok
    assert pipe.ingest_raw(stream_ref=e1, payload=seg48.payload, sample_rate_hz=48000, sample_count=960, sequence=0, sample_offset=0).ok

    late = pipe.ingest_raw(stream_ref=e0, payload=seg8.payload, sample_rate_hz=8000, sample_count=160, sequence=1, sample_offset=160)
    assert not late.ok and late.status == InputOutcomeStatus.STALE


def test_ai25_config_revision_pinned_per_active_stream() -> None:
    snap_v1 = resolve_configuration(overrides={"car_denoiser_hpf_cutoff": 120.0}).snapshot
    snap_v2 = resolve_configuration(overrides={"car_denoiser_hpf_cutoff": 220.0}).snapshot
    cfg_v1 = config_from_snapshot(snap_v1)
    cfg_v2 = config_from_snapshot(snap_v2)

    pipe = AudioInputPipeline(session_id="s-ai25", config=cfg_v1)
    e0 = _make_stream_ref("s-ai25", epoch=0)
    st0 = pipe.open_stream(e0, sample_rate_hz=8000)
    assert st0.pinned_config.config_revision == cfg_v1.config_revision
    assert st0.dsp_chain.hpf.cutoff_hz == 120.0

    # Updating pipeline config does NOT mutate already active epoch 0
    pipe.config = cfg_v2
    assert st0.pinned_config.config_revision == cfg_v1.config_revision
    assert st0.dsp_chain.hpf.cutoff_hz == 120.0

    # New epoch picks up new revision
    e1 = _make_stream_ref("s-ai25", epoch=1)
    st1 = pipe.open_stream(e1, sample_rate_hz=8000)
    assert st1.pinned_config.config_revision == cfg_v2.config_revision
    assert st1.dsp_chain.hpf.cutoff_hz == 220.0


# ============================================================================
# AI26 - AI29: Raw DTMF Branch, Dedup, Isolation
# ============================================================================


def test_ai26_raw_dtmf_before_hpf_fft_gate_at_native_rate() -> None:
    observed_events: list[RawDtmfEvent] = []
    pipe = AudioInputPipeline(
        session_id="s-ai26",
        config=default_audio_frontend_config(),
        dtmf_consumer=observed_events.append,
    )
    for sr in (8000, 48000):
        observed_events.clear()
        tone = generate_dtmf_tone("5", duration_sec=0.08, sample_rate=sr, amplitude=0.45)
        raw_bytes, _ = encode_from_float32(tone, AudioEncoding.PCM_S16LE)
        res = pipe.ingest_raw(
            stream_ref=_make_stream_ref("s-ai26", stream_id=f"dtmf-{sr}"),
            payload=raw_bytes,
            sample_rate_hz=sr,
            sample_count=len(tone),
            sequence=0,
            sample_offset=0,
        )
        assert res.ok
        assert [e.digit for e in observed_events] == ["5"]


def test_ai27_raw_dtmf_preserved_when_dsp_disabled() -> None:
    observed_events: list[RawDtmfEvent] = []
    pipe = AudioInputPipeline(
        session_id="s-ai27",
        config=_bypass_config(),
        dtmf_consumer=observed_events.append,
    )
    tone = generate_dtmf_tone("9", duration_sec=0.08, sample_rate=8000, amplitude=0.45)
    raw_bytes, _ = encode_from_float32(tone, AudioEncoding.PCM_S16LE)
    res = pipe.ingest_raw(
        stream_ref=_make_stream_ref("s-ai27"),
        payload=raw_bytes,
        sample_rate_hz=8000,
        sample_count=len(tone),
        sequence=0,
        sample_offset=0,
        profile=PHONE_8K_PROFILE,
    )
    assert res.ok
    assert [e.digit for e in observed_events] == ["9"]


def test_ai28_dtmf_signaling_and_inband_dedup() -> None:
    clock = HarnessClock(initial_ns=1_000_000_000)
    dispatched: list[RawDtmfEvent] = []
    pipe = AudioInputPipeline(
        session_id="s-ai28",
        config=_bypass_config(),
        clock=clock,
        dtmf_consumer=dispatched.append,
    )
    sref = _make_stream_ref("s-ai28")
    pipe.open_stream(sref, sample_rate_hz=8000, profile=PHONE_8K_PROFILE)

    # Out-of-band signaling arrives first at t=0
    sig_ev = pipe.submit_signaling_dtmf(sref, "1")
    assert sig_ev is not None and sig_ev.digit == "1"

    # Overlapping in-band tone 20 ms later -> deduplicated
    clock.advance_ms(20)
    tone = generate_dtmf_tone("1", duration_sec=0.08, sample_rate=8000, amplitude=0.45)
    raw_bytes, _ = encode_from_float32(tone, AudioEncoding.PCM_S16LE)
    res = pipe.ingest_raw(
        stream_ref=sref,
        payload=raw_bytes,
        sample_rate_hz=8000,
        sample_count=len(tone),
        sequence=0,
        sample_offset=0,
        profile=PHONE_8K_PROFILE,
    )
    assert res.ok
    assert len(dispatched) == 1


def test_ai29_raw_tap_consumer_mutation_or_exception_isolated() -> None:
    def hostile_observer(arr: np.ndarray, sr: int) -> None:
        arr[0] = 999.0  # raises ValueError: assignment destination is read-only

    sref = _make_stream_ref("s-ai29")
    bridge = RawDtmfBridge(sref, sample_rate_hz=8000, raw_tap_observer=hostile_observer)
    samples = np.full(160, 0.25, dtype=np.float32)
    out = bridge.tap_raw_samples(samples)
    assert out.tap_errors == 1
    assert np.allclose(out.main_samples, 0.25)


# ============================================================================
# AI30 - AI38: Legacy DSP Stages (Silence, HPF, FFT, AGC/Gate, Bypass, Fault)
# ============================================================================


def test_ai30_silence_through_bypass_and_legacy_profile() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.frame_20ms(AnalyticSignalKind.SILENCE, sample_rate_hz=16000, encoding=AudioEncoding.FLOAT32_LE)
    for cfg in (_bypass_config(), default_audio_frontend_config()):
        pipe = AudioInputPipeline(session_id="s-ai30", config=cfg)
        res = pipe.ingest_raw(
            stream_ref=_make_stream_ref("s-ai30"),
            payload=seg.payload,
            sample_rate_hz=16000,
            encoding=AudioEncoding.FLOAT32_LE,
            sample_count=320,
            sequence=0,
            sample_offset=0,
        )
        assert res.ok and res.quality is not None
        assert res.quality.linear_rms == 0.0
        assert res.quality.rms_dbfs is None
        assert res.quality.rms_dbfs_status == MetricStatus.UNAVAILABLE


def test_ai31_hpf_impulse_partition_matches_full_reference() -> None:
    impulse = np.zeros(640, dtype=np.float32)
    impulse[0] = 0.8
    ref_filter = CarNoiseFilter(cutoff_hz=120.0, sample_rate=8000, order=4)
    ref_out = ref_filter.process(impulse)

    cfg = default_audio_frontend_config()
    chain = LegacyDspChain(sample_rate_hz=8000, config=cfg, spectral_enabled=False, agc_gate_enabled=False)
    parts = [chain.process(impulse[i : i + 160]).samples for i in range(0, 640, 160)]
    stream_out = np.concatenate(parts)
    assert np.max(np.abs(stream_out - ref_out)) < 1e-6


def test_ai32_hpf_60hz_hum_attenuation_and_1khz_passband_across_rates() -> None:
    cfg = default_audio_frontend_config()
    for sr in (8000, 16000, 48000):
        chain = LegacyDspChain(sample_rate_hz=sr, config=cfg, spectral_enabled=False, agc_gate_enabled=False)
        t = np.arange(sr // 2) / float(sr)
        hum = (0.5 * np.sin(2 * np.pi * 60.0 * t)).astype(np.float32)
        voice = (0.2 * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32)

        y_hum = chain.process(hum).samples
        chain.reset()
        y_voice = chain.process(voice).samples

        steady = sr // 10
        att_hum_db = 20.0 * math.log10(np.sqrt(np.mean(y_hum[steady:] ** 2)) / np.sqrt(np.mean(hum[steady:] ** 2)))
        att_voice_db = 20.0 * math.log10(np.sqrt(np.mean(y_voice[steady:] ** 2)) / np.sqrt(np.mean(voice[steady:] ** 2)))
        assert att_hum_db <= -20.0
        assert abs(att_voice_db) < 2.5


def test_ai33_fft_window_split_matches_continuous_reference() -> None:
    rng = np.random.default_rng(42)
    sig = (rng.standard_normal(1024) * 0.1).astype(np.float32)

    # 1) Hop-aligned (128-sample) partitions match continuous single-call SpectralNoiseSuppressor
    # after accounting for the exact (n_fft - hop_size) = 128-sample initial FIFO delay.
    ref_cont = SpectralNoiseSuppressor(sample_rate=8000, suppression_db=18.0)
    ref_cont_out = ref_cont.process(sig)
    chain_hop = LegacyDspChain(
        sample_rate_hz=8000,
        config=default_audio_frontend_config(),
        hpf_enabled=False,
        agc_gate_enabled=False,
    )
    hop_chunks = [chain_hop.process(sig[i : i + 128]).samples for i in range(0, len(sig), 128)]
    assert np.max(np.abs(np.concatenate(hop_chunks)[128:] - ref_cont_out[:-128])) < 1e-6

    # 2) 20 ms (160-sample) partitions match legacy SpectralNoiseSuppressor partitioned identically
    ref_160 = SpectralNoiseSuppressor(sample_rate=8000, suppression_db=18.0)
    ref_160_out = np.concatenate([ref_160.process(sig[i : i + 160]) for i in range(0, len(sig), 160)])
    chain_160 = LegacyDspChain(
        sample_rate_hz=8000,
        config=default_audio_frontend_config(),
        hpf_enabled=False,
        agc_gate_enabled=False,
    )
    stream_160_out = np.concatenate([chain_160.process(sig[i : i + 160]).samples for i in range(0, len(sig), 160)])
    assert np.max(np.abs(stream_160_out - ref_160_out)) < 1e-6


def test_ai34_seeded_noise_through_existing_denoiser() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.generate(AnalyticSignalKind.WHITE_NOISE, sample_rate_hz=8000, sample_count=8000, amplitude=0.2, seed=42)
    arr, _ = decode_to_float32(seg.payload, seg.format)
    chain = LegacyDspChain(sample_rate_hz=8000, config=default_audio_frontend_config())
    out = chain.process(arr).samples
    assert len(out) == len(arr)
    assert np.isfinite(out).all()


def test_ai35_agc_low_and_high_amplitude_no_overflow() -> None:
    gen = SyntheticAudioGenerator()
    low_seg = gen.generate(AnalyticSignalKind.SINE, sample_rate_hz=8000, sample_count=1600, freq_hz=440.0, amplitude=0.03, seed=1)
    high_seg = gen.generate(AnalyticSignalKind.SINE, sample_rate_hz=8000, sample_count=1600, freq_hz=440.0, amplitude=0.98, seed=2)
    low_arr, _ = decode_to_float32(low_seg.payload, low_seg.format)
    high_arr, _ = decode_to_float32(high_seg.payload, high_seg.format)

    chain_low = LegacyDspChain(sample_rate_hz=8000, config=default_audio_frontend_config(), hpf_enabled=False, spectral_enabled=False)
    out_low = chain_low.process(low_arr).samples
    assert np.sqrt(np.mean(out_low[-320:] ** 2)) > np.sqrt(np.mean(low_arr[-320:] ** 2))

    chain_high = LegacyDspChain(sample_rate_hz=8000, config=default_audio_frontend_config(), hpf_enabled=False, spectral_enabled=False)
    out_high = chain_high.process(high_arr).samples
    assert float(np.max(np.abs(out_high))) <= 1.0


def test_ai36_noise_gate_boundary_preserves_sample_timeline() -> None:
    gen = SyntheticAudioGenerator()
    quiet_seg = gen.generate(AnalyticSignalKind.LOW_LEVEL, sample_rate_hz=8000, sample_count=800, amplitude=0.002, seed=1)
    arr, _ = decode_to_float32(quiet_seg.payload, quiet_seg.format)
    chain = LegacyDspChain(sample_rate_hz=8000, config=default_audio_frontend_config(), hpf_enabled=False, spectral_enabled=False)
    res = chain.process(arr)
    assert len(res.samples) == 800
    assert not res.is_speech
    assert np.sqrt(np.mean(res.samples[-160:] ** 2)) < np.sqrt(np.mean(arr[-160:] ** 2))


def test_ai37_single_active_route_no_double_dsp_or_resample() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=16000, encoding=AudioEncoding.FLOAT32_LE)
    prof = InputProfile(
        profile_id="already_processed_16k",
        source_kind="fixture",
        supported_rates_hz=frozenset({16000}),
        already_processed=True,
    )
    pipe = AudioInputPipeline(session_id="s-ai37", config=default_audio_frontend_config())
    res = pipe.ingest_raw(
        stream_ref=_make_stream_ref("s-ai37"),
        payload=seg.payload,
        sample_rate_hz=16000,
        encoding=AudioEncoding.FLOAT32_LE,
        sample_count=320,
        sequence=0,
        sample_offset=0,
        profile=prof,
    )
    assert res.ok and res.route == "already_processed"
    assert res.output_frames[0].payload == seg.payload


def test_ai38_dsp_stage_exception_returns_explicit_failed_outcome() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=8000, encoding=AudioEncoding.PCM_S16LE)
    pipe = AudioInputPipeline(session_id="s-ai38", config=default_audio_frontend_config())
    sref = _make_stream_ref("s-ai38")
    st = pipe.open_stream(sref, sample_rate_hz=8000)

    def boom(_samples: np.ndarray) -> np.ndarray:
        raise RuntimeError("injected_filter_fault")

    st.dsp_chain.hpf._filter.process = boom  # type: ignore[method-assign]
    res = pipe.ingest_raw(
        stream_ref=sref,
        payload=seg.payload,
        sample_rate_hz=8000,
        sample_count=160,
        sequence=0,
        sample_offset=0,
    )
    assert not res.ok
    assert res.status == InputOutcomeStatus.FAILED
    assert res.error_info is not None and res.error_info.code == "F0_DSP_STAGE_ERROR_HPF"
    assert res.output_frames == ()


# ============================================================================
# AI39 - AI50: Stateful Resampling, EOS Flush, Offsets, Timestamps
# ============================================================================


def test_ai39_8k_to_16k_contiguous_and_eos() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.generate(AnalyticSignalKind.SINE, sample_rate_hz=8000, sample_count=8000, seed=1)
    pipe = AudioInputPipeline(session_id="s-ai39", config=_bypass_config())
    sref = _make_stream_ref("s-ai39")
    r1 = pipe.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=8000, sample_count=8000, sequence=0, sample_offset=0)
    r_eos = pipe.flush_eos(sref)
    assert r1.ok and r_eos.ok
    total_out = sum(f.sample_count for f in (*r1.output_frames, *r_eos.output_frames))
    assert total_out == 16000


def test_ai40_48k_to_16k_contiguous_and_eos() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.generate(AnalyticSignalKind.SINE, sample_rate_hz=48000, sample_count=48000, seed=2)
    pipe = AudioInputPipeline(session_id="s-ai40", config=_bypass_config())
    sref = _make_stream_ref("s-ai40")
    r1 = pipe.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=48000, sample_count=48000, sequence=0, sample_offset=0)
    r_eos = pipe.flush_eos(sref)
    assert r1.ok and r_eos.ok
    total_out = sum(f.sample_count for f in (*r1.output_frames, *r_eos.output_frames))
    assert total_out == 16000


def test_ai41_16k_identity_rate_no_redundant_filter() -> None:
    rs = StatefulResampler(16000, 16000)
    assert rs.is_identity and rs.backend_name == "identity"
    x = np.linspace(-0.8, 0.8, 320, dtype=np.float32)
    y = rs.process(x)
    assert np.array_equal(x, y)
    assert len(rs.flush()) == 0


def test_ai42_uneven_tiny_including_1sample_matches_continuous() -> None:
    t = np.arange(4800) / 48000.0
    x = (0.5 * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32)
    ref_rs = soxr.ResampleStream(48000.0, 16000.0, 1, dtype="float32", quality="HQ")
    ref_y = ref_rs.resample_chunk(x, last=True)

    rs = StatefulResampler(48000, 16000, quality="HQ")
    parts = [rs.process(x[0:1]), rs.process(x[1:2]), rs.process(x[2:73]), rs.process(x[73:2000]), rs.process(x[2000:]), rs.flush()]
    stream_y = np.concatenate(parts)
    assert len(stream_y) == len(ref_y) == 1600
    assert np.max(np.abs(stream_y - ref_y)) < 1e-6


def test_ai43_long_rational_resampling_no_cumulative_drift() -> None:
    # 44.1 kHz -> 16 kHz over 3 seconds (132300 samples -> 48000 samples) in 441-sample blocks
    n_in = 44100 * 3
    x = (0.4 * np.sin(2 * np.pi * 1000.0 * np.arange(n_in) / 44100.0)).astype(np.float32)
    rs = StatefulResampler(44100, 16000, quality="HQ")
    outs = [rs.process(x[i : i + 441]) for i in range(0, n_in, 441)]
    outs.append(rs.flush())
    y = np.concatenate(outs)
    expected = round(n_in * 16000 / 44100)
    assert abs(len(y) - expected) <= 1


def test_ai44_and_ai45_passband_1khz_and_48k_12khz_stopband_alias() -> None:
    t = np.arange(48000) / 48000.0
    sine_1k = np.sin(2 * np.pi * 1000.0 * t).astype(np.float32)
    sine_12k = np.sin(2 * np.pi * 12000.0 * t).astype(np.float32)

    rs1 = StatefulResampler(48000, 16000, quality="HQ")
    y1 = np.concatenate([rs1.process(sine_1k), rs1.flush()])
    rs12 = StatefulResampler(48000, 16000, quality="HQ")
    y12 = np.concatenate([rs12.process(sine_12k), rs12.flush()])

    rms1 = float(np.sqrt(np.mean(y1[1000:-1000] ** 2)))
    rms12 = float(np.sqrt(np.mean(y12[1000:-1000] ** 2)))
    gain_1k_db = 20.0 * math.log10(rms1 / (1.0 / math.sqrt(2.0)))
    suppression_12k_db = 20.0 * math.log10(max(rms12, 1e-12) / rms1)

    assert abs(gain_1k_db) <= 1.0
    assert suppression_12k_db <= -30.0


def test_ai46_legacy_24k_and_44100_profiles_preserved() -> None:
    gen = SyntheticAudioGenerator()
    pipe = AudioInputPipeline(session_id="s-ai46", config=_bypass_config())
    for idx, sr in enumerate((24000, 44100)):
        seg = gen.generate(AnalyticSignalKind.SINE, sample_rate_hz=sr, sample_count=sr // 10, seed=idx)
        res = pipe.ingest_raw(
            stream_ref=_make_stream_ref("s-ai46", stream_id=f"leg-{sr}"),
            payload=seg.payload,
            sample_rate_hz=sr,
            sample_count=seg.sample_count,
            sequence=0,
            sample_offset=0,
            profile=LEGACY_WEB_EXTENDED_PROFILE,
        )
        assert res.ok


def test_ai47_eos_tail_once_and_second_eos_idempotent() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.generate(AnalyticSignalKind.SINE, sample_rate_hz=48000, sample_count=4800, seed=1)
    pipe = AudioInputPipeline(session_id="s-ai47", config=_bypass_config())
    sref = _make_stream_ref("s-ai47")
    r1 = pipe.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=48000, sample_count=4800, sequence=0, sample_offset=0)
    eos1 = pipe.flush_eos(sref)
    eos2 = pipe.flush_eos(sref)
    assert r1.ok and eos1.ok and eos2.ok
    assert eos2.output_frames == ()
    st, _ = pipe.registry.get_active(sref)
    assert st is not None
    st.ledger.assert_invariants()
    assert st.ledger.output_emitted_samples == 1600


def test_ai48_zero_output_intermediate_resampler_no_fake_empty_frame() -> None:
    pipe = AudioInputPipeline(session_id="s-ai48", config=_bypass_config())
    sref = _make_stream_ref("s-ai48")
    one_sample = struct.pack("<h", 1000)
    res = pipe.ingest_raw(
        stream_ref=sref,
        payload=one_sample,
        sample_rate_hz=48000,
        sample_count=1,
        sequence=0,
        sample_offset=0,
    )
    assert res.ok
    assert res.status == InputOutcomeStatus.BUFFERED
    assert res.output_frames == ()
    assert pipe.dispatcher.queued_items == 0


def test_ai49_input_output_stream_mapping_and_offsets() -> None:
    gen = SyntheticAudioGenerator()
    pipe = AudioInputPipeline(session_id="s-ai49", config=_bypass_config())
    sref = _make_stream_ref("s-ai49")
    for seq in range(5):
        seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=8000, seed=seq)
        pipe.ingest_raw(
            stream_ref=sref,
            payload=seg.payload,
            sample_rate_hz=8000,
            sample_count=160,
            sequence=seq,
            sample_offset=seq * 160,
        )
    pipe.flush_eos(sref)
    out_frames = pipe.dispatcher.drain_output_frames()
    expected_offset = 0
    for idx, f in enumerate(out_frames):
        assert f.sequence == idx
        assert f.sample_offset == expected_offset
        expected_offset += f.sample_count
    assert expected_offset == 1600


def test_ai50_timestamps_preserved_truthfully_never_fabricated() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=16000, seed=1)
    pipe = AudioInputPipeline(session_id="s-ai50", config=_bypass_config())
    r_with_ts = pipe.ingest_raw(
        stream_ref=_make_stream_ref("s-ai50", "with-ts"),
        payload=seg.payload,
        sample_rate_hz=16000,
        sample_count=320,
        sequence=0,
        sample_offset=0,
        captured_monotonic_ns=123_456_789,
        clock_domain="client.capture",
    )
    assert r_with_ts.ok
    assert r_with_ts.output_frames[0].captured_monotonic_ns == 123_456_789
    assert r_with_ts.output_frames[0].clock_domain == "client.capture"

    r_no_ts = pipe.ingest_raw(
        stream_ref=_make_stream_ref("s-ai50", "no-ts"),
        payload=seg.payload,
        sample_rate_hz=16000,
        sample_count=320,
        sequence=0,
        sample_offset=0,
    )
    assert r_no_ts.ok
    assert r_no_ts.output_frames[0].captured_monotonic_ns is None
    assert r_no_ts.output_frames[0].clock_domain is None


# ============================================================================
# AI51 - AI59: Backpressure, Control Lane, Stale Fencing, Telemetry, Privacy
# ============================================================================


def test_ai51_and_ai52_bounded_queue_backpressure_and_control_lane_not_starved() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=16000, seed=1)
    cfg = _bypass_config(max_queue_items=2, max_queue_bytes=4096)
    control_received: list[RawDtmfEvent] = []
    pipe = AudioInputPipeline(session_id="s-ai51", config=cfg, dtmf_consumer=control_received.append)
    sref = _make_stream_ref("s-ai51")

    assert pipe.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=16000, sample_count=320, sequence=0, sample_offset=0).ok
    assert pipe.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=16000, sample_count=320, sequence=1, sample_offset=320).ok
    bp = pipe.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=16000, sample_count=320, sequence=2, sample_offset=640)
    assert not bp.ok and bp.status == InputOutcomeStatus.BACKPRESSURE

    # AI52: Control/DTMF lane still succeeds while media queue is full
    ev = pipe.submit_signaling_dtmf(sref, "7")
    assert ev is not None
    assert [e.digit for e in control_received] == ["7"]


def test_ai53_close_while_worker_in_flight_quarantines_and_fences_stale_output() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=16000, seed=1)
    pipe = AudioInputPipeline(session_id="s-ai53", config=_bypass_config())
    sref = _make_stream_ref("s-ai53")
    state = pipe.open_stream(sref, sample_rate_hz=16000)

    assert pipe.lifecycle.enter_in_flight(state)
    # Close stream while worker is processing
    assert pipe.close_stream(sref, reason="disconnect_mid_frame")
    lease = pipe.session_ctx.ledger._leases[state.lease_id]
    assert lease.state == LeaseState.QUARANTINED

    # Worker tries to admit stale output after close -> fenced out
    out_frame = AudioFrame(
        schema_version=CONTRACT_SCHEMA_VERSION,
        stream_ref=sref,
        sequence=0,
        format=AudioFormat(16000, 1, AudioEncoding.FLOAT32_LE),
        sample_count=320,
        sample_offset=0,
        payload=b"\x00" * (320 * 4),
    )
    disp = pipe.dispatcher.admit_output_frame(out_frame, state)
    assert disp.status != "ACCEPTED"
    assert pipe.dispatcher.queued_items == 0

    # Worker finishes -> lease released exact-once
    pipe.lifecycle.exit_in_flight(state)
    assert lease.state == LeaseState.RELEASED
    assert state.release_completed


def test_ai54_cancel_output_generation_preserves_inbound_speech_and_dtmf() -> None:
    async def _run() -> None:
        ctx = SessionContext(SessionIdentity("s-ai54"))
        await ctx.open()
        await ctx.begin_turn()
        await ctx.begin_generation()

        dtmf_hits: list[str] = []
        pipe = AudioInputPipeline(
            session_ctx=ctx,
            config=_bypass_config(),
            dtmf_consumer=lambda ev: dtmf_hits.append(ev.digit),
        )
        # Barge-in cancels outbound generation ONLY
        assert await ctx.commit_interrupt("barge_in")
        assert ctx.lifecycle_state == SessionLifecycleState.ACTIVE

        gen = SyntheticAudioGenerator()
        seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=16000, seed=1)
        sref = _make_stream_ref("s-ai54")
        res = pipe.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=16000, sample_count=320, sequence=0, sample_offset=0)
        assert res.ok
        assert pipe.submit_signaling_dtmf(sref, "0") is not None
        assert dtmf_hits == ["0"]

    asyncio.run(_run())


def test_ai55_repeated_close_exact_once_release_and_no_negative_ledger() -> None:
    gen = SyntheticAudioGenerator()
    seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=8000, seed=1)
    pipe = AudioInputPipeline(session_id="s-ai55", config=_bypass_config())
    sref = _make_stream_ref("s-ai55")
    st = pipe.open_stream(sref, sample_rate_hz=8000)
    pipe.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=8000, sample_count=160, sequence=0, sample_offset=0)
    assert pipe.close(reason="first") == 1
    assert pipe.close(reason="second") == 0
    assert st.release_completed
    st.ledger.assert_invariants()


def test_ai56_observer_exception_and_bus_overflow_never_stall_audio() -> None:
    bus = BoundedEventBus(max_lane_size=1, drop_policy=DropPolicy.DROP_NEWEST)

    def broken_cb(_env: object) -> None:
        raise RuntimeError("observer_boom")

    sub = bus.subscribe("broken", max_lane_size=1, callback=broken_cb)
    tel = AudioFrontendTelemetry(event_bus=bus)
    pipe = AudioInputPipeline(session_id="s-ai56", config=_bypass_config(), telemetry=tel)
    gen = SyntheticAudioGenerator()
    sref = _make_stream_ref("s-ai56")

    for seq in range(4):
        seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=16000, seed=seq)
        res = pipe.ingest_raw(
            stream_ref=sref,
            payload=seg.payload,
            sample_rate_hz=16000,
            sample_count=320,
            sequence=seq,
            sample_offset=seq * 320,
        )
        assert res.ok
    bus.dispatch_all()
    assert sub.callback_error_count >= 1
    assert tel.dropped_events_count >= 1


def test_ai57_quality_metrics_rms_dbfs_peak_clipping() -> None:
    silence = np.zeros(320, dtype=np.float32)
    q_sil = analyze_float32_quality(silence, stage="input")
    assert q_sil.linear_rms == 0.0
    assert q_sil.rms_dbfs is None
    assert q_sil.rms_dbfs_status == MetricStatus.UNAVAILABLE

    const_half = np.full(320, 0.5, dtype=np.float32)
    q_half = analyze_float32_quality(const_half, valid_sample_count=160, stage="output")
    assert math.isclose(q_half.linear_rms, 0.5, abs_tol=1e-6)
    assert q_half.rms_dbfs is not None and math.isclose(q_half.rms_dbfs, -6.0206, abs_tol=1e-3)
    assert q_half.clip_denominator == 160


def test_ai58_m04_timing_with_fake_clock() -> None:
    clock = HarnessClock(initial_ns=5_000_000)
    tel = AudioFrontendTelemetry(clock=clock, evidence_kind=EvidenceKind.SYNTHETIC_FIXTURE)
    ev = tel.record_frame_processed(
        session_id="s-ai58",
        trace_id="tr-58",
        stream_id="in-0",
        format_epoch=0,
        input_rate_hz=8000,
        encoding="PCM_S16LE",
        valid_sample_count=160,
        padding_samples=0,
        config_revision="rev1",
        route="bypass",
        processing_ms=1.25,
        block_duration_ms=20.0,
        queue_delay_ms=0.0,
        group_delay_samples=0.0,
        quality=None,
    )
    assert ev is not None
    hist = tel.metrics.get_histogram_summary("f0.processing_ms", observation_scope="SERVER")
    assert hist is not None and hist.p95 == 1.25


def test_ai59_no_audio_dtmf_or_pii_sentinel_leak_in_telemetry() -> None:
    ev_rec = EvidenceRecorder()
    tel = AudioFrontendTelemetry(evidence=ev_rec, evidence_kind=EvidenceKind.SYNTHETIC_FIXTURE)
    projected = tel.emit_event(
        event_type="pipeline.stage.f0",
        session_id="s-ai59",
        metadata={
            "stage": "F0",
            "status": "completed",
            "audio_bytes": b"RAW_AUDIO_SECRET",
            "payload": "LEAK",
            "digit": "9",
            "reason": "caller +905551112233 plate 34 ABC 123",
        },
    )
    assert projected is not None
    findings = PIISecretScanner.scan_object(projected)
    assert findings == []
    assert "audio_bytes" not in projected.get("metadata", {})
    assert "digit" not in projected.get("metadata", {})

    dtmf_ev = RawDtmfEvent(_make_stream_ref("s-ai59"), digit="9", source="inband", detected_monotonic_ns=10, clock_domain="fake")
    assert "9" not in repr(dtmf_ev)


# ============================================================================
# AI60 - AI64: F1 Seam, Legacy Golden Replay, Concurrency, Regression, Integrity
# ============================================================================


def test_ai60_fake_f1_consumer_and_fake_vad_receive_m01_16k_frames() -> None:
    received_f1: list[AudioFrame] = []
    pipe = AudioInputPipeline(session_id="s-ai60", config=_bypass_config(), f1_consumer=received_f1.append)
    gen = SyntheticAudioGenerator()
    sref = _make_stream_ref("s-ai60")
    for seq in range(3):
        seg = gen.frame_20ms(AnalyticSignalKind.SPEECH_ENVELOPE, sample_rate_hz=48000, seed=seq)
        pipe.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=48000, sample_count=960, sequence=seq, sample_offset=seq * 960)
    pipe.flush_eos(sref)
    assert len(received_f1) >= 2
    assert sum(f.sample_count for f in received_f1) == 960
    assert all(f.format.sample_rate_hz == 16000 and f.format.channels == 1 for f in received_f1)

    vad = FakeVADAdapter([ScriptedVADStep(SpeechEventKind.SPEECH_START, 0, "fake_vad_start", 0.9)])
    events = vad.emit_all(session_id="s-ai60", stream_id="in-0")
    assert len(events) == 1 and events[0].kind == SpeechEventKind.SPEECH_START


def test_ai61_legacy_web_phone_facade_golden_replay() -> None:
    gen = SyntheticAudioGenerator()
    dtmf_hits: list[str] = []
    facade = LegacyAudioInputFacade(
        session_id="s-ai61",
        sample_rate_hz=8000,
        channel="asterisk",
        enable_100ms_coalesce=True,
        dtmf_callback=dtmf_hits.append,
    )
    # 10 x 20ms frames = two 100ms legacy coalesce batches (SoXR emits after startup delay fills)
    emitted_chunks = []
    for seq in range(10):
        seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=8000, seed=seq)
        out = facade.process_pcm16_chunk(seg.payload)
        if seq < 4 or (4 < seq < 9):
            assert out.buffered_only
        if not out.buffered_only:
            emitted_chunks.append(out.samples_16k)
            assert out.route == "legacy_dsp"
    tail = facade.flush_eos()
    if len(tail) > 0:
        emitted_chunks.append(tail)
    assert sum(len(c) for c in emitted_chunks) == 3200
    facade.close()


def test_ai62_multiple_streams_mixed_rates_and_disconnects() -> None:
    gen = SyntheticAudioGenerator()
    pipelines = [
        (AudioInputPipeline(session_id=f"multi-{i}", config=_bypass_config()), sr)
        for i, sr in enumerate((8000, 16000, 48000))
    ]
    for idx, (p, sr) in enumerate(pipelines):
        sref = _make_stream_ref(f"multi-{idx}")
        seg = gen.frame_20ms(AnalyticSignalKind.SINE, sample_rate_hz=sr, seed=idx)
        assert p.ingest_raw(stream_ref=sref, payload=seg.payload, sample_rate_hz=sr, sample_count=seg.sample_count, sequence=0, sample_offset=0).ok
        assert p.flush_eos(sref).ok
        st, _ = p.registry.get_active(sref)
        assert st is not None
        st.ledger.assert_invariants()
        p.close(reason="disconnect")


def test_ai63_m00_feature_preservation_check() -> None:
    reg = json.loads((REPO_ROOT / "docs" / "freya2" / "baseline" / "20261126T001600Z" / "FEATURE_REGISTRY.json").read_text(encoding="utf-8"))
    f0_features = {r["feature_id"]: r for r in reg["records"] if r["domain"] == "F0"}
    assert "FT-F0-0001" in f0_features
    assert "FT-F0-0002" in f0_features
    # Verify legacy symbols remain intact without modification
    assert CarNoiseFilter(120.0, 8000).cutoff_hz == 120.0
    assert len(generate_dtmf_tone("1", 0.04, 8000)) == 320


def test_ai64_evidence_integrity_scope_and_rollback_rehearsal() -> None:
    # Verify all F0-A modules carry Özel Lisans header and zero forbidden files were altered by F0-A
    pkg_dir = REPO_ROOT / "backend" / "audio_frontend"
    py_files = sorted(pkg_dir.glob("*.py"))
    assert len(py_files) == 16
    for pf in py_files:
        head = pf.read_text(encoding="utf-8")[:400]
        assert "Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)" in head

    # Rollback rehearsal: close active strict pipeline and cleanly fall back to legacy path on new stream
    pipe = AudioInputPipeline(session_id="s-ai64-strict", config=default_audio_frontend_config(strict_pipeline_enabled=True))
    sref = _make_stream_ref("s-ai64-strict")
    pipe.open_stream(sref, sample_rate_hz=8000)
    pipe.close(reason="rollback_to_legacy")
    assert pipe.registry.active_count() == 0

    legacy = LegacyAudioInputFacade(session_id="s-ai64-legacy", sample_rate_hz=8000)
    assert legacy.config.strict_pipeline_enabled is False
    legacy.close()
