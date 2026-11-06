# M02 — Conversation State Machine & Barge-in Reducer

## Statü ve amaç

**Uygulandı:** Yalnız Python stdlib ile çalışan deterministik kontrol düzlemi, M01'in mutable session otoritesini koruyan reducer. **Uygulanmadı:** gerçek VAD, STT, LLM, Freya, AudioSocket/WebSocket, PBX buffer flush, medya, gerçek müşteri aramaları ve canlı gecikme ölçümleri.

## Sözleşmeler

- Giriş: `ConversationSignal` (`contracts/conversation_signal.schema.json`). Bütün alanlar sabit ve validated: UUID `event_id`, `SignalKind`, session-local `turn_id`/`generation_id` ve bağımsız session-local input `sequence`, UTC ve process-local `occurred_mono_ns`. `reference`, orijinal müşteri metni değil, yetki kontrollü ayrı depoda tutulan verinin kısa opaque anahtarıdır. `flush_request_id`, yalnız ACK/timeout eventinde bulunur.
- M01'in kendi `EventEnvelope.sequence` sayacı **ayrıdır**; reducer'in input sırası ile eşit olmak zorunda değildir. Bir signal, state değişimi oluşturmayabilir veya atomik ACK+turn halinde iki M01 event'i oluşturabilir.
- Çıkış: `Effect` (`contracts/conversation_effect.schema.json`), `effect_id` UUIDv5 ile `(session,event_id,effect_kind)` üzerinden deterministik oluşur. `REQUEST_LLM`, `START_TTS`, `QUEUE_AUDIO`, `CANCEL_GENERATION`, `FLUSH_MEDIA`, `START_HANDOFF`, `TERMINATE_CALL` komutları yalnızca **niyet bildirir**. Ses veya network I/O yapmaz.
- `ReductionResult`: `applied`, `ignored`, `rejected` ve güvenli neden kodu. `AuditRecord` PII/transkript ve raw ses içermez.

## Konuşma yaşam döngüsü

| Geçerli durum | Giriş | Yeni durum | Olay/etki |
|---|---|---|---|
| IDLE (yok) | `session_opened` | LISTENING | M01 start |
| LISTENING | `vad_speech_started` | LISTENING | VAD aktif; state değişimi gerekmez |
| LISTENING | `transcript_final` | THINKING | M01 begin_turn, REQUEST_LLM |
| THINKING | `llm_response_ready` | SPEAKING | M01 begin_response, START_TTS |
| SPEAKING | `audio_chunk_ready` | SPEAKING | current gen kontrolü, QUEUE_AUDIO |
| SPEAKING | `playout_finished` | LISTENING | M01 finish_playout |
| SPEAKING | `vad_speech_started` | INTERRUPTING | generation invalidation; CANCEL_GENERATION + FLUSH_MEDIA |
| THINKING | `vad_speech_started` | LISTENING | M01 abort_thinking; LLM cancellation |
| INTERRUPTING | `transcript_final` | INTERRUPTING | en fazla 1 opaque transkript tamponlanır |
| INTERRUPTING | eşleşen `media_flush_ack` | LISTENING veya THINKING | atomik ACK; tampon transkript varsa yeni turn + REQUEST_LLM |
| INTERRUPTING | eşleşen `media_flush_timeout` | FAILED | güvenli kapanış + TERMINATE_CALL |
| SPEAKING | `handoff_requested` | INTERRUPTING | flush ACK beklenir, sonra HANDOFF |
| LISTENING/THINKING | `handoff_requested` | HANDOFF | START_HANDOFF, düşünme işi iptal edilir |
| herhangi aktif | `hangup` | ENDED | TERMINATE_CALL, diğer pending komutlar iptal |

`HANDOFF` terminal olmayan özel durumdur; `hangup` veya `fail` ile sonlandırılabilir. `session_opened` ve `hangup` tekrarı yeni etkinlik üretmez. Sinyal callback'i geldi diye M01 kayıtlı task'ın fiziksel olarak durduğu veya PBX tamponunun gerçekten temizlendiği varsayılmaz.

## Barge-in güvenlik değişmezleri

1. `VAD_STARTED` anında `GenerationId` yükselir, eski neslin M01 cancellation token'ı işaretlenir. `CancellationController` görevleri cooperative olarak durdurur, harici medya playback'ini durdurduğu anlamına gelmez.
2. Reducer sırayla `CANCEL_GENERATION` ve `FLUSH_MEDIA` komutlarını çıkarır; flush effect'inin UUID'si ACK eşleşme anahtarıdır. Yanlış ID, yanlış turn/gen veya farklı session ACK'i etkisizdir.
3. **ACK olmadan `INTERRUPTING → LISTENING` geçişi yoktur.** Bekleme sırasında bir güvenli transkript referansı tutulabilir. ACK ve yeni turn / handoff geçişleri tek M01 lock altında atomik commit edilir. M01 outbox doluysa ACK tekrar denenebilir.
4. `poll_flush_timeouts(now_mono_ns)` belirlenen deadline sonrasında sentetik `MEDIA_FLUSH_TIMEOUT` üretir. Arka planda timer yoktur; gerçek adapter/scheduler bunun çağrılmasından sorumlu. Timeout, FAIL + TERMINATE_CALL uygular, konuşmayı gizlice sürdürmez.
5. `HANGUP`/timeout için normal M01 outbox dolarsa özel `emergency_close` güvenli terminal durumu uygulayabilir; **bu yolda M01 event üretilmez**, reducer audit kaydında `emergency_closed_no_m01_event` görünür. Uygulama M09/M10'da kalıcı audit ve outbox gerektirir.
6. M02 pending command kuyruğundan alınan command *teslim edilmiş değildir*. Media adapter, gönderimden hemen önce aktif oturum/generation kontrolü yapmalı, ACK için gerçek medya katmanından doğrulanmış sinyal göndermelidir.

## Olay sıralama ve tekrar kuralı

- Kabul edilen (hatta semantik olarak ignored olan) girişler `expected_input` sırasını tüketir. `sequence_gap`, `monotonic_clock_regression`, `effect_queue_full`, `state_or_outbox_rejected` ise sıra tüketmez; aynı input sırasıyla tekrar denenebilir.
- Tekrarlanan eski sequence `replayed_sequence` olarak kaydedilir, side-effect çıkarmaz; bilinen duplicate UUID yeni sequence ile tekrar gelirse bir slot tüketir ama ikinci effect yaratmaz. Dedup geçmişi bounded RAM'dir ve restart sonrası korunmaz.
- Geç kalan STT/LLM/audio sinyalleri yanlış `turn_id`/`generation_id` yüzünden reddedilir veya yok sayılır. HANGUP, eski nesil callback'leri beklemeksizin sonlandırma önceliğine sahiptir.
- Süre referansı yalnız aynı süreçte anlamlı monotonic saat. Dağıtılmış kaynaklardan gelen zaman damgaları normalize edilip bu sürecin giriş adaptörünce oluşturulmalıdır.

## Sınırlamalar ve sonraki paketler

- M01/M02 **RAM-only**: state, outbox, dedup, audit ve effects işlem yeniden başlatıldığında kaybolur. Exactly-once veya telco ACK garantisi yoktur.
- Reducer'in `drain_effects` metodu bunları caller'a *devreder*; teslimi, kalıcı ACK'i, idempotent transport uygulamasını, gerçek flush gecikmesini garanti etmez. M06/M09/M10'da effect dispatch, retry, persistence, actual transport ACK geliştirilecek.
- `reference` şekil doğrulaması gerçek PII veya güvenli yetkilendirme garantisi değildir. Erişim kontrolü ve şifreli depo daha sonra yapılacak.
- Ayrılmış kaynaklar için bellek / TTL temizleme, process restart replay, watchdog scheduler, cross-process coordination yoktur. Üretim onayı HOLD.
