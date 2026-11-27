"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping
from uuid import uuid4

from backend.core.contracts.validation import freeze_value, require_safe_id
from backend.security.contracts import canonical_json_bytes, redact_sensitive_text, sanitize_audit_payload

_GENESIS_HASH = "0" * 64


class AuditEventKind(StrEnum):
    POLICY_DECISION = "POLICY_DECISION"
    CONFIRMATION_LIFECYCLE = "CONFIRMATION_LIFECYCLE"
    IDEMPOTENCY_TRANSITION = "IDEMPOTENCY_TRANSITION"
    RECONCILIATION = "RECONCILIATION"
    GATEWAY_BRIDGE = "GATEWAY_BRIDGE"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"


@dataclass(frozen=True, slots=True)
class AuditEntry:
    seq: int
    event_id: str
    kind: AuditEventKind
    action: str
    outcome: str
    actor_ref: str | None
    session_id: str | None
    trace_id: str | None
    operation_digest: str | None
    utc_timestamp: str
    details: Mapping[str, Any]
    prev_hash: str
    entry_hash: str


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _compute_entry_hash(
    *,
    seq: int,
    event_id: str,
    kind: AuditEventKind,
    action: str,
    outcome: str,
    actor_ref: str | None,
    session_id: str | None,
    trace_id: str | None,
    operation_digest: str | None,
    utc_timestamp: str,
    details_json: str,
    prev_hash: str,
) -> str:
    payload = {
        "seq": seq,
        "event_id": event_id,
        "kind": kind.value,
        "action": action,
        "outcome": outcome,
        "actor_ref": actor_ref,
        "session_id": session_id,
        "trace_id": trace_id,
        "operation_digest": operation_digest,
        "utc_timestamp": utc_timestamp,
        "details_json": details_json,
        "prev_hash": prev_hash,
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _safe_optional_id(value: str | None) -> str | None:
    if value is None:
        return None
    redacted = redact_sensitive_text(str(value).strip())
    if redacted != str(value).strip():
        return "[REDACTED]"
    try:
        return require_safe_id(redacted, "audit_id")
    except ValueError:
        return "[REDACTED]"


def _row_to_entry(row: sqlite3.Row) -> AuditEntry:
    return AuditEntry(
        seq=row["seq"],
        event_id=row["event_id"],
        kind=AuditEventKind(row["kind"]),
        action=row["action"],
        outcome=row["outcome"],
        actor_ref=row["actor_ref"],
        session_id=row["session_id"],
        trace_id=row["trace_id"],
        operation_digest=row["operation_digest"],
        utc_timestamp=row["utc_timestamp"],
        details=freeze_value(json.loads(row["details_json"])),
        prev_hash=row["prev_hash"],
        entry_hash=row["entry_hash"],
    )


class SecurityAuditLog:
    """Durable, tamper-evident SQLite WAL append log independent of M04 lossy bus."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        utc_now_fn: Callable[[], str] = _utc_iso,
        observer_sink: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        raw = str(db_path).strip()
        if not raw or raw == ":memory:" or raw.startswith("file::memory:"):
            raise ValueError("SecurityAuditLog requires an isolated filesystem SQLite path")
        self._db_path = Path(raw)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._utc_now_fn = utc_now_fn
        self._observer_sink = observer_sink
        self._init_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS security_audit_log (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL,
                    action TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    actor_ref TEXT,
                    session_id TEXT,
                    trace_id TEXT,
                    operation_digest TEXT,
                    utc_timestamp TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_security_audit_kind ON security_audit_log (kind, seq)"
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def append(
        self,
        *,
        kind: AuditEventKind,
        action: str,
        outcome: str,
        actor_ref: str | None = None,
        session_id: str | None = None,
        trace_id: str | None = None,
        operation_digest: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> AuditEntry:
        """Append a sanitized, hash-chained audit record durably; observer failures never drop records."""
        if not isinstance(kind, AuditEventKind):
            raise ValueError("kind must be AuditEventKind")
        safe_action = redact_sensitive_text(str(action).strip())
        safe_outcome = redact_sensitive_text(str(outcome).strip())
        if not safe_action or not safe_outcome:
            raise ValueError("action and outcome must be non-empty")

        safe_actor = _safe_optional_id(actor_ref)
        safe_session = _safe_optional_id(session_id)
        safe_trace = _safe_optional_id(trace_id)
        safe_digest = (
            operation_digest
            if isinstance(operation_digest, str) and len(operation_digest) == 64
            else None
        )
        sanitized_details = sanitize_audit_payload(details or {})
        details_json = canonical_json_bytes(sanitized_details).decode("utf-8")
        # Final defense-in-depth scan over serialized details JSON.
        details_json = redact_sensitive_text(details_json)

        event_id = f"aud-{uuid4().hex[:20]}"
        ts = self._utc_now_fn()

        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            last = conn.execute(
                "SELECT seq, entry_hash FROM security_audit_log ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            next_seq = (int(last["seq"]) + 1) if last is not None else 1
            prev_hash = str(last["entry_hash"]) if last is not None else _GENESIS_HASH
            entry_hash = _compute_entry_hash(
                seq=next_seq,
                event_id=event_id,
                kind=kind,
                action=safe_action,
                outcome=safe_outcome,
                actor_ref=safe_actor,
                session_id=safe_session,
                trace_id=safe_trace,
                operation_digest=safe_digest,
                utc_timestamp=ts,
                details_json=details_json,
                prev_hash=prev_hash,
            )
            conn.execute(
                """
                INSERT INTO security_audit_log (
                    seq, event_id, kind, action, outcome,
                    actor_ref, session_id, trace_id, operation_digest,
                    utc_timestamp, details_json, prev_hash, entry_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    next_seq,
                    event_id,
                    kind.value,
                    safe_action,
                    safe_outcome,
                    safe_actor,
                    safe_session,
                    safe_trace,
                    safe_digest,
                    ts,
                    details_json,
                    prev_hash,
                    entry_hash,
                ),
            )
            row = conn.execute(
                "SELECT * FROM security_audit_log WHERE seq = ?",
                (next_seq,),
            ).fetchone()
            conn.execute("COMMIT")
            entry = _row_to_entry(row)
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

        if self._observer_sink is not None:
            try:
                self._observer_sink(
                    MappingProxyType({
                        "seq": entry.seq,
                        "event_id": entry.event_id,
                        "kind": entry.kind.value,
                        "action": entry.action,
                        "outcome": entry.outcome,
                        "utc_timestamp": entry.utc_timestamp,
                        "details": entry.details,
                    })
                )
            except Exception:
                # Lossy or failing observer must never compromise durable security audit logging.
                pass

        return entry

    def query(
        self,
        *,
        kind: AuditEventKind | None = None,
        limit: int = 100,
    ) -> tuple[AuditEntry, ...]:
        conn = self._connect()
        try:
            if kind is not None:
                rows = conn.execute(
                    "SELECT * FROM security_audit_log WHERE kind = ? ORDER BY seq ASC LIMIT ?",
                    (kind.value, max(1, int(limit))),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM security_audit_log ORDER BY seq ASC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
            return tuple(_row_to_entry(r) for r in rows)
        finally:
            conn.close()

    def count(self) -> int:
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM security_audit_log").fetchone()
            return int(row["cnt"])
        finally:
            conn.close()

    def verify_chain(self) -> bool:
        """Verify monotonic seq and SHA-256 hash chain across all persisted audit entries."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM security_audit_log ORDER BY seq ASC").fetchall()
            expected_prev = _GENESIS_HASH
            expected_seq = 1
            for row in rows:
                if int(row["seq"]) != expected_seq or str(row["prev_hash"]) != expected_prev:
                    return False
                recomputed = _compute_entry_hash(
                    seq=int(row["seq"]),
                    event_id=row["event_id"],
                    kind=AuditEventKind(row["kind"]),
                    action=row["action"],
                    outcome=row["outcome"],
                    actor_ref=row["actor_ref"],
                    session_id=row["session_id"],
                    trace_id=row["trace_id"],
                    operation_digest=row["operation_digest"],
                    utc_timestamp=row["utc_timestamp"],
                    details_json=row["details_json"],
                    prev_hash=row["prev_hash"],
                )
                if recomputed != row["entry_hash"]:
                    return False
                expected_prev = str(row["entry_hash"])
                expected_seq += 1
            return True
        finally:
            conn.close()
