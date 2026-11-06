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

import asyncio
import pytest

from backend.normalizer import normalize_text_for_tts
from backend.streaming_chunker_guard import (
    TelephonyStreamSanitizer,
    AtomicTokenStreamingChunker,
    AntiDoubleNormalizationGuard,
    stream_sanitizer,
    atomic_chunker,
    anti_double_guard,
)
from src.streaming_chunker_guard import (
    TelephonyStreamSanitizer as SrcSanitizer,
    AtomicTokenStreamingChunker as SrcChunker,
    AntiDoubleNormalizationGuard as SrcGuard,
)


# ============================================================================
# 1. TelephonyStreamSanitizer Testleri
# ============================================================================
def test_stream_sanitizer_markdown_and_bullets():
    """Markdown bold/italik, madde işaretleri ve başlıkların temizlendiğini test eder."""
    raw = (
        "### Seçenekleriniz\n"
        "- **Peugeot 3008**: Dizel otomatik *Allure* paketi.\n"
        "- 1. seçenek: `1.850.000 TL` nakit fiyat.\n"
        "Detaylar için https://ornek.com/fiyat adresine bakabilirsiniz."
    )
    clean, intent = TelephonyStreamSanitizer.sanitize_text(raw)
    assert "###" not in clean
    assert "**" not in clean
    assert "`" not in clean
    assert "https://" not in clean
    assert "- " not in clean
    assert "Peugeot 3008: Dizel otomatik Allure paketi." in clean
    assert intent is None


def test_stream_sanitizer_intent_tag_extraction():
    """<intent:...> etiketinin ayıklanıp temizlendiğini test eder."""
    raw = "<intent:pricing> **Peugeot 3008** güncel nakit fiyatı 1.850.000 TL'dir."
    clean, intent = TelephonyStreamSanitizer.sanitize_text(raw)
    assert intent == "pricing"
    assert "<intent:" not in clean
    assert clean == "Peugeot 3008 güncel nakit fiyatı 1.850.000 TL'dir."


# ============================================================================
# 2. AtomicTokenStreamingChunker Testleri (RT-03)
# ============================================================================
def test_atomic_chunker_first_clause_speed():
    """İlk cümleciğin 4-7 kelimede noktalama ile derhal senteze gönderildiğini test eder."""
    chunker = AtomicTokenStreamingChunker()
    tokens = ["Elimizde ", "iki ", "uygun ", "seçenek ", "bulunuyor. ", "İkinci ", "cümle ", "başlıyor."]

    emitted = []
    for tok in tokens:
        res = chunker.feed_token(tok)
        emitted.extend(res)

    assert len(emitted) == 1
    # İlk cümlecik tam 5 kelimede derhal fırlatılmış olmalı
    assert emitted[0] == "Elimizde iki uygun seçenek bulunuyor."
    # Kalan tampon flush edilince ikinci cümlecik gelir
    flushed = chunker.flush()
    assert len(flushed) == 1
    assert flushed[0] == "İkinci cümle başlıyor."


def test_atomic_chunker_non_splitting_automotive_entities():
    """Marka-model, fiyat ve motor kodlarının asla iki ayrı parçaya bölünmediğini test eder."""
    chunker = AtomicTokenStreamingChunker(min_words_first_clause=4, max_words_first_clause=7)

    # "Peugeot" markasından sonra hemen bölmemeli, "3008" modelini beklemeli
    tokens = ["Elimizde ", "bir ", "adet ", "Peugeot ", "3008 ", "mevcuttur. ", "Fiyatı ", "1.850.000 ", "TL'dir."]
    emitted = []
    for tok in tokens:
        emitted.extend(chunker.feed_token(tok))

    assert len(emitted) == 1
    assert emitted[0] == "Elimizde bir adet Peugeot 3008 mevcuttur."
    assert "Peugeot 3008" in emitted[0]

    flushed = chunker.flush()
    assert len(flushed) == 1
    # 1.850.000 TL birleşik kalmalı
    assert flushed[0] == "Fiyatı 1.850.000 TL'dir."


def test_atomic_chunker_comma_decimal_isolation():
    """Ondalık virgülünün (1,49) cümlecik virgülüyle karışmadığını test eder."""
    chunker = AtomicTokenStreamingChunker(min_words_first_clause=4, max_words_first_clause=7)
    tokens = ["Faiz ", "oranımız ", "1,49 ", "olup, ", "kredi ", "başvurunuz ", "onaylanmıştır."]
    emitted = []
    for tok in tokens:
        emitted.extend(chunker.feed_token(tok))

    # "1,49 olup," ifadesinde virgül olup kelimesinden sonradır; 1,49 parçalanmamalıdır
    flushed = chunker.flush()
    all_chunks = emitted + flushed
    full_joined = " ".join(all_chunks)
    assert "1,49" in full_joined


@pytest.mark.asyncio
async def test_atomic_chunker_async_streaming():
    """Asenkron token jeneratörünün tam akışını test eder."""
    async def sample_token_stream():
        text_tokens = [
            "Merhaba, ", "Borusan ", "Otomotiv'e ", "hoş ", "geldiniz. ",
            "Size ", "nasıl ", "yardımcı ", "olabilirim?"
        ]
        for t in text_tokens:
            await asyncio.sleep(0.01)
            yield t

    chunker = AtomicTokenStreamingChunker()
    chunks = []
    async for c in chunker.stream_chunks(sample_token_stream()):
        chunks.append(c)

    assert len(chunks) == 2
    assert "hoş geldiniz." in chunks[0]
    assert "nasıl yardımcı olabilirim?" in chunks[1]


# ============================================================================
# 3. AntiDoubleNormalizationGuard Testleri
# ============================================================================
def test_anti_double_guard_combining_dots_stripping():
    """Python .lower() kaynaklı combining dot above (\\u0307) eklerinin temizlendiğini test eder."""
    guard = AntiDoubleNormalizationGuard()

    # Standart Python .lower() kaynaklı sorunlu metin simülasyonu
    corrupted = "i\u0307stanbul"  # i + combining dot above (2 karakter)
    assert len(corrupted) == 9

    cleaned = guard.strip_unicode_artifacts(corrupted)
    assert len(cleaned) == 8  # combining dot silinmiş olmalı
    assert "\u0307" not in cleaned

    # Sıfır genişlikli boşluk ve BOM
    text_with_zw = "Pöjo\u200b üç\ufeff bin"
    clean_zw = guard.strip_unicode_artifacts(text_with_zw)
    assert clean_zw == "Pöjo üç bin"


def test_anti_double_guard_vocab_validation():
    """92 karakterlik model sözlüğü uyumluluk denetimini test eder."""
    guard = AntiDoubleNormalizationGuard()

    # Tamamen geçerli Türkçe konuşma metni
    valid_text = "Pöjo üç bin sekiz modelimizin başlangıç fiyatı bir milyon sekiz yüz bin Türk lirasıdır."
    is_valid, invalids = guard.validate_spoken_text(valid_text)
    assert is_valid is True
    assert len(invalids) == 0

    # Model sözlüğünde olmayan yabancı simge içeren metin
    invalid_text = "Fiyat: 1000 ¥ ve 500 ₽"
    is_valid2, invalids2 = guard.validate_spoken_text(invalid_text)
    assert is_valid2 is False
    assert "¥" in invalids2 or "₽" in invalids2


def test_anti_double_guard_double_normalization_safe_check():
    """Okunmamış ham rakam veya döviz sembolü kalıp kalmadığını test eder."""
    guard = AntiDoubleNormalizationGuard()

    safe_text = "bir nokta beş te se ı motor seçeneği"
    is_safe, issues = guard.is_double_normalization_safe(safe_text)
    assert is_safe is True
    assert len(issues) == 0

    unsafe_text = "1.5 TSI motor seçeneği 1.250.000 TL"
    is_safe2, issues2 = guard.is_double_normalization_safe(unsafe_text)
    assert is_safe2 is False
    assert len(issues2) >= 1


# ============================================================================
# 4. 200 Cümlelik Otomotiv Regresyon Kalkanı (Ajan 1 & TTS)
# ============================================================================
def test_200_automotive_sentences_guard_regression():
    """
    200 farklı otomotiv cümlesinin (marka, model, fiyat, yüzde, tarih, motor)
    P0 Normalizer'dan geçtikten sonra AntiDoubleNormalizationGuard tarafından
    100% sözlük uyumlu ve çifte normalizasyona ihtiyaç duymadığını doğrular.
    """
    guard = AntiDoubleNormalizationGuard()

    # 10 farklı kategoriden türetilen 200 zengin test cümlesi
    templates = [
        "{brand} {model} modelimizin anahtar teslim fiyatı {price} olarak belirlenmiştir.",
        "{brand} {model} {engine} motor seçeneğinde {date} tarihine kadar {discount} indirim mevcuttur.",
        "Test sürüşü randevunuz saat {time} için {brand} yetkili satıcımızda oluşturulmuştur.",
        "Aracımızın 0-100 km/sa hızlanması {accel} saniye olup, ortalama yakıt tüketimi {fuel} litredir.",
        "Detaylı bilgi ve finansman koşulları için {phone} numaralı çağrı merkezimizi arayabilirsiniz.",
        "{brand} {model} modelinde {hp} beygir güç ve {battery} batarya kapasitesi sunulmaktadır.",
        "Kampanyamız {date} tarihine kadar geçerli olup, kredi faiz oranı yüzde {rate} seviyesindedir.",
        "Plakası {plate} olan {brand} aracınızın periyodik bakım randevusu teyit edilmiştir.",
        "Şasi numarası {vin} olan {brand} {model} aracınız için servis kaydı açılmıştır.",
        "Takas desteğimiz kapsamında {brand} {model} aracınıza ek olarak {trade_in} teklif edilmektedir.",
    ]

    brands = [
        ("Peugeot", "3008"), ("Renault", "Clio"), ("Volkswagen", "Passat"),
        ("BMW", "X5"), ("Mercedes-Benz", "C 200"), ("Togg", "T10X"),
        ("Toyota", "Corolla"), ("Skoda", "Octavia"), ("Ford", "Focus"),
        ("Audi", "A4"), ("Hyundai", "Tucson"), ("Fiat", "Egea"),
        ("Nissan", "Qashqai"), ("Kia", "Sportage"), ("Volvo", "XC60"),
        ("Cupra", "Formentor"), ("Seat", "Leon"), ("Dacia", "Duster"),
        ("Honda", "Civic"), ("BYD", "Atto 3"),
    ]

    sentences = []
    idx = 0
    for b, m in brands:
        for t_idx, tmpl in enumerate(templates):
            s = tmpl.format(
                brand=b,
                model=m,
                price=f"{1_250_000 + idx * 50_000:,} TL".replace(",", "."),
                engine="1.5 TSI" if idx % 2 == 0 else "1.6 EcoBoost",
                date="15.03.2026",
                discount="%10",
                time="14:45",
                accel="7,8",
                fuel="5,4",
                phone="444 0 123",
                hp="150 HP",
                battery="75 kWh",
                rate="1,49",
                plate="34 ABC 789",
                vin="WBA12345678901234",
                trade_in="50.000 TL",
            )
            sentences.append(s)
            idx += 1

    assert len(sentences) == 200

    # 200 cümlenin normalizasyon ve guard denetimi
    for s in sentences:
        spoken = normalize_text_for_tts(s, profile="sozluk_2026")
        # 1. Sözlük uyumu
        is_valid, invalids = guard.validate_spoken_text(spoken)
        assert is_valid is True, f"Geçersiz karakter bulundu: {invalids} (Cümle: {spoken})"
        # 2. Çifte normalizasyon güvenliği (ham rakam kalmamış olmalı)
        is_safe, issues = guard.is_double_normalization_safe(spoken)
        assert is_safe is True, f"Güvenlik ihlali: {issues} (Cümle: {spoken})"


def test_src_reexport():
    """src.streaming_chunker_guard re-export uyumluluğunu test eder."""
    assert SrcSanitizer is TelephonyStreamSanitizer
    assert SrcChunker is AtomicTokenStreamingChunker
    assert SrcGuard is AntiDoubleNormalizationGuard

