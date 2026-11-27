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

import threading

import numpy as np
import pytest

from backend.audio_frontend import (
    AcousticEvidence,
    AdaptationDecision,
    AdaptiveDenoiserStage,
    AecOutputStatus,
    AudioFrontendConfig,
    AudioInputPipeline,
    BoundedNlmsAec,
    ClockMapping,
    ClockMappingStatus,
    DelayStatus,
    DeliveryStatus,
    DoubleTalkCategory,
    DoubleTalkClassifier,
    EnvironmentProfileId,
    NccDelayEstimator,
    PlaybackReferenceReader,
    ReferenceAssociation,
    ReferenceChunk,
    RnnoiseDenoiserAdapter,
    SnrMethod,
    compute_erle_db,
    compute_oracle_snr_db,
    default_audio_frontend_config,
    probe_rnnoise_capability,
    resolve_clock_mapping,
    resolve_enhancement_profile,
)
from backend.core.contracts.audio import AudioEncoding, AudioFormat, AudioFrame
from backend.core.contracts.common import (
    CONTRACT_SCHEMA_VERSION,
    CapabilityState,
    MetricStatus,
    StreamDirection,
    StreamRef,
)
from backend.core.contracts.playback import ObservationScope
from backend.core.runtime.deadlines import FakeClock


class _FakeRnnoiseProvider:
    def __init__(self) -> None:
        self.frames_processed = 0
        self.reset_count = 0
        self.closed = False

    def process_frame_48k(self, frame_48k: np.ndarray) -> tuple[np.ndarray, float | None]:
        assert len(frame_48k) == 480
        self.frames_processed += 1
        return frame_48k * 0.9, 0.75

    def reset(self) -> None:
        self.reset_count += 1

    def close(self) -> None:
        self.closed = True


def _make_speech_like_signal(n: int, sr: int = 16000, *, amp: float = 0.25, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=np.float32) / float(sr)
    sig = (
        0.5 * np.sin(2.0 * np.pi * 220.0 * t)
        + 0.35 * np.sin(2.0 * np.pi * 660.0 * t)
        + 0.15 * np.sin(2.0 * np.pi * 1320.0 * t)
    )
    mod = 0.6 + 0.4 * np.sin(2.0 * np.pi * 4.0 * t)
    noise = 0.01 * rng.standard_normal(n).astype(np.float32)
    return (amp * sig * mod + noise).astype(np.float32)


def test_f0b_passive_imports_zero_threads() -> None:
    before = threading.active_count()
    import backend.audio_frontend as af  # noqa: F401

    after = threading.active_count()
    assert after == before


def test_f0b_opt_in_flags_default_off() -> None:
    cfg = default_audio_frontend_config()
    assert cfg.f0_b_adaptive_dsp_enabled is False
    assert cfg.f0_b_aec_enabled is False
    assert cfg.f0_b_rnnoise_enabled is False
    assert cfg.environment_profile == EnvironmentProfileId.PARKED_CAR


@pytest.mark.parametrize(
    "profile_id",
    [
        EnvironmentProfileId.QUIET_OFFICE,
        EnvironmentProfileId.PARKED_CAR,
        EnvironmentProfileId.MOVING_CAR,
        EnvironmentProfileId.WORKSHOP,
        EnvironmentProfileId.WIND_EXPOSED,
        EnvironmentProfileId.TELEPHONE_NARROWBAND,
    ],
)
def test_environment_profiles_resolve_bounded(profile_id: EnvironmentProfileId) -> None:
    prof = resolve_enhancement_profile(profile_id)
    assert prof.profile_id == profile_id
    assert prof.hpf_cutoff_hz > 0.0
    assert 0.0 < prof.gain_floor <= 1.0
    assert 0.0 < prof.aec_mu < 2.0
    if profile_id == EnvironmentProfileId.TELEPHONE_NARROWBAND:
        assert prof.narrowband_ceiling_hz == 3400.0


def test_clock_mapping_never_subtracts_unmapped_domains() -> None:
    same = resolve_clock_mapping("monotonic_server", "monotonic_server")
    assert same.status == ClockMappingStatus.SAME_MONOTONIC
    assert same.map_ns(12345) == 12345

    diff = resolve_clock_mapping("monotonic_server", "browser_perf_clock")
    assert diff.status == ClockMappingStatus.UNKNOWN
    assert diff.map_ns(12345) is None

    affine = ClockMapping(
        source_domain="browser_perf_clock",
        target_domain="monotonic_server",
        status=ClockMappingStatus.VERIFIED_AFFINE,
        mapping_revision="cal-1",
        slope=1.0,
        offset_ns=5000,
        uncertainty_ns=100,
    )
    mapped = resolve_clock_mapping("monotonic_server", "browser_perf_clock", verified_affine=affine)
    assert mapped.status == ClockMappingStatus.VERIFIED_AFFINE
    assert mapped.map_ns(1000) == 6000


def test_playback_reference_reader_isolation_and_rate_bridge() -> None:
    out_ref = StreamRef("sess-1", "out-1", StreamDirection.OUTPUT, format_epoch=1)
    assoc = ReferenceAssociation(
        session_id="sess-1",
        input_stream_id="in-1",
        input_format_epoch=1,
        output_stream_ref=out_ref,
    )
    reader = PlaybackReferenceReader(assoc, target_rate_hz=16000, max_history_samples=1000)

    # Cross-session chunk rejected
    bad_ref = StreamRef("other-sess", "out-1", StreamDirection.OUTPUT, format_epoch=1)
    bad_chunk = ReferenceChunk(
        stream_ref=bad_ref,
        generation_id=1,
        sequence=0,
        sample_offset=0,
        sample_rate_hz=48000,
        samples=np.zeros(960, dtype=np.float32),
        valid_sample_count=960,
    )
    assert reader.push_reference_chunk(bad_chunk) is False

    # Valid 48 kHz chunks rate-bridged to 16 kHz and bounded at 1000 samples
    for seq in range(5):
        chunk = ReferenceChunk(
            stream_ref=out_ref,
            generation_id=1,
            sequence=seq,
            sample_offset=seq * 960,
            sample_rate_hz=48000,
            samples=np.full(960, 0.1, dtype=np.float32),
            valid_sample_count=960,
            claimed_monotonic_ns=1_000_000 * (seq + 1),
            clock_domain="server_mono",
            delivery_status=DeliveryStatus.COMPLETED_LOCAL,
        )
        assert reader.push_reference_chunk(chunk) is True

    res = reader.read_recent(max_samples=2000)
    assert res.ok is True
    assert res.sample_rate_hz == 16000
    assert len(res.samples) <= 1000
    assert res.evicted_samples > 0
    assert res.delivery_status == DeliveryStatus.COMPLETED_LOCAL

    reader.close()
    closed_res = reader.read_recent(max_samples=320)
    assert closed_res.ok is False
    assert closed_res.delivery_status == DeliveryStatus.UNAVAILABLE


def test_ncc_delay_estimator_lag_and_ambiguity_gates() -> None:
    sr = 16000
    rng = np.random.default_rng(42)
    ref_hist = (0.3 * rng.standard_normal(4000)).astype(np.float32)
    true_lag = 120  # 7.5 ms
    mic_win = ref_hist[4000 - 1280 - true_lag : 4000 - true_lag] * 0.6

    est = NccDelayEstimator(sample_rate_hz=sr, max_lag_ms=50.0, corr_window_ms=80.0)
    res = est.estimate(mic_win, ref_hist)
    assert res.status == DelayStatus.CONFIDENT
    assert res.lag_samples == true_lag
    assert res.score is not None and res.score > 0.9

    # Silent mic rejected as UNKNOWN (never arbitrary 0)
    silent_res = est.estimate(np.zeros(1280, dtype=np.float32), ref_hist)
    assert silent_res.status == DelayStatus.UNKNOWN
    assert silent_res.lag_samples is None

    # Pure periodic sine tone rejected as UNCERTAIN due to periodic ambiguity
    t = np.arange(4000, dtype=np.float32) / float(sr)
    tone_ref = (0.4 * np.sin(2.0 * np.pi * 500.0 * t)).astype(np.float32)
    tone_mic = tone_ref[4000 - 1280 - 64 : 4000 - 64]
    ambig_res = est.estimate(tone_mic, tone_ref)
    assert ambig_res.status == DelayStatus.UNCERTAIN
    assert ambig_res.reason == "ambiguous_periodic_peak"


def test_bounded_nlms_aec_converges_and_freezes_on_double_talk() -> None:
    sr = 16000
    rng = np.random.default_rng(99)
    far_end = (0.35 * rng.standard_normal(sr)).astype(np.float32)
    # Linear echo path: 0.5*x[n] + 0.25*x[n-3] - 0.1*x[n-7]
    echo = np.zeros_like(far_end)
    echo[0:] += 0.5 * far_end[0:]
    echo[3:] += 0.25 * far_end[:-3]
    echo[7:] -= 0.1 * far_end[:-7]

    aec = BoundedNlmsAec(sample_rate_hz=sr, filter_len_ms=16.0, mu=0.4)
    dt = DoubleTalkClassifier()

    block = 320
    last_erle = None
    for i in range(0, sr - block, block):
        m_blk = echo[i : i + block]
        r_blk = far_end[i : i + block]
        ev = dt.classify(mic_samples=m_blk, aligned_ref_samples=r_blk, delay_confident=True)
        out = aec.process_block(m_blk, r_blk, adaptation=ev.adaptation_decision)
        if i >= sr // 2:
            last_erle = compute_erle_db(m_blk, out.samples)

    assert last_erle is not None and last_erle > 8.0

    # Now inject near-end speech (double-talk): classifier must FREEZE adaptation & preserve near-end
    near_end = _make_speech_like_signal(block, sr=sr, amp=0.35, seed=3)
    dt_mix = near_end + echo[:block]
    r_blk = far_end[:block]
    w_before = aec.weights_norm
    ev_dt = dt.classify(mic_samples=dt_mix, aligned_ref_samples=r_blk, residual_samples=dt_mix, delay_confident=True)
    assert ev_dt.category == DoubleTalkCategory.DOUBLE_TALK_LIKELY
    assert ev_dt.adaptation_decision == AdaptationDecision.FREEZE

    res_dt = aec.process_block(dt_mix, r_blk, adaptation=ev_dt.adaptation_decision)
    assert res_dt.output_status == AecOutputStatus.FROZEN_FILTER
    assert pytest.approx(aec.weights_norm, rel=1e-6) == w_before
    assert float(np.sqrt(np.mean(res_dt.samples**2))) > 0.05


def test_adaptive_denoiser_preserves_speech_and_detects_wind() -> None:
    sr = 16000
    prof = resolve_enhancement_profile(EnvironmentProfileId.WIND_EXPOSED)
    denoiser = AdaptiveDenoiserStage(sample_rate_hz=sr, profile=prof)
    rng = np.random.default_rng(12)

    # Calibrate on stationary noise
    noise = (0.03 * rng.standard_normal(320 * 10)).astype(np.float32)
    for i in range(0, len(noise), 320):
        res = denoiser.process(noise[i : i + 320])
        assert len(res.samples) == 320
    assert denoiser.is_calibrated is True
    assert denoiser.noise_floor_dbfs() is not None

    # Speech blocks with noise floor frozen (feed 3 blocks to clear OLA latency)
    speech = _make_speech_like_signal(320 * 3, sr=sr, amp=0.3)
    res_sp = None
    for i in range(0, len(speech), 320):
        res_sp = denoiser.process(speech[i : i + 320], freeze_noise_update=True)
        assert len(res_sp.samples) == 320
    assert res_sp is not None
    assert float(np.sqrt(np.mean(res_sp.samples**2))) > 0.05

    # Low-frequency wind turbulence detection (<250 Hz high energy)
    t = np.arange(512, dtype=np.float32) / float(sr)
    wind = (0.6 * np.sin(2.0 * np.pi * 60.0 * t)).astype(np.float32)
    res_wind = denoiser.process(wind)
    assert res_wind.wind_turbulence_detected is True


def test_rnnoise_capability_probe_and_fake_provider_seam() -> None:
    cap = probe_rnnoise_capability()
    assert cap.state == CapabilityState.UNSUPPORTED
    assert cap.reason == "rnnoise_library_not_installed"

    provider = _FakeRnnoiseProvider()
    adapter = RnnoiseDenoiserAdapter(sample_rate_hz=16000, provider=provider)
    assert adapter.capability.state == CapabilityState.VERIFIED
    out1 = adapter.process(np.full(320, 0.2, dtype=np.float32))
    out2 = adapter.process(np.full(320, 0.2, dtype=np.float32))
    assert len(out1) == 320
    assert len(out2) == 320
    assert provider.frames_processed >= 1
    assert adapter.last_provider_vad_prob == 0.75
    adapter.close()
    assert provider.closed is True


def test_oracle_snr_and_erle_helpers() -> None:
    clean = np.full(160, 0.2, dtype=np.float32)
    noise = np.full(160, 0.02, dtype=np.float32)
    snr = compute_oracle_snr_db(clean, noise)
    assert snr is not None and pytest.approx(snr, abs=0.1) == 20.0
    assert compute_oracle_snr_db(clean, np.zeros(160, dtype=np.float32)) is None
    assert compute_erle_db(clean, noise) == pytest.approx(20.0, abs=0.1)


def test_pipeline_end_to_end_f0b_with_reference_and_evidence() -> None:
    clock = FakeClock(initial_ns=1_000_000_000, clock_domain="server_mono")
    cfg = default_audio_frontend_config(
        f0_b_adaptive_dsp_enabled=True,
        f0_b_aec_enabled=True,
        environment_profile=EnvironmentProfileId.MOVING_CAR,
    )
    out_ref = StreamRef("sess-f0b", "out-1", StreamDirection.OUTPUT, format_epoch=1)
    assoc = ReferenceAssociation(
        session_id="sess-f0b",
        input_stream_id="in-1",
        input_format_epoch=1,
        output_stream_ref=out_ref,
    )
    ref_reader = PlaybackReferenceReader(assoc, target_rate_hz=16000, max_history_samples=8000)

    emitted: list[AudioFrame] = []
    pipe = AudioInputPipeline(
        session_id="sess-f0b",
        config=cfg,
        clock=clock,
        f1_consumer=emitted.append,
        reference_source=ref_reader,
    )
    in_ref = StreamRef("sess-f0b", "in-1", StreamDirection.INPUT, format_epoch=1)
    pipe.open_stream(in_ref, sample_rate_hz=16000)

    rng = np.random.default_rng(101)
    far = (0.3 * rng.standard_normal(320 * 6)).astype(np.float32)
    for seq in range(6):
        blk = far[seq * 320 : (seq + 1) * 320]
        ref_reader.push_reference_chunk(
            ReferenceChunk(
                stream_ref=out_ref,
                generation_id=1,
                sequence=seq,
                sample_offset=seq * 320,
                sample_rate_hz=16000,
                samples=blk,
                valid_sample_count=320,
                claimed_monotonic_ns=clock.monotonic_ns(),
                clock_domain="server_mono",
                observation_scope=ObservationScope.SERVER,
                delivery_status=DeliveryStatus.CLAIMED,
            )
        )
        pcm = (np.clip(blk * 0.4, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        frame = AudioFrame(
            schema_version=CONTRACT_SCHEMA_VERSION,
            stream_ref=in_ref,
            sequence=seq,
            format=AudioFormat(16000, 1, AudioEncoding.PCM_S16LE),
            sample_count=320,
            sample_offset=seq * 320,
            payload=pcm,
            captured_monotonic_ns=clock.monotonic_ns(),
            clock_domain="server_mono",
            valid_sample_count=320,
        )
        res = pipe.ingest_frame(frame)
        assert res.ok is True
        assert res.route == "f0b_adaptive:MOVING_CAR"
        assert isinstance(res.acoustic_evidence, AcousticEvidence)
        assert res.acoustic_evidence.snr_method == SnrMethod.ESTIMATED
        assert res.acoustic_evidence.clock_mapping_status == ClockMappingStatus.SAME_MONOTONIC
        clock.advance_ms(20)

    assert len(emitted) == 6
    pipe.close()
    ref_reader.close()


def test_browser_native_aec_not_duplicated() -> None:
    cfg = default_audio_frontend_config(
        f0_b_adaptive_dsp_enabled=True,
        f0_b_aec_enabled=True,
        environment_profile=EnvironmentProfileId.QUIET_OFFICE,
        browser_native_aec_active=True,
    )
    out_ref = StreamRef("sess-browser", "out-1", StreamDirection.OUTPUT, format_epoch=1)
    assoc = ReferenceAssociation(
        session_id="sess-browser",
        input_stream_id="in-1",
        input_format_epoch=1,
        output_stream_ref=out_ref,
    )
    ref_reader = PlaybackReferenceReader(assoc, target_rate_hz=16000)
    pipe = AudioInputPipeline(
        session_id="sess-browser",
        config=cfg,
        reference_source=ref_reader,
    )
    in_ref = StreamRef("sess-browser", "in-1", StreamDirection.INPUT, format_epoch=1)
    pcm = np.zeros(320, dtype="<i2").tobytes()
    res = pipe.ingest_raw(
        stream_ref=in_ref,
        payload=pcm,
        sample_rate_hz=16000,
        sample_count=320,
        sequence=0,
        sample_offset=0,
    )
    assert res.ok is True
    assert res.acoustic_evidence is not None
    assert res.acoustic_evidence.aec_status == AecOutputStatus.BYPASS
    pipe.close()
