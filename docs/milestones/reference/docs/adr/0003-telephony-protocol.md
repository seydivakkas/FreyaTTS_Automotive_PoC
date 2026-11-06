# ADR-0003 — Telefon portunu geç bağla
**Durum:** Kabul önerisi
**Karar:** Başlangıçta FakeMediaGateway; gerçek SIP kapısı M11. Asterisk chan_websocket uygun sürümde tercih; JSON control için Asterisk 20.18.0+/22.8.0+/23.2.0+ sürüm doğrulaması gerekli. Alternatif AudioSocket, ayrı pacing sorumluluğu gerektirir. Kontrollü kesmede medya kuyruğu flush. **Dayanak:** https://docs.asterisk.org/Configuration/Channel-Drivers/WebSocket/ . **Risk:** Medya çerçevesi türleri, sürümler ve opüs kodlama farklılıkları. **Karşılık:** Transport `AudioFormat` negotiated metadata ve sürümlenmiş adapter.
