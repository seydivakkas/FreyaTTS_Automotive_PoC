"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.core.configuration.contracts import (
    ConfigSnapshot,
    ConfigSource,
    SecretBox,
    SecretRef,
    SensitivityLevel,
    SettingSpec,
)
from backend.core.configuration.setting_catalog import SETTING_CATALOG, SettingCatalog

_URL_CREDENTIALS_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^/@:\s]+):([^/@\s]+)@")
REDACTED_SENTINEL = "[REDACTED]"


def redact_url_credentials(text: str) -> str:
    """Mask embedded user:password@ credentials inside URIs."""
    return _URL_CREDENTIALS_RE.sub(r"\1***:***@", text)


def _scrub_secret_substrings(value: Any, secret_values: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        out = redact_url_credentials(value)
        for sec in secret_values:
            if sec and sec in out:
                out = out.replace(sec, REDACTED_SENTINEL)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrub_secret_substrings(v, secret_values) for v in value]
    if isinstance(value, dict):
        return {str(k): _scrub_secret_substrings(v, secret_values) for k, v in value.items()}
    return value


def _serialize_public_value(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, tuple):
        return list(value)
    return value


def project_setting(
    key: str,
    value: Any,
    spec: SettingSpec,
    source: ConfigSource,
    *,
    secret_values: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Create a safe telemetry/operator representation of a single setting."""
    if spec.sensitivity == SensitivityLevel.SECRET_REF:
        if isinstance(value, SecretRef):
            configured = value.configured
        elif isinstance(value, SecretBox):
            configured = value.is_configured
        else:
            configured = bool(value)
        return {
            "key": key,
            "sensitivity": spec.sensitivity.value,
            "unit": spec.unit,
            "restart_policy": spec.restart_policy.value,
            "source": source.value if isinstance(source, ConfigSource) else str(source),
            "configured": configured,
            "value": REDACTED_SENTINEL,
        }

    plain = _serialize_public_value(value)
    scrubbed = _scrub_secret_substrings(plain, secret_values)
    return {
        "key": key,
        "sensitivity": spec.sensitivity.value,
        "unit": spec.unit,
        "restart_policy": spec.restart_policy.value,
        "source": source.value if isinstance(source, ConfigSource) else str(source),
        "value": scrubbed,
    }


def safe_projection(
    snapshot: ConfigSnapshot,
    *,
    catalog: SettingCatalog = SETTING_CATALOG,
    include_internal: bool = True,
) -> dict[str, Any]:
    """Produce an allowlisted, secret-free JSON-ready projection of ConfigSnapshot."""
    secret_values = tuple(
        box.reveal()
        for box in snapshot._secrets.values()
        if box.is_configured and len(box.reveal()) >= 3
    )

    settings_proj: dict[str, Any] = {}
    for key in sorted(snapshot.values.keys()):
        spec = catalog.get(key)
        val = snapshot.values[key]
        src = snapshot.sources.get(key, ConfigSource.DEFAULT)
        if spec is None:
            continue
        if not include_internal and spec.sensitivity == SensitivityLevel.INTERNAL:
            continue
        settings_proj[key] = project_setting(
            key,
            val,
            spec,
            src,
            secret_values=secret_values,
        )

    flags_proj = {
        str(k): _scrub_secret_substrings(v, secret_values)
        for k, v in sorted(snapshot.feature_flags.items())
    }

    return {
        "schema_version": snapshot.schema_version,
        "snapshot_seq": snapshot.snapshot_seq,
        "config_revision": snapshot.config_revision,
        "feature_flags": flags_proj,
        "settings": settings_proj,
    }


def safe_snapshot_json(
    snapshot: ConfigSnapshot,
    *,
    catalog: SettingCatalog = SETTING_CATALOG,
    include_internal: bool = True,
) -> str:
    """Serialize safe_projection with strict allow_nan=False and secret leak assertion."""
    projected = safe_projection(snapshot, catalog=catalog, include_internal=include_internal)
    dumped = json.dumps(projected, ensure_ascii=False, sort_keys=True, allow_nan=False)
    for box in snapshot._secrets.values():
        secret = box.reveal()
        if len(secret) >= 3 and secret in dumped:
            raise AssertionError("Secret value leaked into safe_snapshot_json output")
    return dumped
