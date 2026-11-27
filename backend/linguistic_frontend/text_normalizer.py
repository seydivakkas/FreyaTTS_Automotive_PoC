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

from backend.linguistic_frontend.lexicon_adapter import LexiconAdapter
from backend.linguistic_frontend.protected_atoms import AtomKind, ProtectedAtom
from backend.linguistic_frontend.text_mapping import (
    NormalizationTrace,
    SpanMappingEntry,
    TextMapping,
    build_text_mapping,
)


RULESET_REVISION = "f4a-tr-rules-1.0"
_FREYA_ACCENT_FALLBACK = str.maketrans("éèëâÉÈËÂ", "eeeaEEEA")
_STAGE_IDS = (
    "stage.1.unicode_nfc",
    "stage.2.protected_atom_realization",
    "stage.3.automotive_lexicon_and_rules",
    "stage.4.vocabulary_safe_punctuation",
)

_UNIT_SPOKEN = {
    "°c": "derece santigrat",
    "km": "kilometre",
    "bg": "beygir",
    "hp": "beygir",
    "kw": "kilovat",
    "kwh": "kilovatsaat",
    "litre": "litre",
    "l": "litre",
    "mm": "milimetre",
    "cm": "santimetre",
    "cc": "si si",
    "kg": "kilogram",
    "bar": "bar",
}

_TR_LETTER_MAP = {
    "A": "a", "B": "be", "C": "ce", "Ç": "çe", "D": "de", "E": "e",
    "F": "fe", "G": "ge", "Ğ": "yumuşak ge", "H": "he", "I": "ı", "İ": "i",
    "J": "je", "K": "ka", "L": "le", "M": "me", "N": "ne", "O": "o",
    "Ö": "ö", "P": "pe", "R": "re", "S": "se", "Ş": "şe", "T": "te",
    "U": "u", "Ü": "ü", "V": "ve", "Y": "ye", "Z": "ze",
    "Q": "ku", "W": "ve", "X": "iks",
}


@dataclass(frozen=True, slots=True)
class SinglePassNormalizationResult:
    """Result of executing the single strict F4-A normalization pass."""

    ok: bool
    source_text: str
    normalized_text: str
    atoms_mapped: tuple[ProtectedAtom, ...]
    text_mapping: TextMapping | None
    trace: NormalizationTrace
    normalization_passes: int = 1
    reason_code: str = "OK"
    safe_message: str = ""
    warnings: tuple[str, ...] = ()


def _tr_lower(text: str) -> str:
    nfc = unicodedata.normalize("NFC", text)
    return nfc.replace("İ", "i").replace("I", "ı").lower().replace("\u0307", "")


def _spell_decimal_exact(val: Decimal, *, spell_int_fn: Any) -> str:
    """Spell an exact Decimal value in Turkish without float rounding."""
    negative = val < 0
    abs_val = -val if negative else val
    s = format(abs_val, "f")
    if "." in s:
        int_part_s, frac_part_s = s.split(".", 1)
        frac_trimmed = frac_part_s.rstrip("0")
    else:
        int_part_s, frac_trimmed = s, ""

    int_spoken = spell_int_fn(int(int_part_s))
    if frac_trimmed:
        if frac_trimmed.startswith("0") and len(frac_trimmed) > 1:
            frac_spoken = " ".join(spell_int_fn(int(ch)) for ch in frac_trimmed)
        else:
            frac_spoken = spell_int_fn(int(frac_trimmed))
        core = f"{int_spoken} nokta {frac_spoken}"
    else:
        core = int_spoken
    return f"eksi {core}" if negative else core


def _realize_atom(
    atom: ProtectedAtom,
    *,
    lexicon_adapter: LexiconAdapter | None,
    spell_int_fn: Any,
    spell_ord_fn: Any,
    harmonize_fn: Any,
    months: list[str],
    code_letters: dict[str, str],
) -> tuple[str, str]:
    """
    Convert a single top-level ProtectedAtom into its approved spoken Turkish string.
    Returns (spoken_text, transformation_kind).
    """
    suf = atom.suffix
    kind = atom.kind

    if kind == AtomKind.PHONE:
        prefix = "artı " if atom.literal_source.lstrip().startswith("+") else ""
        digits = str(atom.semantic_value)
        spoken = prefix + " ".join(spell_int_fn(int(c)) for c in digits)
        return spoken, "ATOM_PHONE"

    if kind == AtomKind.PLATE:
        parts = str(atom.semantic_value).split()
        prov_s, letters_s, digits_s = parts[0], parts[1], parts[2]
        if prov_s.startswith("0"):
            prov_spoken = "sıfır " + spell_int_fn(int(prov_s[1:]))
        else:
            prov_spoken = spell_int_fn(int(prov_s))
        letters_spoken = " ".join(_TR_LETTER_MAP.get(ch, ch.lower()) for ch in letters_s)
        if digits_s.startswith("0"):
            digits_spoken = " ".join(spell_int_fn(int(c)) for c in digits_s)
        else:
            digits_spoken = spell_int_fn(int(digits_s))
        return f"{prov_spoken} {letters_spoken} {digits_spoken}", "ATOM_PLATE"

    if kind == AtomKind.DIAGNOSTIC_CODE:
        code = str(atom.semantic_value)
        first = code_letters.get(code[0], _TR_LETTER_MAP.get(code[0], code[0].lower()))
        rest_parts = []
        for ch in code[1:]:
            if ch.isdigit():
                rest_parts.append(spell_int_fn(int(ch)))
            else:
                rest_parts.append(code_letters.get(ch.upper(), ch.lower()))
        spoken = f"{first} " + " ".join(rest_parts)
        if suf:
            spoken = harmonize_fn(spoken, suf)
        return spoken, "ATOM_DIAGNOSTIC_CODE"

    if kind == AtomKind.ENGINE_CODE:
        disp, rest_low = atom.semantic_value
        maj = int(disp)
        frac = int((disp - maj) * 10)
        rest_spoken = rest_low
        if lexicon_adapter is not None:
            lex_hit = lexicon_adapter.lookup_term_pronunciation(rest_low)
            if lex_hit is not None:
                rest_spoken = lex_hit.spoken_text
        if rest_spoken == rest_low:
            from backend.normalizer_rules import get_lexicon
            rest_spoken = get_lexicon().get(rest_low, rest_low)
        spoken = f"{spell_int_fn(maj)} nokta {spell_int_fn(frac)} {rest_spoken}"
        if suf:
            spoken = harmonize_fn(spoken, suf)
        return spoken, "ATOM_ENGINE_CODE"

    if kind == AtomKind.DATE:
        y, mo, d = atom.semantic_value
        spoken = f"{spell_int_fn(d)} {months[mo - 1]} {spell_int_fn(y)}"
        return spoken, "ATOM_DATE"

    if kind == AtomKind.TIME:
        hh, mm = atom.semantic_value
        spoken = spell_int_fn(hh) if mm == 0 else f"{spell_int_fn(hh)} {spell_int_fn(mm)}"
        if suf:
            spoken = harmonize_fn(spoken, suf)
        return spoken, "ATOM_TIME"

    if kind == AtomKind.CURRENCY:
        val, curr_code = atom.semantic_value
        quantized = val.quantize(Decimal("0.01"))
        int_part = int(quantized)
        minor_units = int((quantized - Decimal(int_part)) * 100)
        if curr_code == "TRY":
            if minor_units > 0:
                spoken = f"{spell_int_fn(int_part)} lira {spell_int_fn(minor_units)} kuruş"
            else:
                spoken = f"{spell_int_fn(int_part)} Türk lirası"
        elif curr_code == "EUR":
            if minor_units > 0:
                spoken = f"{spell_int_fn(int_part)} avro {spell_int_fn(minor_units)} sent"
            else:
                spoken = f"{spell_int_fn(int_part)} avro"
        else:
            if minor_units > 0:
                spoken = f"{spell_int_fn(int_part)} dolar {spell_int_fn(minor_units)} sent"
            else:
                spoken = f"{spell_int_fn(int_part)} dolar"
        if suf:
            spoken = harmonize_fn(spoken, suf)
        return spoken, "ATOM_CURRENCY"

    if kind == AtomKind.PERCENT:
        val: Decimal = atom.semantic_value
        spoken = f"yüzde {_spell_decimal_exact(val, spell_int_fn=spell_int_fn)}"
        if suf:
            spoken = harmonize_fn(spoken, suf)
        return spoken, "ATOM_PERCENT"

    if kind == AtomKind.UNIT:
        val, unit_key = atom.semantic_value
        num_spoken = _spell_decimal_exact(val, spell_int_fn=spell_int_fn)
        u_spoken = _UNIT_SPOKEN.get(unit_key.lower(), unit_key)
        if suf:
            u_spoken = harmonize_fn(u_spoken, suf)
        return f"{num_spoken} {u_spoken}", "ATOM_UNIT"

    if kind == AtomKind.MODEL:
        val_str = str(atom.semantic_value)
        if val_str.startswith("ID."):
            tail = val_str[3:]
            tail_spoken = spell_int_fn(int(tail)) if tail.isdigit() else tail
            spoken = f"i de {tail_spoken}"
        elif re.fullmatch(r"[A-Z]{1,3}\d{1,4}[A-Z]{0,2}", val_str):
            parts = []
            m_parts = re.fullmatch(r"([A-Z]{1,3})(\d{1,4})([A-Z]{0,2})", val_str)
            assert m_parts is not None
            for ch in m_parts.group(1):
                parts.append(code_letters.get(ch, ch.lower()))
            digits_s = m_parts.group(2)
            if digits_s.startswith("0"):
                parts.extend(spell_int_fn(int(c)) for c in digits_s)
            else:
                parts.append(spell_int_fn(int(digits_s)))
            for ch in m_parts.group(3):
                parts.append(code_letters.get(ch, ch.lower()))
            spoken = " ".join(parts)
        else:
            if lexicon_adapter is not None:
                lex_hit = lexicon_adapter.lookup_term_pronunciation(atom.literal_source)
                if lex_hit is not None:
                    return lex_hit.spoken_text, "ATOM_LEXICON_MODEL"
            spoken = atom.literal_source
        if suf:
            spoken = harmonize_fn(spoken, suf)
        return spoken, "ATOM_MODEL"

    if kind in {AtomKind.BRAND, AtomKind.TRIM, AtomKind.ABBREVIATION}:
        if val_str := str(atom.semantic_value):
            if val_str == "4x4":
                return "dört çeker", "ATOM_ABBREVIATION"
        if lexicon_adapter is not None:
            lex_hit = lexicon_adapter.lookup_term_pronunciation(atom.literal_source)
            if lex_hit is not None:
                return lex_hit.spoken_text, "ATOM_LEXICON"
        from backend.normalizer_rules import get_lexicon
        lex = get_lexicon()
        low = _tr_lower(atom.literal_source)
        if low in lex:
            return lex[low], "ATOM_LEXICON_BASE"
        return atom.literal_source, "ATOM_IDENTITY"

    if kind == AtomKind.ORDINAL:
        return spell_ord_fn(int(atom.semantic_value)), "ATOM_ORDINAL"

    if kind in {AtomKind.DECIMAL, AtomKind.NUMBER}:
        if isinstance(atom.semantic_value, str) and atom.semantic_value.isdigit():
            spoken = " ".join(spell_int_fn(int(c)) for c in atom.semantic_value)
        else:
            spoken = _spell_decimal_exact(Decimal(atom.semantic_value), spell_int_fn=spell_int_fn)
        if suf:
            spoken = harmonize_fn(spoken, suf)
        return spoken, "ATOM_NUMBER"

    return atom.literal_source, "IDENTITY"


def _normalize_free_segment(
    segment: str,
    *,
    lexicon_adapter: LexiconAdapter | None,
    harmonize_fn: Any,
    base_lexicon: dict[str, str],
) -> tuple[str, str]:
    """
    Normalize a non-atom free-text segment with Turkish NFC, approved lexicon
    variants (longest token-boundary match), and safe punctuation cleanup.
    """
    if not segment:
        return "", "EMPTY"
    t = unicodedata.normalize("NFC", segment)
    # Remove stray combining dot above after Turkish lowercase if present
    t = t.replace("\u0307", "")

    # Safe symbol replacements matching legacy normalizer behavior
    t = t.replace("−", " eksi ").replace("&", " ve ")
    t = t.replace("!", ".").replace("...", ", ").replace("…", ", ")
    t = t.replace(" — ", ", ").replace(" - ", ", ")
    t = re.sub(r"[()\[\]{}]", ", ", t)
    t = re.sub(r"[\"#\*\^_`|~<>\\]", " ", t)

    # Apply approved M05 / base lexicon terms at exact word boundaries (no substring replacement!)
    if lexicon_adapter is not None:
        scoped = lexicon_adapter.lookup_scoped(t)
        if scoped:
            # Replace right-to-left so spans remain valid
            out = t
            for sc in sorted(scoped, key=lambda x: x.raw_span[0], reverse=True):
                s0, s1 = sc.raw_span
                out = out[:s0] + sc.spoken_text + out[s1:]
            t = out
    else:
        for key in sorted(base_lexicon.keys(), key=len, reverse=True):
            spoken_val = base_lexicon[key]
            pattern = r"(?<![A-Za-z0-9ÇĞİÖŞÜçğıöşü])" + re.escape(key) + r"(?:['’](?P<suf>[a-zA-ZçğıöşüÇĞİÖŞÜ]+))?(?![A-Za-z0-9ÇĞİÖŞÜçğıöşü])"
            t = re.sub(
                pattern,
                lambda m, sv=spoken_val: harmonize_fn(sv, m.group("suf")) if m.group("suf") else sv,
                t,
                flags=re.IGNORECASE,
            )

    # Character-level model compatibility folding (preserves I/İ/ı/i, folds foreign accents)
    t = t.replace("q", "k").replace("Q", "K")
    t = t.replace("w", "v").replace("W", "V")
    t = t.replace("x", "ks").replace("X", "Ks")
    t = t.replace("Ğ", "ğ").translate(_FREYA_ACCENT_FALLBACK)
    # Collapse internal multi-spaces to single spaces while preserving edge spaces for concatenation
    lead_space = " " if t[:1].isspace() else ""
    trail_space = " " if len(t) > 1 and t[-1:].isspace() else ("" if not t[-1:].isspace() else lead_space)
    core = re.sub(r"[ \t\r\n]+", " ", t).strip()
    if not core:
        return (" " if (lead_space or trail_space) else ""), "WHITESPACE_FOLD"
    return f"{lead_space}{core}{trail_space}", "LEXICON_AND_PUNCT"


def run_single_normalization_pass(
    source_text: str,
    *,
    atoms: tuple[ProtectedAtom, ...],
    response_id: str,
    plan_id: str,
    lexicon_adapter: LexiconAdapter | None = None,
    max_expanded_chars: int = 16000,
) -> SinglePassNormalizationResult:
    """
    Single strict F4-A normalization authority (`normalization_passes=1`).

    Executes ordered stages once over `source_text` using pre-scanned top-level
    ProtectedAtoms and builds an exact half-open codepoint TextMapping.
    """
    from backend.normalizer_rules import (
        MODEL_CODE_LETTERS,
        get_lexicon,
        harmonize_suffix,
        spell_tr_int,
        spell_tr_ordinal,
    )
    from backend.text import MONTHS

    stage_trace: list[str] = []
    # Stage 1: Unicode NFC awareness check (source_text itself remains untouched)
    stage_trace.append(_STAGE_IDS[0])

    top_atoms = sorted(
        (a for a in atoms if a.parent_atom_id is None),
        key=lambda a: (a.raw_span[0], a.raw_span[1]),
    )
    children_by_parent: dict[str, list[ProtectedAtom]] = {}
    for a in atoms:
        if a.parent_atom_id is not None:
            children_by_parent.setdefault(a.parent_atom_id, []).append(a)

    base_lex = get_lexicon()
    out_parts: list[str] = []
    entries: list[SpanMappingEntry] = []
    updated_atoms: list[ProtectedAtom] = []
    cursor_src = 0
    cursor_norm = 0

    def _append_segment(src_start: int, src_end: int, piece: str, atom_ids: tuple[str, ...], kind_tag: str) -> tuple[int, int]:
        nonlocal cursor_norm
        if out_parts and piece and not out_parts[-1].endswith(" ") and not piece.startswith((" ", ".", ",", ";", ":", "?", "!")):
            # Ensure token boundary separation if atom replacement abutted a word
            pass
        start_n = cursor_norm
        out_parts.append(piece)
        cursor_norm += len(piece)
        end_n = cursor_norm
        entries.append(
            SpanMappingEntry(
                source_span=(src_start, src_end),
                target_span=(start_n, end_n),
                atom_ids=atom_ids,
                transformation_kind=kind_tag,
                rule_revision=RULESET_REVISION,
            )
        )
        return (start_n, end_n)

    # Stage 2 & 3: Realize protected atoms and normalize interstitial text once
    stage_trace.append(_STAGE_IDS[1])
    stage_trace.append(_STAGE_IDS[2])

    for atom in top_atoms:
        a_start, a_end = atom.raw_span
        if a_start > cursor_src:
            free_raw = source_text[cursor_src:a_start]
            free_norm, free_kind = _normalize_free_segment(
                free_raw,
                lexicon_adapter=lexicon_adapter,
                harmonize_fn=harmonize_suffix,
                base_lexicon=base_lex,
            )
            _append_segment(cursor_src, a_start, free_norm, (), free_kind)

        spoken, trans_kind = _realize_atom(
            atom,
            lexicon_adapter=lexicon_adapter,
            spell_int_fn=spell_tr_int,
            spell_ord_fn=spell_tr_ordinal,
            harmonize_fn=harmonize_suffix,
            months=MONTHS,
            code_letters=MODEL_CODE_LETTERS,
        )
        spoken = spoken.replace("Ğ", "ğ").translate(_FREYA_ACCENT_FALLBACK)
        norm_span = _append_segment(a_start, a_end, spoken, (atom.atom_id,), trans_kind)
        updated_atoms.append(
            ProtectedAtom(
                atom_id=atom.atom_id,
                kind=atom.kind,
                raw_span=atom.raw_span,
                literal_source=atom.literal_source,
                semantic_value=atom.semantic_value,
                unresolved=atom.unresolved,
                unresolved_reason=atom.unresolved_reason,
                provenance_ref=atom.provenance_ref,
                transformation_policy=atom.transformation_policy,
                normalized_span=norm_span,
                critical=atom.critical,
                parent_atom_id=atom.parent_atom_id,
                children_ids=atom.children_ids,
                suffix=atom.suffix,
            )
        )
        for child in children_by_parent.get(atom.atom_id, ()):
            updated_atoms.append(
                ProtectedAtom(
                    atom_id=child.atom_id,
                    kind=child.kind,
                    raw_span=child.raw_span,
                    literal_source=child.literal_source,
                    semantic_value=child.semantic_value,
                    unresolved=child.unresolved,
                    unresolved_reason=child.unresolved_reason,
                    provenance_ref=child.provenance_ref,
                    transformation_policy=child.transformation_policy,
                    normalized_span=norm_span,
                    critical=child.critical,
                    parent_atom_id=child.parent_atom_id,
                    children_ids=child.children_ids,
                    suffix=child.suffix,
                )
            )
        cursor_src = a_end

    if cursor_src < len(source_text):
        tail_raw = source_text[cursor_src:]
        tail_norm, tail_kind = _normalize_free_segment(
            tail_raw,
            lexicon_adapter=lexicon_adapter,
            harmonize_fn=harmonize_suffix,
            base_lexicon=base_lex,
        )
        _append_segment(cursor_src, len(source_text), tail_norm, (), tail_kind)

    # Stage 4: Final whitespace normalization while keeping exact SpanMappingEntry alignment
    stage_trace.append(_STAGE_IDS[3])
    raw_joined = "".join(out_parts)
    # Trim leading/trailing spaces cleanly and update boundary offsets
    lead_trim = len(raw_joined) - len(raw_joined.lstrip(" "))
    trail_trim = len(raw_joined) - len(raw_joined.rstrip(" "))
    normalized_text = raw_joined.strip(" ")

    if len(normalized_text) > max_expanded_chars:
        trace = NormalizationTrace(
            response_id=response_id,
            plan_id=plan_id,
            pass_count=1,
            ruleset_revision=RULESET_REVISION,
            stage_ids=tuple(stage_trace),
            source_length=len(source_text),
            normalized_length=len(normalized_text),
            warning_codes=("LIMIT_EXCEEDED",),
        )
        return SinglePassNormalizationResult(
            ok=False,
            source_text=source_text,
            normalized_text="",
            atoms_mapped=tuple(updated_atoms),
            text_mapping=None,
            trace=trace,
            normalization_passes=1,
            reason_code="LIMIT_EXCEEDED",
            safe_message="Normalized text exceeds max_expanded_chars",
        )

    if not normalized_text or not any(ch.isalnum() for ch in normalized_text):
        trace = NormalizationTrace(
            response_id=response_id,
            plan_id=plan_id,
            pass_count=1,
            ruleset_revision=RULESET_REVISION,
            stage_ids=tuple(stage_trace),
            source_length=len(source_text),
            normalized_length=len(normalized_text),
            warning_codes=("EMPTY_NORMALIZED_TEXT",),
        )
        return SinglePassNormalizationResult(
            ok=False,
            source_text=source_text,
            normalized_text="",
            atoms_mapped=tuple(updated_atoms),
            text_mapping=None,
            trace=trace,
            normalization_passes=1,
            reason_code="EMPTY_NORMALIZED_TEXT",
            safe_message="No speakable alphanumeric content remained after normalization",
        )

    max_len = len(normalized_text)
    adjusted_entries: list[SpanMappingEntry] = []
    for e in entries:
        t0 = max(0, min(max_len, e.target_span[0] - lead_trim))
        t1 = max(t0, min(max_len, e.target_span[1] - lead_trim))
        adjusted_entries.append(
            SpanMappingEntry(
                source_span=e.source_span,
                target_span=(t0, t1),
                atom_ids=e.atom_ids,
                transformation_kind=e.transformation_kind,
                rule_revision=e.rule_revision,
            )
        )

    adjusted_atoms: list[ProtectedAtom] = []
    for a in updated_atoms:
        if a.normalized_span is None:
            adjusted_atoms.append(a)
        else:
            ns0 = max(0, min(max_len, a.normalized_span[0] - lead_trim))
            ns1 = max(ns0, min(max_len, a.normalized_span[1] - lead_trim))
            adjusted_atoms.append(
                ProtectedAtom(
                    atom_id=a.atom_id,
                    kind=a.kind,
                    raw_span=a.raw_span,
                    literal_source=a.literal_source,
                    semantic_value=a.semantic_value,
                    unresolved=a.unresolved,
                    unresolved_reason=a.unresolved_reason,
                    provenance_ref=a.provenance_ref,
                    transformation_policy=a.transformation_policy,
                    normalized_span=(ns0, ns1),
                    critical=a.critical,
                    parent_atom_id=a.parent_atom_id,
                    children_ids=a.children_ids,
                    suffix=a.suffix,
                )
            )

    mapping = build_text_mapping(
        source_text=source_text,
        normalized_text=normalized_text,
        entries=adjusted_entries,
        ruleset_revision=RULESET_REVISION,
    )
    trace = NormalizationTrace(
        response_id=response_id,
        plan_id=plan_id,
        pass_count=1,
        ruleset_revision=RULESET_REVISION,
        stage_ids=tuple(stage_trace),
        source_length=len(source_text),
        normalized_length=len(normalized_text),
    )
    return SinglePassNormalizationResult(
        ok=True,
        source_text=source_text,
        normalized_text=normalized_text,
        atoms_mapped=tuple(adjusted_atoms),
        text_mapping=mapping,
        trace=trace,
        normalization_passes=1,
        reason_code="OK",
    )
