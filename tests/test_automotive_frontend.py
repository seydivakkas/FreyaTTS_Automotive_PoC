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

import base64
import math
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.automotive_frontend import (
    AutomotiveTextNormalizer,
    AutomotiveDSPChain,
    AutomotiveFrontend,
    automotive_frontend,
    load_freya_vocab,
    COMFORT_NOISE_RMS,
)
import src.automotive_frontend as facade


@pytest.fixture
def test_client():
    client = TestClient(app)
    client.auth = ("admin", settings.admin_password)
    return client


def test_facade_exports():
    """src/automotive_frontend.py cephesinin tüm bileşenleri doğru dışa aktardığını doğrular."""
    assert hasattr(facade, "AutomotiveTextNormalizer")
    assert hasattr(facade, "AutomotiveDSPChain")
    assert hasattr(facade, "AutomotiveFrontend")
    assert hasattr(facade, "automotive_frontend")
    assert hasattr(facade, "load_freya_vocab")
    assert hasattr(facade, "COMFORT_NOISE_DBFS")
    assert hasattr(facade, "TURKISH_CONJUNCTIONS")


def test_automotive_brand_normalization_and_suffixes():
    """Yabancı marka isimleri ve Türkçe ses uyumlu ek açılımlarını test eder."""
    normalizer = AutomotiveTextNormalizer()

    # 1. Temel marka isimleri
    assert "Folksvagen" in normalizer.normalize("Volkswagen Passat")
    assert "Kaşkai" in normalizer.normalize("Nissan Qashqai")
    assert "Pejo" in normalizer.normalize("Peugeot 3008")
    assert "Reno" in normalizer.normalize("Renault Megane")
    assert "Sitroen" in normalizer.normalize("Citroën C3")
    assert "Daçya" in normalizer.normalize("Dacia Duster")
    assert "Porşe" in normalizer.normalize("Porsche Macan")

    # 2. Marka ek uyumlaması (konuşma metninde kesme işareti olmadan doğrudan ekleme)
    assert "Folksvagene" in normalizer.normalize("Volkswagen'e")
    assert "Folksvagenin" in normalizer.normalize("Volkswagen'in")
    assert "Folksvagende" in normalizer.normalize("Volkswagen'de")
    assert "Kaşkaiye" in normalizer.normalize("Qashqai'ye")
    assert "Kaşkaide" in normalizer.normalize("Qashqai'de")


def test_engine_displacement_normalization():
    """Motor hacimleri ve şanzıman kısaltmalarının Türkçe açılımı."""
    normalizer = AutomotiveTextNormalizer()

    assert "bir nokta beş ti es ay" in normalizer.normalize("1.5 TSI")
    assert "bir nokta altı te de i" in normalizer.normalize("1.6 TDI")
    assert "iki nokta sıfır te de i" in normalizer.normalize("2.0 TDI")
    assert "bir nokta üç te ce e" in normalizer.normalize("1.3 TCe")
    assert "bir nokta beş i pavır" in normalizer.normalize("1.5 e-Power")
    assert "iki nokta sıfır blu haş de i" in normalizer.normalize("2.0 BlueHDi")

    # Ek uyumu
    assert "bir nokta beş ti es ayın" in normalizer.normalize("1.5 TSI'ın")
    assert "bir nokta altı te de ide" in normalizer.normalize("1.6 TDI'da")


def test_currency_and_price_without_dots():
    """Noktalı ve noktasız fiyat formatları ile ek uyumu."""
    normalizer = AutomotiveTextNormalizer()

    # Noktasız 1250000 ₺
    norm_tl = normalizer.normalize("Aracınızın bedeli 1250000 ₺")
    assert "bir milyon iki yüz elli bin Türk lirası" in norm_tl

    # Noktalı ve noktasız TL
    assert "bir milyon iki yüz elli bin Türk lirası" in normalizer.normalize("1.250.000 TL")
    assert "bir milyon iki yüz elli bin Türk lirası" in normalizer.normalize("1250000 TL")

    # Ekli fiyat
    assert "sekiz yüz elli bin Türk lirasına" in normalizer.normalize("850000 TL'ye")
    assert "bir milyon iki yüz elli bin Türk lirasında" in normalizer.normalize("1250000 ₺'de")


def test_time_expressions_and_suffixes():
    """Saat eklerinin (14:30'da -> on dört otuzda, 15:00'te -> on beşte) ses uyumu."""
    normalizer = AutomotiveTextNormalizer()

    assert "on dört otuzda" in normalizer.normalize("Randevunuz saat 14:30'da")
    assert "on beşte" in normalizer.normalize("Saat 15:00'de")
    assert "on beşte" in normalizer.normalize("Saat 15:00'te")
    assert "on dört kırk beşte" in normalizer.normalize("Saat 14:45'te")
    assert "on altıya" in normalizer.normalize("Saat 16:00'ya")


def test_unk_security_net():
    """Modelin 92 sembollü sözlüğünde olmayan q, ₺, !, $, (, ) karakterlerinin güvenli temizliği."""
    normalizer = AutomotiveTextNormalizer()
    vocab = load_freya_vocab()

    dirty_text = "Fiyat 1250000 ₺! (Audi Q5 & 1.5 TSI) [Superb] {100$} Qashqai? test_plate#1"
    cleaned = normalizer.clean_unk_characters(dirty_text)

    # 1. ₺, $, !, (, ) kalmamalı
    assert "₺" not in cleaned
    assert "$" not in cleaned
    assert "!" not in cleaned
    assert "(" not in cleaned
    assert ")" not in cleaned
    assert "Türk lirası" in cleaned
    assert "dolar" in cleaned

    # 2. Küçük 'q' olmamalı (vocab'da sadece 'Q' veya dönüştürülmüş 'k' olmalı)
    assert "q" not in cleaned

    # 3. Tüm karakterlerin model vocab'ında veya whitespace içinde olduğunu doğrula
    valid_chars = vocab | {" ", "\n"}
    invalid = [ch for ch in cleaned if ch not in valid_chars]
    assert len(invalid) == 0, f"Desteklenmeyen karakterler bulundu: {invalid}"


def test_prosodic_clauses_and_dynamic_pauses():
    """Bağlaç duyarlı yumuşak bölme ve noktalama duraksama süreleri."""
    normalizer = AutomotiveTextNormalizer()

    # 1. Noktalama duraksamaları kontrolü
    clauses = normalizer.split_prosodic_clauses("Merhaba, hoş geldiniz. Randevu alacak mısınız?")
    assert len(clauses) >= 2
    # Soru işareti en uzun duraklamaya sahip olmalı (320 ms)
    question_clause = next(c for c in clauses if "?" in c[0])
    assert question_clause[1] == 0.32

    # Nokta duraklaması (280 ms)
    period_clause = next(c for c in clauses if "." in c[0])
    assert period_clause[1] == 0.28

    # 2. Bağlaç duyarlı bölme (veya, çünkü)
    long_sentence = (
        "2023 model Volkswagen Passat aracınız için ekspertiz randevusu oluşturduk "
        "ancak şubemize gelmeden önce lütfen araç ruhsatını yanınızda bulundurun "
        "çünkü işlemler sırasında ruhsat bilgileri sisteme girilmektedir."
    )
    chunks = normalizer.split_prosodic_clauses(long_sentence)
    assert len(chunks) >= 2
    # Hiçbir parça aşırı uzun olmamalı
    for text, pause in chunks:
        assert len(text.split()) <= 15
        assert pause >= 0.08


def test_dsp_cosine_fade():
    """Kosinüs sönümleme fonksiyonunun parça sınırlarını sıfıra yumuşattığını doğrular."""
    dsp = AutomotiveDSPChain()
    sr = 48000
    n = 4800
    test_audio = np.ones(n, dtype=np.float32)

    faded = dsp.apply_cosine_fade(test_audio, sr=sr, fade_ms=10.0)

    # Başlangıç ve bitiş 0'a yakın olmalı
    assert faded[0] == pytest.approx(0.0, abs=1e-3)
    assert faded[-1] == pytest.approx(0.0, abs=1e-3)
    # Orta kısım 1.0 olarak korunmalı
    mid = n // 2
    assert faded[mid] == pytest.approx(1.0, abs=1e-3)


def test_dsp_de_esser():
    """6.5 kHz sibilance ıslık tonunun bastırıldığını, 1 kHz konuşma tonunun korunduğunu doğrular."""
    dsp = AutomotiveDSPChain()
    sr = 48000
    t = np.linspace(0, 0.2, int(sr * 0.2), endpoint=False)

    # 6.5 kHz saf sibilance sinyali
    sibilance_tone = np.sin(2 * np.pi * 6500.0 * t).astype(np.float32)
    cleaned_sibilance = dsp.apply_de_esser(sibilance_tone, sr=sr, reduction_db=4.5)
    rms_before = np.sqrt(np.mean(sibilance_tone ** 2))
    rms_after = np.sqrt(np.mean(cleaned_sibilance ** 2))
    # ~4.5 dB bastırma (oran ~0.55 - 0.65)
    ratio = rms_after / rms_before
    assert ratio < 0.70

    # 1 kHz normal konuşma sinyali (etkilenmemeli)
    voice_tone = np.sin(2 * np.pi * 1000.0 * t).astype(np.float32)
    cleaned_voice = dsp.apply_de_esser(voice_tone, sr=sr, reduction_db=4.5)
    ratio_voice = np.sqrt(np.mean(cleaned_voice ** 2)) / np.sqrt(np.mean(voice_tone ** 2))
    assert ratio_voice >= 0.95


def test_dsp_comfort_noise():
    """-58 dBFS konfor gürültüsünün doğruluğu ve duraksama PCM üretimi."""
    dsp = AutomotiveDSPChain()
    sr = 8000
    samples = 16000  # 2 saniye

    noise = dsp.generate_comfort_noise(samples, sr=sr)
    rms = np.sqrt(np.mean(noise ** 2))

    # -58 dBFS = ~0.0012589 (tolerans: +/- 3 dB)
    assert 0.0006 < rms < 0.0025

    # Pause PCM üretimi
    pause_bytes = dsp.generate_pause_audio(0.14)
    expected_bytes = int(sr * 0.14) * 2  # 16-bit = 2 bytes per sample
    assert len(pause_bytes) == expected_bytes
    assert pause_bytes != b"\x00" * expected_bytes  # Mutlak sıfır olmamalı


def test_dsp_full_chain_48k_to_8k():
    """48 kHz sinyalin 8 kHz slin16 PCM formatına tam zincir dönüşümü."""
    dsp = AutomotiveDSPChain()
    sr_in = 48000
    t = np.linspace(0, 0.5, int(sr_in * 0.5), endpoint=False)
    synthetic_wav = (0.4 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)

    pcm16 = dsp.process_telephony_dsp(synthetic_wav, apply_de_ess=True, inject_noise=True)

    # 6 kat aşağı örnekleme: 24000 -> 4000 örnek
    assert len(pcm16) == 4000
    assert pcm16.dtype == np.dtype("<i2")
    # Değerler int16 sınırları içinde olmalı
    assert np.max(np.abs(pcm16)) <= 32767


def test_rest_api_frontend_endpoints(test_client):
    """FastAPI REST API ön yüz ve DSP uç noktalarının entegrasyon testleri."""
    # 1. /api/frontend/normalize-prosody
    resp_norm = test_client.post(
        "/api/frontend/normalize-prosody",
        json={"text": "Volkswagen Passat 1.5 TSI saat 14:30'da 1250000 ₺!"},
    )
    assert resp_norm.status_code == 200
    data_norm = resp_norm.json()
    assert "Folksvagen" in data_norm["normalized"]
    assert "bir nokta beş ti es ay" in data_norm["normalized"]
    assert "on dört otuzda" in data_norm["normalized"]
    assert "bir milyon iki yüz elli bin Türk lirası" in data_norm["normalized"]
    assert len(data_norm["clauses"]) >= 1

    # 2. /api/frontend/dsp-telephony
    # 48 kHz 200 ms test sinyali (int16 base64)
    sr_48k = 48000
    t = np.linspace(0, 0.2, int(sr_48k * 0.2), endpoint=False)
    wav_int16 = (np.sin(2 * np.pi * 500.0 * t) * 16000).astype("<i2")
    b64_audio = base64.b64encode(wav_int16.tobytes()).decode("utf-8")

    resp_dsp = test_client.post(
        "/api/frontend/dsp-telephony",
        json={
            "audio_base64": b64_audio,
            "apply_de_esser": True,
            "inject_comfort_noise": True,
        },
    )
    assert resp_dsp.status_code == 200
    data_dsp = resp_dsp.json()
    assert data_dsp["input_samples_48k"] == 9600
    assert data_dsp["output_samples_8k"] == 1600
    assert len(data_dsp["audio_slin16_base64"]) > 0

    # 3. /api/frontend/status
    resp_status = test_client.get("/api/frontend/status")
    assert resp_status.status_code == 200
    status_data = resp_status.json()
    assert "total_processed_texts" in status_data
    assert status_data["comfort_noise_dbfs"] == -58.0
