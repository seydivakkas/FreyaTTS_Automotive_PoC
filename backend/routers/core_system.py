"""Çekirdek sistem uç noktaları: sağlık, hazırlık, model yükleme, birleşik durum."""

import httpx
from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
)
from backend.config import settings
from backend.models import models
from backend.session import active
from backend.unified_server import unified_server
from backend.deps import auth

router = APIRouter()


@router.get("/api/health")
@router.get("/health", include_in_schema=False)
async def health():
    return {"status": "alive"}


@router.get("/api/readiness", dependencies=[Depends(auth)])
async def readiness():
    ollama = {"model": settings.ollama_model}
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get(settings.ollama_url + "/api/tags")
            r.raise_for_status()
            names = [m["name"] for m in r.json().get("models", [])]
        if settings.ollama_model in names:
            ollama["status"] = "READY"
        else:
            ollama.update(status="BLOCKED", reason="Model Ollama'da kurulu değil")
    except Exception as e:
        ollama.update(status="BLOCKED", reason=str(e))

    # Değerler yalnızca gerçek durumdan gelir; demo modu da model durumunu taklit etmez.
    states = {breaker.state.name for breaker in models.breakers.values()}
    breaker_state = next(
        (s for s in ("OPEN", "HALF_OPEN") if s in states), "CLOSED"
    )
    breaker_labels = {
        "CLOSED": "CLOSED (Normal)",
        "HALF_OPEN": "HALF_OPEN (Deneme)",
        "OPEN": "OPEN (Beklemede)",
    }
    return {
        "demo_mode": settings.demo_mode,
        "tts": {"status": "READY" if models.tts else "BLOCKED", "device": settings.tts_device, "engine": "FreyaTTS"},
        "stt": {"status": "READY" if models.stt else "BLOCKED", "device": settings.stt_device, "engine": "Faster-Whisper " + settings.stt_model},
        "vad": {"status": "READY" if models.vad else "BLOCKED", "engine": "Silero VAD"},
        "ollama": ollama,
        "circuit_breaker": {"state": breaker_state, "status": breaker_labels[breaker_state]},
        "loading": models.loading,
        "error": models.error,
        "busy": active.active_count > 0,
        "model_load_ms": models.load_ms,
        "synth_count": models.synth_count,
    }


@router.post("/api/models/load", dependencies=[Depends(auth)])
async def load():
    # "Aktif görüşme" = en az bir oturum var (locked() yalnızca kapasite dolunca True olur).
    if active.active_count > 0:
        raise HTTPException(409, "Aktif görüşme var")
    try:
        await models.load()
    except Exception as e:
        raise HTTPException(503, str(e))
    return {"status": "READY"}


# ============================================================================
# BİRLEŞİK ANA ORKESTRASYON SUNUCUSU (UNIFIED SERVER) TELEMETRİ ENDPOINTS
# ============================================================================

@router.get("/api/system/unified-status", dependencies=[Depends(auth)])
def get_unified_system_status_endpoint():
    """Tüm protokollerin (TCP 9092, WS 8088, HTTP, GPU/VRAM) birleşik durumunu döndürür."""
    return unified_server.get_health_status()
