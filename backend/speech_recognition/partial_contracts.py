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

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from backend.core.contracts.common import StreamRef, TurnRef
from backend.core.contracts.recognition import ASROutcome, ASRStatus, EntityCandidate, UnicodeSpan
from backend.core.contracts.validation import freeze_value, require_finite, require_safe_id, require_strict_int


class PartialLaneState(StrEnum):
    CONFIRMED_ACTIVE = "CONFIRMED_ACTIVE"
    SEALED_FINALIZING = "SEALED_FINALIZING"
    TERMINAL = "TERMINAL"
    ABORTED = "ABORTED"


class ContinuationCue(StrEnum):
    POSSIBLE_CONTINUATION = "POSSIBLE_CONTINUATION"
    POSSIBLE_COMPLETION = "POSSIBLE_COMPLETION"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True, slots=True)
class SpeechScopeRef:
    """
    Pre-final acoustic speech identity scoped to session incarnation and stream epoch.

    Never derived from transcript text and never fabricates a TurnRef.
    """

    session_id: str
    incarnation_id: str
    stream_ref: StreamRef
    speech_ref: str
    start_sample: int
    turn_ref: TurnRef | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.session_id, "session_id")
        require_safe_id(self.incarnation_id, "incarnation_id")
        require_safe_id(self.speech_ref, "speech_ref")
        if not isinstance(self.stream_ref, StreamRef):
            raise TypeError("stream_ref must be StreamRef")
        if self.stream_ref.session_id != self.session_id:
            raise ValueError("stream_ref.session_id mismatch")
        require_strict_int(self.start_sample, "start_sample", minimum=0)
        if self.turn_ref is not None:
            if not isinstance(self.turn_ref, TurnRef):
                raise TypeError("turn_ref must be TurnRef")
            if self.turn_ref.session_id != self.session_id:
                raise ValueError("turn_ref.session_id mismatch")


@dataclass(frozen=True, slots=True)
class IncrementalAudioView:
    """Bounded immutable view of F1 confirmed speech samples."""

    scope: SpeechScopeRef
    start_sample: int
    end_sample_exclusive: int
    valid_sample_count: int
    sample_rate_hz: int
    channels: int
    has_gap: bool
    clock_domain: str
    _samples: np.ndarray = field(repr=False)

    def __post_init__(self) -> None:
        require_strict_int(self.start_sample, "start_sample", minimum=0)
        require_strict_int(self.end_sample_exclusive, "end_sample_exclusive", minimum=self.start_sample)
        require_strict_int(self.valid_sample_count, "valid_sample_count", minimum=0)
        if self.sample_rate_hz != 16_000:
            raise ValueError("IncrementalAudioView requires 16000 Hz")
        if self.channels != 1:
            raise ValueError("IncrementalAudioView requires mono (1 channel)")

    def samples_view(self) -> np.ndarray:
        return self._samples

    def __repr__(self) -> str:
        return (
            f"IncrementalAudioView(speech={self.scope.speech_ref!r}, "
            f"range=[{self.start_sample},{self.end_sample_exclusive}), "
            f"valid={self.valid_sample_count}, gap={self.has_gap})"
        )


@dataclass(frozen=True, slots=True)
class DecodeWindow:
    """Immutable descriptor of a single P5 partial decode window."""

    scope: SpeechScopeRef
    window_id: str
    request_revision: int
    start_sample: int
    end_sample_exclusive: int
    overlap_with_prev_samples: int
    model_revision: str
    config_revision: str
    lexicon_revision: str | None
    deadline_ns: int
    purpose: str = "PARTIAL"

    def __post_init__(self) -> None:
        require_safe_id(self.window_id, "window_id")
        require_strict_int(self.request_revision, "request_revision", minimum=0)
        require_strict_int(self.start_sample, "start_sample", minimum=0)
        require_strict_int(self.end_sample_exclusive, "end_sample_exclusive", minimum=self.start_sample)
        require_strict_int(self.overlap_with_prev_samples, "overlap_with_prev_samples", minimum=0)
        if self.purpose != "PARTIAL":
            raise ValueError("DecodeWindow purpose must be PARTIAL")


@dataclass(frozen=True, slots=True)
class WordObservation:
    """Validated provider word timing mapped to absolute sample coordinates."""

    word: str
    normalized_word: str
    rel_start_sec: float | None
    rel_end_sec: float | None
    abs_start_sample: int | None
    abs_end_sample_exclusive: int | None
    probability: float | None
    valid_timing: bool


@dataclass(frozen=True, slots=True)
class PartialHypothesis:
    """Immutable raw provider output and normalized tokens for one DecodeWindow."""

    scope: SpeechScopeRef
    window_id: str
    request_id: str
    raw_transcript: str
    normalized_text: str
    words: tuple[WordObservation, ...]
    start_sample: int
    end_sample_exclusive: int
    outcome: ASROutcome
    timestamp_status: str

    def __repr__(self) -> str:
        return (
            f"PartialHypothesis(window={self.window_id!r}, "
            f"range=[{self.start_sample},{self.end_sample_exclusive}), "
            f"outcome={self.outcome.value}, ts={self.timestamp_status!r})"
        )


@dataclass(frozen=True, slots=True)
class TokenProvenance:
    """Maps a single token in ReconciledView back to its originating window and sample range."""

    token: str
    normalized: str
    window_id: str
    abs_start_sample: int | None
    abs_end_sample_exclusive: int | None


@dataclass(frozen=True, slots=True)
class ReconciledView:
    """Derived stitched display view with explicit token provenance; never labeled provider raw."""

    version: int
    derived_text: str
    token_provenance: tuple[TokenProvenance, ...]
    covered_start_sample: int
    covered_end_sample_exclusive: int
    has_gap: bool = False
    discontinuity_reason: str | None = None


@dataclass(frozen=True, slots=True)
class StablePrefixEvidence:
    """Revocable advisory stable-prefix evidence across >=2 comparable windows."""

    revision: int
    stable_prefix: str | None
    prefix_span: UnicodeSpan | None
    independent_observations: int
    boundary_guard_samples: int
    valid: bool
    expiry_ns: int | None = None


@dataclass(frozen=True, slots=True)
class ProvisionalRecognitionRevision:
    """
    Immutable non-actionable partial or stable-prefix revision.

    `actionable` and `business_action_eligible` are strictly False.
    """

    scope: SpeechScopeRef
    revision: int
    status: ASRStatus
    window_id: str
    window_range: tuple[int, int]
    raw_transcript: str
    derived_view: str
    stable_prefix: str | None
    prefix_span: UnicodeSpan | None
    independent_observations: int
    entities: tuple[EntityCandidate, ...] = ()
    canonical_transcript: str | None = None
    timestamp_status: str = "UNKNOWN"
    actionable: bool = False
    business_action_eligible: bool = False

    def __post_init__(self) -> None:
        if self.status not in {ASRStatus.PARTIAL, ASRStatus.STABLE_PREFIX}:
            raise ValueError("ProvisionalRecognitionRevision status must be PARTIAL or STABLE_PREFIX")
        if self.actionable or self.business_action_eligible:
            raise ValueError("ProvisionalRecognitionRevision is never actionable")
        if self.canonical_transcript is not None:
            raise ValueError("ProvisionalRecognitionRevision canonical_transcript must be None")
        object.__setattr__(self, "entities", freeze_value(tuple(self.entities)))

    def __repr__(self) -> str:
        return (
            f"ProvisionalRecognitionRevision(speech={self.scope.speech_ref!r}, "
            f"rev={self.revision}, status={self.status.value}, actionable=False)"
        )


@dataclass(frozen=True, slots=True)
class FinalizationBinding:
    """Atomic seal record binding pre-final scope to authoritative F1-A Utterance & TurnRef."""

    scope: SpeechScopeRef
    utterance_id: str
    turn_ref: TurnRef
    final_start_sample: int
    final_end_sample_exclusive: int
    sealed_partial_high_watermark: int
    final_claim_id: str
    coverage_shortened: bool = False


@dataclass(frozen=True, slots=True)
class SemanticEndpointHint:
    """Read-only advisory hint for future F1-C endpointing; never commits actions."""

    hint_id: str
    speech_ref: str
    revision: int
    covered_end_sample_exclusive: int
    observed_monotonic_ns: int
    valid_until_monotonic_ns: int
    clock_domain: str
    continuation_cue: ContinuationCue
    evidence_kind: str = "HEURISTIC_LEXICAL"
    calibrated_probability: float | None = None
    actionable: bool = False
    semantic_endpoint_decision: str | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.hint_id, "hint_id")
        require_safe_id(self.speech_ref, "speech_ref")
        require_strict_int(self.revision, "revision", minimum=0)
        require_strict_int(self.covered_end_sample_exclusive, "covered_end_sample_exclusive", minimum=0)
        if self.calibrated_probability is not None:
            require_finite(self.calibrated_probability, "calibrated_probability", minimum=0.0, maximum=1.0)
        if self.actionable:
            raise ValueError("SemanticEndpointHint is never actionable")
        if self.semantic_endpoint_decision is not None:
            raise ValueError("F2-C cannot emit semantic_endpoint_decision")
