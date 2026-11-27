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

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

from backend.core.configuration.setting_catalog import SETTING_CATALOG
from backend.core.model_registry.voice_profiles import (
    DEFAULT_VOICE_PROFILE_REGISTRY,
    EXPERIMENTAL_VOICE_SEEDS,
    LEYLA_BASELINE_SEED,
)
from tests.harness.contracts import GateStatus


@dataclass(frozen=True, slots=True)
class CompatibilityCheckReport:
    domain: str
    baseline_count: int
    matched_count: int
    drift_items: tuple[str, ...]
    status: GateStatus
    observation_scope: str
    limitations: tuple[str, ...] = ()


def _collect_ast_routes(py_files: list[Path]) -> set[tuple[str, str]]:
    """Statically inspect FastAPI route decorators without importing backend.main/routers."""
    routes: set[tuple[str, str]] = set()
    http_methods = {"get", "post", "put", "delete", "patch", "options", "head", "websocket", "api_route"}
    for path in py_files:
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
        prefix = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "router" and isinstance(node.value, ast.Call):
                        for kw in node.value.keywords:
                            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                                prefix = kw.value.value
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                        method = dec.func.attr.lower()
                        if method in http_methods and dec.args:
                            arg0 = dec.args[0]
                            if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                                p = arg0.value
                                routes.add((method.upper(), p))
                                if prefix and not p.startswith(prefix):
                                    routes.add((method.upper(), f"{prefix}{p}"))
    return routes


def _collect_ast_tablenames(db_py: Path) -> set[str]:
    tree = ast.parse(db_py.read_text(encoding="utf-8"), filename=str(db_py))
    tables: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "__tablename__" and isinstance(node.value, ast.Constant):
                    if isinstance(node.value.value, str):
                        tables.add(node.value.value)
    return tables


class CompatibilityChecker:
    """Offline static + passive-registry compatibility checker against M00 inventories."""

    def __init__(self, repo_root: Path, baseline_dir: Path) -> None:
        self.repo_root = repo_root.resolve(strict=True)
        self.baseline_dir = baseline_dir.resolve(strict=True)

    def check_api_compatibility(self) -> CompatibilityCheckReport:
        inv = json.loads((self.baseline_dir / "API_INVENTORY.json").read_text(encoding="utf-8"))["records"]
        route_files = [
            self.repo_root / "backend" / "main.py",
            *sorted((self.repo_root / "backend" / "routers").glob("*.py")),
            *sorted((self.repo_root / "backend" / "ontology").glob("*.py")),
        ]
        discovered = _collect_ast_routes(route_files)
        discovered_paths = {p for _, p in discovered}

        drift: list[str] = []
        matched = 0
        for item in inv:
            path = item["path_template"]
            proto = item["protocol"]
            method = item["method"].upper()
            if proto == "HTTP":
                if (method, path) in discovered or path in discovered_paths:
                    matched += 1
                else:
                    drift.append(f"MISSING_HTTP_ROUTE:{method}:{path}")
            elif proto == "WEBSOCKET":
                if ("WEBSOCKET", path) in discovered or path in discovered_paths:
                    matched += 1
                else:
                    drift.append(f"MISSING_WS_ROUTE:{path}")
            else:
                # AudioSocket/ChanWS binary/TCP endpoints verified via framing constants below
                matched += 1

        # Verify AudioSocket BE framing constants in backend/audiosocket_server.py
        as_src = (self.repo_root / "backend" / "audiosocket_server.py").read_text(encoding="utf-8")
        for expected_token in ("AUDIOSOCKET_HANGUP = 0x00", "AUDIOSOCKET_UUID = 0x01", "AUDIOSOCKET_DTMF = 0x03", "AUDIOSOCKET_AUDIO = 0x10", "struct.pack(\"!BH\"", "FRAME_SIZE_BYTES = 320"):
            if expected_token not in as_src:
                drift.append(f"AUDIOSOCKET_DRIFT:{expected_token}")

        return CompatibilityCheckReport(
            domain="API_AND_TRANSPORT",
            baseline_count=len(inv),
            matched_count=matched,
            drift_items=tuple(drift),
            status=GateStatus.FAIL if drift else GateStatus.PASS,
            observation_scope="STATIC_AST_AND_FRAMING_CHECK",
            limitations=("Live ASGI HTTP/WS request execution is out of scope for passive M08 compatibility.",),
        )

    def check_ui_compatibility(self) -> CompatibilityCheckReport:
        inv = json.loads((self.baseline_dir / "UI_INVENTORY.json").read_text(encoding="utf-8"))["records"]
        nav_items = inv.get("nav_items", [])
        nav_ts = (self.repo_root / "frontend" / "src" / "nav.ts").read_text(encoding="utf-8")
        drift: list[str] = []
        matched = 0
        for item in nav_items:
            label = item["label"]
            if label in nav_ts:
                matched += 1
            else:
                drift.append(f"MISSING_UI_NAV_LABEL:{label}")

        # Verify referenced UI API call sites exist on disk
        for site in inv.get("api_call_sites", []):
            src_rel = site.get("path", "")
            if src_rel and not (self.repo_root / src_rel).exists():
                drift.append(f"ORPHAN_UI_CALL_SITE:{src_rel}")

        return CompatibilityCheckReport(
            domain="UI_STATIC",
            baseline_count=len(nav_items),
            matched_count=matched,
            drift_items=tuple(drift),
            status=GateStatus.FAIL if drift else GateStatus.PASS,
            observation_scope="STATIC_SOURCE_TRACE_ONLY",
            limitations=("Browser UI runtime acceptance remains HOLD until UI stage.",),
        )

    def check_db_compatibility(self) -> CompatibilityCheckReport:
        inv = json.loads((self.baseline_dir / "DATABASE_INVENTORY.json").read_text(encoding="utf-8"))["records"]
        discovered_tables = _collect_ast_tablenames(self.repo_root / "backend" / "db.py")
        drift: list[str] = []
        matched = 0
        for item in inv:
            tname = item["table"]
            if tname in discovered_tables:
                matched += 1
            else:
                drift.append(f"MISSING_DB_TABLE:{tname}")

        return CompatibilityCheckReport(
            domain="DATABASE_SCHEMA",
            baseline_count=len(inv),
            matched_count=matched,
            drift_items=tuple(drift),
            status=GateStatus.FAIL if drift else GateStatus.PASS,
            observation_scope="STATIC_AST_SCHEMA_CHECK",
            limitations=("Live production DB rows and live migrations are never touched.",),
        )

    def check_config_model_compatibility(self) -> CompatibilityCheckReport:
        inv = json.loads((self.baseline_dir / "CONFIG_MODEL_INVENTORY.json").read_text(encoding="utf-8"))["records"]
        drift: list[str] = []
        matched = 0

        for item in inv:
            kind = item["kind"]
            key = item["public_key"]
            if kind in {"SETTING", "FLAG"}:
                spec = SETTING_CATALOG.specs.get(key.lower())
                if spec is None:
                    drift.append(f"MISSING_SETTING_KEY:{key}")
                else:
                    matched += 1
                    expected_default = item.get("declared_default")
                    if expected_default is not None:
                        actual_cmp = list(spec.default) if isinstance(spec.default, tuple) else spec.default
                        if actual_cmp != expected_default and str(spec.default) != str(expected_default):
                            drift.append(f"DEFAULT_DRIFT:{key}:{expected_default}!={spec.default}")
            elif kind == "VOICE_PROFILE":
                # Validate Leyla seed 9 baseline and experimental seeds 42, 77, 123
                seed_m = re.search(r"(\d+)", str(key))
                if seed_m:
                    seed_val = int(seed_m.group(1))
                    if DEFAULT_VOICE_PROFILE_REGISTRY.get_by_seed(seed_val) is not None:
                        matched += 1
                    else:
                        drift.append(f"MISSING_VOICE_SEED:{seed_val}")
                else:
                    matched += 1
            else:
                matched += 1

        if LEYLA_BASELINE_SEED != 9:
            drift.append(f"LEYLA_BASELINE_SEED_DRIFT:{LEYLA_BASELINE_SEED}")
        if tuple(EXPERIMENTAL_VOICE_SEEDS) != (42, 77, 123):
            drift.append(f"EXPERIMENTAL_SEEDS_DRIFT:{EXPERIMENTAL_VOICE_SEEDS}")

        return CompatibilityCheckReport(
            domain="CONFIG_AND_MODELS",
            baseline_count=len(inv),
            matched_count=matched,
            drift_items=tuple(drift),
            status=GateStatus.FAIL if drift else GateStatus.PASS,
            observation_scope="PASSIVE_CATALOG_AND_REGISTRY_CHECK",
            limitations=("Real model weights and GPU residency are not loaded in M08.",),
        )
