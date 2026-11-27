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

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from tests.harness.contracts import GateStatus


@dataclass(frozen=True, slots=True)
class FeatureRegressionRow:
    feature_id: str
    name: str
    domain: str
    target_owner: str
    implementation_state: str
    baseline_status: str
    existing_test_ids: tuple[str, ...]
    executable_tests_found: tuple[str, ...]
    behavioral_verified: bool
    disposition: str
    blocking: bool


@dataclass(frozen=True, slots=True)
class FeatureRegressionSummary:
    total_features: int
    mapped_features: int
    executable_tests_linked: int
    behavioral_verified_count: int
    pending_or_uncovered_count: int
    known_baseline_fail_count: int
    new_regression_count: int
    duplicate_feature_ids: tuple[str, ...]
    missing_from_regression_matrix: tuple[str, ...]
    rows: tuple[FeatureRegressionRow, ...]
    status: GateStatus


class FeatureRegressionMapper:
    """Joins M00 FEATURE_REGISTRY.json and REGRESSION_MATRIX.csv without dropping IDs."""

    def __init__(self, repo_root: Path, baseline_dir: Path) -> None:
        self.repo_root = repo_root.resolve(strict=True)
        self.baseline_dir = baseline_dir.resolve(strict=True)

    def build_matrix(
        self,
        *,
        observed_test_outcomes: dict[str, GateStatus] | None = None,
    ) -> FeatureRegressionSummary:
        reg_data = json.loads((self.baseline_dir / "FEATURE_REGISTRY.json").read_text(encoding="utf-8"))
        features = reg_data.get("records", [])

        seen_ids: set[str] = set()
        dup_ids: list[str] = []
        for f in features:
            fid = f["feature_id"]
            if fid in seen_ids:
                dup_ids.append(fid)
            seen_ids.add(fid)

        csv_rows: dict[str, dict[str, str]] = {}
        with (self.baseline_dir / "REGRESSION_MATRIX.csv").open("r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                csv_rows[row["feature_id"]] = row

        missing_in_csv = sorted(fid for fid in seen_ids if fid not in csv_rows)
        extra_in_csv = sorted(fid for fid in csv_rows if fid not in seen_ids)

        outcomes = observed_test_outcomes or {}
        joined_rows: list[FeatureRegressionRow] = []
        mapped_count = 0
        exe_linked = 0
        beh_verified = 0
        pending_count = 0
        known_fail = 0
        new_reg = 0

        for f in features:
            fid = f["feature_id"]
            csv_row = csv_rows.get(fid, {})
            baseline_status = csv_row.get("baseline_status", f.get("verification_status", "UNKNOWN"))
            test_refs = tuple(f.get("existing_test_ids", ()))
            found_tests = tuple(t for t in test_refs if (self.repo_root / t).exists())
            if fid in csv_rows:
                mapped_count += 1
            if found_tests:
                exe_linked += 1

            # Determine observed status if tests were run in this snapshot
            obs_statuses = [outcomes[t] for t in found_tests if t in outcomes]
            if not found_tests:
                disposition = "COVERAGE_GAP_NO_EXECUTABLE_TEST"
                is_beh_ok = False
                blocking = True
                pending_count += 1
            elif baseline_status == "FAIL":
                # Unchanged historical baseline defect must remain visible as FAIL, never relabeled PASS.
                known_fail += 1
                if any(s == GateStatus.FAIL for s in obs_statuses):
                    disposition = "KNOWN_BASELINE_FAILURE_UNCHANGED"
                    is_beh_ok = False
                    blocking = False
                elif obs_statuses:
                    disposition = "KNOWN_BASELINE_FAILURE_REVIEW_REQUIRED"
                    is_beh_ok = False
                    blocking = False
                else:
                    disposition = "KNOWN_BASELINE_FAILURE_NOT_REEXECUTED"
                    is_beh_ok = False
                    blocking = False
            elif any(s == GateStatus.FAIL for s in obs_statuses):
                new_reg += 1
                disposition = "NEW_REGRESSION_BLOCKING"
                is_beh_ok = False
                blocking = True
            elif obs_statuses and all(s == GateStatus.PASS for s in obs_statuses):
                beh_verified += 1
                disposition = "BEHAVIOR_VERIFIED_PASS"
                is_beh_ok = True
                blocking = False
            else:
                pending_count += 1
                disposition = "MAPPED_STRUCTURAL_PENDING_EXECUTION"
                is_beh_ok = False
                blocking = False

            joined_rows.append(
                FeatureRegressionRow(
                    feature_id=fid,
                    name=f["name"],
                    domain=f["domain"],
                    target_owner=f["target_owner"],
                    implementation_state=f["implementation_state"],
                    baseline_status=baseline_status,
                    existing_test_ids=test_refs,
                    executable_tests_found=found_tests,
                    behavioral_verified=is_beh_ok,
                    disposition=disposition,
                    blocking=blocking,
                )
            )

        if dup_ids or missing_in_csv or extra_in_csv or new_reg > 0 or any(r.blocking for r in joined_rows):
            overall = GateStatus.FAIL
        else:
            overall = GateStatus.PASS

        return FeatureRegressionSummary(
            total_features=len(features),
            mapped_features=mapped_count,
            executable_tests_linked=exe_linked,
            behavioral_verified_count=beh_verified,
            pending_or_uncovered_count=pending_count,
            known_baseline_fail_count=known_fail,
            new_regression_count=new_reg,
            duplicate_feature_ids=tuple(dup_ids),
            missing_from_regression_matrix=tuple(missing_in_csv + extra_in_csv),
            rows=tuple(joined_rows),
            status=overall,
        )
