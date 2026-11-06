"""Ses ölçümü hesaplarının birim testleri; gerçek model gerektirmez."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.acoustic_evaluation import (
    GATE_CHANNEL,
    build_baseline,
    build_report,
    canonical,
    evaluate_transcript,
    f0_drift_from_baseline,
    find_terms,
    load_latest_report,
    measure_f0,
    report_path,
    select_cases,
    write_json,
)
from backend.main import app, settings as app_settings
from backend.qa_telemetry_operator import ABCTripleVariantEvaluator, VariantType


def _row(case_id="A1", text="Volkswagen Passat 1.5 TSI aracınız.", transcript=None, f0=210.0, rtf=0.4):
    transcript = transcript if transcript is not None else text
    result = evaluate_transcript(text, transcript)
    return {
        "id": case_id,
        "category": "test",
        "text": text,
        "rtf": rtf,
        "f0_hz": f0,
        "channels": {"studio_48k": result, GATE_CHANNEL: result},
    }


def test_canonical_handles_turkish_case_and_punctuation():
    assert canonical("İSTANBUL'da  KIRMIZI, araç!") == "istanbul da kırmızı araç"


def test_find_terms_prefers_longest_and_counts_occurrences():
    terms = [term for term, _ in find_terms("Mercedes-Benz ve Mercedes 1.5 TSI, TSI")]
    assert terms.count("mercedes-benz") == 1
    assert terms.count("mercedes") == 1
    assert terms.count("tsi") == 2
    assert find_terms("Bu cümlede terim yok.") == []


def test_perfect_transcript_has_no_errors():
    result = evaluate_transcript("Volkswagen Passat 1.5 TSI aracınız.", "Volkswagen Passat 1.5 TSI aracınız.")
    assert result["wer"] == 0.0
    assert result["cer"] == 0.0
    assert result["terms_total"] == 3
    assert result["terms_missed"] == []


@pytest.mark.parametrize(
    "transcript",
    [
        "Bu araç 1.5 TSI motorlu.",
        "Bu araç 1.5TSI motorlu.",
        "Bu araç bir nokta beş tsi motorlu.",
        "Bu araç bir nokta beş ti es ay motorlu.",
    ],
)
def test_uppercase_and_glued_codes_count_as_correct(transcript):
    result = evaluate_transcript("Bu araç 1.5 TSI motorlu.", transcript)
    assert result["terms_missed"] == []
    assert result["wer"] == 0.0


def test_digit_transcript_matches_spoken_reference():
    result = evaluate_transcript("Aracınızın değeri 1.250.000 TL.", "Aracınızın değeri 1.250.000 TL.")
    assert result["wer"] == 0.0


def test_wrong_transcript_is_measured_as_error():
    result = evaluate_transcript(
        "Volkswagen Passat 1.5 TSI aracınız.",
        "Force Wagon Puzzle 1.5 Tesey aracınız.",
    )
    assert result["wer"] > 0.3
    assert "volkswagen" in result["terms_missed"]
    assert "passat" in result["terms_missed"]
    assert "tsi" in result["terms_missed"]
    assert result["terms_correct"] == 0


def test_measure_f0_detects_pitch_and_silence():
    rate = 16000
    time_axis = np.arange(rate) / rate
    tone = 0.3 * np.sin(2 * np.pi * 200.0 * time_axis)
    assert measure_f0(tone, rate) == pytest.approx(200.0, abs=3.0)
    assert measure_f0(np.zeros(rate), rate) is None


def test_f0_drift_requires_baseline_and_uses_same_sentence():
    rows = [_row("A1", f0=210.0), _row("A2", f0=205.0), _row("A3", f0=None)]
    assert f0_drift_from_baseline(rows, None) is None
    assert f0_drift_from_baseline(rows, {"f0_by_id": {"X": 200.0}}) is None
    baseline = {"f0_by_id": {"A1": 208.0, "A2": 200.0, "A3": 190.0}}
    assert f0_drift_from_baseline(rows, baseline) == 5.0


def test_report_counts_failed_synthesis_as_full_error():
    good = _row("A1")
    failed = {"id": "A2", "category": "test", "text": "1.5 TSI", "channels": {}, "error": "RuntimeError: x"}
    report = build_report([good, failed])
    channel = report["channels"][GATE_CHANNEL]
    assert report["failed_synthesis"] == 1
    assert channel["sample_count"] == 2
    assert channel["avg_wer_pct"] == 50.0
    assert channel["terms_total"] == 4
    assert channel["automotive_accuracy_pct"] == 75.0
    assert report["not_measured"]["speaker_embedding_abx"]


def test_build_baseline_skips_missing_f0():
    report = build_report([_row("A1", f0=210.0), _row("A2", f0=None)])
    assert build_baseline(report)["f0_by_id"] == {"A1": 210.0}


def test_select_cases_is_stratified():
    cases = [{"id": str(i), "category": "a" if i < 5 else "b"} for i in range(8)]
    assert [c["id"] for c in select_cases(cases, 2)] == ["0", "1", "5", "6"]
    assert len(select_cases(cases, None)) == 8


def test_gate_uses_audio_report_but_never_passes_without_abx():
    report = build_report([_row()], baseline={"f0_by_id": {"A1": 210.0}, "measured_at": "t"})
    result = ABCTripleVariantEvaluator().run_benchmark_suite([("Peugeot 3008", "x")], acoustic_report=report)
    variant_b = result["variant_summaries"][VariantType.VARIANT_B.value]
    assert result["evaluation_scope"] == "audio_roundtrip"
    assert variant_b["avg_wer_pct"] == 0.0
    assert variant_b["automotive_accuracy_pct"] == 100.0
    assert variant_b["max_f0_drift_hz"] == 0.0
    assert variant_b["speaker_embedding_abx"] is None
    assert variant_b["text_wer_pct"] == 100.0
    assert result["quality_gate_5_status"] == "HOLD"
    assert result["quality_gate_missing"] == ["speaker_embedding_abx"]


def test_gate_fails_on_bad_audio_measurement():
    bad = _row(transcript="Force Wagon Puzzle aracınız.")
    result = ABCTripleVariantEvaluator().run_benchmark_suite([], acoustic_report=build_report([bad]))
    assert result["quality_gate_5_status"] == "FAIL"
    assert "automotive_accuracy_pct" in result["quality_gate_failed"]


def test_api_reads_report_from_data_dir(monkeypatch):
    monkeypatch.setattr(app_settings, "admin_password", "secret")
    client = TestClient(app)
    path = report_path()
    assert load_latest_report() is None
    body = client.post("/api/qa/evaluate-variants", json={}, auth=("admin", "secret")).json()
    assert body["evaluation_scope"] == "text_normalization_only"
    assert body["acoustic_report"] is None

    write_json(path, build_report([_row()]))
    try:
        body = client.post("/api/qa/evaluate-variants", json={}, auth=("admin", "secret")).json()
        assert body["evaluation_scope"] == "audio_roundtrip"
        assert body["acoustic_report"]["sample_count"] == 1
    finally:
        path.unlink()
