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

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.automotive_terminology import (
    analyze_acoustic_report_layer_attribution,
    canonicalize_asr_text,
    match_catalog_vehicle,
    run_terminology_verification_suite,
)
from backend.db import Base, Vehicle
from backend.turkish_plate import TurkishPlateParser, extract_plate


def test_canonicalize_asr_text_recovers_phonetic_brands_models_and_codes():
    r1 = canonicalize_asr_text("Pejo 3008 ile Reno Megan için ekspertiz randevusu")
    assert "Peugeot" in r1["canonical_text"]
    assert "Renault" in r1["canonical_text"]
    assert "Megane" in r1["canonical_text"]
    assert len(r1["applied_mappings"]) >= 3

    r2 = canonicalize_asr_text("Nisan Kaşkay 1.5 te se i de se ge arıza var mı?")
    assert "Nissan" in r2["canonical_text"]
    assert "Qashqai" in r2["canonical_text"]
    assert "TSI" in r2["canonical_text"]
    assert "DSG" in r2["canonical_text"]

    r3 = canonicalize_asr_text("Hunday Tukson için p sıfır üç yüz hata kodu çıktı")
    assert "Hyundai" in r3["canonical_text"]
    assert "Tucson" in r3["canonical_text"]
    assert "P0300" in r3["canonical_text"]

    r4 = canonicalize_asr_text("Force wagon puzzle ve Sitroen için fiyat")
    assert "Volkswagen Passat" in r4["canonical_text"]
    assert "Citroën" in r4["canonical_text"]


def test_canonicalize_asr_text_protects_dates_and_plain_turkish_words():
    res = canonicalize_asr_text("3 Nisan sabahı için bir randevu istiyorum, teşekkürler")
    assert "Nissan" not in res["canonical_text"]
    assert "3 Nisan" in res["canonical_text"]
    assert res["applied_mappings"] == []

    # Ancak model bağlamında "Nisan Kaşkay" kurtarılmalı
    res_car = canonicalize_asr_text("Nisan Kaşkay aracım için yarın sabah")
    assert "Nissan" in res_car["canonical_text"]
    assert "Qashqai" in res_car["canonical_text"]


def test_match_catalog_vehicle_blocks_false_positive_numbers_and_detects_brand_only():
    vehicles = [
        SimpleNamespace(id="v-passat", description="Volkswagen Passat 1.5 TSI", plate=""),
        SimpleNamespace(id="v-corolla", description="Toyota Corolla", plate=""),
        SimpleNamespace(id="v-megane", description="Renault Megane", plate=""),
    ]

    # "Bir randevu istiyorum" içindeki "bir", "1.5 TSI" -> "bir nokta beş" içinden eşleşmemeli
    fp = match_catalog_vehicle(vehicles, "Bir randevu istiyorum")
    assert fp["matched_vehicle"] is None
    assert fp["candidates"] == []
    assert fp["brand_only_detected"] is None

    # Marka-tekil ("Toyota için randevu") tam model verilmeden marka sinyali vermeli
    brand_only = match_catalog_vehicle(vehicles, "Toyota için yarın sabah uygun musunuz?")
    assert brand_only["brand_only_detected"] == "Toyota"
    assert brand_only["matched_vehicle"] is None

    # Model söylendiğinde doğrudan araç eşleşmeli ve brand_only_detected None olmalı
    exact = match_catalog_vehicle(vehicles, "Korola için yarın sabah ekspertiz")
    assert exact["matched_vehicle"] is not None
    assert exact["matched_vehicle"].id == "v-corolla"
    assert exact["brand_only_detected"] is None

    # Fonetik bozuk marka+model katalogla eşleşebilmeli
    phonetic_match = match_catalog_vehicle(vehicles, "Reno Megan ekspertiz istiyorum")
    assert phonetic_match["matched_vehicle"] is not None
    assert phonetic_match["matched_vehicle"].id == "v-megane"


def test_turkish_plate_parser_handles_whisper_variants_and_de_trap():
    # Whisper harfleri bitişik grup olarak yazarsa:
    assert extract_plate("otuz dört ABC yüz yirmi üç") == "34 ABC 123"
    parsed = TurkishPlateParser.parse_spoken("otuz dört ABD yüz yirmi üç")
    assert parsed is not None
    assert parsed.plate == "34 ABD 123"

    # Kesme işaretsiz ASR çıktısında plaka düzeltme:
    c1 = TurkishPlateParser.correct_plate("34 ABC 123", "C değil Denizlinin Dsi")
    assert c1 is not None and c1.is_correction
    assert c1.plate == "34 ABD 123"

    # "değil de" bağlacındaki "de", harf "D" olarak yanlış yakalanmamalı:
    c2 = TurkishPlateParser.correct_plate("34 ABC 123", "B değil de Ankara'nın A'sı")
    assert c2 is not None and c2.is_correction
    assert c2.plate == "34 AAC 123"

    # "yerine" ile düzeltme:
    c3 = TurkishPlateParser.correct_plate("34 ABC 123", "C yerine Denizli'nin D'si olsun")
    assert c3 is not None and c3.is_correction
    assert c3.plate == "34 ABD 123"


def test_acoustic_layer_attribution_stays_honest_about_strict_vs_recovered():
    synthetic_report = {
        "measured_at": "2026-11-25T00:00:00Z",
        "gate_channel": "telephony_8k",
        "sample_count": 2,
        "rows": [
            {
                "id": "row-1",
                "text": "Peugeot 3008 aracım var.",
                "channels": {
                    "telephony_8k": {
                        "terms_total": 1,
                        "terms_correct": 0,
                        "terms_missed": ["peugeot"],
                        "transcript": "Pejo 3008 aracım var.",
                    }
                },
            },
            {
                "id": "row-2",
                "text": "Volkswagen DSG ve TDI kontrolü.",
                "channels": {
                    "telephony_8k": {
                        "terms_total": 3,
                        "terms_correct": 2,
                        "terms_missed": ["dsg"],
                        "transcript": "Volkswagen tamamen anlaşılmaz kelime ve TDI kontrolü.",
                    }
                },
            },
        ],
    }

    attr = analyze_acoustic_report_layer_attribution(synthetic_report)
    assert attr["available"] is True
    assert attr["terms_total"] == 4
    # Ham ASR: 4 terimden 2'si doğru (%50.0) — dürüst ham metrik gizlenmez
    assert attr["strict_correct"] == 2
    assert attr["strict_term_accuracy_pct"] == 50.0
    # Kanonik kurtarma: "Pejo" -> "Peugeot" kurtarılır (+1), "tamamen anlaşılmaz" kurtarılamaz
    assert attr["asr_phonetic_recoverable_count"] == 1
    assert attr["true_pronunciation_or_acoustic_miss_count"] == 1
    assert attr["canonical_recovered_correct"] == 3
    assert attr["post_canonical_accuracy_pct"] == 75.0
    assert attr["per_term_breakdown"]["peugeot"]["recovered_by_canonical"] == 1
    assert attr["per_term_breakdown"]["dsg"]["true_acoustic_or_tts_miss"] == 1


def test_terminology_verification_suite_with_isolated_db(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "term_suite.db"))
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(engine, expire_on_commit=False)
    try:
        with SessionLocal() as db:
            db.add_all([
                Vehicle(description="Toyota Corolla", plate=""),
                Vehicle(description="Volkswagen Passat 1.5 TSI", plate=""),
                Vehicle(description="Renault Megane", plate=""),
            ])
            db.commit()

            suite = run_terminology_verification_suite(db=db)
            assert suite["total"] >= 15
            assert suite["failed"] == 0, f"Başarısız vakalar: {[c for c in suite['cases'] if not c['passed']]}"
            assert suite["pass_rate_pct"] == 100.0
            case_ids = {c["id"] for c in suite["cases"]}
            assert "TERM-CAT-FP-GUARD" in case_ids
            assert "TERM-PLATE-03" in case_ids
    finally:
        engine.dispose()
