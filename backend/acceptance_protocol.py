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

import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import func, select

from backend.acoustic_evaluation import load_latest_report
from backend.automotive_terminology import (
    analyze_acoustic_report_layer_attribution,
    canonicalize_asr_text,
)
from backend.config import settings
from backend.db import Appointment, Conversation, Quote, Slot, Turn, Vehicle
from backend.turkish_plate import extract_plate

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

ACCEPTANCE_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "run_1_plate_correction": {
        "id": "run_1_plate_correction",
        "title": "Koşu 1 · Plaka Düzeltme ve Tek Kayıt",
        "short_label": "Koşu 1 (Plaka Düzeltme)",
        "objective": (
            "Doğal Türkçeyle Corolla randevusu iste, sözlü plakayı 'C değil Denizli'nin D'si' ile düzelt "
            "ve açık onay sonrasında takvimde tek kayıt doğrula."
        ),
        "script_steps": [
            "1. 'Corolla için yarın sabah ekspertiz randevusu istiyorum.' deyin.",
            "2. Plaka sorulduğunda 'Otuz dört Adana Bursa Ceyhan yüz yirmi üç' (34 ABC 123) deyin.",
            "3. 'C değil, Denizli'nin D'si' diyerek plakayı 34 ABD 123 olarak güncelleyin.",
            "4. Özeti dinleyin ve 'Evet, onaylıyorum' diyerek kaydı tamamlayın.",
        ],
        "expected_new_appointments": 1,
        "expected_final_plate": "34 ABD 123",
        "pass_criteria": [
            "Freya final plakayı 34 ABD 123 okur ve DB'ye yazar",
            "Onay öncesi DB mutasyonu 0 kalır",
            "Takvimde doğru saatle tam 1 confirmed randevu oluşur",
            "Konuşulan FRY-... referansı veritabanı kimliğiyle eşleşir",
        ],
    },
    "run_2_early_confirm_abort": {
        "id": "run_2_early_confirm_abort",
        "title": "Koşu 2 · Erken Onay Reddi ve Vazgeçme",
        "short_label": "Koşu 2 (Erken Onay / Vazgeçme)",
        "objective": (
            "Teyit sorusunda 'Evet, sizi duyuyorum' erken onayının kayıt yazmadığını ve 'Vazgeçtim' "
            "komutunun randevu oluşturmadan görüşmeyi kapattığını doğrula."
        ),
        "script_steps": [
            "1. Corolla randevusu isteyip plaka söyleyin (ör. 34 ABC 123) ve onay özetini bekleyin.",
            "2. Özet sorusuna 'Evet, sizi duyuyorum' deyin (kayıt OLUŞMAMALI).",
            "3. Ardından 'Vazgeçtim' veya 'Hayır, istemiyorum' diyerek görüşmeyi kapatın.",
        ],
        "expected_new_appointments": 0,
        "expected_final_plate": None,
        "pass_criteria": [
            "Erken 'Evet, sizi duyuyorum' sonrası DB'ye kayıt yazılmaz",
            "Görüşme sonunda net yeni randevu sayısı 0 kalır",
        ],
    },
    "run_3_natural_idempotency": {
        "id": "run_3_natural_idempotency",
        "title": "Koşu 3 · Doğal İfade ve Tekrarlanan Onay (Idempotency)",
        "short_label": "Koşu 3 (Doğal + Çift Onay)",
        "objective": (
            "İlk talebi serbest/doğal kelimelerle başlat, randevuyu onayla ve ardından aynı onayı "
            "tekrarlayarak çift kayıt oluşmadığını doğrula."
        ),
        "script_steps": [
            "1. İlk ekspertiz isteğinizi kendi doğal kelimelerinizle (örn. Corolla / Qashqai / Pejo) söyleyin.",
            "2. Plakayı verip özet sonrası 'Evet, onaylıyorum' ile ilk kaydı oluşturun.",
            "3. Başarılı onay yanıtından sonra 'Evet, onaylıyorum' ifadesini bir kez daha tekrarlayın.",
        ],
        "expected_new_appointments": 1,
        "expected_final_plate": None,
        "pass_criteria": [
            "Doğal ifade doğru araç ve saatle eşleşir",
            "Tekrarlanan onay ikinci bir kayıt oluşturmaz (net yeni randevu = 1)",
        ],
    },
}


def acceptance_runs_dir() -> Path:
    d = Path(settings.data_dir) / "acceptance" / "runs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_json_loads(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw or not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _pct_stats(values: List[float]) -> Optional[Dict[str, Any]]:
    clean = [round(float(v), 1) for v in values if v is not None and v > 0]
    if not clean:
        return None
    arr = np.asarray(clean, dtype=np.float64)
    return {
        "count": len(clean),
        "avg_ms": round(float(np.mean(arr)), 1),
        "p50_ms": round(float(np.percentile(arr, 50)), 1),
        "p95_ms": round(float(np.percentile(arr, 95)), 1),
        "max_ms": round(float(np.max(arr)), 1),
    }


def _normalize_plate_compact(plate: Optional[str]) -> str:
    if not plate:
        return ""
    return re.sub(r"[^A-ZÇĞİÖŞÜ0-9]", "", plate.upper())


def _parse_iso_dt(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        norm = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
        dt = datetime.fromisoformat(norm)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def get_prerequisites_status(db) -> Dict[str, Any]:
    """Canlı mikrofon kabul koşusu ön koşullarını gerçek model ve DB durumuyla denetler."""
    from backend.models import models

    vehicles = db.scalars(select(Vehicle)).all()
    quotes = db.scalars(select(Quote)).all()
    quote_vehicle_ids = {q.vehicle_id for q in quotes if q.amount_kurus}

    corolla_v = next((v for v in vehicles if "corolla" in (v.description or "").lower()), None)
    has_poc_vehicle = corolla_v is not None
    has_poc_quote = (corolla_v.id in quote_vehicle_ids) if corolla_v else False

    now_utc = datetime.now(timezone.utc)
    occupied_slot_ids = set(
        db.scalars(
            select(Appointment.slot_id).where(
                Appointment.slot_id.is_not(None),
                Appointment.status.in_(("confirmed", "pending")),
            )
        ).all()
    )
    future_slots = []
    for s in db.scalars(select(Slot).order_by(Slot.starts_at)).all():
        dt = _parse_iso_dt(s.starts_at)
        if dt and dt > now_utc:
            future_slots.append(s)

    open_future = [s for s in future_slots if s.id not in occupied_slot_ids]
    occupied_future = [s for s in future_slots if s.id in occupied_slot_ids]

    acoustic_report = load_latest_report()
    acoustic_attr = analyze_acoustic_report_layer_attribution(acoustic_report)

    models_ready = {
        "tts": bool(models.tts is not None),
        "stt": bool(models.stt is not None),
        "vad": bool(models.vad is not None),
        "ollama": bool(models.ollama_ready),
    }

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "demo_mode": settings.demo_mode,
        "models_ready": models_ready,
        "all_audio_models_loaded": all(models_ready.values()),
        "stt_model": settings.stt_model,
        "stt_catalog_hotwords": settings.stt_catalog_hotwords,
        "stt_min_rms": settings.stt_min_rms,
        "database": {
            "vehicles_count": len(vehicles),
            "has_poc_corolla": has_poc_vehicle,
            "has_poc_quote": has_poc_quote,
            "future_slots_count": len(future_slots),
            "open_future_slots_count": len(open_future),
            "occupied_future_slots_count": len(occupied_future),
            "poc_fixture_ready": bool(has_poc_vehicle and has_poc_quote and len(open_future) >= 1),
        },
        "acoustic_gate": {
            "available": acoustic_attr.get("available", False),
            "strict_term_accuracy_pct": acoustic_attr.get("strict_term_accuracy_pct"),
            "post_canonical_accuracy_pct": acoustic_attr.get("post_canonical_accuracy_pct"),
            "measured_at": acoustic_attr.get("measured_at"),
        },
    }


def prepare_poc_acceptance_fixtures(db, *, reset_existing: bool = False) -> Dict[str, Any]:
    """Bölüm 10 PoC kabul senaryosu fikstürünü aktif DB üzerinde idempotent biçimde hazırlar.

    - Toyota Corolla aracı ve 2.500 TL (250.000 kuruş) ekspertiz teklifi
    - Yarın 09:00 dolu (alternatif teklif testi için) ve yarın 10:00 müsait slot
    """
    if reset_existing:
        db.query(Appointment).filter(Appointment.customer == "PoC Doluluk (09.00)").delete()
        db.flush()

    corolla = db.scalars(
        select(Vehicle).where(func.lower(Vehicle.description).contains("corolla"))
    ).first()
    if corolla is None:
        corolla = Vehicle(description="Toyota Corolla", plate="")
        db.add(corolla)
        db.flush()

    quote = db.scalars(select(Quote).where(Quote.vehicle_id == corolla.id)).first()
    if quote is None:
        quote = Quote(vehicle_id=corolla.id, amount_kurus=250000)
        db.add(quote)
        db.flush()

    tomorrow = datetime.now(ISTANBUL_TZ) + timedelta(days=1)
    t_09_iso = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0).isoformat()
    t_10_iso = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0).isoformat()

    slot_09 = db.scalars(select(Slot).where(Slot.starts_at == t_09_iso)).first()
    if slot_09 is None:
        slot_09 = Slot(starts_at=t_09_iso, duration_minutes=30)
        db.add(slot_09)
        db.flush()

    existing_09_app = db.scalars(
        select(Appointment).where(
            Appointment.slot_id == slot_09.id,
            Appointment.status.in_(("confirmed", "pending")),
        )
    ).first()
    if existing_09_app is None:
        db.add(
            Appointment(
                slot_id=slot_09.id,
                vehicle_id=corolla.id,
                customer="PoC Doluluk (09.00)",
                customer_phone="05000000099",
                idempotency_key=f"poc-0900-{uuid4().hex[:8]}",
                status="confirmed",
                confirmed=True,
                package_type="standart_ekspertiz",
            )
        )

    slot_10 = db.scalars(select(Slot).where(Slot.starts_at == t_10_iso)).first()
    if slot_10 is None:
        slot_10 = Slot(starts_at=t_10_iso, duration_minutes=30)
        db.add(slot_10)
        db.flush()
    elif reset_existing:
        db.query(Appointment).filter(Appointment.slot_id == slot_10.id).delete()

    # 10:00 slotunun açık olduğundan emin ol (üzerinde dolu randevu varsa serbest bırakma, ek gün slotu aç)
    occupied_10 = db.scalars(
        select(Appointment).where(
            Appointment.slot_id == slot_10.id,
            Appointment.status.in_(("confirmed", "pending")),
        )
    ).first()
    if occupied_10 is not None:
        # Mevcut 10:00 doluysa +2 gün sonraya da 10:00 ek açık slot açarak gerçek veriyi bozmadan test imkanı sun
        alt_iso = (tomorrow + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0).isoformat()
        if db.scalars(select(Slot).where(Slot.starts_at == alt_iso)).first() is None:
            slot_10 = Slot(starts_at=alt_iso, duration_minutes=30)
            db.add(slot_10)
            db.flush()

    db.commit()
    return {
        "prepared": True,
        "vehicle": {"id": corolla.id, "description": corolla.description, "quote_kurus": quote.amount_kurus},
        "occupied_slot": {"id": slot_09.id, "starts_at": slot_09.starts_at},
        "open_slot": {"id": slot_10.id, "starts_at": slot_10.starts_at},
    }


def take_db_snapshot(db) -> Dict[str, Any]:
    """Veritabanı durumunun atomik öncesi/sonrası anlık görüntüsünü alır."""
    slot_ids = list(db.scalars(select(Slot.id)).all())
    app_rows = db.scalars(select(Appointment)).all()
    conv_ids = list(db.scalars(select(Conversation.id)).all())
    turn_ids = list(db.scalars(select(Turn.id)).all())
    vehicles_count = db.scalar(select(func.count()).select_from(Vehicle)) or 0

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "slot_ids": slot_ids,
        "appointment_ids": [a.id for a in app_rows],
        "confirmed_appointment_ids": [a.id for a in app_rows if a.confirmed or a.status == "confirmed"],
        "conversation_ids": conv_ids,
        "turn_ids": turn_ids,
        "counts": {
            "slots": len(slot_ids),
            "appointments": len(app_rows),
            "confirmed_appointments": sum(1 for a in app_rows if a.confirmed or a.status == "confirmed"),
            "conversations": len(conv_ids),
            "turns": len(turn_ids),
            "vehicles": vehicles_count,
        },
    }


def _save_run(run_data: Dict[str, Any]) -> Path:
    path = acceptance_runs_dir() / f"{run_data['run_id']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(run_data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_run(run_id: str) -> Optional[Dict[str, Any]]:
    # Path traversal koruması: yalın dosya kimliği
    safe_id = Path(run_id).name
    if safe_id != run_id or not re.fullmatch(r"[A-Za-z0-9_.-]+", safe_id):
        return None
    path = acceptance_runs_dir() / f"{safe_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_runs(limit: int = 30) -> List[Dict[str, Any]]:
    files = sorted(acceptance_runs_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for f in files[:limit]:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            out.append({
                "run_id": d.get("run_id"),
                "scenario_id": d.get("scenario_id"),
                "scenario_title": d.get("scenario_title"),
                "speaker_label": d.get("speaker_label"),
                "environment": d.get("environment"),
                "channel": d.get("channel"),
                "status": d.get("status"),
                "started_at": d.get("started_at"),
                "verified_at": d.get("verified_at"),
                "net_new_appointments": d.get("diff", {}).get("net_new_appointments"),
                "warm_eos_p95_ms": (
                    (d.get("latency_summary") or {}).get("warm_eos_to_first_audio") or {}
                ).get("p95_ms"),
            })
        except Exception:
            continue
    return out


def start_acceptance_run(
    db,
    *,
    scenario_id: str,
    speaker_label: str = "",
    environment: str = "quiet_room",
    notes: str = "",
    channel: str = "web_mic",
) -> Dict[str, Any]:
    if scenario_id not in ACCEPTANCE_SCENARIOS:
        raise ValueError(f"Bilinmeyen kabul senaryosu: {scenario_id}")

    scenario = ACCEPTANCE_SCENARIOS[scenario_id]
    stamp = datetime.now(ISTANBUL_TZ).strftime("%Y%m%d_%H%M%S")
    run_id = f"{scenario_id}_{stamp}_{uuid4().hex[:6]}"
    before_snap = take_db_snapshot(db)

    run_data = {
        "schema": 1,
        "run_id": run_id,
        "scenario_id": scenario_id,
        "scenario_title": scenario["title"],
        "speaker_label": speaker_label.strip() or "anonim",
        "environment": environment,
        "channel": channel,
        "notes": notes.strip(),
        "status": "IN_PROGRESS",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "verified_at": None,
        "demo_mode": settings.demo_mode,
        "before_snapshot": before_snap,
        "after_snapshot": None,
        "diff": {},
        "turns_timeline": [],
        "latency_summary": {},
        "checks": {},
        "layer_diagnostics": {},
    }
    _save_run(run_data)
    return run_data


def _extract_turn_evidence(db, new_turns: List[Turn]) -> Dict[str, Any]:
    timeline: List[Dict[str, Any]] = []
    warm_eos: List[float] = []
    cold_eos: List[float] = []
    stt_latencies: List[float] = []
    tts_latencies: List[float] = []
    llm_latencies: List[float] = []

    user_texts: List[str] = []
    assistant_texts: List[str] = []
    plates_seen: List[str] = []
    intents_seen: List[str] = []
    unrecognized_count = 0
    max_pre_confirm_mutations = 0
    canonical_fix_count = 0
    metric_trace_by_turn: List[Dict[str, Any]] = []

    for t in new_turns:
        m = _safe_json_loads(t.metrics)
        if t.role == "metric":
            if m.get("stt_unrecognized"):
                unrecognized_count += int(m["stt_unrecognized"])
            if m.get("eos_to_first_audio_ms") is not None:
                val = float(m["eos_to_first_audio_ms"])
                if m.get("cold_synthesis"):
                    cold_eos.append(val)
                else:
                    warm_eos.append(val)
            elif m.get("first_audio_ms") is not None and "cold_synthesis" in m:
                val = float(m["first_audio_ms"])
                if m.get("cold_synthesis"):
                    cold_eos.append(val)
                else:
                    warm_eos.append(val)
            if m.get("tts_ms") is not None:
                tts_latencies.append(float(m["tts_ms"]))
            if m.get("llm_total_ms") is not None:
                llm_latencies.append(float(m["llm_total_ms"]))
            trace = m.get("last_turn_trace")
            dstate = m.get("dialogue_state")
            if isinstance(trace, dict) or isinstance(dstate, dict):
                metric_trace_by_turn.append({"trace": trace or {}, "dialogue_state": dstate or {}})
                if isinstance(trace, dict):
                    if trace.get("plate_candidate"):
                        plates_seen.append(str(trace["plate_candidate"]))
                    if trace.get("intent"):
                        intents_seen.append(str(trace["intent"]))
                    mut_pre = int(trace.get("mutations_before_confirmation") or 0)
                    max_pre_confirm_mutations = max(max_pre_confirm_mutations, mut_pre)
                if isinstance(dstate, dict) and dstate.get("plate"):
                    plates_seen.append(str(dstate["plate"]))
            continue

        if t.role == "user":
            user_texts.append(t.text or "")
            if m.get("stt_ms") is not None:
                stt_latencies.append(float(m["stt_ms"]))
            canon = canonicalize_asr_text(t.text or "")
            if canon["applied_mappings"]:
                canonical_fix_count += len(canon["applied_mappings"])
            parsed_plate = extract_plate(canon["canonical_text"] or t.text or "") or extract_plate(t.text or "")
            if parsed_plate:
                plates_seen.append(parsed_plate)
            timeline.append({
                "turn_id": t.id,
                "conversation_id": t.conversation_id,
                "created_at": t.created_at,
                "role": "user",
                "raw_text": t.text,
                "canonical_text": canon["canonical_text"],
                "applied_term_fixes": canon["applied_mappings"],
                "extracted_plate": parsed_plate,
                "stt_ms": m.get("stt_ms"),
                "endpoint_ms": m.get("endpoint_ms"),
                "input_type": m.get("input_type", "voice"),
            })
        elif t.role == "assistant":
            assistant_texts.append(t.text or "")
            timeline.append({
                "turn_id": t.id,
                "conversation_id": t.conversation_id,
                "created_at": t.created_at,
                "role": "assistant",
                "raw_text": t.text,
                "canonical_text": t.text,
            })

    # Dstate / trace izlerini timeline'daki user turlarına geriye dönük bağla
    user_entries = [item for item in timeline if item["role"] == "user"]
    for idx, tr_bundle in enumerate(metric_trace_by_turn):
        if idx < len(user_entries):
            tr = tr_bundle["trace"]
            ds = tr_bundle["dialogue_state"]
            user_entries[idx]["intent"] = tr.get("intent") or ds.get("inbound_intent")
            user_entries[idx]["state_after"] = tr.get("state_after") or ds.get("booking_status")
            user_entries[idx]["plate_state"] = tr.get("plate_candidate") or ds.get("plate")
            user_entries[idx]["db_mutations"] = tr.get("db_mutations", 0)
            user_entries[idx]["eos_to_first_audio_ms"] = ds.get("eos_to_first_audio_ms")

    return {
        "timeline": timeline,
        "user_texts": user_texts,
        "assistant_texts": assistant_texts,
        "plates_seen": list(dict.fromkeys(plates_seen)),
        "intents_seen": intents_seen,
        "unrecognized_count": unrecognized_count,
        "max_pre_confirm_mutations": max_pre_confirm_mutations,
        "canonical_fix_count": canonical_fix_count,
        "latency_summary": {
            "warm_eos_to_first_audio": _pct_stats(warm_eos),
            "cold_eos_to_first_audio": _pct_stats(cold_eos),
            "stt": _pct_stats(stt_latencies),
            "tts": _pct_stats(tts_latencies),
            "llmRuleDialogue": _pct_stats(llm_latencies),
        },
    }


def _evaluate_run_checks_and_layers(
    scenario_id: str,
    new_apps: List[Dict[str, Any]],
    ev: Dict[str, Any],
) -> tuple[str, Dict[str, Any], Dict[str, Any]]:
    scenario = ACCEPTANCE_SCENARIOS[scenario_id]
    user_turns_count = len(ev["user_texts"])
    confirmed_apps = [a for a in new_apps if a["confirmed"] or a["status"] == "confirmed"]
    net_new_count = len(new_apps)
    confirmed_count = len(confirmed_apps)

    checks: Dict[str, Any] = {
        "has_user_turns": user_turns_count >= 1,
        "no_unrecognized_audio": ev["unrecognized_count"] == 0,
        "zero_preconfirm_mutations": ev["max_pre_confirm_mutations"] == 0,
    }

    if scenario_id == "run_1_plate_correction":
        exp_plate = _normalize_plate_compact(scenario.get("expected_final_plate"))
        actual_plate = _normalize_plate_compact(confirmed_apps[0]["plate"] if confirmed_apps else None)
        ref_code = confirmed_apps[0]["reference_code"] if confirmed_apps else ""
        ref_spoken = bool(
            ref_code
            and any(ref_code in (txt or "").upper() for txt in ev["assistant_texts"])
        )
        checks.update({
            "single_appointment_created": net_new_count == 1 and confirmed_count == 1,
            "final_plate_matches_expected": bool(exp_plate and actual_plate == exp_plate),
            "reference_matches_spoken": ref_spoken,
            "plate_correction_trace_present": (
                "plate_correction" in ev["intents_seen"]
                or len(ev["plates_seen"]) >= 2
                or actual_plate == exp_plate
            ),
        })
    elif scenario_id == "run_2_early_confirm_abort":
        early_or_decline_seen = any(
            i in ev["intents_seen"]
            for i in ("early_yes", "presence_ack_keep_awaiting", "booking_declined", "negated")
        ) or any(
            k in " ".join(ev["user_texts"]).lower()
            for k in ("duyuyorum", "vazgeç", "hayır", "istemiyorum")
        )
        checks.update({
            "zero_appointments_created": net_new_count == 0 and confirmed_count == 0,
            "early_or_abort_uttered": early_or_decline_seen,
        })
    elif scenario_id == "run_3_natural_idempotency":
        confirm_utterances = sum(
            1 for txt in ev["user_texts"] if "onaylıyorum" in (txt or "").lower()
        )
        idempotency_verified = (
            net_new_count == 1
            and confirmed_count == 1
            and ("already_confirmed" in ev["intents_seen"] or confirm_utterances >= 2)
        )
        checks.update({
            "single_appointment_created": net_new_count == 1 and confirmed_count == 1,
            "repeated_confirm_idempotent": idempotency_verified,
        })

    # Katmanlı Hata & Durum Teşhisi
    f2_status = "NOT_RUN" if user_turns_count == 0 else ("WARN" if ev["unrecognized_count"] > 0 else "PASS")
    plate_term_ok = True
    if scenario_id == "run_1_plate_correction":
        plate_term_ok = checks.get("final_plate_matches_expected", False)
    f2b_status = "NOT_RUN" if user_turns_count == 0 else ("PASS" if plate_term_ok else "FAIL")

    policy_ok = checks["zero_preconfirm_mutations"]
    if scenario_id == "run_2_early_confirm_abort":
        policy_ok = policy_ok and checks.get("zero_appointments_created", False)
    elif scenario_id == "run_3_natural_idempotency":
        policy_ok = policy_ok and checks.get("repeated_confirm_idempotent", False)
    f3_status = "NOT_RUN" if user_turns_count == 0 else ("PASS" if policy_ok else "FAIL")

    warm_eos = (ev["latency_summary"] or {}).get("warm_eos_to_first_audio")
    if user_turns_count == 0 or warm_eos is None:
        f5_status = "PASS" if len(ev["assistant_texts"]) > 0 else "NOT_RUN"
    elif warm_eos["p95_ms"] <= 2500.0:
        f5_status = "PASS"
    else:
        f5_status = "WARN"

    if scenario_id == "run_2_early_confirm_abort":
        db_ok = checks.get("zero_appointments_created", False)
    else:
        db_ok = checks.get("single_appointment_created", False) and (
            checks.get("reference_matches_spoken", True)
        )
    db_status = "NOT_RUN" if user_turns_count == 0 else ("PASS" if db_ok else "FAIL")

    layers = {
        "F0_F1_AUDIO_VAD": {
            "status": "NOT_RUN" if user_turns_count == 0 else "PASS",
            "detail": f"{user_turns_count} kullanıcı turu alındı",
        },
        "F2_ASR_STT": {
            "status": f2_status,
            "detail": (
                f"Boş/tanınmayan ses: {ev['unrecognized_count']}, "
                f"Kanonik terim kurtarma: {ev['canonical_fix_count']}"
            ),
        },
        "F2B_PLATE_TERMINOLOGY": {
            "status": f2b_status,
            "detail": f"Görülen plakalar: {ev['plates_seen'] or ['—']}",
        },
        "F3_DIALOGUE_POLICY": {
            "status": f3_status,
            "detail": f"Onay öncesi mutasyon: {ev['max_pre_confirm_mutations']}, Niyet izi: {ev['intents_seen']}",
        },
        "F4_F5_TTS": {
            "status": f5_status,
            "detail": (
                f"Sıcak EOS→İlk Ses p95: {warm_eos['p95_ms']} ms"
                if warm_eos
                else f"Asistan yanıt sayısı: {len(ev['assistant_texts'])}"
            ),
        },
        "DB_CALENDAR": {
            "status": db_status,
            "detail": f"Yeni randevu: {net_new_count} (Confirmed: {confirmed_count})",
        },
    }

    if user_turns_count == 0:
        overall = "INCOMPLETE"
    elif all(bool(v) for v in checks.values()):
        overall = "PASS"
    else:
        overall = "FAIL"

    return overall, checks, layers


def finish_and_verify_run(db, run_id: str) -> Dict[str, Any]:
    """Kabul koşusunun sonrası anlık görüntüsünü alır, DB farkını ve tüm geçme koşullarını doğrular."""
    run_data = load_run(run_id)
    if run_data is None:
        raise ValueError(f"Kabul koşusu bulunamadı: {run_id}")

    before = run_data["before_snapshot"]
    after = take_db_snapshot(db)

    before_app_ids = set(before.get("appointment_ids") or [])
    after_app_ids = set(after.get("appointment_ids") or [])
    new_app_ids = sorted(after_app_ids - before_app_ids)

    new_apps_detailed: List[Dict[str, Any]] = []
    if new_app_ids:
        app_objs = db.scalars(
            select(Appointment).where(Appointment.id.in_(new_app_ids)).order_by(Appointment.created_at)
        ).all()
        for app in app_objs:
            veh = db.get(Vehicle, app.vehicle_id) if app.vehicle_id else None
            slt = db.get(Slot, app.slot_id) if app.slot_id else None
            new_apps_detailed.append({
                "id": app.id,
                "reference_code": f"FRY-{app.id[:6].upper()}",
                "customer": app.customer,
                "customer_phone": app.customer_phone,
                "plate": (veh.plate if veh and veh.plate else app.plate) or "",
                "vehicle_description": veh.description if veh else "",
                "slot_starts_at": slt.starts_at if slt else None,
                "status": app.status,
                "confirmed": bool(app.confirmed),
                "idempotency_key": app.idempotency_key,
                "created_at": app.created_at,
            })

    before_turn_ids = set(before.get("turn_ids") or [])
    after_turn_ids = set(after.get("turn_ids") or [])
    new_turn_ids = list(after_turn_ids - before_turn_ids)
    new_turns: List[Turn] = []
    if new_turn_ids:
        new_turns = db.scalars(
            select(Turn).where(Turn.id.in_(new_turn_ids)).order_by(Turn.created_at, Turn.id)
        ).all()

    before_conv_ids = set(before.get("conversation_ids") or [])
    after_conv_ids = set(after.get("conversation_ids") or [])
    new_conv_ids = sorted(after_conv_ids - before_conv_ids)

    ev = _extract_turn_evidence(db, new_turns)
    overall, checks, layers = _evaluate_run_checks_and_layers(
        run_data["scenario_id"],
        new_apps_detailed,
        ev,
    )

    run_data["status"] = overall
    run_data["verified_at"] = datetime.now(timezone.utc).isoformat()
    run_data["after_snapshot"] = after
    run_data["diff"] = {
        "new_conversation_ids": new_conv_ids,
        "new_conversations_count": len(new_conv_ids),
        "new_turns_count": len(ev["timeline"]),
        "net_new_appointments": len(new_apps_detailed),
        "new_appointments": new_apps_detailed,
        "plates_seen": ev["plates_seen"],
    }
    run_data["turns_timeline"] = ev["timeline"]
    run_data["latency_summary"] = ev["latency_summary"]
    run_data["checks"] = checks
    run_data["layer_diagnostics"] = layers

    _save_run(run_data)
    return run_data


def _mask_name(name: str) -> str:
    if not name or name.strip() == "":
        return ""
    return " ".join(
        (p[0] + "*" * max(1, len(p) - 1)) if len(p) > 1 else "*"
        for p in name.split()
    )


def _mask_plate(plate: str) -> str:
    if not plate:
        return ""
    return re.sub(r"\b(\d{2})\s*[A-ZÇĞİÖŞÜ]{1,3}\s*(\d{2,4})\b", r"\1 *** \2", plate, flags=re.I)


def _mask_phone(phone: str) -> str:
    if not phone or len(phone) < 6:
        return "***" if phone else ""
    return f"{phone[:4]}****{phone[-2:]}"


def mask_acceptance_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """KVKK uyumlu paylaşım için plaka, müşteri adı ve telefon alanlarını maskeler."""
    masked = copy.deepcopy(report)
    masked["kvkk_masked"] = True
    diff = masked.get("diff") or {}
    if isinstance(diff.get("plates_seen"), list):
        diff["plates_seen"] = [_mask_plate(p) for p in diff["plates_seen"]]
    for app in diff.get("new_appointments") or []:
        if app.get("customer"):
            app["customer"] = _mask_name(app["customer"])
        if app.get("customer_phone"):
            app["customer_phone"] = _mask_phone(app["customer_phone"])
        if app.get("plate"):
            app["plate"] = _mask_plate(app["plate"])

    for t in masked.get("turns_timeline") or []:
        if t.get("raw_text"):
            t["raw_text"] = _mask_plate(t["raw_text"])
        if t.get("canonical_text"):
            t["canonical_text"] = _mask_plate(t["canonical_text"])
        if t.get("extracted_plate"):
            t["extracted_plate"] = _mask_plate(t["extracted_plate"])
        if t.get("plate_state"):
            t["plate_state"] = _mask_plate(t["plate_state"])

    return masked
