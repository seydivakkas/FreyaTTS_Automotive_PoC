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

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.db import (
    Appointment,
    CallAnalytics,
    Conversation,
    Turn,
    Vehicle,
    now,
)

logger = logging.getLogger("post_call_analytics")

# Olumlu ve Olumsuz Türkçe Anahtar Sözcük Havuzu
POSITIVE_CUES = [
    "harika", "süper", "çok iyi", "mükemmel", "teşekkür", "sağol",
    "anlaştık", "tamamdır", "uygun", "memnun", "olur", "gelirim",
    "sevindim", "onaylıyorum", "tabii", "evet", "kolay gelsin", "kusursuz"
]

NEGATIVE_CUES = [
    "pahalı", "çok pahalı", "fazla", "berbat", "rezalet", "şikayet",
    "kötü", "zaman kaybı", "vaktim yok", "gelemem", "istemiyorum",
    "vazgeçtim", "iptal", "yanlış", "beğenmedim", "yetkili", "kızgın",
    "bekletildim", "güvenmiyorum", "dolandırıcı"
]

# İtiraz Kategorileri
OBJECTION_PATTERNS = {
    "fiyat_yuksek": re.compile(
        r"\b(pahalı(?:ymış|dır)?|fiyat[ıi]?\s*(?:(?:biraz|çok|fazla)\s*)?(?:yüksek|pahalı|fazla)|yüksek(?:miş|tir)?|bütçemi?\s*aşıyor|indirim|indirim\s*yok\s*mu|daha\s*uygun)\b",
        re.IGNORECASE,
    ),
    "zaman_uyusmuyor": re.compile(
        r"\b(o\s*saat\s*olmaz|uymaz|geç|erken|başka\s*saat|hafta\s*sonu\s*yok\s*mu|mesai|işim\s*var|vaktim\s*yok)\b",
        re.IGNORECASE,
    ),
    "konum_uzak": re.compile(
        r"\b(uzak|mesafe|ters|başka\s*şube|şubeniz\s*nerede|oraya\s*gelemem|yol\s*uzak)\b",
        re.IGNORECASE,
    ),
    "kararsiz_erteleyen": re.compile(
        r"\b(düşüneyim|bakayım|kararsızım|emin\s*değilim|döneceğim|sonra\s*ararım|arkadaşa\s*sorayım|eşimle\s*konuşayım)\b",
        re.IGNORECASE,
    ),
    "rakip_karsilastirmasi": re.compile(
        r"\b(diğer\s*yer|başka\s*firma|tuvtürk|tüvtürk|tarcanlar|pilot\s*garage|otopoint|daha\s*ucuzdu)\b",
        re.IGNORECASE,
    ),
}

# Konu Başlığı Anahtarları
TOPIC_PATTERNS = {
    "ekspertiz_paketi": re.compile(r"\b(paket|full|kapsamlı|vip|motor|mekanik|standart)\b", re.IGNORECASE),
    "fiyat_ve_odeme": re.compile(r"\b(fiyat|ücret|tutar|tl|lira|nakit|kredi\s*kartı|cari)\b", re.IGNORECASE),
    "randevu_saati": re.compile(r"\b(saat|gün|tarih|yarın|pazartesi|salı|çarşamba|perşembe|cuma|cumartesi)\b", re.IGNORECASE),
    "kaporta_boya": re.compile(r"\b(boya|değişen|kaporta|çamurluk|tavan|kaput|mikron)\b", re.IGNORECASE),
    "motor_mekanik": re.compile(r"\b(motor|şanzıman|dyno|fren|alt\s*takım|arıza|obd)\b", re.IGNORECASE),
    "adres_konum": re.compile(r"\b(adres|şube|nerede|konum|harita|yol\s*tarifi)\b", re.IGNORECASE),
    "rapor_teslimati": re.compile(r"\b(rapor|pdf|whatsapp|sms|çıkış|sonuç)\b", re.IGNORECASE),
}


def parse_transcript_turns(raw_transcript: Union[List[Dict[str, Any]], str]) -> List[Dict[str, str]]:
    """
    Farklı formatlardaki transkriptleri normalize ederek [{role, text}] listesine dönüştürür.
    """
    if isinstance(raw_transcript, list):
        normalized = []
        for item in raw_transcript:
            if isinstance(item, dict):
                role = str(item.get("role", "customer")).lower()
                text = str(item.get("text", "")).strip()
                if text:
                    normalized.append({"role": role, "text": text})
            elif isinstance(item, str) and item.strip():
                normalized.append({"role": "customer", "text": item.strip()})
        return normalized

    if isinstance(raw_transcript, str):
        lines = [line.strip() for line in raw_transcript.strip().splitlines() if line.strip()]
        normalized = []
        for line in lines:
            if line.startswith("Müşteri:") or line.startswith("User:"):
                text = re.sub(r"^(Müşteri|User):\s*", "", line, flags=re.IGNORECASE)
                normalized.append({"role": "customer", "text": text})
            elif line.startswith("Asistan:") or line.startswith("Assistant:"):
                text = re.sub(r"^(Asistan|Assistant):\s*", "", line, flags=re.IGNORECASE)
                normalized.append({"role": "assistant", "text": text})
            else:
                normalized.append({"role": "customer", "text": line})
        return normalized

    return []


def detect_call_intent(turns: List[Dict[str, str]]) -> str:
    """
    Konuşma transkriptinden ana çağrı niyetini çıkarır.
    Olası niyetler:
    - 'appointment_booking' (Randevu oluşturma)
    - 'reschedule_or_cancel' (Randevu saati değiştirme veya iptal)
    - 'price_inquiry' (Fiyat ve paket sorma)
    - 'report_inquiry' (Ekspertiz rapor durumu sorma)
    - 'technical_complaint' (Teknik itiraz veya şikayet)
    - 'operator_transfer' (Yetkili veya canlı temsilci talebi)
    - 'general_inquiry' (Genel soru / adres / bilgi)
    """
    combined_user_text = " ".join(
        t["text"] for t in turns if t["role"] in ("customer", "user", "client")
    ).lower()

    if not combined_user_text:
        # Asistan tarafını da dahil et
        combined_user_text = " ".join(t["text"] for t in turns).lower()

    if re.search(r"\b(operatör|yetkili|temsilci|bağla|bağlar\s*mısınız|insanla\s*görüşmek)\b", combined_user_text):
        return "operator_transfer"
    if re.search(r"\b(iptal|saati\s*(?:değiştir|kaydır|alalım)|ertelemek|gelemeyeceğim)\b", combined_user_text):
        return "reschedule_or_cancel"
    if re.search(r"\b(şikayet|rezalet|memnun\s*değilim|yanlış\s*yazılmış|sorun\s*var|hatalı)\b", combined_user_text):
        return "technical_complaint"
    if re.search(r"\b(rapor|raporum|sonuç|pdf|hazır\s*mı|bitti\s*mi)\b", combined_user_text):
        return "report_inquiry"
    if re.search(r"\b(randevu|almak\s*istiyorum|ekspertiz\s*yaptır|saat|gün|uygun\s*mu)\b", combined_user_text):
        return "appointment_booking"
    if re.search(r"\b(ne\s*kadar|fiyat|kaç\s*para|ücret|tarife|paketler|pahalı)\b", combined_user_text):
        return "price_inquiry"

    return "general_inquiry"


def compute_sentiment_and_csat(turns: List[Dict[str, str]]) -> Tuple[str, float]:
    """
    Türkçe transkript üzerinden duygu durumu ('positive', 'neutral', 'negative')
    ve CSAT müşteri memnuniyet skorunu (1.0 - 5.0) hesaplar.
    """
    customer_texts = [
        t["text"].lower()
        for t in turns
        if t["role"] in ("customer", "user", "client")
    ]
    if not customer_texts:
        customer_texts = [t["text"].lower() for t in turns]

    if not customer_texts:
        return "neutral", 3.0

    pos_score = 0
    neg_score = 0

    for text in customer_texts:
        for cue in POSITIVE_CUES:
            if cue in text:
                pos_score += 1
        for cue in NEGATIVE_CUES:
            if cue in text:
                neg_score += 1

    # Son cümlenin duygusuna ek ağırlık (çağrı kapanış memnuniyeti)
    if customer_texts:
        last_text = customer_texts[-1]
        for cue in POSITIVE_CUES:
            if cue in last_text:
                pos_score += 1.5
        for cue in NEGATIVE_CUES:
            if cue in last_text:
                neg_score += 1.5

    delta = pos_score - neg_score

    # CSAT 1.0 - 5.0 ölçeği
    csat = 3.0 + (delta * 0.5)
    csat = max(1.0, min(5.0, round(csat, 1)))

    if delta > 1:
        sentiment = "positive"
    elif delta < -1:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    return sentiment, csat


def extract_objections_and_topics(turns: List[Dict[str, str]]) -> Tuple[List[str], List[str]]:
    """
    Müşterinin dile getirdiği itirazları ve konuşulan konu başlıklarını listeler.
    """
    combined_text = " ".join(t["text"] for t in turns)

    objections = []
    for key, pattern in OBJECTION_PATTERNS.items():
        if pattern.search(combined_text):
            objections.append(key)

    topics = []
    for key, pattern in TOPIC_PATTERNS.items():
        if pattern.search(combined_text):
            topics.append(key)

    return objections, topics


def calculate_lead_score(
    intent: str,
    sentiment: str,
    objections: List[str],
    turns_count: int,
    confirmed: bool,
    has_vehicle_info: bool,
) -> Tuple[int, str]:
    """
    Müşterinin satışa / randevuya dönüşme olasılığını (Lead Score 0-100)
    ve Lead Segmentini ('HOT', 'WARM', 'COLD') hesaplar.
    """
    score = 40

    if confirmed:
        score += 35
    elif intent == "appointment_booking":
        score += 15

    if has_vehicle_info:
        score += 15

    if sentiment == "positive":
        score += 15
    elif sentiment == "negative":
        score -= 20

    if turns_count >= 3:
        score += 10

    if objections:
        # İtiraz sayısına göre ceza
        score -= min(30, len(objections) * 12)

    score = max(0, min(100, score))

    if score >= 75:
        tier = "HOT"
    elif score >= 45:
        tier = "WARM"
    else:
        tier = "COLD"

    return score, tier


def generate_executive_summary(
    intent: str,
    sentiment: str,
    objections: List[str],
    topics: List[str],
    confirmed: bool,
    caller_phone: str = "",
    turns: Optional[List[Dict[str, str]]] = None,
) -> Tuple[str, str]:
    """
    Türkçe yönetici özeti ve önerilen sonraki aksiyonu üretir.
    """
    summary_parts = []
    
    intent_desc = {
        "appointment_booking": "ekspertiz randevusu oluşturma talebiyle aradı",
        "reschedule_or_cancel": "mevcut randevu saatini değiştirme / iptal talebinde bulundu",
        "price_inquiry": "paket fiyatları ve muayene ücretleri hakkında bilgi aldı",
        "report_inquiry": "tamamlanan ekspertiz raporunun durumunu sorguladı",
        "technical_complaint": "önceki işlem veya raporla ilgili itirazını / şikayetini iletti",
        "operator_transfer": "canlı bir uzman veya şube yetkilisiyle görüşmek istedi",
        "general_inquiry": "şube konumu ve çalışma saatleri hakkında genel bilgi sordu",
    }.get(intent, "genel bilgi almak için aradı")

    summary_parts.append(f"Müşteri {intent_desc}.")

    if confirmed:
        summary_parts.append("Randevu saati başarıyla onaylandı ve sisteme işlendi.")
    elif intent == "appointment_booking":
        summary_parts.append("Görüşme esnasında randevu teyidi henüz kesinleşmedi.")

    if objections:
        obj_names = {
            "fiyat_yuksek": "fiyatın yüksek olması",
            "zaman_uyusmuyor": "sunulan saat diliminin uymaması",
            "konum_uzak": "şube mesafesi",
            "kararsiz_erteleyen": "müşterinin kararsız kalması",
            "rakip_karsilastirmasi": "rakip fiyat karşılaştırması",
        }
        obj_str = ", ".join(obj_names.get(o, o) for o in objections)
        summary_parts.append(f"Müşteri tarafından belirtilen başlıca itirazlar: {obj_str}.")

    sentiment_desc = {
        "positive": "Görüşme oldukça pozitif bir tonla tamamlandı.",
        "neutral": "Görüşme standart ve yapıcı bir tonda geçti.",
        "negative": "Görüşme süresince müşteri memnuniyetsizliği gözlemlendi.",
    }.get(sentiment, "")
    if sentiment_desc:
        summary_parts.append(sentiment_desc)

    executive_summary = " ".join(summary_parts)

    # Önerilen Aksiyon
    if confirmed:
        recommended_action = (
            "Randevu onaylandı. Randevudan 2 saat önce şube GPS konum pini ile SMS/WhatsApp hatırlatması gönderilecek."
        )
    elif "fiyat_yuksek" in objections:
        recommended_action = (
            "Müşteri fiyatı yüksek buldu. Satış temsilcisi 1 saat içinde %10 kurumsal indirim veya kampanya teklifi ile arasın."
        )
    elif "kararsiz_erteleyen" in objections or intent == "price_inquiry":
        recommended_action = (
            "Müşteri kararsız kaldı. 24 saat sonra WhatsApp üzerinden ekspertiz paket karşılaştırma broşürü iletilsin."
        )
    elif sentiment == "negative" or intent == "technical_complaint":
        recommended_action = (
            "Müşteri memnuniyetsizliği mevcut. Şube müdürü veya müşteri ilişkileri yöneticisi 30 dakika içinde doğrudan aramalı."
        )
    elif intent == "operator_transfer":
        recommended_action = (
            "Operatöre aktarım talep edildi. Uzman teknisyen çağrı geçmişini ve fısıltı notunu inceleyerek geri dönüş yapmalı."
        )
    else:
        recommended_action = "Standart takip sürecinde tutulsun; ek bir manuel müdahale gerekmemektedir."

    return executive_summary, recommended_action


def analyze_conversation_transcript(
    raw_transcript: Union[List[Dict[str, Any]], str],
    caller_phone: str = "",
    caller_name: str = "",
    appointment_id: Optional[str] = None,
    duration_sec: Optional[float] = None,
    confirmed: bool = False,
    vehicle_info_present: bool = False,
) -> Dict[str, Any]:
    """
    Transkripti analiz eder, niyet, duygu (CSAT), itirazlar, lead skoru ve
    yönetici özetini içeren zengin analitik sözlüğünü döndürür.
    """
    turns = parse_transcript_turns(raw_transcript)
    turns_count = len(turns)

    # Otomatik onay kontrolü: transkriptte onay sözcükleri var mı
    all_text = " ".join(t["text"] for t in turns).lower()
    if not confirmed:
        if re.search(r"\b(randevunuz\s*oluşturuldu|onaylandı|kaydettim|saat\s*.*için\s*bekliyoruz)\b", all_text):
            confirmed = True

    # Otomatik araç bilgisi kontrolü
    if not vehicle_info_present:
        if re.search(r"\b(\d{2}\s*[a-z]{1,3}\s*\d{2,4}|[a-hj-npr-z0-9]{17}|golf|passat|clio|megane|egea|focus)\b", all_text):
            vehicle_info_present = True

    intent = detect_call_intent(turns)
    sentiment, csat = compute_sentiment_and_csat(turns)
    objections, topics = extract_objections_and_topics(turns)
    lead_score, lead_tier = calculate_lead_score(
        intent=intent,
        sentiment=sentiment,
        objections=objections,
        turns_count=turns_count,
        confirmed=confirmed,
        has_vehicle_info=vehicle_info_present,
    )
    summary, action = generate_executive_summary(
        intent=intent,
        sentiment=sentiment,
        objections=objections,
        topics=topics,
        confirmed=confirmed,
        caller_phone=caller_phone,
        turns=turns,
    )

    return {
        "caller_phone": caller_phone,
        "caller_name": caller_name,
        "appointment_id": appointment_id,
        "executive_summary": summary,
        "intent": intent,
        "csat_score": csat,
        "sentiment": sentiment,
        "lead_score": lead_score,
        "lead_tier": lead_tier,
        "objections": objections,
        "topics": topics,
        "recommended_action": action,
        "duration_sec": duration_sec,
        "turns_count": turns_count,
        "confirmed": confirmed,
    }


def evaluate_and_save_call_analytics(
    db: Session,
    *,
    conversation_id: str,
    appointment_id: Optional[str] = None,
    caller_phone: str = "",
    caller_name: str = "",
    duration_sec: Optional[float] = None,
    transcript_override: Optional[Union[List[Dict[str, Any]], str]] = None,
) -> CallAnalytics:
    """
    Veritabanındaki diyalog geçmişini veya verilen transkripti analiz ederek
    `call_analytics` tablosuna atomik olarak kaydeder veya günceller.
    """
    conv = db.get(Conversation, conversation_id)
    if not conv and not transcript_override:
        raise ValueError(f"Görüşme bulunamadı: {conversation_id}")

    turns_data: List[Dict[str, Any]] = []
    if transcript_override is not None:
        turns_data = parse_transcript_turns(transcript_override)
    else:
        # DB'den turn kayıtlarını çek
        db_turns = (
            db.execute(
                select(Turn)
                .where(Turn.conversation_id == conversation_id)
                .order_by(Turn.created_at)
            )
            .scalars()
            .all()
        )
        for t in db_turns:
            turns_data.append({"role": t.role, "text": t.text})

    # Randevu ve araç kontrolü
    confirmed = False
    vehicle_info_present = False
    app = None
    if appointment_id:
        app = db.get(Appointment, appointment_id)
    elif conv:
        # Arama yaparken ilişkili randevuyu bulmaya çalış
        app = (
            db.execute(
                select(Appointment)
                .where(Appointment.customer.ilike(f"%{conv.id[:8]}%"))
            )
            .scalars()
            .first()
        )

    if app:
        appointment_id = app.id
        confirmed = app.confirmed
        if not caller_name:
            caller_name = app.customer
        if app.vehicle_id:
            vehicle_info_present = True

    analyzed = analyze_conversation_transcript(
        raw_transcript=turns_data,
        caller_phone=caller_phone,
        caller_name=caller_name,
        appointment_id=appointment_id,
        duration_sec=duration_sec,
        confirmed=confirmed,
        vehicle_info_present=vehicle_info_present,
    )

    # Mevcut analitik kaydı var mı kontrol et
    existing = (
        db.execute(
            select(CallAnalytics).where(CallAnalytics.conversation_id == conversation_id)
        )
        .scalars()
        .first()
    )

    if existing:
        existing.appointment_id = analyzed["appointment_id"]
        existing.caller_phone = analyzed["caller_phone"] or existing.caller_phone
        existing.caller_name = analyzed["caller_name"] or existing.caller_name
        existing.executive_summary = analyzed["executive_summary"]
        existing.intent = analyzed["intent"]
        existing.csat_score = analyzed["csat_score"]
        existing.sentiment = analyzed["sentiment"]
        existing.lead_score = analyzed["lead_score"]
        existing.lead_tier = analyzed["lead_tier"]
        existing.objections_json = json.dumps(analyzed["objections"], ensure_ascii=False)
        existing.topics_json = json.dumps(analyzed["topics"], ensure_ascii=False)
        existing.recommended_action = analyzed["recommended_action"]
        if duration_sec is not None:
            existing.duration_sec = duration_sec
        record = existing
    else:
        record = CallAnalytics(
            id=f"ca-{uuid4().hex[:12]}",
            conversation_id=conversation_id,
            appointment_id=analyzed["appointment_id"],
            caller_phone=analyzed["caller_phone"],
            caller_name=analyzed["caller_name"],
            executive_summary=analyzed["executive_summary"],
            intent=analyzed["intent"],
            csat_score=analyzed["csat_score"],
            sentiment=analyzed["sentiment"],
            lead_score=analyzed["lead_score"],
            lead_tier=analyzed["lead_tier"],
            objections_json=json.dumps(analyzed["objections"], ensure_ascii=False),
            topics_json=json.dumps(analyzed["topics"], ensure_ascii=False),
            recommended_action=analyzed["recommended_action"],
            duration_sec=duration_sec,
            created_at=now(),
        )
        db.add(record)

    db.commit()
    db.refresh(record)
    return record


def get_analytics_summary_stats(db: Session) -> Dict[str, Any]:
    """
    Yönetim paneli ve KPI raporları için çağrı analitik istatistiklerini hesaplar.
    """
    total_calls = db.scalar(select(func.count(CallAnalytics.id))) or 0
    if total_calls == 0:
        return {
            "total_analyzed_calls": 0,
            "average_csat": 0.0,
            "average_lead_score": 0.0,
            "lead_tier_distribution": {"HOT": 0, "WARM": 0, "COLD": 0},
            "sentiment_distribution": {"positive": 0, "neutral": 0, "negative": 0},
            "top_intents": [],
            "top_objections": [],
        }

    avg_csat = db.scalar(select(func.avg(CallAnalytics.csat_score))) or 0.0
    avg_lead = db.scalar(select(func.avg(CallAnalytics.lead_score))) or 0.0

    # Tier Dağılımı
    hot_count = db.scalar(
        select(func.count(CallAnalytics.id)).where(CallAnalytics.lead_tier == "HOT")
    ) or 0
    warm_count = db.scalar(
        select(func.count(CallAnalytics.id)).where(CallAnalytics.lead_tier == "WARM")
    ) or 0
    cold_count = db.scalar(
        select(func.count(CallAnalytics.id)).where(CallAnalytics.lead_tier == "COLD")
    ) or 0

    # Sentiment Dağılımı
    pos_count = db.scalar(
        select(func.count(CallAnalytics.id)).where(CallAnalytics.sentiment == "positive")
    ) or 0
    neu_count = db.scalar(
        select(func.count(CallAnalytics.id)).where(CallAnalytics.sentiment == "neutral")
    ) or 0
    neg_count = db.scalar(
        select(func.count(CallAnalytics.id)).where(CallAnalytics.sentiment == "negative")
    ) or 0

    # Niyet Dağılımı (Top 5)
    intent_rows = (
        db.execute(
            select(CallAnalytics.intent, func.count(CallAnalytics.id))
            .group_by(CallAnalytics.intent)
            .order_by(desc(func.count(CallAnalytics.id)))
            .limit(5)
        )
        .all()
    )
    top_intents = [{"intent": r[0], "count": r[1]} for r in intent_rows]

    # İtirazları say
    all_objs_rows = db.execute(select(CallAnalytics.objections_json)).scalars().all()
    obj_counts: Dict[str, int] = {}
    for obj_str in all_objs_rows:
        try:
            objs = json.loads(obj_str or "[]")
            for o in objs:
                obj_counts[o] = obj_counts.get(o, 0) + 1
        except Exception:
            pass

    sorted_objs = sorted(obj_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_objections = [{"objection": k, "count": v} for k, v in sorted_objs]

    return {
        "total_analyzed_calls": total_calls,
        "average_csat": round(float(avg_csat), 2),
        "average_lead_score": round(float(avg_lead), 1),
        "lead_tier_distribution": {
            "HOT": hot_count,
            "WARM": warm_count,
            "COLD": cold_count,
        },
        "sentiment_distribution": {
            "positive": pos_count,
            "neutral": neu_count,
            "negative": neg_count,
        },
        "top_intents": top_intents,
        "top_objections": top_objections,
    }
