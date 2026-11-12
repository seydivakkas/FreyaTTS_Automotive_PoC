# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""Pydantic istek modelleri."""

from typing import (
    Any,
    Literal,
    List,
    Dict,
    Union,
    Optional,
)
from pydantic import (
    BaseModel,
    Field,
    AwareDatetime,
)
from backend.deps import AUDIO_B64_MAX


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class DSPProcessIn(BaseModel):
    audio_base64: str = Field(min_length=1, max_length=AUDIO_B64_MAX)
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
    mileage_km: int = Field(ge=0)  # zorunlu: 0 km uydurulmaz (frontend de zorunlu tutuyor)
    # Zorunlu: sessizce 100 puan (kusursuz) uydurulmaz; frontend de zorunlu tutuyor
    score: int = Field(ge=0, le=100)
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


class RescheduleIn(BaseModel):
    target_slot_id: str | None = None
    new_starts_at: AwareDatetime | None = None
    preview_version: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class FeedbackLexiconIn(BaseModel):
    term: str = Field(min_length=1, max_length=100)
    spoken: str = Field(min_length=1, max_length=160)
    category: str = Field(default="custom", max_length=50)
    turn_id: str | None = None



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
    audio_base64: str = Field(min_length=1, max_length=AUDIO_B64_MAX)
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


class KVKKErasureRequestIn(BaseModel):
    identifier_type: Literal["phone", "plate", "customer_name", "conversation_id"] = "phone"
    identifier_value: str = Field(min_length=1, max_length=120)
    requester_name: str = Field(default="", max_length=120)
    reason: str = Field(
        default="KVKK Madde 11 uyarınca silme talebi", max_length=255
    )
    notes: str = Field(default="", max_length=1000)


class TranscriptRetentionPurgeIn(BaseModel):
    dry_run: bool = True
    target_date: str | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)


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
    audio_base64: str | None = Field(default=None, max_length=AUDIO_B64_MAX)
    sample_rate: int = Field(default=16000, ge=8000, le=48000)


class TurnAnalyzeTextIn(BaseModel):
    text: str = Field(default="", max_length=1000)


class EmotionAnalyzeIn(BaseModel):
    transcript: str = Field(default="", max_length=2000)
    audio_base64: str | None = Field(default=None, max_length=AUDIO_B64_MAX)
    audio_duration_sec: float | None = None
    sample_rate: int = Field(default=16000, ge=8000, le=48000)


class EmotionAdaptIn(BaseModel):
    assistant_response_text: str = Field(min_length=1, max_length=2000)
    caller_transcript: str | None = None
    emotion_category: str | None = None


class PauseCleanIn(BaseModel):
    audio_base64: str = Field(min_length=4, max_length=AUDIO_B64_MAX)
    sample_rate: int = Field(default=8000, ge=8000, le=48000)
    fade_ms: float = Field(default=12.0, ge=1.0, le=50.0)


class AudioCacheLookupIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ArchiveCallIn(BaseModel):
    audio_base64: str = Field(min_length=4, max_length=AUDIO_B64_MAX)
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
    mos_score: float | None = None
    rtf: float | None = None


class QAEvaluateVariantsIn(BaseModel):
    samples: list[tuple[str, str]] | None = None


class M11AcceptanceIn(BaseModel):
    has_physical_pbx_trace: bool = False
    has_hardware_trunk: bool = False
    evidence_files: list[str] = Field(default_factory=list)


class MorphologicalCheckIn(BaseModel):
    text: str
    include_hints: bool = True
    chunk_id: Optional[str] = "chunk_0"


class ReviewIn(BaseModel):
    annotation_id: str = Field(min_length=1, max_length=128)
    decision: str
    reviewer: str = Field(min_length=1, max_length=48)
    reason_code: str


class InboundMetadataIn(BaseModel):
    call_uuid: str = Field(min_length=8, max_length=64)
    caller_id: str = Field(default="", max_length=40)
    caller_channel: str = Field(default="", max_length=120)
    did: str = Field(default="", max_length=40)


class TestNotificationIn(BaseModel):
    channel: str = Field(pattern="^(sms|whatsapp)$")
    recipient: str = Field(min_length=7, max_length=40)
    message: str = Field(min_length=1, max_length=1000)

