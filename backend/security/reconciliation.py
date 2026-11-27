"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from backend.security.audit import AuditEventKind, SecurityAuditLog
from backend.security.contracts import IdempotencyState
from backend.security.idempotency import DurableIdempotencyStore, IdempotencyRecord


class ReconciliationVerdict(StrEnum):
    CONFIRMED_COMMITTED = "CONFIRMED_COMMITTED"
    CONFIRMED_BLOCKED = "CONFIRMED_BLOCKED"
    CONFIRMED_NOT_APPLIED = "CONFIRMED_NOT_APPLIED"
    STILL_UNKNOWN = "STILL_UNKNOWN"


@dataclass(frozen=True, slots=True)
class ReconciliationProbeResult:
    verdict: ReconciliationVerdict
    result_ref: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.verdict, ReconciliationVerdict):
            raise ValueError("verdict must be ReconciliationVerdict")


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    idempotency_key: str
    previous_state: IdempotencyState
    final_state: IdempotencyState
    verdict: ReconciliationVerdict
    result_ref: str | None = None
    error_code: str | None = None


ReconciliationProbe = Callable[[IdempotencyRecord], ReconciliationProbeResult]


class IdempotencyReconciler:
    """Explicit out-of-band reconciler for UNKNOWN idempotency records (never auto-retries)."""

    def __init__(
        self,
        store: DurableIdempotencyStore,
        *,
        audit_log: SecurityAuditLog | None = None,
    ) -> None:
        self._store = store
        self._audit_log = audit_log

    def reconcile_one(
        self,
        idempotency_key: str,
        probe: ReconciliationProbe,
    ) -> ReconciliationReport:
        """Move UNKNOWN -> RECONCILING, run read-only probe, and settle fail-closed."""
        reconciling = self._store.begin_reconciliation(idempotency_key)
        try:
            probe_result = probe(reconciling)
            if not isinstance(probe_result, ReconciliationProbeResult):
                raise TypeError("probe must return ReconciliationProbeResult")
        except Exception:
            settled = self._store.mark_unknown(
                idempotency_key,
                operation_digest=reconciling.operation_digest,
                error_code="reconciliation.probe_failed",
            )
            report = ReconciliationReport(
                idempotency_key=idempotency_key,
                previous_state=IdempotencyState.UNKNOWN,
                final_state=settled.state,
                verdict=ReconciliationVerdict.STILL_UNKNOWN,
                error_code=settled.error_code,
            )
            self._audit(reconciling, report)
            return report

        if probe_result.verdict == ReconciliationVerdict.CONFIRMED_COMMITTED:
            settled = self._store.mark_committed(
                idempotency_key,
                operation_digest=reconciling.operation_digest,
                result_ref=probe_result.result_ref,
            )
        elif probe_result.verdict == ReconciliationVerdict.CONFIRMED_BLOCKED:
            settled = self._store.mark_blocked(
                idempotency_key,
                operation_digest=reconciling.operation_digest,
                error_code=probe_result.error_code or "reconciliation.blocked",
            )
        elif probe_result.verdict == ReconciliationVerdict.CONFIRMED_NOT_APPLIED:
            settled = self._store.mark_failed_confirmed(
                idempotency_key,
                operation_digest=reconciling.operation_digest,
                error_code=probe_result.error_code or "reconciliation.not_applied",
            )
        else:
            settled = self._store.mark_unknown(
                idempotency_key,
                operation_digest=reconciling.operation_digest,
                error_code=probe_result.error_code or "reconciliation.still_unknown",
            )

        report = ReconciliationReport(
            idempotency_key=idempotency_key,
            previous_state=IdempotencyState.UNKNOWN,
            final_state=settled.state,
            verdict=probe_result.verdict,
            result_ref=settled.result_ref,
            error_code=settled.error_code,
        )
        self._audit(reconciling, report)
        return report

    def reconcile_pending(
        self,
        probe: ReconciliationProbe,
        *,
        limit: int = 50,
    ) -> tuple[ReconciliationReport, ...]:
        """Reconcile up to `limit` UNKNOWN records without auto-retrying side effects."""
        pending = self._store.list_by_state(IdempotencyState.UNKNOWN, limit=limit)
        return tuple(self.reconcile_one(rec.idempotency_key, probe) for rec in pending)

    def _audit(self, record: IdempotencyRecord, report: ReconciliationReport) -> None:
        if self._audit_log is None:
            return
        self._audit_log.append(
            kind=AuditEventKind.RECONCILIATION,
            action="reconciliation.settled",
            outcome=report.final_state.value,
            actor_ref=record.actor_ref,
            operation_digest=record.operation_digest,
            details={
                "idempotency_key": report.idempotency_key,
                "previous_state": report.previous_state.value,
                "next_state": report.final_state.value,
                "verdict": report.verdict.value,
                "result_ref": report.result_ref,
                "error_code": report.error_code,
            },
        )
