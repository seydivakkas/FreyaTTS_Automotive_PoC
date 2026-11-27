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
from enum import StrEnum

from backend.core.contracts.recognition import UnicodeSpan
from backend.shared_lexicon.contracts import EntityCategory, PronunciationVariant
from backend.shared_lexicon.registry import LexiconRegistry
from backend.shared_lexicon.tts_adapter import ScopedPronunciation, resolve_scoped_pronunciations
from backend.shared_lexicon.unicode_normalizer import normalize_matching_key


class VariantGovernanceStatus(StrEnum):
    """Governance approval state for lexicon pronunciation variants."""

    APPROVED = "APPROVED"
    LEGACY_PRESERVED = "LEGACY_PRESERVED"
    PROPOSED = "PROPOSED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"


_ACTIVE_GOVERNANCE = frozenset({
    VariantGovernanceStatus.APPROVED,
    VariantGovernanceStatus.LEGACY_PRESERVED,
})


@dataclass(frozen=True, slots=True)
class ApprovedPronunciationMatch:
    """Scoped pronunciation resolution pinned to an immutable M05 LexiconSnapshot."""

    entity_id: str
    canonical_name: str
    category: EntityCategory
    raw_text: str
    raw_span: tuple[int, int]
    spoken_text: str
    profile: str
    governance_status: VariantGovernanceStatus
    vocab_validated: bool
    lexicon_revision: str
    phonetic_syllables: tuple[str, ...] = ()
    stress_syllable_idx: int | None = None


class LexiconAdapter:
    """Read-only adapter over a pinned M05 LexiconRegistry snapshot."""

    def __init__(
        self,
        registry: LexiconRegistry,
        *,
        preferred_profile: str = "tts_2026",
        variant_governance: dict[str, VariantGovernanceStatus] | None = None,
    ) -> None:
        if not isinstance(registry, LexiconRegistry):
            raise TypeError("registry must be M05 LexiconRegistry")
        self._registry = registry
        self._preferred_profile = preferred_profile
        self._governance = dict(variant_governance or {})

    @property
    def lexicon_revision(self) -> str:
        return self._registry.lexicon_revision

    @property
    def registry(self) -> LexiconRegistry:
        return self._registry

    def governance_for_variant(self, variant: PronunciationVariant) -> VariantGovernanceStatus:
        if variant.variant_id in self._governance:
            return self._governance[variant.variant_id]
        if variant.surface_key in self._governance:
            return self._governance[variant.surface_key]
        if variant.profile in {"tts_sezer", "base"}:
            return VariantGovernanceStatus.LEGACY_PRESERVED
        return VariantGovernanceStatus.APPROVED

    def lookup_scoped(
        self,
        text: str,
        *,
        span: UnicodeSpan | None = None,
    ) -> tuple[ApprovedPronunciationMatch, ...]:
        """Resolve approved scoped pronunciations without full-sentence rewriting."""
        scoped_list: tuple[ScopedPronunciation, ...] = resolve_scoped_pronunciations(
            self._registry,
            text,
            profile=self._preferred_profile,
            span=span,
        )
        matches: list[ApprovedPronunciationMatch] = []
        for sc in scoped_list:
            if sc.span is None:
                continue
            gov = self.governance_for_variant(sc.variant)
            if gov not in _ACTIVE_GOVERNANCE:
                continue
            ent = self._registry.get_entity(sc.entity_id)
            cat = ent.category if ent is not None else EntityCategory.UNKNOWN
            matches.append(
                ApprovedPronunciationMatch(
                    entity_id=sc.entity_id,
                    canonical_name=sc.canonical_name,
                    category=cat,
                    raw_text=sc.raw_text,
                    raw_span=(sc.span.start, sc.span.end_exclusive),
                    spoken_text=sc.spoken_text,
                    profile=sc.profile,
                    governance_status=gov,
                    vocab_validated=sc.vocab_validated,
                    lexicon_revision=sc.lexicon_revision,
                    phonetic_syllables=sc.phonetic_syllables,
                    stress_syllable_idx=sc.stress_syllable_idx,
                )
            )
        return tuple(matches)

    def lookup_term_pronunciation(
        self,
        term: str,
        *,
        expected_category: EntityCategory | None = None,
    ) -> ApprovedPronunciationMatch | None:
        """
        Lookup an exact single term safely; returns None when ambiguous, missing,
        or governed as PROPOSED/QUARANTINED/REJECTED.
        """
        if not term or not term.strip():
            return None
        lookup = self._registry.lookup_term(term, max_candidates=3)
        if lookup.ambiguous or len(lookup.matches) != 1:
            return None
        m = lookup.matches[0]
        if m.ambiguous or m.selected_entity is None:
            return None
        ent = m.selected_entity
        if expected_category is not None and ent.category != expected_category:
            return None
        key = normalize_matching_key(term)
        variants = tuple(
            v for v in self._registry.get_pronunciations_for_key(key)
            if v.canonical_entity_id == ent.entity_id
        )
        if not variants:
            variants = self._registry.get_pronunciations_for_entity(ent.entity_id)

        # Prefer active preferred profile, then fallback within active governance only.
        for prof in (self._preferred_profile, "tts_2026", "spoken", "tts_sezer", "base", "foreign"):
            for v in variants:
                if v.profile != prof:
                    continue
                gov = self.governance_for_variant(v)
                if gov in _ACTIVE_GOVERNANCE:
                    return ApprovedPronunciationMatch(
                        entity_id=ent.entity_id,
                        canonical_name=ent.canonical_name,
                        category=ent.category,
                        raw_text=term,
                        raw_span=(0, len(term)),
                        spoken_text=v.spoken_text,
                        profile=v.profile,
                        governance_status=gov,
                        vocab_validated=v.vocab_validated,
                        lexicon_revision=self._registry.lexicon_revision,
                        phonetic_syllables=v.phonetic_syllables,
                        stress_syllable_idx=v.stress_syllable_idx,
                    )
        return None
