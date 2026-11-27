"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

from typing import Any

from backend.core.configuration.contracts import ConfigSnapshot, SensitivityLevel
from backend.core.configuration.resolver import resolve_configuration
from backend.core.configuration.setting_catalog import SETTING_CATALOG, SettingCatalog
from backend.core.contracts.validation import ConversionResult


def snapshot_from_legacy_settings(
    settings_obj: Any = None,
    *,
    catalog: SettingCatalog = SETTING_CATALOG,
    created_utc: str | None = None,
    created_monotonic_ns: int | None = None,
    snapshot_seq: int = 0,
) -> ConversionResult[ConfigSnapshot]:
    """Bridge a legacy backend.config.Settings instance into an immutable M03 ConfigSnapshot."""
    if settings_obj is None:
        from backend.config import settings as legacy_settings

        settings_obj = legacy_settings

    raw_overrides: dict[str, Any] = {}
    missing: list[str] = []
    for key in catalog.specs:
        if hasattr(settings_obj, key):
            raw_overrides[key] = getattr(settings_obj, key)
        else:
            missing.append(key)

    try:
        resolution = resolve_configuration(
            overrides=raw_overrides,
            catalog=catalog,
            created_utc=created_utc,
            created_monotonic_ns=created_monotonic_ns,
            snapshot_seq=snapshot_seq,
            note="legacy_settings_bridge",
        )
    except Exception as exc:
        return ConversionResult(
            value=None,
            missing_fields=tuple(missing),
            error=f"{type(exc).__name__}: {exc}",
            lossy=bool(missing),
            source_ref="backend.config.Settings",
        )

    warnings = list(resolution.warnings)
    if missing:
        warnings.append(f"missing_legacy_fields:{','.join(missing)}")

    return ConversionResult(
        value=resolution.snapshot,
        missing_fields=tuple(missing),
        warnings=tuple(warnings),
        lossy=bool(missing),
        source_ref="backend.config.Settings",
    )


def legacy_values_from_snapshot(
    snapshot: ConfigSnapshot,
    *,
    include_secrets: bool = False,
    catalog: SettingCatalog = SETTING_CATALOG,
) -> dict[str, Any]:
    """Project ConfigSnapshot values back to a plain dict for legacy callers."""
    out: dict[str, Any] = {}
    for key, val in snapshot.values.items():
        spec = catalog.get(key)
        if spec is not None and spec.sensitivity == SensitivityLevel.SECRET_REF:
            out[key] = snapshot.get_secret(key) if include_secrets else ""
        else:
            out[key] = list(val) if isinstance(val, tuple) else val
    return out
