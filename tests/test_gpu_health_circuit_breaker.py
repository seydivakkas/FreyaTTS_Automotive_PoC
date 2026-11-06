# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlı olarak paylaşılmıştır.

import base64
import time
import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.gpu_health_circuit_breaker import (
    CircuitBreakerConfig,
    CircuitState,
    FailoverMode,
    GpuHealthCircuitBreaker,
    gpu_health_circuit_breaker,
)
from backend.main import app


@pytest.fixture
def auth_headers(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret")
    creds = base64.b64encode(b"admin:secret").decode("ascii")
    return {"Authorization": f"Basic {creds}"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def test_breaker() -> GpuHealthCircuitBreaker:
    cfg = CircuitBreakerConfig(
        vram_threshold_percent=85.0,
        temp_threshold_c=80.0,
        latency_threshold_ms=350.0,
        consecutive_failure_limit=2,
        cooldown_seconds=0.1,
        half_open_success_target=2,
    )
    return GpuHealthCircuitBreaker(config=cfg)


def test_telemetry_probe(test_breaker: GpuHealthCircuitBreaker):
    snap = test_breaker.sample_telemetry()
    assert snap.gpu_name != ""
    assert snap.circuit_state == CircuitState.CLOSED.value
    assert snap.vram_total_mb >= 0.0
    assert snap.gpu_temperature_c > 0.0
    assert test_breaker.should_allow_gpu_task() is True


def test_record_inference_latency(test_breaker: GpuHealthCircuitBreaker):
    test_breaker.record_inference_latency(120.0)
    test_breaker.record_inference_latency(140.0)
    assert len(test_breaker.latency_history) == 2
    assert 100.0 <= test_breaker.latency_ema_ms <= 150.0


def test_trip_on_consecutive_vram_failures(test_breaker: GpuHealthCircuitBreaker):
    # Simulate high VRAM occupancy (92% >= 85%)
    test_breaker.simulate_telemetry_metrics(vram_percent=92.0)

    # Step 1: First violation
    snap1 = test_breaker.sample_telemetry()
    assert snap1.circuit_state == CircuitState.CLOSED.value
    assert test_breaker.consecutive_failures == 1
    assert test_breaker.should_allow_gpu_task() is True

    # Step 2: Second violation triggers OPEN
    snap2 = test_breaker.sample_telemetry()
    assert snap2.circuit_state == CircuitState.OPEN.value
    assert test_breaker.should_allow_gpu_task() is False
    assert test_breaker.total_trip_count == 1
    assert "VRAM doluluğu aşıldı" in test_breaker.last_trip_reason


def test_trip_on_consecutive_temperature_failures(test_breaker: GpuHealthCircuitBreaker):
    # Simulate high temperature (86°C >= 80°C)
    test_breaker.simulate_telemetry_metrics(temperature_c=86.0)

    test_breaker.sample_telemetry()
    test_breaker.sample_telemetry()

    assert test_breaker.state == CircuitState.OPEN
    assert "GPU sıcaklığı aşıldı" in test_breaker.last_trip_reason


def test_trip_on_latency_ema(test_breaker: GpuHealthCircuitBreaker):
    # Simulate high inference latency (450 ms >= 350 ms)
    test_breaker.simulate_telemetry_metrics(latency_ms=450.0)

    test_breaker.sample_telemetry()
    test_breaker.sample_telemetry()

    assert test_breaker.state == CircuitState.OPEN
    assert "ODE inferans gecikmesi aşıldı" in test_breaker.last_trip_reason


def test_instant_trip_on_cuda_oom(test_breaker: GpuHealthCircuitBreaker):
    test_breaker.record_cuda_oom_event("Out of Memory during DiT ODE solver")

    assert test_breaker.state == CircuitState.OPEN
    assert "CUDA Out of Memory" in test_breaker.last_trip_reason
    assert test_breaker.should_allow_gpu_task() is False


def test_cooldown_and_half_open_recovery(test_breaker: GpuHealthCircuitBreaker):
    # Trip breaker
    test_breaker.record_cuda_oom_event("Emergency trip")
    assert test_breaker.state == CircuitState.OPEN

    # Sleep past cooldown (cooldown_seconds is 0.1s in fixture)
    time.sleep(0.15)

    # Reset simulation metrics so it's healthy now
    test_breaker.simulate_telemetry_metrics(vram_percent=40.0, temperature_c=50.0, latency_ms=100.0)

    # First check after cooldown transitions to HALF_OPEN
    snap = test_breaker.sample_telemetry()
    assert snap.circuit_state == CircuitState.HALF_OPEN.value

    # Step 1 healthy
    test_breaker.sample_telemetry()
    # Step 2 healthy -> Target 2 reached, should transition to CLOSED
    snap_closed = test_breaker.sample_telemetry()
    assert snap_closed.circuit_state == CircuitState.CLOSED.value
    assert test_breaker.state == CircuitState.CLOSED


def test_failover_action_modes(test_breaker: GpuHealthCircuitBreaker):
    test_breaker.force_state(CircuitState.OPEN, "Test Trip")

    # 1. CPU Cache mode
    act_cache = test_breaker.get_failover_action(preferred_mode=FailoverMode.CPU_CACHE)
    assert act_cache.mode == "cpu_cache"
    assert "TelephonyAudioCachePool" in act_cache.details["cache_pool"]

    # 2. Operator Transfer mode
    act_transfer = test_breaker.get_failover_action(preferred_mode=FailoverMode.OPERATOR_TRANSFER)
    assert act_transfer.mode == "operator_transfer"
    assert act_transfer.details["target_extension"] == "1001"

    # 3. Graceful Degrade mode
    act_degrade = test_breaker.get_failover_action(preferred_mode=FailoverMode.GRACEFUL_DEGRADE)
    assert act_degrade.mode == "graceful_degrade"
    assert act_degrade.details["reduced_ode_steps"] == 16


def test_rest_api_gpu_health_endpoints(client: TestClient, auth_headers: dict):
    # 1. Telemetry endpoint
    resp_tel = client.get("/api/gpu-health/telemetry", headers=auth_headers)
    assert resp_tel.status_code == 200
    tel_data = resp_tel.json()
    assert "vram_occupancy_percent" in tel_data
    assert "circuit_state" in tel_data

    # 2. Circuit status endpoint
    resp_st = client.get("/api/gpu-health/circuit-status", headers=auth_headers)
    assert resp_st.status_code == 200
    st_data = resp_st.json()
    assert "config" in st_data
    assert "total_trip_count" in st_data

    # 3. Configure endpoint
    resp_conf = client.post(
        "/api/gpu-health/configure",
        headers=auth_headers,
        json={"vram_threshold_percent": 88.0, "temp_threshold_c": 79.0},
    )
    assert resp_conf.status_code == 200
    conf_data = resp_conf.json()
    assert conf_data["config"]["vram_threshold_percent"] == 88.0
    assert conf_data["config"]["temp_threshold_c"] == 79.0

    # 4. Simulate OOM endpoint
    resp_oom = client.post(
        "/api/gpu-health/simulate-oom",
        headers=auth_headers,
        json={"simulate_oom": True},
    )
    assert resp_oom.status_code == 200
    oom_data = resp_oom.json()
    assert oom_data["circuit_status"]["circuit_state"] == CircuitState.OPEN.value
    assert "action" in oom_data

    # 5. Reset endpoint
    resp_reset = client.post("/api/gpu-health/reset", headers=auth_headers)
    assert resp_reset.status_code == 200
    reset_data = resp_reset.json()
    assert reset_data["circuit_status"]["circuit_state"] == CircuitState.CLOSED.value

