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
import json
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.websocket_adapter import (
    ChanWebSocketAdapter,
    ChanWebSocketSession,
    chan_ws_adapter,
    build_command,
    parse_event,
    COMMAND_FLUSH_MEDIA,
    COMMAND_PAUSE_MEDIA,
    COMMAND_RESUME_MEDIA,
    COMMAND_HANGUP,
    EVENT_CALL_START,
    EVENT_DTMF,
    EVENT_HANGUP,
    EVENT_MEDIA_FLUSHED,
    SAMPLE_RATE,
    FRAME_SIZE_BYTES,
)
from src.chan_websocket_adapter import (
    ChanWebSocketAdapter as SrcChanWebSocketAdapter,
    ChanWebSocketSession as SrcChanWebSocketSession,
    chan_ws_adapter as src_chan_ws_adapter,
    COMMAND_FLUSH_MEDIA as SRC_FLUSH,
)
from backend.main import app
from backend.session import active


def test_build_command_and_parse_event():
    """Asterisk JSON kontrol komutları üretimi ve olay ayrıştırmasını test eder."""
    cmd = build_command(COMMAND_FLUSH_MEDIA, channel="PJSIP/trunk-01", turn_id=4)
    data = json.loads(cmd)
    assert data["command"] == "FLUSH_MEDIA"
    assert data["channel"] == "PJSIP/trunk-01"
    assert data["turn_id"] == 4

    parsed = parse_event('{"event": "DTMF", "digit": "5"}')
    assert parsed["event"] == "DTMF"
    assert parsed["digit"] == "5"

    parsed_invalid = parse_event("not-a-json")
    assert "raw" in parsed_invalid


@pytest.mark.asyncio
async def test_chan_websocket_session_flush_and_controls():
    """ChanWebSocketSession'ın FLUSH_MEDIA, PAUSE_MEDIA ve ses çerçevelerini doğru gönderdiğini test eder."""
    sent_text = []
    sent_bytes = []
    adapter = ChanWebSocketAdapter()

    async def mock_send_text(msg: str):
        sent_text.append(msg)

    async def mock_send_bytes(frame: bytes):
        sent_bytes.append(frame)

    session = ChanWebSocketSession(
        session_id="test-session-123",
        channel_id="PJSIP/maslak-001",
        send_bytes_fn=mock_send_bytes,
        send_text_fn=mock_send_text,
        adapter=adapter,
    )

    # 1. FLUSH_MEDIA Gönderimi (Barge-in)
    await session.flush_media(turn_id=2)
    assert session.flush_count == 1
    assert adapter.total_flush_commands == 1
    assert len(sent_text) == 1
    cmd_data = json.loads(sent_text[0])
    assert cmd_data["command"] == "FLUSH_MEDIA"
    assert cmd_data["channel"] == "PJSIP/maslak-001"
    assert cmd_data["turn_id"] == 2

    # 2. PAUSE & RESUME Gönderimi
    await session.pause_media()
    assert session.pause_count == 1
    await session.resume_media()
    assert session.resume_count == 1
    assert json.loads(sent_text[1])["command"] == "PAUSE_MEDIA"
    assert json.loads(sent_text[2])["command"] == "RESUME_MEDIA"

    # 3. İkili Ses Gönderimi (PBX Game Clock)
    dummy_frame = b"\x00\x01" * 160  # 320 byte
    await session.send_audio_frame(dummy_frame)
    assert session.frames_sent == 1
    assert session.bytes_sent == 320
    assert len(sent_bytes) == 1


@pytest.mark.asyncio
async def test_chan_websocket_barge_in_event_flushing():
    """VoiceSession'dan gelen playback:flush olayının anında FLUSH_MEDIA komutuna dönüştüğünü doğrular."""
    sent_text = []
    adapter = ChanWebSocketAdapter()

    async def mock_send_text(msg: str):
        sent_text.append(msg)

    async def mock_send_bytes(frame: bytes):
        pass

    session = ChanWebSocketSession(
        session_id="test-session-flush",
        channel_id="PJSIP/maslak-flush",
        send_bytes_fn=mock_send_bytes,
        send_text_fn=mock_send_text,
        adapter=adapter,
    )

    # VoiceSession flush olayı
    await session.handle_session_event({"type": "playback", "action": "flush", "turn_id": 3})
    assert len(sent_text) == 1
    flush_payload = json.loads(sent_text[0])
    assert flush_payload["command"] == "FLUSH_MEDIA"
    assert flush_payload["turn_id"] == 3

    # VoiceSession pause & resume olayları
    await session.handle_session_event({"type": "playback", "action": "pause", "turn_id": 3})
    await session.handle_session_event({"type": "playback", "action": "resume", "turn_id": 3})
    assert json.loads(sent_text[1])["command"] == "PAUSE_MEDIA"
    assert json.loads(sent_text[2])["command"] == "RESUME_MEDIA"

    # VoiceSession completed olayı
    await session.handle_session_event({"type": "completed", "reason": "appointment"})
    assert json.loads(sent_text[3])["command"] == "HANGUP"


def test_fastapi_websocket_connection_and_audio_flow():
    """FastAPI /ws/asterisk üzerinden el sıkışma, ses akışı ve DTMF iletimini test eder."""
    client = TestClient(app)

    class MockVoiceSession:
        def __init__(self, channel, emit, send_audio, output_rate, caller_channel):
            self.closed = False
            self.emit = emit
            self.send_audio = send_audio
        async def start(self):
            pass
        async def input(self, data, rate):
            pass
        async def handle_dtmf(self, digit):
            pass
        async def close(self):
            self.closed = True

    with patch("backend.websocket_adapter.VoiceSession", MockVoiceSession):
        with client.websocket_connect("/ws/asterisk") as ws:
            # 1. Asterisk CALL_START olayı gönder
            ws.send_text(json.dumps({
                "event": "CALL_START",
                "channel": "PJSIP/caller-test-01",
                "caller_id": "05329998877",
                "format": "slin16",
                "sample_rate": 8000,
            }))

            # 2. Asterisk 8 kHz ikili ses paketi gönder (320 byte = 20 ms)
            dummy_pcm = b"\x00\x00" * 160
            ws.send_bytes(dummy_pcm)

            # 3. Asterisk DTMF tuşlama gönder
            ws.send_text(json.dumps({
                "event": "DTMF",
                "digit": "1",
            }))

            # 4. Asterisk Hangup gönder
            ws.send_text(json.dumps({
                "event": "HANGUP",
                "cause": "16",
            }))

        assert chan_ws_adapter.total_connections >= 1
        assert chan_ws_adapter.total_binary_frames_in >= 1
        assert chan_ws_adapter.total_dtmf_events >= 1


def test_fastapi_websocket_concurrency_rejection():
    """Kapasite doluyken (/ws/asterisk) bağlantının fail-closed (1008) ile kapatıldığını doğrular."""
    client = TestClient(app)

    with patch.object(active, "locked", return_value=True):
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/ws/asterisk"):
                pass
        assert exc_info.value.code == 1008


@pytest.mark.asyncio
async def test_standalone_server_lifecycle():
    """Bağımsız websockets sunucusu başlatma ve durdurma döngüsünü test eder."""
    adapter = ChanWebSocketAdapter(host="127.0.0.1", port=18088)
    server = await adapter.start_standalone_server()
    assert adapter.is_running is True
    assert server is not None

    await adapter.stop_standalone_server()
    assert adapter.is_running is False
    assert adapter.server is None


def test_src_facade_exports():
    """src.chan_websocket_adapter yolunun tüm ana bileşenleri doğru dışa aktardığını doğrular."""
    adapter = SrcChanWebSocketAdapter()
    assert adapter.port == 8088
    assert SRC_FLUSH == "FLUSH_MEDIA"
    assert src_chan_ws_adapter is not None


def test_chan_websocket_rest_endpoints():
    """FastAPI /api/chan-websocket/stats ve /api/chan-websocket/flush uç noktalarını test eder."""
    client = TestClient(app)
    auth_headers = {"Authorization": "Basic YWRtaW46c2VjcmV0"}

    with patch("backend.main.settings.admin_password", "secret"):
        # 1. GET /api/chan-websocket/stats
        res_stats = client.get("/api/chan-websocket/stats", headers=auth_headers)
        assert res_stats.status_code == 200
        stats = res_stats.json()
        assert "port" in stats
        assert "total_connections" in stats
        assert "total_flush_commands" in stats
        assert "total_binary_frames_in" in stats

        # 2. POST /api/chan-websocket/flush
        res_flush = client.post("/api/chan-websocket/flush", headers=auth_headers)
        assert res_flush.status_code == 200
        flush_data = res_flush.json()
        assert flush_data["status"] == "flushed"
        assert "flushed_sessions_count" in flush_data
