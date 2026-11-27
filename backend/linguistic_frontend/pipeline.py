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
from typing import Callable

from backend.core.configuration.contracts import ConfigSnapshot
from backend.core.contracts.common import GenerationRef, MetricSample
from backend.core.contracts.dialogue import DialogueResponse
from backend.core.contracts.synthesis import SynthesisPlan
from backend.core.model_registry.registry import ModelRegistry
from backend.core.model_registry.voice_profiles import VoiceProfileRegistry
from backend.linguistic_frontend.chunking_adapter import chunk_normalized_text
from backend.linguistic_frontend.f4_b_morphology import F4BMorphologyBundle, analyze_f4b_morphology
from backend.linguistic_frontend.f4_c_prosody import F4CProsodyBundle, plan_f4c_prosody_and_chunks
from backend.linguistic_frontend.config_adapter import (
    DEFAULT_MAX_CHUNK_CHARS,
    DEFAULT_MAX_CHUNK_WORDS,
    DEFAULT_MAX_EXPANDED_CHARS,
    DEFAULT_MAX_TOTAL_CHUNKS,
    PinnedFrontendSnapshot,
    pin_frontend_snapshot,
)
from backend.linguistic_frontend.freya_adapter import FreyaVocabularyValidator, VocabularyCheck
from backend.linguistic_frontend.input_validator import (
    DEFAULT_MAX_INPUT_CHARS,
    InputValidationResult,
    PlanningOutcome,
    ResponseDedupLedger,
    compute_response_content_digest,
    validate_dialogue_response,
)
from backend.linguistic_frontend.lexicon_adapter import LexiconAdapter, VariantGovernanceStatus
from backend.linguistic_frontend.morphology_adapter import MorphologyAnalysisResult, analyze_morphology_readonly
from backend.linguistic_frontend.plan_builder import build_synthesis_plan, make_plan_id
from backend.linguistic_frontend.protected_atoms import ProtectedAtom
from backend.linguistic_frontend.quality_gate import validate_plan_quality
from backend.linguistic_frontend.semantic_tokenizer import tokenize_semantic_atoms
from backend.linguistic_frontend.telemetry import LinguisticTelemetry
from backend.linguistic_frontend.text_mapping import NormalizationTrace, TextMapping
from backend.linguistic_frontend.text_normalizer import run_single_normalization_pass
from backend.shared_lexicon.registry import LexiconRegistry


@dataclass(frozen=True, slots=True)
class PreparationResult:
    """Complete result of a single F4-A linguistic preparation pass."""

    ok: bool
    outcome: PlanningOutcome
    plan: SynthesisPlan | None = None
    reason_code: str = "OK"
    safe_message: str = ""
    normalization_passes: int = 0
    atoms: tuple[ProtectedAtom, ...] = ()
    text_mapping: TextMapping | None = None
    trace: NormalizationTrace | None = None
    morphology: MorphologyAnalysisResult | None = None
    f4b_morphology: F4BMorphologyBundle | None = None
    f4c_prosody: F4CProsodyBundle | None = None
    vocab_checks: tuple[VocabularyCheck, ...] = ()
    metrics: tuple[MetricSample, ...] = ()
    duplicate_of_plan_id: str | None = None


@dataclass(frozen=True, slots=True)
class ShadowComparisonResult:
    """Side-effect-free shadow comparison between F4-A strict output and legacy output."""

    strict_ok: bool
    strict_normalized_text: str
    legacy_normalized_text: str
    texts_equal: bool
    strict_reason_code: str
    dispatched: bool = False


class LinguisticFrontendPipeline:
    """
    Single strict F4-A normalization and planning authority.

    Guarantees normalization_passes=1 per admitted DialogueResponse, pins M03/M05
    snapshots, protects semantic atoms, checks Freya vocab CPU-only, and builds an
    immutable M01 SynthesisPlan.
    """

    def __init__(
        self,
        *,
        config_snapshot_provider: Callable[[], ConfigSnapshot] | None = None,
        model_registry_provider: Callable[[ConfigSnapshot], ModelRegistry] | None = None,
        voice_registry_provider: Callable[[], VoiceProfileRegistry] | None = None,
        lexicon_registry_provider: Callable[[], LexiconRegistry] | None = None,
        vocab_validator_factory: Callable[[PinnedFrontendSnapshot], FreyaVocabularyValidator] | None = None,
        variant_governance: dict[str, VariantGovernanceStatus] | None = None,
        telemetry: LinguisticTelemetry | None = None,
        dedup_ledger: ResponseDedupLedger | None = None,
        require_real_vocab: bool = True,
        strict_enabled: bool = False,
        max_input_chars: int = DEFAULT_MAX_INPUT_CHARS,
        max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
        max_chunk_words: int = DEFAULT_MAX_CHUNK_WORDS,
        max_total_chunks: int = DEFAULT_MAX_TOTAL_CHUNKS,
        max_expanded_chars: int = DEFAULT_MAX_EXPANDED_CHARS,
    ) -> None:
        self._config_provider = config_snapshot_provider
        self._model_provider = model_registry_provider
        self._voice_provider = voice_registry_provider
        self._lexicon_provider = lexicon_registry_provider
        self._vocab_factory = vocab_validator_factory
        self._variant_governance = dict(variant_governance or {})
        self._telemetry = telemetry or LinguisticTelemetry()
        self._dedup_ledger = dedup_ledger if dedup_ledger is not None else ResponseDedupLedger()
        self._require_real_vocab = require_real_vocab
        self._strict_enabled = strict_enabled
        self._max_input_chars = max_input_chars
        self._max_chunk_chars = max_chunk_chars
        self._max_chunk_words = max_chunk_words
        self._max_total_chunks = max_total_chunks
        self._max_expanded_chars = max_expanded_chars

    @property
    def telemetry(self) -> LinguisticTelemetry:
        return self._telemetry

    @property
    def dedup_ledger(self) -> ResponseDedupLedger:
        return self._dedup_ledger

    def validate_only(
        self,
        response: object,
        *,
        expected_session_id: str | None = None,
        expected_turn_id: int | None = None,
        min_state_revision: int | None = None,
        expected_asr_revision: int | None = None,
        incarnation_id: str = "default",
    ) -> InputValidationResult:
        return validate_dialogue_response(
            response,
            expected_session_id=expected_session_id,
            expected_turn_id=expected_turn_id,
            min_state_revision=min_state_revision,
            expected_asr_revision=expected_asr_revision,
            incarnation_id=incarnation_id,
            max_input_chars=self._max_input_chars,
            dedup_ledger=self._dedup_ledger,
        )

    def commit_dedup(
        self,
        response: DialogueResponse,
        *,
        incarnation_id: str,
        plan: SynthesisPlan,
    ) -> None:
        turn_id = response.envelope.turn_id
        if turn_id is None:
            raise ValueError("DialogueResponse missing turn_id")
        self._dedup_ledger.record(
            session_id=response.envelope.session_id,
            incarnation_id=incarnation_id,
            turn_id=turn_id,
            response_id=response.response_id,
            content_digest=compute_response_content_digest(response),
            plan_id=plan.plan_id,
            plan_revision=plan.plan_revision,
        )

    def prepare_response(
        self,
        response: object,
        *,
        generation_ref: GenerationRef | None = None,
        expected_session_id: str | None = None,
        expected_turn_id: int | None = None,
        min_state_revision: int | None = None,
        expected_asr_revision: int | None = None,
        incarnation_id: str = "default",
        plan_revision: int = 0,
        requested_seed: int | None = None,
        requested_profile_id: str | None = None,
        experimental_seeds_enabled: bool = False,
        config_snapshot: ConfigSnapshot | None = None,
        model_registry: ModelRegistry | None = None,
        voice_registry: VoiceProfileRegistry | None = None,
        lexicon_registry: LexiconRegistry | None = None,
        commit_dedup: bool = True,
    ) -> PreparationResult:
        """
        Single strict F4-A entry point:
        admit response -> pin M03/M05 snapshots -> scan protected atoms ->
        run single-pass normalization -> read-only morphology -> safe chunking ->
        Freya vocab check -> build immutable M01 SynthesisPlan -> quality gate.
        """
        start_ns = self._telemetry.monotonic_ns()
        start_domain = self._telemetry.clock_domain

        # 1. Input admission & dedup check
        val_res = validate_dialogue_response(
            response,
            expected_session_id=expected_session_id,
            expected_turn_id=expected_turn_id,
            min_state_revision=min_state_revision,
            expected_asr_revision=expected_asr_revision,
            incarnation_id=incarnation_id,
            max_input_chars=self._max_input_chars,
            dedup_ledger=self._dedup_ledger,
        )

        sess_id = response.envelope.session_id if isinstance(response, DialogueResponse) else (expected_session_id or "unknown")
        trace_id = response.envelope.trace_id if isinstance(response, DialogueResponse) else None
        turn_id = response.envelope.turn_id if isinstance(response, DialogueResponse) else expected_turn_id

        if val_res.outcome != PlanningOutcome.ADMITTED or val_res.admitted is None:
            is_stale_dup = val_res.outcome in {PlanningOutcome.STALE, PlanningOutcome.CONFLICT} or val_res.reason_code == "DUPLICATE_RESPONSE"
            metrics = self._telemetry.record_plan_outcome(
                session_id=sess_id,
                trace_id=trace_id,
                turn_id=turn_id,
                generation_id=generation_ref.generation_id if generation_ref else None,
                plan_id=val_res.duplicate_of_plan_id,
                plan_revision=None,
                status=val_res.outcome.value,
                reason_code=val_res.reason_code,
                start_ns=start_ns,
                start_clock_domain=start_domain,
                normalization_passes=0,
                stage_count=0,
                atom_count=0,
                unresolved_count=0,
                chunk_count=0,
                vocab_rejections=0,
                stale_or_duplicate=is_stale_dup,
            )
            return PreparationResult(
                ok=False,
                outcome=val_res.outcome,
                reason_code=val_res.reason_code,
                safe_message=val_res.safe_message,
                normalization_passes=0,
                metrics=metrics,
                duplicate_of_plan_id=val_res.duplicate_of_plan_id,
            )

        admitted = val_res.admitted
        eff_gen_ref = generation_ref
        if eff_gen_ref is None:
            eff_gen_ref = GenerationRef(
                session_id=admitted.session_id,
                turn_id=admitted.turn_id,
                generation_id=admitted.response.envelope.generation_id or 0,
            )
        elif eff_gen_ref.session_id != admitted.session_id or eff_gen_ref.turn_id != admitted.turn_id:
            metrics = self._telemetry.record_plan_outcome(
                session_id=admitted.session_id,
                trace_id=trace_id,
                turn_id=admitted.turn_id,
                generation_id=eff_gen_ref.generation_id,
                plan_id=None,
                plan_revision=None,
                status=PlanningOutcome.STALE.value,
                reason_code="GENERATION_SCOPE_MISMATCH",
                start_ns=start_ns,
                start_clock_domain=start_domain,
                normalization_passes=0,
                stage_count=0,
                atom_count=0,
                unresolved_count=0,
                chunk_count=0,
                vocab_rejections=0,
                stale_or_duplicate=True,
            )
            return PreparationResult(
                ok=False,
                outcome=PlanningOutcome.STALE,
                reason_code="GENERATION_SCOPE_MISMATCH",
                safe_message="generation_ref does not match admitted response scope",
                normalization_passes=0,
                metrics=metrics,
            )

        # 2. Pin M03 & M05 immutable snapshots
        cfg = config_snapshot or (self._config_provider() if self._config_provider else None)
        mreg = model_registry or (self._model_provider(cfg) if (self._model_provider and cfg) else None)
        vreg = voice_registry or (self._voice_provider() if self._voice_provider else None)
        lreg = lexicon_registry or (self._lexicon_provider() if self._lexicon_provider else None)

        pin_res = pin_frontend_snapshot(
            config_snapshot=cfg,
            model_registry=mreg,
            voice_registry=vreg,
            lexicon_registry=lreg,
            requested_seed=requested_seed,
            requested_profile_id=requested_profile_id,
            experimental_seeds_enabled=experimental_seeds_enabled,
            strict_enabled=self._strict_enabled,
            max_input_chars=self._max_input_chars,
            max_chunk_chars=self._max_chunk_chars,
            max_chunk_words=self._max_chunk_words,
            max_total_chunks=self._max_total_chunks,
            max_expanded_chars=self._max_expanded_chars,
        )
        if not pin_res.ok or pin_res.snapshot is None:
            metrics = self._telemetry.record_plan_outcome(
                session_id=admitted.session_id,
                trace_id=trace_id,
                turn_id=admitted.turn_id,
                generation_id=eff_gen_ref.generation_id,
                plan_id=None,
                plan_revision=None,
                status=PlanningOutcome.REJECTED.value,
                reason_code=pin_res.reason_code,
                start_ns=start_ns,
                start_clock_domain=start_domain,
                normalization_passes=0,
                stage_count=0,
                atom_count=0,
                unresolved_count=0,
                chunk_count=0,
                vocab_rejections=0,
                stale_or_duplicate=False,
            )
            return PreparationResult(
                ok=False,
                outcome=PlanningOutcome.REJECTED,
                reason_code=pin_res.reason_code,
                safe_message=pin_res.safe_message,
                normalization_passes=0,
                metrics=metrics,
            )
        pinned = pin_res.snapshot

        lex_adapter = LexiconAdapter(
            pinned.lexicon_registry,
            variant_governance=self._variant_governance,
        )

        # 3. Protected atom scan + F3 semantic fact verification
        sem_res = tokenize_semantic_atoms(
            admitted.speech_text,
            verified_fact_refs=admitted.response.verified_fact_refs,
            lexicon_adapter=lex_adapter,
        )
        if not sem_res.ok:
            unresolved_cnt = sum(1 for a in sem_res.atoms if a.unresolved)
            metrics = self._telemetry.record_plan_outcome(
                session_id=admitted.session_id,
                trace_id=trace_id,
                turn_id=admitted.turn_id,
                generation_id=eff_gen_ref.generation_id,
                plan_id=None,
                plan_revision=None,
                status=PlanningOutcome.REJECTED.value,
                reason_code=sem_res.reason_code,
                start_ns=start_ns,
                start_clock_domain=start_domain,
                normalization_passes=0,
                stage_count=0,
                atom_count=len(sem_res.atoms),
                unresolved_count=unresolved_cnt,
                chunk_count=0,
                vocab_rejections=0,
                stale_or_duplicate=False,
            )
            return PreparationResult(
                ok=False,
                outcome=PlanningOutcome.REJECTED,
                reason_code=sem_res.reason_code,
                safe_message="Protected semantic validation failed",
                normalization_passes=0,
                atoms=sem_res.atoms,
                metrics=metrics,
            )

        plan_id = make_plan_id(
            session_id=eff_gen_ref.session_id,
            turn_id=eff_gen_ref.turn_id,
            generation_id=eff_gen_ref.generation_id,
            response_id=admitted.response_id,
            plan_revision=plan_revision,
        )

        # 4. Single strict normalization pass (normalization_passes=1)
        norm_res = run_single_normalization_pass(
            admitted.speech_text,
            atoms=sem_res.atoms,
            response_id=admitted.response_id,
            plan_id=plan_id,
            lexicon_adapter=lex_adapter,
            max_expanded_chars=pinned.max_expanded_chars,
        )
        if not norm_res.ok or norm_res.text_mapping is None:
            metrics = self._telemetry.record_plan_outcome(
                session_id=admitted.session_id,
                trace_id=trace_id,
                turn_id=admitted.turn_id,
                generation_id=eff_gen_ref.generation_id,
                plan_id=plan_id,
                plan_revision=plan_revision,
                status=PlanningOutcome.REJECTED.value,
                reason_code=norm_res.reason_code,
                start_ns=start_ns,
                start_clock_domain=start_domain,
                normalization_passes=norm_res.normalization_passes,
                stage_count=len(norm_res.trace.stage_ids),
                atom_count=len(norm_res.atoms_mapped),
                unresolved_count=0,
                chunk_count=0,
                vocab_rejections=0,
                stale_or_duplicate=False,
            )
            return PreparationResult(
                ok=False,
                outcome=PlanningOutcome.REJECTED,
                reason_code=norm_res.reason_code,
                safe_message=norm_res.safe_message,
                normalization_passes=norm_res.normalization_passes,
                atoms=norm_res.atoms_mapped,
                trace=norm_res.trace,
                metrics=metrics,
            )

        # 5. Read-only morphology & clitic hints (kept separate from model_text)
        morph_res = analyze_morphology_readonly(
            norm_res.normalized_text,
            enabled=pinned.morph_precheck_enabled,
            pause_ms=pinned.morph_precheck_pause_ms,
        )

        # 5b. F4-B source-aligned Turkish morphology, pronunciation basis & private G2P guidance
        f4b_res = analyze_f4b_morphology(
            admitted.speech_text,
            atoms=norm_res.atoms_mapped,
            lexicon_adapter=lex_adapter,
            model_scope=pinned.model_revision,
            locale=pinned.language,
        )

        # 6. F4-C prosody, syllabification, stress, clitic/liaison & semantic boundary chunking
        chunk_res, f4c_res = plan_f4c_prosody_and_chunks(
            norm_res.normalized_text,
            atoms=norm_res.atoms_mapped,
            text_mapping=norm_res.text_mapping,
            speech_act=admitted.speech_act,
            focus_entity_refs=admitted.response.focus_entity_refs,
            f4b_bundle=f4b_res,
            max_chunk_chars=pinned.max_chunk_chars,
            max_chunk_words=pinned.max_chunk_words,
            max_total_chunks=pinned.max_total_chunks,
            clitic_pause_ms=morph_res.clitic_pause_ms,
            emphasis_targets=morph_res.emphasis_targets,
        )
        if not chunk_res.ok:
            metrics = self._telemetry.record_plan_outcome(
                session_id=admitted.session_id,
                trace_id=trace_id,
                turn_id=admitted.turn_id,
                generation_id=eff_gen_ref.generation_id,
                plan_id=plan_id,
                plan_revision=plan_revision,
                status=PlanningOutcome.REJECTED.value,
                reason_code=chunk_res.reason_code,
                start_ns=start_ns,
                start_clock_domain=start_domain,
                normalization_passes=norm_res.normalization_passes,
                stage_count=len(norm_res.trace.stage_ids),
                atom_count=len(norm_res.atoms_mapped),
                unresolved_count=0,
                chunk_count=0,
                vocab_rejections=0,
                stale_or_duplicate=False,
            )
            return PreparationResult(
                ok=False,
                outcome=PlanningOutcome.REJECTED,
                reason_code=chunk_res.reason_code,
                safe_message=chunk_res.safe_message,
                normalization_passes=norm_res.normalization_passes,
                atoms=norm_res.atoms_mapped,
                text_mapping=norm_res.text_mapping,
                trace=norm_res.trace,
                morphology=morph_res,
                f4b_morphology=f4b_res,
                f4c_prosody=f4c_res,
                metrics=metrics,
            )

        # 7. Build immutable M01 SynthesisPlan
        plan = build_synthesis_plan(
            generation_ref=eff_gen_ref,
            response_id=admitted.response_id,
            plan_revision=plan_revision,
            source_text=admitted.speech_text,
            normalized_text=norm_res.normalized_text,
            speech_act=admitted.speech_act,
            pinned=pinned,
            chunk_candidates=chunk_res.chunks,
            warnings=norm_res.warnings + morph_res.warnings + f4b_res.warnings + f4c_res.warnings,
            plan_id=plan_id,
        )

        # 8. CPU-only Freya vocabulary + semantic quality gate
        if self._vocab_factory is not None:
            vocab_val = self._vocab_factory(pinned)
        else:
            vocab_val = FreyaVocabularyValidator.from_vocab_file(
                pinned.freya_vocab_path,
                model_revision=pinned.model_revision,
                capability_revision=pinned.capability_revision,
                max_sequence_chars=pinned.max_chunk_chars,
            )

        gate = validate_plan_quality(
            plan,
            expected_source_text=admitted.speech_text,
            atoms=norm_res.atoms_mapped,
            pinned=pinned,
            vocab_validator=vocab_val,
            require_real_vocab=self._require_real_vocab,
        )
        if not gate.ok:
            metrics = self._telemetry.record_plan_outcome(
                session_id=admitted.session_id,
                trace_id=trace_id,
                turn_id=admitted.turn_id,
                generation_id=eff_gen_ref.generation_id,
                plan_id=plan_id,
                plan_revision=plan_revision,
                status=PlanningOutcome.REJECTED.value,
                reason_code=gate.reason_code,
                start_ns=start_ns,
                start_clock_domain=start_domain,
                normalization_passes=norm_res.normalization_passes,
                stage_count=len(norm_res.trace.stage_ids),
                atom_count=len(norm_res.atoms_mapped),
                unresolved_count=0,
                chunk_count=len(plan.chunks),
                vocab_rejections=gate.vocab_rejections,
                stale_or_duplicate=False,
            )
            return PreparationResult(
                ok=False,
                outcome=PlanningOutcome.REJECTED,
                reason_code=gate.reason_code,
                safe_message=gate.safe_message,
                normalization_passes=norm_res.normalization_passes,
                atoms=norm_res.atoms_mapped,
                text_mapping=norm_res.text_mapping,
                trace=norm_res.trace,
                morphology=morph_res,
                f4b_morphology=f4b_res,
                f4c_prosody=f4c_res,
                vocab_checks=gate.vocab_checks,
                metrics=metrics,
            )

        if commit_dedup:
            self.commit_dedup(admitted.response, incarnation_id=incarnation_id, plan=plan)

        metrics = self._telemetry.record_plan_outcome(
            session_id=admitted.session_id,
            trace_id=trace_id,
            turn_id=admitted.turn_id,
            generation_id=eff_gen_ref.generation_id,
            plan_id=plan.plan_id,
            plan_revision=plan.plan_revision,
            status=PlanningOutcome.ADMITTED.value,
            reason_code="OK",
            start_ns=start_ns,
            start_clock_domain=start_domain,
            normalization_passes=1,
            stage_count=len(norm_res.trace.stage_ids),
            atom_count=len(norm_res.atoms_mapped),
            unresolved_count=0,
            chunk_count=len(plan.chunks),
            vocab_rejections=0,
            stale_or_duplicate=False,
        )
        return PreparationResult(
            ok=True,
            outcome=PlanningOutcome.ADMITTED,
            plan=plan,
            reason_code="OK",
            normalization_passes=1,
            atoms=norm_res.atoms_mapped,
            text_mapping=norm_res.text_mapping,
            trace=norm_res.trace,
            morphology=morph_res,
            f4b_morphology=f4b_res,
            f4c_prosody=f4c_res,
            vocab_checks=gate.vocab_checks,
            metrics=metrics,
        )

    def shadow_compare(
        self,
        response: DialogueResponse,
        *,
        config_snapshot: ConfigSnapshot | None = None,
        lexicon_registry: LexiconRegistry | None = None,
    ) -> ShadowComparisonResult:
        """
        Side-effect-free shadow comparison (no dedup write, no generation allocation,
        no speech dispatch).
        """
        from backend.linguistic_frontend.legacy_adapter import legacy_normalize

        res = self.prepare_response(
            response,
            config_snapshot=config_snapshot,
            lexicon_registry=lexicon_registry,
            commit_dedup=False,
        )
        legacy_out = legacy_normalize(response.speech_text)["normalized"]
        strict_norm = res.plan.normalized_text if res.plan is not None else ""
        return ShadowComparisonResult(
            strict_ok=res.ok,
            strict_normalized_text=strict_norm,
            legacy_normalized_text=legacy_out,
            texts_equal=(strict_norm == legacy_out),
            strict_reason_code=res.reason_code,
            dispatched=False,
        )
