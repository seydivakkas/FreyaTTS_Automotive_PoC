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
from dataclasses import dataclass
from enum import StrEnum

from backend.core.contracts.recognition import UnicodeSpan
from backend.shared_lexicon.contracts import ProtectedSpanKind
from backend.shared_lexicon.unicode_normalizer import detect_protected_spans, turkish_nfc_lower


class ProtectedCategory(StrEnum):
    PHONE = "PHONE"
    PLATE = "PLATE"
    VIN = "VIN"
    ENGINE_CODE = "ENGINE_CODE"
    MODEL_CODE = "MODEL_CODE"
    DTC = "DTC"
    YEAR_DATE_TIME = "YEAR_DATE_TIME"
    CURRENCY_AMOUNT = "CURRENCY_AMOUNT"
    BUSINESS_REF = "BUSINESS_REF"
    NEGATION_CORRECTION = "NEGATION_CORRECTION"


_ENGINE_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])\d\.\d\s*(?:TDI|TSI|TFSI|HDI|BlueHDi|dCi|TCe|CRDi|GDI|CDTI|JTD|MJT)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_ALPHANUM_MODEL_CODE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:ID\.\d+|T10[XF]|C[345]|2008|3008|5008|308|208)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_DATE_TIME_YEAR_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:\d{2}\.\d{2}\.\d{4}|\d{1,2}:\d{2}|(?:19\d{2}|20\d{2}))(?![A-Za-z0-9])"
)
_CURRENCY_AMOUNT_RE = re.compile(
    r"(?:%\s*\d+(?:[.,]\d+)?|(?<![A-Za-z0-9])\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?\s*(?:TL|TRY|EUR|USD|kW|HP|BG|km)\b)",
    re.IGNORECASE,
)
_NEGATION_CORRECTION_RE = re.compile(
    r"(?<![A-Za-zÇĞİÖŞÜçğıöşü])(?:değil|hayır|başka|veya|yoksa|mi|mı|mu|mü)(?![A-Za-zÇĞİÖŞÜçğıöşü])",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ProtectedSpanRecord:
    """Immutable protected span indexed by half-open Unicode code points into RAW."""

    span: UnicodeSpan
    category: ProtectedCategory
    raw_literal: str
    deterministic_value: str | None = None
    valid: bool = True
    source_provenance: str = "f2b_scanner"

    def __repr__(self) -> str:
        return (
            f"ProtectedSpanRecord(category={self.category.value}, "
            f"span=[{self.span.start},{self.span.end_exclusive}), valid={self.valid})"
        )


@dataclass(frozen=True, slots=True)
class ProtectedSpanScanResult:
    """Ordered non-overlapping protected spans and semantic relation markers."""

    spans: tuple[ProtectedSpanRecord, ...]
    negation_spans: tuple[ProtectedSpanRecord, ...]
    raw_len: int

    def overlaps_protected(self, span: UnicodeSpan) -> bool:
        """Return True if `span` overlaps any non-negation protected identifier/value."""
        return any(
            rec.category != ProtectedCategory.NEGATION_CORRECTION
            and rec.span.start < span.end_exclusive
            and span.start < rec.span.end_exclusive
            for rec in self.spans
        )

    def overlaps_hard_identifier(self, span: UnicodeSpan) -> bool:
        """Return True if `span` overlaps a phone, plate, VIN, DTC, engine/model code, or amount."""
        hard = {
            ProtectedCategory.PHONE,
            ProtectedCategory.PLATE,
            ProtectedCategory.VIN,
            ProtectedCategory.DTC,
            ProtectedCategory.ENGINE_CODE,
            ProtectedCategory.CURRENCY_AMOUNT,
            ProtectedCategory.YEAR_DATE_TIME,
            ProtectedCategory.BUSINESS_REF,
        }
        return any(
            rec.category in hard and rec.span.start < span.end_exclusive and span.start < rec.span.end_exclusive
            for rec in self.spans
        )


def _map_m05_kind(kind: ProtectedSpanKind) -> ProtectedCategory:
    if kind == ProtectedSpanKind.PHONE:
        return ProtectedCategory.PHONE
    if kind == ProtectedSpanKind.PLATE:
        return ProtectedCategory.PLATE
    if kind == ProtectedSpanKind.VIN:
        return ProtectedCategory.VIN
    if kind == ProtectedSpanKind.DTC:
        return ProtectedCategory.DTC
    return ProtectedCategory.YEAR_DATE_TIME


def scan_protected_spans(raw_text: str) -> ProtectedSpanScanResult:
    """
    Scan RAW transcript for protected automotive identifiers, numbers, and
    Turkish negation/correction/choice markers before generic entity lookup.

    Precedence resolves longest valid structured match first without overlaps.
    """
    if not raw_text:
        return ProtectedSpanScanResult(spans=(), negation_spans=(), raw_len=0)

    candidates: list[tuple[int, int, ProtectedCategory, str]] = []

    # 1. Reuse M05 protected span policy (VIN, PHONE, PLATE, DTC, NUMBER)
    for m05 in detect_protected_spans(raw_text):
        if m05.kind != ProtectedSpanKind.NUMBER:
            candidates.append((m05.span.start, m05.span.end_exclusive, _map_m05_kind(m05.kind), "m05_protected"))

    # 2. Structured engine codes, currency/amounts, dates/years, model codes
    for m in _ENGINE_CODE_RE.finditer(raw_text):
        candidates.append((m.start(), m.end(), ProtectedCategory.ENGINE_CODE, "f2b_engine"))
    for m in _CURRENCY_AMOUNT_RE.finditer(raw_text):
        candidates.append((m.start(), m.end(), ProtectedCategory.CURRENCY_AMOUNT, "f2b_amount"))
    for m in _DATE_TIME_YEAR_RE.finditer(raw_text):
        candidates.append((m.start(), m.end(), ProtectedCategory.YEAR_DATE_TIME, "f2b_datetime"))
    for m in _ALPHANUM_MODEL_CODE_RE.finditer(raw_text):
        candidates.append((m.start(), m.end(), ProtectedCategory.MODEL_CODE, "f2b_model_code"))

    # 3. Remaining M05 numeric spans (lowest precedence among structured)
    for m05 in detect_protected_spans(raw_text):
        if m05.kind == ProtectedSpanKind.NUMBER:
            candidates.append((m05.span.start, m05.span.end_exclusive, ProtectedCategory.CURRENCY_AMOUNT, "m05_number"))

    # 4. Negation / correction / choice markers
    neg_records: list[ProtectedSpanRecord] = []
    for m in _NEGATION_CORRECTION_RE.finditer(raw_text):
        rec = ProtectedSpanRecord(
            span=UnicodeSpan(start=m.start(), end_exclusive=m.end(), representation="RAW"),
            category=ProtectedCategory.NEGATION_CORRECTION,
            raw_literal=raw_text[m.start() : m.end()],
            deterministic_value=turkish_nfc_lower(raw_text[m.start() : m.end()]),
            source_provenance="f2b_negation",
        )
        neg_records.append(rec)
        candidates.append((m.start(), m.end(), ProtectedCategory.NEGATION_CORRECTION, "f2b_negation"))

    # Sort by longest span first, then earliest start, then category priority
    priority_order = {
        ProtectedCategory.VIN: 0,
        ProtectedCategory.PHONE: 1,
        ProtectedCategory.PLATE: 2,
        ProtectedCategory.ENGINE_CODE: 3,
        ProtectedCategory.DTC: 4,
        ProtectedCategory.YEAR_DATE_TIME: 5,
        ProtectedCategory.MODEL_CODE: 6,
        ProtectedCategory.CURRENCY_AMOUNT: 7,
        ProtectedCategory.BUSINESS_REF: 8,
        ProtectedCategory.NEGATION_CORRECTION: 9,
    }
    candidates.sort(
        key=lambda item: (
            -(item[1] - item[0]),
            item[0],
            1 if item[3] == "m05_number" else 0,
            priority_order[item[2]],
        )
    )

    accepted: list[ProtectedSpanRecord] = []
    for start, end, cat, prov in candidates:
        if any(start < rec.span.end_exclusive and rec.span.start < end for rec in accepted):
            continue
        literal = raw_text[start:end]
        accepted.append(
            ProtectedSpanRecord(
                span=UnicodeSpan(start=start, end_exclusive=end, representation="RAW"),
                category=cat,
                raw_literal=literal,
                deterministic_value=turkish_nfc_lower(literal) if cat == ProtectedCategory.NEGATION_CORRECTION else literal,
                valid=True,
                source_provenance=prov,
            )
        )

    accepted.sort(key=lambda r: (r.span.start, r.span.end_exclusive))
    neg_records.sort(key=lambda r: (r.span.start, r.span.end_exclusive))
    return ProtectedSpanScanResult(
        spans=tuple(accepted),
        negation_spans=tuple(neg_records),
        raw_len=len(raw_text),
    )
