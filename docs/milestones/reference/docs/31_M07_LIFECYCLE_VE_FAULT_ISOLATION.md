# M07 — Adapter Lifecycle, Fault Isolation & Synthetic Streaming Contracts

**Durum:** Mimari mock kontrol katmanı. `M01–M06` kaynaklarının public API'lerini değiştirmeden eklenmiştir. Ses örneği, WAV, telefon soketi veya gerçek TTS/STT/LLM kullanılmaz.

## 1. Amaç ve sınır

`SyntheticAdapter` tek bir `AdapterKind` (`stt`, `tts`, `llm`, `telephony`) için aynı veri sözleşmesini uygulayan metaveri-odaklı örnek adaptördür. `AdapterSupervisor` dört bağımsız örneği yönetir. Kendi `MockClock` nesnelerini/ortak bir sanal saati kullanabilirler; **gerçek sistem zamanı** burada karar yetkilisi değildir. `M02` durum ve `M03` otomotiv iş kararlarının otoritesi olmaya devam eder.

## 2. Nesneler ve veri sözleşmeleri

| Nesne / modül | Sorumluluk | Değişmez |
|---|---|---|
| `AdapterKind`, `AdapterState` | Dört adaptör ve başlat/durdur/bozulma durumları | `kind` başına bağımsız sağlık |
| `HealthSnapshot` | Hazır/bozuk/devre/kapasite/sanal zaman | `mock_only=true`, ağ sağlığı ölçülmez |
| `LifecyclePort` | `start`, `stop`, `reconnect`, `submit`, `tick`, `health` | I/O adaptörleri sonradan bu sınırı uygular |
| `SyntheticCommand` | `SessionId`, `TurnId`, `GenerationId`, `sequence`, `command_id`, `payload_ref`, `Deadline` | Ham transkript/PII taşımaz |
| `SyntheticResult` | Kod, deneme sayısı ve opsiyonel opak sonuç referansı | ACK veya ses üretimi kanıtı değildir |
| `MockClock` | `now_ns`, `advance(delta_ns)` | İleri giden sanal monoton saat |
| `RetryPolicy` | Bounded üstel backoff | Yalnız `idempotent` işlerde retry |
| `CircuitBreaker` | `CLOSED → OPEN → HALF_OPEN` | Cooldown dolmadan yeni giriş yok; yarı açıkta bir probe |
| `SyntheticStreamBridge` | M05 mock text → M07 fake TTS → M06 `AudioChunkMetadata` | 20 ms **metadata**, ses byte'ı değil |

## 3. Başlatma, durdurma ve devre kesici

```
CREATED --start--> STARTING --> READY
READY --scripted disconnect--> DEGRADED --reconnect--> READY
READY/DEGRADED --stop--> STOPPING --> STOPPED --start--> READY
```

- `start()` ve `stop()` idempotent olarak tanımlanan durumlarda yeniden çağrılabilir. `stop()` bekleyen sentetik işlerini `CANCELLED` yapar.
- İş kabulü yalnız `READY` durumunda; geri dönüşte `AdapterReceipt(accepted, reason, command_id)` verilir.
- `CircuitBreaker` art arda geçici/kalıcı başarısızlıklarda açılır; `HALF_OPEN` yalnız tek probe'a izin verir. Aynı adaptörün zaten gönderilmiş eşzamanlı işleri fail-safe biçimde sonuçlanabilir; breaker önceki çağrıyı geri alamaz.
- Hata enjekte etme (`inject_faults`) testte sıra ile `ok`, `transient`, `permanent`, `disconnect`, `timeout` döndürür. Gerçek ağ hatası değildir.
- `Deadline` mutlak `mono_ns`; `RetryPolicy` `base_delay_ns * 2**(attempt-1)` ve üst sınır ile işler. Deadline, **tamamlanmadan önce** denetlenir.
- Belirsiz sonuçlu, idempotent olmayan telefon işlemleri otomatik tekrar edilmez. Şu anki sahte `telephony` adaptöründen gelen `OK`, ağ/telefon teslim garantisi değildir.

## 4. İş yaşam döngüsü ve atomiklik

1. `submit()` canlı M01 neslini ve beklenen adaptör/oturum sıra numarasını doğrular.
2. Kapasite sınırı ve opak `command_id` replay kontrolünden geçer.
3. `tick()` bekleyen işi başlatabilir; ilk gerçek ilerleme yalnız sanal saat artırıldığında gözlenir.
4. Her tamamlanmada M01 `generation_id` **yeniden doğrulanır**. `barge-in`, `end`, `handoff` sonrası eski callbacks `STALE`/`CANCELLED` olur.
5. Geçici hata `RetryPolicy` ve circuit breaker'a tabidir. Başka adaptörlerin işi etkilenmez.
6. `command_id` tekrarları birebir eşleşiyorsa `duplicate_ignored`, farklıysa `conflicting_replay` olur. `replay_limit` aşılınca kayıt unutulabilir; kalıcı idempotency garantisi **yoktur**.

**Sıra otoritesi:** Aynı adaptörün tüm göndericileri `SyntheticAdapter.expected_sequence(session_id)` üzerinden beklenen değeri alır. `submit()` içinde tutarlı sıra tek bir async kilitle korunur. Ayrı göndericilerin yarışında yanlış sıra otomatik başarı sayılmaz; yeniden doğrulanıp denenmelidir.

## 5. M02 ve M06 ile köprü

- `EffectKind.REQUEST_LLM` → sahte LLM; `START_TTS` → sahte TTS; `QUEUE_AUDIO` → sahte telephony kontrol isteği (ses gönderilmez).
- `CANCEL_GENERATION` → adaptörlerde oturumun bekleyen görevleri durdurulur.
- `FLUSH_MEDIA` → adaptörlerin işleri iptal edilir, `M06.MediaCoordinator.request_flush(effect)` yerel tamponu bloke eder ve `FakeTransport` üzerinde bekleyen flush yaratır. **Asla otomatik ACK üretilmez.**
- Sadece dışarıdan açık çağrılmış `FakeTransport.confirm_flush()` ardından `MediaCoordinator.accept_fake_ack()` ile `M02` ilerler. Bu adım gerçek PBX kanıtı değildir.
- `TERMINATE_CALL` → ilgili oturumun sahte işleri ve M06 yerel kuyruk/transport'u sonlanır.

### Metadata akışı

```
M05 ClausePlan
  -> M05 MockTTS.pop_next() [review_required engellenir]
  -> M07 SyntheticStreamBridge -> SyntheticAdapter(TTS)
  -> MockClock.tick -> SyntheticResult(OK)
  -> M01 token tekrar doğrula
  -> M06 AudioChunkMetadata (PCM_S16LE 16 kHz, 20 ms, 320 samples)
  -> M06 MediaBuffer -> FakeTransport
```

Buradaki 20 ms **gerçek ses süresi/performansı değil**, codec kontrolünün kabul ettiği sentetik süre metaverisidir. Gerçek Freya, medya format dönüşümü veya ses byte'ı üretilmez.

## 6. Bilinen sınırlamalar

- RAM süreç kapanınca kaybolur. Kalıcı komut kuyruğu, durable outbox, iş kurtarma, dağıtık idempotency yapılmadı.
- `max_pending` ve `max_inflight` adaptör başına sınırlı; global bellek sınırı, hız limiti, tenant quota ve servis koruması henüz yok.
- `last_sequence` ve bazı diagnostic/fault-script sözlükleri oturum kapatma/TTL olmadan büyüyebilir; gerçek üretim sürümünde yaşam döngüsüne bağlı süpürme gerekli.
- `stop` sentetik adaptör işlerini durdurur; gerçek PBX medya oynatmasını kesme garantisi vermez.
- Dış servis hata ayıklama, network retry, TLS, gerçek codec, ASR/LLM doğruluğu, yerel GPU, Windows/Python 3.11, gerçek telefon hepsi **HOLD**.

**Kabul:** `M07 MOCK ADAPTER PASS / PRODUCTION HOLD / REAL AUDIO HOLD`.
