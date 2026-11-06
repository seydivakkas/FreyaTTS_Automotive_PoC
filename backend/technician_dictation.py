"""Automotive Technician Voice Dictation & Entity Extraction Engine.

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from backend.db import Appointment, InspectionReport, Vehicle
from backend.report_generator import generate_inspection_pdf

logger = logging.getLogger(__name__)

# Standard body parts mapped to findings_json["paint_body"] keys
BODY_PARTS: dict[str, list[str]] = {
    "kaput": [r"\b(?:ön\s+)?kaput\b"],
    "tavan": [r"\btavan\b"],
    "bagaj": [r"\bbagaj(?:\s*kapa[gğ][ıi])?\b"],
    "sag_on_camurluk": [r"\bsa[gğ]\s*(?:ön|on)\s*(?:çamurluk|camurluk)\b"],
    "sol_on_camurluk": [r"\bsol\s*(?:ön|on)\s*(?:çamurluk|camurluk)\b"],
    "sag_arka_camurluk": [r"\bsa[gğ]\s*arka\s*(?:çamurluk|camurluk)\b"],
    "sol_arka_camurluk": [r"\bsol\s*arka\s*(?:çamurluk|camurluk)\b"],
    "sag_on_kapi": [r"\bsa[gğ]\s*(?:ön|on)\s*kap[ıi]\b"],
    "sol_on_kapi": [r"\bsol\s*(?:ön|on)\s*kap[ıi]\b"],
    "sag_arka_kapi": [r"\bsa[gğ]\s*arka\s*kap[ıi]\b"],
    "sol_arka_kapi": [r"\bsol\s*arka\s*kap[ıi]\b"],
}

BODY_PART_LABELS: dict[str, str] = {
    "kaput": "Ön Kaput",
    "tavan": "Tavan",
    "bagaj": "Bagaj Kapağı",
    "sag_on_camurluk": "Sağ Ön Çamurluk",
    "sol_on_camurluk": "Sol Ön Çamurluk",
    "sag_arka_camurluk": "Sağ Arka Çamurluk",
    "sol_arka_camurluk": "Sol Arka Çamurluk",
    "sag_on_kapi": "Sağ Ön Kapı",
    "sol_on_kapi": "Sol Ön Kapı",
    "sag_arka_kapi": "Sağ Arka Kapı",
    "sol_arka_kapi": "Sol Arka Kapı",
}

GROUP_PARTS: dict[str, list[str]] = {
    r"\b(?:[oö]n|on)\s*[cç]amurluklar[a-zçğıöşü]*\b": ["sol_on_camurluk", "sag_on_camurluk"],
    r"\barka\s*[cç]amurluklar[a-zçğıöşü]*\b": ["sol_arka_camurluk", "sag_arka_camurluk"],
    r"\b(?:[oö]n|on)\s*kap[ıi]lar[a-zçğıöşü]*\b": ["sol_on_kapi", "sag_on_kapi"],
    r"\barka\s*kap[ıi]lar[a-zçğıöşü]*\b": ["sol_arka_kapi", "sag_arka_kapi"],
    r"\bsa[gğ]\s*(?:yan|taraf)[a-zçğıöşü]*\b": ["sag_on_camurluk", "sag_on_kapi", "sag_arka_kapi", "sag_arka_camurluk"],
    r"\bsol\s*(?:yan|taraf)[a-zçğıöşü]*\b": ["sol_on_camurluk", "sol_on_kapi", "sol_arka_kapi", "sol_arka_camurluk"],
    r"\b(?:t[uü]m\s*kap[ıi]lar|d[oö]rt\s*kap[ıi])[a-zçğıöşü]*\b": ["sol_on_kapi", "sag_on_kapi", "sol_arka_kapi", "sag_arka_kapi"],
}


def _tr_lower(text: str) -> str:
    """Lowercase string taking Turkish characters (I -> ı, İ -> i) into account without combining diacritics."""
    res = []
    for ch in text:
        if ch == "İ":
            res.append("i")
        elif ch == "I":
            res.append("ı")
        else:
            res.append(ch.lower())
    # Strip any stray combining dot above (\u0307)
    return "".join(res).replace("\u0307", "")


def _extract_micron(segment: str) -> int | None:
    """Extract paint thickness in microns (e.g. '180 mikron', '95 um')."""
    m = re.search(r"(\d{2,4})\s*(?:mikron|micron|µm|um)\b", segment, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def parse_technician_dictation(text: str) -> dict[str, Any]:
    """Parse spoken Turkish technician dictation into structured inspection findings.

    Returns a dict with:
      - 'findings': formatted structure matching InspectionReport.findings_json
      - 'extracted_entities': list of detected items (part, state, detail, raw)
      - 'calculated_score': auto-calculated 0-100 score
      - 'generated_summary': comprehensive Turkish inspection Kanaat text
      - 'confidence_score': estimated parsing confidence
    """
    if not text or not text.strip():
        return {
            "findings": {
                "paint_body": {},
                "engine_mechanical": {},
                "chassis_frame": {},
                "tires_wheels": {},
                "interior_electronics": {},
            },
            "extracted_entities": [],
            "calculated_score": 100,
            "generated_summary": "Ekspertiz incelemesinde herhangi bir olumsuz bulgu dikte edilmedi.",
            "confidence_score": 0.0,
        }

    raw_text = text.strip()
    norm_text = _tr_lower(raw_text)

    # Initialize findings
    paint_body: dict[str, str] = {}
    engine_mechanical: dict[str, str] = {}
    chassis_frame: dict[str, str] = {}
    tires_wheels: dict[str, str] = {}
    interior_electronics: dict[str, str] = {}
    entities: list[dict[str, Any]] = []

    # Split into clauses by punctuation and discourse conjunctions
    clauses = [
        c.strip()
        for c in re.split(r"[.,;\n\r]+|\bve\b|\bayr[ıi]ca\b|\bbununla\s*birlikte\b", norm_text)
        if c.strip()
    ]

    # 1. Parse Paint & Body
    # Check for blanket "hatasız / boyasız / orijinal"
    if re.search(r"\b(?:ara[cç]|araba|karoser|kaporta)\s*(?:tamamen\s*)?(?:hatas[ıi]z|boyas[ıi]z|orijinal)\b", norm_text):
        for part_key in BODY_PARTS:
            paint_body[part_key] = "Orijinal"
        entities.append({
            "category": "paint_body",
            "part": "Tüm Gövde",
            "state": "Orijinal",
            "detail": "Fabrika boyası / Boyasız",
            "raw": "Araç hatasız boyasız",
        })

    # Clause-by-clause inspection for body parts
    for clause in clauses:
        micron = _extract_micron(clause)

        # Determine state in clause
        state = None
        penalty_type = None
        if re.search(r"\b(?:de[gğ]i[sş]en|de[gğ]i[sş]mi[sş]|yenilenmi[sş]|ç[ıi]kma(?:\s*parça)?|de[gğ]i[sş]tirildi)\b", clause):
            state = "Değişen"
            penalty_type = "degisen"
        elif re.search(r"\b(?:lokal\s*boya(?:l[ıi])?|yar[ıi]m\s*boya(?:l[ıi])?|k[ıi]smi\s*boya(?:l[ıi])?|yama\s*boya)\b", clause):
            state = "Lokal Boyalı"
            penalty_type = "lokal"
        elif re.search(r"\b(?:boya(?:l[ıi]|nm[ıi][sş])|tam\s*boya(?:l[ıi])?|f[ıi]r[ıi]n\s*boya|boya\s*var)\b", clause):
            state = "Boyalı"
            penalty_type = "boyali"
        elif re.search(r"\b(?:orijinal|orjinal|boyas[ıi]z|hatas[ıi]z|i[sş]lemsiz|fabrika\s*boyas[ıi])\b", clause):
            state = "Orijinal"
            penalty_type = "orijinal"

        if not state:
            continue

        state_formatted = state
        if micron is not None:
            state_formatted = f"{state} ({micron} µm)"

        # Check group patterns first
        matched_group = False
        for grp_pat, parts_list in GROUP_PARTS.items():
            if re.search(grp_pat, clause):
                for p in parts_list:
                    paint_body[p] = state_formatted
                entities.append({
                    "category": "paint_body",
                    "part": ", ".join(BODY_PART_LABELS.get(p, p) for p in parts_list),
                    "state": state,
                    "detail": f"{state_formatted} (Grup)",
                    "raw": clause,
                })
                matched_group = True

        if matched_group:
            continue

        # Check individual body parts
        for part_key, patterns in BODY_PARTS.items():
            for pat in patterns:
                if re.search(pat, clause):
                    paint_body[part_key] = state_formatted
                    entities.append({
                        "category": "paint_body",
                        "part": BODY_PART_LABELS[part_key],
                        "state": state,
                        "detail": state_formatted,
                        "raw": clause,
                    })
                    break

    # 2. Engine & Mechanical
    # Dyno / Motor performansı
    dyno_m = re.search(
        r"(?:(?:motor\s*(?:g[uü]c[uü]|performans[ıi]|dyno)?|dyno)[^\d]{0,25}(?:y[uü]zde|%)\s*(\d{1,3}))|"
        r"(?:(?:y[uü]zde|%)\s*(\d{1,3})\s*(?:motor|dyno|g[uü][cç]))",
        norm_text,
    )
    if dyno_m:
        val = dyno_m.group(1) or dyno_m.group(2)
        engine_mechanical["motor_performansi_yuzde"] = f"%{val}"
        entities.append({
            "category": "engine_mechanical",
            "part": "Dyno Motor Gücü",
            "state": f"%{val}",
            "detail": f"Motor Dyno Performansı %{val}",
            "raw": dyno_m.group(0),
        })

    # Turbo
    if re.search(r"\bturbo\b", norm_text):
        if re.search(r"\b(?:[oö]tme\s*yok|ar[ıi]za\s*yok|sorunsuz)\b", norm_text):
            engine_mechanical["turbo_durumu"] = "Basınç ve çalışma normal"
            entities.append({
                "category": "engine_mechanical",
                "part": "Turbo Kompresör",
                "state": "Normal",
                "detail": "Basınç ve çalışma normal",
                "raw": "Turbo sorunsuz",
            })
        elif re.search(r"\b(?:[oö]t[uü]yor|[oö]tme(?:\s*var)?|ya[gğ]\s*ka[cç][ıi]r[ıi]yor|ar[ıi]zal[ıi]|revizyon)\b", norm_text):
            engine_mechanical["turbo_durumu"] = "Basınç Düşük / Yağ Kaçağı ve Ses Mevcut"
            entities.append({
                "category": "engine_mechanical",
                "part": "Turbo Kompresör",
                "state": "Kusurlu",
                "detail": "Basınç Düşük / Yağ Kaçağı ve Ses Mevcut",
                "raw": "Turbo arızalı / ötme var",
            })
        else:
            engine_mechanical["turbo_durumu"] = "Basınç ve çalışma normal"
            entities.append({
                "category": "engine_mechanical",
                "part": "Turbo Kompresör",
                "state": "Normal",
                "detail": "Basınç ve çalışma normal",
                "raw": "Turbo normal",
            })

    # Şanzıman / Vites
    if re.search(r"\b(?:[sş]anz[ıi]man[a-zçğıöşü]*|vites[a-zçğıöşü]*|dsg|edc|cvt)\b", norm_text):
        if re.search(r"\b(?:vuruntu\s*yok|vuruntusuz|kusursuz|sorunsuz|ge[cç]i[sş]ler\s*d[uü]zg[uü]n)\b", norm_text):
            engine_mechanical["sanziman_vites"] = "Kusursuz / Vuruntu yok"
            entities.append({
                "category": "engine_mechanical",
                "part": "Şanzıman / Vites",
                "state": "Kusursuz",
                "detail": "Kusursuz / Vuruntu yok",
                "raw": "Şanzıman kusursuz / vuruntu yok",
            })
        elif re.search(r"\b(?:vuruntu(?:lu|\s*var)?|sert\s*ge[cç]i[sş]|ka[cç][ıi]rma|ar[ıi]zal[ıi]|kayd[ıi]rma)\b", norm_text):
            engine_mechanical["sanziman_vites"] = "Vuruntu / Geçiş Problemi Mevcut"
            entities.append({
                "category": "engine_mechanical",
                "part": "Şanzıman / Vites",
                "state": "Kusurlu",
                "detail": "Vuruntu / Geçiş Problemi Mevcut",
                "raw": "Şanzımanda vuruntu/sertlik var",
            })
        else:
            engine_mechanical["sanziman_vites"] = "Kusursuz / Vuruntu yok"
            entities.append({
                "category": "engine_mechanical",
                "part": "Şanzıman / Vites",
                "state": "Kusursuz",
                "detail": "Kusursuz / Vuruntu yok",
                "raw": "Şanzıman iyi",
            })

    # Yağ / Sıvı Kaçakları
    if re.search(r"\b(?:ya[gğ]|antifriz|s[ıi]v[ıi]|karter)\s*(?:ve\s*s[ıi]v[ıi]\s*)?ka[cç]a[gğ][ıi]\b|\bs[ıi]z[ıi]nt[ıi]\b|\bterleme\b", norm_text):
        if re.search(r"\b(?:ka[cç]ak\s*var|damlatma|terleme\s*var|s[ıi]z[ıi]nt[ıi]|s[ıi]zd[ıi]rma)\b", norm_text):
            engine_mechanical["yag_sivi_kacaklari"] = "Karter / Blokta Sıvı Kaçağı Tespit Edildi"
            entities.append({
                "category": "engine_mechanical",
                "part": "Yağ / Sıvı Kaçağı",
                "state": "Kaçak Var",
                "detail": "Karter / Blokta Sıvı Kaçağı Tespit Edildi",
                "raw": "Yağ kaçağı tespit edildi",
            })
        elif re.search(r"\b(?:ka[cç]ak\s*yok|g[oö]r[uü]lmedi|kuru|terleme\s*yok|yok)\b", norm_text):
            engine_mechanical["yag_sivi_kacaklari"] = "Kaçak görülmedi / Kuru"
            entities.append({
                "category": "engine_mechanical",
                "part": "Yağ / Sıvı Kaçağı",
                "state": "Kuru",
                "detail": "Kaçak görülmedi / Kuru",
                "raw": "Yağ kaçağı görülmedi",
            })

    # Enjektör / Yakıt
    if re.search(r"\b(?:enjekt[oö]r|yak[ıi]t\s*pompas[ıi]|enjektor)\b", norm_text):
        if re.search(r"\b(?:ar[ıi]za|i[sş]eme|dengesiz|duman)\b", norm_text):
            engine_mechanical["enjektor_yakit"] = "Enjektör püskürtme dengesiz"
            entities.append({
                "category": "engine_mechanical",
                "part": "Enjektör / Yakıt",
                "state": "Kusurlu",
                "detail": "Enjektör püskürtme dengesiz",
                "raw": "Enjektör dengesiz",
            })
        else:
            engine_mechanical["enjektor_yakit"] = "Püskürtme ve basınç normal"

    # Egzoz / Emisyon
    if re.search(r"\b(?:egzoz|emisyon|partik[uü]l|dpf)\b", norm_text):
        if re.search(r"\b(?:duman|siyah\s*duman|mavi\s*duman|dpf\s*t[ıi]kal[ıi]|koku)\b", norm_text):
            engine_mechanical["egzoz_emisyon"] = "Duman atma / DPF partikül filtresi dolu"
            entities.append({
                "category": "engine_mechanical",
                "part": "Egzoz / Emisyon",
                "state": "Kusurlu",
                "detail": "Duman atma / DPF partikül filtresi dolu",
                "raw": "Egzozda duman / partikül problemi",
            })
        else:
            engine_mechanical["egzoz_emisyon"] = "Duman ve partikül normal"

    # 3. Chassis & Frame
    # Podyeler & Şasi & Kuleler
    if re.search(r"\b(?:podye(?:ler)?|[sş]asi|kule(?:ler)?)\b", norm_text):
        if re.search(r"\b(?:i[sş]lemli|hasarl[ıi]|kaynak(?:l[ıi])?|d[uü]zeltilmi[sş]|çektirme|e[gğ]ik|kesme)\b", norm_text):
            chassis_frame["on_podyeler"] = "Hasarlı / Onarım Kaynaklı (AĞIR KUSUR)"
            entities.append({
                "category": "chassis_frame",
                "part": "Ön / Arka Podyeler",
                "state": "Ağır Kusur",
                "detail": "Hasarlı / Onarım Kaynaklı (AĞIR KUSUR)",
                "raw": "Podye/şasi işlemli",
            })
        elif re.search(r"\b(?:i[sş]lemsiz|orijinal|orjinal|hatas[ıi]z|temiz)\b", norm_text):
            chassis_frame["on_podyeler"] = "İşlemsiz / Orijinal"
            entities.append({
                "category": "chassis_frame",
                "part": "Ön / Arka Podyeler",
                "state": "Orijinal",
                "detail": "İşlemsiz / Orijinal",
                "raw": "Podyeler işlemsiz orijinal",
            })

    # Travers & Salıncak
    if re.search(r"\b(?:travers|sal[ıi]ncak|alt\s*tak[ıi]m)\b", norm_text):
        if re.search(r"\b(?:bo[sş]luk|e[gğ]rilik|hasar|darbe|ses|deforme)\b", norm_text):
            chassis_frame["on_arka_travers"] = "Deformasyon / Boşluk Mevcut"
            entities.append({
                "category": "chassis_frame",
                "part": "Kuleler & Travers",
                "state": "Boşluk / Deformasyon",
                "detail": "Deformasyon / Boşluk Mevcut",
                "raw": "Travers / alt takımda boşluk var",
            })
        else:
            chassis_frame["on_arka_travers"] = "Deformasyon yok / Düzgün"

    # Marşpiyeller
    if re.search(r"\b(?:mar[sş]piyel(?:ler)?|taban\s*sac[ıi])\b", norm_text):
        if re.search(r"\b(?:ezik|g[oö][cç][uü]k|kaynak|hasar|[cç][uü]r[uü]k)\b", norm_text):
            chassis_frame["marspiyeller"] = "Ezik / Göçük Mevcut"
            entities.append({
                "category": "chassis_frame",
                "part": "Marşpiyeller",
                "state": "Ezik / Göçük",
                "detail": "Ezik / Göçük Mevcut",
                "raw": "Marşpiyelde ezik var",
            })
        else:
            chassis_frame["marspiyeller"] = "Kaynak / Darbe yok"

    # Fren disk & balata
    if re.search(r"\b(?:fren(?:ler)?|disk(?:ler)?|balata(?:lar)?)\b", norm_text):
        if re.search(r"\b(?:a[sş][ıi]nm[ıi][sş]|bitik|de[gğ]i[sş]im|incelmi[sş]|zay[ıi]f)\b", norm_text):
            chassis_frame["fren_disk_balata"] = "Aşınmış / Değişim Gerekli"
            entities.append({
                "category": "chassis_frame",
                "part": "Fren Disk & Balata",
                "state": "Aşınmış",
                "detail": "Aşınmış / Değişim Gerekli",
                "raw": "Fren balataları aşınmış",
            })
        else:
            chassis_frame["fren_disk_balata"] = "İyi durumda (%80)"

    # 4. Tires & Wheels
    # Diş derinliği
    mm_m = re.search(r"(\d{1,2}(?:[.,]\d)?)\s*(?:mm|milimetre)\b", norm_text)
    if mm_m:
        val_str = mm_m.group(1).replace(",", ".")
        tires_wheels["on_sol_dis_mm"] = f"{val_str} mm"
        tires_wheels["arka_sol_dis_mm"] = f"{val_str} mm"
        entities.append({
            "category": "tires_wheels",
            "part": "Lastik Diş Derinliği",
            "state": f"{val_str} mm",
            "detail": f"Diş Derinliği: {val_str} mm",
            "raw": mm_m.group(0),
        })

    # DOT yılı
    dot_m = re.search(r"\b(?:dot\s*)?(201[7-9]|202[0-9])\b", norm_text)
    if dot_m:
        year_str = dot_m.group(1)
        tires_wheels["dot_yili"] = year_str
        entities.append({
            "category": "tires_wheels",
            "part": "Lastik DOT Yılı",
            "state": year_str,
            "detail": f"Üretim Yılı: {year_str}",
            "raw": dot_m.group(0),
        })

    # Jant
    if re.search(r"\bjant(?:lar)?\b", norm_text):
        if re.search(r"\b(?:çatlak|kaynak(?:l[ıi])?|yamuk|kald[ıi]r[ıi]m\s*izi|hasar)\b", norm_text):
            tires_wheels["jant_durumu"] = "Kaldırım Çizikleri / Düzeltme İhtiyacı"
            entities.append({
                "category": "tires_wheels",
                "part": "Jant Durumu",
                "state": "Çizik / Deforme",
                "detail": "Kaldırım Çizikleri / Düzeltme İhtiyacı",
                "raw": "Jantta kaldırım izi / eğrilik",
            })
        else:
            tires_wheels["jant_durumu"] = "Düzgün / Balans Başarılı"

    # 5. Interior & Electronics
    # Airbag
    if re.search(r"\b(?:airbag(?:ler)?|hava\s*yast[ıi][gğ][ıi])\b", norm_text):
        if re.search(r"\b(?:diren[cç](?:li)?|patlak|a[cç][ıi]lm[ıi][sş]|i[sş]lemli|tamirli|sahte)\b", norm_text):
            interior_electronics["airbag_guvenlik"] = "Dirençli / İşlemli (RİSKLİ!)"
            entities.append({
                "category": "interior_electronics",
                "part": "Airbag Güvenlik",
                "state": "Kritik Risk",
                "detail": "Dirençli / İşlemli (RİSKLİ!)",
                "raw": "Airbagler dirençli / işlemli",
            })
        elif re.search(r"\b(?:orijinal|aktif|hatas[ıi]z|sa[gğ]lam)\b", norm_text):
            interior_electronics["airbag_guvenlik"] = "Orijinal ve aktif"
            entities.append({
                "category": "interior_electronics",
                "part": "Airbag Güvenlik",
                "state": "Orijinal",
                "detail": "Orijinal ve aktif",
                "raw": "Airbagler orijinal",
            })

    # OBD Arıza Taraması
    if re.search(r"\b(?:obd|ar[ıi]za\s*kodu|dtc|ar[ıi]za\s*lambas[ıi])\b", norm_text):
        if re.search(r"\b(?:ar[ıi]za\s*var|dtc\s*var|hata\s*var|lamba\s*yan[ıi]yor)\b", norm_text):
            interior_electronics["obd_ariza_taramasi"] = "Aktif DTC Arıza Kayıtları Mevcut"
            entities.append({
                "category": "interior_electronics",
                "part": "OBD Taraması",
                "state": "Arıza Var",
                "detail": "Aktif DTC Arıza Kayıtları Mevcut",
                "raw": "OBD arıza lambası yanıyor / kod var",
            })
        elif re.search(r"\b(?:ar[ıi]za(?:\s*kodu)?\s*yok|kod[u]?\s*yok|temiz|ba[sş]ar[ıi]l[ıi]|kay[ıi]t\s*yok)\b", norm_text):
            interior_electronics["obd_ariza_taramasi"] = "Aktif DTC arıza kodu yok"
            entities.append({
                "category": "interior_electronics",
                "part": "OBD Taraması",
                "state": "Temiz",
                "detail": "Aktif DTC arıza kodu yok",
                "raw": "OBD arıza kodu yok",
            })

    # Klima
    if re.search(r"\b(?:klima|so[gğ]utma|[ıi]s[ıi]tma|kalorifer)\b", norm_text):
        if re.search(r"\b(?:so[gğ]utmuyor|gaz\s*eksik|ar[ıi]zal[ıi]|kompres[oö]r)\b", norm_text):
            interior_electronics["klima_isitma"] = "Klima soğutmuyor / Gaz eksik"
            entities.append({
                "category": "interior_electronics",
                "part": "Klima & Havalandırma",
                "state": "Kusurlu",
                "detail": "Klima soğutmuyor / Gaz eksik",
                "raw": "Klima soğutmuyor",
            })
        else:
            interior_electronics["klima_isitma"] = "Klima aktif ve soğutuyor"

    # Koltuk / Döşeme
    if re.search(r"\b(?:koltuk(?:lar)?|dö[sş]eme|iç\s*mekan)\b", norm_text):
        if re.search(r"\b(?:y[ıi]rt[ıi]k|yan[ıi]k|sigara|leke|deforme)\b", norm_text):
            interior_electronics["koltuk_doseme"] = "Deformasyon / Yanık mevcut"
            entities.append({
                "category": "interior_electronics",
                "part": "Koltuk & Döşeme",
                "state": "Deforme",
                "detail": "Deformasyon / Yanık mevcut",
                "raw": "Koltukta yanık / yırtık",
            })
        else:
            interior_electronics["koltuk_doseme"] = "Temiz ve lekesiz"

    # Paint notes summary if any micron remarks mentioned
    micron_notes = []
    for k, v in paint_body.items():
        if "µm" in v:
            lbl = BODY_PART_LABELS.get(k, k)
            micron_notes.append(f"{lbl}: {v}")
    if micron_notes:
        paint_body["notlar"] = "; ".join(micron_notes)

    # 6. Calculate Vehicle Score (0-100)
    score = 100
    for part, st in paint_body.items():
        if part == "notlar":
            continue
        if "Değişen" in st:
            score -= 7
        elif "Lokal Boyalı" in st:
            score -= 1
        elif "Boyalı" in st:
            score -= 3

    # Heavy chassis/safety penalties
    if "Hasarlı" in chassis_frame.get("on_podyeler", ""):
        score -= 20
    if "Deformasyon" in chassis_frame.get("on_arka_travers", ""):
        score -= 4
    if "Dirençli" in interior_electronics.get("airbag_guvenlik", ""):
        score -= 25
    if "Geçiş Problemi" in engine_mechanical.get("sanziman_vites", ""):
        score -= 8
    if "Kaçak Var" in engine_mechanical.get("yag_sivi_kacaklari", "") or "Tespit Edildi" in engine_mechanical.get("yag_sivi_kacaklari", ""):
        score -= 4
    if "DTC Arıza" in interior_electronics.get("obd_ariza_taramasi", ""):
        score -= 6
    if "Aşınmış" in chassis_frame.get("fren_disk_balata", ""):
        score -= 3

    # Motor power check
    motor_pct_str = engine_mechanical.get("motor_performansi_yuzde", "")
    if motor_pct_str:
        try:
            m_pct = int(motor_pct_str.replace("%", ""))
            if m_pct < 75:
                score -= 15
            elif m_pct < 85:
                score -= 7
            elif m_pct < 90:
                score -= 3
        except ValueError:
            pass

    score = max(10, min(100, score))

    # 7. Generate Cohesive Technical Summary
    summary_sentences = []

    # Body summary
    degisen_parts = [BODY_PART_LABELS.get(k, k) for k, v in paint_body.items() if k != "notlar" and "Değişen" in v]
    boyali_parts = [BODY_PART_LABELS.get(k, k) for k, v in paint_body.items() if k != "notlar" and "Boyalı" in v and "Lokal" not in v]
    lokal_parts = [BODY_PART_LABELS.get(k, k) for k, v in paint_body.items() if k != "notlar" and "Lokal Boyalı" in v]

    body_desc = []
    if degisen_parts:
        body_desc.append(f"{', '.join(degisen_parts)} değişen")
    if boyali_parts:
        body_desc.append(f"{', '.join(boyali_parts)} boyalı")
    if lokal_parts:
        body_desc.append(f"{', '.join(lokal_parts)} lokal boyalı")

    if body_desc:
        summary_sentences.append(f"Gövde ve karoser kontrolünde; {'; '.join(body_desc)} olarak tespit edilmiştir.")
    elif paint_body:
        summary_sentences.append("Gövde ve kaporta aksamında fabrika boyası ve kalınlıkları korunmuş olup değişen/boyalı parça bulunmamaktadır.")

    # Engine/Mechanical summary
    mech_desc = []
    if "motor_performansi_yuzde" in engine_mechanical:
        mech_desc.append(f"Dyno motor test performansı {engine_mechanical['motor_performansi_yuzde']}")
    if "sanziman_vites" in engine_mechanical:
        mech_desc.append(f"şanzıman {_tr_lower(engine_mechanical['sanziman_vites'])}")
    if "yag_sivi_kacaklari" in engine_mechanical:
        mech_desc.append(f"sıvı kontrollerinde {_tr_lower(engine_mechanical['yag_sivi_kacaklari'])}")
    if mech_desc:
        summary_sentences.append(f"Motor ve mekanik grupta: {', '.join(mech_desc)}.")

    # Chassis & Safety summary
    safety_desc = []
    if "on_podyeler" in chassis_frame:
        safety_desc.append(f"şasi ve podyeler {_tr_lower(chassis_frame['on_podyeler'])}")
    if "airbag_guvenlik" in interior_electronics:
        safety_desc.append(f"hava yastıkları {_tr_lower(interior_electronics['airbag_guvenlik'])}")
    if safety_desc:
        summary_sentences.append(f"Yapısal güvenlik kontrollerinde {', '.join(safety_desc)}.")

    if not summary_sentences:
        generated_summary = f"Sahadan dikte edilen uzman notları başarıyla işlendi: '{raw_text}'"
    else:
        generated_summary = " ".join(summary_sentences)

    confidence = 0.95 if entities else 0.50

    return {
        "findings": {
            "paint_body": paint_body,
            "engine_mechanical": engine_mechanical,
            "chassis_frame": chassis_frame,
            "tires_wheels": tires_wheels,
            "interior_electronics": interior_electronics,
        },
        "extracted_entities": entities,
        "calculated_score": score,
        "generated_summary": generated_summary,
        "confidence_score": confidence,
    }


def apply_dictation_to_report(
    db: Session,
    *,
    report_id: str,
    findings: dict[str, Any],
    summary: str,
    score: int | None = None,
) -> InspectionReport:
    """Merge newly parsed findings into an existing InspectionReport and regenerate PDF.

    - Merges category by category so untouched fields retain their existing values.
    - Updates score and summary.
    - Re-runs PDF generation to update official report on disk immediately.
    """
    report = db.get(InspectionReport, report_id)
    if not report:
        raise ValueError(f"Ekspertiz raporu bulunamadı: {report_id}")

    vehicle = db.get(Vehicle, report.vehicle_id)
    if not vehicle:
        raise ValueError(f"Rapora ait araç bulunamadı: {report.vehicle_id}")

    appointment = None
    if report.appointment_id:
        appointment = db.get(Appointment, report.appointment_id)

    # Load and merge existing findings
    existing_findings = {}
    if report.findings_json:
        try:
            existing_findings = json.loads(report.findings_json)
        except Exception:
            existing_findings = {}

    for cat in ["paint_body", "engine_mechanical", "chassis_frame", "tires_wheels", "interior_electronics"]:
        old_cat = existing_findings.setdefault(cat, {})
        new_cat = findings.get(cat, {})
        if isinstance(new_cat, dict):
            for k, v in new_cat.items():
                if v:
                    old_cat[k] = v

    report.findings_json = json.dumps(existing_findings, ensure_ascii=False)

    if score is not None:
        report.score = score

    if summary:
        if report.summary and report.summary not in summary:
            report.summary = f"{report.summary}\n\n[Teknisyen Dikte]: {summary}"
        else:
            report.summary = summary

    # Re-generate PDF report so digital delivery link reflects the latest state immediately
    if report.pdf_path:
        try:
            generate_inspection_pdf(
                report=report,
                vehicle=vehicle,
                appointment=appointment,
                output_path=report.pdf_path,
            )
        except Exception as e:
            logger.warning(f"Rapor PDF güncellemesi sırasında hata: {e}")

    db.commit()
    db.refresh(report)
    return report
