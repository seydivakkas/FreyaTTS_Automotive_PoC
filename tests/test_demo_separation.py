"""Demo verisinin işletim verisinden ayrı kaldığını doğrular."""

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.analytics import get_analytics_overview
from backend.config import Settings
from backend.db import Base, Conversation
from backend.main import app, models, settings as app_settings

ROOT = Path(__file__).resolve().parents[1]


def test_demo_mode_is_off_by_default():
    settings = Settings(_env_file=None, demo_mode=False)
    assert settings.demo_mode is False
    assert Path(settings.data_dir) != Path("data/demo")


def test_demo_mode_overrides_operational_paths():
    settings = Settings(
        _env_file=None,
        demo_mode=True,
        database_url="sqlite:///./data/assistant.db",
        data_dir=Path("data"),
    )
    assert settings.database_url == "sqlite:///./data/demo/assistant.db"
    assert settings.data_dir == Path("data/demo")


def test_readiness_reports_real_state_without_loaded_models(monkeypatch):
    monkeypatch.setattr(app_settings, "admin_password", "secret")
    monkeypatch.setattr(models, "tts", None)
    monkeypatch.setattr(models, "stt", None)
    monkeypatch.setattr(models, "vad", None)
    monkeypatch.setattr(models, "load_ms", None)
    monkeypatch.setattr(models, "synth_count", 0)
    monkeypatch.setenv("DEMO_READY", "1")
    # Real readiness handler, isolated Ollama transport: a missing service must
    # not silently initiate network traffic in a hermetic test.
    import httpx
    from types import SimpleNamespace
    from backend.routers import core_system

    calls = []

    def unavailable(request):
        calls.append(request.url.path)
        raise httpx.ConnectError("synthetic Ollama unavailable", request=request)

    async_client = httpx.AsyncClient
    monkeypatch.setattr(
        core_system, "httpx",
        SimpleNamespace(AsyncClient=lambda **kwargs: async_client(
            transport=httpx.MockTransport(unavailable), **kwargs
        )),
    )
    body = TestClient(app).get("/api/readiness", auth=("admin", "secret")).json()
    assert calls == ["/api/tags"]
    assert body["ollama"]["status"] == "BLOCKED"
    assert body["demo_mode"] is False
    assert body["tts"]["status"] == "BLOCKED"
    assert body["stt"]["status"] == "BLOCKED"
    assert body["stt"]["device"] == app_settings.stt_device
    assert body["vad"]["status"] == "BLOCKED"
    assert body["model_load_ms"] is None
    assert body["synth_count"] == 0


def test_analytics_declares_data_source(monkeypatch):
    monkeypatch.setattr(app_settings, "admin_password", "secret")
    body = TestClient(app).get("/api/analytics/overview", auth=("admin", "secret")).json()
    assert body["data_source"] == "live"


def _empty_session(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "empty.db").as_posix())
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)()


def test_analytics_returns_null_without_measurements(tmp_path):
    engine, db = _empty_session(tmp_path)
    try:
        overview = get_analytics_overview(db)
    finally:
        db.close()
        engine.dispose()
    summary, kpis = overview["summary"], overview["latency_kpis"]
    assert summary["avg_duration_seconds"] is None
    assert summary["avg_turns_per_conversation"] is None
    assert summary["stt_clarity_rate_pct"] is None
    assert kpis["first_audio_ms"]["p50"] is None
    assert kpis["first_audio_ms"]["sample_count"] == 0
    assert kpis["llm_ms"]["p95_total"] is None
    assert kpis["stt_ms"]["avg"] is None
    assert kpis["tts_ms"]["avg_rtf"] is None


def test_analytics_has_no_special_case_for_demo_conversation_count(tmp_path):
    engine, db = _empty_session(tmp_path)
    try:
        created = datetime.now(timezone.utc).isoformat()
        db.add_all(
            Conversation(id=f"c{i}", channel="web", status="resolved", created_at=created)
            for i in range(97)
        )
        db.commit()
        summary = get_analytics_overview(db)["summary"]
    finally:
        db.close()
        engine.dispose()
    assert summary["total_conversations"] == 97
    assert summary["avg_turns_per_conversation"] == 0
    assert summary["avg_duration_seconds"] is None


def test_seed_script_writes_only_to_demo_database(tmp_path):
    # Çalışma dizini geçici olduğu için data/ yolları gerçek projeye ulaşamaz.
    env = {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "DATABASE_URL": "sqlite:///" + (tmp_path / "must-not-be-used.db").as_posix(),
        "DEMO_MODE": "0",
    }
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "seed_demo_telemetry.py")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / "must-not-be-used.db").exists()
    assert not (tmp_path / "data" / "assistant.db").exists()
    demo = sqlite3.connect(tmp_path / "data" / "demo" / "assistant.db")
    try:
        count = demo.execute("select count(*) from conversations").fetchone()[0]
    finally:
        demo.close()
    assert count == 97
