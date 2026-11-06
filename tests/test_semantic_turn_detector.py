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

from backend.main import app
from backend.semantic_turn_detector import (
    SemanticTurnDetector,
    SmartTurnAudioSocketAdapter,
    analyze_semantic_completeness,
    estimate_f0_pitch_slope,
    resample_to_16k,
)


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


# 1. Tamamlanmış Cümleler Testi
def test_analyze_semantic_completeness_finished_sentences():
    # Çekimli fiil ile biten bildirim
    r1 = analyze_semantic_completeness("Yarın saat 14:00'te gelebilirim.")
    assert r1.is_syntactically_complete is True
    assert r1.has_finite_verb is True
    assert r1.completeness_score >= 0.85

    # Soru cümlesi
    r2 = analyze_semantic_completeness("Ekspertiz paketinizin fiyatı ne kadar?")
    assert r2.is_syntactically_complete is True
    assert r2.is_question is True

    # Soru edatıyla biten onay
    r3 = analyze_semantic_completeness("Yarın saat üçe randevu oluşturabilir miyiz?")
    assert r3.is_syntactically_complete is True
    assert r3.is_question is True

    # Kısa olumlu cevap
    r4 = analyze_semantic_completeness("Evet uygun.")
    assert r4.is_syntactically_complete is True
    assert r4.completeness_score >= 0.85

    # Gelecek zaman kipi
    r5 = analyze_semantic_completeness("Aracı saat on birde getireceğiz")
    assert r5.is_syntactically_complete is True
    assert r5.has_finite_verb is True


# 2. Tamamlanmamış Düşünme ve Bağlaç Belirteçleri Testi
def test_analyze_semantic_completeness_unfinished_discourse_markers():
    # "aslında" ile yarım bırakılan cümle
    r1 = analyze_semantic_completeness("Yarın saat ikide... aslında")
    assert r1.is_syntactically_complete is False
    assert "aslında" in r1.detected_incomplete_markers
    assert r1.completeness_score < 0.30

    # "ve" bağlacı ile yarım bırakılan cümle
    r2 = analyze_semantic_completeness("Sol ön çamurluk boyalı ve")
    assert r2.is_syntactically_complete is False
    assert "ve" in r2.detected_incomplete_markers

    # Çok kelimeli "ya da" bağlacı
    r3 = analyze_semantic_completeness("Full ekspertiz yaptıracağım ya da")
    assert r3.is_syntactically_complete is False
    assert any("ya da" in m for m in r3.detected_incomplete_markers)

    # "çünkü" sebep bağlacı
    r4 = analyze_semantic_completeness("Randevuyu ertelemek istiyorum çünkü")
    assert r4.is_syntactically_complete is False
    assert "çünkü" in r4.detected_incomplete_markers

    # Düşünme heceleri ("ııı", "şey")
    r5 = analyze_semantic_completeness("Plaka otuz dört şey")
    assert r5.is_syntactically_complete is False
    assert "şey" in r5.detected_incomplete_markers


# 3. Askıda Kalan Edatlar Testi
def test_analyze_semantic_completeness_unfinished_postpositions():
    r1 = analyze_semantic_completeness("Yarın akşama doğru")
    assert r1.is_syntactically_complete is False
    assert any("doğru" in m for m in r1.detected_incomplete_markers)

    r2 = analyze_semantic_completeness("Fiyat teklifinize göre")
    assert r2.is_syntactically_complete is False
    assert any("göre" in m for m in r2.detected_incomplete_markers)


# 4. Konuşma Sırası Karar Motoru (WAIT vs COMMIT) Testi
def test_turn_decision_wait_vs_commit():
    detector = SemanticTurnDetector(
        min_silence_ms=250.0,
        extended_silence_ms=800.0,
        max_hold_ms=2500.0,
    )

    # Tamamlanmış cümle: 300 ms sessizlikte COMMIT etmeli
    d1 = detector.decide_turn(text="Yarın gelirim", silence_duration_ms=300.0)
    assert d1.action == "COMMIT"
    assert d1.is_complete is True
    assert d1.recommended_silence_timeout_ms == 250.0

    # Tamamlanmamış cümle: 300 ms sessizlikte henüz WAIT demeli (çünkü 300 < 800 ms)
    d2 = detector.decide_turn(text="Yarın saat ikide aslında", silence_duration_ms=300.0)
    assert d2.action == "WAIT"
    assert d2.is_complete is False
    assert d2.recommended_silence_timeout_ms == 800.0

    # Tamamlanmamış cümle: 850 ms sessizlikte esnetilmiş süre dolduğundan COMMIT etmeli
    d3 = detector.decide_turn(text="Yarın saat ikide aslında", silence_duration_ms=850.0)
    assert d3.action == "COMMIT"

    # Tavan süre aşımı: 2600 ms sessizlikte zorunlu FORCE_COMMIT etmeli
    d4 = detector.decide_turn(text="ııı şey", silence_duration_ms=2600.0)
    assert d4.action == "FORCE_COMMIT"


# 5. Akustik 8 kHz -> 16 kHz ve Perde (Pitch) Eğimi Testi
def test_acoustic_resample_and_pitch_slope():
    # 8 kHz yapay sinüzoidal ses (200 Hz ton)
    sr_8k = 8000
    t = np.linspace(0, 0.5, int(sr_8k * 0.5), endpoint=False)
    sig_8k = (0.5 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)

    # 16 kHz'e yukarı örnekleme
    sig_16k = resample_to_16k(sig_8k, sr_8k)
    assert len(sig_16k) == int(len(sig_8k) * 2)

    # Perde eğimi kestirimi (sabit ton için eğim ~0 civarı olmalı)
    slope = estimate_f0_pitch_slope(sig_16k)
    assert slope is not None
    assert abs(slope) < 0.20


# 6. AudioSocket Akıllı Adaptör Testi
def test_smart_turn_audiosocket_adapter():
    adapter = SmartTurnAudioSocketAdapter(sample_rate=8000)

    # 20 ms'lik (160 örnek) sessizlik çerçevesi
    silence_frame_8k = (np.zeros(160, dtype=np.int16)).tobytes()
    # 20 ms'lik ses çerçevesi
    speech_frame_8k = (np.ones(160, dtype=np.int16) * 1000).tobytes()

    # Kullanıcı konuşurken WAIT dönmeli
    dec_speech = adapter.process_frame(speech_frame_8k, is_speech=True, frame_duration_ms=20.0)
    assert dec_speech.action == "WAIT"

    # Kullanıcı duraksadı ama cümle eksik: 200 ms sessizlikte WAIT kalmalı
    for _ in range(10):
        dec_silence = adapter.process_frame(
            silence_frame_8k,
            is_speech=False,
            frame_duration_ms=20.0,
            partial_transcript="Yarın saat ikide veya",
        )
    assert dec_silence.action == "WAIT"

    # Sessizlik 800 ms'yi aştığında (en az 40 adım x 20 ms = 800 ms) COMMIT dönmeli
    committed = False
    for _ in range(35):
        d = adapter.process_frame(
            silence_frame_8k,
            is_speech=False,
            frame_duration_ms=20.0,
            partial_transcript="Yarın saat ikide veya",
        )
        if d.action == "COMMIT":
            committed = True
            break
    assert committed is True


# 7. REST API Uç Noktaları Testi
def test_turn_detector_api_endpoints(client, auth_headers):
    # 1. POST /api/turn-detector/evaluate
    eval_body = {
        "text": "Sol ön çamurluk ve",
        "silence_duration_ms": 300.0,
    }
    r1 = client.post("/api/turn-detector/evaluate", json=eval_body, headers=auth_headers)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["action"] == "WAIT"
    assert d1["is_complete"] is False
    assert d1["recommended_silence_timeout_ms"] == 800.0

    # 2. POST /api/turn-detector/analyze-text
    analyze_body = {
        "text": "Ekspertiz randevumu saat 15:00'e onaylayabilir misiniz?",
    }
    r2 = client.post("/api/turn-detector/analyze-text", json=analyze_body, headers=auth_headers)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["is_syntactically_complete"] is True
    assert d2["is_question"] is True
    assert d2["completeness_score"] >= 0.85

    # 3. GET /api/turn-detector/config
    r3 = client.get("/api/turn-detector/config", headers=auth_headers)
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["min_silence_ms"] == 250.0
    assert d3["extended_silence_ms"] == 800.0
    assert d3["single_marker_count"] > 20
