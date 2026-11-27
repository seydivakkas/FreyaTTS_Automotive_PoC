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
from types import MappingProxyType
from typing import Any, Mapping

from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION, ContractVersion
from backend.core.contracts.playback import ObservationScope
from backend.core.contracts.validation import freeze_value, require_finite, require_safe_id, require_strict_int, require_utc_iso
from backend.observability.evidence import EvidenceKind


class ExecutionTier(StrEnum):
    T0_UNIT_CONTRACT = "T0"
    T1_REPLAY_MOCK_DB = "T1"
    T2_REAL_MODEL_BENCHMARK = "T2"
    T3_SYNTHETIC_E2E = "T3"
    T4_FAILURE_LOAD = "T4"
    T5_HUMAN_SIP = "T5"


class RunProfile(StrEnum):
    QUICK = "quick"
    PACKAGE = "package"
    CORE_INTEGRATION = "core_integration"
    COMPATIBILITY = "compatibility"
    SYNTHETIC_FUTURE = "synthetic_future"


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    HOLD = "HOLD"
    NOT_RUN = "NOT_RUN"


class PrerequisiteStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    MISSING = "MISSING"
    HOLD = "HOLD"
    CONFLICTING = "CONFLICTING"
    DRIFT_BLOCKED = "DRIFT_BLOCKED"


@dataclass(frozen=True, slots=True)
class TestCaseSpec:
    __test__ = False
    case_id: str
    owner_package: str
    suite: str
    mandatory: bool
    runner_selector: str
    scenario: str
    expected_assertions: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    fixture_refs: tuple[str, ...] = ()
    feature_ids: tuple[str, ...] = ()
    risk_ids: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    allowed_side_effects: tuple[str, ...] = ("TEMP_FS", "TEMP_DB")
    execution_scope: ExecutionTier = ExecutionTier.T0_UNIT_CONTRACT
    timeout_sec: float = 15.0
    seed: int = 0
    cleanup_assertions: tuple[str, ...] = ("NO_SURVIVING_TASKS", "NO_PRODUCTION_TOUCH")
    evidence_requirements: tuple[str, ...] = ("PYTEST_EXIT", "CASE_STATUS")
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        ContractVersion.parse(self.schema_version)
        require_safe_id(self.case_id, "case_id")
        if not self.owner_package.strip():
            raise ValueError("owner_package required")
        if not self.suite.strip():
            raise ValueError("suite required")
        if not self.runner_selector.strip():
            raise ValueError("runner_selector required")
        require_finite(self.timeout_sec, "timeout_sec", minimum=0.01, maximum=600.0)
        require_strict_int(self.seed, "seed", minimum=0)
        for attr in (
            "expected_assertions",
            "dependencies",
            "fixture_refs",
            "feature_ids",
            "risk_ids",
            "preconditions",
            "allowed_side_effects",
            "cleanup_assertions",
            "evidence_requirements",
        ):
            object.__setattr__(self, attr, freeze_value(tuple(getattr(self, attr))))


@dataclass(frozen=True, slots=True)
class FixtureManifest:
    fixture_id: str
    revision: str
    source_class: EvidenceKind
    generator_version: str
    seed: int
    relative_files: tuple[str, ...]
    sha256: Mapping[str, str]
    privacy_class: str = "SYNTHETIC_NO_PII"
    split: str = "calibration"
    sample_rate_hz: int | None = None
    channels: int | None = None
    encoding: str | None = None
    sample_count: int | None = None
    labels: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    provenance: str = "tests.harness.synthetic"
    license_tag: str = "ALL_RIGHTS_RESERVED_TEST_ONLY"
    limitations: tuple[str, ...] = ()
    duplicate_group_id: str | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.fixture_id, "fixture_id")
        if not self.revision.strip():
            raise ValueError("revision required")
        if not isinstance(self.source_class, EvidenceKind):
            raise ValueError("source_class must be EvidenceKind")
        if self.source_class == EvidenceKind.REAL_ENDPOINT_MEASURED:
            raise ValueError("Test fixture manifest cannot claim REAL_ENDPOINT_MEASURED")
        require_strict_int(self.seed, "seed", minimum=0)
        if self.split not in {"calibration", "held_out", "regression", "unit"}:
            raise ValueError(f"Unsupported fixture split: {self.split}")
        if self.sample_rate_hz is not None:
            require_strict_int(self.sample_rate_hz, "sample_rate_hz", minimum=1)
        if self.channels is not None:
            require_strict_int(self.channels, "channels", minimum=1, maximum=8)
        if self.sample_count is not None:
            require_strict_int(self.sample_count, "sample_count", minimum=0)
        object.__setattr__(self, "relative_files", freeze_value(tuple(self.relative_files)))
        object.__setattr__(self, "sha256", freeze_value(dict(self.sha256)))
        object.__setattr__(self, "labels", freeze_value(dict(self.labels)))
        object.__setattr__(self, "limitations", freeze_value(tuple(self.limitations)))


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    collected_node_ids: tuple[str, ...]
    executed: bool
    status: GateStatus
    reason_code: str
    source_class: EvidenceKind
    observation_scope: ObservationScope
    runner_exit_code: int | None = None
    expected_summary: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    observed_summary: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    evidence_refs: tuple[str, ...] = ()
    repetition: int = 1
    seed: int = 0
    cleanup_ok: bool = True
    blockers: tuple[str, ...] = ()
    elapsed_ms: float | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.case_id, "case_id")
        if not isinstance(self.status, GateStatus):
            raise ValueError("status must be GateStatus")
        if not isinstance(self.source_class, EvidenceKind):
            raise ValueError("source_class must be EvidenceKind")
        if not isinstance(self.observation_scope, ObservationScope):
            raise ValueError("observation_scope must be ObservationScope")
        if self.source_class in {
            EvidenceKind.SYNTHETIC_FIXTURE,
            EvidenceKind.MOCK_RUNTIME,
            EvidenceKind.STATIC_CODE,
        } and self.observation_scope == ObservationScope.ENDPOINT:
            raise ValueError("Synthetic/mock/static case cannot claim ENDPOINT observation_scope")
        if self.elapsed_ms is not None:
            require_finite(self.elapsed_ms, "elapsed_ms", minimum=0.0)
        require_strict_int(self.repetition, "repetition", minimum=1)
        require_strict_int(self.seed, "seed", minimum=0)
        object.__setattr__(self, "collected_node_ids", freeze_value(tuple(self.collected_node_ids)))
        object.__setattr__(self, "expected_summary", freeze_value(dict(self.expected_summary)))
        object.__setattr__(self, "observed_summary", freeze_value(dict(self.observed_summary)))
        object.__setattr__(self, "evidence_refs", freeze_value(tuple(self.evidence_refs)))
        object.__setattr__(self, "blockers", freeze_value(tuple(self.blockers)))


@dataclass(frozen=True, slots=True)
class TestRunManifest:
    __test__ = False
    run_id: str
    suite: str
    profile: RunProfile
    baseline_run_id: str
    dependency_run_ids: Mapping[str, str]
    source_scope_hash: str
    approved_changes: tuple[str, ...]
    command: tuple[str, ...]
    tool_versions: Mapping[str, str]
    fixture_revision: str
    clock_domain: str
    start_utc: str
    end_utc: str
    elapsed_ms: float | None
    isolation_mode: str
    selected_cases: tuple[str, ...]
    outcome_counts: Mapping[str, int]
    completeness: float
    evidence_refs: tuple[str, ...]
    schema_version: str = CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        ContractVersion.parse(self.schema_version)
        require_safe_id(self.run_id, "run_id")
        require_safe_id(self.baseline_run_id, "baseline_run_id")
        if not isinstance(self.profile, RunProfile):
            raise ValueError("profile must be RunProfile")
        require_utc_iso(self.start_utc, "start_utc")
        require_utc_iso(self.end_utc, "end_utc")
        if self.elapsed_ms is not None:
            require_finite(self.elapsed_ms, "elapsed_ms", minimum=0.0)
        require_finite(self.completeness, "completeness", minimum=0.0, maximum=1.0)
        object.__setattr__(self, "dependency_run_ids", freeze_value(dict(self.dependency_run_ids)))
        object.__setattr__(self, "approved_changes", freeze_value(tuple(self.approved_changes)))
        object.__setattr__(self, "command", freeze_value(tuple(self.command)))
        object.__setattr__(self, "tool_versions", freeze_value(dict(self.tool_versions)))
        object.__setattr__(self, "selected_cases", freeze_value(tuple(self.selected_cases)))
        object.__setattr__(self, "outcome_counts", freeze_value(dict(self.outcome_counts)))
        object.__setattr__(self, "evidence_refs", freeze_value(tuple(self.evidence_refs)))


@dataclass(frozen=True, slots=True)
class GateRecord:
    gate_id: str
    mandatory: bool
    status: GateStatus
    reason: str
    evidence_refs: tuple[str, ...]
    blocked_consumers: tuple[str, ...] = ()
    reviewer: str = "harness-verifier"
    review_status: str = "VERIFIED"

    def __post_init__(self) -> None:
        require_safe_id(self.gate_id, "gate_id")
        if not isinstance(self.status, GateStatus):
            raise ValueError("status must be GateStatus")
        if not self.reason.strip():
            raise ValueError("reason required")
        object.__setattr__(self, "evidence_refs", freeze_value(tuple(self.evidence_refs)))
        object.__setattr__(self, "blocked_consumers", freeze_value(tuple(self.blocked_consumers)))
