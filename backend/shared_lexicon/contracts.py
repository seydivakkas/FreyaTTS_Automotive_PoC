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

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, ContractVersion
from backend.core.contracts.recognition import UnicodeSpan
from backend.core.contracts.validation import (
    freeze_value,
    require_finite,
    require_safe_id,
    require_strict_int,
    thaw_value,
)

_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_SLUG_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_PHONE_LIKE_RE = re.compile(r"(?:\+90|0)\s*\(?[2-5]\d{2}\)?[\s-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}")

_TRANSLIT_MAP = str.maketrans({
    "ç": "c",
    "Ç": "C",
    "ğ": "g",
    "Ğ": "G",
    "ı": "i",
    "I": "I",
    "İ": "I",
    "ö": "o",
    "Ö": "O",
    "ş": "s",
    "Ş": "S",
    "ü": "u",
    "Ü": "U",
    "š": "s",
    "Š": "S",
    "ë": "e",
    "Ë": "E",
    "é": "e",
    "É": "E",
    "á": "a",
    "Á": "A",
    "â": "a",
    "Â": "A",
    "î": "i",
    "Î": "I",
    "û": "u",
    "Û": "U",
    "ú": "u",
    "Ú": "U",
    "ä": "a",
    "Ä": "A",
    "ž": "z",
    "Ž": "Z",
    "č": "c",
    "Č": "C",
    "ñ": "n",
    "Ñ": "N",
})

_TIMESTAMP_KEYS = frozenset({
    "timestamp",
    "utc_timestamp",
    "created_at",
    "updated_at",
    "loaded_at",
    "generated_at",
    "measured_at",
})


def make_safe_id(prefix: str, key: str) -> str:
    """Builds a deterministic M01-compliant safe identifier from prefix and key."""
    if not isinstance(prefix, str) or not prefix.strip():
        raise ValueError("prefix must be non-empty string")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("key must be non-empty string")
    ascii_prefix = _SAFE_SLUG_RE.sub("_", prefix.translate(_TRANSLIT_MAP)).strip("._-") or "lex"
    raw_ascii = _SAFE_SLUG_RE.sub("_", key.translate(_TRANSLIT_MAP)).strip("._-").lower()
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    if not raw_ascii:
        candidate = f"{ascii_prefix}:{digest}"
    elif raw_ascii != key.strip().lower() or len(ascii_prefix) + 1 + len(raw_ascii) > 110 or _PHONE_LIKE_RE.search(raw_ascii):
        slug = raw_ascii[:88].strip("._-") or "item"
        candidate = f"{ascii_prefix}:{slug}_{digest}"
    else:
        candidate = f"{ascii_prefix}:{raw_ascii}"
    if not candidate[0].isalnum():
        candidate = f"x{candidate}"
    candidate = candidate[:128]
    return require_safe_id(candidate, "entity_id")


class EntityCategory(StrEnum):
    BRAND = "BRAND"
    MODEL = "MODEL"
    TECHNICAL = "TECHNICAL"
    DTC = "DTC"
    INFLECTION = "INFLECTION"
    EXACT_NORMALIZATION = "EXACT_NORMALIZATION"
    UNKNOWN = "UNKNOWN"


class ProtectedSpanKind(StrEnum):
    PLATE = "PLATE"
    VIN = "VIN"
    PHONE = "PHONE"
    DTC = "DTC"
    NUMBER = "NUMBER"


class MatchKind(StrEnum):
    EXACT = "EXACT"
    ALIAS = "ALIAS"
    INFLECTED = "INFLECTED"
    FUZZY = "FUZZY"
    AMBIGUOUS = "AMBIGUOUS"
    PROTECTED = "PROTECTED"
    NONE = "NONE"


class LookupStatus(StrEnum):
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    PROTECTED = "PROTECTED"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True, slots=True)
class CanonicalEntity:
    """Immutable canonical automotive entity."""

    entity_id: str
    canonical_name: str
    category: EntityCategory
    normalized_key: str
    brand_name: str | None = None
    model_name: str | None = None
    aliases: tuple[str, ...] = ()
    priority: int = 30
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        require_safe_id(self.entity_id, "entity_id")
        if not isinstance(self.canonical_name, str) or not self.canonical_name.strip():
            raise ValueError("canonical_name must be non-empty string")
        if not isinstance(self.category, EntityCategory):
            raise ValueError("category must be EntityCategory")
        if not isinstance(self.normalized_key, str) or not self.normalized_key.strip():
            raise ValueError("normalized_key must be non-empty string")
        require_strict_int(self.priority, "priority", minimum=0, maximum=10000)
        object.__setattr__(self, "aliases", freeze_value(tuple(dict.fromkeys(str(a) for a in self.aliases if str(a).strip()))))
        object.__setattr__(self, "metadata", freeze_value(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class AliasEntry:
    """Immutable mapping from a normalized alias key to a canonical entity."""

    alias_id: str
    alias_text: str
    normalized_key: str
    canonical_entity_id: str
    canonical_name: str
    category: EntityCategory
    priority: int = 30
    source: str = "compiled"

    def __post_init__(self) -> None:
        require_safe_id(self.alias_id, "alias_id")
        if not isinstance(self.alias_text, str) or not self.alias_text.strip():
            raise ValueError("alias_text must be non-empty string")
        if not isinstance(self.normalized_key, str) or not self.normalized_key.strip():
            raise ValueError("normalized_key must be non-empty string")
        require_safe_id(self.canonical_entity_id, "canonical_entity_id")
        if not isinstance(self.canonical_name, str) or not self.canonical_name.strip():
            raise ValueError("canonical_name must be non-empty string")
        if not isinstance(self.category, EntityCategory):
            raise ValueError("category must be EntityCategory")
        require_strict_int(self.priority, "priority", minimum=0, maximum=10000)
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must be non-empty string")


@dataclass(frozen=True, slots=True)
class PronunciationVariant:
    """Immutable scoped pronunciation specification for TTS."""

    variant_id: str
    canonical_entity_id: str
    surface_key: str
    spoken_text: str
    profile: str = "tts_2026"
    phonetic_syllables: tuple[str, ...] = ()
    stress_syllable_idx: int | None = None
    ends_with_consonant: bool | None = None
    last_vowel_backness: str | None = None
    vocab_validated: bool = False
    priority: int = 30

    def __post_init__(self) -> None:
        require_safe_id(self.variant_id, "variant_id")
        require_safe_id(self.canonical_entity_id, "canonical_entity_id")
        if not isinstance(self.surface_key, str) or not self.surface_key.strip():
            raise ValueError("surface_key must be non-empty string")
        if not isinstance(self.spoken_text, str) or not self.spoken_text.strip():
            raise ValueError("spoken_text must be non-empty string")
        if not isinstance(self.profile, str) or not self.profile.strip():
            raise ValueError("profile must be non-empty string")
        if self.stress_syllable_idx is not None:
            require_strict_int(self.stress_syllable_idx, "stress_syllable_idx", minimum=0, maximum=128)
        if self.last_vowel_backness is not None and self.last_vowel_backness not in {"back", "front"}:
            raise ValueError("last_vowel_backness must be 'back', 'front', or None")
        if not isinstance(self.vocab_validated, bool):
            raise TypeError("vocab_validated must be bool")
        require_strict_int(self.priority, "priority", minimum=0, maximum=10000)
        object.__setattr__(self, "phonetic_syllables", freeze_value(tuple(str(s) for s in self.phonetic_syllables)))


@dataclass(frozen=True, slots=True)
class TechnicalTerm:
    """Immutable automotive technical term or diagnostic code entry."""

    term_id: str
    canonical_name: str
    normalized_key: str
    category: str
    spoken_text: str | None = None
    aliases: tuple[str, ...] = ()
    priority: int = 40

    def __post_init__(self) -> None:
        require_safe_id(self.term_id, "term_id")
        if not isinstance(self.canonical_name, str) or not self.canonical_name.strip():
            raise ValueError("canonical_name must be non-empty string")
        if not isinstance(self.normalized_key, str) or not self.normalized_key.strip():
            raise ValueError("normalized_key must be non-empty string")
        if not isinstance(self.category, str) or not self.category.strip():
            raise ValueError("category must be non-empty string")
        require_strict_int(self.priority, "priority", minimum=0, maximum=10000)
        object.__setattr__(self, "aliases", freeze_value(tuple(dict.fromkeys(str(a) for a in self.aliases if str(a).strip()))))


@dataclass(frozen=True, slots=True)
class ProtectedSpan:
    """Immutable protected raw span (plate, VIN, phone, DTC, number)."""

    kind: ProtectedSpanKind
    span: UnicodeSpan
    raw_text: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ProtectedSpanKind):
            raise ValueError("kind must be ProtectedSpanKind")
        if not isinstance(self.span, UnicodeSpan):
            raise TypeError("span must be UnicodeSpan")
        if self.span.representation != "RAW":
            raise ValueError("ProtectedSpan requires RAW UnicodeSpan")
        if not isinstance(self.raw_text, str):
            raise TypeError("raw_text must be str")


@dataclass(frozen=True, slots=True)
class LookupMatch:
    """Immutable match item preserving exact raw text and half-open codepoint span."""

    raw_text: str
    span: UnicodeSpan
    matched_key: str
    match_kind: MatchKind
    candidates: tuple[CanonicalEntity, ...]
    selected_entity: CanonicalEntity | None
    score: float
    ambiguous: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.raw_text, str):
            raise TypeError("raw_text must be str")
        if not isinstance(self.span, UnicodeSpan):
            raise TypeError("span must be UnicodeSpan")
        if self.span.representation != "RAW":
            raise ValueError("LookupMatch span must use representation='RAW'")
        if not isinstance(self.matched_key, str):
            raise TypeError("matched_key must be str")
        if not isinstance(self.match_kind, MatchKind):
            raise ValueError("match_kind must be MatchKind")
        require_finite(self.score, "score", minimum=0.0, maximum=1.0)
        frozen_cands = tuple(self.candidates)
        for cand in frozen_cands:
            if not isinstance(cand, CanonicalEntity):
                raise TypeError("candidates must contain CanonicalEntity")
        if self.ambiguous or len(frozen_cands) > 1:
            if self.selected_entity is not None:
                raise ValueError("Ambiguous LookupMatch must not set a silent winner in selected_entity")
            if self.match_kind not in {MatchKind.AMBIGUOUS, MatchKind.PROTECTED}:
                raise ValueError("Multiple candidates require match_kind=AMBIGUOUS")
        elif len(frozen_cands) == 1 and self.selected_entity is not None and self.selected_entity != frozen_cands[0]:
            raise ValueError("selected_entity must match the single candidate")
        object.__setattr__(self, "candidates", freeze_value(frozen_cands))


@dataclass(frozen=True, slots=True)
class LookupResult:
    """Immutable lookup outcome across an input text or term."""

    raw_text: str
    normalized_text: str
    status: LookupStatus
    lexicon_revision: str
    matches: tuple[LookupMatch, ...] = ()
    protected_spans: tuple[ProtectedSpan, ...] = ()
    candidates: tuple[CanonicalEntity, ...] = ()
    ambiguous: bool = False
    bounded_limit: int = 5

    def __post_init__(self) -> None:
        if not isinstance(self.raw_text, str) or not isinstance(self.normalized_text, str):
            raise TypeError("raw_text and normalized_text must be str")
        if not isinstance(self.status, LookupStatus):
            raise ValueError("status must be LookupStatus")
        if not isinstance(self.lexicon_revision, str) or _SHA256_HEX_RE.fullmatch(self.lexicon_revision) is None:
            raise ValueError("lexicon_revision must be 64-char lowercase hex SHA-256")
        require_strict_int(self.bounded_limit, "bounded_limit", minimum=1, maximum=100)
        for m in self.matches:
            if not isinstance(m, LookupMatch):
                raise TypeError("matches must contain LookupMatch")
            if m.span.end_exclusive > len(self.raw_text):
                raise ValueError("LookupMatch span exceeds raw_text length")
            if self.raw_text[m.span.start:m.span.end_exclusive] != m.raw_text:
                raise ValueError("LookupMatch raw_text does not match raw_text[span]")
        for p in self.protected_spans:
            if not isinstance(p, ProtectedSpan):
                raise TypeError("protected_spans must contain ProtectedSpan")
            if p.span.end_exclusive > len(self.raw_text):
                raise ValueError("ProtectedSpan exceeds raw_text length")
        cands = tuple(self.candidates)
        if len(cands) > self.bounded_limit:
            raise ValueError("candidates exceeds bounded_limit")
        object.__setattr__(self, "matches", freeze_value(tuple(self.matches)))
        object.__setattr__(self, "protected_spans", freeze_value(tuple(self.protected_spans)))
        object.__setattr__(self, "candidates", freeze_value(cands))


def _strip_timestamps(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return {
            str(k): _strip_timestamps(v)
            for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))
            if str(k).lower() not in _TIMESTAMP_KEYS
        }
    if isinstance(obj, (list, tuple)):
        return [_strip_timestamps(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(_strip_timestamps(v) for v in obj)
    return thaw_value(obj)


def compute_lexicon_revision(
    *,
    schema_version: str,
    source_version: str,
    entities: tuple[CanonicalEntity, ...],
    aliases: tuple[AliasEntry, ...],
    pronunciations: tuple[PronunciationVariant, ...],
    technical_terms: tuple[TechnicalTerm, ...],
    vocab_chars: frozenset[str],
    source_metadata: Mapping[str, Any] | None = None,
) -> str:
    """Computes deterministic SHA-256 revision independent of timestamps and insertion order."""
    payload = {
        "schema_version": schema_version,
        "source_version": source_version,
        "entities": sorted(
            (
                {
                    "entity_id": e.entity_id,
                    "canonical_name": e.canonical_name,
                    "category": e.category.value,
                    "normalized_key": e.normalized_key,
                    "brand_name": e.brand_name,
                    "model_name": e.model_name,
                    "aliases": sorted(e.aliases),
                    "priority": e.priority,
                    "metadata": _strip_timestamps(e.metadata),
                }
                for e in entities
            ),
            key=lambda x: x["entity_id"],
        ),
        "aliases": sorted(
            (
                {
                    "alias_id": a.alias_id,
                    "alias_text": a.alias_text,
                    "normalized_key": a.normalized_key,
                    "canonical_entity_id": a.canonical_entity_id,
                    "canonical_name": a.canonical_name,
                    "category": a.category.value,
                    "priority": a.priority,
                    "source": a.source,
                }
                for a in aliases
            ),
            key=lambda x: (x["alias_id"], x["canonical_entity_id"]),
        ),
        "pronunciations": sorted(
            (
                {
                    "variant_id": p.variant_id,
                    "canonical_entity_id": p.canonical_entity_id,
                    "surface_key": p.surface_key,
                    "spoken_text": p.spoken_text,
                    "profile": p.profile,
                    "phonetic_syllables": list(p.phonetic_syllables),
                    "stress_syllable_idx": p.stress_syllable_idx,
                    "ends_with_consonant": p.ends_with_consonant,
                    "last_vowel_backness": p.last_vowel_backness,
                    "vocab_validated": p.vocab_validated,
                    "priority": p.priority,
                }
                for p in pronunciations
            ),
            key=lambda x: x["variant_id"],
        ),
        "technical_terms": sorted(
            (
                {
                    "term_id": t.term_id,
                    "canonical_name": t.canonical_name,
                    "normalized_key": t.normalized_key,
                    "category": t.category,
                    "spoken_text": t.spoken_text,
                    "aliases": sorted(t.aliases),
                    "priority": t.priority,
                }
                for t in technical_terms
            ),
            key=lambda x: x["term_id"],
        ),
        "vocab_chars": sorted(vocab_chars),
        "source_metadata": _strip_timestamps(source_metadata or {}),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class LexiconSnapshot:
    """Deeply immutable versioned snapshot of the shared automotive lexicon."""

    entities: tuple[CanonicalEntity, ...]
    aliases: tuple[AliasEntry, ...]
    pronunciations: tuple[PronunciationVariant, ...]
    technical_terms: tuple[TechnicalTerm, ...]
    vocab_chars: frozenset[str] = field(default_factory=frozenset)
    schema_version: str = CONTRACT_SCHEMA_VERSION
    source_version: str = "2026.1"
    lexicon_revision: str = ""
    source_metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        ContractVersion.parse(self.schema_version)
        if not isinstance(self.source_version, str) or not self.source_version.strip():
            raise ValueError("source_version must be non-empty string")
        sorted_entities = tuple(sorted(self.entities, key=lambda e: e.entity_id))
        sorted_aliases = tuple(sorted(self.aliases, key=lambda a: (a.alias_id, a.canonical_entity_id)))
        sorted_prons = tuple(sorted(self.pronunciations, key=lambda p: p.variant_id))
        sorted_terms = tuple(sorted(self.technical_terms, key=lambda t: t.term_id))
        frozen_vocab = frozenset(str(c) for c in self.vocab_chars)
        frozen_meta = freeze_value(dict(self.source_metadata))

        expected_rev = compute_lexicon_revision(
            schema_version=self.schema_version,
            source_version=self.source_version,
            entities=sorted_entities,
            aliases=sorted_aliases,
            pronunciations=sorted_prons,
            technical_terms=sorted_terms,
            vocab_chars=frozen_vocab,
            source_metadata=frozen_meta,
        )
        if not self.lexicon_revision:
            rev = expected_rev
        else:
            if _SHA256_HEX_RE.fullmatch(self.lexicon_revision) is None:
                raise ValueError("lexicon_revision must be 64-char lowercase hex SHA-256")
            if self.lexicon_revision != expected_rev:
                raise ValueError("lexicon_revision does not match canonical snapshot content")
            rev = self.lexicon_revision

        object.__setattr__(self, "entities", sorted_entities)
        object.__setattr__(self, "aliases", sorted_aliases)
        object.__setattr__(self, "pronunciations", sorted_prons)
        object.__setattr__(self, "technical_terms", sorted_terms)
        object.__setattr__(self, "vocab_chars", frozen_vocab)
        object.__setattr__(self, "lexicon_revision", rev)
        object.__setattr__(self, "source_metadata", frozen_meta)

    def __repr__(self) -> str:
        return (
            f"LexiconSnapshot(rev={self.lexicon_revision[:12]!r}, "
            f"entities={len(self.entities)}, aliases={len(self.aliases)}, "
            f"pronunciations={len(self.pronunciations)}, terms={len(self.technical_terms)})"
        )
