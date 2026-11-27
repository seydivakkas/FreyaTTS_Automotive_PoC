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

from dataclasses import dataclass
from datetime import date as _dt_date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import re
from typing import Any
import unicodedata

from backend.core.contracts.dialogue import VerifiedFactRef
from backend.linguistic_frontend.lexicon_adapter import LexiconAdapter
from backend.shared_lexicon.contracts import EntityCategory


DEFAULT_MAX_ATOMS = 128
DEFAULT_MAX_TOKEN_LENGTH = 64
DEFAULT_MAX_NUMERIC_DIGITS = 15

# Precedence order (lower number = higher priority; longest/most specific wins on ties)
_KIND_PRIORITY: dict[str, int] = {
    "PHONE": 1,
    "PLATE": 2,
    "DIAGNOSTIC_CODE": 3,
    "ENGINE_CODE": 4,
    "DATE": 5,
    "TIME": 6,
    "CURRENCY": 7,
    "PERCENT": 8,
    "UNIT": 9,
    "MODEL": 10,
    "BRAND": 11,
    "TRIM": 12,
    "ABBREVIATION": 13,
    "ORDINAL": 14,
    "DECIMAL": 15,
    "NUMBER": 16,
}

_MONTHS_PATTERN = (
    r"ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık"
)

# Bounded linear regex patterns (no nested quantifiers / catastrophic backtracking)
_PHONE_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:\+90\s*|0)\s*\(?[2-5]\d{2}\)?[ \t-]*\d{3}[ \t-]*\d{2}[ \t-]*\d{2}"
    r"(?![A-Za-z0-9])"
)
_PLATE_RE = re.compile(
    r"(?<![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
    r"(?P<prov>\d{2,3})[ \t]+(?P<letters>[A-ZÇĞİÖŞÜ]{1,3})[ \t]+(?P<digits>\d{2,4})"
    r"(?![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
)
_DTC_RE = re.compile(
    r"(?<![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
    r"(?P<code>[PCBU][0-3][0-9A-Fa-f]{3})"
    r"(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]{1,12}))?"
    r"(?![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
)
_ENGINE_RE = re.compile(
    r"(?<![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
    r"(?P<maj>[0-6])[.,](?P<min>[0-9])[ \t]+"
    r"(?P<rest>TSI|TDI|TFSI|CDI|dCi|BlueHDi|HDi|TCe|MultiJet|PureTech|EcoTSI|e-Power|e-Tech|Hybrid|litre|L)"
    r"(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]{1,12}))?"
    r"(?![A-Za-z0-9ÇĞİÖŞÜçğıöşü])",
    re.IGNORECASE,
)
_ISO_DATE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?![A-Za-z0-9])"
)
_DMY_DATE_RE = re.compile(
    r"(?<![A-Za-z0-9.])(?P<d>\d{1,2})(?P<sep>[./])(?P<m>\d{1,2})(?P=sep)(?P<y>\d{4})(?![A-Za-z0-9.])"
)
_TIME_COLON_RE = re.compile(
    r"(?<![A-Za-z0-9:.])(?P<h>[01]?\d|2[0-3]):(?P<m>[0-5]\d)"
    r"(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]{1,12}))?(?![A-Za-z0-9:.])"
)
_TIME_SAAT_DOT_RE = re.compile(
    r"(?<=saat[ \t])(?P<h>[01]?\d|2[0-3])\.(?P<m>[0-5]\d)"
    r"(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]{1,12}))?(?![A-Za-z0-9.])",
    re.IGNORECASE,
)
_CURRENCY_RE = re.compile(
    r"(?<![A-Za-z0-9.,-])"
    r"(?P<num>(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?)"
    r"[ \t]*(?P<unit>TL|TRY|₺|Türk[ \t]+[Ll]irası|EUR|€|USD|\$)"
    r"(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]{1,12}))?"
    r"(?![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
)
_PERCENT_PREFIX_RE = re.compile(
    r"(?<![A-Za-z0-9])%[ \t]*(?P<num>\d+(?:[.,]\d+)?)"
    r"(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]{1,12}))?"
    r"(?![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
)
_PERCENT_SUFFIX_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<num>\d+(?:[.,]\d+)?)[ \t]*%"
    r"(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]{1,12}))?"
    r"(?![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
)
_UNIT_RE = re.compile(
    r"(?<![A-Za-z0-9ÇĞİÖŞÜçğıöşü.,])"
    r"(?P<num>(?:-(?=\d))?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d+)?)"
    r"[ \t]*(?P<u>°[ \t]*[Cc]|km|bg|hp|kW|kw|kWh|kwh|litre|L|mm|cm|cc|kg|bar)"
    r"(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]{1,12}))?"
    r"(?![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
)
_ID_DOT_MODEL_RE = re.compile(
    r"(?<![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
    r"(?P<prefix>ID)\.(?P<num>\d{1,2})"
    r"(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]{1,12}))?"
    r"(?![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
)
_ALPHANUM_MODEL_RE = re.compile(
    r"(?<![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
    r"(?P<code>[A-Z]{1,2}\d{1,2}[A-Z]?)"
    r"(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]{1,12}))?"
    r"(?![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
)
_FOUR_BY_FOUR_RE = re.compile(r"(?<![A-Za-z0-9])4[xX]4(?![A-Za-z0-9])")
_ORDINAL_RE = re.compile(
    rf"(?<![\w.])(?P<num>\d{{1,9}})\.(?=[ \t]+(?!({_MONTHS_PATTERN})\b)[a-zçğıöşüA-ZÇĞİÖŞÜ])"
)
_NUMBER_OR_DECIMAL_RE = re.compile(
    r"(?<![A-Za-z0-9ÇĞİÖŞÜçğıöşü.,])"
    r"(?P<sign>-(?=\d))?"
    r"(?P<body>\d{1,3}(?:\.\d{3})+|\d+(?:[.,]\d+)?)"
    r"(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]{1,12}))?"
    r"(?![A-Za-z0-9ÇĞİÖŞÜçğıöşü.,])"
)


class AtomKind(StrEnum):
    BRAND = "BRAND"
    MODEL = "MODEL"
    ENGINE_CODE = "ENGINE_CODE"
    TRIM = "TRIM"
    DIAGNOSTIC_CODE = "DIAGNOSTIC_CODE"
    PLATE = "PLATE"
    PHONE = "PHONE"
    CURRENCY = "CURRENCY"
    DATE = "DATE"
    TIME = "TIME"
    DECIMAL = "DECIMAL"
    NUMBER = "NUMBER"
    UNIT = "UNIT"
    PERCENT = "PERCENT"
    ORDINAL = "ORDINAL"
    ABBREVIATION = "ABBREVIATION"


@dataclass(frozen=True, slots=True)
class ProtectedAtom:
    """Immutable protected semantic span detected in source_text."""

    atom_id: str
    kind: AtomKind
    raw_span: tuple[int, int]
    literal_source: str
    semantic_value: Any
    unresolved: bool = False
    unresolved_reason: str | None = None
    provenance_ref: str = "scanner"
    transformation_policy: str = "SPOKEN_EXACT_VALUE"
    normalized_span: tuple[int, int] | None = None
    critical: bool = True
    parent_atom_id: str | None = None
    children_ids: tuple[str, ...] = ()
    suffix: str | None = None


@dataclass(frozen=True, slots=True)
class ProtectedAtomScanResult:
    ok: bool
    atoms: tuple[ProtectedAtom, ...]
    reason_code: str = "OK"
    safe_message: str = ""


def _tr_lower(text: str) -> str:
    nfc = unicodedata.normalize("NFC", text)
    return nfc.replace("İ", "i").replace("I", "ı").lower().replace("\u0307", "")


def _parse_tr_decimal(raw_num: str) -> tuple[Decimal | None, bool, str | None]:
    """
    Parse Turkish formatted numbers conservatively with exact Decimal.
    Distinguishes 2.500,50 (valid TR) and 1.250.000 (valid TR grouped)
    from standalone single-group ambiguous '1.250'.
    """
    s = raw_num.strip()
    if "," in s:
        if "." in s:
            if not re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+,\d+", s):
                return None, True, "INVALID_TR_NUMBER_FORMAT"
            canonical = s.replace(".", "").replace(",", ".")
        else:
            canonical = s.replace(",", ".")
        try:
            return Decimal(canonical), False, None
        except InvalidOperation:
            return None, True, "INVALID_DECIMAL"

    if "." in s:
        # Multi-group thousands e.g. 1.250.000
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3}){2,}", s):
            return Decimal(s.replace(".", "")), False, None
        # Single-group 3-digit dot e.g. 1.250 -> ambiguous without unit/currency/fact
        if re.fullmatch(r"-?\d{1,3}\.\d{3}", s):
            return Decimal(s.replace(".", "")), True, "AMBIGUOUS_THOUSAND_SEPARATOR"
        # Short fractional decimal like 1.5 or 12.34
        if re.fullmatch(r"-?\d+\.\d{1,2}", s):
            return Decimal(s), False, None
        return None, True, "AMBIGUOUS_DECIMAL_SEPARATOR"

    try:
        return Decimal(s), False, None
    except InvalidOperation:
        return None, True, "INVALID_INTEGER"


def _has_date_fact(facts: tuple[VerifiedFactRef, ...], y: int, m: int, d: int) -> str | None:
    target = f"{y:04d}-{m:02d}-{d:02d}"
    for f in facts:
        ref = _tr_lower(f.reference_id)
        if target in ref or "date" in ref or "calendar" in _tr_lower(f.provenance):
            return f.reference_id
    return None


def _has_numeric_fact(facts: tuple[VerifiedFactRef, ...], val: Decimal) -> str | None:
    val_str = str(val)
    for f in facts:
        if val_str in f.reference_id:
            return f.reference_id
    return None


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _lexicon_category_to_atom_kind(cat: EntityCategory, canonical_name: str) -> AtomKind:
    if cat == EntityCategory.BRAND:
        return AtomKind.BRAND
    if cat == EntityCategory.MODEL:
        return AtomKind.MODEL
    if cat == EntityCategory.DTC:
        return AtomKind.DIAGNOSTIC_CODE
    if cat == EntityCategory.TECHNICAL:
        low = _tr_lower(canonical_name)
        if low in {"comfortline", "highline", "trendline", "lounge", "touch", "prestige"}:
            return AtomKind.TRIM
        return AtomKind.ABBREVIATION
    return AtomKind.ABBREVIATION


def scan_protected_atoms(
    source_text: str,
    *,
    verified_fact_refs: tuple[VerifiedFactRef, ...] = (),
    lexicon_adapter: LexiconAdapter | None = None,
    max_atoms: int = DEFAULT_MAX_ATOMS,
    max_numeric_digits: int = DEFAULT_MAX_NUMERIC_DIGITS,
    max_token_length: int = DEFAULT_MAX_TOKEN_LENGTH,
) -> ProtectedAtomScanResult:
    """
    Bounded deterministic scanner for protected semantic atoms in source_text.

    Uses exact token boundaries, explicit precedence, parent-child sub-atom links,
    and rejects excessive atom counts or numeric digit counts.
    """
    if not source_text:
        return ProtectedAtomScanResult(ok=True, atoms=())

    # Check bounded token lengths on whitespace-separated tokens first
    for tok in source_text.split():
        if len(tok) > max_token_length:
            return ProtectedAtomScanResult(
                ok=False,
                atoms=(),
                reason_code="LIMIT_EXCEEDED",
                safe_message="Token exceeds max_token_length",
            )

    candidates: list[dict[str, Any]] = []

    def _add_cand(
        *,
        kind: AtomKind,
        span: tuple[int, int],
        semantic_value: Any,
        unresolved: bool = False,
        unresolved_reason: str | None = None,
        provenance_ref: str = "scanner",
        policy: str = "SPOKEN_EXACT_VALUE",
        critical: bool = True,
        suffix: str | None = None,
        sub_amount: dict[str, Any] | None = None,
    ) -> None:
        candidates.append(
            {
                "kind": kind,
                "span": span,
                "literal": source_text[span[0]:span[1]],
                "semantic_value": semantic_value,
                "unresolved": unresolved,
                "unresolved_reason": unresolved_reason,
                "provenance_ref": provenance_ref,
                "policy": policy,
                "critical": critical,
                "suffix": suffix,
                "sub_amount": sub_amount,
            }
        )

    # 1. PHONE
    for m in _PHONE_RE.finditer(source_text):
        digits = "".join(ch for ch in m.group(0) if ch.isdigit())
        _add_cand(
            kind=AtomKind.PHONE,
            span=m.span(),
            semantic_value=digits,
            policy="LITERAL_DIGITS",
            provenance_ref="scanner:phone",
        )

    # 2. PLATE / identifier-like sequence (e.g. 061 ABC 123, 34 ABC 123)
    for m in _PLATE_RE.finditer(source_text):
        prov, letters, digits = m.group("prov"), m.group("letters"), m.group("digits")
        _add_cand(
            kind=AtomKind.PLATE,
            span=m.span(),
            semantic_value=f"{prov} {letters} {digits}",
            policy="LITERAL_CHARS",
            provenance_ref="scanner:plate_identifier",
        )

    # 3. DIAGNOSTIC_CODE (P0300, P0420, etc.)
    for m in _DTC_RE.finditer(source_text):
        code = m.group("code").upper()
        _add_cand(
            kind=AtomKind.DIAGNOSTIC_CODE,
            span=m.span(),
            semantic_value=code,
            policy="LITERAL_CHARS",
            provenance_ref="scanner:dtc",
            suffix=m.group("suf"),
        )

    # 4. ENGINE_CODE (1.6 TDI, 1.5 TSI, etc.)
    for m in _ENGINE_RE.finditer(source_text):
        disp = Decimal(f"{m.group('maj')}.{m.group('min')}")
        rest = m.group("rest")
        _add_cand(
            kind=AtomKind.ENGINE_CODE,
            span=m.span(),
            semantic_value=(disp, _tr_lower(rest)),
            policy="SPOKEN_EXACT_VALUE",
            provenance_ref="scanner:engine",
            suffix=m.group("suf"),
        )

    # 5. DATE (ISO unambiguous + DMY validated/ambiguity-checked)
    for m in _ISO_DATE_RE.finditer(source_text):
        y, mo, d = int(m.group("y")), int(m.group("m")), int(m.group("d"))
        try:
            _dt_date(y, mo, d)
            _add_cand(
                kind=AtomKind.DATE,
                span=m.span(),
                semantic_value=(y, mo, d),
                policy="TYPED_DATE",
                provenance_ref=_has_date_fact(verified_fact_refs, y, mo, d) or "scanner:iso_date",
            )
        except ValueError:
            _add_cand(
                kind=AtomKind.DATE,
                span=m.span(),
                semantic_value=None,
                unresolved=True,
                unresolved_reason="INVALID_CALENDAR_DATE",
                provenance_ref="scanner:iso_date",
            )

    for m in _DMY_DATE_RE.finditer(source_text):
        d, mo, y = int(m.group("d")), int(m.group("m")), int(m.group("y"))
        try:
            _dt_date(y, mo, d)
        except ValueError:
            _add_cand(
                kind=AtomKind.DATE,
                span=m.span(),
                semantic_value=None,
                unresolved=True,
                unresolved_reason="INVALID_CALENDAR_DATE",
                provenance_ref="scanner:dmy_date",
            )
            continue
        fact_ref = _has_date_fact(verified_fact_refs, y, mo, d)
        ambiguous = (d <= 12 and mo <= 12 and d != mo and fact_ref is None)
        _add_cand(
            kind=AtomKind.DATE,
            span=m.span(),
            semantic_value=None if ambiguous else (y, mo, d),
            unresolved=ambiguous,
            unresolved_reason="AMBIGUOUS_DATE_FORMAT" if ambiguous else None,
            policy="TYPED_DATE",
            provenance_ref=fact_ref or "scanner:dmy_date",
        )

    # 6. TIME
    for m in _TIME_COLON_RE.finditer(source_text):
        hh, mm = int(m.group("h")), int(m.group("m"))
        _add_cand(
            kind=AtomKind.TIME,
            span=m.span(),
            semantic_value=(hh, mm),
            policy="TYPED_TIME",
            provenance_ref="scanner:time",
            suffix=m.group("suf"),
        )
    for m in _TIME_SAAT_DOT_RE.finditer(source_text):
        hh, mm = int(m.group("h")), int(m.group("m"))
        _add_cand(
            kind=AtomKind.TIME,
            span=m.span(),
            semantic_value=(hh, mm),
            policy="TYPED_TIME",
            provenance_ref="scanner:time_dot",
            suffix=m.group("suf"),
        )

    # 7. CURRENCY (+ child amount atom)
    for m in _CURRENCY_RE.finditer(source_text):
        raw_num = m.group("num")
        digits_count = sum(1 for c in raw_num if c.isdigit())
        if digits_count > max_numeric_digits:
            return ProtectedAtomScanResult(
                ok=False,
                atoms=(),
                reason_code="LIMIT_EXCEEDED",
                safe_message="Currency digit count exceeds max_numeric_digits",
            )
        # Currency with unit (TL/TRY/₺) disambiguates TR grouping like 1.250 TL -> 1250
        if "." in raw_num and "," not in raw_num and re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw_num):
            val = Decimal(raw_num.replace(".", ""))
            unres, ureason = False, None
        else:
            val, unres, ureason = _parse_tr_decimal(raw_num)
        unit_raw = m.group("unit").upper()
        curr_code = "TRY" if unit_raw in {"TL", "TRY", "₺"} or "LİR" in unit_raw else (
            "EUR" if unit_raw in {"EUR", "€"} else "USD"
        )
        num_span = m.span("num")
        sub_kind = AtomKind.DECIMAL if ("," in raw_num or (val is not None and val != val.to_integral_value())) else AtomKind.NUMBER
        _add_cand(
            kind=AtomKind.CURRENCY,
            span=m.span(),
            semantic_value=(val, curr_code) if val is not None else None,
            unresolved=unres,
            unresolved_reason=ureason,
            policy="SPOKEN_EXACT_VALUE",
            provenance_ref="scanner:currency",
            suffix=m.group("suf"),
            sub_amount={
                "kind": sub_kind,
                "span": num_span,
                "literal": raw_num,
                "semantic_value": val,
                "unresolved": unres,
                "unresolved_reason": ureason,
            },
        )

    # 8. PERCENT
    for regex in (_PERCENT_PREFIX_RE, _PERCENT_SUFFIX_RE):
        for m in regex.finditer(source_text):
            raw_num = m.group("num")
            if sum(1 for c in raw_num if c.isdigit()) > max_numeric_digits:
                return ProtectedAtomScanResult(
                    ok=False,
                    atoms=(),
                    reason_code="LIMIT_EXCEEDED",
                    safe_message="Percent digit count exceeds max_numeric_digits",
                )
            val, unres, ureason = _parse_tr_decimal(raw_num)
            _add_cand(
                kind=AtomKind.PERCENT,
                span=m.span(),
                semantic_value=val,
                unresolved=unres,
                unresolved_reason=ureason,
                policy="SPOKEN_EXACT_VALUE",
                provenance_ref="scanner:percent",
                suffix=m.group("suf"),
            )

    # 9. UNIT
    for m in _UNIT_RE.finditer(source_text):
        raw_num = m.group("num")
        if sum(1 for c in raw_num if c.isdigit()) > max_numeric_digits:
            return ProtectedAtomScanResult(
                ok=False,
                atoms=(),
                reason_code="LIMIT_EXCEEDED",
                safe_message="Unit digit count exceeds max_numeric_digits",
            )
        if "." in raw_num and "," not in raw_num and re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", raw_num):
            val = Decimal(raw_num.replace(".", ""))
            unres, ureason = False, None
        else:
            val, unres, ureason = _parse_tr_decimal(raw_num)
        unit_norm = re.sub(r"\s+", "", m.group("u"))
        if unit_norm.lower() == "°c":
            unit_norm = "°C"
        else:
            unit_norm = unit_norm.lower()
        _add_cand(
            kind=AtomKind.UNIT,
            span=m.span(),
            semantic_value=(val, unit_norm) if val is not None else None,
            unresolved=unres,
            unresolved_reason=ureason,
            policy="SPOKEN_EXACT_VALUE",
            provenance_ref="scanner:unit",
            suffix=m.group("suf"),
        )

    # 10. MODEL / IDENTIFIER (ID.4, T10X, C4, XC40, 4x4, plus M05 lexicon matches)
    for m in _ID_DOT_MODEL_RE.finditer(source_text):
        _add_cand(
            kind=AtomKind.MODEL,
            span=m.span(),
            semantic_value=f"ID.{m.group('num')}",
            policy="LITERAL_CHARS",
            provenance_ref="scanner:id_model",
            suffix=m.group("suf"),
        )
    for m in _ALPHANUM_MODEL_RE.finditer(source_text):
        code = m.group("code")
        # Exclude diagnostic codes already captured at higher priority
        _add_cand(
            kind=AtomKind.MODEL,
            span=m.span(),
            semantic_value=code,
            policy="LITERAL_CHARS",
            provenance_ref="scanner:alphanum_model",
            suffix=m.group("suf"),
        )
    for m in _FOUR_BY_FOUR_RE.finditer(source_text):
        _add_cand(
            kind=AtomKind.ABBREVIATION,
            span=m.span(),
            semantic_value="4x4",
            policy="SPOKEN_EXACT_VALUE",
            provenance_ref="scanner:4x4",
        )

    if lexicon_adapter is not None:
        for lex_match in lexicon_adapter.lookup_scoped(source_text):
            kind = _lexicon_category_to_atom_kind(lex_match.category, lex_match.canonical_name)
            _add_cand(
                kind=kind,
                span=lex_match.raw_span,
                semantic_value=lex_match.canonical_name,
                policy="LEXICON_VARIANT",
                provenance_ref=f"m05:{lex_match.entity_id}",
                critical=(kind in {AtomKind.BRAND, AtomKind.MODEL, AtomKind.DIAGNOSTIC_CODE}),
            )

    # 11. ORDINAL
    for m in _ORDINAL_RE.finditer(source_text):
        num_str = m.group("num")
        if len(num_str) > max_numeric_digits:
            return ProtectedAtomScanResult(
                ok=False,
                atoms=(),
                reason_code="LIMIT_EXCEEDED",
                safe_message="Ordinal digit count exceeds max_numeric_digits",
            )
        _add_cand(
            kind=AtomKind.ORDINAL,
            span=(m.start(), m.end()),
            semantic_value=int(num_str),
            policy="SPOKEN_EXACT_VALUE",
            provenance_ref="scanner:ordinal",
        )

    # 12. DECIMAL / NUMBER
    for m in _NUMBER_OR_DECIMAL_RE.finditer(source_text):
        raw_num = (m.group("sign") or "") + m.group("body")
        digits_count = sum(1 for c in raw_num if c.isdigit())
        if digits_count > max_numeric_digits:
            return ProtectedAtomScanResult(
                ok=False,
                atoms=(),
                reason_code="LIMIT_EXCEEDED",
                safe_message="Numeric digit count exceeds max_numeric_digits",
            )
        val, unres, ureason = _parse_tr_decimal(raw_num)
        fact_ref = _has_numeric_fact(verified_fact_refs, val) if val is not None else None
        if unres and ureason == "AMBIGUOUS_THOUSAND_SEPARATOR" and fact_ref is not None:
            unres = False
            ureason = None
        is_decimal = "," in raw_num or ("." in raw_num and not unres and val is not None and val != val.to_integral_value())
        # Leading-zero identifier-like numbers (e.g. "007") preserve exact string
        if m.group("body").startswith("0") and len(m.group("body")) > 1 and "," not in raw_num and "." not in raw_num:
            sem_val: Any = raw_num
            policy = "LITERAL_DIGITS"
        else:
            sem_val = val
            policy = "SPOKEN_EXACT_VALUE"
        _add_cand(
            kind=AtomKind.DECIMAL if is_decimal else AtomKind.NUMBER,
            span=m.span(),
            semantic_value=sem_val,
            unresolved=unres,
            unresolved_reason=ureason,
            policy=policy,
            provenance_ref=fact_ref or "scanner:number",
            suffix=m.group("suf"),
        )

    # Sort by explicit precedence, then longest span, then earliest start
    candidates.sort(
        key=lambda c: (
            _KIND_PRIORITY[c["kind"].value],
            -(c["span"][1] - c["span"][0]),
            c["span"][0],
        )
    )

    accepted_top: list[dict[str, Any]] = []
    for cand in candidates:
        cspan = cand["span"]
        if any(_overlaps(cspan, ex["span"]) for ex in accepted_top):
            continue
        accepted_top.append(cand)
        if len(accepted_top) > max_atoms:
            return ProtectedAtomScanResult(
                ok=False,
                atoms=(),
                reason_code="LIMIT_EXCEEDED",
                safe_message="Protected atom count exceeds max_atoms",
            )

    # Order accepted atoms by source appearance
    accepted_top.sort(key=lambda c: (c["span"][0], c["span"][1]))

    atoms: list[ProtectedAtom] = []
    atom_seq = 0
    for cand in accepted_top:
        parent_id = f"atom-{atom_seq}"
        atom_seq += 1
        sub = cand.get("sub_amount")
        child_ids: tuple[str, ...] = ()
        child_atom: ProtectedAtom | None = None
        if sub is not None:
            child_id = f"atom-{atom_seq}"
            atom_seq += 1
            child_ids = (child_id,)
            child_atom = ProtectedAtom(
                atom_id=child_id,
                kind=sub["kind"],
                raw_span=sub["span"],
                literal_source=sub["literal"],
                semantic_value=sub["semantic_value"],
                unresolved=sub["unresolved"],
                unresolved_reason=sub["unresolved_reason"],
                provenance_ref=f"child:{parent_id}",
                transformation_policy="SPOKEN_EXACT_VALUE",
                critical=True,
                parent_atom_id=parent_id,
            )

        atoms.append(
            ProtectedAtom(
                atom_id=parent_id,
                kind=cand["kind"],
                raw_span=cand["span"],
                literal_source=cand["literal"],
                semantic_value=cand["semantic_value"],
                unresolved=cand["unresolved"],
                unresolved_reason=cand["unresolved_reason"],
                provenance_ref=cand["provenance_ref"],
                transformation_policy=cand["policy"],
                critical=cand["critical"],
                children_ids=child_ids,
                suffix=cand["suffix"],
            )
        )
        if child_atom is not None:
            atoms.append(child_atom)
        if len(atoms) > max_atoms:
            return ProtectedAtomScanResult(
                ok=False,
                atoms=(),
                reason_code="LIMIT_EXCEEDED",
                safe_message="Total protected atoms (with sub-atoms) exceeds max_atoms",
            )

    return ProtectedAtomScanResult(ok=True, atoms=tuple(atoms), reason_code="OK")
