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
import logging
from pathlib import Path
import signal
import sys
import time
from typing import Any

from backend.config import settings
from backend.audiosocket_server import orchestrator as audiosocket_orchestrator
from backend.websocket_adapter import chan_ws_adapter
from backend.models import models
from backend.session import active
from backend.db import Session, Conversation
from backend import milestones
from backend.ab_testing import seed_default_experiment

logger = logging.getLogger("unified_server")

DEFAULT_AUDIOSOCKET_PORT = 9092
DEFAULT_CHAN_WS_PORT = 8088
DEFAULT_HTTP_PORT = 8000


class UnifiedServer:
    """
    Birleşik Ana Orkestrasyon Sunucusu (Unified Server):
    - Tek Python sürecinde çoklu protokol:
        * TCP Port 9092: Asterisk app_audiosocket (20 ms pacing & double barge-in)
        * WS Port 8088: Asterisk 20.18+ chan_websocket (PBX game clock & FLUSH_MEDIA)
        * HTTP/REST & Webhook: FastAPI komuta paneli ve CRM entegrasyonu
    - Ortak VRAM & GPU kuyruğu: Batched ODE (8'li dinamik micro-batching)
    - Ortak Concurrency denetimi: ConcurrentCallController (50+ çağrı)
    - Graceful Shutdown & Sinyal Yönetimi: SIGINT/SIGTERM temiz hat kapanışı
    """

    def __init__(
        self,
        audiosocket_host: str = settings.audiosocket_host,
        audiosocket_port: int = settings.audiosocket_port,
        chan_ws_host: str = settings.chan_websocket_host,
        chan_ws_port: int = settings.chan_websocket_port,
        http_host: str = "0.0.0.0",
        http_port: int = DEFAULT_HTTP_PORT,
    ):
        self.audiosocket_host = audiosocket_host
        self.audiosocket_port = audiosocket_port
        self.chan_ws_host = chan_ws_host
        self.chan_ws_port = chan_ws_port
        self.http_host = http_host
        self.http_port = http_port

        self.is_running = False
        self.is_shutting_down = False
        self.start_time: float | None = None

        self.cleanup_task: asyncio.Task | None = None
        self._shutdown_event: asyncio.Event | None = None

    async def start(self) -> dict[str, Any]:
        """
        Tüm sunucu bileşenlerini başlatır:
        1. Veritabanı ve deney toparlama
        2. TCP 9092 AudioSocket sunucusu
        3. WS 8088 chan_websocket sunucusu
        4. Arka plan ses temizleme görevi
        """
        if self.is_running:
            return self.get_health_status()

        self.is_running = True
        self.is_shutting_down = False
        self.start_time = time.monotonic()
        self._shutdown_event = asyncio.Event()

        logger.info("Birleşik Ana Orkestrasyon Sunucusu başlatılıyor...")

        # 1. Veritabanı Toparlama
        try:
            await milestones.recover_abandoned()
            with Session() as db:
                db.query(Conversation).filter_by(status="active").update(
                    {"status": "follow_up"}
                )
                seed_default_experiment(db)
                db.commit()
        except Exception as e:
            logger.warning(f"Başlangıç veritabanı toparlama uyarısı: {e}")

        # 2. TCP 9092 AudioSocket Sunucusu
        try:
            await audiosocket_orchestrator.start(self.audiosocket_host, self.audiosocket_port)
            logger.info(f"AudioSocket TCP {self.audiosocket_host}:{self.audiosocket_port} aktif.")
        except Exception as e:
            logger.error(f"AudioSocket TCP sunucu başlatılamadı: {e}")

        # 3. WS 8088 chan_websocket Sunucusu
        if settings.chan_websocket_enabled:
            try:
                await chan_ws_adapter.start_standalone_server(self.chan_ws_host, self.chan_ws_port)
                logger.info(f"chan_websocket WS {self.chan_ws_host}:{self.chan_ws_port} aktif.")
            except Exception as e:
                logger.warning(f"chan_websocket WS sunucu başlatılamadı ({self.chan_ws_port}): {e}")

        # 4. Arka Plan Temizleme Görevi
        async def cleanup_loop():
            while self.is_running:
                try:
                    for p in (settings.data_dir / "recordings").glob("*.wav"):
                        if p.stat().st_mtime < time.time() - settings.retention_days * 86400:
                            p.unlink()
                except Exception:
                    pass
                await asyncio.sleep(3600)

        self.cleanup_task = asyncio.create_task(cleanup_loop())
        logger.info("Birleşik sunucu tüm protokollerde hazır.")
        return self.get_health_status()

    async def stop(self) -> dict[str, Any]:
        """
        Graceful Shutdown (Temiz Kapanma):
        1. Yeni gelen çağrıları engelle (fail-closed).
        2. Aktif WebSocket oturumlarına FLUSH_MEDIA ve HANGUP gönder.
        3. AudioSocket bağlantılarını kapat.
        4. Sunucu soketlerini durdur.
        5. Arka plan görevlerini iptal et.
        6. Veritabanındaki aktif oturumları follow_up olarak kaydet.
        """
        if not self.is_running or self.is_shutting_down:
            return self.get_health_status()

        self.is_shutting_down = True
        logger.info("Birleşik sunucu kapatılıyor (Graceful Shutdown)...")

        # 1. Arka plan temizleme görevini durdur
        if self.cleanup_task:
            self.cleanup_task.cancel()
            await asyncio.gather(self.cleanup_task, return_exceptions=True)
            self.cleanup_task = None

        # 2. Aktif chan_websocket oturumlarını boşalt ve kapat
        try:
            await chan_ws_adapter.flush_all_active_sessions()
            for s in list(chan_ws_adapter.active_sessions.values()):
                await s.send_command("HANGUP", reason="server_shutdown")
                await s.close()
            await chan_ws_adapter.stop_standalone_server()
        except Exception as e:
            logger.warning(f"chan_websocket kapatma uyarısı: {e}")

        # 3. AudioSocket sunucusunu durdur
        try:
            await audiosocket_orchestrator.stop()
        except Exception as e:
            logger.warning(f"audiosocket kapatma uyarısı: {e}")

        # 4. Veritabanı durumu güncelle
        try:
            with Session() as db:
                db.query(Conversation).filter_by(status="active").update(
                    {"status": "follow_up"}
                )
                db.commit()
        except Exception:
            pass

        self.is_running = False
        self.is_shutting_down = False
        if self._shutdown_event:
            self._shutdown_event.set()

        logger.info("Birleşik sunucu tamamen kapatıldı.")
        return self.get_health_status()

    def setup_signal_handlers(self) -> None:
        """SIGINT ve SIGTERM sinyallerini graceful shutdown'a bağlar."""
        def handle_signal(*_):
            logger.warning("Kapanma sinyali alındı, graceful shutdown başlatılıyor...")
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.stop())
            except RuntimeError:
                try:
                    asyncio.run(self.stop())
                except Exception:
                    pass

        try:
            signal.signal(signal.SIGINT, handle_signal)
            signal.signal(signal.SIGTERM, handle_signal)
        except (ValueError, AttributeError):
            pass

    def get_health_status(self) -> dict[str, Any]:
        """Tüm servis ve protokollerin durumunu konsolide JSON olarak döndürür."""
        uptime = round(time.monotonic() - self.start_time, 2) if self.start_time else 0.0

        status = "alive"
        if self.is_shutting_down:
            status = "shutting_down"
        elif not self.is_running:
            status = "stopped"

        engine_active = getattr(models, "batched_ode_engine", None) is not None

        return {
            "status": status,
            "uptime_seconds": uptime,
            "services": {
                "audiosocket_tcp": {
                    "running": audiosocket_orchestrator.is_running,
                    "host": self.audiosocket_host,
                    "port": self.audiosocket_port,
                    "active_sessions": len(audiosocket_orchestrator.active_sessions),
                    "total_connections": audiosocket_orchestrator.total_connections,
                },
                "chan_websocket": {
                    "running": chan_ws_adapter.is_running,
                    "host": self.chan_ws_host,
                    "port": self.chan_ws_port,
                    "active_sessions": len(chan_ws_adapter.active_sessions),
                    "total_connections": chan_ws_adapter.total_connections,
                },
                "models_gpu": {
                    "tts_ready": models.tts is not None,
                    "stt_ready": models.stt is not None,
                    "vad_ready": models.vad is not None,
                    "batched_ode_enabled": engine_active,
                    "synth_count": models.synth_count,
                },
                "concurrency": {
                    "active_calls": getattr(active, "active_count", 0),
                    "max_capacity": getattr(active, "capacity", settings.max_concurrent_calls),
                    "locked": active.locked(),
                },
            },
        }

    async def wait_until_stopped(self) -> None:
        """Sunucu kapanana kadar bekler."""
        if self._shutdown_event:
            await self._shutdown_event.wait()


# Tekil küresel sunucu örneği
unified_server = UnifiedServer()


def main():
    """CLI giriş noktası: python -m backend.unified_server"""
    import uvicorn
    from backend.main import app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger.info("FreyaTTS Otomotiv Birleşik Ana Orkestrasyon Sunucusu başlatılıyor...")

    # Uvicorn HTTP/REST sunucusunu çalıştır; FastAPI lifespan AudioSocket ve chan_websocket'i başlatır
    uvicorn.run(
        app,
        host=settings.audiosocket_host,
        port=DEFAULT_HTTP_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
