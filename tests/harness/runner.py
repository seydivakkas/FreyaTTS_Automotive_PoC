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

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from backend.core.contracts.playback import ObservationScope
from backend.observability.evidence import EvidenceKind
from tests.harness.contracts import GateStatus, RunProfile

_SHELL_METACHAR_RE = re.compile(r"[;&|`$><\r\n]")
_SAFE_SELECTOR_RE = re.compile(r"^[A-Za-z0-9_./:-]+$")


@dataclass(frozen=True, slots=True)
class PackageSuiteRegistration:
    package_id: str
    family_prefix: str
    test_path: str
    planned_ids: tuple[str, ...]
    mandatory: bool = True


def _id_range(prefix: str, start: int, end: int) -> tuple[str, ...]:
    return tuple(f"{prefix}{i:02d}" for i in range(start, end + 1))


FOUNDATION_SUITE_REGISTRATIONS: tuple[PackageSuiteRegistration, ...] = (
    PackageSuiteRegistration("M01", "CT", "tests/contracts/test_m01_contracts.py", _id_range("CT", 1, 36)),
    PackageSuiteRegistration("M02", "RT", "tests/runtime/test_m02_runtime.py", _id_range("RT", 1, 48)),
    PackageSuiteRegistration("M03", "CR", "tests/configuration/test_m03_config_registry.py", _id_range("CR", 1, 48)),
    PackageSuiteRegistration("M04", "OB", "tests/observability/test_m04_observability.py", _id_range("OB", 1, 56)),
    PackageSuiteRegistration("M05", "LX", "tests/lexicon/test_m05_lexicon.py", _id_range("LX", 1, 56)),
    PackageSuiteRegistration("M06", "GPU", "tests/runtime_resources/test_m06_scheduler.py", _id_range("GPU", 1, 64)),
    PackageSuiteRegistration("M07", "SEC", "tests/security/test_m07_security.py", _id_range("SEC", 1, 72)),
    PackageSuiteRegistration("M08", "TH", "tests/harness_tests/test_m08_harness.py", _id_range("TH", 1, 80)),
)


def validate_no_duplicate_test_ids(registrations: Iterable[PackageSuiteRegistration] = FOUNDATION_SUITE_REGISTRATIONS) -> list[str]:
    seen: set[str] = set()
    dups: list[str] = []
    for reg in registrations:
        for tid in reg.planned_ids:
            if tid in seen:
                dups.append(tid)
            seen.add(tid)
    return dups


ALLOWLISTED_PROFILE_TARGETS: dict[RunProfile, tuple[str, ...]] = {
    RunProfile.QUICK: (
        "tests/contracts/test_m01_contracts.py",
        "tests/harness_tests/test_m08_harness.py",
    ),
    RunProfile.PACKAGE: tuple(r.test_path for r in FOUNDATION_SUITE_REGISTRATIONS),
    RunProfile.CORE_INTEGRATION: (
        *(r.test_path for r in FOUNDATION_SUITE_REGISTRATIONS),
        "tests/integration/test_core_gate.py",
    ),
    RunProfile.COMPATIBILITY: (
        "tests/harness_tests/test_m08_harness.py",
        "tests/test_core.py",
    ),
    RunProfile.SYNTHETIC_FUTURE: (),  # Manifest-only in M08; no real-model execution authorized.
}


@dataclass(frozen=True, slots=True)
class PytestSummaryCounts:
    collected: int
    passed: int
    failed: int
    skipped: int
    xfailed: int
    xpassed: int
    errors: int


@dataclass(frozen=True, slots=True)
class BoundedRunResult:
    profile: RunProfile
    command: tuple[str, ...]
    exit_code: int
    status: GateStatus
    reason_code: str
    counts: PytestSummaryCounts
    elapsed_ms: float
    stdout: str
    stderr: str
    source_class: EvidenceKind = EvidenceKind.MOCK_RUNTIME
    observation_scope: ObservationScope = ObservationScope.SERVER
    timed_out: bool = False


class AllowlistViolationError(ValueError):
    """Raised when a profile or test selector is outside the safe allowlist."""


def parse_pytest_summary(output: str, *, collected_count: int = 0) -> PytestSummaryCounts:
    def _extract(label: str) -> int:
        m = re.search(rf"\b(\d+)\s+{label}\b", output)
        return int(m.group(1)) if m else 0

    passed = _extract("passed")
    failed = _extract("failed")
    skipped = _extract("skipped")
    xfailed = _extract("xfailed")
    xpassed = _extract("xpassed")
    errors = _extract("error") + _extract("errors")
    total_executed = passed + failed + skipped + xfailed + xpassed + errors
    collected = max(collected_count, total_executed)
    return PytestSummaryCounts(
        collected=collected,
        passed=passed,
        failed=failed,
        skipped=skipped,
        xfailed=xfailed,
        xpassed=xpassed,
        errors=errors,
    )


def reconcile_run_status(
    *,
    exit_code: int,
    counts: PytestSummaryCounts,
    expected_min_collected: int = 1,
    timed_out: bool = False,
) -> tuple[GateStatus, str]:
    if timed_out:
        return GateStatus.FAIL, "RUNNER_TIMEOUT_EXCEEDED"
    if counts.collected == 0 or counts.collected < expected_min_collected:
        return GateStatus.HOLD, "EMPTY_OR_UNDERCOLLECTED_SELECTION"
    if counts.failed > 0 or counts.errors > 0 or exit_code != 0:
        return GateStatus.FAIL, "PYTEST_FAIL_OR_ERROR"
    if counts.skipped > 0:
        return GateStatus.HOLD, "MANDATORY_CASES_SKIPPED"
    if counts.xpassed > 0:
        return GateStatus.HOLD, "UNEXPECTED_XPASS_REVIEW_REQUIRED"
    if counts.passed != counts.collected:
        return GateStatus.HOLD, "COUNT_MISMATCH_RECONCILE_REQUIRED"
    return GateStatus.PASS, "ALL_COLLECTED_PASSED"


class HarnessRunner:
    """Safe, shell-free pytest runner with strict allowlisting and bounded timeout."""

    def __init__(self, repo_root: Path, *, python_exe: Path | None = None) -> None:
        self.repo_root = repo_root.resolve(strict=True)
        default_py = self.repo_root / ".venv" / "Scripts" / "python.exe"
        self.python_exe = python_exe if python_exe is not None else (default_py if default_py.exists() else Path(sys.executable))

    def validate_selectors(self, profile: RunProfile, selectors: Iterable[str]) -> tuple[str, ...]:
        if not isinstance(profile, RunProfile):
            raise AllowlistViolationError(f"Unknown runner profile: {profile!r}")
        if profile == RunProfile.SYNTHETIC_FUTURE:
            raise AllowlistViolationError("SYNTHETIC_FUTURE profile is manifest-only in M08")
        allowed_roots = ALLOWLISTED_PROFILE_TARGETS[profile]
        cleaned: list[str] = []
        for sel in selectors:
            if not isinstance(sel, str) or not sel.strip():
                raise AllowlistViolationError("Empty selector rejected")
            if _SHELL_METACHAR_RE.search(sel) or not _SAFE_SELECTOR_RE.match(sel):
                raise AllowlistViolationError(f"Unsafe characters in selector: {sel!r}")
            node_file = sel.split("::", 1)[0]
            if node_file not in allowed_roots:
                raise AllowlistViolationError(f"Selector {sel!r} not in allowlist for profile {profile.value}")
            cleaned.append(sel)
        if not cleaned:
            raise AllowlistViolationError("Selection cannot be empty")
        return tuple(cleaned)

    def collect_only(
        self,
        profile: RunProfile,
        selectors: Iterable[str],
        *,
        basetemp: Path,
        timeout_sec: float = 30.0,
    ) -> list[str]:
        valid = self.validate_selectors(profile, selectors)
        argv = [
            str(self.python_exe),
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            f"--basetemp={basetemp}",
            *valid,
        ]
        proc = subprocess.run(
            argv,
            cwd=str(self.repo_root),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            shell=False,
        )
        node_ids: list[str] = []
        for line in proc.stdout.splitlines():
            s = line.strip()
            if "::" in s and not s.startswith("<"):
                node_ids.append(s)
        return node_ids

    def run_allowlisted(
        self,
        profile: RunProfile,
        selectors: Iterable[str],
        *,
        basetemp: Path,
        timeout_sec: float = 120.0,
        expected_min_collected: int = 1,
        extra_env: dict[str, str] | None = None,
    ) -> BoundedRunResult:
        valid = self.validate_selectors(profile, selectors)
        argv = [
            str(self.python_exe),
            "-m",
            "pytest",
            "-q",
            f"--basetemp={basetemp}",
            *valid,
        ]
        env = dict(os.environ)
        env["AUTO_LOAD_MODELS"] = "0"
        if extra_env:
            env.update(extra_env)

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                shell=False,
                env=env,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            counts = parse_pytest_summary(proc.stdout + "\n" + proc.stderr)
            status, reason = reconcile_run_status(
                exit_code=proc.returncode,
                counts=counts,
                expected_min_collected=expected_min_collected,
                timed_out=False,
            )
            return BoundedRunResult(
                profile=profile,
                command=tuple(argv),
                exit_code=proc.returncode,
                status=status,
                reason_code=reason,
                counts=counts,
                elapsed_ms=elapsed_ms,
                stdout=proc.stdout,
                stderr=proc.stderr,
                timed_out=False,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            out = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "")
            err = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "")
            counts = parse_pytest_summary(out + "\n" + err)
            return BoundedRunResult(
                profile=profile,
                command=tuple(argv),
                exit_code=124,
                status=GateStatus.FAIL,
                reason_code="RUNNER_TIMEOUT_EXCEEDED",
                counts=counts,
                elapsed_ms=elapsed_ms,
                stdout=out,
                stderr=err,
                timed_out=True,
            )
