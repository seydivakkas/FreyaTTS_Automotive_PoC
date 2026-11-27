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
from dataclasses import dataclass
from typing import Sequence

from backend.core.contracts.validation import freeze_value, require_safe_id, require_strict_int
from backend.observability.projection import contains_sentinel
from backend.shared_lexicon.contracts import EntityCategory
from backend.shared_lexicon.unicode_normalizer import normalize_matching_key
from backend.speech_recognition.lexicon_adapter import PinnedLexiconSnapshot

DEFAULT_MAX_HOTWORD_ITEMS = 50
DEFAULT_MAX_HOTWORD_CHARS = 512
DEFAULT_MAX_HOTWORD_TOKENS = 128
DEFAULT_MAX_HOTWORD_TERM_CHARS = 64
DEFAULT_MAX_CONTEXT_IDS = 12
DEFAULT_CONTEXT_MAX_AGE_MS = 60_000

_CONTROL_OR_INJECTION_RE = re.compile(r"[\r\n\t\x00-\x1f\x7f;]|<\|.*?\|>|```")
_UNSAFE_SHORT_TURKISH = frozenset({
    "ve", "de", "da", "mi", "mı", "mu", "mü", "bir", "bu", "şu", "o", "ne", "var", "yok",
    "ara", "al", "ol", "et", "at", "evet", "hayır", "değil", "nisan", "cam", "far", "yol",
})


@dataclass(frozen=True, slots=True)
class ContextHintSnapshot:
    """
    Bounded, read-only projection of F3-A's prior committed dialogue state.

    Never carries raw CRM rows, customer names, plates, VINs, phones, or secrets.
    """

    session_id: str
    incarnation_id: str
    state_revision: int
    source_turn_id: int
    captured_monotonic_ns: int
    clock_domain: str
    lexicon_revision: str | None = None
    intent_category: str | None = None
    allowed_entity_ids: tuple[str, ...] = ()
    confirmed_entity_ids: tuple[str, ...] = ()
    service_categories: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_safe_id(self.session_id, "session_id")
        require_safe_id(self.incarnation_id, "incarnation_id")
        require_strict_int(self.state_revision, "state_revision", minimum=0)
        require_strict_int(self.source_turn_id, "source_turn_id", minimum=0)
        require_strict_int(self.captured_monotonic_ns, "captured_monotonic_ns", minimum=0)
        if not isinstance(self.clock_domain, str) or not self.clock_domain.strip():
            raise ValueError("clock_domain required")
        if len(self.allowed_entity_ids) > DEFAULT_MAX_CONTEXT_IDS:
            raise ValueError(f"allowed_entity_ids exceeds max {DEFAULT_MAX_CONTEXT_IDS}")
        if len(self.confirmed_entity_ids) > DEFAULT_MAX_CONTEXT_IDS:
            raise ValueError(f"confirmed_entity_ids exceeds max {DEFAULT_MAX_CONTEXT_IDS}")
        for eid in (*self.allowed_entity_ids, *self.confirmed_entity_ids):
            require_safe_id(eid, "entity_id")
        for cat in self.service_categories:
            if contains_sentinel(cat):
                raise ValueError("PII sentinel forbidden in ContextHintSnapshot")
        object.__setattr__(self, "allowed_entity_ids", freeze_value(tuple(self.allowed_entity_ids)))
        object.__setattr__(self, "confirmed_entity_ids", freeze_value(tuple(self.confirmed_entity_ids)))
        object.__setattr__(self, "service_categories", freeze_value(tuple(self.service_categories)))

    def __repr__(self) -> str:
        return (
            f"ContextHintSnapshot(session={self.session_id!r}, rev={self.state_revision}, "
            f"turn={self.source_turn_id}, confirmed={len(self.confirmed_entity_ids)})"
        )


@dataclass(frozen=True, slots=True)
class HotwordPlan:
    """Immutable per-attempt hotword selection with explicit budget and provenance."""

    scope_id: str
    context_revision: int | None
    lexicon_revision: str | None
    profile_name: str
    selected_entity_ids: tuple[str, ...]
    terms: tuple[str, ...]
    hotwords_text: str | None
    char_count: int
    token_count: int
    truncated: bool
    dropped_count: int
    dropped_reason: str | None = None
    context_used: bool = False
    fallback_reason: str | None = None

    def __repr__(self) -> str:
        return (
            f"HotwordPlan(profile={self.profile_name!r}, count={len(self.terms)}, "
            f"chars={self.char_count}, context_used={self.context_used}, "
            f"truncated={self.truncated}, fallback={self.fallback_reason!r})"
        )


def _is_provider_safe_term(term: str, *, max_term_chars: int = DEFAULT_MAX_HOTWORD_TERM_CHARS) -> bool:
    if not isinstance(term, str):
        return False
    cleaned = term.strip()
    if not cleaned or len(cleaned) > max_term_chars:
        return False
    if _CONTROL_OR_INJECTION_RE.search(cleaned):
        return False
    if contains_sentinel(cleaned):
        return False
    key = normalize_matching_key(cleaned)
    if not key:
        return False
    if " " not in key and (len(key) < 2 or key in _UNSAFE_SHORT_TURKISH):
        return False
    return True


def _validate_context_freshness(
    context_hint: ContextHintSnapshot | None,
    *,
    session_id: str,
    incarnation_id: str,
    lexicon_revision: str | None,
    now_monotonic_ns: int,
    clock_domain: str,
    max_age_ms: int,
) -> tuple[bool, str | None]:
    if context_hint is None:
        return False, "no_context_hint"
    if context_hint.session_id != session_id or context_hint.incarnation_id != incarnation_id:
        return False, "context_scope_mismatch"
    if context_hint.clock_domain != clock_domain:
        return False, "context_clock_domain_mismatch"
    age_ns = now_monotonic_ns - context_hint.captured_monotonic_ns
    if age_ns < 0 or age_ns > max_age_ms * 1_000_000:
        return False, "context_hint_expired"
    if (
        lexicon_revision is not None
        and context_hint.lexicon_revision is not None
        and context_hint.lexicon_revision != lexicon_revision
    ):
        return False, "context_lexicon_revision_mismatch"
    return True, None


class HotwordPlanner:
    """
    Deterministic F2-B hotword planner sourcing active M05 entities and bounded
    F3-A prior context under strict item, character, and token budgets.
    """

    def __init__(
        self,
        *,
        max_items: int = DEFAULT_MAX_HOTWORD_ITEMS,
        max_chars: int = DEFAULT_MAX_HOTWORD_CHARS,
        max_tokens: int = DEFAULT_MAX_HOTWORD_TOKENS,
        max_term_chars: int = DEFAULT_MAX_HOTWORD_TERM_CHARS,
        context_max_age_ms: int = DEFAULT_CONTEXT_MAX_AGE_MS,
    ) -> None:
        require_strict_int(max_items, "max_items", minimum=0, maximum=200)
        require_strict_int(max_chars, "max_chars", minimum=0, maximum=4096)
        require_strict_int(max_tokens, "max_tokens", minimum=0, maximum=1024)
        require_strict_int(max_term_chars, "max_term_chars", minimum=4, maximum=256)
        require_strict_int(context_max_age_ms, "context_max_age_ms", minimum=1, maximum=3_600_000)
        self.max_items = max_items
        self.max_chars = max_chars
        self.max_tokens = max_tokens
        self.max_term_chars = max_term_chars
        self.context_max_age_ms = context_max_age_ms

    def plan(
        self,
        *,
        scope_id: str,
        session_id: str,
        incarnation_id: str,
        pinned_lexicon: PinnedLexiconSnapshot,
        now_monotonic_ns: int,
        clock_domain: str,
        context_hint: ContextHintSnapshot | None = None,
        baseline_terms: Sequence[str] = (),
        profile_name: str = "enhanced_candidate_only",
        disable_context_bias: bool = False,
    ) -> HotwordPlan:
        """Build an immutable HotwordPlan within strict budgets without leaking PII."""
        if not pinned_lexicon.available or pinned_lexicon.registry is None:
            return HotwordPlan(
                scope_id=scope_id,
                context_revision=None,
                lexicon_revision=pinned_lexicon.lexicon_revision,
                profile_name=profile_name,
                selected_entity_ids=(),
                terms=(),
                hotwords_text=None,
                char_count=0,
                token_count=0,
                truncated=False,
                dropped_count=len(baseline_terms),
                dropped_reason="lexicon_unavailable",
                context_used=False,
                fallback_reason="lexicon_snapshot_unavailable",
            )

        registry = pinned_lexicon.registry
        context_valid = False
        fallback_reason: str | None = None
        if disable_context_bias:
            fallback_reason = "context_bias_disabled_for_attempt"
        else:
            context_valid, fallback_reason = _validate_context_freshness(
                context_hint,
                session_id=session_id,
                incarnation_id=incarnation_id,
                lexicon_revision=pinned_lexicon.lexicon_revision,
                now_monotonic_ns=now_monotonic_ns,
                clock_domain=clock_domain,
                max_age_ms=self.context_max_age_ms,
            )

        ordered_candidates: list[tuple[str | None, str]] = []
        if context_valid and context_hint is not None:
            # Verified prior entities precede unverified candidate context entities
            for eid in context_hint.confirmed_entity_ids:
                ent = registry.get_entity(eid)
                if ent is not None and ent.category in {EntityCategory.BRAND, EntityCategory.MODEL, EntityCategory.TECHNICAL}:
                    ordered_candidates.append((ent.entity_id, ent.canonical_name))
            for eid in context_hint.allowed_entity_ids:
                if eid in context_hint.confirmed_entity_ids:
                    continue
                ent = registry.get_entity(eid)
                if ent is not None and ent.category in {EntityCategory.BRAND, EntityCategory.MODEL, EntityCategory.TECHNICAL}:
                    ordered_candidates.append((ent.entity_id, ent.canonical_name))
            for cat in context_hint.service_categories:
                ordered_candidates.append((None, cat))

        # Fill remaining capacity from active M05 entities (brands/models/technical) in deterministic priority order
        active_entities = sorted(
            registry.snapshot.entities,
            key=lambda e: (e.priority, e.entity_id),
        )
        for ent in active_entities:
            if ent.category in {EntityCategory.BRAND, EntityCategory.MODEL, EntityCategory.TECHNICAL}:
                ordered_candidates.append((ent.entity_id, ent.canonical_name))

        for term in baseline_terms:
            ordered_candidates.append((None, term))

        selected_terms: list[str] = []
        selected_ids: list[str] = []
        seen_keys: set[str] = set()
        seen_ids: set[str] = set()
        total_chars = 0
        total_tokens = 0
        dropped_count = 0
        truncated = False
        dropped_reason: str | None = None

        for eid, raw_term in ordered_candidates:
            if not _is_provider_safe_term(raw_term, max_term_chars=self.max_term_chars):
                dropped_count += 1
                continue
            cleaned = raw_term.strip()
            match_key = normalize_matching_key(cleaned)
            if match_key in seen_keys:
                continue

            sep_len = 2 if selected_terms else 0
            term_tokens = len(cleaned.split())
            if (
                len(selected_terms) >= self.max_items
                or (total_chars + sep_len + len(cleaned)) > self.max_chars
                or (total_tokens + term_tokens) > self.max_tokens
            ):
                truncated = True
                dropped_count += 1
                dropped_reason = "budget_limit_reached"
                break

            seen_keys.add(match_key)
            selected_terms.append(cleaned)
            total_chars += sep_len + len(cleaned)
            total_tokens += term_tokens
            if eid is not None and eid not in seen_ids:
                seen_ids.add(eid)
                selected_ids.append(eid)

        hotwords_text = ", ".join(selected_terms) if selected_terms else None
        return HotwordPlan(
            scope_id=scope_id,
            context_revision=context_hint.state_revision if (context_valid and context_hint is not None) else None,
            lexicon_revision=pinned_lexicon.lexicon_revision,
            profile_name=profile_name,
            selected_entity_ids=tuple(selected_ids),
            terms=tuple(selected_terms),
            hotwords_text=hotwords_text,
            char_count=total_chars,
            token_count=total_tokens,
            truncated=truncated,
            dropped_count=dropped_count,
            dropped_reason=dropped_reason,
            context_used=context_valid and not disable_context_bias,
            fallback_reason=fallback_reason if not context_valid else None,
        )
