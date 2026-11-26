from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend import db as db_module
from backend.db import Base
from backend import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "api.db"),
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr("backend.db.Session", sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(main.settings, "admin_password", "test-password")
    c = TestClient(main.app)
    yield c
    c.close()
    engine.dispose()


def test_auth_required(client):
    assert client.get("/api/vehicles").status_code == 401
    assert client.get("/api/vehicles", auth=("admin", "wrong")).status_code == 401
    assert client.get("/api/health").json() == {"status": "alive"}


def test_rendezvous_routes(client):
    auth = ("admin", "test-password")
    v = client.post(
        "/api/vehicles", auth=auth, json={"description": "Test Passat", "plate": "TEST"}
    ).json()
    q = client.post(
        "/api/quotes", auth=auth, json={"vehicle_id": v["id"], "amount_kurus": 125050}
    )
    assert q.status_code == 200
    slot = client.post(
        "/api/slots",
        auth=auth,
        json={
            "starts_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        },
    ).json()
    body = {
        "slot_id": slot["id"],
        "vehicle_id": v["id"],
        "customer": "Test müşteri",
        "idempotency_key": "test-booking",
        "confirmed": False,
    }
    assert client.post("/api/appointments", auth=auth, json=body).status_code == 422
    body["confirmed"] = True
    a = client.post("/api/appointments", auth=auth, json=body)
    assert a.status_code == 200
    assert (
        client.post("/api/appointments", auth=auth, json=body).json()["id"]
        == a.json()["id"]
    )
    body["idempotency_key"] = "conflict"
    assert client.post("/api/appointments", auth=auth, json=body).status_code == 409
    assert (
        client.post(
            "/api/appointments/" + a.json()["id"] + "/cancel", auth=auth
        ).json()["slot_id"]
        is None
    )


def test_ws_ticket_and_invalid_format(client):
    from starlette.websockets import WebSocketDisconnect

    # Kod/neden tarayıcıya ulaşsın diye bağlantı önce kabul edilir, sonra kapatılır.
    with client.websocket_connect("/ws/voice?ticket=invalid") as bad:
        with pytest.raises(WebSocketDisconnect) as closed:
            bad.receive_text()
    assert closed.value.code == 1008
    assert closed.value.reason == "ticket_expired"
    token = client.post("/api/session-ticket", auth=("admin", "test-password")).json()[
        "ticket"
    ]
    with client.websocket_connect("/ws/voice?ticket=" + token) as ws:
        ws.send_json({"sample_rate": 123, "encoding": "pcm_s16le", "channels": 1})
        assert ws.receive_json()["type"] == "error"
    with client.websocket_connect("/ws/voice?ticket=" + token) as reused:
        with pytest.raises(WebSocketDisconnect) as closed:
            reused.receive_text()
    assert closed.value.code == 1008


def test_ws_busy_line_has_distinct_close_code(client, monkeypatch):
    """Meşgul hat (1013/line_busy) ile süresi dolan bilet (1008) ayırt edilir."""
    from starlette.websockets import WebSocketDisconnect

    token = client.post("/api/session-ticket", auth=("admin", "test-password")).json()[
        "ticket"
    ]
    monkeypatch.setattr(main.active, "locked", lambda: True)
    with client.websocket_connect("/ws/voice?ticket=" + token) as busy:
        with pytest.raises(WebSocketDisconnect) as closed:
            busy.receive_text()
    assert closed.value.code == 1013
    assert closed.value.reason == "line_busy"


async def test_teardown_failure_releases_single_call_capacity(client, monkeypatch):
    """Deterministik ASGI sınırı: TestClient context iptali ile close() yarışmaz."""
    import time
    from backend.batched_ode import ConcurrentCallController

    closed = []

    class BrokenClose:
        def __init__(self, channel, emit, send):
            self.emit = emit
            self.closed = False

        async def start(self):
            await self.emit({"type": "session"})

        async def close(self):
            closed.append(True)
            raise RuntimeError("close failed")

    class Socket:
        query_params = {"ticket": "synthetic-teardown"}

        def __init__(self):
            self.close_called = False

        async def accept(self):
            pass

        async def receive_json(self):
            return {"sample_rate": 48000, "encoding": "pcm_s16le", "channels": 1}

        async def receive(self):
            return {"type": "websocket.disconnect"}

        async def send_json(self, event):
            pass

        async def close(self, **kwargs):
            self.close_called = True

    # Gerçek kapasite denetleyicisi, tek slot; sahte ASGI taşıyıcı.
    controller = ConcurrentCallController(max_concurrent=1)
    monkeypatch.setattr(main, "active", controller)
    monkeypatch.setattr(main, "VoiceSession", BrokenClose)
    monkeypatch.setattr(main.settings, "auto_load_models", False)
    monkeypatch.setitem(main.tickets, "synthetic-teardown", time.monotonic() + 30)
    ws = Socket()
    with pytest.raises(RuntimeError, match="close failed"):
        await main.voice(ws)
    assert closed == [True]
    assert ws.close_called
    assert controller.active_count == 0
    assert not controller.locked()
    await controller.acquire()
    assert controller.locked()
    controller.release()
    assert not controller.locked()


def test_vehicle_crud(client):
    auth = ("admin", "test-password")
    v = client.post(
        "/api/vehicles", auth=auth, json={"description": "Renault Megane", "plate": "34ABC01"}
    ).json()
    v_id = v["id"]
    assert v["description"] == "Renault Megane"
    assert v["plate"] == "34ABC01"

    # Update description and plate
    updated = client.put(
        f"/api/vehicles/{v_id}",
        auth=auth,
        json={"description": "Renault Megane E-Tech", "plate": "34DEF02"},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Renault Megane E-Tech"
    assert updated.json()["plate"] == "34DEF02"

    # Add quote
    q = client.post(
        "/api/quotes", auth=auth, json={"vehicle_id": v_id, "amount_kurus": 250000}
    )
    assert q.status_code == 200

    # Delete vehicle with quote (should cascade/delete quote)
    deleted = client.delete(f"/api/vehicles/{v_id}", auth=auth)
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "id": v_id}

    # 404 for deleted vehicle
    assert client.get(f"/api/vehicles/{v_id}", auth=auth).status_code == 404
    assert client.put(f"/api/vehicles/{v_id}", auth=auth, json={"description": "Gecersiz Arac"}).status_code == 404
    assert client.delete(f"/api/vehicles/{v_id}", auth=auth).status_code == 404

    # Deletion prevented if appointment exists
    v2 = client.post(
        "/api/vehicles", auth=auth, json={"description": "Fiat Egea", "plate": "06AAA01"}
    ).json()
    slot = client.post(
        "/api/slots",
        auth=auth,
        json={"starts_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()},
    ).json()
    client.post(
        "/api/appointments",
        auth=auth,
        json={
            "slot_id": slot["id"],
            "vehicle_id": v2["id"],
            "customer": "Test",
            "idempotency_key": "crud-prevent-del",
            "confirmed": True,
        },
    )
    # Trying to delete vehicle with existing appointment raises 409
    assert client.delete(f"/api/vehicles/{v2['id']}", auth=auth).status_code == 409


def test_slot_duration_and_overlap(client):
    auth = ("admin", "test-password")
    base_time = datetime.now(timezone.utc) + timedelta(days=3)

    # Create slot with 45 minutes duration
    s1 = client.post(
        "/api/slots",
        auth=auth,
        json={"starts_at": base_time.isoformat(), "duration_minutes": 45},
    )
    assert s1.status_code == 200
    assert s1.json()["duration_minutes"] == 45

    # Overlapping slot (starts 15 minutes after s1 started, within 45 min window)
    overlap_time = base_time + timedelta(minutes=15)
    s_overlap = client.post(
        "/api/slots",
        auth=auth,
        json={"starts_at": overlap_time.isoformat(), "duration_minutes": 30},
    )
    assert s_overlap.status_code == 409

    # Non-overlapping slot (starts 50 minutes after s1 started)
    valid_time = base_time + timedelta(minutes=50)
    s2 = client.post(
        "/api/slots",
        auth=auth,
        json={"starts_at": valid_time.isoformat(), "duration_minutes": 30},
    )
    assert s2.status_code == 200


def test_conversation_export(client):
    auth = ("admin", "test-password")
    from uuid import uuid4
    from backend.db import Conversation, Turn

    cid = str(uuid4())
    with db_module.Session() as db:
        c = Conversation(id=cid, channel="web", status="completed")
        t1 = Turn(
            conversation_id=cid,
            role="user",
            text="Merhaba",
            metrics='{"stt_ms": 120.5}',
        )
        t2 = Turn(
            conversation_id=cid,
            role="assistant",
            text="Merhaba, nasıl yardımcı olabilirim?",
            metrics='{"tts_ms": 340.2}',
        )
        db.add_all([c, t1, t2])
        db.commit()

    # JSON export
    res_json = client.get(f"/api/conversations/{cid}/export?format=json", auth=auth)
    assert res_json.status_code == 200
    data = res_json.json()
    assert data["turn_count"] == 2
    assert data["turns"][0]["role"] == "user"
    assert data["turns"][0]["metrics"]["stt_ms"] == 120.5
    assert data["turns"][1]["role"] == "assistant"

    # CSV export
    res_csv = client.get(f"/api/conversations/{cid}/export?format=csv", auth=auth)
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["content-type"]
    csv_text = res_csv.text
    assert "conversation_id,turn_id,created_at,role,text,metrics_json" in csv_text
    assert "Merhaba" in csv_text

    # 404 for nonexistent conversation
    assert (
        client.get(f"/api/conversations/{uuid4()}/export", auth=auth).status_code == 404
    )


def test_hotwords_management(client):
    auth = ("admin", "test-password")

    # Initial state
    initial = client.get("/api/hotwords", auth=auth).json()
    assert "catalog_vehicles" in initial
    assert "custom_hotwords" in initial

    # Update custom hotwords
    update_res = client.post(
        "/api/hotwords",
        auth=auth,
        json={"words": ["Ekspertiz", "Dyno", "Tramer"]},
    )
    assert update_res.status_code == 200
    assert update_res.json()["custom_hotwords"] == ["Ekspertiz", "Dyno", "Tramer"]

    # Verify retrieval
    after = client.get("/api/hotwords", auth=auth).json()
    assert after["custom_hotwords"] == ["Ekspertiz", "Dyno", "Tramer"]
    assert "Ekspertiz" in after["active_hints"]


def test_corporate_accounts_crud_and_limits(client):
    auth = ("admin", "test-password")

    # 1. Create corporate account
    body = {
        "name": "Yıldız Oto Galeri",
        "tax_id": "1234567890",
        "phone": "05551234567",
        "credit_limit_kurus": 300000,  # 3.000 TL limit
        "discount_percent": 15,
        "active": True,
    }
    res = client.post("/api/corporate-accounts", auth=auth, json=body)
    assert res.status_code == 200
    acc = res.json()
    acc_id = acc["id"]
    assert acc["name"] == "Yıldız Oto Galeri"
    assert acc["balance_kurus"] == 0

    # Duplicate tax_id raises 409
    assert client.post("/api/corporate-accounts", auth=auth, json=body).status_code == 409

    # Update account
    updated = client.put(
        f"/api/corporate-accounts/{acc_id}",
        auth=auth,
        json={"phone": "05559876543", "discount_percent": 20},
    )
    assert updated.status_code == 200
    assert updated.json()["phone"] == "05559876543"
    assert updated.json()["discount_percent"] == 20

    # 2. Setup vehicle, quote, and slot
    v = client.post(
        "/api/vehicles", auth=auth, json={"description": "BMW 320i", "plate": "34CORP01"}
    ).json()
    # 2.000 TL normal quote
    client.post("/api/quotes", auth=auth, json={"vehicle_id": v["id"], "amount_kurus": 200000})
    slot = client.post(
        "/api/slots",
        auth=auth,
        json={"starts_at": (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()},
    ).json()

    # 3. Book appointment under corporate account (20% discount on 200000 = 160000 kurus)
    booking = {
        "slot_id": slot["id"],
        "vehicle_id": v["id"],
        "customer": "Yıldız Galeri - Yetkili Ahmet",
        "idempotency_key": "corp-book-1",
        "confirmed": True,
        "corporate_account_id": acc_id,
    }
    b_res = client.post("/api/appointments", auth=auth, json=booking)
    assert b_res.status_code == 200
    appt = b_res.json()
    assert appt["corporate_account_id"] == acc_id
    assert appt["billed_amount_kurus"] == 160000

    # Check updated balance
    acc_check = client.get(f"/api/corporate-accounts/{acc_id}", auth=auth).json()
    assert acc_check["balance_kurus"] == 160000

    # Check ledger
    ledger = client.get(f"/api/corporate-accounts/{acc_id}/ledger", auth=auth).json()
    assert len(ledger) == 1
    assert ledger[0]["entry_type"] == "charge"
    assert ledger[0]["amount_kurus"] == 160000

    # 4. Deleting corporate account with active appointment is blocked (409)
    assert client.delete(f"/api/corporate-accounts/{acc_id}", auth=auth).status_code == 409

    # 5. Record payment (reduce balance by 100000 kurus)
    pay_res = client.post(
        f"/api/corporate-accounts/{acc_id}/payments",
        auth=auth,
        json={"amount_kurus": 100000, "description": "Banka havalesi tahsilatı"},
    )
    assert pay_res.status_code == 200
    acc_after_pay = client.get(f"/api/corporate-accounts/{acc_id}", auth=auth).json()
    assert acc_after_pay["balance_kurus"] == 60000

    # 6. Test credit limit exceeded
    # Remaining credit: 300000 - 60000 = 240000. Next booking charge is 160000. That would be 220000 (fits).
    # But if we try a vehicle with quote 400000 (after 20% discount = 320000 charge):
    # 60000 + 320000 = 380000 > 300000 limit -> Should raise 422
    v_expensive = client.post(
        "/api/vehicles", auth=auth, json={"description": "Porsche Taycan", "plate": "34CORP02"}
    ).json()
    client.post("/api/quotes", auth=auth, json={"vehicle_id": v_expensive["id"], "amount_kurus": 400000})
    slot2 = client.post(
        "/api/slots",
        auth=auth,
        json={"starts_at": (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()},
    ).json()
    limit_booking = {
        "slot_id": slot2["id"],
        "vehicle_id": v_expensive["id"],
        "customer": "Yıldız Galeri - Mehmet",
        "idempotency_key": "corp-book-limit-exceeded",
        "confirmed": True,
        "corporate_account_id": acc_id,
    }
    limit_res = client.post("/api/appointments", auth=auth, json=limit_booking)
    assert limit_res.status_code == 422
    assert "kredi limiti" in limit_res.json()["detail"].lower()

    # 7. Test inactive account
    client.put(f"/api/corporate-accounts/{acc_id}", auth=auth, json={"active": False})
    inactive_res = client.post("/api/appointments", auth=auth, json=booking)
    # Different idempotency_key for new booking
    booking["idempotency_key"] = "corp-book-inactive"
    inactive_res = client.post("/api/appointments", auth=auth, json=booking)
    assert inactive_res.status_code == 422
    assert "aktif değil" in inactive_res.json()["detail"].lower()


def test_vin_validation_and_inspection_reports(client):
    auth = ("admin", "test-password")

    # 1. Invalid VIN (contains forbidden letter 'O' and invalid length)
    bad_vin_res = client.post(
        "/api/vehicles",
        auth=auth,
        json={"description": "Test Aracı", "plate": "34TEST99", "vin": "WVWZZZ3CZWE12345O"},
    )
    assert bad_vin_res.status_code == 422
    assert "şase numarası" in bad_vin_res.json()["detail"].lower()

    # 2. Valid 17-char VIN
    valid_vin = "1HGCR2F83HA000000"
    v_res = client.post(
        "/api/vehicles",
        auth=auth,
        json={"description": "Honda Accord", "plate": "34HND01", "vin": valid_vin},
    )
    assert v_res.status_code == 200
    veh = v_res.json()
    veh_id = veh["id"]
    assert veh["vin"] == valid_vin

    # 3. Add past inspection reports to this vehicle
    r1 = client.post(
        f"/api/vehicles/{veh_id}/inspections",
        auth=auth,
        json={
            "summary": "Sol ön çamurluk lokal boyalı, motor performansı %94, şasi orijinal.",
            "mileage_km": 85000,
            "score": 92,
        },
    )
    assert r1.status_code == 200
    assert r1.json()["score"] == 92

    r2 = client.post(
        f"/api/vehicles/{veh_id}/inspections",
        auth=auth,
        json={
            "summary": "Periyodik muayene öncesi genel ekspertiz, mekanik sorunsuz.",
            "mileage_km": 110000,
            "score": 88,
        },
    )
    assert r2.status_code == 200

    # 4. Get inspections list
    list_res = client.get(f"/api/vehicles/{veh_id}/inspections", auth=auth)
    assert list_res.status_code == 200
    inspections = list_res.json()
    assert len(inspections) == 2

    # 5. Lookup vehicle by VIN
    by_vin_res = client.get(f"/api/vehicles/by-vin/{valid_vin}", auth=auth)
    assert by_vin_res.status_code == 200
    vin_data = by_vin_res.json()
    assert vin_data["vehicle"]["id"] == veh_id
    assert vin_data["inspection_count"] == 2
    assert len(vin_data["inspections"]) == 2

    # 6. Non-existent VIN returns 404
    assert client.get("/api/vehicles/by-vin/1HGCR2F83HA999999", auth=auth).status_code == 404


def test_lexicon_management(client, tmp_path, monkeypatch):
    from backend import normalizer_rules

    for name in ("AUTOMOTIVE_LEXICON", "CUSTOM_LEXICON", "CUSTOM_CATEGORIES"):
        monkeypatch.setattr(normalizer_rules, name, getattr(normalizer_rules, name).copy())
    save = normalizer_rules.save_custom_lexicon
    monkeypatch.setattr(normalizer_rules, "save_custom_lexicon", lambda _path: save(tmp_path / "lexicon.json"))

    auth = ("admin", "test-password")

    # 1. Fetch lexicon list
    res = client.get("/api/lexicon", auth=auth)
    assert res.status_code == 200
    entries = res.json()
    assert isinstance(entries, list)
    assert len(entries) > 20
    # Check structure
    sample = next((e for e in entries if e["term"].lower() == "volkswagen"), None)
    assert sample is not None
    assert sample["is_base"] is True
    assert sample["spoken"].lower() == "folksvagen"

    # 2. Validation errors (empty term or invalid characters)
    assert client.post("/api/lexicon", auth=auth, json={"term": "", "spoken": "test"}).status_code == 422
    assert client.post("/api/lexicon", auth=auth, json={"term": "Chery", "spoken": ""}).status_code == 422

    # 3. Add custom automotive term
    add_res = client.post(
        "/api/lexicon",
        auth=auth,
        json={"term": "Chery Tiggo", "spoken": "çeri tigo", "category": "model"},
    )
    assert add_res.status_code == 200
    added = add_res.json()
    assert added["term"] == "Chery Tiggo"
    assert added["spoken"] == "çeri tigo"
    assert added["is_base"] is False
    assert added["is_override"] is False

    # 4. Verify live normalization uses the new term
    norm_res = client.post(
        "/api/normalize",
        auth=auth,
        json={"text": "Chery Tiggo aracınız için ekspertiz randevusu oluşturuldu."},
    )
    assert norm_res.status_code == 200
    assert "çeri tigo" in norm_res.json()["normalized"]

    # 5. Override an existing base term
    orig_passat = next((e for e in entries if e["term"] == "passat"), None)["spoken"]
    upd_res = client.post(
        "/api/lexicon",
        auth=auth,
        json={"term": "Passat", "spoken": "pasat sedan", "category": "model"},
    )
    assert upd_res.status_code == 200
    assert upd_res.json()["is_override"] is True

    norm_passat = client.post(
        "/api/normalize",
        auth=auth,
        json={"text": "Volkswagen Passat randevunuz hazır."},
    )
    assert "pasat sedan" in norm_passat.json()["normalized"]

    # 6. Delete override reverts to base
    del_override = client.delete("/api/lexicon/Passat", auth=auth)
    assert del_override.status_code == 200
    assert del_override.json()["reverted_to_base"] is True

    # Check normalization reverted
    norm_passat_rev = client.post(
        "/api/normalize",
        auth=auth,
        json={"text": "Volkswagen Passat randevunuz hazır."},
    )
    assert "Folksvagen Passat" in norm_passat_rev.json()["normalized"]

    # 7. Delete custom term
    del_custom = client.delete("/api/lexicon/Chery%20Tiggo", auth=auth)
    assert del_custom.status_code == 200
    assert del_custom.json()["deleted"] is True
    assert del_custom.json()["reverted_to_base"] is False

    # 8. Reset lexicon
    reset_res = client.post("/api/lexicon/reset", auth=auth)
    assert reset_res.status_code == 200
    assert reset_res.json()["reset"] is True


def test_voice_chat_turn_endpoint(client, fake_llm):
    # H01.01: canlı Ollama yerine SAHTE LLM yanıtı (tests/fakes/fake_llm.py); ağ çağrısı yok.
    fake_llm.reply({})
    auth = ("admin", "test-password")
    res = client.post(
        "/api/voice/chat-turn",
        auth=auth,
        json={"text": "Periyodik bakım randevusu almak istiyorum", "session_id": "test-chat-turn-1", "reset": True},
    )
    assert res.status_code == 200
    data = res.json()
    assert "reply" in data
    assert "slot_info" in data
    assert "pipeline_events" in data
    events = data["pipeline_events"]
    assert any(e["stage"] == "F0" and e["status"] == "bypassed" and e["source"] == "text_input" for e in events)
    assert any(e["stage"] == "F1" and e["status"] == "bypassed" and e["source"] == "text_input" for e in events)
    assert any(e["stage"] == "F2" and e["status"] == "bypassed" and e["source"] == "text_input" for e in events)
    assert any(e["stage"] == "F3" and e["status"] == "completed" and e["source"] == "text_input" for e in events)
    assert data["slot_info"]["intent"] is not None


def test_ws_voice_text_input_lifecycle(client, monkeypatch):
    import numpy as np

    async def dummy_synth(*args, **kwargs):
        return np.ones(4800, np.float32) * 0.1

    async def dummy_load():
        pass

    class DummyVad:
        def reset_states(self):
            pass

    monkeypatch.setattr(main.models, "synth", dummy_synth)
    monkeypatch.setattr(main.models, "load", dummy_load)
    monkeypatch.setattr(main.models, "vad", DummyVad())
    monkeypatch.setattr(main.models, "ollama_ready", True)

    auth = ("admin", "test-password")
    ticket_res = client.post("/api/session-ticket", auth=auth)
    assert ticket_res.status_code == 200
    ticket = ticket_res.json()["ticket"]

    with client.websocket_connect(f"/ws/voice?ticket={ticket}") as ws:
        # 1. Ses formatı el sıkışması
        ws.send_json({"sample_rate": 16000, "encoding": "pcm_s16le", "channels": 1})

        # 2. Doğrudan metin mesajı gönder
        ws.send_json({"type": "text_input", "text": "Merhabalar, kolay gelsin"})

        # Yanıtları topla
        received_types = []
        pipeline_stages = []
        got_user = False
        for _ in range(40):
            try:
                msg = ws.receive_json()
                t = msg.get("type")
                if t == "error":
                    assert False, f"WS error message was: {msg}"
                received_types.append(t)
                if t == "pipeline_event":
                    ev = msg.get("event", {})
                    pipeline_stages.append((ev.get("stage"), ev.get("status"), ev.get("source")))
                if t == "transcript":
                    if msg.get("role") == "user":
                        got_user = True
                    elif msg.get("role") == "assistant" and got_user:
                        break
            except Exception as exc:
                raise AssertionError(f"WS receive error: {type(exc)} {exc}")

        assert "transcript" in received_types
        assert ("F0", "bypassed", "text_input") in pipeline_stages
        assert ("F1", "bypassed", "text_input") in pipeline_stages
        assert ("F2", "bypassed", "text_input") in pipeline_stages
