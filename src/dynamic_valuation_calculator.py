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

from backend.dynamic_valuation_calculator import (
    MODEL_BASELINES_2020,
    PANEL_DEPRECIATION_RATES,
    ValuationDetail,
    calculate_and_save_valuation,
    calculate_body_condition_deductions,
    calculate_dynamic_valuation,
    calculate_km_adjustment,
    calculate_tramer_deduction,
    get_base_benchmark_price,
    list_vehicle_valuations,
    parse_spoken_valuation_query,
)

__all__ = [
    "MODEL_BASELINES_2020",
    "PANEL_DEPRECIATION_RATES",
    "ValuationDetail",
    "calculate_and_save_valuation",
    "calculate_body_condition_deductions",
    "calculate_dynamic_valuation",
    "calculate_km_adjustment",
    "calculate_tramer_deduction",
    "get_base_benchmark_price",
    "list_vehicle_valuations",
    "parse_spoken_valuation_query",
]

