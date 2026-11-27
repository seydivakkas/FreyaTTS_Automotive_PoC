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
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from backend.core.configuration.contracts import ConfigSnapshot, SupervisorMode
from backend.core.configuration.feature_flags import FeatureFlagRegistry
from backend.core.contracts.common import ErrorCategory, ErrorInfo, Retryability, TurnRef
from backend.core.contracts.dialogue import (
    DialogueOutcome,
    DialogueResponse,
    ProviderMode,
    ToolReceipt,
    ToolReceiptStatus,
    VerifiedFactRef,
)
from backend.core.contracts.recognition import ASROutcome, ASRResult, ASRStatus
from backend.core.contracts.validation import require_safe_id, require_strict_int
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.deadlines import Clock, DeadlineBudget, SystemMonotonicClock
from backend.supervisor.context_manager import (
    CleanupReport,
    ContextManager,
    DialogueContextSnapshot,
    ProtectedRefs,
)
from backend.supervisor.contracts import ConversationContext, Intent, RouteState
from backend.supervisor.input_admission import (
    AdmissionDisposition,
    DialogueInputRef,
    InputAdmissionGate,
    InputAdmissionResult,
)
from backend.supervisor.intent_router import (
    HierarchicalIntentRouter,
    HierarchicalRouteDecision,
    decompose_multi_intent,
)
from backend.supervisor.llm_adapter import LLMAdapter, LLMBridgeResult
from backend.supervisor.orchestrator import RoutingResult, SupervisorOrchestrator
from backend.supervisor.policy import normalize_utterance
from backend.supervisor.rag_retriever import KnowledgeAnswer, OfflineRagRetriever
from backend.supervisor.response_composer import ResponseComposer
from backend.supervisor.response_validator import ResponseValidator
from backend.supervisor.slot_manager import (
    SlotDelta,
    SlotDeltaItem,
    SlotStatus,
    from_m05_entity_candidate,
    resolve_turkish_relative_date,
)
from backend.supervisor.specialist_registry import (
    QualityDecision,
    QualityEvaluator,
    SpecialistRegistry,
)
from backend.supervisor.state_adapter import DialogueDecision, StateAdapter, WorkflowStage
from backend.supervisor.telemetry import DialogueSpanTiming, DialogueTelemetryBridge
from backend.supervisor.workflow_adapter import WorkflowAdapter, WorkflowExecutionResult
from backend.supervisor.workflow_dag import WorkflowDagExecutor, WorkflowOutcome, WorkflowPlan
from backend.security.contracts import AccessContext, AuthStrength, EvidenceSource, PrincipalKind, PrincipalRef
from backend.security.principal import anonymous_principal

_AFFIRMATIVE_RE = re.compile(
    r"^\s*(?:evet(?:\s*,?\s*(?:onaylıyorum|tamam|olur))?|onaylıyorum|onay|tamam|uygun|kesinlikle|kabul\s+ediyorum)[.!?\s]*$",
    re.IGNORECASE,
)
_NEGATIVE_RE = re.compile(
    r"\b(?:hayır|vazgeçtim|istemiyorum|onaylamıyorum|kalsın|olmaz)\b",
    re.IGNORECASE,
)
_PLATE_RE = re.compile(r"\b(\d{2}\s*[A-ZÇĞİÖŞÜ]{1,3}\s*\d{2,4})\b", re.IGNORECASE)


class DialogueDeliveryStatus(StrEnum):
    """Atomic response delivery statuses to downstream F4 consumer."""

    ADMITTED = "ADMITTED"
    REJECTED_STALE_SESSION = "REJECTED_STALE_SESSION"
    REJECTED_STALE_TURN = "REJECTED_STALE_TURN"
    REJECTED_CANCELED = "REJECTED_CANCELED"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    REJECTED_BACKPRESSURE = "REJECTED_BACKPRESSURE"
    REJECTED_CLOSED = "REJECTED_CLOSED"


@dataclass(frozen=True, slots=True)
class DialogueDelivery:
    """Delivery observation separate from ToolReceipt and ASR outcomes."""

    delivered: bool
    status: DialogueDeliveryStatus
    response: DialogueResponse | None = None
    consumer_seq: int | None = None


class DialogueConsumerPort(Protocol):
    """Downstream F4-A / transport consumer boundary."""

    def admit_response(
        self,
        response: DialogueResponse,
        *,
        expected_session_id: str,
        expected_turn_id: int | None,
        cancellation_scope: CancellationScope | None = None,
    ) -> DialogueDelivery: ...


class BoundedDialogueConsumer:
    """Deterministic bounded F4 consumer enforcing atomic scope + dedup + backpressure."""

    def __init__(self, *, max_items: int = 16) -> None:
        require_strict_int(max_items, "max_items", minimum=1)
        self.max_items = max_items
        self._lock = threading.RLock()
        self._queue: deque[DialogueResponse] = deque()
        self._seen_response_ids: set[str] = set()
        self._closed = False
        self._seq = 0

    @property
    def items(self) -> tuple[DialogueResponse, ...]:
        with self._lock:
            return tuple(self._queue)

    def close(self) -> None:
        with self._lock:
            self._closed = True

    def pop_next(self) -> DialogueResponse | None:
        with self._lock:
            return self._queue.popleft() if self._queue else None

    def admit_response(
        self,
        response: DialogueResponse,
        *,
        expected_session_id: str,
        expected_turn_id: int | None,
        cancellation_scope: CancellationScope | None = None,
    ) -> DialogueDelivery:
        with self._lock:
            if self._closed:
                return DialogueDelivery(False, DialogueDeliveryStatus.REJECTED_CLOSED, response=response)
            if response.envelope.session_id != expected_session_id:
                return DialogueDelivery(False, DialogueDeliveryStatus.REJECTED_STALE_SESSION, response=response)
            if cancellation_scope is not None and cancellation_scope.is_cancel_requested:
                return DialogueDelivery(False, DialogueDeliveryStatus.REJECTED_CANCELED, response=response)
            if expected_turn_id is not None and response.envelope.turn_id != expected_turn_id:
                return DialogueDelivery(False, DialogueDeliveryStatus.REJECTED_STALE_TURN, response=response)
            if response.response_id in self._seen_response_ids:
                return DialogueDelivery(False, DialogueDeliveryStatus.REJECTED_DUPLICATE, response=response)
            if len(self._queue) >= self.max_items:
                return DialogueDelivery(False, DialogueDeliveryStatus.REJECTED_BACKPRESSURE, response=response)
            self._seq += 1
            self._seen_response_ids.add(response.response_id)
            self._queue.append(response)
            return DialogueDelivery(True, DialogueDeliveryStatus.ADMITTED, response=response, consumer_seq=self._seq)


@dataclass(frozen=True, slots=True)
class ShadowComparison:
    """Zero-side-effect shadow observation comparing guarded decision against primary."""

    mode: SupervisorMode
    shadow_intent: Intent | None
    shadow_stage: WorkflowStage
    shadow_route_state: RouteState
    extra_effects_executed: int = 0
    extra_private_reads: int = 0
    extra_llm_calls: int = 0
    approvals_consumed: int = 0


@dataclass(frozen=True, slots=True)
class DialogueTurnOutcome:
    """Complete immutable outcome of a single F3-A facade turn."""

    mode: SupervisorMode
    admission: InputAdmissionResult
    decision: DialogueDecision | None
    response: DialogueResponse | None
    delivery: DialogueDelivery | None
    receipt: ToolReceipt | None
    snapshot: DialogueContextSnapshot | None
    shadow: ShadowComparison | None = None
    llm_result: LLMBridgeResult | None = None


_STATIC_PUBLIC_RESPONSES: dict[Intent, tuple[str, str]] = {
    Intent.GREETING: ("Merhaba, size nasıl yardımcı olabilirim?", "GREETING"),
    Intent.GOODBYE: ("Görüşmek üzere, iyi günler dileriz.", "GOODBYE"),
    Intent.CLARIFICATION_REQUEST: ("Hangi kısmı açıklamamı istersiniz?", "CLARIFICATION"),
    Intent.ROADSIDE_EMERGENCY: (
        "Acil bir tehlike varsa lütfen aracınızı güvenli bir yere çekip 112 acil yardım hattını arayın.",
        "SAFETY_ESCALATION",
    ),
    Intent.WARNING_LIGHT_QUESTION: (
        "Gösterge uyarı ışığı için doğrulanmış bir teknik arıza teşhisi veremiyorum; yetkili servis kontrolü önerilir.",
        "TECHNICAL_CAUTION",
    ),
    Intent.SYMPTOM_QUESTION: (
        "Araç belirtileri için uzaktan kesin arıza teşhisi koyamıyorum; güvenli kontrol için servis randevusu alabilirsiniz.",
        "TECHNICAL_CAUTION",
    ),
}


class DialogueFacade:
    """
    Single F3-A composition root & route selector.

    Selects exactly one route per admitted input based on M03 ConfigSnapshot /
    SupervisorMode (OFF, SHADOW, GUARDED), enforces M07 at every protected boundary,
    and delivers immutable M01 DialogueResponse atomically to the F4 consumer port.
    """

    def __init__(
        self,
        *,
        config_snapshot: ConfigSnapshot | None = None,
        mode: SupervisorMode | None = None,
        input_gate: InputAdmissionGate | None = None,
        context_manager: ContextManager | None = None,
        state_adapter: StateAdapter | None = None,
        orchestrator: SupervisorOrchestrator | None = None,
        llm_adapter: LLMAdapter | None = None,
        workflow_adapter: WorkflowAdapter | None = None,
        response_composer: ResponseComposer | None = None,
        response_validator: ResponseValidator | None = None,
        telemetry: DialogueTelemetryBridge | None = None,
        clock: Clock | None = None,
        utc_now_fn: Callable[[], datetime] | None = None,
        legacy_handler: Callable[[str, str], str] | None = None,
        vehicles: tuple[tuple[str, str], ...] = (),
        intent_router: HierarchicalIntentRouter | None = None,
        specialist_registry: SpecialistRegistry | None = None,
        rag_retriever: OfflineRagRetriever | None = None,
        quality_evaluator: QualityEvaluator | None = None,
        dag_executor: WorkflowDagExecutor | None = None,
    ) -> None:
        self._config_snapshot = config_snapshot
        if mode is not None:
            self._mode = mode
        elif config_snapshot is not None:
            self._mode = FeatureFlagRegistry.from_snapshot(config_snapshot).get_mode("supervisor_mode")
        else:
            self._mode = SupervisorMode.GUARDED

        self.clock: Clock = clock or SystemMonotonicClock()
        self._utc_now_fn = utc_now_fn or (lambda: datetime.now(timezone.utc))
        self.input_gate = input_gate or InputAdmissionGate()
        self.context_manager = context_manager or ContextManager()
        self.state_adapter = state_adapter or StateAdapter()
        self.orchestrator = orchestrator or SupervisorOrchestrator(vehicles=vehicles)
        self.llm_adapter = llm_adapter
        self.workflow_adapter = workflow_adapter
        self.response_composer = response_composer or ResponseComposer(clock=self.clock)
        self.response_validator = response_validator or ResponseValidator()
        self.telemetry = telemetry or DialogueTelemetryBridge(clock=self.clock)
        self._legacy_handler = legacy_handler
        self._vehicles = vehicles
        self.intent_router = intent_router or HierarchicalIntentRouter()
        self.specialist_registry = specialist_registry or SpecialistRegistry()
        self.rag_retriever = rag_retriever
        self.quality_evaluator = quality_evaluator or QualityEvaluator(validator=self.response_validator)
        self.dag_executor = dag_executor or WorkflowDagExecutor()

    @property
    def mode(self) -> SupervisorMode:
        return self._mode

    def open_session(
        self,
        *,
        session_id: str,
        incarnation_id: str,
        principal_ref: str = "anonymous",
        subject_ref: str | None = None,
        model_revision: str | None = None,
        lexicon_revision: str | None = None,
    ) -> DialogueContextSnapshot:
        cfg_rev = self._config_snapshot.config_revision if self._config_snapshot else None
        return self.context_manager.open_session(
            session_id=session_id,
            incarnation_id=incarnation_id,
            principal_ref=principal_ref,
            subject_ref=subject_ref,
            config_revision=cfg_rev,
            model_revision=model_revision,
            lexicon_revision=lexicon_revision,
        )

    def close_session(self, session_id: str, incarnation_id: str) -> CleanupReport:
        """Close transient context and revoke any pending unused M07 confirmation challenges."""
        report = self.context_manager.close_session(session_id, incarnation_id)
        if report.revoked_challenge_id and self.workflow_adapter is not None:
            self.workflow_adapter.revoke_confirmation(report.revoked_challenge_id, reason="session_closed")
        return report

    def _run_shadow(
        self,
        routing_result: RoutingResult,
        snapshot: DialogueContextSnapshot,
        *,
        is_aff: bool,
        is_neg: bool,
    ) -> ShadowComparison:
        # Pure in-memory shadow evaluation: zero tools, zero DB reads, zero approvals, zero LLM calls.
        shadow_dec = self.state_adapter.decide(
            routing_result,
            snapshot,
            is_confirmation_affirmative=is_aff,
            is_confirmation_negative=is_neg,
        )
        return ShadowComparison(
            mode=SupervisorMode.SHADOW,
            shadow_intent=shadow_dec.intent,
            shadow_stage=shadow_dec.workflow_stage,
            shadow_route_state=shadow_dec.route_state,
            extra_effects_executed=0,
            extra_private_reads=0,
            extra_llm_calls=0,
            approvals_consumed=0,
        )

    def _deliver_atomically(
        self,
        response: DialogueResponse,
        *,
        consumer: DialogueConsumerPort | None,
        expected_session_id: str,
        expected_turn_id: int,
        cancellation_scope: CancellationScope | None,
    ) -> DialogueDelivery | None:
        if consumer is None:
            return None
        return consumer.admit_response(
            response,
            expected_session_id=expected_session_id,
            expected_turn_id=expected_turn_id,
            cancellation_scope=cancellation_scope,
        )

    async def process_asr_turn(
        self,
        asr_payload: object,
        *,
        session_id: str,
        incarnation_id: str,
        turn_id: int,
        cancellation_scope: CancellationScope | None = None,
        principal: PrincipalRef | None = None,
        consumer: DialogueConsumerPort | None = None,
        allowed_asr_producers: frozenset[str] | None = None,
        use_llm_fallback: bool = False,
        llm_deadline: DeadlineBudget | None = None,
        idempotency_key: str | None = None,
        presentation_confirmed: bool = True,
        target_customer_id: str | None = None,
    ) -> DialogueTurnOutcome:
        """Process one ASRResult input end-to-end under strict F3-A / M07 invariants."""
        t_start_ns = self.clock.monotonic_ns()
        domain = self.clock.clock_domain

        admission = self.input_gate.admit_asr(
            asr_payload,
            expected_session_id=session_id,
            incarnation_id=incarnation_id,
            expected_turn_id=turn_id,
            cancellation_scope=cancellation_scope,
            allowed_producers=allowed_asr_producers,
        )
        snap = self.context_manager.get_snapshot(session_id, incarnation_id)

        if not admission.admitted:
            # Non-final ASR (PARTIAL / STABLE_PREFIX) must never mutate state or dispatch effects.
            if admission.disposition == AdmissionDisposition.REJECTED_NON_FINAL:
                return DialogueTurnOutcome(
                    mode=self._mode,
                    admission=admission,
                    decision=None,
                    response=None,
                    delivery=None,
                    receipt=None,
                    snapshot=snap,
                )
            # Non-OK FINAL ASR (NO_SPEECH / ERROR / REJECTED) emits safe non-OK response if scope active.
            if admission.disposition == AdmissionDisposition.REJECTED_NON_OK and admission.asr_result is not None:
                safe_msg = (
                    "Sizi duyamadım, lütfen tekrar eder misiniz?"
                    if admission.asr_result.outcome == ASROutcome.NO_SPEECH
                    else "Ses algılama sırasında bir sorun oluştu; lütfen tekrar söyler misiniz?"
                )
                resp = self.response_composer.compose(
                    session_id=session_id,
                    trace_id=admission.asr_result.envelope.trace_id,
                    turn_id=turn_id,
                    speech_text=safe_msg,
                    speech_act="ASR_NON_OK_REPROMPT",
                    state_revision=snap.state_revision if snap else 0,
                    outcome=DialogueOutcome.CLARIFICATION_REQUIRED,
                    source_asr_revision=admission.asr_result.revision,
                    error=admission.error,
                )
                delivery = self._deliver_atomically(
                    resp,
                    consumer=consumer,
                    expected_session_id=session_id,
                    expected_turn_id=turn_id,
                    cancellation_scope=cancellation_scope,
                )
                return DialogueTurnOutcome(
                    mode=self._mode,
                    admission=admission,
                    decision=None,
                    response=resp,
                    delivery=delivery,
                    receipt=None,
                    snapshot=snap,
                )
            return DialogueTurnOutcome(
                mode=self._mode,
                admission=admission,
                decision=None,
                response=None,
                delivery=None,
                receipt=None,
                snapshot=snap,
            )

        assert admission.asr_result is not None
        assert admission.input_ref is not None
        asr_res = admission.asr_result
        raw_text = asr_res.raw_transcript  # Preserve exact raw transcript

        if snap is None:
            snap = self.open_session(session_id=session_id, incarnation_id=incarnation_id)

        # Record user turn in bounded history before routing.
        snap = self.context_manager.append_turn(
            session_id=session_id,
            incarnation_id=incarnation_id,
            turn_id=turn_id,
            role="user",
            text=raw_text,
            monotonic_ns=self.clock.monotonic_ns(),
        )

        # OFF mode: single authorized legacy path preserving external shape.
        if self._mode == SupervisorMode.OFF:
            legacy_text = (
                self._legacy_handler(session_id, raw_text)
                if self._legacy_handler is not None
                else "Talebiniz eski diyalog hattı üzerinden işlendi."
            )
            resp = self.response_composer.compose(
                session_id=session_id,
                trace_id=asr_res.envelope.trace_id,
                turn_id=turn_id,
                speech_text=legacy_text,
                speech_act="LEGACY_DELEGATED",
                state_revision=snap.state_revision,
                outcome=DialogueOutcome.OK,
                source_asr_revision=asr_res.revision,
            )
            delivery = self._deliver_atomically(
                resp,
                consumer=consumer,
                expected_session_id=session_id,
                expected_turn_id=turn_id,
                cancellation_scope=cancellation_scope,
            )
            return DialogueTurnOutcome(
                mode=self._mode,
                admission=admission,
                decision=None,
                response=resp,
                delivery=delivery,
                receipt=None,
                snapshot=snap,
            )

        # Route via existing SupervisorOrchestrator (rules-first).
        now_utc = self._utc_now_fn()
        try:
            ctx_uuid = str(uuid4())
            from uuid import UUID

            try:
                parsed_sid = UUID(session_id)
            except ValueError:
                parsed_sid = UUID(ctx_uuid)
        except Exception:
            parsed_sid = uuid4()

        active_intent = None
        if snap.active_workflow:
            try:
                active_intent = Intent(snap.active_workflow)
            except ValueError:
                active_intent = None

        conv_ctx = ConversationContext(
            session_id=parsed_sid,
            turn_at=now_utc,
            active_task=active_intent,
        )
        routing_result = await self.orchestrator.route(
            raw_text,
            conv_ctx,
            is_final=True,
        )
        t_route_end_ns = self.clock.monotonic_ns()

        # Optional M06 P3 LLM fallback ONLY in GUARDED mode when rule routing returned UNKNOWN.
        llm_result: LLMBridgeResult | None = None
        t_llm_start_ns: int | None = None
        t_llm_end_ns: int | None = None
        if (
            self._mode == SupervisorMode.GUARDED
            and use_llm_fallback
            and self.llm_adapter is not None
            and routing_result.decision.route_state == RouteState.UNKNOWN
            and cancellation_scope is not None
        ):
            t_llm_start_ns = self.clock.monotonic_ns()
            llm_result = await self.llm_adapter.propose(
                utterance=raw_text,
                session_id=session_id,
                turn_ref=TurnRef(session_id, turn_id),
                generation_ref=None,
                cancellation_scope=cancellation_scope,
                deadline=llm_deadline,
                safe_slots={k: str(v.value) for k, v in snap.slots.items() if v.value is not None},
            )
            t_llm_end_ns = self.clock.monotonic_ns()

        # Check cancellation after async await before mutating ephemeral context!
        if cancellation_scope is not None and cancellation_scope.is_cancel_requested:
            return DialogueTurnOutcome(
                mode=self._mode,
                admission=admission,
                decision=None,
                response=None,
                delivery=DialogueDelivery(False, DialogueDeliveryStatus.REJECTED_CANCELED),
                receipt=None,
                snapshot=snap,
                llm_result=llm_result,
            )

        is_aff = bool(_AFFIRMATIVE_RE.match(normalize_utterance(raw_text)))
        is_neg = bool(_NEGATIVE_RE.search(normalize_utterance(raw_text)))

        # SHADOW mode: observe strict routing without mutating protected state, DB, approvals, or extra LLM calls.
        if self._mode == SupervisorMode.SHADOW:
            shadow_comp = self._run_shadow(routing_result, snap, is_aff=is_aff, is_neg=is_neg)
            primary_text = (
                self._legacy_handler(session_id, raw_text)
                if self._legacy_handler is not None
                else "Merhaba, size nasıl yardımcı olabilirim?"
            )
            resp = self.response_composer.compose(
                session_id=session_id,
                trace_id=asr_res.envelope.trace_id,
                turn_id=turn_id,
                speech_text=primary_text,
                speech_act="SHADOW_PRIMARY",
                state_revision=snap.state_revision,
                outcome=DialogueOutcome.OK,
                source_asr_revision=asr_res.revision,
            )
            delivery = self._deliver_atomically(
                resp,
                consumer=consumer,
                expected_session_id=session_id,
                expected_turn_id=turn_id,
                cancellation_scope=cancellation_scope,
            )
            return DialogueTurnOutcome(
                mode=self._mode,
                admission=admission,
                decision=None,
                response=resp,
                delivery=delivery,
                receipt=None,
                snapshot=snap,
                shadow=shadow_comp,
            )

        # Extract candidate slots from M05 entities, relative dates, plates, and orchestrator slots.
        slot_changes: list[SlotDeltaItem] = []
        focus_refs: list[str] = []
        vehicle_cands = [e for e in asr_res.entities if e.entity_type == "vehicle_model"]
        if len(vehicle_cands) > 1:
            # Multiple ambiguous model candidates -> ask clarification without arbitrary choice.
            names = ", ".join(c.canonical_value or c.raw_value for c in vehicle_cands)
            resp = self.response_composer.compose(
                session_id=session_id,
                trace_id=asr_res.envelope.trace_id,
                turn_id=turn_id,
                speech_text=f"Birden fazla araç modeli algıladım ({names}); hangisini kastediyorsunuz?",
                speech_act="CLARIFY_CANDIDATE",
                state_revision=snap.state_revision,
                outcome=DialogueOutcome.CLARIFICATION_REQUIRED,
                source_asr_revision=asr_res.revision,
                focus_entity_refs=tuple(c.entity_id for c in vehicle_cands),
            )
            delivery = self._deliver_atomically(
                resp,
                consumer=consumer,
                expected_session_id=session_id,
                expected_turn_id=turn_id,
                cancellation_scope=cancellation_scope,
            )
            return DialogueTurnOutcome(
                mode=self._mode,
                admission=admission,
                decision=None,
                response=resp,
                delivery=delivery,
                receipt=None,
                snapshot=snap,
                llm_result=llm_result,
            )
        elif len(vehicle_cands) == 1:
            ent = vehicle_cands[0]
            focus_refs.append(ent.entity_id)
            sv = from_m05_entity_candidate(ent, value_revision=snap.state_revision)
            slot_changes.append(
                SlotDeltaItem(
                    key="vehicle_model",
                    value=sv.value,
                    raw_value=sv.raw_value,
                    status=SlotStatus.CANDIDATE,
                    source_type="m05_lexicon",
                    source_ref=ent.entity_id,
                    evidence_ref=ent.entity_id,
                )
            )

        plate_match = _PLATE_RE.search(raw_text)
        if plate_match:
            raw_plate = plate_match.group(1).strip()
            slot_changes.append(
                SlotDeltaItem(
                    key="vehicle_plate",
                    value=raw_plate,
                    raw_value=raw_plate,
                    status=SlotStatus.CANDIDATE,
                    source_type="asr_final",
                    source_ref=admission.input_ref.claim_id,
                )
            )

        rel_date, date_err = resolve_turkish_relative_date(raw_text, reference_utc=now_utc)
        if rel_date is not None:
            slot_changes.append(
                SlotDeltaItem(
                    key="preferred_date",
                    value=rel_date,
                    raw_value=raw_text,
                    status=SlotStatus.VALIDATED,
                    source_type="relative_date",
                    source_ref=admission.input_ref.claim_id,
                )
            )
        elif date_err in {"date.ambiguous_multiple", "date.malformed"}:
            resp = self.response_composer.compose(
                session_id=session_id,
                trace_id=asr_res.envelope.trace_id,
                turn_id=turn_id,
                speech_text="Belirttiğiniz tarih net değil; lütfen gün ve tarihi açıkça paylaşır mısınız?",
                speech_act="CLARIFY_DATE",
                state_revision=snap.state_revision,
                outcome=DialogueOutcome.CLARIFICATION_REQUIRED,
                source_asr_revision=asr_res.revision,
            )
            delivery = self._deliver_atomically(
                resp,
                consumer=consumer,
                expected_session_id=session_id,
                expected_turn_id=turn_id,
                cancellation_scope=cancellation_scope,
            )
            return DialogueTurnOutcome(
                mode=self._mode,
                admission=admission,
                decision=None,
                response=resp,
                delivery=delivery,
                receipt=None,
                snapshot=snap,
                llm_result=llm_result,
            )

        if slot_changes:
            delta = SlotDelta(
                expected_state_revision=snap.state_revision,
                changes=tuple(slot_changes),
                source_ref=admission.input_ref.claim_id,
                reason="asr_slot_extraction",
            )
            mut_out, snap = self.context_manager.apply_slot_delta(
                session_id=session_id,
                incarnation_id=incarnation_id,
                delta=delta,
            )
            if mut_out.invalidate_confirmation and snap.protected_refs.pending_challenge_id:
                if self.workflow_adapter is not None:
                    self.workflow_adapter.revoke_confirmation(
                        snap.protected_refs.pending_challenge_id,
                        reason="slot_material_change",
                    )

        decision = self.state_adapter.decide(
            routing_result,
            snap,
            is_confirmation_affirmative=is_aff,
            is_confirmation_negative=is_neg,
        )

        if decision.intent is not None and snap.active_workflow != decision.intent.value:
            _, snap = self.context_manager.update_runtime_state(
                session_id=session_id,
                incarnation_id=incarnation_id,
                expected_state_revision=snap.state_revision,
                active_workflow=decision.intent.value,
                workflow_stage=decision.workflow_stage.value,
                bump_revision=False,
            )

        eff_principal = principal or anonymous_principal()
        access = AccessContext(
            session_id=session_id,
            principal=eff_principal,
            channel="voice",
            state_revision=snap.state_revision,
            trace_id=asr_res.envelope.trace_id,
            asr_status=asr_res.status,
        )

        # Negative / revocation of pending confirmation.
        if decision.proposed_action == "revoke_pending_confirmation":
            if snap.protected_refs.pending_challenge_id and self.workflow_adapter is not None:
                self.workflow_adapter.revoke_confirmation(
                    snap.protected_refs.pending_challenge_id,
                    reason="customer_declined",
                )
                _, snap = self.context_manager.update_runtime_state(
                    session_id=session_id,
                    incarnation_id=incarnation_id,
                    expected_state_revision=snap.state_revision,
                    workflow_stage=WorkflowStage.SAFE_RECOVERY.value,
                    protected_refs=ProtectedRefs(
                        pending_challenge_id=None,
                        pending_operation_id=snap.protected_refs.pending_operation_id,
                        pending_idempotency_key=snap.protected_refs.pending_idempotency_key,
                        active_booking_ref=snap.protected_refs.active_booking_ref,
                        availability_valid=snap.protected_refs.availability_valid,
                    ),
                )
            resp = self.response_composer.compose(
                session_id=session_id,
                trace_id=asr_res.envelope.trace_id,
                turn_id=turn_id,
                speech_text="Anlaşıldı, bekleyen işlem iptal edildi; başka nasıl yardımcı olabilirim?",
                speech_act="CONFIRMATION_REVOKED",
                state_revision=snap.state_revision,
                outcome=DialogueOutcome.OK,
                source_asr_revision=asr_res.revision,
            )
            delivery = self._deliver_atomically(
                resp,
                consumer=consumer,
                expected_session_id=session_id,
                expected_turn_id=turn_id,
                cancellation_scope=cancellation_scope,
            )
            return DialogueTurnOutcome(
                mode=self._mode,
                admission=admission,
                decision=decision,
                response=resp,
                delivery=delivery,
                receipt=None,
                snapshot=snap,
                llm_result=llm_result,
            )

        # No-tool fast deterministic responses (greeting, goodbye, emergency, repeat, missing slots).
        if decision.no_tool_response:
            if decision.intent == Intent.REPEAT_REQUEST:
                speech = self.context_manager.get_last_reply(session_id, incarnation_id) or "Hangi kısmı tekrar etmemi istersiniz?"
                act = "REPEAT"
                out_status = DialogueOutcome.OK
            elif decision.intent in _STATIC_PUBLIC_RESPONSES:
                speech, act = _STATIC_PUBLIC_RESPONSES[decision.intent]
                out_status = DialogueOutcome.OK
            elif decision.route_state == RouteState.OUT_OF_SCOPE:
                speech = "Otomotiv ve servis konularında yardımcı olabilirim."
                act = "OUT_OF_SCOPE"
                out_status = DialogueOutcome.OK
            elif decision.missing_slots:
                missing_name = decision.missing_slots[0]
                if missing_name == "preferred_date":
                    speech = "Servis için hangi günü tercih edersiniz?"
                elif missing_name == "vehicle_model":
                    speech = "Aracınızın marka ve modelini paylaşır mısınız?"
                else:
                    speech = "Devam edebilmek için eksik bilgiyi paylaşır mısınız?"
                act = "QUESTION"
                out_status = DialogueOutcome.CLARIFICATION_REQUIRED
            else:
                speech = "Size nasıl yardımcı olabilirim? Talebinizi biraz daha açık söyler misiniz?"
                act = "CLARIFY"
                out_status = DialogueOutcome.CLARIFICATION_REQUIRED

            resp = self.response_composer.compose(
                session_id=session_id,
                trace_id=asr_res.envelope.trace_id,
                turn_id=turn_id,
                speech_text=speech,
                speech_act=act,
                state_revision=snap.state_revision,
                outcome=out_status,
                source_asr_revision=asr_res.revision,
                focus_entity_refs=tuple(focus_refs),
            )
            validated = self.response_validator.validate(resp)
            self.context_manager.append_turn(
                session_id=session_id,
                incarnation_id=incarnation_id,
                turn_id=turn_id,
                role="assistant",
                text=validated.response.speech_text,
                monotonic_ns=self.clock.monotonic_ns(),
            )
            delivery = self._deliver_atomically(
                validated.response,
                consumer=consumer,
                expected_session_id=session_id,
                expected_turn_id=turn_id,
                cancellation_scope=cancellation_scope,
            )
            t_resp_end_ns = self.clock.monotonic_ns()
            self.telemetry.record_turn_metrics(
                timing=DialogueSpanTiming(
                    clock_domain=domain,
                    routing_ms=DialogueSpanTiming.compute_ms(
                        start_ns=t_start_ns, start_domain=domain, end_ns=t_route_end_ns, end_domain=domain
                    ),
                    llm_ms=DialogueSpanTiming.compute_ms(
                        start_ns=t_llm_start_ns, start_domain=domain, end_ns=t_llm_end_ns, end_domain=domain
                    ),
                    tool_ms=None,
                    response_ms=DialogueSpanTiming.compute_ms(
                        start_ns=t_start_ns, start_domain=domain, end_ns=t_resp_end_ns, end_domain=domain
                    ),
                ),
                labels={"mode": self._mode.value, "channel": "voice"},
                outcome=validated.response.outcome.value,
            )
            return DialogueTurnOutcome(
                mode=self._mode,
                admission=admission,
                decision=decision,
                response=validated.response,
                delivery=delivery,
                receipt=None,
                snapshot=snap,
                llm_result=llm_result,
            )

        # Tool / workflow execution strictly via M07 WorkflowAdapter (fail-closed if unavailable!).
        if self.workflow_adapter is None:
            blocked_rec = ToolReceipt(
                operation_id=f"hold-{uuid4().hex[:12]}",
                tool_id=decision.proposed_tool or "workflow.unavailable",
                status=ToolReceiptStatus.BLOCKED,
                provider_mode=ProviderMode.UNKNOWN,
                verified_result=False,
                error=ErrorInfo(
                    code="policy.gateway_unavailable",
                    category=ErrorCategory.SECURITY,
                    retryable=Retryability.NO,
                    safe_message="Güvenlik geçidi hazır olmadığı için işlem durduruldu.",
                ),
            )
            resp = self.response_composer.compose_from_receipt(
                session_id=session_id,
                trace_id=asr_res.envelope.trace_id,
                turn_id=turn_id,
                receipt=blocked_rec,
                state_revision=snap.state_revision,
                source_asr_revision=asr_res.revision,
            )
            delivery = self._deliver_atomically(
                resp,
                consumer=consumer,
                expected_session_id=session_id,
                expected_turn_id=turn_id,
                cancellation_scope=cancellation_scope,
            )
            return DialogueTurnOutcome(
                mode=self._mode,
                admission=admission,
                decision=decision,
                response=resp,
                delivery=delivery,
                receipt=blocked_rec,
                snapshot=snap,
                llm_result=llm_result,
            )

        t_tool_start_ns = self.clock.monotonic_ns()
        wf_res: WorkflowExecutionResult
        if decision.proposed_tool == "availability.read":
            pref_date_val = str(snap.slots["preferred_date"].value)
            wf_res = self.workflow_adapter.read_availability(
                access=access,
                target_day=datetime.fromisoformat(pref_date_val).date(),
                now_utc=now_utc,
            )
        elif decision.proposed_tool in {"booking.read_status", "customer.read_record"}:
            cust_target = target_customer_id or eff_principal.principal_id
            wf_res = self.workflow_adapter.read_protected_record(
                access=access,
                tool_id=decision.proposed_tool,
                target_customer_id=cust_target,
                booking_id=str(snap.slots["booking_id"].value) if "booking_id" in snap.slots else None,
            )
        elif decision.proposed_tool == "operator.transfer_request":
            wf_res = self.workflow_adapter.request_operator_transfer(
                access=access,
                reason="customer_requested",
            )
        else:
            # Critical write path requires active presented+approved challenge + idempotency key.
            terms = {k: str(v.value) for k, v in snap.slots.items() if v.value is not None}
            challenge_id = snap.protected_refs.pending_challenge_id
            if is_aff and challenge_id is not None:
                self.workflow_adapter.approve_confirmation(
                    challenge_id=challenge_id,
                    access=access,
                    terms=terms,
                    is_final_asr=True,
                    presentation_confirmed=presentation_confirmed,
                )
            wf_res = self.workflow_adapter.execute_mutation(
                access=access,
                tool_id=decision.proposed_tool or "booking.create",
                action=decision.proposed_action or "create_booking",
                idempotency_key=idempotency_key or f"idem-{session_id}-{turn_id}",
                terms=terms,
                challenge_id=challenge_id,
                target_customer_id=target_customer_id,
                presentation_confirmed=presentation_confirmed,
            )
        t_tool_end_ns = self.clock.monotonic_ns()

        if cancellation_scope is not None and cancellation_scope.is_cancel_requested:
            # Even if canceled, durable receipt remains in M07; block stale conversational delivery.
            return DialogueTurnOutcome(
                mode=self._mode,
                admission=admission,
                decision=decision,
                response=None,
                delivery=DialogueDelivery(False, DialogueDeliveryStatus.REJECTED_CANCELED),
                receipt=wf_res.receipt,
                snapshot=snap,
                llm_result=llm_result,
            )

        if decision.proposed_tool == "availability.read" and wf_res.receipt.status == ToolReceiptStatus.COMMITTED:
            avail_count = int(wf_res.data.get("available_count", 0))
            avail_text = (
                f"{wf_res.data.get('date')} tarihinde {avail_count} uygun saat görünüyor; onay için saat seçip kimliğinizi doğrulamamız gerekiyor."
                if avail_count > 0
                else f"{wf_res.data.get('date')} tarihinde uygun saat bulunmuyor."
            )
            resp = self.response_composer.compose(
                session_id=session_id,
                trace_id=asr_res.envelope.trace_id,
                turn_id=turn_id,
                speech_text=avail_text,
                speech_act="AVAILABILITY_OPTIONS",
                state_revision=snap.state_revision,
                outcome=DialogueOutcome.OK,
                source_asr_revision=asr_res.revision,
                verified_fact_refs=wf_res.verified_facts,
                tool_receipt_refs=(wf_res.receipt.operation_id,),
            )
        else:
            resp = self.response_composer.compose_from_receipt(
                session_id=session_id,
                trace_id=asr_res.envelope.trace_id,
                turn_id=turn_id,
                receipt=wf_res.receipt,
                state_revision=snap.state_revision,
                source_asr_revision=asr_res.revision,
                verified_fact_refs=wf_res.verified_facts,
                details=dict(wf_res.data),
            )

        validated = self.response_validator.validate(
            resp,
            receipts=(wf_res.receipt,),
            authorized_dates=(str(wf_res.data["date"]),) if "date" in wf_res.data else (),
            authorized_booking_refs=(str(wf_res.data["reference_code"]),) if "reference_code" in wf_res.data else (),
        )
        delivery = self._deliver_atomically(
            validated.response,
            consumer=consumer,
            expected_session_id=session_id,
            expected_turn_id=turn_id,
            cancellation_scope=cancellation_scope,
        )
        t_resp_end_ns = self.clock.monotonic_ns()
        self.telemetry.record_turn_metrics(
            timing=DialogueSpanTiming(
                clock_domain=domain,
                routing_ms=DialogueSpanTiming.compute_ms(
                    start_ns=t_start_ns, start_domain=domain, end_ns=t_route_end_ns, end_domain=domain
                ),
                llm_ms=DialogueSpanTiming.compute_ms(
                    start_ns=t_llm_start_ns, start_domain=domain, end_ns=t_llm_end_ns, end_domain=domain
                ),
                tool_ms=DialogueSpanTiming.compute_ms(
                    start_ns=t_tool_start_ns, start_domain=domain, end_ns=t_tool_end_ns, end_domain=domain
                ),
                response_ms=DialogueSpanTiming.compute_ms(
                    start_ns=t_start_ns, start_domain=domain, end_ns=t_resp_end_ns, end_domain=domain
                ),
            ),
            labels={
                "mode": self._mode.value,
                "provider_mode": wf_res.receipt.provider_mode.value,
                "channel": "voice",
            },
            outcome=validated.response.outcome.value,
        )
        return DialogueTurnOutcome(
            mode=self._mode,
            admission=admission,
            decision=decision,
            response=validated.response,
            delivery=delivery,
            receipt=wf_res.receipt,
            snapshot=snap,
            llm_result=llm_result,
        )
