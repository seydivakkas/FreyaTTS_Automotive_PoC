"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from backend.core.configuration.contracts import (
    ConfigSnapshot,
    ConfigSource,
    ResolvedSetting,
    SecretBox,
    SecretRef,
    SensitivityLevel,
    SettingSpec,
    SettingValueType,
    SupervisorMode,
)
from backend.core.configuration.feature_flags import FeatureFlagRegistry, parse_supervisor_mode
from backend.core.configuration.setting_catalog import SETTING_CATALOG, SettingCatalog
from backend.core.configuration.snapshots import build_snapshot

_TRUE_STRINGS = frozenset({"1", "true", "yes", "on", "y", "t"})
_FALSE_STRINGS = frozenset({"0", "false", "no", "off", "n", "f"})


def parse_dotenv_text(text: str) -> dict[str, str]:
    """Parse .env formatted text into a key-value dict without mutating os.environ."""
    parsed: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        if key:
            parsed[key] = val
    return parsed


def parse_dotenv_file(path: Path | str) -> dict[str, str]:
    """Explicitly read a .env file on demand (never called at import time)."""
    return parse_dotenv_text(Path(path).read_text(encoding="utf-8"))


def coerce_setting_value(spec: SettingSpec, raw: Any) -> Any:
    """Validate and coerce raw input according to SettingSpec."""
    if raw is None:
        if spec.allow_none:
            return None
        raise ValueError(f"Setting {spec.key!r} does not allow None")

    vt = spec.value_type

    if vt == SettingValueType.BOOL:
        if type(raw) is bool:
            return raw
        if isinstance(raw, str):
            norm = raw.strip().lower()
            if norm in _TRUE_STRINGS:
                return True
            if norm in _FALSE_STRINGS:
                return False
        raise ValueError(f"Setting {spec.key!r} expects bool, got {raw!r}")

    if vt == SettingValueType.INT:
        if type(raw) is bool:
            raise ValueError(f"Setting {spec.key!r} expects int, got bool")
        if type(raw) is int:
            val = raw
        elif isinstance(raw, str):
            s = raw.strip()
            if not s or (s.startswith("-") and not s[1:].isdigit()) or (not s.startswith("-") and not s.isdigit()):
                raise ValueError(f"Setting {spec.key!r} expects int, got {raw!r}")
            val = int(s)
        else:
            raise ValueError(f"Setting {spec.key!r} expects int, got {type(raw).__name__}")
        if spec.min_value is not None and val < spec.min_value:
            raise ValueError(f"Setting {spec.key!r} must be >= {spec.min_value}")
        if spec.max_value is not None and val > spec.max_value:
            raise ValueError(f"Setting {spec.key!r} must be <= {spec.max_value}")
        return val

    if vt == SettingValueType.FLOAT:
        if type(raw) is bool:
            raise ValueError(f"Setting {spec.key!r} expects float, got bool")
        if isinstance(raw, (int, float)):
            val_f = float(raw)
        elif isinstance(raw, str):
            try:
                val_f = float(raw.strip())
            except ValueError as exc:
                raise ValueError(f"Setting {spec.key!r} expects float, got {raw!r}") from exc
        else:
            raise ValueError(f"Setting {spec.key!r} expects float, got {type(raw).__name__}")
        if not math.isfinite(val_f):
            raise ValueError(f"Setting {spec.key!r} must be finite")
        if spec.strict_gt_zero and val_f <= 0.0:
            raise ValueError(f"Setting {spec.key!r} must be > 0")
        if spec.min_value is not None and val_f < spec.min_value:
            raise ValueError(f"Setting {spec.key!r} must be >= {spec.min_value}")
        if spec.max_value is not None and val_f > spec.max_value:
            raise ValueError(f"Setting {spec.key!r} must be <= {spec.max_value}")
        return val_f

    if vt == SettingValueType.PATH:
        if isinstance(raw, Path):
            return raw
        if isinstance(raw, str):
            stripped = raw.strip()
            if not stripped:
                if spec.allow_none:
                    return None
                raise ValueError(f"Setting {spec.key!r} path cannot be empty")
            return Path(stripped)
        raise ValueError(f"Setting {spec.key!r} expects Path or str")

    if vt == SettingValueType.STR_LIST:
        if isinstance(raw, str):
            stripped = raw.strip()
            if not stripped:
                return ()
            if stripped.startswith("["):
                loaded = json.loads(stripped)
                if not isinstance(loaded, list) or not all(isinstance(x, str) for x in loaded):
                    raise ValueError(f"Setting {spec.key!r} JSON list must contain strings")
                return tuple(loaded)
            return tuple(item.strip() for item in stripped.split(",") if item.strip())
        if isinstance(raw, (list, tuple)):
            if not all(isinstance(x, str) for x in raw):
                raise ValueError(f"Setting {spec.key!r} expects sequence of strings")
            return tuple(raw)
        raise ValueError(f"Setting {spec.key!r} expects list[str]")

    if vt == SettingValueType.ENUM:
        if spec.key == "supervisor_mode":
            mode = parse_supervisor_mode(raw)
            return mode.value
        if not isinstance(raw, str):
            raise ValueError(f"Setting {spec.key!r} expects str enum")
        norm = raw.strip().lower()
        if spec.allowed_values and norm not in spec.allowed_values:
            raise ValueError(f"Setting {spec.key!r} invalid value {raw!r}; allowed={spec.allowed_values}")
        return norm

    # STR
    if isinstance(raw, SecretBox):
        return raw.reveal()
    if isinstance(raw, SecretRef):
        raise ValueError(f"Cannot coerce opaque SecretRef back into plaintext for {spec.key!r}")
    if not isinstance(raw, str):
        raise ValueError(f"Setting {spec.key!r} expects str, got {type(raw).__name__}")
    if spec.allowed_values and raw not in spec.allowed_values:
        raise ValueError(f"Setting {spec.key!r} invalid value {raw!r}; allowed={spec.allowed_values}")
    return raw


@dataclass(frozen=True, slots=True)
class ConfigResolution:
    snapshot: ConfigSnapshot
    settings: Mapping[str, ResolvedSetting]
    flags: FeatureFlagRegistry
    warnings: tuple[str, ...] = ()


def resolve_configuration(
    *,
    env: Mapping[str, Any] | None = None,
    file_values: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
    extra_flags: Mapping[str, bool | SupervisorMode] | None = None,
    catalog: SettingCatalog = SETTING_CATALOG,
    created_utc: str | None = None,
    created_monotonic_ns: int | None = None,
    snapshot_seq: int = 0,
    note: str = "",
    strict_unknown_overrides: bool = True,
) -> ConfigResolution:
    """Resolve all settings deterministically from defaults, file_values, env, and overrides."""
    warnings: list[str] = []
    raw_by_key: dict[str, tuple[Any, ConfigSource, str | None]] = {
        key: (spec.default, ConfigSource.DEFAULT, None)
        for key, spec in catalog.specs.items()
    }

    layers: tuple[tuple[Mapping[str, Any] | None, ConfigSource, bool], ...] = (
        (file_values, ConfigSource.FILE, False),
        (env, ConfigSource.ENV, False),
        (overrides, ConfigSource.OVERRIDE, strict_unknown_overrides),
    )

    for layer_map, layer_source, fail_on_unknown in layers:
        if not layer_map:
            continue
        # Process legacy aliases first so canonical keys in the same layer win deterministically.
        canonical_entries: list[tuple[str, Any]] = []
        alias_entries: list[tuple[str, str, Any]] = []
        for raw_key, raw_val in layer_map.items():
            resolved = catalog.resolve_key(str(raw_key))
            if resolved is None:
                if fail_on_unknown:
                    raise KeyError(f"Unknown configuration key in {layer_source.value}: {raw_key!r}")
                continue
            canonical_key, alias_used = resolved
            if alias_used is None:
                canonical_entries.append((canonical_key, raw_val))
            else:
                alias_entries.append((canonical_key, alias_used, raw_val))

        for canonical_key, alias_used, raw_val in alias_entries:
            effective_source = (
                ConfigSource.LEGACY_ALIAS
                if alias_used != canonical_key.upper()
                else layer_source
            )
            raw_by_key[canonical_key] = (raw_val, effective_source, alias_used)
            if effective_source == ConfigSource.LEGACY_ALIAS:
                warnings.append(f"legacy_alias:{alias_used}->{canonical_key}")

        for canonical_key, raw_val in canonical_entries:
            raw_by_key[canonical_key] = (raw_val, layer_source, None)

    coerced_values: dict[str, Any] = {}
    sources: dict[str, ConfigSource] = {}
    aliases: dict[str, str | None] = {}
    for key, spec in catalog.specs.items():
        raw_val, source, alias_used = raw_by_key[key]
        coerced_values[key] = coerce_setting_value(spec, raw_val)
        sources[key] = source
        aliases[key] = alias_used

    # Preserve backend/config.py _isolate_demo_data semantics
    if coerced_values.get("demo_mode"):
        coerced_values["data_dir"] = Path("data/demo")
        coerced_values["database_url"] = "sqlite:///./data/demo/assistant.db"

    snapshot_values: dict[str, Any] = {}
    secret_boxes: dict[str, SecretBox] = {}
    resolved_settings: dict[str, ResolvedSetting] = {}

    for key, spec in catalog.specs.items():
        val = coerced_values[key]
        src = sources[key]
        if spec.sensitivity == SensitivityLevel.SECRET_REF:
            box = val if isinstance(val, SecretBox) else SecretBox(str(val))
            ref = box.to_ref(key, source=src)
            secret_boxes[key] = box
            snapshot_values[key] = ref
            resolved_settings[key] = ResolvedSetting(
                key=key,
                value=ref,
                spec=spec,
                source=src,
                alias_used=aliases[key],
            )
        else:
            snapshot_values[key] = val
            resolved_settings[key] = ResolvedSetting(
                key=key,
                value=val,
                spec=spec,
                source=src,
                alias_used=aliases[key],
            )

    preliminary = build_snapshot(
        values=snapshot_values,
        sources=sources,
        feature_flags={},
        secrets=secret_boxes,
        snapshot_seq=snapshot_seq,
        created_utc=created_utc,
        created_monotonic_ns=created_monotonic_ns,
        note=note,
    )
    flags = FeatureFlagRegistry.from_snapshot(preliminary, extra_flags=extra_flags)
    final_snapshot = build_snapshot(
        values=snapshot_values,
        sources=sources,
        feature_flags=flags.as_primitives(),
        secrets=secret_boxes,
        snapshot_seq=snapshot_seq,
        created_utc=created_utc,
        created_monotonic_ns=created_monotonic_ns,
        note=note,
    )

    return ConfigResolution(
        snapshot=final_snapshot,
        settings=MappingProxyType(resolved_settings),
        flags=flags,
        warnings=tuple(warnings),
    )
