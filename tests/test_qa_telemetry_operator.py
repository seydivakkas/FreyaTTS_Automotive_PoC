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

import pytest
from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.text import normalize
from backend.qa_telemetry_operator import (
    ABCTripleVariantEvaluator,
    CodecType,
    M11HardwareAcceptanceGate,
    OperatorCallState,
    OperatorRealtimePanel,
    OperatorSessionView,
    RealtimeTurnMetrics,
    RealtimeTurnMetricsCollector,
    VariantType,
    abc_evaluator,
    m11_gate,
    operator_panel,
    realtime_turn_collector,
)
import src.qa_telemetry_operator as src_qa


def test_facade_exports():
    """src.qa_telemetry_operator cephesinin tüm sınıfları ve örnekleri eksiksiz dışa aktardığını doğrular."""
    assert src_qa.RealtimeTurnMetrics is RealtimeTurnMetrics
    assert src_qa.RealtimeTurnMetricsCollector is RealtimeTurnMetricsCollector
    assert src_qa.OperatorRealtimePanel is OperatorRealtimePanel
    assert src_qa.OperatorCallState is OperatorCallState
    assert src_qa.OperatorSessionView is OperatorSessionView
    assert src_qa.VariantType is VariantType
    assert src_qa.CodecType is CodecType
    assert src_qa.ABCTripleVariantEvaluator is ABCTripleVariantEvaluator
    assert src_qa.M11HardwareAcceptanceGate is M11HardwareAcceptanceGate
    assert src_qa.realtime_turn_collector is realtime_turn_collector
    assert src_qa.operator_panel is operator_panel
    assert src_qa.abc_evaluator is abc_evaluator
    assert src_qa.m11_gate is m11_gate


def test_realtime_metrics_fake_zero_prohibition():
    """
    Sahte Sıfır Yasağı (Fake Zero Prohibition) Testi:
    Ölçülmemiş veya gerçekleşmemiş gecikme alanları ASLA 0.0 olamaz; kesinlikle None (null) olmalıdır.
    """
    m = RealtimeTurnMetrics(
        turn_id="turn_test_001",
        session_id="sess_test_001",
        started_at_iso="2026-11-03T19:00:00Z",
    )

    # Başlangıçta tüm gecikme değerleri None olmalıdır (0.0 YASAKTIR)
    assert m.asr_latency_ms is None
    assert m.llm_ttft_ms is None
    assert m.llm_total_latency_ms is None
    assert m.tts_ttfa_ms is None
    assert m.tts_total_latency_ms is None
    assert m.barge_in_stop_ms is None
    assert m.total_turn_latency_ms is None

    # model_dump serialize edildiğinde null (None) değerler korunmalıdır
    dump = m.model_dump()
    assert dump["barge_in_stop_ms"] is None
    assert dump["tts_ttfa_ms"] is None

    # Gerçek ölçüm kaydedildiğinde pozitif sayı olmalıdır
    m.tts_ttfa_ms = 185.4
    assert m.tts_ttfa_ms == 185.4
    assert m.barge_in_stop_ms is None  # Barge-in olmadıysa halen None kalmalı


def test_turn_collector_lifecycle_and_opentelemetry_span():
    """RealtimeTurnMetricsCollector yaşam döngüsü ve OpenTelemetry span üretimini test eder."""
    collector = RealtimeTurnMetricsCollector()
    turn_id = "turn_lifecycle_101"
    session_id = "sess_lifecycle_101"

    # Turn başlat
    metrics = collector.start_turn(turn_id=turn_id, session_id=session_id)
    assert metrics.turn_id == turn_id
    assert metrics.session_id == session_id

    # Aşama aşama gecikmeleri kaydet
    collector.record_latency(turn_id, "asr_latency_ms", 120.0)
    collector.record_latency(turn_id, "llm_ttft_ms", 210.5)
    collector.record_latency(turn_id, "tts_ttfa_ms", 195.0)

    # Generation chunk metriklerini kaydet
    collector.record_generation(
        turn_id=turn_id,
        chunk_index=0,
        generation_ms=180.0,
        audio_duration_sec=1.5,
        rtf=0.12,
        tokens_count=8,
    )
    collector.record_generation(
        turn_id=turn_id,
        chunk_index=1,
        generation_ms=160.0,
        audio_duration_sec=1.2,
        rtf=0.13,
        tokens_count=6,
    )

    # Turn sonlandır
    finished = collector.finish_turn(
        turn_id=turn_id,
        total_latency_ms=525.5,
        mos_score=4.42,
    )
    assert finished is not None
    assert finished.total_turn_latency_ms == 525.5
    assert finished.mos_score == 4.42
    assert len(finished.generation_chunks) == 2
    assert finished.avg_rtf == pytest.approx(0.125, rel=1e-2)

    # OpenTelemetry Trace Span doğrulaması
    span = collector.export_opentelemetry_span(turn_id)
    assert span is not None
    assert span["name"] == "freya_telephony_turn"
    assert span["attributes"]["turn.id"] == turn_id
    assert span["attributes"]["session.id"] == session_id
    assert span["attributes"]["latency.tts_ttfa_ms"] == 195.0
    assert span["attributes"]["turn.status"] == "COMPLETED"


def test_operator_takeover_whisper_release_lifecycle():
    """Operatör Paneli (RT-10 / HLS-07) Canlı Devralma, Fısıltı ve İade döngüsünü test eder."""
    panel = OperatorRealtimePanel()
    session_id = "call_op_test_99"
    caller_id = "05321234567"

    # 1. Çağrı kaydı
    sess = panel.register_call(session_id, caller_id, initial_turn_id="turn_init_1")
    assert sess.state == OperatorCallState.AI_HANDLING
    assert sess.session_id == session_id

    # 2. Canlı listeyi sorgula
    live = panel.get_live_sessions()
    assert len(live) == 1
    assert live[0]["session_id"] == session_id
    assert live[0]["state"] == "AI_HANDLING"

    # 3. Operatör Çağrıyı Devralır (Takeover)
    takeover_res = panel.takeover_call(
        session_id=session_id,
        operator_id="operator_elif",
        reason="complex_pricing_inquiry",
    )
    assert takeover_res["success"] is True
    assert takeover_res["state"] == "TAKEN_OVER"
    assert takeover_res["operator_id"] == "operator_elif"

    # 4. Operatör Asistana Fısıldar (Whisper)
    whisper_res = panel.whisper_to_agent(
        session_id=session_id,
        operator_id="operator_elif",
        message="Müşteriye %10 filo indirimi tanımlanabilir bilgisini ekle.",
    )
    assert whisper_res["success"] is True
    assert whisper_res["whisper_delivered"] is True

    # 5. Operatör Görüşmeyi Yapay Zekâya İade Eder (Release)
    release_res = panel.release_call(session_id=session_id, operator_id="operator_elif")
    assert release_res["success"] is True
    assert release_res["state"] == "AI_HANDLING"

    # 6. Çağrı Sonlandırma (Terminated)
    panel.terminate_call(session_id)
    assert len(panel.get_live_sessions()) == 0


def test_abc_triple_variant_wer_cer_mos_evaluation():
    """HLS-08: A/B/C Üçlü Varyant, Levenshtein, WER, CER ve ITU-T MOS hesaplamalarını test eder."""
    evaluator = ABCTripleVariantEvaluator()

    # Levenshtein testleri
    assert evaluator.compute_levenshtein_distance(["a", "b"], ["a", "b"]) == 0
    assert evaluator.compute_levenshtein_distance(["a", "b"], ["a", "c"]) == 1
    assert evaluator.compute_levenshtein_distance([], ["a", "b"]) == 2

    # WER / CER testleri
    metrics = evaluator.compute_wer_cer(
        reference="peugeot üç bin sekiz",
        hypothesis="peugeot üç bin sekiz",
    )
    assert metrics["wer"] == 0.0
    assert metrics["cer"] == 0.0

    # ITU-T G.107 MOS testleri
    mos_studio = evaluator.compute_itu_mos(CodecType.PCM_48K, rtf=0.15)
    mos_g711 = evaluator.compute_itu_mos(CodecType.G711_ALAW, rtf=0.15)
    assert mos_studio >= 4.0
    assert mos_g711 >= 3.5
    assert mos_studio > mos_g711

    # Varyant bazlı metin ölçümü: ham metin okunuşla eşleşmez, ses metriği uydurulmaz
    res_a = evaluator.evaluate_sentence(
        raw_text="Peugeot 3008 1.6 PureTech",
        expected_spoken="pöjo üç bin sekiz bir nokta altı pürtek",
        variant=VariantType.VARIANT_A,
    )
    assert res_a["variant"] == "variant_a"
    assert res_a["measured"] is True
    assert res_a["wer"] > 0.5

    res_c = evaluator.evaluate_sentence(
        raw_text="Peugeot 3008",
        expected_spoken="pöjo üç bin sekiz",
        variant=VariantType.VARIANT_C,
    )
    assert res_c["measured"] is False
    assert res_c["wer"] is None


def _spoken(raw: str) -> str:
    return normalize(raw)["normalized"]


def test_abc_suite_holds_without_acoustic_measurements():
    """Metin kusursuz olsa bile ses ölçümü yokken Kalite Kapısı 5 PASS veremez."""
    evaluator = ABCTripleVariantEvaluator()
    raw = ["Peugeot 3008", "Renault Megane 1.5 dCi", "1.250.000 TL"]
    report = evaluator.run_benchmark_suite([(text, _spoken(text)) for text in raw])

    assert report["total_sentences"] == 3
    assert report["evaluation_scope"] == "text_normalization_only"
    assert report["quality_gate_5_status"] == "HOLD"
    assert report["quality_gate_failed"] == []
    assert set(report["quality_gate_missing"]) == {
        "automotive_accuracy_pct",
        "speaker_embedding_abx",
        "max_f0_drift_hz",
    }

    b_summary = report["variant_summaries"][VariantType.VARIANT_B.value]
    assert b_summary["sample_count"] == 3
    assert b_summary["avg_wer_pct"] == 0.0
    assert b_summary["avg_cer_pct"] == 0.0
    for name in ("avg_mos", "speaker_embedding_abx", "automotive_accuracy_pct", "max_f0_drift_hz"):
        assert b_summary[name] is None

    c_summary = report["variant_summaries"][VariantType.VARIANT_C.value]
    assert c_summary["sample_count"] == 0
    assert c_summary["avg_wer_pct"] is None


def test_abc_suite_results_depend_on_input():
    """Sonuç sabit değildir: yanlış beklenen metin ölçülen hatayı yükseltir ve kapıyı düşürür."""
    evaluator = ABCTripleVariantEvaluator()
    report = evaluator.run_benchmark_suite([("Peugeot 3008", "tamamen ilgisiz bir cümle")])

    b_summary = report["variant_summaries"][VariantType.VARIANT_B.value]
    assert b_summary["avg_wer_pct"] == 100.0
    assert report["quality_gate_5_status"] == "FAIL"
    assert "avg_wer_pct" in report["quality_gate_failed"]


def test_variant_b_measures_the_live_normalizer():
    """Kapı, müşteriye okunan metni üreten canlı normalizer'ı ölçer."""
    raw = "Araç 1.6 PureTech 180 bg motora sahip."
    result = ABCTripleVariantEvaluator().evaluate_sentence(
        raw, _spoken(raw), variant=VariantType.VARIANT_B
    )
    assert result["hypothesis"] == normalize(raw)["normalized"]
    assert result["wer"] == 0.0


def test_abc_suite_handles_no_samples():
    report = ABCTripleVariantEvaluator().run_benchmark_suite([])
    assert report["quality_gate_5_status"] == "HOLD"
    assert report["variant_summaries"][VariantType.VARIANT_B.value]["avg_wer_pct"] is None


def test_quality_gate_passes_only_when_every_criterion_is_measured():
    evaluator = ABCTripleVariantEvaluator()
    measured = {
        "automotive_accuracy_pct": 96.0,
        "avg_wer_pct": 20.0,
        "avg_cer_pct": 15.0,
        "speaker_embedding_abx": 0.85,
        "max_f0_drift_hz": 1.0,
    }
    assert evaluator.evaluate_quality_gate(measured)["status"] == "PASS"
    assert evaluator.evaluate_quality_gate({**measured, "speaker_embedding_abx": None})["status"] == "HOLD"
    failed = evaluator.evaluate_quality_gate(
        {**measured, "speaker_embedding_abx": None, "max_f0_drift_hz": 9.0}
    )
    assert failed["status"] == "FAIL"
    assert failed["failed"] == ["max_f0_drift_hz"]
    assert failed["missing"] == ["speaker_embedding_abx"]


def test_m11_hardware_acceptance_hold_enforcement():
    """M11 Fiziksel Donanım Kabul Güvenlik Kalkanı: Fiziksel PBX kanıtı yoksa durum katı biçimde HOLD olmalıdır."""
    gate = M11HardwareAcceptanceGate()

    # 1. Simülasyon ortamında kanıtsız çağrı -> HOLD
    res_hold = gate.evaluate_acceptance(
        has_physical_pbx_trace=False,
        has_hardware_trunk=False,
    )
    assert res_hold["overall_status"] == "HOLD"
    assert res_hold["physical_acceptance_verified"] is False
    assert res_hold["environment"] == "ENVIRONMENT_SIMULATED"

    # 2. Yalnızca biri var ancak trace eksik -> HOLD
    res_partial = gate.evaluate_acceptance(
        has_physical_pbx_trace=True,
        has_hardware_trunk=False,
    )
    assert res_partial["overall_status"] == "HOLD"

    # 3. Gerçek pcap ve PBX kanıtı mevcut -> PASS
    res_pass = gate.evaluate_acceptance(
        has_physical_pbx_trace=True,
        has_hardware_trunk=True,
        evidence_files=["asterisk_ari_pcap_trace.pcap", "sip_trunk_e1_signaling.log"],
    )
    assert res_pass["overall_status"] == "PASS"
    assert res_pass["physical_acceptance_verified"] is True
    assert res_pass["environment"] == "ENVIRONMENT_PHYSICAL_HARDWARE"


def test_rest_api_operator_and_qa_endpoints():
    """FastAPI REST API Operatör ve QA uç noktalarının entegrasyon testi."""
    client = TestClient(app)
    auth = ("admin", settings.admin_password)

    # 1. Operatör Çağrı Kaydı
    reg_resp = client.post(
        "/api/operator/register-call",
        json={
            "session_id": "api_test_sess_01",
            "caller_id": "05441112233",
            "initial_turn_id": "turn_api_01",
            "mos_score": 4.35,
            "rtf": 0.17,
        },
        auth=auth,
    )
    assert reg_resp.status_code == 200
    assert reg_resp.json()["success"] is True

    # 2. Canlı Çağrı Listesi
    live_resp = client.get("/api/operator/live-sessions", auth=auth)
    assert live_resp.status_code == 200
    sessions = live_resp.json()["sessions"]
    assert any(s["session_id"] == "api_test_sess_01" for s in sessions)

    # 3. Operatör Devralma (Takeover)
    takeover_resp = client.post(
        "/api/operator/takeover",
        json={
            "session_id": "api_test_sess_01",
            "operator_id": "op_ahmet",
            "reason": "customer_requested_human",
        },
        auth=auth,
    )
    assert takeover_resp.status_code == 200
    assert takeover_resp.json()["state"] == "TAKEN_OVER"

    # 4. Operatör Fısıltı (Whisper)
    whisper_resp = client.post(
        "/api/operator/whisper",
        json={
            "session_id": "api_test_sess_01",
            "operator_id": "op_ahmet",
            "message": "Aracı ekspertiz için perşembeye yönlendir.",
        },
        auth=auth,
    )
    assert whisper_resp.status_code == 200
    assert whisper_resp.json()["whisper_delivered"] is True

    # 5. Operatör İade (Release)
    release_resp = client.post(
        "/api/operator/release",
        json={
            "session_id": "api_test_sess_01",
            "operator_id": "op_ahmet",
        },
        auth=auth,
    )
    assert release_resp.status_code == 200
    assert release_resp.json()["state"] == "AI_HANDLING"

    # 6. Telemetri Sorgulama (Önce collector'a turn kaydet)
    realtime_turn_collector.start_turn(turn_id="turn_telemetry_test_api", session_id="api_test_sess_01")
    realtime_turn_collector.finish_turn("turn_telemetry_test_api", total_latency_ms=480.0, mos_score=4.4)

    telem_resp = client.get("/api/qa/telemetry/turn_telemetry_test_api", auth=auth)
    assert telem_resp.status_code == 200
    assert telem_resp.json()["turn"]["turn_id"] == "turn_telemetry_test_api"
    assert "opentelemetry_span" in telem_resp.json()

    # 7. Kalite Kapısı 5 / Üçlü Varyant Değerlendirme
    qa_resp = client.post(
        "/api/qa/evaluate-variants",
        json={
            "samples": [
                ["Peugeot 3008", "pöjo üç bin sekiz"],
                ["Renault Megane", "reno megan"],
            ],
        },
        auth=auth,
    )
    assert qa_resp.status_code == 200
    assert qa_resp.json()["quality_gate_5_status"] != "PASS"
    assert qa_resp.json()["evaluation_scope"] == "text_normalization_only"

    # 8. M11 Donanım Kabul Durumu
    m11_resp = client.get("/api/qa/m11-status", auth=auth)
    assert m11_resp.status_code == 200
    assert m11_resp.json()["overall_status"] == "HOLD"
    assert m11_resp.json()["environment"] == "ENVIRONMENT_SIMULATED"
