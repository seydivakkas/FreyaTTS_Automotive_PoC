# M00-G05 / M01 devir eki — gerçek çağrı kenarları

Taban: `6f5867af52dd8d3fd706dc6c9ddd4a42a2dd360f`. Kanıt sınıfı: STATIC_CODE. Orijinal `PIPELINE_TRACE.md` ve kimlikler değiştirilmedi. Bu ek, taban kaynakları üzerinden okunan ana canlı akışların biçim, durum ve iptal sınırlarını gösterir; gerçek model veya PBX çalıştırması değildir.

| Kenar | Girdi → çıktı / durum | Taban kaynak |
| --- | --- | --- |
| Web giriş | `POST /api/session-ticket` → 30 sn bilet; WS /ws/voice el sıkışması PCM s16le, mono, AudioContext örnekleme hızı; Worklet blokları yalnız bufferedAmount <128000 iken gönderilir | frontend/src/useVoiceSession.ts:133–161; backend/main.py:195–261 |
| AudioSocket giriş | TCP reader → UUID 16 bayt el sıkışması → 8 kHz PCM16 payload; IP/kota; lookback, DTMF, 60 sn okuma zaman aşımı; çağrı bağlamı UUID üzerinden | backend/telephony.py:66–68; backend/audiosocket_server.py:390–523 |
| chan_websocket giriş | IP/kota; VoiceSession(channel=asterisk_ws, output_rate=8k); binary payload → PCM; CALL_START/DTMF/HANGUP/MEDIA_FLUSHED metin olayları. Giden arama eşlemesi yok (kaynakta açık eksik) | backend/websocket_adapter.py:334–433 |
| F0 → F1 | VoiceSession.input: 100 ms PCM birikimi; kalibrasyon sırasında taban akışı erken döner (RISK); araç içi DSP; soxr float32 16 kHz; Goertzel DTMF; Endpoint.feed | backend/session.py:280–328; backend/car_denoiser.py:342+ |
| F1 | 512 örnek blok, Silero >0.55; endpoint geçmiş/pre-roll, speech ve silence oturumda; model nesnesi paylaşılır ve yeni oturum resetler (RISK-0005). Endpoint sonuçları numpy float32 dizisi | backend/audio.py:38–68; backend/session.py:127, 328–364 |
| F1 → F2 | Önceki görev tabanda cancel edilir (RISK-0006); yeni bölüm VoiceSession.process(audio,speech_end) | backend/session.py:358–374 |
| F2 | Float32 16 kHz; RMS filtresi; STT lock, Faster-Whisper Türkçe, beam=1, katalog hotwords; no_speech/logprob/compression filtreleri; kabul edilen parçalar tek str. asyncio.shield ile thread işi korunur | backend/models.py:303–348 |
| F2 → F3 | stage2 backchannel kararı: rollback sırasında oynatma sürer; commit'te generation artar, flush; transkript DB ve UI; Supervisor (varsa) veya Dialogue.answer(str) | backend/session.py:366–465 |
| F3 → F4 | Düz metin cevap; text_input F0–F2 bypass; DTMF ayrı yol; supervisor guarded hata güvenli yanıt, Dialogue iş akışına devreder | backend/session.py:433–465,495–581,626–660 |
| F4 | normalize → metin, clauses → (str,pause); prepare_tts_clause; session generation ile kontrol | backend/text.py:67,246,263; backend/session.py:721–763 |
| F4 → F5 | Parça+seed; cache key; batched_ode_engine varsa devre kesici ve mikro-yığın; aksi halde lock, pending sınırı, worker lock, _synth. Taban seed fallback hatası RISK-0007 | backend/models.py:224–301; backend/batched_ode.py |
| F5 → F6 | 48k float32 waveform; parça fade/sessizlik; generation/closed kontrolü; producer queue maxsize=2; iptal ve stale playback engeli | backend/models.py:284–301; backend/session.py:721–838 |
| F6 telefon | 48k → 80 Hz HPF, presence, polyphase 1/6, limiter → little-endian 8k int16; 20 ms/320 bayt frame; AudioSocket paket yazma/drain (tabanda timeout yok); chan_websocket send callback | backend/dsp.py:26–46; backend/audio.py:21–35; backend/session.py:840–861; backend/audiosocket_server.py:452–456 |
| F6 web | 48k → 16k int16 PCM, 640 bayt/20 ms; send_bytes; tarayıcı Int16Array → Float32 AudioBuffer 16k mono, playback queue; pause/resume/flush ve bağlantı hata durumları | backend/session.py:840–887; backend/main.py:221–227; frontend/src/useVoiceSession.ts:237–280 |
| Oturum kapanışı | generation artışı, DTMF/watchdog/task iptali; transport greeting cancel, session.close, active release; taban aralıklı kapanış yarışları ayrı risk olarak izlenir | backend/session.py:892+; backend/main.py:274+; backend/audiosocket_server.py:535+; backend/websocket_adapter.py:439+ |

## Kanonik sözleşme girdileri

C1 ham PCM bytes ve transport sample_rate; C3/C4 endpoint started + ndarray bölümleri; C5 str (segment metadata atılır); C6 Dialogue/Supervisor state; C7 düz answer str; C8 normalize+clause tuple; C9 48k float32 ndarray; C10 PCM16 frame ve pacing; C11 playback event dict ve generation; C13 make_pipeline_event dict. Mevcut adlandırılmış türler için M01_HANDOFF.md korunur.

## Sınırlar ve riskler

- İşleyici → CRM ve Supervisor alt grafiği WORKFLOW_INVENTORY.json ile birleştirilmeli; her yazma/rollback ve API bağının tam doğrulaması açık.
- Deneysel WSOLA, semantic_turn_detector, asr_mapper ile kanonik canlı yol arasındaki tüm bayrak ve geri besleme bağları bu ekte kanıtlanmadı.
- Statik çağrı izi güçlendi, G05 halen HOLD: bütün dinamik/alternatif yollar ve bağımsız inceleme tamamlanmadı. G03/G08 de bu ek ile PASS olmaz.
