"""Yönetici sunumu üreticisi: ölçümler kaynaktan okunur, kaynak yoksa 'ölçülmedi' yazılır."""

import importlib.util
import json
from pathlib import Path

import pytest

pytest.importorskip("docx")
from docx import Document  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate_executive_docx.py"
FORBIDDEN = ["1095", "785", "4.31", "98.5", "Pilot Yayına Hazır", "TSE"]
FIXTURE_WER = 12.34


def _load():
    spec = importlib.util.spec_from_file_location("generate_executive_docx", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _report():
    channel = {
        "sample_count": 7,
        "avg_wer_pct": FIXTURE_WER,
        "avg_cer_pct": 5.5,
        "terms_total": 10,
        "automotive_accuracy_pct": 40.0,
        "terms_missed": {"tsi": 2},
    }
    return {
        "schema": 1,
        "measured_at": "2026-01-02T03:04:05+00:00",
        "gate_channel": "telephony_8k",
        "provenance": {"stt_model": "m", "stt_device": "cuda", "stt_compute_type": "float16", "lora_adapter": None},
        "sample_count": 7,
        "failed_synthesis": 0,
        "channels": {"telephony_8k": channel},
        "tts": {"rtf_avg": 0.5, "rtf_max": 1.0},
        "f0": {"median_hz": 200.0, "max_drift_from_baseline_hz": None, "baseline_measured_at": None},
    }


def _text(path):
    doc = Document(str(path))
    return "\n".join(
        "".join(t.text or "" for t in el.iter(qn("w:t"))) for el in doc.element.body.iter() if el.tag == qn("w:p")
    )


def test_missing_sources_are_reported_not_invented(tmp_path):
    acoustic = tmp_path / "latest.json"
    acoustic.write_text(json.dumps(_report()), encoding="utf-8")
    out = tmp_path / "out" / "sunum.docx"
    _load().generate_document(
        {
            "output": out,
            "acoustic": acoustic,
            "m11": [tmp_path / "yok.json"],
            "latency": tmp_path / "yok-latency.json",
            "nav": tmp_path / "yok.ts",
            "screenshots": None,
        },
        test_count_line=None,
    )
    text = _text(out)
    assert "ölçülmedi" in text
    assert "12,34" in text  # fixture WER, Türkçe ondalık
    assert "Durum: PoC. Bu belge yalnızca ölçülen değerleri içerir." in text
    for forbidden in FORBIDDEN:
        assert forbidden not in text
