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

from dataclasses import dataclass, replace

from backend.core.contracts.recognition import (
    ASRResult,
    CatalogStatus,
    ConfirmationStatus,
    EntityCandidate,
)
from backend.shared_lexicon.contracts import LookupMatch, LookupResult, make_safe_id
from backend.shared_lexicon.registry import LexiconRegistry


@dataclass(frozen=True, slots=True)
class ASRLexiconExtraction:
    """Immutable ASR lexicon extraction bundle linking M01 EntityCandidates to M05 LookupResult."""

    candidates: tuple[EntityCandidate, ...]
    lookup_result: LookupResult
    lexicon_revision: str


def _entity_candidate_from_match(match: LookupMatch, lexicon_revision: str) -> EntityCandidate:
    if match.ambiguous or match.selected_entity is None:
        categories = {c.category.value for c in match.candidates}
        entity_type = next(iter(categories)) if len(categories) == 1 else "AMBIGUOUS"
        eid = make_safe_id("ambig", f"{match.span.start}-{match.span.end_exclusive}:{match.matched_key}")
        return EntityCandidate(
            entity_id=eid,
            entity_type=entity_type,
            raw_value=match.raw_text,
            canonical_value=None,
            source_span=match.span,
            score=match.score,
            score_kind="lexicon_lookup",
            scorer_revision=lexicon_revision,
            alternatives=tuple(c.canonical_name for c in match.candidates),
            catalog_status=CatalogStatus.UNVERIFIED,
            confirmation_status=ConfirmationStatus.CANDIDATE,
        )

    selected = match.selected_entity
    return EntityCandidate(
        entity_id=selected.entity_id,
        entity_type=selected.category.value,
        raw_value=match.raw_text,
        canonical_value=selected.canonical_name,
        source_span=match.span,
        score=match.score,
        score_kind="lexicon_lookup",
        scorer_revision=lexicon_revision,
        alternatives=(),
        catalog_status=CatalogStatus.UNVERIFIED,
        confirmation_status=ConfirmationStatus.CANDIDATE,
    )


def extract_asr_candidates(
    registry: LexiconRegistry,
    raw_transcript: str,
    *,
    max_candidates: int = 5,
    allow_fuzzy: bool = False,
) -> ASRLexiconExtraction:
    """
    Extracts M01 EntityCandidate objects from raw ASR transcript.
    Strictly enforces catalog_status=UNVERIFIED and confirmation_status=CANDIDATE.
    """
    lookup = registry.lookup_text(
        raw_transcript,
        max_candidates=max_candidates,
        allow_fuzzy=allow_fuzzy,
    )
    candidates = tuple(
        _entity_candidate_from_match(match, registry.lexicon_revision)
        for match in lookup.matches
    )
    return ASRLexiconExtraction(
        candidates=candidates,
        lookup_result=lookup,
        lexicon_revision=registry.lexicon_revision,
    )


def enrich_asr_result(
    registry: LexiconRegistry,
    asr_result: ASRResult,
    *,
    max_candidates: int = 5,
    allow_fuzzy: bool = False,
) -> ASRResult:
    """
    Returns a new immutable M01 ASRResult populated with UNVERIFIED / CANDIDATE EntityCandidates
    without ever altering raw_transcript or confirming entities.
    """
    if not isinstance(asr_result, ASRResult):
        raise TypeError("asr_result must be M01 ASRResult")
    extraction = extract_asr_candidates(
        registry,
        asr_result.raw_transcript,
        max_candidates=max_candidates,
        allow_fuzzy=allow_fuzzy,
    )
    existing_spans = {(e.source_span.start, e.source_span.end_exclusive) for e in asr_result.entities if e.source_span is not None}
    merged = list(asr_result.entities)
    for cand in extraction.candidates:
        if cand.source_span is not None and (cand.source_span.start, cand.source_span.end_exclusive) in existing_spans:
            continue
        merged.append(cand)
    return replace(asr_result, entities=tuple(merged))
