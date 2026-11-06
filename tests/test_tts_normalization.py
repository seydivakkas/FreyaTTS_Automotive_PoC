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

from pathlib import Path
import pandas as pd
import pytest

from backend.asr_mapper import ASRMapper, canonicalize_asr_text
from backend.morphology.lexicon import load_freya_vocab
from backend.normalizer import (
    AutomotiveTTSNormalizer,
    normalize_text_for_tts,
    int_to_turkish,
    decimal_to_turkish,
)

EXCEL_FILE1 = Path("FreyaTTS_Otomotiv_Turkce_Telaffuz_Sezer_ve_Test_Cumleleri.xlsx")
EXCEL_FILE2 = Path("FreyaTTS_Otomotiv_Turkce_Telaffuz_Sozlugu_2026.xlsx")
VOCAB_FILE = Path("config/freya_vocab.json")


@pytest.fixture(scope="module")
def normalizer():
    return AutomotiveTTSNormalizer()


@pytest.fixture(scope="module")
def asr():
    return ASRMapper()


@pytest.fixture(scope="module")
def freya_vocab():
    return load_freya_vocab(VOCAB_FILE)


# ============================================================================
# 1. YARDIMCI SAYI VE ONDALIK FONKSİYONLARI TESTLERİ
# ============================================================================
class TestNumberHelpers:
    """int_to_turkish ve decimal_to_turkish birim testleri"""

    @pytest.mark.parametrize(
        "val,expected",
        [
            (0, "sıfır"),
            (1, "bir"),
            (10, "on"),
            (15, "on beş"),
            (100, "yüz"),
            (105, "yüz beş"),
            (1000, "bin"),
            (1500, "bin beş yüz"),
            (1850000, "bir milyon sekiz yüz elli bin"),
            (2490000, "iki milyon dört yüz doksan bin"),
        ],
    )
    def test_int_to_turkish(self, val, expected):
        assert int_to_turkish(val) == expected

    @pytest.mark.parametrize(
        "val_str,sep_word,expected",
        [
            ("1,49", "virgül", "bir virgül kırk dokuz"),
            ("2,99", "virgül", "iki virgül doksan dokuz"),
            ("1.6", "nokta", "bir nokta altı"),
            ("1.0", "nokta", "bir nokta sıfır"),
            ("89,6", "virgül", "seksen dokuz virgül altı"),
            ("75", "virgül", "yetmiş beş"),
        ],
    )
    def test_decimal_to_turkish(self, val_str, sep_word, expected):
        assert decimal_to_turkish(val_str, sep_word=sep_word) == expected


# ============================================================================
# 2. ASR MAPPER VE KANONİKLEŞTİRME TESTLERİ
# ============================================================================
class TestASRMapper:
    """ASR (Konuşma Tanıma) Transkript Eşleme ve Kanonik Araç Çözümleme Testleri"""

    @pytest.mark.parametrize(
        "raw_transcript,expected_canonical_vehicle,expected_brand",
        [
            ("pöjo 3008 için teklif alabilir miyim?", "Peugeot 3008", "Peugeot"),
            ("bmv 320i bakım randevusu", "BMW 320i", "BMW"),
            ("volks wagen golf fiyat listesi", "Volkswagen Golf", "Volkswagen"),
            ("tog te on iks teslimat tarihi nedir?", "Togg T10X", "Togg"),
            ("audi a3 sportback stok durumu", "Audi A3 Sportback", "Audi"),
        ],
    )
    def test_asr_mapping_canonical_vehicles(
        self, asr, raw_transcript, expected_canonical_vehicle, expected_brand
    ):
        result = asr.map_asr_to_canonical(raw_transcript)
        assert expected_canonical_vehicle.lower() in result["canonical_text"].lower()
        if expected_brand:
            assert result["detected_brand"] == expected_brand

    def test_canonical_brand_lookup(self, asr):
        assert asr.get_canonical_brand("bmv") == "BMW"
        assert asr.get_canonical_brand("pöjo") == "Peugeot"
        assert asr.get_canonical_brand("reno") == "Renault"
        assert asr.get_canonical_brand("volks wagen") == "Volkswagen"

    def test_canonicalize_asr_text_structure(self):
        res = canonicalize_asr_text("pöjo 3008 için randevu alalım")
        assert res["source_text"] == "pöjo 3008 için randevu alalım"
        assert "Peugeot 3008" in res["canonical_text"]
        assert res["detected_brand"] == "Peugeot"
        assert res["detected_model"] == "3008"
        assert res["canonical_vehicle"] == "Peugeot 3008"
        assert "tts_preview" in res
        assert "Pöjo üç bin sekiz" in res["tts_preview"]


# ============================================================================
# 3. 07_TEST_CUMLELERI (81 ALTIN STANDART TESTİ - %100 REGRESYON - sozluk_2026)
# ============================================================================
def load_07_test_cases():
    """07_TEST_CUMLELERI sayfasından 81 test senaryosunu yükler."""
    if not EXCEL_FILE2.exists():
        pytest.skip(f"Test dosyası bulunamadı: {EXCEL_FILE2}")

    df = pd.read_excel(EXCEL_FILE2, sheet_name="07_TEST_CUMLELERI")
    raw_col = [c for c in df.columns if "Ham" in c][0]
    exp_col = [c for c in df.columns if "Beklenen" in c][0]

    cases = []
    for _, row in df.iterrows():
        t_id = str(row["Test ID"])
        cat = str(row["Test kategorisi"])
        raw = str(row[raw_col]) if pd.notna(row[raw_col]) else ""
        exp = str(row[exp_col]) if pd.notna(row[exp_col]) else ""
        cases.append((t_id, cat, raw, exp))
    return cases


class TestGoldStandard07Regression:
    """FreyaTTS 2026 Kataloğu 07_TEST_CUMLELERI Regresyon Test Seti (profile='sozluk_2026')"""

    @pytest.mark.parametrize(
        "test_id,category,raw_text,expected_tts",
        load_07_test_cases(),
    )
    def test_all_81_gold_standard_sentences(
        self, normalizer, test_id, category, raw_text, expected_tts
    ):
        normalized = normalizer.normalize(raw_text, profile="sozluk_2026")
        assert normalized == expected_tts, (
            f"Hata [{test_id} - {category}]:\n"
            f"  Girdi   : {raw_text}\n"
            f"  Beklenen: {expected_tts}\n"
            f"  Üretilen: {normalized}"
        )


# ============================================================================
# 4. DOSYA 1 (CUMLE_TESTLERI) NORMALIZASYON VE KÖŞE DURUMLAR (profile='sezer')
# ============================================================================
def load_sezer_norm_cases():
    """F1 CUMLE_TESTLERI sayfasından 72 Normalizasyon / regresyon senaryosunu yükler."""
    if not EXCEL_FILE1.exists():
        pytest.skip(f"Test dosyası bulunamadı: {EXCEL_FILE1}")

    df = pd.read_excel(EXCEL_FILE1, sheet_name="CUMLE_TESTLERI")
    norm_df = df[df.iloc[:, 6] == "Normalizasyon / regresyon"]
    cases = []
    for _, row in norm_df.iterrows():
        t_id = str(row.iloc[0])
        raw = str(row.iloc[2])
        exp = str(row.iloc[3])
        cases.append((t_id, raw, exp))
    return cases


def load_sezer_kose_cases():
    """F1 CUMLE_TESTLERI sayfasından 32 Elle belirlenmiş köşe durum senaryosunu yükler."""
    if not EXCEL_FILE1.exists():
        pytest.skip(f"Test dosyası bulunamadı: {EXCEL_FILE1}")

    df = pd.read_excel(EXCEL_FILE1, sheet_name="CUMLE_TESTLERI")
    kose_df = df[df.iloc[:, 6] == "Elle belirlenmiş köşe durum"]
    cases = []
    for _, row in kose_df.iterrows():
        t_id = str(row.iloc[0])
        raw = str(row.iloc[2])
        exp = str(row.iloc[3])
        cases.append((t_id, raw, exp))
    return cases


class TestSezerF1Regression:
    """F1 Dosyası Sezer Normalizasyon ve Köşe Durumlar Regresyon Seti (profile='sezer')"""

    @pytest.mark.parametrize(
        "test_id,raw_text,expected_tts",
        load_sezer_norm_cases(),
    )
    def test_all_72_sezer_normalizations(
        self, normalizer, test_id, raw_text, expected_tts
    ):
        normalized = normalizer.normalize(raw_text, profile="sezer")
        assert normalized == expected_tts, (
            f"Hata [{test_id}]:\n"
            f"  Girdi   : {raw_text}\n"
            f"  Beklenen: {expected_tts}\n"
            f"  Üretilen: {normalized}"
        )

    @pytest.mark.parametrize(
        "test_id,raw_text,expected_tts",
        load_sezer_kose_cases(),
    )
    def test_all_32_sezer_kose_cases(
        self, normalizer, test_id, raw_text, expected_tts
    ):
        normalized = normalizer.normalize(raw_text, profile="sezer")
        assert normalized == expected_tts, (
            f"Hata [{test_id}]:\n"
            f"  Girdi   : {raw_text}\n"
            f"  Beklenen: {expected_tts}\n"
            f"  Üretilen: {normalized}"
        )


# ============================================================================
# 5. KELİME SINIRI VE AŞIRI DEĞİŞTİRME YALITIMI (RULE R21)
# ============================================================================
class TestWordBoundaryIsolation:
    """Kelime sınırları ve yanlış hece/harf eşleşmesi yalıtım testleri (Rule R21)"""

    def test_a3_never_replaces_inside_astra(self, normalizer):
        text = "Opel Astra 1.2 benzinli araç."
        res = normalizer.normalize(text)
        assert "Astra" in res or "astra" in res.lower()
        assert "A üç" not in res
        assert "Ey üç" not in res

    def test_ev_never_replaces_inside_ev3(self, normalizer):
        text = "Kia EV3 için kredi kampanyası var mı?"
        res = normalizer.normalize(text)
        assert "Kia İ vi üç için" in res
        assert "İ vi üç" in res

    def test_suv_never_replaces_inside_c_suv(self, normalizer):
        text = "Terim: C-SUV."
        res = normalizer.normalize(text, profile="sozluk_2026")
        assert res == "Terim: Se es yu vi."

    def test_sezer_uppercase_stress_trap(self, normalizer):
        text = "Chevrolet Aveo test sürüşü."
        res = normalizer.normalize(text)
        assert "ŞEV-ro-le" not in res
        assert "Şevrole" in res or "Şevrolet" in res


# ============================================================================
# 6. FREYATTS 92 KARAKTER VOCAB UYUMLULUĞU
# ============================================================================
class TestVocabCompliance:
    """Tüm normalleştirilmiş çıktıların 92 karakterlik FreyaTTS sözlüğüne uygunluğu"""

    @pytest.mark.parametrize(
        "test_id,category,raw_text,expected_tts",
        load_07_test_cases(),
    )
    def test_vocab_characters_in_normalized_text(
        self, normalizer, freya_vocab, test_id, category, raw_text, expected_tts
    ):
        normalized = normalizer.normalize(raw_text, profile="sozluk_2026")
        unsupported_chars = [ch for ch in normalized if ch not in freya_vocab]
        assert not unsupported_chars, (
            f"[{test_id}] Model sözlüğünde (92 karakter) bulunmayan simgeler tespit edildi: {unsupported_chars}\n"
            f"Metin: {normalized}"
        )
