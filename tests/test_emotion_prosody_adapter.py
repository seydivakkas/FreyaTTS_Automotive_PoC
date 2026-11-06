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

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.emotion_prosody_adapter import (
    EmotionCategory,
    EmotionProfile,
    EmotionProsodyAdapter,
    compute_audio_rms_dbfs,
    count_turkish_syllables,
    emotion_prosody_adapter,
)
from backend.main import app


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


# 1. Hece Sayacı ve Ses Enerjisi (RMS) Testi
def test_syllable_counter_and_rms():
    assert count_turkish_syllables("ekspertiz") == 3
    assert count_turkish_syllables("otomotiv") == 4
    assert count_turkish_syllables("Volkswagen Passat") == 5  # o, e, a, a, a

    # Sessiz sinyal vs Yüksek enerjili sinyal
    silent = np.zeros(1600, dtype=np.float32)
    loud = np.ones(1600, dtype=np.float32) * 0.5
    assert compute_audio_rms_dbfs(silent) < -90.0
    assert compute_audio_rms_dbfs(loud) > -10.0


# 2. Fiyat İtirazı Tespiti Testi
def test_analyze_caller_emotion_price_objection():
    adapter = EmotionProsodyAdapter()
    text = "Fiyatınız biraz pahalı geldi, daha uygun bir indirim yapamaz mısınız?"
    profile = adapter.analyze_caller_emotion(text)

    assert profile.primary_category == EmotionCategory.OBJECTION_PRICE
    assert "pahalı" in profile.detected_keywords
    assert "indirim" in profile.detected_keywords
    assert profile.confidence >= 0.70


# 3. Zaman / Saat İtirazı Tespiti Testi
def test_analyze_caller_emotion_time_objection():
    adapter = EmotionProsodyAdapter()
    text = "O saatte işteyim, randevuya kesinlikle yetişemem."
    profile = adapter.analyze_caller_emotion(text)

    assert profile.primary_category == EmotionCategory.OBJECTION_TIME
    assert "işteyim" in profile.detected_keywords
    assert "yetişemem" in profile.detected_keywords


# 4. Kararsız ve Tereddütlü Müşteri Tespiti Testi
def test_analyze_caller_emotion_hesitant():
    adapter = EmotionProsodyAdapter()
    text = "Acaba hangi paketi alsam, tam emin değilim, bir bakarız."
    profile = adapter.analyze_caller_emotion(text)

    assert profile.primary_category == EmotionCategory.HESITANT
    assert "emin değilim" in profile.detected_keywords
    assert "acaba" in profile.detected_keywords


# 5. Hızlı / Aceleci Müşteri ve Akustik Hece Hızı Testi
def test_analyze_caller_emotion_hurried_with_audio():
    adapter = EmotionProsodyAdapter()
    text = "Acil hemen randevu istiyorum çabuk olsun"
    # 1.5 saniye süren ses örneği
    sr = 16000
    samples = (0.2 * np.sin(2 * np.pi * 300 * np.linspace(0, 1.5, int(sr * 1.5)))).astype(np.float32)

    profile = adapter.analyze_caller_emotion(
        text,
        audio_samples=samples,
        audio_duration_sec=1.5,
        sample_rate=sr,
    )

    assert profile.primary_category == EmotionCategory.HURRIED
    assert "acil" in profile.detected_keywords
    assert "hemen" in profile.detected_keywords
    assert profile.speech_rate_syllables_per_sec is not None
    assert profile.speech_rate_syllables_per_sec >= 5.0
    assert profile.speech_rate_category == "fast"


# 6. Kararsız Müşteri İçin Prozodi Esnetme ve Empatik Giriş Testi
def test_adapt_prosody_hesitant_stretches_pauses():
    adapter = EmotionProsodyAdapter(base_period_pause_sec=0.25, base_comma_pause_sec=0.14)
    profile = EmotionProfile(primary_category=EmotionCategory.HESITANT, confidence=0.85)

    resp = "Paketimiz kaporta ve motor testini kapsamaktadır."
    plan = adapter.adapt_prosody(resp, profile)

    # Empatik giriş eklenmeli
    assert "Tabii ki" in plan.adapted_text or "Kararınızı" in plan.adapted_text
    assert plan.injected_discourse_prefix != ""

    # Duraksamalar %25 esnetilmeli
    assert plan.pause_multiplier == 1.25
    assert plan.period_pause_sec > 0.25
    assert plan.comma_pause_sec > 0.14
    assert plan.speed_ratio < 1.0  # Daha sakin konuşma temposu
    assert plan.acoustic_tone == "reassuring_patient"


# 7. Acele Eden Müşteri İçin Hızlı ve Doğrudan Yanıt Testi
def test_adapt_prosody_hurried_quickens_tempo():
    adapter = EmotionProsodyAdapter(base_period_pause_sec=0.25, base_comma_pause_sec=0.14)
    profile = EmotionProfile(primary_category=EmotionCategory.HURRIED, confidence=0.90)

    resp = "Randevunuz saat 14:00'te onaylandı."
    plan = adapter.adapt_prosody(resp, profile)

    # Acele eden müşteriye laf uzatılmaz
    assert plan.injected_discourse_prefix == ""
    assert plan.adapted_text == resp

    # Duraksamalar daraltılmalı, hız artmalı
    assert plan.pause_multiplier == 0.80
    assert plan.period_pause_sec < 0.25
    assert plan.speed_ratio == 1.08
    assert plan.acoustic_tone == "direct_brisk"


# 8. REST API Uç Noktaları Testi
def test_emotion_prosody_api_endpoints(client, auth_headers):
    # 1. POST /api/emotion-prosody/analyze
    req1 = {
        "transcript": "Fiyatlarınız çok yüksek geldi, indirim var mı?",
    }
    r1 = client.post("/api/emotion-prosody/analyze", json=req1, headers=auth_headers)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["primary_category"] == "objection_price"
    assert len(d1["detected_keywords"]) >= 1

    # 2. POST /api/emotion-prosody/adapt
    req2 = {
        "assistant_response_text": "Fiyatımız tüm mikron ve dyno testlerini içeriyor.",
        "caller_transcript": "Fiyatlarınız çok yüksek geldi, indirim var mı?",
    }
    r2 = client.post("/api/emotion-prosody/adapt", json=req2, headers=auth_headers)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["emotion_category"] == "objection_price"
    assert d2["pause_multiplier"] == 1.15
    assert "Sizi çok iyi anlıyorum" in d2["adapted_text"] or "Haklısınız" in d2["adapted_text"]

    # 3. GET /api/emotion-prosody/config
    r3 = client.get("/api/emotion-prosody/config", headers=auth_headers)
    assert r3.status_code == 200
    d3 = r3.json()
    assert "objection_price" in d3["categories"]
    assert "hesitant" in d3["categories"]
    assert d3["base_period_pause_sec"] == 0.25

