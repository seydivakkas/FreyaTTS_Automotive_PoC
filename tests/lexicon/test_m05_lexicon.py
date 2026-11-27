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
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, EventEnvelope
from backend.core.contracts.recognition import (
    ASROutcome,
    ASRResult,
    ASRStatus,
    CatalogStatus,
    ConfirmationStatus,
    UnicodeSpan,
)
from backend.shared_lexicon import (
    AliasEntry,
    CanonicalEntity,
    CatalogItemRef,
    EntityCategory,
    InMemoryCatalogSeam,
    LexiconRegistry,
    LexiconSnapshot,
    LookupMatch,
    LookupStatus,
    MatchKind,
    PronunciationVariant,
    ProtectedSpanKind,
    TechnicalTerm,
    detect_protected_spans,
    enrich_asr_result,
    extract_asr_candidates,
    get_pronunciation_variants,
    load_lexicon_snapshot,
    make_safe_id,
    normalize_matching_key,
    normalize_with_spans,
    resolve_scoped_pronunciations,
    turkish_nfc_lower,
)


@pytest.fixture(scope="module")
def default_snapshot() -> LexiconSnapshot:
    return load_lexicon_snapshot()


@pytest.fixture(scope="module")
def default_registry(default_snapshot: LexiconSnapshot) -> LexiconRegistry:
    return LexiconRegistry.from_snapshot(default_snapshot)


def test_passive_cpu_only_import() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import backend.shared_lexicon; "
                "import backend.shared_lexicon.contracts; "
                "import backend.shared_lexicon.source_loader; "
                "import backend.shared_lexicon.unicode_normalizer; "
                "import backend.shared_lexicon.registry; "
                "import backend.shared_lexicon.asr_adapter; "
                "import backend.shared_lexicon.tts_adapter; "
                "import backend.shared_lexicon.catalog_adapter; "
                "forbidden = {'torch', 'faster_whisper', 'transformers', 'sqlalchemy'}; "
                "loaded = forbidden & set(sys.modules); "
                "assert not loaded, f'Forbidden modules loaded: {loaded}'"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_ozel_lisans_headers_present() -> None:
    expected = "Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)"
    pkg_dir = Path("backend/shared_lexicon")
    py_files = sorted(pkg_dir.glob("*.py"))
    assert len(py_files) == 8
    for f in [*py_files, Path("tests/lexicon/test_m05_lexicon.py")]:
        content = f.read_text(encoding="utf-8")
        assert "ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR" in content, f"Missing header in {f}"
        assert expected in content, f"Missing copyright line in {f}"


def test_immutability_and_deterministic_revision() -> None:
    e1 = CanonicalEntity(
        entity_id="brand:volkswagen",
        canonical_name="Volkswagen",
        category=EntityCategory.BRAND,
        normalized_key="volkswagen",
        brand_name="Volkswagen",
        aliases=("Folksvagen",),
        metadata={"origin": "test", "loaded_at": "2026-01-01T00:00:00Z"},
    )
    e2 = CanonicalEntity(
        entity_id="model:volkswagen_passat",
        canonical_name="Volkswagen Passat",
        category=EntityCategory.MODEL,
        normalized_key="volkswagen passat",
        brand_name="Volkswagen",
        model_name="Passat",
    )
    a1 = AliasEntry(
        alias_id="alias:folksvagen",
        alias_text="Folksvagen",
        normalized_key="folksvagen",
        canonical_entity_id=e1.entity_id,
        canonical_name=e1.canonical_name,
        category=EntityCategory.BRAND,
    )
    p1 = PronunciationVariant(
        variant_id="pron:vw",
        canonical_entity_id=e1.entity_id,
        surface_key="volkswagen",
        spoken_text="Folksvagen",
        profile="tts_2026",
        vocab_validated=True,
    )
    t1 = TechnicalTerm(
        term_id="term:tsi",
        canonical_name="TSI",
        normalized_key="tsi",
        category="Motor",
        spoken_text="ti es ay",
    )

    snap_a = LexiconSnapshot(
        entities=(e1, e2),
        aliases=(a1,),
        pronunciations=(p1,),
        technical_terms=(t1,),
        vocab_chars=frozenset({"a", "b"}),
        source_metadata={"created_at": "2026-11-26T00:00:00Z", "engine": "FreyaTTS"},
    )
    snap_b = LexiconSnapshot(
        entities=(e2, e1),
        aliases=(a1,),
        pronunciations=(p1,),
        technical_terms=(t1,),
        vocab_chars=frozenset({"b", "a"}),
        source_metadata={"timestamp": "2099-12-31T23:59:59Z", "engine": "FreyaTTS"},
    )

    assert len(snap_a.lexicon_revision) == 64
    assert snap_a.lexicon_revision == snap_b.lexicon_revision

    with pytest.raises(FrozenInstanceError):
        e1.canonical_name = "Other"  # type: ignore[misc]
    with pytest.raises(TypeError):
        e1.metadata["origin"] = "mutated"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        snap_a.lexicon_revision = "0" * 64  # type: ignore[misc]
    with pytest.raises(TypeError):
        snap_a.source_metadata["engine"] = "mutated"  # type: ignore[index]
    with pytest.raises(ValueError, match="does not match canonical snapshot"):
        LexiconSnapshot(
            entities=(e1,),
            aliases=(),
            pronunciations=(),
            technical_terms=(),
            lexicon_revision="a" * 64,
        )


def test_turkish_nfc_and_exact_unicode_codepoint_spans(default_registry: LexiconRegistry) -> None:
    assert turkish_nfc_lower("IĞDIR İSTANBUL") == "ığdır istanbul"
    assert "\u0307" not in turkish_nfc_lower("İSTANBUL")
    assert normalize_matching_key("  ŠKODA\tQashqai’ye  ") == "škoda qashqai'ye"

    # Decomposed NFD 'I\u0307' + astral emoji + multi-space
    raw = "I\u0307kinci 🚗   Volkswagen   Passat ve ŠKODA Kamiq"
    text_map = normalize_with_spans(raw)
    assert text_map.normalized_text.startswith("ikinci ")
    assert "\u0307" not in text_map.normalized_text

    res = default_registry.lookup_text(raw)
    assert res.raw_text == raw
    assert res.status == LookupStatus.MATCHED
    assert not res.ambiguous
    matched_raws = [m.raw_text for m in res.matches]
    assert "Volkswagen   Passat" in matched_raws
    assert "ŠKODA Kamiq" in matched_raws
    for m in res.matches:
        assert raw[m.span.start:m.span.end_exclusive] == m.raw_text
        assert m.span.representation == "RAW"


def test_longest_multitoken_match_and_inflection(default_registry: LexiconRegistry) -> None:
    raw = "Force Wagon Puzzle ve Nissan Qashqai’ye randevu, Peugeot 3008 bakımı"
    res = default_registry.lookup_text(raw)
    names = [m.selected_entity.canonical_name for m in res.matches if m.selected_entity]
    assert "Volkswagen Passat" in names
    assert "Nissan Qashqai" in names
    assert "Peugeot 3008" in names
    # Verify inflected span preserves full raw mention
    q_match = next(m for m in res.matches if m.selected_entity and m.selected_entity.canonical_name == "Nissan Qashqai")
    assert q_match.raw_text == "Nissan Qashqai’ye"
    assert q_match.match_kind == MatchKind.INFLECTED
    assert raw[q_match.span.start:q_match.span.end_exclusive] == "Nissan Qashqai’ye"


def test_unsafe_standalone_turkish_words_not_matched(default_registry: LexiconRegistry) -> None:
    res = default_registry.lookup_text("3 Nisan sabahı bir araç için kapı cam ve far kontrolü")
    assert res.matches == ()
    assert res.status == LookupStatus.PROTECTED


def test_protected_spans_block_fuzzy_and_spurious_rewrites(default_registry: LexiconRegistry) -> None:
    raw = (
        "Plaka 34 BMW 320 ve 34 DSG 123, şase WVWZZZ3CZWE123456, "
        "telefon 0532 500 20 08, hata P0300 ve P0301, fiyat 1.250.000 TL ve 500 bin"
    )
    protected = detect_protected_spans(raw)
    kinds = {p.kind for p in protected}
    assert {
        ProtectedSpanKind.PLATE,
        ProtectedSpanKind.VIN,
        ProtectedSpanKind.PHONE,
        ProtectedSpanKind.DTC,
        ProtectedSpanKind.NUMBER,
    }.issubset(kinds)

    res = default_registry.lookup_text(raw, allow_fuzzy=True)
    # Plates, VIN, phone, numbers, and unknown DTC P0301 must NEVER be fuzzy-rewritten or matched;
    # exact DTC P0300 and currency term TL may appear only as EXACT non-rewritten matches.
    for m in res.matches:
        assert m.match_kind != MatchKind.FUZZY
        assert m.raw_text in {"P0300", "TL"}
        assert m.match_kind == MatchKind.EXACT
        for p in protected:
            if p.kind != ProtectedSpanKind.DTC:
                assert not (m.span.start < p.span.end_exclusive and p.span.start < m.span.end_exclusive), (
                    f"Protected span {p} leaked into match {m}"
                )
    assert all(m.raw_text != "P0301" for m in res.matches)

    # Verify non-protected typo can fuzzy-match when allow_fuzzy=True, while protected DTC stays untouched
    typo_res = default_registry.lookup_text("Folksvagenl ve P0301", allow_fuzzy=True)
    assert any(m.raw_text == "Folksvagenl" and m.match_kind == MatchKind.FUZZY for m in typo_res.matches)
    assert all(m.raw_text != "P0301" for m in typo_res.matches)


def test_ambiguous_aliases_bounded_without_silent_winner(default_registry: LexiconRegistry) -> None:
    # Real compiled multi-brand standalone model: 124 Spider -> Abarth 124 Spider & Fiat 124 Spider
    res = default_registry.lookup_text("124 Spider")
    assert res.status == LookupStatus.AMBIGUOUS
    assert res.ambiguous is True
    assert len(res.matches) == 1
    m = res.matches[0]
    assert m.match_kind == MatchKind.AMBIGUOUS
    assert m.selected_entity is None
    assert {c.canonical_name for c in m.candidates} == {"Abarth 124 Spider", "Fiat 124 Spider"}

    # Disambiguated with brand prefix via longest multi-token match
    disamb = default_registry.lookup_text("Fiat 124 Spider")
    assert disamb.status == LookupStatus.MATCHED
    assert not disamb.ambiguous
    assert disamb.matches[0].selected_entity is not None
    assert disamb.matches[0].selected_entity.canonical_name == "Fiat 124 Spider"

    # Synthetic bounded ambiguity test (6 entities sharing alias, max_candidates=3)
    ents = tuple(
        CanonicalEntity(
            entity_id=make_safe_id("model", f"brand_{idx}_orion"),
            canonical_name=f"Brand{idx} Orion",
            category=EntityCategory.MODEL,
            normalized_key=f"brand{idx} orion",
            priority=10 + idx,
        )
        for idx in range(6)
    )
    aliases = tuple(
        AliasEntry(
            alias_id=make_safe_id("alias", f"orion_{idx}"),
            alias_text="Orion",
            normalized_key="orion",
            canonical_entity_id=ent.entity_id,
            canonical_name=ent.canonical_name,
            category=EntityCategory.MODEL,
            priority=10 + idx,
        )
        for idx, ent in enumerate(ents)
    )
    snap = LexiconSnapshot(entities=ents, aliases=aliases, pronunciations=(), technical_terms=())
    reg = LexiconRegistry.from_snapshot(snap)
    bounded = reg.lookup_text("Orion", max_candidates=3)
    assert bounded.ambiguous is True
    assert bounded.matches[0].selected_entity is None
    assert len(bounded.matches[0].candidates) == 3
    assert len(bounded.candidates) == 3

    with pytest.raises(ValueError, match="silent winner"):
        LookupMatch(
            raw_text="Orion",
            span=UnicodeSpan(0, 5, "RAW"),
            matched_key="orion",
            match_kind=MatchKind.AMBIGUOUS,
            candidates=ents[:2],
            selected_entity=ents[0],
            score=0.5,
            ambiguous=True,
        )


def test_asr_adapter_outputs_unverified_candidate_only(default_registry: LexiconRegistry) -> None:
    transcript = "Pejo ve 124 Spider için randevu"
    extraction = extract_asr_candidates(default_registry, transcript)
    assert len(extraction.candidates) == 2
    for cand in extraction.candidates:
        assert cand.catalog_status == CatalogStatus.UNVERIFIED
        assert cand.confirmation_status == ConfirmationStatus.CANDIDATE
        assert cand.source_span is not None
        assert cand.source_span.representation == "RAW"
        assert transcript[cand.source_span.start:cand.source_span.end_exclusive] == cand.raw_value
        assert cand.scorer_revision == default_registry.lexicon_revision

    pejo_cand, spider_cand = extraction.candidates
    assert pejo_cand.canonical_value == "Peugeot"
    assert spider_cand.canonical_value is None
    assert set(spider_cand.alternatives) == {"Abarth 124 Spider", "Fiat 124 Spider"}

    env = EventEnvelope(
        schema_version=CONTRACT_SCHEMA_VERSION,
        event_type="asr.final",
        session_id="sess-m05",
        trace_id="trace-m05",
        turn_id=1,
        generation_id=None,
        sequence=1,
        monotonic_ns=12345,
        clock_domain="test.clock",
        producer="test.asr",
    )
    asr_res = ASRResult(
        envelope=env,
        utterance_id="utt-1",
        revision=1,
        status=ASRStatus.FINAL,
        raw_transcript=transcript,
        outcome=ASROutcome.OK,
    )
    enriched = enrich_asr_result(default_registry, asr_res)
    assert enriched.raw_transcript == transcript
    assert len(enriched.entities) == 2
    assert all(e.confirmation_status == ConfirmationStatus.CANDIDATE for e in enriched.entities)
    assert all(e.catalog_status == CatalogStatus.UNVERIFIED for e in enriched.entities)


def test_tts_adapter_scoped_pronunciations_without_sentence_rewrite(default_registry: LexiconRegistry) -> None:
    sentence = "Yarın saat 14:30'da Peugeot 3008 ve 34 BMW 320 için fiyat 1.250.000 TL."
    scoped = resolve_scoped_pronunciations(default_registry, sentence, profile="tts_2026")
    assert [s.raw_text for s in scoped] == ["Peugeot 3008", "TL"]
    item = scoped[0]
    assert item.canonical_name == "Peugeot 3008"
    assert item.raw_text == "Peugeot 3008"
    assert item.span is not None
    assert sentence[item.span.start:item.span.end_exclusive] == "Peugeot 3008"
    assert "pöjo" in item.spoken_text.lower() or "pejo" in item.spoken_text.lower()
    # Surrounding numbers/time/plate were never rewritten or returned as pronunciations
    assert get_pronunciation_variants(default_registry, "34 BMW 320") == ()
    assert get_pronunciation_variants(default_registry, "1.250.000") == ()
    assert get_pronunciation_variants(default_registry, "WVWZZZ3CZWE123456") == ()
    assert len(get_pronunciation_variants(default_registry, "Peugeot 3008")) >= 1

    # Explicitly scoped sub-span check
    idx = sentence.index("Peugeot 3008")
    sub_scoped = resolve_scoped_pronunciations(
        default_registry,
        sentence,
        span=UnicodeSpan(idx, idx + len("Peugeot 3008"), "RAW"),
    )
    assert len(sub_scoped) == 1
    assert sub_scoped[0].span == UnicodeSpan(idx, idx + len("Peugeot 3008"), "RAW")


def test_catalog_adapter_read_only_opaque_seam(default_registry: LexiconRegistry) -> None:
    items = [
        {"id": "veh-1", "brand": "Renault", "model": "Megane", "description": "Renault Megane 1.5 dCi", "secret_vin": "OPAQUE"},
        {"id": "veh-2", "brand": "Fiat", "model": "124 Spider", "description": "Fiat 124 Spider"},
        {"id": "veh-3", "brand": "Abarth", "model": "124 Spider", "description": "Abarth 124 Spider"},
    ]
    seam = InMemoryCatalogSeam(items, default_registry)
    refs = seam.list_refs()
    assert len(refs) == 3
    assert all(isinstance(r, CatalogItemRef) for r in refs)
    with pytest.raises(TypeError):
        refs[0].opaque_payload["secret_vin"] = "mutated"  # type: ignore[index]

    unambig_lookup = default_registry.lookup_text("Reno Megan")
    unambig_res = seam.resolve_lookup_to_refs(unambig_lookup)
    assert not unambig_res.ambiguous
    assert unambig_res.selected_ref is not None
    assert unambig_res.selected_ref.brand == "Renault"
    assert unambig_res.selected_ref.model == "Megane"

    ambig_lookup = default_registry.lookup_text("124 Spider")
    ambig_res = seam.resolve_lookup_to_refs(ambig_lookup)
    assert ambig_res.ambiguous is True
    assert ambig_res.selected_ref is None
    assert len(ambig_res.candidates) == 2

    asr_extract = extract_asr_candidates(default_registry, "124 Spider")
    cand_res = seam.resolve_candidates_to_refs(asr_extract.candidates)
    assert cand_res.ambiguous is True
    assert cand_res.selected_ref is None
