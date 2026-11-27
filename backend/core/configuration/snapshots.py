"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Mapping

from backend.core.configuration.contracts import (
    ConfigSnapshot,
    ConfigSource,
    SecretBox,
    SecretRef,
    SupervisorMode,
)
from backend.core.contracts.common import CONTRACT_SCHEMA_VERSION


def _canonicalize_value(value: Any) -> Any:
    if isinstance(value, SecretRef):
        return {
            "__secret_ref__": value.key,
            "configured": value.configured,
            "fingerprint": value.fingerprint,
        }
    if isinstance(value, SecretBox):
        return {"__secret_box__": value.is_configured}
    if isinstance(value, SupervisorMode):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, (tuple, list)):
        return [_canonicalize_value(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): _canonicalize_value(v) for k, v in sorted(value.items())}
    return value


def compute_config_revision(
    *,
    schema_version: str,
    values: Mapping[str, Any],
    feature_flags: Mapping[str, bool | str],
    sources: Mapping[str, ConfigSource] | None = None,
) -> str:
    """Compute a deterministic canonical SHA-256 revision independent of timestamps and snapshot_seq."""
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "values": _canonicalize_value(values),
        "feature_flags": _canonicalize_value(feature_flags),
    }
    if sources is not None:
        payload["sources"] = {
            str(k): (v.value if isinstance(v, ConfigSource) else str(v))
            for k, v in sorted(sources.items())
        }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_snapshot(
    *,
    values: Mapping[str, Any],
    sources: Mapping[str, ConfigSource],
    feature_flags: Mapping[str, bool | str],
    secrets: Mapping[str, SecretBox] | None = None,
    snapshot_seq: int = 0,
    created_utc: str | None = None,
    created_monotonic_ns: int | None = None,
    note: str = "",
    schema_version: str = CONTRACT_SCHEMA_VERSION,
) -> ConfigSnapshot:
    revision = compute_config_revision(
        schema_version=schema_version,
        values=values,
        feature_flags=feature_flags,
        sources=sources,
    )
    return ConfigSnapshot(
        schema_version=schema_version,
        snapshot_seq=snapshot_seq,
        config_revision=revision,
        values=values,
        sources=sources,
        feature_flags=feature_flags,
        created_utc=created_utc,
        created_monotonic_ns=created_monotonic_ns,
        note=note,
        _secrets=secrets or {},
    )


class ConfigSnapshotStore:
    """Thread-safe atomic swap & rollback store holding last known-good ConfigSnapshot."""

    def __init__(self, initial: ConfigSnapshot, *, max_history: int = 16) -> None:
        if not isinstance(initial, ConfigSnapshot):
            raise TypeError("initial must be ConfigSnapshot")
        if max_history < 2:
            raise ValueError("max_history must be >= 2")
        self._lock = threading.RLock()
        self._max_history = max_history
        self._history: list[ConfigSnapshot] = [initial]
        self._rollbacks: int = 0

    @property
    def current(self) -> ConfigSnapshot:
        with self._lock:
            return self._history[-1]

    @property
    def last_known_good(self) -> ConfigSnapshot | None:
        with self._lock:
            return self._history[-2] if len(self._history) >= 2 else None

    @property
    def history_depth(self) -> int:
        with self._lock:
            return len(self._history)

    @property
    def rollback_count(self) -> int:
        with self._lock:
            return self._rollbacks

    def swap(self, candidate: ConfigSnapshot) -> ConfigSnapshot:
        """Atomically promote a validated ConfigSnapshot with a monotonic snapshot_seq."""
        if not isinstance(candidate, ConfigSnapshot):
            raise TypeError("candidate must be ConfigSnapshot")
        with self._lock:
            current = self._history[-1]
            expected_rev = compute_config_revision(
                schema_version=candidate.schema_version,
                values=candidate.values,
                feature_flags=candidate.feature_flags,
                sources=candidate.sources,
            )
            if candidate.config_revision != expected_rev:
                raise ValueError("candidate ConfigSnapshot failed canonical revision integrity check")
            next_seq = current.snapshot_seq + 1
            promoted = ConfigSnapshot(
                schema_version=candidate.schema_version,
                snapshot_seq=next_seq,
                config_revision=candidate.config_revision,
                values=candidate.values,
                sources=candidate.sources,
                feature_flags=candidate.feature_flags,
                created_utc=candidate.created_utc,
                created_monotonic_ns=candidate.created_monotonic_ns,
                note=candidate.note,
                _secrets=candidate._secrets,
            )
            self._history.append(promoted)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history :]
            return promoted

    def rollback(self) -> ConfigSnapshot:
        """Atomically roll back to the previous known-good snapshot."""
        with self._lock:
            if len(self._history) < 2:
                raise RuntimeError("No previous known-good ConfigSnapshot available for rollback")
            self._history.pop()
            self._rollbacks += 1
            return self._history[-1]
