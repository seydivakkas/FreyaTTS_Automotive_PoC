import json
import time
from dataclasses import dataclass

from sqlalchemy import and_, delete, func, inspect, or_, select, update
from sqlalchemy.dialects.sqlite import insert

from backend.db import Conversation, FqiciEvent, FqiciRun, FqiciScope, Session
from backend.fqici.events import Closure, EvidenceEvent, canonical, digest

PENDING = ("QUEUED", "RUNNING", "FAILED_RETRYABLE")


@dataclass(frozen=True)
class Lease:
    run_id: str
    fence: int
    event_ids: tuple[str, ...]


class Queue:
    def __init__(
        self, sessions=Session, *, capacity=500, max_attempts=3, rule_version="fqici-rules-v1",
        clock_ms=None,
    ):
        self.sessions = sessions
        self.capacity = capacity
        self.max_attempts = max_attempts
        self.rule_version = rule_version
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)

    def ingest(self, event: EvidenceEvent) -> bool:
        with self.sessions.begin() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            now = self.clock_ms()
            scope = db.get(FqiciScope, str(event.session_id))
            if scope is None:
                raise LookupError("fqici.scope_missing")
            evidence = canonical(event.evidence())
            result = db.execute(insert(FqiciEvent).values(
                id=event.id, scope_id=scope.id, producer=event.producer,
                source_event_id=str(event.source_event_id), evidence=evidence,
            ).on_conflict_do_nothing(index_elements=["producer", "source_event_id"]))
            if not result.rowcount:
                prior = db.get(FqiciEvent, event.id)
                if prior is None or prior.evidence != evidence:
                    raise ValueError("fqici.source_event_conflict")
                return False
            first_terminal = isinstance(event.payload, Closure) and not scope.terminal_seen
            if first_terminal:
                scope.terminal_seen = True
                scope.dirty_since_ms = now
                scope.ready_at_ms = now
                self._enqueue(db, scope, now)
            elif scope.terminal_seen:
                if scope.dirty_since_ms is None:
                    scope.dirty_since_ms = now
                scope.ready_at_ms = min(now + 2_000, scope.dirty_since_ms + 30_000)
            return True

    def _enqueue(self, db, scope: FqiciScope, now: int) -> bool:
        events = db.execute(select(FqiciEvent.id, FqiciEvent.evidence).where(
            FqiciEvent.scope_id == scope.id,
        ).order_by(FqiciEvent.id)).all()
        fingerprint = digest({
            "scope": scope.id, "transport": scope.transport, "origin": scope.origin,
            "transport_id": scope.transport_id, "events": [tuple(row) for row in events],
        })
        prior = db.scalar(select(FqiciRun.id).where(
            FqiciRun.scope_id == scope.id, FqiciRun.evidence_hash == fingerprint,
            FqiciRun.rule_version == self.rule_version,
        ))
        created = False
        if prior is None:
            pending = db.scalar(select(func.count()).select_from(FqiciRun).where(FqiciRun.state.in_(PENDING)))
            if pending >= self.capacity:
                return False
            result = db.execute(insert(FqiciRun).values(
                scope_id=scope.id, evidence_hash=fingerprint, rule_version=self.rule_version,
                event_ids=canonical([row.id for row in events]), state="QUEUED",
                created_at_ms=now, available_at_ms=now,
            ).on_conflict_do_nothing(index_elements=["scope_id", "evidence_hash", "rule_version"]))
            created = bool(result.rowcount)
        scope.dirty_since_ms = None
        scope.ready_at_ms = None
        return created

    def enqueue_due(self, limit=50) -> int:
        with self.sessions.begin() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            now = self.clock_ms()
            scopes = db.scalars(select(FqiciScope).where(
                FqiciScope.ready_at_ms <= now,
            ).order_by(FqiciScope.ready_at_ms, FqiciScope.id).limit(limit)).all()
            return sum(self._enqueue(db, scope, now) for scope in scopes)

    def requeue_scope(self, scope_id: str) -> bool:
        """Explicit replay under this queue's immutable rule version."""
        with self.sessions.begin() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            scope = db.get(FqiciScope, scope_id)
            if scope is None or not scope.terminal_seen:
                return False
            return self._enqueue(db, scope, self.clock_ms())

    def claim(self, lease_ms=30_000) -> Lease | None:
        if lease_ms <= 0:
            raise ValueError("positive lease required")
        with self.sessions.begin() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            now = self.clock_ms()
            expired = and_(FqiciRun.state == "RUNNING", FqiciRun.lease_until_ms <= now)
            db.execute(update(FqiciRun).where(
                expired, FqiciRun.rule_version == self.rule_version, FqiciRun.fence >= self.max_attempts,
            ).values(
                state="FAILED_TERMINAL", lease_until_ms=None,
            ))
            run = db.scalar(select(FqiciRun).where(
                FqiciRun.rule_version == self.rule_version,
                or_(expired, and_(FqiciRun.state.in_(("QUEUED", "FAILED_RETRYABLE")), FqiciRun.available_at_ms <= now)),
            ).order_by(FqiciRun.available_at_ms, FqiciRun.id).limit(1))
            if run is None:
                return None
            run.state = "RUNNING"
            run.fence += 1
            run.lease_until_ms = now + lease_ms
            return Lease(run.id, run.fence, tuple(json.loads(run.event_ids)))

    def finish(self, lease: Lease, *, succeeded: bool, retryable: bool = False) -> bool:
        with self.sessions.begin() as db:
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            now = self.clock_ms()
            retry = not succeeded and retryable and lease.fence < self.max_attempts
            state = "SUCCEEDED" if succeeded else ("FAILED_RETRYABLE" if retry else "FAILED_TERMINAL")
            result = db.execute(update(FqiciRun).where(
                FqiciRun.id == lease.run_id, FqiciRun.fence == lease.fence,
                FqiciRun.state == "RUNNING", FqiciRun.lease_until_ms > now,
            ).values(state=state, lease_until_ms=None, available_at_ms=now + 1_000 * lease.fence))
            return bool(result.rowcount)


def purge_expired_scopes(cutoff: str, sessions=Session) -> None:
    with sessions.begin() as db:
        if not inspect(db.connection()).has_table(FqiciScope.__tablename__):
            return
        db.execute(delete(FqiciScope).where(FqiciScope.id.in_(select(Conversation.id).where(
            or_(Conversation.status == "purged", Conversation.created_at < cutoff),
        ))))
