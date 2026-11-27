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
import random
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np
import pytest

from backend.core.contracts import (
    CONTRACT_SCHEMA_VERSION,
    AudioChunk,
    AudioEncoding,
    AudioFormat,
    CacheStatus,
    ChunkPlan,
    GenerationRef,
    PlanValidationStatus,
    QualityStatus,
    SynthesisPlan,
)
from backend.core.contracts.common import CapabilityState
from backend.core.model_registry import ModelKind, ModelRegistry
from backend.core.runtime import CancellationScope, DeadlineBudget
from backend.neural_synthesis import (
    AdaptiveProfileSelector,
    BASELINE_LATENT_DIM,
    BASELINE_ODE_STEPS,
    BASELINE_SAMPLE_RATE_HZ,
    BASELINE_SOLVER,
    BatchCandidate,
    BatchLayoutBuilder,
    BatchLayoutError,
    CACHE_SCHEMA_VERSION,
    CacheEligibilityKind,
    DeadlineBatchFormer,
    DecoderAdapter,
    DiscreteSolverDescriptor,
    DurationDecision,
    DurationEstimate,
    IsolatedRngAdapter,
    LatentInitializationError,
    ModelResidencyAdapter,
    NeuralSynthesisPipeline,
    QualityGuard,
    RAW_AUDIO_FORMAT,
    SameSeedRecoveryPolicy,
    SolverProfile,
    SpeakerIntelligenceEvaluator,
    SpeakerReferenceManifest,
    StrictSynthesisCacheAdapter,
    SynthesisModelHandles,
    VersionedCacheStore,
    pin_synthesis_snapshot,
    resolve_default_snapshot,
)
from backend.runtime_resources import (
    MIB,
    HandleOwnership,
    MemoryBudget,
    PriorityClass,
    UnifiedGpuScheduler,
)
from tests.harness.adapters import FakeGPUProbeAdapter
from tests.harness.fake_clock import HarnessClock

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_plan(
    *,
    session_id: str = "sess-f5bc",
    turn_id: int = 1,
    gen_id: int = 1,
    plan_id: str = "plan-1",
    plan_rev: int = 1,
    seed: int = 9,
    voice_profile: str = "leyla-baseline-9",
    texts: tuple[str, ...] = ("Merhaba dünya.",),
) -> SynthesisPlan:
    gen_ref = GenerationRef(session_id=session_id, turn_id=turn_id, generation_id=gen_id)
    chunks = tuple(
        ChunkPlan(
            chunk_id=f"chunk-{idx}",
            chunk_index=idx,
            model_text=t,
        )
        for idx, t in enumerate(texts)
    )
    joined = " ".join(texts)
    return SynthesisPlan(
        schema_version=CONTRACT_SCHEMA_VERSION,
        plan_id=plan_id,
        plan_revision=plan_rev,
        generation_ref=gen_ref,
        response_id=f"resp-{plan_id}",
        source_text=joined,
        normalized_text=joined,
        language="tr",
        voice_profile=voice_profile,
        seed=seed,
        normalization_passes=1,
        validation_status=PlanValidationStatus.VALID,
        chunks=chunks,
    )


def _make_scheduler(clock: HarnessClock, *, total_vram_mb: int = 8192) -> UnifiedGpuScheduler:
    probe = FakeGPUProbeAdapter(clock)
    sched = UnifiedGpuScheduler(clock=clock)
    sched.memory_budget.update_probe(probe.valid_probe(free_mib=total_vram_mb))
    return sched


class _FakeDiT:
    def __init__(self, *, fail_first_n: int = 0, uncertain_on_fail: bool = False) -> None:
        self.calls = 0
        self.fail_first_n = fail_first_n
        self.uncertain_on_fail = uncertain_on_fail

    def encode_prepared_text(self, text: str, token_ids: tuple[int, ...], *, device: str = "cpu") -> dict[str, Any]:
        return {
            "observed_text": text,
            "context": np.ones((1, len(token_ids), 8), dtype=np.float32),
            "char_mask": np.ones((1, len(token_ids)), dtype=bool),
        }

    def predict_duration_frames(self, _encoded: Any) -> float:
        return 16.0

    def solve_ode(self, *, latent: Any, encoded: Any, profile: SolverProfile) -> dict[str, Any]:
        self.calls += 1
        if self.calls <= self.fail_first_n:
            err = RuntimeError("transient_ode_failure")
            if self.uncertain_on_fail:
                setattr(err, "uncertain_device_state", True)
            raise err
        return {
            "latents": latent,
            "nfe_evaluated": profile.steps,
            "completed_steps": profile.steps,
        }


class _FakeVAE:
    sample_rate_hz = 48000

    def __init__(self, *, silent_first_n: int = 0) -> None:
        self.calls = 0
        self.silent_first_n = silent_first_n
        self.decoded_shapes: list[tuple[int, ...]] = []

    def decode(self, latents_bct: Any) -> np.ndarray:
        self.calls += 1
        arr = np.asarray(latents_bct)
        self.decoded_shapes.append(tuple(int(d) for d in arr.shape))
        frames = int(arr.shape[2])
        n_samples = frames * 1920
        if self.calls <= self.silent_first_n:
            return np.zeros((1, 1, n_samples), dtype=np.float32)
        t = np.arange(n_samples, dtype=np.float32) / 48000.0
        wave = 0.25 * np.sin(2.0 * np.pi * 220.0 * t)
        return wave.reshape(1, 1, n_samples).astype(np.float32)


def _register_fake_handles(scheduler: UnifiedGpuScheduler, tts_model: Any, vae: Any) -> None:
    cfg = resolve_default_snapshot()
    mreg = ModelRegistry.from_snapshot(cfg)
    desc = mreg.get("tts-freya")
    assert desc is not None
    char_to_id = {ch: idx + 1 for idx, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzçğıöşüÇĞİÖŞÜ .,-!?0123456789")}
    handles = SynthesisModelHandles(
        model_id="tts-freya",
        model_revision=desc.model_revision,
        vocab_revision="vocab-v1",
        tts_model=tts_model,
        vae=vae,
        char_to_id=MappingProxyType(char_to_id),
        device="cpu",
        dtype="float32",
        sample_rate_hz=48000,
        rng_isolation_mode="ISOLATED_GENERATOR",
    )
    res_adapter = ModelResidencyAdapter(scheduler.residency_manager)
    res_adapter.register_handles(handles, vram_bytes=64 * MIB, ownership=HandleOwnership.BORROWED)


# ---------------------------------------------------------------------------
# F5-B Tests: Passive imports, RNG isolation, Layout/Unpadding, Cache, Quality, Recovery
# ---------------------------------------------------------------------------


def test_f5bc_01_passive_import_isolation() -> None:
    script = (
        "import sys; "
        "import backend.neural_synthesis as ns; "
        "from tests.harness.isolation import audit_import_closure; "
        "bad = audit_import_closure(sys.modules.keys()); "
        "assert not bad, bad; "
        "assert 'backend.models' not in sys.modules; "
        "assert 'librosa' not in sys.modules"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_f5bc_02_request_local_rng_isolation_independent_of_peers_and_global_state() -> None:
    plan = _make_plan(seed=42, voice_profile="leyla-warm-42")
    snapshot = pin_synthesis_snapshot(plan, allow_experimental_seeds=True)
    rng_adapter = IsolatedRngAdapter()

    est = DurationEstimate(
        token_count=14,
        char_count=14,
        raw_predicted_frames=16.0,
        raw_predicted_sec=0.64,
        effective_frames=16,
        effective_duration_sec=0.64,
        expected_samples=16 * 1920,
        clamped=False,
        clamp_reason=None,
        units="frames@25Hz",
        latent_rate_hz=25,
        samples_per_frame=1920,
        sample_rate_hz=48000,
        profile_revision="f5b-test",
    )
    decision = DurationDecision(
        allowed=True,
        reason_code="OK",
        estimate=est,
        estimated_latent_bytes=16 * 64 * 4,
        estimated_waveform_bytes=16 * 1920 * 4,
        estimated_vram_bytes=10 * MIB,
    )

    random.seed(99999)
    state_before = random.getstate()
    spec_a = rng_adapter.build_spec(attempt_ref="att-a", seed=42, true_frames=16, latent_dim=64)
    lat_a, desc_a = rng_adapter.draw_true_latent(spec=spec_a, decision=decision, snapshot=snapshot)
    assert random.getstate() == state_before

    # Mutate global RNG and draw with different attempt_ref -> identical initial noise
    random.seed(12345)
    spec_b = rng_adapter.build_spec(attempt_ref="att-b", seed=42, true_frames=16, latent_dim=64)
    lat_b, _ = rng_adapter.draw_true_latent(spec=spec_b, decision=decision, snapshot=snapshot)
    assert np.array_equal(lat_a, lat_b)
    assert desc_a.shape == (1, 16, 64)

    with pytest.raises(LatentInitializationError):
        rng_adapter.draw_true_latent(
            spec=spec_a,
            decision=decision,
            snapshot=snapshot,
            rng_isolation_mode="UNISOLATED",
        )
    with pytest.raises(LatentInitializationError):
        rng_adapter.build_spec(attempt_ref="bad", seed=True, true_frames=16, latent_dim=64)  # type: ignore[arg-type]


def test_f5bc_03_batch_layout_masking_and_unpadded_decode() -> None:
    builder = BatchLayoutBuilder()
    layout = builder.build_layout(
        batch_id="b-1",
        members=[
            ("m1", 10, 12, 12 * 1920, 64),
            ("m2", 18, 20, 20 * 1920, 64),
        ],
        compatibility_key="euler32-cpu-f32",
    )
    assert layout.padded_latent_frames == 20
    assert layout.total_valid_latent_frames == 32
    assert layout.total_padded_latent_frames == 40
    assert math.isclose(layout.padding_fraction, 0.2, rel_tol=1e-6)

    lat1 = np.ones((1, 12, 64), dtype=np.float32) * 1.5
    lat2 = np.ones((1, 20, 64), dtype=np.float32) * 2.5
    padded, mask = builder.stack_and_mask(layout=layout, item_latents=[lat1, lat2])
    assert padded.shape == (2, 20, 64)
    assert mask.shape == (2, 20)
    assert bool(mask[0, 11]) is True and bool(mask[0, 12]) is False
    assert np.all(padded[0, 12:, :] == 0.0)
    assert bool(mask[1, 19]) is True

    unpadded = builder.unpad_latents(layout=layout, solved_batch_latents=padded)
    assert unpadded[0][0] == "m1" and unpadded[0][1].shape == (1, 12, 64)
    assert unpadded[1][0] == "m2" and unpadded[1][1].shape == (1, 20, 64)

    vae = _FakeVAE()
    dec = DecoderAdapter()
    est1 = DurationEstimate(10, 10, 12.0, 0.48, 12, 0.48, 12 * 1920, False, None, "frames@25Hz", 25, 1920, 48000, "f5b-test")
    est2 = DurationEstimate(18, 18, 20.0, 0.80, 20, 0.80, 20 * 1920, False, None, "frames@25Hz", 25, 1920, 48000, "f5b-test")
    decoded = dec.decode_batch_unpadded(
        vae=vae,
        unpadded_items=[("m1", unpadded[0][1], est1), ("m2", unpadded[1][1], est2)],
    )
    # Each member decoded at its true unpadded length (no cross-item padded decode)
    assert vae.decoded_shapes == [(1, 64, 12), (1, 64, 20)]
    assert decoded[0][1].sample_count == 12 * 1920
    assert decoded[1][1].sample_count == 20 * 1920
    assert len(decoded[0][2]) == 12 * 1920 * 4


def test_f5bc_04_versioned_cache_privacy_ttl_capacity_and_borrower_accounting() -> None:
    clock = HarnessClock()
    store = VersionedCacheStore(
        clock=clock,
        max_entries=2,
        max_bytes=16384,
        max_entry_bytes=8192,
        ttl_ns=10_000_000_000,
        private_cache_enabled=True,
        max_private_entries_per_session=2,
        max_private_bytes_per_session=8192,
        private_ttl_ns=5_000_000_000,
        allowlisted_public_templates=frozenset({"greeting_v1"}),
    )

    plan = _make_plan()
    snap = pin_synthesis_snapshot(plan)
    desc1 = StrictSynthesisCacheAdapter.build_canonical_descriptor(chunk=plan.chunks[0], snapshot=snap)
    desc_diff_lex = StrictSynthesisCacheAdapter.build_canonical_descriptor(
        chunk=plan.chunks[0],
        snapshot=snap,
        quality_policy_revision="f5b-quality-v2",
    )
    assert desc1.digest() != desc_diff_lex.digest()

    # Unknown PII provenance => BYPASS
    el_unknown = store.classify_eligibility(
        session_id="s1",
        is_public_template=True,
        template_id="greeting_v1",
        contains_pii=None,
    )
    assert el_unknown.kind == CacheEligibilityKind.BYPASS

    # PII => BYPASS
    el_pii = store.classify_eligibility(
        session_id="s1",
        is_public_template=True,
        template_id="greeting_v1",
        contains_pii=True,
    )
    assert el_pii.kind == CacheEligibilityKind.BYPASS

    # Approved public template
    el_pub = store.classify_eligibility(
        session_id="s1",
        is_public_template=True,
        template_id="greeting_v1",
        contains_pii=False,
    )
    assert el_pub.kind == CacheEligibilityKind.PUBLIC_TEMPLATE

    payload = b"\x00\x00\x80\x3f" * 512  # 2048 bytes (512 samples of 1.0f)
    assert store.put(
        descriptor=desc1,
        eligibility=el_pub,
        payload=payload,
        sample_count=512,
        audio_format=RAW_AUDIO_FORMAT,
    )
    entry, reason = store.get(descriptor=desc1, eligibility=el_pub)
    assert entry is not None and reason == "VERIFIED_RAW_CACHE_HIT"
    assert store.stats().active_borrowers == 1

    # Evict via capacity while borrowed -> retired_bytes tracked until released
    plan2 = _make_plan(texts=("İkinci metin.",))
    desc2 = StrictSynthesisCacheAdapter.build_canonical_descriptor(chunk=plan2.chunks[0], snapshot=snap)
    plan3 = _make_plan(texts=("Üçüncü metin.",))
    desc3 = StrictSynthesisCacheAdapter.build_canonical_descriptor(chunk=plan3.chunks[0], snapshot=snap)
    assert store.put(descriptor=desc2, eligibility=el_pub, payload=payload, sample_count=512, audio_format=RAW_AUDIO_FORMAT)
    assert store.put(descriptor=desc3, eligibility=el_pub, payload=payload, sample_count=512, audio_format=RAW_AUDIO_FORMAT)
    stats_mid = store.stats()
    assert stats_mid.entry_count == 2
    assert stats_mid.retired_bytes == 2048
    store.release_borrow(entry)
    assert store.stats().retired_bytes == 0

    # Private session isolation & immediate invalidation
    el_priv_s1 = store.classify_eligibility(session_id="s1", allow_private_session=True, contains_pii=False)
    el_priv_s2 = store.classify_eligibility(session_id="s2", allow_private_session=True, contains_pii=False)
    assert store.put(descriptor=desc1, eligibility=el_priv_s1, payload=payload, sample_count=512, audio_format=RAW_AUDIO_FORMAT)
    hit_s2, _ = store.get(descriptor=desc1, eligibility=el_priv_s2)
    assert hit_s2 is None
    assert store.invalidate_session("s1") == 1
    hit_s1_after, _ = store.get(descriptor=desc1, eligibility=el_priv_s1)
    assert hit_s1_after is None

    # Monotonic TTL expiry
    clock.advance_ns(15_000_000_000)
    hit_expired, _ = store.get(descriptor=desc2, eligibility=el_pub)
    assert hit_expired is None


def test_f5bc_05_quality_guard_structural_silence_and_dbfs() -> None:
    guard = QualityGuard(max_near_zero_fraction=0.5, max_silence_ms=200.0, calibrated_thresholds_approved=False)

    # Zero-energy buffer -> FAIL, rms_dbfs is None (never -inf / log10(0))
    zeros = np.zeros(4800, dtype=np.float32).tobytes()
    res_zero = guard.assess(payload=zeros, sample_count=4800, audio_format=RAW_AUDIO_FORMAT)
    assert not res_zero.structurally_valid
    assert res_zero.quality_status == QualityStatus.FAIL
    assert res_zero.rms_dbfs is None
    assert res_zero.retryable is True

    # Valid sine wave -> structurally valid, QualityStatus.UNKNOWN (uncalibrated)
    t = np.arange(4800, dtype=np.float32) / 48000.0
    sine = (0.2 * np.sin(2.0 * np.pi * 220.0 * t)).astype("<f4").tobytes()
    res_ok = guard.assess(payload=sine, sample_count=4800, audio_format=RAW_AUDIO_FORMAT)
    assert res_ok.structurally_valid
    assert res_ok.quality_status == QualityStatus.UNKNOWN
    assert res_ok.rms_dbfs is not None and math.isfinite(res_ok.rms_dbfs)

    # Calibrated + collapse guard -> QualityStatus.PASS
    cal_guard = QualityGuard(calibrated_thresholds_approved=True)
    res_cal = cal_guard.assess(
        payload=sine,
        sample_count=4800,
        audio_format=RAW_AUDIO_FORMAT,
        collapse_guard_fn=lambda _w, _sr: 0.85,
    )
    assert res_cal.structurally_valid and res_cal.quality_status == QualityStatus.PASS


@pytest.mark.asyncio
async def test_f5bc_06_same_seed_recovery_bounded_and_uncertain_blocked() -> None:
    clock = HarnessClock()
    sched = _make_scheduler(clock)
    dit = _FakeDiT()
    vae = _FakeVAE(silent_first_n=1)
    _register_fake_handles(sched, dit, vae)

    # First attempt produces silent output -> recovery enabled retries ONCE with same seed 42
    pipe = NeuralSynthesisPipeline(
        scheduler=sched,
        recovery_policy=SameSeedRecoveryPolicy(enabled=True, clock=clock),
    )
    plan = _make_plan(seed=42, voice_profile="leyla-warm-42")
    out = await pipe.synthesize_plan(plan, pin_kwargs={"allow_experimental_seeds": True})
    assert out.status == "COMPLETED"
    assert len(out.accepted_chunks) == 1
    assert out.accepted_chunks[0].seed == 42
    assert dit.calls == 2
    assert vae.calls == 2

    # Uncertain device state must NEVER retry
    sched2 = _make_scheduler(clock)
    dit_uncertain = _FakeDiT(fail_first_n=5, uncertain_on_fail=True)
    vae2 = _FakeVAE()
    _register_fake_handles(sched2, dit_uncertain, vae2)
    pipe2 = NeuralSynthesisPipeline(
        scheduler=sched2,
        recovery_policy=SameSeedRecoveryPolicy(enabled=True, clock=clock),
    )
    plan2 = _make_plan(session_id="sess-unc", seed=42, voice_profile="leyla-warm-42")
    out2 = await pipe2.synthesize_plan(plan2, pin_kwargs={"allow_experimental_seeds": True})
    assert out2.status == "FAILED"
    assert out2.quarantined is True
    assert dit_uncertain.calls == 1


# ---------------------------------------------------------------------------
# F5-C Tests: Adaptive ODE Profiles, Deadline Micro-Batching, Speaker/Pitch Lab
# ---------------------------------------------------------------------------


def test_f5bc_07_adaptive_profile_selector_and_control_disposition() -> None:
    sel_base = AdaptiveProfileSelector(mode="BASELINE_ONLY")
    pick_base = sel_base.select(latent_frames=40, requested_profile_id="euler_16")
    assert pick_base.effective_descriptor.profile_id == "euler_32"
    assert pick_base.effective_descriptor.profile.steps == 32

    # SHADOW mode compares without changing effective profile
    sel_shadow = AdaptiveProfileSelector(mode="SHADOW")
    pick_shadow = sel_shadow.select(latent_frames=40, is_critical_speech=False)
    assert pick_shadow.effective_descriptor.profile_id == "euler_32"
    assert pick_shadow.shadow_recommended_id == "euler_8"

    # ADAPTIVE_OPT_IN with calibrated euler_16
    cat = sel_base.catalog.copy()
    cat["euler_16"] = DiscreteSolverDescriptor(
        profile_id="euler_16",
        profile_revision="f5c-cal-v1",
        profile=SolverProfile(
            solver_name=BASELINE_SOLVER,
            steps=16,
            approved_for_strict=False,
            profile_id="euler_16",
            calibration_status="CALIBRATED",
            active_for_live=True,
        ),
        capability_state=CapabilityState.VERIFIED,
        calibration_status="CALIBRATED",
        active_for_live=True,
        quality_floor_score=0.95,
        max_allowed_for_critical_speech=False,
    )
    sel_opt = AdaptiveProfileSelector(catalog=cat, mode="ADAPTIVE_OPT_IN")
    pick_fast = sel_opt.select(latent_frames=40, is_critical_speech=False, min_quality_floor=0.90)
    assert pick_fast.effective_descriptor.profile_id == "euler_16"

    # Critical speech never downgrades below baseline
    pick_crit = sel_opt.select(latent_frames=40, is_critical_speech=True, min_quality_floor=0.90)
    assert pick_crit.effective_descriptor.profile_id == "euler_32"

    # Control disposition: F6 WSOLA vs NONE vs F5 native
    disp_f6 = AdaptiveProfileSelector.resolve_speed_control(requested_speed=0.95, native_speed_supported=False)
    assert disp_f6.assigned_owner == "F6"
    disp_none = AdaptiveProfileSelector.resolve_speed_control(requested_speed=0.90, native_speed_supported=False)
    assert disp_none.assigned_owner == "NONE"


def test_f5bc_08_deadline_batch_former_priority_bucketing_and_m06_budget() -> None:
    clock = HarnessClock()
    probe = FakeGPUProbeAdapter(clock)
    budget = MemoryBudget(clock=clock)
    budget.update_probe(probe.valid_probe(free_mib=4096))
    former = DeadlineBatchFormer(max_batch_size=4, max_wait_ms=12.0, max_padding_fraction=0.25)

    now = clock.monotonic_ns()
    c_p2 = BatchCandidate("p2-1", 10, 20, 20 * 1920, 64, "euler32", PriorityClass.P2, now, now + 500_000_000, 9)
    c_p4_a = BatchCandidate("p4-a", 12, 22, 22 * 1920, 64, "euler32", PriorityClass.P4, now + 1, now + 500_000_000, 9)
    c_p4_b = BatchCandidate("p4-b", 14, 24, 24 * 1920, 64, "euler32", PriorityClass.P4, now + 2, now + 500_000_000, 42)
    c_expired = BatchCandidate("exp-1", 10, 20, 20 * 1920, 64, "euler32", PriorityClass.P4, now, now - 1, 9)

    dec = former.form_batches(
        candidates=[c_p2, c_p4_a, c_p4_b, c_expired],
        now_monotonic_ns=now,
        memory_budget=budget,
    )
    # Expired candidate rejected; P2 never mixed with P4; urgent P2 => 0 wait
    assert dec.rejected_member_ids == ("exp-1",)
    assert dec.formation_wait_ns == 0
    assert len(dec.batches) == 2
    assert dec.batches[0].member_ids == ("p2-1",)
    assert dec.batches[1].member_ids == ("p4-a", "p4-b")
    assert dec.batches[1].padding_fraction <= 0.25


def test_f5bc_09_speaker_and_pitch_intelligence_cpu_safe_seam() -> None:
    evaluator = SpeakerIntelligenceEvaluator()

    bad_manifest = SpeakerReferenceManifest(
        reference_id="ref-unconsented",
        voice_profile="Leyla",
        seed=9,
        corpus_hash="abc123",
        consent_and_license_verified=False,
        lab_scope_only=True,
        source_sample_rate_hz=48000,
        source_channels=1,
        preprocessing_revision="prep-v1",
    )
    res_rej = evaluator.assess_speaker_embeddings(
        candidate_id="cand-1",
        manifest=bad_manifest,
        candidate_embedding=[1.0, 0.0],
        reference_embedding=[1.0, 0.0],
        duration_sec=1.0,
    )
    assert res_rej.outcome == "REJECTED_MANIFEST"
    assert res_rej.identity_verified is False

    good_manifest = SpeakerReferenceManifest(
        reference_id="ref-leyla",
        voice_profile="Leyla",
        seed=9,
        corpus_hash="sha256:deadbeef",
        consent_and_license_verified=True,
        lab_scope_only=True,
        source_sample_rate_hz=48000,
        source_channels=1,
        preprocessing_revision="prep-v1",
    )
    res_ok = evaluator.assess_speaker_embeddings(
        candidate_id="cand-1",
        manifest=good_manifest,
        candidate_embedding=[1.0, 1.0],
        reference_embedding=[1.0, 1.0],
        duration_sec=1.0,
    )
    assert res_ok.outcome == "EVALUATED"
    assert res_ok.cosine_similarity is not None and math.isclose(res_ok.cosine_similarity, 1.0, rel_tol=1e-6)
    assert res_ok.identity_verified is False

    # Zero-norm embedding => INVALID_EMBEDDING, cosine_similarity=None
    res_zero_norm = evaluator.assess_speaker_embeddings(
        candidate_id="cand-z",
        manifest=good_manifest,
        candidate_embedding=[0.0, 0.0],
        reference_embedding=[1.0, 0.0],
        duration_sec=1.0,
    )
    assert res_zero_norm.outcome == "INVALID_EMBEDDING" and res_zero_norm.cosine_similarity is None

    # Pitch assessment on 220 Hz sine wave vs silence
    t = np.arange(24000, dtype=np.float32) / 48000.0
    sine = 0.25 * np.sin(2.0 * np.pi * 220.0 * t)
    pitch_ok = evaluator.assess_pitch_cpu(waveform_f32=sine, sample_rate_hz=48000)
    assert pitch_ok.outcome == "EVALUATED"
    assert pitch_ok.f0_median_hz is not None and 210.0 <= pitch_ok.f0_median_hz <= 230.0
    assert pitch_ok.voiced_fraction is not None and pitch_ok.voiced_fraction > 0.8

    pitch_silent = evaluator.assess_pitch_cpu(waveform_f32=np.zeros(24000, dtype=np.float32), sample_rate_hz=48000)
    assert pitch_silent.outcome == "UNVOICED_OR_SILENT"
    assert pitch_silent.f0_median_hz is None
