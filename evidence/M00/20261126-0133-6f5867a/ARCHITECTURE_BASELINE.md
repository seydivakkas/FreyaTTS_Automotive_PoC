# Mimari taban

Statik tarama; çalışma ile doğrulanmadı. Taban commit `6f5867a`.

- **Giriş noktası:** `backend/main.py` — FastAPI `app`; `lifespan` içinde `warm_models()` (model ön ısıtma) ve temizlik görevleri. 13 router kaydı: `core_system`, `text_speech`, `operator_qa`, `telephony`, `crm`, `scheduling`, `audio_dsp`, `compliance`, `observability`, `supervisor` (önek `/api/supervisor`, kimlik doğrulamalı), `ontology` (önek `/api/ontology`), `generic_resources`, `dataset`. Toplam 232 HTTP/WS uç (API_INVENTORY.json).
- **Görüşme motoru:** `backend/session.py` (oturum, VAD, söz kesme, yanıt), `backend/dialogue.py` (kural öncelikli diyalog, 1827 satır), `backend/models.py` (Whisper STT, Ollama LLM, FreyaTTS sentez, VAD), `backend/batched_ode.py` (toplu ODE sentez), `backend/dsp.py`, `backend/car_denoiser.py`.
- **Telefoni:** `backend/audiosocket_server.py` (Asterisk AudioSocket), `backend/websocket_adapter.py`, `backend/telephony.py`, `asterisk/` yapılandırması.
- **İkinci yapı:** `automotive_voice/` (M01–M11 entegrasyonu: çekirdek ses/olay türleri, port sözleşmeleri, sözlük, operatör inceleme deposu) ve `contracts/` JSON şemaları. Canlı `backend/` yolu ile kısmen bağlı.
- **Veri:** SQLAlchemy + Alembic (`migrations/`), 34 tablo + ORM'de `caller_profiles`.
- **Ön yüz:** `frontend/` React + Vite; sekmeler `frontend/src/tabs/`, rotalar `frontend/src/ui.ts`; Playwright testi `frontend/tests/ui.spec.ts`.
- **Deneysel:** `experimental/` (33 modül; 8'i canlı koddan içe aktarılıyor olabilir — EXPERIMENT_INVENTORY.json).
- **Başlatma:** `BASLAT.bat`, `BASLAT_HEPSI.bat`, `start.bat` (Windows).
- **Bağımlılıklar:** `pyproject.toml` (Python 3.11; `models` ek grubu torch 2.8.0 cu128, faster-whisper, silero-vad, voxcpm, peft), `uv.lock`, `frontend/package.json`. `python-multipart` tanımlı değil (RISK-0002).
