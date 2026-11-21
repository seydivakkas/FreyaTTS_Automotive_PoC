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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.db import VehicleValuation, now

logger = logging.getLogger("dynamic_valuation_calculator")

CURRENT_YEAR = 2026
BENCHMARK_ANNUAL_KM = 17500

# Türkiye İkinci El Pazarı Popüler Araç Referans Baz Fiyatları (2020 Yılı Baz Alınarak TL Cinsinden)
MODEL_BASELINES_2020: Dict[str, Dict[str, float]] = {
    "VOLKSWAGEN": {
        "PASSAT": 1250000.0,
        "GOLF": 1050000.0,
        "POLO": 750000.0,
        "TIGUAN": 1400000.0,
        "T-ROC": 1150000.0,
        "DEFAULT": 1100000.0,
    },
    "RENAULT": {
        "MEGANE": 780000.0,
        "CLIO": 620000.0,
        "CAPTUR": 820000.0,
        "TALISMAN": 950000.0,
        "KADJAR": 880000.0,
        "DEFAULT": 720000.0,
    },
    "FIAT": {
        "EGEA": 580000.0,
        "DOBLO": 520000.0,
        "FIORINO": 440000.0,
        "500X": 750000.0,
        "DEFAULT": 550000.0,
    },
    "FORD": {
        "FOCUS": 920000.0,
        "FIESTA": 680000.0,
        "PUMA": 950000.0,
        "KUGA": 1350000.0,
        "DEFAULT": 900000.0,
    },
    "PEUGEOT": {
        "208": 680000.0,
        "2008": 950000.0,
        "3008": 1350000.0,
        "5008": 1550000.0,
        "308": 820000.0,
        "DEFAULT": 950000.0,
    },
    "TOYOTA": {
        "COROLLA": 950000.0,
        "YARIS": 720000.0,
        "C-HR": 1100000.0,
        "RAV4": 1850000.0,
        "DEFAULT": 950000.0,
    },
    "HONDA": {
        "CIVIC": 1150000.0,
        "CITY": 720000.0,
        "CR-V": 1700000.0,
        "DEFAULT": 1100000.0,
    },
    "HYUNDAI": {
        "i20": 650000.0,
        "i10": 520000.0,
        "TUCSON": 1380000.0,
        "ELANTRA": 850000.0,
        "BAYON": 780000.0,
        "DEFAULT": 800000.0,
    },
    "OPEL": {
        "ASTRA": 820000.0,
        "CORSA": 680000.0,
        "MOKKA": 980000.0,
        "GRANDLAND": 1250000.0,
        "DEFAULT": 850000.0,
    },
    "SKODA": {
        "OCTAVIA": 1150000.0,
        "SUPERB": 1400000.0,
        "FABIA": 680000.0,
        "KAMIQ": 950000.0,
        "KAROQ": 1250000.0,
        "DEFAULT": 1100000.0,
    },
    "BMW": {
        "3 SERISI": 1850000.0,
        "1 SERISI": 1350000.0,
        "5 SERISI": 2600000.0,
        "X1": 1650000.0,
        "DEFAULT": 1800000.0,
    },
    "MERCEDES": {
        "C SERISI": 1950000.0,
        "A SERISI": 1400000.0,
        "E SERISI": 2800000.0,
        "CLA": 1600000.0,
        "DEFAULT": 1900000.0,
    },
}

# Parça Bazlı Değer Düşüm Oranları (Panel Depreciation Matrix)
# Negatif yüzdelik değerler: Örn. tavan değişen: -22%
PANEL_DEPRECIATION_RATES: Dict[str, Dict[str, float]] = {
    "tavan": {
        "orijinal": 0.0,
        "lokal": -0.06,
        "boyali": -0.12,
        "degisen": -0.22,
    },
    "kaput": {
        "orijinal": 0.0,
        "lokal": -0.02,
        "boyali": -0.045,
        "degisen": -0.085,
    },
    "bagaj": {
        "orijinal": 0.0,
        "lokal": -0.015,
        "boyali": -0.035,
        "degisen": -0.06,
    },
    "sol_on_camurluk": {
        "orijinal": 0.0,
        "lokal": -0.008,
        "boyali": -0.018,
        "degisen": -0.035,
    },
    "sag_on_camurluk": {
        "orijinal": 0.0,
        "lokal": -0.008,
        "boyali": -0.018,
        "degisen": -0.035,
    },
    "sol_arka_camurluk": {
        "orijinal": 0.0,
        "lokal": -0.010,
        "boyali": -0.022,
        "degisen": -0.040,
    },
    "sag_arka_camurluk": {
        "orijinal": 0.0,
        "lokal": -0.010,
        "boyali": -0.022,
        "degisen": -0.040,
    },
    "sol_on_kapi": {
        "orijinal": 0.0,
        "lokal": -0.010,
        "boyali": -0.025,
        "degisen": -0.045,
    },
    "sag_on_kapi": {
        "orijinal": 0.0,
        "lokal": -0.010,
        "boyali": -0.025,
        "degisen": -0.045,
    },
    "sol_arka_kapi": {
        "orijinal": 0.0,
        "lokal": -0.010,
        "boyali": -0.025,
        "degisen": -0.045,
    },
    "sag_arka_kapi": {
        "orijinal": 0.0,
        "lokal": -0.010,
        "boyali": -0.025,
        "degisen": -0.045,
    },
    "sasi_direk": {
        "orijinal": 0.0,
        "hasarli": -0.28,
        "onarilmis": -0.25,
    },
}


# Değerlemenin dayanağı: sabit 2020 tablosu; canlı piyasa verisi DEĞİLDİR
ESTIMATE_BASIS = "sabit 2020 tablosu, piyasa verisi değil"


@dataclass
class ValuationDetail:
    brand: str
    model: str
    model_year: int
    mileage_km: int
    base_benchmark_tl: float
    km_adjustment_ratio: float
    body_damage_ratio: float
    tramer_deduction_ratio: float
    total_depreciation_ratio: float
    estimated_market_value_tl: float
    cash_buy_offer_tl: float
    trade_in_offer_tl: float
    valuation_range_min_tl: float
    valuation_range_max_tl: float
    summary_pitch: str
    breakdown: Dict[str, Any] = field(default_factory=dict)
    estimate_basis: str = ESTIMATE_BASIS


def get_base_benchmark_price(brand: str, model: str, year: int) -> float:
    """
    Marka, model ve model yılına göre enflasyon / yaş düzeltmeli baz pazar fiyatını hesaplar.
    """
    b_upper = brand.strip().upper()
    m_upper = model.strip().upper()

    brand_dict = MODEL_BASELINES_2020.get(b_upper)
    if not brand_dict:
        # Genel kategori baz fiyatı
        base_2020 = 850000.0
    else:
        # Model eşleşmesi ara
        base_2020 = None
        for k, v in brand_dict.items():
            if k in m_upper or m_upper in k:
                base_2020 = v
                break
        if base_2020 is None:
            base_2020 = brand_dict.get("DEFAULT", 850000.0)

    # Model yılı yaş çarpanı (2020 yılı baz):
    # 2020 sonrası her yıl için +%10, 2020 öncesi her yıl için -%8
    year_diff = year - 2020
    if year_diff >= 0:
        year_multiplier = (1.0 + 0.10) ** year_diff
    else:
        year_multiplier = (1.0 - 0.08) ** abs(year_diff)

    benchmark_price = round(base_2020 * year_multiplier, -3)
    return max(200000.0, benchmark_price)


def calculate_km_adjustment(actual_km: int, model_year: int) -> Tuple[float, Dict[str, Any]]:
    """
    Kilometre amortismanı / düşümü hesabı.
    Yıllık standart: 17.500 km.
    Sapma oranına göre değer kaybı veya düşük km primi.
    """
    age = max(1, CURRENT_YEAR - model_year)
    expected_km = age * BENCHMARK_ANNUAL_KM
    delta_km = actual_km - expected_km

    # Her 10.000 km fazlalık için -%0.8 amortisman
    if delta_km > 0:
        ratio = -min(0.25, (delta_km / 10000.0) * 0.008)
    else:
        # Düşük km primi (+%0.6 her 10.000 km için, max +%10)
        ratio = min(0.10, (abs(delta_km) / 10000.0) * 0.006)

    info = {
        "actual_km": actual_km,
        "expected_km": expected_km,
        "delta_km": delta_km,
        "adjustment_percent": round(ratio * 100, 2),
    }
    return ratio, info


def calculate_body_condition_deductions(
    body_panels: Dict[str, str],
) -> Tuple[float, Dict[str, Any]]:
    """
    Kaporta-boya parça matrisine göre toplam değer kaybı yüzdesini hesaplar.
    """
    total_ratio = 0.0
    panel_details = {}

    for panel, state in body_panels.items():
        panel_key = panel.lower().strip()
        state_key = state.lower().strip()

        # Eşleşen panel kalıbını bul
        target_panel = None
        for pk in PANEL_DEPRECIATION_RATES:
            if pk == panel_key or pk in panel_key:
                target_panel = pk
                break

        if target_panel:
            rates = PANEL_DEPRECIATION_RATES[target_panel]
            # Durum eşleşmesi
            applied_rate = 0.0
            if "degisen" in state_key:
                applied_rate = rates.get("degisen", 0.0)
            elif "lokal" in state_key:
                applied_rate = rates.get("lokal", 0.0)
            elif "boya" in state_key:
                applied_rate = rates.get("boyali", 0.0)
            elif "hasar" in state_key:
                applied_rate = rates.get("hasarli", -0.25)
            elif "onar" in state_key:
                applied_rate = rates.get("onarilmis", -0.20)

            total_ratio += applied_rate
            if applied_rate != 0.0:
                panel_details[target_panel] = {
                    "state": state_key,
                    "discount_percent": round(applied_rate * 100, 2),
                }

    # Toplam kaporta indirimi en fazla -%65 olabilir (ağır hasar hariç)
    total_ratio = max(-0.65, total_ratio)
    return total_ratio, panel_details


def calculate_tramer_deduction(
    tramer_tl: float,
    is_heavy_damage: bool,
    base_price: float,
) -> Tuple[float, Dict[str, Any]]:
    """
    Tramer hasar kaydı ve ağır hasar (pert) statüsüne göre değer düşümü hesabı.
    """
    if is_heavy_damage:
        # Ağır hasar kayıtlı araçlarda sabit -%35 düşüm
        return -0.35, {
            "is_heavy_damage": True,
            "tramer_tl": tramer_tl,
            "discount_percent": -35.0,
            "reason": "Ağır Hasar / Pert Kaydı",
        }

    if tramer_tl <= 0:
        return 0.0, {"is_heavy_damage": False, "tramer_tl": 0.0, "discount_percent": 0.0}

    # Normal hasar kaydı baremleri
    if tramer_tl <= 15000:
        ratio = -0.015
    elif tramer_tl <= 50000:
        ratio = -0.035
    elif tramer_tl <= 150000:
        ratio = -0.070
    else:
        ratio = -0.120

    return ratio, {
        "is_heavy_damage": False,
        "tramer_tl": tramer_tl,
        "discount_percent": round(ratio * 100, 2),
    }


def calculate_dynamic_valuation(
    *,
    brand: str,
    model: str,
    model_year: int,
    mileage_km: int,
    body_panels: Optional[Dict[str, str]] = None,
    tramer_amount_tl: float = 0.0,
    is_heavy_damage: bool = False,
    plate: str = "",
) -> ValuationDetail:
    """
    Aracın piyasa değerini, nakit alış teklifini ve takas destekli değerleme teklifini
    dinamik algoritma ile hesaplar.
    """
    panels = body_panels or {}
    base_price = get_base_benchmark_price(brand, model, model_year)

    km_ratio, km_info = calculate_km_adjustment(mileage_km, model_year)
    body_ratio, body_info = calculate_body_condition_deductions(panels)
    tramer_ratio, tramer_info = calculate_tramer_deduction(
        tramer_amount_tl, is_heavy_damage, base_price
    )

    # Toplam düzeltme katsayısı
    total_multiplier = 1.0 + km_ratio + body_ratio + tramer_ratio
    # Değer en az baz fiyatın %20'si kalabilir
    total_multiplier = max(0.20, total_multiplier)

    market_value = round(base_price * total_multiplier, -3)
    cash_offer = round(market_value * 0.90, -3)       # %10 bayi marjı & stok riski
    trade_in_offer = round(market_value * 0.94, -3)   # +%4 takas teşviki

    range_min = round(market_value * 0.96, -3)
    range_max = round(market_value * 1.04, -3)

    # Sesli Asistan Sunum Metni (Telefon / Playout için)
    plate_mention = f"{plate} plakalı " if plate else ""
    speech_pitch = (
        f"{plate_mention}{model_year} model {brand} {model} aracınızın "
        f"değeri sabit bir tabloya göre yaklaşık kaba hesapla {int(market_value):,} Türk lirasıdır; "
        f"bu canlı piyasa verisi değildir. "
        f"Şubemizde takasa vermek isterseniz {int(trade_in_offer):,} Türk lirası takas desteğiyle "
        f"değerlendirebiliyoruz. Nihai teklifimiz fiziki ekspertiz ve lift kontrolü sonrasında netleşecektir."
    ).replace(",", ".")

    breakdown = {
        "base_benchmark_price_tl": base_price,
        "km_analysis": km_info,
        "body_condition_analysis": body_info,
        "tramer_analysis": tramer_info,
        "total_depreciation_percent": round((1.0 - total_multiplier) * 100, 2),
    }

    return ValuationDetail(
        brand=brand,
        model=model,
        model_year=model_year,
        mileage_km=mileage_km,
        base_benchmark_tl=base_price,
        km_adjustment_ratio=km_ratio,
        body_damage_ratio=body_ratio,
        tramer_deduction_ratio=tramer_ratio,
        total_depreciation_ratio=1.0 - total_multiplier,
        estimated_market_value_tl=market_value,
        cash_buy_offer_tl=cash_offer,
        trade_in_offer_tl=trade_in_offer,
        valuation_range_min_tl=range_min,
        valuation_range_max_tl=range_max,
        summary_pitch=speech_pitch,
        breakdown=breakdown,
    )


def parse_spoken_valuation_query(text: str) -> Dict[str, Any]:
    """
    Telefon görüşmesinde müşterinin doğal dille söylediği araç bilgilerini ayıklar.
    Örnek:
      "2021 model Passat 85 binde, sadece sol ön çamurluk boyalı, 10 bin tramer var"
    """
    if not text:
        return {"missing_fields": ["brand", "model", "model_year", "mileage_km"]}

    raw = text.lower()

    # 1. Yıl Tespiti
    year_match = re.search(r"\b(20[0-2][0-9]|199[0-9])\b", raw)
    year = int(year_match.group(1)) if year_match else None  # söylenmediyse uydurulmaz

    # 2. Marka & Model Tespiti
    brand = None
    model = None
    for b in MODEL_BASELINES_2020:
        if b.lower() in raw:
            brand = b
            for m in MODEL_BASELINES_2020[b]:
                if m.lower() in raw and m != "DEFAULT":
                    model = m
                    break
            break

    if brand is None:
        # Marka söylenmedi ama model adı geçiyorsa (örn. "Passat") marka metinden çıkarılır
        for b, models_ in MODEL_BASELINES_2020.items():
            hit = next((m for m in models_ if m != "DEFAULT" and m.lower() in raw), None)
            if hit:
                brand, model = b, hit
                break

    # 3. Tramer Tespiti (Önce Tramer taranmalı ki km aramasıyla çakışmasın)
    tramer_tl = 0.0
    raw_for_km = raw

    # "10 bin tramer", "10 bin tl tramer", "10 bin trameri var", "10.000 tramer", "10 bin tl hasar kaydı"
    tramer_match = re.search(r"\b(\d{1,3})\s*(?:bin)?\s*(?:tl|lira)?\s*(?:tramer[a-z]*|hasar(?:\s*kaydı)?)\b", raw)
    if tramer_match:
        val = int(tramer_match.group(1))
        matched_str = tramer_match.group(0)
        if "bin" in matched_str or val < 500:
            tramer_tl = float(val * 1000)
        else:
            tramer_tl = float(val)
        start, end = tramer_match.span()
        raw_for_km = raw[:start] + " " * (end - start) + raw[end:]
    else:
        tramer_full = re.search(r"(?:tramer|hasar\s*kaydı)[:\s]*(\d{1,3})[.,]?(\d{3})\s*(?:tl|lira)?", raw)
        if tramer_full:
            tramer_tl = float(tramer_full.group(1) + tramer_full.group(2))
            start, end = tramer_full.span()
            raw_for_km = raw[:start] + " " * (end - start) + raw[end:]

    # 4. Kilometre Tespiti
    km = None  # söylenmediyse uydurulmaz
    # "85 binde", "85 bindeydi", "140 bin km", "85.000 km", "120000 km", "85k"
    km_match = re.search(r"\b(\d{1,3})\s*(?:bin(?:de|deydi|deymiş|i|deymis)?|k)\b", raw_for_km)
    if km_match:
        km = int(km_match.group(1)) * 1000
    else:
        km_full = re.search(r"\b(\d{2,3})[.,]?(\d{3})\s*(?:km|kilometre(?:de)?)?\b", raw_for_km)
        if km_full:
            km = int(km_full.group(1) + km_full.group(2))

    # 5. Ağır Hasar Tespiti
    is_heavy = bool(re.search(r"\b(ağır\s*hasar|pert|pert\s*kayıtlı)\b", raw) and "yok" not in raw)

    # 6. Kaporta Parçaları
    panels: Dict[str, str] = {}
    if "hatasız" in raw or "boyasız" in raw:
        pass
    else:
        if "tavan" in raw:
            if "değişen" in raw:
                panels["tavan"] = "degisen"
            elif "boya" in raw:
                panels["tavan"] = "boyali"
        if "kaput" in raw:
            if "değişen" in raw:
                panels["kaput"] = "degisen"
            elif "boya" in raw:
                panels["kaput"] = "boyali"
        if "çamurluk" in raw:
            state = "degisen" if "değişen" in raw else "boyali"
            panels["sol_on_camurluk"] = state
        if "kapı" in raw:
            state = "degisen" if "değişen" in raw else "boyali"
            panels["sag_on_kapi"] = state

    missing = [
        name
        for name, val in (("brand", brand), ("model", model), ("model_year", year), ("mileage_km", km))
        if val is None
    ]
    return {
        "brand": brand.title() if brand else None,
        "model": model.title() if model else None,
        "missing_fields": missing,
        "model_year": year,
        "mileage_km": km,
        "body_panels": panels,
        "tramer_amount_tl": tramer_tl,
        "is_heavy_damage": is_heavy,
    }


def calculate_and_save_valuation(
    db: Session,
    *,
    brand: str,
    model: str,
    model_year: int,
    mileage_km: int,
    body_panels: Optional[Dict[str, str]] = None,
    tramer_amount_tl: float = 0.0,
    is_heavy_damage: bool = False,
    plate: str = "",
    conversation_id: Optional[str] = None,
    appointment_id: Optional[str] = None,
) -> VehicleValuation:
    """
    Değerlemeyi hesaplar ve `vehicle_valuations` tablosuna atomik olarak kaydeder.
    """
    val = calculate_dynamic_valuation(
        brand=brand,
        model=model,
        model_year=model_year,
        mileage_km=mileage_km,
        body_panels=body_panels,
        tramer_amount_tl=tramer_amount_tl,
        is_heavy_damage=is_heavy_damage,
        plate=plate,
    )

    record = VehicleValuation(
        id=f"val-{uuid4().hex[:12]}",
        conversation_id=conversation_id,
        appointment_id=appointment_id,
        plate=plate,
        brand=val.brand,
        model=val.model,
        model_year=val.model_year,
        fuel_type="benzin",
        transmission="otomatik",
        mileage_km=val.mileage_km,
        body_condition_json=json.dumps(body_panels or {}, ensure_ascii=False),
        tramer_amount_tl=tramer_amount_tl,
        is_heavy_damage=is_heavy_damage,
        base_benchmark_tl=val.base_benchmark_tl,
        estimated_market_value_tl=val.estimated_market_value_tl,
        cash_buy_offer_tl=val.cash_buy_offer_tl,
        trade_in_offer_tl=val.trade_in_offer_tl,
        valuation_range_min_tl=val.valuation_range_min_tl,
        valuation_range_max_tl=val.valuation_range_max_tl,
        status="quoted",
        created_at=now(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_vehicle_valuations(db: Session, limit: int = 50) -> List[VehicleValuation]:
    """Sistemde kayıtlı değerleme tekliflerini listeler."""
    return list(
        db.scalars(
            select(VehicleValuation)
            .order_by(desc(VehicleValuation.created_at))
            .limit(limit)
        ).all()
    )
