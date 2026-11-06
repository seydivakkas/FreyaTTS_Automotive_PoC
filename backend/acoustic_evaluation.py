"""Gerçek ses çıktısından kalite ölçümü: TTS sesi STT ile geri tanınır.

WER/CER ve terim doğruluğu TTS ile STT'nin birleşik sonucudur; hata tek bir modele
atfedilemez. Ölçülemeyen metrikler None kalır, tahmini değer üretilmez:
- ABX için kurulu bir konuşmacı modeli yoktur.
- MOS için dinleyici testi veya standart bir ölçüm aracı yoktur.
- F0 sapması yalnızca onaylanmış taban kayda göre hesaplanır.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from backend.config import settings
from backend.normalizer_rules import BASE_AUTOMOTIVE_LEXICON
from backend.qa_telemetry_operator import abc_evaluator
from backend.text import normalize

REPORT_SCHEMA = 1
# Müşterinin telefonda duyduğu hat olduğu için kapı bu kanalın sonucunu kullanır.
GATE_CHANNEL = "telephony_8k"
CHANNELS = ("studio_48k", GATE_CHANNEL)


def report_dir() -> Path:
    return Path(settings.data_dir) / "acoustic"


def report_path() -> Path:
    return report_dir() / "latest.json"


def baseline_path() -> Path:
    return report_dir() / "baseline.json"


def canonical(text: str) -> str:
    """Karşılaştırma için Türkçe küçük harfe çevirir, noktalamayı kaldırır."""
    lowered = text.replace("İ", "i").replace("I", "ı").lower().replace("i̇", "i")
    return " ".join(re.sub(r"[^\w\s]", " ", lowered, flags=re.UNICODE).split())


def spoken_form(text: str) -> str:
    """Metni canlı normalizer'dan geçirir; rakam ve kısaltmalar okunuşa döner."""
    try:
        return canonical(normalize(text)["normalized"])
    except ValueError:
        return canonical(text)


def find_terms(raw_text: str) -> List[Tuple[str, str]]:
    """Cümledeki otomotiv terimlerini (kaynak, okunuş) olarak döndürür."""
    remaining = raw_text.lower()
    found = []
    for term in sorted(BASE_AUTOMOTIVE_LEXICON, key=len, reverse=True):
        pattern = r"(?<![\w-])" + re.escape(term) + r"(?![\w-])"
        for _ in re.findall(pattern, remaining):
            found.append((term, canonical(BASE_AUTOMOTIVE_LEXICON[term])))
        remaining = re.sub(pattern, " ", remaining)
    return found


def _contains_words(haystack: str, needle: str) -> bool:
    # STT Latin kısaltmayı büyük yazar: Türkçe küçültmede "TDI" "tdı" olur, "tdi" ile eşleşmez.
    folded = f" {haystack} ".replace("ı", "i")
    return bool(needle) and f" {needle.replace('ı', 'i')} " in folded


def split_glued_codes(text: str) -> str:
    """STT'nin bitişik yazdığı rakam ve harfleri ayırır: "2.0TDI" -> "2.0 TDI"."""
    return re.sub(r"(?<=\d)(?=[^\W\d_])|(?<=[^\W\d_])(?=\d)", " ", text)


def evaluate_transcript(raw_text: str, transcript: str) -> Dict[str, Any]:
    """Bir kanalın STT çıktısını beklenen okunuşla karşılaştırır."""
    separated = split_glued_codes(transcript)
    reference = spoken_form(raw_text)
    hypothesis = spoken_form(separated)
    errors = abc_evaluator.compute_wer_cer(reference, hypothesis)
    plain = canonical(separated)
    terms = find_terms(raw_text)
    missed = [
        term
        for term, spoken in terms
        if not (_contains_words(hypothesis, spoken) or _contains_words(plain, canonical(term)))
    ]
    return {
        "transcript": transcript,
        "wer": errors["wer"],
        "cer": errors["cer"],
        "terms_total": len(terms),
        "terms_correct": len(terms) - len(missed),
        "terms_missed": missed,
    }


def measure_f0(audio: np.ndarray, sample_rate: int) -> Optional[float]:
    """Sesli bölgelerin medyan F0 değeri (Hz); sesli bölge yoksa None."""
    import librosa

    f0, voiced, _ = librosa.pyin(
        np.asarray(audio, dtype=np.float32),
        fmin=80.0,
        fmax=450.0,
        sr=sample_rate,
        frame_length=1024,
    )
    values = f0[voiced & np.isfinite(f0)] if f0 is not None else np.array([])
    return round(float(np.median(values)), 2) if values.size else None


def _mean_pct(values: List[float]) -> Optional[float]:
    return round(float(np.mean(values)) * 100.0, 2) if values else None


def summarize_channel(rows: List[Dict[str, Any]], channel: str) -> Dict[str, Any]:
    """Başarısız sentez tam hata sayılır; sonuçtan çıkarılmaz."""
    results = [row["channels"].get(channel) for row in rows]
    wer = [r["wer"] if r else 1.0 for r in results]
    cer = [r["cer"] if r else 1.0 for r in results]
    total = sum(r["terms_total"] if r else len(find_terms(row["text"])) for r, row in zip(results, rows))
    correct = sum(r["terms_correct"] for r in results if r)
    missed: Dict[str, int] = {}
    for result in results:
        for term in result["terms_missed"] if result else []:
            missed[term] = missed.get(term, 0) + 1
    return {
        "sample_count": len(rows),
        "avg_wer_pct": _mean_pct(wer),
        "avg_cer_pct": _mean_pct(cer),
        "terms_total": total,
        "automotive_accuracy_pct": round(correct / total * 100.0, 2) if total else None,
        "terms_missed": dict(sorted(missed.items(), key=lambda item: -item[1])),
    }


def f0_drift_from_baseline(
    rows: List[Dict[str, Any]], baseline: Optional[Dict[str, Any]]
) -> Optional[float]:
    """Aynı cümlenin taban kayda göre en büyük F0 farkı; taban yoksa None."""
    if not baseline:
        return None
    reference = baseline.get("f0_by_id", {})
    drifts = [
        abs(row["f0_hz"] - reference[row["id"]])
        for row in rows
        if row.get("f0_hz") is not None and reference.get(row["id"]) is not None
    ]
    return round(max(drifts), 2) if drifts else None


def build_report(
    rows: List[Dict[str, Any]],
    baseline: Optional[Dict[str, Any]] = None,
    provenance: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    f0_values = [row["f0_hz"] for row in rows if row.get("f0_hz") is not None]
    rtf_values = [row["rtf"] for row in rows if row.get("rtf") is not None]
    return {
        "schema": REPORT_SCHEMA,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "gate_channel": GATE_CHANNEL,
        "provenance": provenance or {},
        "sample_count": len(rows),
        "failed_synthesis": sum(1 for row in rows if row.get("error")),
        "channels": {channel: summarize_channel(rows, channel) for channel in CHANNELS},
        "tts": {
            "rtf_avg": round(float(np.mean(rtf_values)), 3) if rtf_values else None,
            "rtf_max": round(float(np.max(rtf_values)), 3) if rtf_values else None,
        },
        "f0": {
            "median_hz": round(float(np.median(f0_values)), 2) if f0_values else None,
            "min_hz": min(f0_values) if f0_values else None,
            "max_hz": max(f0_values) if f0_values else None,
            "baseline_measured_at": baseline.get("measured_at") if baseline else None,
            "max_drift_from_baseline_hz": f0_drift_from_baseline(rows, baseline),
        },
        "not_measured": {
            "speaker_embedding_abx": "Kurulu konuşmacı modeli yok",
            "avg_mos": "Dinleyici testi veya standart ölçüm aracı yok",
        },
        "rows": rows,
    }


def build_baseline(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "measured_at": report["measured_at"],
        "f0_by_id": {row["id"]: row["f0_hz"] for row in report["rows"] if row.get("f0_hz") is not None},
    }


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_latest_report() -> Optional[Dict[str, Any]]:
    report = _read_json(report_path())
    return report if report and report.get("schema") == REPORT_SCHEMA else None


def load_baseline() -> Optional[Dict[str, Any]]:
    return _read_json(baseline_path())


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def select_cases(cases: List[Dict[str, Any]], per_category: Optional[int]) -> List[Dict[str, Any]]:
    """Her kategoriden ilk N cümleyi seçer; None tüm cümleler demektir."""
    if per_category is None:
        return list(cases)
    counts: Dict[str, int] = {}
    selected = []
    for case in cases:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
        if counts[case["category"]] <= per_category:
            selected.append(case)
    return selected
