"""Güvenlik paketi P1: webhook anahtarı, imzalı bağlantılar, yükleme sınırları, arşiv güvenliği."""

import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend import ami as ami_module
from backend.audio_archive_compliance import (
    ArchiveKeyMissingError,
    AudioArchiveComplianceEngine,
)
from backend.config import settings
from backend.db import (
    AudioArchive,
    InspectionReport,
    Session,
    Vehicle,
    VehicleDiagnostic,
)
from backend.main import app
from backend.security_utils import MAX_IMAGE_BYTES, signed_pdf_path


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret")
    creds = base64.b64encode(b"admin:secret").decode("ascii")
    return {"Authorization": f"Basic {creds}"}


@pytest.fixture
def report_id():
    with Session() as db:
        v = Vehicle(description="Test Araç", plate="34 SEC 01")
        db.add(v)
        db.flush()
        r = InspectionReport(vehicle_id=v.id, technician_name="T", summary="s", score=90)
        db.add(r)
        db.commit()
        return r.id


# --- WhatsApp webhook ---

WEBHOOK_FORM = {"From": "whatsapp:+905351112244", "Body": "Onaylıyorum", "MessageSid": "SMsec1"}


def test_webhook_anonymous_rejected(client):
    assert client.post("/api/webhooks/whatsapp", data=WEBHOOK_FORM).status_code == 401


def test_webhook_wrong_token_rejected(client):
    r = client.post(
        "/api/webhooks/whatsapp", data=WEBHOOK_FORM, headers={"X-Webhook-Token": "yanlis"}
    )
    assert r.status_code == 401


def test_webhook_correct_token_accepted(client):
    r = client.post(
        "/api/webhooks/whatsapp",
        data=WEBHOOK_FORM,
        headers={"X-Webhook-Token": settings.whatsapp_webhook_token},
    )
    assert r.status_code == 200


def test_webhook_unset_token_returns_503(client, monkeypatch):
    monkeypatch.setattr(settings, "whatsapp_webhook_token", "")
    r = client.post("/api/webhooks/whatsapp", data=WEBHOOK_FORM, headers={"X-Webhook-Token": ""})
    assert r.status_code == 503


# --- /metrics ve PDF ---


def test_metrics_requires_auth(client, auth_headers):
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers=auth_headers).status_code == 200


def test_pdf_anonymous_rejected(client, report_id):
    assert client.get(f"/api/inspections/{report_id}/pdf").status_code == 401


def test_pdf_with_basic_auth(client, auth_headers, report_id):
    assert client.get(f"/api/inspections/{report_id}/pdf", headers=auth_headers).status_code == 200


def test_signed_link_endpoint_and_access(client, auth_headers, report_id):
    assert client.get(f"/api/inspections/{report_id}/signed-link").status_code == 401
    r = client.get(f"/api/inspections/{report_id}/signed-link", headers=auth_headers)
    assert r.status_code == 200
    url = r.json()["url"]
    assert url.startswith(f"/api/inspections/{report_id}/pdf?exp=")
    pdf = client.get(url)  # kimlik bilgisi yok, yalnızca imza
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")


def test_signed_link_expired_and_tampered(client, report_id):
    expired = signed_pdf_path(report_id, ttl_sec=-10)
    assert client.get(expired).status_code == 401

    valid = signed_pdf_path(report_id)
    assert client.get(valid.replace("sig=", "sig=0")).status_code == 401
    # Başka bir rapora ait imza kullanılamaz
    other = valid.replace(report_id, "baska-id")
    assert client.get(other).status_code == 401
    # Süre uzatma denemesi imzayı bozar
    exp = int(valid.split("exp=")[1].split("&")[0])
    assert client.get(valid.replace(f"exp={exp}", f"exp={exp + 1000}")).status_code == 401


def test_signed_access_disabled_when_key_empty(client, report_id, monkeypatch):
    url = signed_pdf_path(report_id)
    monkeypatch.setattr(settings, "link_signing_key", "")
    assert client.get(url).status_code == 401


def test_send_link_returns_signed_url(client, auth_headers, report_id):
    r = client.post(f"/api/inspections/{report_id}/send-link", headers=auth_headers)
    assert r.status_code == 200
    assert "exp=" in r.json()["url"] and "sig=" in r.json()["url"]


# --- Genel liste sayfalama ---


def test_generic_listing_limit_offset_and_cap(client, auth_headers):
    with Session() as db:
        for i in range(5):
            db.add(Vehicle(description=f"Liste {i}", plate=f"34 LST {i}"))
        db.commit()
    all_rows = client.get("/api/vehicles", headers=auth_headers).json()
    assert isinstance(all_rows, list)
    page = client.get("/api/vehicles?limit=2&offset=1", headers=auth_headers).json()
    assert len(page) == 2
    assert page[0]["id"] == all_rows[1]["id"]
    assert client.get("/api/vehicles?limit=1001", headers=auth_headers).status_code == 422
    assert client.get("/api/vehicles?limit=0", headers=auth_headers).status_code == 422
    for sensitive in ("audio-archives", "whatsapp-messages", "ruhsat-scans", "call-analytics"):
        assert client.get(f"/api/{sensitive}", headers=auth_headers).status_code == 404


# --- Yükleme sınırları ---


def test_photo_upload_over_cap_returns_413(client, auth_headers):
    big = b"\xff" * (MAX_IMAGE_BYTES + 1)
    r = client.post(
        "/api/inspections/photos",
        headers=auth_headers,
        files={"file": ("buyuk.jpg", big, "image/jpeg")},
    )
    assert r.status_code == 413


def test_photo_upload_within_cap_ok(client, auth_headers):
    r = client.post(
        "/api/inspections/photos",
        headers=auth_headers,
        files={"file": ("kucuk.jpg", b"\xff\xd8\xff", "image/jpeg")},
    )
    assert r.status_code == 200


def test_base64_audio_field_over_cap_rejected(client, auth_headers):
    from backend.main import AUDIO_B64_MAX

    r = client.post(
        "/api/outbound/amd-analyze",
        headers=auth_headers,
        json={"audio_base64": "A" * (AUDIO_B64_MAX + 4), "sample_rate": 8000},
    )
    assert r.status_code == 422


# --- Arşiv: anahtarsız kapalı, tasfiye ---


def _engine(tmp_path, key="k-test"):
    return AudioArchiveComplianceEngine(archive_dir=tmp_path, master_key=key)


def test_archive_without_key_fails_closed(client, auth_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "audio_archive_master_key", "")
    with pytest.raises(ArchiveKeyMissingError):
        AudioArchiveComplianceEngine(archive_dir=tmp_path).archive_call_session(
            audio=np.zeros(800, dtype=np.float32)
        )
    assert list(tmp_path.rglob("*.ogg")) == []
    pcm = base64.b64encode(np.zeros(800, dtype=np.int16).tobytes()).decode()
    r = client.post("/api/archive/call-session", headers=auth_headers, json={"audio_base64": pcm})
    assert r.status_code == 503
    assert client.get("/api/archive/x/verify", headers=auth_headers).status_code == 503


def test_verify_never_succeeds_without_stored_hmac(tmp_path):
    eng = _engine(tmp_path)
    with Session() as db:
        res = eng.archive_call_session(audio=np.zeros(800, dtype=np.float32), db=db)
        rec = db.get(AudioArchive, res.archive_id)
        rec.hmac_signature = ""
        db.commit()
        out = eng.verify_archive_integrity(res.archive_id, db=db)
    assert out.is_valid is False
    assert out.status == "unverifiable"


def _expired_archive(eng, db):
    res = eng.archive_call_session(audio=np.zeros(800, dtype=np.float32), db=db)
    rec = db.get(AudioArchive, res.archive_id)
    rec.expires_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    db.commit()
    return res


def test_purge_future_target_date_rejected(client, auth_headers):
    future = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()
    r = client.post(
        "/api/archive/retention-purge",
        headers=auth_headers,
        json={"dry_run": True, "target_date": future},
    )
    assert r.status_code == 400


def test_purge_engine_clamps_future_date(tmp_path):
    eng = _engine(tmp_path)
    with Session() as db:
        res = eng.archive_call_session(audio=np.zeros(800, dtype=np.float32), db=db)
        out = eng.purge_expired_archives(
            db, dry_run=False, target_date=datetime.now(timezone.utc) + timedelta(days=5000)
        )
        assert res.archive_id not in out["purged_archive_ids"]
        assert db.get(AudioArchive, res.archive_id).status != "purged"


def test_purge_failed_unlink_not_marked_purged(tmp_path, monkeypatch):
    eng = _engine(tmp_path)
    with Session() as db:
        res = _expired_archive(eng, db)

        def boom(self, *a, **k):
            raise PermissionError("kilitli")

        with monkeypatch.context() as m:
            m.setattr(Path, "unlink", boom)
            out = eng.purge_expired_archives(db, dry_run=False)
        assert res.archive_id in out["failed_archive_ids"]
        assert res.archive_id not in out["purged_archive_ids"]
        assert db.get(AudioArchive, res.archive_id).status != "purged"
        out = eng.purge_expired_archives(db, dry_run=False)
        assert res.archive_id in out["purged_archive_ids"]
        assert db.get(AudioArchive, res.archive_id).status == "purged"


# --- Teşhis: telefon yok ---


class _CountingAMI:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        async def _record(*a, **k):
            self.calls.append((name, a, k))
            return {"response": "Success"}

        return _record


def test_diagnostic_without_phone_does_not_call(client, auth_headers):
    mock = _CountingAMI()
    previous = ami_module.get_ami_client()
    ami_module.set_ami_client(mock)
    try:
        with Session() as db:
            v = Vehicle(description="Telefonsuz", plate="34 NOP 01")
            db.add(v)
            db.flush()
            d = VehicleDiagnostic(
                vehicle_id=v.id,
                dtc_code="P0301",
                description_tr="Silindir 1",
                recommended_action="Kontrol",
                owner_name="X",
                owner_phone="",
            )
            db.add(d)
            db.commit()
            did = d.id
        call = client.post(f"/api/diagnostics/{did}/call", headers=auth_headers, json={})
        sms = client.post(f"/api/diagnostics/{did}/sms", headers=auth_headers, json={})
        assert call.status_code == 422 and "Telefon yok" in call.json()["detail"]
        assert sms.status_code == 422
        assert mock.calls == []
    finally:
        ami_module.set_ami_client(previous)
