"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Callable

from backend.core.contracts.validation import require_safe_id
from backend.security.audit import AuditEventKind, SecurityAuditLog
from backend.security.contracts import (
    IdempotencyConflictError,
    IdempotencyState,
    IdempotencyStateError,
)

_IDEMPOTENCY_TRANSITIONS: dict[IdempotencyState, frozenset[IdempotencyState]] = {
    IdempotencyState.CLAIMED: frozenset({
        IdempotencyState.COMMITTED,
        IdempotencyState.BLOCKED,
        IdempotencyState.FAILED_CONFIRMED,
        IdempotencyState.UNKNOWN,
    }),
    IdempotencyState.UNKNOWN: frozenset({
        IdempotencyState.RECONCILING,
    }),
    IdempotencyState.RECONCILING: frozenset({
        IdempotencyState.COMMITTED,
        IdempotencyState.BLOCKED,
        IdempotencyState.FAILED_CONFIRMED,
        IdempotencyState.UNKNOWN,
    }),
    IdempotencyState.COMMITTED: frozenset(),
    IdempotencyState.BLOCKED: frozenset(),
    IdempotencyState.FAILED_CONFIRMED: frozenset(),
}


class ClaimOutcome(StrEnum):
    CLAIMED = "CLAIMED"
    ALREADY_COMMITTED = "ALREADY_COMMITTED"
    ALREADY_BLOCKED = "ALREADY_BLOCKED"
    ALREADY_FAILED_CONFIRMED = "ALREADY_FAILED_CONFIRMED"
    IN_FLIGHT = "IN_FLIGHT"
    UNKNOWN_HOLD = "UNKNOWN_HOLD"
    RECONCILING_HOLD = "RECONCILING_HOLD"


_EXISTING_STATE_TO_OUTCOME: dict[IdempotencyState, ClaimOutcome] = {
    IdempotencyState.CLAIMED: ClaimOutcome.IN_FLIGHT,
    IdempotencyState.COMMITTED: ClaimOutcome.ALREADY_COMMITTED,
    IdempotencyState.BLOCKED: ClaimOutcome.ALREADY_BLOCKED,
    IdempotencyState.FAILED_CONFIRMED: ClaimOutcome.ALREADY_FAILED_CONFIRMED,
    IdempotencyState.UNKNOWN: ClaimOutcome.UNKNOWN_HOLD,
    IdempotencyState.RECONCILING: ClaimOutcome.RECONCILING_HOLD,
}


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    idempotency_key: str
    tool_id: str
    action: str
    actor_ref: str
    operation_digest: str
    state: IdempotencyState
    attempt_count: int
    reconcile_attempts: int
    result_ref: str | None
    error_code: str | None
    created_utc: str
    updated_utc: str


@dataclass(frozen=True, slots=True)
class IdempotencyClaimResult:
    acquired: bool
    outcome: ClaimOutcome
    record: IdempotencyRecord


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _row_to_record(row: sqlite3.Row) -> IdempotencyRecord:
    return IdempotencyRecord(
        idempotency_key=row["idempotency_key"],
        tool_id=row["tool_id"],
        action=row["action"],
        actor_ref=row["actor_ref"],
        operation_digest=row["operation_digest"],
        state=IdempotencyState(row["state"]),
        attempt_count=row["attempt_count"],
        reconcile_attempts=row["reconcile_attempts"],
        result_ref=row["result_ref"],
        error_code=row["error_code"],
        created_utc=row["created_utc"],
        updated_utc=row["updated_utc"],
    )


class DurableIdempotencyStore:
    """Isolated SQLite WAL store using BEGIN IMMEDIATE for crash-safe idempotency."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        utc_now_fn: Callable[[], str] = _utc_iso,
        audit_log: SecurityAuditLog | None = None,
    ) -> None:
        raw = str(db_path).strip()
        if not raw or raw == ":memory:" or raw.startswith("file::memory:"):
            raise ValueError("DurableIdempotencyStore requires an isolated filesystem SQLite path")
        self._db_path = Path(raw)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._utc_now_fn = utc_now_fn
        self._audit_log = audit_log
        self._init_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    idempotency_key TEXT PRIMARY KEY,
                    tool_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor_ref TEXT NOT NULL,
                    operation_digest TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    reconcile_attempts INTEGER NOT NULL DEFAULT 0,
                    result_ref TEXT,
                    error_code TEXT,
                    created_utc TEXT NOT NULL,
                    updated_utc TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_idempotency_state ON idempotency_records (state, updated_utc)"
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def _audit(self, record: IdempotencyRecord, action: str, previous_state: IdempotencyState | None) -> None:
        if self._audit_log is None:
            return
        self._audit_log.append(
            kind=AuditEventKind.IDEMPOTENCY_TRANSITION,
            action=action,
            outcome=record.state.value,
            actor_ref=record.actor_ref,
            operation_digest=record.operation_digest,
            details={
                "idempotency_key": record.idempotency_key,
                "tool_id": record.tool_id,
                "action": record.action,
                "previous_state": previous_state.value if previous_state else None,
                "state": record.state.value,
                "attempt_count": record.attempt_count,
                "reconcile_attempts": record.reconcile_attempts,
                "result_ref": record.result_ref,
                "error_code": record.error_code,
            },
        )

    def claim(
        self,
        idempotency_key: str,
        *,
        tool_id: str,
        action: str,
        actor_ref: str,
        operation_digest: str,
    ) -> IdempotencyClaimResult:
        """Atomically claim key or return non-acquired outcome; rejects digest mismatch and never auto-retries UNKNOWN."""
        require_safe_id(idempotency_key, "idempotency_key")
        require_safe_id(tool_id, "tool_id")
        if not isinstance(action, str) or not action.strip():
            raise ValueError("action required")
        require_safe_id(actor_ref, "actor_ref")
        if not isinstance(operation_digest, str) or len(operation_digest) != 64:
            raise ValueError("operation_digest must be 64-char SHA-256 hex")

        now = self._utc_now_fn()
        conn = self._connect()
        previous_state: IdempotencyState | None = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM idempotency_records WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO idempotency_records (
                        idempotency_key, tool_id, action, actor_ref, operation_digest,
                        state, attempt_count, reconcile_attempts, result_ref, error_code,
                        created_utc, updated_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, 0, NULL, NULL, ?, ?)
                    """,
                    (
                        idempotency_key,
                        tool_id,
                        action,
                        actor_ref,
                        operation_digest,
                        IdempotencyState.CLAIMED.value,
                        now,
                        now,
                    ),
                )
                created = conn.execute(
                    "SELECT * FROM idempotency_records WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                conn.execute("COMMIT")
                record = _row_to_record(created)
                result = IdempotencyClaimResult(acquired=True, outcome=ClaimOutcome.CLAIMED, record=record)
            else:
                existing = _row_to_record(row)
                previous_state = existing.state
                if (
                    existing.operation_digest != operation_digest
                    or existing.tool_id != tool_id
                    or existing.action != action
                    or existing.actor_ref != actor_ref
                ):
                    conn.execute("ROLLBACK")
                    raise IdempotencyConflictError(
                        f"Idempotency key {idempotency_key!r} already bound to different operation digest or actor"
                    )
                conn.execute(
                    """
                    UPDATE idempotency_records
                    SET attempt_count = attempt_count + 1, updated_utc = ?
                    WHERE idempotency_key = ?
                    """,
                    (now, idempotency_key),
                )
                updated_row = conn.execute(
                    "SELECT * FROM idempotency_records WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                conn.execute("COMMIT")
                record = _row_to_record(updated_row)
                result = IdempotencyClaimResult(
                    acquired=False,
                    outcome=_EXISTING_STATE_TO_OUTCOME[record.state],
                    record=record,
                )
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

        self._audit(result.record, f"idempotency.claim.{result.outcome.value.lower()}", previous_state)
        return result

    def _transition(
        self,
        idempotency_key: str,
        target: IdempotencyState,
        *,
        expected_digest: str | None = None,
        result_ref: str | None = None,
        error_code: str | None = None,
        increment_reconcile: bool = False,
    ) -> IdempotencyRecord:
        require_safe_id(idempotency_key, "idempotency_key")
        if result_ref is not None:
            require_safe_id(result_ref, "result_ref")
        if error_code is not None:
            require_safe_id(error_code, "error_code")

        now = self._utc_now_fn()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM idempotency_records WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is None:
                raise IdempotencyStateError(f"Unknown idempotency key: {idempotency_key}")
            current = _row_to_record(row)
            if expected_digest is not None and current.operation_digest != expected_digest:
                raise IdempotencyConflictError(
                    f"Digest mismatch transitioning idempotency key {idempotency_key!r}"
                )
            if target not in _IDEMPOTENCY_TRANSITIONS[current.state]:
                raise IdempotencyStateError(
                    f"Invalid idempotency transition: {current.state.value} -> {target.value}"
                )
            new_reconcile = current.reconcile_attempts + (1 if increment_reconcile else 0)
            next_result_ref = result_ref if result_ref is not None else current.result_ref
            next_error_code = error_code if error_code is not None else current.error_code
            if target == IdempotencyState.COMMITTED and error_code is None:
                next_error_code = None
            conn.execute(
                """
                UPDATE idempotency_records
                SET state = ?, reconcile_attempts = ?, result_ref = ?, error_code = ?, updated_utc = ?
                WHERE idempotency_key = ?
                """,
                (target.value, new_reconcile, next_result_ref, next_error_code, now, idempotency_key),
            )
            updated_row = conn.execute(
                "SELECT * FROM idempotency_records WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            conn.execute("COMMIT")
            updated = _row_to_record(updated_row)
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

        self._audit(updated, f"idempotency.{target.value.lower()}", current.state)
        return updated

    def mark_committed(
        self,
        idempotency_key: str,
        *,
        operation_digest: str,
        result_ref: str | None = None,
    ) -> IdempotencyRecord:
        return self._transition(
            idempotency_key,
            IdempotencyState.COMMITTED,
            expected_digest=operation_digest,
            result_ref=result_ref,
        )

    def mark_blocked(
        self,
        idempotency_key: str,
        *,
        operation_digest: str,
        error_code: str = "policy.blocked",
    ) -> IdempotencyRecord:
        return self._transition(
            idempotency_key,
            IdempotencyState.BLOCKED,
            expected_digest=operation_digest,
            error_code=error_code,
        )

    def mark_failed_confirmed(
        self,
        idempotency_key: str,
        *,
        operation_digest: str,
        error_code: str = "tool.failed_confirmed",
    ) -> IdempotencyRecord:
        return self._transition(
            idempotency_key,
            IdempotencyState.FAILED_CONFIRMED,
            expected_digest=operation_digest,
            error_code=error_code,
        )

    def mark_unknown(
        self,
        idempotency_key: str,
        *,
        operation_digest: str,
        error_code: str = "tool.outcome_unknown",
    ) -> IdempotencyRecord:
        return self._transition(
            idempotency_key,
            IdempotencyState.UNKNOWN,
            expected_digest=operation_digest,
            error_code=error_code,
        )

    def begin_reconciliation(self, idempotency_key: str) -> IdempotencyRecord:
        """Transition UNKNOWN -> RECONCILING for explicit out-of-band reconciliation only."""
        return self._transition(
            idempotency_key,
            IdempotencyState.RECONCILING,
            increment_reconcile=True,
        )

    def get(self, idempotency_key: str) -> IdempotencyRecord | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM idempotency_records WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            return _row_to_record(row) if row is not None else None
        finally:
            conn.close()

    def list_by_state(self, state: IdempotencyState, *, limit: int = 100) -> tuple[IdempotencyRecord, ...]:
        if not isinstance(state, IdempotencyState):
            raise ValueError("state must be IdempotencyState")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM idempotency_records WHERE state = ? ORDER BY updated_utc ASC LIMIT ?",
                (state.value, max(1, int(limit))),
            ).fetchall()
            return tuple(_row_to_record(r) for r in rows)
        finally:
            conn.close()
