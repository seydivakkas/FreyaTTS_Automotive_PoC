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
from decimal import Decimal
import re
import unicodedata
from typing import Any

from backend.core.contracts.dialogue import VerifiedFactRef
from backend.linguistic_frontend.lexicon_adapter import LexiconAdapter
from backend.linguistic_frontend.protected_atoms import (
    AtomKind,
    ProtectedAtom,
    ProtectedAtomScanResult,
    scan_protected_atoms,
)


@dataclass(frozen=True, slots=True)
class SemanticTokenizationResult:
    """Conservative tokenization & semantic value binding result."""

    ok: bool
    scan: ProtectedAtomScanResult
    atoms: tuple[ProtectedAtom, ...]
    fact_conflicts: tuple[str, ...] = ()
    unresolved_reasons: tuple[str, ...] = ()
    reason_code: str = "OK"


def _nfc_tr_lower(text: str) -> str:
    nfc = unicodedata.normalize("NFC", text)
    return nfc.replace("İ", "i").replace("I", "ı").lower().replace("\u0307", "")


def _check_fact_conflicts(
    atoms: tuple[ProtectedAtom, ...],
    facts: tuple[VerifiedFactRef, ...],
    source_text: str,
) -> tuple[str, ...]:
    """
    Detect explicit mismatches between F3 VerifiedFactRef descriptors and source text atoms.
    Fact references follow safe reference IDs like 'price:TRY:1250000', 'time:14:30',
    'date:2027-06-05', 'engine:1.6', 'dtc:P0300'. Never invents missing facts.
    """
    if not facts:
        return ()
    conflicts: list[str] = []
    for fact in facts:
        ref = fact.reference_id.strip()
        ref_low = _nfc_tr_lower(ref)
        # Check typed numeric/time/date/engine/dtc hints encoded in reference_id
        m_price = re.match(r"^(?:price|amount|currency)[:_-](?:try|tl|eur|usd)[:_-](\d+(?:\.\d+)?)$", ref_low)
        if m_price:
            expected_val = Decimal(m_price.group(1))
            curr_atoms = [a for a in atoms if a.kind == AtomKind.CURRENCY and isinstance(a.semantic_value, tuple)]
            if curr_atoms and all(a.semantic_value[0] != expected_val for a in curr_atoms):
                conflicts.append(f"FACT_CURRENCY_MISMATCH:{fact.reference_id}")

        m_time = re.match(r"^time[:_-]([0-2]?\d)[:._-]([0-5]\d)$", ref_low)
        if m_time:
            exp_t = (int(m_time.group(1)), int(m_time.group(2)))
            time_atoms = [a for a in atoms if a.kind == AtomKind.TIME]
            if time_atoms and all(a.semantic_value != exp_t for a in time_atoms):
                conflicts.append(f"FACT_TIME_MISMATCH:{fact.reference_id}")

        m_date = re.match(r"^date[:_-](\d{4})-(\d{2})-(\d{2})$", ref_low)
        if m_date:
            exp_d = (int(m_date.group(1)), int(m_date.group(2)), int(m_date.group(3)))
            date_atoms = [a for a in atoms if a.kind == AtomKind.DATE]
            if date_atoms and all(a.semantic_value != exp_d for a in date_atoms):
                conflicts.append(f"FACT_DATE_MISMATCH:{fact.reference_id}")

        m_engine = re.match(r"^engine[:_-](\d+\.\d+)$", ref_low)
        if m_engine:
            exp_e = Decimal(m_engine.group(1))
            eng_atoms = [a for a in atoms if a.kind == AtomKind.ENGINE_CODE and isinstance(a.semantic_value, tuple)]
            if eng_atoms and all(a.semantic_value[0] != exp_e for a in eng_atoms):
                conflicts.append(f"FACT_ENGINE_MISMATCH:{fact.reference_id}")

        m_dtc = re.match(r"^dtc[:_-]([pcbu][0-3][0-9a-f]{3})$", ref_low)
        if m_dtc:
            exp_code = m_dtc.group(1).upper()
            dtc_atoms = [a for a in atoms if a.kind == AtomKind.DIAGNOSTIC_CODE]
            if dtc_atoms and all(a.semantic_value != exp_code for a in dtc_atoms):
                conflicts.append(f"FACT_DTC_MISMATCH:{fact.reference_id}")
    return tuple(conflicts)


def tokenize_semantic_atoms(
    source_text: str,
    *,
    verified_fact_refs: tuple[VerifiedFactRef, ...] = (),
    lexicon_adapter: LexiconAdapter | None = None,
    max_atoms: int = 128,
    max_numeric_digits: int = 15,
    max_token_length: int = 64,
) -> SemanticTokenizationResult:
    """
    Scan source_text conservatively for protected atoms, resolve F3 fact backing,
    and detect unresolved ambiguous values or semantic conflicts.
    """
    scan = scan_protected_atoms(
        source_text,
        verified_fact_refs=verified_fact_refs,
        lexicon_adapter=lexicon_adapter,
        max_atoms=max_atoms,
        max_numeric_digits=max_numeric_digits,
        max_token_length=max_token_length,
    )
    if not scan.ok:
        return SemanticTokenizationResult(
            ok=False,
            scan=scan,
            atoms=scan.atoms,
            reason_code=scan.reason_code,
        )

    conflicts = _check_fact_conflicts(scan.atoms, verified_fact_refs, source_text)
    if conflicts:
        return SemanticTokenizationResult(
            ok=False,
            scan=scan,
            atoms=scan.atoms,
            fact_conflicts=conflicts,
            reason_code="SEMANTIC_FACT_CONFLICT",
        )

    unresolved_reasons = tuple(
        f"{a.atom_id}:{a.kind.value}:{a.unresolved_reason or 'UNRESOLVED'}"
        for a in scan.atoms
        if a.unresolved and a.critical
    )
    if unresolved_reasons:
        return SemanticTokenizationResult(
            ok=False,
            scan=scan,
            atoms=scan.atoms,
            unresolved_reasons=unresolved_reasons,
            reason_code="UNRESOLVED_ATOM",
        )

    return SemanticTokenizationResult(
        ok=True,
        scan=scan,
        atoms=scan.atoms,
        reason_code="OK",
    )
