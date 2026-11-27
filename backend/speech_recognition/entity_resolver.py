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
from enum import StrEnum

from backend.core.contracts.recognition import (
    CatalogStatus,
    ConfirmationStatus,
    EntityCandidate,
    UnicodeSpan,
)
from backend.shared_lexicon.asr_adapter import extract_asr_candidates
from backend.shared_lexicon.contracts import EntityCategory, MatchKind
from backend.shared_lexicon.unicode_normalizer import (
    fold_foreign_diacritics,
    normalize_matching_key,
    normalize_with_spans,
    tokenize_aligned,
)
from backend.speech_recognition.hotword_planner import ContextHintSnapshot
from backend.speech_recognition.lexicon_adapter import PinnedLexiconSnapshot
from backend.speech_recognition.protected_spans import (
    ProtectedCategory,
    ProtectedSpanScanResult,
    scan_protected_spans,
)

SCORER_REVISION = "f2b_tr_ranker_v1"
DEFAULT_MAX_RAW_CHARS = 4096
DEFAULT_MAX_ELIGIBLE_SPANS = 32
DEFAULT_MAX_PHONETIC_POOL = 128
DEFAULT_APPROX_SCORE_MIN = 0.88
DEFAULT_APPROX_MARGIN_MIN = 0.15

_TURKISH_PHONETIC_SUBS = (
    ("kaşkay", "qashqai"),
    ("kaş kay", "qashqai"),
    ("pejo", "peugeot"),
    ("pöjo", "peugeot"),
    ("sitroyen", "citroen"),
    ("reno", "renault"),
    ("folksvagen", "volkswagen"),
    ("volksvagen", "volkswagen"),
    ("şevrole", "chevrolet"),
    ("hunday", "hyundai"),
    ("hyunday", "hyundai"),
    ("nişan", "nissan"),
)


class EvidenceTier(StrEnum):
    EXACT_CANONICAL = "EXACT_CANONICAL"
    REVIEWED_EXACT_ALIAS = "REVIEWED_EXACT_ALIAS"
    REVIEWED_INFLECTED_ALIAS = "REVIEWED_INFLECTED_ALIAS"
    ELIGIBLE_PHONETIC = "ELIGIBLE_PHONETIC"


class CorrectionDecisionKind(StrEnum):
    KEEP = "KEEP"
    PROPOSE = "PROPOSE"
    CANONICALIZE_CANDIDATE = "CANONICALIZE_CANDIDATE"
    CLARIFY = "CLARIFY"
    REJECT = "REJECT"


class ClarificationReason(StrEnum):
    NONE = "NONE"
    AMBIGUOUS_MODEL = "AMBIGUOUS_MODEL"
    UNVERIFIED_ALIAS = "UNVERIFIED_ALIAS"
    PROTECTED_IDENTIFIER_UNCERTAIN = "PROTECTED_IDENTIFIER_UNCERTAIN"
    CONFLICTING_CONTEXT = "CONFLICTING_CONTEXT"
    LOW_ACOUSTIC_EVIDENCE = "LOW_ACOUSTIC_EVIDENCE"
    INCOMPLETE_SEARCH = "INCOMPLETE_SEARCH"
    DECODER_DISAGREEMENT = "DECODER_DISAGREEMENT"


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    """Bounded deterministic candidate evidence without catalog/confirmation inflation."""

    entity_id: str
    entity_type: str
    raw_value: str
    canonical_value: str | None
    source_span: UnicodeSpan
    evidence_tier: EvidenceTier
    ranking_score: float
    lexical_similarity: float
    phonetic_similarity: float | None
    context_support: float | None
    margin: float | None
    alternatives: tuple[str, ...]
    ambiguous: bool
    protected_compatible: bool
    scorer_revision: str = SCORER_REVISION
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CorrectionDecision:
    """Guarded decision record for a single non-overlapping span."""

    span: UnicodeSpan
    original_raw: str
    candidate_entity_id: str | None
    decision: CorrectionDecisionKind
    reason_codes: tuple[str, ...]
    rule_revision: str = SCORER_REVISION
    protected_invariants_ok: bool = True


@dataclass(frozen=True, slots=True)
class ClarificationHint:
    """Read-only F3 clarification metadata; never writes slots or asserts confirmation."""

    utterance_id: str
    final_revision: int
    context_revision_used: int | None
    candidate_ids: tuple[str, ...]
    slot_category: str | None
    reason: ClarificationReason
    required: bool
    preserving_raw: bool = True


@dataclass(frozen=True, slots=True)
class EntityResolutionReport:
    """Complete F2-B resolution output preserving raw_transcript immutability."""

    normalized_transcript: str
    canonical_transcript: str | None
    candidates: tuple[EntityCandidate, ...]
    ranked_candidates: tuple[RankedCandidate, ...]
    decisions: tuple[CorrectionDecision, ...]
    clarification_hint: ClarificationHint | None
    protected_scan: ProtectedSpanScanResult
    truncated: bool = False
    context_contradiction: bool = False


def _turkish_phonetic_key(text: str) -> str:
    key = fold_foreign_diacritics(normalize_matching_key(text))
    for src, dst in _TURKISH_PHONETIC_SUBS:
        if key == src:
            key = dst
            break
    # Conservative Turkish consonant/vowel folding for phonetic comparison only
    key = re.sub(r"ğ", "g", key)
    key = re.sub(r"ş", "sh", key)
    key = re.sub(r"ç", "ch", key)
    key = re.sub(r"qu|q", "k", key)
    key = re.sub(r"w", "v", key)
    key = re.sub(r"x", "ks", key)
    key = re.sub(r"ph", "f", key)
    return key


def _normalized_levenshtein(a: str, b: str) -> float:
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0.0
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    dist = prev[lb]
    return max(0.0, 1.0 - (dist / float(max(la, lb))))


def _has_contrast_near_span(scan: ProtectedSpanScanResult, span: UnicodeSpan, window_chars: int = 24) -> bool:
    for neg in scan.negation_spans:
        if abs(neg.span.start - span.end_exclusive) <= window_chars or abs(span.start - neg.span.end_exclusive) <= window_chars:
            if neg.deterministic_value in {"değil", "hayır", "başka"}:
                return True
    return False


def resolve_automotive_entities(
    *,
    utterance_id: str,
    raw_transcript: str,
    pinned_lexicon: PinnedLexiconSnapshot,
    context_hint: ContextHintSnapshot | None = None,
    projection_policy: str = "candidate_only",
    final_revision: int = 0,
    max_candidates: int = 5,
    low_acoustic_evidence: bool = False,
) -> EntityResolutionReport:
    """
    Run bounded F2-B protected span scanning, M05 exact/alias/inflected lookup,
    Turkish phonetic candidate ranking, and false-correction guarding.
    """
    protected_scan = scan_protected_spans(raw_transcript)
    norm_map = normalize_with_spans(raw_transcript)
    normalized_text = norm_map.normalized_text

    if not raw_transcript.strip() or not pinned_lexicon.available or pinned_lexicon.registry is None:
        return EntityResolutionReport(
            normalized_transcript=normalized_text,
            canonical_transcript=None,
            candidates=(),
            ranked_candidates=(),
            decisions=(),
            clarification_hint=None,
            protected_scan=protected_scan,
            truncated=False,
        )

    truncated = len(raw_transcript) > DEFAULT_MAX_RAW_CHARS
    bounded_raw = raw_transcript[:DEFAULT_MAX_RAW_CHARS] if truncated else raw_transcript
    registry = pinned_lexicon.registry

    # 1. Authoritative M05 exact/alias/inflected extraction (no fuzzy mutation)
    extraction = extract_asr_candidates(
        registry,
        bounded_raw,
        max_candidates=max_candidates,
        allow_fuzzy=False,
    )

    ranked: list[RankedCandidate] = []
    decisions: list[CorrectionDecision] = []
    final_candidates: list[EntityCandidate] = []
    occupied_spans: list[UnicodeSpan] = []

    ctx_entity_ids = set(context_hint.allowed_entity_ids) | set(context_hint.confirmed_entity_ids) if context_hint else set()
    context_contradiction = False
    clarify_reasons: list[ClarificationReason] = []
    clarify_ids: list[str] = []

    for cand in extraction.candidates:
        if cand.source_span is None:
            continue
        span = cand.source_span
        if protected_scan.overlaps_hard_identifier(span):
            decisions.append(
                CorrectionDecision(
                    span=span,
                    original_raw=cand.raw_value,
                    candidate_entity_id=cand.entity_id,
                    decision=CorrectionDecisionKind.KEEP,
                    reason_codes=("protected_identifier_overlap",),
                )
            )
            continue

        occupied_spans.append(span)
        ambiguous = cand.canonical_value is None or len(cand.alternatives) > 1
        match_key = normalize_matching_key(cand.raw_value)
        ent = registry.get_entity(cand.entity_id) if not ambiguous else None
        if ent is not None and ent.normalized_key == match_key:
            tier = EvidenceTier.EXACT_CANONICAL
        elif "'" in cand.raw_value or "’" in cand.raw_value:
            tier = EvidenceTier.REVIEWED_INFLECTED_ALIAS
        else:
            tier = EvidenceTier.REVIEWED_EXACT_ALIAS

        ctx_sup = 1.0 if (context_hint and cand.entity_id in ctx_entity_ids) else (0.0 if context_hint else None)
        if context_hint and ctx_entity_ids and cand.entity_id not in ctx_entity_ids and _has_contrast_near_span(protected_scan, span):
            context_contradiction = True
            clarify_reasons.append(ClarificationReason.CONFLICTING_CONTEXT)

        r_cand = RankedCandidate(
            entity_id=cand.entity_id,
            entity_type=cand.entity_type,
            raw_value=cand.raw_value,
            canonical_value=cand.canonical_value,
            source_span=span,
            evidence_tier=tier,
            ranking_score=cand.score if cand.score is not None else 1.0,
            lexical_similarity=cand.score if cand.score is not None else 1.0,
            phonetic_similarity=None,
            context_support=ctx_sup,
            margin=None,
            alternatives=cand.alternatives,
            ambiguous=ambiguous,
            protected_compatible=True,
            reason_codes=("ambiguous_match",) if ambiguous else ("reviewed_m05_match",),
        )
        ranked.append(r_cand)
        final_candidates.append(cand)

        if ambiguous:
            clarify_reasons.append(ClarificationReason.AMBIGUOUS_MODEL)
            clarify_ids.append(cand.entity_id)
            decisions.append(
                CorrectionDecision(
                    span=span,
                    original_raw=cand.raw_value,
                    candidate_entity_id=cand.entity_id,
                    decision=CorrectionDecisionKind.CLARIFY,
                    reason_codes=("ambiguous_candidates",),
                )
            )
        elif projection_policy == "reviewed_canonical_projection" and not context_contradiction:
            decisions.append(
                CorrectionDecision(
                    span=span,
                    original_raw=cand.raw_value,
                    candidate_entity_id=cand.entity_id,
                    decision=CorrectionDecisionKind.CANONICALIZE_CANDIDATE,
                    reason_codes=("reviewed_projection_permitted",),
                )
            )
        else:
            decisions.append(
                CorrectionDecision(
                    span=span,
                    original_raw=cand.raw_value,
                    candidate_entity_id=cand.entity_id,
                    decision=CorrectionDecisionKind.PROPOSE if tier != EvidenceTier.EXACT_CANONICAL else CorrectionDecisionKind.KEEP,
                    reason_codes=("candidate_only_mode",),
                )
            )

    # 2. Bounded Turkish phonetic candidate lookup on eligible unmatched spans
    bounded_map = norm_map if not truncated else normalize_with_spans(bounded_raw)
    tokens = tokenize_aligned(bounded_map)
    pool_entities = [
        e
        for e in sorted(registry.snapshot.entities, key=lambda x: (x.priority, x.entity_id))
        if e.category in {EntityCategory.BRAND, EntityCategory.MODEL}
    ][:DEFAULT_MAX_PHONETIC_POOL]

    examined_spans = 0
    for idx in range(len(tokens)):
        if examined_spans >= DEFAULT_MAX_ELIGIBLE_SPANS:
            truncated = True
            clarify_reasons.append(ClarificationReason.INCOMPLETE_SEARCH)
            break
        for width in (2, 1):
            if idx + width > len(tokens):
                continue
            window = tokens[idx : idx + width]
            span = UnicodeSpan(
                start=window[0].raw_span.start,
                end_exclusive=window[-1].raw_span.end_exclusive,
                representation="RAW",
            )
            if any(s.start < span.end_exclusive and span.start < s.end_exclusive for s in occupied_spans):
                continue
            if protected_scan.overlaps_protected(span):
                continue
            phrase_key = " ".join(t.normalized for t in window)
            if len(phrase_key) < 4:
                continue
            examined_spans += 1
            phon_query = _turkish_phonetic_key(phrase_key)
            lex_query = fold_foreign_diacritics(phrase_key)

            scored_pool: list[tuple[float, float, float, float | None, str, str, str]] = []
            for ent in pool_entities:
                ent_lex = fold_foreign_diacritics(ent.normalized_key)
                ent_phon = _turkish_phonetic_key(ent.normalized_key)
                lex_sim = _normalized_levenshtein(lex_query, ent_lex)
                phon_sim = _normalized_levenshtein(phon_query, ent_phon)
                ctx_sup = (1.0 if ent.entity_id in ctx_entity_ids else 0.0) if context_hint else None
                if ctx_sup is not None:
                    total = 0.50 * lex_sim + 0.35 * phon_sim + 0.15 * ctx_sup
                else:
                    total = 0.50 * lex_sim + 0.50 * phon_sim
                if phon_query == ent_phon:
                    total = max(total, 0.90)
                if phon_sim >= 0.80 or total >= 0.80:
                    scored_pool.append((total, lex_sim, phon_sim, ctx_sup, ent.entity_id, ent.category.value, ent.canonical_name))

            if not scored_pool:
                continue
            scored_pool.sort(key=lambda x: (-x[0], x[4]))
            best = scored_pool[0]
            runner_up = scored_pool[1] if len(scored_pool) > 1 else None
            margin = (best[0] - runner_up[0]) if runner_up is not None else None

            if best[0] >= DEFAULT_APPROX_SCORE_MIN and (margin is None or margin >= DEFAULT_APPROX_MARGIN_MIN):
                occupied_spans.append(span)
                raw_val = bounded_raw[span.start : span.end_exclusive]
                ec = EntityCandidate(
                    entity_id=best[4],
                    entity_type=best[5],
                    raw_value=raw_val,
                    canonical_value=best[6],
                    source_span=span,
                    score=round(best[0], 4),
                    score_kind="RANKING_SCORE",
                    scorer_revision=SCORER_REVISION,
                    alternatives=tuple(s[6] for s in scored_pool[:3] if s[4] != best[4]),
                    catalog_status=CatalogStatus.UNVERIFIED,
                    confirmation_status=ConfirmationStatus.CANDIDATE,
                )
                final_candidates.append(ec)
                ranked.append(
                    RankedCandidate(
                        entity_id=best[4],
                        entity_type=best[5],
                        raw_value=raw_val,
                        canonical_value=best[6],
                        source_span=span,
                        evidence_tier=EvidenceTier.ELIGIBLE_PHONETIC,
                        ranking_score=round(best[0], 4),
                        lexical_similarity=round(best[1], 4),
                        phonetic_similarity=round(best[2], 4),
                        context_support=best[3],
                        margin=round(margin, 4) if margin is not None else None,
                        alternatives=ec.alternatives,
                        ambiguous=False,
                        protected_compatible=True,
                        reason_codes=("phonetic_candidate_only",),
                    )
                )
                decisions.append(
                    CorrectionDecision(
                        span=span,
                        original_raw=raw_val,
                        candidate_entity_id=best[4],
                        decision=CorrectionDecisionKind.PROPOSE,
                        reason_codes=("approximate_never_auto_canonicalizes",),
                    )
                )
                clarify_reasons.append(ClarificationReason.UNVERIFIED_ALIAS)
                clarify_ids.append(best[4])
                break

    # 3. Optional guarded canonical projection (only if explicitly enabled and all invariants hold)
    canonical_transcript: str | None = None
    if (
        projection_policy == "reviewed_canonical_projection"
        and not truncated
        and not context_contradiction
        and not any(d.decision == CorrectionDecisionKind.CLARIFY for d in decisions)
    ):
        edits = sorted(
            [
                (d.span.start, d.span.end_exclusive, rc.canonical_value)
                for d, rc in zip(decisions, ranked)
                if d.decision == CorrectionDecisionKind.CANONICALIZE_CANDIDATE and rc.canonical_value is not None
            ],
            key=lambda x: (x[0], x[1]),
        )
        if edits:
            parts: list[str] = []
            cursor = 0
            overlap_err = False
            for s_idx, e_idx, repl in edits:
                if s_idx < cursor:
                    overlap_err = True
                    break
                parts.append(raw_transcript[cursor:s_idx])
                parts.append(repl)
                cursor = e_idx
            if not overlap_err:
                parts.append(raw_transcript[cursor:])
                canonical_transcript = "".join(parts)

    if low_acoustic_evidence:
        clarify_reasons.append(ClarificationReason.LOW_ACOUSTIC_EVIDENCE)

    clarification_hint: ClarificationHint | None = None
    if clarify_reasons:
        clarification_hint = ClarificationHint(
            utterance_id=utterance_id,
            final_revision=final_revision,
            context_revision_used=context_hint.state_revision if context_hint is not None else None,
            candidate_ids=tuple(dict.fromkeys(clarify_ids)),
            slot_category=ranked[0].entity_type if ranked else None,
            reason=clarify_reasons[0],
            required=True,
        )

    final_candidates.sort(key=lambda c: (c.source_span.start if c.source_span else 0, c.entity_id))
    return EntityResolutionReport(
        normalized_transcript=normalized_text,
        canonical_transcript=canonical_transcript,
        candidates=tuple(final_candidates),
        ranked_candidates=tuple(ranked),
        decisions=tuple(decisions),
        clarification_hint=clarification_hint,
        protected_scan=protected_scan,
        truncated=truncated,
        context_contradiction=context_contradiction,
    )
