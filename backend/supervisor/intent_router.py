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
import math
import re
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Awaitable, Callable, Mapping, Protocol

from backend.core.contracts.recognition import ASROutcome, ASRResult, ASRStatus
from backend.supervisor.catalogue import CATALOGUE
from backend.supervisor.contracts import (
    ConversationContext,
    Intent,
    IntentCandidate,
    IntentDecision,
    RouteState,
)
from backend.supervisor.policy import (
    BARE_DATE,
    CORRECTION,
    HANDOFF_DENIED,
    WRITE_DENIED,
    normalize_utterance,
    rule_decision,
)

MAX_ROUTE_ALTERNATIVES = 8
MAX_SUB_INTENTS = 4

_CONVERSATION_CANCEL_RE = re.compile(
    r"\b(?:görüşmeyi|konuşmayı|sohbeti|oturumu)\s+(?:iptal|sonlandır|bitir|kapat)\b|\bdur\b|\bsus\b",
    re.IGNORECASE,
)
_AFFIRMATIVE_EXACT_RE = re.compile(
    r"^\s*(?:evet(?:\s*,?\s*(?:onaylıyorum|tamam|olur))?|onaylıyorum|onay|tamam|uygun|kesinlikle|kabul\s+ediyorum)[.!?\s]*$",
    re.IGNORECASE,
)
_NEGATIVE_EXACT_RE = re.compile(
    r"\b(?:hayır|vazgeçtim|istemiyorum|onaylamıyorum|kalsın|olmaz)\b",
    re.IGNORECASE,
)
# Protected spans that must NEVER be split by conjunction/punctuation splitters.
_PROTECTED_SPAN_RE = re.compile(
    r"\b\d{2}\s*[A-ZÇĞİÖŞÜ]{1,3}\s*\d{2,4}\b"
    r"|\b20\d{2}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}\.\d{1,2}\.20\d{2}\b"
    r"|\b\d+[.,]\d+\b",
    re.IGNORECASE,
)
_CLAUSE_SPLIT_RE = re.compile(r"\s*(?:;|\bve\b|\bbir\s+de\b|\bayrıca\b|\bhem\s+de\b)\s*", re.IGNORECASE)

_LEVEL3_SERVICE_INTENTS: frozenset[Intent] = frozenset({
    Intent.BOOKING_CREATE,
    Intent.BOOKING_RESCHEDULE,
    Intent.BOOKING_CANCEL,
    Intent.BOOKING_STATUS,
})

_LEVEL4_SPECIALIST_INTENTS: frozenset[Intent] = frozenset({
    Intent.SERVICE_PRICE_ESTIMATE,
    Intent.WARNING_LIGHT_QUESTION,
    Intent.SYMPTOM_QUESTION,
    Intent.MAINTENANCE_SCHEDULE_QUESTION,
    Intent.VEHICLE_SPEC_QUESTION,
    Intent.MODEL_COMPARISON,
    Intent.VEHICLE_PRICE_QUOTE,
    Intent.TEST_DRIVE_REQUEST,
    Intent.PART_COMPATIBILITY,
    Intent.PART_AVAILABILITY,
    Intent.CUSTOMER_RECORD_QUESTION,
    Intent.COMPLAINT_CREATE,
})

_LEVEL5_GENERAL_INTENTS: frozenset[Intent] = frozenset({
    Intent.GREETING,
    Intent.GOODBYE,
    Intent.REPEAT_REQUEST,
    Intent.CLARIFICATION_REQUEST,
})


class RouteLevel(IntEnum):
    """Deterministic F3-B intent hierarchy levels (0..5)."""

    L0_INPUT_RECOVERY = 0
    L1_SAFETY_CONTROL = 1
    L2_ACTIVE_WORKFLOW = 2
    L3_SERVICE_BOOKING = 3
    L4_SPECIALIST_DOMAIN = 4
    L5_GENERAL_OR_AMBIGUOUS = 5


class RouteDisposition(StrEnum):
    """High-level routing disposition; never carries execution authority."""

    ROUTED = "ROUTED"
    CLARIFY = "CLARIFY"
    UNSUPPORTED = "UNSUPPORTED"
    RECOVERY = "RECOVERY"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class EffectClass(StrEnum):
    """Effect classification for sub-intent decomposition."""

    NO_TOOL = "NO_TOOL"
    READ = "READ"
    MUTATION = "MUTATION"
    CONTROL = "CONTROL"


@dataclass(frozen=True, slots=True)
class HierarchicalRouteDecision:
    """Immutable F3-B hierarchical routing result (zero authority)."""

    level: RouteLevel
    disposition: RouteDisposition
    primary_intent: Intent | None
    candidates: tuple[IntentCandidate, ...]
    source: str
    needs_clarification: bool
    reason_codes: tuple[str, ...]
    active_workflow_invalidated: bool = False
    classifier_used: bool = False
    llm_used: bool = False
    router_revision: str = "f3b-router-v1"
    has_authority: bool = False

    def __post_init__(self) -> None:
        if self.has_authority:
            raise ValueError("HierarchicalRouteDecision cannot grant authority")
        if len(self.candidates) > MAX_ROUTE_ALTERNATIVES:
            raise ValueError(f"candidates exceeds max {MAX_ROUTE_ALTERNATIVES}")


@dataclass(frozen=True, slots=True)
class SubIntent:
    """Bounded candidate sub-intent with exact half-open Unicode span in source text."""

    sub_intent_id: str
    span_start: int
    span_end: int
    clause_text: str
    intent: Intent | None
    effect_class: EffectClass
    negated: bool = False
    ambiguity: bool = False
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.span_start < 0 or self.span_end < self.span_start:
            raise ValueError("invalid Unicode span bounds")


class OptionalClassifierPort(Protocol):
    """Approved CPU-only classifier port returning bounded IntentCandidates."""

    @property
    def version(self) -> str: ...

    def classify(self, normalized_text: str) -> tuple[IntentCandidate, ...]: ...


def _classify_effect(intent: Intent | None) -> EffectClass:
    if intent is None or intent in _LEVEL5_GENERAL_INTENTS or intent == Intent.ROADSIDE_EMERGENCY:
        return EffectClass.NO_TOOL
    if intent == Intent.HUMAN_HANDOFF_REQUEST:
        return EffectClass.CONTROL
    if CATALOGUE[intent].critical_write:
        return EffectClass.MUTATION
    return EffectClass.READ


def _level_for_intent(intent: Intent | None) -> RouteLevel:
    if intent is None:
        return RouteLevel.L5_GENERAL_OR_AMBIGUOUS
    if intent in {Intent.ROADSIDE_EMERGENCY, Intent.HUMAN_HANDOFF_REQUEST}:
        return RouteLevel.L1_SAFETY_CONTROL
    if intent in _LEVEL3_SERVICE_INTENTS:
        return RouteLevel.L3_SERVICE_BOOKING
    if intent in _LEVEL4_SPECIALIST_INTENTS:
        return RouteLevel.L4_SPECIALIST_DOMAIN
    return RouteLevel.L5_GENERAL_OR_AMBIGUOUS


def _is_safe_model_candidate(intent: Intent, normalized_text: str) -> bool:
    if intent in {Intent.ROADSIDE_EMERGENCY, Intent.HUMAN_HANDOFF_REQUEST}:
        return False
    if CATALOGUE[intent].critical_write:
        return False
    if WRITE_DENIED.search(normalized_text) or HANDOFF_DENIED.search(normalized_text):
        return False
    return True


def _sanitize_candidates(
    candidates: tuple[IntentCandidate, ...],
    *,
    normalized_text: str,
) -> tuple[IntentCandidate, ...]:
    seen: set[Intent] = set()
    clean: list[IntentCandidate] = []
    for c in candidates:
        if c.intent_id in seen:
            continue
        if c.score is not None and not math.isfinite(c.score):
            continue
        if not _is_safe_model_candidate(c.intent_id, normalized_text):
            continue
        seen.add(c.intent_id)
        clean.append(c)
        if len(clean) >= MAX_ROUTE_ALTERNATIVES:
            break
    return tuple(clean)


class HierarchicalIntentRouter:
    """
    Deterministic Level 0..5 intent router for F3-B/C.

    Precedence is guard-ordered rather than blind keyword priority:
      L0: Invalid / non-final / non-OK / unauthenticated protected input
      L1: Roadside emergency, explicit conversation stop, operator handoff
      L2: Active confirmation / rejection / correction / slot answer against exact pending context
      L3: Service booking (CREATE / RESCHEDULE / CANCEL / STATUS)
      L4: Specialist domains (Technical, Sales/Parts, CRM, Workshop)
      L5: Greeting / general / out-of-scope / unknown / ambiguous
    """

    def __init__(
        self,
        *,
        classifier: OptionalClassifierPort | None = None,
        llm_fallback: Callable[[str], Awaitable[tuple[Intent, ...]]] | None = None,
        timeout_seconds: float = 1.5,
    ) -> None:
        self._classifier = classifier
        self._llm_fallback = llm_fallback
        self._timeout_seconds = timeout_seconds

    async def route(
        self,
        *,
        asr_result: ASRResult | None,
        context: ConversationContext,
        pending_challenge_id: str | None = None,
        is_authenticated: bool = True,
        allow_llm_fallback: bool = False,
        dtmf_digit: str | None = None,
    ) -> HierarchicalRouteDecision:
        # Level 0: input validity, finality, outcome, and auth guard
        if asr_result is None and dtmf_digit is None:
            return HierarchicalRouteDecision(
                level=RouteLevel.L0_INPUT_RECOVERY,
                disposition=RouteDisposition.RECOVERY,
                primary_intent=None,
                candidates=(),
                source="guard.l0",
                needs_clarification=True,
                reason_codes=("l0.missing_input",),
            )

        if asr_result is not None:
            if asr_result.status in {ASRStatus.PARTIAL, ASRStatus.STABLE_PREFIX}:
                return HierarchicalRouteDecision(
                    level=RouteLevel.L0_INPUT_RECOVERY,
                    disposition=RouteDisposition.RECOVERY,
                    primary_intent=None,
                    candidates=(),
                    source="guard.l0",
                    needs_clarification=False,
                    reason_codes=("l0.non_final_asr",),
                )
            if asr_result.outcome != ASROutcome.OK:
                return HierarchicalRouteDecision(
                    level=RouteLevel.L0_INPUT_RECOVERY,
                    disposition=RouteDisposition.RECOVERY,
                    primary_intent=None,
                    candidates=(),
                    source="guard.l0",
                    needs_clarification=True,
                    reason_codes=(f"l0.asr_{asr_result.outcome.value.lower()}",),
                )

        raw_text = asr_result.raw_transcript if asr_result is not None else ""
        norm = normalize_utterance(raw_text)

        if not norm and dtmf_digit is None:
            return HierarchicalRouteDecision(
                level=RouteLevel.L0_INPUT_RECOVERY,
                disposition=RouteDisposition.RECOVERY,
                primary_intent=None,
                candidates=(),
                source="guard.l0",
                needs_clarification=True,
                reason_codes=("l0.empty_utterance",),
            )

        # Level 1: Emergency, explicit conversation stop (distinct from booking cancel), handoff
        base_decision: IntentDecision = rule_decision(norm) if norm else IntentDecision(
            candidates=(),
            route_state=RouteState.UNKNOWN,
            source="none",
            needs_clarification=True,
            reason_codes=("intent.insufficient_evidence",),
        )
        reasons = list(base_decision.reason_codes)

        if any(c.intent_id == Intent.ROADSIDE_EMERGENCY for c in base_decision.candidates):
            emerg = tuple(c for c in base_decision.candidates if c.intent_id == Intent.ROADSIDE_EMERGENCY)
            return HierarchicalRouteDecision(
                level=RouteLevel.L1_SAFETY_CONTROL,
                disposition=RouteDisposition.ROUTED,
                primary_intent=Intent.ROADSIDE_EMERGENCY,
                candidates=emerg,
                source="rule.l1",
                needs_clarification=False,
                reason_codes=tuple(reasons),
            )

        if "safety.clarify" in reasons:
            return HierarchicalRouteDecision(
                level=RouteLevel.L1_SAFETY_CONTROL,
                disposition=RouteDisposition.CLARIFY,
                primary_intent=None,
                candidates=(),
                source="rule.l1",
                needs_clarification=True,
                reason_codes=tuple(reasons),
            )

        if _CONVERSATION_CANCEL_RE.search(norm) and "randevu" not in norm:
            return HierarchicalRouteDecision(
                level=RouteLevel.L1_SAFETY_CONTROL,
                disposition=RouteDisposition.ROUTED,
                primary_intent=Intent.GOODBYE,
                candidates=(IntentCandidate(intent_id=Intent.GOODBYE, evidence="rule.l1_stop_conversation"),),
                source="rule.l1",
                needs_clarification=False,
                reason_codes=tuple(dict.fromkeys([*reasons, "l1.conversation_stop"])),
            )

        if any(c.intent_id == Intent.HUMAN_HANDOFF_REQUEST for c in base_decision.candidates):
            handoff = tuple(c for c in base_decision.candidates if c.intent_id == Intent.HUMAN_HANDOFF_REQUEST)
            return HierarchicalRouteDecision(
                level=RouteLevel.L1_SAFETY_CONTROL,
                disposition=RouteDisposition.ROUTED,
                primary_intent=Intent.HUMAN_HANDOFF_REQUEST,
                candidates=handoff,
                source="rule.l1",
                needs_clarification=False,
                reason_codes=tuple(reasons),
            )

        # Level 2: Active confirmation / rejection / correction / slot answer / DTMF
        if dtmf_digit is not None and pending_challenge_id is not None:
            if dtmf_digit in {"1", "2"}:
                act_intent = context.active_task
                cands = (
                    (IntentCandidate(intent_id=act_intent, evidence="dtmf.challenge_selection"),)
                    if act_intent is not None
                    else ()
                )
                return HierarchicalRouteDecision(
                    level=RouteLevel.L2_ACTIVE_WORKFLOW,
                    disposition=RouteDisposition.ROUTED if cands else RouteDisposition.CLARIFY,
                    primary_intent=act_intent,
                    candidates=cands,
                    source="dtmf.l2",
                    needs_clarification=not bool(cands),
                    reason_codes=("l2.dtmf_confirmation" if dtmf_digit == "1" else "l2.dtmf_rejection",),
                    active_workflow_invalidated=(dtmf_digit == "2"),
                )

        if pending_challenge_id is not None:
            if _NEGATIVE_EXACT_RE.search(norm) or "policy.negated_write" in reasons:
                return HierarchicalRouteDecision(
                    level=RouteLevel.L2_ACTIVE_WORKFLOW,
                    disposition=RouteDisposition.ROUTED,
                    primary_intent=context.active_task,
                    candidates=(
                        (IntentCandidate(intent_id=context.active_task, evidence="l2.confirmation_rejected"),)
                        if context.active_task is not None
                        else ()
                    ),
                    source="rule.l2",
                    needs_clarification=False,
                    reason_codes=tuple(dict.fromkeys([*reasons, "l2.confirmation_rejected"])),
                    active_workflow_invalidated=True,
                )
            if _AFFIRMATIVE_EXACT_RE.match(norm) and context.active_task is not None:
                return HierarchicalRouteDecision(
                    level=RouteLevel.L2_ACTIVE_WORKFLOW,
                    disposition=RouteDisposition.ROUTED,
                    primary_intent=context.active_task,
                    candidates=(IntentCandidate(intent_id=context.active_task, evidence="l2.confirmation_answer"),),
                    source="rule.l2",
                    needs_clarification=False,
                    reason_codes=tuple(dict.fromkeys([*reasons, "l2.confirmation_answer"])),
                )

        if CORRECTION.search(norm):
            return HierarchicalRouteDecision(
                level=RouteLevel.L2_ACTIVE_WORKFLOW,
                disposition=RouteDisposition.CLARIFY if not base_decision.candidates else RouteDisposition.ROUTED,
                primary_intent=base_decision.candidates[0].intent_id if base_decision.candidates else context.active_task,
                candidates=base_decision.candidates[:MAX_ROUTE_ALTERNATIVES],
                source="rule.l2",
                needs_clarification=not bool(base_decision.candidates),
                reason_codes=tuple(dict.fromkeys([*reasons, "l2.customer_correction"])),
                active_workflow_invalidated=True,
            )

        if not base_decision.candidates and context.active_task == Intent.BOOKING_CREATE and BARE_DATE.fullmatch(norm):
            return HierarchicalRouteDecision(
                level=RouteLevel.L2_ACTIVE_WORKFLOW,
                disposition=RouteDisposition.ROUTED,
                primary_intent=Intent.BOOKING_CREATE,
                candidates=(IntentCandidate(intent_id=Intent.BOOKING_CREATE, evidence="context.pending_booking_date"),),
                source="rule.l2",
                needs_clarification=False,
                reason_codes=("l2.slot_answer",),
            )

        # Level 3 & Level 4: Rule-matched service booking or specialist domain
        candidates = list(base_decision.candidates[:MAX_ROUTE_ALTERNATIVES])
        source = base_decision.source
        classifier_used = False
        llm_used = False

        if candidates:
            # Explicit topic switch invalidates unrelated pending challenge.
            primary = candidates[0].intent_id
            topic_switched = context.active_task is not None and primary != context.active_task
            if not is_authenticated and primary in {
                Intent.BOOKING_STATUS,
                Intent.CUSTOMER_RECORD_QUESTION,
                Intent.BOOKING_CANCEL,
            }:
                reasons.append("l0.unauthenticated_protected_intent")
            return HierarchicalRouteDecision(
                level=_level_for_intent(primary),
                disposition=RouteDisposition.ROUTED,
                primary_intent=primary,
                candidates=tuple(candidates),
                source=source,
                needs_clarification=False,
                reason_codes=tuple(dict.fromkeys(reasons)),
                active_workflow_invalidated=topic_switched,
            )

        if base_decision.route_state == RouteState.OUT_OF_SCOPE:
            return HierarchicalRouteDecision(
                level=RouteLevel.L5_GENERAL_OR_AMBIGUOUS,
                disposition=RouteDisposition.OUT_OF_SCOPE,
                primary_intent=None,
                candidates=(),
                source="rule.l5",
                needs_clarification=False,
                reason_codes=tuple(reasons),
            )

        # Optional approved CPU classifier pass (at most 1)
        if self._classifier is not None and "policy.negated_write" not in reasons:
            classifier_used = True
            try:
                raw_ranked = await asyncio.wait_for(
                    asyncio.to_thread(self._classifier.classify, norm),
                    timeout=self._timeout_seconds,
                )
                safe_ranked = _sanitize_candidates(tuple(raw_ranked), normalized_text=norm)
                if 0 < len(safe_ranked) <= 3:
                    primary = safe_ranked[0].intent_id
                    return HierarchicalRouteDecision(
                        level=_level_for_intent(primary),
                        disposition=RouteDisposition.ROUTED,
                        primary_intent=primary,
                        candidates=safe_ranked,
                        source="classifier",
                        needs_clarification=False,
                        reason_codes=("classifier.accepted",),
                        classifier_used=True,
                    )
                if safe_ranked:
                    reasons.append("classifier.ambiguous")
            except TimeoutError:
                reasons.append("classifier.timeout")
            except Exception:
                reasons.append("classifier.unavailable")

        # Optional bounded LLM fallback (at most 1 call)
        if allow_llm_fallback and self._llm_fallback is not None and "policy.negated_write" not in reasons:
            llm_used = True
            try:
                proposed = await asyncio.wait_for(self._llm_fallback(raw_text), timeout=self._timeout_seconds)
                llm_cands = _sanitize_candidates(
                    tuple(IntentCandidate(intent_id=i, evidence="llm.proposal") for i in proposed),
                    normalized_text=norm,
                )
                if llm_cands:
                    primary = llm_cands[0].intent_id
                    return HierarchicalRouteDecision(
                        level=_level_for_intent(primary),
                        disposition=RouteDisposition.ROUTED,
                        primary_intent=primary,
                        candidates=llm_cands,
                        source="llm",
                        needs_clarification=False,
                        reason_codes=("llm.proposal_accepted",),
                        classifier_used=classifier_used,
                        llm_used=True,
                    )
                reasons.append("llm.abstained")
            except TimeoutError:
                reasons.append("llm.timeout")
            except Exception:
                reasons.append("llm.unavailable")

        # Level 5 fallback: clarification
        return HierarchicalRouteDecision(
            level=RouteLevel.L5_GENERAL_OR_AMBIGUOUS,
            disposition=RouteDisposition.CLARIFY,
            primary_intent=None,
            candidates=(),
            source="none",
            needs_clarification=True,
            reason_codes=tuple(dict.fromkeys(reasons)),
            classifier_used=classifier_used,
            llm_used=llm_used,
        )


def _split_clauses_preserving_protected(text: str) -> list[tuple[int, int, str]]:
    """Split utterance on conjunctions without ever splitting inside protected spans."""
    protected_ranges = [(m.start(), m.end()) for m in _PROTECTED_SPAN_RE.finditer(text)]

    def _inside_protected(pos: int) -> bool:
        return any(s <= pos < e for s, e in protected_ranges)

    clauses: list[tuple[int, int, str]] = []
    last = 0
    for m in _CLAUSE_SPLIT_RE.finditer(text):
        if _inside_protected(m.start()) or _inside_protected(m.end()):
            continue
        seg = text[last : m.start()].strip()
        if seg:
            lead = len(text[last : m.start()]) - len(text[last : m.start()].lstrip())
            start = last + lead
            end = start + len(seg)
            clauses.append((start, end, seg))
        last = m.end()
    tail = text[last:].strip()
    if tail:
        lead = len(text[last:]) - len(text[last:].lstrip())
        start = last + lead
        end = start + len(tail)
        clauses.append((start, end, tail))
    return clauses


def decompose_multi_intent(raw_text: str) -> tuple[SubIntent, ...]:
    """
    Deterministic F3-C multi-intent splitter (max 4 sub-intents).

    Preserves half-open Unicode spans, per-clause negation, and never splits
    inside protected plates, dates, or decimal numbers.
    """
    if not raw_text or not raw_text.strip():
        return ()

    clauses = _split_clauses_preserving_protected(raw_text)
    if not clauses:
        clauses = [(0, len(raw_text), raw_text.strip())]

    sub_intents: list[SubIntent] = []
    prior_has_booking_topic = False
    for idx, (start, end, clause_text) in enumerate(clauses[:MAX_SUB_INTENTS]):
        norm_clause = normalize_utterance(clause_text)
        if "randevu" in norm_clause:
            prior_has_booking_topic = True
        eval_clause = norm_clause
        if prior_has_booking_topic and "randevu" not in norm_clause and re.search(r"\b(?:saat\w*|durum\w*|ne zaman)\b", norm_clause):
            eval_clause = f"randevu {norm_clause}"
        dec = rule_decision(eval_clause)
        negated = bool(WRITE_DENIED.search(norm_clause))
        if dec.candidates:
            intent = dec.candidates[0].intent_id
            ambig = len(dec.candidates) > 1
        else:
            intent = None
            ambig = "policy.negated_write" not in dec.reason_codes
        sub_intents.append(
            SubIntent(
                sub_intent_id=f"sub-{idx + 1}",
                span_start=start,
                span_end=end,
                clause_text=clause_text,
                intent=intent,
                effect_class=_classify_effect(intent),
                negated=negated,
                ambiguity=ambig,
                reason_codes=dec.reason_codes,
            )
        )
    return tuple(sub_intents)
