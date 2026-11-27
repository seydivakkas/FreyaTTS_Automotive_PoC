# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""Otomotiv Eylem ve Niyet Sevk Motoru (Automotive Action Dispatch Engine).

Bu modül gelen ses/metin kullanıcı ifadelerini analiz ederek 6 temel otomotiv eylemini
ve M01-M11 acil durum güvenlik bariyerlerini sevk eder:
  1. Acil Durum / Yol Yardım Güvenlik Bariyeri (Roadside Emergency)
  2. Randevu Talebi (Booking / Reschedule / Cancel)
  3. Lift & İstasyon Kapasite Durumu (Lift Status)
  4. OBD-II DTC Arıza Analizi ve Teşhis (Diagnostics)
  5. Teknisyen Sesli Dikte İşleme (Technician Dictation)
  6. WhatsApp Ekspertiz Raporu Gönderimi (WhatsApp Delivery)
  7. Dinamik Araç Değerleme ve Paket Fiyatlandırma (Valuation & Pricing)
"""

import logging
import re
from typing import Any, Dict, Optional
from backend.db import Session
from backend.diagnostics import lookup_dtc
from backend.queue_lift import get_lift_capacity_status
from backend import queue_lift
from backend.technician_dictation import parse_technician_dictation
from backend.dynamic_valuation_calculator import (
    parse_spoken_valuation_query,
    calculate_dynamic_valuation,
)
from backend.ontology.grounding import AutomotiveGroundingEngine

logger = logging.getLogger("automotive_voice.dispatch")

# Acil Durum Güvenlik Bariyeri Regex'i
_EMERGENCY_RE = re.compile(
    r"\b(fren(?:ler|im)?\s*(?:tutmuyor|boşaldı|patladı)|"
    r"kaza\s*(?:yaptım|yapacağım|yapmak üzereyim|geçirdik)|"
    r"(?:araba|araç|motor)(?:m|ım)?\s*(?:yanıyor|alev aldı)|"
    r"(?:motor(?:dan|umdan)|kaput(?:tan|un altından))\s*duman\s*çıkıyor|"
    r"hararet\s*(?:kırmızıda|tavan yaptı|sonuna dayandı)|"
    r"direksiyon\s*kilitlendi|"
    r"can\s*güvenliği|acil\s*yardım|yolda\s*kaldım)\b",
    re.IGNORECASE,
)

# Lift & İstasyon Durumu Regex'i
_LIFT_STATUS_RE = re.compile(
    r"\b(lift|istasyon)\w*\b.*\b(durum\w*|doluluk\w*|müsait\w*|boş\w*|kapasite\w*|yer\s+var\s+mı)\b|"
    r"\b(boş\s+(?:lift|istasyon|yer)|liftler\s+dolu)\b",
    re.IGNORECASE,
)

# OBD-II DTC Kod Regex'i: P0300, C1234, B0001, U0100 vb.
_DTC_CODE_RE = re.compile(r"\b([PCBU][0-3]\d{3})\b", re.IGNORECASE)

# WhatsApp Rapor Gönderimi Regex'i
_WHATSAPP_REPORT_RE = re.compile(
    r"\b(whatsapp|whatsap|vatsap)\b.*\b(rapor|gönder|at|ilet|paylaş)\b|"
    r"\b(rapor(?:umu|umuzu)?\s*(?:whatsapp|whatsap|vatsap)(?:'tan|tan|'dan|dan| ile)?\s*(?:gönder|at|ilet|paylaş))\b",
    re.IGNORECASE,
)

# Teknisyen Dikte Belirteçleri
_DICTATION_KEYWORDS = (
    "mikron", "boyalı", "değişen", "lokal boya", "macun", "çamurluk",
    "kaput", "tavan", "bagaj", "podye", "şasi", "direk", "far ayağı",
    "kasa", "panel", "kaporta",
)

# Araç Değerleme Belirteçleri (Fiyat sorgusunu araç değerlemeden ayırmak için)
_VALUATION_KEYWORDS = (
    "değerleme", "piyasa değeri", "aracım ne kadar eder", "kaç para eder",
    "değeri nedir", "satmak istiyorum", "ikinci el değeri",
)


def dispatch_emergency(text: str) -> Optional[Dict[str, Any]]:
    """M01-M11 Can Güvenliği ve Acil Durum Kontrolü."""
    if not text:
        return None
    clean = text.strip()
    if _EMERGENCY_RE.search(clean) or ("fren" in clean.lower() and ("tutmuyor" in clean.lower() or "boşaldı" in clean.lower())) or ("kaza" in clean.lower() and "yapacağım" in clean.lower()):
        return {
            "intent": "roadside_emergency",
            "message": (
                "Acil durum uyarısı: Can güvenliğiniz için lütfen aracınızı derhal emniyetli bir alanda durdurun "
                "ve dörtlü flaşörlerinizi yakın. Sizi hemen acil yol yardım ve çekici ekibimize aktarıyorum."
            ),
            "transfer_required": True,
        }
    return None


def dispatch_lift_status(text: str, db=None) -> Optional[Dict[str, Any]]:
    """Ekspertiz lifti ve muayene istasyonu anlık kapasite durumu kontrolü."""
    if not text:
        return None
    if _LIFT_STATUS_RE.search(text) or ("lift" in text.lower() and any(w in text.lower() for w in ("durum", "müsait", "boş", "kapasite"))):
        close_db = False
        if db is None:
            db = Session()
            close_db = True
        try:
            status = get_lift_capacity_status(db)
            return {
                "intent": "lift_durumu",
                "message": status["spoken_message"],
                "data": status,
            }
        finally:
            if close_db:
                db.close()
    return None


def dispatch_obd_dtc(text: str) -> Optional[Dict[str, Any]]:
    """OBD-II DTC Arıza Kodu ve Ontolojik Semptom Teşhisi."""
    if not text:
        return None
    dtc_match = _DTC_CODE_RE.search(text)
    if dtc_match:
        code = dtc_match.group(1).upper()
        lookup = lookup_dtc(code)
        msg = (
            f"{lookup['dtc_code']} arıza kodu: {lookup['description_tr']}. "
            f"Sistem: {lookup['system_category']}, ciddiyet: {lookup['severity']}. "
            f"Önerilen işlem: {lookup['recommended_action']}"
        )
        return {
            "intent": "obd_dtc_ariza",
            "message": msg,
            "data": lookup,
        }

    # Belirti bazlı semptom sorgusu
    lowered = text.lower()
    if any(kw in lowered for kw in ("arıza lambası", "arıza kodu", "ikaz ışığı", "motor ışığı", "hararet", "tekleme")):
        faults = AutomotiveGroundingEngine.diagnose_symptom(text)
        if faults:
            f = faults[0]
            symptoms = ", ".join(f.common_symptoms[:2]) if getattr(f, "common_symptoms", None) else "Genel arıza"
            action = getattr(f, "suggested_action", "Yetkili servise danışınız.")
            msg = (
                f"Belirttiğiniz semptom için teşhis: {f.obd_code} - {f.description}. "
                f"Sistem: {f.system}, belirtiler: {symptoms}. Tavsiye: {action}"
            )
            return {
                "intent": "obd_dtc_ariza",
                "message": msg,
                "data": {"obd_code": f.obd_code, "description": f.description},
            }
    return None


def dispatch_technician_dictation(text: str) -> Optional[Dict[str, Any]]:
    """Teknisyen sesli diktesini yapılandırılmış ekspertiz bulgularına dönüştürür."""
    if not text:
        return None
    lowered = text.lower()
    # Dikte veya mikron/panel anahtar kelimeleri kontrolü
    has_keyword = any(kw in lowered for kw in _DICTATION_KEYWORDS)
    has_micron = bool(re.search(r"\b\d{2,4}\s*(?:mikron|um)?\b", lowered))

    if has_keyword and (has_micron or any(w in lowered for w in ("boyalı", "değişen", "orijinal", "lokal"))):
        parsed = parse_technician_dictation(text)
        if parsed.get("extracted_entities"):
            score = parsed.get("calculated_score")
            score_txt = f" (Hesaplanan Ekspertiz Puanı: {score}/100)" if score is not None else ""
            msg = f"Teknisyen diktesi kaydedildi: {parsed['generated_summary']}{score_txt}"
            return {
                "intent": "teknisyen_dikte",
                "message": msg,
                "data": parsed,
            }
    return None


def dispatch_whatsapp_report(
    text: str,
    phone: str = "",
    plate: str = "",
    customer: str = "",
    db=None,
) -> Optional[Dict[str, Any]]:
    """WhatsApp üzerinden dijital ekspertiz raporu gönderimini sevk eder."""
    if not text:
        return None
    if _WHATSAPP_REPORT_RE.search(text) or ("whatsapp" in text.lower() and "rapor" in text.lower()):
        target_phone = phone.strip()
        target_plate = plate.strip() or "aracınıza"
        target_cust = customer.strip() or "müşterimiz"

        if target_phone:
            # Bildirim kuyruğuna al
            if db is not None:
                try:
                    from backend.notifications import NotificationOutbox
                    from backend.db import uid, now
                    outbox_entry = NotificationOutbox(
                        id=uid(),
                        channel="whatsapp",
                        recipient=target_phone,
                        template_name="inspection_report_delivery",
                        payload_json=f'{{"plate": "{target_plate}", "customer": "{target_cust}"}}',
                        status="queued",
                        created_at=now(),
                    )
                    db.add(outbox_entry)
                    db.flush()
                except Exception:
                    logger.warning("WhatsApp bildirim outbox ekleme atlandı", exc_info=True)

            msg = (
                f"Sayın {target_cust}, {target_plate} ait ekspertiz raporunuz "
                f"WhatsApp üzerinden {target_phone} numaralı hattınıza iletilmek üzere sıraya alındı."
            )
            return {
                "intent": "whatsapp_rapor",
                "message": msg,
                "data": {"phone": target_phone, "plate": target_plate},
            }
        else:
            msg = "Ekspertiz raporunuzu WhatsApp üzerinden iletebilmemiz için lütfen cep telefonu numaranızı söyler misiniz?"
            return {
                "intent": "whatsapp_rapor",
                "message": msg,
                "data": {"missing": "phone"},
            }
    return None


def dispatch_valuation_or_pricing(text: str) -> Optional[Dict[str, Any]]:
    """Dinamik araç piyasa değerleme veya servis paketi fiyatlandırmasını ayırır ve sevk eder."""
    if not text:
        return None
    lowered = text.lower()

    # Araç değerleme sorgusu mu? (örneğin "Passat fiyatı ne kadar?", "2020 Passat ne kadar eder?", "aracımın değeri nedir?")
    is_valuation = any(kw in lowered for kw in _VALUATION_KEYWORDS) or (
        ("fiyat" in lowered or "kaç para" in lowered or "ne kadar" in lowered or "eder" in lowered)
        and any(brand.lower() in lowered for brand in ("passat", "golf", "clio", "megane", "corolla", "egea", "focus", "peugeot", "3008", "civic", "bmw", "mercedes", "audi", "volkswagen", "renault", "toyota", "fiat"))
    )

    if is_valuation:
        parsed_q = parse_spoken_valuation_query(text)
        brand = parsed_q.get("brand")
        model = parsed_q.get("model")
        year = parsed_q.get("model_year") or 2020
        km = parsed_q.get("mileage_km") or 100000

        if brand and model:
            val = calculate_dynamic_valuation(
                brand=brand,
                model=model,
                model_year=year,
                mileage_km=km,
                body_panels=parsed_q.get("body_panels", {}),
                tramer_amount_tl=parsed_q.get("tramer_amount_tl", 0.0),
                is_heavy_damage=parsed_q.get("is_heavy_damage", False),
            )
            est = f"{val.estimated_market_value_tl:,.0f}".replace(",", ".")
            min_p = f"{val.valuation_range_min_tl:,.0f}".replace(",", ".")
            max_p = f"{val.valuation_range_max_tl:,.0f}".replace(",", ".")
            msg = (
                f"{val.brand} {val.model} ({val.model_year}) aracınızın tahmini piyasa değeri "
                f"{est} TL'dir (Beklenen aralık: {min_p} - {max_p} TL). "
                f"Detaylı ekspertiz ve kesin değerleme randevusu oluşturmak ister misiniz?"
            )
            return {
                "intent": "fiyat_parca_sorgusu",
                "sub_type": "vehicle_valuation",
                "message": msg,
                "data": {
                    "brand": val.brand,
                    "model": val.model,
                    "estimated_value_tl": val.estimated_market_value_tl,
                    "price_range": {"min_tl": val.valuation_range_min_tl, "max_tl": val.valuation_range_max_tl},
                },
            }
        elif any(kw in lowered for kw in _VALUATION_KEYWORDS):
            msg = "Aracınızın güncel piyasa değerini hesaplayabilmem için marka, model, yıl ve yaklaşık kilometresini söyler misiniz?"
            return {
                "intent": "fiyat_parca_sorgusu",
                "sub_type": "vehicle_valuation",
                "message": msg,
                "data": {"missing": "vehicle_info"},
            }

    # Paket Fiyat Sorgusu
    if any(w in lowered for w in ("fiyat", "ücret", "kaç para", "ne kadar", "paket")):
        matched_pkg = None
        for k, p in queue_lift.PACKAGE_DEFINITIONS.items():
            if any(kw in lowered for kw in p.get("keywords", [])):
                matched_pkg = p
                break
        if matched_pkg:
            price_tl = f"{matched_pkg['base_price_kurus'] // 100:,}".replace(",", ".")
            msg = (
                f"{matched_pkg['name']} paketimiz {price_tl} TL'dir. "
                f"Yaklaşık {matched_pkg['duration_minutes']} dakika sürer ve {matched_pkg['description']} "
                f"Bu paket için randevu oluşturmak ister misiniz?"
            )
            return {
                "intent": "fiyat_parca_sorgusu",
                "sub_type": "service_packages",
                "message": msg,
                "data": {"package": matched_pkg["key"], "price": price_tl},
            }
        else:
            msg = (
                "Ekspertiz merkezimizde 4 ana paketimiz bulunmaktadır: "
                "Motor ve Mekanik 950 TL, Standart Ekspertiz 1.450 TL, Full Kapsamlı 1.950 TL ve VIP Premium 2.600 TL'dir. "
                "Hangi paketimiz için randevu oluşturmak istersiniz?"
            )
            return {
                "intent": "fiyat_parca_sorgusu",
                "sub_type": "service_packages",
                "message": msg,
                "data": {"packages": list(queue_lift.PACKAGE_DEFINITIONS.keys())},
            }

    return None
