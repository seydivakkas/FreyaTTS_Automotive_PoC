# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
import asyncio
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import (
    FastAPI,
    Depends,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.staticfiles import StaticFiles
from backend.config import settings
from backend.db import Conversation
from backend.ab_testing import seed_default_experiment
from backend.models import models
from backend.session import (
    VoiceSession,
    active,
)
from backend.telephony import connection
from backend.websocket_adapter import chan_ws_adapter
from backend.unified_server import unified_server
from backend import milestones
from backend import db as db_module
from backend.deps import (  # noqa: F401  (geriye uyumlu yeniden dışa aktarım)
    AUDIO_B64_MAX,
    auth,
    call_analytics_row,
    optional_security,
    row,
    security,
)
from backend.schemas import *  # noqa: F401,F403
from backend.routers import (
    core_system,
    text_speech,
    operator_qa,
    telephony,
    crm,
    scheduling,
    audio_dsp,
    compliance,
    observability,
    supervisor,
    generic_resources,
    dataset,
)
from backend.ontology import router as ontology_router


logger = logging.getLogger("automotive_voice.main")
tickets = {}


async def warm_models():
    try:
        await models.load()
    except Exception:
        logger.exception("Modeller başlatma sırasında yüklenemedi")


@asynccontextmanager
async def lifespan(app):
    await milestones.recover_abandoned()
    # Modelleri (FreyaTTS, Faster-Whisper, Silero VAD, Ollama) otomatik arka planda yükle ve ısıt
    if settings.auto_load_models:
        asyncio.create_task(warm_models())
    fqici_task = None
    if settings.fqici_enabled:
        from backend.fqici.journal import poll, run_poll_loop
        from backend.fqici.queue import Queue

        fqici_root = milestones.runtime_root()
        fqici_queue = Queue()
        await poll(fqici_root, fqici_queue, startup=True)
    with db_module.Session() as db:
        db.query(Conversation).filter_by(status="active").update(
            {"status": "follow_up"}
        )
        seed_default_experiment(db)
        try:
            from backend.caller_memory import seed_default_profiles
            seed_default_profiles(db)
        except Exception:
            logger.warning("Caller memory default profile seeding failed", exc_info=True)
        db.commit()
    server = await asyncio.start_server(
        connection, settings.audiosocket_host, settings.audiosocket_port
    )
    unified_server.set_lifespan_listener("audiosocket_tcp", True)
    chan_ws_server = None
    if settings.chan_websocket_enabled:
        try:
            chan_ws_server = await chan_ws_adapter.start_standalone_server(
                settings.chan_websocket_host, settings.chan_websocket_port
            )
            unified_server.set_lifespan_listener("chan_websocket", True)
        except Exception:
            pass

    def purge_old_recordings():
        """Eski kayıtları siler; tek dosyadaki OSError diğerlerini durdurmaz."""
        limit = time.time() - settings.retention_days * 86400
        try:
            files = list((settings.data_dir / "recordings").glob("*.wav"))
        except OSError:
            return
        for p in files:
            try:
                if p.stat().st_mtime < limit:
                    p.unlink()
            except OSError:
                continue

    def purge_old_transcripts():
        """KVKK gereğince saklama süresi dolan transkriptleri imha eder."""
        try:
            from backend.kvkk_compliance import purge_expired_transcripts
            from backend.db import Session
            from backend.fqici.queue import purge_expired_scopes
            from backend.supervisor.quality import purge_expired
            with Session() as db:
                result = purge_expired_transcripts(db, dry_run=False)
            purge_expired(result["cutoff_date"])
            purge_expired_scopes(result["cutoff_date"])
        except Exception:
            pass

    async def cleanup():
        while True:
            try:
                # Engelleyen dosya sistemi ve veritabanı işlemleri olay döngüsünü tutmasın.
                await asyncio.to_thread(purge_old_recordings)
                if settings.kvkk_erasure_enabled and settings.auto_purge_transcripts:
                    await asyncio.to_thread(purge_old_transcripts)
            except Exception:
                pass
            await asyncio.sleep(3600)

    task = asyncio.create_task(cleanup())
    if settings.fqici_enabled:
        fqici_task = asyncio.create_task(run_poll_loop(fqici_root, fqici_queue))
    yield
    if chan_ws_server:
        try:
            await chan_ws_adapter.stop_standalone_server()
        except Exception:
            pass
        unified_server.set_lifespan_listener("chan_websocket", False)
    server.close()
    await server.wait_closed()
    unified_server.set_lifespan_listener("audiosocket_tcp", False)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    if fqici_task:
        fqici_task.cancel()
        await asyncio.gather(fqici_task, return_exceptions=True)


app = FastAPI(title="Freya Otomotiv Asistanı", lifespan=lifespan)

app.include_router(core_system.router)
app.include_router(text_speech.router)
app.include_router(operator_qa.router)
app.include_router(telephony.router)
app.include_router(crm.router)
app.include_router(scheduling.router)
app.include_router(audio_dsp.router)
app.include_router(compliance.router)
app.include_router(observability.router)
app.include_router(supervisor.router)
app.include_router(ontology_router.router)
app.include_router(generic_resources.router)
app.include_router(dataset.router)


@app.post("/api/session-ticket", dependencies=[Depends(auth)])
def ticket():
    for k in list(tickets):
        if tickets[k] < time.monotonic():
            del tickets[k]
    token = secrets.token_urlsafe(32)
    tickets[token] = time.monotonic() + 30
    return {"ticket": token}


@app.websocket("/ws/voice")
async def voice(ws: WebSocket):
    token = ws.query_params.get("ticket", "")
    # Kabul edilmeden kapatılırsa tarayıcı kod/neden göremez (1006); bu yüzden önce kabul edilir.
    if tickets.pop(token, 0) < time.monotonic():
        await ws.accept()
        await ws.close(code=1008, reason="ticket_expired")
        return
    if active.locked():
        await ws.accept()
        await ws.close(code=1013, reason="line_busy")
        return
    await active.acquire()
    session = None
    greeting = None
    try:
        await ws.accept()
        hello = await asyncio.wait_for(ws.receive_json(), 5)
        rate = hello.get("sample_rate")
        if (
            rate not in (8000, 16000, 24000, 44100, 48000)
            or hello.get("encoding") != "pcm_s16le"
            or hello.get("channels") != 1
        ):
            raise ValueError("Ses biçimi desteklenmiyor")
        lock = asyncio.Lock()
        from backend.audiosocket_server import NetworkWriteTimeout, send_with_timeout

        async def _close_after_timeout():
            # H01.12: okumayan istemci → kontrollü kapanış (kapanış da süresiz beklemez).
            try:
                await asyncio.wait_for(ws.close(code=1011, reason="write_timeout"), 1.0)
            except Exception:
                pass

        async def emit(event):
            async with lock:
                try:
                    await send_with_timeout(ws.send_json(event), "web olay")
                except NetworkWriteTimeout:
                    await _close_after_timeout()
                    raise

        async def audio(frame):
            async with lock:
                try:
                    await send_with_timeout(ws.send_bytes(frame), "web ses")
                except NetworkWriteTimeout:
                    await _close_after_timeout()
                    raise

        if settings.auto_load_models and not models.ollama_ready:
            await emit({"type": "status", "value": "Modeller hazırlanıyor..."})
            await models.load()

        session = VoiceSession("web", emit, audio)
        greeting = asyncio.create_task(session.start())
        while not session.closed:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                session.fqici_close_reason = "disconnect"
                break
            text_data = message.get("text")
            if text_data:
                try:
                    payload = json.loads(text_data)
                    if payload.get("type") == "dtmf":
                        digit = str(payload.get("digit", "")).strip()
                        if digit:
                            # Referans tutulur, hata loglanır, oturum içinde sıralanır.
                            session.schedule_dtmf(digit)
                    elif payload.get("type") == "recalibrate":
                        asyncio.create_task(session.recalibrate())
                    elif payload.get("type") in ("text", "text_input", "user_message"):
                        user_text = str(payload.get("text", "")).strip()
                        if user_text:
                            asyncio.create_task(session.handle_text_input(user_text))
                except Exception:
                    pass
            data = message.get("bytes")
            if data:
                if len(data) > 192000:
                    raise ValueError("Ses paketi çok büyük")
                await session.input(data, rate)
    except WebSocketDisconnect:
        if session:
            session.fqici_close_reason = "disconnect"
    except Exception as e:
        if session:
            session.fqici_close_reason = "transport_error"
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        if greeting:
            greeting.cancel()
            await asyncio.gather(greeting, return_exceptions=True)
        try:
            if session:
                await session.close()
        finally:
            active.release()
            try:
                await ws.close()
            except Exception:
                pass


if Path("frontend/dist").exists():
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="ui")
