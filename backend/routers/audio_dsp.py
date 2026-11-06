"""Ses işleme uç noktaları: DTMF, DSP, toplu ODE, tur algılama, duygu/prozodi, duraklama, ses önbelleği."""

import asyncio
import io
import time
import soundfile as sf
import numpy as np
from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
    Response,
    UploadFile,
    File,
    Form,
)
from backend.config import settings
from backend.security_utils import (
    MAX_AUDIO_BYTES,
    read_upload_capped,
)
from backend.semantic_turn_detector import (
    DISCOURSE_MARKERS_UNFINISHED_MULTI,
    DISCOURSE_MARKERS_UNFINISHED_SINGLE,
    POSTPOSITIONS_INCOMPLETE,
    SemanticTurnDetector,
)
from backend.emotion_prosody_adapter import (
    EmotionCategory,
    EmotionProfile,
    emotion_prosody_adapter,
)
from backend.pause_breath_cleaner import (
    TOP_25_AUTOMOTIVE_PHRASES,
    pause_breath_cleaner,
    telephony_audio_cache,
)
from backend.models import models
from backend.session import active
from backend.schemas import (
    AudioCacheLookupIn,
    BatchedBenchmarkIn,
    BatchedODEConfigIn,
    DSPConfigIn,
    DTMFIn,
    EmotionAdaptIn,
    EmotionAnalyzeIn,
    PauseCleanIn,
    TurnAnalyzeTextIn,
    TurnEvaluateIn,
)
from backend.deps import auth

router = APIRouter()


@router.post("/api/dtmf/generate-tone", dependencies=[Depends(auth)])
def get_dtmf_tone_endpoint(body: DTMFIn):
    from backend.dtmf import generate_dtmf_tone
    try:
        w = generate_dtmf_tone(body.digit[0], duration_sec=0.1, sample_rate=8000)
    except ValueError as e:
        raise HTTPException(400, str(e))
    buf = io.BytesIO()
    sf.write(buf, w, 8000, format="WAV", subtype="PCM_16")
    return Response(buf.getvalue(), media_type="audio/wav")


# ============================================================================
# 8 KHZ ARAÇ İÇİ GÜRÜLTÜ BASTIRMA VE SOFT AGC (CAR DENOISER) ENDPOINTS
# ============================================================================

@router.get("/api/dsp/config", dependencies=[Depends(auth)])
def get_dsp_config():
    return {
        "enabled": settings.car_denoiser_enabled,
        "hpf_cutoff": settings.car_denoiser_hpf_cutoff,
        "suppression_db": settings.car_denoiser_suppression_db,
        "target_dbfs": settings.car_denoiser_target_dbfs,
        "noise_gate_dbfs": settings.car_denoiser_noise_gate_dbfs,
        "max_boost_db": settings.car_denoiser_max_boost_db,
    }


@router.post("/api/dsp/config", dependencies=[Depends(auth)])
def update_dsp_config(body: DSPConfigIn):
    settings.car_denoiser_enabled = body.enabled
    settings.car_denoiser_hpf_cutoff = body.hpf_cutoff
    settings.car_denoiser_suppression_db = body.suppression_db
    settings.car_denoiser_target_dbfs = body.target_dbfs
    settings.car_denoiser_noise_gate_dbfs = body.noise_gate_dbfs
    settings.car_denoiser_max_boost_db = body.max_boost_db
    return {
        "status": "updated",
        "config": get_dsp_config(),
    }


@router.post("/api/dsp/denoise-preview", dependencies=[Depends(auth)])
async def denoise_audio_preview(
    file: UploadFile = File(None),
    audio_file: UploadFile = File(None),
    hpf_cutoff: float = Form(None),
    suppression_db: float = Form(None),
    target_dbfs: float = Form(None),
):
    upload = file or audio_file
    if not upload:
        raise HTTPException(400, "Ses dosyası yüklenmelidir")
    content = await read_upload_capped(upload, MAX_AUDIO_BYTES)
    if not content:
        raise HTTPException(400, "Ses dosyası boş")

    from backend.car_denoiser import process_audio_stream
    from backend.audio import resample
    import soundfile as sf
    import base64

    try:
        audio_data, sr = sf.read(io.BytesIO(content), dtype="float32")
        if audio_data.ndim > 1:
            audio_data = audio_data.mean(axis=1)
        if sr != 8000:
            audio_data = resample(audio_data, sr, 8000)
    except Exception as e:
        raise HTTPException(400, f"Ses dosyası okunamadı: {e}")

    cutoff = hpf_cutoff if hpf_cutoff is not None else settings.car_denoiser_hpf_cutoff
    supp = suppression_db if suppression_db is not None else settings.car_denoiser_suppression_db
    target = target_dbfs if target_dbfs is not None else settings.car_denoiser_target_dbfs

    cleaned_data, stats = process_audio_stream(
        audio_data,
        sample_rate=8000,
        chunk_size=160,
        hpf_cutoff_hz=cutoff,
        suppression_db=supp,
        target_dbfs=target,
    )

    out_buf = io.BytesIO()
    sf.write(out_buf, cleaned_data, 8000, format="WAV", subtype="PCM_16")
    wav_bytes = out_buf.getvalue()

    return {
        "status": "success",
        "stats": stats,
        "sample_rate": 8000,
        "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
    }


# ============================================================================
# BATCHED ODE VE ÇOKLU ÇAĞRI MOTORU (BATCHED ODE & CONCURRENCY) ENDPOINTS
# ============================================================================

@router.get("/api/batched-ode/config", dependencies=[Depends(auth)])
def get_batched_ode_config_endpoint():
    engine_inst = getattr(models, "batched_ode_engine", None)
    return {
        "enabled": settings.batched_ode_enabled,
        "batch_size": settings.batched_ode_batch_size,
        "micro_window_ms": settings.batched_ode_micro_window_ms,
        "max_concurrent_calls": settings.max_concurrent_calls,
        "steps": settings.batched_ode_steps,
        "default_seed": settings.batched_ode_default_seed,
        "active_calls_count": getattr(active, "active_count", 0),
        "engine_active": engine_inst is not None and engine_inst.enabled,
    }


@router.post("/api/batched-ode/config", dependencies=[Depends(auth)])
def update_batched_ode_config_endpoint(body: BatchedODEConfigIn):
    settings.batched_ode_enabled = body.enabled
    settings.batched_ode_batch_size = body.batch_size
    settings.batched_ode_micro_window_ms = body.micro_window_ms
    settings.max_concurrent_calls = body.max_concurrent_calls
    settings.batched_ode_steps = body.steps
    if hasattr(active, "set_capacity"):
        active.set_capacity(body.max_concurrent_calls)
    engine_inst = getattr(models, "batched_ode_engine", None)
    if engine_inst:
        engine_inst.update_config(
            batch_size=body.batch_size,
            micro_window_ms=body.micro_window_ms,
            enabled=body.enabled,
        )
    return {
        "status": "updated",
        "config": get_batched_ode_config_endpoint(),
    }


@router.get("/api/batched-ode/metrics", dependencies=[Depends(auth)])
def get_batched_ode_metrics_endpoint():
    engine_inst = getattr(models, "batched_ode_engine", None)
    if not engine_inst:
        return {
            "enabled": settings.batched_ode_enabled,
            "batch_size": settings.batched_ode_batch_size,
            "micro_window_ms": settings.batched_ode_micro_window_ms,
            "total_batches_processed": 0,
            "total_clauses_synthesized": 0,
            "total_audio_seconds": 0.0,
            "rtf": 0.0,
            "audio_seconds_per_wall_second": 0.0,
            "approx_concurrent_call_capacity": 50,
            "whisper_collapses_prevented": 0,
            "active_calls_count": getattr(active, "active_count", 0),
        }
    m = engine_inst.get_metrics()
    m["active_calls_count"] = getattr(active, "active_count", 0)
    return m


@router.post("/api/batched-ode/benchmark", dependencies=[Depends(auth)])
async def run_batched_ode_benchmark(body: BatchedBenchmarkIn):
    sample_texts = body.texts if body.texts else [
        "Volkswagen Passat 1.5 TSI aracınızın ekspertiz randevusu saat 14:30'da onaylanmıştır.",
        "Şu an iki liftimiz dolu, en erken saat 15:00'te randevu verebiliyoruz.",
        "Aracınızda P0301 arıza kodu algılandı, kontrol randevusu öneriyoruz.",
        "Sol ön çamurluk boyalı, sağ arka kapı değişen olarak rapora işlendi.",
        "Maslak Ekspertiz Merkezine hoş geldiniz, nasıl yardımcı olabilirim?",
        "Ekspertiz raporunuz hazırlandı, WhatsApp üzerinden indirme linki iletildi.",
        "Kurumsal galeri cari hesabınıza randevu bedeli başarıyla işlenmiştir.",
        "Operatöre aktarıyorum, lütfen hatta kalınız.",
    ]
    concurrency = min(body.concurrency, len(sample_texts))
    texts_to_run = sample_texts[:concurrency]

    from backend.batched_ode import BatchedODEEngine, check_voicedness
    test_engine = getattr(models, "batched_ode_engine", None)
    if not test_engine:
        test_engine = BatchedODEEngine(
            batch_size=settings.batched_ode_batch_size,
            micro_window_ms=settings.batched_ode_micro_window_ms,
            steps=settings.batched_ode_steps,
            enabled=True,
            allow_sine_fallback=True,  # model yokken yalnızca kıyaslama; ses çalınmaz
        )

    bench_start = time.monotonic()
    tasks = [
        test_engine.synthesize_clause(txt, seed=body.seed + idx)
        for idx, txt in enumerate(texts_to_run)
    ]
    waveforms = await asyncio.gather(*tasks)
    total_elapsed = time.monotonic() - bench_start

    total_audio_sec = sum(len(w) / 48000 for w in waveforms)
    voiced_scores = [round(check_voicedness(w), 3) for w in waveforms]
    avg_voicedness = round(sum(voiced_scores) / max(len(voiced_scores), 1), 3)

    audio_per_sec = total_audio_sec / max(total_elapsed, 1e-4)
    rtf = total_elapsed / max(total_audio_sec, 1e-4)

    return {
        "status": "success",
        "concurrency": len(texts_to_run),
        "total_elapsed_ms": round(total_elapsed * 1000, 2),
        "total_audio_seconds": round(total_audio_sec, 2),
        "audio_seconds_per_wall_second": round(audio_per_sec, 1),
        "rtf": round(rtf, 4),
        "estimated_concurrent_capacity": int(audio_per_sec * 0.85),
        "avg_voicedness_score": avg_voicedness,
        "voiced_scores": voiced_scores,
    }


# ============================================================================
# AKUSTİK VE ANLAMSAL SMART TURN DEDEKTÖRÜ (SEMANTIC TURN DETECTOR) ENDPOINTS
# ============================================================================

_global_turn_detector = SemanticTurnDetector()


@router.post("/api/turn-detector/evaluate", dependencies=[Depends(auth)])
def turn_evaluate_endpoint(body: TurnEvaluateIn):
    samples = None
    if body.audio_base64:
        try:
            import base64
            raw_bytes = base64.b64decode(body.audio_base64)
            samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        except Exception:
            samples = None

    decision = _global_turn_detector.decide_turn(
        text=body.text,
        silence_duration_ms=body.silence_duration_ms,
        audio_samples=samples,
        sample_rate=body.sample_rate,
    )
    return decision.to_dict()


@router.post("/api/turn-detector/analyze-text", dependencies=[Depends(auth)])
def turn_analyze_text_endpoint(body: TurnAnalyzeTextIn):
    res = _global_turn_detector.analyze_text(body.text)
    return res.to_dict()


@router.get("/api/turn-detector/config", dependencies=[Depends(auth)])
def turn_config_endpoint():
    return {
        "min_silence_ms": _global_turn_detector.min_silence_ms,
        "extended_silence_ms": _global_turn_detector.extended_silence_ms,
        "max_hold_ms": _global_turn_detector.max_hold_ms,
        "enable_acoustic_pitch": _global_turn_detector.enable_acoustic_pitch,
        "single_marker_count": len(DISCOURSE_MARKERS_UNFINISHED_SINGLE),
        "multi_marker_count": len(DISCOURSE_MARKERS_UNFINISHED_MULTI),
        "postposition_count": len(POSTPOSITIONS_INCOMPLETE),
    }


# ============================================================================
# DUYGU DURUMU DUYARLI PROZODİ VE HIZ ADAPTÖRÜ (EMOTION PROSODY ADAPTER) ENDPOINTS
# ============================================================================

@router.post("/api/emotion-prosody/analyze", dependencies=[Depends(auth)])
def emotion_analyze_endpoint(body: EmotionAnalyzeIn):
    samples = None
    if body.audio_base64:
        try:
            import base64
            raw_bytes = base64.b64decode(body.audio_base64)
            samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        except Exception:
            samples = None

    profile = emotion_prosody_adapter.analyze_caller_emotion(
        transcript=body.transcript,
        audio_samples=samples,
        audio_duration_sec=body.audio_duration_sec,
        sample_rate=body.sample_rate,
    )
    return profile.to_dict()


@router.post("/api/emotion-prosody/adapt", dependencies=[Depends(auth)])
def emotion_adapt_endpoint(body: EmotionAdaptIn):
    if body.emotion_category:
        try:
            cat = EmotionCategory(body.emotion_category)
        except Exception:
            cat = EmotionCategory.SATISFIED_CALM
        profile = EmotionProfile(primary_category=cat, confidence=1.0)
    elif body.caller_transcript:
        profile = emotion_prosody_adapter.analyze_caller_emotion(transcript=body.caller_transcript)
    else:
        profile = EmotionProfile(primary_category=EmotionCategory.SATISFIED_CALM, confidence=0.8)

    plan = emotion_prosody_adapter.adapt_prosody(
        assistant_response_text=body.assistant_response_text,
        emotion_profile=profile,
    )
    return plan.to_dict()


@router.get("/api/emotion-prosody/config", dependencies=[Depends(auth)])
def emotion_config_endpoint():
    return {
        "categories": [c.value for c in EmotionCategory],
        "base_period_pause_sec": emotion_prosody_adapter.base_period_pause_sec,
        "base_comma_pause_sec": emotion_prosody_adapter.base_comma_pause_sec,
    }


@router.post("/api/pause-cleaner/clean-audio", dependencies=[Depends(auth)])
def clean_audio_endpoint(payload: PauseCleanIn):
    import base64

    try:
        raw_pcm = base64.b64decode(payload.audio_base64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 audio: {e}")
    if len(raw_pcm) == 0:
        raise HTTPException(status_code=400, detail="Empty audio payload")

    wav = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0
    res = pause_breath_cleaner.clean_waveform_edges(
        wav, sample_rate=payload.sample_rate, fade_ms=payload.fade_ms
    )
    cleaned_i16 = np.clip(res.cleaned_audio * 32767.0, -32768, 32767).astype(np.int16)
    cleaned_b64 = base64.b64encode(cleaned_i16.tobytes()).decode("ascii")
    return {
        "cleaned_audio_base64": cleaned_b64,
        "leading_trimmed_samples": res.leading_trimmed_samples,
        "trailing_trimmed_samples": res.trailing_trimmed_samples,
        "breath_spike_detected": res.breath_spike_detected,
        "sample_rate": res.sample_rate,
        "duration_ms": round(len(res.cleaned_audio) / res.sample_rate * 1000.0, 2),
    }


@router.get("/api/audio-cache/metrics", dependencies=[Depends(auth)])
def audio_cache_metrics_endpoint():
    return telephony_audio_cache.get_metrics()


@router.get("/api/audio-cache/phrases", dependencies=[Depends(auth)])
def audio_cache_phrases_endpoint():
    return [
        {
            "index": i + 1,
            "text": phrase,
            "cached": telephony_audio_cache.has(phrase),
            "num_frames": len(telephony_audio_cache.get_20ms_frames(phrase))
            if telephony_audio_cache.has(phrase)
            else 0,
        }
        for i, phrase in enumerate(TOP_25_AUTOMOTIVE_PHRASES)
    ]


@router.post("/api/audio-cache/lookup", dependencies=[Depends(auth)])
def audio_cache_lookup_endpoint(payload: AudioCacheLookupIn):
    cached = telephony_audio_cache.has(payload.text)
    if cached:
        pcm = telephony_audio_cache.get(payload.text)
        frames = telephony_audio_cache.get_20ms_frames(payload.text)
        return {
            "found": True,
            "text": payload.text,
            "num_frames_20ms": len(frames),
            "byte_size": len(pcm) if pcm else 0,
            "duration_sec": round(len(pcm) / 16000.0, 3) if pcm else 0.0,
        }
    return {
        "found": False,
        "text": payload.text,
        "num_frames_20ms": 0,
        "byte_size": 0,
        "duration_sec": 0.0,
    }


@router.post("/api/audio-cache/warmup", dependencies=[Depends(auth)])
def audio_cache_warmup_endpoint():
    # Gerçek TTS sentezleyici bu uçta bağlı değil: sahte/sinüs ses konmaz, önbellek boş kalır.
    warmed = telephony_audio_cache.warm_cache_with_phrases(TOP_25_AUTOMOTIVE_PHRASES)
    return {
        "status": "ok" if warmed > 0 else "not_warmed",
        "implemented": warmed > 0,
        "simulated": False,
        "note": None if warmed > 0 else "Gerçek sentezleyici bağlı değil; önbellek yalnızca put() ile dolar.",
        "warmed_count": warmed,
        "cached_count": len(telephony_audio_cache.cache),
        "metrics": telephony_audio_cache.get_metrics(),
    }
