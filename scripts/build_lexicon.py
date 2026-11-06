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

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Set

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_lexicon")

GENERIC_TERMS = {
    "mpv", "ev", "bev", "phev", "hev", "mhev", "suv", "sedan",
    "van", "cabriolet", "hatchback", "crossover", "coupe", "coupé"
}


def load_vocab_set(vocab_path: Path) -> Set[str]:
    """FreyaTTS 92 sembollü karakter sözlüğünü yükler."""
    if vocab_path.exists():
        try:
            data = json.loads(vocab_path.read_text(encoding="utf-8"))
            return set(data.keys())
        except Exception as e:
            logger.warning(f"Vocab okunamadı ({e}), yedek liste kullanılıyor.")
    return {
        "<FILL>", "<UNK>", " ", "%", "&", "'", "+", ",", "-", ".", "/",
        "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ":", ";", ">", "?",
        "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N",
        "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
        "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n",
        "o", "p", "r", "s", "t", "u", "v", "w", "x", "y", "z",
        "Ç", "Ö", "Ü", "á", "â", "ç", "ö", "ú", "ü", "ğ", "İ", "ı", "Ş", "ş", "’", "€"
    }


def clean_text(s: Any) -> str:
    """Metin girdisini temizler, NaN veya float ise boş string döner."""
    if pd.isna(s) or s is None:
        return ""
    val = str(s).strip()
    return "" if val.lower() == "nan" else val


def build_lexicons(
    file1_path: Path,
    file2_path: Path,
    vocab_path: Path,
    output_compiled_path: Path,
    output_flat_path: Path,
    output_unified_path: Path | None = None,
    output_root_path: Path | None = None,
) -> Dict[str, Any]:
    """
    İki Excel dosyasındaki sayfaları okur, öncelik sırasına göre birleştirir ve tekilleştirir:
    - 102 marka (brands)
    - 1.505 tam marka+model (full_models)
    - 1.456 tekil model (standalone_models)
    - 1.664 ASR varyantı (asr_mappings)
    - 102 doğrudan normalizasyon (exact_normalizations)
    - 201 sektörel terim/kısaltma (abbreviations_and_terms)
    - 7 kademeli pipeline_order
    - Çift profil desteği (tts_sezer ve tts_2026)
    """
    vocab = load_vocab_set(vocab_path)
    logger.info(f"Model vocab boyutu: {len(vocab)}")

    # 1. Dosya 1: FreyaTTS_Otomotiv_Turkce_Telaffuz_Sezer_ve_Test_Cumleleri.xlsx
    logger.info(f"Dosya 1 okunuyor: {file1_path}")
    xls1 = pd.ExcelFile(file1_path)
    df_m1 = pd.read_excel(xls1, "MARKA_SOZLUGU")
    df_mod1 = pd.read_excel(xls1, "MODEL_SOZLUGU")
    df_norm1 = pd.read_excel(xls1, "NORMALIZASYON")
    df_kis1 = pd.read_excel(xls1, "KISALTMALAR")

    # 2. Dosya 2: FreyaTTS_Otomotiv_Turkce_Telaffuz_Sozlugu_2026.xlsx
    logger.info(f"Dosya 2 okunuyor: {file2_path}")
    xls2 = pd.ExcelFile(file2_path)
    df_m2 = pd.read_excel(xls2, "02_MARKALAR")
    df_mod2 = pd.read_excel(xls2, "03_MODELLER")
    df_alias2 = pd.read_excel(xls2, "04_TTS_ALIAS")
    df_terim2 = pd.read_excel(xls2, "05_TERIMLER")
    df_sayi2 = pd.read_excel(xls2, "06_SAYI_KURALLARI")

    # F2 Terimler ve Sayı Kuralları haritası (hızlı çapraz başvuru için)
    f2_terimler_map: Dict[str, str] = {}
    for _, row in df_terim2.iterrows():
        t_src = clean_text(row.get("Terim / kısaltma")).lower()
        t_spk = clean_text(row.get("Türkçe okunuş adayı"))
        if t_src and t_spk:
            f2_terimler_map[t_src] = t_spk

    f1_kisaltmalar_map: Dict[str, str] = {}
    for _, row in df_kis1.iterrows():
        t_src = clean_text(row.get("Kısaltma / terim")).lower()
        t_spk = clean_text(row.get("Önerilen okunuş veya açılım"))
        if t_src and t_spk:
            f1_kisaltmalar_map[t_src] = t_spk

    # =========================================================================
    # KADEME 1: Kesme İşaretli Çekim Ekleri (apostrophe_inflections - Öncelik 5)
    # =========================================================================
    apostrophe_inflections: List[Dict[str, Any]] = [
        {
            "source": "Clio’nun",
            "source_alt": "Clio'nun",
            "canonical": "Renault Clio",
            "tts_sezer": "Kliyo’nun",
            "tts_2026": "Klio’nun",
            "priority": 5,
        },
        {
            "source": "Qashqai’ye",
            "source_alt": "Qashqai'ye",
            "canonical": "Nissan Qashqai",
            "tts_sezer": "Kaşkay’a",
            "tts_2026": "Kaşkay’a",
            "priority": 5,
        },
        {
            "source": "BMW’nin",
            "source_alt": "BMW'nin",
            "canonical": "BMW",
            "tts_sezer": "Be Em Ve’nin",
            "tts_2026": "Be em ve’nin",
            "priority": 5,
        },
        {
            "source": "Peugeot’nun",
            "source_alt": "Peugeot'nun",
            "canonical": "Peugeot",
            "tts_sezer": "Pöjo’nun",
            "tts_2026": "Pöjo’nun",
            "priority": 5,
        },
        {
            "source": "Mercedes’in",
            "source_alt": "Mercedes'in",
            "canonical": "Mercedes-Benz",
            "tts_sezer": "Mersedes’in",
            "tts_2026": "Mersedes’in",
            "priority": 5,
        },
        {
            "source": "Audi’nin",
            "source_alt": "Audi'nin",
            "canonical": "Audi",
            "tts_sezer": "Audi’nin",
            "tts_2026": "Audi’nin",
            "priority": 5,
        },
        {
            "source": "Volkswagen’in",
            "source_alt": "Volkswagen'in",
            "canonical": "Volkswagen",
            "tts_sezer": "Folksvagen’in",
            "tts_2026": "Folksvagen’in",
            "priority": 5,
        },
        {
            "source": "Togg’un",
            "source_alt": "Togg'un",
            "canonical": "Togg",
            "tts_sezer": "Tog’un",
            "tts_2026": "Tog’un",
            "priority": 5,
        },
    ]

    # =========================================================================
    # KADEME 2: Tam Marka + Model İfadeleri (full_models - Öncelik 10, Toplam 1.505)
    # =========================================================================
    full_models_dict: Dict[str, Dict[str, Any]] = {}

    for _, row in df_mod1.iterrows():
        source = clean_text(row.get("Tam orijinal yazım"))
        spoken_sezer = clean_text(row.get("Tam FreyaTTS metni"))
        model_spoken_sezer = clean_text(row.get("Modelin okunuş adayı"))
        brand = clean_text(row.get("Marka"))
        model = clean_text(row.get("Model / kod"))
        if source and spoken_sezer:
            full_models_dict[source.lower()] = {
                "canonical": source,
                "source": source,
                "brand": brand,
                "model": model,
                "tts_sezer": spoken_sezer,
                "tts_2026": spoken_sezer,
                "model_tts_sezer": model_spoken_sezer,
                "model_tts_2026": model_spoken_sezer,
                "spoken": spoken_sezer,
                "priority": 10,
                "origin": "f1_model_sozlugu",
            }

    for _, row in df_mod2.iterrows():
        source = clean_text(row.get("Tam araç adı"))
        spoken_2026 = clean_text(row.get("Önerilen TTS tam okunuş"))
        model_spoken_2026 = clean_text(row.get("Modelin TTS okunuşu"))
        brand = clean_text(row.get("Marka"))
        model = clean_text(row.get("Model / versiyon"))
        if source and spoken_2026:
            k = source.lower()
            if k in full_models_dict:
                full_models_dict[k]["canonical"] = source
                full_models_dict[k]["source"] = source
                full_models_dict[k]["tts_2026"] = spoken_2026
                full_models_dict[k]["model_tts_2026"] = model_spoken_2026
                full_models_dict[k]["spoken"] = spoken_2026
            else:
                full_models_dict[k] = {
                    "canonical": source,
                    "source": source,
                    "brand": brand,
                    "model": model,
                    "tts_sezer": spoken_2026,
                    "tts_2026": spoken_2026,
                    "model_tts_sezer": model_spoken_2026,
                    "model_tts_2026": model_spoken_2026,
                    "spoken": spoken_2026,
                    "priority": 10,
                    "origin": "f2_03_modeller",
                }

    # =========================================================================
    # KADEME 3: Tekil Model İsimleri (standalone_models - Öncelik 20, Toplam 1.456)
    # =========================================================================
    models_dict: Dict[str, Dict[str, Any]] = {}

    for _, row in df_mod1.iterrows():
        model_name = clean_text(row.get("Model / kod"))
        spoken_sezer = clean_text(row.get("Modelin okunuş adayı"))
        brand = clean_text(row.get("Marka"))
        if model_name and spoken_sezer:
            k = model_name.lower()
            if k not in models_dict:
                models_dict[k] = {
                    "model": model_name,
                    "source": model_name,
                    "tts_sezer": spoken_sezer,
                    "tts_2026": spoken_sezer,
                    "spoken": spoken_sezer,
                    "by_brand": [brand] if brand else [],
                    "brand": brand,
                    "priority": 20,
                    "origin": "f1_model_single",
                }
            else:
                if brand and brand not in models_dict[k]["by_brand"]:
                    models_dict[k]["by_brand"].append(brand)

    for _, row in df_mod2.iterrows():
        model_name = clean_text(row.get("Model / versiyon"))
        spoken_2026 = clean_text(row.get("Modelin TTS okunuşu"))
        brand = clean_text(row.get("Marka"))
        if model_name and spoken_2026:
            k = model_name.lower()
            if k not in models_dict:
                models_dict[k] = {
                    "model": model_name,
                    "source": model_name,
                    "tts_sezer": spoken_2026,
                    "tts_2026": spoken_2026,
                    "spoken": spoken_2026,
                    "by_brand": [brand] if brand else [],
                    "brand": brand,
                    "priority": 20,
                    "origin": "f2_model_single",
                }
            else:
                models_dict[k]["model"] = model_name
                models_dict[k]["tts_2026"] = spoken_2026
                models_dict[k]["spoken"] = spoken_2026
                if brand and brand not in models_dict[k]["by_brand"]:
                    models_dict[k]["by_brand"].append(brand)

    # =========================================================================
    # KADEME 4: Marka İsimleri (brands - Öncelik 30, Toplam 102)
    # =========================================================================
    brands_dict: Dict[str, Dict[str, Any]] = {}

    for _, row in df_m1.iterrows():
        brand = clean_text(row.get("Orijinal marka"))
        spoken_sezer = clean_text(row.get("FreyaTTS okunuş adayı"))
        if brand and spoken_sezer:
            k = brand.lower()
            brands_dict[k] = {
                "canonical": brand,
                "source": brand,
                "tts_sezer": spoken_sezer,
                "tts_2026": spoken_sezer,
                "spoken": spoken_sezer,
                "asr_variants": [],
                "aliases": [],
                "priority": 30,
                "origin": "f1_marka",
            }

    for _, row in df_m2.iterrows():
        brand = clean_text(row.get("Marka"))
        spoken_2026 = clean_text(row.get("Türkçe TTS okunuş adayı"))
        aliases_raw = clean_text(row.get("ASR yazım varyantları"))
        aliases = [a.strip() for a in aliases_raw.split(";") if a.strip()] if aliases_raw else []
        if brand and spoken_2026:
            k = brand.lower()
            if k in brands_dict:
                brands_dict[k]["canonical"] = brand
                brands_dict[k]["source"] = brand
                brands_dict[k]["tts_2026"] = spoken_2026
                brands_dict[k]["spoken"] = spoken_2026
                brands_dict[k]["asr_variants"] = aliases
                brands_dict[k]["aliases"] = aliases
            else:
                brands_dict[k] = {
                    "canonical": brand,
                    "source": brand,
                    "tts_sezer": spoken_2026,
                    "tts_2026": spoken_2026,
                    "spoken": spoken_2026,
                    "asr_variants": aliases,
                    "aliases": aliases,
                    "priority": 30,
                    "origin": "f2_marka",
                }

    # =========================================================================
    # KADEME 5: Doğrudan Normalizasyon Eşlemeleri (exact_normalizations - Öncelik 35, Toplam 102)
    # =========================================================================
    exact_normalizations: List[Dict[str, Any]] = []

    # F1 NORMALIZASYON (72 kayıt)
    for _, row in df_norm1.iterrows():
        r_id = clean_text(row.iloc[0])
        cat = clean_text(row.iloc[1]) if len(row) > 1 else ""
        src = clean_text(row.iloc[2]) if len(row) > 2 else ""
        spk_sezer = clean_text(row.iloc[3]) if len(row) > 3 else ""
        # 2026 profili için F2'de varsa F2 okunuşunu kullan
        spk_2026 = f2_terimler_map.get(src.lower(), spk_sezer)
        if src and spk_sezer:
            exact_normalizations.append({
                "id": r_id,
                "category": cat,
                "source": src,
                "tts_sezer": spk_sezer,
                "tts_2026": spk_2026,
                "spoken": spk_2026,
                "priority": 35,
                "origin": "f1_normalizasyon",
            })

    # F2 06_SAYI_KURALLARI (30 kayıt)
    for idx, row in df_sayi2.iterrows():
        src = clean_text(row.iloc[0])
        spk = clean_text(row.iloc[1])
        cat = clean_text(row.iloc[2]) if len(row) > 2 else ""
        ctx = clean_text(row.iloc[3]) if len(row) > 3 else ""
        if src and spk:
            exact_normalizations.append({
                "id": f"NUM_{idx+1:03d}",
                "category": cat,
                "source": src,
                "tts_sezer": spk,
                "tts_2026": spk,
                "spoken": spk,
                "context": ctx,
                "priority": 35,
                "origin": "f2_sayi_kurallari",
            })

    # =========================================================================
    # KADEME 6: Kısaltmalar ve Sektörel Terimler (abbreviations_and_terms - Öncelik 40, Toplam 201)
    # =========================================================================
    terms_list: List[Dict[str, Any]] = []

    # F1 KISALTMALAR (81 kayıt)
    for _, row in df_kis1.iterrows():
        term = clean_text(row.get("Kısaltma / terim"))
        spoken_sezer = clean_text(row.get("Önerilen okunuş veya açılım"))
        spoken_2026 = f2_terimler_map.get(term.lower(), spoken_sezer)
        cat = clean_text(row.get("Sınıf"))
        if term and spoken_sezer:
            terms_list.append({
                "term": term,
                "source": term,
                "spoken_sezer": spoken_sezer,
                "spoken_2026": spoken_2026,
                "tts_sezer": spoken_sezer,
                "tts_2026": spoken_2026,
                "spoken": spoken_2026,
                "category": cat,
                "priority": 40,
                "origin": "f1_kisaltmalar",
            })

    # F2 05_TERIMLER (120 kayıt)
    for _, row in df_terim2.iterrows():
        term = clean_text(row.get("Terim / kısaltma"))
        spoken_2026 = clean_text(row.get("Türkçe okunuş adayı"))
        spoken_sezer = f1_kisaltmalar_map.get(term.lower(), spoken_2026)
        cat = clean_text(row.get("Grup"))
        if term and spoken_2026:
            terms_list.append({
                "term": term,
                "source": term,
                "spoken_sezer": spoken_sezer,
                "spoken_2026": spoken_2026,
                "tts_sezer": spoken_sezer,
                "tts_2026": spoken_2026,
                "spoken": spoken_2026,
                "category": cat,
                "priority": 40,
                "origin": "f2_terimler",
            })

    # =========================================================================
    # KADEME 7: ASR Varyantları Tablosu (asr_mappings - 04_TTS_ALIAS, Toplam 1.664)
    # =========================================================================
    asr_mappings: List[Dict[str, Any]] = []
    seen_asr_pairs: Set[str] = set()

    for _, row in df_alias2.iterrows():
        variant = clean_text(row.get("Gelen yazım / ASR varyantı"))
        canonical = clean_text(row.get("Kanonik ifade"))
        spoken = clean_text(row.get("Önerilen konuşma metni"))
        alias_type = clean_text(row.get("Alias türü"))
        priority = int(row.get("Öncelik") or 30)
        pair_key = f"{variant.lower()}->{canonical.lower()}"
        if variant and canonical and pair_key not in seen_asr_pairs:
            seen_asr_pairs.add(pair_key)
            asr_mappings.append({
                "variant": variant,
                "canonical": canonical,
                "spoken": spoken,
                "alias_type": alias_type,
                "priority": priority,
            })

    # =========================================================================
    # KADEME 8: Standart Regex Şablonları (regex_patterns - Öncelik 50 - 180)
    # =========================================================================
    regex_patterns: List[Dict[str, Any]] = [
        {
            "id": "REG_PRICE",
            "name": "Fiyat ve Para Birimleri",
            "pattern": r"\b(?P<val>\d+(?:[.,]\d+)?)\s*(?P<unit>milyon|bin)\s*(?:TL|Türk\s+lirası|₺)(?!\w)",
            "priority": 50,
            "description": "1.850.000 TL, 2.490.000 ₺, 1,5 milyon TL açılımları",
        },
        {
            "id": "REG_PERCENT",
            "name": "Yüzde ve Oranlar",
            "pattern": r"%(?P<val>\d+(?:,\d+)?)",
            "priority": 60,
            "description": "%20, %1,49, %30-%80 açılımları",
        },
        {
            "id": "REG_DATE_TIME",
            "name": "Tarih ve Saatler",
            "pattern": r"\b\d{2}[./]\d{2}[./]\d{4}\b|\b\d{2}:\d{2}\b",
            "priority": 70,
            "description": "02.11.2026, 14:30, 09.00-18.00 açılımları",
        },
        {
            "id": "REG_SPEED_UNIT",
            "name": "Mesafe, Hız ve Batarya Birimleri",
            "pattern": r"\b\d+\s*(?:km/sa|km/s|km|kWh|kW|HP|Nm|rpm)\b",
            "priority": 80,
            "description": "0-100 km/sa, 75 kWh, 150 HP, 320 Nm açılımları",
        },
        {
            "id": "REG_PLATE_PHONE",
            "name": "Plaka ve Telefon Numaraları",
            "pattern": r"\b\d{2}\s+[A-Z]{1,3}\s+\d{2,4}\b|\b0?[2-5]\d{2}\s*\d{3}\s*\d{2}\s*\d{2}\b",
            "priority": 90,
            "description": "34 ABC 123, 61 AB 123, 0532 123 45 67, 444 0 123 açılımları",
        },
        {
            "id": "REG_TIRE",
            "name": "Lastik Ebatları",
            "pattern": r"\b\d{3}/\d{2}\s*R\d{2}\b",
            "priority": 100,
            "description": "225/45 R17, 245/40 R19 açılımları",
        },
        {
            "id": "REG_DISPLACEMENT",
            "name": "Motor Hacmi ve Hacim İfadeleri",
            "pattern": r"\b[0-6][.,][0-9]\s+(?:motor|litre|benzinli|dizel)\b",
            "priority": 110,
            "description": "1.6 motor, 1,5 litre açılımları",
        },
    ]

    # Sıralamalar (Longest-match-first)
    sorted_full_models = sorted(
        full_models_dict.values(), key=lambda x: len(x["source"]), reverse=True
    )
    sorted_standalone_models = sorted(
        models_dict.values(), key=lambda x: len(x["source"]), reverse=True
    )
    sorted_brands = sorted(
        brands_dict.values(), key=lambda x: len(x["source"]), reverse=True
    )
    sorted_exact_norm = sorted(
        exact_normalizations, key=lambda x: len(x["source"]), reverse=True
    )
    sorted_terms = sorted(
        terms_list, key=lambda x: len(x["source"]), reverse=True
    )

    # Birleşik Leksikon Yükü
    unified_payload: Dict[str, Any] = {
        "metadata": {
            "version": "2026.1",
            "engine": "FreyaTTS",
            "default_seed": 9,
            "description": "FreyaTTS Otomotiv Türkçe Telaffuz ve Normalizasyon Derlenmiş Leksikonu",
            "total_brands": len(sorted_brands),
            "total_full_models": len(sorted_full_models),
            "total_standalone_models": len(sorted_standalone_models),
            "total_asr_aliases": len(asr_mappings),
            "total_exact_normalizations": len(sorted_exact_norm),
            "total_abbreviations_and_terms": len(sorted_terms),
        },
        "pipeline_order": [
            {"stage": 1, "name": "apostrophe_inflections", "priority": 5, "description": "Kesme işaretli çekim ekleri (Clio'nun, Qashqai'ye, BMW'nin vb.)"},
            {"stage": 2, "name": "full_models", "priority": 10, "description": "Tam marka + model ifadeleri"},
            {"stage": 3, "name": "standalone_models", "priority": 20, "description": "Tekil model isimleri"},
            {"stage": 4, "name": "brands", "priority": 30, "description": "Marka adları"},
            {"stage": 5, "name": "exact_normalizations", "priority": 35, "description": "Doğrudan sayı ve normalizasyon eşleşmeleri"},
            {"stage": 6, "name": "abbreviations_and_terms", "priority": 40, "description": "Kısaltmalar ve sektörel terimler"},
            {"stage": 7, "name": "regex_patterns", "priority": 50, "description": "Fiyat, yüzde, tarih, saat, hız, plaka, telefon, lastik kalıpları"},
        ],
        "apostrophe_inflections": apostrophe_inflections,
        "brands": sorted_brands,
        "full_models": sorted_full_models,
        "standalone_models": sorted_standalone_models,
        "exact_normalizations": sorted_exact_norm,
        "abbreviations_and_terms": sorted_terms,
        "asr_mappings": asr_mappings,
        "regex_patterns": regex_patterns,
        # Geriye dönük uyumluluk alanları
        "full_expressions": sorted_full_models,
        "models": sorted_standalone_models,
        "terms": sorted_terms,
        "number_rules": [e for e in sorted_exact_norm if e.get("origin") == "f2_sayi_kurallari"],
        "normalization_rules": [e for e in sorted_exact_norm if e.get("origin") == "f1_normalizasyon"],
    }

    # 1. output_compiled_path (config/automotive_compiled_lexicon.json)
    output_compiled_path.parent.mkdir(parents=True, exist_ok=True)
    compiled_json_text = json.dumps(unified_payload, ensure_ascii=False, indent=2)
    output_compiled_path.write_text(compiled_json_text, encoding="utf-8")
    logger.info(f"Derlenmiş sözlük kaydedildi: {output_compiled_path} ({output_compiled_path.stat().st_size} bayt)")

    # 2. output_unified_path (config/freyatts_automotive_lexicon.json)
    if output_unified_path:
        output_unified_path.parent.mkdir(parents=True, exist_ok=True)
        output_unified_path.write_text(compiled_json_text, encoding="utf-8")
        logger.info(f"Birleşik sözlük kaydedildi: {output_unified_path}")

    # 3. output_root_path (freyatts_automotive_lexicon.json)
    if output_root_path:
        output_root_path.write_text(compiled_json_text, encoding="utf-8")
        logger.info(f"Kök dizin birleşik sözlük kaydedildi: {output_root_path}")

    # 4. Geriye dönük uyumlu düz automotive_flat_lexicon.json üretimi
    flat_lexicon: Dict[str, str] = {}
    for item in sorted_exact_norm:
        flat_lexicon[item["source"].lower()] = item["spoken"]
    for item in sorted_terms:
        flat_lexicon[item["source"].lower()] = item["spoken"]
    for item in sorted_brands:
        flat_lexicon[item["source"].lower()] = item["spoken"]
    for item in sorted_standalone_models:
        flat_lexicon[item["source"].lower()] = item["spoken"]
    for item in sorted_full_models:
        flat_lexicon[item["source"].lower()] = item["spoken"]

    output_flat_path.write_text(
        json.dumps(flat_lexicon, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"Düz sözlük kaydedildi: {output_flat_path} ({len(flat_lexicon)} giriş)")

    return unified_payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Otomotiv TTS Leksikon ETL Betiği")
    parser.add_argument(
        "--file1",
        default="FreyaTTS_Otomotiv_Turkce_Telaffuz_Sezer_ve_Test_Cumleleri.xlsx",
        help="1. Excel dosyası yolu",
    )
    parser.add_argument(
        "--file2",
        default="FreyaTTS_Otomotiv_Turkce_Telaffuz_Sozlugu_2026.xlsx",
        help="2. Excel dosyası yolu",
    )
    parser.add_argument(
        "--vocab",
        default="config/freya_vocab.json",
        help="FreyaTTS vocab JSON dosyası",
    )
    parser.add_argument(
        "--out-compiled",
        default="config/automotive_compiled_lexicon.json",
        help="Derlenmiş sözlük JSON çıktısı",
    )
    parser.add_argument(
        "--out-unified",
        default="config/freyatts_automotive_lexicon.json",
        help="Birleşik sözlük JSON çıktısı",
    )
    parser.add_argument(
        "--out-root",
        default="freyatts_automotive_lexicon.json",
        help="Kök dizin birleşik sözlük JSON çıktısı",
    )
    parser.add_argument(
        "--out-flat",
        default="config/automotive_flat_lexicon.json",
        help="Düz sözlük JSON çıktısı",
    )
    args = parser.parse_args()

    build_lexicons(
        file1_path=Path(args.file1),
        file2_path=Path(args.file2),
        vocab_path=Path(args.vocab),
        output_compiled_path=Path(args.out_compiled),
        output_flat_path=Path(args.out_flat),
        output_unified_path=Path(args.out_unified),
        output_root_path=Path(args.out_root),
    )
