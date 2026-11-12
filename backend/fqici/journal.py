import asyncio
import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select

from automotive_voice.core.events import EventEnvelope, EventType
from backend.db import FqiciScope
from backend.fqici.events import Closure, EvidenceEvent
from backend.fqici.queue import Queue

logger = logging.getLogger(__name__)


def terminal_event(root: Path, session_id: str) -> EvidenceEvent | None:
    path = root / (str(UUID(session_id)) + ".sqlite3")
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute(
            """SELECT envelope FROM outbox WHERE session_id = ?
               AND json_extract(envelope, '$.event_type') IN ('session_ended', 'session_failed')
               ORDER BY sequence DESC LIMIT 1""", (session_id,),
        ).fetchone()
    if row is None:
        return None
    source = EventEnvelope.from_dict(json.loads(row[0]))
    if str(source.session_id) != session_id:
        raise ValueError("fqici.journal_scope_mismatch")
    recovered = source.payload.get("code") == "unclean_restart"
    reason = source.payload.get("closure_reason")
    if recovered:
        reason = "unclean_restart"
    elif reason not in {"normal", "disconnect", "transport_error"}:
        reason = "normal" if source.event_type == EventType.SESSION_ENDED else "transport_error"
    return EvidenceEvent(
        producer="session_journal", source_event_id=source.event_id,
        session_id=session_id, occurred_at=source.occurred_at_utc,
        payload=Closure(
            kind="session.recovered" if recovered else "session.closed", reason=reason,
            state="ENDED" if source.event_type == EventType.SESSION_ENDED else "FAILED",
        ),
    )


def replay(root: Path, queue: Queue, *, startup: bool = False) -> int:
    """Deliver durable journal terminals, including local event-bus ACKed rows."""
    accepted = 0
    with queue.sessions() as db:
        scopes = list(db.scalars(select(FqiciScope.id).where(~FqiciScope.terminal_seen)))
    for session_id in scopes:
        try:
            event = terminal_event(root, session_id)
            if event is None and startup:
                # Enrollment committed, but the process exited before a terminal
                # record could be created. Preserve the uncertainty of the outcome.
                event = EvidenceEvent(
                    producer="startup_recovery", session_id=session_id,
                    source_event_id=uuid5(NAMESPACE_URL, f"freya:fqici:missing-terminal:{session_id}"),
                    occurred_at=datetime.now(timezone.utc),
                    payload=Closure(kind="session.recovered", reason="unclean_restart", state="UNKNOWN"),
                )
            if event is not None:
                accepted += queue.ingest(event)
        except (sqlite3.Error, OSError, LookupError, ValueError):
            logger.warning("FQICI terminal evidence could not be delivered")
    queue.enqueue_due()
    return accepted


async def poll(root: Path, queue: Queue, *, startup: bool = False) -> None:
    try:
        await asyncio.to_thread(replay, root, queue, startup=startup)
    except Exception:
        logger.warning("FQICI journal delivery deferred")


async def run_poll_loop(root: Path, queue: Queue) -> None:
    while True:
        await poll(root, queue)
        await asyncio.sleep(1)
