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

import math
from dataclasses import dataclass
from enum import StrEnum

from backend.core.contracts.common import StreamRef
from backend.core.contracts.validation import require_safe_id, require_strict_int
from backend.voice_activity.config_adapter import F1RouteMode


def quantize_min_windows(ms: int, *, sample_rate_hz: int = 16000, window_samples: int = 512) -> int:
    """Ceil quantization of milliseconds to full VAD windows."""
    require_strict_int(ms, "ms", minimum=1)
    return math.ceil((ms * (sample_rate_hz // 1000)) / float(window_samples))


def quantize_max_windows(ms: int, *, sample_rate_hz: int = 16000, window_samples: int = 512) -> int:
    """Floor quantization of milliseconds to full VAD windows (never exceeds cap)."""
    require_strict_int(ms, "ms", minimum=1)
    return math.floor((ms * (sample_rate_hz // 1000)) / float(window_samples))


class ContinuationCue(StrEnum):
    POSSIBLE_CONTINUATION = "POSSIBLE_CONTINUATION"
    POSSIBLE_COMPLETION = "POSSIBLE_COMPLETION"
    INCOMPLETE_EXPECTED_SLOT = "INCOMPLETE_EXPECTED_SLOT"
    CORRECTION_OR_NEGATION = "CORRECTION_OR_NEGATION"
    BACKCHANNEL_CANDIDATE = "BACKCHANNEL_CANDIDATE"
    EXPLICIT_INTERRUPT_CUE = "EXPLICIT_INTERRUPT_CUE"
    UNKNOWN = "UNKNOWN"


class EchoAcousticCategory(StrEnum):
    FAR_END_ONLY_LIKELY = "FAR_END_ONLY_LIKELY"
    NEAR_END_ONLY_LIKELY = "NEAR_END_ONLY_LIKELY"
    DOUBLE_TALK_LIKELY = "DOUBLE_TALK_LIKELY"
    NO_RELIABLE_ACTIVITY = "NO_RELIABLE_ACTIVITY"
    UNKNOWN = "UNKNOWN"


class ExpectedSlotCategory(StrEnum):
    NONE = "NONE"
    SHORT_CONFIRMATION = "SHORT_CONFIRMATION"
    NAME = "NAME"
    VEHICLE = "VEHICLE"
    DATE_TIME = "DATE_TIME"
    PHONE_PLATE = "PHONE_PLATE"
    FREE_TEXT = "FREE_TEXT"


class EndpointAdviceKind(StrEnum):
    CONTINUE = "CONTINUE"
    WAIT = "WAIT"
    FINALIZE = "FINALIZE"
    ACOUSTIC_FALLBACK = "ACOUSTIC_FALLBACK"
    INVALID = "INVALID"


class BackchannelCategory(StrEnum):
    BACKCHANNEL_LIKELY = "BACKCHANNEL_LIKELY"
    INTERRUPT_LIKELY = "INTERRUPT_LIKELY"
    ECHO_ONLY_LIKELY = "ECHO_ONLY_LIKELY"
    MEANINGFUL_RESPONSE = "MEANINGFUL_RESPONSE"
    UNKNOWN = "UNKNOWN"


class InterruptionAdviceKind(StrEnum):
    HOLD = "HOLD"
    RESUME_ELIGIBLE = "RESUME_ELIGIBLE"
    COMMIT_ELIGIBLE = "COMMIT_ELIGIBLE"
    BASELINE = "BASELINE"
    INVALID = "INVALID"


@dataclass(frozen=True, slots=True)
class F1CProfileConfig:
    """Validated, bounded profile for F1-C semantic endpointing & backchannel/echo policy."""

    mode: F1RouteMode = F1RouteMode.OFF
    sample_rate_hz: int = 16000
    window_samples: int = 512
    post_roll_samples: int = 2560
    base_budget_ms: int = 320
    min_budget_ms: int = 256
    max_budget_ms: int = 1200
    semantic_wait_deadline_ms: int = 1200
    hint_ttl_ms: int = 750
    hint_max_coverage_lag_samples: int = 12800
    acoustic_evidence_max_age_ms: int = 160
    context_ttl_ms: int = 60000
    enable_echo_rejection: bool = False
    enable_backchannel_rejection: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.mode, F1RouteMode):
            raise ValueError("mode must be F1RouteMode")
        require_strict_int(self.sample_rate_hz, "sample_rate_hz", minimum=16000, maximum=16000)
        require_strict_int(self.window_samples, "window_samples", minimum=512, maximum=512)
        require_strict_int(self.post_roll_samples, "post_roll_samples", minimum=0, maximum=160000)
        require_strict_int(self.min_budget_ms, "min_budget_ms", minimum=32, maximum=10000)
        require_strict_int(self.base_budget_ms, "base_budget_ms", minimum=self.min_budget_ms, maximum=10000)
        require_strict_int(self.max_budget_ms, "max_budget_ms", minimum=self.base_budget_ms, maximum=20000)
        require_strict_int(self.semantic_wait_deadline_ms, "semantic_wait_deadline_ms", minimum=32, maximum=20000)
        require_strict_int(self.hint_ttl_ms, "hint_ttl_ms", minimum=1, maximum=5000)
        require_strict_int(self.hint_max_coverage_lag_samples, "hint_max_coverage_lag_samples", minimum=0, maximum=160000)
        require_strict_int(self.acoustic_evidence_max_age_ms, "acoustic_evidence_max_age_ms", minimum=1, maximum=5000)
        require_strict_int(self.context_ttl_ms, "context_ttl_ms", minimum=1, maximum=600000)
        if type(self.enable_echo_rejection) is not bool:
            raise ValueError("enable_echo_rejection must be bool")
        if type(self.enable_backchannel_rejection) is not bool:
            raise ValueError("enable_backchannel_rejection must be bool")

        min_win = quantize_min_windows(self.min_budget_ms, sample_rate_hz=self.sample_rate_hz, window_samples=self.window_samples)
        max_win = quantize_max_windows(self.max_budget_ms, sample_rate_hz=self.sample_rate_hz, window_samples=self.window_samples)
        if min_win > max_win:
            raise ValueError(f"Quantized min windows ({min_win}) exceeds max windows ({max_win})")
        if self.post_roll_samples > (min_win * self.window_samples):
            raise ValueError("post_roll_samples must be <= quantized min_budget_samples")

    @property
    def min_budget_samples(self) -> int:
        return quantize_min_windows(self.min_budget_ms, sample_rate_hz=self.sample_rate_hz, window_samples=self.window_samples) * self.window_samples

    @property
    def base_budget_samples(self) -> int:
        return quantize_min_windows(self.base_budget_ms, sample_rate_hz=self.sample_rate_hz, window_samples=self.window_samples) * self.window_samples

    @property
    def max_budget_samples(self) -> int:
        return quantize_max_windows(self.max_budget_ms, sample_rate_hz=self.sample_rate_hz, window_samples=self.window_samples) * self.window_samples


@dataclass(frozen=True, slots=True)
class SemanticEndpointHint:
    """Optional provisional F2-C hint consumed by F1-C (strictly non-actionable)."""

    hint_id: str
    speech_scope_id: str
    stream_ref: StreamRef
    revision: int
    covered_end_sample_exclusive: int
    observed_monotonic_ns: int
    ttl_ms: int
    clock_domain: str
    cue: ContinuationCue | None = None
    provisional_text: str | None = None
    stable_prefix_revoked: bool = False
    sealed: bool = False
    actionable: bool = False

    def __post_init__(self) -> None:
        require_safe_id(self.hint_id, "hint_id")
        require_safe_id(self.speech_scope_id, "speech_scope_id")
        if not isinstance(self.stream_ref, StreamRef):
            raise TypeError("stream_ref must be StreamRef")
        require_strict_int(self.revision, "revision", minimum=0)
        require_strict_int(self.covered_end_sample_exclusive, "covered_end_sample_exclusive", minimum=0)
        require_strict_int(self.observed_monotonic_ns, "observed_monotonic_ns", minimum=0)
        require_strict_int(self.ttl_ms, "ttl_ms", minimum=1, maximum=5000)
        if not isinstance(self.clock_domain, str) or not self.clock_domain.strip():
            raise ValueError("clock_domain required")
        if self.cue is not None and not isinstance(self.cue, ContinuationCue):
            raise ValueError("cue must be ContinuationCue or None")
        if self.actionable:
            raise ValueError("SemanticEndpointHint.actionable must always be False")


@dataclass(frozen=True, slots=True)
class AcousticEvidence:
    """Optional F0-B echo/double-talk acoustic evidence interval."""

    evidence_id: str
    stream_ref: StreamRef
    start_sample: int
    end_sample_exclusive: int
    sample_rate_hz: int
    observed_monotonic_ns: int
    clock_domain: str
    category: EchoAcousticCategory
    reference_valid: bool = True
    alignment_valid: bool = True
    history_sufficient: bool = True

    def __post_init__(self) -> None:
        require_safe_id(self.evidence_id, "evidence_id")
        if not isinstance(self.stream_ref, StreamRef):
            raise TypeError("stream_ref must be StreamRef")
        require_strict_int(self.start_sample, "start_sample", minimum=0)
        require_strict_int(self.end_sample_exclusive, "end_sample_exclusive", minimum=self.start_sample)
        require_strict_int(self.sample_rate_hz, "sample_rate_hz", minimum=8000, maximum=48000)
        require_strict_int(self.observed_monotonic_ns, "observed_monotonic_ns", minimum=0)
        if not isinstance(self.clock_domain, str) or not self.clock_domain.strip():
            raise ValueError("clock_domain required")
        if not isinstance(self.category, EchoAcousticCategory):
            raise ValueError("category must be EchoAcousticCategory")


@dataclass(frozen=True, slots=True)
class ExpectedSlotProjection:
    """Read-only F3-A dialogue slot expectation (opaque scope only, zero PII)."""

    context_revision: int
    workflow_stage: str
    expected_slot: ExpectedSlotCategory
    prompt_role: str
    confirmation_pending: bool
    prompt_presented: bool | None
    issued_monotonic_ns: int
    ttl_ms: int
    clock_domain: str
    subject_scope_id: str

    def __post_init__(self) -> None:
        require_strict_int(self.context_revision, "context_revision", minimum=0)
        if not isinstance(self.expected_slot, ExpectedSlotCategory):
            raise ValueError("expected_slot must be ExpectedSlotCategory")
        if type(self.confirmation_pending) is not bool:
            raise ValueError("confirmation_pending must be bool")
        require_strict_int(self.issued_monotonic_ns, "issued_monotonic_ns", minimum=0)
        require_strict_int(self.ttl_ms, "ttl_ms", minimum=1, maximum=600000)
        if not isinstance(self.clock_domain, str) or not self.clock_domain.strip():
            raise ValueError("clock_domain required")
        require_safe_id(self.subject_scope_id, "subject_scope_id")


@dataclass(frozen=True, slots=True)
class EndpointAdvice:
    """Pure policy advice for SILENCE_PENDING (never allocates a turn)."""

    kind: EndpointAdviceKind
    effective_silence_samples: int
    effective_windows: int
    requested_budget_ms: int
    effective_budget_ms: int
    reason: str
    cue: ContinuationCue = ContinuationCue.UNKNOWN
    actionable_for_business: bool = False


@dataclass(frozen=True, slots=True)
class InterruptionAdvice:
    """Pure F1-C advisory output for F1-B (never directly executes M02 commands)."""

    kind: InterruptionAdviceKind
    backchannel_category: BackchannelCategory
    acoustic_category: EchoAcousticCategory
    reason: str
    business_approval: bool = False
