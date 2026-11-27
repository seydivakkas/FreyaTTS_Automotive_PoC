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

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from backend.core.contracts.common import EventEnvelope, MetricSample
from backend.core.contracts.validation import require_strict_int
from backend.observability.evidence import EvidenceRecord
from backend.observability.projection import Projection


@dataclass(frozen=True, slots=True)
class LocalStoreStats:
    written_count: int
    dropped_count: int
    rotated_files_count: int


class LocalObservabilityStore:
    """Lazy, bounded JSONL store that persists only safely projected observability records."""

    def __init__(
        self,
        base_dir: Path | str,
        *,
        max_records_per_file: int = 1000,
        max_files: int = 5,
        projector: Projection | None = None,
    ) -> None:
        require_strict_int(max_records_per_file, "max_records_per_file", minimum=1)
        require_strict_int(max_files, "max_files", minimum=1)
        self.base_dir = Path(base_dir).resolve()
        self.max_records_per_file = max_records_per_file
        self.max_files = max_files
        self._projector = projector or Projection()
        self._lock = threading.Lock()
        self._line_counts: dict[str, int] = {}
        self._written_count = 0
        self._dropped_count = 0
        self._rotated_files_count = 0

    def _safe_stream_path(self, stream_name: str) -> Path:
        if not stream_name or "/" in stream_name or "\\" in stream_name or ".." in stream_name:
            raise ValueError(f"Unsafe stream_name: {stream_name!r}")
        target = (self.base_dir / f"{stream_name}.jsonl").resolve()
        if not target.is_relative_to(self.base_dir):
            raise ValueError("Resolved path escapes base_dir")
        return target

    def _rotate_if_needed(self, path: Path, stream_name: str) -> None:
        count = self._line_counts.get(stream_name)
        if count is None:
            if path.exists():
                with path.open("r", encoding="utf-8") as fh:
                    count = sum(1 for _ in fh)
            else:
                count = 0
            self._line_counts[stream_name] = count

        if count < self.max_records_per_file:
            return

        # Rotate .1 .. .max_files-1 safely inside base_dir.
        for idx in range(self.max_files - 1, 0, -1):
            src = self.base_dir / f"{stream_name}.{idx}.jsonl"
            dst = self.base_dir / f"{stream_name}.{idx + 1}.jsonl"
            if src.exists():
                if idx + 1 >= self.max_files:
                    src.unlink(missing_ok=True)
                else:
                    src.replace(dst)
        if self.max_files > 1 and path.exists():
            path.replace(self.base_dir / f"{stream_name}.1.jsonl")
        elif path.exists():
            path.unlink(missing_ok=True)

        self._line_counts[stream_name] = 0
        self._rotated_files_count += 1

    def _write_json_line(self, stream_name: str, payload: dict[str, Any]) -> bool:
        try:
            line = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except Exception:
            with self._lock:
                self._dropped_count += 1
            return False

        with self._lock:
            self.base_dir.mkdir(parents=True, exist_ok=True)
            path = self._safe_stream_path(stream_name)
            self._rotate_if_needed(path, stream_name)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            self._line_counts[stream_name] = self._line_counts.get(stream_name, 0) + 1
            self._written_count += 1
        return True

    def append_event(self, event: EventEnvelope | dict[str, Any]) -> bool:
        projected = self._projector.project(event)
        if projected is None:
            with self._lock:
                self._dropped_count += 1
            return False
        return self._write_json_line("events", projected)

    def append_metrics(self, samples: Sequence[MetricSample]) -> bool:
        projected_items: list[dict[str, Any]] = []
        for sample in samples:
            pm = self._projector.project(sample)
            if pm is None:
                with self._lock:
                    self._dropped_count += 1
                return False
            projected_items.append(pm)
        return self._write_json_line("metrics", {"samples": projected_items})

    def append_evidence(self, record: EvidenceRecord) -> bool:
        projected_metrics: list[dict[str, Any]] = []
        for m in record.metrics:
            pm = self._projector.project(m)
            if pm is None:
                with self._lock:
                    self._dropped_count += 1
                return False
            projected_metrics.append(pm)
        payload = {
            "evidence_id": record.evidence_id,
            "kind": record.kind.value,
            "claim": record.claim,
            "subject": record.subject,
            "clock_domain": record.clock_domain,
            "recorded_monotonic_ns": record.recorded_monotonic_ns,
            "observation_scope": record.observation_scope,
            "utc_timestamp": record.utc_timestamp,
            "trace_id": record.trace_id,
            "source_ref": record.source_ref,
            "metrics": projected_metrics,
            "details": dict(record.details),
            "details_dropped": record.details_dropped,
        }
        return self._write_json_line("evidence", payload)

    def _read_stream(self, stream_name: str, limit: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            path = self._safe_stream_path(stream_name)
            if not path.exists():
                return []
            with path.open("r", encoding="utf-8") as fh:
                lines = [ln.strip() for ln in fh if ln.strip()]
        if limit is not None and limit >= 0:
            lines = lines[-limit:] if limit > 0 else []
        return [json.loads(ln) for ln in lines]

    def read_events(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self._read_stream("events", limit=limit)

    def read_metrics(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self._read_stream("metrics", limit=limit)

    def read_evidence(self, limit: int | None = None) -> list[dict[str, Any]]:
        return self._read_stream("evidence", limit=limit)

    @property
    def stats(self) -> LocalStoreStats:
        with self._lock:
            return LocalStoreStats(
                written_count=self._written_count,
                dropped_count=self._dropped_count,
                rotated_files_count=self._rotated_files_count,
            )
