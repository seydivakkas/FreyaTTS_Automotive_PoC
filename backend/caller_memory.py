# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""Kullanıcı & Görüşme Hafızası Sistemi (Caller & Session Memory System).

Bu modül; telefon numarası, plaka veya müşteri adı üzerinden arayan profilini,
araç detaylarını, geçmiş bakım kayıtlarını (ör. balata değişimi), garanti
durumunu ve tercihlerini SQLite tabanında yönetir. Çoklu-tur konuşmalarda
bağlamsal sorguları çözümler ve LLM diyalog istemine (Qwen2.5) hafıza enjeksiyonu sağlar.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import or_, func
from backend.db import CallerProfile, now, uid

logger = logging.getLogger("automotive_voice.caller_memory")


def normalize_phone(phone: Optional[str]) -> str:
    """Telefon numarasını standart formata (05XXXXXXXXX) dönüştürür."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    if len(digits) == 12 and digits.startswith("905"):
        return "0" + digits[2:]
    if len(digits) == 11 and digits.startswith("05"):
        return digits
    if len(digits) == 10 and digits.startswith("5"):
        return "0" + digits
    return digits


def normalize_plate(plate: Optional[str]) -> str:
    """Araç plakasını standart formata (örn. '61 TS 061') normalize eder."""
    if not plate:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", str(plate)).upper()
    # 61TS061 -> 61 TS 061 gibi yaygın Türk plakası formatı
    m = re.match(r"^(\d{2})([A-Z]{1,3})(\d{2,4})$", cleaned)
    if m:
        return f"{m.group(1)} {m.group(2)} {m.group(3)}"
    return cleaned


def get_or_create_caller_profile(
    db,
    phone: Optional[str] = None,
    plate: Optional[str] = None,
    name: Optional[str] = None,
) -> CallerProfile:
    """Telefon, plaka veya müşteri adı üzerinden arayan profilini getirir veya oluşturur."""
    norm_phone = normalize_phone(phone)
    norm_plate = normalize_plate(plate)
    clean_name = (name or "").strip()

    profile: Optional[CallerProfile] = None

    # 1. Telefon numarasına göre ara
    if norm_phone:
        profile = (
            db.query(CallerProfile)
            .filter(CallerProfile.phone == norm_phone)
            .first()
        )

    # 2. Plakaya göre ara
    if not profile and norm_plate:
        profile = (
            db.query(CallerProfile)
            .filter(
                or_(
                    CallerProfile.plate == norm_plate,
                    func.replace(CallerProfile.plate, " ", "") == norm_plate.replace(" ", ""),
                )
            )
            .first()
        )

    # 3. Ada göre ara (büyük/küçük harf duyarsız)
    if not profile and clean_name and len(clean_name) >= 3:
        profile = (
            db.query(CallerProfile)
            .filter(func.lower(CallerProfile.name) == clean_name.lower())
            .first()
        )

    # Bulunduysa eksik alanları güncelle
    if profile:
        changed = False
        if norm_phone and not profile.phone:
            profile.phone = norm_phone
            changed = True
        if norm_plate and not profile.plate:
            profile.plate = norm_plate
            changed = True
        if clean_name and not profile.name:
            profile.name = clean_name
            changed = True
        if changed:
            profile.updated_at = now()
            db.flush()
        return profile

    # Bulunamadıysa yeni profil oluştur
    new_profile = CallerProfile(
        id=uid(),
        phone=norm_phone or (phone or "").strip(),
        plate=norm_plate or (plate or "").strip(),
        name=clean_name,
        vehicle_model="",
        warranty_expires_at=None,
        warranty_status="unknown",
        maintenance_history_json="[]",
        inspection_scores_json="[]",
        notes="",
        user_preferences_json="{}",
        created_at=now(),
        updated_at=now(),
    )
    db.add(new_profile)
    db.flush()
    return new_profile


def format_caller_memory_context(profile: Optional[CallerProfile]) -> str:
    """LLM (Qwen2.5) prompt'u için yapılandırılmış hafıza bağlamı metni üretir."""
    if not profile:
        return ""

    parts = []
    if profile.name:
        parts.append(f"Müşteri: {profile.name}")
    if profile.phone:
        parts.append(f"Telefon: {profile.phone}")
    if profile.plate:
        parts.append(f"Plaka: {profile.plate}")
    if profile.vehicle_model:
        parts.append(f"Araç: {profile.vehicle_model}")

    # Garanti durumu
    w_info = resolve_warranty_inquiry(profile)
    if w_info["status"] != "unknown":
        status_tr = "Aktif" if w_info["is_valid"] else ("Sona Erdi" if w_info["status"] == "expired" else "Geçersiz")
        exp_date = w_info.get("expires_at", "")
        parts.append(f"Garanti: {status_tr} ({exp_date})")

    # Bakım geçmişi özeti
    try:
        history = json.loads(profile.maintenance_history_json or "[]")
        if history:
            last_repairs = []
            for item in history[:2]:  # En son 2 işlem
                d = item.get("date", "")
                it = item.get("item", "")
                km = f"{item.get('km', '')} km" if item.get("km") else ""
                nt = item.get("notes", "")
                entry = f"{d} {km} {it}".strip()
                if nt:
                    entry += f" ({nt})"
                last_repairs.append(entry)
            parts.append("Geçmiş Bakımlar: " + "; ".join(last_repairs))
    except Exception:
        pass

    # Ekspertiz puanı
    try:
        scores = json.loads(profile.inspection_scores_json or "[]")
        if scores:
            last_score = scores[-1]
            parts.append(f"Son Ekspertiz: {last_score.get('score', 100)}/100 ({last_score.get('date', '')})")
    except Exception:
        pass

    if profile.notes:
        parts.append(f"Not: {profile.notes}")

    return " | ".join(parts)


def resolve_warranty_inquiry(
    profile: Optional[CallerProfile],
    query_date: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Aracın garanti süresi ve geçerlilik durumunu değerlendirir."""
    if not profile or not profile.warranty_expires_at:
        return {
            "is_valid": False,
            "status": "unknown" if not profile else profile.warranty_status,
            "expires_at": None,
            "message": "Aracınıza ait sistemimizde kayıtlı bir garanti kaydı bulunamadı. Servis danışmanımız ruhsat bilgileriyle garanti kontrolü yapabilir.",
        }

    now_dt = query_date or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)

    # void / geçersiz kontrolü
    if profile.warranty_status in ("void", "cancelled", "invalid"):
        return {
            "is_valid": False,
            "status": "void",
            "expires_at": profile.warranty_expires_at,
            "message": f"Sayın {profile.name or 'müşterimiz'}, {profile.vehicle_model or 'aracınızın'} garantisi yetkili servis dışı müdahale nedeniyle geçersiz görünmektedir.",
        }

    # Tarih ayrıştırma (ISO format veya YYYY-MM-DD)
    exp_str = str(profile.warranty_expires_at).strip()
    exp_dt = None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            exp_dt = datetime.strptime(exp_str[:19], fmt[: len(exp_str[:19])]).replace(tzinfo=timezone.utc)
            break
        except ValueError:
            continue

    if not exp_dt:
        return {
            "is_valid": profile.warranty_status == "active",
            "status": profile.warranty_status,
            "expires_at": exp_str,
            "message": f"Sayın {profile.name or 'müşterimiz'}, garanti durumunuz: {profile.warranty_status} ({exp_str}).",
        }

    formatted_tr = exp_dt.strftime("%d.%m.%Y")
    if exp_dt >= now_dt:
        return {
            "is_valid": True,
            "status": "active",
            "expires_at": formatted_tr,
            "message": f"Evet Sayın {profile.name or 'müşterimiz'}, {profile.vehicle_model or 'aracınızın'} garantisi {formatted_tr} tarihine kadar aktif olarak devam etmektedir.",
        }
    else:
        return {
            "is_valid": False,
            "status": "expired",
            "expires_at": formatted_tr,
            "message": f"Sayın {profile.name or 'müşterimiz'}, {profile.vehicle_model or 'aracınızın'} fabrika garantisi {formatted_tr} tarihinde sona ermiştir.",
        }


def resolve_past_maintenance(profile: Optional[CallerProfile], keyword: str) -> Optional[str]:
    """Müşterinin geçmiş bakım kayıtlarında anahtar kelimeyi (ör. 'balata', 'yağ') arar."""
    if not profile or not profile.maintenance_history_json:
        return None

    try:
        history: List[Dict[str, Any]] = json.loads(profile.maintenance_history_json)
    except Exception:
        return None

    kw = (keyword or "").strip().lower()
    if not kw:
        return None

    # Türkçe karakter dönüşümü
    kw_norm = kw.replace("i̇", "i").replace("ı", "i")

    for rec in history:
        item = str(rec.get("item", "")).lower().replace("i̇", "i").replace("ı", "i")
        notes = str(rec.get("notes", "")).lower().replace("i̇", "i").replace("ı", "i")
        desc = str(rec.get("description", "")).lower().replace("i̇", "i").replace("ı", "i")

        if kw_norm in item or kw_norm in notes or kw_norm in desc:
            d = rec.get("date", "")
            km = f"{rec.get('km', '')} km" if rec.get("km") else ""
            it = rec.get("item", "")
            nt = rec.get("notes", "")
            # Tarih varsa Türkçeleştir veya biçimlendir
            details = f"{d} tarihinde {km} bakımında {it}".strip()
            if nt:
                details += f" ({nt})"
            return f"Kayıtlarımıza göre {details} yapılmıştır."

    return None


def add_maintenance_record(
    profile: CallerProfile,
    date: str,
    item: str,
    km: int = 0,
    cost_tl: int = 0,
    notes: str = "",
) -> None:
    """Profile yeni bir bakım geçmişi kaydı ekler."""
    try:
        history = json.loads(profile.maintenance_history_json or "[]")
    except Exception:
        history = []

    history.insert(
        0,
        {
            "date": date,
            "item": item,
            "km": km,
            "cost_tl": cost_tl,
            "notes": notes,
        },
    )
    profile.maintenance_history_json = json.dumps(history, ensure_ascii=False)
    profile.updated_at = now()


def seed_default_profiles(db) -> List[CallerProfile]:
    """Demo ve test senaryoları için varsayılan müşteri bellek kayıtlarını ekler (idempotent)."""
    existing_ahmet = (
        db.query(CallerProfile)
        .filter(CallerProfile.phone == "05321234567")
        .first()
    )
    created = []
    if not existing_ahmet:
        ahmet = CallerProfile(
            id=uid(),
            phone="05321234567",
            plate="61 TS 061",
            name="Ahmet Yılmaz",
            vehicle_model="2023 Peugeot 3008 1.5 BlueHDi",
            warranty_expires_at="2027-06-15",
            warranty_status="active",
            maintenance_history_json=json.dumps(
                [
                    {
                        "date": "2026-09-12",
                        "km": 45000,
                        "item": "Ön fren balatası ve disk değişimi",
                        "cost_tl": 4500,
                        "notes": "Orijinal Bosch fren balatası takıldı, hidrolik yenilendi",
                    },
                    {
                        "date": "2026-03-05",
                        "km": 30000,
                        "item": "30.000 km periyodik bakım",
                        "cost_tl": 5200,
                        "notes": "Motor yağı, yağ, hava ve polen filtreleri değişti",
                    },
                ],
                ensure_ascii=False,
            ),
            inspection_scores_json=json.dumps(
                [{"date": "2026-03-05", "score": 94}], ensure_ascii=False
            ),
            notes="Düzenli yetkili servis müşterisi. Orijinal parça ve mobil onay tercih ediyor.",
            user_preferences_json=json.dumps(
                {"preferred_time": "morning", "sms_notify": True}, ensure_ascii=False
            ),
            created_at=now(),
            updated_at=now(),
        )
        db.add(ahmet)
        created.append(ahmet)

    existing_mehmet = (
        db.query(CallerProfile)
        .filter(CallerProfile.phone == "05559876543")
        .first()
    )
    if not existing_mehmet:
        mehmet = CallerProfile(
            id=uid(),
            phone="05559876543",
            plate="34 BJK 1903",
            name="Mehmet Demir",
            vehicle_model="2020 Volkswagen Passat 1.5 TSI",
            warranty_expires_at="2023-10-15",
            warranty_status="expired",
            maintenance_history_json=json.dumps(
                [
                    {
                        "date": "2023-09-10",
                        "km": 60000,
                        "item": "DSG şanzıman yağı ve mekatronik bakımı",
                        "cost_tl": 8500,
                        "notes": "Kavrama adaptasyonu yapıldı",
                    }
                ],
                ensure_ascii=False,
            ),
            inspection_scores_json=json.dumps(
                [{"date": "2023-09-10", "score": 87}], ensure_ascii=False
            ),
            notes="Garantisi bitmiş araç. İndirimli özel paketler önerilmeli.",
            user_preferences_json=json.dumps({"sms_notify": True}, ensure_ascii=False),
            created_at=now(),
            updated_at=now(),
        )
        db.add(mehmet)
        created.append(mehmet)

    if created:
        db.commit()
    return created
