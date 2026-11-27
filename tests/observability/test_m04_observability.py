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

import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.core.contracts import (
    CONTRACT_SCHEMA_VERSION,
    ErrorCategory,
    ErrorInfo,
    EventEnvelope,
    MetricSample,
    MetricStatus,
    Retryability,
)
from backend.core.runtime import AdmissionStatus, FakeClock
from backend.observability import (
    BoundedEventBus,
    ClockDomainMismatchError,
    DropPolicy,
    EventPriority,
    EvidenceKind,
    EvidenceRecorder,
    LocalObservabilityStore,
    MetricsRegistry,
    Projection,
    SpanStatus,
    TraceStore,
    adapt_legacy_event,
    allowed_metadata_keys_for,
    legacy_event_to_safe_projection,
    priority_for_event,
)
from backend.pipeline_telemetry import make_pipeline_event

ROOT = Path(__file__).resolve().parents[2]


def _make_env(
    event_type: str = "session.opened",
    *,
    session_id: str = "sess-m04",
    trace_id: str | None = "trace-1",
    turn_id: int | None = 1,
    generation_id: int | None = 1,
    sequence: int = 0,
    monotonic_ns: int = 1_000,
    clock_domain: str = "test.clock",
    utc_timestamp: str | None = "2026-11-26T00:00:00Z",
    metadata: dict | None = None,
) -> EventEnvelope:
    return EventEnvelope(
        schema_version=CONTRACT_SCHEMA_VERSION,
        event_type=event_type,
        session_id=session_id,
        trace_id=trace_id,
        turn_id=turn_id,
        generation_id=generation_id,
        sequence=sequence,
        monotonic_ns=monotonic_ns,
        clock_domain=clock_domain,
        producer="m04.test",
        utc_timestamp=utc_timestamp,
        metadata=metadata or {},
    )


def test_license_headers_and_passive_import():
    obs_dir = ROOT / "backend" / "observability"
    py_files = sorted(obs_dir.glob("*.py"))
    assert len(py_files) == 9
    for path in py_files:
        text = path.read_text(encoding="utf-8")
        assert "Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)" in text, path.name
        assert "ÖZEL LİSANS" in text, path.name

    code = (
        "import sys, threading; "
        "before = threading.active_count(); "
        "import backend.observability as obs; "
        "after = threading.active_count(); "
        "assert before == after; "
        "assert 'torch' not in sys.modules; "
        "assert 'faster_whisper' not in sys.modules; "
        "assert 'sqlalchemy' not in sys.modules"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_event_catalog_priorities_and_allowlist():
    assert priority_for_event("session.closed") == EventPriority.CRITICAL
    assert priority_for_event("generation.revoked") == EventPriority.CRITICAL
    assert priority_for_event("asr.final") == EventPriority.HIGH
    assert priority_for_event("pipeline.stage.f0") == EventPriority.NORMAL
    assert priority_for_event("asr.partial") == EventPriority.LOW
    assert priority_for_event("custom.provider.error") == EventPriority.CRITICAL
    assert priority_for_event("custom.debug.probe") == EventPriority.LOW
    assert "reason" in allowed_metadata_keys_for("generation.revoked")
    assert "raw_transcript" not in allowed_metadata_keys_for("asr.final")


def test_projection_strict_allowlist_and_sentinel_redaction():
    proj = Projection()
    env = _make_env(
        "generation.revoked",
        metadata={
            "reason": "caller 0532 123 45 67 plate 34 ABC 1234 vin WVWZZZ1KZAW123456 Bearer eyJhbGciOiJIUzI1NiJ9.payload123.sig456",
            "raw_transcript": "merhaba aracim 34 XYZ 99",
            "phone": "05321112233",
            "token": "sk-secret1234567890",
        },
    )
    safe = proj.project(env)
    assert safe is not None
    assert safe["utc_timestamp"] == "2026-11-26T00:00:00Z"
    assert "raw_transcript" not in safe["metadata"]
    assert "phone" not in safe["metadata"]
    assert "token" not in safe["metadata"]
    reason = safe["metadata"]["reason"]
    assert "0532" not in reason
    assert "34 ABC 1234" not in reason
    assert "WVWZZZ1KZAW123456" not in reason
    assert "eyJhbGciOi" not in reason
    assert "[REDACTED_PHONE]" in reason
    assert "[REDACTED_PLATE]" in reason
    assert "[REDACTED_VIN]" in reason
    assert "[REDACTED_TOKEN]" in reason

    # Transcript sentinel embedded in an allowlisted field is also redacted
    err = ErrorInfo(
        code="ERR_ASR",
        category=ErrorCategory.PROVIDER,
        retryable=Retryability.YES,
        safe_message="failed near raw_transcript=\"aracim 06 AA 123\" token=secret999",
    )
    safe_err = proj.project(err)
    assert safe_err is not None
    assert "aracim" not in safe_err["safe_message"]
    assert "secret999" not in safe_err["safe_message"]
    assert "[REDACTED_TRANSCRIPT]" in safe_err["safe_message"]
    assert proj.stats.redacted_field_count >= 2


def test_projection_drops_and_increments_on_failure_never_falls_back():
    def broken_redactor(_value: str):
        raise RuntimeError("redactor crashed")

    proj = Projection(redactor=broken_redactor)
    env = _make_env("session.opened", metadata={"reason": "ok"})
    assert proj.project(env) is None
    assert proj.stats.dropped_count == 1
    assert proj.stats.failure_count == 1
    assert proj.stats.projected_count == 0

    # Leaky redactor that fails to strip a sentinel must also trigger drop, never fallback
    leaky_proj = Projection(redactor=lambda s: (s, {}))
    leaky_env = _make_env("generation.revoked", metadata={"reason": "call 0532 555 66 77"})
    assert leaky_proj.project(leaky_env) is None
    assert leaky_proj.stats.dropped_count == 1

    # Non-finite float in an allowlisted scalar key drops cleanly
    bad_proj = Projection()
    assert bad_proj.project({"status": "ok", "actual_duration_ms": float("nan")}) is None
    assert bad_proj.stats.dropped_count == 1


def test_bounded_event_bus_priority_lanes_and_subscriber_isolation():
    bus = BoundedEventBus(max_lane_size=2, drop_policy=DropPolicy.DROP_NEWEST)

    # Without subscribers: lane capacity applies per priority; LOW overflow doesn't drop CRITICAL
    assert bus.try_publish(_make_env("asr.partial", sequence=1)) == AdmissionStatus.ACCEPTED
    assert bus.try_publish(_make_env("asr.partial", sequence=2)) == AdmissionStatus.ACCEPTED
    assert bus.try_publish(_make_env("asr.partial", sequence=3)) == AdmissionStatus.BACKPRESSURE
    assert bus.try_publish(_make_env("session.closed", sequence=4)) == AdmissionStatus.ACCEPTED

    first = bus.pop_next()
    assert first is not None and first.event_type == "session.closed"
    assert bus.stats.dropped_count == 1
    assert bus.stats.overflow_count == 1

    # With isolated subscribers: slow A overflows while fast B receives all events
    received_b: list[str] = []

    def broken_cb(_ev: EventEnvelope) -> None:
        raise RuntimeError("subscriber A boom")

    sub_a = bus.subscribe("sub-a", max_lane_size=1, callback=broken_cb)
    sub_b = bus.subscribe("sub-b", max_lane_size=8, callback=lambda e: received_b.append(e.event_type))

    assert bus.try_publish(_make_env("asr.partial", sequence=10)) == AdmissionStatus.ACCEPTED
    assert bus.try_publish(_make_env("asr.partial", sequence=11)) == AdmissionStatus.ACCEPTED
    assert sub_a.dropped_count == 1
    assert sub_b.dropped_count == 0
    assert bus.stats.subscriber_drops["sub-a"] == 1

    # Critical lane in sub_a still accepts even when LOW lane in sub_a is full
    assert bus.try_publish(_make_env("generation.revoked", sequence=12)) == AdmissionStatus.ACCEPTED

    dispatched = bus.dispatch_all()
    assert dispatched["sub-a"] == 0
    assert sub_a.callback_error_count == 2
    assert dispatched["sub-b"] == 3
    assert received_b[0] == "generation.revoked"

    bus.close()
    assert bus.try_publish(_make_env("session.opened", sequence=99)) == AdmissionStatus.CLOSED
    assert bus.try_publish("not-an-envelope") == AdmissionStatus.INVALID  # type: ignore[arg-type]


def test_trace_store_bounds_clock_domain_and_partial_eviction():
    clock = FakeClock(1_000_000, clock_domain="fake.clock")
    store = TraceStore(max_traces=2, max_spans_per_trace=2, max_total_spans=4)

    store.start_span(
        trace_id="t1",
        span_id="s1",
        name="F0",
        session_id="sess-1",
        start_monotonic_ns=clock.monotonic_ns(),
        clock_domain=clock.clock_domain,
    )
    clock.advance_ms(5)
    done = store.finish_span(
        trace_id="t1",
        span_id="s1",
        end_monotonic_ns=clock.monotonic_ns(),
        clock_domain=clock.clock_domain,
    )
    assert done is not None
    assert done.duration_ns == 5_000_000
    assert done.duration_ms == 5.0

    # Clock domain mismatch and backwards monotonic timestamp rejected
    with pytest.raises(ClockDomainMismatchError):
        store.start_span(
            trace_id="t1",
            span_id="s2",
            name="F1",
            session_id="sess-1",
            start_monotonic_ns=clock.monotonic_ns(),
            clock_domain="other.clock",
        )
    store.start_span(
        trace_id="t1",
        span_id="s2",
        name="F1",
        session_id="sess-1",
        start_monotonic_ns=clock.monotonic_ns(),
        clock_domain=clock.clock_domain,
    )
    with pytest.raises(ValueError):
        store.finish_span(
            trace_id="t1",
            span_id="s2",
            end_monotonic_ns=clock.monotonic_ns() - 1,
            clock_domain=clock.clock_domain,
        )

    # Span eviction inside t1 marks t1 partial=True
    clock.advance_ms(2)
    store.start_span(
        trace_id="t1",
        span_id="s3",
        name="F2",
        session_id="sess-1",
        start_monotonic_ns=clock.monotonic_ns(),
        clock_domain=clock.clock_domain,
    )
    t1 = store.get_trace("t1")
    assert t1 is not None
    assert t1.partial is True
    assert t1.evicted_span_count == 1
    assert len(t1.spans) == 2

    # Trace eviction when max_traces=2 exceeded
    store.start_span(trace_id="t2", span_id="s1", name="F0", session_id="sess-1", start_monotonic_ns=10, clock_domain=clock.clock_domain)
    store.start_span(trace_id="t3", span_id="s1", name="F0", session_id="sess-1", start_monotonic_ns=20, clock_domain=clock.clock_domain)
    assert store.get_trace("t1") is None
    assert store.evicted_traces_count == 1
    assert store.evicted_summaries()[0].partial is True


def test_metrics_registry_null_vs_zero_and_bounded_histograms():
    reg = MetricsRegistry(max_series=16, default_histogram_capacity=3)

    # Unrecorded counter/gauge is UNAVAILABLE with None (never 0.0)
    assert reg.get_counter("turns").value is None
    assert reg.get_counter("turns").status == MetricStatus.UNAVAILABLE
    assert reg.get_gauge("ttfa_ms").value is None
    assert reg.get_gauge("ttfa_ms").status == MetricStatus.UNAVAILABLE

    # Explicit 0.0 is MEASURED
    c_zero = reg.inc("turns", 0.0)
    assert c_zero is not None and c_zero.value == 0.0 and c_zero.status == MetricStatus.MEASURED
    g_zero = reg.set_gauge("ttfa_ms", 0.0, unit="ms")
    assert g_zero is not None and g_zero.value == 0.0 and g_zero.status == MetricStatus.MEASURED

    # Null gauge preserves UNAVAILABLE
    g_null = reg.set_gauge("ttfa_ms", None, unit="ms", reason="not_voice_turn")
    assert g_null is not None and g_null.value is None and g_null.status == MetricStatus.UNAVAILABLE

    # Histogram null-only vs bounded numeric observations
    reg.observe("eos_ms", None, reason="no_voice")
    h_null = reg.get_histogram_summary("eos_ms")
    assert h_null is not None and h_null.status == MetricStatus.UNAVAILABLE and h_null.p95 is None and h_null.null_count == 1

    for v in (0.0, 10.0, 20.0, 30.0):
        reg.observe("eos_ms", v)
    h_val = reg.get_histogram_summary("eos_ms")
    assert h_val is not None
    assert h_val.status == MetricStatus.MEASURED
    assert h_val.count == 3
    assert h_val.evicted_count == 1
    assert h_val.min_value == 10.0
    assert h_val.max_value == 30.0
    assert h_val.p50 == 20.0

    with pytest.raises(ValueError):
        reg.inc("turns", -1.0)
    with pytest.raises(ValueError):
        reg.set_gauge("bad", float("nan"))


def test_evidence_recorder_all_kinds_and_honesty():
    rec = EvidenceRecorder(max_records=4)
    for idx, kind in enumerate(EvidenceKind):
        rec.record(
            evidence_id=f"ev-{idx}",
            kind=kind,
            claim=f"claim for {kind.value}",
            subject="m04.pipeline",
            recorded_monotonic_ns=100 + idx,
            clock_domain="test.clock",
            observation_scope="ENDPOINT" if kind == EvidenceKind.REAL_ENDPOINT_MEASURED else "SERVER",
            details={"reason": "phone 0532 111 22 33", "raw_transcript": "secret"},
        )
    summary = rec.summary()
    assert summary["evicted_count"] == 2
    assert summary["active_count"] == 4

    real_ev = rec.get("ev-5")
    assert real_ev is not None
    assert real_ev.proves_real_endpoint is True
    assert real_ev.is_live_measured is True
    assert "raw_transcript" not in real_ev.details
    assert "0532" not in real_ev.details["reason"]

    with pytest.raises(ValueError):
        rec.record(
            kind=EvidenceKind.REAL_ENDPOINT_MEASURED,
            claim="fake real claim",
            subject="sip",
            recorded_monotonic_ns=1,
            clock_domain="test.clock",
            observation_scope="MOCK",
        )


def test_local_store_lazy_rotation_and_projection(tmp_path: Path):
    store_dir = tmp_path / "obs_store"
    store = LocalObservabilityStore(store_dir, max_records_per_file=2, max_files=2)
    # Passive init & empty read: directory must not exist yet
    assert not store_dir.exists()
    assert store.read_events() == []
    assert not store_dir.exists()

    # Path escape guard
    with pytest.raises(ValueError):
        store._safe_stream_path("../escape")

    for seq in range(3):
        ok = store.append_event(
            _make_env(
                "pipeline.stage.f2",
                sequence=seq,
                metadata={"reason": "call 0532 999 88 77", "raw_transcript": "gizli"},
            )
        )
        assert ok is True

    assert store.stats.written_count == 3
    assert store.stats.rotated_files_count == 1
    assert (store_dir / "events.1.jsonl").exists()
    events = store.read_events()
    assert len(events) == 1
    raw_text = (store_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "gizli" not in raw_text
    assert "0532" not in raw_text
    parsed = json.loads(raw_text.strip())
    assert parsed["metadata"]["reason"] == "call [REDACTED_PHONE]"


def test_legacy_adapter_bridges_v3_telemetry_safely():
    v3_f2 = make_pipeline_event(
        session_id="sess-legacy-1",
        turn_id=3,
        stage="F2",
        status="completed",
        source="live",
        duration_ms=42.5,
        metrics={"char_count": 12, "word_count": 2, "eos_to_first_audio_ms": None, "ttfa_ms": 0.0},
        intermediate_data={"raw_transcript": "aracim 34 ABC 123 telefonum 0532 111 22 33"},
        error_code="WARN_01",
        error_message="failed with Bearer eyJhbGciOiJIUzI1NiJ9.abcdef12.sig1234",
    )
    res = adapt_legacy_event(v3_f2, monotonic_ns=50_000, sequence=7)
    assert res.ok and res.value is not None
    assert res.lossy is True
    assert "dropped_intermediate_data" in res.warnings

    adapted = res.value
    assert adapted.envelope.event_type == "pipeline.stage.f2"
    assert adapted.envelope.clock_domain == "legacy.synthesized"
    assert adapted.error is not None
    assert "eyJhbGciOi" not in adapted.error.safe_message
    assert "[REDACTED_TOKEN]" in adapted.error.safe_message

    # Null vs zero preserved in adapted MetricSamples
    by_name = {m.name: m for m in adapted.metrics}
    assert by_name["eos_to_first_audio_ms"].value is None
    assert by_name["eos_to_first_audio_ms"].status == MetricStatus.UNAVAILABLE
    assert by_name["ttfa_ms"].value == 0.0
    assert by_name["ttfa_ms"].status == MetricStatus.MEASURED

    proj = legacy_event_to_safe_projection(v3_f2)
    assert proj is not None
    serialized = json.dumps(proj, allow_nan=False)
    assert "raw_transcript" not in serialized
    assert "34 ABC 123" not in serialized
    assert "0532" not in serialized
    assert "eyJhbGciOi" not in serialized

    bad_res = adapt_legacy_event({"schema_version": "1.0", "session_id": "s", "turn_id": 0, "stage": "F0", "status": "ok"})
    assert not bad_res.ok
