import asyncio
import json
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
    generic_resources,
)


tickets = {}


@asynccontextmanager
async def lifespan(app):
    await milestones.recover_abandoned()
    with db_module.Session() as db:
        db.query(Conversation).filter_by(status="active").update(
            {"status": "follow_up"}
        )
        seed_default_experiment(db)
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

    async def cleanup():
        while True:
            try:
                # Engelleyen dosya sistemi işlemleri olay döngüsünü tutmasın.
                await asyncio.to_thread(purge_old_recordings)
            except Exception:
                pass
            await asyncio.sleep(3600)

    task = asyncio.create_task(cleanup())
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
app.include_router(generic_resources.router)


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

        async def emit(event):
            async with lock:
                await ws.send_json(event)

        async def audio(frame):
            async with lock:
                await ws.send_bytes(frame)

        session = VoiceSession("web", emit, audio)
        greeting = asyncio.create_task(session.start())
        while not session.closed:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
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
                except Exception:
                    pass
            data = message.get("bytes")
            if data:
                if len(data) > 192000:
                    raise ValueError("Ses paketi çok büyük")
                await session.input(data, rate)
    except WebSocketDisconnect:
        pass
    except Exception as e:
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
