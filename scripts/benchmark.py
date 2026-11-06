"""Run real local inference; stores measured values, never synthetic metrics."""

import asyncio
import json
import time
from pathlib import Path
import soundfile as sf
from backend.models import models
from backend.audio import resample, apply_telephony_eq_and_downsample_8k
from backend.text import normalize

SENTENCES = [
    "Volkswagen Passat 1.5 TSI aracınız için sizi arıyorum.",
    "Aracınızın tahmini değeri 1.250.000 TL.",
    "Sizin için yarın saat 14:30'da ekspertiz randevusu oluşturabiliriz.",
    "2023 model Nissan Qashqai 1.5 e-Power aracınızın 145.000 km'deki ekspertiz fiyatı 1.450.000 TL'dir!",
]


async def main():
    out = Path("data/benchmark")
    out.mkdir(parents=True, exist_ok=True)
    await models.load()
    report = {
        "model_load_ms": models.load_ms,
        "device": models.tts.device,
        "measurements": [],
    }
    for i, text in enumerate(SENTENCES):
        for mode in ["first", "warm"]:
            start = time.perf_counter()
            audio = await models.synth(text)
            elapsed = time.perf_counter() - start
            path = out / f"{i + 1}-{mode}.wav"
            sf.write(path, audio, 48000)
            sf.write(
                out / f"{i + 1}-{mode}-8khz.wav",
                apply_telephony_eq_and_downsample_8k(audio),
                8000,
                subtype="PCM_16",
            )
            start = time.perf_counter()
            transcript = await models.transcribe(resample(audio, 48000))
            stt_ms = (time.perf_counter() - start) * 1000
            report["measurements"].append(
                {
                    "input": text,
                    "normalized": normalize(text)["normalized"],
                    "mode": mode,
                    "tts_ms": elapsed * 1000,
                    "audio_seconds": len(audio) / 48000,
                    "rtf": elapsed / (len(audio) / 48000),
                    "stt_ms": stt_ms,
                    "transcript": transcript,
                }
            )
            (out / "results.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
            )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
