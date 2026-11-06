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
import socket
import time
from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.five_cuts_bargein_controller import (
    SAMPLE_RATE_8K,
    FRAME_SIZE_8K_BYTES,
    PRE_ONSET_FRAMES_COUNT,
    PRE_ONSET_TOTAL_BYTES,
    CallState,
    InterruptionVerdict,
    FiveCutsReport,
    PreOnsetRingBuffer,
    BackchannelEchoFilter,
    AsteriskMediaBridge,
    DialogueHistoryPruner,
    FiveCutsBargeInController,
    five_cuts_controller,
    COMMAND_FLUSH_MEDIA,
    COMMAND_MARK_MEDIA,
    EVENT_MEDIA_MARK_PROCESSED,
    EVENT_MEDIA_XOFF,
    EVENT_MEDIA_XON,
    EVENT_MEDIA_FLUSHED,
)
from src.five_cuts_bargein_controller import (
    FiveCutsBargeInController as SrcFiveCutsController,
    AsteriskMediaBridge as SrcAsteriskBridge,
    PreOnsetRingBuffer as SrcRingBuffer,
)


# ============================================================================
# 1. PreOnsetRingBuffer Testleri
# ============================================================================
def test_pre_onset_ring_buffer_capacity_and_fifo():
    """300 ms (15 çerçeve x 320 bayt = 4800 bayt) halka tampon mantığını test eder."""
    rb = PreOnsetRingBuffer(capacity_frames=PRE_ONSET_FRAMES_COUNT, frame_bytes=FRAME_SIZE_8K_BYTES)
    assert rb.frame_count == 0
    assert len(rb.get_preroll_bytes()) == 0

    # 10 çerçeve ekle
    for i in range(10):
        rb.push_frame(bytes([i % 256]) * FRAME_SIZE_8K_BYTES)
    assert rb.frame_count == 10
    assert len(rb.get_preroll_bytes()) == 10 * 320

    # 10 çerçeve daha ekle (toplam 20 çerçeve, kapasite 15 olmalı)
    for i in range(10, 20):
        rb.push_frame(bytes([i % 256]) * FRAME_SIZE_8K_BYTES)
    assert rb.frame_count == 15
    preroll = rb.get_preroll_bytes()
    assert len(preroll) == PRE_ONSET_TOTAL_BYTES  # 4800 bayt
    assert rb.duration_sec == pytest.approx(0.30, abs=1e-3)

    # İlk çerçeve 5. indekse ait olmalı (0-4 atılmış olmalı)
    assert preroll[:320] == bytes([5]) * 320


def test_pre_onset_preroll_masking_for_asr():
    """Pre-roll çerçevelerinin sese eklenip sesli süre hesabından maskelendiğini test eder."""
    preroll = b"\x00" * 4800  # 300 ms sessizlik tamponu
    speech = b"\x12\x34" * 8000  # 1 saniyelik (16.000 bayt) 8 kHz slin16 ses

    combined, voiced_dur = PreOnsetRingBuffer.mask_preroll_for_asr(speech, preroll)
    assert len(combined) == 4800 + 16000
    # Sesli süre pre-roll hariç tam 1.0 saniye olmalıdır (Whisper halüsinasyon kalkanı)
    assert voiced_dur == pytest.approx(1.0, abs=1e-3)


# ============================================================================
# 2. BackchannelEchoFilter Testleri
# ============================================================================
def test_backchannel_echo_filter():
    """Arka kanal ('hı hı', 'evet') ve düşük enerjili yankıların doğru filtrelendiğini test eder."""
    flt = BackchannelEchoFilter()

    # 1. Düşük enerji (Eko veya hat dip gürültüsü)
    v_echo = flt.evaluate(duration_ms=150.0, energy_rms=1e-4, transcript="")
    assert v_echo.is_hard_interruption is False
    assert "Eko" in v_echo.reason or "Düşük enerji" in v_echo.reason

    # 2. Arka kanal onay sözcüğü ("hı hı")
    v_bc1 = flt.evaluate(duration_ms=250.0, energy_rms=0.05, transcript="hı hı")
    assert v_bc1.is_hard_interruption is False
    assert v_bc1.is_backchannel is True

    # 3. Arka kanal onay sözcüğü ("evet")
    v_bc2 = flt.evaluate(duration_ms=300.0, energy_rms=0.08, transcript="evet")
    assert v_bc2.is_hard_interruption is False
    assert v_bc2.is_backchannel is True

    # 4. Gerçek söz kesme ("Bir dakika dizel olanı soruyorum")
    v_hard = flt.evaluate(duration_ms=600.0, energy_rms=0.10, transcript="bir dakika dizel olanı soruyorum")
    assert v_hard.is_hard_interruption is True
    assert v_hard.is_backchannel is False


# ============================================================================
# 3. AsteriskMediaBridge Testleri
# ============================================================================
@pytest.mark.asyncio
async def test_asterisk_media_bridge_tcp_nodelay_and_control():
    """Soket TCP_NODELAY ve kontrol komutlarını doğrular."""
    # Mock socket nesnesi
    mock_sock = MagicMock()
    mock_sock.setsockopt = MagicMock()
    assert AsteriskMediaBridge.apply_socket_tcp_nodelay(mock_sock) is True
    mock_sock.setsockopt.assert_called_with(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    sent_texts = []
    sent_bytes = []

    async def mock_send_text(msg: str):
        sent_texts.append(msg)

    async def mock_send_bytes(b: bytes):
        sent_bytes.append(b)

    bridge = AsteriskMediaBridge(
        send_bytes_fn=mock_send_bytes,
        send_text_fn=mock_send_text,
        channel_id="PJSIP/test-chan-1",
    )

    # 1. FLUSH_MEDIA testi
    await bridge.flush_media(turn_id=42)
    assert len(sent_texts) == 1
    flush_cmd = json.loads(sent_texts[0])
    assert flush_cmd["command"] == COMMAND_FLUSH_MEDIA
    assert flush_cmd["turn_id"] == 42

    # 2. MARK_MEDIA ve Oynatma Teyidi testi
    await bridge.mark_media("clause_abc_123")
    assert len(sent_texts) == 2
    mark_cmd = json.loads(sent_texts[1])
    assert mark_cmd["command"] == COMMAND_MARK_MEDIA
    assert mark_cmd["correlation_id"] == "clause_abc_123"
    assert bridge.is_clause_confirmed("clause_abc_123") is False

    # Asterisk'ten oynatma teyidi geldi
    bridge.handle_inbound_event({
        "event": EVENT_MEDIA_MARK_PROCESSED,
        "correlation_id": "clause_abc_123",
    })
    assert bridge.is_clause_confirmed("clause_abc_123") is True
    assert bridge.total_marks_confirmed == 1


@pytest.mark.asyncio
async def test_asterisk_media_bridge_backpressure_xoff_xon():
    """Asterisk MEDIA_XOFF / MEDIA_XON geri basınç yönetimini test eder."""
    sent_bytes = []

    async def mock_send_bytes(b: bytes):
        sent_bytes.append(b)

    bridge = AsteriskMediaBridge(
        send_bytes_fn=mock_send_bytes,
        send_text_fn=AsyncMock(),
        channel_id="PJSIP/test-chan-2",
    )

    frame = b"\x00" * 320

    # Normal durumda gönderim başarılı
    assert await bridge.send_audio_frame_8k(frame) is True
    assert len(sent_bytes) == 1

    # Asterisk kuyruğu 900 kareye ulaştı (MEDIA_XOFF)
    bridge.handle_inbound_event({"event": EVENT_MEDIA_XOFF})
    assert bridge.is_xoff_active is True

    # Gönderim durdurulmalı (False dönmeli)
    assert await bridge.send_audio_frame_8k(frame) is False
    assert len(sent_bytes) == 1  # Yeni çerçeve gönderilmedi

    # Asterisk kuyruğu 800 kareye düştü (MEDIA_XON)
    bridge.handle_inbound_event({"event": EVENT_MEDIA_XON})
    assert bridge.is_xoff_active is False

    # Gönderim tekrar aktif
    assert await bridge.send_audio_frame_8k(frame) is True
    assert len(sent_bytes) == 2


# ============================================================================
# 4. DialogueHistoryPruner Testleri
# ============================================================================
def test_dialogue_history_pruner():
    """Kesim 5: Dinletilmemiş cümlelerin diyalogdan budanmasını doğrular."""
    history = [
        {"role": "user", "content": "Peugeot 3008 fiyatı nedir?"},
        {
            "role": "assistant",
            "content": "Peugeot 3008 fiyatımız 1.850.000 TL'dir. İsterseniz kredi seçeneklerini de inceleyebiliriz.",
            "tool_calls": [{"id": "call_1", "function": "get_credit_quote"}],
        },
    ]

    all_clauses = [
        {"clause_id": "c1", "text": "Peugeot 3008 fiyatımız 1.850.000 TL'dir."},
        {"clause_id": "c2", "text": "İsterseniz kredi seçeneklerini de inceleyebiliriz."},
    ]

    # Müşteri yalnızca c1'i duydu (c2 oynatılmadan söz kesti)
    confirmed_ids = {"c1"}

    pruned_history, pruned_count, dropped_tools = DialogueHistoryPruner.prune_dialogue_history(
        history=history,
        all_clauses=all_clauses,
        confirmed_clause_ids=confirmed_ids,
    )

    assert pruned_count == 1
    assert dropped_tools == 1
    last_assistant_turn = pruned_history[1]
    # Sadece c1 kalmalı ve arkasına [KESİLDİ - MÜŞTERİ DUYMADI] eklenmeli
    assert "Peugeot 3008 fiyatımız 1.850.000 TL'dir." in last_assistant_turn["content"]
    assert "İsterseniz kredi" not in last_assistant_turn["content"]
    assert DialogueHistoryPruner.TAG_CUT in last_assistant_turn["content"]
    assert len(last_assistant_turn.get("tool_calls", [])) == 0


# ============================================================================
# 5. FiveCutsBargeInController Entegrasyon Testleri
# ============================================================================
@pytest.mark.asyncio
async def test_five_cuts_controller_execution_and_sla():
    """Beş Kesim (Five Cuts) protokolünün 5 katmanı senkronize temizlediğini ve SLA < 250 ms olduğunu test eder."""
    mock_bridge = MagicMock()
    mock_bridge.flush_media = AsyncMock()

    controller = FiveCutsBargeInController(media_bridge=mock_bridge)

    local_queue_cleared = False
    llm_cancelled = False
    history_pruned = False

    def clear_local_queue():
        nonlocal local_queue_cleared
        local_queue_cleared = True

    def cancel_llm():
        nonlocal llm_cancelled
        llm_cancelled = True

    def prune_history():
        nonlocal history_pruned
        history_pruned = True
        return 2, 1  # 2 cümle budandı, 1 tool call iptal edildi

    controller.local_queue_clear_fn = clear_local_queue
    controller.llm_cancel_fn = cancel_llm
    controller.dialogue_prune_fn = prune_history

    controller.set_state(CallState.ASSISTANT_SPEAKING)

    report = await controller.execute_five_cuts(turn_id=10, generation_id="gen_xyz_99")

    # 1. Beş katmanın da tetiklendiğini doğrula
    mock_bridge.flush_media.assert_called_once_with(turn_id=10)  # Kesim 1
    assert local_queue_cleared is True                          # Kesim 2
    assert llm_cancelled is True                                # Kesim 4
    assert history_pruned is True                               # Kesim 5

    # 2. SLA Raporunu doğrula
    assert report.success is True
    assert report.clauses_pruned_count == 2
    assert report.tool_calls_dropped_count == 1
    # Hedef SLA: P95 <= 250 ms (Kod seviyesinde genellikle < 5 ms sürer)
    assert report.total_latency_ms < 50.0
    assert controller.state == CallState.USER_SPEAKING


@pytest.mark.asyncio
async def test_five_cuts_voice_activity_evaluation():
    """Gelen sesin durum makinesini doğru yönlendirdiğini test eder."""
    controller = FiveCutsBargeInController()
    controller.set_state(CallState.ASSISTANT_SPEAKING)

    # 1. Arka kanal geldiğinde konuşma kesilmemeli
    is_cut1 = await controller.evaluate_voice_activity(duration_ms=200.0, energy_rms=0.05, transcript="hı hı")
    assert is_cut1 is False
    assert controller.total_backchannels_ignored == 1
    assert controller.state == CallState.ASSISTANT_SPEAKING

    # 2. Gerçek kesinti geldiğinde INTERRUPTION_CANDIDATE durumuna geçmeli
    is_cut2 = await controller.evaluate_voice_activity(duration_ms=500.0, energy_rms=0.12, transcript="dur bir saniye")
    assert is_cut2 is True
    assert controller.state == CallState.INTERRUPTION_CANDIDATE


def test_src_module_reexport():
    """src.five_cuts_bargein_controller re-export uyumluluğunu test eder."""
    assert SrcFiveCutsController is FiveCutsBargeInController
    assert SrcAsteriskBridge is AsteriskMediaBridge
    assert SrcRingBuffer is PreOnsetRingBuffer

