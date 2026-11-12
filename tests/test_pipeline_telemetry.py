"""FreyaTTS Automotive Cockpit V3 — Telemetri Sözleşmesi Birim Testleri.

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
"""

import pytest
from backend.pipeline_telemetry import make_pipeline_event, StageId


def test_pipeline_event_schema_v3():
    ev = make_pipeline_event(
        session_id="test-session-123",
        turn_id=1,
        stage="F0",
        status="completed",
        source="live",
        duration_ms=3.14,
        metrics={"ambient_dbfs": -42.0},
        intermediate_data={"filter": "Butterworth"},
    )
    assert ev["schema_version"] == "3.0"
    assert ev["session_id"] == "test-session-123"
    assert ev["turn_id"] == 1
    assert ev["stage"] == "F0"
    assert ev["status"] == "completed"
    assert ev["source"] == "live"
    assert ev["duration_ms"] == 3.14
    assert ev["metrics"]["ambient_dbfs"] == -42.0
    assert ev["intermediate_data"]["filter"] == "Butterworth"
    assert "event_id" in ev
    assert "timestamp" in ev


def test_all_f0_to_f6_stages_valid():
    stages: list[StageId] = ["F0", "F1", "F2", "F3", "F4", "F5", "F6"]
    for s in stages:
        ev = make_pipeline_event("sess-1", 1, s, "running")
        assert ev["stage"] == s
        assert ev["status"] == "running"

