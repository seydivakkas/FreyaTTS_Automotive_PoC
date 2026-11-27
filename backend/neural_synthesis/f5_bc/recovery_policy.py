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

from backend.core.contracts.common import ErrorInfo, GenerationRef
from backend.core.runtime.cancellation import CancellationScope
from backend.core.runtime.deadlines import Clock, DeadlineBudget, SystemMonotonicClock

RECOVERY_POLICY_REVISION = "f5b-recovery-v1"
RETRYABLE_FAILURE_CODES = frozenset({
    "SILENT_MODEL_OUTPUT",
    "COLLAPSE_GUARD_REJECTED",
    "EXCESSIVE_NEAR_ZERO_FRACTION",
    "EXCESSIVE_SILENCE_RUN",
    "ODE_PROVIDER_FAILURE",
})
NON_RETRYABLE_FAILURE_CODES = frozenset({
    "UNCERTAIN_DEVICE_STATE",
    "CANCELLED_LEASE_QUARANTINED",
    "CANCELLED_DURING_EXECUTION",
    "CANCELLED_BEFORE_DISPATCH",
    "GENERATION_CANCELLED",
    "INVALID_SEED",
    "UNAPPROVED_SEED",
    "SEED_DISABLED_BY_POLICY",
    "UNSUPPORTED_SOLVER_PROFILE",
    "UNAPPROVED_SOLVER_PROFILE",
    "UNISOLATED_RNG_HOLD",
    "AMBIGUOUS_DECODER_LAYOUT",
    "DECODER_SAMPLE_RATE_MISMATCH",
    "INSUFFICIENT_GPU_BUDGET",
})


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    """Bounded same-seed recovery decision (at most 1 extra attempt, unchanged seed/plan)."""

    should_retry: bool
    prior_attempt: int
    next_attempt: int | None
    policy_revision: str
    seed: int
    generation_ref: GenerationRef
    plan_id: str
    plan_revision: int
    chunk_id: str
    reason_code: str


class SameSeedRecoveryPolicy:
    """
    Bounded same-seed recovery policy.

    - Disabled by default (`enabled=False`) unless explicitly authorized.
    - Maximum 1 additional attempt per logical chunk (2 total including initial).
    - Never changes seed (never falls back 42/77/123 -> 9), solver, steps, or plan.
    - Never retries when native state is uncertain/quarantined, cancelled, already delivered,
      or deadline is exhausted.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        max_additional_attempts: int = 1,
        policy_revision: str = RECOVERY_POLICY_REVISION,
        clock: Clock | None = None,
    ) -> None:
        self.enabled = bool(enabled)
        self.max_additional_attempts = min(1, max(0, int(max_additional_attempts)))
        self.policy_revision = policy_revision
        self.clock: Clock = clock or SystemMonotonicClock()

    def evaluate(
        self,
        *,
        attempt: int,
        seed: int,
        generation_ref: GenerationRef,
        plan_id: str,
        plan_revision: int,
        chunk_id: str,
        error: ErrorInfo | None,
        physical_completed: bool,
        quarantined: bool,
        already_delivered: bool,
        cancellation_scope: CancellationScope | None = None,
        deadline: DeadlineBudget | None = None,
    ) -> RecoveryDecision:
        def _deny(reason: str) -> RecoveryDecision:
            return RecoveryDecision(
                should_retry=False,
                prior_attempt=attempt,
                next_attempt=None,
                policy_revision=self.policy_revision,
                seed=seed,
                generation_ref=generation_ref,
                plan_id=plan_id,
                plan_revision=plan_revision,
                chunk_id=chunk_id,
                reason_code=reason,
            )

        if not self.enabled:
            return _deny("RECOVERY_DISABLED_BY_POLICY")
        if attempt > self.max_additional_attempts:
            return _deny("MAX_RECOVERY_ATTEMPTS_EXHAUSTED")
        if already_delivered:
            return _deny("CHUNK_ALREADY_DELIVERED")
        if quarantined or not physical_completed:
            return _deny("NATIVE_STATE_UNCERTAIN_OR_QUARANTINED")
        if cancellation_scope is not None and cancellation_scope.is_cancel_requested:
            return _deny("SCOPE_CANCELLED")
        if deadline is not None and deadline.is_expired(self.clock.monotonic_ns()):
            return _deny("DEADLINE_EXPIRED")
        if error is None:
            return _deny("NO_ERROR_TO_RETRY")
        if error.code in NON_RETRYABLE_FAILURE_CODES:
            return _deny(f"NON_RETRYABLE_ERROR:{error.code}")
        if error.code not in RETRYABLE_FAILURE_CODES:
            return _deny(f"UNAPPROVED_RETRY_REASON:{error.code}")

        return RecoveryDecision(
            should_retry=True,
            prior_attempt=attempt,
            next_attempt=attempt + 1,
            policy_revision=self.policy_revision,
            seed=seed,
            generation_ref=generation_ref,
            plan_id=plan_id,
            plan_revision=plan_revision,
            chunk_id=chunk_id,
            reason_code=f"SAME_SEED_RECOVERY_ELIGIBLE:{error.code}",
        )


__all__ = [
    "NON_RETRYABLE_FAILURE_CODES",
    "RECOVERY_POLICY_REVISION",
    "RETRYABLE_FAILURE_CODES",
    "RecoveryDecision",
    "SameSeedRecoveryPolicy",
]
