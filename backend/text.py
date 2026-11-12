"""Domain front-end; preserve source spans and reject unsupported characters."""

import json
import re
from pathlib import Path
from backend.normalizer_rules import (
    normalize_automotive_turkish,
    spell_tr_int,
    harmonize_suffix,
)

LEXICON = Path("config/lexicon.json")
# Süre tahmininin şiştiği ve tek başına sentezin bozulduğu parça uzunluğu (karakter).
SHORT_CLAUSE_MAX_CHARS = 15
MONTHS = [
    "ocak",
    "şubat",
    "mart",
    "nisan",
    "mayıs",
    "haziran",
    "temmuz",
    "ağustos",
    "eylül",
    "ekim",
    "kasım",
    "aralık",
]
LETTERS = dict(
    zip(
        "ABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ",
        [
            "a",
            "be",
            "ce",
            "çe",
            "de",
            "e",
            "fe",
            "ge",
            "yumuşak ge",
            "he",
            "ı",
            "i",
            "je",
            "ka",
            "le",
            "me",
            "ne",
            "o",
            "ö",
            "pe",
            "re",
            "se",
            "şe",
            "te",
            "u",
            "ü",
            "ve",
            "ye",
            "ze",
        ],
    )
)


def normalize(text: str):
    if not text.strip() or len(text) > 4000:
        raise ValueError("Metin uzunluğu 1–4000 olmalı")
    # Reject rather than silently discard meaningful unsupported symbols.
    unsupported = sorted(set(re.findall(r"[^\w\s.,:;?!%\'’₺€+()\-–—/]", text)))
    if unsupported:
        raise ValueError("Desteklenmeyen karakterler: " + " ".join(unsupported))
    t = text
    t = re.sub(
        r"(?<!\w)(?:\+90|0)\s*\(?[2-5]\d{2}\)?[ -]*\d{3}[ -]*\d{2}[ -]*\d{2}(?!\d)",
        lambda m: (
            ("artı " if m[0].startswith("+") else "")
            + " ".join(spell_tr_int(int(c)) for c in m[0] if c.isdigit())
        ),
        t,
    )

    def money(m):
        value = spell_tr_int(int(m["integer"].replace(".", "")))
        fraction = int((m["fraction"] or "").ljust(2, "0") or "0")
        spoken = (
            f"{value} lira {spell_tr_int(fraction)} kuruş"
            if fraction
            else f"{value} Türk lirası"
        )
        suffix = m["suffix"]
        if suffix:
            if fraction:
                spoken = harmonize_suffix(spoken, suffix)
            else:
                normalized = {
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
                if suffix.lower() not in normalized:
                    raise ValueError("Para birimi eki desteklenmiyor: " + suffix)
                spoken += normalized[suffix.lower()]
        if m["question"]:
            spoken += " mu" if fraction else " mı"
        return spoken

    t = re.sub(
        r"\b(?P<integer>\d{1,3}(?:\.\d{3})+|\d+)(?:,(?P<fraction>\d{1,2}))?\s*(?:TL|TRY|₺)(?:['’](?P<suffix>[a-zçğıöşü]+))?(?:\s+(?P<question>mi|mı|mu|mü)\b)?",
        money,
        t,
        flags=re.I,
    )
    t = re.sub(
        r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b",
        lambda m: date_words(*map(int, m.groups())),
        t,
    )
    t = re.sub(
        r"\b(\d{4})-(\d{2})-(\d{2})\b",
        lambda m: date_words(int(m[3]), int(m[2]), int(m[1])),
        t,
    )
    t = re.sub(r"\b(saat\s+)([0-2]?\d)\.([0-5]\d)", r"\1\2:\3", t, flags=re.I)
    t = re.sub(
        r"\b0\d{3}[ ()-]*\d{3}[ -]*\d{2}[ -]*\d{2}\b",
        lambda m: " ".join(spell_tr_int(int(c)) for c in m[0] if c.isdigit()),
        t,
    )
    t = re.sub(
        r"\b(\d{2})\s+([A-ZÇĞİÖŞÜ]{1,3})\s+(\d{2,4})\b",
        lambda m: (
            spell_tr_int(int(m[1]))
            + " "
            + " ".join(LETTERS.get(c, c) for c in m[2])
            + " "
            + spell_tr_int(int(m[3]))
        ),
        t,
    )
    # Otomotiv sozlugu normalize_automotive_turkish icinde dinamik isletilir
    t = normalize_automotive_turkish(t).replace("x", "ks").replace("X", "Ks")
    vocab = json.loads(Path("config/freya_vocab.json").read_text(encoding="utf8"))
    t = t.replace("Ğ", "ğ")
    missing = sorted(set(t) - set(vocab))
    if missing:
        raise ValueError("Model karakter sözlüğü desteklemiyor: " + " ".join(missing))
    return {
        "source": text,
        "normalized": t,
        "warnings": [
            "Telefon bandı ses kalitesi ayrıca dinlenerek değerlendirilmelidir."
        ],
    }


def date_words(day, month, year):
    from datetime import date

    date(year, month, day)
    return f"{spell_tr_int(day)} {MONTHS[month - 1]} {spell_tr_int(year)}"


NUMBER_WORDS = set(
    "sıfır bir iki üç dört beş altı yedi sekiz dokuz on yirmi otuz kırk elli altmış yetmiş seksen doksan yüz bin milyon milyar trilyon nokta virgül".split()
)


def protected_atoms(sentence):
    from backend.normalizer_rules import get_lexicon

    lexicon = get_lexicon()
    phrases = [
        v.lower().split() for v in lexicon.values() if len(v.split()) > 1
    ]
    words = sentence.split()
    i = 0

    def plain(w):
        return w.lower().strip(".,?!:;")

    while i < len(words):
        start = i
        if plain(words[i]) in NUMBER_WORDS:
            while i < len(words) and plain(words[i]) in NUMBER_WORDS:
                i += 1
            if (
                i < len(words)
                and plain(words[i]) == "türk"
                and i + 1 < len(words)
                and plain(words[i + 1]).startswith("lira")
            ):
                i += 2
            elif i < len(words) and plain(words[i]).startswith(
                ("kilometre", "lira", "kuruş", "beygir", "kilovat")
            ):
                i += 1
            if "nokta" in [plain(w) for w in words[start:i]]:
                for phrase in sorted(phrases, key=len, reverse=True):
                    if [plain(w) for w in words[i : i + len(phrase)]] == phrase:
                        i += len(phrase)
                        break
        else:
            match = next(
                (
                    p
                    for p in sorted(phrases, key=len, reverse=True)
                    if [plain(w) for w in words[i : i + len(p)]] == p
                ),
                None,
            )
            i += len(match) if match else 1
        yield words[start:i]


def turkish_capitalize(text: str) -> str:
    """Türkçe imla kurallarına uygun olarak ilk harfi büyütür."""
    s = text.strip()
    if not s:
        return s
    tr_map = {"i": "İ", "ı": "I", "ü": "Ü", "ş": "Ş", "ö": "Ö", "ç": "Ç", "ğ": "ğ"}
    first = tr_map.get(s[0], s[0].upper())
    return first + s[1:]


def prepare_tts_clause(text: str) -> str:
    """TTS akustik modeline girecek her yan tümceyi Leyla ses kimliğine kilitler.

    FreyaDiT akustik modeli eğitim kümesinde yalnızca büyük harfle başlayan cümlelerle
    eğitildiği için, küçük harfle başlayan yan tümceler modelin perdesini erkek/kalın
    ses bölgesine (130-170 Hz) düşürür. Bu fonksiyon her yan tümcenin baş harfini
    Türkçe kurallarına uygun büyütür ve uygun noktalama ekler.
    """
    s = text.strip()
    if not s:
        return s
    capitalized = turkish_capitalize(s)
    if capitalized[-1] not in ".?!,:;":
        capitalized += "."
    return capitalized


def clauses(text):
    # "Evet," gibi çok kısa bir parça tek başına sentezlenirse model süreyi doldurmak için
    # sözcüğü tekrar ediyor ("Evet, evet"); bu yüzden virgülden sonraki parçayla birleşir.
    pending = ""
    for sentence in re.split(r"(?<=[,.;?!:])\s+", text):
        if not sentence:
            continue
        if pending:
            sentence, pending = f"{pending} {sentence}", ""
        if sentence.endswith(",") and len(sentence) <= SHORT_CLAUSE_MAX_CHARS:
            pending = sentence
            continue
        pause = {",": 0.14, ";": 0.2, ":": 0.2, ".": 0.28, "?": 0.32, "!": 0.28}.get(
            sentence[-1], 0.08
        )
        if len(sentence.split()) <= 15 and len(sentence) <= 270:
            yield sentence, pause
            continue
        chunk = []
        for atom in protected_atoms(sentence):
            if len(" ".join(atom)) > 270:
                raise ValueError("Sayı veya terim öbeği model sınırını aşıyor")
            if chunk and (
                len(chunk) + len(atom) > 11 or len(" ".join(chunk + atom)) > 270
            ):
                yield " ".join(chunk), 0.08
                chunk = []
            chunk.extend(atom)
        if chunk:
            yield " ".join(chunk), pause
    if pending:
        yield pending, 0.14
