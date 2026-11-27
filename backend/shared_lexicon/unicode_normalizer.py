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

import re
import unicodedata
from dataclasses import dataclass

from backend.core.contracts.recognition import UnicodeSpan
from backend.shared_lexicon.contracts import ProtectedSpan, ProtectedSpanKind

_APOSTROPHE_CHARS = frozenset({"’", "‘", "ʼ", "´", "`"})

_FOREIGN_DIACRITIC_FOLD = str.maketrans({
    "š": "s",
    "ë": "e",
    "é": "e",
    "è": "e",
    "ê": "e",
    "á": "a",
    "à": "a",
    "â": "a",
    "ä": "a",
    "ú": "u",
    "ù": "u",
    "û": "u",
    "î": "i",
    "í": "i",
    "ô": "o",
    "ó": "o",
    "ž": "z",
    "č": "c",
    "ñ": "n",
})

_NON_PLATE_WORDS = frozenset({
    "bin", "yüz", "tl", "try", "km", "bg", "hp", "kw", "lt", "l", "ml",
    "ay", "yıl", "gün", "saat", "dk", "sn", "mm", "cm", "m", "kg", "gr",
    "cc", "adet", "kişi", "kisi", "kat", "sıra", "madde", "adetlik",
})

# Priority order: VIN > PHONE > PLATE > DTC > NUMBER
_VIN_RE = re.compile(r"(?<![A-Za-z0-9])[A-HJ-NPR-Za-hj-npr-z0-9]{17}(?![A-Za-z0-9])")
_PHONE_RE = re.compile(
    r"(?:(?:\+?90\s*|0)\(?[2-5]\d{2}\)?[\s.-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}\b"
    r"|(?<![A-Za-z0-9])5\d{2}[\s.-]\d{3}[\s.-]\d{2}[\s.-]\d{2}(?![A-Za-z0-9]))"
)
_PLATE_RE = re.compile(
    r"(?<![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
    r"(?P<prov>0[1-9]|[1-7][0-9]|8[01])"
    r"[\s-]?"
    r"(?P<letters>[A-Za-zÇĞİÖŞÜçğıöşü]{1,3})"
    r"[\s-]?"
    r"(?P<digits>\d{2,5})"
    r"(?![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
)
_DTC_RE = re.compile(r"(?<![A-Za-z0-9])[PCBU][0-3][0-9A-Fa-f]{3}(?![A-Za-z0-9])", re.IGNORECASE)
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
    r"(?:\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)"
    r"(?![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
)

_LEADING_PUNCT = ".,;:!?\"'()[]{}<>«»“”"
_TRAILING_PUNCT = ".,;:!?\"'()[]{}<>«»“”"


def turkish_nfc_lower(text: str) -> str:
    """Turkish-aware NFC lowercase preserving I->ı and İ->i without U+0307 leakage."""
    if not text:
        return ""
    nfc = unicodedata.normalize("NFC", text)
    mapped = nfc.replace("İ", "i").replace("I", "ı").lower().replace("\u0307", "")
    return unicodedata.normalize("NFC", mapped)


def fold_foreign_diacritics(key: str) -> str:
    """Folds non-Turkish foreign Latin accents while preserving ç, ğ, ı, i, ö, ş, ü."""
    return key.translate(_FOREIGN_DIACRITIC_FOLD)


def normalize_matching_key(text: str, *, fold_foreign: bool = False) -> str:
    """Canonical Turkish-aware matching key for lexicon indexing and direct term lookup."""
    if not text:
        return ""
    out_chars: list[str] = []
    for ch in turkish_nfc_lower(text):
        if ch in _APOSTROPHE_CHARS:
            out_chars.append("'")
        elif ch.isspace():
            out_chars.append(" ")
        else:
            out_chars.append(ch)
    collapsed = re.sub(r" +", " ", "".join(out_chars)).strip()
    return fold_foreign_diacritics(collapsed) if fold_foreign else collapsed


@dataclass(frozen=True, slots=True)
class NormalizedTextMap:
    """Normalized matching text paired with exact half-open codepoint mapping back to raw_text."""

    raw_text: str
    normalized_text: str
    norm_to_raw_start: tuple[int, ...]
    norm_to_raw_end: tuple[int, ...]

    def raw_span(self, norm_start: int, norm_end: int) -> UnicodeSpan:
        """Converts half-open [norm_start, norm_end) indices to an exact RAW UnicodeSpan."""
        if norm_start < 0 or norm_end < norm_start or norm_end > len(self.normalized_text):
            raise ValueError("Invalid normalized span bounds")
        if norm_start == norm_end:
            pos = self.norm_to_raw_start[norm_start] if norm_start < len(self.norm_to_raw_start) else len(self.raw_text)
            return UnicodeSpan(start=pos, end_exclusive=pos, representation="RAW")
        raw_start = self.norm_to_raw_start[norm_start]
        raw_end = self.norm_to_raw_end[norm_end - 1]
        return UnicodeSpan(start=raw_start, end_exclusive=raw_end, representation="RAW")


@dataclass(frozen=True, slots=True)
class AlignedToken:
    """Token in normalized text linked to exact raw_text half-open Unicode codepoint span."""

    normalized: str
    raw_text: str
    raw_span: UnicodeSpan
    norm_start: int
    norm_end: int


def normalize_with_spans(raw_text: str) -> NormalizedTextMap:
    """Normalizes text to Turkish NFC lowercase while tracking exact raw codepoint offsets."""
    if not isinstance(raw_text, str):
        raise TypeError("raw_text must be str")
    if not raw_text:
        return NormalizedTextMap(
            raw_text="",
            normalized_text="",
            norm_to_raw_start=(),
            norm_to_raw_end=(),
        )

    n = len(raw_text)
    clusters: list[tuple[str, int, int]] = []
    i = 0
    while i < n:
        ch = raw_text[i]
        if ch.isspace():
            j = i + 1
            while j < n and raw_text[j].isspace():
                j += 1
            clusters.append((" ", i, j))
            i = j
            continue

        j = i + 1
        while j < n and unicodedata.combining(raw_text[j]) != 0:
            j += 1
        cluster = raw_text[i:j]
        nfc_cluster = unicodedata.normalize("NFC", cluster)
        lowered = nfc_cluster.replace("İ", "i").replace("I", "ı").lower().replace("\u0307", "")
        lowered = unicodedata.normalize("NFC", lowered)
        if lowered in _APOSTROPHE_CHARS:
            lowered = "'"
        clusters.append((lowered, i, j))
        i = j

    norm_chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for norm_piece, raw_start, raw_end in clusters:
        for c in norm_piece:
            norm_chars.append(c)
            starts.append(raw_start)
            ends.append(raw_end)

    return NormalizedTextMap(
        raw_text=raw_text,
        normalized_text="".join(norm_chars),
        norm_to_raw_start=tuple(starts),
        norm_to_raw_end=tuple(ends),
    )


def tokenize_aligned(text_map: NormalizedTextMap) -> tuple[AlignedToken, ...]:
    """Splits NormalizedTextMap into word-level tokens with exact raw codepoint spans."""
    norm = text_map.normalized_text
    raw = text_map.raw_text
    if not norm:
        return ()

    tokens: list[AlignedToken] = []
    for m in re.finditer(r"\S+", norm):
        ns, ne = m.start(), m.end()
        while ns < ne and norm[ns] in _LEADING_PUNCT:
            ns += 1
        while ne > ns and norm[ne - 1] in _TRAILING_PUNCT:
            ne -= 1
        if ns >= ne:
            continue
        raw_span = text_map.raw_span(ns, ne)
        tokens.append(
            AlignedToken(
                normalized=norm[ns:ne],
                raw_text=raw[raw_span.start:raw_span.end_exclusive],
                raw_span=raw_span,
                norm_start=ns,
                norm_end=ne,
            )
        )
    return tuple(tokens)


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def detect_protected_spans(raw_text: str) -> tuple[ProtectedSpan, ...]:
    """Detects plates, VINs, phones, DTCs, and numbers in raw_text with exact RAW spans."""
    if not raw_text:
        return ()

    accepted: list[ProtectedSpan] = []

    def _try_add(kind: ProtectedSpanKind, start: int, end: int) -> None:
        if start >= end:
            return
        for existing in accepted:
            if _overlaps(start, end, existing.span.start, existing.span.end_exclusive):
                return
        accepted.append(
            ProtectedSpan(
                kind=kind,
                span=UnicodeSpan(start=start, end_exclusive=end, representation="RAW"),
                raw_text=raw_text[start:end],
            )
        )

    # 1. VIN (17 chars, must contain both digit and alpha to avoid plain 17-letter words)
    for m in _VIN_RE.finditer(raw_text):
        seg = m.group(0)
        if any(c.isdigit() for c in seg) and any(c.isalpha() for c in seg):
            _try_add(ProtectedSpanKind.VIN, m.start(), m.end())

    # 2. Phone numbers
    for m in _PHONE_RE.finditer(raw_text):
        _try_add(ProtectedSpanKind.PHONE, m.start(), m.end())

    # 3. Turkish plates
    for m in _PLATE_RE.finditer(raw_text):
        letters = m.group("letters")
        if turkish_nfc_lower(letters) in _NON_PLATE_WORDS:
            continue
        _try_add(ProtectedSpanKind.PLATE, m.start(), m.end())

    # 4. OBD-II DTC codes (P0300, P0171, U0100, etc.)
    for m in _DTC_RE.finditer(raw_text):
        _try_add(ProtectedSpanKind.DTC, m.start(), m.end())

    # 5. Standalone numbers (years, prices, mileages, numeric models in isolation)
    for m in _NUMBER_RE.finditer(raw_text):
        _try_add(ProtectedSpanKind.NUMBER, m.start(), m.end())

    accepted.sort(key=lambda p: (p.span.start, p.span.end_exclusive))
    return tuple(accepted)
