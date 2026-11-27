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

import subprocess
import sys

import pytest

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, EventEnvelope, GenerationRef
from backend.core.contracts.dialogue import DialogueOutcome, DialogueResponse
from backend.linguistic_frontend import (
    AnalysisStatus,
    CapabilitySupportStatus,
    CliticType,
    ControlOwner,
    FreyaVocabularyValidator,
    G2PStatus,
    LexiconAdapter,
    LinguisticFrontendPipeline,
    MorphologicalAnalysis,
    PlanningOutcome,
    RealizationDecisionKind,
    StressRuleClass,
    SyllableWeight,
    VariantGovernanceStatus,
    VocabularyStatus,
    analyze_f4b_morphology,
    plan_f4c_prosody_and_chunks,
    resolve_vowel_harmony,
)
from backend.linguistic_frontend.f4_b_morphology import MAX_F4B_SOURCE_CODEPOINTS
from backend.linguistic_frontend.text_mapping import SpanMappingEntry, TextMapping
from backend.shared_lexicon import (
    CanonicalEntity,
    EntityCategory,
    LexiconRegistry,
    PronunciationVariant,
    load_lexicon_snapshot,
)


def _make_response(
    speech_text: str,
    *,
    session_id: str = "sess-f4bc-1",
    turn_id: int = 1,
    generation_id: int = 1,
    response_id: str = "resp-f4bc-1",
    speech_act: str = "INFORM",
    focus_entity_refs: tuple[str, ...] = (),
) -> DialogueResponse:
    return DialogueResponse(
        envelope=EventEnvelope(
            schema_version=CONTRACT_SCHEMA_VERSION,
            event_type="dialogue.response",
            session_id=session_id,
            turn_id=turn_id,
            generation_id=generation_id,
            trace_id="trace-f4bc-1",
            sequence=0,
            monotonic_ns=1_000_000,
            clock_domain="harness.fake.clock",
            producer="f3.dialogue",
        ),
        response_id=response_id,
        speech_text=speech_text,
        speech_act=speech_act,
        state_revision=1,
        outcome=DialogueOutcome.OK,
        focus_entity_refs=focus_entity_refs,
    )


def test_passive_imports_no_torch_no_threads() -> None:
    code = (
        "import sys, threading; "
        "t0 = threading.active_count(); "
        "import backend.linguistic_frontend.f4_b_morphology; "
        "import backend.linguistic_frontend.f4_c_prosody; "
        "assert 'torch' not in sys.modules; "
        "assert threading.active_count() == t0"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def test_pipeline_preserves_normalization_passes_1_and_populates_f4bc() -> None:
    reg = LexiconRegistry(load_lexicon_snapshot())
    pipe = LinguisticFrontendPipeline(lexicon_registry_provider=lambda: reg, require_real_vocab=True)
    resp = _make_response("Aracınız hazır. Saat 14:30 uygun mu?", speech_act="QUESTION")
    res = pipe.prepare_response(
        resp,
        generation_ref=GenerationRef(session_id="sess-f4bc-1", turn_id=1, generation_id=1),
    )
    assert res.ok is True
    assert res.outcome == PlanningOutcome.ADMITTED
    assert res.normalization_passes == 1
    assert res.plan is not None
    assert res.plan.normalization_passes == 1
    assert res.plan.source_text == "Aracınız hazır. Saat 14:30 uygun mu?"
    assert res.f4b_morphology is not None
    assert len(res.f4b_morphology.analyses) >= 5
    assert res.f4c_prosody is not None
    assert res.f4c_prosody.prosody_target is not None
    assert res.f4c_prosody.prosody_target.contour_category == "YES_NO_QUESTION"
    assert any(cl.clitic_type == CliticType.QUESTION_MI and not cl.may_split for cl in res.f4c_prosody.clitic_links)
    for vc in res.vocab_checks:
        assert vc.status == VocabularyStatus.PASS


def test_f4b_source_aligned_spans_apostrophe_and_non_bmp() -> None:
    text = "🚗 Peugeot’ya ve Peugeot'ya bakın."
    bundle = analyze_f4b_morphology(text)
    assert len(bundle.analyses) == 5
    # First Peugeot’ya starts after emoji + space (codepoint index 2)
    a1 = bundle.analyses[1]
    assert text[a1.source_span[0] : a1.source_span[1]] == "Peugeot’ya"
    assert text[a1.root_span[0] : a1.root_span[1]] == "Peugeot"
    assert a1.separator_span is not None
    assert text[a1.separator_span[0] : a1.separator_span[1]] == "’"
    assert a1.suffix_parts[0].surface_form == "ya"
    assert a1.suffix_parts[0].grammatical_function == "DATIVE"

    # Second Peugeot'ya has ASCII apostrophe
    a3 = bundle.analyses[3]
    assert text[a3.source_span[0] : a3.source_span[1]] == "Peugeot'ya"
    assert a3.separator_span is not None
    assert text[a3.separator_span[0] : a3.separator_span[1]] == "'"


def test_f4b_rejects_bool_in_span_indices() -> None:
    with pytest.raises(TypeError):
        MorphologicalAnalysis(
            token_id="tok-0",
            source_span=(False, 5),  # type: ignore[arg-type]
            root_span=(0, 5),
            separator_span=None,
            suffix_parts=(),
            lexical_entity_ref=None,
            lemma="araba",
            grammatical_features=(),
            analysis_status=AnalysisStatus.RESOLVED,
        )


def test_f4b_vowel_harmony_all_8_vowels_and_exceptions() -> None:
    assert resolve_vowel_harmony("araba") == ("a", "ı")
    assert resolve_vowel_harmony("kapı") == ("a", "ı")
    assert resolve_vowel_harmony("ev") == ("e", "i")
    assert resolve_vowel_harmony("kedi") == ("e", "i")
    assert resolve_vowel_harmony("yol") == ("a", "u")
    assert resolve_vowel_harmony("kutu") == ("a", "u")
    assert resolve_vowel_harmony("göz") == ("e", "ü")
    assert resolve_vowel_harmony("gül") == ("e", "ü")

    bundle = analyze_f4b_morphology("hukuk")
    assert "CONSONANT_ALTERNATION_EXCEPTION" in bundle.analyses[0].reason_codes


def test_f4b_proposed_variant_not_activated_and_g2p_separate() -> None:
    ent = CanonicalEntity(
        entity_id="brand:peugeottest",
        canonical_name="PeugeotTest",
        category=EntityCategory.BRAND,
        normalized_key="peugeottest",
    )
    var = PronunciationVariant(
        variant_id="var-pejo-prop",
        canonical_entity_id="brand:peugeottest",
        surface_key="peugeottest",
        spoken_text="Pejo",
        profile="tts_2026",
        vocab_validated=True,
    )
    snap = load_lexicon_snapshot(extra_entities=(ent,), extra_pronunciations=(var,))
    reg = LexiconRegistry(snap)
    adapter = LexiconAdapter(
        reg,
        variant_governance={"var-pejo-prop": VariantGovernanceStatus.PROPOSED},
    )
    bundle = analyze_f4b_morphology("PeugeotTest'ya", lexicon_adapter=adapter)
    assert bundle.realization_decisions[0].decision == RealizationDecisionKind.PRESERVE
    assert bundle.g2p_guidances[0].status in {G2PStatus.MAPPED, G2PStatus.PARTIAL}
    assert bundle.g2p_guidances[0].phone_sequence is not None

    # Full pipeline keeps model_text clean (no IPA glyphs)
    pipe = LinguisticFrontendPipeline(
        lexicon_registry_provider=lambda: reg,
        variant_governance={"var-pejo-prop": VariantGovernanceStatus.PROPOSED},
        require_real_vocab=True,
    )
    res = pipe.prepare_response(_make_response("PeugeotTest'ya bakın."))
    assert res.ok is True
    assert res.plan is not None
    for chk in res.plan.chunks:
        assert "ˈ" not in chk.model_text
        assert "<prosody" not in chk.model_text


def test_f4b_source_cap_bounded() -> None:
    long_text = "a" * (MAX_F4B_SOURCE_CODEPOINTS + 1)
    bundle = analyze_f4b_morphology(long_text)
    assert bundle.budget_exceeded is True
    assert "F4B_SOURCE_CAP_EXCEEDED" in bundle.warnings


def test_f4c_syllables_sezer_stress_clitics_liaison_and_ownership() -> None:
    text = "Ankara ve Adana hazır. Bir araç geldi mi? Acil uyarı."
    mapping = TextMapping(
        source_text=text,
        normalized_text=text,
        entries=(SpanMappingEntry(source_span=(0, len(text)), target_span=(0, len(text))),),
    )
    chk_res, prosody = plan_f4c_prosody_and_chunks(
        text,
        atoms=(),
        text_mapping=mapping,
        speech_act="WARNING",
        focus_entity_refs=("ent-brake",),
    )
    assert chk_res.ok is True
    # Ankara -> index 0 (SEZER_ELIGIBLE), Adana -> index 1 (SEZER_ELIGIBLE)
    ankara_stress = prosody.stress_assessments[0]
    adana_stress = prosody.stress_assessments[2]
    assert ankara_stress.rule_class == StressRuleClass.SEZER_ELIGIBLE
    assert ankara_stress.primary_index == 0
    assert adana_stress.rule_class == StressRuleClass.SEZER_ELIGIBLE
    assert adana_stress.primary_index == 1

    # Syllable weight check: An (closed -> HEAVY), ka (open -> LIGHT)
    ankara_syl = prosody.syllabifications[0]
    assert [s.surface for s in ankara_syl.syllables] == ["an", "ka", "ra"]
    assert ankara_syl.syllables[0].weight == SyllableWeight.HEAVY
    assert ankara_syl.syllables[1].weight == SyllableWeight.LIGHT

    # Liaison "Bir araç" inside same chunk is eligible
    assert any(lh.eligible and lh.reason == "CONSONANT_TO_VOWEL_ULAMA" for lh in prosody.liaison_hints)

    # WARNING rate 0.90 is outside F6 WSOLA [0.94, 1.06] -> UNSUPPORTED, NONE owner, NOT_APPLIED
    rate_disp = prosody.control_dispositions[0]
    assert rate_disp.requested_value == 0.90
    assert rate_disp.support_status == CapabilitySupportStatus.UNSUPPORTED
    assert rate_disp.chosen_owner == ControlOwner.NONE
    assert rate_disp.consumed_status == "NOT_APPLIED"

    # Real vocab bounds check on produced chunks
    vocab = FreyaVocabularyValidator.from_vocab_file(
        "config/freya_vocab.json",
        model_revision="m-test",
        capability_revision="cap-test",
        max_sequence_chars=270,
    )
    for chk in chk_res.chunks:
        vc = vocab.check_chunk(chk.model_text, expected_capability_revision="cap-test", require_real_vocab=True)
        assert vc.status == VocabularyStatus.PASS
