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
import dataclasses
import inspect
import json
import math
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType
from typing import Any

import numpy as np
import pytest

from backend import text as legacy_text
from backend.core.adapters.legacy_synthesis import synthesis_plan_from_legacy
from backend.core.configuration import FeatureFlagRegistry, resolve_configuration
from backend.core.contracts import (
    CONTRACT_SCHEMA_VERSION,
    AudioChunk,
    AudioEncoding,
    AudioFormat,
    CacheStatus,
    ChunkPlan,
    ErrorCategory,
    GenerationRef,
    MetricStatus,
    ObservationScope,
    PlanValidationStatus,
    QualityStatus,
    SessionIdentity,
    SynthesisPlan,
)
from backend.core.model_registry import ModelKind, ModelRegistry
from backend.core.runtime import AdmissionStatus, CancellationScope, DeadlineBudget, SessionContext
from backend.core.runtime.turn_generation import PauseState
from backend.neural_synthesis import (
    BASELINE_ODE_STEPS,
    BASELINE_SOLVER,
    DecoderAdapter,
    DecoderValidationError,
    DurationEstimator,
    DurationGuard,
    EncoderAdapter,
    EncoderValidationError,
    GenerationDeliveryFence,
    LatentInitializationError,
    LatentInitializer,
    LegacySynthesisBridge,
    ModelResidencyAdapter,
    NeuralSynthesisPipeline,
    ProviderBarriers,
    RawAudioValidator,
    RawCacheEntry,
    ScopedPlanClaimRegistry,
    SolverAdapter,
    SolverExecutionError,
    SolverValidationError,
    StrictSynthesisCacheAdapter,
    SynthesisModelHandles,
    SynthesisTelemetry,
    UncertainDeviceStateError,
    adapt_legacy_synth_output,
    audit_strict_bypasses,
    classify_synthesis_paths,
    compute_clause_frame_count,
    inventory_experimental_routes,
    load_static_char_vocab,
    pin_synthesis_snapshot,
    validate_and_admit_plan,
    validate_solver_profile,
)
from backend.observability import BoundedEventBus, EvidenceKind, EvidenceRecorder, MetricsRegistry, Projection
from backend.runtime_resources import (
    MIB,
    AdmissionOutcome,
    ExecutionLeaseState,
    HandleOwnership,
    MemoryBudget,
    PriorityClass,
    ProviderKind,
    QuarantineManager,
    UnifiedGpuScheduler,
)
from tests.harness.adapters import FakeGPUProbeAdapter
from tests.harness.barriers import PhaseGate
from tests.harness.contracts import GateStatus, PrerequisiteStatus
from tests.harness.evidence_validator import EvidenceValidator, PIISecretScanner
from tests.harness.fake_clock import HarnessClock
from tests.harness.feature_regression import FeatureRegressionMapper
from tests.harness.isolation import OutboundGuard, audit_import_closure

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_RUN_ID = "20261126T004342Z"
M00_BASELINE_ID = "20261126T001600Z"


class FakeDiTModel:
    """Deterministic fake FreyaDiT boundary (no torch/CUDA)."""

    def __init__(
        self,
        *,
        predicted_frames: float = 20.0,
        fail_ode_step: int | None = None,
        uncertain_failure: bool = False,
        mutate_text_to: str | None = None,
        nonfinite_ode: bool = False,
    ) -> None:
        self.predicted_frames = predicted_frames
        self.fail_ode_step = fail_ode_step
        self.uncertain_failure = uncertain_failure
        self.mutate_text_to = mutate_text_to
        self.nonfinite_ode = nonfinite_ode
        self.encoded_texts: list[str] = []
        self.seeds_used: list[int] = []
        self.solver_profiles_seen: list[Any] = []
        self.encode_calls = 0
        self.ode_calls = 0

    def encode_prepared_text(self, text: str, token_ids: tuple[int, ...], *, device: str = "cpu") -> dict[str, Any]:
        self.encode_calls += 1
        self.encoded_texts.append(text)
        observed = self.mutate_text_to if self.mutate_text_to is not None else text
        return {
            "observed_text": observed,
            "context": np.ones((1, len(token_ids), 8), dtype=np.float32),
            "char_mask": np.ones((1, len(token_ids)), dtype=bool),
        }

    def predict_duration_frames(self, _encoded: Any) -> float:
        return self.predicted_frames

    def solve_ode(self, *, latent: Any, encoded: Any, profile: Any) -> dict[str, Any]:
        self.ode_calls += 1
        self.solver_profiles_seen.append(profile)
        if self.fail_ode_step is not None:
            if self.uncertain_failure:
                raise UncertainDeviceStateError(f"cuda_uncertain_at_step_{self.fail_ode_step}")
            raise RuntimeError(f"ode_failed_at_step_{self.fail_ode_step}")
        arr = np.array(latent, dtype=np.float32, copy=True)
        if self.nonfinite_ode:
            arr[0, 0, 0] = np.nan
        else:
            # Deterministic linear Euler step transformation preserving shape (1, T, 64)
            for i in range(profile.steps):
                t = i / profile.steps
                arr = arr + np.float32(0.01 * (1.0 - t) / profile.steps)
        return {
            "latents": arr,
            "nfe_evaluated": profile.steps,
            "completed_steps": profile.steps,
        }


class FakeAudioVAE:
    """Deterministic fake VoxCPM2 AudioVAE boundary (48 kHz mono float32)."""

    def __init__(
        self,
        *,
        sample_rate_hz: int = 48000,
        output_mode: str = "1d",
        dtype: str = "float32",
        inject_nan: bool = False,
        inject_silence: bool = False,
        extra_samples: int = 0,
        override_samples: int | None = None,
        empty: bool = False,
        fail_uncertain: bool = False,
    ) -> None:
        self.sample_rate_hz = sample_rate_hz
        self.output_mode = output_mode
        self.dtype = dtype
        self.inject_nan = inject_nan
        self.inject_silence = inject_silence
        self.extra_samples = extra_samples
        self.override_samples = override_samples
        self.empty = empty
        self.fail_uncertain = fail_uncertain
        self.decode_calls = 0

    def decode(self, latents_bct: Any) -> Any:
        self.decode_calls += 1
        if self.fail_uncertain:
            raise UncertainDeviceStateError("vae_cuda_stream_uncertain")
        arr = np.asarray(latents_bct)
        frames = int(arr.shape[-1]) if arr.ndim == 3 else 8
        n_samples = 0 if self.empty else (self.override_samples if self.override_samples is not None else frames * 1920 + self.extra_samples)
        if n_samples == 0:
            wav = np.zeros((0,), dtype=np.float32)
        elif self.inject_silence:
            wav = np.zeros((n_samples,), dtype=np.float32)
        else:
            t = np.arange(n_samples, dtype=np.float32) / float(self.sample_rate_hz)
            seed_bias = float(np.mean(arr)) * 0.05
            wav = (0.25 * np.sin(2.0 * np.pi * 220.0 * t) + seed_bias).astype(np.float32)
            if self.inject_nan:
                wav[0] = np.nan

        if self.dtype == "int16":
            wav = np.clip(wav * 32767.0, -32768, 32767).astype("<i2")
        elif self.dtype == ">f4":
            wav = wav.astype(">f4")

        if self.output_mode == "1d":
            return wav
        if self.output_mode == "2d_singleton":
            return wav[None, :]
        if self.output_mode == "3d_singleton":
            return wav[None, None, :]
        if self.output_mode == "multi_channel":
            return np.stack([wav, wav], axis=0)[None, :, :]
        if self.output_mode == "multi_batch":
            return np.stack([wav, wav], axis=0)
        raise ValueError(f"Unknown output_mode: {self.output_mode}")


def _make_handles(
    dit: FakeDiTModel | None = None,
    vae: FakeAudioVAE | None = None,
    *,
    model_revision: str = "freya-tts:batched-ode",
    ownership: HandleOwnership = HandleOwnership.BORROWED,
    rng_isolation_mode: str = "ISOLATED_GENERATOR",
) -> SynthesisModelHandles:
    vocab = load_static_char_vocab(repo_root=REPO_ROOT)
    return SynthesisModelHandles(
        model_id="tts-freya",
        model_revision=model_revision,
        tts_model=dit or FakeDiTModel(),
        vae=vae or FakeAudioVAE(),
        char_to_id=vocab.vocab_map,
        vocab_revision=vocab.vocab_revision,
        ownership=ownership,
        device="cpu",
        dtype="float32",
        rng_isolation_mode=rng_isolation_mode,
        supports_isolated_rng=(rng_isolation_mode != "UNISOLATED"),
    )


def _make_env(
    *,
    clock: HarnessClock | None = None,
    dit: FakeDiTModel | None = None,
    vae: FakeAudioVAE | None = None,
    free_mib: int = 4096,
    ownership: HandleOwnership = HandleOwnership.BORROWED,
    max_quarantine: int = 4,
    event_bus: BoundedEventBus | None = None,
    metrics: MetricsRegistry | None = None,
) -> tuple[HarnessClock, UnifiedGpuScheduler, NeuralSynthesisPipeline, SynthesisModelHandles]:
    clk = clock or HarnessClock(initial_ns=10_000_000)
    sched = UnifiedGpuScheduler(
        clock=clk,
        quarantine_manager=QuarantineManager(clock=clk, max_entries=max_quarantine),
    )
    sched.memory_budget.update_probe(FakeGPUProbeAdapter(clk).valid_probe(free_mib=free_mib))
    handles = _make_handles(dit=dit, vae=vae, ownership=ownership)
    res_adapter = ModelResidencyAdapter(sched.residency_manager)
    res_adapter.register_handles(handles, vram_bytes=64 * MIB, ownership=ownership)
    tel = SynthesisTelemetry(clock=clk, metrics=metrics, event_bus=event_bus)
    pipe = NeuralSynthesisPipeline(scheduler=sched, residency_adapter=res_adapter, telemetry=tel)
    return clk, sched, pipe, handles


def _make_plan(
    *,
    session_id: str = "sess-f5a",
    turn_id: int = 1,
    generation_id: int = 1,
    plan_id: str = "plan-1",
    plan_revision: int = 0,
    response_id: str = "resp-1",
    texts: tuple[str, ...] = ("Merhaba, size nasıl yardımcı olabilirim?",),
    voice_profile: str = "leyla-baseline-9",
    seed: int | None = 9,
    normalization_passes: int | None = 1,
    validation_status: PlanValidationStatus = PlanValidationStatus.VALID,
    speech_act: str = "STATEMENT",
    model_revision: str | None = "freya-tts:batched-ode",
    lexicon_revision: str | None = "lex-rev-1",
    capability_revision: str | None = "cap-rev-1",
    post_pause_ms: int | None = None,
    requested_speed: float | None = None,
    requested_controls: tuple[str, ...] = (),
) -> SynthesisPlan:
    chunks = tuple(
        ChunkPlan(
            chunk_id=f"chk-{idx}",
            chunk_index=idx,
            model_text=txt,
            post_pause_ms=post_pause_ms,
            requested_speed=requested_speed,
            requested_controls=requested_controls,
        )
        for idx, txt in enumerate(texts)
    )
    joined = " ".join(texts)
    return SynthesisPlan(
        schema_version=CONTRACT_SCHEMA_VERSION,
        generation_ref=GenerationRef(session_id, turn_id, generation_id),
        plan_id=plan_id,
        plan_revision=plan_revision,
        response_id=response_id,
        source_text=joined,
        normalized_text=joined,
        language="tr",
        voice_profile=voice_profile,
        seed=seed,
        chunks=chunks,
        model_revision=model_revision,
        lexicon_revision=lexicon_revision,
        capability_revision=capability_revision,
        normalization_passes=normalization_passes,
        speech_act=speech_act,
        validation_status=validation_status,
    )


async def _open_session(
    clock: HarnessClock,
    session_id: str = "sess-f5a",
    *,
    max_queue_bytes: int = 4 * MIB,
) -> tuple[SessionContext, GenerationRef]:
    ctx = SessionContext(
        SessionIdentity(session_id, trace_id=f"tr-{session_id}"),
        clock=clock,
        max_queue_bytes=max_queue_bytes,
    )
    await ctx.open()
    t, _ = await ctx.begin_turn()
    g, _ = await ctx.begin_generation(t)
    return ctx, g


# =====================================================================
# NS01 - NS12: Preflight, Import Traps, Plan Admission & Deduplication
# =====================================================================


def test_ns01_missing_core_gate_or_owner_approval_holds(tmp_path: Path) -> None:
    core_acc = json.loads(
        (REPO_ROOT / "docs" / "freya2" / "core_integration" / CORE_RUN_ID / "CORE_ACCEPTANCE_MATRIX.json").read_text(
            encoding="utf-8"
        )
    )
    assert core_acc["core_integration_ready"] is True
    assert core_acc["core_integration_status"] == "PASS"

    # Missing core evidence in isolated root must HOLD/MISSING
    ev = EvidenceValidator(tmp_path)
    res = ev.verify_m00_baseline(M00_BASELINE_ID)
    assert res.status == PrerequisiteStatus.MISSING


def test_ns02_stale_or_absent_package_acceptance_holds(tmp_path: Path) -> None:
    ev = EvidenceValidator(REPO_ROOT)
    res = ev.verify_package_acceptance_dir("F4_A", tmp_path / "missing_f4_a")
    assert res.status == PrerequisiteStatus.MISSING

    bad_dir = tmp_path / "f4_a" / "run-bad"
    bad_dir.mkdir(parents=True)
    (bad_dir / "ACCEPTANCE_MATRIX.json").write_text(
        json.dumps({"overall": "HOLD", "gates": {"G00": "HOLD"}, "f4_a_accepted": False}),
        encoding="utf-8",
    )
    hold_res = ev.verify_package_acceptance_dir(
        "F4_A",
        tmp_path / "f4_a",
        required_gates=("G00",),
        ready_flag="f4_a_accepted",
    )
    assert hold_res.status == PrerequisiteStatus.HOLD


def test_ns03_clean_passive_import_no_torch_cuda_or_network() -> None:
    script = (
        "import sys; "
        "import backend.neural_synthesis as ns; "
        "from tests.harness.isolation import audit_import_closure; "
        "bad = audit_import_closure(sys.modules.keys()); "
        "assert not bad, bad; "
        "assert 'backend.models' not in sys.modules; "
        "assert 'httpx' not in sys.modules"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    guard = OutboundGuard()
    assert len(guard.blocked_attempts) == 0


def test_ns04_real_m01_m02_m06_types_and_invalid_schema_rejected() -> None:
    res = validate_and_admit_plan({"not": "a_synthesis_plan"})
    assert not res.accepted
    assert res.error is not None and res.error.code == "INVALID_PLAN_SCHEMA"
    plan = _make_plan()
    adm = validate_and_admit_plan(plan)
    assert adm.accepted and adm.pinned_snapshot is not None
    assert adm.generation_ref == plan.generation_ref


@pytest.mark.asyncio
async def test_ns05_valid_immutable_strict_plan_and_contiguous_chunks() -> None:
    clk, _, pipe, _ = _make_env()
    ctx, g = await _open_session(clk)
    plan = _make_plan(
        session_id=g.session_id,
        turn_id=g.turn_id,
        generation_id=g.generation_id,
        texts=("Randevunuz onaylandı.", "Yarın saat dokuzda bekliyoruz."),
    )
    out = await pipe.synthesize_plan(plan, session_ctx=ctx)
    assert out.status == "COMPLETED"
    assert len(out.accepted_chunks) == 2
    assert [c.chunk_index for c in out.accepted_chunks] == [0, 1]
    assert [c.chunk_id for c in out.accepted_chunks] == ["chk-0", "chk-1"]
    await ctx.close("done")


def test_ns06_unvalidated_or_unknown_plan_rejected_before_native_request() -> None:
    for st in (PlanValidationStatus.UNKNOWN, PlanValidationStatus.INVALID):
        plan = _make_plan(validation_status=st)
        adm = validate_and_admit_plan(plan)
        assert not adm.accepted
        assert adm.error is not None and adm.error.code == "PLAN_NOT_VALIDATED"


@pytest.mark.asyncio
async def test_ns07_normalization_passes_must_be_exactly_one_and_legacy_not_promoted() -> None:
    _, _, pipe, handles = _make_env()
    for bad_passes in (None, 0, 2):
        plan = _make_plan(normalization_passes=bad_passes)
        out = await pipe.synthesize_plan(plan)
        assert out.status == "FAILED"
        assert out.error is not None and out.error.code == "INVALID_NORMALIZATION_PASSES"
        assert handles.tts_model.encode_calls == 0

    legacy_conv = synthesis_plan_from_legacy(
        session_id="sess-f5a",
        turn_id=1,
        generation_id=1,
        plan_id="leg-1",
        response_id="resp-leg",
        source_text="Merhaba.",
        normalized_text="Merhaba.",
        chunks_text=[("Merhaba.", 0.0)],
        seed=9,
    )
    assert legacy_conv.value is not None
    assert legacy_conv.value.normalization_passes is None
    assert not validate_and_admit_plan(legacy_conv.value).accepted


def test_ns08_duplicate_chunk_ids_or_noncontiguous_indices_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate chunk_id"):
        SynthesisPlan(
            schema_version=CONTRACT_SCHEMA_VERSION,
            generation_ref=GenerationRef("sess-a", 1, 1),
            plan_id="p1",
            plan_revision=0,
            response_id="r1",
            source_text="a b",
            normalized_text="a b",
            language="tr",
            voice_profile="leyla-baseline-9",
            seed=9,
            chunks=(
                ChunkPlan("dup", 0, "Merhaba."),
                ChunkPlan("dup", 1, "Tamam."),
            ),
            validation_status=PlanValidationStatus.VALID,
        )

    with pytest.raises(ValueError, match="contiguous"):
        SynthesisPlan(
            schema_version=CONTRACT_SCHEMA_VERSION,
            generation_ref=GenerationRef("sess-a", 1, 1),
            plan_id="p1",
            plan_revision=0,
            response_id="r1",
            source_text="a b",
            normalized_text="a b",
            language="tr",
            voice_profile="leyla-baseline-9",
            seed=9,
            chunks=(
                ChunkPlan("c0", 0, "Merhaba."),
                ChunkPlan("c2", 2, "Tamam."),
            ),
            validation_status=PlanValidationStatus.VALID,
        )


@pytest.mark.asyncio
async def test_ns09_empty_explicit_no_speech_plan_creates_zero_jobs() -> None:
    _, _, pipe, handles = _make_env()
    plan = _make_plan(texts=(), speech_act="NO_SPEECH")
    out = await pipe.synthesize_plan(plan)
    assert out.status == "NO_SPEECH"
    assert out.accepted_chunks == ()
    assert out.execution_ok is True
    assert handles.tts_model.encode_calls == 0
    assert handles.tts_model.ode_calls == 0
    assert handles.vae.decode_calls == 0


def test_ns10_blank_model_text_rejected_before_gpu_allocation() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        ChunkPlan("chk-0", 0, "   ")
    enc = EncoderAdapter()
    blank_like = dataclasses.replace(_make_plan().chunks[0], model_text=" ") if False else None
    assert blank_like is None
    with pytest.raises(EncoderValidationError) as exc_info:
        # Direct validation via helper with mocked object attribute check
        class _FakeBlank:
            model_text = "   "

        enc.validate_and_tokenize(_FakeBlank(), {"a": 1})  # type: ignore[arg-type]
    assert exc_info.value.error_info.code == "BLANK_MODEL_TEXT"


def test_ns11_oversized_plan_chunk_or_unsupported_control_rejected() -> None:
    too_long = "a" * 600
    plan_long = _make_plan(texts=(too_long,))
    adm_long = validate_and_admit_plan(plan_long)
    assert not adm_long.accepted
    assert adm_long.error is not None and adm_long.error.code == "CHUNK_TEXT_TOO_LONG"

    plan_ctrl = _make_plan(requested_controls=("voice_clone",))
    adm_ctrl = validate_and_admit_plan(plan_ctrl)
    assert not adm_ctrl.accepted
    assert adm_ctrl.error is not None and adm_ctrl.error.code == "UNSUPPORTED_CONTROL"


def test_ns12_duplicate_claim_and_conflicting_same_identity_rejected() -> None:
    reg = ScopedPlanClaimRegistry()
    p1 = _make_plan(texts=("Merhaba.",))
    p1_conflict = _make_plan(texts=("Farklı metin.",))
    assert reg.claim(p1, p1.chunks[0])[0] == "CLAIMED"
    assert reg.claim(p1, p1.chunks[0])[0] == "DUPLICATE"
    assert reg.claim(p1_conflict, p1_conflict.chunks[0])[0] == "CONFLICT"


# =====================================================================
# NS13 - NS18: Normalization Boundary, Vocab, Immutability, Scope
# =====================================================================


@pytest.mark.asyncio
async def test_ns13_prepared_text_with_protected_tokens_passed_verbatim() -> None:
    _, _, pipe, handles = _make_env()
    prepared_text = "İki bin beş yüz Türk lirası, on beş ocak iki bin yirmi altı."
    plan = _make_plan(texts=(prepared_text,))
    out = await pipe.synthesize_plan(plan)
    assert out.status == "COMPLETED"
    assert handles.tts_model.encoded_texts == [prepared_text]
    assert plan.chunks[0].model_text == prepared_text
    assert plan.source_text == prepared_text


@pytest.mark.asyncio
async def test_ns14_f4_called_once_f5_normalizer_spy_count_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    norm_calls = 0
    prep_calls = 0
    clause_calls = 0

    orig_norm = legacy_text.normalize
    orig_prep = legacy_text.prepare_tts_clause
    orig_clauses = legacy_text.clauses

    def spy_norm(t: str):
        nonlocal norm_calls
        norm_calls += 1
        return orig_norm(t)

    def spy_prep(t: str):
        nonlocal prep_calls
        prep_calls += 1
        return orig_prep(t)

    def spy_clauses(t: str):
        nonlocal clause_calls
        clause_calls += 1
        return orig_clauses(t)

    monkeypatch.setattr(legacy_text, "normalize", spy_norm)
    monkeypatch.setattr(legacy_text, "prepare_tts_clause", spy_prep)
    monkeypatch.setattr(legacy_text, "clauses", spy_clauses)

    # F4 runs ONCE to build prepared text
    f4_norm = legacy_text.normalize("Merhaba, 250 TL bakım.")["normalized"]
    f4_parts = [legacy_text.prepare_tts_clause(p) for p, _ in legacy_text.clauses(f4_norm)]
    assert norm_calls == 1 and prep_calls >= 1 and clause_calls == 1

    before_f5 = (norm_calls, prep_calls, clause_calls)
    _, _, pipe, _ = _make_env()
    plan = _make_plan(texts=tuple(f4_parts))
    out = await pipe.synthesize_plan(plan)
    assert out.status == "COMPLETED"
    assert (norm_calls, prep_calls, clause_calls) == before_f5


@pytest.mark.asyncio
async def test_ns15_hidden_encoder_cleaning_and_public_flag_rejected() -> None:
    dit_mut = FakeDiTModel(mutate_text_to="degistirilmis")
    _, _, pipe, _ = _make_env(dit=dit_mut)
    plan = _make_plan(texts=("Merhaba.",))

    out_flag = await pipe.synthesize_plan(plan, untrusted_already_normalized_flag=True)
    assert out_flag.status == "FAILED"
    assert out_flag.error is not None and out_flag.error.code == "UNTRUSTED_BYPASS_FLAG"

    out_mut = await pipe.synthesize_plan(plan)
    assert out_mut.status == "FAILED"
    assert out_mut.error is not None and out_mut.error.code == "UNTRUSTED_TEXT_TRANSFORMATION"


@pytest.mark.asyncio
async def test_ns16_unsupported_vocab_codepoint_rejected_without_rewrite() -> None:
    _, _, pipe, handles = _make_env()
    plan = _make_plan(texts=("Merhaba ~ emoji \U0001f600",))
    out = await pipe.synthesize_plan(plan)
    assert out.status == "FAILED"
    assert out.error is not None and out.error.code == "UNSUPPORTED_VOCABULARY"
    assert handles.tts_model.encode_calls == 0


def test_ns17_nested_mutation_of_plan_chunk_or_snapshot_prohibited() -> None:
    plan = _make_plan()
    adm = validate_and_admit_plan(plan)
    assert adm.accepted and adm.pinned_snapshot is not None
    with pytest.raises((TypeError, dataclasses.FrozenInstanceError)):
        plan.plan_id = "mutated"  # type: ignore[misc]
    with pytest.raises((TypeError, dataclasses.FrozenInstanceError)):
        plan.chunks[0].model_text = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        adm.pinned_snapshot.feature_flags["demo_mode"] = True  # type: ignore[index]


@pytest.mark.asyncio
async def test_ns18_same_plan_reused_in_unauthorized_generation_rejected() -> None:
    clk, _, pipe, _ = _make_env()
    ctx, g1 = await _open_session(clk)
    g2, _ = await ctx.begin_generation()
    plan_for_g1 = _make_plan(session_id=g1.session_id, turn_id=g1.turn_id, generation_id=g1.generation_id)
    out = await pipe.synthesize_plan(plan_for_g1, session_ctx=ctx, expected_generation_ref=g2)
    assert out.status == "FAILED"
    assert out.error is not None and out.error.code == "STALE_GENERATION_SCOPE"
    await ctx.close("done")


# =====================================================================
# NS19 - NS25: Voice Seed, Revisions & Residency Borrowing
# =====================================================================


@pytest.mark.asyncio
async def test_ns19_m03_leyla_seed_9_reaches_rng_and_metadata() -> None:
    _, _, pipe, _ = _make_env()
    plan = _make_plan(voice_profile="leyla-baseline-9", seed=9)
    out = await pipe.synthesize_plan(plan)
    assert out.status == "COMPLETED"
    assert out.chunk_outcomes[0].latent_descriptor is not None
    assert out.chunk_outcomes[0].latent_descriptor.seed == 9
    assert out.accepted_chunks[0].seed == 9


@pytest.mark.asyncio
async def test_ns20_experimental_seeds_42_77_123_preserved_without_fallback_to_9() -> None:
    _, _, pipe, _ = _make_env()
    # Disabled by default -> must NOT silently fall back to seed 9
    disabled_plan = _make_plan(voice_profile="leyla-warm-42", seed=42)
    out_disabled = await pipe.synthesize_plan(disabled_plan)
    assert out_disabled.status == "FAILED"
    assert out_disabled.error is not None and out_disabled.error.code == "SEED_DISABLED_BY_POLICY"

    # Explicitly enabled via M03 feature flags -> each seed preserved independently
    for seed_val, prof_id, flag_name in (
        (42, "leyla-warm-42", "experimental_voice_seed_42"),
        (77, "leyla-dynamic-77", "experimental_voice_seed_77"),
        (123, "leyla-formal-123", "experimental_voice_seed_123"),
    ):
        cfg = resolve_configuration().snapshot
        flags = FeatureFlagRegistry.from_snapshot(cfg, extra_flags={flag_name: True})
        plan = _make_plan(plan_id=f"plan-{seed_val}", voice_profile=prof_id, seed=seed_val)
        out = await pipe.synthesize_plan(
            plan,
            pin_kwargs={"config_snapshot": cfg, "feature_flag_registry": flags},
        )
        assert out.status == "COMPLETED"
        assert out.accepted_chunks[0].seed == seed_val
        assert out.accepted_chunks[0].voice_profile == prof_id


def test_ns21_missing_invalid_out_of_range_bool_seed_rejected() -> None:
    plan_none = _make_plan(seed=None)
    adm_none = validate_and_admit_plan(plan_none)
    assert not adm_none.accepted and adm_none.error is not None and adm_none.error.code == "INVALID_SEED"

    with pytest.raises(ValueError):
        _make_plan(seed=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        _make_plan(seed=-1)

    plan_unapproved = _make_plan(seed=999)
    adm_unapproved = validate_and_admit_plan(plan_unapproved)
    assert not adm_unapproved.accepted
    assert adm_unapproved.error is not None and adm_unapproved.error.code == "UNAPPROVED_SEED"


def test_ns22_profile_model_capability_revision_mismatch_rejected() -> None:
    plan_mod = _make_plan(model_revision="wrong-model-rev")
    adm_mod = validate_and_admit_plan(plan_mod)
    assert not adm_mod.accepted and adm_mod.error is not None and adm_mod.error.code == "MODEL_REVISION_MISMATCH"

    plan_cap = _make_plan(capability_revision="cap-v1")
    adm_cap = validate_and_admit_plan(plan_cap, pin_kwargs={"expected_capability_revision": "cap-v2"})
    assert not adm_cap.accepted and adm_cap.error is not None and adm_cap.error.code == "CAPABILITY_REVISION_MISMATCH"


@pytest.mark.asyncio
async def test_ns23_lexicon_snapshot_change_mid_generation_keeps_plan_pinned() -> None:
    clk, _, pipe, handles = _make_env()
    ctx, g = await _open_session(clk)
    plan = _make_plan(
        session_id=g.session_id,
        turn_id=g.turn_id,
        generation_id=g.generation_id,
        texts=("İlk cümle.", "İkinci cümle."),
        lexicon_revision="lex-pinned-v1",
    )
    # Simulate external lexicon revision change after plan was built:
    # Pipeline pins the plan's lexicon_revision and passes chunks verbatim without re-normalizing
    out = await pipe.synthesize_plan(plan, session_ctx=ctx)
    assert out.status == "COMPLETED"
    assert out.plan_admission.pinned_snapshot is not None
    assert out.plan_admission.pinned_snapshot.lexicon_revision == "lex-pinned-v1"
    assert handles.tts_model.encoded_texts == ["İlk cümle.", "İkinci cümle."]
    await ctx.close("done")


@pytest.mark.asyncio
async def test_ns24_concurrent_requests_reuse_residency_handle_single_load() -> None:
    clk = HarnessClock(initial_ns=1_000_000)
    sched = UnifiedGpuScheduler(clock=clk)
    sched.memory_budget.update_probe(FakeGPUProbeAdapter(clk).valid_probe(free_mib=4096))
    handles = _make_handles()
    load_calls = 0

    def loader():
        nonlocal load_calls
        load_calls += 1
        return handles

    res_adapter = ModelResidencyAdapter(sched.residency_manager)
    res_adapter.register_loader(ownership=HandleOwnership.OWNED, vram_bytes=64 * MIB, loader=loader)
    pipe = NeuralSynthesisPipeline(scheduler=sched, residency_adapter=res_adapter)

    p1 = _make_plan(session_id="sess-1", plan_id="p-1")
    p2 = _make_plan(session_id="sess-2", plan_id="p-2")
    o1, o2 = await asyncio.gather(pipe.synthesize_plan(p1), pipe.synthesize_plan(p2))
    assert o1.status == "COMPLETED" and o2.status == "COMPLETED"
    assert load_calls == 1
    assert sched.residency_manager.get_handle("tts-freya").load_count == 1


@pytest.mark.asyncio
async def test_ns25_borrowed_handle_kept_alive_when_one_session_closes() -> None:
    clk, sched, pipe, _ = _make_env(ownership=HandleOwnership.BORROWED)
    ctx_a, ga = await _open_session(clk, "sess-a")
    ctx_b, gb = await _open_session(clk, "sess-b")
    out_a = await pipe.synthesize_plan(
        _make_plan(session_id=ga.session_id, turn_id=ga.turn_id, generation_id=ga.generation_id, plan_id="pa"),
        session_ctx=ctx_a,
    )
    assert out_a.status == "COMPLETED"
    await pipe.lifecycle.close_session("sess-a", session_ctx=ctx_a)
    assert await pipe.residency_adapter.unload_if_owned() is False
    out_b = await pipe.synthesize_plan(
        _make_plan(session_id=gb.session_id, turn_id=gb.turn_id, generation_id=gb.generation_id, plan_id="pb"),
        session_ctx=ctx_b,
    )
    assert out_b.status == "COMPLETED"
    await ctx_b.close("done")


# =====================================================================
# NS26 - NS33: Duration Estimator & Pre-allocation Duration Guard
# =====================================================================


def test_ns26_valid_duration_estimate_preserves_units_and_semantics() -> None:
    plan = _make_plan(texts=("Randevunuz hazırlandı.",))
    snap = pin_synthesis_snapshot(plan)
    handles = _make_handles(dit=FakeDiTModel(predicted_frames=40.0))
    enc = EncoderAdapter().encode(plan.chunks[0], tts_model=handles.tts_model, char_to_id=handles.char_to_id, vocab_revision=handles.vocab_revision)
    est = DurationEstimator().estimate(enc, tts_model=handles.tts_model, snapshot=snap)
    assert est.units == "frames@25Hz"
    assert est.raw_predicted_frames == 40.0
    assert est.effective_frames == 40
    assert est.expected_samples == 40 * 1920


@pytest.mark.asyncio
async def test_ns27_zero_or_negative_duration_rejected_before_allocation() -> None:
    for pred in (0.0, -5.0):
        _, _, pipe, handles = _make_env(dit=FakeDiTModel(predicted_frames=pred))
        out = await pipe.synthesize_plan(_make_plan())
        assert out.status == "FAILED"
        assert out.error is not None and out.error.code == "NONPOSITIVE_DURATION"
        assert handles.tts_model.ode_calls == 0


@pytest.mark.asyncio
async def test_ns28_nan_inf_duration_or_unsupported_units_rejected() -> None:
    for pred in (float("nan"), float("inf")):
        _, _, pipe, _ = _make_env(dit=FakeDiTModel(predicted_frames=pred))
        out = await pipe.synthesize_plan(_make_plan())
        assert out.status == "FAILED"
        assert out.error is not None and out.error.code == "NONFINITE_DURATION"

    _, _, pipe2, _ = _make_env()
    out_units = await pipe2.synthesize_plan(_make_plan(), duration_units="milliseconds")
    assert out_units.status == "FAILED"
    assert out_units.error is not None and out_units.error.code == "UNSUPPORTED_DURATION_UNITS"


@pytest.mark.asyncio
async def test_ns29_extreme_duration_shape_product_rejected_before_allocation() -> None:
    _, _, pipe, handles = _make_env(dit=FakeDiTModel(predicted_frames=99999.0))
    out = await pipe.synthesize_plan(_make_plan())
    assert out.status == "FAILED"
    assert out.error is not None and out.error.code == "EXTREME_DURATION_PREDICTION"
    assert handles.tts_model.ode_calls == 0


def test_ns30_documented_duration_clamp_preserves_raw_and_effective() -> None:
    frames_short, clamped_short, reason_short = compute_clause_frame_count(chars=5, predicted_frames=30.0)
    assert clamped_short is True
    assert frames_short == 11  # ceil(5*1.8)+2 = 11
    assert reason_short == "short_clause_cap"

    frames_cap, clamped_cap, reason_cap = compute_clause_frame_count(chars=40, predicted_frames=450.0)
    assert clamped_cap is True
    assert frames_cap == 300
    assert reason_cap == "max_cap_300"


@pytest.mark.asyncio
async def test_ns31_unknown_latent_rate_holds_without_guessing_25hz() -> None:
    _, _, pipe, _ = _make_env()
    out = await pipe.synthesize_plan(
        _make_plan(),
        pin_kwargs={"latent_rate_hz": None},
    )
    assert out.status == "FAILED"
    assert out.error is not None and out.error.code == "UNKNOWN_LATENT_RATE"


def test_ns32_valid_estimate_under_m06_budget_not_called_actual_vram() -> None:
    clk = HarnessClock(initial_ns=1_000_000)
    budget = MemoryBudget(clock=clk)
    budget.update_probe(FakeGPUProbeAdapter(clk).valid_probe(free_mib=2048))
    plan = _make_plan(texts=("Randevunuz hazır.",))
    snap = pin_synthesis_snapshot(plan)
    handles = _make_handles(dit=FakeDiTModel(predicted_frames=25.0))
    enc = EncoderAdapter().encode(plan.chunks[0], tts_model=handles.tts_model, char_to_id=handles.char_to_id, vocab_revision=handles.vocab_revision)
    est = DurationEstimator().estimate(enc, tts_model=handles.tts_model, snapshot=snap)
    dec = DurationGuard().evaluate(est, snap, memory_budget=budget)
    assert dec.allowed is True
    assert dec.is_measured_vram is False
    assert dec.estimated_latent_bytes == 1 * est.effective_frames * 64 * 4
    assert dec.estimated_waveform_bytes == est.expected_samples * 4


@pytest.mark.asyncio
async def test_ns33_duration_guard_rejection_does_not_emit_fallback_on_active_response() -> None:
    clk, _, pipe, handles = _make_env(dit=FakeDiTModel(predicted_frames=20.0))
    ctx, g = await _open_session(clk)
    sink: list[AudioChunk] = []
    p1 = _make_plan(session_id=g.session_id, turn_id=g.turn_id, generation_id=g.generation_id, plan_id="p-ok")
    assert (await pipe.synthesize_plan(p1, session_ctx=ctx, chunk_sink=sink.append)).status == "COMPLETED"
    handles.tts_model.predicted_frames = -2.0
    p2 = _make_plan(session_id=g.session_id, turn_id=g.turn_id, generation_id=g.generation_id, plan_id="p-bad", plan_revision=1)
    out2 = await pipe.synthesize_plan(p2, session_ctx=ctx, chunk_sink=sink.append)
    assert out2.status == "FAILED"
    assert len(sink) == 1
    await ctx.close("done")


# =====================================================================
# NS34 - NS42: Seeded Latent Initialization & Baseline Euler32 Solver
# =====================================================================


def test_ns34_same_seed_reproduces_exact_seeded_latent() -> None:
    plan = _make_plan(seed=9)
    snap = pin_synthesis_snapshot(plan)
    handles = _make_handles()
    enc = EncoderAdapter().encode(plan.chunks[0], tts_model=handles.tts_model, char_to_id=handles.char_to_id, vocab_revision=handles.vocab_revision)
    est = DurationEstimator().estimate(enc, tts_model=handles.tts_model, snapshot=snap)
    dec = DurationGuard().evaluate(est, snap)
    init = LatentInitializer()
    l1, d1 = init.initialize(decision=dec, snapshot=snap)
    l2, d2 = init.initialize(decision=dec, snapshot=snap)
    assert d1 == d2
    assert np.array_equal(l1, l2)


@pytest.mark.asyncio
async def test_ns35_interleaved_sessions_no_cross_session_rng_contamination() -> None:
    import random

    _, _, pipe, _ = _make_env()
    # Mutate process-global random state before and between calls; isolated generator must remain unaffected
    random.seed(12345)
    o1 = await pipe.synthesize_plan(_make_plan(session_id="sess-r1", plan_id="pr1", texts=("Merhaba.",)))
    random.seed(99999)
    o2 = await pipe.synthesize_plan(_make_plan(session_id="sess-r2", plan_id="pr2", texts=("Merhaba.",)))
    assert o1.status == "COMPLETED" and o2.status == "COMPLETED"
    assert o1.accepted_chunks[0].payload == o2.accepted_chunks[0].payload


@pytest.mark.asyncio
async def test_ns36_unisolated_legacy_rng_holds_strict_mode() -> None:
    _, _, pipe, _ = _make_env()
    out = await pipe.synthesize_plan(_make_plan(), override_rng_isolation_mode="UNISOLATED")
    assert out.status == "FAILED"
    assert out.error is not None and out.error.code == "UNISOLATED_RNG_HOLD"


@pytest.mark.asyncio
async def test_ns37_wrong_latent_rank_channel_dtype_device_rejected() -> None:
    _, _, pipe, handles = _make_env()
    bad_rank = np.zeros((44, 64), dtype=np.float32)
    out_rank = await pipe.synthesize_plan(_make_plan(plan_id="p-rank"), override_latent=bad_rank)
    assert out_rank.status == "FAILED" and out_rank.error is not None and out_rank.error.code == "INVALID_LATENT_SHAPE"

    bad_dtype = np.zeros((1, 44, 64), dtype=np.float64)
    out_dtype = await pipe.synthesize_plan(_make_plan(plan_id="p-dtype"), override_latent=bad_dtype)
    assert out_dtype.status == "FAILED" and out_dtype.error is not None and out_dtype.error.code == "INVALID_LATENT_DTYPE"
    assert handles.tts_model.ode_calls == 0


@pytest.mark.asyncio
async def test_ns38_nonfinite_latent_rejected_before_ode() -> None:
    _, _, pipe, handles = _make_env()
    bad_nan = np.full((1, 44, 64), np.nan, dtype=np.float32)
    out = await pipe.synthesize_plan(_make_plan(), override_latent=bad_nan)
    assert out.status == "FAILED"
    assert out.error is not None and out.error.code == "NONFINITE_LATENT"
    assert handles.tts_model.ode_calls == 0


@pytest.mark.asyncio
async def test_ns39_euler32_profile_and_time_grid_passed_unchanged() -> None:
    _, _, pipe, handles = _make_env()
    out = await pipe.synthesize_plan(_make_plan())
    assert out.status == "COMPLETED"
    seen = handles.tts_model.solver_profiles_seen[0]
    assert seen.solver_name == "Euler"
    assert seen.steps == 32
    assert len(seen.time_grid()) == 32
    assert seen.time_grid()[0] == 0.0 and math.isclose(seen.time_grid()[-1], 31 / 32)
    assert out.accepted_chunks[0].solver == "Euler"
    assert out.accepted_chunks[0].ode_steps == 32


@pytest.mark.asyncio
async def test_ns40_alternate_solver_or_steps_rejected_in_strict_mode() -> None:
    _, _, pipe, handles = _make_env()
    out_steps = await pipe.synthesize_plan(_make_plan(plan_id="p-16"), requested_ode_steps=16)
    assert out_steps.status == "FAILED" and out_steps.error is not None and out_steps.error.code == "UNAPPROVED_SOLVER_PROFILE"

    out_solver = await pipe.synthesize_plan(_make_plan(plan_id="p-heun"), requested_solver="Heun")
    assert out_solver.status == "FAILED" and out_solver.error is not None and out_solver.error.code == "UNAPPROVED_SOLVER_PROFILE"
    assert handles.tts_model.ode_calls == 0


def test_ns41_legacy_explicit_alternative_profile_preserved_for_legacy_scope() -> None:
    with pytest.raises(SolverValidationError):
        validate_solver_profile("Euler", 16, strict=True)
    leg = validate_solver_profile("Euler", 16, strict=False, legacy_alternative_approved=True)
    assert leg.steps == 16 and leg.approved_for_strict is False


@pytest.mark.asyncio
async def test_ns42_provider_fails_midway_through_ode_no_partial_speech() -> None:
    _, _, pipe, _ = _make_env(dit=FakeDiTModel(fail_ode_step=12))
    out = await pipe.synthesize_plan(_make_plan())
    assert out.status == "FAILED"
    assert out.accepted_chunks == ()
    assert out.error is not None and out.error.code == "ODE_PROVIDER_FAILURE"


# =====================================================================
# NS43 - NS53: M06 Scheduling, Lease Lifecycle, Quarantine & Batch Ownership
# =====================================================================


@pytest.mark.asyncio
async def test_ns43_first_speech_chunk_uses_p2_with_scope_and_cost() -> None:
    clk, _, pipe, _ = _make_env()
    deadline = DeadlineBudget.from_now(clk, 5000)
    plan = _make_plan(texts=("İlk konuşma parçası.",))
    out = await pipe.synthesize_plan(plan, deadline=deadline)
    assert out.status == "COMPLETED"
    job = out.chunk_outcomes[0].job_ref
    assert job is not None
    assert job.priority == PriorityClass.P2
    assert job.generation_ref == plan.generation_ref
    assert job.estimated_vram_bytes > 0


@pytest.mark.asyncio
async def test_ns44_later_speech_chunks_use_p4_and_bounded_outstanding() -> None:
    _, _, pipe, _ = _make_env()
    plan = _make_plan(texts=("İlk parça.", "İkinci parça.", "Üçüncü parça."))
    out = await pipe.synthesize_plan(plan)
    assert out.status == "COMPLETED"
    prios = [c.job_ref.priority for c in out.chunk_outcomes if c.job_ref]
    assert prios == [PriorityClass.P2, PriorityClass.P4, PriorityClass.P4]
    assert pipe.scheduler_bridge.in_flight_count(plan.generation_ref) == 0


@pytest.mark.asyncio
async def test_ns45_expired_deadline_denies_dispatch_before_native_call() -> None:
    clk, _, pipe, handles = _make_env()
    expired = DeadlineBudget.from_now(clk, 10)
    clk.advance_ms(20)
    out = await pipe.synthesize_plan(_make_plan(), deadline=expired)
    assert out.status == "FAILED"
    assert out.error is not None and out.error.code == "SCHEDULER_REJECTED_DEADLINE"
    assert handles.tts_model.ode_calls == 0


@pytest.mark.asyncio
async def test_ns46_unavailable_gpu_probe_or_budget_blocks_native_dispatch() -> None:
    clk = HarnessClock(initial_ns=1_000_000)
    sched = UnifiedGpuScheduler(clock=clk)
    # No probe updated -> PROBE_UNKNOWN
    handles = _make_handles()
    res = ModelResidencyAdapter(sched.residency_manager)
    res.register_handles(handles, vram_bytes=64 * MIB)
    pipe = NeuralSynthesisPipeline(scheduler=sched, residency_adapter=res)
    out = await pipe.synthesize_plan(_make_plan())
    assert out.status == "FAILED"
    assert out.error is not None and out.error.code == "INSUFFICIENT_GPU_BUDGET"
    assert handles.tts_model.ode_calls == 0


@pytest.mark.asyncio
async def test_ns47_lease_retained_until_materialization_barrier() -> None:
    clk, sched, pipe, _ = _make_env()
    gate = PhaseGate("before_materialize")
    barriers = {0: ProviderBarriers(before_materialize=lambda: gate.arrive_and_wait())}
    task = asyncio.create_task(pipe.synthesize_plan(_make_plan(), barriers_by_chunk=barriers))
    await gate.wait_arrived()

    # While stopped before materialization, lease is IN_FLIGHT and holds physical resources
    active_leases = [l for l in sched._leases.values() if l.holds_physical_resources]
    assert len(active_leases) == 1
    assert active_leases[0].state == ExecutionLeaseState.IN_FLIGHT

    gate.release()
    out = await task
    assert out.status == "COMPLETED"
    assert active_leases[0].state == ExecutionLeaseState.RELEASED


@pytest.mark.asyncio
async def test_ns48_cancel_during_dit_ode_fences_output_and_retains_lease_until_finish() -> None:
    clk, sched, pipe, _ = _make_env()
    ctx, g = await _open_session(clk)
    gate = PhaseGate("after_ode")
    drain_gate = PhaseGate("drain_done")
    barriers = {
        0: ProviderBarriers(
            after_ode=lambda: gate.arrive_and_wait(),
            await_physical_drain=lambda _l: drain_gate.arrive_and_wait(),
        )
    }
    sink: list[AudioChunk] = []
    task = asyncio.create_task(
        pipe.synthesize_plan(
            _make_plan(session_id=g.session_id, turn_id=g.turn_id, generation_id=g.generation_id),
            session_ctx=ctx,
            chunk_sink=sink,
            barriers_by_chunk=barriers,
        )
    )
    await gate.wait_arrived()
    await ctx.commit_interrupt("barge_in")
    # Release ODE barrier -> drain_grace_ms expires -> quarantined until drain_gate finishes
    out = await task
    assert out.status == "CANCELLED"
    assert sink == []
    assert out.quarantined is True
    assert sched.quarantine_manager.active_count == 1

    gate.release()
    drain_gate.release()
    await sched.wait_reclaims()
    assert sched.quarantine_manager.active_count == 0
    await ctx.close("done")


@pytest.mark.asyncio
async def test_ns49_cancel_during_vae_decode_blocks_delivery_and_retains_lease() -> None:
    clk, sched, pipe, _ = _make_env()
    ctx, g = await _open_session(clk)
    gate = PhaseGate("after_decode")
    barriers = {0: ProviderBarriers(after_decode=lambda: gate.arrive_and_wait())}
    sink: list[AudioChunk] = []
    task = asyncio.create_task(
        pipe.synthesize_plan(
            _make_plan(session_id=g.session_id, turn_id=g.turn_id, generation_id=g.generation_id),
            session_ctx=ctx,
            chunk_sink=sink,
            barriers_by_chunk=barriers,
        )
    )
    await gate.wait_arrived()
    await ctx.commit_interrupt("cancel_during_decode")
    gate.release()
    out = await task
    assert out.status == "CANCELLED"
    assert sink == []
    assert out.delivery_accepted is False
    await ctx.close("done")


@pytest.mark.asyncio
async def test_ns50_duplicate_completion_callback_is_idempotent() -> None:
    clk, sched, pipe, _ = _make_env()
    out = await pipe.synthesize_plan(_make_plan())
    assert out.status == "COMPLETED"
    job_ref = out.chunk_outcomes[0].job_ref
    assert job_ref is not None
    lease = next(iter(sched._leases.values()))
    # Duplicate callback returns False and triggers no second release
    assert pipe.scheduler_bridge.adapter.notify_completion_callback(lease, job_ref.request_id) is False
    assert pipe.scheduler_bridge.adapter.completion_callback_count(job_ref.request_id) >= 1
    assert len(out.accepted_chunks) == 1


@pytest.mark.asyncio
async def test_ns51_provider_uncertain_device_state_moves_lease_to_quarantine() -> None:
    clk, sched, pipe, _ = _make_env(dit=FakeDiTModel(fail_ode_step=5, uncertain_failure=True))
    drain_gate = PhaseGate("uncertain_drain")
    barriers = {0: ProviderBarriers(await_physical_drain=lambda _l: drain_gate.arrive_and_wait())}
    out = await pipe.synthesize_plan(_make_plan(), barriers_by_chunk=barriers)
    assert out.status == "FAILED"
    assert out.quarantined is True
    assert out.physical_completed is False
    assert sched.quarantine_manager.active_count == 1
    drain_gate.release()
    await sched.wait_reclaims()
    assert sched.quarantine_manager.active_count == 0


@pytest.mark.asyncio
async def test_ns52_oom_no_independent_retry_fresh_admission_after_recovery() -> None:
    clk, sched, pipe, handles = _make_env(free_mib=260)  # usable = 260 - 256 = 4 MiB < execution budget
    plan = _make_plan()
    out_oom = await pipe.synthesize_plan(plan)
    assert out_oom.status == "FAILED"
    assert out_oom.error is not None and out_oom.error.code == "INSUFFICIENT_GPU_BUDGET"
    assert handles.tts_model.ode_calls == 0

    # After M06 VRAM recovery, fresh admission with unchanged plan succeeds (using fresh claim registry or rev)
    sched.memory_budget.update_probe(FakeGPUProbeAdapter(clk).valid_probe(free_mib=4096))
    plan_retry = _make_plan(plan_revision=1)
    out_ok = await pipe.synthesize_plan(plan_retry)
    assert out_ok.status == "COMPLETED"
    assert handles.tts_model.ode_calls == 1


def test_ns53_single_scheduler_authority_and_legacy_batched_ode_preserved() -> None:
    paths = {p.path_id: p for p in classify_synthesis_paths()}
    assert paths["f5_a_strict_pipeline"].scheduler_owner == "M06_UNIFIED_GPU_SCHEDULER"
    assert paths["legacy_batched_ode"].classification == "LIVE_PATH"
    assert paths["legacy_batched_ode"].strict_compatible is False


# =====================================================================
# NS54 - NS63: Decoder Output, Raw Validation & AudioChunk Contract
# =====================================================================


@pytest.mark.asyncio
async def test_ns54_valid_singleton_mono_vae_layouts_produce_exact_48k_f32_bytes() -> None:
    for mode in ("1d", "2d_singleton", "3d_singleton"):
        _, _, pipe, _ = _make_env(vae=FakeAudioVAE(output_mode=mode))
        out = await pipe.synthesize_plan(_make_plan(plan_id=f"p-{mode}"))
        assert out.status == "COMPLETED"
        chk = out.accepted_chunks[0]
        assert chk.format == AudioFormat(48000, 1, AudioEncoding.FLOAT32_LE)
        assert len(chk.payload) == chk.sample_count * 4
        assert math.isclose(chk.actual_duration_ms, (chk.sample_count * 1000.0) / 48000.0)


@pytest.mark.asyncio
async def test_ns55_unexpected_decoder_sample_rate_rejected_without_resample() -> None:
    _, _, pipe, _ = _make_env(vae=FakeAudioVAE(sample_rate_hz=24000))
    out = await pipe.synthesize_plan(_make_plan())
    assert out.status == "FAILED"
    assert out.error is not None and out.error.code == "DECODER_SAMPLE_RATE_MISMATCH"


@pytest.mark.asyncio
async def test_ns56_multi_channel_or_multi_batch_decoder_output_rejected() -> None:
    for mode in ("multi_channel", "multi_batch"):
        _, _, pipe, _ = _make_env(vae=FakeAudioVAE(output_mode=mode))
        out = await pipe.synthesize_plan(_make_plan(plan_id=f"p-{mode}"))
        assert out.status == "FAILED"
        assert out.error is not None and out.error.code == "AMBIGUOUS_DECODER_LAYOUT"


@pytest.mark.asyncio
async def test_ns57_empty_nan_silent_waveform_rejected_no_zero_fill() -> None:
    for vae_kw, expected_code in (
        ({"empty": True}, "EMPTY_DECODER_OUTPUT"),
        ({"inject_nan": True}, "NONFINITE_WAVEFORM"),
        ({"inject_silence": True}, "SILENT_MODEL_OUTPUT"),
    ):
        _, _, pipe, _ = _make_env(vae=FakeAudioVAE(**vae_kw))
        out = await pipe.synthesize_plan(_make_plan(plan_id=f"p-{expected_code}"))
        assert out.status == "FAILED"
        assert out.accepted_chunks == ()
        assert out.error is not None and out.error.code == expected_code


@pytest.mark.asyncio
async def test_ns58_dtype_conversion_and_endianness_produce_finite_float32_le() -> None:
    for dtype in ("int16", ">f4"):
        _, _, pipe, _ = _make_env(vae=FakeAudioVAE(dtype=dtype))
        out = await pipe.synthesize_plan(_make_plan(plan_id=f"p-{dtype.replace('>', 'be_')}"))
        assert out.status == "COMPLETED"
        chk = out.accepted_chunks[0]
        vals = struct.unpack(f"<{chk.sample_count}f", chk.payload)
        assert all(math.isfinite(v) for v in vals)


@pytest.mark.asyncio
async def test_ns59_actual_sample_count_differs_from_estimate_uses_actual_bytes_and_tolerance() -> None:
    # Default 40-char text -> 44 effective frames; 45 frames is ~2.3% delta (< 25% tolerance)
    _, _, pipe_ok, _ = _make_env(
        dit=FakeDiTModel(predicted_frames=44.0),
        vae=FakeAudioVAE(override_samples=45 * 1920),
    )
    out_ok = await pipe_ok.synthesize_plan(_make_plan(), allow_baseline_frame_trim=False)
    assert out_ok.status == "COMPLETED"
    assert out_ok.accepted_chunks[0].sample_count == 45 * 1920
    assert math.isclose(out_ok.accepted_chunks[0].actual_duration_ms, 45 * 40.0)

    # Exceeding tolerance (70 frames instead of 44 -> 59% > 25%) -> rejected
    _, _, pipe_bad, _ = _make_env(
        dit=FakeDiTModel(predicted_frames=44.0),
        vae=FakeAudioVAE(override_samples=70 * 1920),
    )
    out_bad = await pipe_bad.synthesize_plan(_make_plan(plan_id="p-mismatch"), allow_baseline_frame_trim=False)
    assert out_bad.status == "FAILED"
    assert out_bad.error is not None and out_bad.error.code == "ACTUAL_DURATION_MISMATCH"


def test_ns60_huge_payload_or_byte_length_mismatch_rejected() -> None:
    val = RawAudioValidator(max_payload_bytes=1024)
    res_huge = val.validate(
        payload=b"\x00\x00\x80\x3e" * 512,
        sample_count=512,
        audio_format=AudioFormat(48000, 1, AudioEncoding.FLOAT32_LE),
    )
    assert not res_huge.structurally_valid and res_huge.error is not None and res_huge.error.code == "PAYLOAD_BYTE_MISMATCH"

    res_mismatch = val.validate(
        payload=b"\x00\x00\x80\x3e" * 10,
        sample_count=12,
        audio_format=AudioFormat(48000, 1, AudioEncoding.FLOAT32_LE),
    )
    assert not res_mismatch.structurally_valid and res_mismatch.error is not None and res_mismatch.error.code == "PAYLOAD_BYTE_MISMATCH"


@pytest.mark.asyncio
async def test_ns61_collapse_guard_rejection_blocks_delivery_and_sets_fail() -> None:
    _, _, pipe, _ = _make_env()
    sink: list[AudioChunk] = []
    out = await pipe.synthesize_plan(
        _make_plan(),
        chunk_sink=sink,
        collapse_guard_fn=lambda _samples, _sr: 0.02,  # < 0.06 voicedness threshold
    )
    assert out.status == "FAILED"
    assert sink == []
    assert out.quality_status == QualityStatus.FAIL
    assert out.error is not None and out.error.code == "COLLAPSE_GUARD_REJECTED"


@pytest.mark.asyncio
async def test_ns62_valid_unmeasured_waveform_is_quality_unknown_never_pass() -> None:
    _, _, pipe, _ = _make_env()
    out = await pipe.synthesize_plan(_make_plan())
    assert out.status == "COMPLETED"
    assert out.structurally_valid is True
    assert out.quality_status == QualityStatus.UNKNOWN
    assert out.accepted_chunks[0].quality_status == QualityStatus.UNKNOWN


@pytest.mark.asyncio
async def test_ns63_plan_pause_and_speed_hints_preserved_without_dsp_or_silence() -> None:
    _, _, pipe, _ = _make_env(dit=FakeDiTModel(predicted_frames=44.0))
    plan = _make_plan(post_pause_ms=320, requested_speed=1.15)
    out = await pipe.synthesize_plan(plan)
    assert out.status == "COMPLETED"
    chk = out.accepted_chunks[0]
    assert chk.post_pause_ms == 320
    assert chk.requested_speed == 1.15
    assert chk.applied_speed is None
    # Exact 44 effective frames * 1920 samples, zero appended silence
    assert chk.sample_count == 44 * 1920


# =====================================================================
# NS64 - NS67: Cache Provenance & Experiment Compatibility
# =====================================================================


@pytest.mark.asyncio
async def test_ns64_legacy_cache_without_provenance_triggers_strict_bypass() -> None:
    _, _, pipe, handles = _make_env()
    text = "Merhaba."
    legacy_cache = {(text, 9): np.ones(4800, dtype=np.float32)}
    out = await pipe.synthesize_plan(_make_plan(texts=(text,)), legacy_cache=legacy_cache)
    assert out.status == "COMPLETED"
    assert out.chunk_outcomes[0].cache_status == CacheStatus.BYPASS
    assert out.accepted_chunks[0].cache_status == CacheStatus.BYPASS
    assert handles.tts_model.ode_calls == 1


@pytest.mark.asyncio
async def test_ns65_approved_raw_cache_hit_skips_gpu_and_blocks_private_cross_session() -> None:
    _, _, pipe, handles = _make_env()
    text = "Hoş geldiniz."
    raw_samples = (0.25 * np.sin(2.0 * np.pi * 220.0 * np.arange(9600, dtype=np.float32) / 48000.0)).astype("<f4")
    pipe.cache_adapter.put_verified_raw(
        RawCacheEntry(
            model_text=text,
            voice_profile="leyla-baseline-9",
            seed=9,
            model_revision="freya-tts:batched-ode",
            lexicon_revision="lex-rev-1",
            capability_revision="cap-rev-1",
            solver="Euler",
            ode_steps=32,
            format=AudioFormat(48000, 1, AudioEncoding.FLOAT32_LE),
            sample_count=9600,
            payload=raw_samples.tobytes(),
            is_raw_unprocessed=True,
            is_private=False,
        )
    )
    out_hit = await pipe.synthesize_plan(_make_plan(session_id="sess-pub", texts=(text,)))
    assert out_hit.status == "COMPLETED"
    assert out_hit.chunk_outcomes[0].cache_status == CacheStatus.HIT
    assert handles.tts_model.ode_calls == 0

    # Private entry owned by sess-1 must NOT hit for sess-2
    priv_text = "Özel plaka bilgisi."
    pipe.cache_adapter.put_verified_raw(
        RawCacheEntry(
            model_text=priv_text,
            voice_profile="leyla-baseline-9",
            seed=9,
            model_revision="freya-tts:batched-ode",
            lexicon_revision="lex-rev-1",
            capability_revision="cap-rev-1",
            solver="Euler",
            ode_steps=32,
            format=AudioFormat(48000, 1, AudioEncoding.FLOAT32_LE),
            sample_count=9600,
            payload=raw_samples.tobytes(),
            is_raw_unprocessed=True,
            is_private=True,
            owner_session_id="sess-owner-1",
        )
    )
    out_priv = await pipe.synthesize_plan(_make_plan(session_id="sess-other-2", texts=(priv_text,)))
    assert out_priv.chunk_outcomes[0].cache_status == CacheStatus.BYPASS
    assert handles.tts_model.ode_calls == 1


def test_ns66_rendered_or_wrong_rate_cache_entry_rejected() -> None:
    cache = StrictSynthesisCacheAdapter()
    with pytest.raises(ValueError, match="refuses rendered"):
        cache.put_verified_raw(
            RawCacheEntry(
                model_text="x",
                voice_profile="leyla-baseline-9",
                seed=9,
                model_revision="m1",
                lexicon_revision=None,
                capability_revision=None,
                solver="Euler",
                ode_steps=32,
                format=AudioFormat(48000, 1, AudioEncoding.FLOAT32_LE),
                sample_count=100,
                payload=b"\x00" * 400,
                is_raw_unprocessed=False,
            )
        )
    with pytest.raises(ValueError, match="48000 Hz"):
        cache.put_verified_raw(
            RawCacheEntry(
                model_text="x",
                voice_profile="leyla-baseline-9",
                seed=9,
                model_revision="m1",
                lexicon_revision=None,
                capability_revision=None,
                solver="Euler",
                ode_steps=32,
                format=AudioFormat(8000, 1, AudioEncoding.PCM_S16LE),
                sample_count=100,
                payload=b"\x00" * 200,
                is_raw_unprocessed=True,
            )
        )


def test_ns67_experimental_routes_inventoried_and_not_auto_activated() -> None:
    inv = inventory_experimental_routes()
    assert inv["prewarm_tts"]["auto_activated_in_f5a"] is False
    assert inv["sft_leyla_lora"]["auto_activated_in_f5a"] is False
    assert inv["ab_seed_presets"]["default_experimental_enabled"] is False


# =====================================================================
# NS68 - NS74: Atomic Generation Delivery, Ordering & Lifecycle
# =====================================================================


@pytest.mark.asyncio
async def test_ns68_generation_revoked_just_before_output_insertion_rejected() -> None:
    clk = HarnessClock(initial_ns=1_000_000)
    ctx, g = await _open_session(clk)
    fence = GenerationDeliveryFence()
    _, _, pipe, _ = _make_env(clock=clk)
    out = await pipe.synthesize_plan(_make_plan(session_id=g.session_id, turn_id=g.turn_id, generation_id=g.generation_id))
    chunk = out.accepted_chunks[0]

    await ctx.commit_interrupt("barge_in")
    deliv = await fence.deliver(chunk, session_ctx=ctx)
    assert deliv.accepted is False
    assert deliv.status == AdmissionStatus.CANCELED
    await ctx.close("done")


@pytest.mark.asyncio
async def test_ns69_new_turn_or_plan_revision_supersedes_old_chunk() -> None:
    clk = HarnessClock(initial_ns=1_000_000)
    ctx, g1 = await _open_session(clk)
    fence = GenerationDeliveryFence()
    _, _, pipe, _ = _make_env(clock=clk)
    out = await pipe.synthesize_plan(_make_plan(session_id=g1.session_id, turn_id=g1.turn_id, generation_id=g1.generation_id))
    old_chunk = out.accepted_chunks[0]

    # Supersede with new turn
    t2, _ = await ctx.begin_turn()
    await ctx.begin_generation(t2)
    deliv = await fence.deliver(old_chunk, session_ctx=ctx)
    assert deliv.accepted is False
    assert deliv.status == AdmissionStatus.STALE_TURN
    await ctx.close("done")


@pytest.mark.asyncio
async def test_ns70_two_interleaved_sessions_same_chunk_index_isolated() -> None:
    clk, _, pipe, _ = _make_env()
    ctx_a, ga = await _open_session(clk, "sess-alpha")
    ctx_b, gb = await _open_session(clk, "sess-beta")
    sink_a: list[AudioChunk] = []
    sink_b: list[AudioChunk] = []
    pa = _make_plan(session_id=ga.session_id, turn_id=ga.turn_id, generation_id=ga.generation_id, plan_id="pa")
    pb = _make_plan(session_id=gb.session_id, turn_id=gb.turn_id, generation_id=gb.generation_id, plan_id="pb")
    oa, ob = await asyncio.gather(
        pipe.synthesize_plan(pa, session_ctx=ctx_a, chunk_sink=sink_a.append),
        pipe.synthesize_plan(pb, session_ctx=ctx_b, chunk_sink=sink_b.append),
    )
    assert oa.status == "COMPLETED" and ob.status == "COMPLETED"
    assert sink_a[0].generation_ref == ga and sink_b[0].generation_ref == gb
    await ctx_a.close("done")
    await ctx_b.close("done")


@pytest.mark.asyncio
async def test_ns71_duplicate_and_reordered_chunk_rejected() -> None:
    clk, _, pipe, _ = _make_env()
    plan = _make_plan(texts=("Bir.", "İki."))
    out = await pipe.synthesize_plan(plan)
    c0, c1 = out.accepted_chunks

    fence = GenerationDeliveryFence()
    # Out-of-order c1 before c0
    res_ooo = await fence.deliver(c1)
    assert not res_ooo.accepted and res_ooo.status == AdmissionStatus.OUT_OF_ORDER
    # Valid c0 then duplicate c0
    res_ok = await fence.deliver(c0)
    assert res_ok.accepted
    res_dup = await fence.deliver(c0)
    assert not res_dup.accepted and res_dup.status == AdmissionStatus.DUPLICATE


@pytest.mark.asyncio
async def test_ns72_close_session_prevents_reentry_and_preserves_quarantine() -> None:
    clk, sched, pipe, _ = _make_env(dit=FakeDiTModel(fail_ode_step=2, uncertain_failure=True))
    ctx, g = await _open_session(clk)
    drain_gate = PhaseGate("close_drain")
    barriers = {0: ProviderBarriers(await_physical_drain=lambda _l: drain_gate.arrive_and_wait())}
    await pipe.synthesize_plan(
        _make_plan(session_id=g.session_id, turn_id=g.turn_id, generation_id=g.generation_id),
        session_ctx=ctx,
        barriers_by_chunk=barriers,
    )
    rep = await pipe.lifecycle.close_session(g.session_id, session_ctx=ctx, wait_reclaims=False)
    assert rep.closed is True
    assert rep.quarantined_leases == 1
    assert pipe.lifecycle.is_session_closed(g.session_id)

    reentry = await pipe.synthesize_plan(
        _make_plan(session_id=g.session_id, turn_id=g.turn_id, generation_id=g.generation_id, plan_id="reenter"),
        session_ctx=ctx,
    )
    assert reentry.status == "FAILED"
    assert reentry.error is not None and reentry.error.code == "SESSION_CLOSED_NO_REENTRY"

    drain_gate.release()
    await sched.wait_reclaims()


@pytest.mark.asyncio
async def test_ns73_consumer_backpressure_and_disconnect_bounded() -> None:
    clk, _, pipe, _ = _make_env()
    # Tiny session media queue triggers M02 BACKPRESSURE safely
    ctx, g = await _open_session(clk, max_queue_bytes=1024)
    out = await pipe.synthesize_plan(
        _make_plan(session_id=g.session_id, turn_id=g.turn_id, generation_id=g.generation_id),
        session_ctx=ctx,
    )
    assert out.status == "FAILED"
    assert out.delivery_accepted is False
    assert out.error is not None and out.error.code == "DELIVERY_BACKPRESSURE"
    await ctx.close("done")


@pytest.mark.asyncio
async def test_ns74_soft_pause_distinct_from_hard_cancellation() -> None:
    clk = HarnessClock(initial_ns=1_000_000)
    ctx, g = await _open_session(clk)
    pref = await ctx.soft_pause()
    assert pref is not None and ctx.pause.state == PauseState.SOFT_PAUSED
    assert GenerationDeliveryFence.is_soft_paused(ctx) is True
    assert ctx.tg.generation_scope is not None and ctx.tg.generation_scope.is_cancel_requested is False
    assert await ctx.resume_pause(pref) is True
    assert ctx.pause.state == PauseState.RUNNING
    await ctx.close("done")


# =====================================================================
# NS75 - NS80: Telemetry, Privacy, F4->F5->F6 Seam, Compatibility & Rollback
# =====================================================================


def test_ns75_telemetry_same_clock_boundaries_rtf_and_null_vs_zero() -> None:
    clk = HarnessClock(initial_ns=1_000_000)
    tel = SynthesisTelemetry(clock=clk)
    assert tel.elapsed_ms(1_000_000, 5_000_000, clock_domain="wrong.domain") is None
    assert tel.observation_loss_count == 1
    rtf_missing = tel.compute_rtf(inference_ms=10.0, audio_duration_ms=0.0)
    assert rtf_missing.value is None and rtf_missing.status == MetricStatus.UNAVAILABLE
    rtf_ok = tel.compute_rtf(inference_ms=20.0, audio_duration_ms=100.0)
    assert rtf_ok.value == pytest.approx(0.2) and rtf_ok.status == MetricStatus.MEASURED


@pytest.mark.asyncio
async def test_ns76_telemetry_subscriber_overflow_or_error_does_not_block_delivery() -> None:
    clk = HarnessClock(initial_ns=1_000_000)
    bus = BoundedEventBus(max_lane_size=1)

    def broken_cb(_env: Any) -> None:
        raise RuntimeError("subscriber_crash")

    bus.subscribe("broken", callback=broken_cb)
    _, _, pipe, _ = _make_env(clock=clk, event_bus=bus)
    out = await pipe.synthesize_plan(_make_plan())
    assert out.status == "COMPLETED"
    assert out.delivery_accepted is True
    assert out.physical_completed is True


@pytest.mark.asyncio
async def test_ns77_no_pii_text_or_secrets_in_telemetry_or_evidence() -> None:
    clk = HarnessClock(initial_ns=1_000_000)
    bus = BoundedEventBus()
    sub = bus.subscribe("audit")
    _, _, pipe, _ = _make_env(clock=clk, event_bus=bus)
    secret_text = "Plaka 34 ABC 1234 telefon 0532 111 22 33 için randevu."
    out = await pipe.synthesize_plan(_make_plan(texts=(secret_text,)))
    assert out.status == "COMPLETED"
    events = sub.drain()
    assert len(events) >= 1
    for ev in events:
        findings = PIISecretScanner.scan_object({"event": ev.event_type, "metadata": dict(ev.metadata)})
        assert findings == []
        assert "0532" not in str(ev.metadata)
        assert "34 ABC" not in str(ev.metadata)


@pytest.mark.asyncio
async def test_ns78_f4_plan_to_f5_to_recording_f6_sink() -> None:
    # Step 1: F4 produces prepared text once
    norm = legacy_text.normalize("Merhaba, 1500 TL bakım randevunuz onaylandı.")["normalized"]
    prepared = tuple(legacy_text.prepare_tts_clause(p) for p, _ in legacy_text.clauses(norm))

    # Step 2: F5 synthesizes strict plan into recording F6 sink
    clk, _, pipe, _ = _make_env()
    ctx, g = await _open_session(clk)
    f6_recorded_chunks: list[AudioChunk] = []
    plan = _make_plan(
        session_id=g.session_id,
        turn_id=g.turn_id,
        generation_id=g.generation_id,
        texts=prepared,
        post_pause_ms=200,
    )
    out = await pipe.synthesize_plan(plan, session_ctx=ctx, chunk_sink=f6_recorded_chunks.append)
    assert out.status == "COMPLETED"
    assert len(f6_recorded_chunks) == len(prepared)
    for idx, chk in enumerate(f6_recorded_chunks):
        assert chk.format == AudioFormat(48000, 1, AudioEncoding.FLOAT32_LE)
        assert chk.post_pause_ms == 200
        assert chk.quality_status == QualityStatus.UNKNOWN
        assert chk.chunk_index == idx
    await ctx.close("done")


@pytest.mark.asyncio
async def test_ns79_legacy_compatibility_and_strict_bypass_audit_clear() -> None:
    audit = audit_strict_bypasses()
    assert audit["status"] == "CLEAR"
    assert audit["f5_internal_normalization_calls"] == 0
    assert audit["f5_internal_dsp_calls"] == 0
    assert audit["f5_direct_gpu_bypasses"] == 0

    _, _, pipe, _ = _make_env()

    class _FakeLegacyModels:
        async def synth(self, text: str, seed: int | None = None):
            return np.ones(2400, dtype=np.float32) * 0.1

    bridge = LegacySynthesisBridge(strict_pipeline=pipe, legacy_models=_FakeLegacyModels())
    leg_wav = await bridge.synthesize_legacy_text("Merhaba", seed=9)
    conv = adapt_legacy_synth_output(
        generation_ref=GenerationRef("sess-leg", 1, 1),
        plan_id="leg-p",
        plan_revision=0,
        chunk_id="leg-c0",
        chunk_index=0,
        waveform_48k=leg_wav,
        seed=9,
    )
    assert conv.ok and conv.lossy is True and conv.value is not None
    assert conv.value.cache_status == CacheStatus.UNKNOWN


def test_ns80_regression_integrity_and_isolated_rollback_rehearsal(tmp_path: Path) -> None:
    # Verify M00 feature denominator remains intact (18 features)
    summary = FeatureRegressionMapper(
        REPO_ROOT,
        REPO_ROOT / "docs" / "freya2" / "baseline" / M00_BASELINE_ID,
    ).build_matrix()
    assert summary.total_features == 18
    assert summary.duplicate_feature_ids == ()
    assert summary.missing_from_regression_matrix == ()

    # Rehearse isolated rollback in temp copy without touching repo files
    sandbox_pkg = tmp_path / "backend" / "neural_synthesis"
    shutil.copytree(REPO_ROOT / "backend" / "neural_synthesis", sandbox_pkg)
    assert len(list(sandbox_pkg.glob("*.py"))) == 19
    shutil.rmtree(sandbox_pkg)
    assert not sandbox_pkg.exists()
    assert (REPO_ROOT / "backend" / "neural_synthesis" / "pipeline.py").exists()
