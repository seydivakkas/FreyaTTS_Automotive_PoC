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
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from backend.core.configuration import resolve_configuration
from backend.core.contracts import (
    ASROutcome,
    ASRStatus,
    AudioEncoding,
    AudioFormat,
    CatalogStatus,
    ConfirmationStatus,
    SessionIdentity,
    StreamDirection,
    StreamRef,
    Utterance,
)
from backend.core.runtime import (
    FakeClock,
    SessionRegistry,
)
from tests.harness.adapters.fake_gpu import FakeGPUProbeAdapter
from backend.runtime_resources import (
    MIB,
    HandleOwnership,
    MemoryBudget,
    ModelSpec,
    PriorityClass,
    ProviderKind,
    QuarantineManager,
    ResidencyManager,
    UnifiedGpuScheduler,
)
from backend.shared_lexicon import (
    AliasEntry,
    CanonicalEntity,
    EntityCategory,
    LexiconRegistry,
    LexiconSnapshot,
)
from backend.speech_recognition import (
    ASRDeliveryStatus,
    ASRLifecycleManager,
    ASRRouteMode,
    ASRTelemetryBridge,
    ASRUtteranceAdmission,
    ClarificationReason,
    ContextHintSnapshot,
    ContinuationCue,
    CorrectionDecisionKind,
    DecodeAttemptRecord,
    DecodeBeamProfile,
    HotwordPlanner,
    InMemoryASRConsumer,
    PartialLaneState,
    PseudoStreamingController,
    SpeechRecognitionPipeline,
    SpeechScopeRef,
    StreamingWindowConfig,
    WhisperSchedulerEngine,
    arbitrate_decode_attempts,
    pin_lexicon_snapshot,
    resolve_asr_config,
    resolve_automotive_entities,
    scan_protected_spans,
    should_run_alternate_decode,
)
from backend.speech_recognition.protected_spans import ProtectedCategory


def _build_lexicon() -> LexiconRegistry:
    entities = (
        CanonicalEntity(
            entity_id="brand:nissan",
            canonical_name="Nissan",
            category=EntityCategory.BRAND,
            normalized_key="nissan",
            brand_name="Nissan",
            priority=10,
        ),
        CanonicalEntity(
            entity_id="model:qashqai",
            canonical_name="Qashqai",
            category=EntityCategory.MODEL,
            normalized_key="qashqai",
            brand_name="Nissan",
            model_name="Qashqai",
            priority=20,
        ),
        CanonicalEntity(
            entity_id="model:juke",
            canonical_name="Juke",
            category=EntityCategory.MODEL,
            normalized_key="juke",
            brand_name="Nissan",
            model_name="Juke",
            priority=25,
        ),
        CanonicalEntity(
            entity_id="brand:peugeot",
            canonical_name="Peugeot",
            category=EntityCategory.BRAND,
            normalized_key="peugeot",
            brand_name="Peugeot",
            priority=30,
        ),
        CanonicalEntity(
            entity_id="tech:dsg",
            canonical_name="DSG",
            category=EntityCategory.TECHNICAL,
            normalized_key="dsg",
            priority=40,
        ),
    )
    aliases = (
        AliasEntry(
            alias_id="alias:kaskay",
            alias_text="kaşkay",
            normalized_key="kaşkay",
            canonical_entity_id="model:qashqai",
            canonical_name="Qashqai",
            category=EntityCategory.MODEL,
            priority=20,
            source="reviewed_asr",
        ),
        AliasEntry(
            alias_id="alias:pejo",
            alias_text="pejo",
            normalized_key="pejo",
            canonical_entity_id="brand:peugeot",
            canonical_name="Peugeot",
            category=EntityCategory.BRAND,
            priority=30,
            source="reviewed_asr",
        ),
    )
    snap = LexiconSnapshot(
        entities=entities,
        aliases=aliases,
        pronunciations=(),
        technical_terms=(),
    )
    return LexiconRegistry.from_snapshot(snap)


async def _build_runtime(clock: FakeClock):
    snap = resolve_configuration(
        env={"STT_CATALOG_HOTWORDS": "true", "STT_MIN_RMS": "0.0"},
    ).snapshot
    pinned_cfg = resolve_asr_config(snap, route_mode=ASRRouteMode.STRICT)

    budget = MemoryBudget(clock=clock, headroom_bytes=256 * MIB, max_probe_age_ms=2_000)
    probe = FakeGPUProbeAdapter(clock, total_mib=8192)
    budget.update_probe(probe.valid_probe(free_mib=4096))
    residency = ResidencyManager(memory_budget=budget)
    spec = ModelSpec(
        model_id="stt-whisper",
        provider=ProviderKind.CTRANSLATE2,
        vram_bytes=0,
        ownership=HandleOwnership.BORROWED,
        loader=lambda: "borrowed-whisper-handle",
    )
    residency.register_model(spec)
    scheduler = UnifiedGpuScheduler(
        clock=clock,
        memory_budget=budget,
        quarantine_manager=QuarantineManager(clock=clock),
        residency_manager=residency,
    )
    sess_reg = SessionRegistry(clock=clock)
    ctx = await sess_reg.create("sess-f2bc", trace_id="trace-1")
    await ctx.open()
    turn, _ = await ctx.begin_turn()
    return pinned_cfg, scheduler, ctx, turn


# ---------------------------------------------------------------------------
# F2-B Tests: HotwordPlanner, ProtectedSpans, EntityResolver, DecodePolicy
# ---------------------------------------------------------------------------


def test_f2b_hotword_planner_freshness_budget_and_pii_scrub() -> None:
    clock = FakeClock(initial_ns=10_000_000_000)
    lex_reg = _build_lexicon()
    pinned_lex = pin_lexicon_snapshot(lex_reg)

    ctx_hint = ContextHintSnapshot(
        session_id="sess-f2bc",
        incarnation_id="inc-1",
        state_revision=4,
        source_turn_id=3,
        captured_monotonic_ns=9_500_000_000,
        clock_domain=clock.clock_domain,
        lexicon_revision=lex_reg.lexicon_revision,
        allowed_entity_ids=("model:juke",),
        confirmed_entity_ids=("brand:nissan", "model:qashqai"),
        service_categories=("periyodik bakım", "PII_SENTINEL_NAME"),
    )

    planner = HotwordPlanner(max_items=4, max_chars=48, max_tokens=16)
    plan = planner.plan(
        scope_id="utt-1",
        session_id="sess-f2bc",
        incarnation_id="inc-1",
        pinned_lexicon=pinned_lex,
        now_monotonic_ns=clock.monotonic_ns(),
        clock_domain=clock.clock_domain,
        context_hint=ctx_hint,
        baseline_terms=("nisan", "değil", "yağ\nfiltresi", "fren balatası"),
    )

    assert plan.context_used is True
    assert plan.context_revision == 4
    assert plan.terms[:2] == ("Nissan", "Qashqai")
    assert plan.char_count <= 48
    assert len(plan.terms) <= 4
    assert "PII_SENTINEL_NAME" not in plan.terms
    assert "nisan" not in plan.terms
    assert "değil" not in plan.terms
    assert plan.truncated is True

    # Expired context hint -> falls back to context-free baseline without raising
    clock.advance_ms(70_000)
    stale_plan = planner.plan(
        scope_id="utt-2",
        session_id="sess-f2bc",
        incarnation_id="inc-1",
        pinned_lexicon=pinned_lex,
        now_monotonic_ns=clock.monotonic_ns(),
        clock_domain=clock.clock_domain,
        context_hint=ctx_hint,
    )
    assert stale_plan.context_used is False
    assert stale_plan.context_revision is None
    assert stale_plan.fallback_reason == "context_hint_expired"


def test_f2b_protected_spans_precedence_and_safe_repr() -> None:
    raw = "Plakam 34 ABC 123, şasi WVWZZZ1JZXW000001, tel 0555 123 45 67, 1.6 TDI P0300 2020 1.250.000 TL değil"
    scan = scan_protected_spans(raw)
    cats = [s.category for s in scan.spans]
    assert ProtectedCategory.PLATE in cats
    assert ProtectedCategory.VIN in cats
    assert ProtectedCategory.PHONE in cats
    assert ProtectedCategory.ENGINE_CODE in cats
    assert ProtectedCategory.DTC in cats
    assert ProtectedCategory.YEAR_DATE_TIME in cats
    assert ProtectedCategory.CURRENCY_AMOUNT in cats
    assert ProtectedCategory.NEGATION_CORRECTION in cats

    # Ensure non-overlapping sorted spans and safe repr (no raw literal leaked)
    for i in range(len(scan.spans) - 1):
        assert scan.spans[i].span.end_exclusive <= scan.spans[i + 1].span.start
        assert "0555 123 45 67" not in repr(scan.spans[i])


def test_f2b_entity_resolver_turkish_phonetic_and_false_correction_guard() -> None:
    lex_reg = _build_lexicon()
    pinned_lex = pin_lexicon_snapshot(lex_reg)

    # 1. Phonetic candidate-only mode: raw_transcript untouched, canonical_transcript=None
    raw = " Nisan kaş kay iki bin yirmi. "
    rep = resolve_automotive_entities(
        utterance_id="utt-phon-1",
        raw_transcript=raw,
        pinned_lexicon=pinned_lex,
        projection_policy="candidate_only",
    )
    assert rep.canonical_transcript is None
    qashqai_cands = [c for c in rep.candidates if c.entity_id == "model:qashqai"]
    assert len(qashqai_cands) == 1
    cand = qashqai_cands[0]
    assert cand.raw_value == "kaş kay"
    assert raw[cand.source_span.start : cand.source_span.end_exclusive] == "kaş kay"
    assert cand.catalog_status == CatalogStatus.UNVERIFIED
    assert cand.confirmation_status == ConfirmationStatus.CANDIDATE
    assert rep.clarification_hint is not None
    assert rep.clarification_hint.required is True

    # 2. Explicit contrast against prior context -> CONFLICTING_CONTEXT, literal preserved
    ctx_hint = ContextHintSnapshot(
        session_id="sess-f2bc",
        incarnation_id="inc-1",
        state_revision=2,
        source_turn_id=1,
        captured_monotonic_ns=1_000_000,
        clock_domain="fake",
        confirmed_entity_ids=("model:qashqai",),
    )
    rep_contrast = resolve_automotive_entities(
        utterance_id="utt-contrast",
        raw_transcript="Qashqai değil, Juke",
        pinned_lexicon=pinned_lex,
        context_hint=ctx_hint,
        projection_policy="reviewed_canonical_projection",
    )
    assert rep_contrast.context_contradiction is True
    assert rep_contrast.canonical_transcript is None
    assert rep_contrast.clarification_hint is not None
    assert rep_contrast.clarification_hint.reason == ClarificationReason.CONFLICTING_CONTEXT

    # 3. Protected identifier never fuzzy-rewritten even under projection policy
    rep_prot = resolve_automotive_entities(
        utterance_id="utt-prot",
        raw_transcript="34 ABC 123 P0300",
        pinned_lexicon=pinned_lex,
        projection_policy="reviewed_canonical_projection",
    )
    assert rep_prot.candidates == ()
    assert rep_prot.canonical_transcript is None


def test_f2b_decode_arbitration_disagreement_keeps_primary() -> None:
    lex_reg = _build_lexicon()
    pinned_lex = pin_lexicon_snapshot(lex_reg)
    plan = HotwordPlanner().plan(
        scope_id="utt-arb",
        session_id="sess-f2bc",
        incarnation_id="inc-1",
        pinned_lexicon=pinned_lex,
        now_monotonic_ns=1_000_000,
        clock_domain="fake",
    )
    a0 = DecodeAttemptRecord(
        utterance_id="utt-arb",
        attempt_index=0,
        beam_profile=DecodeBeamProfile.FAST_FINAL,
        beam_size=1,
        hotword_plan=plan,
        outcome=ASROutcome.OK,
        raw_transcript="2020 Qashqai",
        avg_logprob=-0.75,
        no_speech_prob=0.1,
        compression_ratio=1.1,
    )
    r0 = resolve_automotive_entities(utterance_id="utt-arb", raw_transcript=a0.raw_transcript, pinned_lexicon=pinned_lex)
    run_alt, _ = should_run_alternate_decode(
        alternate_enabled=True,
        attempt0=a0,
        resolution0=r0,
        remaining_deadline_ms=5000,
    )
    assert run_alt is True

    a1 = DecodeAttemptRecord(
        utterance_id="utt-arb",
        attempt_index=1,
        beam_profile=DecodeBeamProfile.ALTERNATE_FINAL,
        beam_size=3,
        hotword_plan=plan,
        outcome=ASROutcome.OK,
        raw_transcript="2021 Qashqai",
        avg_logprob=-0.20,
        no_speech_prob=0.05,
        compression_ratio=1.1,
    )
    r1 = resolve_automotive_entities(utterance_id="utt-arb", raw_transcript=a1.raw_transcript, pinned_lexicon=pinned_lex)
    arb = arbitrate_decode_attempts(attempt0=a0, resolution0=r0, attempt1=a1, resolution1=r1)
    assert arb.disagreement is True
    assert arb.selected_attempt.attempt_index == 0
    assert arb.selected_attempt.raw_transcript == "2020 Qashqai"
    assert arb.clarification_hint is not None
    assert arb.clarification_hint.reason == ClarificationReason.DECODER_DISAGREEMENT


@pytest.mark.asyncio
async def test_f2b_pipeline_end_to_end_with_alternate_decode() -> None:
    clock = FakeClock(initial_ns=5_000_000_000)
    pinned_cfg, scheduler, ctx, turn = await _build_runtime(clock)
    lex_reg = _build_lexicon()

    calls: list[dict[str, object]] = []

    class FakeModel:
        def transcribe(self, audio, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return ([SimpleNamespace(text="kaşkay", start=0.0, end=0.5, avg_logprob=-0.75, no_speech_prob=0.1, compression_ratio=1.1)], SimpleNamespace(language="tr"))
            return ([SimpleNamespace(text="Qashqai", start=0.0, end=0.5, avg_logprob=-0.20, no_speech_prob=0.05, compression_ratio=1.1)], SimpleNamespace(language="tr"))

    engine = WhisperSchedulerEngine(scheduler, model_getter=FakeModel)
    consumer = InMemoryASRConsumer()
    pipeline = SpeechRecognitionPipeline(
        engine=engine,
        admission=ASRUtteranceAdmission(),
        consumer=consumer,
        telemetry=ASRTelemetryBridge(),
        lifecycle=ASRLifecycleManager(),
    )

    audio_fmt = AudioFormat(sample_rate_hz=16_000, channels=1, encoding=AudioEncoding.FLOAT32_LE)
    samples = np.full(16_000, 0.05, dtype=np.float32)
    utt = Utterance(
        utterance_id="utt-f2b-e2e",
        stream_ref=StreamRef(session_id="sess-f2bc", stream_id="in-1", direction=StreamDirection.INPUT, format_epoch=0),
        turn_ref=turn,
        start_sample=0,
        end_sample_exclusive=16_000,
        finalized=True,
        finalization_reason="endpoint",
        payload=samples.tobytes(),
    )
    ctx_hint = ContextHintSnapshot(
        session_id="sess-f2bc",
        incarnation_id="inc-1",
        state_revision=1,
        source_turn_id=0,
        captured_monotonic_ns=clock.monotonic_ns(),
        clock_domain=clock.clock_domain,
        lexicon_revision=lex_reg.lexicon_revision,
        confirmed_entity_ids=("brand:nissan", "model:qashqai"),
    )

    rec = await pipeline.process_utterance(
        utt,
        audio_fmt,
        session_ctx=ctx,
        pinned_config=pinned_cfg,
        lexicon_registry=lex_reg,
        context_hint=ctx_hint,
        enable_f2b=True,
        beam_profile=DecodeBeamProfile.FAST_FINAL,
        alternate_enabled=True,
    )

    assert len(calls) == 2
    assert rec.delivery.delivery_status == ASRDeliveryStatus.DELIVERED
    assert rec.result is not None
    assert rec.result.raw_transcript == "Qashqai"
    assert rec.result.entities[0].entity_id == "model:qashqai"
    assert rec.result.entities[0].catalog_status == CatalogStatus.UNVERIFIED
    assert rec.result.entities[0].confirmation_status == ConfirmationStatus.CANDIDATE
    assert rec.attempt_arbitration is not None
    assert rec.attempt_arbitration.selected_attempt.attempt_index == 1


# ---------------------------------------------------------------------------
# F2-C Tests: Pseudo-Streaming ASR, Stability, Semantic Hints & Final Seal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f2c_windowing_stability_contradiction_and_final_seal() -> None:
    clock = FakeClock(initial_ns=1_000_000_000)
    pinned_cfg, scheduler, ctx, turn = await _build_runtime(clock)
    lex_reg = _build_lexicon()
    pinned_lex = pin_lexicon_snapshot(lex_reg)

    scripted_outputs = [
        ("Aracım Nissan", [{"word": "Aracım", "start": 0.0, "end": 0.4}, {"word": "Nissan", "start": 0.4, "end": 0.8}]),
        ("Aracım Nissan Qashqai", [{"word": "Aracım", "start": 0.0, "end": 0.35}, {"word": "Nissan", "start": 0.35, "end": 0.7}, {"word": "Qashqai", "start": 0.7, "end": 1.2}]),
        ("Nissan Qashqai değil", [{"word": "Nissan", "start": 0.0, "end": 0.4}, {"word": "Qashqai", "start": 0.4, "end": 0.9}, {"word": "değil", "start": 0.9, "end": 1.3}]),
        ("Aracım Nissan Qashqai değil, Juke.", []),
    ]
    call_idx = 0

    class ScriptedModel:
        def transcribe(self, audio, **kwargs):
            nonlocal call_idx
            text, words = scripted_outputs[min(call_idx, len(scripted_outputs) - 1)]
            call_idx += 1
            return ([SimpleNamespace(text=text, start=0.0, end=1.0, avg_logprob=-0.2, no_speech_prob=0.05, compression_ratio=1.1, words=words or None)], SimpleNamespace(language="tr"))

    engine = WhisperSchedulerEngine(scheduler, model_getter=ScriptedModel)
    ctrl = PseudoStreamingController(
        engine=engine,
        config=StreamingWindowConfig(),
        pinned_lexicon=pinned_lex,
    )
    audio_fmt = AudioFormat(sample_rate_hz=16_000, channels=1, encoding=AudioEncoding.FLOAT32_LE)
    stream_ref = StreamRef(session_id="sess-f2bc", stream_id="in-1", direction=StreamDirection.INPUT, format_epoch=0)
    scope = ctrl.open_scope(
        SpeechScopeRef(
            session_id="sess-f2bc",
            incarnation_id="inc-1",
            stream_ref=stream_ref,
            speech_ref="speech-1",
            start_sample=0,
            turn_ref=None,
        )
    )
    assert scope.turn_ref is None

    # Below 12,800 samples warm-up -> no window planned
    ctrl.append_audio("speech-1", np.full(12_799, 0.02, dtype=np.float32), audio_format=audio_fmt)
    assert ctrl.plan_next_window("speech-1", pinned_config=pinned_cfg) is None

    # Reach 12,800 samples -> first P5 partial window
    ctrl.append_audio("speech-1", np.full(1, 0.02, dtype=np.float32), audio_format=audio_fmt)
    w1 = ctrl.plan_next_window("speech-1", pinned_config=pinned_cfg)
    assert w1 is not None and (w1.start_sample, w1.end_sample_exclusive) == (0, 12_800)
    r1 = await ctrl.run_partial_window(w1, pinned_config=pinned_cfg, audio_format=audio_fmt)
    assert r1 is not None
    assert r1.revision == 1
    assert r1.status == ASRStatus.PARTIAL
    assert r1.stable_prefix is None
    assert r1.actionable is False
    assert r1.business_action_eligible is False

    # Add 8,000 samples (20,800 total) -> w2, stable prefix emerges
    ctrl.append_audio("speech-1", np.full(8_000, 0.02, dtype=np.float32), audio_format=audio_fmt)
    w2 = ctrl.plan_next_window("speech-1", pinned_config=pinned_cfg)
    assert w2 is not None
    r2 = await ctrl.run_partial_window(w2, pinned_config=pinned_cfg, audio_format=audio_fmt)
    assert r2 is not None
    assert r2.revision == 2
    assert r2.status == ASRStatus.STABLE_PREFIX
    assert r2.stable_prefix == "Aracım Nissan"
    assert r2.independent_observations == 2

    # Add 8,000 samples (28,800 total) -> w3, negation preserved & hint active
    ctrl.append_audio("speech-1", np.full(8_000, 0.02, dtype=np.float32), audio_format=audio_fmt)
    w3 = ctrl.plan_next_window("speech-1", pinned_config=pinned_cfg)
    assert w3 is not None
    r3 = await ctrl.run_partial_window(w3, pinned_config=pinned_cfg, audio_format=audio_fmt)
    assert r3 is not None
    assert r3.revision == 3
    assert r3.derived_view == "Aracım Nissan Qashqai değil"

    hint = ctrl.get_semantic_hint("speech-1")
    assert hint is not None
    assert hint.continuation_cue == ContinuationCue.POSSIBLE_CONTINUATION
    assert hint.actionable is False

    # TTL expiry -> hint returns None
    clock.advance_ms(800)
    assert ctrl.get_semantic_hint("speech-1") is None

    # Seal on authoritative F1-A UTTERANCE_FINALIZED (coverage shortened to 24,000 < 28,800)
    final_utt = Utterance(
        utterance_id="utt-final-1",
        stream_ref=stream_ref,
        turn_ref=turn,
        start_sample=0,
        end_sample_exclusive=24_000,
        finalized=True,
        finalization_reason="eos",
        payload=np.full(24_000, 0.02, dtype=np.float32).tobytes(),
    )
    binding = ctrl.seal_for_finalization(
        "speech-1",
        utterance=final_utt,
        turn_ref=turn,
        final_claim_id="claim-1",
    )
    assert ctrl.get_state("speech-1") == PartialLaneState.SEALED_FINALIZING
    assert binding.sealed_partial_high_watermark == 3
    assert binding.coverage_shortened is True
    assert ctrl.plan_next_window("speech-1", pinned_config=pinned_cfg) is None

    # Authoritative P1 final decode has revision > sealed_partial_high_watermark
    pipeline = SpeechRecognitionPipeline(
        engine=engine,
        admission=ASRUtteranceAdmission(),
        consumer=InMemoryASRConsumer(),
    )
    final_rec = await pipeline.process_utterance(
        final_utt,
        audio_fmt,
        session_ctx=ctx,
        pinned_config=pinned_cfg,
        lexicon_registry=lex_reg,
        enable_f2b=True,
        min_revision=binding.sealed_partial_high_watermark + 1,
    )
    assert final_rec.result is not None
    assert final_rec.result.status == ASRStatus.FINAL
    assert final_rec.result.revision == 4
    assert final_rec.result.raw_transcript == "Aracım Nissan Qashqai değil, Juke."

    ctrl.mark_terminal("speech-1")
    assert ctrl.get_state("speech-1") == PartialLaneState.TERMINAL
    with pytest.raises(ValueError):
        ctrl.open_scope(scope)


@pytest.mark.asyncio
async def test_f2c_invalid_word_timestamps_rejected_without_fabrication() -> None:
    clock = FakeClock(initial_ns=2_000_000_000)
    pinned_cfg, scheduler, _, _ = await _build_runtime(clock)

    class BadTsModel:
        def transcribe(self, audio, **kwargs):
            return (
                [
                    SimpleNamespace(
                        text="Nissan",
                        start=0.0,
                        end=0.5,
                        avg_logprob=-0.2,
                        no_speech_prob=0.05,
                        compression_ratio=1.0,
                        words=[{"word": "Nissan", "start": -0.5, "end": 0.2}],
                    )
                ],
                SimpleNamespace(language="tr"),
            )

    engine = WhisperSchedulerEngine(scheduler, model_getter=BadTsModel)
    ctrl = PseudoStreamingController(engine=engine)
    audio_fmt = AudioFormat(sample_rate_hz=16_000, channels=1, encoding=AudioEncoding.FLOAT32_LE)
    stream_ref = StreamRef(session_id="sess-f2bc", stream_id="in-2", direction=StreamDirection.INPUT, format_epoch=0)
    ctrl.open_scope(
        SpeechScopeRef(
            session_id="sess-f2bc",
            incarnation_id="inc-1",
            stream_ref=stream_ref,
            speech_ref="speech-bad-ts",
            start_sample=0,
        )
    )
    ctrl.append_audio("speech-bad-ts", np.full(12_800, 0.02, dtype=np.float32), audio_format=audio_fmt)
    win = ctrl.plan_next_window("speech-bad-ts", pinned_config=pinned_cfg)
    assert win is not None
    rev = await ctrl.run_partial_window(win, pinned_config=pinned_cfg, audio_format=audio_fmt)
    assert rev is not None
    assert rev.raw_transcript == "Nissan"
    assert rev.timestamp_status == "UNKNOWN"


def test_f2bc_passive_imports_no_threads_spawned() -> None:
    code = (
        "import threading; "
        "b = threading.active_count(); "
        "import backend.speech_recognition; "
        "a = threading.active_count(); "
        "assert a == b, f'Threads spawned on import: {a - b}'"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr or proc.stdout
