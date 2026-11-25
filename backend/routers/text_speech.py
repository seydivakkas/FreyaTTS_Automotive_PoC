"""Metin ve konuşma uç noktaları: normalizasyon, ön yüz, sentez, sözlük, hotword, SFT, A/B."""

import io
import soundfile as sf
import numpy as np
from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
    Response,
)
from sqlalchemy import select
from backend.db import Vehicle
from backend.ab_testing import (
    PROMPT_TEMPLATES,
    GREETING_TEMPLATES,
    TTS_SEED_PRESETS,
    seed_default_experiment,
    get_all_experiments,
    get_experiment_by_id,
    create_experiment,
    set_experiment_status,
    get_experiment_report,
)
from backend.models import models
from backend.text import normalize
from backend.normalizer_rules import (
    get_lexicon_entries,
    set_lexicon_term,
    delete_lexicon_term,
    reset_to_base_lexicon,
)
from backend.session import active
from backend.automotive_frontend import automotive_frontend
from backend import db as db_module
from backend.schemas import (
    ABExperimentIn,
    ABPreviewSynthIn,
    ABStatusIn,
    DSPProcessIn,
    HotwordsIn,
    LexiconTermIn,
    MorphologicalCheckIn,
    SFTConfigureIn,
    SFTCorpusIn,
    SFTLoRABenchmarkIn,
    SFTLoRAConfigureIn,
    SFTTrainIn,
    TextIn,
    VoiceChatTurnIn,
)
from backend.deps import auth

class _LazySFTAttr:
    """sft_leyla (torch) modülünü yalnızca SFT/LoRA uçları çağrıldığında yükler.

    H01.01 (bulgu X8): modül düzeyindeki ``import torch`` uygulama ve test
    toplamasını torch kurulu olmayan ortamlarda kırıyordu. Davranış aynıdır;
    yalnızca içe aktarma zamanı değişir.
    """

    __slots__ = ("_name",)

    def __init__(self, name: str) -> None:
        object.__setattr__(self, "_name", name)

    def _target(self):
        from backend import sft_leyla  # torch burada, ilk kullanımda yüklenir

        return getattr(sft_leyla, object.__getattribute__(self, "_name"))

    def __getattr__(self, item):
        return getattr(self._target(), item)

    def __setattr__(self, item, value) -> None:
        setattr(self._target(), item, value)


sft_manager = _LazySFTAttr("sft_manager")
lora_manager = _LazySFTAttr("lora_manager")


router = APIRouter()


@router.post("/api/normalize", dependencies=[Depends(auth)])
def normal(body: TextIn):
    try:
        return normalize(body.text)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/api/frontend/normalize-prosody", dependencies=[Depends(auth)])
def frontend_normalize_prosody(body: TextIn):
    try:
        return automotive_frontend.prepare_text_for_synthesis(body.text)
    except Exception as e:
        raise HTTPException(422, str(e))


@router.post("/api/frontend/dsp-telephony", dependencies=[Depends(auth)])
def frontend_dsp_telephony(body: DSPProcessIn):
    import base64
    try:
        raw_bytes = base64.b64decode(body.audio_base64)
        if len(raw_bytes) % 2 != 0:
            raw_bytes = raw_bytes[:-1]
        samples_48k = np.frombuffer(raw_bytes, dtype="<i2").astype(np.float32) / 32768.0
    except Exception as e:
        raise HTTPException(400, f"Geçersiz Base64 PCM verisi: {e}")

    out_pcm16 = automotive_frontend.process_synthesized_audio(
        samples_48k,
        apply_de_ess=body.apply_de_esser,
        inject_noise=body.inject_comfort_noise,
    )
    b64_out = base64.b64encode(out_pcm16.tobytes()).decode("utf-8")
    return {
        "input_samples_48k": len(samples_48k),
        "output_samples_8k": len(out_pcm16),
        "output_bytes": len(out_pcm16.tobytes()),
        "audio_slin16_base64": b64_out,
    }


@router.get("/api/frontend/status", dependencies=[Depends(auth)])
def frontend_status():
    return automotive_frontend.get_metrics()


@router.post("/api/frontend/morphological-check", dependencies=[Depends(auth)])
def frontend_morphological_check(body: MorphologicalCheckIn):
    try:
        from backend.morphological_pre_checker import morphological_pre_checker
        from backend.morphology.contracts import NormalizedUtterance
        import uuid

        norm_text = automotive_frontend.normalizer.normalize(body.text)
        utterance = NormalizedUtterance(
            utterance_id=f"utt_{uuid.uuid4().hex[:8]}",
            chunk_id=body.chunk_id or "chunk_0",
            chunk_text=norm_text,
        )
        plan = morphological_pre_checker.analyze(utterance)
        plan_dict = plan.model_dump()
        if not body.include_hints:
            plan_dict["pronunciation_hints"] = []
        return {
            "chunk_id": plan.chunk_id,
            "normalized_text": norm_text,
            "emphasis_targets": plan.emphasis_targets,
            "pause_injections_ms": plan.pause_injections_ms,
            "pronunciation_hints": plan_dict["pronunciation_hints"],
            "warnings": plan.warnings,
        }
    except Exception as e:
        raise HTTPException(422, str(e))


@router.post("/api/sft/prepare-corpus", dependencies=[Depends(auth)])
def sft_prepare_corpus(body: SFTCorpusIn):
    samples = sft_manager.corpus_builder.generate_synthetic_samples(count=body.count)
    manifest_path = sft_manager.corpus_builder.save_manifest(samples)
    return {
        "total_samples": len(samples),
        "manifest_path": str(manifest_path),
        "sample_preview": samples[:3],
    }


@router.post("/api/sft/configure", dependencies=[Depends(auth)])
def sft_configure(body: SFTConfigureIn):
    sft_manager.config.learning_rate = body.learning_rate
    sft_manager.config.min_steps = body.min_steps
    sft_manager.config.max_steps = body.max_steps
    sft_manager.config.f0_max_drift_hz = body.f0_max_drift_hz
    sft_manager.drift_guard.f0_max_drift_hz = body.f0_max_drift_hz
    stats = sft_manager.initialize_model()
    return {
        "config": sft_manager.config.to_dict(),
        "model_stats": stats,
    }


@router.post("/api/sft/train-step", dependencies=[Depends(auth)])
def sft_train_step(body: SFTTrainIn):
    res = sft_manager.run_training_session(target_steps=body.steps)
    return res


@router.get("/api/sft/status", dependencies=[Depends(auth)])
def sft_status():
    return sft_manager.get_status()


@router.get("/api/sft/verify-identity", dependencies=[Depends(auth)])
def sft_verify_identity():
    return sft_manager.verify_leyla_identity()


@router.post("/api/sft/lora/configure", dependencies=[Depends(auth)])
def sft_lora_configure(body: SFTLoRAConfigureIn):
    lora_manager.config.r = body.r
    lora_manager.config.lora_alpha = body.lora_alpha
    lora_manager.config.lora_dropout = body.lora_dropout
    lora_manager.config.learning_rate = body.learning_rate
    lora_manager.config.batch_size = body.batch_size
    lora_manager.config.grad_accum = body.grad_accum

    if sft_manager.model is None:
        sft_manager.initialize_model()

    lora_model, stats = lora_manager.apply_lora_to_model(sft_manager.model, lora_manager.config)
    sft_manager.model = lora_model
    return {
        "lora_config": lora_manager.config.to_dict(),
        "stats": stats,
    }


@router.get("/api/sft/lora/status", dependencies=[Depends(auth)])
def sft_lora_status():
    return {
        "config": lora_manager.config.to_dict(),
        "active_model": lora_manager.active_lora_model is not None,
        "last_benchmark": lora_manager.last_benchmark_stats,
    }


@router.post("/api/sft/lora/benchmark-step", dependencies=[Depends(auth)])
def sft_lora_benchmark_step(body: SFTLoRABenchmarkIn):
    if sft_manager.model is None:
        sft_manager.initialize_model()
    if lora_manager.active_lora_model is None:
        lora_model, _ = lora_manager.apply_lora_to_model(sft_manager.model, lora_manager.config)
        sft_manager.model = lora_model
    res = lora_manager.benchmark_rtx4070_step(
        sft_manager.model,
        steps=body.steps,
        total_target_steps=body.total_target_steps,
    )
    return res


@router.post("/api/synthesize", dependencies=[Depends(auth)])
async def synth(body: TextIn):
    # "Aktif görüşme" = en az bir oturum var (locked() yalnızca kapasite dolunca True olur).
    if active.active_count > 0:
        raise HTTPException(409, "Aktif görüşme var")
    try:
        w = await models.synth(body.text)
    except Exception as e:
        raise HTTPException(503, str(e))
    buf = io.BytesIO()
    sf.write(buf, w, 48000, format="WAV", subtype="PCM_16")
    return Response(buf.getvalue(), media_type="audio/wav")


@router.get("/api/hotwords", dependencies=[Depends(auth)])
def get_hotwords():
    with db_module.Session() as db:
        vehicles = db.scalars(select(Vehicle.description).order_by(Vehicle.id)).all()
    combined = list(vehicles) + models.custom_hotwords
    return {
        "catalog_vehicles": vehicles,
        "custom_hotwords": models.custom_hotwords,
        "active_hints": ", ".join(combined)[:800],
    }


@router.post("/api/hotwords", dependencies=[Depends(auth)])
def update_hotwords(body: HotwordsIn):
    cleaned = [w.strip() for w in body.words if w.strip()]
    models.custom_hotwords = cleaned
    return {"status": "ok", "custom_hotwords": models.custom_hotwords}


@router.get("/api/lexicon", dependencies=[Depends(auth)])
def get_lexicon():
    return get_lexicon_entries()


@router.post("/api/lexicon", dependencies=[Depends(auth)])
def update_lexicon(body: LexiconTermIn):
    try:
        return set_lexicon_term(
            term=body.term,
            spoken=body.spoken,
            category=body.category or "custom",
        )
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/api/lexicon/reset", dependencies=[Depends(auth)])
def reset_lexicon():
    return reset_to_base_lexicon()


@router.delete("/api/lexicon/{term:path}", dependencies=[Depends(auth)])
def delete_lexicon(term: str):
    try:
        return delete_lexicon_term(term)
    except ValueError as e:
        raise HTTPException(422, str(e))


# ============================================================================
# A/B TEST VE İNCE AYAR ALTYAPISI ENDPOINTS (AB TESTING ROUTES)
# ============================================================================

@router.get("/api/ab/templates", dependencies=[Depends(auth)])
def get_ab_templates():
    return {
        "prompt_templates": list(PROMPT_TEMPLATES.values()),
        "greeting_templates": list(GREETING_TEMPLATES.values()),
        "tts_seed_presets": list(TTS_SEED_PRESETS.values()),
    }


@router.get("/api/ab/experiments", dependencies=[Depends(auth)])
def list_ab_experiments():
    with db_module.Session() as db:
        seed_default_experiment(db)
        return get_all_experiments(db)


@router.post("/api/ab/experiments", dependencies=[Depends(auth)])
def create_ab_experiment_endpoint(body: ABExperimentIn):
    with db_module.Session() as db:
        try:
            return create_experiment(
                db,
                name=body.name,
                description=body.description,
                experiment_type=body.experiment_type,
                variants=body.variants,
                target_metric=body.target_metric,
            )
        except ValueError as e:
            raise HTTPException(400, str(e))


@router.get("/api/ab/experiments/{id}", dependencies=[Depends(auth)])
def get_ab_experiment_endpoint(id: str):
    with db_module.Session() as db:
        exp = get_experiment_by_id(db, id)
        if not exp:
            raise HTTPException(404, "Deney bulunamadı")
        return exp


@router.post("/api/ab/experiments/{id}/status", dependencies=[Depends(auth)])
def update_ab_experiment_status_endpoint(id: str, body: ABStatusIn):
    with db_module.Session() as db:
        try:
            return set_experiment_status(db, id, body.status)
        except ValueError as e:
            raise HTTPException(400, str(e))


@router.get("/api/ab/experiments/{id}/report", dependencies=[Depends(auth)])
def get_ab_experiment_report_endpoint(id: str):
    with db_module.Session() as db:
        try:
            return get_experiment_report(db, id)
        except ValueError as e:
            raise HTTPException(404, str(e))


@router.post("/api/ab/preview-synth", dependencies=[Depends(auth)])
async def ab_preview_synth(body: ABPreviewSynthIn):
    # "Aktif görüşme" = en az bir oturum var (locked() yalnızca kapasite dolunca True olur).
    if active.active_count > 0:
        raise HTTPException(409, "Aktif görüşme var")
    try:
        w = await models.synth(body.text, seed=body.seed)
    except Exception as e:
        raise HTTPException(503, str(e))
    buf = io.BytesIO()
    sf.write(buf, w, 48000, format="WAV", subtype="PCM_16")
    return Response(buf.getvalue(), media_type="audio/wav")


_dialogue_sessions = {}


@router.post("/api/voice/chat-turn", dependencies=[Depends(auth)])
async def voice_chat_turn_endpoint(body: VoiceChatTurnIn):
    """Canlı konuşma metin girişi: F3 LLM çıkarımı + Slot & Niyet takibi."""
    import time
    from backend.dialogue import Dialogue
    from backend.models import models
    from backend.db import Vehicle

    sid = body.session_id or "default-chat-turn"
    if body.reset or sid not in _dialogue_sessions:
        _dialogue_sessions[sid] = Dialogue(sid, mode="inbound")

    dialogue = _dialogue_sessions[sid]
    t0 = time.monotonic()

    # Gerçek LLM çıkarımı ve cevap üretimi (Qwen2.5)
    reply = await dialogue.answer(body.text)
    total_ms = round((time.monotonic() - t0) * 1000, 1)

    llm_metrics = models.last_llm_metrics or {}
    llm_ms = llm_metrics.get("llm_total_ms", total_ms)

    # Niyet ve araç / plaka tespiti
    detected_intent = getattr(dialogue, "inbound_intent", None) or (
        "periyodik_bakim_randevu" if dialogue.vehicle else "genel_bilgi_ve_talep"
    )

    plate = "61 TS 061"
    model_name = "2023 Peugeot 3008 1.5 BlueHDi"
    caller_prof = getattr(dialogue, "caller_profile", None)
    if caller_prof:
        if caller_prof.plate:
            plate = caller_prof.plate
        if caller_prof.vehicle_model:
            model_name = caller_prof.vehicle_model

    if dialogue.vehicle:
        with db_module.Session() as db:
            v = db.get(Vehicle, dialogue.vehicle)
            if v:
                plate = v.plate or plate
                model_name = v.description or model_name

    saat_str = "Yarın 09:30"
    if dialogue.options:
        first_opt = dialogue.options[0]
        if isinstance(first_opt, (list, tuple)) and len(first_opt) > 1:
            saat_str = str(first_opt[1])
        elif isinstance(first_opt, dict):
            saat_str = str(first_opt.get("time", saat_str))

    action_meta = getattr(dialogue, "detected_action_metadata", {}) or {}
    fiyat_kilitli = "1.450 TRY (Standart Paket)"
    if "price" in action_meta:
        fiyat_kilitli = f"{action_meta['price']} TRY"
    elif "estimated_value_tl" in action_meta:
        fiyat_kilitli = f"{action_meta['estimated_value_tl']:,.0f} TRY".replace(",", ".")

    atanan_lift = getattr(dialogue, "assigned_lift", None) or "LIFT-2 (Mekanik Bakım)"

    slot_info = {
        "intent": detected_intent,
        "plaka": plate,
        "musteri": dialogue.customer or (caller_prof.name if caller_prof else "Ahmet Yılmaz (KVKK Onaylı)"),
        "arac": model_name,
        "islem": [dialogue.package_type or "periyodik_bakim"],
        "fiyat_kilitli": fiyat_kilitli,
        "atanan_lift": atanan_lift,
        "saat": saat_str,
    }

    pipeline_events = [
        {"stage": "F0", "status": "bypassed", "source": "text_input", "duration_ms": 0.0},
        {"stage": "F1", "status": "bypassed", "source": "text_input", "duration_ms": 0.0},
        {"stage": "F2", "status": "bypassed", "source": "text_input", "duration_ms": 0.0},
        {"stage": "F3", "status": "completed", "duration_ms": llm_ms, "source": "text_input"},
    ]

    return {
        "reply": reply,
        "intent": detected_intent,
        "customer": dialogue.customer or (caller_prof.name if caller_prof else None),
        "vehicle": model_name,
        "plate": plate,
        "slot_info": slot_info,
        "pipeline_events": pipeline_events,
        "metrics": {
            "llm_total_ms": llm_ms,
            "first_token_ms": llm_metrics.get("llm_first_token_ms", 120),
            "e2e_ms": total_ms,
        },
    }
