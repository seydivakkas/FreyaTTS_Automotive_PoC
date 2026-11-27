"""Automotive normalization rules migrated from the original PoC."""

import json
import re
import threading
from pathlib import Path
from typing import Dict, List

BASE_AUTOMOTIVE_LEXICON: Dict[str, str] = {
    # Otomobil Markalari
    "volkswagen": "Folksvagen",
    "peugeot": "Pejo",
    "renault": "Reno",
    "citroën": "Sitroen",
    "citroen": "Sitroen",
    "qashqai": "Kaşkai",
    "nissan": "Nisan",
    "hyundai": "Hunday",
    "škoda": "Skoda",
    "skoda": "Skoda",
    "dacia": "Daçya",
    "chevrolet": "Şevrole",
    "porsche": "Porşe",
    "mercedes-benz": "Mersedes Benz",
    "mercedes": "Mersedes",
    "audi": "Audi",
    "bmw": "Be Me Ve",
    "chery": "Çeri",
    "togg": "Tog",
    # Model ve Paket Isimleri
    "passat": "Passat",
    "tiguan": "Tiguan",
    "t-roc": "Ti Rok",
    "tucson": "Tukson",
    "megane": "Megaan",
    "mégane": "Megaan",
    "captur": "Kaptur",
    "kamiq": "Kamik",
    "octavia": "Oktavya",
    "superb": "Süperb",
    "corolla": "Korolla",
    "q2": "ku iki",
    "q3": "ku üç",
    "q5": "ku beş",
    "q7": "ku yedi",
    "q8": "ku sekiz",
    "e-power": "i pavır",
    "e-tech": "i tek",
    "hybrid": "hibrit",
    "lounge": "launc",
    "touch": "taç",
    "prestige": "prestij",
    "comfortline": "komfortlayn",
    "highline": "haylayn",
    "trendline": "trendlayn",
    # Motor, Sanziman ve Guvenlik Kisaltmalari
    "tsi": "ti es ay",
    "tdi": "te de i",
    "tfsi": "ti ef es ay",
    "dci": "de ce i",
    "bluehdi": "blu haş de i",
    "hdi": "he de i",
    "tce": "te ce e",
    "multijet": "multijet",
    "puretech": "pürtek",
    "ecotsi": "eko ti es ay",
    "dsg": "DSG",
    "edc": "e de ce",
    "eat8": "e a te sekiz",
    "cvt": "CVT",
    "suv": "suv",
    "abs": "ABS",
    "esp": "e se pe",
    "kdv": "ka de ve",
    "ötv": "ö te ve",
    "mtv": "me te ve",
    "tramer": "tramer",
    "cdi": "ce de i",
    "e-cvt": "i ce ve te",
    "obd": "o be de",
    "ecu": "e ce u",
    "tpms": "TPMS",
    "awd": "a ve de",
    "phev": "pe he e ve",
    "bev": "be e ve",
}

BASE_CATEGORIES: Dict[str, str] = {
    # Markalar
    "volkswagen": "brand",
    "peugeot": "brand",
    "renault": "brand",
    "citroën": "brand",
    "citroen": "brand",
    "nissan": "brand",
    "hyundai": "brand",
    "škoda": "brand",
    "skoda": "brand",
    "dacia": "brand",
    "chevrolet": "brand",
    "porsche": "brand",
    "mercedes-benz": "brand",
    "mercedes": "brand",
    "audi": "brand",
    "bmw": "brand",
    "chery": "brand",
    "togg": "brand",
    # Modeller
    "qashqai": "model",
    "passat": "model",
    "tiguan": "model",
    "t-roc": "model",
    "tucson": "model",
    "megane": "model",
    "mégane": "model",
    "captur": "model",
    "kamiq": "model",
    "octavia": "model",
    "superb": "model",
    "corolla": "model",
    "q2": "model",
    "q3": "model",
    "q5": "model",
    "q7": "model",
    "q8": "model",
    "e-power": "model",
    "e-tech": "model",
    "hybrid": "model",
    "lounge": "model",
    "touch": "model",
    "prestige": "model",
    "comfortline": "model",
    "highline": "model",
    "trendline": "model",
    # Teknik
    "tsi": "technical",
    "tdi": "technical",
    "tfsi": "technical",
    "dci": "technical",
    "bluehdi": "technical",
    "hdi": "technical",
    "tce": "technical",
    "multijet": "technical",
    "puretech": "technical",
    "ecotsi": "technical",
    "dsg": "technical",
    "edc": "technical",
    "eat8": "technical",
    "cvt": "technical",
    "suv": "technical",
    "abs": "technical",
    "esp": "technical",
    "kdv": "technical",
    "ötv": "technical",
    "mtv": "technical",
    "tramer": "technical",
    "cdi": "technical",
    "e-cvt": "technical",
    "obd": "technical",
    "ecu": "technical",
    "tpms": "technical",
    "awd": "technical",
    "phev": "technical",
    "bev": "technical",
}

AUTOMOTIVE_LEXICON: Dict[str, str] = dict(BASE_AUTOMOTIVE_LEXICON)
CUSTOM_LEXICON: Dict[str, str] = {}
CUSTOM_CATEGORIES: Dict[str, str] = {}
_lexicon_lock = threading.Lock()


def load_custom_lexicon(path: Path | str = "config/lexicon.json") -> int:
    """Loads custom terms and overrides from JSON file and updates AUTOMOTIVE_LEXICON."""
    p = Path(path)
    if not p.exists():
        return 0
    with _lexicon_lock:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return 0

        cat_file = p.parent / "lexicon_categories.json"
        saved_cats = {}
        if cat_file.exists():
            try:
                saved_cats = json.loads(cat_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        count = 0
        for k, v in data.items():
            if not k:
                continue
            spoken = v.get("spoken", "") if isinstance(v, dict) else str(v)
            cat = v.get("category", "") if isinstance(v, dict) else saved_cats.get(k, "")
            if not spoken:
                continue
            CUSTOM_LEXICON[k] = spoken
            if cat:
                CUSTOM_CATEGORIES[k] = cat
            AUTOMOTIVE_LEXICON[k.lower()] = spoken
            count += 1
        return count


def save_custom_lexicon(path: Path | str = "config/lexicon.json") -> None:
    """Saves custom terms to config/lexicon.json and config/lexicon_categories.json."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lexicon_lock:
        p.write_text(json.dumps(CUSTOM_LEXICON, ensure_ascii=False, indent=2), encoding="utf-8")
        cat_file = p.parent / "lexicon_categories.json"
        cat_file.write_text(json.dumps(CUSTOM_CATEGORIES, ensure_ascii=False, indent=2), encoding="utf-8")


def get_lexicon() -> Dict[str, str]:
    """Returns a thread-safe copy of the active lexicon."""
    with _lexicon_lock:
        return dict(AUTOMOTIVE_LEXICON)


def get_lexicon_entries() -> List[dict]:
    """Returns detailed entries of all terms, categories, and override status."""
    with _lexicon_lock:
        all_terms = {}
        for k, spoken in BASE_AUTOMOTIVE_LEXICON.items():
            all_terms[k] = {
                "term": k,
                "spoken": spoken,
                "category": BASE_CATEGORIES.get(k, "technical"),
                "is_base": True,
                "is_override": False,
            }
        for term, spoken in CUSTOM_LEXICON.items():
            k_low = term.lower()
            cat = CUSTOM_CATEGORIES.get(term, "")
            if k_low in all_terms:
                all_terms[k_low]["term"] = term
                all_terms[k_low]["spoken"] = spoken
                all_terms[k_low]["is_override"] = (spoken != BASE_AUTOMOTIVE_LEXICON.get(k_low))
                if cat:
                    all_terms[k_low]["category"] = cat
            else:
                all_terms[k_low] = {
                    "term": term,
                    "spoken": spoken,
                    "category": cat or "custom",
                    "is_base": False,
                    "is_override": False,
                }
        return sorted(all_terms.values(), key=lambda x: x["term"].lower())


def set_lexicon_term(
    term: str,
    spoken: str,
    category: str = "custom",
    path: Path | str = "config/lexicon.json",
) -> dict:
    """Adds or updates a pronunciation term in active memory and persists it."""
    clean_term = term.strip()
    clean_spoken = spoken.strip()
    if not clean_term:
        raise ValueError("Terim boş olamaz")
    if not clean_spoken:
        raise ValueError("Telaffuz boş olamaz")
    if len(clean_term) > 100 or len(clean_spoken) > 160:
        raise ValueError("Terim veya telaffuz uzunluk sınırını aşıyor")

    vocab_file = Path("config/freya_vocab.json")
    if vocab_file.exists():
        try:
            vocab = set(json.loads(vocab_file.read_text(encoding="utf-8")).keys())
            check_str = clean_spoken.replace("Ğ", "ğ")
            unsupported = sorted(set(check_str) - vocab)
            if unsupported:
                chars_str = " ".join(unsupported)
                raise ValueError(
                    f"Telaffuz metni model karakter sözlüğünde olmayan karakterler içeriyor: {chars_str}"
                )
        except ValueError:
            raise
        except Exception:
            pass

    k_low = clean_term.lower()
    with _lexicon_lock:
        CUSTOM_LEXICON[clean_term] = clean_spoken
        CUSTOM_CATEGORIES[clean_term] = category or "custom"
        AUTOMOTIVE_LEXICON[k_low] = clean_spoken

    save_custom_lexicon(path)
    is_base = k_low in BASE_AUTOMOTIVE_LEXICON
    is_override = is_base and (clean_spoken != BASE_AUTOMOTIVE_LEXICON.get(k_low))
    return {
        "term": clean_term,
        "spoken": clean_spoken,
        "category": category or "custom",
        "is_base": is_base,
        "is_override": is_override,
    }


def delete_lexicon_term(term: str, path: Path | str = "config/lexicon.json") -> dict:
    """Deletes a custom term or reverts an override back to base pronunciation."""
    clean_term = term.strip()
    if not clean_term:
        raise ValueError("Terim boş olamaz")
    k_low = clean_term.lower()
    with _lexicon_lock:
        matched_custom_key = next((k for k in list(CUSTOM_LEXICON.keys()) if k.lower() == k_low), None)
        if matched_custom_key:
            del CUSTOM_LEXICON[matched_custom_key]
            CUSTOM_CATEGORIES.pop(matched_custom_key, None)

        reverted_to_base = False
        if k_low in BASE_AUTOMOTIVE_LEXICON:
            AUTOMOTIVE_LEXICON[k_low] = BASE_AUTOMOTIVE_LEXICON[k_low]
            reverted_to_base = True
        else:
            AUTOMOTIVE_LEXICON.pop(k_low, None)

    save_custom_lexicon(path)
    return {
        "deleted": True,
        "term": clean_term,
        "reverted_to_base": reverted_to_base,
    }


def reset_to_base_lexicon(path: Path | str = "config/lexicon.json") -> dict:
    """Resets all custom terms and overrides back to initial base lexicon."""
    with _lexicon_lock:
        CUSTOM_LEXICON.clear()
        CUSTOM_CATEGORIES.clear()
        AUTOMOTIVE_LEXICON.clear()
        AUTOMOTIVE_LEXICON.update(BASE_AUTOMOTIVE_LEXICON)

    save_custom_lexicon(path)
    return {"reset": True, "count": len(AUTOMOTIVE_LEXICON)}

_UNITS = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]

_TENS = [
    "",
    "on",
    "yirmi",
    "otuz",
    "kırk",
    "elli",
    "altmış",
    "yetmiş",
    "seksen",
    "doksan",
]

_SCALES = [(10**9, "milyar"), (10**6, "milyon"), (10**3, "bin")]

VOWELS = "aeıioöuüAEIİOÖUÜ"

BACK_VOWELS = "aıouAIOU"

ROUND_VOWELS = "oöuüOÖUÜ"

HARD_CONSONANTS = "fstkçşhpFSTKÇŞHP"


def spell_tr_int(n: int) -> str:
    """Tam sayilari Turkce kurallarina gore yaziya cevirir (1000 -> 'bin', 'bir bin' degil)."""
    if n == 0:
        return "sıfır"
    if n < 0:
        return "eksi " + spell_tr_int(-n)
    parts: list[str] = []
    for scale, name in _SCALES:
        if n >= scale:
            head = n // scale
            n = n % scale
            if not (scale == 1000 and head == 1):
                parts.append(spell_tr_int(head))
            parts.append(name)
    if n >= 100:
        if n // 100 > 1:
            parts.append(_UNITS[n // 100])
        parts.append("yüz")
        n = n % 100
    if n >= 10:
        parts.append(_TENS[n // 10])
        n = n % 10
    if n > 0:
        parts.append(_UNITS[n])
    return " ".join(parts)


MODEL_CODE_LETTERS = dict(
    zip(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "a be ce de e fe ge he ı je ka le me ne o pe ku re se te u ve ve iks ye ze".split(),
    )
)


def spell_tr_ordinal(n: int) -> str:
    """Sayısal sıra etiketini Türkçe okunuşuna çevirir."""
    spoken = spell_tr_int(n)
    if spoken.endswith("dört"):
        return spoken[:-1] + "düncü"
    vowel = next(ch for ch in reversed(spoken) if ch in VOWELS)
    ending = dict(zip("aıeiouöü", "ııiiuuüü"))
    harmonic = ending[vowel]
    suffix = f"nc{harmonic}" if spoken[-1] in VOWELS else f"{harmonic}nc{harmonic}"
    return spoken + suffix


def harmonize_suffix(stem_spoken: str, raw_suffix: str) -> str:
    """
    Sayi, saat, para birimi veya yabanci marka okunusuna gelen Turkce ekleri
    (orn. 14:30'da -> on dört otuzda, 15:00'de -> on beşte) son sese göre uyumlar.
    """
    stem = stem_spoken.strip()
    suf = raw_suffix.strip().lower()
    if not stem or not suf:
        return stem + suf

    last_vowel = "e"
    for ch in reversed(stem):
        if ch in VOWELS:
            last_vowel = ch.lower()
            break
    ends_with_vowel = stem[-1] in VOWELS
    ends_with_hard = stem[-1] in HARD_CONSONANTS

    is_back = last_vowel in "aıou"
    a_e = "a" if is_back else "e"
    if last_vowel in "aı":
        i_4 = "ı"
    elif last_vowel in "ei":
        i_4 = "i"
    elif last_vowel in "ou":
        i_4 = "u"
    else:
        i_4 = "ü"
    d_t = "t" if ends_with_hard else "d"

    if stem.endswith("lirası"):
        lira_map = {
            "a": "na",
            "e": "na",
            "ya": "na",
            "ye": "na",
            "da": "nda",
            "de": "nda",
            "ta": "nda",
            "te": "nda",
            "dan": "ndan",
            "den": "ndan",
            "tan": "ndan",
            "ten": "ndan",
            "ı": "nı",
            "i": "nı",
            "yı": "nı",
            "yi": "nı",
            "ın": "nın",
            "in": "nın",
            "nın": "nın",
            "nin": "nın",
            "dır": "dır",
            "dir": "dır",
        }
        if suf in lira_map:
            return stem + lira_map[suf]

    if suf in ("ıncı", "inci", "uncu", "üncü", "ncı", "nci", "ncu", "ncü"):
        if stem.endswith("dört"):
            stem = stem[:-4] + "dörd"
        return stem + ("nc" + i_4 if ends_with_vowel else i_4 + "nc" + i_4)

    if suf in ("da", "de", "ta", "te"):
        return f"{stem}{d_t}{a_e}"
    if suf in ("dan", "den", "tan", "ten"):
        return f"{stem}{d_t}{a_e}n"
    if suf in ("daki", "deki", "taki", "teki"):
        return f"{stem}{d_t}{a_e}ki"
    if suf in ("dakiler", "dekiler", "takiler", "tekiler"):
        return f"{stem}{d_t}{a_e}kiler"
    if suf in ("a", "e", "ya", "ye"):
        buf = "y" if ends_with_vowel else ""
        return f"{stem}{buf}{a_e}"
    if suf in ("ı", "i", "u", "ü", "yı", "yi", "yu", "yü"):
        buf = "y" if ends_with_vowel else ""
        return f"{stem}{buf}{i_4}"
    if suf in ("ın", "in", "un", "ün", "nın", "nin", "nun", "nün"):
        buf = "n" if ends_with_vowel else ""
        return f"{stem}{buf}{i_4}n"
    if suf in ("dır", "dir", "dur", "dür", "tır", "tir", "tur", "tür"):
        return f"{stem}{d_t}{i_4}r"
    if suf in ("lık", "lik", "luk", "lük"):
        return f"{stem}l{i_4}k"

    return f"{stem}{suf}"


def normalize_automotive_turkish(text: str) -> str:
    """
    FreyaTTS icin otomotiv alanina ozel kapsamli Turkce metin normalizasyonu.
    FreyaTTS'in dahili normalize() fonksiyonundaki 5 temel kisiti giderir.
    """
    t = text.strip()
    t = re.sub(
        r"(?<![\w.])([0-9]{1,9})\.(?=[ \t]+"
        r"(?!(?:ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık)\b)"
        r"(?:(?i:seçenek|sıra|madde|kat)\b|[a-zçğıöşü]))",
        lambda match: spell_tr_ordinal(int(match[1])),
        t,
    )

    # 1. Saat ifadeleri ve ekleri (orn. "14:30'da", "09.00'da", "15:00'e")
    def _replace_time(m: re.Match) -> str:
        prefix = m.group("prefix") or ""
        hh = int(m.group("h"))
        mm = int(m.group("m"))
        suf = m.group("suf")
        spoken_time = (
            spell_tr_int(hh) if mm == 0 else f"{spell_tr_int(hh)} {spell_tr_int(mm)}"
        )
        if suf:
            spoken_time = harmonize_suffix(spoken_time, suf)
        return f"{prefix}{spoken_time}"

    t = re.sub(
        r"(?P<prefix>(?:saat|yarın|bugün|sabah|akşam)\s+)?\b(?P<h>[01]?\d|2[0-3]):(?P<m>[0-5]\d)(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]+))?\b",
        _replace_time,
        t,
        flags=re.IGNORECASE,
    )

    # 2. Motor hacmi sablonlari (orn. "1.5 TSI", "1.6 TDI", "2.0 BlueHDi", "1.3 TCe", "1.5 e-Power")
    def _replace_engine(m: re.Match) -> str:
        major = spell_tr_int(int(m.group("maj")))
        minor = spell_tr_int(int(m.group("min")))
        rest = m.group("rest")
        return f"{major} nokta {minor} {rest}"

    t = re.sub(
        r"\b(?P<maj>[0-6])[.,](?P<min>[0-9])\s+(?P<rest>(?:TSI|TDI|TFSI|CDI|dCi|BlueHDi|HDi|TCe|MultiJet|PureTech|EcoTSI|e-Power|e-Tech|Hybrid|L|litre)\b)",
        _replace_engine,
        t,
        flags=re.IGNORECASE,
    )

    # 3. Para birimi ve arac fiyatlari (orn. "1.250.000 TL", "1250000 TL", "850.500,50 TL'ye")
    def _replace_currency(m: re.Match) -> str:
        int_part = int(m.group("int").replace(".", ""))
        frac_part = m.group("frac")
        suf = m.group("suf")
        if frac_part and int(frac_part) > 0:
            spoken = (
                f"{spell_tr_int(int_part)} lira {spell_tr_int(int(frac_part))} kuruş"
            )
        else:
            spoken = f"{spell_tr_int(int_part)} Türk lirası"
        if suf:
            spoken = harmonize_suffix(spoken, suf)
        return spoken

    t = re.sub(
        r"\b(?P<int>\d{1,3}(?:\.\d{3})+|\d+)(?:,(?P<frac>\d{1,2}))?\s*(?:TL|TRY|₺|Türk\s+[Ll]irası)(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]+))?",
        _replace_currency,
        t,
    )

    # 4. Kilometre ve diger birimler (orn. "145.000 km'de", "150 bg")
    def _replace_unit(m: re.Match) -> str:
        val = spell_tr_int(int(m.group("num").replace(".", "")))
        unit_map = {"km": "kilometre", "bg": "beygir", "hp": "beygir", "kw": "kilovat"}
        u_spoken = unit_map[m.group("u").lower()]
        suf = m.group("suf")
        if suf:
            u_spoken = harmonize_suffix(u_spoken, suf)
        return f"{val} {u_spoken}"

    t = re.sub(
        r"\b(?P<num>\d{1,3}(?:\.\d{3})+|\d+)\s*(?P<u>km|bg|hp|kw)(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]+))?\b",
        _replace_unit,
        t,
        flags=re.IGNORECASE,
    )

    # 5. Otomotiv Telaffuz Sozlugu (Marka, Model, Kisaltma + Ek Uyumlama)
    with _lexicon_lock:
        active_lex = dict(AUTOMOTIVE_LEXICON)

    for key in sorted(active_lex.keys(), key=len, reverse=True):
        spoken_val = active_lex[key]

        def _lex_sub(m: re.Match, sv: str = spoken_val) -> str:
            suf = m.group("suf")
            return harmonize_suffix(sv, suf) if suf else sv

        pattern = r"\b" + re.escape(key) + r"(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]+))?\b"
        t = re.sub(pattern, _lex_sub, t, flags=re.IGNORECASE)

    # 5b. Model kodlari (orn. "C3", "X5", "XC40", "A3'un", "P0420") ve 4x4
    def _replace_model_code(m: re.Match) -> str:
        letters = " ".join(MODEL_CODE_LETTERS[ch] for ch in m.group("letters"))
        digits = m.group("num")
        if digits.startswith("0"):
            number = " ".join(spell_tr_int(int(ch)) for ch in digits)
        else:
            number = spell_tr_int(int(digits))
        spoken = f"{letters} {number}"
        suf = m.group("suf")
        return harmonize_suffix(spoken, suf) if suf else spoken

    t = re.sub(r"\b4[xX]4\b", "dört çeker", t)
    t = re.sub(
        r"\b(?P<letters>[A-Z]{1,3})(?P<num>\d{1,4})(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]+))?\b",
        _replace_model_code,
        t,
    )

    # 6. Kalan standart sayilar, yuzdeler ve ekli sayilar (orn. "%20'si", "2023", "3008")
    def _replace_number(m: re.Match) -> str:
        pct = m.group("pct")
        num_str = m.group("num").replace(".", "")
        suf = m.group("suf")
        if len(num_str) >= 10 and num_str.startswith("0"):
            spoken = " ".join(spell_tr_int(int(ch)) for ch in num_str)
        else:
            spoken = spell_tr_int(int(num_str))
        if pct:
            spoken = f"yüzde {spoken}"
        if suf:
            spoken = harmonize_suffix(spoken, suf)
        return spoken

    t = re.sub(
        r"(?P<pct>%\s*)?\b(?P<num>\d{1,3}(?:\.\d{3})+|\d+)(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]+))?\b",
        _replace_number,
        t,
    )

    # 7. FreyaTTS char_vocab.json <UNK> Guvenlik Agi (kucuk 'q', '!', 'TL', parantez temizligi)
    t = t.replace("!", ".").replace("₺", " Türk lirası ")
    t = t.replace("q", "k").replace("Q", "K").replace("w", "v").replace("W", "V")
    t = re.sub(r"[()\[\]{}\"#$\*\^_`|~<>]", " ", t)
    t = (
        t.replace("...", ", ")
        .replace("…", ", ")
        .replace(" — ", ", ")
        .replace(" - ", ", ")
    )
    return re.sub(r"\s+", " ", t).strip()

load_custom_lexicon()
