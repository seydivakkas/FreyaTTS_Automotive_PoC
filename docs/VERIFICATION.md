# Doğrulama kaydı

Durum: PoC. Bu dosya yalnızca ölçülmüş veya komutla yeniden üretilebilir kanıtları içerir. Önceki sürümün (31 Ekim) ölçümleri güncel profille (large-v3-turbo, kural öncelikli diyalog, ön ısıtma) uyuşmadığı için kaldırıldı.

## Doğrulananlar

| Konu | Kanıt | Kaynak |
|---|---|---|
| Otomatik testler | Toplanan test sayısı `pytest --collect-only -q` son satırıdır; geçen sayısı için `pytest -q` çalıştırın | `pyproject.toml` `testpaths` (`tests`, `experimental/tests`) |
| Akustik geri tanıma | 320 örnek, TTS -> 8 kHz telefon bandı -> STT; WER %18,7, CER %7,6, otomotiv terim doğruluğu %48,04; STT large-v3-turbo CUDA float16 | `data/acoustic/latest.json` (ölçüm 2026-11-06), `scripts/acoustic_benchmark.py` |
| Kalite kapısı | WER ve CER eşik içinde (PASS); terim doğruluğu eşiğin (%95) altında (FAIL); ABX ve F0 tabanı ölçülmedi (HOLD); genel durum FAIL | `abc_evaluator.run_benchmark_suite([], acoustic_report=...)` |
| Gerçek model tarayıcı testi | Sanal mikrofon, gerçek modeller; müşteri sesi sentetik TTS sesidir. Ana kabul testi son 6 çalıştırmanın 2'sinde geçti; kısaltılmış araç cümlesiyle 4 çalıştırmanın 4'ünde geçti (araç adımı kararsız) | `docs/measured-latency.json`, `scripts/voice_acceptance.py` |
| Gecikme (tek çalıştırma) | Karşılama ilk sesi ~15 ms (önbellekte), isim turu ~1,4 s, araç turu ~3,2 s, seçim/onay ~3,2 s, LLM gerektiren turlar ~6 s, STT ~0,3-1,5 s | `docs/measured-latency.json` |
| VRAM | Tepe 7478 / 8188 MiB (yaklaşık 1770 MiB masaüstü uygulamaları dahil); P5 ön ısıtmadan önce ölçüldü | `docs/measured-latency.json` |
| Kural öncelikli diyalog, ön ısıtma | Kod ve testlerle doğrulanır | `backend/dialogue.py`, `backend/models.py`, `tests/test_p5_latency.py` |
| Telefon protokolü | AudioSocket paket ayrıştırma ve 8 kHz akışı birim testleriyle sınandı | `tests/test_audiosocket_server.py` |

Gecikme değerleri tek çalıştırma örneğidir: SLA değildir, dağılım değildir. WER/CER ve terim doğruluğu TTS ile STT'nin birleşik sonucudur; hata tek bir modele atfedilemez.

## Doğrulanmayanlar

- İnsan sesiyle uçtan uca görüşme.
- Gerçek Asterisk ve SIP hattı: M11 kayıtlarında kanıt gönderilmemiş kapılar `HOLD` (`data/m11/M11_ACCEPTANCE.json`, `docs/milestones/current-acceptance.json`).
- Gerçek SMS/WhatsApp sağlayıcısı: sağlayıcı sahtedir.
- Gerçek aktarım ve giden arama: AMI istemcisi sahtedir.
- ABX (konuşmacı benzerliği), MOS ve F0 tabanı; ses doğallığı için dinleme kabulü.
- LoRA adaptörü: yoktur.
- LLM gerektiren turlarda 1,2 s ilk ses hedefi: karşılanmıyor (~6 s).
- KVKK maddeleri: hukuki incelemede; saklama süresi yalnızca ses kayıtlarını kapsar.
- P5 ön ısıtma sonrası VRAM ve gecikme yeniden ölçülmedi.

## Tekrarlama

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m scripts.acoustic_benchmark
.venv\Scripts\python -m scripts.voice_acceptance
.venv\Scripts\python scripts\generate_executive_docx.py
```

Akustik ve sesli kabul komutları gerçek modeller ve GPU ister. `generate_executive_docx.py` `tools` ekstrasını gerektirir (`uv sync --frozen --inexact --extra tools`).
