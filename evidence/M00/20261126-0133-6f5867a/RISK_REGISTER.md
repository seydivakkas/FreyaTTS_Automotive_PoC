# Risk kaydı — M00

Taban commit `6f5867a` · Durum: `CONFIRMED` (kodla veya test çalıştırmasıyla doğrulandı) · `STATIC_CONFIRMED` (kodda görüldü, çalışma ile doğrulanmadı) · `UNRESOLVED`.

## Bilinen bulguların doğrulanması

| Kimlik | Bulgu (plan) | Durum | Kanıt | Devir |
| --- | --- | --- | --- | --- |
| RISK-0001 | X8 — torch olmadan test toplanamıyor | CONFIRMED | `backend/sft_leyla.py:34` ve `backend/gpu_health_circuit_breaker.py:35` modül düzeyinde `import torch`; taban çalıştırmada 43 dosya `ModuleNotFoundError: torch` (BASELINE_TEST_RESULTS) | H01.01 |
| RISK-0002 | **Yeni:** `python-multipart` bağımlılığı tanımlı değil | CONFIRMED | FastAPI form uçları bu paketi ister; `pyproject.toml`/`uv.lock` içinde yok. GitHub CI (çalıştırma 45712813946) 44 dosyada `Form data requires "python-multipart"` ile toplama hatası verdi; CI'nın kırmızı olmasının nedeni bu | H01.01 |
| RISK-0003 | P4/P5 — kimliksiz özel kayıt; arama başında otomatik profil | STATIC_CONFIRMED | `backend/dialogue.py:1363-1370` garanti sorgusu `get_or_create_caller_profile` ile arayan profilinden yanıtlanıyor; `backend/caller_memory.py:50` profil yoksa oluşturuyor | H01.03 |
| RISK-0004 | P7 — çoklu araç randevusu | CONFIRMED | `tests/test_madde3_customer_experience.py::test_multi_vehicle_preplanned_booking` ve `::test_multi_vehicle_sequential_inquiry` başarısız (tanı çalıştırması) | H01.04 |
| RISK-0005 | S1 — paylaşılan Silero durumu | STATIC_CONFIRMED | `backend/session.py:127` `models.vad.reset_states()` tüm oturumların paylaştığı modelde | H01.06 |
| RISK-0006 | S5 — bölüm iptali | STATIC_CONFIRMED | `backend/session.py:361, 514, 650` `self.task.cancel()` | H01.05 |
| RISK-0007 | N3 — seed düşürmeleri | STATIC_CONFIRMED | `backend/batched_ode.py:261` `seed if seed is not None else LEYLA_SEED`, `:385` yedek yolda sabit `LEYLA_SEED`; `backend/models.py:272` `except TypeError` | H01.10 |
| RISK-0008 | R6 — ağ yazma zaman aşımı yok | STATIC_CONFIRMED | `backend/audiosocket_server.py:456` `await writer.drain()` zaman aşımsız | H01.12 |
| RISK-0009 | Ölçülmemiş performans iddiası | STATIC_CONFIRMED | `backend/batched_ode.py:171-172` RTX 4090 / RTF / F0 iddiaları kaynaksız | H01.13 |
| RISK-0010 | UI-2 — arayüzde üretilen başarı cümlesi | STATIC_CONFIRMED | `frontend/src/tabs/VoiceTab.tsx` içinde "başarıyla iletilmiştir" metni | H01.15 |
| RISK-0011 | L5 — tek karakter yanıtı düşürür | UNRESOLVED | `backend/text.py` ve `normalizer_rules.py` içinde `°` için kural bulunmadı; çalışma ile doğrulanmadı | H01.08 |
| RISK-0012 | Karşılamada yapay zekâ bildirimi yok (ADR-X-03) | STATIC_CONFIRMED | `backend/ab_testing.py` `GREETING_TEMPLATES` ve `backend/session.py:193, 231` giden arama metinleri bildirim içermiyor | H01.14 |
| RISK-0013 | ADR-F3-01 için doğum yılı alanı yok | CONFIRMED | DATABASE_INVENTORY: hiçbir tabloda doğum yılı sütunu yok; `caller_profiles.plate` ve `vehicles.plate` var → kararın "kayıtta yoksa plaka son 3–4 hanesi" yolu uygulanır | H01.03 |
| RISK-0014 | `caller_profiles` tablosu göçte yok | STATIC_CONFIRMED | Yalnız ORM modelinde; `migrations/` içinde `create_table` bulunamadı (alembic check bu denetimde çalıştırılmadı) | M07 / F3-A |

## Tanı çalıştırmasındaki diğer başarısız testler (CPU torch + python-multipart ile, 21 başarısız)

| Kimlik | Test | Olası neden (doğrulanmadı) | Devir |
| --- | --- | --- | --- |
| RISK-0015 | `test_sft_leyla.py` (12 test) | Model bağımlılıkları (peft, ağırlıklar) ve donanım gerektiriyor; hermetik değil | H01.01 (işaretleme) / F5-D |
| RISK-0016 | `test_api.py::test_voice_chat_turn_endpoint`, `test_e2e_automotive_cockpit.py::test_tier1_f1_voice_chat_turn_basic_text_reply` | `httpx.ConnectError`: canlı servis (Ollama) gerektiriyor | H01.01 (`llm` işareti / sahte LLM) |
| RISK-0017 | `test_voice_path_honesty.py` (3 test) | `librosa` eksik ve yanıt metni değişmiş (onay kodu eklenmiş) | H01.13 |
| RISK-0018 | `test_session.py::test_handle_text_input_emits_bypassed_and_f3_pipeline_events`, `test_acoustic_evaluation.py::test_measure_f0_detects_pitch_and_silence` | UNRESOLVED | H01.02 karakterizasyon |

## Diğer riskler

- **RISK-0019:** `pyproject.toml` `requires-python = ">=3.11,<3.12"`; kullanıcı ortamı farklı sürümdeyse uv ayrı Python indirir.
- **RISK-0020:** İçe aktarılıp bildirilmemiş paketler (ad eşleşmesiyle): freyatts, playwright, pytesseract, sklearn, xgboost (DEPENDENCIES.json). Bazıları isteğe bağlı yollarda olabilir.
- **RISK-0021:** Sığ klon; commit geçmişi denetlenmedi.
