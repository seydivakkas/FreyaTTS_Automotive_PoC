from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.db import Base, Conversation, OperatorTransfer
from backend.operator_inbox import LEGACY_CALLBACK, today_view
from backend.routers import operator_qa


@pytest.fixture
def store(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'inbox.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def test_today_list_uses_recorded_states_and_istanbul_day_boundary(store):
    now = datetime(2026, 11, 9, 21, 0, 8, tzinfo=timezone.utc)
    old = "2026-11-09T20:59:00+00:00"
    new = "2026-11-10T00:00:00+03:00"
    with store.begin() as db:
        db.add_all([
            Conversation(id="callback", channel="web", status="follow_up",
                         follow_up_kind="callback", follow_up_at=new, created_at=old),
            Conversation(id="booking", channel="web", status="follow_up",
                         follow_up_kind="booking_pending", follow_up_at=old, created_at=old),
            Conversation(id="legacy", channel="web", status="follow_up",
                         operator_notes=f"[{old}{LEGACY_CALLBACK} private notes", created_at=old),
            Conversation(id="duplicate", channel="asterisk", status="follow_up", created_at=old),
            Conversation(id="purged", channel="asterisk", status="purged", created_at=old),
            Conversation(id="resolved", channel="web", status="resolved", follow_up_kind="callback"),
            Conversation(id="generic", channel="web", status="follow_up", created_at=old),
        ])
        db.flush()
        db.add_all([
            OperatorTransfer(id="pending", conversation_id="duplicate", status="whispering", created_at=new,
                             customer_name="private caller", summary="private summary"),
            OperatorTransfer(id="expired", conversation_id=None, status="initiated", created_at=old),
            OperatorTransfer(id="purged-transfer", conversation_id="purged", status="whispering", created_at=new),
            OperatorTransfer(id="accepted", conversation_id=None, status="accepted", created_at=new),
        ])
    with store() as db:
        data = today_view(db, now=now, period="all", category="all", limit=50, offset=0)
        assert data["local_date"] == "2026-11-10"
        assert data["counts"] == {"booking_pending": 1, "callback": 2, "follow_up": 1, "transfer": 1}
        assert data["items"][0]["id"] == "pending"
        assert data["items"][0]["age_seconds"] == 8
        assert "private" not in str(data) and "expired" not in str(data)
        assert db.get(OperatorTransfer, "expired").status == "initiated"
        today = today_view(db, now=now, period="today", category="all", limit=1, offset=1)
        assert today["total"] == 2 and [item["id"] for item in today["items"]] == ["callback"]
        carryover = today_view(db, now=now, period="carryover", category="booking", limit=50, offset=0)
        assert [item["id"] for item in carryover["items"]] == ["booking"]
        assert next(item for item in data["items"] if item["id"] == "legacy")["since_source"] == "conversation"


def test_today_endpoint_requires_auth_and_valid_filters(store, monkeypatch):
    monkeypatch.setattr(operator_qa, "Session", store)
    monkeypatch.setattr(settings, "admin_password", "operator-test")
    app = FastAPI()
    app.include_router(operator_qa.router)
    with TestClient(app) as client:
        assert client.get("/api/operator/today").status_code == 401
        assert client.get("/api/operator/today?category=other", auth=("admin", "operator-test")).status_code == 422
        response = client.get("/api/operator/today", auth=("admin", "operator-test"))
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json()["total"] == 0


async def test_voice_close_records_booking_and_callback_without_reopening_terminal_status(store, monkeypatch):
    from automotive_voice.dialogue.models import BookingStatus
    from backend import session

    monkeypatch.setattr(session, "Session", store)
    monkeypatch.setattr(settings, "fqici_enabled", False)
    monkeypatch.setattr(settings, "record_audio", False)

    class Vad:
        def reset_states(self):
            pass

    monkeypatch.setattr(session.models, "vad", Vad())

    async def ignore(*_):
        pass

    cases = (
        (BookingStatus.AWAITING_CONFIRMATION, "booking_pending"),
        (BookingStatus.UNKNOWN, "booking_unknown"),
        (BookingStatus.DECLINED, None),
    )
    for status, expected in cases:
        voice = session.VoiceSession("web", ignore, ignore)
        voice.dialogue.booking_status = status
        await voice.close()
        with store() as db:
            result = db.get(Conversation, voice.id)
            assert result.follow_up_kind == expected
            assert result.follow_up_at is not None
    voice = session.VoiceSession("web", ignore, ignore)
    with store() as db:
        voice.dialogue.record_callback_request(db)
        start = db.get(Conversation, voice.id).follow_up_at
    await voice.close()
    with store.begin() as db:
        result = db.get(Conversation, voice.id)
        assert result.follow_up_kind == "callback" and result.follow_up_at == start
        result.status = "resolved"
    await voice.close()
    with store() as db:
        assert db.get(Conversation, voice.id).status == "resolved"
