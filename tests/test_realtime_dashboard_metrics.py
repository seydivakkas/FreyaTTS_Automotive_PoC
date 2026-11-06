# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlı olarak paylaşılmıştır.

import base64
import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.realtime_dashboard_metrics import (
    RealtimeDashboardMetricsCollector,
    SLAComplianceLevel,
    SLAConfig,
    calculate_itu_mos,
    dashboard_metrics_collector,
)


@pytest.fixture
def auth_headers(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret")
    creds = base64.b64encode(b"admin:secret").decode("ascii")
    return {"Authorization": f"Basic {creds}"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def test_collector() -> RealtimeDashboardMetricsCollector:
    cfg = SLAConfig(
        max_p95_latency_ms=250.0,
        min_call_answer_rate_pct=95.0,
        min_mos_score=4.0,
        max_packet_loss_pct=1.0,
        max_gpu_vram_pct=90.0,
        max_gpu_temp_c=82.0,
        max_queue_wait_sec=30.0,
    )
    return RealtimeDashboardMetricsCollector(sla_config=cfg)


def test_itu_mos_calculation():
    # 1. Ideal line conditions: RTT 20ms, Jitter 2ms, Loss 0%
    mos_ideal = calculate_itu_mos(rtt_ms=20.0, jitter_ms=2.0, packet_loss_pct=0.0)
    assert mos_ideal >= 4.2

    # 2. Impaired line: RTT 250ms, Jitter 25ms, Loss 4%
    mos_bad = calculate_itu_mos(rtt_ms=250.0, jitter_ms=25.0, packet_loss_pct=4.0)
    assert mos_bad < 3.8
    assert mos_bad < mos_ideal


def test_record_call_and_percentiles(test_collector: RealtimeDashboardMetricsCollector):
    # Initial active calls
    assert test_collector.active_calls == 0

    test_collector.record_call_start(direction="inbound")
    assert test_collector.active_calls == 1
    assert test_collector.total_calls_inbound == 1

    test_collector.record_call_end(
        success=True,
        duration_sec=45.0,
        packet_loss_pct=0.1,
        jitter_ms=1.8,
        csat_score=4.9,
        queue_wait_sec=5.0,
        converted_to_appointment=True,
    )
    assert test_collector.active_calls == 0
    assert test_collector.total_calls_completed == 1

    # Record TTS inference latencies
    test_collector.record_tts_inference(duration_audio_sec=2.0, inference_time_sec=0.15)
    test_collector.record_tts_inference(duration_audio_sec=3.0, inference_time_sec=0.22)

    pcts = test_collector.get_latency_percentiles()
    assert pcts["p50"] > 0.0
    assert pcts["p95"] >= pcts["p50"]
    assert pcts["p99"] >= pcts["p95"]


def test_evaluate_sla_status(test_collector: RealtimeDashboardMetricsCollector):
    # 1. Default state should be HEALTHY or WARNING
    report = test_collector.evaluate_sla_status()
    assert report.total_checks == 7
    assert report.compliance_score_pct >= 70.0
    assert report.overall_status in (SLAComplianceLevel.HEALTHY.value, SLAComplianceLevel.WARNING.value)

    # 2. Strict latency threshold to force a BREACH
    test_collector.sla_config.max_p95_latency_ms = 10.0  # Unrealistic 10ms target
    report_breached = test_collector.evaluate_sla_status()
    assert report_breached.breached_checks >= 1
    lat_check = next(c for c in report_breached.checks if c.metric_name == "tts_p95_latency")
    assert lat_check.is_breached is True
    assert lat_check.status == "FAIL"


def test_generate_prometheus_metrics_text(test_collector: RealtimeDashboardMetricsCollector):
    text = test_collector.generate_prometheus_metrics_text()
    assert isinstance(text, str)
    assert len(text) > 100

    # Key metric tags
    assert "# HELP freya_active_calls" in text
    assert "# TYPE freya_active_calls gauge" in text
    assert "freya_active_calls " in text

    assert "freya_calls_total{direction=\"inbound\"}" in text
    assert "freya_audiosocket_packet_loss_ratio " in text
    assert "freya_audiosocket_jitter_ms " in text
    assert "freya_sip_mos_score " in text
    assert "freya_tts_rtf " in text
    assert "freya_tts_inference_latency_ms{quantile=\"0.95\"}" in text
    assert "freya_gpu_vram_occupancy_ratio " in text
    assert "freya_gpu_temperature_celsius " in text
    assert "freya_gpu_circuit_breaker_state " in text
    assert "freya_audio_cache_hit_rate_percent " in text
    assert "freya_customer_csat_average " in text
    assert "freya_sip_trunk_status{" in text
    assert "freya_sip_trunk_rtt_ms{" in text


def test_get_live_dashboard_summary(test_collector: RealtimeDashboardMetricsCollector):
    summary = test_collector.get_live_dashboard_summary()
    assert "timestamp" in summary
    assert "sla" in summary
    assert "telephony" in summary
    assert "tts_performance" in summary
    assert "hardware" in summary
    assert "trunks" in summary
    assert "audio_cache" in summary
    assert "crm_kpis" in summary

    assert summary["sla"]["total_checks"] == 7
    assert summary["crm_kpis"]["csat_average"] > 0.0


def test_rest_api_metrics_endpoints(client: TestClient, auth_headers: dict):
    # 1. Prometheus /metrics endpoint (public or authenticated)
    prom_resp = client.get("/metrics")
    assert prom_resp.status_code == 200
    assert "text/plain" in prom_resp.headers["content-type"]
    assert "freya_active_calls" in prom_resp.text
    assert "freya_sip_mos_score" in prom_resp.text

    # 2. SLA status endpoint
    sla_resp = client.get("/api/sla/status", headers=auth_headers)
    assert sla_resp.status_code == 200
    sla_data = sla_resp.json()
    assert "compliance_score_pct" in sla_data
    assert "checks" in sla_data
    assert len(sla_data["checks"]) == 7

    # 3. Live dashboard summary endpoint
    dash_resp = client.get("/api/dashboard/live-summary", headers=auth_headers)
    assert dash_resp.status_code == 200
    dash_data = dash_resp.json()
    assert "sla" in dash_data
    assert "telephony" in dash_data
    assert "hardware" in dash_data

    # 4. Record call metrics endpoint
    rec_resp = client.post(
        "/api/metrics/record-call",
        headers=auth_headers,
        json={
            "success": True,
            "duration_sec": 75.0,
            "packet_loss_pct": 0.2,
            "jitter_ms": 2.5,
            "csat_score": 4.8,
            "queue_wait_sec": 12.0,
            "converted_to_appointment": True,
        },
    )
    assert rec_resp.status_code == 200
    assert rec_resp.json()["status"] == "ok"

    # 5. Configure SLA endpoint
    conf_resp = client.post(
        "/api/sla/configure",
        headers=auth_headers,
        json={"max_p95_latency_ms": 280.0, "min_mos_score": 4.05},
    )
    assert conf_resp.status_code == 200
    conf_data = conf_resp.json()
    assert conf_data["config"]["max_p95_latency_ms"] == 280.0
    assert conf_data["config"]["min_mos_score"] == 4.05

