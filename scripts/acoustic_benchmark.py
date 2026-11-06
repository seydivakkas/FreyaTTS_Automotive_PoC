"""Kalite Kapısı 5 için gerçek ses ölçümü. Taklit model kullanmaz.

FreyaTTS ile ses üretir, telefon hattına çevirir ve faster-whisper ile geri tanır.
Sonuç data/acoustic/latest.json dosyasına, sesler data/acoustic/audio/ altına yazılır.
İşletim veritabanına dokunmaz.

    .venv\\Scripts\\python -m scripts.acoustic_benchmark
    .venv\\Scripts\\python -m scripts.acoustic_benchmark --all
    .venv\\Scripts\\python -m scripts.acoustic_benchmark --save-baseline

--save-baseline yalnızca sesler dinlenip onaylandıktan sonra kullanılmalıdır;
sonraki ölçümlerin F0 sapması bu kayda göre hesaplanır.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# backend içe aktarılmadan önce: STT ipuçları sabit kalsın, işletim verisi okunmasın.
_database_dir = tempfile.TemporaryDirectory(prefix="freya-acoustic-", ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = "sqlite:///" + Path(_database_dir.name, "empty.db").as_posix()

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from backend.acoustic_evaluation import (  # noqa: E402
    baseline_path,
    build_baseline,
    build_report,
    evaluate_transcript,
    load_baseline,
    measure_f0,
    report_dir,
    report_path,
    select_cases,
    write_json,
)
from backend.audio import apply_telephony_eq_and_downsample_8k, resample  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.models import models  # noqa: E402

FIXTURE = ROOT / "data" / "fixtures" / "legacy_320_cases.json"


def _vendor_commit() -> str | None:
    result = subprocess.run(
        ["git", "-C", str(ROOT / settings.freya_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None


async def measure_case(case: dict, audio_dir: Path) -> dict:
    row = {"id": case["id"], "category": case["category"], "text": case["text"], "channels": {}}
    try:
        start = time.perf_counter()
        audio = np.asarray(await models.synth(case["text"]), dtype=np.float32)
        elapsed = time.perf_counter() - start
    except Exception as error:
        row["error"] = f"{type(error).__name__}: {error}"
        return row

    duration = len(audio) / 48000
    row.update(tts_ms=round(elapsed * 1000), audio_seconds=round(duration, 2), rtf=round(elapsed / duration, 3))
    row["f0_hz"] = measure_f0(resample(audio, 48000, 16000), 16000)

    # Telefon hattına giden gerçek çıktı int16'dır; STT için [-1, 1] aralığına alınır.
    telephony_pcm = apply_telephony_eq_and_downsample_8k(audio)
    telephony = telephony_pcm.astype(np.float32) / 32768.0
    sf.write(audio_dir / f"{case['id']}_48k.wav", audio, 48000)
    sf.write(audio_dir / f"{case['id']}_8k.wav", telephony_pcm, 8000, subtype="PCM_16")

    for channel, wave, rate in (("studio_48k", audio, 48000), ("telephony_8k", telephony, 8000)):
        transcript = await models.transcribe(resample(wave, rate, 16000))
        row["channels"][channel] = evaluate_transcript(case["text"], transcript)
    return row


async def main(args) -> None:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    selected = select_cases(cases, None if args.all else args.per_category)
    audio_dir = report_dir() / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    await asyncio.to_thread(models._load)
    # İlk sentez tembel başlatma içerir; ölçüme girmez.
    await models.synth("Merhaba.")

    rows = []
    for index, case in enumerate(selected, start=1):
        row = await measure_case(case, audio_dir)
        rows.append(row)
        telephone = row["channels"].get("telephony_8k") or {}
        print(
            f"[{index}/{len(selected)}] {case['id']} wer={telephone.get('wer')} "
            f"rtf={row.get('rtf')} f0={row.get('f0_hz')} {row.get('error') or ''}",
            flush=True,
        )

    report = build_report(
        rows,
        load_baseline(),
        provenance={
            "script": "scripts/acoustic_benchmark.py",
            "tts_model": "freyavoice/freya-tts",
            "tts_device": settings.tts_device,
            "tts_path": "models.synth",
            "freya_commit": _vendor_commit(),
            "stt_model": settings.stt_model,
            "stt_device": settings.stt_device,
            "stt_compute_type": settings.stt_compute_type,
            "stt_catalog_hints": False,
            "fixture": FIXTURE.name,
            "selection": "all" if args.all else f"first {args.per_category} per category",
            "lora_adapter": None,
        },
    )
    write_json(report_path(), report)
    if args.save_baseline:
        write_json(baseline_path(), build_baseline(report))

    summary = {key: report[key] for key in ("measured_at", "sample_count", "failed_synthesis", "tts", "f0")}
    summary["channels"] = report["channels"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-category", type=int, default=3, help="Her kategoriden alınacak cümle sayısı")
    parser.add_argument("--all", action="store_true", help="320 cümlenin tamamını ölç")
    parser.add_argument("--save-baseline", action="store_true", help="Sonucu F0 taban kaydı olarak kaydet")
    asyncio.run(main(parser.parse_args()))
