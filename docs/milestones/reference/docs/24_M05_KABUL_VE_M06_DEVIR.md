# M05 kabul kararı ve M06 devri

## M05 mock kabul

- [x] M01–M04 regresyonları değişmeden geçti.
- [x] `PhraseBoundary`, `ClausePlan`, `Clause`, `TTSInput` immutable.
- [x] Para/tarih/saat/motor/model/ek ve kilometre korumalı spanlar.
- [x] Her clause'a M01 oturum/tur/nesil kimliği iliştirildi.
- [x] M04 `review_required` ses işlem çağrısını bloke ediyor.
- [x] Barge-in ve terminal oturum durumunda stale çıktılar mock kuyruğundan gönderilmiyor.
- [x] Backpressure ve tekrar/çelişkili içerik kontrolü var.
- [x] M02 `START_TTS` + M03 `ReferenceStore` bağlantısı, yetkisiz kaynak referansı reddi.
- [x] 320 text fixture değişmedi; rapor üretildi.
- [x] JSON sözleşme kontrolü ve Windows çalışma betiği mevcut.
- [ ] Gerçek TTS Freya çıkarımı, TTFA/RTF, MOS, WER/CER, SSML/prozodi ve telefon testleri: **BİLEREK SON FAZA BIRAKILDI**.

## M06 — Audio Queue, Transport Adapters & Codec Contracts

Sözleşmeler öncelikle metinsel/mock olacak:

1. `TTSInput` -> sahte `AudioChunkMetadata` portu; hiçbir WAV oluşturulmaz.
2. `MediaBuffer` slotları: sıralama, kapasite, backpressure, format ve nesil ayrımı.
3. `flush_request_id`/`media_flush_ack` bağlantısı M02 sözleşmelerine uyumlu; ACK sahte olsa bile timeout ve yanlış ID reddi.
4. Codec çerçeve sözleşmesi: 8/16/48 kHz, mono, G.711/G.722/PCM tasarım sınırları; gerçek encode/decode son faz.
5. `CancellationController` ve M01 state check, enqueue, dequeue, transport teslim öncesinde tekrar denetlenecek.
6. Test: gecikmiş chunk, eski generation, simüle out-of-order, kapasite, flush-hangup-race, sürümlenmiş payload.
7. Arayüz ve sentetik uçtan uca testler **M06 ve sonraki özelliklerden sonra**, gerçek ses en sonda.

M06 gerçek Asterisk veya Freya bağlantısına izin vermez. Nihai pilot için ayrıca izinli kaynak/gerçek telefon kabul gereklidir.
