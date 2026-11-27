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

import re
from collections import defaultdict

from backend.core.contracts.recognition import UnicodeSpan
from backend.shared_lexicon.contracts import (
    CanonicalEntity,
    EntityCategory,
    LexiconSnapshot,
    LookupMatch,
    LookupResult,
    LookupStatus,
    MatchKind,
    PronunciationVariant,
    ProtectedSpan,
    ProtectedSpanKind,
    TechnicalTerm,
)
from backend.shared_lexicon.source_loader import load_lexicon_snapshot
from backend.shared_lexicon.unicode_normalizer import (
    AlignedToken,
    detect_protected_spans,
    fold_foreign_diacritics,
    normalize_matching_key,
    normalize_with_spans,
    tokenize_aligned,
)

# Short/generic Turkish words that must never trigger standalone 1-token entity extraction.
_UNSAFE_STANDALONE_KEYS = frozenset({
    "ds", "ce", "be", "de", "te", "se", "ef", "ka", "le", "me", "ne", "re", "ve", "ye", "ze",
    "ara", "ek", "al", "ol", "et", "at", "var", "yok", "bir", "iki", "üç", "dört", "beş",
    "fiyat", "cam", "far", "kapı", "yol", "gün", "ses", "su", "tip", "gaz", "kar", "tür",
    "line", "sport", "life", "style", "active", "plus", "pro", "max", "air", "hybrid", "nisan",
    "lounge", "touch", "prestige",
})

_TURKISH_APOSTROPHE_SUFFIX_RE = re.compile(
    r"^(?:(?:lar|ler)?"
    r"(?:[ıiuü]m|[ıiuü]n|s?[ıiuü]|[ıiuü]m[ıiuü]z|[ıiuü]n[ıiuü]z|lar[ıi]|ler[ıi])?"
    r"(?:l[ıiuü]|s[ıiuü]z|c[ıiuü]|ç[ıiuü])?"
    r"(?:y?[ae]|d[ae]|t[ae]|d[ae]n|t[ae]n|n?[ıiuü]|n?[ıiuü]n)?"
    r"(?:y?l[ae]|d[ae]ki|t[ae]ki|d[ıiuü]r|t[ıiuü]r|m[ıiuü]ş)*)$"
)


def _spans_overlap(a: UnicodeSpan, b: UnicodeSpan) -> bool:
    return a.start < b.end_exclusive and b.start < a.end_exclusive


def _edit_distance_at_most_one(a: str, b: str) -> bool:
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        return sum(1 for ca, cb in zip(a, b) if ca != cb) == 1
    if la > lb:
        a, b = b, a
        la, lb = lb, la
    i = j = diffs = 0
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
        else:
            diffs += 1
            if diffs > 1:
                return False
            j += 1
    return True


class LexiconRegistry:
    """Read-only, deterministic in-memory index over an immutable LexiconSnapshot."""

    def __init__(self, snapshot: LexiconSnapshot) -> None:
        if not isinstance(snapshot, LexiconSnapshot):
            raise TypeError("snapshot must be LexiconSnapshot")
        self._snapshot = snapshot
        self._entity_by_id: dict[str, CanonicalEntity] = {e.entity_id: e for e in snapshot.entities}

        # Key -> ordered unique CanonicalEntity list (primary key and foreign-folded secondary key)
        exact_map: dict[str, list[CanonicalEntity]] = defaultdict(list)
        folded_map: dict[str, list[CanonicalEntity]] = defaultdict(list)
        alias_map: dict[str, list[tuple[int, CanonicalEntity]]] = defaultdict(list)
        alias_folded_map: dict[str, list[tuple[int, CanonicalEntity]]] = defaultdict(list)
        max_tokens = 1

        def _append_unique(bucket: list[CanonicalEntity], ent: CanonicalEntity) -> None:
            if all(existing.entity_id != ent.entity_id for existing in bucket):
                bucket.append(ent)

        for ent in snapshot.entities:
            token_count = len(ent.normalized_key.split())
            if token_count > max_tokens:
                max_tokens = token_count
            _append_unique(exact_map[ent.normalized_key], ent)
            fk = fold_foreign_diacritics(ent.normalized_key)
            if fk != ent.normalized_key:
                _append_unique(folded_map[fk], ent)

        for al in snapshot.aliases:
            ent = self._entity_by_id.get(al.canonical_entity_id)
            if ent is None:
                continue
            token_count = len(al.normalized_key.split())
            if token_count > max_tokens:
                max_tokens = token_count
            alias_map[al.normalized_key].append((al.priority, ent))
            fk = fold_foreign_diacritics(al.normalized_key)
            if fk != al.normalized_key:
                alias_folded_map[fk].append((al.priority, ent))

        self._exact_entities: dict[str, tuple[CanonicalEntity, ...]] = {
            k: tuple(sorted(v, key=lambda e: (e.priority, e.entity_id)))
            for k, v in exact_map.items()
        }
        self._folded_entities: dict[str, tuple[CanonicalEntity, ...]] = {
            k: tuple(sorted(v, key=lambda e: (e.priority, e.entity_id)))
            for k, v in folded_map.items()
        }
        self._alias_entities: dict[str, tuple[CanonicalEntity, ...]] = {}
        for k, pairs in alias_map.items():
            seen: dict[str, tuple[int, CanonicalEntity]] = {}
            for prio, ent in pairs:
                if ent.entity_id not in seen or prio < seen[ent.entity_id][0]:
                    seen[ent.entity_id] = (prio, ent)
            ordered = tuple(ent for _, ent in sorted(seen.values(), key=lambda x: (x[0], x[1].entity_id)))
            self._alias_entities[k] = ordered

        self._alias_folded_entities: dict[str, tuple[CanonicalEntity, ...]] = {}
        for k, pairs in alias_folded_map.items():
            seen = {}
            for prio, ent in pairs:
                if ent.entity_id not in seen or prio < seen[ent.entity_id][0]:
                    seen[ent.entity_id] = (prio, ent)
            ordered = tuple(ent for _, ent in sorted(seen.values(), key=lambda x: (x[0], x[1].entity_id)))
            self._alias_folded_entities[k] = ordered

        # Pronunciation indexes
        prons_by_entity: dict[str, list[PronunciationVariant]] = defaultdict(list)
        prons_by_key: dict[str, list[PronunciationVariant]] = defaultdict(list)
        for pr in snapshot.pronunciations:
            prons_by_entity[pr.canonical_entity_id].append(pr)
            prons_by_key[pr.surface_key].append(pr)
        self._prons_by_entity: dict[str, tuple[PronunciationVariant, ...]] = {
            k: tuple(sorted(v, key=lambda p: (p.priority, p.profile, p.variant_id)))
            for k, v in prons_by_entity.items()
        }
        self._prons_by_key: dict[str, tuple[PronunciationVariant, ...]] = {
            k: tuple(sorted(v, key=lambda p: (p.priority, p.profile, p.variant_id)))
            for k, v in prons_by_key.items()
        }

        # Technical term indexes
        terms_by_key: dict[str, list[TechnicalTerm]] = defaultdict(list)
        for tm in snapshot.technical_terms:
            terms_by_key[tm.normalized_key].append(tm)
            for al in tm.aliases:
                terms_by_key[normalize_matching_key(al)].append(tm)
        self._terms_by_key: dict[str, tuple[TechnicalTerm, ...]] = {
            k: tuple(sorted(v, key=lambda t: (t.priority, t.term_id)))
            for k, v in terms_by_key.items()
        }

        self._max_tokens = min(max_tokens, 8)
        self._fuzzy_single_keys: tuple[str, ...] = tuple(
            sorted(
                k
                for k in set(self._exact_entities.keys()) | set(self._alias_entities.keys())
                if " " not in k and len(k) >= 5 and k not in _UNSAFE_STANDALONE_KEYS and k.replace("-", "").isalpha()
            )
        )

    @classmethod
    def from_snapshot(cls, snapshot: LexiconSnapshot) -> "LexiconRegistry":
        return cls(snapshot)

    @classmethod
    def from_default_sources(cls) -> "LexiconRegistry":
        return cls(load_lexicon_snapshot())

    @property
    def snapshot(self) -> LexiconSnapshot:
        return self._snapshot

    @property
    def lexicon_revision(self) -> str:
        return self._snapshot.lexicon_revision

    def get_entity(self, entity_id: str) -> CanonicalEntity | None:
        return self._entity_by_id.get(entity_id)

    def get_pronunciations_for_entity(
        self, entity_id: str, *, profile: str | None = None
    ) -> tuple[PronunciationVariant, ...]:
        variants = self._prons_by_entity.get(entity_id, ())
        if profile is None:
            return variants
        return tuple(v for v in variants if v.profile == profile)

    def get_pronunciations_for_key(
        self, surface_key: str, *, profile: str | None = None
    ) -> tuple[PronunciationVariant, ...]:
        key = normalize_matching_key(surface_key)
        variants = self._prons_by_key.get(key, ())
        if profile is None:
            return variants
        return tuple(v for v in variants if v.profile == profile)

    def get_technical_terms(self, key_or_alias: str) -> tuple[TechnicalTerm, ...]:
        return self._terms_by_key.get(normalize_matching_key(key_or_alias), ())

    def _resolve_key(
        self,
        key: str,
        *,
        token_count: int,
        allow_fuzzy: bool = False,
    ) -> tuple[tuple[CanonicalEntity, ...], MatchKind, float] | None:
        if not key:
            return None
        if token_count == 1 and key in _UNSAFE_STANDALONE_KEYS:
            return None

        # 1. Exact canonical key
        exact = self._exact_entities.get(key)
        if exact:
            kind = MatchKind.AMBIGUOUS if len(exact) > 1 else MatchKind.EXACT
            score = 0.5 if len(exact) > 1 else 1.0
            return exact, kind, score

        # 2. Exact alias key
        aliased = self._alias_entities.get(key)
        if aliased:
            kind = MatchKind.AMBIGUOUS if len(aliased) > 1 else MatchKind.ALIAS
            score = 0.5 if len(aliased) > 1 else 0.95
            return aliased, kind, score

        # 3. Foreign diacritic folded match (preserving Turkish letters)
        folded = fold_foreign_diacritics(key)
        if folded != key:
            if token_count == 1 and folded in _UNSAFE_STANDALONE_KEYS:
                return None
            f_exact = self._exact_entities.get(folded) or self._folded_entities.get(folded)
            if f_exact:
                kind = MatchKind.AMBIGUOUS if len(f_exact) > 1 else MatchKind.ALIAS
                score = 0.5 if len(f_exact) > 1 else 0.92
                return f_exact, kind, score
            f_alias = self._alias_entities.get(folded) or self._alias_folded_entities.get(folded)
            if f_alias:
                kind = MatchKind.AMBIGUOUS if len(f_alias) > 1 else MatchKind.ALIAS
                score = 0.5 if len(f_alias) > 1 else 0.90
                return f_alias, kind, score
        else:
            f_exact = self._folded_entities.get(key)
            if f_exact:
                kind = MatchKind.AMBIGUOUS if len(f_exact) > 1 else MatchKind.ALIAS
                score = 0.5 if len(f_exact) > 1 else 0.92
                return f_exact, kind, score
            f_alias = self._alias_folded_entities.get(key)
            if f_alias:
                kind = MatchKind.AMBIGUOUS if len(f_alias) > 1 else MatchKind.ALIAS
                score = 0.5 if len(f_alias) > 1 else 0.90
                return f_alias, kind, score

        # 4. Bounded edit-distance=1 fuzzy match (only when explicitly enabled, non-protected, single alpha token >= 5)
        if allow_fuzzy and token_count == 1 and len(key) >= 5 and key.replace("-", "").isalpha():
            fuzzy_entities: dict[str, CanonicalEntity] = {}
            for cand_key in self._fuzzy_single_keys:
                if _edit_distance_at_most_one(key, cand_key):
                    for ent in self._exact_entities.get(cand_key, ()) or self._alias_entities.get(cand_key, ()):
                        fuzzy_entities[ent.entity_id] = ent
            if fuzzy_entities:
                ordered = tuple(sorted(fuzzy_entities.values(), key=lambda e: (e.priority, e.entity_id)))
                kind = MatchKind.AMBIGUOUS if len(ordered) > 1 else MatchKind.FUZZY
                score = 0.45 if len(ordered) > 1 else 0.75
                return ordered, kind, score

        return None

    def _match_token_window(
        self,
        tokens: tuple[AlignedToken, ...],
        start_idx: int,
        length: int,
        protected_spans: tuple[ProtectedSpan, ...],
        *,
        allow_fuzzy: bool,
    ) -> tuple[tuple[CanonicalEntity, ...], MatchKind, float, str] | None:
        window = tokens[start_idx : start_idx + length]
        span = UnicodeSpan(
            start=window[0].raw_span.start,
            end_exclusive=window[-1].raw_span.end_exclusive,
            representation="RAW",
        )

        # Protect plates, VINs, and phones completely from entity/alias extraction
        for p in protected_spans:
            if p.kind in {ProtectedSpanKind.PLATE, ProtectedSpanKind.VIN, ProtectedSpanKind.PHONE}:
                if _spans_overlap(span, p.span):
                    return None

        # Protect standalone numbers and DTCs from fuzzy rewrite and standalone model false positives
        if length == 1:
            for p in protected_spans:
                if p.kind == ProtectedSpanKind.NUMBER and _spans_overlap(span, p.span):
                    return None
                if p.kind == ProtectedSpanKind.DTC and _spans_overlap(span, p.span):
                    # Exact DTC matches only if explicitly registered without fuzzy rewrite
                    exact_dtc = self._exact_entities.get(window[0].normalized)
                    if exact_dtc and all(e.category == EntityCategory.DTC for e in exact_dtc):
                        kind = MatchKind.AMBIGUOUS if len(exact_dtc) > 1 else MatchKind.EXACT
                        return exact_dtc, kind, (0.5 if len(exact_dtc) > 1 else 1.0), window[0].normalized
                    return None

        # If any internal token is a protected NUMBER, allow only exact multi-token match (never fuzzy)
        has_protected_overlap = any(_spans_overlap(span, p.span) for p in protected_spans)
        effective_fuzzy = allow_fuzzy and not has_protected_overlap

        phrase_key = " ".join(t.normalized for t in window)
        direct = self._resolve_key(phrase_key, token_count=length, allow_fuzzy=effective_fuzzy)
        if direct is not None:
            ents, kind, score = direct
            return ents, kind, score, phrase_key

        # Try stripping Turkish apostrophe inflection suffix on the trailing token (e.g. "Nissan Qashqai'ye")
        last_norm = window[-1].normalized
        if "'" in last_norm:
            stem, suffix = last_norm.split("'", 1)
            if stem and (not suffix or _TURKISH_APOSTROPHE_SUFFIX_RE.fullmatch(suffix)):
                inflected_key = " ".join([*(t.normalized for t in window[:-1]), stem])
                inflected = self._resolve_key(inflected_key, token_count=length, allow_fuzzy=False)
                if inflected is not None:
                    ents, kind, score = inflected
                    out_kind = MatchKind.AMBIGUOUS if len(ents) > 1 else MatchKind.INFLECTED
                    out_score = score if out_kind == MatchKind.AMBIGUOUS else min(score, 0.90)
                    return ents, out_kind, out_score, inflected_key

        return None

    def lookup_text(
        self,
        raw_text: str,
        *,
        max_candidates: int = 5,
        allow_fuzzy: bool = False,
    ) -> LookupResult:
        """Performs greedy longest multi-token lookup preserving raw text and exact codepoint spans."""
        if not isinstance(raw_text, str):
            raise TypeError("raw_text must be str")
        if max_candidates < 1 or max_candidates > 100:
            raise ValueError("max_candidates must be in [1, 100]")

        text_map = normalize_with_spans(raw_text)
        tokens = tokenize_aligned(text_map)
        protected_spans = detect_protected_spans(raw_text)

        matches: list[LookupMatch] = []
        i = 0
        n_tok = len(tokens)
        while i < n_tok:
            matched_step = False
            max_w = min(self._max_tokens, n_tok - i)
            for length in range(max_w, 0, -1):
                res = self._match_token_window(
                    tokens,
                    i,
                    length,
                    protected_spans,
                    allow_fuzzy=allow_fuzzy,
                )
                if res is not None:
                    ents, kind, score, matched_key = res
                    bounded_ents = ents[:max_candidates]
                    is_ambig = len(ents) > 1 or kind == MatchKind.AMBIGUOUS
                    span = UnicodeSpan(
                        start=tokens[i].raw_span.start,
                        end_exclusive=tokens[i + length - 1].raw_span.end_exclusive,
                        representation="RAW",
                    )
                    matches.append(
                        LookupMatch(
                            raw_text=raw_text[span.start:span.end_exclusive],
                            span=span,
                            matched_key=matched_key,
                            match_kind=MatchKind.AMBIGUOUS if is_ambig else kind,
                            candidates=bounded_ents,
                            selected_entity=None if is_ambig else bounded_ents[0],
                            score=score,
                            ambiguous=is_ambig,
                        )
                    )
                    i += length
                    matched_step = True
                    break
            if not matched_step:
                i += 1

        # Aggregate bounded unique candidates across matches
        agg_cands: list[CanonicalEntity] = []
        seen_ids: set[str] = set()
        for m in matches:
            for c in m.candidates:
                if c.entity_id not in seen_ids:
                    seen_ids.add(c.entity_id)
                    agg_cands.append(c)
                    if len(agg_cands) >= max_candidates:
                        break
            if len(agg_cands) >= max_candidates:
                break

        any_ambiguous = any(m.ambiguous for m in matches)
        if any_ambiguous:
            status = LookupStatus.AMBIGUOUS
        elif matches:
            status = LookupStatus.MATCHED
        elif protected_spans:
            status = LookupStatus.PROTECTED
        else:
            status = LookupStatus.NOT_FOUND

        return LookupResult(
            raw_text=raw_text,
            normalized_text=text_map.normalized_text,
            status=status,
            lexicon_revision=self.lexicon_revision,
            matches=tuple(matches),
            protected_spans=protected_spans,
            candidates=tuple(agg_cands),
            ambiguous=any_ambiguous,
            bounded_limit=max_candidates,
        )

    def lookup_term(
        self,
        term: str,
        *,
        max_candidates: int = 5,
        allow_fuzzy: bool = False,
    ) -> LookupResult:
        """Convenience lookup for a single term or phrase."""
        return self.lookup_text(term, max_candidates=max_candidates, allow_fuzzy=allow_fuzzy)
