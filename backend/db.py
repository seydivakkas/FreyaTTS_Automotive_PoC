# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
import uuid
from datetime import datetime, timezone
from sqlalchemy import BigInteger, create_engine, String, Text, ForeignKey, event, Index, Float, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from backend.config import settings

settings.data_dir.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    settings.database_url, connect_args={"check_same_thread": False, "timeout": 15}
)


@event.listens_for(engine, "connect")
def pragmas(dbapi, _):
    dbapi.execute("PRAGMA foreign_keys=ON")
    dbapi.execute("PRAGMA journal_mode=WAL")


Session = sessionmaker(engine, expire_on_commit=False)


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


class Vehicle(Base):
    __tablename__ = "vehicles"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    description: Mapped[str]
    plate: Mapped[str] = mapped_column(default="")
    vin: Mapped[str] = mapped_column(default="", server_default="")


class InspectionReport(Base):
    __tablename__ = "inspection_reports"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    vehicle_id: Mapped[str] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE")
    )
    appointment_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
    technician_name: Mapped[str] = mapped_column(
        String(120), default="Uzman Teknisyen", server_default="Uzman Teknisyen"
    )
    summary: Mapped[str] = mapped_column(Text)
    mileage_km: Mapped[int] = mapped_column(default=0, server_default="0")
    score: Mapped[int] = mapped_column(default=100, server_default="100")
    findings_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    photos_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    pdf_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivered_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    inspected_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (
        Index("ix_inspection_reports_appointment_id", "appointment_id"),
        Index("ix_inspection_reports_vehicle_id", "vehicle_id"),
    )


class VehicleDiagnostic(Base):
    __tablename__ = "vehicle_diagnostics"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    vehicle_id: Mapped[str] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE")
    )
    dtc_code: Mapped[str] = mapped_column(String(16))
    severity: Mapped[str] = mapped_column(
        String(32), default="warning", server_default="warning"
    )
    system_category: Mapped[str] = mapped_column(
        String(64), default="engine", server_default="engine"
    )
    description_tr: Mapped[str] = mapped_column(String(255))
    recommended_action: Mapped[str] = mapped_column(Text)
    current_mileage_km: Mapped[int] = mapped_column(default=0, server_default="0")
    next_service_km: Mapped[int] = mapped_column(default=0, server_default="0")
    maintenance_status: Mapped[str] = mapped_column(
        String(32), default="normal", server_default="normal"
    )
    source: Mapped[str] = mapped_column(
        String(64), default="obd_dongle", server_default="obd_dongle"
    )
    is_resolved: Mapped[bool] = mapped_column(default=False, server_default="0")
    owner_phone: Mapped[str] = mapped_column(
        String(40), default="", server_default=""
    )
    owner_name: Mapped[str] = mapped_column(
        String(120), default="", server_default=""
    )
    last_notified_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (
        Index("ix_vehicle_diagnostics_vehicle_id", "vehicle_id"),
        Index("ix_vehicle_diagnostics_dtc_code", "dtc_code"),
        Index("ix_vehicle_diagnostics_severity", "severity"),
    )


class Quote(Base):
    __tablename__ = "quotes"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("vehicles.id"), unique=True)
    amount_kurus: Mapped[int]


class Slot(Base):
    __tablename__ = "slots"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    starts_at: Mapped[str] = mapped_column(unique=True)
    duration_minutes: Mapped[int] = mapped_column(default=30, server_default="30")


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    slot_id: Mapped[str | None] = mapped_column(ForeignKey("slots.id"), unique=True)
    vehicle_id: Mapped[str] = mapped_column(ForeignKey("vehicles.id"))
    customer: Mapped[str]
    idempotency_key: Mapped[str] = mapped_column(unique=True)
    confirmed: Mapped[bool]
    status: Mapped[str] = mapped_column(default="confirmed")
    corporate_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("corporate_accounts.id", ondelete="SET NULL"), nullable=True
    )
    billed_amount_kurus: Mapped[int] = mapped_column(default=0, server_default="0")
    package_type: Mapped[str] = mapped_column(
        String(64), default="standart_ekspertiz", server_default="standart_ekspertiz"
    )
    customer_phone: Mapped[str] = mapped_column(
        String(40), default="", server_default=""
    )
    created_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (
        Index("ix_appointments_vehicle_id", "vehicle_id"),
        Index("ix_appointments_status", "status"),
        Index("ix_appointments_created_at", "created_at"),
        Index("ix_appointments_customer_phone", "customer_phone"),
    )


class InspectionLift(Base):
    __tablename__ = "inspection_lifts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    lift_number: Mapped[int] = mapped_column(unique=True)
    status: Mapped[str] = mapped_column(
        String(32), default="idle", server_default="idle"
    )  # "idle" | "busy" | "maintenance"
    current_appointment_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
    current_vehicle_plate: Mapped[str] = mapped_column(
        String(32), default="", server_default=""
    )
    package_type: Mapped[str] = mapped_column(
        String(64), default="standart_ekspertiz", server_default="standart_ekspertiz"
    )
    started_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    estimated_duration_min: Mapped[int] = mapped_column(
        default=45, server_default="45"
    )
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (
        Index("ix_inspection_lifts_status", "status"),
        Index("ix_inspection_lifts_lift_number", "lift_number"),
    )


class InspectionQueue(Base):
    __tablename__ = "inspection_queues"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    queue_number: Mapped[int]
    appointment_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
    vehicle_id: Mapped[str | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )
    plate: Mapped[str] = mapped_column(String(32))
    customer: Mapped[str] = mapped_column(String(120))
    package_type: Mapped[str] = mapped_column(
        String(64), default="standart_ekspertiz", server_default="standart_ekspertiz"
    )
    duration_minutes: Mapped[int] = mapped_column(
        default=45, server_default="45"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="waiting", server_default="waiting"
    )  # "waiting" | "in_progress" | "completed" | "cancelled"
    lift_id: Mapped[str | None] = mapped_column(
        ForeignKey("inspection_lifts.id", ondelete="SET NULL"), nullable=True
    )
    check_in_at: Mapped[str] = mapped_column(default=now)
    started_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        Index("ix_inspection_queues_status", "status"),
        Index("ix_inspection_queues_check_in_at", "check_in_at"),
    )


class CorporateAccount(Base):
    __tablename__ = "corporate_accounts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str]
    tax_id: Mapped[str] = mapped_column(unique=True)
    phone: Mapped[str] = mapped_column(default="", server_default="")
    credit_limit_kurus: Mapped[int] = mapped_column(
        default=5000000, server_default="5000000"
    )
    balance_kurus: Mapped[int] = mapped_column(default=0, server_default="0")
    discount_percent: Mapped[int] = mapped_column(default=10, server_default="10")
    active: Mapped[bool] = mapped_column(default=True, server_default="1")
    created_at: Mapped[str] = mapped_column(default=now)


class CorporateLedger(Base):
    __tablename__ = "corporate_ledger"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("corporate_accounts.id", ondelete="CASCADE")
    )
    appointment_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
    entry_type: Mapped[str]
    amount_kurus: Mapped[int]
    balance_after_kurus: Mapped[int]
    description: Mapped[str] = mapped_column(default="", server_default="")
    created_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (Index("ix_corporate_ledger_account_id", "account_id"),)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    channel: Mapped[str]
    status: Mapped[str] = mapped_column(default="active", server_default="active")
    operator_notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    resolved_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    follow_up_kind: Mapped[str | None] = mapped_column(String(24))
    follow_up_at: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (
        Index("ix_conversations_status", "status"),
        Index("ix_conversations_created_at", "created_at"),
    )


class Turn(Base):
    __tablename__ = "turns"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str]
    text: Mapped[str] = mapped_column(Text)
    metrics: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (Index("ix_turns_conversation_id", "conversation_id"),)


class SupervisorTrace(Base):
    __tablename__ = "supervisor_traces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True,
    )
    payload: Mapped[str] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(24), default="PENDING")
    review_labels: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40), default=now, index=True)


class FqiciScope(Base):
    __tablename__ = "fqici_scopes"
    id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    transport: Mapped[str] = mapped_column(String(12))
    origin: Mapped[str] = mapped_column(String(12))
    transport_id: Mapped[str | None] = mapped_column(String(36))
    terminal_seen: Mapped[bool] = mapped_column(default=False, index=True)
    dirty_since_ms: Mapped[int | None] = mapped_column(BigInteger)
    ready_at_ms: Mapped[int | None] = mapped_column(BigInteger, index=True)


class FqiciEvent(Base):
    __tablename__ = "fqici_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_id: Mapped[str] = mapped_column(ForeignKey("fqici_scopes.id", ondelete="CASCADE"), index=True)
    producer: Mapped[str] = mapped_column(String(24))
    source_event_id: Mapped[str] = mapped_column(String(36))
    evidence: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[str] = mapped_column(String(40), default=now)
    __table_args__ = (UniqueConstraint("producer", "source_event_id", name="uq_fqici_source_event"),)


class FqiciRun(Base):
    __tablename__ = "fqici_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    scope_id: Mapped[str] = mapped_column(ForeignKey("fqici_scopes.id", ondelete="CASCADE"), index=True)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    rule_version: Mapped[str] = mapped_column(String(32))
    event_ids: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(24), index=True)
    created_at_ms: Mapped[int] = mapped_column(BigInteger)
    available_at_ms: Mapped[int] = mapped_column(BigInteger)
    fence: Mapped[int] = mapped_column(default=0)
    lease_until_ms: Mapped[int | None] = mapped_column(BigInteger)
    __table_args__ = (UniqueConstraint("scope_id", "evidence_hash", "rule_version", name="uq_fqici_run_snapshot"),)


class IntentTrainingCandidate(Base):
    __tablename__ = "intent_training_candidates"
    trace_id: Mapped[str] = mapped_column(
        ForeignKey("supervisor_traces.id", ondelete="CASCADE"), primary_key=True,
    )
    text_digest: Mapped[str] = mapped_column(String(64), unique=True)
    group_id: Mapped[str] = mapped_column(String(36), index=True)
    split: Mapped[str] = mapped_column(String(12))
    example: Mapped[str] = mapped_column(Text)


class SupervisorWriteReceipt(Base):
    __tablename__ = "supervisor_write_receipts"
    key: Mapped[str] = mapped_column(String(36), primary_key=True)
    action: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40), default=now)


class ABExperiment(Base):
    __tablename__ = "ab_experiments"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    experiment_type: Mapped[str] = mapped_column(
        String(40), default="composite", server_default="composite"
    )  # "prompt" | "tts_seed" | "greeting" | "composite"
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active"
    )  # "active" | "paused" | "completed"
    variants_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    target_metric: Mapped[str] = mapped_column(
        String(40), default="conversion_rate", server_default="conversion_rate"
    )
    created_at: Mapped[str] = mapped_column(default=now)
    updated_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (
        Index("ix_ab_experiments_status", "status"),
    )


class ABAssignment(Base):
    __tablename__ = "ab_assignments"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), unique=True
    )
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("ab_experiments.id", ondelete="CASCADE")
    )
    variant_id: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending"
    )  # "pending" | "converted" | "abandoned"
    first_audio_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    tts_total_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_total_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    turns_count: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[str] = mapped_column(default=now)
    completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        Index("ix_ab_assignments_experiment_id", "experiment_id"),
        Index("ix_ab_assignments_variant_id", "variant_id"),
        Index("ix_ab_assignments_outcome", "outcome"),
    )


class NotificationOutbox(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    appointment_id: Mapped[str] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE")
    )
    recipient_type: Mapped[str] = mapped_column(String(32))  # "customer" | "corporate"
    recipient: Mapped[str] = mapped_column(String(120))
    channel: Mapped[str] = mapped_column(
        String(32), default="sms", server_default="sms"
    )
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending"
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(default=now)
    sent_at: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_notifications_status_created_at", "status", "created_at"),
        Index("ix_notifications_appointment_id", "appointment_id"),
    )


class OutboundCall(Base):
    __tablename__ = "outbound_calls"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    appointment_id: Mapped[str] = mapped_column(
        ForeignKey("appointments.id", ondelete="CASCADE")
    )
    phone: Mapped[str] = mapped_column(String(40))
    customer: Mapped[str] = mapped_column(String(120))
    call_type: Mapped[str] = mapped_column(
        String(32), default="reminder", server_default="reminder"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="queued", server_default="queued"
    )
    outcome: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending"
    )
    action_id: Mapped[str] = mapped_column(String(64), default="", server_default="")
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(default=now)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_outbound_calls_status_created_at", "status", "created_at"),
        Index("ix_outbound_calls_appointment_id", "appointment_id"),
    )


class OperatorTransfer(Base):
    __tablename__ = "operator_transfers"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    caller_channel: Mapped[str] = mapped_column(
        String(120), default="", server_default=""
    )
    operator_extension: Mapped[str] = mapped_column(
        String(32), default="6002", server_default="6002"
    )
    customer_name: Mapped[str] = mapped_column(
        String(120), default="", server_default=""
    )
    vehicle_plate: Mapped[str] = mapped_column(
        String(32), default="", server_default=""
    )
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    whisper_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(
        String(32), default="initiated", server_default="initiated"
    )  # "initiated", "whispering", "accepted", "declined", "timeout", "failed"
    sip_headers_json: Mapped[str] = mapped_column(
        Text, default="{}", server_default="{}"
    )
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[str] = mapped_column(default=now)
    completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

    __table_args__ = (
        Index("ix_operator_transfers_status", "status"),
        Index("ix_operator_transfers_conversation_id", "conversation_id"),
        Index("ix_operator_transfers_created_at", "created_at"),
    )


class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    message_sid: Mapped[str] = mapped_column(
        String(128), default="", server_default=""
    )
    from_phone: Mapped[str] = mapped_column(
        String(40), default="", server_default=""
    )
    customer_name: Mapped[str] = mapped_column(
        String(120), default="", server_default=""
    )
    message_type: Mapped[str] = mapped_column(
        String(32), default="text", server_default="text"
    )
    raw_content: Mapped[str] = mapped_column(Text, default="", server_default="")
    transcription: Mapped[str] = mapped_column(Text, default="", server_default="")
    extracted_intent: Mapped[str] = mapped_column(
        String(40), default="unknown", server_default="unknown"
    )
    extracted_time: Mapped[str] = mapped_column(
        String(40), default="", server_default=""
    )
    appointment_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
    reply_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    outbound_calls_cancelled: Mapped[int] = mapped_column(
        default=0, server_default="0"
    )
    processed: Mapped[bool] = mapped_column(default=True, server_default="1")
    created_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (
        Index("ix_whatsapp_messages_from_phone", "from_phone"),
        Index("ix_whatsapp_messages_appointment_id", "appointment_id"),
        Index("ix_whatsapp_messages_created_at", "created_at"),
    )


class CallAnalytics(Base):
    __tablename__ = "call_analytics"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    appointment_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
    caller_phone: Mapped[str] = mapped_column(
        String(40), default="", server_default=""
    )
    caller_name: Mapped[str] = mapped_column(
        String(120), default="", server_default=""
    )
    executive_summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    intent: Mapped[str] = mapped_column(
        String(64), default="unknown", server_default="unknown"
    )
    csat_score: Mapped[float] = mapped_column(Float, default=3.0, server_default="3.0")
    sentiment: Mapped[str] = mapped_column(
        String(32), default="neutral", server_default="neutral"
    )
    lead_score: Mapped[int] = mapped_column(default=50, server_default="50")
    lead_tier: Mapped[str] = mapped_column(
        String(16), default="WARM", server_default="WARM"
    )  # "HOT", "WARM", "COLD"
    objections_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    topics_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    recommended_action: Mapped[str] = mapped_column(Text, default="", server_default="")
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (
        Index("ix_call_analytics_conversation_id", "conversation_id"),
        Index("ix_call_analytics_lead_tier", "lead_tier"),
        Index("ix_call_analytics_created_at", "created_at"),
    )


class RuhsatScan(Base):
    __tablename__ = "ruhsat_scans"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    vehicle_id: Mapped[str | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )
    appointment_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
    from_phone: Mapped[str] = mapped_column(
        String(40), default="", server_default=""
    )
    plate: Mapped[str] = mapped_column(String(32), default="", server_default="")
    vin: Mapped[str] = mapped_column(String(32), default="", server_default="")
    engine_code: Mapped[str] = mapped_column(
        String(32), default="", server_default=""
    )
    model_year: Mapped[int | None] = mapped_column(nullable=True)
    brand_model: Mapped[str] = mapped_column(
        String(120), default="", server_default=""
    )
    document_serial: Mapped[str] = mapped_column(
        String(32), default="", server_default=""
    )
    owner_name: Mapped[str] = mapped_column(
        String(120), default="", server_default=""
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0")
    raw_extracted_text: Mapped[str] = mapped_column(
        Text, default="", server_default=""
    )
    created_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (
        Index("ix_ruhsat_scans_plate", "plate"),
        Index("ix_ruhsat_scans_vin", "vin"),
        Index("ix_ruhsat_scans_from_phone", "from_phone"),
        Index("ix_ruhsat_scans_created_at", "created_at"),
    )


class VehicleValuation(Base):
    __tablename__ = "vehicle_valuations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    appointment_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
    plate: Mapped[str] = mapped_column(String(32), default="", server_default="")
    brand: Mapped[str] = mapped_column(String(64), default="", server_default="")
    model: Mapped[str] = mapped_column(String(64), default="", server_default="")
    model_year: Mapped[int] = mapped_column(default=2020, server_default="2020")
    fuel_type: Mapped[str] = mapped_column(
        String(32), default="benzin", server_default="benzin"
    )
    transmission: Mapped[str] = mapped_column(
        String(32), default="otomatik", server_default="otomatik"
    )
    mileage_km: Mapped[int] = mapped_column(default=0, server_default="0")
    body_condition_json: Mapped[str] = mapped_column(
        Text, default="{}", server_default="{}"
    )
    tramer_amount_tl: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0.0"
    )
    is_heavy_damage: Mapped[bool] = mapped_column(
        default=False, server_default="0"
    )
    base_benchmark_tl: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0.0"
    )
    estimated_market_value_tl: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0.0"
    )
    cash_buy_offer_tl: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0.0"
    )
    trade_in_offer_tl: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0.0"
    )
    valuation_range_min_tl: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0.0"
    )
    valuation_range_max_tl: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0.0"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="quoted", server_default="quoted"
    )
    created_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (
        Index("ix_vehicle_valuations_plate", "plate"),
        Index("ix_vehicle_valuations_conversation_id", "conversation_id"),
        Index("ix_vehicle_valuations_created_at", "created_at"),
    )


class InspectionBay(Base):
    __tablename__ = "inspection_bays"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    bay_number: Mapped[int] = mapped_column(unique=True)
    bay_type: Mapped[str] = mapped_column(
        String(64), default="mechanic_underbody", server_default="mechanic_underbody"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="idle", server_default="idle"
    )  # "idle" | "busy" | "maintenance"
    current_appointment_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
    current_vehicle_plate: Mapped[str] = mapped_column(
        String(32), default="", server_default=""
    )
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (
        Index("ix_inspection_bays_bay_type", "bay_type"),
        Index("ix_inspection_bays_status", "status"),
        Index("ix_inspection_bays_bay_number", "bay_number"),
    )


class Technician(Base):
    __tablename__ = "technicians"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(
        String(120), default="Uzman Teknisyen", server_default="Uzman Teknisyen"
    )
    specialties_json: Mapped[str] = mapped_column(
        Text, default="[]", server_default="[]"
    )
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1")
    daily_capacity: Mapped[int] = mapped_column(default=8, server_default="8")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (Index("ix_technicians_is_active", "is_active"),)


class BaySchedule(Base):
    __tablename__ = "bay_schedules"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    appointment_id: Mapped[str | None] = mapped_column(
        ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
    bay_id: Mapped[str] = mapped_column(
        ForeignKey("inspection_bays.id", ondelete="CASCADE")
    )
    technician_id: Mapped[str | None] = mapped_column(
        ForeignKey("technicians.id", ondelete="SET NULL"), nullable=True
    )
    package_type: Mapped[str] = mapped_column(
        String(64), default="standart_ekspertiz", server_default="standart_ekspertiz"
    )
    stage_name: Mapped[str] = mapped_column(String(120))
    stage_index: Mapped[int] = mapped_column(default=1, server_default="1")
    starts_at: Mapped[str] = mapped_column(String(40))
    ends_at: Mapped[str] = mapped_column(String(40))
    duration_minutes: Mapped[int] = mapped_column(default=15, server_default="15")
    status: Mapped[str] = mapped_column(
        String(32), default="scheduled", server_default="scheduled"
    )  # "scheduled" | "in_progress" | "completed" | "cancelled"
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (
        Index("ix_bay_schedules_appointment_id", "appointment_id"),
        Index("ix_bay_schedules_bay_id", "bay_id"),
        Index("ix_bay_schedules_starts_at", "starts_at"),
        Index("ix_bay_schedules_status", "status"),
    )


class AudioArchive(Base):
    __tablename__ = "audio_archives"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    call_session_id: Mapped[str] = mapped_column(
        String(80), default="", server_default=""
    )
    caller_phone: Mapped[str] = mapped_column(
        String(40), default="", server_default=""
    )
    codec: Mapped[str] = mapped_column(
        String(20), default="opus", server_default="opus"
    )
    channels: Mapped[int] = mapped_column(default=1, server_default="1")
    sample_rate: Mapped[int] = mapped_column(default=8000, server_default="8000")
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0")
    raw_size_bytes: Mapped[int] = mapped_column(default=0, server_default="0")
    compressed_size_bytes: Mapped[int] = mapped_column(default=0, server_default="0")
    compression_ratio_percent: Mapped[float] = mapped_column(
        Float, default=0.0, server_default="0.0"
    )
    sha256_hash: Mapped[str] = mapped_column(
        String(64), default="", server_default=""
    )
    raw_sha256_hash: Mapped[str] = mapped_column(
        String(64), default="", server_default=""
    )
    hmac_signature: Mapped[str] = mapped_column(
        String(64), default="", server_default=""
    )
    file_path: Mapped[str] = mapped_column(
        String(255), default="", server_default=""
    )
    retention_years: Mapped[int] = mapped_column(default=2, server_default="2")
    expires_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_redacted: Mapped[bool] = mapped_column(default=False, server_default="0")
    status: Mapped[str] = mapped_column(
        String(32), default="active", server_default="active"
    )
    created_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (
        Index("ix_audio_archives_conversation_id", "conversation_id"),
        Index("ix_audio_archives_call_session_id", "call_session_id"),
        Index("ix_audio_archives_status", "status"),
        Index("ix_audio_archives_created_at", "created_at"),
        Index("ix_audio_archives_expires_at", "expires_at"),
    )


class KVKKErasureRequest(Base):
    __tablename__ = "kvkk_erasure_requests"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    identifier_type: Mapped[str] = mapped_column(
        String(32)
    )  # "phone" | "plate" | "customer_name" | "conversation_id"
    identifier_value: Mapped[str] = mapped_column(String(120))
    requester_name: Mapped[str] = mapped_column(
        String(120), default="", server_default=""
    )
    reason: Mapped[str] = mapped_column(
        String(255),
        default="KVKK Madde 11 uyarınca silme talebi",
        server_default="KVKK Madde 11 uyarınca silme talebi",
    )
    status: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending"
    )  # "pending" | "executed" | "rejected"
    impact_summary_json: Mapped[str] = mapped_column(
        Text, default="{}", server_default="{}"
    )
    certificate_sha256: Mapped[str] = mapped_column(
        String(64), default="", server_default=""
    )
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[str] = mapped_column(default=now)
    executed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    executed_by: Mapped[str] = mapped_column(
        String(80), default="admin", server_default="admin"
    )

    __table_args__ = (
        Index("ix_kvkk_erasure_requests_status", "status"),
        Index("ix_kvkk_erasure_requests_identifier_value", "identifier_value"),
        Index("ix_kvkk_erasure_requests_created_at", "created_at"),
    )


class CallerProfile(Base):
    __tablename__ = "caller_profiles"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    phone: Mapped[str] = mapped_column(
        String(40), default="", server_default=""
    )
    plate: Mapped[str] = mapped_column(
        String(32), default="", server_default=""
    )
    name: Mapped[str] = mapped_column(
        String(120), default="", server_default=""
    )
    vehicle_model: Mapped[str] = mapped_column(
        String(120), default="", server_default=""
    )
    warranty_expires_at: Mapped[str | None] = mapped_column(
        String(40), nullable=True
    )
    warranty_status: Mapped[str] = mapped_column(
        String(32), default="active", server_default="active"
    )
    maintenance_history_json: Mapped[str] = mapped_column(
        Text, default="[]", server_default="[]"
    )
    inspection_scores_json: Mapped[str] = mapped_column(
        Text, default="[]", server_default="[]"
    )
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    user_preferences_json: Mapped[str] = mapped_column(
        Text, default="{}", server_default="{}"
    )
    created_at: Mapped[str] = mapped_column(default=now)
    updated_at: Mapped[str] = mapped_column(default=now)

    __table_args__ = (
        Index("ix_caller_profiles_phone", "phone"),
        Index("ix_caller_profiles_plate", "plate"),
        Index("ix_caller_profiles_name", "name"),
    )


def book(
    db,
    *,
    slot_id,
    vehicle_id,
    customer,
    idempotency_key,
    confirmed,
    corporate_account_id=None,
    customer_phone="",
    package_type="standart_ekspertiz",
    plate="",
):
    if not confirmed:
        raise ValueError("Açık müşteri onayı gerekli")
    old = db.query(Appointment).filter_by(idempotency_key=idempotency_key).first()
    if old:
        if (old.slot_id, old.vehicle_id, old.customer) != (
            slot_id,
            vehicle_id,
            customer,
        ):
            raise ValueError("İşlem anahtarı farklı bir istekte kullanılmış")
        return old
    slot = db.get(Slot, slot_id)
    vehicle = db.get(Vehicle, vehicle_id)
    if not slot or not vehicle:
        raise ValueError("Araç veya saat bulunamadı")
    if datetime.fromisoformat(slot.starts_at) <= datetime.now(timezone.utc):
        raise ValueError("Geçmiş saate randevu oluşturulamaz")

    if plate and vehicle:
        vehicle.plate = plate

    billed_charge = 0
    account = None
    if corporate_account_id:
        account = db.get(CorporateAccount, corporate_account_id)
        if not account:
            raise ValueError("Kurumsal cari hesap bulunamadı")
        if not account.active:
            raise ValueError("Kurumsal cari hesap aktif değil / bloke edilmiş")
        quote = db.query(Quote).filter_by(vehicle_id=vehicle_id).first()
        base_fee = quote.amount_kurus if quote else 0
        discount = (base_fee * account.discount_percent) // 100
        billed_charge = base_fee - discount
        if account.balance_kurus + billed_charge > account.credit_limit_kurus:
            raise ValueError(
                f"Kurumsal kredi limiti aşıldı (Mevcut Bakiye: {account.balance_kurus // 100} TL, Limit: {account.credit_limit_kurus // 100} TL)"
            )
        account.balance_kurus += billed_charge

    obj = Appointment(
        slot_id=slot_id,
        vehicle_id=vehicle_id,
        customer=customer,
        customer_phone=(customer_phone or "").strip(),
        idempotency_key=idempotency_key,
        confirmed=True,
        corporate_account_id=corporate_account_id,
        billed_amount_kurus=billed_charge,
        package_type=package_type,
    )
    db.add(obj)
    db.flush()

    if corporate_account_id and billed_charge > 0:
        ledger = CorporateLedger(
            account_id=corporate_account_id,
            appointment_id=obj.id,
            entry_type="charge",
            amount_kurus=billed_charge,
            balance_after_kurus=account.balance_kurus,
            description=f"{customer} - Ekspertiz randevu bedeli",
        )
        db.add(ledger)

    # M10 Transactional Outbox: Musteri ve Galeri Bildirimlerini Kuyruga Al
    from backend.notifications import (
        queue_appointment_notifications,
        dispatch_pending_notifications,
    )

    queue_appointment_notifications(
        db,
        appointment=obj,
        slot=slot,
        vehicle=vehicle,
        account=account,
        customer_phone=customer_phone,
    )

    db.commit()

    # Commit sonrasi beklemeden gonderim denemesi
    try:
        dispatch_pending_notifications(db, limit=5)
    except Exception:
        pass

    return obj


def cancel_appointment(db, appointment, *, commit=True):
    """Randevuyu iptal eder, saati boşaltır ve kurumsal ücreti bir kez iade eder.

    Tüm iptal yolları (API, sesli diyalog, giden arama, WhatsApp) bunu kullanır.
    İade, defterde bu randevuya ait 'reversal' satırı varsa tekrarlanmaz (idempotent).
    """
    appointment.status = "cancelled"
    appointment.slot_id = None
    billed = appointment.billed_amount_kurus or 0
    if appointment.corporate_account_id and billed > 0:
        already = (
            db.query(CorporateLedger)
            .filter_by(appointment_id=appointment.id, entry_type="reversal")
            .first()
        )
        account = db.get(CorporateAccount, appointment.corporate_account_id)
        if account and not already:
            account.balance_kurus -= billed
            db.add(
                CorporateLedger(
                    account_id=account.id,
                    appointment_id=appointment.id,
                    entry_type="reversal",
                    amount_kurus=-billed,
                    balance_after_kurus=account.balance_kurus,
                    description=f"{appointment.customer} - Randevu iptali iadesi",
                )
            )
    if commit:
        db.commit()
    return appointment


def record_payment(
    db,
    *,
    account_id: str,
    amount_kurus: int,
    description: str = "Tahsilat / Ödeme",
):
    if amount_kurus <= 0:
        raise ValueError("Ödeme tutarı 0'dan büyük olmalıdır")
    account = db.get(CorporateAccount, account_id)
    if not account:
        raise ValueError("Kurumsal cari hesap bulunamadı")
    account.balance_kurus -= amount_kurus
    ledger = CorporateLedger(
        account_id=account_id,
        entry_type="payment",
        amount_kurus=-amount_kurus,
        balance_after_kurus=account.balance_kurus,
        description=description,
    )
    db.add(ledger)
    db.commit()
    return ledger
