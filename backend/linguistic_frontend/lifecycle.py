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
from typing import Awaitable, Callable

from backend.core.contracts.common import GenerationRef, TurnRef
from backend.core.contracts.dialogue import DialogueResponse
from backend.core.contracts.synthesis import SynthesisPlan
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.result_admission import AdmissionStatus
from backend.core.runtime.session_context import SessionContext, SessionLifecycleState
from backend.linguistic_frontend.input_validator import PlanningOutcome
from backend.linguistic_frontend.pipeline import LinguisticFrontendPipeline, PreparationResult


@dataclass(frozen=True, slots=True)
class LifecycleDeliveryResult:
    """Atomic M02-fenced plan preparation and delivery result."""

    admitted: bool
    admission_status: AdmissionStatus
    outcome: PlanningOutcome
    plan: SynthesisPlan | None = None
    generation_ref: GenerationRef | None = None
    reason_code: str = "OK"
    preparation: PreparationResult | None = None


class LinguisticPreparationCoordinator:
    """
    Coordinates M02 session/turn/generation allocation and atomic fence delivery
    without holding session locks during pure CPU linguistic preparation.
    """

    def __init__(self, pipeline: LinguisticFrontendPipeline) -> None:
        self._pipeline = pipeline

    async def prepare_and_admit(
        self,
        session: SessionContext,
        response: object,
        *,
        turn_ref: TurnRef | None = None,
        pre_hook: Callable[[], Awaitable[None]] | None = None,
        mid_hook: Callable[[GenerationRef, CancellationScope], Awaitable[None]] | None = None,
        plan_revision: int = 0,
        requested_seed: int | None = None,
        requested_profile_id: str | None = None,
        experimental_seeds_enabled: bool = False,
        on_admit: Callable[[SynthesisPlan], None] | None = None,
    ) -> LifecycleDeliveryResult:
        """
        Execute F4-A preparation bound to M02 session/turn/generation lifecycle:
        1. Pre-check response & session/cancellation BEFORE allocating a generation.
        2. Pin snapshot & allocate generation under session lock.
        3. Release session lock and run pure CPU linguistic pipeline.
        4. Atomically verify M02 fence (session active, scope active, generation active)
           before invoking `on_admit` or committing dedup record.
        """
        # Step 1: Pre-validate response before allocating generation (avoid wasteful gen alloc)
        if session.lifecycle_state != SessionLifecycleState.ACTIVE or session.root_scope.is_cancel_requested:
            return LifecycleDeliveryResult(
                admitted=False,
                admission_status=AdmissionStatus.CANCELED if session.root_scope.is_cancel_requested else AdmissionStatus.CLOSED,
                outcome=PlanningOutcome.STALE,
                reason_code="SESSION_NOT_ACTIVE",
            )

        if pre_hook is not None:
            await pre_hook()

        if session.lifecycle_state != SessionLifecycleState.ACTIVE or session.root_scope.is_cancel_requested:
            return LifecycleDeliveryResult(
                admitted=False,
                admission_status=AdmissionStatus.CANCELED,
                outcome=PlanningOutcome.STALE,
                reason_code="CANCELED_BEFORE_ALLOCATION",
            )

        active_turn = session.tg.active_turn
        if not isinstance(response, DialogueResponse):
            pre_val = self._pipeline.validate_only(
                response,
                expected_session_id=session.identity.session_id,
                expected_turn_id=active_turn.turn_id if active_turn else None,
                incarnation_id=session.incarnation_id,
            )
            return LifecycleDeliveryResult(
                admitted=False,
                admission_status=AdmissionStatus.INVALID,
                outcome=pre_val.outcome,
                reason_code=pre_val.reason_code,
            )

        pre_val = self._pipeline.validate_only(
            response,
            expected_session_id=session.identity.session_id,
            expected_turn_id=active_turn.turn_id if active_turn else None,
            incarnation_id=session.incarnation_id,
        )
        if pre_val.outcome != PlanningOutcome.ADMITTED:
            status = AdmissionStatus.DUPLICATE if pre_val.reason_code == "DUPLICATE_RESPONSE" else (
                AdmissionStatus.STALE_TURN if pre_val.outcome == PlanningOutcome.STALE else AdmissionStatus.INVALID
            )
            return LifecycleDeliveryResult(
                admitted=False,
                admission_status=status,
                outcome=pre_val.outcome,
                reason_code=pre_val.reason_code,
            )

        # Step 2: Allocate M02 GenerationRef + CancellationScope and track temporary buffer lease
        try:
            gen_ref, gen_scope = await session.begin_generation(turn_ref)
        except Exception:
            return LifecycleDeliveryResult(
                admitted=False,
                admission_status=AdmissionStatus.STALE_TURN,
                outcome=PlanningOutcome.STALE,
                reason_code="GENERATION_ALLOCATION_REJECTED",
            )

        lease = session.ledger.acquire(
            lease_id=f"f4:{gen_scope.scope_id}",
            kind="f4_temp_plan_buffer",
        )

        try:
            # Step 3: Pure CPU work OUTSIDE session.lock (with optional deterministic barrier hook for tests)
            prep = self._pipeline.prepare_response(
                response,
                generation_ref=gen_ref,
                expected_session_id=session.identity.session_id,
                expected_turn_id=gen_ref.turn_id,
                incarnation_id=session.incarnation_id,
                plan_revision=plan_revision,
                requested_seed=requested_seed,
                requested_profile_id=requested_profile_id,
                experimental_seeds_enabled=experimental_seeds_enabled,
                commit_dedup=False,
            )

            if mid_hook is not None:
                await mid_hook(gen_ref, gen_scope)

            if not prep.ok or prep.plan is None:
                gen_scope.request_cancel(f"f4_prep_failed:{prep.reason_code}")
                return LifecycleDeliveryResult(
                    admitted=False,
                    admission_status=AdmissionStatus.INVALID,
                    outcome=prep.outcome,
                    generation_ref=gen_ref,
                    reason_code=prep.reason_code,
                    preparation=prep,
                )

            # Step 4: Atomic M02 delivery fence under session lock
            async with session.lock:
                if session.lifecycle_state in {SessionLifecycleState.CLOSING, SessionLifecycleState.CLOSED}:
                    gen_scope.request_cancel("session_closed")
                    return LifecycleDeliveryResult(
                        admitted=False,
                        admission_status=AdmissionStatus.CLOSED,
                        outcome=PlanningOutcome.STALE,
                        generation_ref=gen_ref,
                        reason_code="SESSION_CLOSED",
                        preparation=prep,
                    )
                if session.tg.active_generation != gen_ref:
                    gen_scope.request_cancel("generation_superseded")
                    return LifecycleDeliveryResult(
                        admitted=False,
                        admission_status=AdmissionStatus.STALE_GENERATION,
                        outcome=PlanningOutcome.STALE,
                        generation_ref=gen_ref,
                        reason_code="GENERATION_SUPERSEDED",
                        preparation=prep,
                    )
                if session.root_scope.is_cancel_requested or gen_scope.is_cancel_requested:
                    return LifecycleDeliveryResult(
                        admitted=False,
                        admission_status=AdmissionStatus.CANCELED,
                        outcome=PlanningOutcome.STALE,
                        generation_ref=gen_ref,
                        reason_code="CANCELED_BEFORE_ADMISSION",
                        preparation=prep,
                    )

                self._pipeline.commit_dedup(
                    response,
                    incarnation_id=session.incarnation_id,
                    plan=prep.plan,
                )
                if on_admit is not None:
                    on_admit(prep.plan)

                return LifecycleDeliveryResult(
                    admitted=True,
                    admission_status=AdmissionStatus.ACCEPTED,
                    outcome=PlanningOutcome.ADMITTED,
                    plan=prep.plan,
                    generation_ref=gen_ref,
                    reason_code="ADMITTED",
                    preparation=prep,
                )
        finally:
            session.ledger.release(lease.lease_id)
