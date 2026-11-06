# ADR 0008: Denetlenebilir Türkçe NLP ve onay kapısı

**Durum:** Accepted for synthetic architecture phase.

M01-M03 iş kuralları değişmez. M04, yalnız deterministik TTS hazırlığı ve mock NLU üretir. A01-YT sözlü izin kaydı **telaffuzun onaylandığı anlamına gelmez**; model okunuşu kanıtsız değiştirilemez. Belirsiz yer, araç, fiyat, saat, tarih için **fail-closed** kabul edilir. Ham konuşma içeriği M02 EventEnvelope/audit kayıtlarına konulmaz. Üretim ses testleri final kabul aşamasına bırakılır.
