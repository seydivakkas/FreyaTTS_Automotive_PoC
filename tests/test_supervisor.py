import asyncio
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.db import Appointment, Base, Conversation, IntentTrainingCandidate, Slot as DbSlot, SupervisorTrace, Vehicle
from backend.supervisor.catalogue import CATALOGUE
from backend.supervisor.contracts import (
    ConversationContext, ExecutionPlan, Intent, IntentCandidate, IntentDecision,
    PlanStep, RouteState, Slot,
)
from backend.supervisor.policy import build_plan, normalize_utterance, resolve_slots, rule_decision
from backend.supervisor.dataset import partition_examples
from backend.supervisor.gateway import ConfirmedWrite, ToolGateway, WriteTool, request_digest
from backend.supervisor.orchestrator import Proposal, SupervisorOrchestrator
from backend.supervisor.quality import ReviewInput, apply_review, record_trace
from backend.supervisor.synthetic import synthetic_examples


def test_catalogue_is_exact_and_versioned():
    assert set(CATALOGUE) == set(Intent)
    assert Counter(item.domain for item in CATALOGUE.values()) == {
        "conversation": 5, "service": 5, "technical": 4, "sales": 3,
        "parts": 2, "crm": 2, "safety": 1,
    }
    assert {item.catalogue_version for item in CATALOGUE.values()} == {"intent-v1"}
    assert all(item.positive and item.negative and item.agent for item in CATALOGUE.values())


def test_decision_roundtrip_and_validation():
    decision = IntentDecision.model_validate_json(
        '{"route_state":"ROUTED","source":"rule","candidates":['
        '{"intent_id":"booking_status","evidence":"rule.booking_status"}]}'
    )
    assert decision.intent_ids == (Intent.BOOKING_STATUS,)
    assert decision.scores == {Intent.BOOKING_STATUS: None}
    with pytest.raises(ValidationError):
        IntentDecision(route_state=RouteState.ROUTED, source="rule")
    with pytest.raises(ValidationError):
        IntentCandidate(intent_id=Intent.GREETING, score=1.1, evidence="rule.greeting")


def test_unconfirmed_slots_and_invalid_dependencies_are_rejected():
    with pytest.raises(ValidationError):
        Slot(name="vehicle_year", value=2021, verified=True, evidence="asr_final")
    with pytest.raises(ValidationError):
        ConversationContext(session_id=uuid4(), turn_at=datetime.now())
    with pytest.raises(ValidationError):
        ExecutionPlan(
            steps=(PlanStep(step_id="write", agent="CRM", action="write", writes=True),),
            priority="normal", requires_confirmation=False, model_version="rules", trace_id=uuid4(),
        )
    context = ConversationContext(session_id=uuid4(), turn_at=datetime.now(timezone.utc))
    assert context.verified_vehicle == ()


@pytest.mark.parametrize(("text", "expected"), [
    ("Randevumu iptal etmek istemiyorum, sadece saatini öğrenmek istiyorum", (Intent.BOOKING_STATUS,)),
    ("Randevumu iptal etmeyin", ()),
    ("Fren tutmuyor, yoldayım!", (Intent.ROADSIDE_EMERGENCY,)),
    ("Fren balatası stokta mı?", (Intent.PART_AVAILABILITY,)),
    ("Fren tutmazsa ne yapmalıyım?", ()),
    ("Fren tutmuyor, kaza olursa ne yapacağım?", (Intent.ROADSIDE_EMERGENCY,)),
    ("Geçen yıl kaza yaptım", ()),
    ("Operatöre bağlar mısınız?", (Intent.HUMAN_HANDOFF_REQUEST,)),
    ("Temsilciyle görüşmek istemiyorum", ()),
])
def test_rule_decisions(text, expected):
    assert rule_decision(normalize_utterance(text)).intent_ids == expected


def test_emergency_dominates_and_technical_precedes_booking():
    for text, priority, actions in (
        ("Randevu istiyorum ama fren tutmuyor, yoldayım", "emergency",
         ["urgent_safety_message", "request_handoff"]),
        ("2021 Peugeot 3008 motor arıza ışığı yanıyor, cuma servise gelebilir miyim?", "normal",
         ["answer_with_verified_sources", "clarify_date_and_check_availability"]),
    ):
        decision = rule_decision(normalize_utterance(text))
        plan = build_plan(decision.intent_ids, decision.reason_codes, uuid4(), "rules-v1")
        assert plan.priority == priority
        assert [step.action for step in plan.steps] == actions
        assert plan.steps[1].depends_on == (plan.steps[0].step_id,)
        assert all(not step.writes for step in plan.steps)


def test_unknown_out_of_scope_and_uncertain_safety_are_distinct():
    assert rule_decision("eee şey").route_state == RouteState.UNKNOWN
    assert rule_decision("hava durumu nasıl").route_state == RouteState.OUT_OF_SCOPE
    decision = rule_decision("yoldayım duman var")
    assert decision.needs_clarification
    assert build_plan(decision.intent_ids, decision.reason_codes, uuid4(), "rules-v1").steps[0].action == "clarify_urgent_risk"


def test_relative_date_uses_istanbul_clock_and_context_is_isolated():
    now = datetime(2026, 11, 12, 22, tzinfo=timezone.utc)
    verified = Slot(name="vehicle_model", value="3008", verified=True, evidence="confirmed_context")
    first = ConversationContext(session_id=uuid4(), turn_at=now, verified_vehicle=(verified,))
    second = ConversationContext(session_id=uuid4(), turn_at=now)
    resolved = {slot.name: slot for slot in resolve_slots("cuma servise gelebilir miyim", first)}
    assert resolved["preferred_date"].value == "2026-11-13"
    assert not resolved["preferred_date"].verified
    assert resolved["vehicle_model"] == verified
    assert {slot.name for slot in resolve_slots("cuma", second)} == {"preferred_date"}


def make_context(**kwargs):
    return ConversationContext(session_id=uuid4(), turn_at=datetime.now(timezone.utc), **kwargs)


@pytest.fixture
def local_store(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'supervisor.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine)
    engine.dispose()


async def test_orchestrator_multilabel_vehicle_and_partial_guard():
    supervisor = SupervisorOrchestrator(vehicles=(("Peugeot", "3008"),))
    context = make_context()
    result = await supervisor.route(
        "2021 Peugeot 3008 motor arıza ışığı yanıyor, cuma servise gelebilir miyim? Operatöre bağlar mısınız?",
        context,
    )
    assert set(result.decision.intent_ids) == {
        Intent.WARNING_LIGHT_QUESTION, Intent.BOOKING_CREATE, Intent.HUMAN_HANDOFF_REQUEST,
    }
    assert [step.agent for step in result.plan.steps] == ["Operator", "AutomotiveExpert", "ServiceBooking"]
    assert {slot.name: slot.value for slot in result.slots}["vehicle_model"] == "3008"
    assert all(not slot.verified for slot in result.slots)
    assert result.plan.requires_confirmation
    partial = await supervisor.route("Fren tutmuyor, randevumu iptal edin", context, is_final=False)
    assert partial.decision.intent_ids == ()
    assert partial.decision.reason_codes == ("asr.partial_ignored",)


async def test_context_only_resolves_short_date_for_pending_booking():
    router = SupervisorOrchestrator()
    booking = await router.route("Cuma", make_context(active_task=Intent.BOOKING_CREATE))
    assert booking.decision.intent_ids == (Intent.BOOKING_CREATE,)
    assert booking.slots[0].evidence == "relative_date"
    other = await router.route("Cuma", make_context())
    assert other.decision.route_state == RouteState.UNKNOWN
    ambiguous = await router.route("Cuma veya cumartesi servise gelebilir miyim", make_context())
    assert not any(slot.name == "preferred_date" for slot in ambiguous.slots)


async def test_llm_cannot_suggest_writes_safety_or_handoff_and_timeout_abstains():
    async def malicious(_):
        return Proposal(intents=(Intent.BOOKING_CANCEL, Intent.ROADSIDE_EMERGENCY, Intent.HUMAN_HANDOFF_REQUEST))

    result = await SupervisorOrchestrator(fallback=malicious).route("bir şey soracaktım", make_context())
    assert result.decision.route_state == RouteState.UNKNOWN
    assert "llm.abstained" in result.decision.reason_codes

    async def slow(_):
        await asyncio.sleep(10)

    result = await SupervisorOrchestrator(fallback=slow, timeout_seconds=0.01).route("eee", make_context())
    assert "llm.timeout" in result.decision.reason_codes
    assert result.plan.steps[0].action == "clarify_intent"


async def test_gateway_denies_unconfirmed_or_changed_write_and_deduplicates(local_store):
    result = await SupervisorOrchestrator().route("randevumu iptal edin", make_context())
    fields = {"booking_id": "slot-test"}
    action = "cancel_booking"
    grant = ConfirmedWrite(
        idempotency_key=uuid4(), trace_id=result.plan.trace_id, action=action,
        request_digest=request_digest(action, fields), verified_customer_id="owner",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    checks = []

    def recheck(db, identity, values):
        checks.append(identity)
        return db.get(DbSlot, values["booking_id"]) is None and identity == "owner"

    def apply(db, identity, values):
        db.add(DbSlot(id=values["booking_id"], starts_at="2026-11-30T08:00:00+00:00"))

    gateway = ToolGateway({action: WriteTool(recheck, apply)}, session_factory=local_store)
    assert await gateway.execute_write(result.plan, Intent.BOOKING_CANCEL, fields, None) == "denied"
    assert await gateway.execute_write(result.plan, Intent.BOOKING_CANCEL, {"booking_id": "different"}, grant) == "denied"
    outcomes = await asyncio.gather(*(
        gateway.execute_write(result.plan, Intent.BOOKING_CANCEL, fields, grant) for _ in range(2)
    ))
    assert sorted(outcomes) == ["applied", "duplicate"]
    assert checks == ["owner"]
    with local_store() as db:
        assert db.get(DbSlot, "slot-test") is not None


async def test_redacted_trace_and_review_gate(local_store):
    context = make_context()
    with local_store.begin() as db:
        db.add(Conversation(id=str(context.session_id), channel="web"))
    supervisor = SupervisorOrchestrator()
    result = await supervisor.route("Adım Burak, numaram 0555 123 45 67, randevum saat kaçta", context)
    record_trace(str(context.session_id), result, "identity_required", local_store)
    with local_store() as db:
        trace = db.get(SupervisorTrace, str(result.plan.trace_id))
        payload = json.loads(trace.payload)
        assert payload["transcript"] == "[WITHHELD]"
        assert "Burak" not in trace.payload and "0555" not in trace.payload
        assert db.get(IntentTrainingCandidate, trace.id) is None
    group = uuid4()
    review = ReviewInput(
        verdict="ACCEPT", anonymous_text="Randevum hangi saatte", group_id=group,
        split="train", anonymity_attested=True, consent_attested=True,
    )
    with pytest.raises(ValidationError):
        apply_review(result.plan.trace_id, review.model_copy(update={"anonymous_text": "0555 123 45 67"}), local_store)
    apply_review(result.plan.trace_id, review, local_store)
    with local_store() as db:
        row = db.get(IntentTrainingCandidate, str(result.plan.trace_id))
        assert json.loads(row.example)["source"] == "human_review"

    second = await supervisor.route("randevum hangi gün", context)
    record_trace(str(context.session_id), second, "identity_required", local_store)
    with pytest.raises(ValueError, match="group or split"):
        apply_review(second.plan.trace_id, review.model_copy(update={
            "anonymous_text": "Rezervasyonum hangi gün", "split": "test",
        }), local_store)
    with pytest.raises(ValueError, match="duplicate"):
        apply_review(second.plan.trace_id, review, local_store)
    apply_review(result.plan.trace_id, ReviewInput(verdict="REJECT"), local_store)
    with local_store() as db:
        assert list(db.scalars(select(IntentTrainingCandidate))) == []


def test_group_split_rejects_leakage_and_missing_label_coverage():
    rows = synthetic_examples()
    assert {key: len(value) for key, value in partition_examples(rows).items()} == {
        "train": 47, "validation": 26, "test": 26,
    }
    with pytest.raises(ValueError, match="more than one split"):
        partition_examples(rows + [rows[0].model_copy(update={"text": "Selamlar efendim", "split": "test"})])
    with pytest.raises(ValueError, match="needs every positive label"):
        partition_examples([row for row in rows if Intent.ROADSIDE_EMERGENCY not in row.intents])


async def test_web_modes_use_real_read_only_tool_and_no_live_write(monkeypatch):
    from backend.supervisor import runtime

    seen = []
    monkeypatch.setattr(runtime, "approved_ranker", lambda: None)
    monkeypatch.setattr(runtime, "vehicle_pairs", lambda: ())
    monkeypatch.setattr(runtime, "record_trace", lambda *args: seen.append(args))
    monkeypatch.setattr(runtime, "free_slot_count", lambda day, now: 1)
    shadow = runtime.WebSupervisor(str(uuid4()), "shadow")
    assert await shadow.process_final("Fren tutmuyor yoldayım") is None
    assert seen[-1][2] == "legacy_delegated"
    guarded = runtime.WebSupervisor(str(uuid4()), "guarded")
    assert "hangi günü" in await guarded.process_final("Randevu almak istiyorum")
    answer = await guarded.process_final("Cuma")
    assert "boş saat" in answer and "kimliğinizi doğrulamamız" in answer
    assert seen[-1][2] == "identity_required"
    assert "kimliğinizi" in await guarded.process_final("Randevumun saati nedir?")


def test_quality_api_requires_operator_auth_and_review_is_not_automatic(monkeypatch, local_store):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.config import settings
    from backend.routers import supervisor as routes

    monkeypatch.setattr(settings, "admin_password", "test-supervisor")
    monkeypatch.setattr(routes, "Session", local_store)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        assert client.get("/api/supervisor/quality").status_code == 401
        auth = ("admin", "test-supervisor")
        body = client.get("/api/supervisor/quality", auth=auth).json()
        assert len(body["catalogue"]) == 22
        assert body["physical_regression"] == "NOT RUN"
        assert body["trace_store"] == "READY"
        assert client.get("/api/supervisor/dataset", auth=auth).text == ""
        assert client.post(
            f"/api/supervisor/review/{uuid4()}", auth=auth,
            json={"verdict": "ACCEPT", "anonymous_text": "Ekspertiz istiyorum"},
        ).status_code == 422


def test_read_only_availability_uses_actual_slot_instants(monkeypatch, local_store):
    from backend.supervisor import runtime

    monkeypatch.setattr(runtime, "Session", local_store)
    with local_store.begin() as db:
        db.add_all([
            DbSlot(id="local-offset", starts_at="2026-11-13T23:40:00+03:00"),
            DbSlot(id="next-day", starts_at="2026-11-14T00:01:00+03:00"),
            DbSlot(id="occupied", starts_at="2026-11-13T18:00:00+00:00"),
            Vehicle(id="vehicle", description="Peugeot 3008"),
        ])
        db.flush()
        db.add(Appointment(
            slot_id="occupied", vehicle_id="vehicle", customer="Synthetic test",
            idempotency_key="occupied-test", confirmed=True,
        ))
    now = datetime(2026, 11, 13, 17, tzinfo=timezone.utc)
    assert runtime.free_slot_count(date(2026, 11, 13), now) == 1
