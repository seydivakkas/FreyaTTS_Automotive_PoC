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
import json
import logging
import time
from typing import Any, Callable, Coroutine
import uuid
from fastapi import WebSocket, WebSocketDisconnect

from backend.config import settings
from backend.session import VoiceSession, active

logger = logging.getLogger("chan_websocket")

# Asterisk 20.18+ chan_websocket Protokol Komutları
COMMAND_FLUSH_MEDIA = "FLUSH_MEDIA"
COMMAND_PAUSE_MEDIA = "PAUSE_MEDIA"
COMMAND_CONTINUE_MEDIA = "CONTINUE_MEDIA"
COMMAND_SET_VARIABLE = "SET_VARIABLE"
COMMAND_HANGUP = "HANGUP"

# Asterisk Gelen Olayları (Inbound Events)
EVENT_CALL_START = "CALL_START"
EVENT_DTMF = "DTMF"
EVENT_HANGUP = "HANGUP"
EVENT_MEDIA_FLUSHED = "MEDIA_FLUSHED"

# 8 kHz Ses Çerçeve Parametreleri (PBX Game Clock)
SAMPLE_RATE = 8000
BYTES_PER_SAMPLE = 2
FRAME_SIZE_BYTES = 320  # 20 ms @ 8 kHz slin16 mono


def build_command(command: str, **kwargs: Any) -> str:
    """Asterisk chan_websocket kontrol komutu JSON dizesi oluşturur."""
    payload = {"command": command, **kwargs}
    return json.dumps(payload, ensure_ascii=False)


def parse_event(message: str) -> dict[str, Any]:
    """Asterisk chan_websocket JSON metin mesajını ayrıştırır."""
    try:
        data = json.loads(message)
        if isinstance(data, dict):
            return data
        return {"raw": data}
    except Exception as e:
        logger.debug(f"JSON ayrıştırma hatası: {e} (mesaj: {message[:100]})")
        return {"raw": message}


class ChanWebSocketSession:
    """
    Tek bir Asterisk chan_websocket oturumunu yönetir:
    - Asterisk'e 8 kHz ikili (binary) ses gönderir (PBX oyun saati).
    - Müşteri araya girdiğinde (Barge-in) anında {"command": "FLUSH_MEDIA"} iletir.
    - Asterisk'ten gelen ikili ses paketlerini ve DTMF/Hangup JSON olaylarını işler.
    """

    def __init__(
        self,
        session_id: str,
        channel_id: str,
        send_bytes_fn: Callable[[bytes], Coroutine[Any, Any, None]],
        send_text_fn: Callable[[str], Coroutine[Any, Any, None]],
        adapter: ChanWebSocketAdapter,
        caller_id: str = "",
    ):
        self.session_id = session_id
        self.channel_id = channel_id
        self.caller_id = caller_id
        self.send_bytes_fn = send_bytes_fn
        self.send_text_fn = send_text_fn
        self.adapter = adapter

        self.voice_session: VoiceSession | None = None
        self.started_at = time.monotonic()
        self.is_closed = False
        self.send_lock = asyncio.Lock()

        # Oturum bazlı sayaçlar
        self.flush_count = 0
        self.pause_count = 0
        self.resume_count = 0
        self.frames_sent = 0
        self.bytes_sent = 0
        self.frames_received = 0
        self.bytes_received = 0
        self.dtmf_count = 0

    async def send_command(self, command: str, **kwargs: Any) -> None:
        """Asterisk'e anında JSON kontrol komutu iletir."""
        if self.is_closed:
            return
        msg = build_command(command, channel=self.channel_id, **kwargs)
        async with self.send_lock:
            try:
                await self.send_text_fn(msg)
            except TimeoutError:
                raise
            except Exception as e:
                logger.warning(f"Asterisk komut gönderme hatası ({command}): {e}")

    async def flush_media(self, turn_id: int | None = None) -> None:
        """
        KRİTİK BARGE-IN: Asterisk'in iç çalma tamponundaki (playout buffer)
        henüz aboneye dinletilmemiş tüm ses paketlerini 0 ms gecikmeyle sildirir.
        """
        self.flush_count += 1
        self.adapter.total_flush_commands += 1
        logger.info(f"FLUSH_MEDIA gönderiliyor -> Kanal: {self.channel_id}, Turn: {turn_id}")
        await self.send_command(
            COMMAND_FLUSH_MEDIA,
            turn_id=turn_id,
            timestamp=round(time.monotonic(), 4),
        )

    async def pause_media(self) -> None:
        """Stage 1 Soft Pause: Asterisk çalmasını geçici olarak duraklatır."""
        self.pause_count += 1
        self.adapter.total_pause_commands += 1
        await self.send_command(COMMAND_PAUSE_MEDIA)

    async def resume_media(self) -> None:
        """Stage 2 Backchannel Rollback: Asterisk çalmasını devam ettirir."""
        self.resume_count += 1
        self.adapter.total_resume_commands += 1
        await self.send_command(COMMAND_CONTINUE_MEDIA)

    async def send_audio_frame(self, frame: bytes) -> None:
        """
        8 kHz slin16 PCM ses çerçevesini ikili (binary) olarak Asterisk'e gönderir.
        Zamanlama ve RTP akışı Asterisk PBX Oyun Saatine (PBX Game Clock) devredilir.
        """
        if self.is_closed:
            return
        async with self.send_lock:
            try:
                await self.send_bytes_fn(frame)
                self.frames_sent += 1
                self.bytes_sent += len(frame)
                self.adapter.total_binary_frames_out += 1
                self.adapter.total_bytes_out += len(frame)
            except TimeoutError:
                raise
            except Exception as e:
                logger.warning(f"Asterisk ses iletim hatası: {e}")

    async def handle_session_event(self, event: dict[str, Any]) -> None:
        """VoiceSession'dan gelen olayları dinler ve Asterisk kontrol sinyallerine dönüştürür."""
        ev_type = event.get("type")
        action = event.get("action")

        # Barge-in Olayları
        if ev_type == "playback":
            if action == "flush":
                # Asterisk içindeki tüm tamponu anında boşalt!
                await self.flush_media(turn_id=event.get("turn_id"))
            elif action == "pause":
                # Yumuşak duraklatma sinyali gönder
                await self.pause_media()
            elif action == "resume":
                # Çalmaya devam et
                await self.resume_media()

        # Tamamlanma veya Hata
        elif ev_type in ("completed", "error"):
            await self.send_command(COMMAND_HANGUP, reason=event.get("reason", "completed"))

    async def close(self) -> None:
        """Oturumu kapatır ve kaynakları serbest bırakır."""
        if self.is_closed:
            return
        self.is_closed = True
        if self.voice_session:
            try:
                await self.voice_session.close()
            except Exception:
                pass


class ChanWebSocketAdapter:
    """
    Asterisk 20.18+ chan_websocket WS 8088 Adaptörü ve Orkestratörü.
    FastAPI WebSocket uç noktası (`/ws/asterisk`) veya bağımsız `websockets` sunucusu
    üzerinden çalışabilir.
    """

    def __init__(
        self,
        host: str = settings.chan_websocket_host,
        port: int = settings.chan_websocket_port,
        allowed_ips: list[str] | None = None,
    ):
        self.host = host
        self.port = port
        self.allowed_ips = allowed_ips or settings.pbx_allowed_ips
        self.active_sessions: dict[str, ChanWebSocketSession] = {}
        self.server: Any = None
        self.is_running = False

        # Küresel İstatistikler & Telemetri
        self.total_connections = 0
        self.total_rejected_connections = 0
        self.total_flush_commands = 0
        self.total_pause_commands = 0
        self.total_resume_commands = 0
        self.total_binary_frames_in = 0
        self.total_binary_frames_out = 0
        self.total_bytes_in = 0
        self.total_bytes_out = 0
        self.total_dtmf_events = 0

    async def start_standalone_server(self, host: str | None = None, port: int | None = None) -> Any:
        """Bağımsız websockets sunucusunu Port 8088 üzerinde başlatır."""
        import websockets

        h = host or self.host
        p = port or self.port

        async def ws_handler(ws: Any) -> None:
            peername = getattr(ws, "remote_address", ("unknown", 0))
            client_ip = peername[0] if peername else "unknown"

            async def send_bytes(b: bytes) -> None:
                await ws.send(b)

            async def send_text(t: str) -> None:
                await ws.send(t)

            async def receive_msg() -> tuple[str, bytes | str | None]:
                msg = await ws.recv()
                if isinstance(msg, bytes):
                    return "bytes", msg
                elif isinstance(msg, str):
                    return "text", msg
                return "unknown", None

            async def close_conn() -> None:
                await ws.close()

            await self.process_connection(
                send_bytes_fn=send_bytes,
                send_text_fn=send_text,
                receive_msg_fn=receive_msg,
                client_ip=client_ip,
                close_fn=close_conn,
            )

        self.server = await websockets.serve(ws_handler, h, p)
        self.is_running = True
        logger.info(f"chan_websocket adaptörü Port {h}:{p} üzerinde dinliyor.")
        return self.server

    async def stop_standalone_server(self) -> None:
        """Bağımsız sunucuyu temiz bir şekilde durdurur."""
        self.is_running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
        logger.info("chan_websocket adaptörü durduruldu.")

    async def handle_fastapi_websocket(self, ws: WebSocket) -> None:
        """FastAPI WebSocket (`/ws/asterisk` veya `/ws/chan_websocket`) bağlantısını işler."""
        client = ws.client
        client_ip = client.host if client else "unknown"

        # IP Kontrolü
        if self.allowed_ips and client_ip not in self.allowed_ips and client_ip != "testclient":
            logger.warning(f"chan_websocket reddedildi: {client_ip} izin verilenler listesinde değil.")
            self.total_rejected_connections += 1
            await ws.close(code=1008)
            return

        # Kapasite Kontrolü
        if active.locked():
            logger.warning("chan_websocket reddedildi: Maksimum kapasiteye ulaşıldı.")
            self.total_rejected_connections += 1
            await ws.close(code=1008)
            return

        await ws.accept()

        async def send_bytes(b: bytes) -> None:
            await ws.send_bytes(b)

        async def send_text(t: str) -> None:
            await ws.send_text(t)

        async def receive_msg() -> tuple[str, bytes | str | None]:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return "disconnect", None
            if "bytes" in msg and msg["bytes"]:
                return "bytes", msg["bytes"]
            if "text" in msg and msg["text"]:
                return "text", msg["text"]
            return "unknown", None

        async def close_conn() -> None:
            try:
                await ws.close()
            except Exception:
                pass

        await self.process_connection(
            send_bytes_fn=send_bytes,
            send_text_fn=send_text,
            receive_msg_fn=receive_msg,
            client_ip=client_ip,
            close_fn=close_conn,
        )

    async def process_connection(
        self,
        send_bytes_fn: Callable[[bytes], Coroutine[Any, Any, None]],
        send_text_fn: Callable[[str], Coroutine[Any, Any, None]],
        receive_msg_fn: Callable[[], Coroutine[Any, Any, tuple[str, bytes | str | None]]],
        client_ip: str,
        close_fn: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        """Ortak Asterisk chan_websocket oturum mantığı."""
        # IP Kontrolü
        if self.allowed_ips and client_ip not in self.allowed_ips and client_ip != "testclient":
            self.total_rejected_connections += 1
            await close_fn()
            return

        # Concurrency Kotası
        if active.locked():
            self.total_rejected_connections += 1
            await close_fn()
            return

        await active.acquire()
        owned = True

        call_uuid_str = str(uuid.uuid4())
        channel_id = f"PJSIP/asterisk-{call_uuid_str[:8]}"
        connection_task = asyncio.current_task()
        write_timed_out = False

        async def send(message, sender):
            nonlocal write_timed_out
            if write_timed_out:
                raise TimeoutError("chan_websocket media transport already timed out")
            try:
                async with asyncio.timeout(settings.media_write_timeout_sec):
                    await sender(message)
            except TimeoutError:
                write_timed_out = True
                logger.warning("chan_websocket media write timed out")
                if session.voice_session:
                    session.voice_session.fqici_close_reason = "transport_error"
                if connection_task is not asyncio.current_task():
                    connection_task.cancel()
                raise

        session = ChanWebSocketSession(
            session_id=call_uuid_str,
            channel_id=channel_id,
            send_bytes_fn=lambda frame: send(frame, send_bytes_fn),
            send_text_fn=lambda message: send(message, send_text_fn),
            adapter=self,
        )
        self.active_sessions[call_uuid_str] = session
        self.total_connections += 1

        greeting_task: asyncio.Task | None = None

        try:
            # VoiceSession'ı başlat (8 kHz slin16 Asterisk formatı)
            # BİLİNEN EKSİK: Giden aramalarda mode/appointment_id/call_id taşınamıyor. chan_websocket
            # bağlantısında OutboundCall'ı belirleyen bir kimlik (sorgu parametresi veya CALL_START
            # değişkeni) tanımlı değil; Asterisk tarafında böyle bir sözleşme kurulmadan eşleme
            # uydurulmaz. Şimdilik bu kanaldaki oturumlar "inbound" davranır.
            v_session = VoiceSession(
                channel="asterisk_ws",
                emit=session.handle_session_event,
                send_audio=session.send_audio_frame,
                output_rate=SAMPLE_RATE,
                caller_channel=channel_id,
            )
            session.voice_session = v_session
            greeting_task = asyncio.create_task(v_session.start())

            # Ana Mesaj Alma Döngüsü
            while not session.is_closed:
                msg_type, payload = await receive_msg_fn()
                if msg_type == "disconnect":
                    logger.info(f"chan_websocket bağlantısı kapandı: {channel_id}")
                    break

                # İkili (Binary) Ses Verisi (Asterisk -> AI)
                if msg_type == "bytes" and payload:
                    raw_data = bytes(payload)
                    session.frames_received += 1
                    session.bytes_received += len(raw_data)
                    self.total_binary_frames_in += 1
                    self.total_bytes_in += len(raw_data)
                    await v_session.input(raw_data, rate=SAMPLE_RATE)

                # Metin / JSON Kontrol Mesajı (Asterisk -> AI)
                elif msg_type == "text" and payload:
                    text_str = str(payload).strip()
                    event_data = parse_event(text_str)
                    ev_name = event_data.get("event") or event_data.get("type")

                    # Çağrı Başlangıcı (CALL_START)
                    if ev_name == EVENT_CALL_START:
                        new_chan = event_data.get("channel")
                        if new_chan:
                            session.channel_id = str(new_chan)
                        session.caller_id = str(event_data.get("caller_id", ""))
                        logger.info(f"Asterisk CALL_START: {session.channel_id} (Arayan: {session.caller_id})")

                    # DTMF Olayı
                    elif ev_name == EVENT_DTMF or "digit" in event_data:
                        digit = str(event_data.get("digit", "")).strip()
                        if digit:
                            session.dtmf_count += 1
                            self.total_dtmf_events += 1
                            asyncio.create_task(v_session.handle_dtmf(digit))

                    # Asterisk Tarafından Çağrının Sonlandırılması
                    elif ev_name == EVENT_HANGUP:
                        logger.info(f"Asterisk HANGUP aldı: {session.channel_id}")
                        break

                    # FLUSH Teyidi
                    elif ev_name == EVENT_MEDIA_FLUSHED:
                        logger.debug(f"MEDIA_FLUSHED teyidi alındı: {session.channel_id}")

        except asyncio.CancelledError:
            if not write_timed_out:
                raise
        except (WebSocketDisconnect, ConnectionError, asyncio.IncompleteReadError, TimeoutError):
            pass
        except Exception as e:
            logger.exception(f"chan_websocket oturum hatası ({channel_id}): {e}")
        finally:
            if greeting_task:
                greeting_task.cancel()
                await asyncio.gather(greeting_task, return_exceptions=True)

            try:
                await session.close()
            finally:
                if owned:
                    active.release()

                if call_uuid_str in self.active_sessions:
                    del self.active_sessions[call_uuid_str]

                try:
                    async with asyncio.timeout(settings.media_write_timeout_sec):
                        await close_fn()
                except TimeoutError:
                    logger.warning("chan_websocket close timed out")

    def get_metrics(self) -> dict[str, Any]:
        """Tüm chan_websocket adaptör metriklerini döndürür."""
        return {
            "is_running": self.is_running,
            "host": self.host,
            "port": self.port,
            "active_connections": len(self.active_sessions),
            "total_connections": self.total_connections,
            "total_rejected_connections": self.total_rejected_connections,
            "total_flush_commands": self.total_flush_commands,
            "total_pause_commands": self.total_pause_commands,
            "total_resume_commands": self.total_resume_commands,
            "total_binary_frames_in": self.total_binary_frames_in,
            "total_binary_frames_out": self.total_binary_frames_out,
            "total_bytes_in": self.total_bytes_in,
            "total_bytes_out": self.total_bytes_out,
            "total_dtmf_events": self.total_dtmf_events,
            "allowed_ips": self.allowed_ips,
        }

    async def flush_all_active_sessions(self) -> int:
        """Tüm aktif oturumlara anında FLUSH_MEDIA komutu gönderir."""
        flushed = 0
        for s in list(self.active_sessions.values()):
            try:
                await s.flush_media()
                flushed += 1
            except Exception:
                pass
        return flushed


# Modül düzeyinde tekil adaptör örneği
chan_ws_adapter = ChanWebSocketAdapter()
