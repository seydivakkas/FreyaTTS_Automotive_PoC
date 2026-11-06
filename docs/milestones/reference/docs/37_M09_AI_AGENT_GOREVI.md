# M09 AI Coding Agent Prompt — Deterministic Synthetic End-to-End Integration

M08 ZIP'ini tek ana kod tabanı olarak kullan. M01–M08 davranışlarını ve `data/fixtures/legacy_320_cases.json` SHA-256'sını değiştirme. Dış ağ, model, gerçek ses, SIP, CRM prod erişimi yasak.

1. Simülasyon harness'ı kur: M02 state machine → M03 domain policy → M04 NLP → M05 clause plan → M07 fake TTS/LLM/STT adapters → M06 media metadata → fake PBX ACK → M08 read-model.
2. Test fixtures: ekspertiz onayı, müşteri reddi, tekrarlı rezervasyon, belirsiz sonuç, fiyat geçersizliği, insan devri, barge-in ve flush timeout, XOFF, gecikmiş nesil, supervisor degrade/recovery, çoklu oturum izolasyonu.
3. Testte M02 `FLUSH_MEDIA` için kendiliğinden ACK oluşturma. `FakeTransport.confirm_flush` ayrı, açık işlem olmalı. Timeout olduğunda güvenli terminal state.
4. Synthetic `MockClock` ve deterministik fake adapter'ları kullan; fiziksel gecikme/RTF/MOS uydurma.
5. UI'de test senaryoları için ayrı, denetlenebilir kontrol ve raporlar ekle; ancak arayüzü bozma.
6. Testlerin tamamını, JSON Schema doğrulamasını, eksik/yanlış sinyalleri ve Golden SHA kontrolünü çalıştır.
7. `M09_ACCEPTANCE_REPORT.md` ve bir sonraki aşamaya devir dökümanı ekle.
8. Windows-first ve offline-first; gerçek Freya sesi, gerçek YouTube sesleri, gerçek Asterisk, GPU ve telefon M11 HOLD.
