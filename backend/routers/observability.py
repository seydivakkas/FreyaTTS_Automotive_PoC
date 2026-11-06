"""Gözlemlenebilirlik uç noktaları: GPU, SIP hattı, metrik, SLA, kilometre taşları."""

from dataclasses import asdict
from pathlib import Path
from uuid import UUID
from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
    Response,
)
from backend.gpu_health_circuit_breaker import gpu_health_circuit_breaker
from backend.sip_trunk_failover import (
    SIPTrunk,
    sip_trunk_failover_manager,
)
from backend.realtime_dashboard_metrics import dashboard_metrics_collector
from backend import milestones
from backend.schemas import (
    GPUConfigureIn,
    GPUSimulateIn,
    ReviewIn,
    SLAConfigureIn,
    SLARecordCallIn,
    TextIn,
    TrunkConfigIn,
    TrunkMaintenanceIn,
    TrunkSelectIn,
    TrunkSimulateIn,
)
from backend.deps import auth

router = APIRouter()


@router.get("/api/gpu-health/telemetry", dependencies=[Depends(auth)])
def gpu_telemetry_endpoint():
    snap = gpu_health_circuit_breaker.sample_telemetry()
    return snap.to_dict()


@router.get("/api/gpu-health/circuit-status", dependencies=[Depends(auth)])
def gpu_circuit_status_endpoint():
    return gpu_health_circuit_breaker.get_status()


@router.post("/api/gpu-health/configure", dependencies=[Depends(auth)])
def gpu_configure_endpoint(payload: GPUConfigureIn):
    gpu_health_circuit_breaker.configure(
        vram_threshold_percent=payload.vram_threshold_percent,
        temp_threshold_c=payload.temp_threshold_c,
        latency_threshold_ms=payload.latency_threshold_ms,
        cooldown_seconds=payload.cooldown_seconds,
        consecutive_failure_limit=payload.consecutive_failure_limit,
        default_failover_mode=payload.default_failover_mode,
    )
    return gpu_health_circuit_breaker.get_status()


@router.post("/api/gpu-health/simulate-oom", dependencies=[Depends(auth)])
def gpu_simulate_oom_endpoint(payload: GPUSimulateIn):
    if payload.simulate_oom:
        gpu_health_circuit_breaker.record_cuda_oom_event("Simüle Edilmiş CUDA OOM Olayı")
    else:
        gpu_health_circuit_breaker.simulate_telemetry_metrics(
            vram_percent=payload.vram_percent,
            temperature_c=payload.temperature_c,
            latency_ms=payload.latency_ms,
        )
        gpu_health_circuit_breaker.sample_telemetry()

    return {
        "status": "ok",
        "action": gpu_health_circuit_breaker.get_failover_action().to_dict(),
        "circuit_status": gpu_health_circuit_breaker.get_status(),
    }


@router.post("/api/gpu-health/reset", dependencies=[Depends(auth)])
def gpu_reset_endpoint():
    gpu_health_circuit_breaker.reset_circuit_breaker()
    return {
        "status": "ok",
        "circuit_status": gpu_health_circuit_breaker.get_status(),
    }


@router.get("/api/sip-trunks", dependencies=[Depends(auth)])
def list_sip_trunks_endpoint():
    return sip_trunk_failover_manager.list_trunks()


@router.get("/api/sip-trunks/{trunk_id}/ping", dependencies=[Depends(auth)])
def ping_sip_trunk_endpoint(trunk_id: str):
    try:
        res = sip_trunk_failover_manager.ping_trunk(trunk_id)
        return res.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/sip-trunks/select", dependencies=[Depends(auth)])
def select_sip_trunk_endpoint(payload: TrunkSelectIn):
    try:
        res = sip_trunk_failover_manager.select_best_trunk(
            destination_phone=payload.destination_phone,
            force_priority=payload.force_priority,
            exclude_trunk_ids=payload.exclude_trunks,
        )
        return res.to_dict()
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/api/sip-trunks/simulate-outage", dependencies=[Depends(auth)])
def simulate_trunk_outage_endpoint(payload: TrunkSimulateIn):
    sip_trunk_failover_manager.simulate_trunk_outage(payload.trunk_id, outage=payload.outage)
    t = sip_trunk_failover_manager.get_trunk(payload.trunk_id)
    if not t:
        raise HTTPException(status_code=404, detail="Trunk not found")
    return {"status": "ok", "trunk": t.to_dict()}


@router.post("/api/sip-trunks/maintenance", dependencies=[Depends(auth)])
def trunk_maintenance_endpoint(payload: TrunkMaintenanceIn):
    sip_trunk_failover_manager.set_trunk_maintenance(payload.trunk_id, maintenance=payload.maintenance)
    t = sip_trunk_failover_manager.get_trunk(payload.trunk_id)
    if not t:
        raise HTTPException(status_code=404, detail="Trunk not found")
    return {"status": "ok", "trunk": t.to_dict()}


@router.post("/api/sip-trunks/configure", dependencies=[Depends(auth)])
def configure_sip_trunk_endpoint(payload: TrunkConfigIn):
    new_trunk = SIPTrunk(
        trunk_id=payload.trunk_id,
        name=payload.name,
        host=payload.host,
        port=payload.port,
        transport=payload.transport,
        priority=payload.priority,
        weight=payload.weight,
        max_channels=payload.max_channels,
    )
    sip_trunk_failover_manager.add_or_update_trunk(new_trunk)
    return {"status": "ok", "trunk": new_trunk.to_dict()}


@router.get("/metrics", dependencies=[Depends(auth)])
def prometheus_metrics_endpoint():
    """Prometheus text exposition formatı (version 0.0.4) ile anlık sistem telemetrisi."""
    content = dashboard_metrics_collector.generate_prometheus_metrics_text()
    return Response(
        content=content,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/api/sla/status", dependencies=[Depends(auth)])
def sla_status_endpoint():
    """Canlı kurumsal SLA uyumluluk durumu, ihlal kontrolleri ve skoru."""
    report = dashboard_metrics_collector.evaluate_sla_status()
    return report.to_dict()


@router.get("/api/dashboard/live-summary", dependencies=[Depends(auth)])
def dashboard_live_summary_endpoint():
    """Grafana ve web arayüzleri için konsolide anlık sistem özeti."""
    return dashboard_metrics_collector.get_live_dashboard_summary()


@router.post("/api/metrics/record-call", dependencies=[Depends(auth)])
def record_call_metrics_endpoint(payload: SLARecordCallIn):
    """Çağrı tamamlandığında telemetri ve kalite metriklerini kaydeder."""
    dashboard_metrics_collector.record_call_end(
        success=payload.success,
        duration_sec=payload.duration_sec,
        packet_loss_pct=payload.packet_loss_pct,
        jitter_ms=payload.jitter_ms,
        csat_score=payload.csat_score,
        queue_wait_sec=payload.queue_wait_sec,
        converted_to_appointment=payload.converted_to_appointment,
    )
    return {"status": "ok", "sla": dashboard_metrics_collector.evaluate_sla_status().to_dict()}


@router.post("/api/sla/configure", dependencies=[Depends(auth)])
def configure_sla_endpoint(payload: SLAConfigureIn):
    """SLA kurallarını ve eşik değerlerini dinamik günceller."""
    cfg = dashboard_metrics_collector.sla_config
    if payload.max_p95_latency_ms is not None:
        cfg.max_p95_latency_ms = payload.max_p95_latency_ms
    if payload.min_call_answer_rate_pct is not None:
        cfg.min_call_answer_rate_pct = payload.min_call_answer_rate_pct
    if payload.min_mos_score is not None:
        cfg.min_mos_score = payload.min_mos_score
    if payload.max_packet_loss_pct is not None:
        cfg.max_packet_loss_pct = payload.max_packet_loss_pct
    if payload.max_gpu_vram_pct is not None:
        cfg.max_gpu_vram_pct = payload.max_gpu_vram_pct
    if payload.max_gpu_temp_c is not None:
        cfg.max_gpu_temp_c = payload.max_gpu_temp_c
    if payload.max_queue_wait_sec is not None:
        cfg.max_queue_wait_sec = payload.max_queue_wait_sec

    return {"status": "ok", "config": asdict(cfg), "sla": dashboard_metrics_collector.evaluate_sla_status().to_dict()}


@router.get("/api/milestones/overview", dependencies=[Depends(auth)])
def milestone_overview():
    from automotive_voice.m11.acceptance import summary

    acceptance = summary(Path("data/m11/current"))
    manifest = __import__("json").loads(
        Path("docs/milestones/import-manifest.json").read_text(encoding="utf8")
    )
    return {
        "archive": manifest["archive"],
        "source_sha256": manifest["archive_sha256"],
        "imported_files": len(manifest["files"]),
        "live_components": [
            "M01 session authority",
            "M03 booking state machine",
            "M06 PCM media contract",
            "M07 circuit breakers",
            "M10 durable journal",
            "M04/M05 text review",
            "M08 pronunciation review",
        ],
        "physical_acceptance": acceptance["overall"],
        "physical_gates": acceptance["gates"],
        "synthetic_adapters_in_live_path": False,
    }


@router.post("/api/milestones/inspect", dependencies=[Depends(auth)])
def milestone_inspect(body: TextIn):
    try:
        return milestones.inspect_text(body.text)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/api/milestones/pronunciation", dependencies=[Depends(auth)])
def pronunciation_items():
    return milestones.reviews().items()


@router.post("/api/milestones/pronunciation", dependencies=[Depends(auth)])
def pronunciation_review(body: ReviewIn):
    try:
        return milestones.reviews().decide(
            body.annotation_id,
            body.decision,
            reviewer=body.reviewer,
            reason_code=body.reason_code,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/api/milestones/timeline/{id}", dependencies=[Depends(auth)])
def milestone_timeline(id: UUID):
    return milestones.timeline(str(id))
