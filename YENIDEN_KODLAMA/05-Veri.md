# Kalıcı veri modeli

SQLite dış anahtar denetimi ve WAL açık, bağlantı bekleme süresi 15 saniye. Kimlik ve zaman damgası dahil Python tarafında verilen varsayılanlar SQL DDL içinde görünmeyebilir. Alan başlangıçları aşağıda ORM ifadeleriyle verilmiştir. Migration sırası ve veri dönüşümleri son bölümde yer alır.

```sql

CREATE TABLE ab_experiments (
	id VARCHAR NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	description TEXT DEFAULT '' NOT NULL, 
	experiment_type VARCHAR(40) DEFAULT 'composite' NOT NULL, 
	status VARCHAR(20) DEFAULT 'active' NOT NULL, 
	variants_json TEXT DEFAULT '[]' NOT NULL, 
	target_metric VARCHAR(40) DEFAULT 'conversion_rate' NOT NULL, 
	created_at VARCHAR NOT NULL, 
	updated_at VARCHAR NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX ix_ab_experiments_status ON ab_experiments (status);

CREATE TABLE caller_profiles (
	id VARCHAR NOT NULL, 
	phone VARCHAR(40) DEFAULT '' NOT NULL, 
	plate VARCHAR(32) DEFAULT '' NOT NULL, 
	name VARCHAR(120) DEFAULT '' NOT NULL, 
	vehicle_model VARCHAR(120) DEFAULT '' NOT NULL, 
	warranty_expires_at VARCHAR(40), 
	warranty_status VARCHAR(32) DEFAULT 'active' NOT NULL, 
	maintenance_history_json TEXT DEFAULT '[]' NOT NULL, 
	inspection_scores_json TEXT DEFAULT '[]' NOT NULL, 
	notes TEXT DEFAULT '' NOT NULL, 
	user_preferences_json TEXT DEFAULT '{}' NOT NULL, 
	created_at VARCHAR NOT NULL, 
	updated_at VARCHAR NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX ix_caller_profiles_name ON caller_profiles (name);
CREATE INDEX ix_caller_profiles_phone ON caller_profiles (phone);
CREATE INDEX ix_caller_profiles_plate ON caller_profiles (plate);

CREATE TABLE conversations (
	id VARCHAR NOT NULL, 
	channel VARCHAR NOT NULL, 
	status VARCHAR DEFAULT 'active' NOT NULL, 
	operator_notes TEXT DEFAULT '' NOT NULL, 
	resolved_at VARCHAR(40), 
	follow_up_kind VARCHAR(24), 
	follow_up_at VARCHAR(40), 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX ix_conversations_created_at ON conversations (created_at);
CREATE INDEX ix_conversations_status ON conversations (status);

CREATE TABLE corporate_accounts (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	tax_id VARCHAR NOT NULL, 
	phone VARCHAR DEFAULT '' NOT NULL, 
	credit_limit_kurus INTEGER DEFAULT '5000000' NOT NULL, 
	balance_kurus INTEGER DEFAULT '0' NOT NULL, 
	discount_percent INTEGER DEFAULT '10' NOT NULL, 
	active BOOLEAN DEFAULT '1' NOT NULL, 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (tax_id)
)

;

CREATE TABLE kvkk_erasure_requests (
	id VARCHAR NOT NULL, 
	identifier_type VARCHAR(32) NOT NULL, 
	identifier_value VARCHAR(120) NOT NULL, 
	requester_name VARCHAR(120) DEFAULT '' NOT NULL, 
	reason VARCHAR(255) DEFAULT 'KVKK Madde 11 uyarınca silme talebi' NOT NULL, 
	status VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	impact_summary_json TEXT DEFAULT '{}' NOT NULL, 
	certificate_sha256 VARCHAR(64) DEFAULT '' NOT NULL, 
	notes TEXT DEFAULT '' NOT NULL, 
	created_at VARCHAR NOT NULL, 
	executed_at VARCHAR(40), 
	executed_by VARCHAR(80) DEFAULT 'admin' NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX ix_kvkk_erasure_requests_created_at ON kvkk_erasure_requests (created_at);
CREATE INDEX ix_kvkk_erasure_requests_identifier_value ON kvkk_erasure_requests (identifier_value);
CREATE INDEX ix_kvkk_erasure_requests_status ON kvkk_erasure_requests (status);

CREATE TABLE slots (
	id VARCHAR NOT NULL, 
	starts_at VARCHAR NOT NULL, 
	duration_minutes INTEGER DEFAULT '30' NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (starts_at)
)

;

CREATE TABLE supervisor_write_receipts (
	"key" VARCHAR(36) NOT NULL, 
	action VARCHAR(64) NOT NULL, 
	request_digest VARCHAR(64) NOT NULL, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY ("key")
)

;

CREATE TABLE technicians (
	id VARCHAR NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	title VARCHAR(120) DEFAULT 'Uzman Teknisyen' NOT NULL, 
	specialties_json TEXT DEFAULT '[]' NOT NULL, 
	is_active BOOLEAN DEFAULT '1' NOT NULL, 
	daily_capacity INTEGER DEFAULT '8' NOT NULL, 
	notes TEXT DEFAULT '' NOT NULL, 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id)
)

;
CREATE INDEX ix_technicians_is_active ON technicians (is_active);

CREATE TABLE vehicles (
	id VARCHAR NOT NULL, 
	description VARCHAR NOT NULL, 
	plate VARCHAR NOT NULL, 
	vin VARCHAR DEFAULT '' NOT NULL, 
	PRIMARY KEY (id)
)

;

CREATE TABLE ab_assignments (
	id VARCHAR NOT NULL, 
	conversation_id VARCHAR NOT NULL, 
	experiment_id VARCHAR NOT NULL, 
	variant_id VARCHAR(64) NOT NULL, 
	outcome VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	first_audio_ms FLOAT, 
	tts_total_ms FLOAT, 
	llm_total_ms FLOAT, 
	duration_seconds FLOAT, 
	turns_count INTEGER DEFAULT '0' NOT NULL, 
	created_at VARCHAR NOT NULL, 
	completed_at VARCHAR(40), 
	PRIMARY KEY (id), 
	UNIQUE (conversation_id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE, 
	FOREIGN KEY(experiment_id) REFERENCES ab_experiments (id) ON DELETE CASCADE
)

;
CREATE INDEX ix_ab_assignments_experiment_id ON ab_assignments (experiment_id);
CREATE INDEX ix_ab_assignments_outcome ON ab_assignments (outcome);
CREATE INDEX ix_ab_assignments_variant_id ON ab_assignments (variant_id);

CREATE TABLE appointments (
	id VARCHAR NOT NULL, 
	slot_id VARCHAR, 
	vehicle_id VARCHAR NOT NULL, 
	customer VARCHAR NOT NULL, 
	idempotency_key VARCHAR NOT NULL, 
	confirmed BOOLEAN NOT NULL, 
	status VARCHAR NOT NULL, 
	corporate_account_id VARCHAR, 
	billed_amount_kurus INTEGER DEFAULT '0' NOT NULL, 
	package_type VARCHAR(64) DEFAULT 'standart_ekspertiz' NOT NULL, 
	customer_phone VARCHAR(40) DEFAULT '' NOT NULL, 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (slot_id), 
	FOREIGN KEY(slot_id) REFERENCES slots (id), 
	FOREIGN KEY(vehicle_id) REFERENCES vehicles (id), 
	UNIQUE (idempotency_key), 
	FOREIGN KEY(corporate_account_id) REFERENCES corporate_accounts (id) ON DELETE SET NULL
)

;
CREATE INDEX ix_appointments_created_at ON appointments (created_at);
CREATE INDEX ix_appointments_customer_phone ON appointments (customer_phone);
CREATE INDEX ix_appointments_status ON appointments (status);
CREATE INDEX ix_appointments_vehicle_id ON appointments (vehicle_id);

CREATE TABLE audio_archives (
	id VARCHAR NOT NULL, 
	conversation_id VARCHAR, 
	call_session_id VARCHAR(80) DEFAULT '' NOT NULL, 
	caller_phone VARCHAR(40) DEFAULT '' NOT NULL, 
	codec VARCHAR(20) DEFAULT 'opus' NOT NULL, 
	channels INTEGER DEFAULT '1' NOT NULL, 
	sample_rate INTEGER DEFAULT '8000' NOT NULL, 
	duration_sec FLOAT DEFAULT '0.0' NOT NULL, 
	raw_size_bytes INTEGER DEFAULT '0' NOT NULL, 
	compressed_size_bytes INTEGER DEFAULT '0' NOT NULL, 
	compression_ratio_percent FLOAT DEFAULT '0.0' NOT NULL, 
	sha256_hash VARCHAR(64) DEFAULT '' NOT NULL, 
	raw_sha256_hash VARCHAR(64) DEFAULT '' NOT NULL, 
	hmac_signature VARCHAR(64) DEFAULT '' NOT NULL, 
	file_path VARCHAR(255) DEFAULT '' NOT NULL, 
	retention_years INTEGER DEFAULT '2' NOT NULL, 
	expires_at VARCHAR(40), 
	is_redacted BOOLEAN DEFAULT '0' NOT NULL, 
	status VARCHAR(32) DEFAULT 'active' NOT NULL, 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE SET NULL
)

;
CREATE INDEX ix_audio_archives_call_session_id ON audio_archives (call_session_id);
CREATE INDEX ix_audio_archives_conversation_id ON audio_archives (conversation_id);
CREATE INDEX ix_audio_archives_created_at ON audio_archives (created_at);
CREATE INDEX ix_audio_archives_expires_at ON audio_archives (expires_at);
CREATE INDEX ix_audio_archives_status ON audio_archives (status);

CREATE TABLE fqici_scopes (
	id VARCHAR NOT NULL, 
	transport VARCHAR(12) NOT NULL, 
	origin VARCHAR(12) NOT NULL, 
	transport_id VARCHAR(36), 
	terminal_seen BOOLEAN NOT NULL, 
	dirty_since_ms BIGINT, 
	ready_at_ms BIGINT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(id) REFERENCES conversations (id) ON DELETE CASCADE
)

;
CREATE INDEX ix_fqici_scopes_ready_at_ms ON fqici_scopes (ready_at_ms);
CREATE INDEX ix_fqici_scopes_terminal_seen ON fqici_scopes (terminal_seen);

CREATE TABLE operator_transfers (
	id VARCHAR NOT NULL, 
	conversation_id VARCHAR, 
	caller_channel VARCHAR(120) DEFAULT '' NOT NULL, 
	operator_extension VARCHAR(32) DEFAULT '6002' NOT NULL, 
	customer_name VARCHAR(120) DEFAULT '' NOT NULL, 
	vehicle_plate VARCHAR(32) DEFAULT '' NOT NULL, 
	summary TEXT DEFAULT '' NOT NULL, 
	whisper_text TEXT DEFAULT '' NOT NULL, 
	status VARCHAR(32) DEFAULT 'initiated' NOT NULL, 
	sip_headers_json TEXT DEFAULT '{}' NOT NULL, 
	duration_seconds FLOAT, 
	created_at VARCHAR NOT NULL, 
	completed_at VARCHAR(40), 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE SET NULL
)

;
CREATE INDEX ix_operator_transfers_conversation_id ON operator_transfers (conversation_id);
CREATE INDEX ix_operator_transfers_created_at ON operator_transfers (created_at);
CREATE INDEX ix_operator_transfers_status ON operator_transfers (status);

CREATE TABLE quotes (
	id VARCHAR NOT NULL, 
	vehicle_id VARCHAR NOT NULL, 
	amount_kurus INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (vehicle_id), 
	FOREIGN KEY(vehicle_id) REFERENCES vehicles (id)
)

;

CREATE TABLE supervisor_traces (
	id VARCHAR(36) NOT NULL, 
	conversation_id VARCHAR NOT NULL, 
	payload TEXT NOT NULL, 
	review_status VARCHAR(24) NOT NULL, 
	review_labels TEXT, 
	created_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
)

;
CREATE INDEX ix_supervisor_traces_conversation_id ON supervisor_traces (conversation_id);
CREATE INDEX ix_supervisor_traces_created_at ON supervisor_traces (created_at);

CREATE TABLE turns (
	id VARCHAR NOT NULL, 
	conversation_id VARCHAR NOT NULL, 
	role VARCHAR NOT NULL, 
	text TEXT NOT NULL, 
	metrics TEXT NOT NULL, 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
)

;
CREATE INDEX ix_turns_conversation_id ON turns (conversation_id);

CREATE TABLE vehicle_diagnostics (
	id VARCHAR NOT NULL, 
	vehicle_id VARCHAR NOT NULL, 
	dtc_code VARCHAR(16) NOT NULL, 
	severity VARCHAR(32) DEFAULT 'warning' NOT NULL, 
	system_category VARCHAR(64) DEFAULT 'engine' NOT NULL, 
	description_tr VARCHAR(255) NOT NULL, 
	recommended_action TEXT NOT NULL, 
	current_mileage_km INTEGER DEFAULT '0' NOT NULL, 
	next_service_km INTEGER DEFAULT '0' NOT NULL, 
	maintenance_status VARCHAR(32) DEFAULT 'normal' NOT NULL, 
	source VARCHAR(64) DEFAULT 'obd_dongle' NOT NULL, 
	is_resolved BOOLEAN DEFAULT '0' NOT NULL, 
	owner_phone VARCHAR(40) DEFAULT '' NOT NULL, 
	owner_name VARCHAR(120) DEFAULT '' NOT NULL, 
	last_notified_at VARCHAR(40), 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(vehicle_id) REFERENCES vehicles (id) ON DELETE CASCADE
)

;
CREATE INDEX ix_vehicle_diagnostics_dtc_code ON vehicle_diagnostics (dtc_code);
CREATE INDEX ix_vehicle_diagnostics_severity ON vehicle_diagnostics (severity);
CREATE INDEX ix_vehicle_diagnostics_vehicle_id ON vehicle_diagnostics (vehicle_id);

CREATE TABLE call_analytics (
	id VARCHAR NOT NULL, 
	conversation_id VARCHAR NOT NULL, 
	appointment_id VARCHAR, 
	caller_phone VARCHAR(40) DEFAULT '' NOT NULL, 
	caller_name VARCHAR(120) DEFAULT '' NOT NULL, 
	executive_summary TEXT DEFAULT '' NOT NULL, 
	intent VARCHAR(64) DEFAULT 'unknown' NOT NULL, 
	csat_score FLOAT DEFAULT '3.0' NOT NULL, 
	sentiment VARCHAR(32) DEFAULT 'neutral' NOT NULL, 
	lead_score INTEGER DEFAULT '50' NOT NULL, 
	lead_tier VARCHAR(16) DEFAULT 'WARM' NOT NULL, 
	objections_json TEXT DEFAULT '[]' NOT NULL, 
	topics_json TEXT DEFAULT '[]' NOT NULL, 
	recommended_action TEXT DEFAULT '' NOT NULL, 
	duration_sec FLOAT, 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE, 
	FOREIGN KEY(appointment_id) REFERENCES appointments (id) ON DELETE SET NULL
)

;
CREATE INDEX ix_call_analytics_conversation_id ON call_analytics (conversation_id);
CREATE INDEX ix_call_analytics_created_at ON call_analytics (created_at);
CREATE INDEX ix_call_analytics_lead_tier ON call_analytics (lead_tier);

CREATE TABLE corporate_ledger (
	id VARCHAR NOT NULL, 
	account_id VARCHAR NOT NULL, 
	appointment_id VARCHAR, 
	entry_type VARCHAR NOT NULL, 
	amount_kurus INTEGER NOT NULL, 
	balance_after_kurus INTEGER NOT NULL, 
	description VARCHAR DEFAULT '' NOT NULL, 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(account_id) REFERENCES corporate_accounts (id) ON DELETE CASCADE, 
	FOREIGN KEY(appointment_id) REFERENCES appointments (id) ON DELETE SET NULL
)

;
CREATE INDEX ix_corporate_ledger_account_id ON corporate_ledger (account_id);

CREATE TABLE fqici_events (
	id VARCHAR(36) NOT NULL, 
	scope_id VARCHAR NOT NULL, 
	producer VARCHAR(24) NOT NULL, 
	source_event_id VARCHAR(36) NOT NULL, 
	evidence TEXT NOT NULL, 
	observed_at VARCHAR(40) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_fqici_source_event UNIQUE (producer, source_event_id), 
	FOREIGN KEY(scope_id) REFERENCES fqici_scopes (id) ON DELETE CASCADE
)

;
CREATE INDEX ix_fqici_events_scope_id ON fqici_events (scope_id);

CREATE TABLE fqici_runs (
	id VARCHAR(36) NOT NULL, 
	scope_id VARCHAR NOT NULL, 
	evidence_hash VARCHAR(64) NOT NULL, 
	rule_version VARCHAR(32) NOT NULL, 
	event_ids TEXT NOT NULL, 
	state VARCHAR(24) NOT NULL, 
	created_at_ms BIGINT NOT NULL, 
	available_at_ms BIGINT NOT NULL, 
	fence INTEGER NOT NULL, 
	lease_until_ms BIGINT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_fqici_run_snapshot UNIQUE (scope_id, evidence_hash, rule_version), 
	FOREIGN KEY(scope_id) REFERENCES fqici_scopes (id) ON DELETE CASCADE
)

;
CREATE INDEX ix_fqici_runs_scope_id ON fqici_runs (scope_id);
CREATE INDEX ix_fqici_runs_state ON fqici_runs (state);

CREATE TABLE inspection_bays (
	id VARCHAR NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	bay_number INTEGER NOT NULL, 
	bay_type VARCHAR(64) DEFAULT 'mechanic_underbody' NOT NULL, 
	status VARCHAR(32) DEFAULT 'idle' NOT NULL, 
	current_appointment_id VARCHAR, 
	current_vehicle_plate VARCHAR(32) DEFAULT '' NOT NULL, 
	notes TEXT DEFAULT '' NOT NULL, 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (bay_number), 
	FOREIGN KEY(current_appointment_id) REFERENCES appointments (id) ON DELETE SET NULL
)

;
CREATE INDEX ix_inspection_bays_bay_number ON inspection_bays (bay_number);
CREATE INDEX ix_inspection_bays_bay_type ON inspection_bays (bay_type);
CREATE INDEX ix_inspection_bays_status ON inspection_bays (status);

CREATE TABLE inspection_lifts (
	id VARCHAR NOT NULL, 
	name VARCHAR(120) NOT NULL, 
	lift_number INTEGER NOT NULL, 
	status VARCHAR(32) DEFAULT 'idle' NOT NULL, 
	current_appointment_id VARCHAR, 
	current_vehicle_plate VARCHAR(32) DEFAULT '' NOT NULL, 
	package_type VARCHAR(64) DEFAULT 'standart_ekspertiz' NOT NULL, 
	started_at VARCHAR(40), 
	estimated_duration_min INTEGER DEFAULT '45' NOT NULL, 
	notes TEXT DEFAULT '' NOT NULL, 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (lift_number), 
	FOREIGN KEY(current_appointment_id) REFERENCES appointments (id) ON DELETE SET NULL
)

;
CREATE INDEX ix_inspection_lifts_lift_number ON inspection_lifts (lift_number);
CREATE INDEX ix_inspection_lifts_status ON inspection_lifts (status);

CREATE TABLE inspection_reports (
	id VARCHAR NOT NULL, 
	vehicle_id VARCHAR NOT NULL, 
	appointment_id VARCHAR, 
	technician_name VARCHAR(120) DEFAULT 'Uzman Teknisyen' NOT NULL, 
	summary TEXT NOT NULL, 
	mileage_km INTEGER DEFAULT '0' NOT NULL, 
	score INTEGER DEFAULT '100' NOT NULL, 
	findings_json TEXT DEFAULT '{}' NOT NULL, 
	photos_json TEXT DEFAULT '[]' NOT NULL, 
	pdf_path VARCHAR(255), 
	delivered_at VARCHAR(40), 
	inspected_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(vehicle_id) REFERENCES vehicles (id) ON DELETE CASCADE, 
	FOREIGN KEY(appointment_id) REFERENCES appointments (id) ON DELETE SET NULL
)

;
CREATE INDEX ix_inspection_reports_appointment_id ON inspection_reports (appointment_id);
CREATE INDEX ix_inspection_reports_vehicle_id ON inspection_reports (vehicle_id);

CREATE TABLE intent_training_candidates (
	trace_id VARCHAR(36) NOT NULL, 
	text_digest VARCHAR(64) NOT NULL, 
	group_id VARCHAR(36) NOT NULL, 
	split VARCHAR(12) NOT NULL, 
	example TEXT NOT NULL, 
	PRIMARY KEY (trace_id), 
	FOREIGN KEY(trace_id) REFERENCES supervisor_traces (id) ON DELETE CASCADE, 
	UNIQUE (text_digest)
)

;
CREATE INDEX ix_intent_training_candidates_group_id ON intent_training_candidates (group_id);

CREATE TABLE notifications (
	id VARCHAR NOT NULL, 
	appointment_id VARCHAR NOT NULL, 
	recipient_type VARCHAR(32) NOT NULL, 
	recipient VARCHAR(120) NOT NULL, 
	channel VARCHAR(32) DEFAULT 'sms' NOT NULL, 
	message TEXT NOT NULL, 
	status VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	idempotency_key VARCHAR(128) NOT NULL, 
	attempts INTEGER DEFAULT '0' NOT NULL, 
	last_error TEXT, 
	created_at VARCHAR NOT NULL, 
	sent_at VARCHAR, 
	PRIMARY KEY (id), 
	FOREIGN KEY(appointment_id) REFERENCES appointments (id) ON DELETE CASCADE, 
	UNIQUE (idempotency_key)
)

;
CREATE INDEX ix_notifications_appointment_id ON notifications (appointment_id);
CREATE INDEX ix_notifications_status_created_at ON notifications (status, created_at);

CREATE TABLE outbound_calls (
	id VARCHAR NOT NULL, 
	appointment_id VARCHAR NOT NULL, 
	phone VARCHAR(40) NOT NULL, 
	customer VARCHAR(120) NOT NULL, 
	call_type VARCHAR(32) DEFAULT 'reminder' NOT NULL, 
	status VARCHAR(32) DEFAULT 'queued' NOT NULL, 
	outcome VARCHAR(32) DEFAULT 'pending' NOT NULL, 
	action_id VARCHAR(64) DEFAULT '' NOT NULL, 
	attempts INTEGER DEFAULT '0' NOT NULL, 
	last_error TEXT, 
	created_at VARCHAR NOT NULL, 
	completed_at VARCHAR, 
	PRIMARY KEY (id), 
	FOREIGN KEY(appointment_id) REFERENCES appointments (id) ON DELETE CASCADE
)

;
CREATE INDEX ix_outbound_calls_appointment_id ON outbound_calls (appointment_id);
CREATE INDEX ix_outbound_calls_status_created_at ON outbound_calls (status, created_at);

CREATE TABLE ruhsat_scans (
	id VARCHAR NOT NULL, 
	vehicle_id VARCHAR, 
	appointment_id VARCHAR, 
	from_phone VARCHAR(40) DEFAULT '' NOT NULL, 
	plate VARCHAR(32) DEFAULT '' NOT NULL, 
	vin VARCHAR(32) DEFAULT '' NOT NULL, 
	engine_code VARCHAR(32) DEFAULT '' NOT NULL, 
	model_year INTEGER, 
	brand_model VARCHAR(120) DEFAULT '' NOT NULL, 
	document_serial VARCHAR(32) DEFAULT '' NOT NULL, 
	owner_name VARCHAR(120) DEFAULT '' NOT NULL, 
	confidence FLOAT DEFAULT '0.0' NOT NULL, 
	raw_extracted_text TEXT DEFAULT '' NOT NULL, 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(vehicle_id) REFERENCES vehicles (id) ON DELETE SET NULL, 
	FOREIGN KEY(appointment_id) REFERENCES appointments (id) ON DELETE SET NULL
)

;
CREATE INDEX ix_ruhsat_scans_created_at ON ruhsat_scans (created_at);
CREATE INDEX ix_ruhsat_scans_from_phone ON ruhsat_scans (from_phone);
CREATE INDEX ix_ruhsat_scans_plate ON ruhsat_scans (plate);
CREATE INDEX ix_ruhsat_scans_vin ON ruhsat_scans (vin);

CREATE TABLE vehicle_valuations (
	id VARCHAR NOT NULL, 
	conversation_id VARCHAR, 
	appointment_id VARCHAR, 
	plate VARCHAR(32) DEFAULT '' NOT NULL, 
	brand VARCHAR(64) DEFAULT '' NOT NULL, 
	model VARCHAR(64) DEFAULT '' NOT NULL, 
	model_year INTEGER DEFAULT '2020' NOT NULL, 
	fuel_type VARCHAR(32) DEFAULT 'benzin' NOT NULL, 
	transmission VARCHAR(32) DEFAULT 'otomatik' NOT NULL, 
	mileage_km INTEGER DEFAULT '0' NOT NULL, 
	body_condition_json TEXT DEFAULT '{}' NOT NULL, 
	tramer_amount_tl FLOAT DEFAULT '0.0' NOT NULL, 
	is_heavy_damage BOOLEAN DEFAULT '0' NOT NULL, 
	base_benchmark_tl FLOAT DEFAULT '0.0' NOT NULL, 
	estimated_market_value_tl FLOAT DEFAULT '0.0' NOT NULL, 
	cash_buy_offer_tl FLOAT DEFAULT '0.0' NOT NULL, 
	trade_in_offer_tl FLOAT DEFAULT '0.0' NOT NULL, 
	valuation_range_min_tl FLOAT DEFAULT '0.0' NOT NULL, 
	valuation_range_max_tl FLOAT DEFAULT '0.0' NOT NULL, 
	status VARCHAR(32) DEFAULT 'quoted' NOT NULL, 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE SET NULL, 
	FOREIGN KEY(appointment_id) REFERENCES appointments (id) ON DELETE SET NULL
)

;
CREATE INDEX ix_vehicle_valuations_conversation_id ON vehicle_valuations (conversation_id);
CREATE INDEX ix_vehicle_valuations_created_at ON vehicle_valuations (created_at);
CREATE INDEX ix_vehicle_valuations_plate ON vehicle_valuations (plate);

CREATE TABLE whatsapp_messages (
	id VARCHAR NOT NULL, 
	message_sid VARCHAR(128) DEFAULT '' NOT NULL, 
	from_phone VARCHAR(40) DEFAULT '' NOT NULL, 
	customer_name VARCHAR(120) DEFAULT '' NOT NULL, 
	message_type VARCHAR(32) DEFAULT 'text' NOT NULL, 
	raw_content TEXT DEFAULT '' NOT NULL, 
	transcription TEXT DEFAULT '' NOT NULL, 
	extracted_intent VARCHAR(40) DEFAULT 'unknown' NOT NULL, 
	extracted_time VARCHAR(40) DEFAULT '' NOT NULL, 
	appointment_id VARCHAR, 
	reply_text TEXT DEFAULT '' NOT NULL, 
	outbound_calls_cancelled INTEGER DEFAULT '0' NOT NULL, 
	processed BOOLEAN DEFAULT '1' NOT NULL, 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(appointment_id) REFERENCES appointments (id) ON DELETE SET NULL
)

;
CREATE INDEX ix_whatsapp_messages_appointment_id ON whatsapp_messages (appointment_id);
CREATE INDEX ix_whatsapp_messages_created_at ON whatsapp_messages (created_at);
CREATE INDEX ix_whatsapp_messages_from_phone ON whatsapp_messages (from_phone);

CREATE TABLE bay_schedules (
	id VARCHAR NOT NULL, 
	appointment_id VARCHAR, 
	bay_id VARCHAR NOT NULL, 
	technician_id VARCHAR, 
	package_type VARCHAR(64) DEFAULT 'standart_ekspertiz' NOT NULL, 
	stage_name VARCHAR(120) NOT NULL, 
	stage_index INTEGER DEFAULT '1' NOT NULL, 
	starts_at VARCHAR(40) NOT NULL, 
	ends_at VARCHAR(40) NOT NULL, 
	duration_minutes INTEGER DEFAULT '15' NOT NULL, 
	status VARCHAR(32) DEFAULT 'scheduled' NOT NULL, 
	notes TEXT DEFAULT '' NOT NULL, 
	created_at VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(appointment_id) REFERENCES appointments (id) ON DELETE SET NULL, 
	FOREIGN KEY(bay_id) REFERENCES inspection_bays (id) ON DELETE CASCADE, 
	FOREIGN KEY(technician_id) REFERENCES technicians (id) ON DELETE SET NULL
)

;
CREATE INDEX ix_bay_schedules_appointment_id ON bay_schedules (appointment_id);
CREATE INDEX ix_bay_schedules_bay_id ON bay_schedules (bay_id);
CREATE INDEX ix_bay_schedules_starts_at ON bay_schedules (starts_at);
CREATE INDEX ix_bay_schedules_status ON bay_schedules (status);

CREATE TABLE inspection_queues (
	id VARCHAR NOT NULL, 
	queue_number INTEGER NOT NULL, 
	appointment_id VARCHAR, 
	vehicle_id VARCHAR, 
	plate VARCHAR(32) NOT NULL, 
	customer VARCHAR(120) NOT NULL, 
	package_type VARCHAR(64) DEFAULT 'standart_ekspertiz' NOT NULL, 
	duration_minutes INTEGER DEFAULT '45' NOT NULL, 
	status VARCHAR(32) DEFAULT 'waiting' NOT NULL, 
	lift_id VARCHAR, 
	check_in_at VARCHAR NOT NULL, 
	started_at VARCHAR(40), 
	completed_at VARCHAR(40), 
	PRIMARY KEY (id), 
	FOREIGN KEY(appointment_id) REFERENCES appointments (id) ON DELETE SET NULL, 
	FOREIGN KEY(vehicle_id) REFERENCES vehicles (id) ON DELETE SET NULL, 
	FOREIGN KEY(lift_id) REFERENCES inspection_lifts (id) ON DELETE SET NULL
)

;
CREATE INDEX ix_inspection_queues_check_in_at ON inspection_queues (check_in_at);
CREATE INDEX ix_inspection_queues_status ON inspection_queues (status);
```

### backend/db.py

````python
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
````

## Sürüm geçişleri


### migrations/versions/001_initial.py

````python
"""Initial local assistant schema, frozen independently of ORM evolution."""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None


def upgrade():
    op.create_table(
        "vehicles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("plate", sa.String(), nullable=False),
    )
    op.create_table(
        "quotes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "vehicle_id", sa.String(), sa.ForeignKey("vehicles.id"), nullable=False
        ),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
    )
    op.create_table(
        "slots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("starts_at", sa.String(), nullable=False, unique=True),
    )
    op.create_table(
        "appointments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("slot_id", sa.String(), sa.ForeignKey("slots.id"), unique=True),
        sa.Column(
            "vehicle_id", sa.String(), sa.ForeignKey("vehicles.id"), nullable=False
        ),
        sa.Column("customer", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "turns",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metrics", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )


def downgrade():
    for name in [
        "turns",
        "conversations",
        "appointments",
        "slots",
        "quotes",
        "vehicles",
    ]:
        op.drop_table(name)
````


### migrations/versions/002_quote_unique.py

````python
"""One current service quote per vehicle."""

from alembic import op

revision = "002"
down_revision = "001"


def upgrade():
    with op.batch_alter_table("quotes") as batch:
        batch.create_unique_constraint("uq_quotes_vehicle_id", ["vehicle_id"])


def downgrade():
    with op.batch_alter_table("quotes") as batch:
        batch.drop_constraint("uq_quotes_vehicle_id", type_="unique")
````


### migrations/versions/003_slot_duration.py

````python
"""Add duration_minutes to slots table."""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"


def upgrade():
    with op.batch_alter_table("slots") as batch:
        batch.add_column(
            sa.Column(
                "duration_minutes", sa.Integer(), nullable=False, server_default="30"
            )
        )


def downgrade():
    with op.batch_alter_table("slots") as batch:
        batch.drop_column("duration_minutes")
````


### migrations/versions/004_vin_and_inspections.py

````python
"""Add vin to vehicles and create inspection_reports table."""

from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"


def upgrade():
    with op.batch_alter_table("vehicles") as batch:
        batch.add_column(
            sa.Column("vin", sa.String(), nullable=False, server_default="")
        )

    op.create_table(
        "inspection_reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "vehicle_id",
            sa.String(),
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("mileage_km", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("inspected_at", sa.String(), nullable=False),
    )


def downgrade():
    op.drop_table("inspection_reports")
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("vin")
````


### migrations/versions/005_corporate_accounts.py

````python
"""Create corporate_accounts, corporate_ledger, and link to appointments."""

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"


def upgrade():
    op.create_table(
        "corporate_accounts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("tax_id", sa.String(), nullable=False, unique=True),
        sa.Column("phone", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "credit_limit_kurus", sa.Integer(), nullable=False, server_default="5000000"
        ),
        sa.Column(
            "balance_kurus", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "discount_percent", sa.Integer(), nullable=False, server_default="10"
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(), nullable=False),
    )

    op.create_table(
        "corporate_ledger",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(),
            sa.ForeignKey("corporate_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("entry_type", sa.String(), nullable=False),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
        sa.Column("balance_after_kurus", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(), nullable=False),
    )

    with op.batch_alter_table("appointments") as batch:
        batch.add_column(
            sa.Column(
                "corporate_account_id",
                sa.String(),
                sa.ForeignKey(
                    "corporate_accounts.id",
                    name="fk_appointments_corporate_account_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "billed_amount_kurus",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade():
    with op.batch_alter_table("appointments") as batch:
        batch.drop_column("billed_amount_kurus")
        batch.drop_column("corporate_account_id")
    op.drop_table("corporate_ledger")
    op.drop_table("corporate_accounts")
````


### migrations/versions/006_notifications_outbox.py

````python
"""Create notifications table for M10 outbox messaging.

Revision ID: 006
Revises: 005
Create Date: 2026-11-01 22:20:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient_type", sa.String(length=32), nullable=False),
        sa.Column("recipient", sa.String(length=120), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="sms"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("sent_at", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_notifications_status_created_at",
        "notifications",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_notifications_appointment_id",
        "notifications",
        ["appointment_id"],
    )


def downgrade():
    op.drop_index("ix_notifications_appointment_id", table_name="notifications")
    op.drop_index("ix_notifications_status_created_at", table_name="notifications")
    op.drop_table("notifications")
````


### migrations/versions/007_outbound_calls.py

````python
"""Create outbound_calls table for Asterisk AMI call origination.

Revision ID: 007
Revises: 006
Create Date: 2026-11-01 22:30:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"


def upgrade():
    op.create_table(
        "outbound_calls",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phone", sa.String(length=40), nullable=False),
        sa.Column("customer", sa.String(length=120), nullable=False),
        sa.Column(
            "call_type",
            sa.String(length=32),
            nullable=False,
            server_default="reminder",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "outcome",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "action_id",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("completed_at", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_outbound_calls_status_created_at",
        "outbound_calls",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_outbound_calls_appointment_id",
        "outbound_calls",
        ["appointment_id"],
    )


def downgrade():
    op.drop_index("ix_outbound_calls_appointment_id", table_name="outbound_calls")
    op.drop_index("ix_outbound_calls_status_created_at", table_name="outbound_calls")
    op.drop_table("outbound_calls")
````


### migrations/versions/008_inspection_templates_and_digital_delivery.py

````python
"""Add inspection findings, photos, pdf_path, and digital delivery fields.

Revision ID: 008
Revises: 007
Create Date: 2026-11-01 23:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"


def upgrade():
    with op.batch_alter_table("inspection_reports") as batch:
        batch.add_column(
            sa.Column(
                "appointment_id",
                sa.String(),
                sa.ForeignKey(
                    "appointments.id",
                    name="fk_inspection_reports_appointment_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "technician_name",
                sa.String(length=120),
                nullable=False,
                server_default="Uzman Teknisyen",
            )
        )
        batch.add_column(
            sa.Column(
                "findings_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            )
        )
        batch.add_column(
            sa.Column(
                "photos_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            )
        )
        batch.add_column(
            sa.Column(
                "pdf_path",
                sa.String(length=255),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "delivered_at",
                sa.String(length=40),
                nullable=True,
            )
        )
        batch.create_index(
            "ix_inspection_reports_appointment_id",
            ["appointment_id"],
        )
        batch.create_index(
            "ix_inspection_reports_vehicle_id",
            ["vehicle_id"],
        )


def downgrade():
    with op.batch_alter_table("inspection_reports") as batch:
        batch.drop_index("ix_inspection_reports_vehicle_id")
        batch.drop_index("ix_inspection_reports_appointment_id")
        batch.drop_column("delivered_at")
        batch.drop_column("pdf_path")
        batch.drop_column("photos_json")
        batch.drop_column("findings_json")
        batch.drop_column("technician_name")
        batch.drop_column("appointment_id")
````


### migrations/versions/009_analytics_and_conversation_resolution.py

````python
"""Add operator_notes and resolved_at to conversations with indexes.

Revision ID: 009
Revises: 008
Create Date: 2026-11-01 23:20:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"


def upgrade():
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(
            sa.Column(
                "operator_notes",
                sa.Text(),
                nullable=False,
                server_default="",
            )
        )
        batch.add_column(
            sa.Column(
                "resolved_at",
                sa.String(length=40),
                nullable=True,
            )
        )
        batch.create_index(
            "ix_conversations_status",
            ["status"],
        )
        batch.create_index(
            "ix_conversations_created_at",
            ["created_at"],
        )


def downgrade():
    with op.batch_alter_table("conversations") as batch:
        batch.drop_index("ix_conversations_created_at")
        batch.drop_index("ix_conversations_status")
        batch.drop_column("resolved_at")
        batch.drop_column("operator_notes")
````


### migrations/versions/010_proactive_diagnostics_and_telemetry.py

````python
"""Create vehicle_diagnostics table for OBD-II telemetry and proactive maintenance.

Revision ID: 010
Revises: 009
Create Date: 2026-11-01 23:35:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"


def upgrade():
    op.create_table(
        "vehicle_diagnostics",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "vehicle_id",
            sa.String(),
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dtc_code", sa.String(length=16), nullable=False),
        sa.Column(
            "severity",
            sa.String(length=32),
            nullable=False,
            server_default="warning",
        ),
        sa.Column(
            "system_category",
            sa.String(length=64),
            nullable=False,
            server_default="engine",
        ),
        sa.Column("description_tr", sa.String(length=255), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column(
            "current_mileage_km",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "next_service_km",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "maintenance_status",
            sa.String(length=32),
            nullable=False,
            server_default="normal",
        ),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            server_default="obd_dongle",
        ),
        sa.Column(
            "is_resolved",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "owner_phone",
            sa.String(length=40),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "owner_name",
            sa.String(length=120),
            nullable=False,
            server_default="",
        ),
        sa.Column("last_notified_at", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_vehicle_diagnostics_vehicle_id",
        "vehicle_diagnostics",
        ["vehicle_id"],
    )
    op.create_index(
        "ix_vehicle_diagnostics_dtc_code",
        "vehicle_diagnostics",
        ["dtc_code"],
    )
    op.create_index(
        "ix_vehicle_diagnostics_severity",
        "vehicle_diagnostics",
        ["severity"],
    )


def downgrade():
    op.drop_index("ix_vehicle_diagnostics_severity", table_name="vehicle_diagnostics")
    op.drop_index("ix_vehicle_diagnostics_dtc_code", table_name="vehicle_diagnostics")
    op.drop_index("ix_vehicle_diagnostics_vehicle_id", table_name="vehicle_diagnostics")
    op.drop_table("vehicle_diagnostics")
````


### migrations/versions/011_lift_and_queue_management.py

````python
"""Create inspection_lifts and inspection_queues tables, add package_type to appointments.

Revision ID: 011
Revises: 010
Create Date: 2026-11-02 01:12:00.000000

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"


def upgrade():
    # 1. Inspection Lifts table
    op.create_table(
        "inspection_lifts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("lift_number", sa.Integer(), nullable=False, unique=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="idle",
        ),
        sa.Column(
            "current_appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "current_vehicle_plate",
            sa.String(length=32),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "package_type",
            sa.String(length=64),
            nullable=False,
            server_default="standart_ekspertiz",
        ),
        sa.Column("started_at", sa.String(length=40), nullable=True),
        sa.Column(
            "estimated_duration_min",
            sa.Integer(),
            nullable=False,
            server_default="45",
        ),
        sa.Column(
            "notes",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index(
        "ix_inspection_lifts_status",
        "inspection_lifts",
        ["status"],
    )
    op.create_index(
        "ix_inspection_lifts_lift_number",
        "inspection_lifts",
        ["lift_number"],
    )

    # 2. Inspection Queue table
    op.create_table(
        "inspection_queues",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("queue_number", sa.Integer(), nullable=False),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "vehicle_id",
            sa.String(),
            sa.ForeignKey("vehicles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("plate", sa.String(length=32), nullable=False),
        sa.Column("customer", sa.String(length=120), nullable=False),
        sa.Column(
            "package_type",
            sa.String(length=64),
            nullable=False,
            server_default="standart_ekspertiz",
        ),
        sa.Column(
            "duration_minutes",
            sa.Integer(),
            nullable=False,
            server_default="45",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="waiting",
        ),
        sa.Column(
            "lift_id",
            sa.String(),
            sa.ForeignKey("inspection_lifts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("check_in_at", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.String(length=40), nullable=True),
        sa.Column("completed_at", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_inspection_queues_status",
        "inspection_queues",
        ["status"],
    )
    op.create_index(
        "ix_inspection_queues_check_in_at",
        "inspection_queues",
        ["check_in_at"],
    )

    # 3. Add package_type column to appointments
    with op.batch_alter_table("appointments") as batch_op:
        batch_op.add_column(
            sa.Column(
                "package_type",
                sa.String(length=64),
                nullable=False,
                server_default="standart_ekspertiz",
            )
        )


def downgrade():
    with op.batch_alter_table("appointments") as batch_op:
        batch_op.drop_column("package_type")
    op.drop_index("ix_inspection_queues_check_in_at", table_name="inspection_queues")
    op.drop_index("ix_inspection_queues_status", table_name="inspection_queues")
    op.drop_table("inspection_queues")
    op.drop_index("ix_inspection_lifts_lift_number", table_name="inspection_lifts")
    op.drop_index("ix_inspection_lifts_status", table_name="inspection_lifts")
    op.drop_table("inspection_lifts")
````


### migrations/versions/012_ab_testing_infrastructure.py

````python
"""Create ab_experiments and ab_assignments tables.

Revision ID: 012
Revises: 011
Create Date: 2026-11-02 01:35:00.000000

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"


def upgrade():
    op.create_table(
        "ab_experiments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "experiment_type",
            sa.String(length=40),
            nullable=False,
            server_default="composite",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "variants_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "target_metric",
            sa.String(length=40),
            nullable=False,
            server_default="conversion_rate",
        ),
        sa.Column(
            "created_at",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.String(length=40),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_ab_experiments_status",
        "ab_experiments",
        ["status"],
    )

    op.create_table(
        "ab_assignments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "experiment_id",
            sa.String(),
            sa.ForeignKey("ab_experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("variant_id", sa.String(length=64), nullable=False),
        sa.Column(
            "outcome",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("first_audio_ms", sa.Float(), nullable=True),
        sa.Column("tts_total_ms", sa.Float(), nullable=True),
        sa.Column("llm_total_ms", sa.Float(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column(
            "turns_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("completed_at", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_ab_assignments_experiment_id",
        "ab_assignments",
        ["experiment_id"],
    )
    op.create_index(
        "ix_ab_assignments_variant_id",
        "ab_assignments",
        ["variant_id"],
    )
    op.create_index(
        "ix_ab_assignments_outcome",
        "ab_assignments",
        ["outcome"],
    )


def downgrade():
    op.drop_index("ix_ab_assignments_outcome", table_name="ab_assignments")
    op.drop_index("ix_ab_assignments_variant_id", table_name="ab_assignments")
    op.drop_index("ix_ab_assignments_experiment_id", table_name="ab_assignments")
    op.drop_table("ab_assignments")

    op.drop_index("ix_ab_experiments_status", table_name="ab_experiments")
    op.drop_table("ab_experiments")
````


### migrations/versions/013_operator_transfers.py

````python
"""Create operator_transfers table for live warm transfers and screen-pop.

Revision ID: 013
Revises: 012
Create Date: 2026-11-02 02:35:00.000000

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"


def upgrade():
    op.create_table(
        "operator_transfers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("caller_channel", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("operator_extension", sa.String(length=32), nullable=False, server_default="6002"),
        sa.Column("customer_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("vehicle_plate", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("whisper_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="initiated"),
        sa.Column("sip_headers_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("completed_at", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_operator_transfers_status",
        "operator_transfers",
        ["status"],
    )
    op.create_index(
        "ix_operator_transfers_conversation_id",
        "operator_transfers",
        ["conversation_id"],
    )
    op.create_index(
        "ix_operator_transfers_created_at",
        "operator_transfers",
        ["created_at"],
    )


def downgrade():
    op.drop_index("ix_operator_transfers_created_at", table_name="operator_transfers")
    op.drop_index("ix_operator_transfers_conversation_id", table_name="operator_transfers")
    op.drop_index("ix_operator_transfers_status", table_name="operator_transfers")
    op.drop_table("operator_transfers")
````


### migrations/versions/014_whatsapp_inbound.py

````python
"""Create whatsapp_messages table for two-way WhatsApp/SMS management.

Revision ID: 014
Revises: 013
Create Date: 2026-11-02 03:05:00.000000

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"


def upgrade():
    op.create_table(
        "whatsapp_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("message_sid", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("from_phone", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("customer_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("message_type", sa.String(length=32), nullable=False, server_default="text"),
        sa.Column("raw_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("transcription", sa.Text(), nullable=False, server_default=""),
        sa.Column("extracted_intent", sa.String(length=40), nullable=False, server_default="unknown"),
        sa.Column("extracted_time", sa.String(length=40), nullable=False, server_default=""),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reply_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("outbound_calls_cancelled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index(
        "ix_whatsapp_messages_from_phone",
        "whatsapp_messages",
        ["from_phone"],
    )
    op.create_index(
        "ix_whatsapp_messages_appointment_id",
        "whatsapp_messages",
        ["appointment_id"],
    )
    op.create_index(
        "ix_whatsapp_messages_created_at",
        "whatsapp_messages",
        ["created_at"],
    )


def downgrade():
    op.drop_index("ix_whatsapp_messages_created_at", table_name="whatsapp_messages")
    op.drop_index("ix_whatsapp_messages_appointment_id", table_name="whatsapp_messages")
    op.drop_index("ix_whatsapp_messages_from_phone", table_name="whatsapp_messages")
    op.drop_table("whatsapp_messages")
````


### migrations/versions/015_call_analytics_and_ruhsat.py

````python
"""Create call_analytics and ruhsat_scans tables.

Revision ID: 015
Revises: 014
Create Date: 2026-11-02 05:46:00.000000

ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlı olarak paylaşılmıştır.
"""

from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"


def upgrade():
    # 1. call_analytics table
    op.create_table(
        "call_analytics",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("caller_phone", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("caller_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("executive_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("intent", sa.String(length=64), nullable=False, server_default="unknown"),
        sa.Column("csat_score", sa.Float(), nullable=False, server_default="3.0"),
        sa.Column("sentiment", sa.String(length=32), nullable=False, server_default="neutral"),
        sa.Column("lead_score", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("lead_tier", sa.String(length=16), nullable=False, server_default="WARM"),
        sa.Column("objections_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("topics_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("recommended_action", sa.Text(), nullable=False, server_default=""),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index(
        "ix_call_analytics_conversation_id",
        "call_analytics",
        ["conversation_id"],
    )
    op.create_index(
        "ix_call_analytics_lead_tier",
        "call_analytics",
        ["lead_tier"],
    )
    op.create_index(
        "ix_call_analytics_created_at",
        "call_analytics",
        ["created_at"],
    )

    # 2. ruhsat_scans table
    op.create_table(
        "ruhsat_scans",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "vehicle_id",
            sa.String(),
            sa.ForeignKey("vehicles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("from_phone", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("plate", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("vin", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("engine_code", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("model_year", sa.Integer(), nullable=True),
        sa.Column("brand_model", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("document_serial", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("owner_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("raw_extracted_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index(
        "ix_ruhsat_scans_plate",
        "ruhsat_scans",
        ["plate"],
    )
    op.create_index(
        "ix_ruhsat_scans_vin",
        "ruhsat_scans",
        ["vin"],
    )
    op.create_index(
        "ix_ruhsat_scans_from_phone",
        "ruhsat_scans",
        ["from_phone"],
    )
    op.create_index(
        "ix_ruhsat_scans_created_at",
        "ruhsat_scans",
        ["created_at"],
    )


def downgrade():
    op.drop_index("ix_ruhsat_scans_created_at", table_name="ruhsat_scans")
    op.drop_index("ix_ruhsat_scans_from_phone", table_name="ruhsat_scans")
    op.drop_index("ix_ruhsat_scans_vin", table_name="ruhsat_scans")
    op.drop_index("ix_ruhsat_scans_plate", table_name="ruhsat_scans")
    op.drop_table("ruhsat_scans")

    op.drop_index("ix_call_analytics_created_at", table_name="call_analytics")
    op.drop_index("ix_call_analytics_lead_tier", table_name="call_analytics")
    op.drop_index("ix_call_analytics_conversation_id", table_name="call_analytics")
    op.drop_table("call_analytics")
````


### migrations/versions/016_vehicle_valuations.py

````python
"""Create vehicle_valuations table for dynamic vehicle valuation and trade-in offers.

Revision ID: 016
Revises: 015
Create Date: 2026-11-02 06:10:00.000000

ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlı olarak paylaşılmıştır.
"""

from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "015"


def upgrade():
    op.create_table(
        "vehicle_valuations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("plate", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("brand", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("model_year", sa.Integer(), nullable=False, server_default="2020"),
        sa.Column("fuel_type", sa.String(length=32), nullable=False, server_default="benzin"),
        sa.Column("transmission", sa.String(length=32), nullable=False, server_default="otomatik"),
        sa.Column("mileage_km", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("body_condition_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("tramer_amount_tl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("is_heavy_damage", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("base_benchmark_tl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("estimated_market_value_tl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("cash_buy_offer_tl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("trade_in_offer_tl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("valuation_range_min_tl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("valuation_range_max_tl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="quoted"),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index(
        "ix_vehicle_valuations_plate",
        "vehicle_valuations",
        ["plate"],
    )
    op.create_index(
        "ix_vehicle_valuations_conversation_id",
        "vehicle_valuations",
        ["conversation_id"],
    )
    op.create_index(
        "ix_vehicle_valuations_created_at",
        "vehicle_valuations",
        ["created_at"],
    )


def downgrade():
    op.drop_index("ix_vehicle_valuations_created_at", table_name="vehicle_valuations")
    op.drop_index("ix_vehicle_valuations_conversation_id", table_name="vehicle_valuations")
    op.drop_index("ix_vehicle_valuations_plate", table_name="vehicle_valuations")
    op.drop_table("vehicle_valuations")
````


### migrations/versions/017_lift_bay_capacity_scheduler.py

````python
"""Create inspection_bays, technicians, and bay_schedules tables for lift bay capacity scheduling.

Revision ID: 017
Revises: 016
Create Date: 2026-11-02 08:15:00.000000

ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlı olarak paylaşılmıştır.
"""

from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"


def upgrade():
    # 1. inspection_bays
    op.create_table(
        "inspection_bays",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("bay_number", sa.Integer(), nullable=False, unique=True),
        sa.Column("bay_type", sa.String(length=64), nullable=False, server_default="mechanic_underbody"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="idle"),
        sa.Column(
            "current_appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("current_vehicle_plate", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index("ix_inspection_bays_bay_type", "inspection_bays", ["bay_type"])
    op.create_index("ix_inspection_bays_status", "inspection_bays", ["status"])
    op.create_index("ix_inspection_bays_bay_number", "inspection_bays", ["bay_number"])

    # 2. technicians
    op.create_table(
        "technicians",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False, server_default="Uzman Teknisyen"),
        sa.Column("specialties_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("daily_capacity", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index("ix_technicians_is_active", "technicians", ["is_active"])

    # 3. bay_schedules
    op.create_table(
        "bay_schedules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "bay_id",
            sa.String(),
            sa.ForeignKey("inspection_bays.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "technician_id",
            sa.String(),
            sa.ForeignKey("technicians.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("package_type", sa.String(length=64), nullable=False, server_default="standart_ekspertiz"),
        sa.Column("stage_name", sa.String(length=120), nullable=False),
        sa.Column("stage_index", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("starts_at", sa.String(length=40), nullable=False),
        sa.Column("ends_at", sa.String(length=40), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="scheduled"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index("ix_bay_schedules_appointment_id", "bay_schedules", ["appointment_id"])
    op.create_index("ix_bay_schedules_bay_id", "bay_schedules", ["bay_id"])
    op.create_index("ix_bay_schedules_starts_at", "bay_schedules", ["starts_at"])
    op.create_index("ix_bay_schedules_status", "bay_schedules", ["status"])


def downgrade():
    op.drop_table("bay_schedules")
    op.drop_table("technicians")
    op.drop_table("inspection_bays")
````


### migrations/versions/018_audio_archives.py

````python
"""Create audio_archives table for legal retention and compression compliance.

Revision ID: 018
Revises: 017
Create Date: 2026-11-02 09:35:00.000000

ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlı olarak paylaşılmıştır.
"""

from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"


def upgrade():
    op.create_table(
        "audio_archives",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("call_session_id", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("caller_phone", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("codec", sa.String(length=20), nullable=False, server_default="opus"),
        sa.Column("channels", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sample_rate", sa.Integer(), nullable=False, server_default="8000"),
        sa.Column("duration_sec", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("raw_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compressed_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compression_ratio_percent", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("sha256_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("raw_sha256_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("hmac_signature", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("file_path", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("retention_years", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("expires_at", sa.String(length=40), nullable=True),
        sa.Column("is_redacted", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index("ix_audio_archives_conversation_id", "audio_archives", ["conversation_id"])
    op.create_index("ix_audio_archives_call_session_id", "audio_archives", ["call_session_id"])
    op.create_index("ix_audio_archives_status", "audio_archives", ["status"])
    op.create_index("ix_audio_archives_created_at", "audio_archives", ["created_at"])
    op.create_index("ix_audio_archives_expires_at", "audio_archives", ["expires_at"])


def downgrade():
    op.drop_index("ix_audio_archives_expires_at", table_name="audio_archives")
    op.drop_index("ix_audio_archives_created_at", table_name="audio_archives")
    op.drop_index("ix_audio_archives_status", table_name="audio_archives")
    op.drop_index("ix_audio_archives_call_session_id", table_name="audio_archives")
    op.drop_index("ix_audio_archives_conversation_id", table_name="audio_archives")
    op.drop_table("audio_archives")
````


### migrations/versions/019_latency_indexes.py

````python
"""Add missing hot-path indexes (turns, appointments, corporate_ledger).

Revision ID: 019
Revises: 018
Create Date: 2026-11-06 10:00:00.000000
"""

from alembic import op

revision = "019"
down_revision = "018"

_INDEXES = (
    ("ix_turns_conversation_id", "turns", ["conversation_id"]),
    ("ix_appointments_vehicle_id", "appointments", ["vehicle_id"]),
    ("ix_appointments_status", "appointments", ["status"]),
    ("ix_appointments_created_at", "appointments", ["created_at"]),
    ("ix_corporate_ledger_account_id", "corporate_ledger", ["account_id"]),
)


def upgrade():
    for name, table, cols in _INDEXES:
        op.create_index(name, table, cols)


def downgrade():
    for name, table, _ in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
````


### migrations/versions/020_appointment_customer_phone.py

````python
# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""Add customer_phone column to appointments table.

Revision ID: 020
Revises: 019
Create Date: 2026-11-08 21:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"


def upgrade():
    with op.batch_alter_table("appointments") as batch_op:
        batch_op.add_column(
            sa.Column(
                "customer_phone",
                sa.String(length=40),
                nullable=False,
                server_default="",
            )
        )
        batch_op.create_index(
            "ix_appointments_customer_phone",
            ["customer_phone"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("appointments") as batch_op:
        batch_op.drop_index("ix_appointments_customer_phone")
        batch_op.drop_column("customer_phone")
````


### migrations/versions/021_kvkk_erasure_requests.py

````python
# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""Add kvkk_erasure_requests table for transcript retention & erasure workflow.

Revision ID: 021
Revises: 020
Create Date: 2026-11-09 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"


def upgrade():
    op.create_table(
        "kvkk_erasure_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("identifier_type", sa.String(length=32), nullable=False),
        sa.Column("identifier_value", sa.String(length=120), nullable=False),
        sa.Column("requester_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column(
            "reason",
            sa.String(length=255),
            nullable=False,
            server_default="KVKK Madde 11 uyarınca silme talebi",
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("impact_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("certificate_sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("executed_at", sa.String(length=40), nullable=True),
        sa.Column("executed_by", sa.String(length=80), nullable=False, server_default="admin"),
    )
    op.create_index(
        "ix_kvkk_erasure_requests_status",
        "kvkk_erasure_requests",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_kvkk_erasure_requests_identifier_value",
        "kvkk_erasure_requests",
        ["identifier_value"],
        unique=False,
    )
    op.create_index(
        "ix_kvkk_erasure_requests_created_at",
        "kvkk_erasure_requests",
        ["created_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_kvkk_erasure_requests_created_at", table_name="kvkk_erasure_requests")
    op.drop_index("ix_kvkk_erasure_requests_identifier_value", table_name="kvkk_erasure_requests")
    op.drop_index("ix_kvkk_erasure_requests_status", table_name="kvkk_erasure_requests")
    op.drop_table("kvkk_erasure_requests")
````


### migrations/versions/022_supervisor_quality.py

````python
"""Add Supervisor routing traces, reviewed examples and write receipts."""

import sqlalchemy as sa
from alembic import op

revision = "022"
down_revision = "021"


def upgrade():
    op.create_table(
        "supervisor_traces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("review_status", sa.String(24), nullable=False),
        sa.Column("review_labels", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_supervisor_traces_conversation_id", "supervisor_traces", ["conversation_id"])
    op.create_index("ix_supervisor_traces_created_at", "supervisor_traces", ["created_at"])
    op.create_table(
        "intent_training_candidates",
        sa.Column("trace_id", sa.String(36), sa.ForeignKey("supervisor_traces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("text_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("group_id", sa.String(36), nullable=False),
        sa.Column("split", sa.String(12), nullable=False),
        sa.Column("example", sa.Text(), nullable=False),
    )
    op.create_index("ix_intent_training_candidates_group_id", "intent_training_candidates", ["group_id"])
    op.create_table(
        "supervisor_write_receipts",
        sa.Column("key", sa.String(36), primary_key=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )


def downgrade():
    op.drop_table("supervisor_write_receipts")
    op.drop_table("intent_training_candidates")
    op.drop_table("supervisor_traces")
````


### migrations/versions/023_fqici_queue.py

````python
"""Persist FQICI scopes, sanitized events, and leased analysis runs."""

import sqlalchemy as sa
from alembic import op

revision = "023"
down_revision = "022"


def upgrade():
    op.create_table(
        "fqici_scopes",
        sa.Column("id", sa.String(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("transport", sa.String(12), nullable=False),
        sa.Column("origin", sa.String(12), nullable=False),
        sa.Column("transport_id", sa.String(36)),
        sa.Column("terminal_seen", sa.Boolean(), nullable=False),
        sa.Column("dirty_since_ms", sa.BigInteger()),
        sa.Column("ready_at_ms", sa.BigInteger()),
    )
    op.create_table(
        "fqici_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope_id", sa.String(), sa.ForeignKey("fqici_scopes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("producer", sa.String(24), nullable=False),
        sa.Column("source_event_id", sa.String(36), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("producer", "source_event_id", name="uq_fqici_source_event"),
    )
    op.create_table(
        "fqici_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope_id", sa.String(), sa.ForeignKey("fqici_scopes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("event_ids", sa.Text(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("available_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("lease_until_ms", sa.BigInteger()),
        sa.UniqueConstraint("scope_id", "evidence_hash", "rule_version", name="uq_fqici_run_snapshot"),
    )
    for table, columns in (
        ("fqici_scopes", ("terminal_seen", "ready_at_ms")),
        ("fqici_events", ("scope_id",)),
        ("fqici_runs", ("scope_id", "state")),
    ):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    op.drop_table("fqici_runs")
    op.drop_table("fqici_events")
    op.drop_table("fqici_scopes")
````


### migrations/versions/024_operator_follow_up.py

````python
"""Record the reason and start time of operator follow-up."""

import sqlalchemy as sa
from alembic import op

revision = "024"
down_revision = "023"


def upgrade():
    op.add_column("conversations", sa.Column("follow_up_kind", sa.String(24)))
    op.add_column("conversations", sa.Column("follow_up_at", sa.String(40)))


def downgrade():
    op.drop_column("conversations", "follow_up_at")
    op.drop_column("conversations", "follow_up_kind")
````
