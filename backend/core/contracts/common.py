"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from backend.core.contracts.validation import (
    freeze_value,
    require_finite,
    require_safe_id,
    require_strict_int,
    require_utc_iso,
)

CONTRACT_SCHEMA_VERSION = "2.0"


@dataclass(frozen=True, slots=True)
class ContractVersion:
    major: int
    minor: int

    def __post_init__(self) -> None:
        require_strict_int(self.major, "major", minimum=1, maximum=999)
        require_strict_int(self.minor, "minor", minimum=0, maximum=999)

    @classmethod
    def parse(cls, raw: str) -> "ContractVersion":
        if not isinstance(raw, str) or "." not in raw:
            raise ValueError("ContractVersion must be '<major>.<minor>'")
        parts = raw.split(".")
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            raise ValueError("ContractVersion segments must be non-negative digits")
        ver = cls(int(parts[0]), int(parts[1]))
        if ver.major != 2:
            raise ValueError(f"Unsupported contract major version: {ver.major}")
        return ver

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


class StreamDirection(StrEnum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"


class ErrorCategory(StrEnum):
    VALIDATION = "VALIDATION"
    STALE_SCOPE = "STALE_SCOPE"
    CAPACITY = "CAPACITY"
    PROVIDER = "PROVIDER"
    SECURITY = "SECURITY"
    INTERNAL = "INTERNAL"


class Retryability(StrEnum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


class MetricStatus(StrEnum):
    MEASURED = "MEASURED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class CapabilityState(StrEnum):
    DECLARED = "DECLARED"
    VERIFIED = "VERIFIED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    session_id: str
    trace_id: str | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.session_id, "session_id")
        if self.trace_id is not None:
            require_safe_id(self.trace_id, "trace_id")


@dataclass(frozen=True, slots=True)
class TurnRef:
    session_id: str
    turn_id: int

    def __post_init__(self) -> None:
        require_safe_id(self.session_id, "session_id")
        require_strict_int(self.turn_id, "turn_id", minimum=0)


@dataclass(frozen=True, slots=True)
class GenerationRef:
    session_id: str
    turn_id: int
    generation_id: int

    def __post_init__(self) -> None:
        require_safe_id(self.session_id, "session_id")
        require_strict_int(self.turn_id, "turn_id", minimum=0)
        require_strict_int(self.generation_id, "generation_id", minimum=0)

    @property
    def turn_ref(self) -> TurnRef:
        return TurnRef(self.session_id, self.turn_id)


@dataclass(frozen=True, slots=True)
class StreamRef:
    session_id: str
    stream_id: str
    direction: StreamDirection
    format_epoch: int = 0

    def __post_init__(self) -> None:
        require_safe_id(self.session_id, "session_id")
        require_safe_id(self.stream_id, "stream_id")
        if not isinstance(self.direction, StreamDirection):
            raise ValueError("direction must be StreamDirection")
        require_strict_int(self.format_epoch, "format_epoch", minimum=0)


@dataclass(frozen=True, slots=True)
class CancellationReference:
    generation_ref: GenerationRef
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.generation_ref, GenerationRef):
            raise TypeError("generation_ref must be GenerationRef")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be non-empty string")


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    code: str
    category: ErrorCategory
    retryable: Retryability = Retryability.UNKNOWN
    safe_message: str = ""
    field_name: str | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.code, "code")
        if not isinstance(self.category, ErrorCategory):
            raise ValueError("category must be ErrorCategory")
        if not isinstance(self.retryable, Retryability):
            raise ValueError("retryable must be Retryability")
        if not isinstance(self.safe_message, str):
            raise TypeError("safe_message must be str")


@dataclass(frozen=True, slots=True)
class MetricSample:
    name: str
    value: float | None
    unit: str
    observation_scope: str
    status: MetricStatus = MetricStatus.MEASURED
    reason: str | None = None
    source_ref: str | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.name, "name")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError("unit must be non-empty")
        if not isinstance(self.observation_scope, str) or not self.observation_scope.strip():
            raise ValueError("observation_scope must be non-empty")
        if not isinstance(self.status, MetricStatus):
            raise ValueError("status must be MetricStatus")
        if self.value is not None:
            require_finite(self.value, "value")
            if self.status != MetricStatus.MEASURED:
                raise ValueError("non-null value requires status=MEASURED")
        elif self.status == MetricStatus.MEASURED:
            raise ValueError("status=MEASURED requires finite numeric value")


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    name: str
    scope: str
    state: CapabilityState
    version: str | None = None
    evidence_ref: str | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.name, "name")
        if not isinstance(self.scope, str) or not self.scope.strip():
            raise ValueError("scope required")
        if not isinstance(self.state, CapabilityState):
            raise ValueError("state must be CapabilityState")


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    schema_version: str
    event_type: str
    session_id: str
    trace_id: str | None
    turn_id: int | None
    generation_id: int | None
    sequence: int
    monotonic_ns: int
    clock_domain: str
    producer: str
    utc_timestamp: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        ContractVersion.parse(self.schema_version)
        if not isinstance(self.event_type, str) or not self.event_type.strip():
            raise ValueError("event_type required")
        require_safe_id(self.session_id, "session_id")
        if self.trace_id is not None:
            require_safe_id(self.trace_id, "trace_id")
        if self.turn_id is not None:
            require_strict_int(self.turn_id, "turn_id", minimum=0)
        if self.generation_id is not None:
            require_strict_int(self.generation_id, "generation_id", minimum=0)
        require_strict_int(self.sequence, "sequence", minimum=0)
        require_strict_int(self.monotonic_ns, "monotonic_ns", minimum=0)
        if not isinstance(self.clock_domain, str) or not self.clock_domain.strip():
            raise ValueError("clock_domain required")
        if not isinstance(self.producer, str) or not self.producer.strip():
            raise ValueError("producer required")
        if self.utc_timestamp is not None:
            require_utc_iso(self.utc_timestamp, "utc_timestamp")
        object.__setattr__(self, "metadata", freeze_value(dict(self.metadata)))
