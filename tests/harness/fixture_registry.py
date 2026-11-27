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
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from backend.observability.evidence import EvidenceKind
from tests.harness.contracts import FixtureManifest
from tests.harness.isolation import resolve_confined_path


class HashMismatchError(ValueError):
    """Raised when a fixture file SHA-256 differs from its manifest."""


class SplitLeakageError(ValueError):
    """Raised when calibration and held-out evaluation splits share IDs or duplicate groups."""


class FixtureCapExceededError(ValueError):
    """Raised when fixture generation exceeds bounded size/sample/item limits."""


@dataclass(frozen=True, slots=True)
class FixtureLimits:
    max_bytes_per_fixture: int = 8 * 1024 * 1024
    max_samples_per_fixture: int = 48000 * 30
    max_items: int = 1024


def stream_sha256_file(path: Path, *, chunk_size: int = 65536) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def local_rng(seed: int) -> random.Random:
    """Create an isolated local PRNG without touching Python's global RNG or TTS seed."""
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be non-negative int")
    return random.Random(seed)


def canonical_fixture_json_bytes(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class FixtureRegistry:
    """Versioned synthetic fixture registry enforcing provenance, SHA-256, caps, and split hygiene."""

    def __init__(self, root: Path, *, limits: FixtureLimits | None = None) -> None:
        self.root = root.resolve(strict=True)
        self.limits = limits or FixtureLimits()
        self._manifests: dict[str, FixtureManifest] = {}

    def register(self, manifest: FixtureManifest, *, verify_files: bool = True) -> None:
        if manifest.fixture_id in self._manifests:
            existing = self._manifests[manifest.fixture_id]
            if existing.revision == manifest.revision and existing.sha256 != manifest.sha256:
                raise HashMismatchError(
                    f"Refusing silent regeneration for {manifest.fixture_id}@{manifest.revision}"
                )
        if manifest.sample_count is not None and manifest.sample_count > self.limits.max_samples_per_fixture:
            raise FixtureCapExceededError(
                f"sample_count {manifest.sample_count} exceeds cap {self.limits.max_samples_per_fixture}"
            )
        if verify_files:
            for rel in manifest.relative_files:
                fpath = resolve_confined_path(self.root, rel, allow_missing=False)
                size = fpath.stat().st_size
                if size > self.limits.max_bytes_per_fixture:
                    raise FixtureCapExceededError(
                        f"Fixture file {rel} size {size} exceeds cap {self.limits.max_bytes_per_fixture}"
                    )
                expected_hash = manifest.sha256.get(rel)
                if expected_hash is None:
                    raise HashMismatchError(f"Missing expected sha256 for {rel}")
                actual_hash = stream_sha256_file(fpath)
                if actual_hash != expected_hash:
                    raise HashMismatchError(
                        f"SHA-256 mismatch for {rel}: expected {expected_hash}, got {actual_hash}"
                    )
        self._manifests[manifest.fixture_id] = manifest
        self.validate_split_hygiene(self._manifests.values())

    def get(self, fixture_id: str) -> FixtureManifest | None:
        return self._manifests.get(fixture_id)

    def all(self) -> tuple[FixtureManifest, ...]:
        return tuple(self._manifests.values())

    @staticmethod
    def validate_split_hygiene(manifests: Iterable[FixtureManifest]) -> None:
        cal_ids: set[str] = set()
        eval_ids: set[str] = set()
        cal_groups: set[str] = set()
        eval_groups: set[str] = set()
        for m in manifests:
            if m.split == "calibration":
                cal_ids.add(m.fixture_id)
                if m.duplicate_group_id:
                    cal_groups.add(m.duplicate_group_id)
            elif m.split == "held_out":
                eval_ids.add(m.fixture_id)
                if m.duplicate_group_id:
                    eval_groups.add(m.duplicate_group_id)
        shared_ids = cal_ids & eval_ids
        if shared_ids:
            raise SplitLeakageError(f"Calibration/held_out ID overlap: {sorted(shared_ids)}")
        shared_groups = cal_groups & eval_groups
        if shared_groups:
            raise SplitLeakageError(f"Calibration/held_out duplicate_group overlap: {sorted(shared_groups)}")

    @classmethod
    def load_manifest_file(cls, root: Path, manifest_rel: str) -> list[FixtureManifest]:
        path = resolve_confined_path(root, manifest_rel, allow_missing=False)
        data = json.loads(path.read_text(encoding="utf-8"))
        out: list[FixtureManifest] = []
        for item in data.get("fixtures", ()):
            out.append(
                FixtureManifest(
                    fixture_id=item["fixture_id"],
                    revision=item["revision"],
                    source_class=EvidenceKind(item["source_class"]),
                    generator_version=item["generator_version"],
                    seed=int(item["seed"]),
                    relative_files=tuple(item.get("relative_files", ())),
                    sha256=dict(item.get("sha256", {})),
                    privacy_class=item.get("privacy_class", "SYNTHETIC_NO_PII"),
                    split=item.get("split", "calibration"),
                    sample_rate_hz=item.get("sample_rate_hz"),
                    channels=item.get("channels"),
                    encoding=item.get("encoding"),
                    sample_count=item.get("sample_count"),
                    labels=dict(item.get("labels", {})),
                    provenance=item.get("provenance", "tests.harness.fixtures"),
                    limitations=tuple(item.get("limitations", ())),
                    duplicate_group_id=item.get("duplicate_group_id"),
                )
            )
        return out
