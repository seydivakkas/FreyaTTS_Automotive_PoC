# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlı olarak paylaşılmıştır.

import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.audio_archive_compliance import (
    AudioArchiveComplianceEngine,
    align_stereo_channels,
    calculate_retention_expiry,
    compute_hmac_sha256,
    compute_sha256,
)
from backend.config import settings
from backend.db import AudioArchive, Session
from backend.main import app


@pytest.fixture
def auth_headers(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret")
    creds = base64.b64encode(b"admin:secret").decode("ascii")
    return {"Authorization": f"Basic {creds}"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def test_engine(tmp_path: Path):
    return AudioArchiveComplianceEngine(
        archive_dir=tmp_path / "archives",
        master_key="test-compliance-secret-key-2026",
    )


def test_compress_decompress_opus(test_engine: AudioArchiveComplianceEngine):
    sr = 8000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    wav = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)

    compressed, ext = test_engine.compress_audio(wav, sample_rate=sr, codec="opus")
    assert ext == ".ogg"
    assert len(compressed) > 0
    # Raw S16LE size: 8000 samples * 2 bytes = 16,000 bytes
    raw_size = len(wav) * 2
    compression_ratio = (1.0 - (len(compressed) / raw_size)) * 100.0
    assert compression_ratio > 70.0  # OPUS achieves > 85% compression

    reconstructed, rec_sr = test_engine.decompress_audio(compressed)
    assert rec_sr == sr
    assert len(reconstructed) > 7000  # roughly 1 second


def test_compress_decompress_gsm610(test_engine: AudioArchiveComplianceEngine):
    sr = 8000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    wav = (0.4 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)

    compressed, ext = test_engine.compress_audio(wav, sample_rate=sr, codec="gsm_fr")
    assert ext == ".gsm.wav"
    assert len(compressed) > 0

    reconstructed, rec_sr = test_engine.decompress_audio(compressed)
    assert rec_sr == 8000
    assert len(reconstructed) > 7000


def test_stereo_alignment_and_compression(test_engine: AudioArchiveComplianceEngine):
    sr = 8000
    # Caller channel: 0.5s = 4000 samples
    caller = np.ones(4000, dtype=np.float32) * 0.3
    # Assistant channel: 1.0s = 8000 samples
    assistant = np.ones(8000, dtype=np.float32) * 0.5

    stereo = align_stereo_channels(caller, assistant)
    assert stereo.shape == (8000, 2)
    assert np.allclose(stereo[:4000, 0], 0.3)
    assert np.allclose(stereo[4000:, 0], 0.0)  # Zero-padded
    assert np.allclose(stereo[:, 1], 0.5)

    compressed, ext = test_engine.compress_audio(stereo, sample_rate=sr, codec="opus")
    assert ext == ".ogg"
    reconstructed, _ = test_engine.decompress_audio(compressed)
    assert reconstructed.shape[1] == 2


def test_archive_call_session_and_database(test_engine: AudioArchiveComplianceEngine):
    sr = 8000
    wav = np.zeros(8000, dtype=np.float32)

    with Session() as db:
        res = test_engine.archive_call_session(
            audio=wav,
            sample_rate=sr,
            call_session_id="test-session-123",
            caller_phone="05321112233",
            codec="opus",
            retention_years=2,
            db=db,
        )

        assert res.archive_id.startswith("arch-")
        assert res.codec == "opus"
        assert res.sample_rate == 8000
        assert res.duration_sec == 1.0
        assert res.compression_ratio_percent > 70.0
        assert len(res.raw_sha256) == 64
        assert len(res.archive_sha256) == 64
        assert len(res.hmac_signature) == 64
        assert Path(res.file_path).exists()

        # DB check
        record = db.get(AudioArchive, res.archive_id)
        assert record is not None
        assert record.call_session_id == "test-session-123"
        assert record.caller_phone == "05321112233"
        assert record.sha256_hash == res.archive_sha256


def test_verify_integrity_valid_and_tampered(test_engine: AudioArchiveComplianceEngine):
    sr = 8000
    wav = np.ones(4000, dtype=np.float32) * 0.2

    with Session() as db:
        res = test_engine.archive_call_session(
            audio=wav,
            sample_rate=sr,
            codec="opus",
            db=db,
        )

        # 1. Valid verification
        v_valid = test_engine.verify_archive_integrity(res.archive_id, db=db)
        assert v_valid.is_valid is True
        assert v_valid.status == "verified"
        assert v_valid.hmac_valid is True

        # 2. Tampered verification: alter file bytes on disk
        target_file = Path(res.file_path)
        original_bytes = target_file.read_bytes()
        tampered_bytes = original_bytes + b"MALICIOUS_TAMPER_DATA"
        target_file.write_bytes(tampered_bytes)

        v_tampered = test_engine.verify_archive_integrity(res.archive_id, db=db)
        assert v_tampered.is_valid is False
        assert v_tampered.status == "tampered"
        assert v_tampered.hmac_valid is False


def test_retention_audit_and_purge(test_engine: AudioArchiveComplianceEngine):
    sr = 8000
    wav = np.zeros(2000, dtype=np.float32)

    with Session() as db:
        res = test_engine.archive_call_session(
            audio=wav,
            sample_rate=sr,
            codec="opus",
            retention_years=2,
            db=db,
        )

        # Normal audit today
        audit_today = test_engine.audit_retention_compliance(db=db)
        assert audit_today["total_records"] >= 1
        assert audit_today["active_count"] >= 1

        # Audit 3 years in the future (all current archives should be expired)
        future_date = datetime.now(timezone.utc) + timedelta(days=3 * 365)
        audit_future = test_engine.audit_retention_compliance(db=db, target_date=future_date)
        assert audit_future["expired_count"] >= 1

        # Gelecek tarihle tasfiye yasal saklamayı atlatamaz: süre dolmadan kayıt tasfiye edilmez
        purge_future = test_engine.purge_expired_archives(db=db, dry_run=True, target_date=future_date)
        assert res.archive_id not in purge_future["purged_archive_ids"]

        # Kaydın saklama süresi gerçekten dolmuş olsun
        rec = db.get(AudioArchive, res.archive_id)
        rec.expires_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        db.commit()

        # Dry run purge
        purge_dry = test_engine.purge_expired_archives(db=db, dry_run=True)
        assert purge_dry["dry_run"] is True
        assert purge_dry["purged_count"] >= 1
        assert Path(res.file_path).exists()  # Not deleted in dry run

        # Real purge
        purge_real = test_engine.purge_expired_archives(db=db, dry_run=False)
        assert purge_real["dry_run"] is False
        assert purge_real["purged_count"] >= 1
        assert not Path(res.file_path).exists()  # Deleted from disk

        # Record status should be 'purged' (tombstone)
        updated_rec = db.get(AudioArchive, res.archive_id)
        assert updated_rec.status == "purged"


def test_rest_api_archive_endpoints(client: TestClient, auth_headers: dict):
    # 1. Archive call session
    t = np.linspace(0, 0.2, 1600, endpoint=False)
    wav_i16 = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
    audio_b64 = base64.b64encode(wav_i16.tobytes()).decode("ascii")

    post_resp = client.post(
        "/api/archive/call-session",
        headers=auth_headers,
        json={
            "audio_base64": audio_b64,
            "sample_rate": 8000,
            "call_session_id": "api-session-test",
            "caller_phone": "05559998877",
            "codec": "opus",
            "retention_years": 2,
        },
    )
    assert post_resp.status_code == 200
    arch_data = post_resp.json()
    arch_id = arch_data["archive_id"]
    assert arch_id.startswith("arch-")
    assert arch_data["compression_ratio_percent"] > 50.0

    # 2. Verify endpoint
    ver_resp = client.get(f"/api/archive/{arch_id}/verify", headers=auth_headers)
    assert ver_resp.status_code == 200
    assert ver_resp.json()["is_valid"] is True
    assert ver_resp.json()["status"] == "verified"

    # 3. Download endpoint
    dl_resp = client.get(f"/api/archive/{arch_id}/download", headers=auth_headers)
    assert dl_resp.status_code == 200
    assert "X-Freya-SHA256" in dl_resp.headers
    assert "X-Freya-HMAC" in dl_resp.headers
    assert len(dl_resp.content) > 0

    # 4. Retention audit endpoint
    audit_resp = client.get("/api/archive/retention-audit", headers=auth_headers)
    assert audit_resp.status_code == 200
    assert "total_records" in audit_resp.json()

    # 5. Retention purge endpoint
    purge_resp = client.post(
        "/api/archive/retention-purge",
        headers=auth_headers,
        json={"dry_run": True},
    )
    assert purge_resp.status_code == 200
    assert purge_resp.json()["dry_run"] is True

    # 6. Hassas tablo genel liste ucundan kaldırıldı
    list_resp = client.get("/api/audio-archives", headers=auth_headers)
    assert list_resp.status_code == 404

