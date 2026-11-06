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

import json
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from backend.db import Conversation, Turn, Appointment, Slot, Vehicle, Session, CallAnalytics
from backend.main import app
from backend.post_call_analytics import (
    analyze_conversation_transcript,
    calculate_lead_score,
    compute_sentiment_and_csat,
    detect_call_intent,
    evaluate_and_save_call_analytics,
    extract_objections_and_topics,
    generate_executive_summary,
    get_analytics_summary_stats,
    parse_transcript_turns,
)


def uid():
    return uuid4().hex


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(monkeypatch):
    import base64
    from backend.config import settings
    monkeypatch.setattr(settings, "admin_password", "secret")
    creds = base64.b64encode(b"admin:secret").decode("ascii")
    return {"Authorization": f"Basic {creds}"}


def test_transcript_parsing():
    raw_str = (
        "Müşteri: Merhaba yarın saat iki için ekspertiz randevusu almak istiyorum.\n"
        "Asistan: Tabii ki 34 ABC 123 plakalı aracınız için saat 14:00 uygundur.\n"
        "Müşteri: Harika, teşekkürler."
    )
    turns = parse_transcript_turns(raw_str)
    assert len(turns) == 3
    assert turns[0]["role"] == "customer"
    assert "randevu" in turns[0]["text"]
    assert turns[1]["role"] == "assistant"
    assert turns[2]["role"] == "customer"


def test_detect_call_intent():
    turns_booking = [
        {"role": "customer", "text": "Yarın saat 14:00 için ekspertiz randevusu almak istiyorum."}
    ]
    assert detect_call_intent(turns_booking) == "appointment_booking"

    turns_price = [
        {"role": "customer", "text": "Full kapsamlı paket ücreti ne kadar, fiyat bilgisi alabilir miyim?"}
    ]
    assert detect_call_intent(turns_price) == "price_inquiry"

    turns_cancel = [
        {"role": "customer", "text": "Randevumu iptal etmek istiyorum gelemeyeceğim."}
    ]
    assert detect_call_intent(turns_cancel) == "reschedule_or_cancel"

    turns_complaint = [
        {"role": "customer", "text": "Dün yapılan ekspertizde boya bilgisi hatalı yazılmış, şikayetçiyim."}
    ]
    assert detect_call_intent(turns_complaint) == "technical_complaint"

    turns_transfer = [
        {"role": "customer", "text": "Beni bir canlı operatöre bağlar mısınız?"}
    ]
    assert detect_call_intent(turns_transfer) == "operator_transfer"


def test_sentiment_and_csat():
    pos_turns = [
        {"role": "customer", "text": "Harika çok teşekkürler, sisteminiz çok iyi çalışıyor süper."}
    ]
    sentiment, csat = compute_sentiment_and_csat(pos_turns)
    assert sentiment == "positive"
    assert csat >= 4.0

    neg_turns = [
        {"role": "customer", "text": "Fiyatlar çok pahalı, berbat bir hizmet, rezalet."}
    ]
    sentiment, csat = compute_sentiment_and_csat(neg_turns)
    assert sentiment == "negative"
    assert csat <= 2.5

    neutral_turns = [
        {"role": "customer", "text": "Saat 15:00 dediniz, adres neresiydi?"}
    ]
    sentiment, csat = compute_sentiment_and_csat(neutral_turns)
    assert sentiment == "neutral"
    assert 2.8 <= csat <= 3.5


def test_objections_and_lead_scoring():
    turns_objection = [
        {"role": "customer", "text": "3000 TL çok pahalı geldi, biraz düşüneyim başka firma daha ucuzdu."}
    ]
    objections, topics = extract_objections_and_topics(turns_objection)
    assert "fiyat_yuksek" in objections
    assert "kararsiz_erteleyen" in objections
    assert "rakip_karsilastirmasi" in objections
    assert "fiyat_ve_odeme" in topics

    # Score calculation
    score, tier = calculate_lead_score(
        intent="price_inquiry",
        sentiment="negative",
        objections=objections,
        turns_count=2,
        confirmed=False,
        has_vehicle_info=False,
    )
    assert tier == "COLD"
    assert score < 45

    # Hot lead
    hot_score, hot_tier = calculate_lead_score(
        intent="appointment_booking",
        sentiment="positive",
        objections=[],
        turns_count=5,
        confirmed=True,
        has_vehicle_info=True,
    )
    assert hot_tier == "HOT"
    assert hot_score >= 75


def test_executive_summary_and_action():
    summary, action = generate_executive_summary(
        intent="appointment_booking",
        sentiment="positive",
        objections=[],
        topics=["randevu_saati", "ekspertiz_paketi"],
        confirmed=True,
        caller_phone="05321112233",
    )
    assert "ekspertiz randevusu" in summary
    assert "onaylandı" in summary
    assert "SMS/WhatsApp hatırlatması" in action


def test_evaluate_and_save_call_analytics_db():
    with Session() as db:
        c_id = f"conv-{uid()[:8]}"
        conv = Conversation(id=c_id, channel="phone", status="resolved")
        db.add(conv)

        t1 = Turn(conversation_id=c_id, role="customer", text="34 BCF 1234 için randevu istiyorum.")
        t2 = Turn(conversation_id=c_id, role="assistant", text="Saat 14:00 için randevunuz oluşturuldu.")
        t3 = Turn(conversation_id=c_id, role="customer", text="Tamamdır teşekkür ederim.")
        db.add_all([t1, t2, t3])
        db.commit()

        record = evaluate_and_save_call_analytics(
            db,
            conversation_id=c_id,
            caller_phone="05329998877",
            caller_name="Ahmet Yılmaz",
            duration_sec=74.5,
        )
        assert record.id.startswith("ca-")
        assert record.conversation_id == c_id
        assert record.intent == "appointment_booking"
        assert record.lead_tier == "HOT"
        assert record.csat_score >= 3.5
        assert record.caller_phone == "05329998877"

        # Check summary stats
        stats = get_analytics_summary_stats(db)
        assert stats["total_analyzed_calls"] >= 1
        assert stats["lead_tier_distribution"]["HOT"] >= 1


def test_analytics_api_endpoints(client, auth_headers):
    c_id = f"conv-api-{uid()[:8]}"
    with Session() as db:
        conv = Conversation(id=c_id, channel="phone", status="active")
        db.add(conv)
        db.commit()

    # 1. POST /api/analytics/evaluate-call
    eval_payload = {
        "conversation_id": c_id,
        "caller_phone": "05441234567",
        "caller_name": "Canan Dağ",
        "duration_sec": 82.0,
        "transcript": [
            {"role": "customer", "text": "Merhaba ekspertiz fiyatı ne kadar?"},
            {"role": "assistant", "text": "Standart ekspertiz paketimiz 2500 TL'dir."},
            {"role": "customer", "text": "Fiyat biraz yüksekmiş, düşüneyim."},
        ],
    }
    r = client.post("/api/analytics/evaluate-call", json=eval_payload, headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["conversation_id"] == c_id
    assert "csat_score" not in data
    assert data["csat_is_estimate"] is True
    assert 1.0 <= data["estimated_sentiment_score"] <= 5.0
    assert data["intent"] == "price_inquiry"
    assert "fiyat_yuksek" in data["objections_json"]

    # 2. GET /api/analytics/calls
    r2 = client.get("/api/analytics/calls", headers=auth_headers)
    assert r2.status_code == 200
    calls = r2.json()
    assert any(c["conversation_id"] == c_id for c in calls)

    # 3. GET /api/analytics/call-stats
    r3 = client.get("/api/analytics/call-stats", headers=auth_headers)
    assert r3.status_code == 200
    stats = r3.json()
    assert stats["total_analyzed_calls"] >= 1
    # Gerçek CSAT yok: null; tahmin ayrı alanda ve etiketli
    assert stats["average_csat"] is None
    assert stats["csat_is_estimate"] is True
    assert stats["average_estimated_sentiment_score"] is not None
    assert "top_intents" in stats

    # 4. GET /api/analytics/calls (genel liste ucu hassas tablo için kapatıldı)
    r4 = client.get("/api/analytics/calls", headers=auth_headers)
    assert r4.status_code == 200
    res_list = r4.json()
    assert len(res_list) >= 1
