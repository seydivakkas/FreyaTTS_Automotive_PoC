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

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from backend.core.contracts.playback import ObservationScope
from backend.observability.evidence import EvidenceKind
from backend.observability.projection import contains_sentinel
from tests.harness.contracts import CaseResult, GateStatus, PrerequisiteStatus, TestRunManifest


@dataclass(frozen=True, slots=True)
class PrerequisiteValidationResult:
    package_id: str
    run_id: str | None
    status: PrerequisiteStatus
    missing_items: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class PIISecretScanner:
    """Rejects PII/secrets in serialized harness artifacts, logs, and manifests."""

    FORBIDDEN_LITERAL_KEYS: frozenset[str] = frozenset({
        "raw_transcript",
        "transcript",
        "phone",
        "owner_phone",
        "plate",
        "vin",
        "password",
        "admin_password",
        "ami_secret",
        "twilio_auth_token",
        "link_signing_key",
        "audio_archive_master_key",
        "whatsapp_webhook_token",
        "pbx_metadata_secret",
        "secret",
        "token",
        "raw_audio_b64",
    })

    @classmethod
    def scan_object(cls, obj: Any, *, path: str = "$") -> list[str]:
        findings: list[str] = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                k_low = str(k).lower()
                if k_low in cls.FORBIDDEN_LITERAL_KEYS and v not in (None, "", "[REDACTED]"):
                    findings.append(f"FORBIDDEN_KEY:{path}.{k}")
                findings.extend(cls.scan_object(v, path=f"{path}.{k}"))
        elif isinstance(obj, (list, tuple)):
            for idx, item in enumerate(obj):
                findings.extend(cls.scan_object(item, path=f"{path}[{idx}]"))
        elif isinstance(obj, str):
            # Exact SHA-256/git-SHA hex digests are cryptographic identifiers, not phone/plate strings.
            if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", obj):
                return findings
            if contains_sentinel(obj):
                findings.append(f"SENTINEL_PII_OR_SECRET:{path}")
        return findings


class EvidenceValidator:
    """Offline validator for prerequisites, hashes, scope provenance, and run manifests."""

    REQUIRED_M00_DOCS: tuple[str, ...] = (
        "BASELINE_MANIFEST.json",
        "SOURCE_SCOPE.json",
        "FEATURE_REGISTRY.json",
        "REGRESSION_MATRIX.csv",
        "API_INVENTORY.json",
        "UI_INVENTORY.json",
        "DATABASE_INVENTORY.json",
        "CONFIG_MODEL_INVENTORY.json",
        "PIPELINE_TRACE.md",
        "WORKFLOW_INVENTORY.json",
        "EXPERIMENT_INVENTORY.json",
        "TEST_INVENTORY.json",
        "BASELINE_TEST_RESULTS.json",
        "METRIC_BASELINE.json",
        "RISK_REGISTER.md",
        "INTEGRITY_AFTER.json",
        "ACCEPTANCE_MATRIX.json",
        "M01_HANDOFF.md",
        "M00_REPORT.md",
    )

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve(strict=True)

    def verify_m00_baseline(self, run_id: str | None) -> PrerequisiteValidationResult:
        if not run_id:
            return PrerequisiteValidationResult("M00", None, PrerequisiteStatus.MISSING, ("M00_RUN_ID_REQUIRED",))
        doc_dir = self.repo_root / "docs" / "freya2" / "baseline" / run_id
        ev_dir = self.repo_root / "evidence" / "m00" / run_id
        if not doc_dir.exists() or not ev_dir.exists():
            return PrerequisiteValidationResult("M00", run_id, PrerequisiteStatus.MISSING, ("M00_DIRS_MISSING",))

        missing = [f for f in self.REQUIRED_M00_DOCS if not (doc_dir / f).exists()]
        for ef in ("manifest.json", "artifact_hashes.json"):
            if not (ev_dir / ef).exists():
                missing.append(f"evidence:{ef}")
        if missing:
            return PrerequisiteValidationResult("M00", run_id, PrerequisiteStatus.MISSING, tuple(missing))

        acc = json.loads((doc_dir / "ACCEPTANCE_MATRIX.json").read_text(encoding="utf-8"))
        rec = acc.get("records", {})
        errors: list[str] = []
        if rec.get("overall") != "PASS" or rec.get("m01_ready") is not True:
            errors.append("M00_NOT_PASS_OR_M01_NOT_READY")
        gates = rec.get("gates", {})
        for g in ("G00_Integrity", "G01_Baseline", "G02_Scope", "G03_API_UI", "G04_Data_Business", "G05_F0_F6", "G06_Config_Models_Experiments", "G07_Tests_Metrics", "G08_Preservation_Registry", "G09_Handoff", "G10_Evidence_Privacy"):
            if gates.get(g) != "PASS":
                errors.append(f"M00_GATE_NOT_PASS:{g}")

        hashes = json.loads((ev_dir / "artifact_hashes.json").read_text(encoding="utf-8"))
        for rel_path, expected_sha in hashes.items():
            target = (self.repo_root / rel_path).resolve()
            if not target.is_relative_to(self.repo_root):
                errors.append(f"M00_PATH_ESCAPE:{rel_path}")
                continue
            if not target.exists():
                errors.append(f"M00_HASH_TARGET_MISSING:{rel_path}")
                continue
            actual_sha = sha256_file(target)
            if actual_sha != expected_sha:
                errors.append(f"M00_HASH_MISMATCH:{rel_path}")

        if errors:
            return PrerequisiteValidationResult("M00", run_id, PrerequisiteStatus.HOLD, errors=tuple(errors))
        return PrerequisiteValidationResult("M00", run_id, PrerequisiteStatus.ACCEPTED)

    def verify_package_acceptance_dir(
        self,
        package_id: str,
        package_doc_root: Path,
        *,
        explicit_run_id: str | None = None,
        required_gates: Iterable[str] = (),
        ready_flag: str | None = None,
    ) -> PrerequisiteValidationResult:
        if not package_doc_root.exists():
            return PrerequisiteValidationResult(package_id, explicit_run_id, PrerequisiteStatus.MISSING, (f"{package_id}_DOC_ROOT_MISSING",))

        candidates = sorted(p.name for p in package_doc_root.iterdir() if p.is_dir())
        if explicit_run_id is None:
            if len(candidates) == 0:
                return PrerequisiteValidationResult(package_id, None, PrerequisiteStatus.MISSING, (f"{package_id}_NO_RUNS",))
            if len(candidates) > 1:
                return PrerequisiteValidationResult(
                    package_id,
                    None,
                    PrerequisiteStatus.CONFLICTING,
                    errors=(f"MULTIPLE_CANDIDATE_RUNS:{','.join(candidates)}",),
                )
            run_id = candidates[0]
        else:
            run_id = explicit_run_id

        run_dir = package_doc_root / run_id
        acc_file = run_dir / "ACCEPTANCE_MATRIX.json"
        if not acc_file.exists():
            return PrerequisiteValidationResult(package_id, run_id, PrerequisiteStatus.MISSING, ("ACCEPTANCE_MATRIX.json",))

        data = json.loads(acc_file.read_text(encoding="utf-8"))
        gates = data.get("gates", data.get("records", {}).get("gates", {}))
        overall = data.get("overall", data.get("records", {}).get("overall"))
        errors: list[str] = []
        if overall != "PASS":
            errors.append(f"{package_id}_OVERALL_NOT_PASS:{overall}")
        for g in required_gates:
            if gates.get(g) != "PASS":
                errors.append(f"{package_id}_MISSING_OR_FAILED_GATE:{g}")
        if ready_flag is not None:
            flag_val = data.get(ready_flag, data.get("records", {}).get(ready_flag))
            if flag_val is not True:
                errors.append(f"{package_id}_READY_FLAG_FALSE:{ready_flag}")
        if errors:
            return PrerequisiteValidationResult(package_id, run_id, PrerequisiteStatus.HOLD, errors=tuple(errors))
        return PrerequisiteValidationResult(package_id, run_id, PrerequisiteStatus.ACCEPTED)

    @staticmethod
    def validate_case_provenance(case: CaseResult) -> list[str]:
        errors: list[str] = []
        if case.source_class in {
            EvidenceKind.SYNTHETIC_FIXTURE,
            EvidenceKind.MOCK_RUNTIME,
            EvidenceKind.STATIC_CODE,
        } and case.observation_scope in {ObservationScope.ENDPOINT, ObservationScope.PBX}:
            errors.append(f"PROVENANCE_SCOPE_MISMATCH:{case.case_id}")
        if case.status == GateStatus.PASS and not case.executed:
            errors.append(f"PASS_WITHOUT_EXECUTION:{case.case_id}")
        if case.status == GateStatus.PASS and not case.collected_node_ids:
            errors.append(f"PASS_WITHOUT_NODE_IDS:{case.case_id}")
        return errors

    @staticmethod
    def validate_run_manifest(manifest: TestRunManifest, *, expected_snapshot: str) -> list[str]:
        errors: list[str] = []
        if manifest.source_scope_hash != expected_snapshot:
            errors.append(f"STALE_SNAPSHOT:{manifest.source_scope_hash}!={expected_snapshot}")
        if not manifest.selected_cases:
            errors.append("EMPTY_SELECTION")
        pii = PIISecretScanner.scan_object({
            "run_id": manifest.run_id,
            "approved_changes": list(manifest.approved_changes),
            "command": list(manifest.command),
            "evidence_refs": list(manifest.evidence_refs),
        })
        errors.extend(pii)
        return errors

    def verify_evidence_bundle(self, evidence_dir: Path) -> list[str]:
        errors: list[str] = []
        manifest_path = evidence_dir / "manifest.json"
        hashes_path = evidence_dir / "artifact_hashes.json"
        if not manifest_path.exists():
            errors.append("MISSING_EVIDENCE_MANIFEST")
        if not hashes_path.exists():
            errors.append("MISSING_ARTIFACT_HASHES")
        if errors:
            return errors
        hashes = json.loads(hashes_path.read_text(encoding="utf-8"))
        for rel_path, expected_sha in hashes.items():
            target = (self.repo_root / rel_path).resolve()
            if not target.is_relative_to(self.repo_root):
                errors.append(f"EVIDENCE_PATH_ESCAPE:{rel_path}")
                continue
            if not target.exists():
                errors.append(f"MISSING_HASHED_ARTIFACT:{rel_path}")
                continue
            if sha256_file(target) != expected_sha:
                errors.append(f"ARTIFACT_SHA_MISMATCH:{rel_path}")
        return errors

    def write_noncircular_hashes(self, paths: Iterable[Path], hashes_out_path: Path) -> dict[str, str]:
        """Compute deterministic relative-path SHA-256 map excluding hashes_out_path itself."""
        resolved_out = hashes_out_path.resolve()
        mapping: dict[str, str] = {}
        for p in sorted({p.resolve() for p in paths}):
            if p == resolved_out or not p.is_file():
                continue
            rel = p.relative_to(self.repo_root).as_posix()
            mapping[rel] = sha256_file(p)
        hashes_out_path.parent.mkdir(parents=True, exist_ok=True)
        hashes_out_path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return mapping
