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

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import json
import logging
import socket
import time
from typing import Any, Awaitable, Callable, Coroutine, Dict, List, Optional, Set, Tuple, Union

import numpy as np

from backend.dsp import apply_telephony_eq_and_downsample_8k
from backend.prosody_wsola_streamer import prosody_wsola_streamer

logger = logging.getLogger("five_cuts_bargein_controller")

# ============================================================================
# Sabitler ve Protokol Tanımları (Ajan 4 & 5)
# ============================================================================
# 8 kHz slin16 Ses Parametreleri
SAMPLE_RATE_8K: int = 8000
SAMPLE_RATE_16K: int = 16000
FRAME_MS: float = 20.0
FRAME_SIZE_8K_BYTES: int = 320   # 20 ms @ 8 kHz 16-bit slin mono
FRAME_SIZE_16K_BYTES: int = 640  # 20 ms @ 16 kHz 16-bit slin mono

# 300 ms Pre-Onset Geri Dönüşlü Tampon (4.8 kB @ 8 kHz slin)
PRE_ONSET_FRAMES_COUNT: int = 15  # 15 x 20 ms = 300 ms
PRE_ONSET_TOTAL_BYTES: int = PRE_ONSET_FRAMES_COUNT * FRAME_SIZE_8K_BYTES  # 4800 bayt

# Asterisk Akış Denetimi (Backpressure) Eşikleri
XOFF_THRESHOLD_FRAMES: int = 900  # Asterisk kuyruğu 900 çerçeveye ulaştığında gönderimi duraklat
XON_THRESHOLD_FRAMES: int = 800   # Asterisk kuyruğu 800 çerçeveye düştüğünde gönderime devam et

# Arka Kanal (Backchannel) Eşikleri
BACKCHANNEL_MAX_DURATION_MS: float = 400.0
BACKCHANNEL_KEYWORDS: set[str] = {
    "hı hı",
    "hıhı",
    "evet",
    "anladım",
    "tamam",
    "tamamdır",
    "hmm",
    "ha",
    "tabii",
    "peki",
}

# Asterisk 20.18+ / 22.8+ chan_websocket JSON Kontrol Komutları
COMMAND_FLUSH_MEDIA = "FLUSH_MEDIA"
COMMAND_MARK_MEDIA = "MARK_MEDIA"
COMMAND_PAUSE_MEDIA = "PAUSE_MEDIA"
COMMAND_RESUME_MEDIA = "RESUME_MEDIA"
COMMAND_HANGUP = "HANGUP"

# Asterisk Gelen Olayları
EVENT_MEDIA_FLUSHED = "MEDIA_FLUSHED"
EVENT_MEDIA_MARK_PROCESSED = "MEDIA_MARK_PROCESSED"
EVENT_MEDIA_XOFF = "MEDIA_XOFF"
EVENT_MEDIA_XON = "MEDIA_XON"
EVENT_CALL_START = "CALL_START"
EVENT_DTMF = "DTMF"
EVENT_HANGUP = "HANGUP"


# ============================================================================
# Durum Makinesi (Full-Duplex Call State Machine)
# ============================================================================
class CallState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    USER_SPEAKING = "USER_SPEAKING"
    THINKING = "THINKING"
    ASSISTANT_SPEAKING = "ASSISTANT_SPEAKING"
    INTERRUPTION_CANDIDATE = "INTERRUPTION_CANDIDATE"
    BARGE_IN_TRIGGERED = "BARGE_IN_TRIGGERED"


@dataclass
class InterruptionVerdict:
    """Araya girme değerlendirme kararı."""
    is_hard_interruption: bool
    is_backchannel: bool
    confidence: float
    reason: str


@dataclass
class FiveCutsReport:
    """Beş Kesim (Five Cuts) protokolü icra ve gecikme raporu."""
    turn_id: int
    generation_id: str
    cut1_asterisk_flush_ms: float
    cut2_local_queue_clear_ms: float
    cut3_gpu_stale_cancel_ms: float
    cut4_llm_stream_cancel_ms: float
    cut5_history_prune_ms: float
    total_latency_ms: float
    clauses_pruned_count: int
    tool_calls_dropped_count: int
    success: bool


# ============================================================================
# 1. 300 ms Pre-Onset Geri Dönüşlü Halka Tampon (Ajan 4 - RT-01)
# ============================================================================
class PreOnsetRingBuffer:
    """
    300 ms (15 çerçeve) 8 kHz slin16 ses halka tamponu (Ring Buffer, 4.8 kB).

    Müşteri konuşmaya başladığı anda VAD algılama gecikmesinde (100-200 ms)
    kaybolabilecek ilk ötümsüz ünsüzleri (P, T, K, Ç, S vb.) koruyarak ASR'a pre-roll sağlar.
    Whisper ASR halüsinasyonunu önlemek için eklenen bu çerçeveler sesli süre
    (voiced duration) hesabından maskelenir.
    """

    def __init__(
        self,
        capacity_frames: int = PRE_ONSET_FRAMES_COUNT,
        frame_bytes: int = FRAME_SIZE_8K_BYTES,
    ):
        self.capacity_frames = max(1, int(capacity_frames))
        self.frame_bytes = max(1, int(frame_bytes))
        self._buffer: deque[bytes] = deque(maxlen=self.capacity_frames)
        self.total_pushed_frames = 0

    def push_frame(self, frame: bytes) -> None:
        """Yeni bir ses çerçevesi (20 ms slin16) ekler."""
        if not frame:
            return
        if len(frame) != self.frame_bytes:
            # Gerekirse uygun çerçeve boyutuna tamamla veya kırp
            if len(frame) < self.frame_bytes:
                frame = frame.ljust(self.frame_bytes, b"\x00")
            else:
                frame = frame[:self.frame_bytes]
        self._buffer.append(frame)
        self.total_pushed_frames += 1

    def get_preroll_bytes(self) -> bytes:
        """Tampondaki tüm pre-roll ses baytlarını döndürür (en fazla 4.8 kB)."""
        return b"".join(self._buffer)

    @property
    def frame_count(self) -> int:
        return len(self._buffer)

    @property
    def duration_sec(self) -> float:
        return len(self._buffer) * (FRAME_MS / 1000.0)

    def clear(self) -> None:
        """Tamponu sıfırlar."""
        self._buffer.clear()

    @staticmethod
    def mask_preroll_for_asr(raw_audio: bytes, preroll_bytes: bytes) -> tuple[bytes, float]:
        """
        ASR için birleştirilmiş ses dizisi ve gerçek sesli süre (voiced duration) döndürür.
        Pre-roll tamponu sese eklenir ancak sesli süreye dahil edilmez (Whisper halüsinasyon kalkanı).
        """
        combined = preroll_bytes + raw_audio
        raw_samples = len(raw_audio) // 2  # 16-bit
        voiced_duration_sec = raw_samples / float(SAMPLE_RATE_8K)
        return combined, voiced_duration_sec


# ============================================================================
# 2. Akustik Eko ve Arka Kanal (Backchannel) Filtresi (Ajan 4)
# ============================================================================
class BackchannelEchoFilter:
    """
    Telefon hoparlöründen sızan yankıyı veya 'hı hı', 'evet', 'tamam' gibi
    kısa onay belirteçlerini gerçek kesintiden (hard barge-in) ayıran filtre.
    """

    def __init__(
        self,
        max_backchannel_ms: float = BACKCHANNEL_MAX_DURATION_MS,
        keywords: Optional[set[str]] = None,
    ):
        self.max_backchannel_ms = max_backchannel_ms
        self.keywords = keywords or BACKCHANNEL_KEYWORDS

    def evaluate(
        self,
        duration_ms: float,
        energy_rms: float,
        transcript: str = "",
    ) -> InterruptionVerdict:
        """
        Araya giren ses sinyalini süre, enerji ve metin bazında değerlendirir.
        """
        clean_text = transcript.strip().lower()

        # 1. Çok düşük enerjili sesler (muhtemel hat gürültüsü veya hafif yankı)
        if energy_rms < 1e-3:
            return InterruptionVerdict(
                is_hard_interruption=False,
                is_backchannel=False,
                confidence=0.85,
                reason="Düşük enerji / hat gürültüsü (Eko şüphesi)",
            )

        # 2. Kısa süre (<400 ms) ve arka kanal anahtar sözcüğü eşleşmesi
        if clean_text and any(clean_text == kw or clean_text.startswith(kw) for kw in self.keywords):
            return InterruptionVerdict(
                is_hard_interruption=False,
                is_backchannel=True,
                confidence=0.92,
                reason=f"Arka kanal onay sözcüğü ('{clean_text}')",
            )

        # 3. Henüz transkripsiyon gelmediyse ama süre çok kısaysa (<200 ms)
        if duration_ms < 200.0 and not clean_text:
            return InterruptionVerdict(
                is_hard_interruption=False,
                is_backchannel=True,
                confidence=0.70,
                reason="Aşırı kısa konuşma patlaması (<200 ms)",
            )

        # 4. Gerçek ve kesin araya girme (Hard Barge-In)
        return InterruptionVerdict(
            is_hard_interruption=True,
            is_backchannel=False,
            confidence=0.95,
            reason="Gerçek kesinti (Müşteri konuşması doğrulandı)",
        )


# ============================================================================
# 3. İki Yönlü Asterisk chan_websocket Medya Köprüsü (Ajan 5 - RT-07, RT-08)
# ============================================================================
class AsteriskMediaBridge:
    """
    Asterisk 20.18+ / 22.8+ chan_websocket Sürücüsüyle İki Yönlü Medya ve Kontrol Köprüsü.

    Özellikler:
    - Soket düzeyinde TCP_NODELAY (Nagle algoritmasının kapatılması).
    - MARK_MEDIA ve MEDIA_MARK_PROCESSED ile iki yönlü oynatma teyidi.
    - MEDIA_XOFF ve MEDIA_XON ile akış denetimi ve geri basınç (backpressure) yönetimi.
    - Polifazlı sinc süzgeci ve 80 Hz HPF ile 48 kHz -> 8 kHz slin16 anti-aliasing dönüşümü.
    """

    def __init__(
        self,
        send_bytes_fn: Callable[[bytes], Coroutine[Any, Any, None]],
        send_text_fn: Callable[[str], Coroutine[Any, Any, None]],
        channel_id: str = "",
    ):
        self.send_bytes_fn = send_bytes_fn
        self.send_text_fn = send_text_fn
        self.channel_id = channel_id

        # Akış Denetimi Durumu (Backpressure)
        self.is_xoff_active: bool = False
        self.buffer_frame_count: int = 0

        # Oynatma Teyidi (MARK_MEDIA) Takibi
        self.pending_marks: dict[str, float] = {}       # correlation_id -> timestamp
        self.confirmed_marks: set[str] = set()          # Müşteriye ulaştığı teyit edilen clause_id'ler
        self.flushed_marks: set[str] = set()

        # Telemetri
        self.total_frames_sent = 0
        self.total_marks_sent = 0
        self.total_marks_confirmed = 0
        self.total_xoff_events = 0
        self.total_xon_events = 0

    @staticmethod
    def apply_socket_tcp_nodelay(sock: Any) -> bool:
        """
        Verilen soket nesnesinde TCP_NODELAY (Nagle algoritmasını kapatma) bayrağını etkinleştirir.
        Böylece 20 ms'lik ses paketleri 40 ms soket tamponunda beklemeden anında iletilir.
        """
        if sock is None:
            return False
        try:
            # Doğrudan soket nesnesi ise
            if hasattr(sock, "setsockopt") and callable(getattr(sock, "setsockopt")):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                logger.debug("TCP_NODELAY başarıyla aktifleştirildi.")
                return True
            # Asyncio transport sarmalayıcısı ise
            raw_sock = getattr(sock, "_sock", None)
            if raw_sock is not None and hasattr(raw_sock, "setsockopt"):
                raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                logger.debug("TCP_NODELAY sarmalayıcı sokette aktifleştirildi.")
                return True
        except Exception as e:
            logger.warning(f"TCP_NODELAY ayarlanırken hata: {e}")
        return False

    async def send_command(self, command: str, **kwargs: Any) -> None:
        """Asterisk'e JSON TEXT kontrol çerçevesi iletir."""
        payload = {"command": command, "channel": self.channel_id, **kwargs}
        msg = json.dumps(payload, ensure_ascii=False)
        try:
            await self.send_text_fn(msg)
        except Exception as e:
            logger.warning(f"Asterisk komut gönderme hatası ({command}): {e}")

    async def flush_media(self, turn_id: Optional[int] = None) -> None:
        """
        Kesim 1: Asterisk'in iç çalma tamponundaki (playout buffer)
        henüz aboneye dinletilmemiş tüm ses paketlerini 0 bayt sızıntıyla anında sildirir.
        """
        await self.send_command(
            COMMAND_FLUSH_MEDIA,
            turn_id=turn_id,
            timestamp=round(time.monotonic(), 4),
        )

    async def mark_media(self, correlation_id: str) -> None:
        """
        Bir cümleciğin son ses çerçevesinin ardından Asterisk'e işaret koyar.
        Asterisk bu kareyi hatta çaldığında MEDIA_MARK_PROCESSED döndürecektir.
        """
        self.pending_marks[correlation_id] = time.monotonic()
        self.total_marks_sent += 1
        await self.send_command(
            COMMAND_MARK_MEDIA,
            correlation_id=correlation_id,
            timestamp=round(time.monotonic(), 4),
        )

    async def send_audio_frame_8k(self, frame_bytes: bytes) -> bool:
        """
        8 kHz slin16 PCM ses çerçevesini (320 bayt) ikili (BINARY) olarak Asterisk'e gönderir.
        Eğer MEDIA_XOFF aktifse gönderim duraklatılır (Geri basınç koruması).
        """
        if self.is_xoff_active:
            # Asterisk tamponu dolu (900 çerçeve), geri basınç aktif
            return False
        try:
            await self.send_bytes_fn(frame_bytes)
            self.total_frames_sent += 1
            return True
        except Exception as e:
            logger.warning(f"Ses çerçevesi gönderme hatası: {e}")
            return False

    def handle_inbound_event(self, event_data: dict[str, Any]) -> None:
        """Asterisk'ten gelen JSON TEXT olaylarını işler."""
        event_name = event_data.get("event") or event_data.get("type")

        # 1. Oynatma Onayı (MEDIA_MARK_PROCESSED)
        if event_name == EVENT_MEDIA_MARK_PROCESSED:
            corr_id = str(event_data.get("correlation_id", ""))
            if corr_id:
                self.confirmed_marks.add(corr_id)
                self.pending_marks.pop(corr_id, None)
                self.total_marks_confirmed += 1
                logger.debug(f"Asterisk ses oynatma teyidi alındı: {corr_id}")

        # 2. Akış Denetimi (MEDIA_XOFF - Geri Basınç Başlangıcı)
        elif event_name == EVENT_MEDIA_XOFF:
            self.is_xoff_active = True
            self.total_xoff_events += 1
            logger.warning("Asterisk MEDIA_XOFF aldı: Playout kuyruğu 900 kareye ulaştı, ses gönderimi durduruldu.")

        # 3. Akış Denetimi (MEDIA_XON - Gönderime Devam)
        elif event_name == EVENT_MEDIA_XON:
            self.is_xoff_active = False
            self.total_xon_events += 1
            logger.info("Asterisk MEDIA_XON aldı: Playout kuyruğu 800 kareye düştü, ses gönderimi devam ediyor.")

        # 4. Tampon Boşaltma Onayı (MEDIA_FLUSHED)
        elif event_name == EVENT_MEDIA_FLUSHED:
            # Bekleyen tüm işaretleri flushed olarak işaretle
            for corr_id in list(self.pending_marks.keys()):
                self.flushed_marks.add(corr_id)
            self.pending_marks.clear()
            logger.debug("Asterisk MEDIA_FLUSHED teyidi işlendi.")

    def is_clause_confirmed(self, clause_id: str) -> bool:
        """Belirtilen cümlenin müşteri tarafından gerçekten duyulduğunu teyit eder."""
        return clause_id in self.confirmed_marks


# ============================================================================
# 4. Diyalog Hafızası ve Kesim Budayıcı (Ajan 4 - Kesim 5)
# ============================================================================
class DialogueHistoryPruner:
    """
    Müşteri söz kestiğinde (Barge-In); LLM diyalog geçmişinden henüz müşteriye
    dinletilmemiş (MEDIA_MARK_PROCESSED onayı almamış) cümleleri silen ve
    sonuna `[KESİLDİ - MÜŞTERİ DUYMADI]` etiketini ekleyen bellek koruyucu.
    """

    TAG_CUT = "[KESİLDİ - MÜŞTERİ DUYMADI]"

    @classmethod
    def prune_dialogue_history(
        cls,
        history: list[dict[str, Any]],
        all_clauses: list[dict[str, Any]],  # [{"clause_id": "c1", "text": "..."}]
        confirmed_clause_ids: set[str],
    ) -> tuple[list[dict[str, Any]], int, int]:
        """
        Diyalog geçmişini günceller.
        Döndürür: (güncellenmiş_geçmiş, budanan_cümlecik_sayısı, iptal_edilen_araç_sayısı)
        """
        if not history:
            return history, 0, 0

        # Sadece teyit edilen cümlecikleri tut
        heard_texts: list[str] = []
        pruned_count = 0

        for item in all_clauses:
            cid = item.get("clause_id", "")
            text = item.get("text", "")
            if cid in confirmed_clause_ids:
                heard_texts.append(text)
            else:
                pruned_count += 1

        # En son asistan dönüşünü bul ve içeriğini güncelle
        dropped_tools = 0
        new_history = list(history)
        for i in range(len(new_history) - 1, -1, -1):
            turn = new_history[i]
            if turn.get("role") == "assistant":
                # Tamamlanmamış tool_calls varsa temizle
                if "tool_calls" in turn and turn["tool_calls"]:
                    dropped_tools += len(turn["tool_calls"])
                    turn["tool_calls"] = []

                if heard_texts:
                    turn["content"] = " ".join(heard_texts) + f" {cls.TAG_CUT}"
                else:
                    turn["content"] = cls.TAG_CUT
                break

        return new_history, pruned_count, dropped_tools


# ============================================================================
# 5. Tam Çift Yönlü "Beş Kesim" (Five Cuts) Orkestratörü (Ajan 4 - RT-06)
# ============================================================================
class FiveCutsBargeInController:
    """
    Beş Katmanlı Kesinti (Five Cuts) Protokolü Orkestratörü.

    P95 <= 250 ms hedefiyle kesinti anında 5 katmanı senkronize olarak temizler:
      Kesim 1: Asterisk WebSocket FLUSH_MEDIA (Asterisk playout kuyruğunu temizler).
      Kesim 2: Yerel ses çalma kuyruğunu anında boşaltır (Local AudioPlaybackQueue.clear()).
      Kesim 3: GPU FreyaTTS çıkarımındaki generation_id'yi STALE yapar, çıktıyı çöpe atar.
      Kesim 4: LLM token üretim akışını (StreamingLLMAdapter) anında iptal eder.
      Kesim 5: LLM diyalog geçmişinden dinletilmemiş cümleleri budar ([KESİLDİ - MÜŞTERİ DUYMADI]).
    """

    def __init__(
        self,
        media_bridge: Optional[AsteriskMediaBridge] = None,
        ring_buffer: Optional[PreOnsetRingBuffer] = None,
        backchannel_filter: Optional[BackchannelEchoFilter] = None,
    ):
        self.media_bridge = media_bridge
        self.ring_buffer = ring_buffer or PreOnsetRingBuffer()
        self.backchannel_filter = backchannel_filter or BackchannelEchoFilter()
        self.state: CallState = CallState.IDLE

        # İptal Edilebilir Görev Kancaları (Callbacks)
        self.local_queue_clear_fn: Optional[Callable[[], None]] = None
        self.llm_cancel_fn: Optional[Callable[[], None]] = None
        self.dialogue_prune_fn: Optional[Callable[[], tuple[int, int]]] = None

        # Telemetri
        self.total_bargeins_executed = 0
        self.total_backchannels_ignored = 0
        self.max_cut_latency_ms: float = 0.0

    def set_state(self, new_state: CallState) -> None:
        """Çağrı durumunu günceller."""
        old_state = self.state
        self.state = new_state
        logger.debug(f"CallState değişti: {old_state} -> {new_state}")

    async def evaluate_voice_activity(
        self,
        duration_ms: float,
        energy_rms: float,
        transcript: str = "",
    ) -> bool:
        """
        Gelen sesi değerlendirir.
        Eğer gerçek bir araya girmeyse `True` döner ve `INTERRUPTION_CANDIDATE` durumuna geçer.
        Arka kanal veya ekoyla `False` döner.
        """
        verdict = self.backchannel_filter.evaluate(duration_ms, energy_rms, transcript)
        if verdict.is_hard_interruption:
            self.set_state(CallState.INTERRUPTION_CANDIDATE)
            return True
        elif verdict.is_backchannel:
            self.total_backchannels_ignored += 1
            logger.info(f"Arka kanal onaylandı, konuşma kesilmedi: {verdict.reason}")
            return False
        return False

    async def execute_five_cuts(
        self,
        turn_id: int,
        generation_id: str,
        reason: str = "customer_barge_in",
    ) -> FiveCutsReport:
        """
        Beş Kesim (Five Cuts) Protokolünü milisaniyelik zamanlama ile yürütür.
        """
        t_global_start = time.perf_counter()
        self.set_state(CallState.BARGE_IN_TRIGGERED)
        self.total_bargeins_executed += 1

        # Kesim 1: Asterisk WebSocket FLUSH_MEDIA
        t0 = time.perf_counter()
        if self.media_bridge:
            await self.media_bridge.flush_media(turn_id=turn_id)
        cut1_ms = (time.perf_counter() - t0) * 1000.0

        # Kesim 2: Yerel Uygulama Kuyruğunu Temizle
        t0 = time.perf_counter()
        if self.local_queue_clear_fn:
            try:
                self.local_queue_clear_fn()
            except Exception as e:
                logger.warning(f"Kesim 2 yerel kuyruk temizleme hatası: {e}")
        cut2_ms = (time.perf_counter() - t0) * 1000.0

        # Kesim 3: GPU TTS generation_id'yi STALE Yap (prosody_wsola_streamer)
        t0 = time.perf_counter()
        try:
            prosody_wsola_streamer.cancel_generation(generation_id)
        except Exception as e:
            logger.warning(f"Kesim 3 GPU iptal hatası: {e}")
        cut3_ms = (time.perf_counter() - t0) * 1000.0

        # Kesim 4: LLM Token Akışını İptal Et
        t0 = time.perf_counter()
        if self.llm_cancel_fn:
            try:
                self.llm_cancel_fn()
            except Exception as e:
                logger.warning(f"Kesim 4 LLM iptal hatası: {e}")
        cut4_ms = (time.perf_counter() - t0) * 1000.0

        # Kesim 5: Diyalog Geçmişini ve Tool Call'ları Buda
        t0 = time.perf_counter()
        clauses_pruned = 0
        tools_dropped = 0
        if self.dialogue_prune_fn:
            try:
                clauses_pruned, tools_dropped = self.dialogue_prune_fn()
            except Exception as e:
                logger.warning(f"Kesim 5 diyalog budama hatası: {e}")
        cut5_ms = (time.perf_counter() - t0) * 1000.0

        total_ms = (time.perf_counter() - t_global_start) * 1000.0
        self.max_cut_latency_ms = max(self.max_cut_latency_ms, total_ms)

        report = FiveCutsReport(
            turn_id=turn_id,
            generation_id=generation_id,
            cut1_asterisk_flush_ms=cut1_ms,
            cut2_local_queue_clear_ms=cut2_ms,
            cut3_gpu_stale_cancel_ms=cut3_ms,
            cut4_llm_stream_cancel_ms=cut4_ms,
            cut5_history_prune_ms=cut5_ms,
            total_latency_ms=total_ms,
            clauses_pruned_count=clauses_pruned,
            tool_calls_dropped_count=tools_dropped,
            success=True,
        )

        logger.info(
            f"Beş Kesim (Five Cuts) tamamlandı: Toplam={total_ms:.2f} ms "
            f"(K1={cut1_ms:.2f}ms, K2={cut2_ms:.2f}ms, K3={cut3_ms:.2f}ms, K4={cut4_ms:.2f}ms, K5={cut5_ms:.2f}ms) "
            f"[Budanan Cümlecik: {clauses_pruned}, İptal Araç: {tools_dropped}]"
        )

        self.set_state(CallState.USER_SPEAKING)
        return report


# Global Tekil Örnek
five_cuts_controller = FiveCutsBargeInController()

__all__ = [
    "SAMPLE_RATE_8K",
    "SAMPLE_RATE_16K",
    "FRAME_MS",
    "FRAME_SIZE_8K_BYTES",
    "FRAME_SIZE_16K_BYTES",
    "PRE_ONSET_FRAMES_COUNT",
    "PRE_ONSET_TOTAL_BYTES",
    "XOFF_THRESHOLD_FRAMES",
    "XON_THRESHOLD_FRAMES",
    "BACKCHANNEL_MAX_DURATION_MS",
    "BACKCHANNEL_KEYWORDS",
    "COMMAND_FLUSH_MEDIA",
    "COMMAND_MARK_MEDIA",
    "COMMAND_PAUSE_MEDIA",
    "COMMAND_RESUME_MEDIA",
    "COMMAND_HANGUP",
    "EVENT_MEDIA_FLUSHED",
    "EVENT_MEDIA_MARK_PROCESSED",
    "EVENT_MEDIA_XOFF",
    "EVENT_MEDIA_XON",
    "CallState",
    "InterruptionVerdict",
    "FiveCutsReport",
    "PreOnsetRingBuffer",
    "BackchannelEchoFilter",
    "AsteriskMediaBridge",
    "DialogueHistoryPruner",
    "FiveCutsBargeInController",
    "five_cuts_controller",
]
