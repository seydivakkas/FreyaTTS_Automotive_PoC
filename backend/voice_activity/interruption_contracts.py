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

from backend.core.contracts.common import GenerationRef, StreamRef
from backend.core.contracts.validation import require_finite, require_safe_id, require_strict_int
from backend.core.runtime.turn_generation import PauseRef


class InterruptionState(StrEnum):
    """F1-B two-stage barge-in decision states."""

    IDLE = "IDLE"
    CANDIDATE_PENDING = "CANDIDATE_PENDING"
    PAUSE_REQUESTED = "PAUSE_REQUESTED"
    SOFT_PAUSED = "SOFT_PAUSED"
    RESUMED = "RESUMED"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"
    REJECTED = "REJECTED"


class OutputAvailability(StrEnum):
    """Authoritative output generation readiness/drain classification."""

    NONE = "NONE"
    SYNTHESIS_PENDING = "SYNTHESIS_PENDING"
    LOCAL_QUEUED = "LOCAL_QUEUED"
    SUBMITTING = "SUBMITTING"
    IN_FLIGHT_POSSIBLE = "IN_FLIGHT_POSSIBLE"
    DRAINED_TERMINAL = "DRAINED_TERMINAL"


@dataclass(frozen=True, slots=True)
class F1BPolicyConfig:
    """Validated bounded policy configuration for F1-B barge-in control."""

    enabled: bool = True
    pause_deadline_ms: int = 250
    allow_synthesis_pending_pause: bool = False
    max_retained_terminal_attempts: int = 32
    allow_precommit_backchannel_reject: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be bool")
        require_strict_int(self.pause_deadline_ms, "pause_deadline_ms", minimum=1, maximum=10000)
        if type(self.allow_synthesis_pending_pause) is not bool:
            raise ValueError("allow_synthesis_pending_pause must be bool")
        require_strict_int(self.max_retained_terminal_attempts, "max_retained_terminal_attempts", minimum=1, maximum=1024)
        if type(self.allow_precommit_backchannel_reject) is not bool:
            raise ValueError("allow_precommit_backchannel_reject must be bool")


@dataclass(frozen=True, slots=True)
class InputCandidateRef:
    """Private opaque identity for an F1-A speech candidate."""

    session_id: str
    incarnation_id: str
    stream_ref: StreamRef
    start_sample: int
    sequence: int

    def __post_init__(self) -> None:
        require_safe_id(self.session_id, "session_id")
        require_safe_id(self.incarnation_id, "incarnation_id")
        if not isinstance(self.stream_ref, StreamRef):
            raise TypeError("stream_ref must be StreamRef")
        if self.stream_ref.session_id != self.session_id:
            raise ValueError("stream_ref.session_id mismatch")
        require_strict_int(self.start_sample, "start_sample", minimum=0)
        require_strict_int(self.sequence, "sequence", minimum=0)

    @property
    def candidate_key(self) -> tuple[str, str, str, int, int]:
        return (
            self.session_id,
            self.incarnation_id,
            self.stream_ref.stream_id,
            self.stream_ref.format_epoch,
            self.start_sample,
        )


@dataclass(frozen=True, slots=True)
class OutputTargetSnapshot:
    """Authoritative snapshot of the current output generation eligible for gating."""

    generation_ref: GenerationRef
    plan_revision: int
    availability: OutputAvailability
    queued_items: int = 0
    queued_bytes: int = 0
    in_flight_submitted: bool = False
    drained: bool = False
    can_gate: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.generation_ref, GenerationRef):
            raise TypeError("generation_ref must be GenerationRef")
        require_strict_int(self.plan_revision, "plan_revision", minimum=0)
        if not isinstance(self.availability, OutputAvailability):
            raise ValueError("availability must be OutputAvailability")
        require_strict_int(self.queued_items, "queued_items", minimum=0)
        require_strict_int(self.queued_bytes, "queued_bytes", minimum=0)
        if type(self.in_flight_submitted) is not bool:
            raise ValueError("in_flight_submitted must be bool")
        if type(self.drained) is not bool:
            raise ValueError("drained must be bool")
        if type(self.can_gate) is not bool:
            raise ValueError("can_gate must be bool")


@dataclass(frozen=True, slots=True)
class FlushIntent:
    """Target-scoped flush intent emitted on hard commit (never claims remote recall)."""

    command_id: str
    target_generation: GenerationRef
    reason: str
    requested_scope: str = "SERVER"
    local_purged_items: int = 0
    remote_flush_status: str = "UNKNOWN"
    in_flight_recall_claimed: bool = False

    def __post_init__(self) -> None:
        require_safe_id(self.command_id, "command_id")
        if not isinstance(self.target_generation, GenerationRef):
            raise TypeError("target_generation must be GenerationRef")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason required")
        require_strict_int(self.local_purged_items, "local_purged_items", minimum=0)
        if self.in_flight_recall_claimed:
            raise ValueError("in_flight_recall_claimed must always be False")


@dataclass(frozen=True, slots=True)
class InterruptionAttempt:
    """Immutable snapshot of a single F1-B interruption attempt."""

    attempt_id: str
    candidate_ref: InputCandidateRef
    target_generation: GenerationRef
    plan_revision: int
    pause_epoch: int
    state: InterruptionState
    pause_ref: PauseRef | None
    created_monotonic_ns: int
    deadline_monotonic_ns: int
    clock_domain: str
    resolved_monotonic_ns: int | None = None
    reason: str = ""
    flush_intent: FlushIntent | None = None
    in_flight_possible: bool = False

    def __post_init__(self) -> None:
        require_safe_id(self.attempt_id, "attempt_id")
        require_strict_int(self.plan_revision, "plan_revision", minimum=0)
        require_strict_int(self.pause_epoch, "pause_epoch", minimum=0)
        require_strict_int(self.created_monotonic_ns, "created_monotonic_ns", minimum=0)
        require_strict_int(self.deadline_monotonic_ns, "deadline_monotonic_ns", minimum=self.created_monotonic_ns)
        if not isinstance(self.clock_domain, str) or not self.clock_domain.strip():
            raise ValueError("clock_domain required")


@dataclass(frozen=True, slots=True)
class DecisionOutcome:
    """Result of an F1-B controller step."""

    attempt_id: str | None
    state: InterruptionState
    action_taken: str
    reason: str
    observation_scope: str = "SERVER"
    pause_ref: PauseRef | None = None
    flush_intent: FlushIntent | None = None
    in_flight_recall_claimed: bool = False
    local_purged_items: int = 0
    in_flight_possible: bool = False
