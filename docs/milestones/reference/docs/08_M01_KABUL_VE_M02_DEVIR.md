# M01 Teknik Kabul / M02 Devir Dosyası

## Kapsam kapısı

- [x] M00 master paketi baz alındı; mevcut 320 test metni aynı biçimde korundu.
- [x] Tek süreç, Python >=3.11, stdlib-only çekirdek.
- [x] `SessionManager`: per-session locks, immutable snapshot, state validation, idempotent `end`.
- [x] `EventBus`: in-process sıralı teslim, bounded fanout, atomik backpressure, replay edilmemiş event reddi.
- [x] `TurnId/GenerationId` ve `EventEnvelope v1.0` uygulanmış tipler.
- [x] `CancellationController`: etkin nesil, eski neslin reddi, async görev iptali.
- [x] `AudioFormat/AudioFrame`: açık format ve binary length denetimi.
- [x] Durum hatası sırasında değişiklik olmaması, outbox dolması, eşzamanlı tur başlatma, çoklu session, fake barge-in testleri.
- [x] Windows yerel çalıştırma talimatı ve sentetik demo.
- [ ] Tam JSON Schema validator ile dış doğrulama / kalıcı outbox / consumer-ack / gerçek media flush: **M02 ve sonraki iş paketlerine bırakıldı.**
- [ ] UI ve model adapterleri: **M07–M10**.
- [ ] Gerçek ses, YouTube klibi, GPU, Asterisk, çağrı, MOS/WER/CER: **M11**.

## M02 geliştirme görevleri (M01 arayüzlerini kırmadan)

1. `DialogueEvent` / `MediaEvent` taksonomisi ve reducer: dış olayları doğrula, belirsiz state geçişini kabul etme.
2. `barge_in` transaction: VAD event → generation invalidation → synth task cancellation → output flush → flush ACK → listening.
3. `transcript_final` ile yeni tur, `assistant_response_started` ile speak ve `playout_finished` ile listen bağları.
4. Hangup/handoff/timeout, late event ve duplicated event deterministik senaryoları.
5. EventBus outbox dispatch ekranda `pending`, `published`, `rejected` olarak görünür; M08 UI bunun üzerine kurulur.
6. Fake STT/TTS/transport ile tüm branch'ler için test. Yalnız en son M11 gerçek medya.

**Risk:** Mevcut event bus RAM içi, worker ve restart dayanıklılığı yok; pilot öncesinde iş-kritik veriler için durable outbox stratejisi gerekir. Gerçek zamanda barge-in p95 hedefi M11'e kadar doğrulanamaz.
