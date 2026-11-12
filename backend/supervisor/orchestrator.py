import asyncio
import hashlib
import io
from pathlib import Path
from typing import Awaitable, Callable
from uuid import UUID, uuid4

from pydantic import Field

from backend.supervisor.catalogue import CATALOGUE
from backend.supervisor.contracts import (
    CATALOGUE_VERSION, Contract, ConversationContext, ExecutionPlan, Intent,
    IntentCandidate, IntentDecision, RouteState, Slot,
)
from backend.supervisor.policy import (
    BARE_DATE, HANDOFF_DENIED, WRITE_DENIED, build_plan, normalize_utterance, resolve_slots,
    rule_decision,
)


class Proposal(Contract):
    intents: tuple[Intent, ...] = Field(max_length=3)


class RoutingResult(Contract):
    decision: IntentDecision
    plan: ExecutionPlan
    slots: tuple[Slot, ...]


class ApprovedRanker:
    def __init__(self, path: Path, approved_sha256: str):
        import joblib
        import sklearn

        artifact = path.read_bytes()
        if not approved_sha256 or hashlib.sha256(artifact).hexdigest() != approved_sha256:
            raise ValueError("artifact digest has not been approved")
        bundle = joblib.load(io.BytesIO(artifact))
        manifest = bundle["manifest"]
        if (
            manifest["kind"] != "baseline"
            or manifest["catalogue_version"] != CATALOGUE_VERSION
            or manifest["label_index"] != list(Intent)
            or manifest["sklearn_version"] != sklearn.__version__
            or manifest["dataset_sources"] != ["human_review"]
        ):
            raise ValueError("artifact is incompatible or lacks a reviewed dataset")
        self.version = manifest["model_version"]
        self.thresholds = manifest["thresholds"]
        self.features = bundle["features"]
        self.estimator = bundle["estimator"]

    def __call__(self, text: str) -> tuple[IntentCandidate, ...]:
        scores = self.estimator.predict_proba(self.features.transform([text]))[0]
        return tuple(
            IntentCandidate(intent_id=intent, score=float(score), evidence="classifier.threshold")
            for intent, score in zip(Intent, scores, strict=True) if score >= self.thresholds[intent]
        )


def _safe_model_candidate(intent: Intent, text: str) -> bool:
    return (
        intent not in {Intent.ROADSIDE_EMERGENCY, Intent.HUMAN_HANDOFF_REQUEST}
        and not CATALOGUE[intent].critical_write
        and not WRITE_DENIED.search(text)
        and not HANDOFF_DENIED.search(text)
    )


class SupervisorOrchestrator:
    def __init__(
        self,
        ranker: ApprovedRanker | None = None,
        fallback: Callable[[str], Awaitable[Proposal]] | None = None,
        timeout_seconds: float = 2.0,
        vehicles: tuple[tuple[str, str], ...] = (),
    ):
        self.ranker = ranker
        self.fallback = fallback
        self.timeout_seconds = timeout_seconds
        self.vehicles = vehicles

    async def route(
        self, transcript: str, context: ConversationContext, *,
        trace_id: UUID | None = None, is_final: bool = True,
    ) -> RoutingResult:
        trace_id = trace_id or uuid4()
        text = normalize_utterance(transcript)
        if not is_final:
            decision = IntentDecision(route_state=RouteState.UNKNOWN, source="none",
                                      needs_clarification=True, reason_codes=("asr.partial_ignored",))
            return RoutingResult(decision=decision, plan=build_plan((), (), trace_id, "rules-v1"), slots=())
        decision = rule_decision(text)
        candidates = {candidate.intent_id: candidate for candidate in decision.candidates}
        version = "rules-v1"
        source = decision.source
        reasons = list(decision.reason_codes)
        if not candidates and context.active_task == Intent.BOOKING_CREATE and BARE_DATE.fullmatch(text):
            candidates[Intent.BOOKING_CREATE] = IntentCandidate(
                intent_id=Intent.BOOKING_CREATE, evidence="context.pending_booking_date",
            )
            source = "rule"
        allow_model = (
            bool(text) and decision.route_state != RouteState.OUT_OF_SCOPE
            and "safety.clarify" not in reasons and "policy.negated_write" not in reasons
            and not candidates.keys() & {Intent.ROADSIDE_EMERGENCY, Intent.HUMAN_HANDOFF_REQUEST}
            and not any(CATALOGUE[intent].critical_write for intent in candidates)
        )
        if allow_model and self.ranker:
            try:
                ranked = await asyncio.wait_for(asyncio.to_thread(self.ranker, text), self.timeout_seconds)
                accepted = [
                    candidate for candidate in ranked
                    if _safe_model_candidate(candidate.intent_id, text) and candidate.intent_id not in candidates
                ]
                if 0 < len(accepted) <= 3:
                    source = "hybrid" if candidates else "classifier"
                    candidates.update((candidate.intent_id, candidate) for candidate in accepted)
                    version = self.ranker.version
                elif accepted:
                    reasons.append("classifier.ambiguous")
            except Exception:
                reasons.append("classifier.unavailable")
        if allow_model and self.fallback and not candidates:
            try:
                proposal = await asyncio.wait_for(self.fallback(transcript), self.timeout_seconds)
                for intent in proposal.intents:
                    if _safe_model_candidate(intent, text):
                        candidates[intent] = IntentCandidate(intent_id=intent, evidence="llm.proposal")
                if candidates:
                    source = "llm"
                    version = "local-llm-v1"
                else:
                    reasons.append("llm.abstained")
            except TimeoutError:
                reasons.append("llm.timeout")
            except Exception:
                reasons.append("llm.unavailable")
        if candidates:
            reasons = [reason for reason in reasons if reason != "intent.insufficient_evidence"]
        decision = IntentDecision(
            candidates=tuple(candidates.values()),
            route_state=RouteState.ROUTED if candidates else decision.route_state,
            source=source, needs_clarification="safety.clarify" in reasons or (
                not candidates and decision.route_state == RouteState.UNKNOWN
            ),
            reason_codes=tuple(reasons),
        )
        slots = resolve_slots(text, context, vehicles=self.vehicles)
        plan = build_plan(decision.intent_ids, decision.reason_codes, trace_id, version)
        return RoutingResult(decision=decision, plan=plan, slots=slots)
