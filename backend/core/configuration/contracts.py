"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from backend.core.contracts.common import ContractVersion
from backend.core.contracts.validation import (
    freeze_value,
    require_finite,
    require_safe_id,
    require_strict_int,
    require_utc_iso,
)


class SensitivityLevel(StrEnum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    SECRET_REF = "SECRET_REF"


class RestartPolicy(StrEnum):
    HOT_RELOAD = "HOT_RELOAD"
    NEW_SESSION = "NEW_SESSION"
    PROCESS_RESTART = "PROCESS_RESTART"


class SettingValueType(StrEnum):
    STR = "STR"
    INT = "INT"
    FLOAT = "FLOAT"
    BOOL = "BOOL"
    PATH = "PATH"
    STR_LIST = "STR_LIST"
    ENUM = "ENUM"


class ConfigSource(StrEnum):
    DEFAULT = "DEFAULT"
    FILE = "FILE"
    ENV = "ENV"
    LEGACY_ALIAS = "LEGACY_ALIAS"
    OVERRIDE = "OVERRIDE"


class SupervisorMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    GUARDED = "guarded"


class SecretBox:
    """Immutable secret holder that never exposes its plaintext value in repr or str."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("SecretBox requires str")
        object.__setattr__(self, "_value", value)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("SecretBox is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("SecretBox is immutable")

    @property
    def is_configured(self) -> bool:
        return bool(self._value)

    def reveal(self) -> str:
        return self._value

    def fingerprint(self, key: str) -> str | None:
        if not self._value:
            return None
        return hashlib.sha256(f"freya-secret-v1:{key}:{self._value}".encode("utf-8")).hexdigest()[:16]

    def to_ref(self, key: str, source: ConfigSource = ConfigSource.DEFAULT) -> "SecretRef":
        return SecretRef(
            key=key,
            configured=self.is_configured,
            fingerprint=self.fingerprint(key),
            source=source,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SecretBox):
            return NotImplemented
        return hmac.compare_digest(self._value, other._value)

    def __hash__(self) -> int:
        return hash(hashlib.sha256(self._value.encode("utf-8")).digest())

    def __repr__(self) -> str:
        state = "configured" if self._value else "unset"
        return f"SecretBox(<REDACTED:{state}>)"

    def __str__(self) -> str:
        return "[REDACTED]"


@dataclass(frozen=True, slots=True)
class SecretRef:
    """Opaque metadata reference for a SECRET_REF setting; never holds plaintext."""

    key: str
    configured: bool
    fingerprint: str | None = None
    source: ConfigSource = ConfigSource.DEFAULT

    def __post_init__(self) -> None:
        require_safe_id(self.key, "key")
        if type(self.configured) is not bool:
            raise ValueError("configured must be bool")
        if self.fingerprint is not None and (
            not isinstance(self.fingerprint, str) or len(self.fingerprint) < 8
        ):
            raise ValueError("fingerprint must be a hex prefix >= 8 chars")
        if not isinstance(self.source, ConfigSource):
            raise ValueError("source must be ConfigSource")

    def __repr__(self) -> str:
        return f"SecretRef(key={self.key!r}, configured={self.configured}, source={self.source.value!r})"

    def __str__(self) -> str:
        return f"<SecretRef:{self.key}:{'configured' if self.configured else 'unset'}>"


@dataclass(frozen=True, slots=True)
class SettingSpec:
    """Canonical specification for a single registered configuration setting."""

    key: str
    value_type: SettingValueType
    default: Any
    unit: str
    sensitivity: SensitivityLevel
    restart_policy: RestartPolicy
    legacy_aliases: tuple[str, ...] = ()
    allowed_values: tuple[Any, ...] = ()
    min_value: int | float | None = None
    max_value: int | float | None = None
    strict_gt_zero: bool = False
    allow_none: bool = False
    category: str = "general"
    description: str = ""

    def __post_init__(self) -> None:
        require_safe_id(self.key, "key")
        if not isinstance(self.value_type, SettingValueType):
            raise ValueError("value_type must be SettingValueType")
        if not isinstance(self.unit, str) or not self.unit.strip():
            raise ValueError("unit must be non-empty")
        if not isinstance(self.sensitivity, SensitivityLevel):
            raise ValueError("sensitivity must be SensitivityLevel")
        if not isinstance(self.restart_policy, RestartPolicy):
            raise ValueError("restart_policy must be RestartPolicy")
        if self.min_value is not None:
            require_finite(self.min_value, "min_value")
        if self.max_value is not None:
            require_finite(self.max_value, "max_value")
        object.__setattr__(self, "legacy_aliases", tuple(self.legacy_aliases))
        object.__setattr__(self, "allowed_values", tuple(self.allowed_values))
        if self.default is not None:
            object.__setattr__(self, "default", freeze_value(self.default))

    def __repr__(self) -> str:
        default_repr = "[REDACTED]" if self.sensitivity == SensitivityLevel.SECRET_REF else repr(self.default)
        return (
            f"SettingSpec(key={self.key!r}, type={self.value_type.value}, "
            f"sensitivity={self.sensitivity.value}, default={default_repr})"
        )


@dataclass(frozen=True, slots=True)
class ResolvedSetting:
    """Single resolved configuration setting with provenance."""

    key: str
    value: Any
    spec: SettingSpec
    source: ConfigSource
    alias_used: str | None = None

    def __post_init__(self) -> None:
        require_safe_id(self.key, "key")
        if not isinstance(self.spec, SettingSpec):
            raise TypeError("spec must be SettingSpec")
        if not isinstance(self.source, ConfigSource):
            raise ValueError("source must be ConfigSource")
        if self.spec.sensitivity == SensitivityLevel.SECRET_REF and not isinstance(self.value, SecretRef):
            raise TypeError("SECRET_REF resolved value must be SecretRef")
        object.__setattr__(self, "value", freeze_value(self.value))

    def __repr__(self) -> str:
        val_repr = repr(self.value) if self.spec.sensitivity != SensitivityLevel.SECRET_REF else str(self.value)
        return (
            f"ResolvedSetting(key={self.key!r}, value={val_repr}, "
            f"source={self.source.value!r}, alias_used={self.alias_used!r})"
        )


@dataclass(frozen=True, slots=True)
class FeatureFlagSpec:
    """Descriptor for a feature flag or tri-state rollout flag."""

    name: str
    default: bool | SupervisorMode
    setting_key: str | None = None
    experimental: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        require_safe_id(self.name, "name")
        if not isinstance(self.default, (bool, SupervisorMode)):
            raise TypeError("FeatureFlagSpec default must be bool or SupervisorMode")
        if self.experimental:
            if isinstance(self.default, bool) and self.default is not False:
                raise ValueError("Experimental boolean flag must default to False")
            if isinstance(self.default, SupervisorMode) and self.default != SupervisorMode.OFF:
                raise ValueError("Experimental mode flag must default to SupervisorMode.OFF")


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    """Deeply immutable, canonical configuration snapshot."""

    schema_version: str
    snapshot_seq: int
    config_revision: str
    values: Mapping[str, Any]
    sources: Mapping[str, ConfigSource]
    feature_flags: Mapping[str, bool | str]
    created_utc: str | None = None
    created_monotonic_ns: int | None = None
    note: str = ""
    _secrets: Mapping[str, SecretBox] = field(default_factory=lambda: MappingProxyType({}), repr=False, compare=False)

    def __post_init__(self) -> None:
        ContractVersion.parse(self.schema_version)
        require_strict_int(self.snapshot_seq, "snapshot_seq", minimum=0)
        if (
            not isinstance(self.config_revision, str)
            or len(self.config_revision) != 64
            or any(c not in "0123456789abcdef" for c in self.config_revision)
        ):
            raise ValueError("config_revision must be a 64-char lowercase SHA-256 hex digest")
        if self.created_utc is not None:
            require_utc_iso(self.created_utc, "created_utc")
        if self.created_monotonic_ns is not None:
            require_strict_int(self.created_monotonic_ns, "created_monotonic_ns", minimum=0)
        object.__setattr__(self, "values", freeze_value(dict(self.values)))
        object.__setattr__(self, "sources", freeze_value(dict(self.sources)))
        object.__setattr__(self, "feature_flags", freeze_value(dict(self.feature_flags)))
        frozen_secrets = {
            str(k): (v if isinstance(v, SecretBox) else SecretBox(str(v)))
            for k, v in dict(self._secrets).items()
        }
        object.__setattr__(self, "_secrets", MappingProxyType(frozen_secrets))

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def get_secret(self, key: str) -> str:
        box = self._secrets.get(key)
        if box is None:
            raise KeyError(f"Unknown secret key: {key}")
        return box.reveal()

    def is_secret_configured(self, key: str) -> bool:
        box = self._secrets.get(key)
        return box.is_configured if box is not None else False

    def __repr__(self) -> str:
        return (
            f"ConfigSnapshot(schema={self.schema_version!r}, seq={self.snapshot_seq}, "
            f"rev={self.config_revision[:12]!r}, keys={len(self.values)}, "
            f"flags={len(self.feature_flags)})"
        )
