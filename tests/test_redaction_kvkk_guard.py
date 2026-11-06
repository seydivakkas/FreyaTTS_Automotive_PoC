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

import io
import json
import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from backend.main import app
from backend.redaction_kvkk_guard import (
    KVKKGuard,
    default_kvkk_guard,
    is_valid_luhn,
    is_valid_tckn,
    is_valid_tr_iban,
    mask_credit_card,
    mask_email,
    mask_iban,
    mask_phone,
    mask_tckn,
    redact_audio,
    redact_dialogue_turns,
    redact_text,
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


# 1. TCKN Doğrulama Testleri
def test_is_valid_tckn():
    # Geçerli TCKN örnekleri (algoritmik formüle uyan)
    assert is_valid_tckn("10000000146") is True
    assert is_valid_tckn("51234567800") is True or is_valid_tckn(10000000146) is True

    # Geçersiz durumlar
    assert is_valid_tckn("01234567890") is False  # 0 ile başlayamaz
    assert is_valid_tckn("1234567890") is False   # 10 hane
    assert is_valid_tckn("123456789012") is False # 12 hane
    assert is_valid_tckn("10000000147") is False  # Yanlış sağlama
    assert is_valid_tckn("abcdefghijk") is False  # Harf
    assert is_valid_tckn("") is False


# 2. Luhn Kredi Kartı Testleri
def test_is_valid_luhn():
    # Geçerli kartlar
    assert is_valid_luhn("4532015112830366") is True  # Visa
    assert is_valid_luhn("5425233430109903") is True  # Mastercard
    assert is_valid_luhn("4532-0151-1283-0366") is True
    assert is_valid_luhn("4532 0151 1283 0366") is True

    # Geçersiz kartlar
    assert is_valid_luhn("4532015112830367") is False # Hatalı checksum
    assert is_valid_luhn("12345") is False            # Çok kısa
    assert is_valid_luhn("") is False


# 3. TR IBAN Doğrulama Testleri
def test_is_valid_tr_iban():
    # Standart geçerli Türkiye IBAN örneği (Mod 97 == 1)
    valid_iban = "TR780006100519786452104130"
    assert is_valid_tr_iban(valid_iban) is True
    assert is_valid_tr_iban("TR78 0006 1005 1978 6452 1041 30") is True

    # Geçersiz IBAN'lar
    assert is_valid_tr_iban("TR330006100519786452104130") is False # Hatalı kontrol basamağı
    assert is_valid_tr_iban("TR000000000000000000000000") is False
    assert is_valid_tr_iban("DE330006100519786452104130") is False # TR değil
    assert is_valid_tr_iban("TR123") is False                       # 26 karakter değil


# 4. Maskeleme Fonksiyonları
def test_masking_functions():
    assert mask_tckn("10000000146") == "100******46"
    assert mask_tckn("10000000146", "#") == "100######46"

    masked_card = mask_credit_card("4532015112830366")
    assert "4532" in masked_card
    assert "0366" in masked_card
    assert "****" in masked_card

    assert mask_phone("05321234567") == "0532 *** ** 67"
    assert mask_phone("+90 532 123 45 67") == "0532 *** ** 67"

    assert mask_email("ahmet.yilmaz@gmail.com") == "a**********z@gmail.com"
    assert mask_email("ali@test.com") == "a*i@test.com"

    masked_iban = mask_iban("TR780006100519786452104130")
    assert masked_iban.startswith("TR")
    assert masked_iban.endswith("41 30")


# 5. Tam Metin Maskeleme (KVKK Redaction)
def test_redact_text_comprehensive():
    raw_text = (
        "Müşteri Ahmet Yılmaz, TCKN: 10000000146, telefonu 05321234567, "
        "e-postası ahmet@ornek.com. Ödemeyi 4532 0151 1283 0366 nolu kartla yaptı, "
        "CVV: 456 ve son kullanma tarihi 12/26. İade IBAN: TR780006100519786452104130."
    )

    res = redact_text(raw_text)
    redacted = res.redacted_text

    # Hassas verilerin maskelendiğini doğrula
    assert "10000000146" not in redacted
    assert "100******46" in redacted

    assert "05321234567" not in redacted
    assert "0532 *** ** 67" in redacted

    assert "ahmet@ornek.com" not in redacted
    assert "@ornek.com" in redacted

    assert "4532 0151 1283 0366" not in redacted
    assert "4532 **** **** 0366" in redacted

    assert "CVV: 456" not in redacted
    assert "CVV: ***" in redacted

    assert "TR780006100519786452104130" not in redacted
    assert res.redaction_count >= 5
    assert len(res.entities) >= 5


# 6. Sesli Rakam Dizisi Maskeleme
def test_redact_spoken_numbers():
    # 10000000146 -> "bir sıfır sıfır sıfır sıfır sıfır sıfır sıfır bir dört altı"
    spoken_text = "Benim kimlik numaram bir sıfır sıfır sıfır sıfır sıfır sıfır sıfır bir dört altı kontrol eder misiniz"
    res = redact_text(spoken_text)
    assert "[TCKN MASKELENDİ: 100******46]" in res.redacted_text
    assert "bir sıfır sıfır" not in res.redacted_text


# 7. Ses Maskeleme (Audio Bleep / Mute)
def test_redact_audio():
    sr = 8000
    duration_sec = 2.0
    # 2 saniyelik 440 Hz test sesi
    t = np.linspace(0, duration_sec, int(sr * duration_sec), endpoint=False)
    orig_audio = 0.5 * np.sin(2 * np.pi * 440 * t)

    # 0.5 ile 1.2 saniye arasını sessize al (mute)
    muted_audio = redact_audio(orig_audio, sr, [(0.5, 1.2)], mode="mute")
    # 0.6 ile 1.1 saniye arasındaki enerjinin 0 olduğunu doğrula
    mid_sample_start = int(0.6 * sr)
    mid_sample_end = int(1.1 * sr)
    assert np.allclose(muted_audio[mid_sample_start:mid_sample_end], 0.0, atol=1e-5)
    # Başlangıç ve son kısımların bozulmadığını doğrula
    assert np.max(np.abs(muted_audio[: int(0.4 * sr)])) > 0.3

    # Bleep (1000 Hz) modu
    bleep_audio = redact_audio(orig_audio, sr, [(0.5, 1.2)], mode="beep", beep_freq=1000.0)
    assert len(bleep_audio) == len(orig_audio)
    # Bip bölgesinde genlik yaklaşık 0.25 olmalı
    assert np.max(np.abs(bleep_audio[mid_sample_start:mid_sample_end])) > 0.2


# 8. Diyalog Turları Maskeleme
def test_redact_dialogue_turns():
    turns = [
        {"role": "customer", "text": "Kimlik numaram 10000000146, randevu istiyorum."},
        {"role": "assistant", "text": "Teşekkürler, saat 14:00 uygun mudur?"},
        {"role": "customer", "text": "Kartım 4532015112830366, ödemeyi çekebilirsiniz."},
    ]
    redacted_turns, count = redact_dialogue_turns(turns)
    assert count == 2
    assert "100******46" in redacted_turns[0]["text"]
    assert "10000000146" not in redacted_turns[0]["text"]
    assert "4532015112830366" not in redacted_turns[2]["text"]


# 9. REST API Uç Noktaları Testi
def test_kvkk_api_endpoints(client, auth_headers):
    # 1. POST /api/kvkk/validate-tckn
    r1 = client.post("/api/kvkk/validate-tckn", json={"tckn": "10000000146"}, headers=auth_headers)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["is_valid"] is True
    assert d1["masked"] == "100******46"

    # Geçersiz TCKN
    r1_inv = client.post("/api/kvkk/validate-tckn", json={"tckn": "12345678901"}, headers=auth_headers)
    assert r1_inv.status_code == 200
    assert r1_inv.json()["is_valid"] is False

    # 2. POST /api/kvkk/validate-card
    r2 = client.post("/api/kvkk/validate-card", json={"card_number": "4532015112830366"}, headers=auth_headers)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["is_valid"] is True
    assert "4532" in d2["masked"]

    # 3. GET /api/kvkk/policy
    r3 = client.get("/api/kvkk/policy", headers=auth_headers)
    assert r3.status_code == 200
    pol = r3.json()
    assert "tckn" in pol["supported_pii"]
    assert pol["beep_freq_hz"] == 1000.0

    # 4. POST /api/kvkk/redact-text
    r4 = client.post(
        "/api/kvkk/redact-text",
        json={"text": "Telefonum 05321112233 ve TCKN 10000000146"},
        headers=auth_headers,
    )
    assert r4.status_code == 200
    d4 = r4.json()
    assert "100******46" in d4["redacted_text"]
    assert "0532 *** ** 33" in d4["redacted_text"]
    assert d4["redaction_count"] == 2

    # 5. POST /api/kvkk/redact-audio
    sr = 8000
    audio_data = np.zeros(sr * 1, dtype=np.float32)  # 1 sn sessizlik
    buf = io.BytesIO()
    sf.write(buf, audio_data, sr, format="WAV", subtype="PCM_16")
    buf.seek(0)

    files = {"file": ("test.wav", buf.read(), "audio/wav")}
    data = {
        "ranges_json": json.dumps([[0.2, 0.5]]),
        "mode": "beep",
    }
    r5 = client.post("/api/kvkk/redact-audio", files=files, data=data, headers=auth_headers)
    assert r5.status_code == 200
    assert r5.headers["content-type"] == "audio/wav"
    out_audio, out_sr = sf.read(io.BytesIO(r5.content))
    assert out_sr == sr
    # Bip sesinin uygulandığını doğrula
    assert np.max(np.abs(out_audio[int(0.25 * sr) : int(0.45 * sr)])) > 0.1
