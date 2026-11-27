"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Generic, Mapping, TypeVar

T = TypeVar("T")

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PHONE_LIKE_RE = re.compile(r"(?:\+90|0)\s*\(?[2-5]\d{2}\)?[\s-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}")


def require_strict_int(value: Any, name: str, *, minimum: int = 0, maximum: int = 2**63 - 1) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def require_finite(value: Any, name: str, *, minimum: float | None = None, maximum: float | None = None, allow_none: bool = False) -> float | None:
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{name} cannot be None")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    f = float(value)
    if not math.isfinite(f):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and f < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and f > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return f


def require_safe_id(value: Any, name: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must match 1..128 safe identifier characters")
    if _PHONE_LIKE_RE.search(value):
        raise ValueError(f"{name} must not contain phone-number-like PII")
    return value


def require_utc_iso(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an ISO-8601 UTC string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} invalid ISO timestamp") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError(f"{name} must have UTC (+00:00 / Z) offset")
    return value


def freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): freeze_value(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_value(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(freeze_value(v) for v in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite float not permitted in immutable contract")
    return value


def thaw_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: thaw_value(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [thaw_value(v) for v in value]
    if isinstance(value, frozenset):
        return sorted(thaw_value(v) for v in value)
    return value


@dataclass(frozen=True, slots=True)
class ConversionResult(Generic[T]):
    value: T | None
    missing_fields: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    error: str | None = None
    lossy: bool = False
    source_ref: str | None = None

    @property
    def ok(self) -> bool:
        return self.value is not None and self.error is None
