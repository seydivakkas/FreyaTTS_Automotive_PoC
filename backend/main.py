import asyncio
import io
import json
import os
import secrets
import time
from dataclasses import asdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import UUID
from typing import Any, Literal, List, Dict, Union, Optional
import httpx
import soundfile as sf
import numpy as np
from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    WebSocket,
    WebSocketDisconnect,
    Response,
    UploadFile,
    File,
    Form,
    Request,
)
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, AwareDatetime
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from backend.config import settings
from backend.db import (
    Session,
    Vehicle,
    Quote,
    Slot,
    Appointment,
    Conversation,
    Turn,
    book,
    CorporateAccount,
    CorporateLedger,
    record_payment,
    InspectionReport,
    NotificationOutbox,
    OutboundCall,
    VehicleDiagnostic,
    InspectionLift,
    InspectionQueue,
    ABExperiment,
    ABAssignment,
    OperatorTransfer,
    WhatsAppMessage,
    CallAnalytics,
    RuhsatScan,
    VehicleValuation,
    InspectionBay,
    Technician,
    BaySchedule,
    AudioArchive,
)
from backend.lift_bay_capacity_scheduler import (
    BAY_TYPES,
    PACKAGE_STAGE_ROUTING,
    STAGE_DEFINITIONS,
    CapacityCheckResult,
    cancel_appointment_schedules,
    check_multi_stage_bay_capacity,
    get_bay_station_analytics,
    list_bay_schedules,
    list_bays,
    list_technicians,
    schedule_multi_stage_appointment,
    set_bay_status,
    set_technician_status,
)
from backend.semantic_turn_detector import (
    DISCOURSE_MARKERS_UNFINISHED_MULTI,
    DISCOURSE_MARKERS_UNFINISHED_SINGLE,
    POSTPOSITIONS_INCOMPLETE,
    SemanticAnalysisResult,
    SemanticTurnDetector,
    TurnDecision,
    analyze_semantic_completeness,
)
from backend.emotion_prosody_adapter import (
    EmotionCategory,
    EmotionProfile,
    AdaptedProsodyPlan,
    EmotionProsodyAdapter,
    emotion_prosody_adapter,
)
from backend.pause_breath_cleaner import (
    BreathCleaningResult,
    PauseBreathCleaner,
    TelephonyAudioCachePool,
    TOP_25_AUTOMOTIVE_PHRASES,
    pause_breath_cleaner,
    telephony_audio_cache,
)
from backend.audio_archive_compliance import (
    ArchiveCodec,
    ArchiveResult,
    AudioArchiveComplianceEngine,
    VerificationResult,
    align_stereo_channels,
    audio_archive_engine,
)
from backend.gpu_health_circuit_breaker import (
    CircuitBreakerConfig,
    CircuitState,
    FailoverAction,
    FailoverMode,
    GpuHealthCircuitBreaker,
    GpuTelemetrySnapshot,
    gpu_health_circuit_breaker,
)
from backend.sip_trunk_failover import (
    PingResult,
    SIPTrunk,
    SIPTrunkFailoverManager,
    TrunkSelectionResult,
    TrunkStatus,
    sip_trunk_failover_manager,
)
from backend.realtime_dashboard_metrics import (
    RealtimeDashboardMetricsCollector,
    SLACheckItem,
    SLAComplianceLevel,
    SLAConfig,
    SLAReport,
    calculate_itu_mos,
    dashboard_metrics_collector,
)
from backend.dynamic_valuation_calculator import (
    calculate_and_save_valuation,
    calculate_dynamic_valuation,
    list_vehicle_valuations,
    parse_spoken_valuation_query,
)
from backend.whatsapp_webhook import (
    process_inbound_text,
    process_inbound_voice,
    process_inbound_image,
    list_whatsapp_messages,
)
from backend.post_call_analytics import (
    analyze_conversation_transcript,
    evaluate_and_save_call_analytics,
    get_analytics_summary_stats,
)
from backend.vin_ruhsat_decoder import (
    decode_phonetic_spelling,
    decode_ruhsat_text,
    process_inbound_ruhsat_image,
)
from backend.redaction_kvkk_guard import (
    KVKKGuard,
    default_kvkk_guard,
    is_valid_luhn,
    is_valid_tckn,
    is_valid_tr_iban,
    mask_credit_card,
    mask_email,
    mask_iban,
    mask_phone,
    mask_tckn,
    redact_audio,
    redact_dialogue_turns,
    redact_text,
)
from backend.transfer import (
    FALLBACK_AI_PROMPT,
    TRANSFER_ANNOUNCEMENT,
    generate_screen_pop_headers,
    generate_whisper_text,
    initiate_operator_transfer,
    accept_operator_transfer,
    decline_operator_transfer,
    handle_operator_dtmf,
    check_transfer_timeouts,
    list_transfers,
)
from backend.ab_testing import (
    PROMPT_TEMPLATES,
    GREETING_TEMPLATES,
    TTS_SEED_PRESETS,
    seed_default_experiment,
    get_all_experiments,
    get_experiment_by_id,
    create_experiment,
    set_experiment_status,
    get_experiment_report,
)
from backend.queue_lift import (
    PACKAGE_DEFINITIONS,
    get_all_lifts,
    add_lift,
    set_lift_status,
    assign_lift,
    release_lift,
    enqueue_vehicle,
    get_queue,
    call_next_queue_item,
    get_lift_capacity_status,
    check_slot_lift_capacity,
)
from backend.notifications import (
    dispatch_pending_notifications,
    retry_notification,
    queue_inspection_delivery_notifications,
)
from backend.report_generator import generate_inspection_pdf
from backend.analytics import (
    get_analytics_overview,
    get_follow_up_conversations,
    resolve_conversation,
    reopen_conversation,
)
from backend.diagnostics import (
    DTC_REGISTRY,
    lookup_dtc,
    calculate_maintenance_schedule,
    ingest_vehicle_telemetry,
    trigger_proactive_diagnostic_call,
    trigger_proactive_diagnostic_sms,
    resolve_diagnostic,
)
from backend.technician_dictation import (
    parse_technician_dictation,
    apply_dictation_to_report,
)
from backend.outbound import (
    initiate_outbound_call,
    complete_outbound_call,
    cancel_outbound_call,
    get_outbound_stats,
)
from backend.outbound_dialer import (
    campaign_dialer,
    detect_turkish_amd,
    AMDResult,
)
from backend.ami import get_ami_client
from backend.vin import validate_vin
from backend.acoustic_evaluation import load_latest_report
from backend.models import models
from backend.text import normalize
from backend.normalizer_rules import (
    get_lexicon_entries,
    set_lexicon_term,
    delete_lexicon_term,
    reset_to_base_lexicon,
)
from backend.session import VoiceSession, active
from backend.telephony import connection
from backend.audiosocket_server import orchestrator, TwoStageBargeInController
from backend.websocket_adapter import chan_ws_adapter
from backend.unified_server import unified_server
from backend.automotive_frontend import automotive_frontend
from backend.sft_leyla import (
    sft_manager,
    LeylaSFTConfig,
    lora_manager,
    FreyaCrossAttentionLoRAConfig,
)
from backend.qa_telemetry_operator import (
    realtime_turn_collector,
    operator_panel,
    abc_evaluator,
    m11_gate,
    VariantType,
)
from backend import milestones

security = HTTPBasic()
tickets = {}


def auth(credentials: HTTPBasicCredentials = Depends(security)):
    if not settings.admin_password:
        raise HTTPException(503, "ADMIN_PASSWORD ayarlanmalı")
    if not (
        secrets.compare_digest(credentials.username.encode(), b"admin")
        and secrets.compare_digest(
            credentials.password.encode(), settings.admin_password.encode()
        )
    ):
        raise HTTPException(
            401, "Geçersiz giriş", headers={"WWW-Authenticate": "Basic"}
        )


@asynccontextmanager
async def lifespan(app):
    await milestones.recover_abandoned()
    with Session() as db:
        db.query(Conversation).filter_by(status="active").update(
            {"status": "follow_up"}
        )
        seed_default_experiment(db)
        db.commit()
    server = await asyncio.start_server(
        connection, settings.audiosocket_host, settings.audiosocket_port
    )
    chan_ws_server = None
    if settings.chan_websocket_enabled:
        try:
            chan_ws_server = await chan_ws_adapter.start_standalone_server(
                settings.chan_websocket_host, settings.chan_websocket_port
            )
        except Exception:
            pass

    async def cleanup():
        while True:
            for p in (settings.data_dir / "recordings").glob("*.wav"):
                if p.stat().st_mtime < time.time() - settings.retention_days * 86400:
                    p.unlink()
            await asyncio.sleep(3600)

    task = asyncio.create_task(cleanup())
    yield
    if chan_ws_server:
        try:
            await chan_ws_adapter.stop_standalone_server()
        except Exception:
            pass
    server.close()
    await server.wait_closed()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="Freya Otomotiv Asistanı", lifespan=lifespan)


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class DSPProcessIn(BaseModel):
    audio_base64: str = Field(min_length=1)
    apply_de_esser: bool = Field(default=True)
    inject_comfort_noise: bool = Field(default=True)


class SFTCorpusIn(BaseModel):
    count: int = Field(default=50, ge=5, le=500)


class SFTConfigureIn(BaseModel):
    learning_rate: float = Field(default=2e-6, ge=1e-7, le=1e-4)
    min_steps: int = Field(default=75, ge=10, le=5000)
    max_steps: int = Field(default=1000, ge=75, le=20000)
    f0_max_drift_hz: float = Field(default=2.3, ge=0.5, le=10.0)


class SFTTrainIn(BaseModel):
    steps: int = Field(default=10, ge=1, le=200)


class SFTLoRAConfigureIn(BaseModel):
    r: int = Field(default=16, ge=4, le=64)
    lora_alpha: int = Field(default=32, ge=8, le=128)
    lora_dropout: float = Field(default=0.05, ge=0.0, le=0.5)
    learning_rate: float = Field(default=2e-5, ge=1e-6, le=1e-4)
    batch_size: int = Field(default=1, ge=1, le=4)
    grad_accum: int = Field(default=8, ge=1, le=32)


class SFTLoRABenchmarkIn(BaseModel):
    steps: int = Field(default=5, ge=1, le=20)
    total_target_steps: int = Field(default=1000, ge=50, le=10000)


class VehicleIn(BaseModel):
    description: str = Field(min_length=2, max_length=200)
    plate: str = Field(default="", max_length=20)
    vin: str = Field(default="", max_length=17)


class VehicleUpdateIn(BaseModel):
    description: str | None = Field(default=None, min_length=2, max_length=200)
    plate: str | None = Field(default=None, max_length=20)
    vin: str | None = Field(default=None, max_length=17)


class InspectionReportIn(BaseModel):
    summary: str = Field(min_length=5, max_length=1000)
    mileage_km: int = Field(default=0, ge=0)
    score: int = Field(default=100, ge=0, le=100)
    appointment_id: str | None = None
    technician_name: str = "Uzman Teknisyen"
    findings: dict[str, Any] = Field(default_factory=dict)
    photos: list[dict[str, Any]] = Field(default_factory=list)


class ConversationResolveIn(BaseModel):
    notes: str = Field(default="", max_length=1000)


class TelemetryIngestIn(BaseModel):
    current_km: int = Field(default=0, ge=0)
    dtc_codes: list[str] = Field(default_factory=list)
    source: str = "obd_dongle"
    owner_name: str = ""
    owner_phone: str = ""


class DictationTextIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    report_id: str | None = None
    vehicle_id: str | None = None
    technician_name: str | None = "Uzman Teknisyen"


class ProactiveActionIn(BaseModel):
    phone: str = ""


class QuoteIn(BaseModel):
    vehicle_id: str
    amount_kurus: int = Field(gt=0, le=10**12)


class SlotIn(BaseModel):
    starts_at: AwareDatetime
    duration_minutes: int = Field(default=30, ge=5, le=480)


class HotwordsIn(BaseModel):
    words: list[str] = Field(max_length=100)


class LexiconTermIn(BaseModel):
    term: str = Field(min_length=1, max_length=100)
    spoken: str = Field(min_length=1, max_length=160)
    category: str | None = Field(default="custom", max_length=50)


class CorporateAccountIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    tax_id: str = Field(min_length=10, max_length=11)
    phone: str = Field(default="", max_length=20)
    credit_limit_kurus: int = Field(default=5000000, gt=0)
    discount_percent: int = Field(default=10, ge=0, le=100)
    active: bool = True


class CorporateAccountUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=20)
    credit_limit_kurus: int | None = Field(default=None, gt=0)
    discount_percent: int | None = Field(default=None, ge=0, le=100)
    active: bool | None = None


class PaymentIn(BaseModel):
    amount_kurus: int = Field(gt=0, le=10**12)
    description: str = Field(default="Tahsilat / Ödeme", min_length=1, max_length=200)


class BookingIn(BaseModel):
    slot_id: str
    vehicle_id: str
    customer: str = Field(min_length=2, max_length=120)
    customer_phone: str | None = Field(default="", max_length=30)
    idempotency_key: str = Field(min_length=8, max_length=100)
    confirmed: bool = False
    corporate_account_id: str | None = None
    package_type: str = Field(default="standart_ekspertiz", max_length=64)


class LiftIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    lift_number: int | None = Field(default=None, ge=1)
    notes: str = Field(default="", max_length=500)


class LiftStatusIn(BaseModel):
    status: str = Field(pattern="^(idle|busy|maintenance)$")
    notes: str = Field(default="", max_length=500)


class LiftAssignIn(BaseModel):
    appointment_id: str | None = None
    queue_id: str | None = None
    plate: str = Field(default="", max_length=32)
    package_type: str = Field(default="standart_ekspertiz", max_length=64)


class QueueEntryIn(BaseModel):
    plate: str = Field(min_length=2, max_length=32)
    customer: str = Field(min_length=2, max_length=120)
    package_type: str = Field(default="standart_ekspertiz", max_length=64)
    appointment_id: str | None = None
    vehicle_id: str | None = None


class OutboundCallIn(BaseModel):
    appointment_id: str
    phone: str | None = Field(default=None, max_length=40)
    call_type: str = Field(default="reminder", max_length=32)


class CallOutcomeIn(BaseModel):
    outcome: str = Field(pattern="^(confirmed|cancelled|unreachable)$")
    notes: str = Field(default="", max_length=200)


class CampaignDialIn(BaseModel):
    appointment_ids: list[str] = Field(min_length=1, max_length=100)
    dial_mode: Literal["ami", "callfile"] = Field(default="ami")
    call_type: str = Field(default="reminder", max_length=32)


class AMDAnalyzeIn(BaseModel):
    audio_base64: str = Field(min_length=1)
    sample_rate: int = Field(default=8000, ge=8000, le=48000)


class AMDEvaluateCallIn(BaseModel):
    call_id: str
    classification: Literal["HUMAN", "MACHINE", "UNKNOWN"]
    reason: str = Field(default="", max_length=200)


class ABExperimentIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=1000)
    experiment_type: str = Field(
        default="composite", pattern="^(prompt|tts_seed|greeting|composite)$"
    )
    variants: list[dict[str, Any]] = Field(min_length=2)
    target_metric: str = Field(default="conversion_rate", max_length=40)


class ABStatusIn(BaseModel):
    status: str = Field(pattern="^(active|paused|completed)$")


class ABPreviewSynthIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    seed: int = Field(default=9)


class DTMFIn(BaseModel):
    digit: str = Field(min_length=1, max_length=10)
    session_id: str | None = None


class DSPConfigIn(BaseModel):
    enabled: bool = True
    hpf_cutoff: float = Field(default=120.0, ge=40.0, le=400.0)
    suppression_db: float = Field(default=18.0, ge=0.0, le=36.0)
    target_dbfs: float = Field(default=-16.0, ge=-40.0, le=-6.0)
    noise_gate_dbfs: float = Field(default=-42.0, ge=-60.0, le=-20.0)
    max_boost_db: float = Field(default=12.0, ge=0.0, le=24.0)


class BatchedODEConfigIn(BaseModel):
    enabled: bool = True
    batch_size: int = Field(default=8, ge=1, le=32)
    micro_window_ms: float = Field(default=12.0, ge=1.0, le=100.0)
    max_concurrent_calls: int = Field(default=50, ge=1, le=200)
    steps: int = Field(default=32, ge=8, le=64)


class BatchedBenchmarkIn(BaseModel):
    texts: list[str] = Field(default_factory=list)
    seed: int = Field(default=9)
    concurrency: int = Field(default=8, ge=1, le=32)


class SimulateBargeInIn(BaseModel):
    text: str = Field(default="", max_length=1000)


class TransferInitiateIn(BaseModel):
    conversation_id: str | None = None
    caller_channel: str = ""
    customer_name: str = ""
    vehicle_plate: str = ""
    summary: str = ""
    intent: str = "operator_transfer"
    operator_extension: str | None = None


class TransferAcceptIn(BaseModel):
    operator_channel: str | None = None


class TransferDeclineIn(BaseModel):
    reason: str = "declined"


class TransferDTMFIn(BaseModel):
    digit: str = Field(min_length=1, max_length=2)
    operator_channel: str | None = None


class WhatsAppInboundIn(BaseModel):
    from_phone: str | None = None
    phone: str | None = None
    text: str = Field(min_length=1, max_length=2000)
    customer_name: str | None = None
    message_sid: str | None = None

    @property
    def sender_phone(self) -> str:
        return self.from_phone or self.phone or ""


class CallAnalyticsIn(BaseModel):
    conversation_id: str = Field(min_length=1)
    appointment_id: str | None = None
    caller_phone: str | None = None
    caller_name: str | None = None
    duration_sec: float | None = None
    transcript: Union[List[Dict[str, Any]], str, None] = None


class PhoneticDecodeIn(BaseModel):
    spoken_text: str = Field(min_length=1, max_length=2000)


class RuhsatTextDecodeIn(BaseModel):
    ocr_text: str = Field(min_length=1, max_length=5000)


class RuhsatApplyIn(BaseModel):
    scan_id: str | None = None
    plate: str = Field(min_length=2, max_length=32)
    vin: str | None = None
    brand_model: str | None = None
    appointment_id: str | None = None


class KVKKRedactIn(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    categories: list[str] | None = None
    mask_char: str = "*"
    validate_strict: bool = True


class TCKNValidateIn(BaseModel):
    tckn: str = Field(min_length=1, max_length=20)


class CardValidateIn(BaseModel):
    card_number: str = Field(min_length=12, max_length=30)


class VehicleValuationIn(BaseModel):
    brand: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=64)
    model_year: int = Field(ge=1990, le=2030)
    mileage_km: int = Field(ge=0, le=1000000)
    body_panels: dict[str, str] | None = None
    tramer_amount_tl: float = 0.0
    is_heavy_damage: bool = False
    plate: str | None = None
    conversation_id: str | None = None
    appointment_id: str | None = None


class SpokenValuationIn(BaseModel):
    query_text: str = Field(min_length=1, max_length=1000)
    plate: str | None = None


class BayCapacityCheckIn(BaseModel):
    package_type: str = Field(default="standart_ekspertiz", max_length=64)
    requested_start_iso: str = Field(min_length=10, max_length=40)
    exclude_schedule_id: str | None = None


class BayBookingIn(BaseModel):
    appointment_id: str = Field(min_length=1, max_length=64)
    package_type: str = Field(default="standart_ekspertiz", max_length=64)
    start_time_iso: str = Field(min_length=10, max_length=40)
    plate: str | None = ""
    notes: str | None = ""


class BayStatusIn(BaseModel):
    status: str = Field(min_length=3, max_length=32)


class TechnicianStatusIn(BaseModel):
    is_active: bool


class TurnEvaluateIn(BaseModel):
    text: str = Field(default="", max_length=1000)
    silence_duration_ms: float = Field(default=300.0, ge=0.0, le=10000.0)
    audio_base64: str | None = None
    sample_rate: int = Field(default=16000, ge=8000, le=48000)


class TurnAnalyzeTextIn(BaseModel):
    text: str = Field(default="", max_length=1000)


class EmotionAnalyzeIn(BaseModel):
    transcript: str = Field(default="", max_length=2000)
    audio_base64: str | None = None
    audio_duration_sec: float | None = None
    sample_rate: int = Field(default=16000, ge=8000, le=48000)


class EmotionAdaptIn(BaseModel):
    assistant_response_text: str = Field(min_length=1, max_length=2000)
    caller_transcript: str | None = None
    emotion_category: str | None = None


class PauseCleanIn(BaseModel):
    audio_base64: str = Field(min_length=4)
    sample_rate: int = Field(default=8000, ge=8000, le=48000)
    fade_ms: float = Field(default=12.0, ge=1.0, le=50.0)


class AudioCacheLookupIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ArchiveCallIn(BaseModel):
    audio_base64: str = Field(min_length=4)
    sample_rate: int = Field(default=8000, ge=8000, le=48000)
    conversation_id: str | None = None
    call_session_id: str = ""
    caller_phone: str = ""
    codec: str = Field(default="opus", pattern="^(opus|gsm_fr|raw_wav)$")
    is_redacted: bool = False
    retention_years: int = Field(default=2, ge=1, le=10)


class ArchivePurgeIn(BaseModel):
    dry_run: bool = True
    target_date: str | None = None


class GPUConfigureIn(BaseModel):
    vram_threshold_percent: float | None = Field(default=None, ge=10.0, le=99.0)
    temp_threshold_c: float | None = Field(default=None, ge=40.0, le=100.0)
    latency_threshold_ms: float | None = Field(default=None, ge=50.0, le=2000.0)
    cooldown_seconds: float | None = Field(default=None, ge=1.0, le=300.0)
    consecutive_failure_limit: int | None = Field(default=None, ge=1, le=20)
    default_failover_mode: str | None = Field(
        default=None, pattern="^(cpu_cache|operator_transfer|graceful_degrade)$"
    )


class GPUSimulateIn(BaseModel):
    simulate_oom: bool = False
    vram_percent: float | None = None
    temperature_c: float | None = None
    latency_ms: float | None = None


class TrunkSelectIn(BaseModel):
    destination_phone: str = ""
    force_priority: int | None = None
    exclude_trunks: list[str] = Field(default_factory=list)


class TrunkSimulateIn(BaseModel):
    trunk_id: str
    outage: bool = True


class TrunkMaintenanceIn(BaseModel):
    trunk_id: str
    maintenance: bool = True


class TrunkConfigIn(BaseModel):
    trunk_id: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=120)
    host: str = Field(min_length=3, max_length=120)
    port: int = Field(default=5060, ge=1, le=65535)
    transport: str = Field(default="UDP", pattern="^(UDP|TCP|TLS)$")
    priority: int = Field(default=1, ge=1, le=10)
    weight: int = Field(default=50, ge=1, le=100)
    max_channels: int = Field(default=30, ge=1, le=1000)


class SLARecordCallIn(BaseModel):
    success: bool = True
    duration_sec: float = Field(default=60.0, ge=1.0, le=7200.0)
    packet_loss_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    jitter_ms: float | None = Field(default=None, ge=0.0, le=1000.0)
    csat_score: float | None = Field(default=None, ge=1.0, le=5.0)
    queue_wait_sec: float | None = Field(default=None, ge=0.0, le=3600.0)
    converted_to_appointment: bool = False


class SLAConfigureIn(BaseModel):
    max_p95_latency_ms: float | None = Field(default=None, ge=50.0, le=2000.0)
    min_call_answer_rate_pct: float | None = Field(default=None, ge=50.0, le=100.0)
    min_mos_score: float | None = Field(default=None, ge=1.0, le=5.0)
    max_packet_loss_pct: float | None = Field(default=None, ge=0.1, le=50.0)
    max_gpu_vram_pct: float | None = Field(default=None, ge=10.0, le=99.0)
    max_gpu_temp_c: float | None = Field(default=None, ge=40.0, le=100.0)
    max_queue_wait_sec: float | None = Field(default=None, ge=1.0, le=300.0)


class OperatorTakeoverIn(BaseModel):
    session_id: str
    operator_id: str
    reason: str = "customer_request"


class OperatorWhisperIn(BaseModel):
    session_id: str
    operator_id: str
    message: str


class OperatorReleaseIn(BaseModel):
    session_id: str
    operator_id: str


class OperatorRegisterCallIn(BaseModel):
    session_id: str
    caller_id: str
    initial_turn_id: str | None = None
    mos_score: float = 4.3
    rtf: float = 0.18


class QAEvaluateVariantsIn(BaseModel):
    samples: list[tuple[str, str]] | None = None


class M11AcceptanceIn(BaseModel):
    has_physical_pbx_trace: bool = False
    has_hardware_trunk: bool = False
    evidence_files: list[str] = Field(default_factory=list)


def row(obj):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


@app.get("/api/health")
@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "alive"}


@app.get("/api/readiness", dependencies=[Depends(auth)])
async def readiness():
    ollama = {"model": settings.ollama_model}
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            r = await client.get(settings.ollama_url + "/api/tags")
            r.raise_for_status()
            names = [m["name"] for m in r.json().get("models", [])]
        if settings.ollama_model in names:
            ollama["status"] = "READY"
        else:
            ollama.update(status="BLOCKED", reason="Model Ollama'da kurulu değil")
    except Exception as e:
        ollama.update(status="BLOCKED", reason=str(e))

    # Değerler yalnızca gerçek durumdan gelir; demo modu da model durumunu taklit etmez.
    states = {breaker.state.name for breaker in models.breakers.values()}
    breaker_state = next(
        (s for s in ("OPEN", "HALF_OPEN") if s in states), "CLOSED"
    )
    breaker_labels = {
        "CLOSED": "CLOSED (Normal)",
        "HALF_OPEN": "HALF_OPEN (Deneme)",
        "OPEN": "OPEN (Beklemede)",
    }
    return {
        "demo_mode": settings.demo_mode,
        "tts": {"status": "READY" if models.tts else "BLOCKED", "device": settings.tts_device, "engine": "FreyaTTS"},
        "stt": {"status": "READY" if models.stt else "BLOCKED", "device": settings.stt_device, "engine": "Faster-Whisper " + settings.stt_model},
        "vad": {"status": "READY" if models.vad else "BLOCKED", "engine": "Silero VAD"},
        "ollama": ollama,
        "circuit_breaker": {"state": breaker_state, "status": breaker_labels[breaker_state]},
        "loading": models.loading,
        "error": models.error,
        "busy": active.locked(),
        "model_load_ms": models.load_ms,
        "synth_count": models.synth_count,
    }


@app.post("/api/models/load", dependencies=[Depends(auth)])
async def load():
    if active.locked():
        raise HTTPException(409, "Aktif görüşme var")
    try:
        await models.load()
    except Exception as e:
        raise HTTPException(503, str(e))
    return {"status": "READY"}


@app.post("/api/normalize", dependencies=[Depends(auth)])
def normal(body: TextIn):
    try:
        return normalize(body.text)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/frontend/normalize-prosody", dependencies=[Depends(auth)])
def frontend_normalize_prosody(body: TextIn):
    try:
        return automotive_frontend.prepare_text_for_synthesis(body.text)
    except Exception as e:
        raise HTTPException(422, str(e))


@app.post("/api/frontend/dsp-telephony", dependencies=[Depends(auth)])
def frontend_dsp_telephony(body: DSPProcessIn):
    import base64
    try:
        raw_bytes = base64.b64decode(body.audio_base64)
        if len(raw_bytes) % 2 != 0:
            raw_bytes = raw_bytes[:-1]
        samples_48k = np.frombuffer(raw_bytes, dtype="<i2").astype(np.float32) / 32768.0
    except Exception as e:
        raise HTTPException(400, f"Geçersiz Base64 PCM verisi: {e}")

    out_pcm16 = automotive_frontend.process_synthesized_audio(
        samples_48k,
        apply_de_ess=body.apply_de_esser,
        inject_noise=body.inject_comfort_noise,
    )
    b64_out = base64.b64encode(out_pcm16.tobytes()).decode("utf-8")
    return {
        "input_samples_48k": len(samples_48k),
        "output_samples_8k": len(out_pcm16),
        "output_bytes": len(out_pcm16.tobytes()),
        "audio_slin16_base64": b64_out,
    }


@app.get("/api/frontend/status", dependencies=[Depends(auth)])
def frontend_status():
    return automotive_frontend.get_metrics()


class MorphologicalCheckIn(BaseModel):
    text: str
    include_hints: bool = True
    chunk_id: Optional[str] = "chunk_0"


@app.post("/api/frontend/morphological-check", dependencies=[Depends(auth)])
def frontend_morphological_check(body: MorphologicalCheckIn):
    try:
        from backend.morphological_pre_checker import morphological_pre_checker
        from backend.morphology.contracts import NormalizedUtterance
        import uuid

        norm_text = automotive_frontend.normalizer.normalize(body.text)
        utterance = NormalizedUtterance(
            utterance_id=f"utt_{uuid.uuid4().hex[:8]}",
            chunk_id=body.chunk_id or "chunk_0",
            chunk_text=norm_text,
        )
        plan = morphological_pre_checker.analyze(utterance)
        plan_dict = plan.model_dump()
        if not body.include_hints:
            plan_dict["pronunciation_hints"] = []
        return {
            "chunk_id": plan.chunk_id,
            "normalized_text": norm_text,
            "emphasis_targets": plan.emphasis_targets,
            "pause_injections_ms": plan.pause_injections_ms,
            "pronunciation_hints": plan_dict["pronunciation_hints"],
            "warnings": plan.warnings,
        }
    except Exception as e:
        raise HTTPException(422, str(e))


@app.post("/api/sft/prepare-corpus", dependencies=[Depends(auth)])
def sft_prepare_corpus(body: SFTCorpusIn):
    samples = sft_manager.corpus_builder.generate_synthetic_samples(count=body.count)
    manifest_path = sft_manager.corpus_builder.save_manifest(samples)
    return {
        "total_samples": len(samples),
        "manifest_path": str(manifest_path),
        "sample_preview": samples[:3],
    }


@app.post("/api/sft/configure", dependencies=[Depends(auth)])
def sft_configure(body: SFTConfigureIn):
    sft_manager.config.learning_rate = body.learning_rate
    sft_manager.config.min_steps = body.min_steps
    sft_manager.config.max_steps = body.max_steps
    sft_manager.config.f0_max_drift_hz = body.f0_max_drift_hz
    sft_manager.drift_guard.f0_max_drift_hz = body.f0_max_drift_hz
    stats = sft_manager.initialize_model()
    return {
        "config": sft_manager.config.to_dict(),
        "model_stats": stats,
    }


@app.post("/api/sft/train-step", dependencies=[Depends(auth)])
def sft_train_step(body: SFTTrainIn):
    res = sft_manager.run_training_session(target_steps=body.steps)
    return res


@app.get("/api/sft/status", dependencies=[Depends(auth)])
def sft_status():
    return sft_manager.get_status()


@app.get("/api/sft/verify-identity", dependencies=[Depends(auth)])
def sft_verify_identity():
    return sft_manager.verify_leyla_identity()


@app.post("/api/sft/lora/configure", dependencies=[Depends(auth)])
def sft_lora_configure(body: SFTLoRAConfigureIn):
    lora_manager.config.r = body.r
    lora_manager.config.lora_alpha = body.lora_alpha
    lora_manager.config.lora_dropout = body.lora_dropout
    lora_manager.config.learning_rate = body.learning_rate
    lora_manager.config.batch_size = body.batch_size
    lora_manager.config.grad_accum = body.grad_accum

    if sft_manager.model is None:
        sft_manager.initialize_model()

    lora_model, stats = lora_manager.apply_lora_to_model(sft_manager.model, lora_manager.config)
    sft_manager.model = lora_model
    return {
        "lora_config": lora_manager.config.to_dict(),
        "stats": stats,
    }


@app.get("/api/sft/lora/status", dependencies=[Depends(auth)])
def sft_lora_status():
    return {
        "config": lora_manager.config.to_dict(),
        "active_model": lora_manager.active_lora_model is not None,
        "last_benchmark": lora_manager.last_benchmark_stats,
    }


@app.post("/api/sft/lora/benchmark-step", dependencies=[Depends(auth)])
def sft_lora_benchmark_step(body: SFTLoRABenchmarkIn):
    if sft_manager.model is None:
        sft_manager.initialize_model()
    if lora_manager.active_lora_model is None:
        lora_model, _ = lora_manager.apply_lora_to_model(sft_manager.model, lora_manager.config)
        sft_manager.model = lora_model
    res = lora_manager.benchmark_rtx4070_step(
        sft_manager.model,
        steps=body.steps,
        total_target_steps=body.total_target_steps,
    )
    return res


# -----------------------------------------------------------------------------
# Ajan 7: Dağıtık Telemetri, Canlı Operatör Paneli ve Kalite Kapısı Endpoints
# -----------------------------------------------------------------------------

@app.post("/api/operator/register-call", dependencies=[Depends(auth)])
def operator_register_call(body: OperatorRegisterCallIn):
    sess = operator_panel.register_call(
        session_id=body.session_id,
        caller_id=body.caller_id,
        initial_turn_id=body.initial_turn_id,
        mos_score=body.mos_score,
        rtf=body.rtf,
    )
    return {"success": True, "session": sess.to_dict()}


@app.post("/api/operator/takeover", dependencies=[Depends(auth)])
def operator_takeover(body: OperatorTakeoverIn):
    res = operator_panel.takeover_call(
        session_id=body.session_id,
        operator_id=body.operator_id,
        reason=body.reason,
    )
    if not res.get("success"):
        raise HTTPException(404, res.get("error", "Call not found"))
    return res


@app.post("/api/operator/whisper", dependencies=[Depends(auth)])
def operator_whisper(body: OperatorWhisperIn):
    res = operator_panel.whisper_to_agent(
        session_id=body.session_id,
        operator_id=body.operator_id,
        message=body.message,
    )
    if not res.get("success"):
        raise HTTPException(404, res.get("error", "Call not found"))
    return res


@app.post("/api/operator/release", dependencies=[Depends(auth)])
def operator_release(body: OperatorReleaseIn):
    res = operator_panel.release_call(
        session_id=body.session_id,
        operator_id=body.operator_id,
    )
    if not res.get("success"):
        raise HTTPException(404, res.get("error", "Call not found"))
    return res


@app.get("/api/operator/live-sessions", dependencies=[Depends(auth)])
def operator_live_sessions():
    return {"sessions": operator_panel.get_live_sessions()}


@app.post("/api/qa/evaluate-variants", dependencies=[Depends(auth)])
def qa_evaluate_variants(body: QAEvaluateVariantsIn):
    test_samples = body.samples
    if not test_samples:
        test_samples = [
            ("Bugün Peugeot 3008 için servis randevusu aldım.", "Bugün Pöjo üç bin sekiz için servis randevusu aldım."),
            ("Araç 1.6 PureTech 180 bg motora sahip.", "Araç bir nokta altı Pürtek yüz seksen beygir motora sahip."),
            ("Fiyat 1.250.000 TL olarak belirlendi.", "Fiyat bir milyon iki yüz elli bin Türk lirası olarak belirlendi."),
        ]
    return abc_evaluator.run_benchmark_suite(test_samples, acoustic_report=load_latest_report())


@app.get("/api/qa/telemetry/{turn_id}", dependencies=[Depends(auth)])
def qa_get_telemetry(turn_id: str):
    turn = realtime_turn_collector.get_turn(turn_id)
    if not turn:
        raise HTTPException(404, f"Turn telemetry not found for id: {turn_id}")
    return {
        "turn": turn.model_dump(),
        "opentelemetry_span": realtime_turn_collector.export_opentelemetry_span(turn_id),
    }


@app.get("/api/qa/m11-status", dependencies=[Depends(auth)])
def qa_m11_status(has_physical_pbx_trace: bool = False, has_hardware_trunk: bool = False):
    return m11_gate.evaluate_acceptance(
        has_physical_pbx_trace=has_physical_pbx_trace,
        has_hardware_trunk=has_hardware_trunk,
    )



@app.post("/api/synthesize", dependencies=[Depends(auth)])
async def synth(body: TextIn):
    if active.locked():
        raise HTTPException(409, "Aktif görüşme var")
    try:
        w = await models.synth(body.text)
    except Exception as e:
        raise HTTPException(503, str(e))
    buf = io.BytesIO()
    sf.write(buf, w, 48000, format="WAV", subtype="PCM_16")
    return Response(buf.getvalue(), media_type="audio/wav")



@app.get("/api/hotwords", dependencies=[Depends(auth)])
def get_hotwords():
    with Session() as db:
        vehicles = db.scalars(select(Vehicle.description).order_by(Vehicle.id)).all()
    combined = list(vehicles) + models.custom_hotwords
    return {
        "catalog_vehicles": vehicles,
        "custom_hotwords": models.custom_hotwords,
        "active_hints": ", ".join(combined)[:800],
    }


@app.post("/api/hotwords", dependencies=[Depends(auth)])
def update_hotwords(body: HotwordsIn):
    cleaned = [w.strip() for w in body.words if w.strip()]
    models.custom_hotwords = cleaned
    return {"status": "ok", "custom_hotwords": models.custom_hotwords}


@app.get("/api/lexicon", dependencies=[Depends(auth)])
def get_lexicon():
    return get_lexicon_entries()


@app.post("/api/lexicon", dependencies=[Depends(auth)])
def update_lexicon(body: LexiconTermIn):
    try:
        return set_lexicon_term(
            term=body.term,
            spoken=body.spoken,
            category=body.category or "custom",
        )
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/lexicon/reset", dependencies=[Depends(auth)])
def reset_lexicon():
    return reset_to_base_lexicon()


@app.delete("/api/lexicon/{term:path}", dependencies=[Depends(auth)])
def delete_lexicon(term: str):
    try:
        return delete_lexicon_term(term)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/notifications", dependencies=[Depends(auth)])
def list_notifications(
    status: str | None = None,
    appointment_id: str | None = None,
    recipient_type: str | None = None,
):
    with Session() as db:
        query = select(NotificationOutbox).order_by(
            NotificationOutbox.created_at.desc()
        )
        if status:
            query = query.where(NotificationOutbox.status == status)
        if appointment_id:
            query = query.where(NotificationOutbox.appointment_id == appointment_id)
        if recipient_type:
            query = query.where(NotificationOutbox.recipient_type == recipient_type)
        items = db.scalars(query.limit(100)).all()
        return [row(n) for n in items]


@app.post("/api/notifications/dispatch", dependencies=[Depends(auth)])
def dispatch_notifications():
    with Session() as db:
        dispatched = dispatch_pending_notifications(db, limit=50)
        return {
            "dispatched_count": len(dispatched),
            "dispatched": [row(n) for n in dispatched],
        }


@app.post("/api/notifications/{id}/retry", dependencies=[Depends(auth)])
def retry_single_notification(id: str):
    with Session() as db:
        res = retry_notification(db, id)
        if not res:
            raise HTTPException(404, "Bildirim bulunamadı")
        return row(res)


@app.post("/api/outbound/call", dependencies=[Depends(auth)])
async def create_outbound_call(body: OutboundCallIn):
    with Session() as db:
        try:
            call_record = await initiate_outbound_call(
                db,
                appointment_id=body.appointment_id,
                phone=body.phone,
                call_type=body.call_type,
            )
            return row(call_record)
        except ValueError as e:
            raise HTTPException(422, str(e))
        except RuntimeError as e:
            raise HTTPException(502, str(e))


@app.get("/api/outbound/calls", dependencies=[Depends(auth)])
def list_outbound_calls(
    appointment_id: str | None = None,
    status: str | None = None,
):
    with Session() as db:
        query = select(OutboundCall).order_by(OutboundCall.created_at.desc())
        if appointment_id:
            query = query.where(OutboundCall.appointment_id == appointment_id)
        if status:
            query = query.where(OutboundCall.status == status)
        calls = db.scalars(query.limit(100)).all()
        return [row(c) for c in calls]


@app.post("/api/outbound/calls/{id}/cancel", dependencies=[Depends(auth)])
def cancel_call(id: str):
    with Session() as db:
        try:
            return row(cancel_outbound_call(db, id))
        except ValueError as e:
            raise HTTPException(404, str(e))


@app.post("/api/outbound/calls/{id}/complete", dependencies=[Depends(auth)])
def complete_call(id: str, body: CallOutcomeIn):
    with Session() as db:
        try:
            return row(
                complete_outbound_call(
                    db, call_id=id, outcome=body.outcome, notes=body.notes
                )
            )
        except ValueError as e:
            raise HTTPException(422, str(e))


@app.get("/api/outbound/ami-status", dependencies=[Depends(auth)])
async def get_ami_status():
    ami = get_ami_client()
    is_up = await ami.ping()
    with Session() as db:
        stats = get_outbound_stats(db)
    return {
        "ami_host": settings.ami_host,
        "ami_port": settings.ami_port,
        "connected": is_up,
        "stats": stats,
    }


@app.post("/api/outbound/campaign-dial", dependencies=[Depends(auth)])
async def campaign_dial(body: CampaignDialIn):
    results = []
    errors = []
    with Session() as db:
        for app_id in body.appointment_ids:
            try:
                if body.dial_mode == "callfile":
                    call_rec, _ = campaign_dialer.originate_call_file(
                        db, appointment_id=app_id, call_type=body.call_type
                    )
                    results.append(row(call_rec))
                else:
                    call_rec = await campaign_dialer.originate_call_ami(
                        db, appointment_id=app_id, call_type=body.call_type
                    )
                    results.append(row(call_rec))
            except Exception as e:
                errors.append({"appointment_id": app_id, "error": str(e)})

    return {
        "mode": body.dial_mode,
        "total": len(body.appointment_ids),
        "successful_count": len(results),
        "failed_count": len(errors),
        "calls": results,
        "errors": errors,
    }


@app.post("/api/outbound/amd-analyze", dependencies=[Depends(auth)])
def amd_analyze(body: AMDAnalyzeIn):
    import base64
    try:
        raw_bytes = base64.b64decode(body.audio_base64)
    except Exception as e:
        raise HTTPException(400, f"Geçersiz Base64 verisi: {e}")

    result = detect_turkish_amd(raw_bytes, sample_rate=body.sample_rate)
    return result.to_dict()


@app.post("/api/outbound/amd-evaluate-call", dependencies=[Depends(auth)])
def amd_evaluate_call(body: AMDEvaluateCallIn):
    with Session() as db:
        try:
            amd_res = AMDResult(
                classification=body.classification,
                confidence=0.95,
                greeting_duration_sec=1.0,
                silence_duration_sec=0.5,
                beep_detected=(body.classification == "MACHINE"),
                reason=body.reason or f"Manüel/Olay bazlı {body.classification} ataması",
            )
            updated_call = campaign_dialer.process_amd_result(db, body.call_id, amd_res)
            return row(updated_call)
        except ValueError as e:
            raise HTTPException(404, str(e))


@app.get("/api/outbound/retry-queue", dependencies=[Depends(auth)])
def get_retry_queue():
    with Session() as db:
        query = (
            select(OutboundCall)
            .where(OutboundCall.status == "retry_scheduled")
            .order_by(OutboundCall.created_at.asc())
        )
        scheduled_calls = db.scalars(query).all()
        return [row(c) for c in scheduled_calls]


@app.post("/api/outbound/retry-process", dependencies=[Depends(auth)])
async def trigger_retry_process(limit: int = 10):
    with Session() as db:
        retried = await campaign_dialer.process_retry_queue(db, limit=limit)
        return {
            "processed": len(retried),
            "retried_calls": [row(c) for c in retried],
        }


@app.get("/api/outbound/campaign-stats", dependencies=[Depends(auth)])
def get_campaign_stats():
    return campaign_dialer.get_metrics()


@app.get("/api/vehicles/{id}", dependencies=[Depends(auth)])
def get_vehicle(id: str):
    with Session() as db:
        v = db.get(Vehicle, id)
        if not v:
            raise HTTPException(404, "Araç bulunamadı")
        return row(v)


@app.get("/api/inspections", dependencies=[Depends(auth)])
def list_inspections():
    with Session() as db:
        reports = db.scalars(
            select(InspectionReport).order_by(InspectionReport.inspected_at.desc())
        ).all()
        result = []
        for r in reports:
            v = db.get(Vehicle, r.vehicle_id)
            d = row(r)
            d["vehicle_plate"] = getattr(v, "plate", "") if v else ""
            d["vehicle_description"] = getattr(v, "description", "") if v else ""
            result.append(d)
        return result


@app.get("/api/inspections/{id}", dependencies=[Depends(auth)])
def get_inspection(id: str):
    with Session() as db:
        report = db.get(InspectionReport, id)
        if not report:
            raise HTTPException(404, "Ekspertiz raporu bulunamadı")
        vehicle = db.get(Vehicle, report.vehicle_id)
        d = row(report)
        d["vehicle"] = row(vehicle) if vehicle else None
        return d


@app.get("/api/analytics/overview", dependencies=[Depends(auth)])
def analytics_overview():
    with Session() as db:
        return {
            **get_analytics_overview(db),
            "data_source": "demo" if settings.demo_mode else "live",
        }


@app.get("/api/analytics/follow-ups", dependencies=[Depends(auth)])
def list_follow_ups(status: str = "all", limit: int = 50):
    with Session() as db:
        return get_follow_up_conversations(db, status_filter=status, limit=limit)


@app.post("/api/analytics/conversations/{id}/resolve", dependencies=[Depends(auth)])
def resolve_conv(id: str, body: ConversationResolveIn):
    with Session() as db:
        try:
            c = resolve_conversation(db, id, operator_notes=body.notes)
            return row(c)
        except ValueError as e:
            raise HTTPException(404, str(e))


@app.post("/api/analytics/conversations/{id}/reopen", dependencies=[Depends(auth)])
def reopen_conv(id: str):
    with Session() as db:
        try:
            c = reopen_conversation(db, id)
            return row(c)
        except ValueError as e:
            raise HTTPException(404, str(e))


@app.get("/api/diagnostics/dtc-registry", dependencies=[Depends(auth)])
def get_dtc_registry():
    return DTC_REGISTRY


@app.get("/api/diagnostics", dependencies=[Depends(auth)])
def list_all_diagnostics(is_resolved: bool | None = None):
    with Session() as db:
        query = select(VehicleDiagnostic).order_by(VehicleDiagnostic.created_at.desc())
        if is_resolved is not None:
            query = query.where(VehicleDiagnostic.is_resolved == is_resolved)
        records = db.scalars(query).all()
        result = []
        for r in records:
            v = db.get(Vehicle, r.vehicle_id)
            d = row(r)
            d["vehicle_plate"] = getattr(v, "plate", "") if v else ""
            d["vehicle_description"] = getattr(v, "description", "") if v else ""
            result.append(d)
        return result


@app.get("/api/vehicles/{id}/diagnostics", dependencies=[Depends(auth)])
def list_vehicle_diagnostics(id: str):
    with Session() as db:
        if not db.get(Vehicle, id):
            raise HTTPException(404, "Araç bulunamadı")
        records = db.scalars(
            select(VehicleDiagnostic)
            .where(VehicleDiagnostic.vehicle_id == id)
            .order_by(VehicleDiagnostic.created_at.desc())
        ).all()
        return [row(r) for r in records]


@app.post("/api/vehicles/{id}/diagnostics", dependencies=[Depends(auth)])
def add_vehicle_telemetry(id: str, body: TelemetryIngestIn):
    with Session() as db:
        try:
            created = ingest_vehicle_telemetry(
                db,
                vehicle_id=id,
                current_km=body.current_km,
                dtc_codes=body.dtc_codes,
                source=body.source,
                owner_name=body.owner_name,
                owner_phone=body.owner_phone,
            )
            return [row(d) for d in created]
        except ValueError as e:
            raise HTTPException(404, str(e))


@app.post("/api/diagnostics/{id}/call", dependencies=[Depends(auth)])
async def call_diagnostic_owner(id: str, body: ProactiveActionIn):
    with Session() as db:
        try:
            call_obj = await trigger_proactive_diagnostic_call(
                db, diagnostic_id=id, phone=body.phone
            )
            return row(call_obj)
        except ValueError as e:
            raise HTTPException(404, str(e))


@app.post("/api/diagnostics/{id}/sms", dependencies=[Depends(auth)])
def sms_diagnostic_owner(id: str, body: ProactiveActionIn):
    with Session() as db:
        try:
            notif = trigger_proactive_diagnostic_sms(
                db, diagnostic_id=id, phone=body.phone
            )
            dispatched = dispatch_pending_notifications(db)
            return {
                "notification": row(notif),
                "dispatched_count": len(dispatched),
            }
        except ValueError as e:
            raise HTTPException(404, str(e))


@app.post("/api/diagnostics/{id}/resolve", dependencies=[Depends(auth)])
def resolve_diag(id: str):
    with Session() as db:
        try:
            diag = resolve_diagnostic(db, id)
            return row(diag)
        except ValueError as e:
            raise HTTPException(404, str(e))


@app.get("/api/packages", dependencies=[Depends(auth)])
def list_packages():
    return list(PACKAGE_DEFINITIONS.values())


@app.get("/api/lifts", dependencies=[Depends(auth)])
def list_lifts():
    with Session() as db:
        lifts = get_all_lifts(db)
        return [row(l) for l in lifts]


@app.post("/api/lifts", dependencies=[Depends(auth)])
def create_lift(body: LiftIn):
    with Session() as db:
        lift = add_lift(
            db,
            name=body.name,
            lift_number=body.lift_number,
            notes=body.notes,
        )
        return row(lift)


@app.get("/api/lifts/capacity", dependencies=[Depends(auth)])
def lift_capacity():
    with Session() as db:
        return get_lift_capacity_status(db)


@app.post("/api/lifts/{id}/status", dependencies=[Depends(auth)])
def update_lift_status(id: str, body: LiftStatusIn):
    with Session() as db:
        try:
            lift = set_lift_status(db, lift_id=id, status=body.status, notes=body.notes)
            return row(lift)
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.post("/api/lifts/{id}/assign", dependencies=[Depends(auth)])
def assign_vehicle_to_lift(id: str, body: LiftAssignIn):
    with Session() as db:
        try:
            lift = assign_lift(
                db,
                lift_id=id,
                appointment_id=body.appointment_id,
                queue_id=body.queue_id,
                plate=body.plate,
                package_type=body.package_type,
            )
            return row(lift)
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.post("/api/lifts/{id}/release", dependencies=[Depends(auth)])
def release_vehicle_from_lift(id: str):
    with Session() as db:
        try:
            lift = release_lift(db, lift_id=id)
            return row(lift)
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.post("/api/lifts/{id}/call-next", dependencies=[Depends(auth)])
def call_next_for_lift(id: str):
    with Session() as db:
        try:
            q_item = call_next_queue_item(db, lift_id=id)
            if not q_item:
                return {"message": "Sırada bekleyen araç bulunmuyor", "assigned": False}
            lift = db.get(InspectionLift, id)
            return {
                "assigned": True,
                "queue_item": row(q_item),
                "lift": row(lift) if lift else None,
            }
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.get("/api/queue", dependencies=[Depends(auth)])
def list_queue(status: str | None = None):
    with Session() as db:
        items = get_queue(db, status=status)
        return [row(x) for x in items]


@app.post("/api/queue", dependencies=[Depends(auth)])
def add_to_queue(body: QueueEntryIn):
    with Session() as db:
        item = enqueue_vehicle(
            db,
            plate=body.plate,
            customer=body.customer,
            package_type=body.package_type,
            appointment_id=body.appointment_id,
            vehicle_id=body.vehicle_id,
        )
        return row(item)


@app.post("/api/queue/{id}/cancel", dependencies=[Depends(auth)])
def cancel_queue(id: str):
    with Session() as db:
        item = db.get(InspectionQueue, id)
        if not item:
            raise HTTPException(404, "Sıra kaydı bulunamadı")
        item.status = "cancelled"
        db.commit()
        return row(item)


# ============================================================================
# A/B TEST VE İNCE AYAR ALTYAPISI ENDPOINTS (AB TESTING ROUTES)
# ============================================================================

@app.get("/api/ab/templates", dependencies=[Depends(auth)])
def get_ab_templates():
    return {
        "prompt_templates": list(PROMPT_TEMPLATES.values()),
        "greeting_templates": list(GREETING_TEMPLATES.values()),
        "tts_seed_presets": list(TTS_SEED_PRESETS.values()),
    }


@app.get("/api/ab/experiments", dependencies=[Depends(auth)])
def list_ab_experiments():
    with Session() as db:
        seed_default_experiment(db)
        return get_all_experiments(db)


@app.post("/api/ab/experiments", dependencies=[Depends(auth)])
def create_ab_experiment_endpoint(body: ABExperimentIn):
    with Session() as db:
        try:
            return create_experiment(
                db,
                name=body.name,
                description=body.description,
                experiment_type=body.experiment_type,
                variants=body.variants,
                target_metric=body.target_metric,
            )
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.get("/api/ab/experiments/{id}", dependencies=[Depends(auth)])
def get_ab_experiment_endpoint(id: str):
    with Session() as db:
        exp = get_experiment_by_id(db, id)
        if not exp:
            raise HTTPException(404, "Deney bulunamadı")
        return exp


@app.post("/api/ab/experiments/{id}/status", dependencies=[Depends(auth)])
def update_ab_experiment_status_endpoint(id: str, body: ABStatusIn):
    with Session() as db:
        try:
            return set_experiment_status(db, id, body.status)
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.get("/api/ab/experiments/{id}/report", dependencies=[Depends(auth)])
def get_ab_experiment_report_endpoint(id: str):
    with Session() as db:
        try:
            return get_experiment_report(db, id)
        except ValueError as e:
            raise HTTPException(404, str(e))


@app.post("/api/ab/preview-synth", dependencies=[Depends(auth)])
async def ab_preview_synth(body: ABPreviewSynthIn):
    if active.locked():
        raise HTTPException(409, "Aktif görüşme var")
    try:
        w = await models.synth(body.text, seed=body.seed)
    except Exception as e:
        raise HTTPException(503, str(e))
    buf = io.BytesIO()
    sf.write(buf, w, 48000, format="WAV", subtype="PCM_16")
    return Response(buf.getvalue(), media_type="audio/wav")


@app.post("/api/dtmf/generate-tone", dependencies=[Depends(auth)])
def get_dtmf_tone_endpoint(body: DTMFIn):
    from backend.dtmf import generate_dtmf_tone
    try:
        w = generate_dtmf_tone(body.digit[0], duration_sec=0.1, sample_rate=8000)
    except ValueError as e:
        raise HTTPException(400, str(e))
    buf = io.BytesIO()
    sf.write(buf, w, 8000, format="WAV", subtype="PCM_16")
    return Response(buf.getvalue(), media_type="audio/wav")


# ============================================================================
# 8 KHZ ARAÇ İÇİ GÜRÜLTÜ BASTIRMA VE SOFT AGC (CAR DENOISER) ENDPOINTS
# ============================================================================

@app.get("/api/dsp/config", dependencies=[Depends(auth)])
def get_dsp_config():
    return {
        "enabled": settings.car_denoiser_enabled,
        "hpf_cutoff": settings.car_denoiser_hpf_cutoff,
        "suppression_db": settings.car_denoiser_suppression_db,
        "target_dbfs": settings.car_denoiser_target_dbfs,
        "noise_gate_dbfs": settings.car_denoiser_noise_gate_dbfs,
        "max_boost_db": settings.car_denoiser_max_boost_db,
    }


@app.post("/api/dsp/config", dependencies=[Depends(auth)])
def update_dsp_config(body: DSPConfigIn):
    settings.car_denoiser_enabled = body.enabled
    settings.car_denoiser_hpf_cutoff = body.hpf_cutoff
    settings.car_denoiser_suppression_db = body.suppression_db
    settings.car_denoiser_target_dbfs = body.target_dbfs
    settings.car_denoiser_noise_gate_dbfs = body.noise_gate_dbfs
    settings.car_denoiser_max_boost_db = body.max_boost_db
    return {
        "status": "updated",
        "config": get_dsp_config(),
    }


@app.post("/api/dsp/denoise-preview", dependencies=[Depends(auth)])
async def denoise_audio_preview(
    file: UploadFile = File(None),
    audio_file: UploadFile = File(None),
    hpf_cutoff: float = Form(None),
    suppression_db: float = Form(None),
    target_dbfs: float = Form(None),
):
    upload = file or audio_file
    if not upload:
        raise HTTPException(400, "Ses dosyası yüklenmelidir")
    content = await upload.read()
    if not content:
        raise HTTPException(400, "Ses dosyası boş")

    from backend.car_denoiser import process_audio_stream
    from backend.audio import resample
    import soundfile as sf
    import base64

    try:
        audio_data, sr = sf.read(io.BytesIO(content), dtype="float32")
        if audio_data.ndim > 1:
            audio_data = audio_data.mean(axis=1)
        if sr != 8000:
            audio_data = resample(audio_data, sr, 8000)
    except Exception as e:
        raise HTTPException(400, f"Ses dosyası okunamadı: {e}")

    cutoff = hpf_cutoff if hpf_cutoff is not None else settings.car_denoiser_hpf_cutoff
    supp = suppression_db if suppression_db is not None else settings.car_denoiser_suppression_db
    target = target_dbfs if target_dbfs is not None else settings.car_denoiser_target_dbfs

    cleaned_data, stats = process_audio_stream(
        audio_data,
        sample_rate=8000,
        chunk_size=160,
        hpf_cutoff_hz=cutoff,
        suppression_db=supp,
        target_dbfs=target,
    )

    out_buf = io.BytesIO()
    sf.write(out_buf, cleaned_data, 8000, format="WAV", subtype="PCM_16")
    wav_bytes = out_buf.getvalue()

    return {
        "status": "success",
        "stats": stats,
        "sample_rate": 8000,
        "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
    }


# ============================================================================
# BATCHED ODE VE ÇOKLU ÇAĞRI MOTORU (BATCHED ODE & CONCURRENCY) ENDPOINTS
# ============================================================================

@app.get("/api/batched-ode/config", dependencies=[Depends(auth)])
def get_batched_ode_config_endpoint():
    engine_inst = getattr(models, "batched_ode_engine", None)
    return {
        "enabled": settings.batched_ode_enabled,
        "batch_size": settings.batched_ode_batch_size,
        "micro_window_ms": settings.batched_ode_micro_window_ms,
        "max_concurrent_calls": settings.max_concurrent_calls,
        "steps": settings.batched_ode_steps,
        "default_seed": settings.batched_ode_default_seed,
        "active_calls_count": getattr(active, "active_count", 0),
        "engine_active": engine_inst is not None and engine_inst.enabled,
    }


@app.post("/api/batched-ode/config", dependencies=[Depends(auth)])
def update_batched_ode_config_endpoint(body: BatchedODEConfigIn):
    settings.batched_ode_enabled = body.enabled
    settings.batched_ode_batch_size = body.batch_size
    settings.batched_ode_micro_window_ms = body.micro_window_ms
    settings.max_concurrent_calls = body.max_concurrent_calls
    settings.batched_ode_steps = body.steps
    if hasattr(active, "set_capacity"):
        active.set_capacity(body.max_concurrent_calls)
    engine_inst = getattr(models, "batched_ode_engine", None)
    if engine_inst:
        engine_inst.update_config(
            batch_size=body.batch_size,
            micro_window_ms=body.micro_window_ms,
            enabled=body.enabled,
        )
    return {
        "status": "updated",
        "config": get_batched_ode_config_endpoint(),
    }


@app.get("/api/batched-ode/metrics", dependencies=[Depends(auth)])
def get_batched_ode_metrics_endpoint():
    engine_inst = getattr(models, "batched_ode_engine", None)
    if not engine_inst:
        return {
            "enabled": settings.batched_ode_enabled,
            "batch_size": settings.batched_ode_batch_size,
            "micro_window_ms": settings.batched_ode_micro_window_ms,
            "total_batches_processed": 0,
            "total_clauses_synthesized": 0,
            "total_audio_seconds": 0.0,
            "rtf": 0.0,
            "audio_seconds_per_wall_second": 0.0,
            "approx_concurrent_call_capacity": 50,
            "whisper_collapses_prevented": 0,
            "active_calls_count": getattr(active, "active_count", 0),
        }
    m = engine_inst.get_metrics()
    m["active_calls_count"] = getattr(active, "active_count", 0)
    return m


@app.post("/api/batched-ode/benchmark", dependencies=[Depends(auth)])
async def run_batched_ode_benchmark(body: BatchedBenchmarkIn):
    sample_texts = body.texts if body.texts else [
        "Volkswagen Passat 1.5 TSI aracınızın ekspertiz randevusu saat 14:30'da onaylanmıştır.",
        "Şu an iki liftimiz dolu, en erken saat 15:00'te randevu verebiliyoruz.",
        "Aracınızda P0301 arıza kodu algılandı, kontrol randevusu öneriyoruz.",
        "Sol ön çamurluk boyalı, sağ arka kapı değişen olarak rapora işlendi.",
        "Maslak Ekspertiz Merkezine hoş geldiniz, nasıl yardımcı olabilirim?",
        "Ekspertiz raporunuz hazırlandı, WhatsApp üzerinden indirme linki iletildi.",
        "Kurumsal galeri cari hesabınıza randevu bedeli başarıyla işlenmiştir.",
        "Operatöre aktarıyorum, lütfen hatta kalınız.",
    ]
    concurrency = min(body.concurrency, len(sample_texts))
    texts_to_run = sample_texts[:concurrency]

    from backend.batched_ode import BatchedODEEngine, check_voicedness
    test_engine = getattr(models, "batched_ode_engine", None)
    if not test_engine:
        test_engine = BatchedODEEngine(
            batch_size=settings.batched_ode_batch_size,
            micro_window_ms=settings.batched_ode_micro_window_ms,
            steps=settings.batched_ode_steps,
            enabled=True,
        )

    bench_start = time.monotonic()
    tasks = [
        test_engine.synthesize_clause(txt, seed=body.seed + idx)
        for idx, txt in enumerate(texts_to_run)
    ]
    waveforms = await asyncio.gather(*tasks)
    total_elapsed = time.monotonic() - bench_start

    total_audio_sec = sum(len(w) / 48000 for w in waveforms)
    voiced_scores = [round(check_voicedness(w), 3) for w in waveforms]
    avg_voicedness = round(sum(voiced_scores) / max(len(voiced_scores), 1), 3)

    audio_per_sec = total_audio_sec / max(total_elapsed, 1e-4)
    rtf = total_elapsed / max(total_audio_sec, 1e-4)

    return {
        "status": "success",
        "concurrency": len(texts_to_run),
        "total_elapsed_ms": round(total_elapsed * 1000, 2),
        "total_audio_seconds": round(total_audio_sec, 2),
        "audio_seconds_per_wall_second": round(audio_per_sec, 1),
        "rtf": round(rtf, 4),
        "estimated_concurrent_capacity": int(audio_per_sec * 0.85),
        "avg_voicedness_score": avg_voicedness,
        "voiced_scores": voiced_scores,
    }


# ============================================================================
# AUDIOSOCKET TCP 9092 & ÇİFT KADEMELİ BARGE-IN ENDPOINTS
# ============================================================================

@app.get("/api/audiosocket/stats", dependencies=[Depends(auth)])
def get_audiosocket_stats_endpoint():
    """Asterisk app_audiosocket TCP 9092 orkestratör metriklerini döndürür."""
    return orchestrator.get_metrics()


@app.post("/api/audiosocket/simulate-bargein", dependencies=[Depends(auth)])
def simulate_barge_in_endpoint(body: SimulateBargeInIn):
    """Çift kademeli barge-in (Stage 1 soft pause, Stage 2 rollback vs commit) simülasyonu."""
    ctrl = TwoStageBargeInController()
    ctrl.stage1_soft_pause()
    decision = ctrl.stage2_evaluate(body.text)
    is_backchannel = decision == "rollback"
    return {
        "input_text": body.text,
        "decision": decision,
        "is_backchannel": is_backchannel,
        "action": "resume_playback" if is_backchannel else "flush_and_cancel_queue",
        "explanation": (
            "Dinleme teyidi (backchannel) algılandı; ses çalmaya devam eder, LLM kuyruğu korunur."
            if is_backchannel
            else "Kullanıcı müdahalesi algılandı; aktif ses ve LLM kuyruğu iptal edilir (hard flush)."
        ),
        "stats": ctrl.get_stats(),
    }


# ============================================================================
# CHAN_WEBSOCKET ASTERISK 20.18+ WS 8088 & FLUSH_MEDIA ENDPOINTS
# ============================================================================

@app.websocket("/ws/asterisk")
async def asterisk_chan_websocket_endpoint(ws: WebSocket):
    """Asterisk 20.18+ chan_websocket WebSocket bağlantı uç noktası."""
    await chan_ws_adapter.handle_fastapi_websocket(ws)


@app.get("/api/chan-websocket/stats", dependencies=[Depends(auth)])
def get_chan_websocket_stats_endpoint():
    """Asterisk chan_websocket WS 8088 adaptör metriklerini döndürür."""
    return chan_ws_adapter.get_metrics()


@app.post("/api/chan-websocket/flush", dependencies=[Depends(auth)])
async def trigger_chan_websocket_flush_endpoint():
    """Tüm aktif chan_websocket oturumlarına anında FLUSH_MEDIA komutu gönderir."""
    flushed_count = await chan_ws_adapter.flush_all_active_sessions()
    return {
        "status": "flushed",
        "flushed_sessions_count": flushed_count,
        "active_sessions": len(chan_ws_adapter.active_sessions),
    }


# ============================================================================
# BİRLEŞİK ANA ORKESTRASYON SUNUCUSU (UNIFIED SERVER) TELEMETRİ ENDPOINTS
# ============================================================================

@app.get("/api/system/unified-status", dependencies=[Depends(auth)])
def get_unified_system_status_endpoint():
    """Tüm protokollerin (TCP 9092, WS 8088, HTTP, GPU/VRAM) birleşik durumunu döndürür."""
    return unified_server.get_health_status()


@app.get("/api/transfers", dependencies=[Depends(auth)])
def get_transfers_endpoint(status: str | None = None, limit: int = 50):
    with Session() as db:
        check_transfer_timeouts(db)
        items = list_transfers(db, status=status, limit=limit)
        result = []
        for t in items:
            r = row(t)
            try:
                r["sip_headers"] = json.loads(t.sip_headers_json)
            except Exception:
                r["sip_headers"] = {}
            result.append(r)
        return result


@app.get("/api/transfers/{id}", dependencies=[Depends(auth)])
def get_transfer_detail_endpoint(id: str):
    with Session() as db:
        check_transfer_timeouts(db)
        t = db.get(OperatorTransfer, id)
        if not t:
            raise HTTPException(404, "Aktarım kaydı bulunamadı")
        r = row(t)
        try:
            r["sip_headers"] = json.loads(t.sip_headers_json)
        except Exception:
            r["sip_headers"] = {}
        return r


@app.post("/api/transfers/initiate", dependencies=[Depends(auth)])
async def initiate_transfer_endpoint(body: TransferInitiateIn):
    with Session() as db:
        try:
            t = await initiate_operator_transfer(
                db,
                conversation_id=body.conversation_id,
                caller_channel=body.caller_channel,
                customer_name=body.customer_name,
                vehicle_plate=body.vehicle_plate,
                summary=body.summary,
                intent=body.intent,
                operator_extension=body.operator_extension,
            )
            r = row(t)
            try:
                r["sip_headers"] = json.loads(t.sip_headers_json)
            except Exception:
                r["sip_headers"] = {}
            return r
        except ValueError as e:
            raise HTTPException(422, str(e))
        except Exception as e:
            raise HTTPException(500, str(e))


@app.post("/api/transfers/{id}/accept", dependencies=[Depends(auth)])
async def accept_transfer_endpoint(id: str, body: TransferAcceptIn = None):
    op_ch = body.operator_channel if body else None
    with Session() as db:
        try:
            t = await accept_operator_transfer(db, id, operator_channel=op_ch)
            return row(t)
        except ValueError as e:
            raise HTTPException(404, str(e))


@app.post("/api/transfers/{id}/decline", dependencies=[Depends(auth)])
async def decline_transfer_endpoint(id: str, body: TransferDeclineIn = None):
    reason = body.reason if body else "declined"
    with Session() as db:
        try:
            t = await decline_operator_transfer(db, id, reason=reason)
            r = row(t)
            r["fallback_prompt"] = FALLBACK_AI_PROMPT
            return r
        except ValueError as e:
            raise HTTPException(404, str(e))


@app.post("/api/transfers/{id}/dtmf", dependencies=[Depends(auth)])
async def transfer_dtmf_endpoint(id: str, body: TransferDTMFIn):
    with Session() as db:
        try:
            res = await handle_operator_dtmf(
                db, id, body.digit, operator_channel=body.operator_channel
            )
            return res
        except ValueError as e:
            raise HTTPException(404, str(e))


@app.get("/api/whatsapp/messages", dependencies=[Depends(auth)])
def get_whatsapp_messages_endpoint(limit: int = 50):
    with Session() as db:
        msgs = list_whatsapp_messages(db, limit=limit)
        return [row(m) for m in msgs]


@app.post("/api/whatsapp/inbound", dependencies=[Depends(auth)])
def whatsapp_inbound_endpoint(body: WhatsAppInboundIn):
    sender = body.sender_phone
    if not sender:
        raise HTTPException(422, "from_phone veya phone alanı zorunludur")
    with Session() as db:
        res = process_inbound_text(
            db,
            from_phone=sender,
            text=body.text,
            customer_name=body.customer_name or "",
            message_sid=body.message_sid or "",
        )
        return res


@app.post("/api/whatsapp/inbound-voice", dependencies=[Depends(auth)])
async def whatsapp_inbound_voice_endpoint(
    file: UploadFile = File(None),
    audio_file: UploadFile = File(None),
    from_phone: str = Form(None),
    phone: str = Form(None),
    customer_name: str | None = Form(None),
):
    upload = file or audio_file
    if not upload:
        raise HTTPException(400, "Ses dosyası boş veya eksik")
    sender = from_phone or phone
    if not sender:
        raise HTTPException(422, "from_phone veya phone alanı zorunludur")

    content = await upload.read()
    if not content:
        raise HTTPException(400, "Ses dosyası boş")

    import soundfile as sf
    from backend.audio import resample

    try:
        audio_data, sr = sf.read(io.BytesIO(content), dtype="float32")
        if audio_data.ndim > 1:
            audio_data = audio_data.mean(axis=1)
        if sr != 16000:
            audio_data = resample(audio_data, sr, 16000)
    except Exception:
        audio_data = io.BytesIO(content)

    with Session() as db:
        res = await process_inbound_voice(
            db,
            from_phone=sender,
            audio_data=audio_data,
            customer_name=customer_name or "",
        )
        return res


@app.post("/api/webhooks/whatsapp")
async def whatsapp_webhook_endpoint(request: Request):
    """
    Twilio / WhatsApp Cloud API webhook alıcısı.
    Form-urlencoded (Twilio) veya JSON (WhatsApp Cloud) kabul eder.
    """
    content_type = request.headers.get("content-type", "")
    from_phone = ""
    text_content = ""
    message_sid = ""

    if "application/json" in content_type:
        try:
            data = await request.json()
            entries = data.get("entry", [])
            if entries:
                changes = entries[0].get("changes", [])
                if changes:
                    val = changes[0].get("value", {})
                    messages = val.get("messages", [])
                    if messages:
                        m = messages[0]
                        from_phone = m.get("from", "")
                        message_sid = m.get("id", "")
                        if m.get("type") == "text":
                            text_content = m.get("text", {}).get("body", "")
            if not from_phone and "from_phone" in data:
                from_phone = data.get("from_phone", "")
                text_content = data.get("text", "")
                message_sid = data.get("message_sid", "")
        except Exception:
            raise HTTPException(400, "Geçersiz JSON yükü")
    else:
        form_data = await request.form()
        from_phone = str(form_data.get("From", "")).replace("whatsapp:", "")
        text_content = str(form_data.get("Body", ""))
        message_sid = str(form_data.get("MessageSid", ""))

    if not from_phone or not text_content:
        raise HTTPException(422, "Telefon ve mesaj metni gereklidir")

    with Session() as db:
        res = process_inbound_text(
            db,
            from_phone=from_phone,
            text=text_content,
            message_sid=message_sid,
        )
        return res


@app.post("/api/whatsapp/inbound-image", dependencies=[Depends(auth)])
async def whatsapp_inbound_image_endpoint(
    file: UploadFile = File(None),
    image_file: UploadFile = File(None),
    from_phone: str = Form(None),
    phone: str = Form(None),
    customer_name: str | None = Form(None),
):
    upload = file or image_file
    if not upload:
        raise HTTPException(400, "Görsel dosyası boş veya eksik")
    sender = from_phone or phone
    if not sender:
        raise HTTPException(422, "from_phone veya phone alanı zorunludur")

    content = await upload.read()
    if not content:
        raise HTTPException(400, "Görsel içeriği boş")

    with Session() as db:
        res = process_inbound_image(
            db,
            from_phone=sender,
            image_bytes=content,
            customer_name=customer_name or "",
            filename=upload.filename or "ruhsat.jpg",
        )
        return res


@app.post("/api/analytics/evaluate-call", dependencies=[Depends(auth)])
def evaluate_call_endpoint(body: CallAnalyticsIn):
    with Session() as db:
        try:
            record = evaluate_and_save_call_analytics(
                db,
                conversation_id=body.conversation_id,
                appointment_id=body.appointment_id,
                caller_phone=body.caller_phone or "",
                caller_name=body.caller_name or "",
                duration_sec=body.duration_sec,
                transcript_override=body.transcript,
            )
            return row(record)
        except ValueError as e:
            raise HTTPException(404, str(e))


@app.get("/api/analytics/calls", dependencies=[Depends(auth)])
def get_analytics_calls_endpoint(limit: int = 50, lead_tier: str | None = None):
    with Session() as db:
        stmt = select(CallAnalytics).order_by(CallAnalytics.created_at.desc())
        if lead_tier:
            stmt = stmt.where(CallAnalytics.lead_tier == lead_tier.upper())
        records = db.scalars(stmt.limit(limit)).all()
        return [row(r) for r in records]


@app.get("/api/analytics/call-stats", dependencies=[Depends(auth)])
def get_analytics_call_stats_endpoint():
    with Session() as db:
        return get_analytics_summary_stats(db)


@app.post("/api/ruhsat/decode-image", dependencies=[Depends(auth)])
async def ruhsat_decode_image_endpoint(
    file: UploadFile = File(None),
    from_phone: str = Form(""),
    appointment_id: str | None = Form(None),
):
    if not file:
        raise HTTPException(400, "Ruhsat görsel dosyası gereklidir")
    content = await file.read()
    if not content:
        raise HTTPException(400, "Dosya içeriği boş")

    with Session() as db:
        scan_record, parsed = process_inbound_ruhsat_image(
            db,
            from_phone=from_phone,
            image_bytes=content,
            appointment_id=appointment_id,
            filename=file.filename or "",
        )
        res = row(scan_record)
        res["parsed"] = parsed
        return res


@app.post("/api/ruhsat/decode-text", dependencies=[Depends(auth)])
def ruhsat_decode_text_endpoint(body: RuhsatTextDecodeIn):
    parsed = decode_ruhsat_text(body.ocr_text)
    return parsed


@app.post("/api/ruhsat/decode-phonetic", dependencies=[Depends(auth)])
def ruhsat_decode_phonetic_endpoint(body: PhoneticDecodeIn):
    return decode_phonetic_spelling(body.spoken_text)


@app.post("/api/ruhsat/apply-to-crm", dependencies=[Depends(auth)])
def ruhsat_apply_crm_endpoint(body: RuhsatApplyIn):
    with Session() as db:
        vehicle = None
        norm_plate = body.plate.replace(" ", "").upper()
        vehicles = db.scalars(select(Vehicle)).all()
        for v in vehicles:
            if v.plate and v.plate.replace(" ", "").upper() == norm_plate:
                vehicle = v
                break

        if not vehicle:
            desc = body.brand_model or f"Araç {body.plate}"
            vehicle = Vehicle(plate=body.plate, description=desc, vin=body.vin or "")
            db.add(vehicle)
            db.flush()
        else:
            if body.vin and not vehicle.vin:
                vehicle.vin = body.vin
            if body.brand_model and "Araç" in vehicle.description:
                vehicle.description = body.brand_model

        if body.appointment_id:
            app = db.get(Appointment, body.appointment_id)
            if app:
                app.vehicle_id = vehicle.id

        if body.scan_id:
            scan = db.get(RuhsatScan, body.scan_id)
            if scan:
                scan.vehicle_id = vehicle.id
                if body.appointment_id:
                    scan.appointment_id = body.appointment_id

        db.commit()
        return {
            "status": "applied",
            "vehicle_id": vehicle.id,
            "plate": vehicle.plate,
            "vin": vehicle.vin,
            "description": vehicle.description,
        }


@app.get("/api/ruhsat/scans", dependencies=[Depends(auth)])
def get_ruhsat_scans_endpoint(limit: int = 50):
    with Session() as db:
        scans = db.scalars(
            select(RuhsatScan).order_by(RuhsatScan.created_at.desc()).limit(limit)
        ).all()
        return [row(s) for s in scans]


@app.post("/api/kvkk/redact-text", dependencies=[Depends(auth)])
def kvkk_redact_text_endpoint(body: KVKKRedactIn):
    cats = set(body.categories) if body.categories else None
    res = redact_text(
        body.text,
        categories=cats,
        mask_char=body.mask_char,
        validate_strict=body.validate_strict,
    )
    return {
        "original_text": res.original_text,
        "redacted_text": res.redacted_text,
        "entities": res.entities,
        "redaction_count": res.redaction_count,
    }


@app.post("/api/kvkk/validate-tckn", dependencies=[Depends(auth)])
def kvkk_validate_tckn_endpoint(body: TCKNValidateIn):
    valid = is_valid_tckn(body.tckn)
    masked = mask_tckn(body.tckn)
    return {
        "tckn": body.tckn,
        "is_valid": valid,
        "masked": masked,
    }


@app.post("/api/kvkk/validate-card", dependencies=[Depends(auth)])
def kvkk_validate_card_endpoint(body: CardValidateIn):
    valid = is_valid_luhn(body.card_number)
    masked = mask_credit_card(body.card_number)
    return {
        "card_number": body.card_number,
        "is_valid": valid,
        "masked": masked,
    }


@app.get("/api/kvkk/policy", dependencies=[Depends(auth)])
def kvkk_get_policy_endpoint():
    return {
        "enabled_categories": list(default_kvkk_guard.enabled_categories),
        "mask_char": default_kvkk_guard.mask_char,
        "validate_strict": default_kvkk_guard.validate_strict,
        "beep_freq_hz": default_kvkk_guard.beep_freq_hz,
        "supported_pii": [
            "tckn",
            "credit_card",
            "cvv",
            "expiry",
            "phone",
            "email",
            "iban",
            "spoken_numbers",
        ],
    }


@app.post("/api/kvkk/redact-audio", dependencies=[Depends(auth)])
async def kvkk_redact_audio_endpoint(
    file: UploadFile = File(...),
    ranges_json: str = Form("[]"),
    mode: str = Form("beep"),
):
    content = await file.read()
    if not content:
        raise HTTPException(400, "Ses dosyası boş")

    try:
        ranges_data = json.loads(ranges_json)
    except Exception:
        ranges_data = []

    time_ranges = []
    for item in ranges_data:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            time_ranges.append((float(item[0]), float(item[1])))
        elif isinstance(item, dict) and "start_sec" in item and "end_sec" in item:
            time_ranges.append((float(item["start_sec"]), float(item["end_sec"])))

    audio_arr, sr = sf.read(io.BytesIO(content), dtype="float32")
    if audio_arr.ndim > 1:
        audio_arr = audio_arr.mean(axis=1)

    redacted = redact_audio(audio_arr, sr, time_ranges, mode=mode)
    out_buf = io.BytesIO()
    sf.write(out_buf, redacted, sr, format="WAV", subtype="PCM_16")
    out_buf.seek(0)

    return Response(content=out_buf.read(), media_type="audio/wav")


@app.post("/api/valuation/calculate", dependencies=[Depends(auth)])
def valuation_calculate_endpoint(body: VehicleValuationIn):
    val = calculate_dynamic_valuation(
        brand=body.brand,
        model=body.model,
        model_year=body.model_year,
        mileage_km=body.mileage_km,
        body_panels=body.body_panels,
        tramer_amount_tl=body.tramer_amount_tl,
        is_heavy_damage=body.is_heavy_damage,
        plate=body.plate or "",
    )
    return asdict(val)


@app.post("/api/valuation/save", dependencies=[Depends(auth)])
def valuation_save_endpoint(body: VehicleValuationIn):
    with Session() as db:
        record = calculate_and_save_valuation(
            db,
            brand=body.brand,
            model=body.model,
            model_year=body.model_year,
            mileage_km=body.mileage_km,
            body_panels=body.body_panels,
            tramer_amount_tl=body.tramer_amount_tl,
            is_heavy_damage=body.is_heavy_damage,
            plate=body.plate or "",
            conversation_id=body.conversation_id,
            appointment_id=body.appointment_id,
        )
        return row(record)


@app.post("/api/valuation/parse-spoken", dependencies=[Depends(auth)])
def valuation_parse_spoken_endpoint(body: SpokenValuationIn):
    parsed = parse_spoken_valuation_query(body.query_text)
    val = calculate_dynamic_valuation(
        brand=parsed.get("brand", "Volkswagen"),
        model=parsed.get("model", "Passat"),
        model_year=parsed.get("model_year", 2020),
        mileage_km=parsed.get("mileage_km", 60000),
        body_panels=parsed.get("body_panels", {}),
        tramer_amount_tl=parsed.get("tramer_amount_tl", 0.0),
        is_heavy_damage=parsed.get("is_heavy_damage", False),
        plate=body.plate or "",
    )
    res = asdict(val)
    res["parsed_query"] = parsed
    return res


@app.get("/api/valuation/valuations", dependencies=[Depends(auth)])
def valuation_list_endpoint(limit: int = 50):
    with Session() as db:
        records = list_vehicle_valuations(db, limit=limit)
        return [row(r) for r in records]


# ============================================================================
# FİZİKSEL LİFT VE TEKNİSYEN KAPASİTE PLANLAYICI (BAY SCHEDULER) ENDPOINTS
# ============================================================================

@app.post("/api/bay-scheduler/check-capacity", dependencies=[Depends(auth)])
def bay_check_capacity_endpoint(body: BayCapacityCheckIn):
    with Session() as db:
        res = check_multi_stage_bay_capacity(
            db,
            package_type=body.package_type,
            requested_start_iso=body.requested_start_iso,
            exclude_schedule_id=body.exclude_schedule_id,
        )
        return res.to_dict()


@app.post("/api/bay-scheduler/book-stages", dependencies=[Depends(auth)])
def bay_book_stages_endpoint(body: BayBookingIn):
    with Session() as db:
        try:
            schedules = schedule_multi_stage_appointment(
                db,
                appointment_id=body.appointment_id,
                package_type=body.package_type,
                start_time_iso=body.start_time_iso,
                plate=body.plate or "",
                notes=body.notes or "",
            )
            return [row(s) for s in schedules]
        except ValueError as e:
            raise HTTPException(409, str(e))


@app.get("/api/bay-scheduler/bays", dependencies=[Depends(auth)])
def bay_list_endpoint():
    with Session() as db:
        bays = list_bays(db)
        return [row(b) for b in bays]


@app.get("/api/bay-scheduler/technicians", dependencies=[Depends(auth)])
def technician_list_endpoint():
    with Session() as db:
        techs = list_technicians(db)
        return [row(t) for t in techs]


@app.get("/api/bay-scheduler/schedules", dependencies=[Depends(auth)])
def bay_schedules_list_endpoint(date: str | None = None, limit: int = 100):
    with Session() as db:
        schedules = list_bay_schedules(db, date_str=date, limit=limit)
        return [row(s) for s in schedules]


@app.get("/api/bay-scheduler/analytics", dependencies=[Depends(auth)])
def bay_analytics_endpoint(date: str | None = None):
    with Session() as db:
        return get_bay_station_analytics(db, date_str=date)


@app.put("/api/bay-scheduler/bays/{bay_id}/status", dependencies=[Depends(auth)])
def bay_set_status_endpoint(bay_id: str, body: BayStatusIn):
    with Session() as db:
        try:
            updated = set_bay_status(db, bay_id, body.status)
            return row(updated)
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.put("/api/bay-scheduler/technicians/{technician_id}/status", dependencies=[Depends(auth)])
def technician_set_status_endpoint(technician_id: str, body: TechnicianStatusIn):
    with Session() as db:
        try:
            updated = set_technician_status(db, technician_id, body.is_active)
            return row(updated)
        except ValueError as e:
            raise HTTPException(400, str(e))


@app.delete("/api/bay-scheduler/appointments/{appointment_id}", dependencies=[Depends(auth)])
def cancel_appointment_schedules_endpoint(appointment_id: str):
    with Session() as db:
        canceled_count = cancel_appointment_schedules(db, appointment_id=appointment_id)
        return {"appointment_id": appointment_id, "cancelled_schedules_count": canceled_count}


# ============================================================================
# AKUSTİK VE ANLAMSAL SMART TURN DEDEKTÖRÜ (SEMANTIC TURN DETECTOR) ENDPOINTS
# ============================================================================

_global_turn_detector = SemanticTurnDetector()


@app.post("/api/turn-detector/evaluate", dependencies=[Depends(auth)])
def turn_evaluate_endpoint(body: TurnEvaluateIn):
    samples = None
    if body.audio_base64:
        try:
            import base64
            raw_bytes = base64.b64decode(body.audio_base64)
            samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        except Exception:
            samples = None

    decision = _global_turn_detector.decide_turn(
        text=body.text,
        silence_duration_ms=body.silence_duration_ms,
        audio_samples=samples,
        sample_rate=body.sample_rate,
    )
    return decision.to_dict()


@app.post("/api/turn-detector/analyze-text", dependencies=[Depends(auth)])
def turn_analyze_text_endpoint(body: TurnAnalyzeTextIn):
    res = _global_turn_detector.analyze_text(body.text)
    return res.to_dict()


@app.get("/api/turn-detector/config", dependencies=[Depends(auth)])
def turn_config_endpoint():
    return {
        "min_silence_ms": _global_turn_detector.min_silence_ms,
        "extended_silence_ms": _global_turn_detector.extended_silence_ms,
        "max_hold_ms": _global_turn_detector.max_hold_ms,
        "enable_acoustic_pitch": _global_turn_detector.enable_acoustic_pitch,
        "single_marker_count": len(DISCOURSE_MARKERS_UNFINISHED_SINGLE),
        "multi_marker_count": len(DISCOURSE_MARKERS_UNFINISHED_MULTI),
        "postposition_count": len(POSTPOSITIONS_INCOMPLETE),
    }


# ============================================================================
# DUYGU DURUMU DUYARLI PROZODİ VE HIZ ADAPTÖRÜ (EMOTION PROSODY ADAPTER) ENDPOINTS
# ============================================================================

@app.post("/api/emotion-prosody/analyze", dependencies=[Depends(auth)])
def emotion_analyze_endpoint(body: EmotionAnalyzeIn):
    samples = None
    if body.audio_base64:
        try:
            import base64
            raw_bytes = base64.b64decode(body.audio_base64)
            samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        except Exception:
            samples = None

    profile = emotion_prosody_adapter.analyze_caller_emotion(
        transcript=body.transcript,
        audio_samples=samples,
        audio_duration_sec=body.audio_duration_sec,
        sample_rate=body.sample_rate,
    )
    return profile.to_dict()


@app.post("/api/emotion-prosody/adapt", dependencies=[Depends(auth)])
def emotion_adapt_endpoint(body: EmotionAdaptIn):
    if body.emotion_category:
        try:
            cat = EmotionCategory(body.emotion_category)
        except Exception:
            cat = EmotionCategory.SATISFIED_CALM
        profile = EmotionProfile(primary_category=cat, confidence=1.0)
    elif body.caller_transcript:
        profile = emotion_prosody_adapter.analyze_caller_emotion(transcript=body.caller_transcript)
    else:
        profile = EmotionProfile(primary_category=EmotionCategory.SATISFIED_CALM, confidence=0.8)

    plan = emotion_prosody_adapter.adapt_prosody(
        assistant_response_text=body.assistant_response_text,
        emotion_profile=profile,
    )
    return plan.to_dict()


@app.get("/api/emotion-prosody/config", dependencies=[Depends(auth)])
def emotion_config_endpoint():
    return {
        "categories": [c.value for c in EmotionCategory],
        "base_period_pause_sec": emotion_prosody_adapter.base_period_pause_sec,
        "base_comma_pause_sec": emotion_prosody_adapter.base_comma_pause_sec,
    }


@app.post("/api/pause-cleaner/clean-audio", dependencies=[Depends(auth)])
def clean_audio_endpoint(payload: PauseCleanIn):
    import base64

    try:
        raw_pcm = base64.b64decode(payload.audio_base64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 audio: {e}")
    if len(raw_pcm) == 0:
        raise HTTPException(status_code=400, detail="Empty audio payload")

    wav = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0
    res = pause_breath_cleaner.clean_waveform_edges(
        wav, sample_rate=payload.sample_rate, fade_ms=payload.fade_ms
    )
    cleaned_i16 = np.clip(res.cleaned_audio * 32767.0, -32768, 32767).astype(np.int16)
    cleaned_b64 = base64.b64encode(cleaned_i16.tobytes()).decode("ascii")
    return {
        "cleaned_audio_base64": cleaned_b64,
        "leading_trimmed_samples": res.leading_trimmed_samples,
        "trailing_trimmed_samples": res.trailing_trimmed_samples,
        "breath_spike_detected": res.breath_spike_detected,
        "sample_rate": res.sample_rate,
        "duration_ms": round(len(res.cleaned_audio) / res.sample_rate * 1000.0, 2),
    }


@app.get("/api/audio-cache/metrics", dependencies=[Depends(auth)])
def audio_cache_metrics_endpoint():
    return telephony_audio_cache.get_metrics()


@app.get("/api/audio-cache/phrases", dependencies=[Depends(auth)])
def audio_cache_phrases_endpoint():
    return [
        {
            "index": i + 1,
            "text": phrase,
            "cached": telephony_audio_cache.has(phrase),
            "num_frames": len(telephony_audio_cache.get_20ms_frames(phrase))
            if telephony_audio_cache.has(phrase)
            else 0,
        }
        for i, phrase in enumerate(TOP_25_AUTOMOTIVE_PHRASES)
    ]


@app.post("/api/audio-cache/lookup", dependencies=[Depends(auth)])
def audio_cache_lookup_endpoint(payload: AudioCacheLookupIn):
    cached = telephony_audio_cache.has(payload.text)
    if cached:
        pcm = telephony_audio_cache.get(payload.text)
        frames = telephony_audio_cache.get_20ms_frames(payload.text)
        return {
            "found": True,
            "text": payload.text,
            "num_frames_20ms": len(frames),
            "byte_size": len(pcm) if pcm else 0,
            "duration_sec": round(len(pcm) / 16000.0, 3) if pcm else 0.0,
        }
    return {
        "found": False,
        "text": payload.text,
        "num_frames_20ms": 0,
        "byte_size": 0,
        "duration_sec": 0.0,
    }


@app.post("/api/audio-cache/warmup", dependencies=[Depends(auth)])
def audio_cache_warmup_endpoint():
    warmed = telephony_audio_cache.warm_cache_with_phrases(TOP_25_AUTOMOTIVE_PHRASES)
    return {
        "status": "ok",
        "warmed_count": warmed,
        "cached_count": len(telephony_audio_cache.cache),
        "metrics": telephony_audio_cache.get_metrics(),
    }


@app.post("/api/archive/call-session", dependencies=[Depends(auth)])
def archive_call_endpoint(payload: ArchiveCallIn):
    import base64

    try:
        raw_pcm = base64.b64decode(payload.audio_base64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 audio: {e}")
    if len(raw_pcm) == 0:
        raise HTTPException(status_code=400, detail="Empty audio payload")

    with Session() as db:
        res = audio_archive_engine.archive_call_session(
            audio=raw_pcm,
            sample_rate=payload.sample_rate,
            conversation_id=payload.conversation_id,
            call_session_id=payload.call_session_id,
            caller_phone=payload.caller_phone,
            codec=payload.codec,
            is_redacted=payload.is_redacted,
            retention_years=payload.retention_years,
            db=db,
        )
        return res.to_dict()


@app.get("/api/archive/retention-audit", dependencies=[Depends(auth)])
def retention_audit_endpoint():
    with Session() as db:
        return audio_archive_engine.audit_retention_compliance(db=db)


@app.post("/api/archive/retention-purge", dependencies=[Depends(auth)])
def retention_purge_endpoint(payload: ArchivePurgeIn):
    target_dt = None
    if payload.target_date:
        try:
            target_dt = datetime.fromisoformat(payload.target_date)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid target_date format: {e}")

    with Session() as db:
        return audio_archive_engine.purge_expired_archives(
            db=db,
            dry_run=payload.dry_run,
            target_date=target_dt,
        )


@app.get("/api/archive/{archive_id}/verify", dependencies=[Depends(auth)])
def verify_archive_endpoint(archive_id: str):
    with Session() as db:
        res = audio_archive_engine.verify_archive_integrity(archive_id=archive_id, db=db)
        if res.status == "missing":
            raise HTTPException(status_code=404, detail="Archive not found on disk or DB")
        return res.to_dict()


@app.get("/api/archive/{archive_id}/download", dependencies=[Depends(auth)])
def download_archive_endpoint(archive_id: str):
    with Session() as db:
        record = db.get(AudioArchive, archive_id)
        if not record:
            raise HTTPException(status_code=404, detail="Archive record not found")
        path = Path(record.file_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Archive file missing from storage")
        media_type = "audio/ogg" if record.codec == "opus" else "audio/wav"
        return FileResponse(
            path=str(path),
            media_type=media_type,
            filename=path.name,
            headers={
                "X-Freya-SHA256": record.sha256_hash,
                "X-Freya-HMAC": record.hmac_signature,
                "X-Freya-Codec": record.codec,
                "X-Freya-Retention-Expires": record.expires_at or "",
            },
        )


@app.get("/api/gpu-health/telemetry", dependencies=[Depends(auth)])
def gpu_telemetry_endpoint():
    snap = gpu_health_circuit_breaker.sample_telemetry()
    return snap.to_dict()


@app.get("/api/gpu-health/circuit-status", dependencies=[Depends(auth)])
def gpu_circuit_status_endpoint():
    return gpu_health_circuit_breaker.get_status()


@app.post("/api/gpu-health/configure", dependencies=[Depends(auth)])
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


@app.post("/api/gpu-health/simulate-oom", dependencies=[Depends(auth)])
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


@app.post("/api/gpu-health/reset", dependencies=[Depends(auth)])
def gpu_reset_endpoint():
    gpu_health_circuit_breaker.reset_circuit_breaker()
    return {
        "status": "ok",
        "circuit_status": gpu_health_circuit_breaker.get_status(),
    }


@app.get("/api/sip-trunks", dependencies=[Depends(auth)])
def list_sip_trunks_endpoint():
    return sip_trunk_failover_manager.list_trunks()


@app.get("/api/sip-trunks/{trunk_id}/ping", dependencies=[Depends(auth)])
def ping_sip_trunk_endpoint(trunk_id: str):
    try:
        res = sip_trunk_failover_manager.ping_trunk(trunk_id)
        return res.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/sip-trunks/select", dependencies=[Depends(auth)])
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


@app.post("/api/sip-trunks/simulate-outage", dependencies=[Depends(auth)])
def simulate_trunk_outage_endpoint(payload: TrunkSimulateIn):
    sip_trunk_failover_manager.simulate_trunk_outage(payload.trunk_id, outage=payload.outage)
    t = sip_trunk_failover_manager.get_trunk(payload.trunk_id)
    if not t:
        raise HTTPException(status_code=404, detail="Trunk not found")
    return {"status": "ok", "trunk": t.to_dict()}


@app.post("/api/sip-trunks/maintenance", dependencies=[Depends(auth)])
def trunk_maintenance_endpoint(payload: TrunkMaintenanceIn):
    sip_trunk_failover_manager.set_trunk_maintenance(payload.trunk_id, maintenance=payload.maintenance)
    t = sip_trunk_failover_manager.get_trunk(payload.trunk_id)
    if not t:
        raise HTTPException(status_code=404, detail="Trunk not found")
    return {"status": "ok", "trunk": t.to_dict()}


@app.post("/api/sip-trunks/configure", dependencies=[Depends(auth)])
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


@app.get("/metrics")
def prometheus_metrics_endpoint():
    """Prometheus text exposition formatı (version 0.0.4) ile anlık sistem telemetrisi."""
    content = dashboard_metrics_collector.generate_prometheus_metrics_text()
    return Response(
        content=content,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/api/sla/status", dependencies=[Depends(auth)])
def sla_status_endpoint():
    """Canlı kurumsal SLA uyumluluk durumu, ihlal kontrolleri ve skoru."""
    report = dashboard_metrics_collector.evaluate_sla_status()
    return report.to_dict()


@app.get("/api/dashboard/live-summary", dependencies=[Depends(auth)])
def dashboard_live_summary_endpoint():
    """Grafana ve web arayüzleri için konsolide anlık sistem özeti."""
    return dashboard_metrics_collector.get_live_dashboard_summary()


@app.post("/api/metrics/record-call", dependencies=[Depends(auth)])
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


@app.post("/api/sla/configure", dependencies=[Depends(auth)])
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


@app.get("/api/{resource}", dependencies=[Depends(auth)])
def listing(resource: str):
    table = {
        "vehicles": Vehicle,
        "quotes": Quote,
        "slots": Slot,
        "appointments": Appointment,
        "conversations": Conversation,
        "corporate-accounts": CorporateAccount,
        "corporate-ledger": CorporateLedger,
        "inspection-reports": InspectionReport,
        "notifications": NotificationOutbox,
        "outbound-calls": OutboundCall,
        "vehicle-diagnostics": VehicleDiagnostic,
        "inspection-lifts": InspectionLift,
        "inspection-queues": InspectionQueue,
        "ab-experiments": ABExperiment,
        "ab-assignments": ABAssignment,
        "operator-transfers": OperatorTransfer,
        "transfers": OperatorTransfer,
        "whatsapp-messages": WhatsAppMessage,
        "call-analytics": CallAnalytics,
        "ruhsat-scans": RuhsatScan,
        "vehicle-valuations": VehicleValuation,
        "inspection-bays": InspectionBay,
        "technicians": Technician,
        "bay-schedules": BaySchedule,
        "audio-archives": AudioArchive,
    }.get(resource)
    if not table:
        raise HTTPException(404)
    with Session() as db:
        return [row(x) for x in db.scalars(select(table)).all()]


@app.post("/api/corporate-accounts", dependencies=[Depends(auth)])
def create_corporate_account(body: CorporateAccountIn):
    with Session() as db:
        acc = CorporateAccount(**body.model_dump())
        db.add(acc)
        try:
            db.commit()
        except IntegrityError:
            raise HTTPException(
                409, "Bu vergi numarası ile kayıtlı bir hesap zaten var"
            )
        return row(acc)


@app.get("/api/corporate-accounts/{id}", dependencies=[Depends(auth)])
def get_corporate_account(id: str):
    with Session() as db:
        acc = db.get(CorporateAccount, id)
        if not acc:
            raise HTTPException(404, "Kurumsal cari hesap bulunamadı")
        return row(acc)


@app.put("/api/corporate-accounts/{id}", dependencies=[Depends(auth)])
def update_corporate_account(id: str, body: CorporateAccountUpdateIn):
    with Session() as db:
        acc = db.get(CorporateAccount, id)
        if not acc:
            raise HTTPException(404, "Kurumsal cari hesap bulunamadı")
        for field, val in body.model_dump(exclude_unset=True).items():
            setattr(acc, field, val)
        db.commit()
        return row(acc)


@app.delete("/api/corporate-accounts/{id}", dependencies=[Depends(auth)])
def delete_corporate_account(id: str):
    with Session() as db:
        acc = db.get(CorporateAccount, id)
        if not acc:
            raise HTTPException(404, "Kurumsal cari hesap bulunamadı")
        has_appointments = db.scalars(
            select(Appointment).where(Appointment.corporate_account_id == id)
        ).first()
        if has_appointments:
            raise HTTPException(
                409, "Bağlı randevusu olan kurumsal cari hesap silinemez"
            )
        db.delete(acc)
        db.commit()
        return {"deleted": True, "id": id}


@app.get("/api/corporate-accounts/{id}/ledger", dependencies=[Depends(auth)])
def get_corporate_ledger(id: str):
    with Session() as db:
        if not db.get(CorporateAccount, id):
            raise HTTPException(404, "Kurumsal cari hesap bulunamadı")
        entries = db.scalars(
            select(CorporateLedger)
            .where(CorporateLedger.account_id == id)
            .order_by(CorporateLedger.created_at)
        ).all()
        return [row(e) for e in entries]


@app.post("/api/corporate-accounts/{id}/payments", dependencies=[Depends(auth)])
def add_corporate_payment(id: str, body: PaymentIn):
    with Session() as db:
        try:
            ledger_entry = record_payment(
                db,
                account_id=id,
                amount_kurus=body.amount_kurus,
                description=body.description,
            )
            return row(ledger_entry)
        except ValueError as e:
            raise HTTPException(422, str(e))


@app.post("/api/vehicles", dependencies=[Depends(auth)])
def vehicle(body: VehicleIn):
    if body.vin:
        try:
            body.vin = validate_vin(body.vin)
        except ValueError as e:
            raise HTTPException(422, str(e))
    with Session() as db:
        x = Vehicle(**body.model_dump())
        db.add(x)
        db.commit()
        return row(x)


@app.put("/api/vehicles/{id}", dependencies=[Depends(auth)])
def update_vehicle(id: str, body: VehicleUpdateIn):
    with Session() as db:
        v = db.get(Vehicle, id)
        if not v:
            raise HTTPException(404, "Araç bulunamadı")
        if body.description is not None:
            v.description = body.description
        if body.plate is not None:
            v.plate = body.plate
        if body.vin is not None:
            try:
                v.vin = validate_vin(body.vin) if body.vin else ""
            except ValueError as e:
                raise HTTPException(422, str(e))
        db.commit()
        return row(v)


@app.delete("/api/vehicles/{id}", dependencies=[Depends(auth)])
def delete_vehicle(id: str):
    with Session() as db:
        v = db.get(Vehicle, id)
        if not v:
            raise HTTPException(404, "Araç bulunamadı")
        has_appointments = db.scalars(
            select(Appointment).where(Appointment.vehicle_id == id)
        ).first()
        if has_appointments:
            raise HTTPException(409, "Bağlı randevusu bulunan araç silinemez")
        quote = db.scalars(select(Quote).where(Quote.vehicle_id == id)).first()
        if quote:
            db.delete(quote)
        db.delete(v)
        db.commit()
        return {"deleted": True, "id": id}


@app.get("/api/vehicles/by-vin/{vin}", dependencies=[Depends(auth)])
def get_vehicle_by_vin(vin: str):
    try:
        clean_vin = validate_vin(vin)
    except ValueError as e:
        raise HTTPException(422, str(e))
    with Session() as db:
        v = db.scalars(select(Vehicle).where(Vehicle.vin == clean_vin)).first()
        if not v:
            raise HTTPException(404, "Bu şase numarasına ait araç bulunamadı")
        inspections = db.scalars(
            select(InspectionReport)
            .where(InspectionReport.vehicle_id == v.id)
            .order_by(InspectionReport.inspected_at.desc())
        ).all()
        return {
            "vehicle": row(v),
            "inspections": [row(i) for i in inspections],
            "inspection_count": len(inspections),
        }


@app.get("/api/vehicles/{id}/inspections", dependencies=[Depends(auth)])
def get_vehicle_inspections(id: str):
    with Session() as db:
        if not db.get(Vehicle, id):
            raise HTTPException(404, "Araç bulunamadı")
        reports = db.scalars(
            select(InspectionReport)
            .where(InspectionReport.vehicle_id == id)
            .order_by(InspectionReport.inspected_at.desc())
        ).all()
        return [row(r) for r in reports]


@app.post("/api/vehicles/{id}/inspections", dependencies=[Depends(auth)])
def add_vehicle_inspection(id: str, body: InspectionReportIn):
    with Session() as db:
        vehicle = db.get(Vehicle, id)
        if not vehicle:
            raise HTTPException(404, "Araç bulunamadı")
        appointment = None
        if body.appointment_id:
            appointment = db.get(Appointment, body.appointment_id)

        report = InspectionReport(
            vehicle_id=id,
            appointment_id=body.appointment_id,
            technician_name=body.technician_name,
            summary=body.summary,
            mileage_km=body.mileage_km,
            score=body.score,
            findings_json=json.dumps(body.findings, ensure_ascii=False),
            photos_json=json.dumps(body.photos, ensure_ascii=False),
        )
        db.add(report)
        db.flush()

        pdf_dir = settings.data_dir / "inspections" / "pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_file = pdf_dir / f"{report.id}.pdf"
        try:
            generate_inspection_pdf(report, vehicle, appointment, output_path=pdf_file)
            report.pdf_path = str(pdf_file)
        except Exception:
            report.pdf_path = None

        db.commit()
        return row(report)


@app.get("/api/inspections/{id}/pdf")
def get_inspection_pdf(id: str):
    with Session() as db:
        report = db.get(InspectionReport, id)
        if not report:
            raise HTTPException(404, "Ekspertiz raporu bulunamadı")
        vehicle = db.get(Vehicle, report.vehicle_id)
        if not vehicle:
            raise HTTPException(404, "İlişkili araç bulunamadı")
        appointment = (
            db.get(Appointment, report.appointment_id)
            if report.appointment_id
            else None
        )

        pdf_bytes = None
        if report.pdf_path and Path(report.pdf_path).is_file():
            try:
                pdf_bytes = Path(report.pdf_path).read_bytes()
            except Exception:
                pdf_bytes = None

        if not pdf_bytes:
            pdf_bytes = generate_inspection_pdf(report, vehicle, appointment)

        filename = f"ekspertiz_{vehicle.plate or id[:8]}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )


@app.post("/api/inspections/{id}/send-link", dependencies=[Depends(auth)])
def send_inspection_link(id: str):
    with Session() as db:
        report = db.get(InspectionReport, id)
        if not report:
            raise HTTPException(404, "Ekspertiz raporu bulunamadı")
        vehicle = db.get(Vehicle, report.vehicle_id)
        if not vehicle:
            raise HTTPException(404, "İlişkili araç bulunamadı")
        appointment = (
            db.get(Appointment, report.appointment_id)
            if report.appointment_id
            else None
        )

        queued = queue_inspection_delivery_notifications(
            db,
            report=report,
            vehicle=vehicle,
            appointment=appointment,
        )
        report.delivered_at = datetime.now(timezone.utc).isoformat()
        db.commit()

        dispatched = dispatch_pending_notifications(db)
        return {
            "status": "delivered",
            "delivered_at": report.delivered_at,
            "url": f"/api/inspections/{report.id}/pdf",
            "notifications_queued": len(queued),
            "notifications_dispatched": len(dispatched),
        }


@app.post("/api/inspections/photos", dependencies=[Depends(auth)])
async def upload_inspection_photo(
    file: UploadFile = File(...),
    caption: str = Form(""),
    category: str = Form("Genel"),
):
    allowed = {".jpg", ".jpeg", ".png", ".webp"}
    ext = Path(file.filename or "").suffix.lower()
    if ext not in allowed:
        raise HTTPException(
            400,
            f"Desteklenmeyen görsel formatı ({ext}). İzin verilenler: {', '.join(sorted(allowed))}",
        )

    photos_dir = settings.data_dir / "inspections" / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{secrets.token_hex(8)}{ext}"
    out_file = photos_dir / fname

    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(400, "Dosya boyutu 15MB sınırını aşamaz")

    out_file.write_bytes(content)
    return {
        "url": f"/api/inspections/photos/{fname}",
        "filename": fname,
        "caption": caption or (file.filename or "Fotoğraf"),
        "category": category or "Genel",
    }


@app.get("/api/inspections/photos/{filename}")
def get_inspection_photo(filename: str):
    clean_name = Path(filename).name
    photo_file = settings.data_dir / "inspections" / "photos" / clean_name
    if not photo_file.is_file():
        raise HTTPException(404, "Fotoğraf bulunamadı")
    return FileResponse(str(photo_file))


@app.post("/api/technician/dictate-text", dependencies=[Depends(auth)])
def technician_dictate_text(body: DictationTextIn):
    result = parse_technician_dictation(body.text)
    report_dict = None
    with Session() as db:
        if body.report_id:
            try:
                rep = apply_dictation_to_report(
                    db,
                    report_id=body.report_id,
                    findings=result["findings"],
                    summary=result["generated_summary"],
                    score=result["calculated_score"],
                )
                report_dict = row(rep)
            except ValueError as e:
                raise HTTPException(404, str(e))
        elif body.vehicle_id:
            vehicle = db.get(Vehicle, body.vehicle_id)
            if not vehicle:
                raise HTTPException(404, "Araç bulunamadı")
            rep = InspectionReport(
                vehicle_id=body.vehicle_id,
                technician_name=body.technician_name or "Uzman Teknisyen",
                summary=result["generated_summary"],
                score=result["calculated_score"],
                findings_json=json.dumps(result["findings"], ensure_ascii=False),
            )
            db.add(rep)
            db.flush()
            pdf_dir = settings.data_dir / "inspections" / "pdfs"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            pdf_file = pdf_dir / f"{rep.id}.pdf"
            try:
                generate_inspection_pdf(rep, vehicle, output_path=pdf_file)
                rep.pdf_path = str(pdf_file)
            except Exception:
                rep.pdf_path = None
            db.commit()
            report_dict = row(rep)

    return {
        **result,
        "report": report_dict,
    }


@app.post("/api/technician/dictate-audio", dependencies=[Depends(auth)])
async def technician_dictate_audio(
    file: UploadFile = File(...),
    report_id: str | None = Form(None),
    vehicle_id: str | None = Form(None),
    technician_name: str | None = Form("Uzman Teknisyen"),
):
    content = await file.read()
    if not content:
        raise HTTPException(400, "Ses dosyası boş")

    transcribed_text = ""
    try:
        import io
        import soundfile as sf
        from backend.audio import resample

        try:
            audio_data, sr = sf.read(io.BytesIO(content), dtype="float32")
            if audio_data.ndim > 1:
                audio_data = audio_data.mean(axis=1)
            if sr != 16000:
                audio_data = resample(audio_data, sr, 16000)
        except Exception:
            audio_data = io.BytesIO(content)

        if models.stt:
            transcribed_text = await models.transcribe(audio_data)
        else:
            transcribed_text = ""
    except Exception as e:
        logger.warning(f"Ses transkripsiyonu hatası: {e}")
        transcribed_text = ""

    result = parse_technician_dictation(transcribed_text)
    report_dict = None
    with Session() as db:
        if report_id:
            try:
                rep = apply_dictation_to_report(
                    db,
                    report_id=report_id,
                    findings=result["findings"],
                    summary=result["generated_summary"],
                    score=result["calculated_score"],
                )
                report_dict = row(rep)
            except ValueError as e:
                raise HTTPException(404, str(e))
        elif vehicle_id:
            vehicle = db.get(Vehicle, vehicle_id)
            if not vehicle:
                raise HTTPException(404, "Araç bulunamadı")
            rep = InspectionReport(
                vehicle_id=vehicle_id,
                technician_name=technician_name or "Uzman Teknisyen",
                summary=result["generated_summary"],
                score=result["calculated_score"],
                findings_json=json.dumps(result["findings"], ensure_ascii=False),
            )
            db.add(rep)
            db.flush()
            pdf_dir = settings.data_dir / "inspections" / "pdfs"
            pdf_dir.mkdir(parents=True, exist_ok=True)
            pdf_file = pdf_dir / f"{rep.id}.pdf"
            try:
                generate_inspection_pdf(rep, vehicle, output_path=pdf_file)
                rep.pdf_path = str(pdf_file)
            except Exception:
                rep.pdf_path = None
            db.commit()
            report_dict = row(rep)

    return {
        "transcribed_text": transcribed_text,
        **result,
        "report": report_dict,
    }


@app.post("/api/quotes", dependencies=[Depends(auth)])
def quote(body: QuoteIn):
    with Session() as db:
        if not db.get(Vehicle, body.vehicle_id):
            raise HTTPException(404, "Araç bulunamadı")
        x = db.scalars(select(Quote).where(Quote.vehicle_id == body.vehicle_id)).first()
        if x:
            x.amount_kurus = body.amount_kurus
        else:
            x = Quote(**body.model_dump())
            db.add(x)
        try:
            db.commit()
        except IntegrityError:
            raise HTTPException(409, "Fiyat eşzamanlı güncellendi; tekrar deneyin")
        return row(x)


@app.post("/api/slots", dependencies=[Depends(auth)])
def slot(body: SlotIn):
    now_utc = datetime.now(timezone.utc)
    slot_start = body.starts_at.astimezone(timezone.utc)
    if slot_start <= now_utc:
        raise HTTPException(422, "Gelecek tarih gerekli")
    slot_end = slot_start + timedelta(minutes=body.duration_minutes)
    with Session() as db:
        existing_slots = db.scalars(select(Slot)).all()
        for s in existing_slots:
            try:
                s_start = datetime.fromisoformat(s.starts_at)
                if s_start.tzinfo is None:
                    s_start = s_start.replace(tzinfo=timezone.utc)
                s_dur = getattr(s, "duration_minutes", 30) or 30
                s_end = s_start + timedelta(minutes=s_dur)
                if slot_start < s_end and slot_end > s_start:
                    raise HTTPException(
                        409, "Bu zaman aralığında çakışan bir randevu saati mevcut"
                    )
            except (ValueError, TypeError):
                continue
        x = Slot(
            starts_at=slot_start.isoformat(),
            duration_minutes=body.duration_minutes,
        )
        db.add(x)
        try:
            db.commit()
        except IntegrityError:
            raise HTTPException(409, "Saat zaten var")
        return row(x)


@app.post("/api/appointments", dependencies=[Depends(auth)])
def appointment(body: BookingIn):
    with Session() as db:
        try:
            return row(book(db, **body.model_dump()))
        except ValueError as e:
            raise HTTPException(422, str(e))
        except IntegrityError:
            raise HTTPException(409, "Saat dolu")


@app.post("/api/appointments/{id}/cancel", dependencies=[Depends(auth)])
def cancel(id: UUID):
    id = str(id)
    with Session() as db:
        x = db.get(Appointment, id)
        if not x:
            raise HTTPException(404)
        x.status = "cancelled"
        x.slot_id = None
        db.commit()
        return row(x)


@app.get("/api/conversations/{id}", dependencies=[Depends(auth)])
def detail(id: UUID):
    id = str(id)
    with Session() as db:
        if not db.get(Conversation, id):
            raise HTTPException(404)
        return [
            row(t)
            for t in db.scalars(
                select(Turn).where(Turn.conversation_id == id).order_by(Turn.created_at)
            ).all()
        ]


@app.delete("/api/conversations/{id}", dependencies=[Depends(auth)])
def delete(id: UUID):
    id = str(id)
    if active.locked():
        raise HTTPException(409, "Aktif görüşme sırasında silinemez")
    with Session() as db:
        x = db.get(Conversation, id)
        if x:
            db.delete(x)
            db.commit()
    (settings.data_dir / "recordings" / f"{id}.wav").unlink(missing_ok=True)
    return {"deleted": True}


@app.get("/api/conversations/{id}/export", dependencies=[Depends(auth)])
def export_conversation(id: UUID, format: str = "json"):
    id_str = str(id)
    with Session() as db:
        c = db.get(Conversation, id_str)
        if not c:
            raise HTTPException(404, "Görüşme bulunamadı")
        turns = db.scalars(
            select(Turn).where(Turn.conversation_id == id_str).order_by(Turn.created_at)
        ).all()
        turn_data = []
        for t in turns:
            try:
                metrics_dict = json.loads(t.metrics) if t.metrics else {}
            except Exception:
                metrics_dict = {}
            turn_data.append(
                {
                    "id": t.id,
                    "role": t.role,
                    "text": t.text,
                    "metrics": metrics_dict,
                    "created_at": t.created_at,
                }
            )
        if format.lower() == "csv":
            import csv

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(
                [
                    "conversation_id",
                    "turn_id",
                    "created_at",
                    "role",
                    "text",
                    "metrics_json",
                ]
            )
            for td in turn_data:
                writer.writerow(
                    [
                        id_str,
                        td["id"],
                        td["created_at"],
                        td["role"],
                        td["text"],
                        json.dumps(td["metrics"], ensure_ascii=False),
                    ]
                )
            return Response(
                content=output.getvalue().encode("utf-8-sig"),
                media_type="text/csv",
                headers={
                    "Content-Disposition": f'attachment; filename="conversation_{id_str}.csv"'
                },
            )
        else:
            export_payload = {
                "conversation": row(c),
                "turns": turn_data,
                "turn_count": len(turn_data),
            }
            return Response(
                content=json.dumps(export_payload, ensure_ascii=False, indent=2),
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="conversation_{id_str}.json"'
                },
            )



@app.post("/api/session-ticket", dependencies=[Depends(auth)])
def ticket():
    for k in list(tickets):
        if tickets[k] < time.monotonic():
            del tickets[k]
    token = secrets.token_urlsafe(32)
    tickets[token] = time.monotonic() + 30
    return {"ticket": token}


@app.websocket("/ws/voice")
async def voice(ws: WebSocket):
    token = ws.query_params.get("ticket", "")
    if tickets.pop(token, 0) < time.monotonic() or active.locked():
        await ws.close(code=1008)
        return
    await active.acquire()
    session = None
    greeting = None
    try:
        await ws.accept()
        hello = await asyncio.wait_for(ws.receive_json(), 5)
        rate = hello.get("sample_rate")
        if (
            rate not in (8000, 16000, 24000, 44100, 48000)
            or hello.get("encoding") != "pcm_s16le"
            or hello.get("channels") != 1
        ):
            raise ValueError("Ses biçimi desteklenmiyor")
        lock = asyncio.Lock()

        async def emit(event):
            async with lock:
                await ws.send_json(event)

        async def audio(frame):
            async with lock:
                await ws.send_bytes(frame)

        session = VoiceSession("web", emit, audio)
        greeting = asyncio.create_task(session.start())
        while not session.closed:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            text_data = message.get("text")
            if text_data:
                try:
                    payload = json.loads(text_data)
                    if payload.get("type") == "dtmf":
                        digit = str(payload.get("digit", "")).strip()
                        if digit:
                            asyncio.create_task(session.handle_dtmf(digit))
                except Exception:
                    pass
            data = message.get("bytes")
            if data:
                if len(data) > 192000:
                    raise ValueError("Ses paketi çok büyük")
                await session.input(data, rate)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        if greeting:
            greeting.cancel()
            await asyncio.gather(greeting, return_exceptions=True)
        try:
            if session:
                await session.close()
        finally:
            active.release()
            try:
                await ws.close()
            except Exception:
                pass


class ReviewIn(BaseModel):
    annotation_id: str = Field(min_length=1, max_length=128)
    decision: str
    reviewer: str = Field(min_length=1, max_length=48)
    reason_code: str


@app.get("/api/milestones/overview", dependencies=[Depends(auth)])
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


@app.post("/api/milestones/inspect", dependencies=[Depends(auth)])
def milestone_inspect(body: TextIn):
    try:
        return milestones.inspect_text(body.text)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/milestones/pronunciation", dependencies=[Depends(auth)])
def pronunciation_items():
    return milestones.reviews().items()


@app.post("/api/milestones/pronunciation", dependencies=[Depends(auth)])
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


@app.get("/api/milestones/timeline/{id}", dependencies=[Depends(auth)])
def milestone_timeline(id: UUID):
    return milestones.timeline(str(id))


if Path("frontend/dist").exists():
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="ui")
