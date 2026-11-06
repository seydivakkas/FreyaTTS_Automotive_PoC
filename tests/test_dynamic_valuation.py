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

from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from backend.db import Conversation, Session, VehicleValuation
from backend.dynamic_valuation_calculator import (
    calculate_and_save_valuation,
    calculate_body_condition_deductions,
    calculate_dynamic_valuation,
    calculate_km_adjustment,
    calculate_tramer_deduction,
    get_base_benchmark_price,
    list_vehicle_valuations,
    parse_spoken_valuation_query,
)
from backend.main import app


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


# 1. Baz Benchmark Fiyatı Hesaplama Testi
def test_get_base_benchmark_price():
    # 2020 Passat baz fiyatı
    p_2020 = get_base_benchmark_price("VOLKSWAGEN", "PASSAT", 2020)
    assert p_2020 >= 1000000.0

    # 2022 Passat daha yeni olduğundan daha yüksek olmalıdır
    p_2022 = get_base_benchmark_price("VOLKSWAGEN", "PASSAT", 2022)
    assert p_2022 > p_2020

    # 2018 Passat daha eski olduğundan daha düşük olmalıdır
    p_2018 = get_base_benchmark_price("VOLKSWAGEN", "PASSAT", 2018)
    assert p_2018 < p_2020

    # Bilinmeyen marka fallback kontrolü
    p_unknown = get_base_benchmark_price("BILINMEYEN", "MODEL", 2020)
    assert p_unknown >= 500000.0


# 2. Kilometre Amortismanı Testi
def test_calculate_km_adjustment():
    # Yüksek km: 2020 model araç için 2026'da (6 yaş) beklenen km: 6 * 17500 = 105.000 km
    # 180.000 km fazlalık içerdiğinden negatif oran olmalı
    adj_high, info_high = calculate_km_adjustment(180000, 2020)
    assert adj_high < 0.0
    assert info_high["delta_km"] > 0

    # Düşük km: 35.000 km (prim almalı)
    adj_low, info_low = calculate_km_adjustment(35000, 2020)
    assert adj_low > 0.0
    assert info_low["delta_km"] < 0


# 3. Kaporta Hasar Matrisi Testi
def test_calculate_body_condition_deductions():
    # Hatasız / Orijinal araç
    ratio_clean, details_clean = calculate_body_condition_deductions({})
    assert ratio_clean == 0.0
    assert len(details_clean) == 0

    # Tavan değişen ve kaput boyalı
    panels = {
        "tavan": "degisen",
        "kaput": "boyali",
        "sol_on_camurluk": "degisen",
    }
    ratio_dmg, details_dmg = calculate_body_condition_deductions(panels)
    assert ratio_dmg < -0.20  # Tavan değişen tek başına -%22
    assert "tavan" in details_dmg
    assert "kaput" in details_dmg
    assert "sol_on_camurluk" in details_dmg


# 4. Tramer Hasar Kaydı Testi
def test_calculate_tramer_deduction():
    # Hasar kaydı yok
    r_zero, _ = calculate_tramer_deduction(0.0, False, 1000000.0)
    assert r_zero == 0.0

    # Küçük hasar (10.000 TL)
    r_small, _ = calculate_tramer_deduction(10000.0, False, 1000000.0)
    assert r_small == -0.015

    # Ağır hasar / Pert kaydı (Doğrudan -%35)
    r_heavy, info_heavy = calculate_tramer_deduction(45000.0, True, 1000000.0)
    assert r_heavy == -0.35
    assert info_heavy["is_heavy_damage"] is True


# 5. Tam Dinamik Değerleme ve Takas Teklifi Testi
def test_calculate_dynamic_valuation():
    val = calculate_dynamic_valuation(
        brand="Volkswagen",
        model="Passat",
        model_year=2021,
        mileage_km=85000,
        body_panels={"kaput": "boyali", "sol_on_camurluk": "degisen"},
        tramer_amount_tl=12000.0,
        is_heavy_damage=False,
        plate="34 ABC 789",
    )

    assert val.estimated_market_value_tl > 500000.0
    # Nakit teklif pazar değerinin %90'ı civarında olmalıdır
    assert val.cash_buy_offer_tl < val.estimated_market_value_tl
    # Takas teklifi nakit tekliften daha yüksek olmalıdır (takas desteği)
    assert val.trade_in_offer_tl > val.cash_buy_offer_tl
    assert val.trade_in_offer_tl <= val.estimated_market_value_tl
    # Aralık kontrolü
    assert val.valuation_range_min_tl < val.estimated_market_value_tl < val.valuation_range_max_tl
    # Sesli asistan konuşma metni
    assert "34 ABC 789" in val.summary_pitch
    assert "takas desteğiyle" in val.summary_pitch


# 6. Doğal Dil ve Sesli Sorgu Ayrıştırma Testi
def test_parse_spoken_valuation_query():
    spoken = "2021 model Passat 85 binde, sadece sol ön çamurluk boyalı, 10 bin tramer var"
    parsed = parse_spoken_valuation_query(spoken)

    assert parsed["brand"] == "Volkswagen"
    assert parsed["model"] == "Passat"
    assert parsed["model_year"] == 2021
    assert parsed["mileage_km"] == 85000
    assert parsed["tramer_amount_tl"] == 10000.0
    assert "sol_on_camurluk" in parsed["body_panels"]
    assert parsed["is_heavy_damage"] is False

    # Hatasız araç sorgusu
    clean_spoken = "2022 model Renault Megane 40 bin kilometrede hatasız boyasız"
    clean_parsed = parse_spoken_valuation_query(clean_spoken)
    assert clean_parsed["brand"] == "Renault"
    assert clean_parsed["model"] == "Megane"
    assert clean_parsed["mileage_km"] == 40000
    assert len(clean_parsed["body_panels"]) == 0


# 7. Veritabanı Kaydetme ve Listeleme Testi
def test_calculate_and_save_valuation_db():
    c_id = f"conv-val-{uid()[:8]}"
    with Session() as db:
        conv = Conversation(id=c_id, channel="phone", status="active")
        db.add(conv)
        db.commit()

        rec = calculate_and_save_valuation(
            db,
            brand="Peugeot",
            model="3008",
            model_year=2022,
            mileage_km=55000,
            body_panels={"sag_on_kapi": "boyali"},
            tramer_amount_tl=8000.0,
            plate="34 PGT 08",
            conversation_id=c_id,
        )

        assert rec.id.startswith("val-")
        assert rec.brand == "Peugeot"
        assert rec.model == "3008"
        assert rec.plate == "34 PGT 08"
        assert rec.estimated_market_value_tl > 0.0
        assert rec.cash_buy_offer_tl > 0.0
        assert rec.trade_in_offer_tl > rec.cash_buy_offer_tl

        # Listeleme
        items = list_vehicle_valuations(db, limit=10)
        assert any(item.id == rec.id for item in items)


# 8. REST API Uç Noktaları Testi
def test_valuation_api_endpoints(client, auth_headers):
    # 1. POST /api/valuation/calculate
    calc_body = {
        "brand": "Fiat",
        "model": "Egea",
        "model_year": 2022,
        "mileage_km": 45000,
        "body_panels": {"kaput": "boyali"},
        "tramer_amount_tl": 5000.0,
        "plate": "06 EGA 22",
    }
    r1 = client.post("/api/valuation/calculate", json=calc_body, headers=auth_headers)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["estimated_market_value_tl"] > 300000.0
    assert d1["trade_in_offer_tl"] > d1["cash_buy_offer_tl"]
    assert "06 EGA 22" in d1["summary_pitch"]

    # 2. POST /api/valuation/save
    r2 = client.post("/api/valuation/save", json=calc_body, headers=auth_headers)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["id"].startswith("val-")
    assert d2["brand"] == "Fiat"
    assert d2["plate"] == "06 EGA 22"

    # 3. POST /api/valuation/parse-spoken
    spoken_body = {
        "query_text": "2021 model Passat 85 binde sol ön çamurluk değişen",
        "plate": "34 SPK 21",
    }
    r3 = client.post("/api/valuation/parse-spoken", json=spoken_body, headers=auth_headers)
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["model_year"] == 2021
    assert "Passat" in d3["summary_pitch"]
    assert "parsed_query" in d3

    # 4. GET /api/valuation/valuations
    r4 = client.get("/api/valuation/valuations", headers=auth_headers)
    assert r4.status_code == 200
    vals = r4.json()
    assert len(vals) >= 1

    # 5. GET /api/vehicle-valuations (resource listing)
    r5 = client.get("/api/vehicle-valuations", headers=auth_headers)
    assert r5.status_code == 200
    assert len(r5.json()) >= 1

