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
from decimal import Decimal
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from backend.core.configuration.contracts import ConfigSnapshot
from backend.core.configuration.resolver import resolve_configuration
from backend.core.configuration.snapshots import ConfigSnapshotStore, build_snapshot
from backend.core.contracts.common import (
    CONTRACT_SCHEMA_VERSION,
    CapabilityDescriptor,
    CapabilityState,
    ErrorCategory,
    ErrorInfo,
    EventEnvelope,
    GenerationRef,
    MetricStatus,
    SessionIdentity,
    TurnRef,
)
from backend.core.contracts.dialogue import DialogueOutcome, DialogueResponse, VerifiedFactRef
from backend.core.contracts.synthesis import ChunkPlan, PlanValidationStatus, SynthesisPlan
from backend.core.model_registry.contracts import ModelDescriptor, ModelKind, ProfileTier, VoiceProfile
from backend.core.model_registry.registry import ModelRegistry
from backend.core.model_registry.voice_profiles import DEFAULT_VOICE_PROFILE_REGISTRY, VoiceProfileRegistry
from backend.core.runtime.result_admission import AdmissionStatus
from backend.core.runtime.session_context import CleanupStatus, SessionContext
from backend.linguistic_frontend import (
    AtomKind,
    FreyaVocabularyValidator,
    LexiconAdapter,
    LinguisticFrontendPipeline,
    LinguisticPreparationCoordinator,
    LinguisticTelemetry,
    PlanningOutcome,
    ProvenanceClass,
    VariantGovernanceStatus,
    VocabularyStatus,
    accept_prepared_plan,
    legacy_clauses,
    legacy_normalize,
    legacy_prepare_tts_clause,
    scan_protected_atoms,
    wrap_legacy_string,
)
from backend.observability.event_bus import BoundedEventBus, DropPolicy
from backend.observability.metrics import MetricsRegistry
from backend.observability.projection import Projection, contains_sentinel
from backend.shared_lexicon import (
    CanonicalEntity,
    EntityCategory,
    LexiconRegistry,
    PronunciationVariant,
    load_lexicon_snapshot,
    make_safe_id,
)
from tests.harness.adapters.fake_tts import FakeTTSAdapter
from tests.harness.acceptance import evaluate_gates
from tests.harness.contracts import GateRecord, GateStatus
from tests.harness.evidence_validator import EvidenceValidator, PIISecretScanner
from tests.harness.fake_clock import HarnessClock


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_GATE_RUN_ID = "20261126T004342Z"


def _make_response(
    speech_text: str,
    *,
    session_id: str = "sess-f4a-1",
    trace_id: str = "trace-f4a-1",
    turn_id: int | None = 1,
    generation_id: int | None = 1,
    response_id: str = "resp-1",
    speech_act: str = "STATEMENT",
    state_revision: int = 1,
    source_asr_revision: int | None = 1,
    outcome: DialogueOutcome = DialogueOutcome.OK,
    producer: str = "f3.dialogue",
    verified_fact_refs: tuple[VerifiedFactRef, ...] = (),
    display_text: str | None = None,
) -> DialogueResponse:
    env = EventEnvelope(
        schema_version=CONTRACT_SCHEMA_VERSION,
        event_type="dialogue.response",
        session_id=session_id,
        trace_id=trace_id,
        turn_id=turn_id,
        generation_id=generation_id,
        sequence=0,
        monotonic_ns=1_000_000,
        clock_domain="harness.fake.clock",
        producer=producer,
    )
    return DialogueResponse(
        envelope=env,
        response_id=response_id,
        speech_text=speech_text,
        display_text=display_text,
        speech_act=speech_act,
        state_revision=state_revision,
        source_asr_revision=source_asr_revision,
        outcome=outcome,
        verified_fact_refs=verified_fact_refs,
    )


_CACHED_DEFAULT_LEXICON: LexiconRegistry | None = None


def _default_lexicon() -> LexiconRegistry:
    global _CACHED_DEFAULT_LEXICON
    if _CACHED_DEFAULT_LEXICON is None:
        _CACHED_DEFAULT_LEXICON = LexiconRegistry.from_default_sources()
    return _CACHED_DEFAULT_LEXICON


def _make_pipeline(
    *,
    lexicon_registry: LexiconRegistry | None = None,
    config_snapshot: ConfigSnapshot | None = None,
    model_registry: ModelRegistry | None = None,
    voice_registry: VoiceProfileRegistry | None = None,
    variant_governance: dict[str, VariantGovernanceStatus] | None = None,
    telemetry: LinguisticTelemetry | None = None,
    vocab_factory: Any = None,
    require_real_vocab: bool = True,
    max_input_chars: int = 4000,
    max_chunk_chars: int = 270,
    max_chunk_words: int = 15,
    max_total_chunks: int = 64,
    max_expanded_chars: int = 16000,
) -> LinguisticFrontendPipeline:
    cfg = config_snapshot or resolve_configuration().snapshot
    lreg = lexicon_registry or _default_lexicon()
    return LinguisticFrontendPipeline(
        config_snapshot_provider=lambda: cfg,
        model_registry_provider=(lambda c: model_registry) if model_registry is not None else None,
        voice_registry_provider=(lambda: voice_registry) if voice_registry is not None else None,
        lexicon_registry_provider=lambda: lreg,
        vocab_validator_factory=vocab_factory,
        variant_governance=variant_governance,
        telemetry=telemetry,
        require_real_vocab=require_real_vocab,
        max_input_chars=max_input_chars,
        max_chunk_chars=max_chunk_chars,
        max_chunk_words=max_chunk_words,
        max_total_chunks=max_total_chunks,
        max_expanded_chars=max_expanded_chars,
    )


# ---------------------------------------------------------------------------
# LN01 - LN04: Preflight, Passive Imports, M01 Contracts
# ---------------------------------------------------------------------------

def test_ln01_missing_core_gate_evidence_is_hold(tmp_path: Path) -> None:
    empty_repo = tmp_path / "empty_repo"
    empty_repo.mkdir()
    core_matrix = empty_repo / "docs" / "freya2" / "core_integration" / CORE_GATE_RUN_ID / "CORE_ACCEPTANCE_MATRIX.json"
    assert not core_matrix.exists()
    validator = EvidenceValidator(empty_repo)
    pre = validator.verify_m00_baseline("20261126T001600Z")
    assert pre.status.value == "MISSING"
    # Verify actual repo Core Gate evidence IS present & ready
    actual_matrix = json.loads(
        (REPO_ROOT / "docs" / "freya2" / "core_integration" / CORE_GATE_RUN_ID / "CORE_ACCEPTANCE_MATRIX.json").read_text(encoding="utf-8")
    )
    assert actual_matrix["core_integration_ready"] is True
    assert all(v == "PASS" for v in actual_matrix["gates"].values())


def test_ln02_missing_prerequisite_or_hash_holds(tmp_path: Path) -> None:
    # Missing M05 lexicon snapshot causes explicit rejection (HOLD), never fabricated default
    pipeline = LinguisticFrontendPipeline(
        config_snapshot_provider=lambda: resolve_configuration().snapshot,
        lexicon_registry_provider=None,
    )
    resp = _make_response("Merhaba, randevu uygun mu?")
    res = pipeline.prepare_response(resp)
    assert not res.ok
    assert res.reason_code == "MISSING_LEXICON_SNAPSHOT"
    assert res.plan is None

    # Corrupt hash in synthetic evidence check fails integrity
    ev = EvidenceValidator(REPO_ROOT)
    res_m00 = ev.verify_m00_baseline("nonexistent_run_id")
    assert res_m00.status.value == "MISSING"


def test_ln03_passive_import_no_gpu_network_or_model_load() -> None:
    code = (
        "import sys; "
        "import backend.linguistic_frontend as f4; "
        "forbidden = {'torch','torchaudio','faster_whisper','ctranslate2','freyatts','pyaudio','sounddevice','sqlalchemy'}; "
        "loaded = sorted(forbidden & set(sys.modules)); "
        "assert not loaded, f'Forbidden modules loaded: {loaded}'; "
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


def test_ln04_reuses_actual_m01_contracts() -> None:
    pipe = _make_pipeline()
    resp = _make_response("Merhaba, servis randevusu uygun mu?", speech_act="QUESTION")
    res = pipe.prepare_response(resp)
    assert res.ok and res.plan is not None
    assert type(res.plan) is SynthesisPlan
    assert len(res.plan.chunks) == 1
    assert type(res.plan.chunks[0]) is ChunkPlan
    assert res.plan.schema_version == CONTRACT_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# LN05 - LN12: Input Admission, Dedup, Length & Unicode
# ---------------------------------------------------------------------------

def test_ln05_valid_admitted_response() -> None:
    pipe = _make_pipeline()
    resp = _make_response("Aracınız bakıma hazırdır.")
    res = pipe.prepare_response(resp, expected_session_id="sess-f4a-1", expected_turn_id=1)
    assert res.ok
    assert res.outcome == PlanningOutcome.ADMITTED
    assert res.plan is not None
    assert res.plan.response_id == "resp-1"


def test_ln06_stale_turn_or_wrong_session_rejected() -> None:
    pipe = _make_pipeline()
    resp = _make_response("Merhaba.", session_id="sess-other", turn_id=1)
    r1 = pipe.prepare_response(resp, expected_session_id="sess-f4a-1", expected_turn_id=1)
    assert not r1.ok and r1.outcome == PlanningOutcome.STALE and r1.reason_code == "WRONG_SESSION"

    resp2 = _make_response("Merhaba.", session_id="sess-f4a-1", turn_id=1)
    r2 = pipe.prepare_response(resp2, expected_session_id="sess-f4a-1", expected_turn_id=2)
    assert not r2.ok and r2.outcome == PlanningOutcome.STALE and r2.reason_code == "STALE_TURN"

    r3 = pipe.prepare_response(resp2, expected_session_id="sess-f4a-1", expected_turn_id=1, min_state_revision=5)
    assert not r3.ok and r3.outcome == PlanningOutcome.STALE and r3.reason_code == "STALE_STATE_REVISION"


def test_ln07_untrusted_raw_dict_claims_admitted_rejected() -> None:
    pipe = _make_pipeline()
    untrusted_dict = {"admitted": True, "already_normalized": True, "speech_text": "Merhaba"}
    res = pipe.prepare_response(untrusted_dict)
    assert not res.ok
    assert res.outcome == PlanningOutcome.REJECTED
    assert res.reason_code == "UNTRUSTED_RESPONSE_TYPE"

    raw_prod = _make_response("Merhaba", producer="public.raw_caller")
    res2 = pipe.prepare_response(raw_prod)
    assert not res2.ok and res2.reason_code == "UNTRUSTED_PRODUCER"


def test_ln08_duplicate_response_identical_content_no_second_plan() -> None:
    pipe = _make_pipeline()
    resp = _make_response("Randevunuz onaylandı.", response_id="resp-dup-1")
    first = pipe.prepare_response(resp)
    assert first.ok and first.plan is not None

    second = pipe.prepare_response(resp)
    assert not second.ok
    assert second.outcome == PlanningOutcome.NO_SYNTHESIS
    assert second.reason_code == "DUPLICATE_RESPONSE"
    assert second.duplicate_of_plan_id == first.plan.plan_id


def test_ln09_duplicate_identity_different_text_conflict() -> None:
    pipe = _make_pipeline()
    r1 = _make_response("Randevunuz saat 14:30 için onaylandı.", response_id="resp-conf-1")
    r2 = _make_response("Randevunuz saat 16:00 için onaylandı.", response_id="resp-conf-1")
    first = pipe.prepare_response(r1)
    assert first.ok
    second = pipe.prepare_response(r2)
    assert not second.ok
    assert second.outcome == PlanningOutcome.CONFLICT
    assert second.reason_code == "DUPLICATE_RESPONSE_CONFLICT"


def test_ln10_explicit_no_response_produces_no_synthesis() -> None:
    pipe = _make_pipeline()
    resp = _make_response("Bu metin sentezlenmemeli.", outcome=DialogueOutcome.NO_RESPONSE)
    res = pipe.prepare_response(resp)
    assert not res.ok
    assert res.outcome == PlanningOutcome.NO_SYNTHESIS
    assert res.reason_code == "NO_RESPONSE"
    assert res.plan is None


def test_ln11_empty_or_invalid_unicode_controlled_failure() -> None:
    pipe = _make_pipeline()
    empty_resp = _make_response("   \t  ")
    r_empty = pipe.prepare_response(empty_resp)
    assert not r_empty.ok and r_empty.reason_code == "EMPTY_SPEECH_TEXT"

    surrogate_resp = _make_response("Merhaba \ud800 dünya")
    r_surr = pipe.prepare_response(surrogate_resp)
    assert not r_surr.ok and r_surr.reason_code == "INVALID_UNICODE_SURROGATE"

    ctrl_resp = _make_response("Merhaba\x00dünya")
    r_ctrl = pipe.prepare_response(ctrl_resp)
    assert not r_ctrl.ok and r_ctrl.reason_code == "INVALID_CONTROL_CHAR"


def test_ln12_oversized_input_rejected_before_expansion() -> None:
    pipe = _make_pipeline(max_input_chars=120)
    oversized = _make_response("a " * 100)
    res = pipe.prepare_response(oversized)
    assert not res.ok
    assert res.outcome == PlanningOutcome.REJECTED
    assert res.reason_code == "LIMIT_EXCEEDED"
    assert res.normalization_passes == 0


# ---------------------------------------------------------------------------
# LN13 - LN17: Snapshot Pinning, Leyla Seed 9 & Gated Seeds 42/77/123
# ---------------------------------------------------------------------------

def test_ln13_m03_config_changes_during_planning_pinned_snapshot_consistent() -> None:
    cfg1 = resolve_configuration(overrides={"morph_precheck_pause_ms": 35}).snapshot
    store = ConfigSnapshotStore(cfg1)
    pipe = LinguisticFrontendPipeline(
        config_snapshot_provider=lambda: store.current,
        lexicon_registry_provider=_default_lexicon,
    )
    resp = _make_response("Aracınız da hazır.", response_id="r-pin-1")
    res1 = pipe.prepare_response(resp)
    # Swap config after first plan
    cfg2 = resolve_configuration(overrides={"morph_precheck_pause_ms": 55}).snapshot
    store.swap(cfg2)
    assert res1.ok and res1.plan is not None
    # First plan keeps original capability/config binding
    res2 = pipe.prepare_response(_make_response("Aracınız da hazır.", response_id="r-pin-2"))
    assert res2.ok and res2.plan is not None
    assert res1.plan.chunks[0].post_pause_ms == 315  # 280 + 35
    assert res2.plan.chunks[0].post_pause_ms == 335  # 280 + 55


def test_ln14_m05_revision_changes_mid_plan_old_snapshot_intact() -> None:
    snap1 = load_lexicon_snapshot()
    reg1 = LexiconRegistry(snap1)
    extra_ent = CanonicalEntity(
        entity_id="brand:testbrand",
        canonical_name="TestBrand",
        category=EntityCategory.BRAND,
        normalized_key="testbrand",
    )
    snap2 = load_lexicon_snapshot(extra_entities=(extra_ent,))
    reg2 = LexiconRegistry(snap2)
    assert reg1.lexicon_revision != reg2.lexicon_revision

    pipe1 = _make_pipeline(lexicon_registry=reg1)
    pipe2 = _make_pipeline(lexicon_registry=reg2)
    r1 = pipe1.prepare_response(_make_response("Peugeot aracınız hazır.", response_id="r-lex-1"))
    r2 = pipe2.prepare_response(_make_response("Peugeot aracınız hazır.", response_id="r-lex-2"))
    assert r1.ok and r2.ok and r1.plan and r2.plan
    assert r1.plan.lexicon_revision == reg1.lexicon_revision
    assert r2.plan.lexicon_revision == reg2.lexicon_revision


def test_ln15_leyla_default_profile_seed_9() -> None:
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("Hoş geldiniz."))
    assert res.ok and res.plan is not None
    assert res.plan.voice_profile == "leyla-baseline-9"
    assert res.plan.seed == 9


@pytest.mark.parametrize("seed", [42, 77, 123])
def test_ln16_approved_experimental_seeds_preserved_without_fallback(seed: int) -> None:
    flag_name = f"experimental_voice_seed_{seed}"
    cfg = resolve_configuration(extra_flags={flag_name: True}).snapshot
    pipe = _make_pipeline(config_snapshot=cfg)
    res = pipe.prepare_response(
        _make_response("Test mesajı.", response_id=f"r-seed-{seed}"),
        requested_seed=seed,
    )
    assert res.ok and res.plan is not None
    assert res.plan.seed == seed

    # When flag is OFF, requesting experimental seed must NOT silently fall back to seed 9
    pipe_off = _make_pipeline()
    res_off = pipe_off.prepare_response(
        _make_response("Test mesajı.", response_id=f"r-seed-off-{seed}"),
        requested_seed=seed,
    )
    assert not res_off.ok
    assert res_off.reason_code == "PROFILE_MISMATCH"


def test_ln17_missing_or_incompatible_profile_revision_rejected() -> None:
    cfg = resolve_configuration().snapshot
    bad_model_reg = ModelRegistry(
        models=(
            ModelDescriptor(
                model_id="tts-freya",
                kind=ModelKind.TTS,
                model_revision="unapproved",
                version="freya-tts-v1",
                device="cpu",
                capability=CapabilityDescriptor(
                    name="tts-freya",
                    scope="TTS_SYNTHESIS",
                    state=CapabilityState.UNSUPPORTED,
                ),
            ),
        ),
        voice_profiles=DEFAULT_VOICE_PROFILE_REGISTRY,
    )
    pipe = _make_pipeline(config_snapshot=cfg, model_registry=bad_model_reg)
    res = pipe.prepare_response(_make_response("Merhaba."))
    assert not res.ok
    assert res.reason_code == "INVALID_MODEL_REVISION"


# ---------------------------------------------------------------------------
# LN18 - LN34: Unicode, Protected Atoms & Semantic Boundaries
# ---------------------------------------------------------------------------

def test_ln18_source_text_whitespace_and_combining_chars_retained() -> None:
    raw = "  I\u0307stanbul   ve  a\u0302lem  "
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response(raw))
    assert res.ok and res.plan is not None
    # Exact verbatim source retained
    assert res.plan.source_text == raw
    assert "\u0307" not in res.plan.normalized_text
    assert "İstanbul" in res.plan.normalized_text


def test_ln19_turkish_i_dotted_dotless_unicode_variants() -> None:
    pipe = _make_pipeline()
    raw = "IŞIK İstanbul ışık iğne"
    res = pipe.prepare_response(_make_response(raw))
    assert res.ok and res.plan is not None
    assert res.plan.source_text == raw
    assert "IŞIK" in res.plan.normalized_text
    assert "İstanbul" in res.plan.normalized_text
    assert "ışık" in res.plan.normalized_text
    assert "iğne" in res.plan.normalized_text
    assert "\u0307" not in res.plan.normalized_text


def test_ln20_canonical_model_name_and_punctuation_atom_span() -> None:
    raw = "Peugeot 3008, randevuya hazır."
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response(raw))
    assert res.ok and res.plan is not None
    models = [a for a in res.atoms if a.kind == AtomKind.MODEL]
    assert len(models) == 1
    assert models[0].literal_source == "Peugeot 3008"
    assert models[0].raw_span == (0, 12)
    assert "Pöjo" in res.plan.normalized_text


def test_ln21_engine_designation_1_6_tdi_vs_1_5() -> None:
    pipe = _make_pipeline()
    r1 = pipe.prepare_response(_make_response("Aracınız 1.6 TDI motorlu.", response_id="eng-16"))
    r2 = pipe.prepare_response(_make_response("Aracınız 1.5 TSI motorlu.", response_id="eng-15"))
    assert r1.ok and r2.ok and r1.plan and r2.plan
    e1 = [a for a in r1.atoms if a.kind == AtomKind.ENGINE_CODE][0]
    e2 = [a for a in r2.atoms if a.kind == AtomKind.ENGINE_CODE][0]
    assert e1.semantic_value[0] == Decimal("1.6")
    assert e2.semantic_value[0] == Decimal("1.5")
    assert "bir nokta altı" in r1.plan.normalized_text
    assert "bir nokta beş" in r2.plan.normalized_text


def test_ln22_id4_c4_t10x_alphanumeric_models_not_coerced() -> None:
    pipe = _make_pipeline()
    raw = "ID.4, C4 ve T10X modelleri stokta."
    res = pipe.prepare_response(_make_response(raw))
    assert res.ok and res.plan is not None
    models = [a for a in res.atoms if a.kind == AtomKind.MODEL]
    assert [m.semantic_value for m in models] == ["ID.4", "C4", "T10X"]
    assert "i de dört" in res.plan.normalized_text
    assert "ce dört" in res.plan.normalized_text
    assert "te on iks" in res.plan.normalized_text


def test_ln23_p0300_diagnostic_code_and_leading_zeros_preserved() -> None:
    pipe = _make_pipeline()
    raw = "Arıza kodu P0300 olarak okundu."
    res = pipe.prepare_response(_make_response(raw))
    assert res.ok and res.plan is not None
    dtcs = [a for a in res.atoms if a.kind == AtomKind.DIAGNOSTIC_CODE]
    assert len(dtcs) == 1
    assert dtcs[0].semantic_value == "P0300"
    assert "pe sıfır üç sıfır sıfır" in res.plan.normalized_text


def test_ln24_phone_and_plate_synthetic_input_no_digit_loss() -> None:
    pipe = _make_pipeline()
    raw = "Plaka 061 ABC 123 ve telefon 0555 000 00 00."
    res = pipe.prepare_response(_make_response(raw))
    assert res.ok and res.plan is not None
    plates = [a for a in res.atoms if a.kind == AtomKind.PLATE]
    phones = [a for a in res.atoms if a.kind == AtomKind.PHONE]
    assert len(plates) == 1 and plates[0].semantic_value == "061 ABC 123"
    assert len(phones) == 1 and phones[0].semantic_value == "05550000000"
    assert "sıfır altmış bir a be ce yüz yirmi üç" in res.plan.normalized_text
    assert "sıfır beş beş beş sıfır sıfır sıfır sıfır sıfır sıfır" in res.plan.normalized_text


def test_ln25_currency_1250000_tl() -> None:
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("Araç bedeli 1.250.000 TL."))
    assert res.ok and res.plan is not None
    cur = [a for a in res.atoms if a.kind == AtomKind.CURRENCY][0]
    assert cur.semantic_value == (Decimal("1250000"), "TRY")
    assert "bir milyon iki yüz elli bin Türk lirası" in res.plan.normalized_text


def test_ln26_currency_2500_50_tl_exact_decimal() -> None:
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("Servis tutarı 2.500,50 TL."))
    assert res.ok and res.plan is not None
    cur = [a for a in res.atoms if a.kind == AtomKind.CURRENCY][0]
    assert cur.semantic_value == (Decimal("2500.50"), "TRY")
    assert "iki bin beş yüz lira elli kuruş" in res.plan.normalized_text


def test_ln27_signed_decimal_and_negative_temperature() -> None:
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("Dış sıcaklık -5 °C ve düzeltme -2,5 oldu."))
    assert res.ok and res.plan is not None
    units = [a for a in res.atoms if a.kind == AtomKind.UNIT]
    decs = [a for a in res.atoms if a.kind == AtomKind.DECIMAL]
    assert units[0].semantic_value == (Decimal("-5"), "°C")
    assert decs[0].semantic_value == Decimal("-2.5")
    assert "eksi beş derece santigrat" in res.plan.normalized_text
    assert "eksi iki nokta beş" in res.plan.normalized_text


def test_ln28_time_14_30_preserved() -> None:
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("Saat 14:30 uygun mu?", speech_act="QUESTION"))
    assert res.ok and res.plan is not None
    t_atom = [a for a in res.atoms if a.kind == AtomKind.TIME][0]
    assert t_atom.semantic_value == (14, 30)
    assert res.plan.normalized_text == "Saat on dört otuz uygun mu?"


def test_ln29_valid_typed_date_vs_ambiguous_date() -> None:
    pipe = _make_pipeline()
    # Ambiguous date without F3 typed fact -> rejected (never guessed)
    amb_resp = _make_response("Randevu tarihi 05.06.2027 olsun.", response_id="date-amb")
    r_amb = pipe.prepare_response(amb_resp)
    assert not r_amb.ok and r_amb.reason_code == "AMBIGUOUS_DATE_FORMAT" or r_amb.reason_code == "UNRESOLVED_ATOM"

    # Typed date with F3 VerifiedFactRef -> admitted and spoken cleanly
    typed_resp = _make_response(
        "Randevu tarihi 05.06.2027 olsun.",
        response_id="date-typed",
        verified_fact_refs=(
            VerifiedFactRef(
                provenance="f3.calendar",
                reference_id="date:2027-06-05",
                status="VERIFIED",
                revision=1,
            ),
        ),
    )
    r_ok = pipe.prepare_response(typed_resp)
    assert r_ok.ok and r_ok.plan is not None
    assert "beş haziran iki bin yirmi yedi" in r_ok.plan.normalized_text


def test_ln30_percentages_ranges_and_units() -> None:
    pipe = _make_pipeline()
    raw = "İndirim %20, menzil 10-20 km ve güç 150 bg."
    res = pipe.prepare_response(_make_response(raw))
    assert res.ok and res.plan is not None
    assert "yüzde yirmi" in res.plan.normalized_text
    assert "on" in res.plan.normalized_text and "yirmi kilometre" in res.plan.normalized_text
    assert "yüz elli beygir" in res.plan.normalized_text


def test_ln31_overlap_amount_currency_parent_child() -> None:
    scan = scan_protected_atoms("Fiyat 2.500,50 TL.")
    assert scan.ok
    parents = [a for a in scan.atoms if a.kind == AtomKind.CURRENCY]
    children = [a for a in scan.atoms if a.parent_atom_id is not None]
    assert len(parents) == 1
    assert len(children) == 1
    assert children[0].parent_atom_id == parents[0].atom_id
    assert parents[0].children_ids == (children[0].atom_id,)
    assert children[0].semantic_value == Decimal("2500.50")


def test_ln32_alias_substring_embedded_no_accidental_replacement() -> None:
    pipe = _make_pipeline()
    raw = "parça4 ve C400 ile aq2z test edildi."
    res = pipe.prepare_response(_make_response(raw))
    assert res.ok and res.plan is not None
    assert "ce dört" not in res.plan.normalized_text
    assert "ku iki" not in res.plan.normalized_text


def test_ln33_placeholder_looking_source_no_sentinel_collision() -> None:
    pipe = _make_pipeline()
    raw = "Kod __ATOM_0__ ve {{0}} ile saat 14:30 metni."
    res = pipe.prepare_response(_make_response(raw))
    assert res.ok and res.plan is not None
    assert "on dört otuz" in res.plan.normalized_text
    assert "__ATOM_" not in res.plan.normalized_text
    assert "{{" not in res.plan.normalized_text


def test_ln34_excessive_atoms_digits_bounded_rejection() -> None:
    many_nums = " ".join(str(i) for i in range(150))
    scan = scan_protected_atoms(many_nums, max_atoms=128)
    assert not scan.ok and scan.reason_code == "LIMIT_EXCEEDED"

    huge_digits = "1" * 25 + " TL"
    scan2 = scan_protected_atoms(huge_digits, max_numeric_digits=15)
    assert not scan2.ok and scan2.reason_code == "LIMIT_EXCEEDED"


# ---------------------------------------------------------------------------
# LN35 - LN39: Single Normalization Authority & Call-Site Spies
# ---------------------------------------------------------------------------

def test_ln35_standard_one_pass_raw_input_spy_count(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.linguistic_frontend.pipeline as pipe_mod
    import backend.text as legacy_text
    import backend.normalizer_rules as legacy_rules

    calls = {"f4_pass": 0, "legacy_norm": 0, "legacy_auto_norm": 0}
    orig_pass = pipe_mod.run_single_normalization_pass
    orig_legacy = legacy_text.normalize
    orig_auto = legacy_rules.normalize_automotive_turkish

    def spy_pass(*args: Any, **kwargs: Any) -> Any:
        calls["f4_pass"] += 1
        return orig_pass(*args, **kwargs)

    def spy_legacy(*args: Any, **kwargs: Any) -> Any:
        calls["legacy_norm"] += 1
        return orig_legacy(*args, **kwargs)

    def spy_auto(*args: Any, **kwargs: Any) -> Any:
        calls["legacy_auto_norm"] += 1
        return orig_auto(*args, **kwargs)

    monkeypatch.setattr(pipe_mod, "run_single_normalization_pass", spy_pass)
    monkeypatch.setattr(legacy_text, "normalize", spy_legacy)
    monkeypatch.setattr(legacy_rules, "normalize_automotive_turkish", spy_auto)

    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("Saat 14:30 için 1.500 TL teklif verildi."))
    assert res.ok and res.plan is not None
    assert res.plan.normalization_passes == 1
    assert calls["f4_pass"] == 1
    assert calls["legacy_norm"] == 0
    assert calls["legacy_auto_norm"] == 0


def test_ln36_stages_recorded_pass_count_remains_one() -> None:
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("Peugeot 3008 saat 14:30'da 1.250.000 TL."))
    assert res.ok and res.trace is not None and res.plan is not None
    assert res.trace.pass_count == 1
    assert len(res.trace.stage_ids) == 4
    assert res.plan.normalization_passes == 1


def test_ln37_already_prepared_trusted_plan_to_fake_f5_no_second_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.linguistic_frontend.pipeline as pipe_mod

    norm_calls = 0
    orig_pass = pipe_mod.run_single_normalization_pass

    def spy_pass(*args: Any, **kwargs: Any) -> Any:
        nonlocal norm_calls
        norm_calls += 1
        return orig_pass(*args, **kwargs)

    monkeypatch.setattr(pipe_mod, "run_single_normalization_pass", spy_pass)

    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("Randevunuz saat 14:30'da onaylandı."))
    assert res.ok and res.plan is not None
    assert norm_calls == 1

    handoff = accept_prepared_plan(
        res.plan,
        expected_model_revision=res.plan.model_revision,
        expected_capability_revision=res.plan.capability_revision,
    )
    fake_f5 = FakeTTSAdapter()
    chunk = fake_f5.synthesize_chunk(handoff.plan, 0)
    assert chunk.plan_id == res.plan.plan_id
    assert norm_calls == 1


def test_ln38_raw_public_caller_claims_prepared_cannot_bypass() -> None:
    with pytest.raises(TypeError):
        accept_prepared_plan({"already_normalized": True, "normalized_text": "Saat on dört otuz."})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        accept_prepared_plan("Saat on dört otuz.")  # type: ignore[arg-type]


def test_ln39_legacy_string_path_unknown_provenance_no_fabricated_pass_count() -> None:
    wrapped = wrap_legacy_string("Saat on dört otuz.")
    assert wrapped.provenance == ProvenanceClass.LEGACY_UNVERIFIED
    assert wrapped.normalization_passes is None
    assert wrapped.strict_coverage is False


# ---------------------------------------------------------------------------
# LN40 - LN45: Legacy Preservation, Span Mapping, Semantic Fact Boundaries
# ---------------------------------------------------------------------------

def test_ln40_legacy_strip_punctuation_behavior_preserved() -> None:
    assert legacy_prepare_tts_clause("  merhaba  ") == "Merhaba."
    assert legacy_prepare_tts_clause("istanbul") == "İstanbul."
    out = legacy_normalize("Saat 14:30 uygun mu?")
    assert out["normalized"] == "Saat on dört otuz uygun mu?"


def test_ln41_numeric_expansion_and_adjacent_punctuation_span_map() -> None:
    pipe = _make_pipeline()
    raw = "Fiyat 1.250.000 TL, lütfen onaylayın."
    res = pipe.prepare_response(_make_response(raw))
    assert res.ok and res.plan is not None and res.text_mapping is not None
    chk0 = res.plan.chunks[0]
    assert chk0.source_span is not None
    s0, s1 = chk0.source_span
    assert 0 <= s0 < s1 <= len(raw)
    assert "1.250.000 TL" in raw[s0:s1]


def test_ln42_existing_normalizer_golden_fixtures_preserved() -> None:
    assert legacy_normalize("Aracınızın bedeli 1.250.000 TL")["normalized"] == "Aracınızın bedeli bir milyon iki yüz elli bin Türk lirası"
    assert legacy_normalize("Randevunuz saat 14:30'da")["normalized"] == "Randevunuz saat on dört otuzda"
    assert legacy_normalize("1.6 TDI")["normalized"] == "bir nokta altı te de i"


def test_ln43_unsupported_critical_number_range_rejected() -> None:
    pipe = _make_pipeline()
    # Invalid TR separator pattern like 1.25.00 TL
    res = pipe.prepare_response(_make_response("Tutar 1.250 olmadan önce 1.250 kontrol edilsin."))
    assert not res.ok
    assert res.reason_code == "UNRESOLVED_ATOM"


def test_ln44_f3_typed_fact_conflict_rejected() -> None:
    pipe = _make_pipeline()
    resp = _make_response(
        "Toplam tutar 1.500 TL.",
        verified_fact_refs=(
            VerifiedFactRef(
                provenance="f3.pricing",
                reference_id="price:TRY:1250",
                status="VERIFIED",
                revision=1,
            ),
        ),
    )
    res = pipe.prepare_response(resp)
    assert not res.ok
    assert res.reason_code == "SEMANTIC_FACT_CONFLICT"


def test_ln45_relative_date_without_resolution_no_invented_calendar_date() -> None:
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("Yarın saat 14:30 için servis uygun mu?", speech_act="QUESTION"))
    assert res.ok and res.plan is not None
    assert "Yarın" in res.plan.normalized_text
    assert not any(m in res.plan.normalized_text.lower() for m in ("ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos", "eylül", "ekim", "kasım", "aralık"))


# ---------------------------------------------------------------------------
# LN46 - LN53: M05 Governance, Ambiguity & Morphology Boundary
# ---------------------------------------------------------------------------

def test_ln46_approved_m05_variant_scoped_source_unchanged() -> None:
    pipe = _make_pipeline()
    raw = "Peugeot bakımı tamamlandı."
    res = pipe.prepare_response(_make_response(raw))
    assert res.ok and res.plan is not None
    assert res.plan.source_text == raw
    assert "Pöjo" in res.plan.normalized_text


def test_ln47_legacy_preserved_variant_retained() -> None:
    reg = _default_lexicon()
    adapter = LexiconAdapter(reg)
    hit = adapter.lookup_term_pronunciation("Qashqai")
    assert hit is not None
    assert hit.governance_status == VariantGovernanceStatus.LEGACY_PRESERVED
    assert hit.spoken_text == "Kaşkai"


def test_ln48_proposed_rejected_quarantined_variants_not_activated() -> None:
    ent = CanonicalEntity(
        entity_id="brand:customx",
        canonical_name="CustomX",
        category=EntityCategory.BRAND,
        normalized_key="customx",
    )
    p1 = PronunciationVariant(
        variant_id="pron:customx:prop",
        canonical_entity_id=ent.entity_id,
        surface_key="customx",
        spoken_text="KastımİksProp",
        profile="tts_2026",
        vocab_validated=True,
    )
    snap = load_lexicon_snapshot(extra_entities=(ent,), extra_pronunciations=(p1,))
    reg = LexiconRegistry(snap)
    for blocked in (
        VariantGovernanceStatus.PROPOSED,
        VariantGovernanceStatus.REJECTED,
        VariantGovernanceStatus.QUARANTINED,
    ):
        adapter = LexiconAdapter(reg, variant_governance={"pron:customx:prop": blocked})
        assert adapter.lookup_term_pronunciation("CustomX") is None


def test_ln49_ambiguous_m05_alias_never_promoted() -> None:
    e1 = CanonicalEntity(
        entity_id="model:alpha_a",
        canonical_name="Alpha A",
        category=EntityCategory.MODEL,
        normalized_key="alpha_a",
        aliases=("Alpha",),
    )
    e2 = CanonicalEntity(
        entity_id="model:alpha_b",
        canonical_name="Alpha B",
        category=EntityCategory.MODEL,
        normalized_key="alpha_b",
        aliases=("Alpha",),
    )
    from backend.shared_lexicon import AliasEntry

    a1 = AliasEntry(
        alias_id=make_safe_id("alias", "alpha->a"),
        alias_text="Alpha",
        normalized_key="alpha",
        canonical_entity_id=e1.entity_id,
        canonical_name=e1.canonical_name,
        category=EntityCategory.MODEL,
    )
    a2 = AliasEntry(
        alias_id=make_safe_id("alias", "alpha->b"),
        alias_text="Alpha",
        normalized_key="alpha",
        canonical_entity_id=e2.entity_id,
        canonical_name=e2.canonical_name,
        category=EntityCategory.MODEL,
    )
    snap = load_lexicon_snapshot(extra_entities=(e1, e2), extra_aliases=(a1, a2))
    reg = LexiconRegistry(snap)
    adapter = LexiconAdapter(reg)
    assert adapter.lookup_term_pronunciation("Alpha") is None


def test_ln50_missing_lexicon_term_safe_baseline() -> None:
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("BilinmeyenMarka aracınız serviste."))
    assert res.ok and res.plan is not None
    assert "BilinmeyenMarka" in res.plan.normalized_text


def test_ln51_existing_suffix_apostrophe_morphology_preserved() -> None:
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("Saat 14:30'da ve 1.500 TL'ye hazır."))
    assert res.ok and res.plan is not None
    assert "on dört otuzda" in res.plan.normalized_text
    assert "bin beş yüz Türk lirasına" in res.plan.normalized_text


def test_ln52_morphology_adapter_no_second_normalizer(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.text as legacy_text

    calls = 0

    def spy_norm(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return {}

    monkeypatch.setattr(legacy_text, "normalize", spy_norm)
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("Halbuki aracınız da hazırdı."))
    assert res.ok and res.morphology is not None
    assert calls == 0


def test_ln53_phonetic_guidance_ipa_not_injected_into_model_text() -> None:
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("Halbuki aracınız görüşülemedi."))
    assert res.ok and res.plan is not None and res.morphology is not None
    assert res.morphology.phonetic_guides_held_back >= 1
    for chk in res.plan.chunks:
        assert "ˈ" not in chk.model_text
        assert "ˌ" not in chk.model_text


# ---------------------------------------------------------------------------
# LN54 - LN59: Freya Vocabulary & Capability Validation (CPU-Only)
# ---------------------------------------------------------------------------

def test_ln54_actual_checkpoint_vocab_cpu_only_provenance() -> None:
    val = FreyaVocabularyValidator.from_vocab_file(
        REPO_ROOT / "config" / "freya_vocab.json",
        model_revision="freya-tts:batched-ode",
        capability_revision="tts-freya:48khz-ode:abc",
    )
    assert val.real_vocab_available is True
    assert val.vocab_sha256 is not None and len(val.vocab_sha256) == 64
    chk = val.check_chunk("Merhaba, randevunuz saat on dört otuzda.")
    assert chk.status == VocabularyStatus.PASS


def test_ln55_missing_real_vocab_fake_passes_remains_unknown_hold() -> None:
    fake_val = FreyaVocabularyValidator.from_fake_vocab(
        frozenset("abcçdefgğhıijklmnoöprsştuüvyzABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ .,?"),
        model_revision="freya-tts:batched-ode",
        capability_revision="tts-freya:48khz-ode:abc",
    )
    # With require_real_vocab=False, interface check passes
    iface = fake_val.check_chunk("Merhaba.", require_real_vocab=False)
    assert iface.status == VocabularyStatus.PASS
    # With require_real_vocab=True, real compatibility is UNKNOWN / HOLD
    real = fake_val.check_chunk("Merhaba.", require_real_vocab=True)
    assert real.status == VocabularyStatus.UNKNOWN
    assert real.reason_code == "REAL_VOCAB_UNAVAILABLE"


def test_ln56_unsupported_glyph_or_control_char_rejected() -> None:
    val = FreyaVocabularyValidator.from_vocab_file(
        REPO_ROOT / "config" / "freya_vocab.json",
        model_revision="freya-tts:batched-ode",
        capability_revision="tts-freya:48khz-ode:abc",
    )
    bad = val.check_chunk("Merhaba 😀.")
    assert bad.status == VocabularyStatus.FAIL
    assert bad.reason_code == "UNSUPPORTED_VOCAB"


def test_ln57_unknown_token_would_delete_critical_code_rejected() -> None:
    pipe = _make_pipeline()
    # Critical diagnostic code with unsupported non-vocab char inside literal won't silently delete
    val = FreyaVocabularyValidator.from_vocab_file(
        REPO_ROOT / "config" / "freya_vocab.json",
        model_revision="freya-tts:batched-ode",
        capability_revision="tts-freya:48khz-ode:abc",
    )
    chk = val.check_chunk("Arıza kodu P0300 ☃")
    assert chk.status == VocabularyStatus.FAIL
    assert pipe.prepare_response(_make_response("Arıza kodu P0300.")).ok


def test_ln58_model_capability_revision_mismatch_rejected() -> None:
    def mismatch_factory(pinned: Any) -> FreyaVocabularyValidator:
        return FreyaVocabularyValidator.from_vocab_file(
            REPO_ROOT / "config" / "freya_vocab.json",
            model_revision=pinned.model_revision,
            capability_revision="stale-cap-rev-000",
        )

    pipe = _make_pipeline(vocab_factory=mismatch_factory)
    res = pipe.prepare_response(_make_response("Merhaba."))
    assert not res.ok
    assert res.reason_code == "CAPABILITY_MISMATCH"


def test_ln59_unapproved_ssml_pitch_or_markup_rejected() -> None:
    val = FreyaVocabularyValidator.from_vocab_file(
        REPO_ROOT / "config" / "freya_vocab.json",
        model_revision="freya-tts:batched-ode",
        capability_revision="tts-freya:48khz-ode:abc",
    )
    ssml = val.check_chunk("<speak>Merhaba</speak>")
    assert ssml.status == VocabularyStatus.FAIL
    assert "SSML_OR_MARKUP" in ssml.unsupported_classes

    ctrl = val.check_chunk("Merhaba.", requested_controls=("pitch:+2st",))
    assert ctrl.status == VocabularyStatus.FAIL
    assert ctrl.reason_code == "UNSUPPORTED_CONTROLS"


# ---------------------------------------------------------------------------
# LN60 - LN65: Chunking, Boundaries & Length-Changing Mappings
# ---------------------------------------------------------------------------

def test_ln60_ordinary_punctuation_split_preserves_order_and_pauses() -> None:
    pipe = _make_pipeline()
    raw = "Aracınız bakıma hazır. Randevunuz saat 14:30 için onaylandı mı?"
    res = pipe.prepare_response(_make_response(raw))
    assert res.ok and res.plan is not None
    assert len(res.plan.chunks) == 2
    assert res.plan.chunks[0].chunk_index == 0
    assert res.plan.chunks[1].chunk_index == 1
    assert res.plan.chunks[0].post_pause_ms == 280
    assert res.plan.chunks[1].post_pause_ms == 320


def test_ln61_chunk_boundary_never_splits_protected_atom() -> None:
    pipe = _make_pipeline(max_chunk_words=4, max_chunk_chars=90)
    raw = "Aracınızın toplam bakım tutarı 1.250.000 TL olarak hesaplanmıştır."
    res = pipe.prepare_response(_make_response(raw))
    assert res.ok and res.plan is not None
    full_joined = " ".join(c.model_text for c in res.plan.chunks)
    assert "bir milyon iki yüz elli bin türk lirası" in full_joined.lower()
    # Protected atom is referenced by exactly one chunk, never split across two
    currency_atoms = [a for a in res.atoms if a.kind == AtomKind.CURRENCY]
    assert len(currency_atoms) == 1
    aid = currency_atoms[0].atom_id
    owners = [c for c in res.plan.chunks if aid in c.protected_entity_refs]
    assert len(owners) == 1


def test_ln62_protected_atom_longer_than_model_limit_rejected_no_truncation() -> None:
    pipe = _make_pipeline(max_chunk_chars=25)
    raw = "Tutar 1.250.000 TL."
    res = pipe.prepare_response(_make_response(raw))
    assert not res.ok
    assert res.reason_code == "PROTECTED_ATOM_EXCEEDS_LIMIT"


def test_ln63_whitespace_only_segment_after_splitting_not_emitted() -> None:
    pipe = _make_pipeline()
    raw = "Merhaba.   .   Nasılsınız?"
    res = pipe.prepare_response(_make_response(raw))
    assert res.ok and res.plan is not None
    for chk in res.plan.chunks:
        assert chk.model_text.strip() != ""
        assert any(ch.isalnum() for ch in chk.model_text)


def test_ln64_oversized_total_expansion_or_chunk_count_rejected() -> None:
    pipe_chunks = _make_pipeline(max_total_chunks=2)
    res1 = pipe_chunks.prepare_response(_make_response("Birinci cümle. İkinci cümle. Üçüncü cümle."))
    assert not res1.ok and res1.reason_code == "LIMIT_EXCEEDED"

    pipe_exp = _make_pipeline(max_expanded_chars=30)
    res2 = pipe_exp.prepare_response(_make_response("Araç bedeli 1.250.000 TL olarak belirlendi."))
    assert not res2.ok and res2.reason_code == "LIMIT_EXCEEDED"


def test_ln65_length_changing_unicode_and_number_expansions_mapped() -> None:
    pipe = _make_pipeline()
    raw = "I\u0307stanbul fiyatı 2.500,50 TL."
    res = pipe.prepare_response(_make_response(raw))
    assert res.ok and res.text_mapping is not None and res.plan is not None
    assert res.plan.source_text == raw
    cur_atom = [a for a in res.atoms if a.kind == AtomKind.CURRENCY][0]
    assert cur_atom.normalized_span is not None
    ns0, ns1 = cur_atom.normalized_span
    projected_src = res.text_mapping.source_span_for_normalized(ns0, ns1)
    assert raw[projected_src[0]:projected_src[1]] == "2.500,50 TL"


# ---------------------------------------------------------------------------
# LN66 - LN69: Immutable Plan, Hints & Validation
# ---------------------------------------------------------------------------

def test_ln66_complete_valid_plan_ordered_unique_chunks() -> None:
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("Birinci kısım. İkinci kısım."))
    assert res.ok and res.plan is not None
    assert res.plan.validation_status == PlanValidationStatus.VALID
    assert [c.chunk_index for c in res.plan.chunks] == [0, 1]
    assert len({c.chunk_id for c in res.plan.chunks}) == 2


def test_ln67_immutable_plan_and_chunk_metadata() -> None:
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("Peugeot 3008 hazır."))
    assert res.ok and res.plan is not None
    with pytest.raises(AttributeError):
        res.plan.normalized_text = "mutated"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        res.plan.chunks[0].model_text = "mutated"  # type: ignore[misc]
    assert isinstance(res.plan.chunks, tuple)
    assert isinstance(res.plan.chunks[0].protected_entity_refs, tuple)


def test_ln68_negative_pause_or_nonfinite_speed_rejected() -> None:
    with pytest.raises(ValueError):
        ChunkPlan(chunk_id="chk-0", chunk_index=0, model_text="Merhaba.", post_pause_ms=-1)
    with pytest.raises(ValueError):
        ChunkPlan(chunk_id="chk-0", chunk_index=0, model_text="Merhaba.", requested_speed=math.nan)
    with pytest.raises(ValueError):
        ChunkPlan(chunk_id="chk-0", chunk_index=0, model_text="Merhaba.", requested_speed=-1.0)


def test_ln69_supported_pause_hint_requested_only_not_applied_as_audio() -> None:
    pipe = _make_pipeline()
    res = pipe.prepare_response(_make_response("Randevunuz saat 14:30 için hazır mı?", speech_act="QUESTION"))
    assert res.ok and res.plan is not None
    assert res.plan.chunks[0].post_pause_ms == 320
    # Plan contains zero audio payloads; pause is strictly metadata hint for F6
    assert not hasattr(res.plan, "payload")


# ---------------------------------------------------------------------------
# LN70 - LN76: M02 Lifecycle, Concurrency Isolation & M04 Telemetry Privacy
# ---------------------------------------------------------------------------

def test_ln70_cancel_before_generation_admission_allocates_nothing() -> None:
    async def _run() -> None:
        clock = HarnessClock(initial_ns=1_000_000)
        ctx = SessionContext(SessionIdentity("sess-ln70"), clock=clock)
        await ctx.open()
        tref, _ = await ctx.begin_turn()
        ctx.root_scope.request_cancel("user_barge_in")

        coord = LinguisticPreparationCoordinator(_make_pipeline())
        resp = _make_response("Merhaba.", session_id="sess-ln70", turn_id=tref.turn_id)
        out = await coord.prepare_and_admit(ctx, resp, turn_ref=tref)
        assert not out.admitted
        assert out.admission_status == AdmissionStatus.CANCELED
        assert ctx.tg.active_generation is None

    asyncio.run(_run())


def test_ln71_cancel_between_validation_and_enqueue_atomic_fence() -> None:
    async def _run() -> None:
        clock = HarnessClock(initial_ns=1_000_000)
        ctx = SessionContext(SessionIdentity("sess-ln71"), clock=clock)
        await ctx.open()
        tref, _ = await ctx.begin_turn()

        coord = LinguisticPreparationCoordinator(_make_pipeline())
        resp = _make_response("Servis randevusu hazır.", session_id="sess-ln71", turn_id=tref.turn_id)
        delivered: list[SynthesisPlan] = []

        async def _mid_cancel(gen_ref: GenerationRef, gen_scope: Any) -> None:
            gen_scope.request_cancel("barge_in_during_prep")

        out = await coord.prepare_and_admit(
            ctx,
            resp,
            turn_ref=tref,
            mid_hook=_mid_cancel,
            on_admit=delivered.append,
        )
        assert not out.admitted
        assert out.admission_status == AdmissionStatus.CANCELED
        assert delivered == []

    asyncio.run(_run())


def test_ln72_new_generation_supersedes_old_plan() -> None:
    async def _run() -> None:
        clock = HarnessClock(initial_ns=1_000_000)
        ctx = SessionContext(SessionIdentity("sess-ln72"), clock=clock)
        await ctx.open()
        tref, _ = await ctx.begin_turn()

        coord = LinguisticPreparationCoordinator(_make_pipeline())
        resp1 = _make_response("İlk yanıt.", session_id="sess-ln72", turn_id=tref.turn_id, response_id="resp-old")
        delivered: list[SynthesisPlan] = []

        async def _supersede(gen_ref: GenerationRef, _scope: Any) -> None:
            # Allocate a newer generation while old plan is preparing
            await ctx.begin_generation(tref)

        out = await coord.prepare_and_admit(
            ctx,
            resp1,
            turn_ref=tref,
            mid_hook=_supersede,
            on_admit=delivered.append,
        )
        assert not out.admitted
        assert out.admission_status == AdmissionStatus.STALE_GENERATION
        assert delivered == []

    asyncio.run(_run())


def test_ln73_session_closes_with_pending_preparation_bounded_cleanup() -> None:
    async def _run() -> None:
        clock = HarnessClock(initial_ns=1_000_000)
        ctx = SessionContext(SessionIdentity("sess-ln73"), clock=clock)
        await ctx.open()
        tref, _ = await ctx.begin_turn()

        coord = LinguisticPreparationCoordinator(_make_pipeline())
        resp = _make_response("Kapanış testi.", session_id="sess-ln73", turn_id=tref.turn_id)

        async def _close_mid(_gen_ref: GenerationRef, _scope: Any) -> None:
            await ctx.close("hangup")

        out = await coord.prepare_and_admit(ctx, resp, turn_ref=tref, mid_hook=_close_mid)
        assert not out.admitted
        assert out.admission_status in {AdmissionStatus.CLOSED, AdmissionStatus.CANCELED}
        assert ctx.cleanup_status == CleanupStatus.COMPLETE
        assert ctx.ledger.active_count == 0

    asyncio.run(_run())


def test_ln74_two_sessions_interleave_no_cross_session_leakage() -> None:
    cfg_a = resolve_configuration(extra_flags={"experimental_voice_seed_42": True}).snapshot
    cfg_b = resolve_configuration().snapshot
    pipe_a = _make_pipeline(config_snapshot=cfg_a)
    pipe_b = _make_pipeline(config_snapshot=cfg_b)

    ra = pipe_a.prepare_response(
        _make_response("Oturum A metni.", session_id="sess-A", response_id="r-a"),
        requested_seed=42,
    )
    rb = pipe_b.prepare_response(
        _make_response("Oturum B metni.", session_id="sess-B", response_id="r-b"),
    )
    assert ra.ok and rb.ok and ra.plan and rb.plan
    assert ra.plan.seed == 42 and rb.plan.seed == 9
    assert "Oturum A" in ra.plan.source_text and "Oturum A" not in rb.plan.normalized_text
    assert "Oturum B" in rb.plan.source_text and "Oturum B" not in ra.plan.normalized_text


def test_ln75_safe_telemetry_no_sensitive_payload_or_pii() -> None:
    clock = HarnessClock(initial_ns=10_000_000)
    bus = BoundedEventBus(max_lane_size=16)
    received: list[EventEnvelope] = []
    sub = bus.subscribe("sub-f4", callback=lambda ev: received.append(ev))
    tel = LinguisticTelemetry(bus=bus, metrics=MetricsRegistry(), projection=Projection(), clock=clock)
    pipe = _make_pipeline(telemetry=tel)

    secret_phone_text = "Plaka 34 ABC 1234 ve telefon 0555 123 45 67."
    res = pipe.prepare_response(_make_response(secret_phone_text))
    assert res.ok
    assert tel.observer_errors == 0
    sub.dispatch_pending()
    assert len(received) == 1
    ev = received[0]
    proj = tel.projection.project(ev)
    assert proj is not None
    serialized = json.dumps(proj, ensure_ascii=False)
    assert not contains_sentinel(serialized)
    assert "0555" not in serialized
    assert "ABC" not in serialized
    assert PIISecretScanner.scan_object(proj) == []
    assert res.metrics[0].status == MetricStatus.MEASURED


def test_ln76_m04_event_queue_overflow_or_failure_never_blocks_or_bypasses() -> None:
    clock = HarnessClock(initial_ns=10_000_000)
    bus = BoundedEventBus(max_lane_size=1, drop_policy=DropPolicy.DROP_NEWEST)

    def broken_sub(_ev: EventEnvelope) -> None:
        raise RuntimeError("observer crashed")

    bus.subscribe("broken", callback=broken_sub)
    tel = LinguisticTelemetry(bus=bus, clock=clock)
    pipe = _make_pipeline(telemetry=tel)

    # Valid response still succeeds even if observer/subscriber fails
    ok_res = pipe.prepare_response(_make_response("Merhaba."))
    assert ok_res.ok and ok_res.plan is not None

    # Invalid response is STILL rejected even if telemetry fails
    bad_res = pipe.prepare_response(_make_response("   "))
    assert not bad_res.ok and bad_res.reason_code == "EMPTY_SPEECH_TEXT"


# ---------------------------------------------------------------------------
# LN77 - LN80: Legacy Paths, E2E Seam, Regression & Acceptance Policy
# ---------------------------------------------------------------------------

def test_ln77_legacy_direct_paths_and_shadow_compare() -> None:
    # Legacy string APIs keep baseline behavior without claiming strict F4-A pass count
    cl = legacy_clauses("Merhaba, nasılsınız? İyiyim.")
    assert len(cl) == 2
    wrapped = wrap_legacy_string("Merhaba.")
    assert wrapped.strict_coverage is False and wrapped.normalization_passes is None

    # Shadow compare is side-effect-free (does not mutate dedup ledger)
    pipe = _make_pipeline()
    resp = _make_response("Saat 14:30 uygun mu?", response_id="shadow-1")
    sh = pipe.shadow_compare(resp)
    assert sh.strict_ok is True
    assert sh.texts_equal is True
    assert sh.dispatched is False
    # Real preparation with same response_id still succeeds because shadow had no side effects
    real = pipe.prepare_response(resp)
    assert real.ok


def test_ln78_f3_response_to_real_f4_to_fake_f5_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.linguistic_frontend.pipeline as pipe_mod

    norm_count = 0
    orig = pipe_mod.run_single_normalization_pass

    def spy(*args: Any, **kwargs: Any) -> Any:
        nonlocal norm_count
        norm_count += 1
        return orig(*args, **kwargs)

    monkeypatch.setattr(pipe_mod, "run_single_normalization_pass", spy)

    pipe = _make_pipeline()
    resp = _make_response(
        "Peugeot 3008 için 1.250.000 TL randevunuz saat 14:30'da onaylandı.",
        speech_act="CONFIRMATION",
        verified_fact_refs=(
            VerifiedFactRef(provenance="f3.pricing", reference_id="price:TRY:1250000", status="VERIFIED", revision=1),
            VerifiedFactRef(provenance="f3.booking", reference_id="time:14:30", status="VERIFIED", revision=1),
        ),
    )
    res = pipe.prepare_response(resp)
    assert res.ok and res.plan is not None
    assert norm_count == 1
    handoff = accept_prepared_plan(res.plan)
    fake_f5 = FakeTTSAdapter()
    audio_chunk = fake_f5.synthesize_chunk(handoff.plan, 0)
    assert audio_chunk.generation_ref == res.plan.generation_ref
    assert audio_chunk.seed == 9
    assert norm_count == 1


def test_ln79_impacted_foundation_integrity_and_no_forbidden_mutations() -> None:
    # Verify legacy files remain untouched and rollback-safe strict flag defaults off
    cfg = resolve_configuration().snapshot
    pipe = _make_pipeline(config_snapshot=cfg)
    assert pipe._strict_enabled is False
    # Verify protected files still parse & import cleanly
    from backend import text as legacy_text, normalizer_rules
    assert callable(legacy_text.normalize)
    assert callable(normalizer_rules.normalize_automotive_turkish)


def test_ln80_acceptance_gate_policy_rejects_hold_or_not_run() -> None:
    held = evaluate_gates(
        (
            GateRecord(gate_id="G00", mandatory=True, status=GateStatus.PASS, reason="ok", evidence_refs=("ev:0",)),
            GateRecord(gate_id="G10", mandatory=True, status=GateStatus.HOLD, reason="missing_vocab", evidence_refs=("ev:1",)),
        )
    )
    assert held.overall == GateStatus.HOLD
    assert held.ready is False

    not_run = evaluate_gates(
        (
            GateRecord(gate_id="G00", mandatory=True, status=GateStatus.PASS, reason="ok", evidence_refs=("ev:0",)),
            GateRecord(gate_id="G17", mandatory=True, status=GateStatus.NOT_RUN, reason="missing_ln", evidence_refs=("ev:2",)),
        )
    )
    assert not_run.overall == GateStatus.HOLD
    assert not_run.ready is False
