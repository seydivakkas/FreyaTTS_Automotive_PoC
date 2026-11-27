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
from enum import StrEnum
import re
import unicodedata

from backend.linguistic_frontend.lexicon_adapter import LexiconAdapter, VariantGovernanceStatus
from backend.linguistic_frontend.protected_atoms import ProtectedAtom
from backend.morphology.inflected_matcher import SUFFIX_CHAIN_REGEX
from backend.morphology.syllabifier import BACK_VOWELS, FRONT_VOWELS, VOWELS
from backend.morphology.text_utils import normalize_apostrophes, tr_lower


F4B_ALGORITHM_REVISION = "f4b-tr-morph-1.0"
G2P_ALPHABET_ID = "freya-tr-phoneme-v1"
G2P_ALPHABET_VERSION = "1.0"

MAX_F4B_SOURCE_CODEPOINTS = 2048
MAX_F4B_TOKENS = 256
MAX_F4B_TOKEN_CODEPOINTS = 128
MAX_F4B_CANDIDATES_PER_TOKEN = 4
MAX_F4B_SUFFIX_PARTS = 8
MAX_F4B_PHONE_UNITS = 4096

_APOSTROPHES = frozenset({"'", "’"})
_TOKEN_RE = re.compile(r"\S+")

# Turkish 8-vowel harmony table: last_vowel -> (two_way_A, four_way_I)
VOWEL_HARMONY_TABLE: dict[str, tuple[str, str]] = {
    "a": ("a", "ı"),
    "ı": ("a", "ı"),
    "â": ("a", "ı"),
    "e": ("e", "i"),
    "i": ("e", "i"),
    "î": ("e", "i"),
    "o": ("a", "u"),
    "u": ("a", "u"),
    "û": ("a", "u"),
    "ö": ("e", "ü"),
    "ü": ("e", "ü"),
}

# Lexicalized consonant-final exceptions that resist soft-alternation (p/b, ç/c, t/d, k/ğ)
CONSONANT_ALTERNATION_EXCEPTIONS = frozenset({
    "hukuk",
    "devlet",
    "millet",
    "sanat",
    "saat",
    "dikkat",
    "sepet",
    "paket",
    "bilet",
    "market",
    "motor",
    "jant",
    "park",
    "tank",
})

# Invariant or partially harmonic suffixes that do not undergo full 2-way/4-way harmony
INVARIANT_SUFFIXES = frozenset({"ki", "yor", "ken", "yken"})

# Bounded Turkish suffix inventory for explainable decomposition
_KNOWN_SUFFIX_TABLE: tuple[tuple[str, str], ...] = (
    ("larımızdan", "PLURAL+POSS_1PL+ABLATIVE"),
    ("lerimizden", "PLURAL+POSS_1PL+ABLATIVE"),
    ("larımızda", "PLURAL+POSS_1PL+LOCATIVE"),
    ("lerimizde", "PLURAL+POSS_1PL+LOCATIVE"),
    ("larımız", "PLURAL+POSS_1PL"),
    ("lerimiz", "PLURAL+POSS_1PL"),
    ("larınız", "PLURAL+POSS_2PL"),
    ("leriniz", "PLURAL+POSS_2PL"),
    ("ların", "PLURAL+GENITIVE"),
    ("lerin", "PLURAL+GENITIVE"),
    ("lardan", "PLURAL+ABLATIVE"),
    ("lerden", "PLURAL+ABLATIVE"),
    ("larda", "PLURAL+LOCATIVE"),
    ("lerde", "PLURAL+LOCATIVE"),
    ("lara", "PLURAL+DATIVE"),
    ("lere", "PLURAL+DATIVE"),
    ("ları", "PLURAL+ACC_OR_POSS3"),
    ("leri", "PLURAL+ACC_OR_POSS3"),
    ("lar", "PLURAL"),
    ("ler", "PLURAL"),
    ("ımız", "POSS_1PL"),
    ("imiz", "POSS_1PL"),
    ("umuz", "POSS_1PL"),
    ("ümüz", "POSS_1PL"),
    ("ınız", "POSS_2PL"),
    ("iniz", "POSS_2PL"),
    ("unuz", "POSS_2PL"),
    ("ünüz", "POSS_2PL"),
    ("daki", "LOCATIVE+RELATIVIZER"),
    ("deki", "LOCATIVE+RELATIVIZER"),
    ("taki", "LOCATIVE+RELATIVIZER"),
    ("teki", "LOCATIVE+RELATIVIZER"),
    ("dan", "ABLATIVE"),
    ("den", "ABLATIVE"),
    ("tan", "ABLATIVE"),
    ("ten", "ABLATIVE"),
    ("da", "LOCATIVE"),
    ("de", "LOCATIVE"),
    ("ta", "LOCATIVE"),
    ("te", "LOCATIVE"),
    ("nın", "GENITIVE"),
    ("nin", "GENITIVE"),
    ("nun", "GENITIVE"),
    ("nün", "GENITIVE"),
    ("ın", "GENITIVE_OR_POSS2SG"),
    ("in", "GENITIVE_OR_POSS2SG"),
    ("un", "GENITIVE_OR_POSS2SG"),
    ("ün", "GENITIVE_OR_POSS2SG"),
    ("ya", "DATIVE"),
    ("ye", "DATIVE"),
    ("a", "DATIVE"),
    ("e", "DATIVE"),
    ("yı", "ACCUSATIVE"),
    ("yi", "ACCUSATIVE"),
    ("yu", "ACCUSATIVE"),
    ("yü", "ACCUSATIVE"),
    ("ı", "ACC_OR_POSS3"),
    ("i", "ACC_OR_POSS3"),
    ("u", "ACC_OR_POSS3"),
    ("ü", "ACC_OR_POSS3"),
    ("yla", "INSTRUMENTAL"),
    ("yle", "INSTRUMENTAL"),
    ("la", "INSTRUMENTAL"),
    ("le", "INSTRUMENTAL"),
    ("lı", "DERIVATIONAL_WITH"),
    ("li", "DERIVATIONAL_WITH"),
    ("lu", "DERIVATIONAL_WITH"),
    ("lü", "DERIVATIONAL_WITH"),
    ("sız", "DERIVATIONAL_WITHOUT"),
    ("siz", "DERIVATIONAL_WITHOUT"),
    ("suz", "DERIVATIONAL_WITHOUT"),
    ("süz", "DERIVATIONAL_WITHOUT"),
    ("dır", "COPULA"),
    ("dir", "COPULA"),
    ("dur", "COPULA"),
    ("dür", "COPULA"),
    ("tır", "COPULA"),
    ("tir", "COPULA"),
    ("tur", "COPULA"),
    ("tür", "COPULA"),
    ("yor", "PROGRESSIVE"),
    ("ken", "CONVERB"),
    ("ki", "RELATIVIZER"),
)

_G2P_MAP: dict[str, str] = {
    "a": "a", "b": "b", "c": "dZ", "ç": "tS", "d": "d", "e": "e",
    "f": "f", "g": "g", "ğ": ":", "h": "h", "ı": "1", "i": "i",
    "j": "Z", "k": "k", "l": "l", "m": "m", "n": "n", "o": "o",
    "ö": "2", "p": "p", "r": "r", "s": "s", "ş": "S", "t": "t",
    "u": "u", "ü": "y", "v": "v", "y": "j", "z": "z",
    "â": "a:", "î": "i:", "û": "u:",
}


class AnalysisStatus(StrEnum):
    RESOLVED = "RESOLVED"
    CANDIDATE = "CANDIDATE"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


class RealizationDecisionKind(StrEnum):
    PRESERVE = "PRESERVE"
    APPLY_APPROVED = "APPLY_APPROVED"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED = "UNSUPPORTED"
    BLOCKED = "BLOCKED"


class G2PStatus(StrEnum):
    MAPPED = "MAPPED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


def _validate_span(span: tuple[int, int], max_len: int, label: str) -> tuple[int, int]:
    if len(span) != 2:
        raise ValueError(f"{label} must be 2-tuple")
    s, e = span
    if type(s) is not int or type(e) is not int:
        raise TypeError(f"{label} indices must be exact int (bool rejected)")
    if s < 0 or e < s or e > max_len:
        raise ValueError(f"{label} out of bounds: {span} for len {max_len}")
    return (s, e)


@dataclass(frozen=True, slots=True)
class SuffixPart:
    """Source-aligned suffix segment with grammatical function and harmony class."""

    raw_span: tuple[int, int]
    surface_form: str
    morph_type: str
    grammatical_function: str
    harmony_class: str
    observed_form: str
    realized_form: str
    rule_ref: str

    def __post_init__(self) -> None:
        s, e = self.raw_span
        if type(s) is not int or type(e) is not int or s < 0 or e < s:
            raise ValueError(f"Invalid SuffixPart span: {self.raw_span}")


@dataclass(frozen=True, slots=True)
class MorphologicalAnalysis:
    """Source-aligned root/suffix morphological analysis for one token."""

    token_id: str
    source_span: tuple[int, int]
    root_span: tuple[int, int]
    separator_span: tuple[int, int] | None
    suffix_parts: tuple[SuffixPart, ...]
    lexical_entity_ref: str | None
    lemma: str
    grammatical_features: tuple[str, ...]
    analysis_status: AnalysisStatus
    alternatives: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    algorithm_revision: str = F4B_ALGORITHM_REVISION

    def __post_init__(self) -> None:
        s0, s1 = self.source_span
        r0, r1 = self.root_span
        if type(s0) is not int or type(s1) is not int or type(r0) is not int or type(r1) is not int:
            raise TypeError("Spans must use exact int")
        if s0 < 0 or r0 < s0 or r1 < r0 or r1 > s1:
            raise ValueError("root_span must lie within source_span")
        if self.separator_span is not None:
            p0, p1 = self.separator_span
            if type(p0) is not int or type(p1) is not int or p0 < r1 or p1 < p0 or p1 > s1:
                raise ValueError("separator_span must follow root_span within source_span")


@dataclass(frozen=True, slots=True)
class PronunciationBasis:
    """Scoped M05 pronunciation basis with explicit review & acoustic status."""

    token_id: str
    entity_ref: str | None
    variant_id: str | None
    model_scope: str
    locale: str
    spoken_basis: str | None
    pronunciation_strategy: str
    review_state: VariantGovernanceStatus | str
    acoustic_status: str = "NOT_RUN"
    source_ref: str = "M05"


@dataclass(frozen=True, slots=True)
class G2PGuidance:
    """Private CPU-only grapheme-to-phoneme guidance kept separate from model_text."""

    token_id: str
    source_span: tuple[int, int]
    phone_alphabet: str
    alphabet_version: str
    phone_sequence: tuple[str, ...] | None
    grapheme_to_phone_alignment: tuple[tuple[int, int], ...]
    status: G2PStatus
    rule_ids: tuple[str, ...] = ()
    uncertainty: str | None = None


@dataclass(frozen=True, slots=True)
class RealizationDecision:
    """Explicit realization decision for a token without silent variant activation."""

    token_id: str
    decision: RealizationDecisionKind
    selected_variant_id: str | None
    model_text_candidate: str | None
    source_span: tuple[int, int]
    reason: str


@dataclass(frozen=True, slots=True)
class F4BMorphologyBundle:
    """Complete immutable F4-B morphology, phonology, and G2P guidance bundle."""

    analyses: tuple[MorphologicalAnalysis, ...] = ()
    pronunciation_bases: tuple[PronunciationBasis, ...] = ()
    g2p_guidances: tuple[G2PGuidance, ...] = ()
    realization_decisions: tuple[RealizationDecision, ...] = ()
    warnings: tuple[str, ...] = ()
    algorithm_revision: str = F4B_ALGORITHM_REVISION
    budget_exceeded: bool = False


def resolve_vowel_harmony(stem_or_basis: str) -> tuple[str, str] | None:
    """Return (two_way_A, four_way_I) for the last relevant vowel in stem_or_basis."""
    lowered = tr_lower(stem_or_basis)
    for ch in reversed(lowered):
        if ch in VOWEL_HARMONY_TABLE:
            return VOWEL_HARMONY_TABLE[ch]
    return None


def _decompose_suffixes(
    suffix_text: str,
    *,
    base_offset: int,
    stem_lower: str,
) -> tuple[tuple[SuffixPart, ...], tuple[str, ...], AnalysisStatus]:
    """Bounded deterministic suffix decomposition."""
    if not suffix_text:
        return (), (), AnalysisStatus.RESOLVED

    lowered = tr_lower(suffix_text)
    if not SUFFIX_CHAIN_REGEX.fullmatch(lowered):
        # Single unknown/unparsed suffix span
        part = SuffixPart(
            raw_span=(base_offset, base_offset + len(suffix_text)),
            surface_form=suffix_text,
            morph_type="UNPARSED",
            grammatical_function="UNKNOWN",
            harmony_class="UNKNOWN",
            observed_form=suffix_text,
            realized_form=suffix_text,
            rule_ref="f4b.suffix.unknown",
        )
        return (part,), ("UNKNOWN",), AnalysisStatus.UNKNOWN

    parts: list[SuffixPart] = []
    features: list[str] = []
    pos = 0
    ambiguous = False
    harmony = resolve_vowel_harmony(stem_lower)
    h_class = f"A={harmony[0]},I={harmony[1]}" if harmony else "UNKNOWN"

    while pos < len(lowered) and len(parts) < MAX_F4B_SUFFIX_PARTS:
        matched = False
        for suf_form, feat in _KNOWN_SUFFIX_TABLE:
            if lowered.startswith(suf_form, pos):
                end = pos + len(suf_form)
                raw_slice = suffix_text[pos:end]
                if "OR" in feat:
                    ambiguous = True
                is_inv = suf_form in INVARIANT_SUFFIXES
                parts.append(
                    SuffixPart(
                        raw_span=(base_offset + pos, base_offset + end),
                        surface_form=raw_slice,
                        morph_type="INVARIANT" if is_inv else "INFLECTIONAL",
                        grammatical_function=feat,
                        harmony_class="INVARIANT" if is_inv else h_class,
                        observed_form=raw_slice,
                        realized_form=raw_slice,
                        rule_ref="f4b.suffix.table.v1",
                    )
                )
                features.append(feat)
                pos = end
                matched = True
                break
        if not matched:
            parts.append(
                SuffixPart(
                    raw_span=(base_offset + pos, base_offset + len(suffix_text)),
                    surface_form=suffix_text[pos:],
                    morph_type="INFLECTIONAL",
                    grammatical_function="SUFFIX_SEGMENT",
                    harmony_class=h_class,
                    observed_form=suffix_text[pos:],
                    realized_form=suffix_text[pos:],
                    rule_ref="f4b.suffix.chain.v1",
                )
            )
            features.append("SUFFIX_SEGMENT")
            pos = len(lowered)

    status = AnalysisStatus.AMBIGUOUS if ambiguous else AnalysisStatus.RESOLVED
    return tuple(parts), tuple(features), status


def _compute_g2p_guidance(
    token_id: str,
    source_span: tuple[int, int],
    basis_text: str,
    *,
    is_supported_basis: bool,
) -> G2PGuidance:
    """Deterministic CPU-only grapheme-to-phoneme guidance over approved/ordinary basis."""
    if not basis_text or not is_supported_basis:
        return G2PGuidance(
            token_id=token_id,
            source_span=source_span,
            phone_alphabet=G2P_ALPHABET_ID,
            alphabet_version=G2P_ALPHABET_VERSION,
            phone_sequence=None,
            grapheme_to_phone_alignment=(),
            status=G2PStatus.UNKNOWN,
            rule_ids=(),
            uncertainty="BASIS_UNVERIFIED",
        )

    lowered = tr_lower(unicodedata.normalize("NFC", basis_text))
    phones: list[str] = []
    align: list[tuple[int, int]] = []
    partial = False
    for idx, ch in enumerate(lowered):
        if ch in _APOSTROPHES or ch in ".-,;:!?":
            continue
        ph = _G2P_MAP.get(ch)
        if ph is not None:
            p_idx = len(phones)
            phones.append(ph)
            align.append((idx, p_idx))
        else:
            partial = True

    if not phones:
        return G2PGuidance(
            token_id=token_id,
            source_span=source_span,
            phone_alphabet=G2P_ALPHABET_ID,
            alphabet_version=G2P_ALPHABET_VERSION,
            phone_sequence=None,
            grapheme_to_phone_alignment=(),
            status=G2PStatus.UNSUPPORTED,
            rule_ids=(),
            uncertainty="NO_PHONEME_MAPPING",
        )

    return G2PGuidance(
        token_id=token_id,
        source_span=source_span,
        phone_alphabet=G2P_ALPHABET_ID,
        alphabet_version=G2P_ALPHABET_VERSION,
        phone_sequence=tuple(phones),
        grapheme_to_phone_alignment=tuple(align),
        status=G2PStatus.PARTIAL if partial else G2PStatus.MAPPED,
        rule_ids=("f4b.g2p.tr.v1",),
        uncertainty="PARTIAL_GRAPHEME_COVERAGE" if partial else None,
    )


def analyze_f4b_morphology(
    source_text: str,
    *,
    atoms: tuple[ProtectedAtom, ...] = (),
    lexicon_adapter: LexiconAdapter | None = None,
    model_scope: str = "freya-tr-v1",
    locale: str = "tr-TR",
) -> F4BMorphologyBundle:
    """
    Execute bounded, source-aligned F4-B Turkish morphology, pronunciation-basis
    selection, and private G2P guidance over source_text.

    Never mutates source_text, never activates PROPOSED/QUARANTINED/REJECTED
    variants, and never injects IPA/SSML into model_text.
    """
    if not source_text or not source_text.strip():
        return F4BMorphologyBundle()

    if len(source_text) > MAX_F4B_SOURCE_CODEPOINTS:
        return F4BMorphologyBundle(
            warnings=("F4B_SOURCE_CAP_EXCEEDED",),
            budget_exceeded=True,
        )

    analyses: list[MorphologicalAnalysis] = []
    bases: list[PronunciationBasis] = []
    guidances: list[G2PGuidance] = []
    decisions: list[RealizationDecision] = []
    warnings: list[str] = []
    total_phones = 0

    # Index top-level protected atoms by source span
    top_atoms = [a for a in atoms if a.parent_atom_id is None]

    for tok_idx, m in enumerate(_TOKEN_RE.finditer(source_text)):
        if tok_idx >= MAX_F4B_TOKENS:
            warnings.append("F4B_TOKEN_CAP_EXCEEDED")
            return F4BMorphologyBundle(
                analyses=tuple(analyses),
                pronunciation_bases=tuple(bases),
                g2p_guidances=tuple(guidances),
                realization_decisions=tuple(decisions),
                warnings=tuple(warnings),
                budget_exceeded=True,
            )

        tok_start, tok_end = m.start(), m.end()
        raw_tok = m.group(0)
        # Strip leading/trailing punctuation while keeping exact source offsets
        l_trim = 0
        while l_trim < len(raw_tok) and raw_tok[l_trim] in ".,!?;:\"'()[]{}":
            l_trim += 1
        r_trim = len(raw_tok)
        while r_trim > l_trim and raw_tok[r_trim - 1] in ".,!?;:\"'()[]{}":
            r_trim -= 1

        if r_trim <= l_trim:
            continue

        c_start = tok_start + l_trim
        c_end = tok_start + r_trim
        core_tok = source_text[c_start:c_end]
        if len(core_tok) > MAX_F4B_TOKEN_CODEPOINTS:
            warnings.append("F4B_TOKEN_LEN_CAP_EXCEEDED")
            continue

        token_id = f"tok-{tok_idx}"

        # Check if token overlaps a ProtectedAtom
        matched_atom: ProtectedAtom | None = None
        for a in top_atoms:
            a0, a1 = a.raw_span
            if a0 <= c_start and c_end <= a1:
                matched_atom = a
                break
            if a0 < c_end and c_start < a1:
                matched_atom = a
                break

        # Split on apostrophe if present (preserving literal span)
        apos_idx = -1
        for ap in _APOSTROPHES:
            idx = core_tok.find(ap)
            if idx > 0:
                apos_idx = idx
                break

        if apos_idx > 0:
            root_str = core_tok[:apos_idx]
            root_span = (c_start, c_start + apos_idx)
            sep_span = (c_start + apos_idx, c_start + apos_idx + 1)
            suf_str = core_tok[apos_idx + 1 :]
            suf_base = c_start + apos_idx + 1
        else:
            root_str = core_tok
            root_span = (c_start, c_end)
            sep_span = None
            suf_str = ""
            suf_base = c_end

        # M05 scoped pronunciation lookup (without activating unapproved variants)
        entity_ref: str | None = matched_atom.atom_id if matched_atom else None
        variant_id: str | None = None
        spoken_basis: str | None = None
        strategy = "ORDINARY_TURKISH"
        review_state: VariantGovernanceStatus | str = "NOT_APPLICABLE"
        decision_kind = RealizationDecisionKind.PRESERVE
        decision_reason = "ORDINARY_OR_PRESERVED"
        model_candidate: str | None = core_tok

        if matched_atom is not None:
            strategy = f"PROTECTED_{matched_atom.kind.value}"

        if lexicon_adapter is not None:
            # Check scoped match for root_str
            lex_match = lexicon_adapter.lookup_term_pronunciation(root_str)
            if lex_match is not None:
                entity_ref = lex_match.entity_id
                variant_id = f"{lex_match.entity_id}:{lex_match.profile}"
                spoken_basis = lex_match.spoken_text
                review_state = lex_match.governance_status
                strategy = "M05_SCOPED_LEXICON"
                if lex_match.governance_status in {
                    VariantGovernanceStatus.APPROVED,
                    VariantGovernanceStatus.LEGACY_PRESERVED,
                }:
                    decision_kind = RealizationDecisionKind.APPLY_APPROVED
                    decision_reason = f"GOVERNANCE_{lex_match.governance_status.value}"
                    model_candidate = f"{lex_match.spoken_text}{suf_str}" if suf_str else lex_match.spoken_text
                else:
                    decision_kind = RealizationDecisionKind.PRESERVE
                    decision_reason = "VARIANT_NOT_ACTIVATED"
                    model_candidate = core_tok
            elif matched_atom is not None and matched_atom.atom_id:
                # Atom is protected, preserve canonical until approved
                gov = VariantGovernanceStatus.PROPOSED
                review_state = gov
                decision_kind = RealizationDecisionKind.PRESERVE
                decision_reason = "VARIANT_NOT_ACTIVATED"

        # Decompose suffix if any
        if suf_str:
            suffix_parts, features, status = _decompose_suffixes(
                suf_str,
                base_offset=suf_base,
                stem_lower=tr_lower(spoken_basis or root_str),
            )
        else:
            suffix_parts = ()
            features = ()
            status = AnalysisStatus.RESOLVED if matched_atom or entity_ref else AnalysisStatus.CANDIDATE

        # Check consonant alternation exception
        root_lower = tr_lower(root_str)
        reason_codes: list[str] = []
        if root_lower in CONSONANT_ALTERNATION_EXCEPTIONS:
            reason_codes.append("CONSONANT_ALTERNATION_EXCEPTION")

        analyses.append(
            MorphologicalAnalysis(
                token_id=token_id,
                source_span=(c_start, c_end),
                root_span=root_span,
                separator_span=sep_span,
                suffix_parts=suffix_parts,
                lexical_entity_ref=entity_ref,
                lemma=root_lower,
                grammatical_features=features,
                analysis_status=status,
                alternatives=(),
                reason_codes=tuple(reason_codes),
            )
        )

        bases.append(
            PronunciationBasis(
                token_id=token_id,
                entity_ref=entity_ref,
                variant_id=variant_id,
                model_scope=model_scope,
                locale=locale,
                spoken_basis=spoken_basis or (core_tok if matched_atom is None else None),
                pronunciation_strategy=strategy,
                review_state=review_state,
                acoustic_status="NOT_RUN",
                source_ref="M05" if variant_id else "SOURCE",
            )
        )

        g2p = _compute_g2p_guidance(
            token_id,
            (c_start, c_end),
            spoken_basis or core_tok,
            is_supported_basis=(matched_atom is None or spoken_basis is not None),
        )
        if g2p.phone_sequence is not None:
            total_phones += len(g2p.phone_sequence)
            if total_phones > MAX_F4B_PHONE_UNITS:
                warnings.append("F4B_PHONE_CAP_EXCEEDED")
                return F4BMorphologyBundle(
                    analyses=tuple(analyses),
                    pronunciation_bases=tuple(bases),
                    g2p_guidances=tuple(guidances),
                    realization_decisions=tuple(decisions),
                    warnings=tuple(warnings),
                    budget_exceeded=True,
                )
        guidances.append(g2p)

        decisions.append(
            RealizationDecision(
                token_id=token_id,
                decision=decision_kind,
                selected_variant_id=variant_id,
                model_text_candidate=model_candidate,
                source_span=(c_start, c_end),
                reason=decision_reason,
            )
        )

    return F4BMorphologyBundle(
        analyses=tuple(analyses),
        pronunciation_bases=tuple(bases),
        g2p_guidances=tuple(guidances),
        realization_decisions=tuple(decisions),
        warnings=tuple(warnings),
        budget_exceeded=False,
    )
