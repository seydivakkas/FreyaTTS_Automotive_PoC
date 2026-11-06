# M06 Kabul ve M07 Devri

## Gerçekleşen kabul kriterleri

- [x] M01–M05 mevcut sözleşmeler ve 237 regresyon testi korundu.
- [x] `MediaFormat`, `AudioChunkMetadata`, `FlushRequest`, `FlushAck`, `AudioBufferPort`, `TransportPort` tanımlı.
- [x] 8/16/48 kHz PCM, 8 kHz G.711 ve 16 kHz decoded/8 kHz RTP G.722 **metaveri** sınırları tanımlı.
- [x] Sıralama, replay, stream/nesil ayrımı, per-session kapasite ve süre limiti, XOFF ve yerel buffer flush test edildi.
- [x] Sahte adaptör tarafından gerçekten üretilmemiş ACK reddedildi; ACK olmadan M02 state `INTERRUPTING` kalıyor.
- [x] Hangup, timeout, eski generation, deferred transcript, concurrency yarışları sentetik kontrol edildi.
- [x] 320 golden cümle SHA-256 değişmedi. M05 raporunun metinsel sonuçları korundu.
- [x] Beş yeni JSON Schema, Windows test betiği ve örnek çalıştırma dosyası eklendi.
- [ ] Windows/Python 3.11 **fiilen çalıştırılmadı** (Linux/Python 3.13 doğrulaması).
- [ ] Gerçek Freya, Whisper, GPU, RTP/telefon, YouTube kaydı veya kalite testi **yapılmadı**.

**Karar: M06 MOCK CORE PASS / PRODUCTION HOLD**. Fake ACK, PBX ACK değildir. RAM outbox kalıcı değildir. Ağ üstünde kesintisiz teslim garantisi yoktur.

## M07 önerisi — Adapter Lifecycle, Fault Isolation & Synthetic Streaming

Önce yeni M06 portları üzerinden `FakeSTT`, `FakeTTS`, `FakeLLM`, `FakeTelephony` adaptörleri için yaşam döngüsü, timeout, retry, healthcheck, bounded concurrency, cancellation propagasyonu ve sentetik stream akışını oluştur. M02 tek durum otoritesi, M03 CRM karar otoritesi, M04 telaffuz kanıt kapısı ve M05 text clause planlayıcısı değişmemeli. M06 gerçek codec/wav/sip bağlantısı **son aşamada**. Sonrasında UI, sentetik uçtan uca testler ve en son gerçek ses/telefon kabul.
