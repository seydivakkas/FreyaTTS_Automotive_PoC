"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from backend.core.contracts.common import CapabilityDescriptor, ErrorInfo, MetricSample
from backend.core.contracts.validation import freeze_value, require_safe_id, require_strict_int


class ModelKind(StrEnum):
    TTS = "TTS"
    STT = "STT"
    VAD = "VAD"
    LLM = "LLM"
    SUPERVISOR = "SUPERVISOR"


class ArtifactStatus(StrEnum):
    VERIFIED = "VERIFIED"
    MISSING = "MISSING"
    HASH_MISMATCH = "HASH_MISMATCH"
    UNAPPROVED = "UNAPPROVED"
    PATH_REJECTED = "PATH_REJECTED"
    NOT_CHECKED = "NOT_CHECKED"


class ProfileTier(StrEnum):
    BASELINE = "BASELINE"
    EXPERIMENTAL = "EXPERIMENTAL"


class PreflightState(StrEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class ModelArtifactSpec:
    """Immutable specification for a local model artifact verified before loading."""

    model_id: str
    kind: ModelKind
    version: str
    relative_path: str
    expected_sha256: str | None = None
    required: bool = True
    device_preference: str = "cpu"
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        require_safe_id(self.model_id, "model_id")
        if not isinstance(self.kind, ModelKind):
            raise ValueError("kind must be ModelKind")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version must be non-empty")
        if not isinstance(self.relative_path, str) or not self.relative_path.strip():
            raise ValueError("relative_path must be non-empty")
        if self.expected_sha256 is not None:
            normalized = self.expected_sha256.strip().lower()
            if normalized:
                if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
                    raise ValueError("expected_sha256 must be a 64-char hex SHA-256 digest")
                object.__setattr__(self, "expected_sha256", normalized)
            else:
                object.__setattr__(self, "expected_sha256", None)
        object.__setattr__(self, "metadata", freeze_value(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ArtifactVerificationResult:
    """Outcome of read-only artifact path and SHA-256 verification."""

    model_id: str
    status: ArtifactStatus
    resolved_path: str | None = None
    actual_sha256: str | None = None
    expected_sha256: str | None = None
    size_bytes: int | None = None
    error: ErrorInfo | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.model_id, "model_id")
        if not isinstance(self.status, ArtifactStatus):
            raise ValueError("status must be ArtifactStatus")
        if self.size_bytes is not None:
            require_strict_int(self.size_bytes, "size_bytes", minimum=0)

    @property
    def is_valid(self) -> bool:
        return self.status == ArtifactStatus.VERIFIED


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    """Immutable voice synthesis profile descriptor."""

    profile_id: str
    speaker: str
    seed: int
    tier: ProfileTier
    display_name: str
    tone: str
    language: str = "tr"
    sample_rate_hz: int = 48000
    ode_steps: int = 32
    enabled_by_default: bool = False
    flag_name: str | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.profile_id, "profile_id")
        require_safe_id(self.speaker, "speaker")
        require_strict_int(self.seed, "seed", minimum=0, maximum=2**31 - 1)
        if not isinstance(self.tier, ProfileTier):
            raise ValueError("tier must be ProfileTier")
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError("display_name required")
        if not isinstance(self.tone, str) or not self.tone.strip():
            raise ValueError("tone required")
        require_strict_int(self.sample_rate_hz, "sample_rate_hz", minimum=8000, maximum=192000)
        require_strict_int(self.ode_steps, "ode_steps", minimum=1, maximum=256)
        if self.flag_name is not None:
            require_safe_id(self.flag_name, "flag_name")


@dataclass(frozen=True, slots=True)
class ModelDescriptor:
    """Immutable registry entry for a passive ML/runtime model dependency."""

    model_id: str
    kind: ModelKind
    model_revision: str
    version: str
    device: str
    artifact: ModelArtifactSpec | None = None
    external_ref: str | None = None
    required: bool = True
    capability: CapabilityDescriptor | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.model_id, "model_id")
        if not isinstance(self.kind, ModelKind):
            raise ValueError("kind must be ModelKind")
        if not isinstance(self.model_revision, str) or not self.model_revision.strip():
            raise ValueError("model_revision required")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version required")
        if not isinstance(self.device, str) or not self.device.strip():
            raise ValueError("device required")


@dataclass(frozen=True, slots=True)
class PreflightCheckItem:
    """Result of a single read-only offline preflight check."""

    target_id: str
    kind: ModelKind
    state: PreflightState
    artifact_status: ArtifactStatus
    reason: str
    metrics: tuple[MetricSample, ...] = ()

    def __post_init__(self) -> None:
        require_safe_id(self.target_id, "target_id")
        if not isinstance(self.kind, ModelKind):
            raise ValueError("kind must be ModelKind")
        if not isinstance(self.state, PreflightState):
            raise ValueError("state must be PreflightState")
        if not isinstance(self.artifact_status, ArtifactStatus):
            raise ValueError("artifact_status must be ArtifactStatus")
        object.__setattr__(self, "metrics", tuple(self.metrics))


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """Aggregate read-only offline preflight report; weights_loaded is always False."""

    overall_state: PreflightState
    config_revision: str
    model_registry_revision: str
    items: tuple[PreflightCheckItem, ...]
    checked_offline: bool = True
    weights_loaded: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.overall_state, PreflightState):
            raise ValueError("overall_state must be PreflightState")
        if self.weights_loaded:
            raise ValueError("offline_preflight must never load weights")
        object.__setattr__(self, "items", tuple(self.items))
