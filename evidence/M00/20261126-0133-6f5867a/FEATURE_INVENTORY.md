# Özellik envanteri

Taban `6f5867a` · 51 kayıt · Statik tarama (AST/regex); çalışma kanıtı değildir.

| Kimlik | Ad | Alan | Durum | Kaynak (ilk) | Test sayısı |
| --- | --- | --- | --- | --- | --- |
| FT-F0-0001 | web mikrofonu/AudioWorklet | F0 | LIVE_PATH | `frontend/src/VoiceWaveformBar.tsx` | 0 |
| FT-F0-0002 | telefon girişi AudioSocket | F0 | LIVE_PATH | `automotive_voice/readiness/contracts.py` | 8 |
| FT-F0-0003 | HPF | F0 | LIVE_PATH | `backend/automotive_frontend.py` | 1 |
| FT-F0-0004 | FFT gürültü bastırma | F0 | LIVE_PATH | `backend/car_denoiser.py` | 1 |
| FT-F0-0005 | AGC | F0 | LIVE_PATH | `backend/car_denoiser.py` | 1 |
| FT-F0-0006 | DTMF | F0 | LIVE_PATH | `backend/audiosocket_server.py` | 7 |
| FT-F0-0007 | yeniden örnekleme | F0 | LIVE_PATH | `backend/audio.py` | 3 |
| FT-F1-0001 | Silero VAD | F1 | LIVE_PATH | `backend/models.py` | 0 |
| FT-F1-0002 | lookback/ön kayıt | F1 | LIVE_PATH | `backend/audiosocket_server.py` | 1 |
| FT-F1-0003 | barge-in | F1 | LIVE_PATH | `automotive_voice/core/session_manager.py` | 10 |
| FT-F1-0004 | backchannel | F1 | LIVE_PATH | `backend/audiosocket_server.py` | 3 |
| FT-F1-0005 | anlamsal tur sonu | F1 | LIVE_PATH | `backend/routers/audio_dsp.py` | 1 |
| FT-F2-0001 | Faster-Whisper | F2 | LIVE_PATH | `automotive_voice/m11/__main__.py` | 0 |
| FT-F2-0002 | hotword | F2 | LIVE_PATH | `backend/config.py` | 4 |
| FT-F2-0003 | no_speech/logprob filtresi | F2 | LIVE_PATH | `backend/models.py` | 1 |
| FT-F2-0004 | ASR mapper | F2 | EXPERIMENTAL | `experimental/asr_mapper.py` | 1 |
| FT-F3-0001 | Supervisor kipleri | F3 | LIVE_PATH | `backend/config.py` | 1 |
| FT-F3-0002 | randevu | F3 | LIVE_PATH | `automotive_voice/dialogue/models.py` | 10 |
| FT-F3-0003 | CRM | F3 | LIVE_PATH | `automotive_voice/adapters/lifecycle/supervisor.py` | 7 |
| FT-F3-0004 | müşteri hafızası | F3 | LIVE_PATH | `backend/caller_memory.py` | 2 |
| FT-F3-0005 | outbox | F3 | LIVE_PATH | `automotive_voice/conversation/reducer.py` | 6 |
| FT-F3-0006 | operatöre aktarım | F3 | LIVE_PATH | `backend/automotive_dispatch.py` | 9 |
| FT-F3-0007 | idempotency | F3 | LIVE_PATH | `automotive_voice/adapters/lifecycle/contracts.py` | 10 |
| FT-F3-0008 | RAG | F3 | LIVE_PATH | `automotive_voice/nlp/a01yt_adapter.py` | 2 |
| FT-F4-0001 | normalizasyon | F4 | LIVE_PATH | `automotive_voice/e2e/runner.py` | 10 |
| FT-F4-0002 | otomotiv sözlüğü | F4 | LIVE_PATH | `automotive_voice/m04_report.py` | 9 |
| FT-F4-0003 | morfoloji | F4 | LIVE_PATH | `backend/automotive_frontend.py` | 2 |
| FT-F4-0004 | G2P | F4 | LIVE_PATH | `frontend/src/AudioPipelineInspector.tsx` | 0 |
| FT-F5-0001 | FreyaTTS/VoxCPM | F5 | LIVE_PATH | `backend/batched_ode.py` | 0 |
| FT-F5-0002 | Leyla seed | F5 | LIVE_PATH | `backend/batched_ode.py` | 7 |
| FT-F5-0003 | ODE çözücü | F5 | LIVE_PATH | `automotive_voice/adapters/fake.py` | 10 |
| FT-F5-0004 | önbellek | F5 | LIVE_PATH | `backend/gpu_health_circuit_breaker.py` | 5 |
| FT-F6-0001 | fade/konfor gürültüsü | F6 | LIVE_PATH | `backend/audio.py` | 8 |
| FT-F6-0002 | WSOLA | F6 | LIVE_PATH | `frontend/src/nav.ts` | 1 |
| FT-F6-0003 | telefon EQ | F6 | LIVE_PATH | `automotive_voice/adapters/lifecycle/supervisor.py` | 8 |
| FT-F6-0004 | tempo/pacing | F6 | LIVE_PATH | `automotive_voice/m11/__main__.py` | 10 |
| FT-F6-0005 | AMI/ARI | F6 | LIVE_PATH | `automotive_voice/e2e/__init__.py` | 10 |
| FT-CORE-0001 | API yüzeyi: backend/main.py | CORE | LIVE_PATH | `backend/main.py` | 0 |
| FT-CORE-0002 | API yüzeyi: backend/ontology/router.py | CORE | LIVE_PATH | `backend/ontology/router.py` | 0 |
| FT-CORE-0003 | API yüzeyi: backend/routers/audio_dsp.py | CORE | LIVE_PATH | `backend/routers/audio_dsp.py` | 0 |
| FT-CORE-0004 | API yüzeyi: backend/routers/compliance.py | CORE | LIVE_PATH | `backend/routers/compliance.py` | 0 |
| FT-CORE-0005 | API yüzeyi: backend/routers/core_system.py | CORE | LIVE_PATH | `backend/routers/core_system.py` | 0 |
| FT-CORE-0006 | API yüzeyi: backend/routers/crm.py | CORE | LIVE_PATH | `backend/routers/crm.py` | 0 |
| FT-CORE-0007 | API yüzeyi: backend/routers/dataset.py | CORE | LIVE_PATH | `backend/routers/dataset.py` | 0 |
| FT-CORE-0008 | API yüzeyi: backend/routers/generic_resources.py | CORE | LIVE_PATH | `backend/routers/generic_resources.py` | 0 |
| FT-CORE-0009 | API yüzeyi: backend/routers/observability.py | CORE | LIVE_PATH | `backend/routers/observability.py` | 0 |
| FT-CORE-0010 | API yüzeyi: backend/routers/operator_qa.py | CORE | LIVE_PATH | `backend/routers/operator_qa.py` | 0 |
| FT-CORE-0011 | API yüzeyi: backend/routers/scheduling.py | CORE | LIVE_PATH | `backend/routers/scheduling.py` | 0 |
| FT-CORE-0012 | API yüzeyi: backend/routers/supervisor.py | CORE | LIVE_PATH | `backend/routers/supervisor.py` | 0 |
| FT-CORE-0013 | API yüzeyi: backend/routers/telephony.py | CORE | LIVE_PATH | `backend/routers/telephony.py` | 0 |
| FT-CORE-0014 | API yüzeyi: backend/routers/text_speech.py | CORE | LIVE_PATH | `backend/routers/text_speech.py` | 0 |
