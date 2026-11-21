# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""Otomotiv LLM Fine-Tuning Veriseti Üretim Motoru (Dataset Generator).

Bu modül; sistemin operasyonel diyaloglarından, 280+ fonetik otomotiv teriminden,
sertifikalı ekspertiz paketlerinden (P01-P04), OBD-II arıza kodlarından ve M01-M11
güvenlik kapılarından beslenen Alpaca ve ShareGPT formatında veri setleri üretir.
"""

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Union

from backend.normalizer_rules import BASE_AUTOMOTIVE_LEXICON
from backend.ontology.grounding import CERTIFIED_SERVICE_PACKAGES

# Gerçekçi operasyonel otomotiv diyalog şablonları (M01-M11 uyumlu)
OPERATIONAL_INTENT_TEMPLATES = [
    (
        "Randevu oluşturma",
        "Periyodik bakım için en yakın müsait zamana randevu almak istiyorum.",
        "Tabii, servis takvimimizi kontrol ediyorum. Müsait olan en yakın lift bay için randevunuzu oluşturabilirim. Plakanızı teyit edebilir misiniz?"
    ),
    (
        "Garanti sorgulama",
        "Aracımın fabrika garantisi veya yetkili servis garanti süresi devam ediyor mu?",
        "Sistemimizdeki servis kayıtlarına göre aracınızın garantisi kontrol edilmiştir. Detaylı garanti kapsamınız aktif olarak devam etmektedir."
    ),
    (
        "OBD Arıza tespiti",
        "Gösterge panelinde motor arıza lambası yandı ve {dtc} arıza kodu aldım, ne yapmalıyım?",
        "{dtc} kodu ({dtc_desc}) kritik bir arıza işaretidir. M08 güvenlik protokolü gereğince aracı zorlamadan en yakın lift bayimize getirmenizi öneririz."
    ),
    (
        "Ekspertiz paketi fiyatı",
        "{package_name} ({package_id}) paketinizin içeriği ve güncel ücreti nedir?",
        "{package_name} paketimiz {duration} dakika sürmekte olup güncel fiyatı KDV dahil {price} TL'dir. İçerik: {description}"
    ),
    (
        "Balata ve fren bakım geçmişi",
        "Geçen seferki ön fren balata ve disk değişimi ne zaman ve kaç kilometrede yapılmıştı?",
        "Kullanıcı hafıza kayıtlarımıza göre önceki bakımınız yetkili servisimizde gerçekleştirilmiş olup fren sistemi kontrolleri başarıyla tamamlanmıştır."
    ),
    (
        "Teknisyen sesli dikte ekspertiz",
        "Lift 2'deki aracın ön sol salıncak burcunda aşınma var, fren balatası 3 milimetre kalmış.",
        "Teknisyen diktesi işlendi: Ön sol salıncak burcu aşınmış, fren balatası 3 mm kritik seviyede. WhatsApp ekspertiz raporu taslağına eklendi."
    ),
]

COMMON_DTCS = [
    ("P0300", "Rastgele/Çoklu Silindir Ateşleme Hatası"),
    ("P0420", "Katalizör Sistemi Verimliliği Eşik Altı"),
    ("P0171", "Sistem Çok Fakir (Bank 1)"),
    ("P0700", "Şanzıman Kontrol Sistemi Arızası"),
    ("P0101", "Kütle Hava Akış (MAF) Sensör Performans Sorunu"),
]


def generate_dataset(count: int, format: str = "alpaca", seed: int = 42) -> List[Dict[str, Any]]:
    """Alpaca veya ShareGPT formatında sentetik otomotiv eğitim veri seti üretir."""
    if count < 0:
        raise ValueError("Count cannot be negative")
    if format not in ("alpaca", "sharegpt"):
        raise ValueError(f"Unsupported format: {format}")
    if count == 0:
        return []

    rng = random.Random(seed)
    lexicon_items = list(BASE_AUTOMOTIVE_LEXICON.items())
    package_items = list(CERTIFIED_SERVICE_PACKAGES.items())

    results: List[Dict[str, Any]] = []
    for i in range(count):
        tpl_idx = (i + rng.randint(0, 3)) % len(OPERATIONAL_INTENT_TEMPLATES)
        inst_raw, inp_raw, out_raw = OPERATIONAL_INTENT_TEMPLATES[tpl_idx]

        dtc_code, dtc_desc = COMMON_DTCS[i % len(COMMON_DTCS)]
        pkg_id, pkg_concept = package_items[i % len(package_items)]
        lex_key, lex_val = lexicon_items[(i * 3) % len(lexicon_items)]

        # Değişkenleri yerleştir ve otomotiv ontolojisi ile zenginleştir
        instruction = inst_raw
        inp = inp_raw.format(
            dtc=dtc_code,
            dtc_desc=dtc_desc,
            package_name=pkg_concept.name,
            package_id=pkg_id,
            duration=pkg_concept.duration_min,
            price=pkg_concept.price_tl,
            description=pkg_concept.description,
        )
        context_input = f"{inp} (Parça/Terim: {lex_key.capitalize()}, Hizmet: {pkg_id})"

        out = out_raw.format(
            dtc=dtc_code,
            dtc_desc=dtc_desc,
            package_name=pkg_concept.name,
            package_id=pkg_id,
            duration=pkg_concept.duration_min,
            price=pkg_concept.price_tl,
            description=pkg_concept.description,
        )

        if format == "alpaca":
            results.append({
                "instruction": instruction,
                "input": context_input,
                "output": out,
            })
        else:  # sharegpt
            results.append({
                "conversations": [
                    {"from": "human", "value": f"{instruction}: {context_input}"},
                    {"from": "gpt", "value": out},
                ]
            })

    return results


def export_dataset_file(
    format: str,
    output_path: Union[str, Path],
    count: int = 50,
    seed: int = 42,
) -> Path:
    """Veri setini belirtilen dosya yoluna JSONL formatında kaydeder."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = generate_dataset(count=count, format=format, seed=seed)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path
