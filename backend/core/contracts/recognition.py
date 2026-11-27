"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from backend.core.contracts.common import ErrorInfo, EventEnvelope, MetricSample
from backend.core.contracts.validation import freeze_value, require_finite, require_safe_id, require_strict_int


class ASRStatus(StrEnum):
    PARTIAL = "PARTIAL"
    STABLE_PREFIX = "STABLE_PREFIX"
    FINAL = "FINAL"


class ASROutcome(StrEnum):
    OK = "OK"
    NO_SPEECH = "NO_SPEECH"
    REJECTED = "REJECTED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class CatalogStatus(StrEnum):
    VERIFIED = "VERIFIED"
    NOT_FOUND = "NOT_FOUND"
    UNVERIFIED = "UNVERIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ConfirmationStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ConfidenceEstimate:
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    ranking_score: float | None = None
    calibrated_prob: float | None = None
    calibration_version: str | None = None

    def __post_init__(self) -> None:
        if self.avg_logprob is not None:
            require_finite(self.avg_logprob, "avg_logprob", maximum=0.0)
        if self.no_speech_prob is not None:
            require_finite(self.no_speech_prob, "no_speech_prob", minimum=0.0, maximum=1.0)
        if self.ranking_score is not None:
            require_finite(self.ranking_score, "ranking_score", minimum=0.0)
        if self.calibrated_prob is not None:
            require_finite(self.calibrated_prob, "calibrated_prob", minimum=0.0, maximum=1.0)
            if not isinstance(self.calibration_version, str) or not self.calibration_version.strip():
                raise ValueError("calibrated_prob requires calibration_version")


@dataclass(frozen=True, slots=True)
class UnicodeSpan:
    start: int
    end_exclusive: int
    representation: str = "RAW"

    def __post_init__(self) -> None:
        require_strict_int(self.start, "start", minimum=0)
        require_strict_int(self.end_exclusive, "end_exclusive", minimum=self.start)
        if self.representation not in {"RAW", "NORMALIZED", "CANONICAL"}:
            raise ValueError("representation must be RAW, NORMALIZED, or CANONICAL")


@dataclass(frozen=True, slots=True)
class EntityCandidate:
    entity_id: str
    entity_type: str
    raw_value: str
    canonical_value: str | None = None
    source_span: UnicodeSpan | None = None
    score: float | None = None
    score_kind: str | None = None
    scorer_revision: str | None = None
    alternatives: tuple[str, ...] = ()
    catalog_status: CatalogStatus = CatalogStatus.UNVERIFIED
    confirmation_status: ConfirmationStatus = ConfirmationStatus.CANDIDATE

    def __post_init__(self) -> None:
        require_safe_id(self.entity_id, "entity_id")
        if not isinstance(self.entity_type, str) or not self.entity_type.strip():
            raise ValueError("entity_type required")
        if not isinstance(self.raw_value, str):
            raise TypeError("raw_value must be str")
        if self.score is not None:
            require_finite(self.score, "score")
        if not isinstance(self.catalog_status, CatalogStatus):
            raise ValueError("catalog_status invalid")
        if not isinstance(self.confirmation_status, ConfirmationStatus):
            raise ValueError("confirmation_status invalid")
        object.__setattr__(self, "alternatives", freeze_value(tuple(self.alternatives)))


@dataclass(frozen=True, slots=True)
class ASRResult:
    envelope: EventEnvelope
    utterance_id: str
    revision: int
    status: ASRStatus
    raw_transcript: str
    outcome: ASROutcome
    language: str | None = None
    normalized_transcript: str | None = None
    canonical_transcript: str | None = None
    stable_prefix: str | None = None
    entities: tuple[EntityCandidate, ...] = ()
    confidence: ConfidenceEstimate | None = None
    requires_confirmation: bool | None = None
    error: ErrorInfo | None = None
    metrics: tuple[MetricSample, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, EventEnvelope):
            raise TypeError("envelope must be EventEnvelope")
        require_safe_id(self.utterance_id, "utterance_id")
        require_strict_int(self.revision, "revision", minimum=0)
        if not isinstance(self.status, ASRStatus):
            raise ValueError("status must be ASRStatus")
        if not isinstance(self.outcome, ASROutcome):
            raise ValueError("outcome must be ASROutcome")
        if not isinstance(self.raw_transcript, str):
            raise TypeError("raw_transcript must be str")
        if self.outcome == ASROutcome.OK and not self.raw_transcript.strip():
            raise ValueError("Empty raw_transcript cannot have outcome=OK")
        if self.status in {ASRStatus.PARTIAL, ASRStatus.STABLE_PREFIX} and self.envelope.turn_id is not None:
            # Partial ASR may still carry turn_id if scoped, but never authorizes writes.
            pass
        for ent in self.entities:
            if ent.source_span is not None and ent.source_span.representation == "RAW":
                if ent.source_span.end_exclusive > len(self.raw_transcript):
                    raise ValueError("Entity RAW source_span exceeds raw_transcript length")
        object.__setattr__(self, "entities", freeze_value(tuple(self.entities)))
        object.__setattr__(self, "metrics", freeze_value(tuple(self.metrics)))

    @property
    def is_write_eligible(self) -> bool:
        return self.status == ASRStatus.FINAL and self.outcome == ASROutcome.OK

    def __repr__(self) -> str:
        return (
            f"ASRResult(utterance_id={self.utterance_id!r}, rev={self.revision}, "
            f"status={self.status.value}, outcome={self.outcome.value})"
        )
