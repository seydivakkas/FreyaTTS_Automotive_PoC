"""FreyaTTS Automotive Cockpit V3 — F0–F6 Pipeline Telemetri Modülü.

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
"""

import time
import uuid
from typing import Any, Literal, Optional

StageId = Literal["F0", "F1", "F2", "F3", "F4", "F5", "F6"]
StageStatus = Literal[
    "idle", "queued", "running", "completed", "failed", "cancelled", "skipped", "bypassed"
]


def make_pipeline_event(
    session_id: str,
    turn_id: int,
    stage: StageId,
    status: StageStatus,
    *,
    source: str = "live",
    duration_ms: Optional[float] = None,
    metrics: Optional[dict[str, Any]] = None,
    intermediate_data: Optional[dict[str, Any]] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> dict[str, Any]:
    """F0–F6 ortak telemetri sözleşmesine (Schema v3.0) uygun olay sözlüğü üretir."""
    ev = {
        "schema_version": "3.0",
        "event_id": str(uuid.uuid4()),
        "session_id": session_id,
        "turn_id": turn_id,
        "stage": stage,
        "status": status,
        "source": source,
        "timestamp": time.time(),
        "metrics": metrics or {},
    }
    if duration_ms is not None:
        ev["duration_ms"] = round(float(duration_ms), 2)
    if intermediate_data:
        ev["intermediate_data"] = intermediate_data
    if error_code:
        ev["error_code"] = error_code
    if error_message:
        ev["error_message"] = str(error_message)
    return ev

