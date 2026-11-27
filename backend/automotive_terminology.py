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
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.normalizer_rules import BASE_AUTOMOTIVE_LEXICON, BASE_CATEGORIES, get_lexicon
from backend.text import normalize

logger = logging.getLogger("automotive_voice.terminology")

# Türkçe sayı, ek, hece ve genel sohbet sözcükleri; tekil model eşleşmesi olarak kabul edilmez.
NON_MODEL_STOPWORDS = frozenset({
    "sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz",
    "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan",
    "yüz", "bin", "milyon", "nokta", "virgül",
    "model", "araç", "araba", "paket", "lira", "türk", "lirası", "kuruş", "tl",
    "fiyat", "ekspertiz", "randevu", "beygir", "kilometre", "kilovat", "bg", "hp", "kw",
    "motor", "otomatik", "manuel", "dizel", "benzin", "hibrit", "hybrid", "elektrikli",
    "te", "se", "de", "ce", "ef", "ay", "ey", "haş", "es", "em", "ve", "ka", "be", "ti", "i",
    "yeni", "eski", "standart", "kapsamlı", "gold", "platinum", "yarın", "bugün", "sabah",
})

KNOWN_BRAND_TOKENS = frozenset({
    "toyota", "renault", "volkswagen", "folksvagen", "fiat", "ford", "honda",
    "hyundai", "hunday", "nissan", "nisan", "peugeot", "pejo", "pöjo",
    "citroen", "citroën", "sitroen", "opel", "dacia", "daçya",
    "skoda", "škoda", "bmw", "audi", "mercedes", "mercedes-benz", "mersedes",
    "togg", "tog", "chery", "çeri", "porsche", "porşe", "chevrolet", "şevrole",
    "kia", "seat", "cupra", "volvo", "suzuki", "mazda", "mini", "jeep", "land", "rover",
})

# Yalnızca kısa/belirsiz Türkçe kelimelerle çakışmayan, güvenli ASR -> Kanonik otomotiv eşlemeleri.
# Yapı: variant_lower -> (canonical, category)
CORE_ASR_PHONETIC_ALIASES: Dict[str, Tuple[str, str]] = {
    # Markalar
    "folksvagen": ("Volkswagen", "brand"),
    "folksfagen": ("Volkswagen", "brand"),
    "volksvagen": ("Volkswagen", "brand"),
    "wolkswagen": ("Volkswagen", "brand"),
    "force wagon": ("Volkswagen", "brand"),
    "force wagon puzzle": ("Volkswagen Passat", "model"),
    "pejo": ("Peugeot", "brand"),
    "pöjo": ("Peugeot", "brand"),
    "pežo": ("Peugeot", "brand"),
    "pejoo": ("Peugeot", "brand"),
    "pöjoo": ("Peugeot", "brand"),
    "peujo": ("Peugeot", "brand"),
    "reno": ("Renault", "brand"),
    "röno": ("Renault", "brand"),
    "rönö": ("Renault", "brand"),
    "renoo": ("Renault", "brand"),
    "sitroen": ("Citroën", "brand"),
    "sitroyen": ("Citroën", "brand"),
    "sitröen": ("Citroën", "brand"),
    "sitroyn": ("Citroën", "brand"),
    "hunday": ("Hyundai", "brand"),
    "hünday": ("Hyundai", "brand"),
    "hyunday": ("Hyundai", "brand"),
    "şkoda": ("Škoda", "brand"),
    "skoda": ("Škoda", "brand"),
    "iskoda": ("Škoda", "brand"),
    "daçya": ("Dacia", "brand"),
    "daçiya": ("Dacia", "brand"),
    "şevrole": ("Chevrolet", "brand"),
    "şevrolet": ("Chevrolet", "brand"),
    "şevroleh": ("Chevrolet", "brand"),
    "porşe": ("Porsche", "brand"),
    "mersedes": ("Mercedes", "brand"),
    "mersedes benz": ("Mercedes-Benz", "brand"),
    "be me ve": ("BMW", "brand"),
    "be em ve": ("BMW", "brand"),
    "bi em dabılyu": ("BMW", "brand"),
    "bmv": ("BMW", "brand"),
    "nisan": ("Nissan", "brand"),
    "toyoto": ("Toyota", "brand"),
    "çeri": ("Chery", "brand"),
    # Modeller
    "kaşkay": ("Qashqai", "model"),
    "kaşkai": ("Qashqai", "model"),
    "kaşkayi": ("Qashqai", "model"),
    "kaşkaay": ("Qashqai", "model"),
    "kaskai": ("Qashqai", "model"),
    "kaşgöl": ("Qashqai", "model"),
    "kaşker": ("Qashqai", "model"),
    "megan": ("Megane", "model"),
    "megaan": ("Megane", "model"),
    "mejan": ("Megane", "model"),
    "korola": ("Corolla", "model"),
    "korolla": ("Corolla", "model"),
    "pasat": ("Passat", "model"),
    "pasaat": ("Passat", "model"),
    "passaat": ("Passat", "model"),
    "tukson": ("Tucson", "model"),
    "tükson": ("Tucson", "model"),
    "oktavya": ("Octavia", "model"),
    "oktavia": ("Octavia", "model"),
    "süperb": ("Superb", "model"),
    "kaptur": ("Captur", "model"),
    "kamik": ("Kamiq", "model"),
    "ti rok": ("T-Roc", "model"),
    "tirok": ("T-Roc", "model"),
    "klio": ("Clio", "model"),
    "kilyo": ("Clio", "model"),
    "kuga": ("Kuga", "model"),
    # Motor, Şanzıman, Arıza ve Donanım Kısaltmaları
    "ti es ay": ("TSI", "technical"),
    "te se i": ("TSI", "technical"),
    "te es i": ("TSI", "technical"),
    "t s i": ("TSI", "technical"),
    "tesey i": ("TSI", "technical"),
    "tesey ay": ("TSI", "technical"),
    "tesei": ("TSI", "technical"),
    "tiesay": ("TSI", "technical"),
    "t ssi": ("TSI", "technical"),
    "eziz ay": ("TSI", "technical"),
    "te de i": ("TDI", "technical"),
    "t d i": ("TDI", "technical"),
    "tedei": ("TDI", "technical"),
    "ti di ay": ("TDI", "technical"),
    "tidiay": ("TDI", "technical"),
    "t de il": ("TDI", "technical"),
    "te ef es ay": ("TFSI", "technical"),
    "te fe se i": ("TFSI", "technical"),
    "te ef es i": ("TFSI", "technical"),
    "de ce i": ("dCi", "technical"),
    "dece i": ("dCi", "technical"),
    "d c i": ("dCi", "technical"),
    "di si ay": ("dCi", "technical"),
    "he de i": ("HDi", "technical"),
    "haş de i": ("HDi", "technical"),
    "eyç di ay": ("HDi", "technical"),
    "blu haş de i": ("BlueHDi", "technical"),
    "mavi hdi": ("BlueHDi", "technical"),
    "blue hdi": ("BlueHDi", "technical"),
    "te ce e": ("TCe", "technical"),
    "t c e": ("TCe", "technical"),
    "tece": ("TCe", "technical"),
    "eko ti es ay": ("EcoTSI", "technical"),
    "pürtek": ("PureTech", "technical"),
    "de se ge": ("DSG", "technical"),
    "desege": ("DSG", "technical"),
    "d s g": ("DSG", "technical"),
    "di es ci": ("DSG", "technical"),
    "e de ce": ("EDC", "technical"),
    "e d c": ("EDC", "technical"),
    "e a te sekiz": ("EAT8", "technical"),
    "o be de": ("OBD-II", "technical"),
    "obd 2": ("OBD-II", "technical"),
    "obd iki": ("OBD-II", "technical"),
    "o b d": ("OBD-II", "technical"),
    "e ce u": ("ECU", "technical"),
    "i si yu": ("ECU", "technical"),
    "e se pe": ("ESP", "technical"),
    "i es pi": ("ESP", "technical"),
    "a be se": ("ABS", "technical"),
    "ey bi es": ("ABS", "technical"),
    "a ve de": ("AWD", "technical"),
    "ey dabılyu di": ("AWD", "technical"),
    "ce de i": ("CDI", "technical"),
    "cedei": ("CDI", "technical"),
    "si di ay": ("CDI", "technical"),
    "be e ve": ("BEV", "technical"),
    "pe he e ve": ("PHEV", "technical"),
    "e ce ve te": ("e-CVT", "technical"),
    "i ce ve te": ("e-CVT", "technical"),
    "i pavır": ("e-Power", "technical"),
    "e power": ("e-Power", "technical"),
    "i tek": ("e-Tech", "technical"),
    "e tech": ("e-Tech", "technical"),
    "ce ve te": ("CVT", "technical"),
    "si vi ti": ("CVT", "technical"),
    "te pe me se": ("TPMS", "technical"),
    "ti pi em es": ("TPMS", "technical"),
    "ed blu": ("AdBlue", "technical"),
    "ad blue": ("AdBlue", "technical"),
    "et blu": ("AdBlue", "technical"),
    "p 0 300": ("P0300", "dtc"),
    "p0 300": ("P0300", "dtc"),
    "pe sıfır üç yüz": ("P0300", "dtc"),
    "p sıfır üç yüz": ("P0300", "dtc"),
    "p 0 171": ("P0171", "dtc"),
    "pe sıfır yüz yetmiş bir": ("P0171", "dtc"),
}

# Türkçe konuşmada geçen sözcüklerle çakışma ihtimali yüksek kısa/jenerik kelimeler ASLA alias yapılmaz.
_UNSAFE_ALIAS_WORDS = frozenset({
    "ds", "ce", "be", "de", "te", "se", "ef", "ka", "le", "me", "ne", "re", "ve", "ye", "ze",
    "ara", "ek", "al", "ol", "et", "at", "var", "yok", "bir", "iki", "üç", "dört", "beş",
    "fiyat", "cam", "far", "kapı", "yol", "gün", "ses", "su", "tip", "gaz", "kar", "tür",
    "line", "sport", "life", "style", "active", "plus", "pro", "max", "air", "hybrid",
    "nisan",  # DİKKAT: tek başına "nisan" bazen ay adı ("3 nisan") olabilir; yalnızca araç/model bağlamı dışında dikkat
})

_CANON_LOCK = threading.Lock()
_CACHED_ALIAS_MAP: Optional[Dict[str, Tuple[str, str]]] = None
_CACHED_PATTERN: Optional[re.Pattern] = None
_CACHED_CANONICAL_LOOKUP: Optional[Dict[str, Tuple[str, str]]] = None


def tr_lower(text: str) -> str:
    """Türkçe I/İ kurallarına sadık küçük harfe çeviri."""
    return text.replace("İ", "i").replace("I", "ı").lower().replace("i̇", "i")


def normalize_apostrophes(text: str) -> str:
    return re.sub(r"[’´`]", "'", text)


def split_glued_codes(text: str) -> str:
    """Bitişik yazılmış sayı ve harfleri ayırır (örn. '1.5TSI' -> '1.5 TSI', '3008BlueHDi')."""
    # P0300 / P0171 gibi OBD DTC kodları veya Q3/Q5/X5/T10X/EAT8 gibi kısa model kodları bozulmaz.
    protected = re.sub(
        r"\b(P0\d{3}|[A-ZÇĞİÖŞÜ]{1,2}\d{1,2}|EAT8|T10X|T10F|ID\.?\d|4x4)\b",
        lambda m: f"__PROT_{m.group(0)}__",
        text,
    )
    separated = re.sub(r"(?<=\d)(?=[^\W\d_])|(?<=[^\W\d_])(?=\d)", " ", protected)
    return re.sub(r"__PROT_(.*?)__", r"\1", separated)


def _find_compiled_lexicon_path() -> Optional[Path]:
    for candidate in (
        Path("config/freyatts_automotive_lexicon.json"),
        Path("freyatts_automotive_lexicon.json"),
    ):
        if candidate.exists():
            return candidate
    return None


def _build_canonical_index() -> Tuple[Dict[str, Tuple[str, str]], re.Pattern, Dict[str, Tuple[str, str]]]:
    """Derlenmiş otomotiv sözlüğünü ve çekirdek fonetik kuralları tek seferde derler."""
    alias_map: Dict[str, Tuple[str, str]] = {}
    canonical_lookup: Dict[str, Tuple[str, str]] = {}

    # 1. BASE_AUTOMOTIVE_LEXICON içindeki ters fonetik eşlemeler
    for term_key, spoken_val in BASE_AUTOMOTIVE_LEXICON.items():
        cat = BASE_CATEGORIES.get(term_key, "technical")
        canon_disp = term_key.upper() if cat == "technical" and len(term_key) <= 4 else term_key.title()
        canonical_lookup[tr_lower(term_key)] = (canon_disp, cat)

        spk_low = tr_lower(spoken_val).strip()
        if (
            spk_low
            and spk_low != tr_lower(term_key)
            and len(spk_low) >= 4
            and spk_low not in _UNSAFE_ALIAS_WORDS
        ):
            alias_map.setdefault(spk_low, (canon_disp, cat))

    # 2. Çekirdek Whisper fonetik kuralları (yüksek doğruluk, "nissan"/"qashqai" hariç "nisan" bağlamsal kalır)
    for variant, (canon, cat) in CORE_ASR_PHONETIC_ALIASES.items():
        v_low = tr_lower(variant).strip()
        if v_low == "nisan":
            # "3 nisan" tarihini bozmamak için "nisan <model>" formunda yakalanır
            continue
        alias_map[v_low] = (canon, cat)
        canonical_lookup.setdefault(tr_lower(canon), (canon, cat))

    # "nisan kaşkai/qashqai/juke/micra/x-trail" gibi güvenli marka+model tamlamaları
    for nissan_model in ("kaşkai", "kaşkay", "kaşgöl", "qashqai", "juke", "micra", "x-trail", "note", "navara", "pulsar"):
        alias_map[f"nisan {nissan_model}"] = (
            f"Nissan {'Qashqai' if nissan_model.startswith('kaş') else nissan_model.title()}",
            "model",
        )

    # 3. config/freyatts_automotive_lexicon.json dosyasından güvenli ek alias'lar
    lex_path = _find_compiled_lexicon_path()
    if lex_path is not None:
        try:
            data = json.loads(lex_path.read_text(encoding="utf-8"))
            for item in data.get("brands", []):
                canon = (item.get("canonical") or item.get("source") or "").strip()
                if not canon:
                    continue
                canonical_lookup.setdefault(tr_lower(canon), (canon, "brand"))
                candidates = list(item.get("asr_variants") or []) + list(item.get("aliases") or [])
                spk = (item.get("tts_2026") or item.get("spoken") or "").strip()
                if spk:
                    candidates.append(spk)
                for cand in candidates:
                    c_low = tr_lower(cand).strip()
                    if (
                        len(c_low) >= 4
                        and c_low != tr_lower(canon)
                        and c_low not in _UNSAFE_ALIAS_WORDS
                        and c_low not in alias_map
                    ):
                        alias_map[c_low] = (canon, "brand")

            for item in data.get("asr_mappings", []):
                var = (item.get("variant") or "").strip()
                canon = (item.get("canonical") or "").strip()
                cat = "brand" if item.get("alias_type") == "Marka" else "model"
                v_low = tr_lower(var)
                if (
                    len(v_low) >= 4
                    and canon
                    and v_low != tr_lower(canon)
                    and v_low not in _UNSAFE_ALIAS_WORDS
                    and v_low not in alias_map
                ):
                    alias_map[v_low] = (canon, cat)
        except Exception:
            logger.warning("Otomotiv derlenmiş leksikon okunamadı: %s", lex_path, exc_info=True)

    # En uzun eşleşme önce gelecek tek geçişli regex
    sorted_variants = sorted(alias_map.keys(), key=len, reverse=True)
    if sorted_variants:
        alternatives = "|".join(re.escape(v) for v in sorted_variants)
        compiled = re.compile(rf"(?<![\w-])({alternatives})(?![\w-])", re.IGNORECASE)
    else:
        compiled = re.compile(r"(?!x)x")

    return alias_map, compiled, canonical_lookup


def _get_compiled_index() -> Tuple[Dict[str, Tuple[str, str]], re.Pattern, Dict[str, Tuple[str, str]]]:
    global _CACHED_ALIAS_MAP, _CACHED_PATTERN, _CACHED_CANONICAL_LOOKUP
    with _CANON_LOCK:
        if _CACHED_ALIAS_MAP is None or _CACHED_PATTERN is None or _CACHED_CANONICAL_LOOKUP is None:
            _CACHED_ALIAS_MAP, _CACHED_PATTERN, _CACHED_CANONICAL_LOOKUP = _build_canonical_index()
        return _CACHED_ALIAS_MAP, _CACHED_PATTERN, _CACHED_CANONICAL_LOOKUP


def canonicalize_asr_text(raw_text: str) -> Dict[str, Any]:
    """Ham ASR transkriptini koruyarak otomotiv terimlerini kanonik forma çözümler."""
    if not raw_text or not raw_text.strip():
        return {
            "raw_transcript": raw_text or "",
            "canonical_text": "",
            "applied_mappings": [],
            "detected_brands": [],
            "detected_models": [],
            "detected_technical": [],
            "canonical_terms": [],
        }

    alias_map, pattern, canonical_lookup = _get_compiled_index()
    prepared = normalize_apostrophes(split_glued_codes(raw_text.strip()))
    applied: List[Dict[str, str]] = []

    def _replace(m: re.Match) -> str:
        matched = m.group(0)
        key = tr_lower(matched)
        entry = alias_map.get(key)
        if not entry:
            return matched
        canon, cat = entry
        if tr_lower(matched) != tr_lower(canon) or matched != canon:
            applied.append({"from": matched, "to": canon, "category": cat})
        return canon

    canonical_text = pattern.sub(_replace, prepared)

    # Tarih koruması olmayan gerçek araç bağlamında "Nisan Qashqai" gibi düzeltme
    canonical_text = re.sub(
        r"\bNisan\s+(Qashqai|Juke|Micra|X-Trail|Navara|Note|Pulsar)\b",
        r"Nissan \1",
        canonical_text,
        flags=re.IGNORECASE,
    )

    # Tespit edilen kanonik terimleri çıkar
    canon_low = tr_lower(canonical_text)
    brands: List[str] = []
    models: List[str] = []
    technical: List[str] = []

    for term_key, (canon_disp, cat) in canonical_lookup.items():
        if len(term_key) < 2:
            continue
        if re.search(rf"(?<![\w-]){re.escape(term_key)}(?![\w-])", canon_low):
            if cat == "brand" and canon_disp not in brands:
                brands.append(canon_disp)
            elif cat == "model" and canon_disp not in models:
                models.append(canon_disp)
            elif cat in ("technical", "dtc") and canon_disp not in technical:
                technical.append(canon_disp)

    for item in applied:
        c = item["to"]
        cat = item["category"]
        if cat == "brand" and c not in brands:
            brands.append(c)
        elif cat == "model" and c not in models:
            models.append(c)
        elif cat in ("technical", "dtc") and c not in technical:
            technical.append(c)

    all_terms = list(dict.fromkeys(brands + models + technical))
    return {
        "raw_transcript": raw_text,
        "canonical_text": canonical_text,
        "applied_mappings": applied,
        "detected_brands": brands,
        "detected_models": models,
        "detected_technical": technical,
        "canonical_terms": all_terms,
    }


def _squash(s: str) -> str:
    return re.sub(r"\W+", " ", s).strip()


def match_catalog_vehicle(vehicles: Iterable[Any], raw_text: str) -> Dict[str, Any]:
    """Ham veya ASR-bozuk metni katalogdaki araçlarla yanlış pozitif üretmeden eşleştirir."""
    canon_info = canonicalize_asr_text(raw_text)
    canon_text = canon_info["canonical_text"]
    clean_raw = tr_lower(_squash(raw_text))
    clean_canon = tr_lower(_squash(canon_text))
    try:
        clean_spoken = tr_lower(_squash(normalize(canon_text)["normalized"])) if canon_text.strip() else ""
    except ValueError:
        clean_spoken = clean_canon

    candidates: List[Tuple[int, Any]] = []
    for v in vehicles:
        desc = getattr(v, "description", "") or ""
        raw_desc = tr_lower(_squash(desc))
        if not raw_desc:
            continue
        try:
            norm_desc = tr_lower(_squash(normalize(desc)["normalized"]))
        except ValueError:
            norm_desc = raw_desc

        score = 0
        # 1. Tam araç tanımı eşleşmesi (kelime sınırıyla)
        if raw_desc and f" {raw_desc} " in f" {clean_canon} ":
            score = 100
        elif raw_desc and f" {raw_desc} " in f" {clean_raw} ":
            score = 95
        elif norm_desc and f" {norm_desc} " in f" {clean_spoken} ":
            score = 90
        else:
            # 2. Ayırt edici model token'ları (sayı/motor dolgu kelimeleri hariç!)
            raw_tokens = [
                w for w in raw_desc.split()
                if len(w) >= 3
                and w not in NON_MODEL_STOPWORDS
                and w not in KNOWN_BRAND_TOKENS
                and not (w.isdigit() and len(w) <= 2)
            ]
            # Ör. "3008", "2008", "T10X", "Corolla", "Passat", "Qashqai", "Egea", "Megane", "C3"
            matched_tokens = [
                w for w in raw_tokens
                if (
                    f" {w} " in f" {clean_canon} "
                    or f" {w} " in f" {clean_raw} "
                    or f" {w} " in f" {clean_spoken} "
                )
            ]
            if matched_tokens:
                # Yalnızca motor hacmi ("tsi", "tdi") veya yıl ("2020") tek başına araç seçmesin
                distinctive = [
                    w for w in matched_tokens
                    if tr_lower(w) not in {"tsi", "tdi", "tfsi", "dci", "hdi", "bluehdi", "dsg", "cvt"}
                    and not (w.isdigit() and 1990 <= int(w) <= 2035)
                ]
                if distinctive:
                    score = 50 + min(40, len(distinctive) * 15)

        if score > 0:
            candidates.append((score, v))

    candidates.sort(key=lambda item: -item[0])
    top_score = candidates[0][0] if candidates else 0
    top_matches = [v for sc, v in candidates if sc == top_score] if candidates else []

    brand_only_detected = None
    if not candidates and canon_info["detected_brands"] and not canon_info["detected_models"]:
        brand_only_detected = canon_info["detected_brands"][0]

    return {
        "matched_vehicle": top_matches[0] if len(top_matches) == 1 else None,
        "candidates": [v for _, v in candidates],
        "ambiguous": len(top_matches) > 1,
        "brand_only_detected": brand_only_detected,
        "canonical_info": canon_info,
    }


def analyze_acoustic_report_layer_attribution(report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Mevcut akustik benchmark raporundaki kaçan terimleri katmanlara ayırır.

    Dürüstlük kuralı: Sıkı (strict) terim doğruluğunu ASLA şişirmez; yalnızca
    ASR fonetik yazım farkından kaynaklanan kurtarılabilir payı ayrı raporlar.
    """
    if not report or "rows" not in report:
        return {"available": False, "reason": "Akustik ölçüm raporu bulunamadı."}

    from backend.acoustic_evaluation import canonical, evaluate_transcript

    gate_channel = report.get("gate_channel", "telephony_8k")
    rows = report.get("rows", [])

    terms_total = 0
    strict_correct = 0
    canonical_recovered_correct = 0
    per_term_breakdown: Dict[str, Dict[str, int]] = {}
    sample_recoveries: List[Dict[str, Any]] = []

    for row in rows:
        ch = (row.get("channels") or {}).get(gate_channel)
        if not ch:
            continue
        t_tot = int(ch.get("terms_total", 0))
        t_cor = int(ch.get("terms_correct", 0))
        missed = ch.get("terms_missed") or []
        terms_total += t_tot
        strict_correct += t_cor

        if not missed:
            canonical_recovered_correct += t_cor
            continue

        raw_transcript = ch.get("transcript", "")
        canon_res = canonicalize_asr_text(raw_transcript)
        canon_eval = evaluate_transcript(row.get("text", ""), canon_res["canonical_text"])
        after_missed = set(canon_eval.get("terms_missed") or [])

        recovered_here = [m for m in missed if m not in after_missed]
        canonical_recovered_correct += (t_tot - len(after_missed))

        for m in missed:
            entry = per_term_breakdown.setdefault(m, {"missed_raw": 0, "recovered_by_canonical": 0, "true_acoustic_or_tts_miss": 0})
            entry["missed_raw"] += 1
            if m in after_missed:
                entry["true_acoustic_or_tts_miss"] += 1
            else:
                entry["recovered_by_canonical"] += 1

        if recovered_here and len(sample_recoveries) < 12:
            sample_recoveries.append({
                "id": row.get("id"),
                "source_text": row.get("text"),
                "raw_asr_transcript": canonical(raw_transcript),
                "canonical_asr_transcript": canon_res["canonical_text"],
                "recovered_terms": recovered_here,
                "remaining_missed": sorted(after_missed),
            })

    strict_pct = round(strict_correct / terms_total * 100.0, 2) if terms_total else None
    recovered_pct = round(canonical_recovered_correct / terms_total * 100.0, 2) if terms_total else None

    return {
        "available": True,
        "measured_at": report.get("measured_at"),
        "channel": gate_channel,
        "sample_count": report.get("sample_count", len(rows)),
        "terms_total": terms_total,
        "strict_correct": strict_correct,
        "strict_term_accuracy_pct": strict_pct,
        "canonical_recovered_correct": canonical_recovered_correct,
        "post_canonical_accuracy_pct": recovered_pct,
        "asr_phonetic_recoverable_count": max(0, canonical_recovered_correct - strict_correct),
        "true_pronunciation_or_acoustic_miss_count": max(0, terms_total - canonical_recovered_correct),
        "per_term_breakdown": dict(
            sorted(per_term_breakdown.items(), key=lambda kv: -kv[1]["missed_raw"])
        ),
        "sample_recoveries": sample_recoveries,
    }


def run_terminology_verification_suite(db=None) -> Dict[str, Any]:
    """Otomotiv Terim Doğrulama Protokolü: çift yönlü F4 sentez ve F2/F3 ASR/plaka denetimi."""
    from backend.turkish_plate import TurkishPlateParser
    from backend.db import Vehicle
    from sqlalchemy import select

    vocab_chars: Optional[set[str]] = None
    vocab_path = Path("config/freya_vocab.json")
    if vocab_path.exists():
        vocab_chars = set(json.loads(vocab_path.read_text(encoding="utf-8")).keys())

    # 1. Çıkış Yolu (F4 Normalizer -> FreyaTTS Karakter Sözlüğü) & 2. Giriş Yolu (Whisper ASR -> Kanonik)
    audit_cases = [
        # Markalar
        {
            "id": "TERM-BRAND-01",
            "category": "markalar",
            "direction": "outbound_tts",
            "input": "Volkswagen Passat aracınız için randevu.",
            "expected_tokens": ["folksvagen", "passat"],
        },
        {
            "id": "TERM-BRAND-02",
            "category": "markalar",
            "direction": "inbound_asr",
            "input": "Pejo ve Reno için ekspertiz istiyorum.",
            "expected_canonical": ["Peugeot", "Renault"],
        },
        {
            "id": "TERM-BRAND-03",
            "category": "markalar",
            "direction": "inbound_asr",
            "input": "Folksvagen ile Sitroen karşılaştırması.",
            "expected_canonical": ["Volkswagen", "Citroën"],
        },
        # Modeller
        {
            "id": "TERM-MODEL-01",
            "category": "modeller",
            "direction": "outbound_tts",
            "input": "Nissan Qashqai e-Power kontrolü.",
            "expected_tokens": ["nisan", tr_lower(get_lexicon().get("qashqai", "kaşkai")), "i pavır"],
        },
        {
            "id": "TERM-MODEL-02",
            "category": "modeller",
            "direction": "inbound_asr",
            "input": "Nisan Kaşkay ve Hunday Tukson için fiyat alabilir miyim?",
            "expected_canonical": ["Nissan", "Qashqai", "Hyundai", "Tucson"],
        },
        {
            "id": "TERM-MODEL-03",
            "category": "modeller",
            "direction": "inbound_asr",
            "input": "Korola ile Reno Megan müsait mi?",
            "expected_canonical": ["Corolla", "Renault", "Megane"],
        },
        # Motor & Teknik
        {
            "id": "TERM-TECH-01",
            "category": "motor_teknik",
            "direction": "outbound_tts",
            "input": "1.5 TSI ve 1.6 TDI araçlarda DSG kontrolü.",
            "expected_tokens": ["bir nokta beş", "te de i", "dsg"],
        },
        {
            "id": "TERM-TECH-02",
            "category": "motor_teknik",
            "direction": "inbound_asr",
            "input": "1.5 te se i motor, de se ge şanzıman ve o be de p 0 300 arızası var.",
            "expected_canonical": ["TSI", "DSG", "OBD-II", "P0300"],
        },
        {
            "id": "TERM-TECH-03",
            "category": "motor_teknik",
            "direction": "inbound_asr",
            "input": "1.5 blu haş de i ve 1.3 te ce e ekspertiz.",
            "expected_canonical": ["BlueHDi", "TCe"],
        },
        # Plaka & Düzeltme
        {
            "id": "TERM-PLATE-01",
            "category": "plaka_duzeltme",
            "direction": "plate_parse",
            "input": "Otuz dört Adana Bursa Ceyhan yüz yirmi üç",
            "expected_plate": "34 ABC 123",
        },
        {
            "id": "TERM-PLATE-02",
            "category": "plaka_duzeltme",
            "direction": "plate_parse",
            "input": "otuz dört ABC yüz yirmi üç",
            "expected_plate": "34 ABC 123",
        },
        {
            "id": "TERM-PLATE-03",
            "category": "plaka_duzeltme",
            "direction": "plate_correct",
            "base_plate": "34 ABC 123",
            "input": "C değil Denizlinin Dsi",
            "expected_plate": "34 ABD 123",
        },
        {
            "id": "TERM-PLATE-04",
            "category": "plaka_duzeltme",
            "direction": "plate_correct",
            "base_plate": "34 ABC 123",
            "input": "B değil de Ankara'nın A'sı",
            "expected_plate": "34 AAC 123",
        },
        # Fiyat & Saat
        {
            "id": "TERM-PRICE-01",
            "category": "fiyat_saat",
            "direction": "outbound_tts",
            "input": "Yarın saat 14:30'da bedel 2.500 TL.",
            "expected_tokens": ["on dört otuzda", "iki bin beş yüz türk lirası"],
        },
    ]

    results: List[Dict[str, Any]] = []
    for case in audit_cases:
        direction = case["direction"]
        passed = False
        actual = ""
        error_reason = None

        try:
            if direction == "outbound_tts":
                res = normalize(case["input"])
                norm_str = res["normalized"]
                norm_low = tr_lower(norm_str)
                vocab_ok = True
                if vocab_chars is not None:
                    missing = sorted(set(norm_str.replace("Ğ", "ğ")) - vocab_chars)
                    vocab_ok = len(missing) == 0
                    if missing:
                        error_reason = f"Vocab eksik: {missing}"
                tokens_ok = all(tr_lower(tok) in norm_low for tok in case["expected_tokens"])
                if not tokens_ok and not error_reason:
                    error_reason = "Beklenen telaffuz öbekleri eşleşmedi"
                passed = vocab_ok and tokens_ok
                actual = norm_str
            elif direction == "inbound_asr":
                c_res = canonicalize_asr_text(case["input"])
                c_text_low = tr_lower(c_res["canonical_text"])
                passed = all(tr_lower(tok) in c_text_low for tok in case["expected_canonical"])
                actual = c_res["canonical_text"]
                if not passed:
                    error_reason = f"Eksik kanonik terimler: {[t for t in case['expected_canonical'] if tr_lower(t) not in c_text_low]}"
            elif direction == "plate_parse":
                p_res = TurkishPlateParser.parse_spoken(case["input"])
                actual = p_res.plate if p_res else ""
                passed = actual == case["expected_plate"]
                if not passed:
                    error_reason = f"Beklenen: {case['expected_plate']}, Alınan: {actual or 'None'}"
            elif direction == "plate_correct":
                c_res = TurkishPlateParser.correct_plate(case["base_plate"], case["input"])
                actual = c_res.plate if (c_res and c_res.is_correction) else ""
                passed = actual == case["expected_plate"]
                if not passed:
                    error_reason = f"Beklenen: {case['expected_plate']}, Alınan: {actual or 'None'}"
        except Exception as exc:
            error_reason = f"{type(exc).__name__}: {exc}"

        results.append({
            "id": case["id"],
            "category": case["category"],
            "direction": direction,
            "input": case["input"],
            "actual": actual,
            "passed": passed,
            "error": error_reason,
        })

    # Veritabanı katalog eşleştirme kontrolü (varsa aktif araçlar + yanlış pozitif bariyeri)
    if db is not None:
        vehicles = db.scalars(select(Vehicle)).all()
        # Yanlış pozitif bariyeri testi ("Bir randevu istiyorum" araç eşlememeli)
        fp_check = match_catalog_vehicle(vehicles, "Bir randevu istiyorum")
        results.append({
            "id": "TERM-CAT-FP-GUARD",
            "category": "katalog_eslesme",
            "direction": "catalog_guard",
            "input": "Bir randevu istiyorum",
            "actual": fp_check["matched_vehicle"].description if fp_check["matched_vehicle"] else "None (Korundu)",
            "passed": fp_check["matched_vehicle"] is None,
            "error": "Sayı sözcüğü yanlış araç eşleşmesine yol açtı" if fp_check["matched_vehicle"] is not None else None,
        })
        for idx, v in enumerate(vehicles[:10], start=1):
            norm_res = canonicalize_asr_text(v.description)
            m_res = match_catalog_vehicle(vehicles, norm_res["canonical_text"])
            matched_id = m_res["matched_vehicle"].id if m_res["matched_vehicle"] else None
            ok = matched_id == v.id or len(m_res["candidates"]) >= 1
            results.append({
                "id": f"TERM-CAT-{idx:02d}",
                "category": "katalog_eslesme",
                "direction": "catalog_roundtrip",
                "input": v.description,
                "actual": m_res["matched_vehicle"].description if m_res["matched_vehicle"] else (f"{len(m_res['candidates'])} aday" if m_res["candidates"] else "Eşleşmedi"),
                "passed": ok,
                "error": None if ok else "Kayıtlı katalog aracı metinden çözülemedi",
            })

    # Kategori özetleri
    categories: Dict[str, Dict[str, Any]] = {}
    for r in results:
        cat = categories.setdefault(r["category"], {"passed": 0, "total": 0})
        cat["total"] += 1
        if r["passed"]:
            cat["passed"] += 1
    for cat in categories.values():
        cat["rate_pct"] = round(cat["passed"] / cat["total"] * 100.0, 2) if cat["total"] else 0.0

    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)

    # Akustik katman ayrıştırması (en son akustik rapor mevcutsa)
    from backend.acoustic_evaluation import load_latest_report
    acoustic_attribution = analyze_acoustic_report_layer_attribution(load_latest_report())

    return {
        "total": total_count,
        "passed": passed_count,
        "failed": total_count - passed_count,
        "pass_rate_pct": round(passed_count / total_count * 100.0, 2) if total_count else 0.0,
        "categories": categories,
        "cases": results,
        "acoustic_attribution": acoustic_attribution,
        "active_lexicon_count": len(get_lexicon()),
    }
