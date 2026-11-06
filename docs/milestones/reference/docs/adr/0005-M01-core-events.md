# ADR-0005: M01 oturum otoritesi ve bounded event-bus

**Karar:** Tek process `asyncio` modüler monolit. M01'de tüm konuşma ve adaptör olayları session-local, 0'dan sıralı `EventEnvelope v1.0` ile taşınır. `SessionManager` per-session lock ve bounded in-memory outbox'ı yönetir. `EventBus` atomik, bounded at-most-once fanout sağlar. `GenerationId` turn'den ayrı artar ve iptal edilmiş TTS çıktılarını reddeder.

**Neden:** Model, UI ve telefon adaptörlerinin tek oturum kimliği ve sıralı olay modeli üzerinde kurulabilmesi. Erken dağıtık broker, bulut altyapısı ve gerçek medya zorunluluğu yok.

**Alternatifler:** Doğrudan handler çağrıları (iç içe event/reentrancy), `asyncio.Queue` sınırsız buffer (RAM riski), Redis/Kafka (erken dağıtık bağımlılık) ertelendi.

**Sınırlamalar:** In-memory outbox olayları süreç kapanınca kaybolur; subprocess sınırı yok; ACK/retry persistence yok. `INTERRUPTING` durumundan geçiş için gerçek medya flush ACK M02'ye bırakılmıştır.

**Geri alma:** M01 EventBus yerine `FakeEventBus` aynı publish arayüzünü uygulayabilir. `SessionManager` dışarıya yalnız DTO ve event v1.0 verir; önceki `Session` mock örnekleri değişmeden korunmuştur.
