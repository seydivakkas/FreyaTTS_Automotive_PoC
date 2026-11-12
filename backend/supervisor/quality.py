import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from backend.db import Conversation, IntentTrainingCandidate, Session, SupervisorTrace
from backend.supervisor.contracts import Contract, Intent, RouteState
from backend.supervisor.dataset import TrainingExample
from backend.supervisor.orchestrator import RoutingResult
from backend.supervisor.policy import normalize_utterance

Outcome = Literal["legacy_delegated", "response_prepared", "tool_unavailable", "identity_required", "fallback"]


def record_trace(conversation_id: str, result: RoutingResult, outcome: Outcome, session_factory=Session) -> None:
    decision = result.decision
    plan = result.plan
    flags = []
    if decision.needs_clarification or decision.source in {"classifier", "llm", "hybrid"}:
        flags.append("needs_review")
    if outcome in {"tool_unavailable", "fallback"}:
        flags.append(outcome)
    if plan.priority == "emergency":
        flags.append("safety_review")
    if "dialogue.customer_correction" in decision.reason_codes:
        flags.append("customer_correction")
    payload = {
        "provenance": "asr_final",
        "transcript": "[WITHHELD]",
        "decision": {
            **decision.model_dump(mode="json"), "intent_ids": decision.intent_ids, "scores": decision.scores,
        },
        "plan": plan.model_dump(mode="json"),
        "slots": [{"name": slot.name, "verified": slot.verified} for slot in result.slots],
        "outcome": outcome,
        "qa_flags": flags,
    }
    with session_factory.begin() as db:
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        conversation = db.get(Conversation, conversation_id)
        if conversation is None or conversation.status == "purged":
            return
        db.add(SupervisorTrace(
            id=str(plan.trace_id), conversation_id=conversation_id,
            payload=json.dumps(payload, ensure_ascii=False),
            review_status="PENDING" if flags else "OBSERVED",
        ))


def finalize_conversation(conversation_id: str, session_factory=Session) -> None:
    with session_factory.begin() as db:
        traces = list(db.scalars(select(SupervisorTrace).where(
            SupervisorTrace.conversation_id == conversation_id,
        )))
        items = [(trace, json.loads(trace.payload)) for trace in traces]
        clarifications = [
            (trace, payload) for trace, payload in items if payload["decision"]["needs_clarification"]
        ]
        if len(clarifications) > 1:
            for trace, payload in clarifications:
                if "repeated_clarification" not in payload["qa_flags"]:
                    payload["qa_flags"].append("repeated_clarification")
                    trace.payload = json.dumps(payload, ensure_ascii=False)


def purge_expired(cutoff_iso: str, session_factory=Session) -> None:
    with session_factory.begin() as db:
        db.execute(delete(SupervisorTrace).where(SupervisorTrace.created_at < cutoff_iso))


class ReviewInput(Contract):
    verdict: Literal["ACCEPT", "EDIT", "REJECT", "NEEDS_MORE_EVIDENCE"]
    labels: tuple[Intent, ...] | None = None
    anonymous_text: str | None = Field(default=None, min_length=1, max_length=1200)
    group_id: UUID | None = None
    split: Literal["train", "validation", "test"] | None = None
    anonymity_attested: bool = False
    consent_attested: bool = False

    @model_validator(mode="after")
    def validate_review(self):
        if self.verdict == "EDIT" and self.labels is None:
            raise ValueError("EDIT requires corrected labels")
        if self.verdict != "EDIT" and self.labels is not None:
            raise ValueError("labels are only accepted with EDIT")
        if self.labels is not None and len(set(self.labels)) != len(self.labels):
            raise ValueError("duplicate review labels")
        if self.anonymous_text is not None and not (
            self.verdict in {"ACCEPT", "EDIT"} and self.group_id is not None and self.split
            and self.anonymity_attested and self.consent_attested
        ):
            raise ValueError("dataset admission requires accepted review, group, split, consent and anonymization")
        return self


def apply_review(trace_id: UUID, body: ReviewInput, session_factory=Session) -> str:
    try:
        with session_factory.begin() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            trace = db.get(SupervisorTrace, str(trace_id))
            if trace is None:
                raise LookupError("trace not found")
            payload = json.loads(trace.payload)
            assigned = tuple(Intent(row["intent_id"]) for row in payload["decision"]["candidates"])
            labels = body.labels if body.verdict == "EDIT" else assigned
            if (
                body.anonymous_text is not None and body.verdict == "ACCEPT"
                and payload["decision"]["route_state"] == RouteState.UNKNOWN
            ):
                raise ValueError("unknown route requires explicit corrected labels before admission")
            current_example = db.get(IntentTrainingCandidate, trace.id)
            preserve_example = (
                current_example is not None and body.anonymous_text is None
                and body.verdict in {"ACCEPT", "EDIT"}
                and json.loads(current_example.example)["intents"] == list(labels)
            )
            if current_example and not preserve_example:
                db.delete(current_example)
                db.flush()
            if body.anonymous_text is not None:
                example = TrainingExample(
                    text=body.anonymous_text, intents=labels, group_id=str(body.group_id),
                    split=body.split, source="human_review", review_id=trace.id,
                    anonymity_attested=body.anonymity_attested, consent_attested=body.consent_attested,
                )
                same_conversation = db.scalars(
                    select(IntentTrainingCandidate)
                    .join(SupervisorTrace, SupervisorTrace.id == IntentTrainingCandidate.trace_id)
                    .where(SupervisorTrace.conversation_id == trace.conversation_id)
                )
                if any(
                    row.group_id != example.group_id or row.split != example.split for row in same_conversation
                ):
                    raise ValueError("conversation is already assigned to another dataset group or split")
                if db.scalar(select(IntentTrainingCandidate.trace_id).where(
                    IntentTrainingCandidate.group_id == example.group_id,
                    IntentTrainingCandidate.split != example.split,
                )):
                    raise ValueError("group is already assigned to another split")
                db.add(IntentTrainingCandidate(
                    trace_id=trace.id, group_id=example.group_id, split=example.split,
                    text_digest=hashlib.sha256(normalize_utterance(example.text).encode()).hexdigest(),
                    example=example.model_dump_json(),
                ))
            trace.review_status = body.verdict
            trace.review_labels = json.dumps(labels) if body.verdict in {"ACCEPT", "EDIT"} else None
        return body.verdict
    except IntegrityError as exc:
        raise ValueError("duplicate approved utterance") from exc
