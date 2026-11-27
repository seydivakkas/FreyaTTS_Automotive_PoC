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

from dataclasses import dataclass, replace
from enum import StrEnum

from backend.core.contracts.recognition import ASROutcome
from backend.speech_recognition.config_adapter import DecodeProfile
from backend.speech_recognition.entity_resolver import (
    ClarificationHint,
    ClarificationReason,
    EntityResolutionReport,
)
from backend.speech_recognition.hotword_planner import HotwordPlan

MAX_DECODE_ATTEMPTS = 2


class DecodeBeamProfile(StrEnum):
    BASELINE_COMPAT = "BASELINE_COMPAT"
    FAST_FINAL = "FAST_FINAL"
    BALANCED_FINAL = "BALANCED_FINAL"
    DIFFICULT_FINAL = "DIFFICULT_FINAL"
    ALTERNATE_FINAL = "ALTERNATE_FINAL"


_PROFILE_BEAM_MAP: dict[DecodeBeamProfile, int] = {
    DecodeBeamProfile.BASELINE_COMPAT: 1,
    DecodeBeamProfile.FAST_FINAL: 1,
    DecodeBeamProfile.BALANCED_FINAL: 3,
    DecodeBeamProfile.DIFFICULT_FINAL: 5,
    DecodeBeamProfile.ALTERNATE_FINAL: 3,
}


@dataclass(frozen=True, slots=True)
class DecodeAttemptRecord:
    """Private bounded record of a single final decode attempt (0 or 1)."""

    utterance_id: str
    attempt_index: int
    beam_profile: DecodeBeamProfile
    beam_size: int
    hotword_plan: HotwordPlan
    outcome: ASROutcome
    raw_transcript: str
    avg_logprob: float | None
    no_speech_prob: float | None
    compression_ratio: float | None
    selected: bool = False
    selection_reason: str = "primary_default"

    def __repr__(self) -> str:
        return (
            f"DecodeAttemptRecord(utt={self.utterance_id!r}, attempt={self.attempt_index}, "
            f"profile={self.beam_profile.value}, beam={self.beam_size}, "
            f"outcome={self.outcome.value}, selected={self.selected})"
        )


@dataclass(frozen=True, slots=True)
class AttemptArbitrationResult:
    """Deterministic selection between attempt0 and optional attempt1."""

    selected_attempt: DecodeAttemptRecord
    selected_resolution: EntityResolutionReport
    attempts: tuple[DecodeAttemptRecord, ...]
    disagreement: bool = False
    clarification_hint: ClarificationHint | None = None
    reason: str = "primary_selected"


def build_attempt_decode_profile(
    base_profile: DecodeProfile,
    beam_profile: DecodeBeamProfile,
) -> DecodeProfile:
    """Return a validated DecodeProfile for the requested beam profile."""
    beam = _PROFILE_BEAM_MAP[beam_profile]
    return replace(base_profile, beam_size=beam)


def should_run_alternate_decode(
    *,
    alternate_enabled: bool,
    attempt0: DecodeAttemptRecord,
    resolution0: EntityResolutionReport,
    remaining_deadline_ms: int,
    min_required_ms: int = 1200,
    cancelled: bool = False,
    quarantined: bool = False,
) -> tuple[bool, str]:
    """
    Bounded gate deciding whether a single alternate final decode attempt (attempt 1)
    is permitted. Never retries after OOM, quarantine, or cancellation.
    """
    if not alternate_enabled:
        return False, "alternate_disabled"
    if cancelled or quarantined:
        return False, "cancelled_or_quarantined"
    if attempt0.attempt_index != 0:
        return False, "max_attempts_reached"
    if attempt0.outcome in {ASROutcome.ERROR, ASROutcome.UNKNOWN, ASROutcome.REJECTED}:
        return False, "primary_native_not_completed"
    if remaining_deadline_ms < min_required_ms:
        return False, "insufficient_remaining_deadline"

    low_lp = attempt0.avg_logprob is not None and attempt0.avg_logprob < -0.65
    has_clarify = resolution0.clarification_hint is not None
    if attempt0.outcome == ASROutcome.NO_SPEECH or low_lp or has_clarify or resolution0.context_contradiction:
        return True, "ambiguity_or_low_evidence_trigger"
    return False, "primary_evidence_sufficient"


def arbitrate_decode_attempts(
    *,
    attempt0: DecodeAttemptRecord,
    resolution0: EntityResolutionReport,
    attempt1: DecodeAttemptRecord | None = None,
    resolution1: EntityResolutionReport | None = None,
) -> AttemptArbitrationResult:
    """
    Deterministically arbitrate between primary attempt0 and optional attempt1.

    - Never merges strings across attempts.
    - If attempts disagree on protected identifiers or negation markers, keeps
      primary attempt0 as raw_transcript and requests F3 clarification.
    """
    if attempt1 is None or resolution1 is None:
        sel0 = replace(attempt0, selected=True, selection_reason="single_attempt")
        return AttemptArbitrationResult(
            selected_attempt=sel0,
            selected_resolution=resolution0,
            attempts=(sel0,),
            disagreement=False,
            clarification_hint=resolution0.clarification_hint,
            reason="single_attempt",
        )

    if attempt1.outcome != ASROutcome.OK:
        sel0 = replace(attempt0, selected=True, selection_reason="alternate_not_ok")
        return AttemptArbitrationResult(
            selected_attempt=sel0,
            selected_resolution=resolution0,
            attempts=(sel0, attempt1),
            disagreement=False,
            clarification_hint=resolution0.clarification_hint,
            reason="alternate_not_ok",
        )

    # Check material disagreement on protected spans or negation markers
    prot0 = [(s.category, s.deterministic_value) for s in resolution0.protected_scan.spans]
    prot1 = [(s.category, s.deterministic_value) for s in resolution1.protected_scan.spans]
    if attempt0.outcome == ASROutcome.OK and prot0 != prot1:
        sel0 = replace(attempt0, selected=True, selection_reason="material_disagreement_keep_primary")
        hint = ClarificationHint(
            utterance_id=attempt0.utterance_id,
            final_revision=0,
            context_revision_used=(
                resolution0.clarification_hint.context_revision_used
                if resolution0.clarification_hint is not None
                else attempt0.hotword_plan.context_revision
            ),
            candidate_ids=tuple(c.entity_id for c in resolution0.candidates),
            slot_category=resolution0.candidates[0].entity_type if resolution0.candidates else None,
            reason=ClarificationReason.DECODER_DISAGREEMENT,
            required=True,
        )
        return AttemptArbitrationResult(
            selected_attempt=sel0,
            selected_resolution=resolution0,
            attempts=(sel0, attempt1),
            disagreement=True,
            clarification_hint=hint,
            reason="material_disagreement_keep_primary",
        )

    # If primary was NO_SPEECH and alternate produced valid OK speech, select alternate
    if attempt0.outcome != ASROutcome.OK and attempt1.outcome == ASROutcome.OK:
        sel1 = replace(attempt1, selected=True, selection_reason="primary_invalid_alternate_ok")
        return AttemptArbitrationResult(
            selected_attempt=sel1,
            selected_resolution=resolution1,
            attempts=(attempt0, sel1),
            disagreement=False,
            clarification_hint=resolution1.clarification_hint,
            reason="primary_invalid_alternate_ok",
        )

    # Prefer alternate only if it resolves ambiguity with higher/comparable acoustic evidence
    lp0 = attempt0.avg_logprob if attempt0.avg_logprob is not None else -999.0
    lp1 = attempt1.avg_logprob if attempt1.avg_logprob is not None else -999.0
    if resolution0.clarification_hint is not None and resolution1.clarification_hint is None and lp1 >= lp0:
        sel1 = replace(attempt1, selected=True, selection_reason="alternate_resolved_ambiguity")
        return AttemptArbitrationResult(
            selected_attempt=sel1,
            selected_resolution=resolution1,
            attempts=(attempt0, sel1),
            disagreement=(attempt0.raw_transcript != attempt1.raw_transcript),
            clarification_hint=None,
            reason="alternate_resolved_ambiguity",
        )

    sel0 = replace(attempt0, selected=True, selection_reason="primary_retained")
    return AttemptArbitrationResult(
        selected_attempt=sel0,
        selected_resolution=resolution0,
        attempts=(sel0, attempt1),
        disagreement=(attempt0.raw_transcript != attempt1.raw_transcript),
        clarification_hint=resolution0.clarification_hint,
        reason="primary_retained",
    )
