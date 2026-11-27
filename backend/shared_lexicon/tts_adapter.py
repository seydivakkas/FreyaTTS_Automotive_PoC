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

from backend.core.contracts.recognition import UnicodeSpan
from backend.shared_lexicon.contracts import (
    LookupMatch,
    PronunciationVariant,
    ProtectedSpanKind,
)
from backend.shared_lexicon.registry import LexiconRegistry
from backend.shared_lexicon.unicode_normalizer import detect_protected_spans, normalize_matching_key

_PROFILE_FALLBACK_ORDER = ("tts_2026", "spoken", "tts_sezer", "base", "foreign")


@dataclass(frozen=True, slots=True)
class ScopedPronunciation:
    """Immutable scoped pronunciation variant bound to a specific span or term (never full-sentence rewrite)."""

    entity_id: str
    canonical_name: str
    raw_text: str
    span: UnicodeSpan | None
    variant: PronunciationVariant
    spoken_text: str
    phonetic_syllables: tuple[str, ...]
    stress_syllable_idx: int | None
    profile: str
    vocab_validated: bool
    lexicon_revision: str


def _select_variant(
    variants: tuple[PronunciationVariant, ...],
    *,
    preferred_profile: str,
) -> PronunciationVariant | None:
    if not variants:
        return None
    for prof in (preferred_profile, *_PROFILE_FALLBACK_ORDER):
        for v in variants:
            if v.profile == prof:
                return v
    return variants[0]


def get_pronunciation_variants(
    registry: LexiconRegistry,
    term_or_entity_id: str,
    *,
    profile: str | None = None,
) -> tuple[PronunciationVariant, ...]:
    """
    Returns scoped pronunciation variants for a single entity_id or surface term.
    Never normalizes full sentences and returns empty for protected spans (plates/VIN/phones/DTCs/numbers).
    """
    if not isinstance(term_or_entity_id, str) or not term_or_entity_id.strip():
        return ()

    direct_entity = registry.get_entity(term_or_entity_id)
    if direct_entity is not None:
        return registry.get_pronunciations_for_entity(direct_entity.entity_id, profile=profile)

    stripped = term_or_entity_id.strip()
    protected = detect_protected_spans(stripped)
    for p in protected:
        if p.kind in {ProtectedSpanKind.PLATE, ProtectedSpanKind.VIN, ProtectedSpanKind.PHONE}:
            return ()
        if p.span.start == 0 and p.span.end_exclusive == len(stripped):
            return ()

    key = normalize_matching_key(term_or_entity_id)
    by_key = registry.get_pronunciations_for_key(key, profile=profile)
    if by_key:
        return by_key

    lookup = registry.lookup_term(term_or_entity_id, max_candidates=2)
    if len(lookup.matches) != 1:
        return ()
    match = lookup.matches[0]
    if match.ambiguous or match.selected_entity is None:
        return ()
    return registry.get_pronunciations_for_entity(match.selected_entity.entity_id, profile=profile)


def _scoped_from_match(
    registry: LexiconRegistry,
    match: LookupMatch,
    *,
    profile: str,
    offset: int = 0,
) -> ScopedPronunciation | None:
    if match.ambiguous or match.selected_entity is None:
        return None
    ent = match.selected_entity
    surface_variants = registry.get_pronunciations_for_key(match.matched_key)
    matching_surface = tuple(v for v in surface_variants if v.canonical_entity_id == ent.entity_id)
    chosen = _select_variant(matching_surface, preferred_profile=profile)
    if chosen is None:
        entity_variants = registry.get_pronunciations_for_entity(ent.entity_id)
        chosen = _select_variant(entity_variants, preferred_profile=profile)
    if chosen is None:
        return None
    span = UnicodeSpan(
        start=match.span.start + offset,
        end_exclusive=match.span.end_exclusive + offset,
        representation="RAW",
    )
    return ScopedPronunciation(
        entity_id=ent.entity_id,
        canonical_name=ent.canonical_name,
        raw_text=match.raw_text,
        span=span,
        variant=chosen,
        spoken_text=chosen.spoken_text,
        phonetic_syllables=chosen.phonetic_syllables,
        stress_syllable_idx=chosen.stress_syllable_idx,
        profile=chosen.profile,
        vocab_validated=chosen.vocab_validated,
        lexicon_revision=registry.lexicon_revision,
    )


def resolve_scoped_pronunciations(
    registry: LexiconRegistry,
    text: str,
    *,
    profile: str = "tts_2026",
    span: UnicodeSpan | None = None,
) -> tuple[ScopedPronunciation, ...]:
    """
    Resolves scoped pronunciation hints ONLY for matched automotive lexicon spans.
    Does not rewrite or normalize surrounding sentences, numbers, plates, VINs, phones, or DTCs.
    """
    if not isinstance(text, str):
        raise TypeError("text must be str")
    if span is not None:
        if span.representation != "RAW":
            raise ValueError("Scoped pronunciation span must have representation='RAW'")
        if span.end_exclusive > len(text):
            raise ValueError("Scoped pronunciation span exceeds text length")
        subtext = text[span.start:span.end_exclusive]
        offset = span.start
    else:
        subtext = text
        offset = 0

    lookup = registry.lookup_text(subtext, max_candidates=5, allow_fuzzy=False)
    results: list[ScopedPronunciation] = []
    for match in lookup.matches:
        scoped = _scoped_from_match(registry, match, profile=profile, offset=offset)
        if scoped is not None:
            results.append(scoped)
    return tuple(results)
