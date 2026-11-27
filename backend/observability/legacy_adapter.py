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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from backend.core.contracts.common import (
    CONTRACT_SCHEMA_VERSION,
    ErrorCategory,
    ErrorInfo,
    EventEnvelope,
    MetricSample,
    MetricStatus,
    Retryability,
)
from backend.core.contracts.validation import ConversionResult, require_safe_id, require_strict_int
from backend.observability.projection import Projection

_VALID_STAGES = frozenset({"F0", "F1", "F2", "F3", "F4", "F5", "F6"})
_VALID_STATUSES = frozenset({
    "idle",
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "skipped",
    "bypassed",
})


@dataclass(frozen=True, slots=True)
class AdaptedLegacyTelemetry:
    """Typed M04 bridge result for a legacy pipeline_telemetry v3.0 event dictionary."""

    envelope: EventEnvelope
    stage: str
    status: str
    source: str
    legacy_event_id: str | None
    metrics: tuple[MetricSample, ...]
    error: ErrorInfo | None
    safe_projection: dict[str, Any]


def _unix_to_utc_iso(ts: Any) -> str | None:
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None
    val = float(ts)
    if not math.isfinite(val) or val < 0:
        return None
    try:
        dt = datetime.fromtimestamp(val, tz=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError):
        return None


def _infer_unit(metric_name: str) -> str:
    if metric_name.endswith("_ms"):
        return "ms"
    if metric_name.endswith("_rate"):
        return "hz"
    if metric_name.endswith("_bytes"):
        return "bytes"
    if metric_name == "dbfs":
        return "dbfs"
    return "unit"


def _convert_metrics(
    raw_metrics: Any,
    duration_ms: Any,
    warnings: list[str],
) -> tuple[MetricSample, ...]:
    samples: list[MetricSample] = []

    if duration_ms is not None:
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, (int, float)) or not math.isfinite(float(duration_ms)):
            warnings.append("dropped_invalid_duration_ms")
        else:
            samples.append(
                MetricSample(
                    name="stage_duration_ms",
                    value=float(duration_ms),
                    unit="ms",
                    observation_scope="SERVER",
                    status=MetricStatus.MEASURED,
                    source_ref="legacy.pipeline_telemetry.v3",
                )
            )

    if isinstance(raw_metrics, Mapping):
        for raw_key, raw_val in raw_metrics.items():
            key = str(raw_key)
            try:
                require_safe_id(key, "metric_name")
            except ValueError:
                warnings.append(f"skipped_unsafe_metric_name:{key}")
                continue
            unit = _infer_unit(key)
            if raw_val is None:
                samples.append(
                    MetricSample(
                        name=key,
                        value=None,
                        unit=unit,
                        observation_scope="SERVER",
                        status=MetricStatus.UNAVAILABLE,
                        reason="legacy_null_metric",
                        source_ref="legacy.pipeline_telemetry.v3",
                    )
                )
            elif isinstance(raw_val, bool):
                samples.append(
                    MetricSample(
                        name=key,
                        value=1.0 if raw_val else 0.0,
                        unit="bool",
                        observation_scope="SERVER",
                        status=MetricStatus.MEASURED,
                        source_ref="legacy.pipeline_telemetry.v3",
                    )
                )
            elif isinstance(raw_val, (int, float)):
                fval = float(raw_val)
                if not math.isfinite(fval):
                    warnings.append(f"dropped_non_finite_metric:{key}")
                    continue
                samples.append(
                    MetricSample(
                        name=key,
                        value=fval,
                        unit=unit,
                        observation_scope="SERVER",
                        status=MetricStatus.MEASURED,
                        source_ref="legacy.pipeline_telemetry.v3",
                    )
                )
            else:
                warnings.append(f"skipped_non_numeric_metric:{key}")

    return tuple(samples)


def adapt_legacy_event(
    legacy_event: Mapping[str, Any],
    *,
    monotonic_ns: int = 0,
    clock_domain: str = "legacy.synthesized",
    sequence: int = 0,
    projector: Projection | None = None,
) -> ConversionResult[AdaptedLegacyTelemetry]:
    """Bridge a backend/pipeline_telemetry.py v3.0 event dict into a safe M04 projection."""
    active_projector = projector or Projection()
    warnings: list[str] = []
    missing: list[str] = []

    if not isinstance(legacy_event, Mapping):
        return ConversionResult(value=None, error="legacy_event must be a mapping", source_ref="legacy.v3")

    if legacy_event.get("schema_version") != "3.0":
        return ConversionResult(
            value=None,
            error=f"Unsupported legacy schema_version: {legacy_event.get('schema_version')!r}",
            source_ref="legacy.v3",
        )

    for req in ("session_id", "turn_id", "stage", "status"):
        if req not in legacy_event:
            missing.append(req)
    if missing:
        return ConversionResult(
            value=None,
            missing_fields=tuple(missing),
            error="Missing required legacy v3.0 fields",
            source_ref="legacy.v3",
        )

    stage = str(legacy_event["stage"])
    status = str(legacy_event["status"])
    if stage not in _VALID_STAGES:
        return ConversionResult(value=None, error=f"Invalid legacy stage: {stage!r}", source_ref="legacy.v3")
    if status not in _VALID_STATUSES:
        return ConversionResult(value=None, error=f"Invalid legacy status: {status!r}", source_ref="legacy.v3")

    try:
        session_id = require_safe_id(legacy_event["session_id"], "session_id")
        turn_id = require_strict_int(legacy_event["turn_id"], "turn_id", minimum=0)
        require_strict_int(monotonic_ns, "monotonic_ns", minimum=0)
        require_strict_int(sequence, "sequence", minimum=0)
    except ValueError as exc:
        return ConversionResult(value=None, error=str(exc), source_ref="legacy.v3")

    source = str(legacy_event.get("source") or "legacy")
    raw_event_id = legacy_event.get("event_id")
    trace_id: str | None = None
    if isinstance(raw_event_id, str):
        try:
            trace_id = require_safe_id(raw_event_id, "event_id")
        except ValueError:
            warnings.append("dropped_unsafe_event_id")

    lossy = False
    if "intermediate_data" in legacy_event and legacy_event["intermediate_data"] is not None:
        lossy = True
        warnings.append("dropped_intermediate_data")

    utc_timestamp = _unix_to_utc_iso(legacy_event.get("timestamp"))
    if legacy_event.get("timestamp") is not None and utc_timestamp is None:
        warnings.append("dropped_invalid_timestamp")

    metadata: dict[str, Any] = {
        "stage": stage,
        "status": status,
        "source": source,
    }
    if isinstance(legacy_event.get("duration_ms"), (int, float)) and not isinstance(legacy_event.get("duration_ms"), bool):
        dval = float(legacy_event["duration_ms"])
        if math.isfinite(dval):
            metadata["duration_ms"] = dval
    if legacy_event.get("error_code"):
        metadata["error_code"] = str(legacy_event["error_code"])

    envelope = EventEnvelope(
        schema_version=CONTRACT_SCHEMA_VERSION,
        event_type=f"pipeline.stage.{stage.lower()}",
        session_id=session_id,
        trace_id=trace_id,
        turn_id=turn_id,
        generation_id=None,
        sequence=sequence,
        monotonic_ns=monotonic_ns,
        clock_domain=clock_domain,
        producer="legacy.pipeline_telemetry.v3",
        utc_timestamp=utc_timestamp,
        metadata=metadata,
    )

    metric_samples = _convert_metrics(legacy_event.get("metrics"), legacy_event.get("duration_ms"), warnings)

    error_info: ErrorInfo | None = None
    err_code = legacy_event.get("error_code")
    err_msg = legacy_event.get("error_message")
    if err_code or err_msg:
        safe_code = str(err_code) if err_code else "LEGACY_STAGE_ERROR"
        try:
            require_safe_id(safe_code, "error_code")
        except ValueError:
            safe_code = "LEGACY_STAGE_ERROR"
            warnings.append("sanitized_unsafe_error_code")
        raw_err = ErrorInfo(
            code=safe_code,
            category=ErrorCategory.PROVIDER,
            retryable=Retryability.UNKNOWN,
            safe_message=str(err_msg or ""),
        )
        proj_err = active_projector.project(raw_err)
        if proj_err is None:
            lossy = True
            warnings.append("dropped_unsafe_error")
            error_info = ErrorInfo(
                code=safe_code,
                category=ErrorCategory.PROVIDER,
                retryable=Retryability.UNKNOWN,
                safe_message="",
            )
        else:
            error_info = ErrorInfo(
                code=str(proj_err["code"]),
                category=ErrorCategory(proj_err["category"]),
                retryable=Retryability(proj_err["retryable"]),
                safe_message=str(proj_err.get("safe_message", "")),
            )

    safe_proj = active_projector.project(envelope)
    if safe_proj is None:
        return ConversionResult(
            value=None,
            warnings=tuple(warnings),
            error="Projection dropped legacy event",
            lossy=True,
            source_ref="legacy.v3",
        )

    projected_metrics: list[dict[str, Any]] = []
    for sample in metric_samples:
        pm = active_projector.project(sample)
        if pm is None:
            lossy = True
            warnings.append(f"dropped_metric_projection:{sample.name}")
        else:
            projected_metrics.append(pm)
    if projected_metrics:
        safe_proj["metrics"] = projected_metrics
    if error_info is not None:
        pe = active_projector.project(error_info)
        if pe is not None:
            safe_proj["error"] = pe

    adapted = AdaptedLegacyTelemetry(
        envelope=envelope,
        stage=stage,
        status=status,
        source=source,
        legacy_event_id=trace_id,
        metrics=metric_samples,
        error=error_info,
        safe_projection=safe_proj,
    )
    return ConversionResult(
        value=adapted,
        warnings=tuple(warnings),
        lossy=lossy,
        source_ref="legacy.v3",
    )


def legacy_event_to_safe_projection(
    legacy_event: Mapping[str, Any],
    *,
    monotonic_ns: int = 0,
    clock_domain: str = "legacy.synthesized",
    sequence: int = 0,
    projector: Projection | None = None,
) -> dict[str, Any] | None:
    """Convenience helper returning only the safe projected dict (or None on drop/error)."""
    res = adapt_legacy_event(
        legacy_event,
        monotonic_ns=monotonic_ns,
        clock_domain=clock_domain,
        sequence=sequence,
        projector=projector,
    )
    if not res.ok or res.value is None:
        return None
    return res.value.safe_projection
