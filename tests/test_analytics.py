"""Unit and API tests for Analytics Dashboard, KPIs, and Conversation Follow-up Workflow.

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

import json
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import (
    Base,
    Conversation,
    Turn,
    Appointment,
    Vehicle,
    Slot,
    now,
)
from backend import main
from backend.analytics import (
    get_analytics_overview,
    get_follow_up_conversations,
    resolve_conversation,
    reopen_conversation,
    _calc_percentile,
)


@pytest.fixture
def analytics_setup(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "analytics_test.db"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    sm = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("backend.db.Session", sm)
    monkeypatch.setattr("backend.analytics.Turn", Turn)
    monkeypatch.setattr("backend.analytics.Conversation", Conversation)
    monkeypatch.setattr("backend.analytics.Appointment", Appointment)
    monkeypatch.setattr(main.settings, "admin_password", "test-pass")

    client = TestClient(main.app)
    yield client, sm, engine
    client.close()
    engine.dispose()


def test_percentile_calculation():
    # Empty list
    assert _calc_percentile([], 50) is None

    # Single item
    assert _calc_percentile([100.0], 50) == 100.0
    assert _calc_percentile([100.0], 95) == 100.0

    # Ordered list 1..10
    data = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    p50 = _calc_percentile(data, 50)
    assert 50.0 <= p50 <= 60.0
    p95 = _calc_percentile(data, 95)
    assert p95 >= 90.0


def test_analytics_kpi_computation_and_endpoint(analytics_setup):
    client, SessionLocal, engine = analytics_setup
    auth = ("admin", "test-pass")

    # Seed data
    with SessionLocal() as db:
        # 1. Successful conversation with appointment
        c1 = Conversation(channel="web", status="completed")
        # 2. Conversation requiring follow up (unclear)
        c2 = Conversation(channel="phone", status="follow_up")
        # 3. Active conversation
        c3 = Conversation(channel="web", status="active")
        db.add_all([c1, c2, c3])
        db.flush()

        v = Vehicle(description="Toyota Corolla 1.5", plate="34 TY 101")
        db.add(v)
        db.flush()

        slot = Slot(
            starts_at=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        )
        db.add(slot)
        db.flush()

        app = Appointment(
            slot_id=slot.id,
            vehicle_id=v.id,
            customer="Ali Kaya",
            idempotency_key="app-ali-101",
            confirmed=True,
            status="confirmed",
        )
        db.add(app)

        # Add turns for c1 with latency metrics
        t1_u = Turn(
            conversation_id=c1.id,
            role="user",
            text="Merhaba, yarın için randevu almak istiyorum.",
            metrics=json.dumps({"stt_ms": 320.5}),
        )
        t1_a = Turn(
            conversation_id=c1.id,
            role="assistant",
            text="Tabii ki, hangi aracınız için randevu almak istersiniz?",
            metrics=json.dumps(
                {
                    "first_audio_ms": 480.0,
                    "llm_total_ms": 650.0,
                    "llm_first_token_ms": 150.0,
                    "tts_ms": 280.0,
                    "rtf": 0.35,
                }
            ),
        )

        # Add turns for c2 with unclear utterance and barge-in
        t2_u = Turn(
            conversation_id=c2.id,
            role="user",
            text="cızırtılı ses",
            metrics=json.dumps({"stt_ms": 410.0}),
        )
        t2_a = Turn(
            conversation_id=c2.id,
            role="assistant",
            text="Anlayamadım, lütfen tekrar edebilir misiniz?",
            metrics=json.dumps(
                {
                    "first_audio_ms": 520.0,
                    "llm_total_ms": 710.0,
                    "llm_first_token_ms": 180.0,
                    "barge_in_signal_ms": 45.0,
                }
            ),
        )

        db.add_all([t1_u, t1_a, t2_u, t2_a])
        db.commit()

    # Call endpoint GET /api/analytics/overview
    res = client.get("/api/analytics/overview", auth=auth)
    assert res.status_code == 200, res.text
    data = res.json()

    summary = data["summary"]
    assert summary["total_conversations"] == 3
    assert summary["completed_conversations"] == 1
    assert summary["follow_up_conversations"] == 1
    assert summary["total_appointments"] == 1
    assert summary["confirmed_appointments"] == 1
    assert summary["conversion_rate_pct"] == round(1 / 3 * 100, 1)
    assert summary["channels"]["web"] == 2
    assert summary["channels"]["phone"] == 1

    # Quality & STT accuracy
    assert summary["stt_unclear_count"] == 1
    assert summary["stt_clarity_rate_pct"] == 50.0  # 1 unclear out of 2 user turns

    # Latency KPIs
    latencies = data["latency_kpis"]
    assert latencies["first_audio_ms"]["sample_count"] == 2
    assert latencies["first_audio_ms"]["min"] == 480.0
    assert latencies["first_audio_ms"]["max"] == 520.0
    assert latencies["llm_ms"]["sample_count"] == 2
    assert latencies["llm_ms"]["avg_total"] == 680.0
    assert latencies["stt_ms"]["sample_count"] == 2
    assert latencies["barge_in_count"] == 1

    # Daily trend and hourly distribution
    assert len(data["daily_trend"]) == 14
    assert len(data["hourly_distribution"]) == 24


def test_follow_up_resolution_workflow(analytics_setup):
    client, SessionLocal, engine = analytics_setup
    auth = ("admin", "test-pass")

    # Create follow-up conversation
    with SessionLocal() as db:
        c = Conversation(channel="phone", status="follow_up")
        db.add(c)
        db.flush()
        t1 = Turn(
            conversation_id=c.id,
            role="user",
            text="Fiyatlarınız çok yüksek geldi.",
        )
        t2 = Turn(
            conversation_id=c.id,
            role="assistant",
            text="Randevu sonucunu doğrulayamadım. Tekrar kayıt oluşturmadan önce operatör kontrolü gerekiyor.",
        )
        db.add_all([t1, t2])
        db.commit()
        cid = c.id

    # 1. Fetch follow-ups list
    res = client.get("/api/analytics/follow-ups?status=follow_up", auth=auth)
    assert res.status_code == 200
    items = res.json()
    assert len(items) >= 1
    target = next((item for item in items if item["id"] == cid), None)
    assert target is not None
    assert target["status"] == "follow_up"
    assert target["turn_count"] == 2
    assert "Fiyatlarınız çok yüksek" in target["last_user_text"]
    assert "operatör kontrolü" in target["last_assistant_text"]

    # 2. Resolve conversation with operator notes
    resolve_res = client.post(
        f"/api/analytics/conversations/{cid}/resolve",
        json={"notes": "Müşteri arandı, %10 kampanya indirimi ile randevu ikna edildi."},
        auth=auth,
    )
    assert resolve_res.status_code == 200
    res_data = resolve_res.json()
    assert res_data["status"] == "resolved"
    assert (
        res_data["operator_notes"]
        == "Müşteri arandı, %10 kampanya indirimi ile randevu ikna edildi."
    )
    assert res_data["resolved_at"] is not None

    # Verify database state
    with SessionLocal() as db:
        check_c = db.get(Conversation, cid)
        assert check_c.status == "resolved"
        assert check_c.resolved_at is not None

    # 3. Reopen conversation back to follow_up
    reopen_res = client.post(
        f"/api/analytics/conversations/{cid}/reopen",
        auth=auth,
    )
    assert reopen_res.status_code == 200
    reopen_data = reopen_res.json()
    assert reopen_data["status"] == "follow_up"
    assert reopen_data["resolved_at"] is None

    # 4. Reopen non-existent conversation returns 404
    bad_res = client.post(
        "/api/analytics/conversations/non-existent-id/reopen",
        auth=auth,
    )
    assert bad_res.status_code == 404

