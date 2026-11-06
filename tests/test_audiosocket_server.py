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
import struct
import time
from unittest.mock import patch
import uuid
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.audiosocket_server import (
    AudioSocketOrchestrator,
    AudioPacer,
    LookbackBuffer,
    TwoStageBargeInController,
    read_packet,
    build_packet,
    AUDIOSOCKET_HANGUP,
    AUDIOSOCKET_UUID,
    AUDIOSOCKET_DTMF,
    AUDIOSOCKET_AUDIO,
    AUDIOSOCKET_ERROR,
    FRAME_SIZE_BYTES,
    LOOKBACK_FRAMES_COUNT,
    SAMPLE_RATE,
)
from src.audiosocket_orchestrator import (
    AudioSocketOrchestrator as SrcAudioSocketOrchestrator,
    AudioPacer as SrcAudioPacer,
    LookbackBuffer as SrcLookbackBuffer,
    TwoStageBargeInController as SrcTwoStageBargeInController,
    BACKCHANNEL_WORDS,
)
from backend.main import app
from backend.session import active


@pytest.mark.asyncio
async def test_audio_pacer_timing_and_reclamation():
    """AudioPacer'ın 20 ms'lik paketleri gecikmelerde burst yapmadan re-clamp ile gönderdiğini doğrular."""
    pacer = AudioPacer(sample_rate=8000, frame_duration_ms=20.0, frame_bytes=320)
    current_time = [100.0]
    sent_frames = []
    sleep_calls = []

    async def mock_send(frame: bytes):
        sent_frames.append(frame)
        # 2. çerçevede yapay 500 ms'lik TTS sentez gecikmesi simüle et
        if len(sent_frames) == 2:
            current_time[0] += 0.50

    async def mock_sleep(delay: float):
        sleep_calls.append(delay)
        current_time[0] += delay

    # 5 çerçevelik (5 x 320 = 1600 byte) ses gönder
    dummy_audio = b"\x01\x02" * 800
    stats = await pacer.pace_frames(
        dummy_audio,
        mock_send,
        clock=lambda: current_time[0],
        sleep_fn=mock_sleep,
    )

    assert stats["frames_sent"] == 5
    assert stats["bytes_sent"] == 1600
    # 2. çerçevede 0.50s gecikme olduğundan deadline re-clamping tetiklenmeli
    assert stats["reclampe_count"] >= 1
    assert stats["burst_prevented_seconds"] > 0.0


@pytest.mark.asyncio
async def test_audio_pacer_cancellation_honored():
    """Kullanıcı araya girdiğinde (Barge-in) AudioPacer'ın çalmayı anında durdurduğunu doğrular."""
    pacer = AudioPacer(sample_rate=8000, frame_duration_ms=20.0, frame_bytes=320)
    current_time = [0.0]
    sent_count = 0

    async def mock_send(frame: bytes):
        nonlocal sent_count
        sent_count += 1

    async def mock_sleep(delay: float):
        current_time[0] += delay

    # 10 çerçevelik ses, 3. çerçeveden sonra iptal
    dummy_audio = b"\x00" * 3200
    stats = await pacer.pace_frames(
        dummy_audio,
        mock_send,
        is_cancelled=lambda: sent_count >= 3,
        clock=lambda: current_time[0],
        sleep_fn=mock_sleep,
    )

    assert stats["frames_sent"] == 3
    assert stats["cancellations_honored"] == 1


def test_lookback_buffer_fifo_and_samples():
    """LookbackBuffer'ın son 15 çerçeveyi (300 ms) sakladığını ve örnek dönüşümünü doğrular."""
    buf = LookbackBuffer(capacity_frames=15, frame_bytes=320)
    assert buf.current_frames_count == 0

    # 20 adet 320 byte çerçeve ekle (ilk 5 tanesi düşmeli)
    for i in range(20):
        frame = bytes([i % 256]) * 320
        buf.push(frame)

    assert buf.current_frames_count == 15
    assert buf.current_duration_ms == 300.0
    raw = buf.get_bytes()
    assert len(raw) == 15 * 320  # 4800 byte

    # İlk çerçevenin değeri 5 (0..4 düştü)
    assert raw[0] == 5

    # 16 kHz örneklere çevir
    samples_16k = buf.get_samples(target_sample_rate=16000)
    assert isinstance(samples_16k, np.ndarray)
    assert len(samples_16k) > 0

    # Konuşmanın başına lookback ekleme
    dummy_speech = np.ones(1000, dtype=np.float32)
    prepended = buf.prepend_to_speech(dummy_speech, sample_rate=16000)
    assert len(prepended) == len(samples_16k) + len(dummy_speech)

    buf.clear()
    assert buf.current_frames_count == 0


def test_two_stage_barge_in_backchannel_rollback():
    """Çift kademeli barge-in'de dinleme teyidi (backchannel) metinlerinin sesi devam ettirdiğini (Rollback) doğrular."""
    ctrl = TwoStageBargeInController()
    backchannels = ["evet", "hı hı", "hı-hı", "anlıyorum", "tamam", "dinliyorum", ""]

    for text in backchannels:
        # 1. Kademe: VAD konuşma başı -> Soft Pause
        ctrl.stage1_soft_pause()
        assert ctrl.paused is True
        assert ctrl.state == "soft_paused"

        # 2. Kademe: STT transkripsiyonu değerlendirme
        decision = ctrl.stage2_evaluate(text)
        assert decision == "rollback", f"'{text}' için rollback bekleniyordu ama {decision} döndü"
        assert ctrl.paused is False
        assert ctrl.state == "rollbacked"

    stats = ctrl.get_stats()
    assert stats["total_stage1_pauses"] == len(backchannels)
    assert stats["total_stage2_rollbacks"] == len(backchannels)
    assert stats["false_alarms_prevented"] == len(backchannels)


def test_two_stage_barge_in_command_commit():
    """Çift kademeli barge-in'de gerçek kullanıcı müdahalelerinin asistanı susturduğunu (Commit/Flush) doğrular."""
    ctrl = TwoStageBargeInController()
    queries = [
        "Hayır saat 16:00 olsun",
        "Ekspertiz ücreti ne kadar?",
        "Operatöre bağlanmak istiyorum",
        "Randevumu iptal edin",
    ]

    for q in queries:
        ctrl.stage1_soft_pause()
        assert ctrl.paused is True

        decision = ctrl.stage2_evaluate(q)
        assert decision == "commit", f"'{q}' için commit bekleniyordu ama {decision} döndü"
        assert ctrl.paused is False
        assert ctrl.state == "committed"

    stats = ctrl.get_stats()
    assert stats["total_stage2_commits"] == len(queries)


def test_two_stage_barge_in_pause_timeout():
    """Kullanıcı yumuşak duraklatma sonrası sessiz kalırsa zaman aşımında otomatik devam ettiğini doğrular."""
    ctrl = TwoStageBargeInController(max_pause_timeout_sec=0.01)
    ctrl.stage1_soft_pause()
    assert ctrl.paused is True

    # 15 ms bekle ve kontrol et
    time.sleep(0.015)
    timed_out = ctrl.check_pause_timeout()
    assert timed_out is True
    assert ctrl.paused is False
    assert ctrl.state == "rollbacked"


@pytest.mark.asyncio
async def test_audiosocket_protocol_packets():
    """AudioSocket ikili paket formatını ve sınırlarını doğrular."""
    # 0x01 UUID
    test_uuid = uuid.uuid4()
    pkt_uuid = build_packet(AUDIOSOCKET_UUID, test_uuid.bytes)
    assert pkt_uuid[:3] == struct.pack("!BH", 0x01, 16)
    assert pkt_uuid[3:] == test_uuid.bytes

    # 0x10 Audio
    audio_frame = b"\x12\x34" * 160
    pkt_audio = build_packet(AUDIOSOCKET_AUDIO, audio_frame)
    assert pkt_audio[:3] == struct.pack("!BH", 0x10, 320)

    # 0x03 DTMF
    pkt_dtmf = build_packet(AUDIOSOCKET_DTMF, b"1")
    assert pkt_dtmf == b"\x03\x00\x011"

    # 0x00 Hangup
    pkt_hangup = build_packet(AUDIOSOCKET_HANGUP, b"")
    assert pkt_hangup == b"\x00\x00\x00"

    # read_packet ayrıştırma
    reader = asyncio.StreamReader()
    reader.feed_data(pkt_uuid + pkt_audio + pkt_dtmf + pkt_hangup)
    reader.feed_eof()

    k1, p1 = await read_packet(reader)
    assert k1 == AUDIOSOCKET_UUID and p1 == test_uuid.bytes

    k2, p2 = await read_packet(reader)
    assert k2 == AUDIOSOCKET_AUDIO and p2 == audio_frame

    k3, p3 = await read_packet(reader)
    assert k3 == AUDIOSOCKET_DTMF and p3 == b"1"

    k4, p4 = await read_packet(reader)
    assert k4 == AUDIOSOCKET_HANGUP and p4 == b""


@pytest.mark.asyncio
async def test_audiosocket_orchestrator_ip_and_concurrency_rejection():
    """İzin verilmeyen IP ve dolu oturum durumunda çağrının fail-closed reddedildiğini doğrular."""
    orch = AudioSocketOrchestrator(allowed_ips=["127.0.0.1"])

    # 1. İzin verilmeyen IP
    reader = asyncio.StreamReader()
    writer_closed = False

    class FakeWriter:
        def get_extra_info(self, name):
            if name == "peername":
                return ("192.168.1.100", 50000)
            return None
        def close(self):
            nonlocal writer_closed
            writer_closed = True
        async def wait_closed(self):
            pass

    await orch.handle_connection(reader, FakeWriter())
    assert writer_closed is True
    assert orch.total_rejected_connections >= 1

    # 2. Concurrency Kapasite Aşımı (active.locked() == True)
    writer_closed_2 = False

    class FakeWriter2:
        def get_extra_info(self, name):
            if name == "peername":
                return ("127.0.0.1", 50000)
            return None
        def close(self):
            nonlocal writer_closed_2
            writer_closed_2 = True
        async def wait_closed(self):
            pass

    with patch.object(active, "locked", return_value=True):
        await orch.handle_connection(reader, FakeWriter2())
        assert writer_closed_2 is True


def test_src_facade_exports():
    """src.audiosocket_orchestrator yolunun tüm ana bileşenleri doğru dışa aktardığını doğrular."""
    orch = SrcAudioSocketOrchestrator()
    pacer = SrcAudioPacer()
    buf = SrcLookbackBuffer()
    bargein = SrcTwoStageBargeInController()

    assert orch.port == 9092
    assert pacer.frame_bytes == 320
    assert buf.capacity_frames == 15
    assert "evet" in BACKCHANNEL_WORDS
    assert "hı hı" in BACKCHANNEL_WORDS


def test_audiosocket_rest_endpoints():
    """FastAPI AudioSocket istatistik ve barge-in simülasyon uç noktalarını test eder."""
    client = TestClient(app)
    auth_headers = {"Authorization": "Basic YWRtaW46c2VjcmV0"}

    with patch("backend.main.settings.admin_password", "secret"):
        # 1. GET /api/audiosocket/stats
        res_stats = client.get("/api/audiosocket/stats", headers=auth_headers)
        assert res_stats.status_code == 200
        stats_data = res_stats.json()
        assert "port" in stats_data
        assert "total_connections" in stats_data
        assert "total_reclampe_count" in stats_data
        assert "total_barge_in_stage1" in stats_data

        # 2. POST /api/audiosocket/simulate-bargein (Backchannel -> Rollback)
        res_barge_rb = client.post(
            "/api/audiosocket/simulate-bargein",
            json={"text": "hı hı"},
            headers=auth_headers,
        )
        assert res_barge_rb.status_code == 200
        rb_data = res_barge_rb.json()
        assert rb_data["decision"] == "rollback"
        assert rb_data["is_backchannel"] is True
        assert rb_data["action"] == "resume_playback"

        # 3. POST /api/audiosocket/simulate-bargein (Customer query -> Commit)
        res_barge_cm = client.post(
            "/api/audiosocket/simulate-bargein",
            json={"text": "Randevu saatini 15:00 yapabilir miyiz?"},
            headers=auth_headers,
        )
        assert res_barge_cm.status_code == 200
        cm_data = res_barge_cm.json()
        assert cm_data["decision"] == "commit"
        assert cm_data["is_backchannel"] is False
        assert cm_data["action"] == "flush_and_cancel_queue"


def test_pacer_totals_are_null_not_zero():
    """Pacer toplamları ölçülmüyor (oturum kendi pacing'ini yapıyor): 0 değil None raporlanır."""
    from backend.audiosocket_server import AudioSocketOrchestrator

    m = AudioSocketOrchestrator().get_metrics()
    assert m["total_reclampe_count"] is None
    assert m["total_burst_prevented_seconds"] is None
