# M06 AI Kodlama Ajanı Talimatı

Sen FreyaTTS Otomotiv Asistanı sistem mühendisisin. **Yalnız M05 paketini esas al**; M01–M05 public API'leri ve 320 golden veri dosyasını değiştirme. Hedef: M06 **Audio Queue, Transport Adapters & Codec Contracts**; gerçek ses üretmeden sentetik byte/metadata içeriği ve transport protokolü simülasyonunu kodla.

Önce repo/kabul dosyalarını oku; `src/automotive_voice/audio/` ve `telephony/` sınırlarını çakıştırma. Önce `MediaFormat`, `AudioChunkMetadata`, `AudioBufferPort`, `TransportPort`, `FlushRequest`, `FlushAck` sözleşmelerini oluştur. Güvenilir `session_id/turn_id/generation_id` ve bounded sıra kontrolünü zorunlu tut. Zaman damgaları birimi belirli olsun; `flush_ack` yalnız eşleşen istek ve gerçek adapter onayı alındığında doğrulanabilir sayılmalı (mock testte bir fake ACK yalnız fake kabul). PCM/G.711 örnek uzunlukları ve 8/16/48 kHz mantıksal format sınırlarını denetle.

Özellik ve mimari bitmeden UI başlatma. Ardından UI, sentetik entegrasyon, en son gerçek Freya ve YouTube kayıtları ile fiziksel telefon kabulü. Uydurma ses performansı, WAV/MOS/RTF ölçümü üretme. Testler tam regresyon + yeni yarış/iptal/backpressure senaryolarını kapsasın. Eksik production dayanıklılık açıkça HOLD olsun. Windows PowerShell kontrol betiği ve imzalı/hash'li teslim manifesti oluştur.
