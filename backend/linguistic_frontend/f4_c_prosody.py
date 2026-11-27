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
import math
import re

from backend.linguistic_frontend.chunking_adapter import ChunkCandidate, ChunkingResult, chunk_normalized_text
from backend.linguistic_frontend.f4_b_morphology import F4BMorphologyBundle
from backend.linguistic_frontend.protected_atoms import ProtectedAtom
from backend.linguistic_frontend.text_mapping import TextMapping
from backend.morphology.clitics import CliticLookaheadAnalyzer, STANDALONE_CLITICS
from backend.morphology.lexicon import get_stress_exceptions
from backend.morphology.stress_engine import MorphologicalStressEngine
from backend.morphology.syllabifier import TurkishSyllabifier, VOWELS
from backend.morphology.text_utils import tr_lower

# Advisory-only import — resolve_intent_prosody provides prosody metadata guidance
# but MUST NOT mutate model_text or inject SSML/XML unless capability-gated externally.
from backend.linguistic_frontend.intent_prosody import (
    IntentProsodySpec,
    INTENT_PROSODY_TABLE,
    resolve_intent_prosody,
)


F4C_RULE_REVISION = "f4c-tr-prosody-1.0"
_LONG_VOWELS = frozenset({"â", "î", "û"})
_QUESTION_CLITICS = frozenset({
    "mi", "mı", "mu", "mü",
    "misin", "mısın", "musun", "müsün",
    "miyiz", "mıyız", "muyuz", "müyüz",
    "miydi", "mıydı", "muydu", "müydü",
})
_ADDITIVE_CLITICS = frozenset({"de", "da"})
_CONJUNCTION_CLITICS = frozenset({"ki"})

# Restricted Sezer-eligible place names (not a universal brand rule)
_SEZER_PLACE_LEXICON: dict[str, int] = {
    "ankara": 0,
    "adana": 1,
    "istanbul": 1,
    "izmir": 0,
    "antalya": 1,
    "sakarya": 1,
}

# Speech-act to lab prosody profile (rate_factor, contour_category)
_SPEECH_ACT_PROFILES: dict[str, tuple[float, str]] = {
    "INFORM": (1.00, "NEUTRAL"),
    "STATEMENT": (1.00, "NEUTRAL"),
    "GREETING": (1.02, "NEUTRAL"),
    "PRICING": (0.93, "NEUTRAL"),
    "QUESTION": (1.00, "YES_NO_QUESTION"),
    "CONFIRMATION": (0.94, "CONFIRMATION"),
    "APOLOGY": (0.95, "APOLOGY"),
    "WARNING": (0.90, "WARNING"),
    "FAREWELL": (0.98, "FAREWELL"),
}

_F6_WSOLA_MIN_RATE = 0.94
_F6_WSOLA_MAX_RATE = 1.06


class SyllableWeight(StrEnum):
    LIGHT = "LIGHT"
    HEAVY = "HEAVY"
    UNKNOWN = "UNKNOWN"


class StressRuleClass(StrEnum):
    DEFAULT_FINAL = "DEFAULT_FINAL"
    PRE_STRESSING_SUFFIX = "PRE_STRESSING_SUFFIX"
    LEXICALIZED_EXCEPTION = "LEXICALIZED_EXCEPTION"
    SEZER_ELIGIBLE = "SEZER_ELIGIBLE"
    CLITIC_LOCKED = "CLITIC_LOCKED"
    MONOSYLLABIC = "MONOSYLLABIC"
    UNKNOWN = "UNKNOWN"


class CliticType(StrEnum):
    QUESTION_MI = "QUESTION_MI"
    ADDITIVE_DE = "ADDITIVE_DE"
    CONJUNCTION_KI = "CONJUNCTION_KI"
    OTHER = "OTHER"


class ControlOwner(StrEnum):
    NONE = "NONE"
    F5 = "F5"
    F6 = "F6"


class CapabilitySupportStatus(StrEnum):
    DECLARED = "DECLARED"
    VERIFIED = "VERIFIED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SyllableUnit:
    index: int
    span: tuple[int, int]
    surface: str
    weight: SyllableWeight
    method: str = "TurkishSyllabifier"


@dataclass(frozen=True, slots=True)
class SyllabificationResult:
    token_ref: str
    syllables: tuple[SyllableUnit, ...]
    status: str
    rule_revision: str = F4C_RULE_REVISION


@dataclass(frozen=True, slots=True)
class StressAssessment:
    token_ref: str
    primary_index: int | None
    rule_class: StressRuleClass
    uncertainty: str | None = None


@dataclass(frozen=True, slots=True)
class CliticLink:
    host_token_ref: str
    dependent_token_ref: str
    boundary_ref: str
    clitic_type: CliticType
    may_split: bool


@dataclass(frozen=True, slots=True)
class LiaisonHint:
    left_token_ref: str
    right_token_ref: str
    boundary_ref: str
    eligible: bool
    reason: str
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProsodyTarget:
    speech_act: str
    contour_category: str
    requested_rate_factor: float | None
    focus_entity_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PauseIntent:
    boundary_id: str
    requested_ms: int | None
    owner: ControlOwner
    policy_rev: str
    reason: str
    terminal: bool = False


@dataclass(frozen=True, slots=True)
class ControlDisposition:
    control_id: str
    kind: str
    requested_value: float | int | str | None
    support_status: CapabilitySupportStatus
    chosen_owner: ControlOwner
    effective_value: float | int | str | None
    consumed_status: str = "NOT_APPLIED"
    behavior_revision: str = F4C_RULE_REVISION


@dataclass(frozen=True, slots=True)
class F4CProsodyBundle:
    """Complete immutable F4-C prosody, syllabification, stress, clitic, and control plan."""

    syllabifications: tuple[SyllabificationResult, ...] = ()
    stress_assessments: tuple[StressAssessment, ...] = ()
    clitic_links: tuple[CliticLink, ...] = ()
    liaison_hints: tuple[LiaisonHint, ...] = ()
    prosody_target: ProsodyTarget | None = None
    pause_intents: tuple[PauseIntent, ...] = ()
    control_dispositions: tuple[ControlDisposition, ...] = ()
    warnings: tuple[str, ...] = ()
    rule_revision: str = F4C_RULE_REVISION
    intent_prosody: IntentProsodySpec | None = None


def _syllable_weight(syl: str) -> SyllableWeight:
    if not syl:
        return SyllableWeight.UNKNOWN
    last_ch = syl[-1]
    if last_ch in _LONG_VOWELS or last_ch not in VOWELS:
        return SyllableWeight.HEAVY
    return SyllableWeight.LIGHT


def _analyze_syllables_and_stress(
    tokens: list[str],
    *,
    stress_engine: MorphologicalStressEngine,
    clitic_indices: set[int],
) -> tuple[tuple[SyllabificationResult, ...], tuple[StressAssessment, ...]]:
    syl_results: list[SyllabificationResult] = []
    stress_results: list[StressAssessment] = []

    for idx, raw_tok in enumerate(tokens):
        tok_ref = f"tok-{idx}"
        clean = re.sub(r"[^a-zçğıöşüâîû]", "", tr_lower(raw_tok))
        if not clean:
            syl_results.append(SyllabificationResult(token_ref=tok_ref, syllables=(), status="NON_LEXICAL"))
            stress_results.append(StressAssessment(token_ref=tok_ref, primary_index=None, rule_class=StressRuleClass.UNKNOWN, uncertainty="NON_LEXICAL"))
            continue

        syl_offsets = TurkishSyllabifier.syllabify_with_offsets(clean)
        units = tuple(
            SyllableUnit(
                index=s_idx,
                span=(s0, s1),
                surface=s_text,
                weight=_syllable_weight(s_text),
            )
            for s_idx, (s_text, s0, s1) in enumerate(syl_offsets)
        )
        syl_results.append(SyllabificationResult(token_ref=tok_ref, syllables=units, status="RESOLVED"))

        if len(units) <= 1:
            stress_results.append(StressAssessment(token_ref=tok_ref, primary_index=0, rule_class=StressRuleClass.MONOSYLLABIC))
            continue

        # Sezer-class quantity-sensitive rule for restricted place-name lexicon
        if clean in _SEZER_PLACE_LEXICON:
            sezer_idx = _SEZER_PLACE_LEXICON[clean]
            stress_results.append(StressAssessment(token_ref=tok_ref, primary_index=sezer_idx, rule_class=StressRuleClass.SEZER_ELIGIBLE))
            continue

        next_is_clitic = (idx + 1) in clitic_indices
        hint = stress_engine.analyze_word(raw_tok, force_stress_before_clitic=next_is_clitic)
        if hint is not None and hint.primary_stress_syllable_idx is not None:
            if hint.stress_reason == "lexicalized_exception":
                r_cls = StressRuleClass.LEXICALIZED_EXCEPTION
            elif hint.stress_reason == "clitic_locked":
                r_cls = StressRuleClass.CLITIC_LOCKED
            else:
                r_cls = StressRuleClass.PRE_STRESSING_SUFFIX
            stress_results.append(
                StressAssessment(token_ref=tok_ref, primary_index=hint.primary_stress_syllable_idx, rule_class=r_cls)
            )
        else:
            stress_results.append(
                StressAssessment(token_ref=tok_ref, primary_index=len(units) - 1, rule_class=StressRuleClass.DEFAULT_FINAL)
            )

    return tuple(syl_results), tuple(stress_results)


def plan_f4c_prosody_and_chunks(
    normalized_text: str,
    *,
    atoms: tuple[ProtectedAtom, ...],
    text_mapping: TextMapping,
    speech_act: str,
    focus_entity_refs: tuple[str, ...] = (),
    f4b_bundle: F4BMorphologyBundle | None = None,
    max_chunk_chars: int = 270,
    max_chunk_words: int = 15,
    max_total_chunks: int = 64,
    clitic_pause_ms: int = 0,
    emphasis_targets: tuple[str, ...] = (),
    intent: str | None = None,
) -> tuple[ChunkingResult, F4CProsodyBundle]:
    """
    Execute F4-C syllable, lexical stress, Sezer-class, clitic, speech-act/focus,
    protected semantic chunking, and pause/control ownership resolution before
    freezing M01 SynthesisPlan.
    """
    tokens = normalized_text.split()
    clitic_analyzer = CliticLookaheadAnalyzer(default_pause_ms=35)
    _, _, clitic_indices = clitic_analyzer.analyze_tokens(tokens)

    # Resolve advisory intent prosody metadata early (never mutates model_text)
    intent_prosody_spec: IntentProsodySpec | None = resolve_intent_prosody(intent) if intent is not None else None

    stress_engine = MorphologicalStressEngine(get_stress_exceptions())
    syl_results, stress_results = _analyze_syllables_and_stress(
        tokens,
        stress_engine=stress_engine,
        clitic_indices=clitic_indices,
    )

    # Build CliticLinks (host + dependent; question particle may_split=False)
    clitic_links: list[CliticLink] = []
    for c_idx in sorted(clitic_indices):
        if c_idx == 0:
            continue
        clean_c = re.sub(r"[^a-zçğıöşüâîû]", "", tr_lower(tokens[c_idx]))
        if clean_c in _QUESTION_CLITICS:
            c_type = CliticType.QUESTION_MI
            may_split = False
        elif clean_c in _ADDITIVE_CLITICS:
            c_type = CliticType.ADDITIVE_DE
            may_split = True
        elif clean_c in _CONJUNCTION_CLITICS:
            c_type = CliticType.CONJUNCTION_KI
            may_split = True
        else:
            c_type = CliticType.OTHER
            may_split = True

        clitic_links.append(
            CliticLink(
                host_token_ref=f"tok-{c_idx - 1}",
                dependent_token_ref=f"tok-{c_idx}",
                boundary_ref=f"b-tok-{c_idx - 1}-{c_idx}",
                clitic_type=c_type,
                may_split=may_split,
            )
        )

    # Speech-act & focus policy
    act_upper = speech_act.strip().upper()
    req_rate, contour = _SPEECH_ACT_PROFILES.get(act_upper, (1.00, "UNKNOWN"))
    prosody_target = ProsodyTarget(
        speech_act=act_upper,
        contour_category=contour,
        requested_rate_factor=req_rate,
        focus_entity_refs=tuple(focus_entity_refs),
    )

    # Run protected chunking (reusing F4-A chunker with protected atoms)
    chunk_res = chunk_normalized_text(
        normalized_text,
        atoms=atoms,
        text_mapping=text_mapping,
        max_chunk_chars=max_chunk_chars,
        max_chunk_words=max_chunk_words,
        max_total_chunks=max_total_chunks,
        clitic_pause_ms=clitic_pause_ms,
        emphasis_targets=emphasis_targets,
    )

    if not chunk_res.ok:
        return chunk_res, F4CProsodyBundle(
            syllabifications=syl_results,
            stress_assessments=stress_results,
            clitic_links=tuple(clitic_links),
            prosody_target=prosody_target,
            warnings=("F4C_CHUNKING_FAILED",),
            intent_prosody=intent_prosody_spec,
        )

    # Reconcile LiaisonHints AFTER chunk selection (never carry cross-chunk liaison)
    # Build token -> chunk_index map by walking normalized_text
    tok_chunk_idx: dict[int, int] = {}
    search_pos = 0
    for c_idx, chk in enumerate(chunk_res.chunks):
        n0, n1 = chk.norm_span
        for t_i, tok in enumerate(tokens):
            if t_i in tok_chunk_idx:
                continue
            pos = normalized_text.find(tok, search_pos)
            if pos >= 0 and n0 <= pos < n1:
                tok_chunk_idx[t_i] = c_idx
                search_pos = pos + len(tok)

    liaison_hints: list[LiaisonHint] = []
    for idx in range(len(tokens) - 1):
        left_tok = tokens[idx]
        right_tok = tokens[idx + 1]
        left_clean = re.sub(r"[^a-zçğıöşüâîû]", "", tr_lower(left_tok))
        right_clean = re.sub(r"[^a-zçğıöşüâîû]", "", tr_lower(right_tok))
        if not left_clean or not right_clean:
            continue
        if left_clean[-1] not in VOWELS and right_clean[0] in VOWELS:
            blockers: list[str] = []
            if left_tok and left_tok[-1] in ".,!?;:":
                blockers.append("PUNCTUATION_BOUNDARY")
            if tok_chunk_idx.get(idx) != tok_chunk_idx.get(idx + 1):
                blockers.append("CROSS_CHUNK_BOUNDARY")
            liaison_hints.append(
                LiaisonHint(
                    left_token_ref=f"tok-{idx}",
                    right_token_ref=f"tok-{idx + 1}",
                    boundary_ref=f"b-tok-{idx}-{idx + 1}",
                    eligible=(len(blockers) == 0),
                    reason="CONSONANT_TO_VOWEL_ULAMA" if not blockers else "BLOCKED_ULAMA",
                    blockers=tuple(blockers),
                )
            )

    # Pause intents & exact-once control ownership
    pause_intents: list[PauseIntent] = []
    for chk in chunk_res.chunks:
        is_last = chk.chunk_index == len(chunk_res.chunks) - 1
        b_id = f"b-chk-{chk.chunk_index}"
        pause_intents.append(
            PauseIntent(
                boundary_id=b_id,
                requested_ms=chk.post_pause_ms,
                owner=ControlOwner.F6 if chk.post_pause_ms is not None else ControlOwner.NONE,
                policy_rev=F4C_RULE_REVISION,
                reason="PUNCTUATION_OR_CLITIC_PAUSE" if chk.post_pause_ms is not None else "NO_EXPLICIT_PAUSE",
                terminal=is_last,
            )
        )

    # Rate control disposition: exact-once ownership; F6 WSOLA [0.94, 1.06] does not cover 0.90/0.93
    if req_rate < _F6_WSOLA_MIN_RATE or req_rate > _F6_WSOLA_MAX_RATE:
        rate_disp = ControlDisposition(
            control_id="ctrl-rate-0",
            kind="SPEECH_RATE",
            requested_value=req_rate,
            support_status=CapabilitySupportStatus.UNSUPPORTED,
            chosen_owner=ControlOwner.NONE,
            effective_value=None,
            consumed_status="NOT_APPLIED",
        )
    else:
        rate_disp = ControlDisposition(
            control_id="ctrl-rate-0",
            kind="SPEECH_RATE",
            requested_value=req_rate,
            support_status=CapabilitySupportStatus.UNKNOWN,
            chosen_owner=ControlOwner.NONE,
            effective_value=None,
            consumed_status="NOT_APPLIED",
        )

    bundle = F4CProsodyBundle(
        syllabifications=syl_results,
        stress_assessments=stress_results,
        clitic_links=tuple(clitic_links),
        liaison_hints=tuple(liaison_hints),
        prosody_target=prosody_target,
        pause_intents=tuple(pause_intents),
        control_dispositions=(rate_disp,),
        warnings=(),
        intent_prosody=intent_prosody_spec,
    )
    return chunk_res, bundle
