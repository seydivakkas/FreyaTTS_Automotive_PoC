# M01 — Sistem Çekirdeği ve Olay Sözleşmeleri (uygulanmış tasarım)

**Durum:** 2026-10-31 tarihli yerel mock/stdlib sözleşmesi. *Gerçek ses, Freya inference, VAD/STT, CRM veya Asterisk çalıştırılmadı.*

## 1. Seçilen uygulama semantiği

- **İşlem modeli:** Tek Python sürecinde `asyncio` ile çalışan, **in-memory modüler monolit**. `SessionManager` her oturum için ayrı `asyncio.Lock` kullanır; farklı oturumlar eşzamanlı ilerleyebilir. Birden çok süreç ya da sunucu arasında koordine edilemez.
- **Otorite:** `SessionManager` tek yetkili oturum yazıcısıdır. `Session` önceki çekirdekten korunur; yeni kod doğrudan `Session` nesnesini dışarı vermez. `SessionSnapshot` salt okunur/immutable DTO'dur.
- **Olay:** `EventEnvelope` `schema_version=1.0` ile sürümlüdür; `event_id` UUID, `session_id` güvenli ASCII, `turn_id` ve `generation_id` session-local **0 tabanlı** tamsayılardır. `sequence` **oturum içinde** 0'dan itibaren kesintisiz artar. Zaman UTC ve monotonic(ns) olarak tutulur. Monotonic saat **yalnız aynı süreç içinde** anlamlıdır.
- **Yeni turn:** `begin_turn()` yalnız `LISTENING` durumunda kabul edilir; hem turn hem generation artar. Aynı tur içinde `interrupt()` sadece generation'ı artırarak eski üretimi geçersizleştirir. `end()` tekrar çağrıldığında değişiklik/ikinci event üretmez.
- **İptal:** `CancellationController` eski token'ı işaretler, kaydedilmiş `asyncio.Task`'lara `cancel()` iletir. Harici GPU, PBX veya ağ iptali **garanti edilmez**; adaptörler ayrıca flush/ack gerçekleştirmelidir. Eski nesil chunk `SessionManager.accepts_chunk(session, generation)` ile reddedilir.
- **AudioFormat:** Yalnız explicit mono `8000/16000/48000 Hz` ve `pcm_s16le (16-bit)`, `float32 (32-bit)`, `alaw/mulaw (8-bit, yalnız 8 kHz)` kabul edilir; **örtük codec/resampling yoktur**. `AudioFrame` (ikili yük) numune sayısı × byte/sample uzunluğunu kontrol eder. JSON şeması yalnız **metadata** içindir; ham ses payload'ı JSON'a gömülmez.

## 2. EventBus teslim garantileri

`EventBus` adlandırılmış, kapasitesi sınırlı dinleyici kuyruklarından oluşur. `publish()` tek kilit altında tüm abonelerin kapasitesini kontrol eder. **Bir abonede yer yoksa hiçbiri olayı almaz**, `EventBusFull` yükselir. `EventOrderingError` ile session içi boşluklu/tekrarlı sıra reddedilir. Başarılı çağrı `Subscription` kuyruklarına **bir kez** ekler, fakat tüketicinin işlendiğine dair ack yoktur. Dinleyiciler event'leri kuyruktan kendileri çeker.

Bu yüzden **in-process at-most-once fanout**, **durable exactly-once** değil. Kapanışta/disconnect'te kuyruklar kaybolabilir. `unsubscribe()` sırasında halihazırda `get()` bekleyen görev otomatik uyandırılmaz; tüketicinin kendi cancellation/timeout kontrolünü kullanması gerekir.

### Outbox ilkesi

`SessionManager` değişimi doğrular, yeni `Session` kopyasını commit eder ve event'i session-local **bounded outbox** içine yazar. `dispatch_pending()` olayları sıra ile EventBus'a aktarır. `EventBusFull` çıkarsa gönderilmemiş olay **outbox'ta kalır**, tekrar denenebilir. Önceden başarıyla gönderilenler çıkartılmış olur. Outbox doluysa yeni geçiş reddedilir **ve önceki state değişmez**. EventBus'a abone olunmamışsa gönderim sessizce tüketilir; üretimde kalıcı audit subscriber veya DB-backed outbox M10 öncesinde gerekecektir.

**Dayanıklılık sınırı:** Bu outbox RAM'dedir. Süreç kapanınca kaybolur; iş-kritik olaylar için M09–M10 aşamasında SQLite/PostgreSQL transaction outbox, yeniden başlatma replay ve consumer ACK tasarımı gereklidir. Bu davranışı production garantisi gibi göstermeyin.

## 3. Sözleşme tablosu

| Bileşen | Birincil API | Başarılı sonuç | Hata/invariant |
|---|---|---|---|
| `SessionId` | `SessionId(value)`/`.new()` | 1–128 ASCII id | Boş/geçersiz karakter reddi |
| `TurnId`, `GenerationId` | `TurnId(int)`, `GenerationId(int)` | 0..2^63−1 | bool/negatif/float reddi |
| `AudioFormat` | `AudioFormat(rate,channels,width,encoding)` | Immutable format | Rate/encoding mismatch reddi |
| `AudioFrame` | `AudioFrame(..., sample_count, payload)` | Immutable frame | PCM/codec boyut uyuşmazlığı reddi |
| `EventEnvelope` | `.create()`/`.to_dict()`/`.from_dict()` | Sürüm ve UTC kontrollü olay | Unknown field, NaN, invalid UUID reddi |
| `EventBus` | `subscribe`, `publish`, `unsubscribe`, `close` | Sıralı bounded fanout | Dolu, sırasız, kapalı event bus reddi |
| `SessionManager` | `create`, `start`, `begin_turn`, `begin_response`, `interrupt`, `complete_interrupt`, `finish_playout`, `end`, `snapshot` | İzole session snapshot + outbox event | Yanlış state / outbox-full geri dönüş |
| `CancellationController` | `.token_for`, `.advance`, `.cancel_current` | Generation-scoped token | Eski generation reddi + task iptal sinyali |

## 4. Örnek olay sözleşmesi

```json
{
  "schema_version": "1.0",
  "event_id": "b94c5e7c-c77a-4bc9-80de-7a05f6951b4e",
  "event_type": "interrupted",
  "session_id": "demo-1",
  "turn_id": 1,
  "generation_id": 2,
  "sequence": 3,
  "occurred_at_utc": "2026-10-31T13:45:00Z",
  "occurred_mono_ns": 11111100000,
  "payload": {"reason": "barge_in", "to": "INTERRUPTING"}
}
```

Bu örnek sentetiktir, hiçbir gerçek müşteriye/çağrıya ait değildir. `contracts/event.schema.json`, `contracts/session_snapshot.schema.json`, `contracts/audio_frame.metadata.schema.json` API şekilleridir; runtime doğrulama stdlib Python invariant'ları ile yapılır. Tam JSON Schema 2020-12 dış validator çalıştırması henüz bu paketin kapsamına girmez.

## 5. Eşzamanlılık, güvenlik ve gerçek sağlayıcı sınırları

- Olay payload'ı derin kopyalanarak dondurulur; bir tüketici başka tüketicinin datasını değiştiremez.
- İstisna oluşan geçiş `last_sequence`, outbox veya `generation_id` artırmaz.
- `CancellationController`'ın public metotları doğrudan çok iş parçacıklı kullanım için güvenli değildir; `SessionManager` per-session lock altında çağırır.
- `SessionManager.register_task()` sadece **aktif generation** için izin verir; yanlış generation otomatik reddedilir. Üretim adaptörü görev hayat döngüsü M07'de tamamlanır.
- M01 olayları müşteri telefon numarası, konuşma metni, fiyat ve PII gibi hassas payload'ları **kabul etmemelidir**; M02 güvenli event taxonomy, M08/09 redact/logging stratejisini tamamlamalıdır. JSON serileştirilebilir olmak verinin KVKK açısından güvenli olduğu anlamına gelmez.
- Henüz UI, FastAPI REST/WS, FreyaTTS ve gerçek Asterisk yoktur.

## 6. M02 için sabitlenecek geçiş kuralları

`IDLE → LISTENING → THINKING → SPEAKING`, `SPEAKING → INTERRUPTING → LISTENING`, `SPEAKING → LISTENING` ve terminal `ENDED`. M02 bunları **olay kaynaklı konuşma durumu makinesine** dönüştürecek; `VAD speech-start`, `ASR final`, `LLM started`, `media flush ack`, `hangup`, `handoff` koşullarını ayıracak. Özellikle `INTERRUPTING → LISTENING`, bir codec/telefon buffer flush sinyali **doğrulanınca** gerçekleşmelidir. M01 `complete_interrupt()` metodunu içerir ama bu ACK'i kendi başına kontrol etmez.
