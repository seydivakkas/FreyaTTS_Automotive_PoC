# M06 — Audio Queue, Transport Adapters & Codec Contracts

**Sürüm:** 1.0 (mock-only)  
**Önkoşul:** M01–M05 API davranışları değişmeyecek.  
**Kabul kapsamı:** Yalnız sentetik medya **metaverisi**, hafızada sınırlı kuyruk ve sahte adaptör. Gerçek codec, Freya çıkarımı, YouTube sesleri, SIP/PBX bağlantısı, telefon görüşmesi, WAV/MOS/RTF/WER **YOK**.

## Bileşen sınırları

| Port/uygulama | Girdi | Çıktı | Yetki sınırı |
|---|---|---|---|
| `AudioBufferPort` / `MediaBuffer` | `AudioChunkMetadata` | `MediaReceipt` / dequeued metadata | Şifreleme, ses dönüştürme, soket yok |
| `TransportPort` / `FakeTransport` | Metadata, flush request | Fake sent/confirmation | PBX ACK kanıtı değil |
| `MediaCoordinator` | M02 `Effect(FLUSH_MEDIA)` | `FlushRequest`, onaylı `ConversationSignal` | Tek durum otoritesi M01+M02 |
| `AsteriskCommandEncoder` | `FlushRequest` | JSON komut sözlüğü | Yalnız **dry-run**; soket veya komut gönderimi yok |

## Biçimler ve çerçeve kuralları

| Codec | Çözümlenmiş frekans | RTP saat frekansı | 20 ms sample | 20 ms bayt (düz kodlama) | Destek |
|---|---:|---:|---:|---:|---|
| PCM S16LE | 8.000 Hz | 8.000 | 160 | 320 | Metadata, byte uzunluğu hesaplanabilir |
| PCM S16LE | 16.000 Hz | 16.000 | 320 | 640 | Metadata, byte uzunluğu hesaplanabilir |
| PCM S16LE | 48.000 Hz | 48.000 | 960 | 1.920 | Metadata, byte uzunluğu hesaplanabilir |
| G.711 A-law / µ-law | 8.000 Hz | 8.000 | 160 | 160 | Metadata, byte uzunluğu hesaplanabilir |
| G.722 | 16.000 Hz | **8.000** | 320 | Kodlama bağımlı | Yalnız format pazarlığı metaverisi; **paket encoding/decoding yok** |

Her chunk için `sample_count * 1000 == sample_rate_hz * duration_ms` koşulu aranır. Süre 1–2000 ms ve mono format zorunludur. **Baytlar üretilmez, dönüştürülmez veya telemetriye yazılmaz.** G.722 için decoded sample rate ve RTP clock rate ayrı tutulur.

## Kuyruk garantileri

- Oturum/turn/generation/stream bazında sıra numarası `0` ile başlar. Aradaki sıralar (`seq` gap) kabul edilmez; gecikmiş veya çelişkili replay reddedilir. Aynı chunk ikinci kez eklenmez.
- Kapasite hem **chunk sayısı** hem de **toplam süre (ms)** ile sınırlıdır. Dolu kuyruğun kabul etmediği chunk sırası tüketilmez. Her oturumun kuyruğu ayrıdır.
- Enqueue, dequeue ve **transport öncesinde** güncel M01 `SPEAKING/TurnId/GenerationId` ve cancellation token kontrol edilir. İptal sonrası eski ses yeniden canlanmaz.
- XOFF veya fake transport kapasitesi doluyken dequeue yapılmaz. Dequeue ile mock gönderim arasında reddedilirse `return_front` ile chunk'ı geri koymak için çaba gösterilir. Geçersiz nesil canlandırılmaz. Bu işlem gerçek ağdaki paket kaybına dair kesin garanti vermez.
- RAM içi kuyruk, hata sonrası yeniden başlatma ve dağıtık exactly-once garanti etmez. Global oturum sayısı veya toplam RAM sınırı henüz eklenmemiştir. Bunlar üretim kabulü için açık risklerdir.

## `FLUSH_MEDIA` ve ACK bariyeri

1. M02 `vad_speech_started` ile `INTERRUPTING` durumuna geçer, önceki nesli iptal eder ve deterministik `FLUSH_MEDIA` etkisi üretir.
2. M06 etkiden `FlushRequest(flush_request_id=effect.effect_id, SessionId, TurnId, new GenerationId)` oluşturur.
3. `MediaBuffer.begin_flush` **yalnız yerel tamponu siler** ve kuyruk alımını durdurur. `FakeTransport.request_flush` aktarım beklemesi başlatır.
4. Sahte adaptörün *açıkça çağrılan* `confirm_flush` işlemi kendi bekleyen iletisini temizler ve bir `FlushAck` üretir. Bu sadece **fake adapter** doğrulamasıdır; gerçek PBX onayı değildir.
5. `MediaCoordinator.accept_fake_ack` UUID, kimlik, nesil, adaptör kimliği ve adaptör tarafından üretilmiş onay kaydını sınar. Yalnız M02 `Decision.APPLIED` dönerse yerel bariyer açılır. Yanlış sıra/ACK sonrası M02 `INTERRUPTING` durumunda kalır; watchdog `MEDIA_FLUSH_TIMEOUT` için sorumludur.
6. Timeout veya hangup sonrasında `terminate` ile iki yerel kuyruk temizlenir. Söz konusu terminal kapanış **kalıcı audit garantisi değildir**.

### Gerçek Asterisk sürümlerine ilişkin uyarı

Asterisk'in [resmî `chan_websocket` dokümanı](https://docs.asterisk.org/Configuration/Channel-Drivers/WebSocket/) sürüme göre plain-text/JSON kontrol formatlarını, `FLUSH_MEDIA`, `QUEUE_DRAINED`, `MEDIA_XOFF`/`MEDIA_XON` olaylarını tanımlar. **`FLUSH_MEDIA` komutunun websocket'e yazılmış olması flush ACK anlamına gelmez.** Bazı olaylar kuyruk işlem sırasını bildirir; telefondaki kişinin sesi duyması da ayrıca bir iddiadır. M07 veya sonrasındaki gerçek adaptör, hedef Asterisk sürümü üzerinden korelasyon ve durum kanıtını ayrı gerçekleştirmeli; gerçek PBX ACK'i geldiğini varsayan otomatik sahte `MEDIA_FLUSH_ACK` üretmemelidir.

`AsteriskCommandEncoder.flush_json()` yalnız dokümana uyumlu bir komut sözlüğü döndürür. **Soket bağlantısı, kimlik doğrulama, medya aktarımı veya ACK işleme kodu yoktur.** Passthrough codec ve ek çerçevelemeyi açmaz.

## Güvenlik / observability

Olay ve JSON sözleşmeleri yalnız opak ID, codec, örnekleme oranı, `duration_ms`, sıra ve zaman verisi içerir. M04/M05'in kaynak metni, müşteri kimlikleri, ham transkript ve WAV payload'ı dışa aktarılmaz. M01 oturum otoritesi korunur; sahte TTS çıktıları metaveriye çevrilir, modele bağlanmaz.

## Kalan işler (Production readiness: HOLD)

Gerçek codec dönüştürme/sampling, TLS/mTLS ve PBX bağlantıları, ses payload'ları, alt sistemler arası delivery ACK, event/outbox kalıcılığı, sınırlandırılmış oturum yaşam döngüsü, telephony flush kesinliği, operasyonel gözlemlenebilirlik ve gerçek performans/akustik kabul **son faz**.
