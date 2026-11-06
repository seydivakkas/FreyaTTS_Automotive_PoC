# M01 doğrulama raporu — 31 Ekim 2026

## Gerçek olarak çalıştırılanlar

- Python 3.13 ortamında, `PYTHONPATH=src python -m unittest discover -s tests -v`: **28 test, 28 PASS**, 0 failure/error, 0 skip.
- `PYTHONPATH=src python -m automotive_voice.m01_demo`: 6 sentetik event üretildi, sequence `[0,1,2,3,4,5]`, kesinti öncesi eski generation kabul, kesinti sonrası ret, final state `ENDED`.
- `contracts/event.schema.json`, `contracts/audio_frame.metadata.schema.json`, `contracts/session_snapshot.schema.json`: Draft 2020-12 şema yapıları ve örnek instance'lar `jsonschema` ile doğrulandı. Bu validator, runtime için zorunlu bağımlılık değildir; standart testler yalnız stdlib kullanır.
- 320 test cümlesi `legacy_320_cases.json` dosyasının kaynağına göre SHA-256 eşleşmesi: `7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e`.

## Doğrulanmayanlar

- Windows / Python 3.11 cihazında çalışma (uyumluluk hedeflenmiştir; bu ortamda Python 3.13 ile sınanmıştır).
- İşlem kesintisinden sonra dayanıklılık/replay, dağıtık çalışanlarda sıralama, medya flush ACK, latency, gerçek TTS/ASR/LLM/SIP, 640 WAV, izinli YouTube sesleri.

**Karar:** M01 in-memory çekirdek ve sözleşme düzeyinde **PASS**, M02 reducer'ın geliştirilmesine geçilebilir. Production/live-call izni değil.
