"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
amaçlı olarak paylaşılmıştır.

YASAKLAR:
  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.
  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.
  3. Alt lisanslanamaz, satılamaz veya devredilemez.
  4. Tersine mühendislik yapılamaz.

İZİN VERİLEN KULLANIM:
  - GitHub üzerinde görüntüleme ve okuma.
  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).

YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.
İzin talepleri için: GitHub @seydivakkas
"""

import asyncio
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from backend.unified_server import (
    UnifiedServer,
    unified_server,
    DEFAULT_AUDIOSOCKET_PORT,
    DEFAULT_CHAN_WS_PORT,
    DEFAULT_HTTP_PORT,
)
from backend.main import app


def test_unified_server_initial_state():
    """UnifiedServer varsayılan yapılandırma ve portlarını test eder."""
    server = UnifiedServer()
    assert server.audiosocket_port == 9092
    assert server.chan_ws_port == 8088
    assert server.http_port == 8000
    assert server.is_running is False
    assert server.is_shutting_down is False


@pytest.mark.asyncio
async def test_unified_server_start_and_stop_lifecycle():
    """Birleşik sunucunun çift protokol (TCP 19092 & WS 18088) ile başlama ve durma yaşam döngüsünü test eder."""
    server = UnifiedServer(
        audiosocket_host="127.0.0.1",
        audiosocket_port=19092,
        chan_ws_host="127.0.0.1",
        chan_ws_port=18088,
    )

    # Başlatma
    status = await server.start()
    assert server.is_running is True
    assert status["status"] == "alive"
    assert "services" in status
    assert status["services"]["audiosocket_tcp"]["running"] is True
    assert status["services"]["chan_websocket"]["running"] is True

    # Tekrar start çağrıldığında idempotent davranmalı
    status_again = await server.start()
    assert status_again["status"] == "alive"

    # Graceful Shutdown
    shutdown_status = await server.stop()
    assert server.is_running is False
    assert shutdown_status["status"] == "stopped"


def test_unified_server_health_status_structure():
    """get_health_status() raporunun tüm servisleri ve alanları içerdiğini doğrular."""
    server = UnifiedServer()
    health = server.get_health_status()

    assert "status" in health
    assert "uptime_seconds" in health
    assert "services" in health

    svc = health["services"]
    assert "audiosocket_tcp" in svc
    assert "chan_websocket" in svc
    assert "models_gpu" in svc
    assert "concurrency" in svc

    assert "active_calls" in svc["concurrency"]
    assert "max_capacity" in svc["concurrency"]
    assert "tts_ready" in svc["models_gpu"]


def test_unified_server_signal_handlers():
    """Sinyal yöneticisi kaydının istisnasız çalıştığını doğrular."""
    server = UnifiedServer()
    server.setup_signal_handlers()  # Hata fırlatmamalı


@pytest.mark.asyncio
async def test_graceful_shutdown_cleans_sessions():
    """Sunucu kapatılırken aktif chan_websocket ve audiosocket oturumlarının temizlendiğini doğrular."""
    server = UnifiedServer(audiosocket_port=19093, chan_ws_port=18089)
    await server.start()

    # Sahte aktif oturum ekle
    class DummyWsSession:
        def __init__(self):
            self.hungup = False
            self.closed = False
        async def flush_media(self):
            pass
        async def send_command(self, cmd, **kwargs):
            if cmd == "HANGUP":
                self.hungup = True
        async def close(self):
            self.closed = True

    from backend.websocket_adapter import chan_ws_adapter
    dummy = DummyWsSession()
    chan_ws_adapter.active_sessions["dummy-call"] = dummy

    await server.stop()
    assert dummy.hungup is True
    assert dummy.closed is True


def test_default_ports():
    """Birleşik sunucunun varsayılan AudioSocket ve ChanWebSocket portlarını doğrular."""
    assert DEFAULT_AUDIOSOCKET_PORT == 9092
    assert DEFAULT_CHAN_WS_PORT == 8088


def test_unified_system_status_rest_endpoint():
    """FastAPI GET /api/system/unified-status uç noktasını test eder."""
    client = TestClient(app)
    auth_headers = {"Authorization": "Basic YWRtaW46c2VjcmV0"}

    with patch("backend.main.settings.admin_password", "secret"):
        res = client.get("/api/system/unified-status", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert "status" in data
        assert "services" in data
        assert "audiosocket_tcp" in data["services"]
        assert "chan_websocket" in data["services"]
        assert "models_gpu" in data["services"]
        assert "concurrency" in data["services"]



def test_health_reflects_lifespan_listeners():
    """main.py lifespan'in açtığı gerçek dinleyiciler 'stopped' yerine 'alive' olarak yansır."""
    server = UnifiedServer()
    assert server.get_health_status()["status"] == "stopped"
    assert server.get_health_status()["uptime_seconds"] is None

    server.set_lifespan_listener("audiosocket_tcp", True)
    health = server.get_health_status()
    assert health["status"] == "alive"
    assert health["services"]["audiosocket_tcp"]["running"] is True
    assert health["services"]["chan_websocket"]["running"] is False

    server.set_lifespan_listener("audiosocket_tcp", False)
    assert server.get_health_status()["status"] == "stopped"
