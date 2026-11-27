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

import math
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from backend.core.contracts.common import ErrorInfo, EventEnvelope, MetricSample
from backend.core.contracts.serialization import safe_telemetry_projection
from backend.observability.event_catalog import allowed_metadata_keys_for

# Forbidden keys that must NEVER pass allowlists into telemetry projections.
FORBIDDEN_TELEMETRY_KEYS: frozenset[str] = frozenset({
    "raw_transcript",
    "normalized_transcript",
    "canonical_transcript",
    "stable_prefix",
    "transcript",
    "speech_text",
    "display_text",
    "utterance_text",
    "answer",
    "prompt",
    "intermediate_data",
    "payload",
    "audio",
    "audio_bytes",
    "pcm",
    "phone",
    "phone_number",
    "caller_phone",
    "plate",
    "plaka",
    "license_plate",
    "vin",
    "chassis",
    "sase_no",
    "tckn",
    "iban",
    "credit_card",
    "card_number",
    "cvv",
    "email",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "secret",
    "password",
    "authorization",
    "bearer",
    "cookie",
    "master_key",
    "signing_key",
    "ami_secret",
})

# Sentinel patterns for PII / secrets embedded inside otherwise-allowlisted string fields.
_PHONE_SENTINEL_RE = re.compile(
    r"(?:(?:\+?90\s*|0)\s*\(?[2-5]\d{2}\)?[\s.-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}"
    r"|\+\d{1,3}[\s.-]?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{2,4})"
)
_TR_PLATE_SENTINEL_RE = re.compile(
    r"(?<![:\d-])(?:0[1-9]|[1-7][0-9]|8[01])"
    r"(?:\s+[A-Za-zÇĞİÖŞÜçğıöşü]{1,3}\s+\d{2,4}"
    r"|[A-ZÇĞİÖŞÜ]{1,3}\d{2,4}"
    r"|-[A-Za-zÇĞİÖŞÜçğıöşü]{1,3}-\d{2,4})"
    r"\b(?![\d:])"
)
_VIN_CANDIDATE_RE = re.compile(r"(?<![A-Za-z0-9])[A-HJ-NPR-Za-hj-npr-z0-9]{17}(?![A-Za-z0-9])")
_TRANSCRIPT_SENTINEL_RE = re.compile(
    r"(?i)\b(?:raw_transcript|normalized_transcript|canonical_transcript|speech_text|display_text|transcript)\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|\S+(?:\s+\S+)*)"
)
_TOKEN_SENTINEL_RE = re.compile(
    r"(?:"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"
    r"|(?i:bearer)\s+[A-Za-z0-9._\-]{8,}"
    r"|(?:sk|pk|rk|ghp|gho|ghu|xox[baprs])-[A-Za-z0-9_-]{10,}"
    r"|AIza[A-Za-z0-9_-]{16,}"
    r"|(?i:(?:token|secret|password|api_key|signing_key|master_key|authorization))\s*[:=]\s*\S+"
    r")"
)

_REDACTION_LABELS: tuple[tuple[str, str], ...] = (
    ("token", "[REDACTED_TOKEN]"),
    ("transcript", "[REDACTED_TRANSCRIPT]"),
    ("phone", "[REDACTED_PHONE]"),
    ("vin", "[REDACTED_VIN]"),
    ("plate", "[REDACTED_PLATE]"),
)


def _replace_vin(match: re.Match[str], hits: dict[str, int]) -> str:
    candidate = match.group(0)
    if any(ch.isalpha() for ch in candidate) and any(ch.isdigit() for ch in candidate):
        hits["vin"] = hits.get("vin", 0) + 1
        return "[REDACTED_VIN]"
    return candidate


def _has_vin_sentinel(text: str) -> bool:
    for m in _VIN_CANDIDATE_RE.finditer(text):
        cand = m.group(0)
        if any(ch.isalpha() for ch in cand) and any(ch.isdigit() for ch in cand):
            return True
    return False


def redact_sentinels(text: str) -> tuple[str, dict[str, int]]:
    """Redact token, transcript, phone, VIN, and Turkish plate sentinels from text."""
    hits: dict[str, int] = {}
    out = text

    out, n_tok = _TOKEN_SENTINEL_RE.subn("[REDACTED_TOKEN]", out)
    if n_tok:
        hits["token"] = n_tok

    out, n_tr = _TRANSCRIPT_SENTINEL_RE.subn("[REDACTED_TRANSCRIPT]", out)
    if n_tr:
        hits["transcript"] = n_tr

    out, n_ph = _PHONE_SENTINEL_RE.subn("[REDACTED_PHONE]", out)
    if n_ph:
        hits["phone"] = n_ph

    out = _VIN_CANDIDATE_RE.sub(lambda m: _replace_vin(m, hits), out)

    out, n_pl = _TR_PLATE_SENTINEL_RE.subn("[REDACTED_PLATE]", out)
    if n_pl:
        hits["plate"] = n_pl

    return out, hits


def contains_sentinel(text: str) -> bool:
    """Return True if any unredacted PII/secret sentinel remains in text."""
    if _TOKEN_SENTINEL_RE.search(text):
        return True
    if _TRANSCRIPT_SENTINEL_RE.search(text):
        return True
    if _PHONE_SENTINEL_RE.search(text):
        return True
    if _has_vin_sentinel(text):
        return True
    if _TR_PLATE_SENTINEL_RE.search(text):
        return True
    return False


@dataclass(frozen=True, slots=True)
class ProjectionStats:
    """Counters describing safe telemetry projection outcomes."""

    projected_count: int
    dropped_count: int
    failure_count: int
    redacted_field_count: int
    redaction_hits: Mapping[str, int]


class Projection:
    """Strict allowlist + PII/secret sentinel redactor. Drops on failure, never falls back."""

    def __init__(
        self,
        *,
        extra_allowlist: frozenset[str] = frozenset(),
        redactor: Callable[[str], tuple[str, dict[str, int]]] | None = None,
    ) -> None:
        clean_extra = frozenset(k for k in extra_allowlist if k.lower() not in FORBIDDEN_TELEMETRY_KEYS)
        self._extra_allowlist = clean_extra
        self._redactor = redactor or redact_sentinels
        self._lock = threading.Lock()
        self._projected_count = 0
        self._dropped_count = 0
        self._failure_count = 0
        self._redacted_field_count = 0
        self._redaction_hits: dict[str, int] = {name: 0 for name, _ in _REDACTION_LABELS}

    @property
    def stats(self) -> ProjectionStats:
        with self._lock:
            return ProjectionStats(
                projected_count=self._projected_count,
                dropped_count=self._dropped_count,
                failure_count=self._failure_count,
                redacted_field_count=self._redacted_field_count,
                redaction_hits=dict(self._redaction_hits),
            )

    def _record_drop(self) -> None:
        with self._lock:
            self._dropped_count += 1
            self._failure_count += 1

    def _record_success(self, redacted_fields: int, hits: dict[str, int]) -> None:
        with self._lock:
            self._projected_count += 1
            self._redacted_field_count += redacted_fields
            for k, v in hits.items():
                self._redaction_hits[k] = self._redaction_hits.get(k, 0) + v

    def _sanitize_scalar(
        self,
        value: Any,
        redacted_fields: list[int],
        total_hits: dict[str, int],
    ) -> Any:
        if value is None or isinstance(value, bool) or type(value) is int:
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("Non-finite float not permitted in telemetry projection")
            return value
        if isinstance(value, str):
            sanitized, hits = self._redactor(value)
            if not isinstance(sanitized, str):
                raise TypeError("Redactor must return str")
            if contains_sentinel(sanitized):
                raise ValueError("Post-redaction sentinel verification failed")
            if hits or sanitized != value:
                redacted_fields[0] += 1
                for k, v in hits.items():
                    total_hits[k] = total_hits.get(k, 0) + v
            return sanitized
        raise TypeError(f"Non-scalar telemetry value rejected: {type(value).__name__}")

    def _sanitize_mapping(
        self,
        data: Mapping[str, Any],
        allowlist: frozenset[str],
        redacted_fields: list[int],
        total_hits: dict[str, int],
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in data.items():
            key = str(k)
            if key.lower() in FORBIDDEN_TELEMETRY_KEYS:
                continue
            if key not in allowlist and key not in self._extra_allowlist:
                continue
            if isinstance(v, (str, int, float, bool, type(None))):
                out[key] = self._sanitize_scalar(v, redacted_fields, total_hits)
        return out

    def project(
        self,
        record: Any,
        *,
        extra_allowlist: frozenset[str] = frozenset(),
    ) -> dict[str, Any] | None:
        """Project a contract/dict into a safe, allowlisted, redacted dict or return None on failure."""
        try:
            redacted_fields = [0]
            total_hits: dict[str, int] = {}

            if isinstance(record, EventEnvelope):
                base = safe_telemetry_projection(record)
                result = self._sanitize_mapping(
                    base,
                    frozenset(base.keys()) | self._extra_allowlist | extra_allowlist,
                    redacted_fields,
                    total_hits,
                )
                meta_allow = (allowed_metadata_keys_for(record.event_type) | extra_allowlist) - FORBIDDEN_TELEMETRY_KEYS
                if record.metadata:
                    safe_meta = self._sanitize_mapping(record.metadata, meta_allow, redacted_fields, total_hits)
                    if safe_meta:
                        result["metadata"] = safe_meta
            elif isinstance(record, MetricSample):
                result = self._project_metric_internal(record, redacted_fields, total_hits)
            elif isinstance(record, ErrorInfo):
                result = self._project_error_internal(record, redacted_fields, total_hits)
            else:
                projected = safe_telemetry_projection(record)
                if not isinstance(projected, dict) or not projected:
                    raise ValueError("Record produced empty or non-dict safe projection")
                result = self._sanitize_tree(
                    projected,
                    extra_allowlist=extra_allowlist,
                    redacted_fields=redacted_fields,
                    total_hits=total_hits,
                )

            self._verify_projected_tree(result)
            self._record_success(redacted_fields[0], total_hits)
            return result
        except Exception:
            self._record_drop()
            return None

    def _project_metric_internal(
        self,
        sample: MetricSample,
        redacted_fields: list[int],
        total_hits: dict[str, int],
    ) -> dict[str, Any]:
        # Reuse M01 safe_telemetry_projection for observation_scope/reason while preserving null vs zero value.
        base = safe_telemetry_projection(sample)
        out: dict[str, Any] = {
            "name": self._sanitize_scalar(sample.name, redacted_fields, total_hits),
            "value": self._sanitize_scalar(sample.value, redacted_fields, total_hits),
            "unit": self._sanitize_scalar(sample.unit, redacted_fields, total_hits),
            "observation_scope": self._sanitize_scalar(
                base.get("observation_scope", sample.observation_scope), redacted_fields, total_hits
            ),
            "status": sample.status.value,
        }
        if sample.reason is not None:
            out["reason"] = self._sanitize_scalar(sample.reason, redacted_fields, total_hits)
        if sample.source_ref is not None:
            out["source_ref"] = self._sanitize_scalar(sample.source_ref, redacted_fields, total_hits)
        return out

    def _project_error_internal(
        self,
        err: ErrorInfo,
        redacted_fields: list[int],
        total_hits: dict[str, int],
    ) -> dict[str, Any]:
        base = safe_telemetry_projection(err)
        out: dict[str, Any] = {
            "code": self._sanitize_scalar(base.get("code", err.code), redacted_fields, total_hits),
            "category": self._sanitize_scalar(base.get("category", err.category.value), redacted_fields, total_hits),
            "retryable": self._sanitize_scalar(base.get("retryable", err.retryable.value), redacted_fields, total_hits),
        }
        if err.safe_message:
            out["safe_message"] = self._sanitize_scalar(err.safe_message, redacted_fields, total_hits)
        if err.field_name is not None:
            out["field_name"] = self._sanitize_scalar(err.field_name, redacted_fields, total_hits)
        return out

    def _sanitize_tree(
        self,
        node: Mapping[str, Any],
        *,
        extra_allowlist: frozenset[str],
        redacted_fields: list[int],
        total_hits: dict[str, int],
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in node.items():
            key = str(k)
            if key.lower() in FORBIDDEN_TELEMETRY_KEYS:
                continue
            if isinstance(v, Mapping):
                nested = self._sanitize_tree(
                    v,
                    extra_allowlist=extra_allowlist,
                    redacted_fields=redacted_fields,
                    total_hits=total_hits,
                )
                if nested:
                    out[key] = nested
            elif isinstance(v, (str, int, float, bool, type(None))):
                out[key] = self._sanitize_scalar(v, redacted_fields, total_hits)
        return out

    def _verify_projected_tree(self, node: Mapping[str, Any]) -> None:
        for k, v in node.items():
            if str(k).lower() in FORBIDDEN_TELEMETRY_KEYS:
                raise ValueError(f"Forbidden key leaked into projection: {k}")
            if isinstance(v, Mapping):
                self._verify_projected_tree(v)
            elif isinstance(v, str) and contains_sentinel(v):
                raise ValueError("Sentinel leaked into projection")
            elif isinstance(v, float) and not math.isfinite(v):
                raise ValueError("Non-finite float leaked into projection")
