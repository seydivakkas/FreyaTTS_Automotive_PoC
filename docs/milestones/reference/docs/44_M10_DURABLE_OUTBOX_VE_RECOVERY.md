# M10 — Kalıcı Oturum ve Olay Outbox Sözleşmesi

## Hedef ve kapsam

`DurableJournal` ve `DurableSessionManager`, M01 `Session` durum değişikliklerini ve `EventEnvelope` kayıtlarını **aynı SQLite transaction** içerisinde kalıcılaştırır. SQLite WAL, `synchronous=FULL`, `BEGIN IMMEDIATE` ve `UPDATE ...` öncesi sürüm/sayaç denetimi uygulanır. Her oturumda `sequence`, `turn_id` ve `generation_id` tek yönlü ilerler. Bu sürüm **Windows-first yerel geliştirme / dry-run** içindir.

### Depolama şeması

- `sessions(session_id PK, state, turn_id, generation_id, last_sequence, recovery_required)`
- `outbox(session_id, sequence PK-scoped, event_id UNIQUE, envelope JSON, status=pending|acked)`

`DurableSessionManager._apply()` iş olayını önce SQLite'a atomik yazar, yalnızca commit sonrasında RAM durumunu ve M01 iptal denetimini değiştirir. Disk commit başarısızsa RAM durumu değişmez. `complete_interrupt_with_followup` iki olayı tek transaction'da yazar.

### Restart güvenliği

Yeni işlem başlarken **mutlaka** `await manager.restore_fail_closed()` çağrılır. `LISTENING`, `THINKING`, `SPEAKING`, `INTERRUPTING`, `IDLE` ve `HANDOFF` dahil terminalleşmemiş veya dış etkisi belirsiz durumlar otomatik devam ettirilmez. Yeniden başlatmada güvenli `FAILED`/`ENDED` durumuna alınır; `recovery_required` işaretlenir ve ilgili terminal olay kalıcı yazılır. M02'nin RAM içinde tutulan flush bekleyişi, onay ve CRM/rezervasyon etkileri **otomatik replay edilmez**. Gerekirse insan veya dış servisteki aynı idempotency anahtarıyla uzlaştırma gereklidir.

### Olay sevkiyatı

`dispatch_pending()` oturum sıra numarasına göre `EventBus` fanout yapar, sonra SQLite'da ACK işaretler. Kuyruk doluysa olay diskte bekler. İlk teslimat ile disk ACK'i arasındaki çökmede **aynı `event_id` yeniden görülebilir**; bu nedenle tüketici `event_id` ile deduplikasyon yapmalıdır. **Exactly-once garanti edilmez.** Kesinti sonrası yeni `EventBus` imleci önceki kalıcı ACK seviyesinden yüklenir.

### Kapsam dışı / riskler

- M02 `pending_effects`, LLM/STT/TTS işi, telephony transport, sahte PBX ACK'i ve CRM/booking idempotency kayıtları **bu şemada kalıcı değil**.
- SQLite şifreli değildir. Olay payload'ında `transcript`, `phone_number`, `vin`, `audio_bytes` vb. alan adları fail-closed reddedilir. Bu anahtar kontrolü tam KVKK veri sızıntısı önleme sistemi değildir.
- Birden fazla işlem aynı veritabanına yazarsa SQLite CAS çakışmaları güvenli biçimde reddedilir; otomatik lider seçimi veya dağıtık koordinasyon sunulmaz.
- İşlem sırasında yeni sürecin açılamaması, disk doluluğu, fsync başarısızlığı ve üretim işletim sistemi çökme dayanıklılığı fiziki kabulde ölçülecektir.

## Hızlı kullanım

```python
bus = EventBus()
journal = DurableJournal("local/events.sqlite3")
manager = DurableSessionManager(bus, journal)
await manager.restore_fail_closed()
await manager.create("session-1")
await manager.start("session-1")
# reset: new manager + same path -> unfinished session FAILED, no effect replay
```

Veritabanını Git'e eklemeyin; gerçek konuşma ve müşteri bilgisini test kayıtlarına koymayın.
