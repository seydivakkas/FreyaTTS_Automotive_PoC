import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from backend.db import Base, Conversation, FqiciEvent, FqiciRun, FqiciScope
from backend.fqici.events import Closure, EvidenceEvent, ToolCommit, ToolTimeout, elapsed_ms
from backend.fqici.journal import replay
from backend.fqici.queue import Queue, purge_expired_scopes


@pytest.fixture
def storage(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'fqici.db').as_posix()}")

    @event.listens_for(engine, "connect")
    def enable_fk(dbapi, _):
        dbapi.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False), tmp_path / "journals"
    engine.dispose()


def enroll(sessions, transport="WEB"):
    sid = uuid4()
    with sessions.begin() as db:
        db.add(Conversation(id=str(sid), channel="web"))
        db.flush()
        db.add(FqiciScope(id=str(sid), transport=transport, origin="SYNTHETIC"))
    return sid


def closure(sid):
    return EvidenceEvent(
        producer="session_journal", source_event_id=uuid4(), session_id=sid,
        occurred_at=datetime.now(timezone.utc),
        payload=Closure(kind="session.closed", reason="normal", state="ENDED"),
    )


def test_duplicate_close_and_concurrent_consumers_fence_stale_worker(storage):
    sessions, _ = storage
    tick = [1_000]
    queue = Queue(sessions, clock_ms=lambda: tick[0])
    ended = closure(enroll(sessions))
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(queue.ingest, [ended] * 10)) == 1
        claimed = list(pool.map(lambda _: queue.claim(lease_ms=5), range(2)))
    old, = [lease for lease in claimed if lease is not None]
    tick[0] += 5
    reopened = Queue(sessions, clock_ms=lambda: tick[0])
    new = reopened.claim()
    assert new.run_id == old.run_id and new.fence == old.fence + 1
    assert not reopened.finish(old, succeeded=True)
    assert reopened.finish(new, succeeded=True)
    with sessions() as db:
        row, = db.scalars(select(FqiciRun)).all()
        assert row.state == "SUCCEEDED"
        assert len(db.scalars(select(FqiciEvent)).all()) == 1


async def test_real_journal_replay_after_fresh_processes(monkeypatch, storage):
    from backend import milestones

    sessions, root = storage
    monkeypatch.setattr(milestones, "runtime_root", lambda: root)
    sid = enroll(sessions)
    control = milestones.LiveControl(str(sid))
    await control.close(closure_reason="disconnect")
    await control.close(closure_reason="disconnect")
    with sessions() as db:
        assert db.scalars(select(FqiciRun)).all() == []
    script = (
        "from pathlib import Path; import sys; "
        "from backend.fqici.journal import replay; from backend.fqici.queue import Queue; "
        "print(replay(Path(sys.argv[1]), Queue(), startup=True), flush=True); "
        "import os; os._exit(0)"
    )
    database_url = str(sessions.kw["bind"].url)
    counts = [subprocess.run(
        [sys.executable, "-c", script, str(root)], check=True, capture_output=True, text=True,
        env={**os.environ, "DATABASE_URL": database_url}, timeout=20,
    ).stdout.strip() for _ in range(2)]
    assert counts == ["1", "0"]
    with sessions() as db:
        row, = db.scalars(select(FqiciRun)).all()
        source, = db.scalars(select(FqiciEvent)).all()
        assert row.state == "QUEUED"
        assert json.loads(source.evidence)["payload"] == {
            "kind": "session.closed", "reason": "disconnect", "state": "ENDED",
        }


async def test_startup_recovers_abandoned_session_and_missing_journal(monkeypatch, storage):
    from backend import milestones

    sessions, root = storage
    monkeypatch.setattr(milestones, "runtime_root", lambda: root)
    sid = enroll(sessions)
    enroll(sessions)
    control = milestones.LiveControl(str(sid))
    await control.move("thinking")
    control.journal.close()
    assert await milestones.recover_abandoned() == 1
    queue = Queue(sessions)
    assert replay(root, queue, startup=True) == 2
    assert replay(root, Queue(sessions), startup=True) == 0
    with sessions() as db:
        assert len(db.scalars(select(FqiciRun)).all()) == 2
        payloads = [json.loads(row.evidence)["payload"] for row in db.scalars(select(FqiciEvent))]
        assert {item["state"] for item in payloads} == {"FAILED", "UNKNOWN"}
        assert {item["kind"] for item in payloads} == {"session.recovered"}


def test_full_queue_deferred_and_late_tool_evidence_replayed(storage):
    sessions, _ = storage
    tick = [1_000]
    sid = enroll(sessions)
    queue = Queue(sessions, capacity=1, clock_ms=lambda: tick[0])
    queue.ingest(closure(sid))
    other = enroll(sessions, "AUDIOSOCKET")
    queue.ingest(closure(other))
    operation = uuid4()
    timestamp = datetime.now(timezone.utc)
    event = EvidenceEvent(
        producer="tool_gateway", source_event_id=uuid4(), session_id=sid, occurred_at=timestamp,
        payload=ToolTimeout(kind="tool.timeout", operation_id=operation, attempt_id=uuid4(), elapsed_ms=50),
    )
    queue.ingest(event)
    queue.ingest(EvidenceEvent(
        producer="tool_gateway", source_event_id=uuid4(), session_id=sid, occurred_at=timestamp,
        payload=ToolCommit(kind="tool.commit_observed", operation_id=operation, commit_state="COMMITTED"),
    ))
    assert queue.enqueue_due() == 0
    assert queue.finish(queue.claim(), succeeded=True)
    reopened = Queue(sessions, capacity=1, clock_ms=lambda: tick[0])
    assert reopened.enqueue_due() == 1
    assert reopened.finish(reopened.claim(), succeeded=True)
    tick[0] += 2_000
    assert reopened.enqueue_due() == 1
    assert reopened.finish(reopened.claim(), succeeded=True)
    assert Queue(sessions, rule_version="fqici-rules-v2").requeue_scope(str(sid))
    with sessions() as db:
        rows = db.scalars(select(FqiciRun).where(FqiciRun.scope_id == str(sid))).all()
        assert len(rows) == 3
        assert len({row.evidence_hash for row in rows}) == 2
        assert max(len(json.loads(row.event_ids)) for row in rows) == 3


def test_privacy_clock_and_conflicting_replay(storage):
    sessions, _ = storage
    first = closure(enroll(sessions))
    with pytest.raises(ValidationError):
        Closure(kind="session.closed", reason="normal", state="ENDED", phone="05551234567")
    one = first.model_copy(update={"clock_domain_id": uuid4(), "monotonic_offset_ms": 10})
    two = one.model_copy(update={"clock_domain_id": uuid4(), "monotonic_offset_ms": 25})
    assert elapsed_ms(one, two) is None
    assert elapsed_ms(one, one.model_copy(update={"monotonic_offset_ms": 25})) == 15
    queue = Queue(sessions)
    assert queue.ingest(one)
    with pytest.raises(ValueError, match="source_event_conflict"):
        queue.ingest(two)


def test_event_and_run_rollback_together_and_purge_cascades(monkeypatch, storage):
    sessions, _ = storage
    sid = enroll(sessions)
    event = closure(sid)
    queue = Queue(sessions)

    def interrupted(*_):
        raise RuntimeError("simulated transaction interruption")

    monkeypatch.setattr(queue, "_enqueue", interrupted)
    with pytest.raises(RuntimeError, match="transaction interruption"):
        queue.ingest(event)
    with sessions() as db:
        assert db.scalars(select(FqiciEvent)).all() == []
        assert db.scalars(select(FqiciRun)).all() == []
        assert not db.get(FqiciScope, str(sid)).terminal_seen
    assert Queue(sessions).ingest(event)
    with sessions.begin() as db:
        db.get(Conversation, str(sid)).status = "purged"
    purge_expired_scopes("2000-01-01T00:00:00+00:00", sessions)
    with sessions() as db:
        assert db.get(FqiciScope, str(sid)) is None
        assert db.scalars(select(FqiciEvent)).all() == []
        assert db.scalars(select(FqiciRun)).all() == []


async def test_web_session_and_synthetic_audiosocket_transport(monkeypatch, storage):
    from backend import milestones, session
    from backend.audiosocket_server import (
        AUDIOSOCKET_HANGUP, AUDIOSOCKET_UUID, AudioSocketOrchestrator, build_packet,
    )

    sessions, root = storage
    monkeypatch.setattr(session, "Session", sessions)
    monkeypatch.setattr(milestones, "runtime_root", lambda: root)
    monkeypatch.setattr(session.settings, "fqici_enabled", True)
    monkeypatch.setattr(session.settings, "record_audio", False)

    class Vad:
        def reset_states(self):
            pass

    monkeypatch.setattr(session.models, "vad", Vad())

    async def noop(*_):
        pass

    monkeypatch.setattr(session.VoiceSession, "start", noop)
    web = session.VoiceSession("web", noop, noop)
    await web.close()
    orch = AudioSocketOrchestrator()
    completed = asyncio.Event()

    async def handle(reader, writer):
        try:
            await orch.handle_connection(reader, writer, synthetic=True)
        finally:
            completed.set()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    call = uuid4()
    async with server:
        _, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
        writer.write(build_packet(AUDIOSOCKET_UUID, call.bytes) + build_packet(AUDIOSOCKET_HANGUP, b""))
        await writer.drain()
        await asyncio.wait_for(completed.wait(), timeout=5)
        writer.close()
        await writer.wait_closed()
    assert replay(root, Queue(sessions)) == 2
    assert replay(root, Queue(sessions), startup=True) == 0
    with sessions() as db:
        scopes = {row.transport: row for row in db.scalars(select(FqiciScope))}
        assert scopes["WEB"].transport_id is None
        assert scopes["AUDIOSOCKET"].origin == "SYNTHETIC"
        assert scopes["AUDIOSOCKET"].transport_id == str(call)
        assert len(db.scalars(select(FqiciRun)).all()) == 2
