# M03 — Otomotiv Diyalog Politikası: AI Agent Görevi

**Başlamadan:** `README.md`, `docs/07_M01_SOZLESMELER.md`, `docs/11_M02_SOZLESME_VE_DURUM_MAKINESI.md`, `docs/12_M02_KABUL_VE_M03_DEVIR.md`, `src/automotive_voice/conversation/*`, `src/automotive_voice/core/*` ve `tests/test_m02.py` dosyalarını oku.

**Kural:** M01 ve M02 public API'lerini kırma. `tests/test_core.py`, `tests/test_m01.py`, `tests/test_m02.py` yeşil kalmalı. Ses testleri, YouTube medya, Freya inference, gerçek SIP ve ses dinlemeyi başlatma.

**Uygula:** Yeni `DialoguePolicy` iş kuralları ile `BookingStateMachine`; CRM/ekspertiz için mock tool portları; `AVAILABLE/UNAVAILABLE/UNKNOWN/CONFIRMED` ayrımı; idempotent rezervasyon anahtarı; opt-in / KVKK bayrakları; güvenli fallback, handoff; kontrol edilmiş otomotiv terminolojisi ve niteliksiz fiyat üretimini engelleyen testler. LLM yalnız söylem üretsin, iş-kritik kararı kurallı politika versin. `transcript_ref` and `response_ref` referans verilerini mock secure store'da tut; audit'e ham metin yazma. M02'ye `LLM_RESPONSE_READY` olayını yalnız güncel turn/generation ile gönder. Önce özellikler, sonra kullanıcı arayüzü, daha sonra sentetik uçtan uca test, en son gerçek ses.

**Kanıt:** Unit testler, deterministik dialog fixtures, security negative cases, schema validation, ve M04 devir kararı olmadan tamamlandı deme.
