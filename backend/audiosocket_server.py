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
import logging
import struct
import time
from typing import Any, Callable, Coroutine
import uuid
import numpy as np

from backend.config import settings
from backend.session import VoiceSession, active

logger = logging.getLogger("audiosocket")

# AudioSocket Protokol Sabitleri
AUDIOSOCKET_HANGUP = 0x00
AUDIOSOCKET_UUID = 0x01
AUDIOSOCKET_DTMF = 0x03
AUDIOSOCKET_AUDIO = 0x10
AUDIOSOCKET_ERROR = 0xFF

# 8 kHz Ses Çerçeve Parametreleri
SAMPLE_RATE = 8000
FRAME_DURATION_MS = 20.0
SAMPLES_PER_FRAME = 160  # 8000 Hz * 0.020 s = 160 örnek
BYTES_PER_SAMPLE = 2     # 16-bit PCM (slin16)
FRAME_SIZE_BYTES = 320   # 160 * 2 = 320 byte

# 300 ms Lookback Parametreleri (15 x 20 ms = 300 ms)
LOOKBACK_FRAMES_COUNT = 15
LOOKBACK_TOTAL_BYTES = LOOKBACK_FRAMES_COUNT * FRAME_SIZE_BYTES  # 4800 byte (2400 örnek @ 8 kHz)

# Dinleme Teyidi (Backchannel) Sözlüğü
BACKCHANNEL_WORDS = frozenset([
    "",
    "evet",
    "hı",
    "hıhı",
    "hı hı",
    "hı-hı",
    "hım",
    "hı hım",
    "anlıyorum",
    "tamam",
    "dinliyorum",
    "he",
    "ha",
    "efendim",
    "peki",
])


async def read_packet(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    """Asterisk app_audiosocket 3-byte başlık (kind: uint8, len: uint16_be) ve yükünü okur."""
    head = await reader.readexactly(3)
    kind, length = struct.unpack("!BH", head)
    if length > 64000:
        raise ValueError("AudioSocket paketi çok büyük (> 64 KB)")
    payload = await reader.readexactly(length) if length > 0 else b""
    return kind, payload


def build_packet(kind: int, payload: bytes) -> bytes:
    """Asterisk app_audiosocket formatında ikili paket üretir."""
    return struct.pack("!BH", kind, len(payload)) + payload


class LookbackBuffer:
    """
    300 ms (15 çerçeve) 8 kHz slin16 ses halka tamponu (Ring Buffer).
    Kullanıcı konuşmaya başladığı anda VAD algılama gecikmesinde kaybolabilecek
    ilk hece ve ünsüzleri (k, p, t, s, vb.) koruyarak STT'ye pre-roll sağlar.
    """

    def __init__(self, capacity_frames: int = LOOKBACK_FRAMES_COUNT, frame_bytes: int = FRAME_SIZE_BYTES):
        self.capacity_frames = capacity_frames
        self.frame_bytes = frame_bytes
        self._buffer: deque[bytes] = deque(maxlen=capacity_frames)
        self.total_frames_pushed = 0

    def push(self, frame: bytes) -> None:
        """Yeni bir 8 kHz ses çerçevesini (varsayılan 320 byte) halka tampona ekler."""
        if len(frame) != self.frame_bytes:
            # Gelen veri parça halindeyse frame_bytes boyutuna tamamla veya böl
            for i in range(0, len(frame), self.frame_bytes):
                chunk = frame[i : i + self.frame_bytes]
                if len(chunk) == self.frame_bytes:
                    self._buffer.append(chunk)
                    self.total_frames_pushed += 1
                elif len(chunk) > 0:
                    self._buffer.append(chunk.ljust(self.frame_bytes, b"\0"))
                    self.total_frames_pushed += 1
        else:
            self._buffer.append(frame)
            self.total_frames_pushed += 1

    def get_bytes(self) -> bytes:
        """Mevcut halka tamponundaki tüm çerçeveleri kronolojik sırada birleştirir."""
        return b"".join(self._buffer)

    def get_samples(self, target_sample_rate: int = 16000) -> np.ndarray:
        """
        Tampondaki ses verisini float32 (-1.0, 1.0) dizisine ve istenen örnekleme oranına
        (varsayılan 16 kHz Whisper/VAD standardı) dönüştürür.
        """
        raw_bytes = self.get_bytes()
        if not raw_bytes:
            return np.zeros(0, dtype=np.float32)

        samples_8k = np.frombuffer(raw_bytes, dtype="<i2").astype(np.float32) / 32768.0
        if target_sample_rate == 8000 or len(samples_8k) == 0:
            return samples_8k

        try:
            import soxr
            return soxr.resample(samples_8k, 8000, target_sample_rate, quality="HQ")
        except Exception:
            from scipy.signal import resample_poly
            from math import gcd
            g = gcd(8000, target_sample_rate)
            return resample_poly(samples_8k, target_sample_rate // g, 8000 // g).astype(np.float32)

    def prepend_to_speech(self, speech_samples: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
        """Konuşma verisinin başına 300 ms lookback sesini ekler."""
        lookback = self.get_samples(target_sample_rate=sample_rate)
        if len(lookback) == 0:
            return speech_samples
        return np.concatenate((lookback, speech_samples))

    def clear(self) -> None:
        """Tamponu sıfırlar."""
        self._buffer.clear()

    @property
    def current_frames_count(self) -> int:
        return len(self._buffer)

    @property
    def current_duration_ms(self) -> float:
        return len(self._buffer) * FRAME_DURATION_MS


class AudioPacer:
    """
    20 ms Çerçeve Saati ve Deadline Re-Clamping İletim Yöneticisi.
    TTS yan cümle aralarından sonra biriken paketlerin burst olarak Asterisk'e
    gitmesini ve RTP jitter buffer taşmasını (cümle başı yutulmasını) önler.
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        frame_duration_ms: float = FRAME_DURATION_MS,
        frame_bytes: int = FRAME_SIZE_BYTES,
    ):
        self.sample_rate = sample_rate
        self.frame_duration_sec = frame_duration_ms / 1000.0
        self.frame_bytes = frame_bytes

        # İstatistikler ve Telemetri
        self.frames_sent = 0
        self.bytes_sent = 0
        self.reclampe_count = 0
        self.burst_prevented_seconds = 0.0
        self.cancellations_honored = 0

    async def pace_frames(
        self,
        data: bytes,
        send_fn: Callable[[bytes], Coroutine[Any, Any, None]],
        is_cancelled: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], Coroutine[Any, Any, None]] = asyncio.sleep,
    ) -> dict[str, Any]:
        """
        Sentezlenmiş PCM ses verisini kesin 20 ms (320-byte) aralıklarla gönderir.
        İşleme gecikmelerinde birikmiş süreyi burst yapmak yerine deadline re-clamping uygular.
        """
        deadline = clock()
        chunk_size = self.frame_bytes
        total_data_len = len(data)

        for i in range(0, total_data_len, chunk_size):
            if is_cancelled and is_cancelled():
                self.cancellations_honored += 1
                return self.get_stats()

            frame = data[i : i + chunk_size]
            if len(frame) < chunk_size:
                frame = frame.ljust(chunk_size, b"\0")

            await send_fn(frame)
            self.frames_sent += 1
            self.bytes_sent += len(frame)

            deadline += self.frame_duration_sec
            now = clock()

            # Deadline Re-Clamping: Eğer deadline şimdiki zamanın gerisinde kaldıysa,
            # gecikmeyi burst olarak telafi etmek YERİNE deadline'ı yeniden kenetle!
            if deadline < now:
                lag = now - deadline
                self.reclampe_count += 1
                self.burst_prevented_seconds += lag
                deadline = now + self.frame_duration_sec

            wait_time = deadline - clock()
            if wait_time > 0:
                await sleep_fn(wait_time)

        return self.get_stats()

    def get_stats(self) -> dict[str, Any]:
        return {
            "frames_sent": self.frames_sent,
            "bytes_sent": self.bytes_sent,
            "reclampe_count": self.reclampe_count,
            "burst_prevented_seconds": round(self.burst_prevented_seconds, 4),
            "cancellations_honored": self.cancellations_honored,
        }


class TwoStageBargeInController:
    """
    Çift Kademeli Araya Girme (Two-Stage Barge-in) Denetleyicisi:
    - 1. Kademe (VAD Başlangıcı - Soft Pause): Ses çalma geçici duraklatılır,
      ancak aktif LLM/TTS kuyruğu iptal edilmez.
    - 2. Kademe (STT Değerlendirmesi - Rollback vs Commit):
        * 'evet / hı-hı / anlıyorum' (backchannel) ise ses çalmaya devam eder (Rollback).
        * Gerçek bir kullanıcı talebi ise aktif kuyruk tamamen iptal edilir (Commit / Flush).
    """

    def __init__(self, backchannel_words: frozenset[str] = BACKCHANNEL_WORDS, max_pause_timeout_sec: float = 3.5):
        self.backchannel_words = backchannel_words
        self.max_pause_timeout_sec = max_pause_timeout_sec

        self.state: str = "idle"  # idle, soft_paused, committed, rollbacked
        self.paused: bool = False
        self.pause_started_at: float | None = None

        # Telemetri
        self.total_stage1_pauses = 0
        self.total_stage2_rollbacks = 0
        self.total_stage2_commits = 0
        self.false_alarms_prevented = 0

    def stage1_soft_pause(self) -> bool:
        """1. Kademe: VAD konuşma algıladığında çalmayı geçici duraklatır."""
        self.state = "soft_paused"
        self.paused = True
        self.pause_started_at = time.monotonic()
        self.total_stage1_pauses += 1
        return True

    def stage2_evaluate(self, transcription: str) -> str:
        """
        2. Kademe: STT transkripsiyonunu değerlendirir.
        Döndürür:
          - 'rollback': Dinleme teyidi (backchannel), asistan sesini kaldığı yerden devam ettir.
          - 'commit': Gerçek soru/istek, asistan çalmasını derhal sil ve yeni tura geç.
        """
        clean_text = transcription.strip().lower().strip(".!?,;:\"'")
        self.pause_started_at = None

        if clean_text in self.backchannel_words:
            # Geri Alma (Rollback): Kuyruk korunur, çalma devam ettirilir
            self.state = "rollbacked"
            self.paused = False
            self.total_stage2_rollbacks += 1
            self.false_alarms_prevented += 1
            return "rollback"
        else:
            # Onay (Commit / Hard Flush): Asistan susturulur, yeni kullanıcı girdisi işlenir
            self.state = "committed"
            self.paused = False
            self.total_stage2_commits += 1
            return "commit"

    def check_pause_timeout(self) -> bool:
        """Bekleme süresi aşıldığında (kullanıcı nefes alıp sustuysa) otomatik devam ettirir."""
        if self.paused and self.pause_started_at:
            if time.monotonic() - self.pause_started_at > self.max_pause_timeout_sec:
                self.paused = False
                self.state = "rollbacked"
                self.total_stage2_rollbacks += 1
                self.false_alarms_prevented += 1
                self.pause_started_at = None
                return True
        return False

    def get_stats(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "paused": self.paused,
            "total_stage1_pauses": self.total_stage1_pauses,
            "total_stage2_rollbacks": self.total_stage2_rollbacks,
            "total_stage2_commits": self.total_stage2_commits,
            "false_alarms_prevented": self.false_alarms_prevented,
        }


class AudioSocketOrchestrator:
    """
    Asterisk app_audiosocket TCP Port 9092 Ana Orkestrasyon Sunucusu.
    Tek oturumlu veya çok oturumlu Asterisk PBX bağlantılarını yönetir,
    20 ms deadline re-clamping, 300 ms lookback ve 2-kademe barge-in uygular.
    """

    def __init__(
        self,
        host: str = settings.audiosocket_host,
        port: int = settings.audiosocket_port,
        allowed_ips: list[str] | None = None,
    ):
        self.host = host
        self.port = port
        self.allowed_ips = allowed_ips or settings.pbx_allowed_ips
        self.server: asyncio.Server | None = None
        self.is_running = False

        # Aktif bağlantılar ve küresel metrikler
        self.active_sessions: dict[str, dict[str, Any]] = {}
        self.total_connections = 0
        self.total_rejected_connections = 0
        self.total_dtmf_received = 0
        self.total_audio_frames_in = 0
        self.total_audio_frames_out = 0
        self.total_reclampe_count = 0
        self.total_burst_prevented_sec = 0.0
        self.total_barge_in_stage1 = 0
        self.total_barge_in_stage2_rollback = 0
        self.total_barge_in_stage2_commit = 0

    async def start(self, host: str | None = None, port: int | None = None) -> asyncio.Server:
        """TCP 9092 AudioSocket sunucusunu başlatır."""
        h = host or self.host
        p = port or self.port
        self.server = await asyncio.start_server(self.handle_connection, h, p)
        self.is_running = True
        logger.info(f"AudioSocket Orchestrator TCP {h}:{p} üzerinde dinliyor.")
        return self.server

    async def stop(self) -> None:
        """Sunucuyu ve tüm aktif bağlantıları temiz bir şekilde kapatır."""
        self.is_running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        logger.info("AudioSocket Orchestrator durduruldu.")

    async def handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Tek bir Asterisk AudioSocket bağlantısını yönetir."""
        peername = writer.get_extra_info("peername")
        client_ip = peername[0] if peername else "unknown"

        # 1. IP Beyaz Liste Güvenlik Kontrolü
        if self.allowed_ips and client_ip not in self.allowed_ips:
            logger.warning(f"AudioSocket erişim reddedildi: {client_ip} izin verilenler listesinde değil.")
            self.total_rejected_connections += 1
            writer.close()
            await writer.wait_closed()
            return

        # 2. Concurrency (Kapasite) Kontrolü
        if active.locked():
            logger.warning(f"AudioSocket çağrı reddedildi: Sistem maksimum kapasitede.")
            self.total_rejected_connections += 1
            writer.close()
            await writer.wait_closed()
            return

        await active.acquire()
        owned = True
        session: VoiceSession | None = None
        greeting_task: asyncio.Task | None = None
        call_uuid_str = ""

        # Oturum bazlı bileşenler
        lookback = LookbackBuffer(capacity_frames=LOOKBACK_FRAMES_COUNT)
        pacer = AudioPacer(sample_rate=SAMPLE_RATE, frame_duration_ms=FRAME_DURATION_MS)
        bargein = TwoStageBargeInController()

        self.total_connections += 1

        try:
            # 3. El Sıkışma (Handshake): 0x01 UUID Paketi Bekleme
            kind, payload = await asyncio.wait_for(read_packet(reader), timeout=5.0)
            if kind != AUDIOSOCKET_UUID or len(payload) != 16:
                raise ValueError("Geçersiz AudioSocket el sıkışması: 16-byte UUID bekleniyordu.")
            call_uuid = uuid.UUID(bytes=payload)
            call_uuid_str = str(call_uuid)

            session_id = f"audiosocket-{call_uuid_str[:8]}"
            self.active_sessions[call_uuid_str] = {
                "session_id": session_id,
                "client_ip": client_ip,
                "started_at": time.monotonic(),
                "pacer": pacer,
                "lookback": lookback,
                "bargein": bargein,
            }

            # 4. Geri Çağrı (Callback) Fonksiyonları
            async def emit_event(event: dict[str, Any]) -> None:
                if event.get("type") in ("completed", "error"):
                    try:
                        writer.close()
                    except Exception:
                        pass

            async def send_audio_frame(frame: bytes) -> None:
                """AudioSocket 0x10 ses paketi gönderir."""
                packet = build_packet(AUDIOSOCKET_AUDIO, frame)
                writer.write(packet)
                await writer.drain()
                self.total_audio_frames_out += 1

            # 5. VoiceSession Başlatma (8 kHz telefon formatı)
            session = VoiceSession(
                channel="asterisk",
                emit=emit_event,
                send_audio=send_audio_frame,
                output_rate=SAMPLE_RATE,
                caller_channel=f"AudioSocket/{call_uuid_str}",
            )
            greeting_task = asyncio.create_task(session.start())

            # 6. Ana Olay Döngüsü (Read Loop)
            while True:
                kind, payload = await asyncio.wait_for(read_packet(reader), timeout=60.0)

                # Sonlandırma Sinyali
                if kind in (AUDIOSOCKET_HANGUP, AUDIOSOCKET_ERROR):
                    logger.info(f"AudioSocket çağrı sonlandı (kind={kind}): {call_uuid_str}")
                    break

                # Gelen Ses (8 kHz slin16 PCM)
                elif kind == AUDIOSOCKET_AUDIO:
                    self.total_audio_frames_in += 1
                    # 300 ms Lookback tamponuna ekle
                    lookback.push(payload)
                    # Oturuma ilet
                    await session.input(payload, rate=SAMPLE_RATE)

                # DTMF Tuşlama
                elif kind == AUDIOSOCKET_DTMF:
                    self.total_dtmf_received += 1
                    digit = payload.decode("ascii", errors="ignore")
                    await session.handle_dtmf(digit)

                else:
                    raise ValueError(f"Desteklenmeyen AudioSocket mesaj türü: {kind}")

        except (asyncio.IncompleteReadError, ConnectionError, TimeoutError):
            pass
        except Exception as e:
            logger.exception(f"AudioSocket oturum hatası ({call_uuid_str}): {e}")
        finally:
            if greeting_task:
                greeting_task.cancel()
                await asyncio.gather(greeting_task, return_exceptions=True)

            try:
                if session:
                    await session.close()
            finally:
                if owned:
                    active.release()

                # İstatistikleri birleştir
                self.total_reclampe_count += pacer.reclampe_count
                self.total_burst_prevented_sec += pacer.burst_prevented_seconds
                self.total_barge_in_stage1 += bargein.total_stage1_pauses
                self.total_barge_in_stage2_rollback += bargein.total_stage2_rollbacks
                self.total_barge_in_stage2_commit += bargein.total_stage2_commits

                if call_uuid_str in self.active_sessions:
                    del self.active_sessions[call_uuid_str]

                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

    def get_metrics(self) -> dict[str, Any]:
        """Tüm AudioSocket orkestratör metriklerini döndürür."""
        return {
            "is_running": self.is_running,
            "host": self.host,
            "port": self.port,
            "active_connections": len(self.active_sessions),
            "total_connections": self.total_connections,
            "total_rejected_connections": self.total_rejected_connections,
            "total_dtmf_received": self.total_dtmf_received,
            "total_audio_frames_in": self.total_audio_frames_in,
            "total_audio_frames_out": self.total_audio_frames_out,
            "total_reclampe_count": self.total_reclampe_count,
            "total_burst_prevented_seconds": round(self.total_burst_prevented_sec, 3),
            "total_barge_in_stage1": self.total_barge_in_stage1,
            "total_barge_in_stage2_rollback": self.total_barge_in_stage2_rollback,
            "total_barge_in_stage2_commit": self.total_barge_in_stage2_commit,
            "allowed_ips": self.allowed_ips,
        }


# Modül düzeyinde tekil orkestratör örneği
orchestrator = AudioSocketOrchestrator()

