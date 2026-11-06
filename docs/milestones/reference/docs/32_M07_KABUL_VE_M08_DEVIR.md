# M07 kabul, devir ve üretim sınırı

## Mimari kabul — PASS

- [x] M01–M06 API'leri ve 287 regresyon testi korundu.
- [x] Dört bağımsız sahte adaptör: STT, TTS, LLM, telephony.
- [x] Yaşam döngüsü ve sağlık metaverisi.
- [x] Sanal monoton nanosecond clock, deadline, bounded exponential retry.
- [x] Circuit breaker, fail-closed permanent/timeout, kontrollü reconnect.
- [x] Session/Turn/Generation bazlı iptal, stale callback reddi, idempotency ve seq.
- [x] M05 sahte clause → M07 sahte completion → M06 metadata-only medya kuyruğu.
- [x] FLUSH_MEDIA sonucu M02 `INTERRUPTING` durumunda kalıyor; sahte ACK açıkça istenmeden ilerlemiyor.
- [x] Codec/medya gerçek ses baytları **yok**.
- [x] 320 legacy golden corpus hash korunuyor.
- [x] Windows PowerShell kontrol betiği ve Draft 2020-12 şemaları eklendi.

## Açık işler — HOLD

- [ ] Gerçek Freya/Whisper/LLM/Asterisk bağlantısı.
- [ ] Windows üzerinde fiziksel Python 3.11 çalıştırması.
- [ ] Kalıcı komut kuyruğu, yeniden başlatma ve ağ kesintisi kurtarma.
- [ ] Gerçek PBX flush ACK ve uçtan uca playout doğrulaması.
- [ ] Gerçek audio buffering, codec çözme/kodlama, STT/TTS latency/MOS/WER/CER/RTF.
- [ ] Güvenlik, KVKK, ağ izolasyonu, üretim ölçeğinde stress/load testleri.

## M08'e devir — Local Operator Console & Pronunciation Review UI

Önce **M08 UI**: dört adaptörün sağlık durumunu, Session/Turn/Generation zincirini, transcript yerine opak referansları, sıra/kapasite/timeout/gate durumunu ve FLUSH/ACK ayrımını gösteren çevrimdışı operatör paneli. A01-YT'nin yalnız insan onaylı sözlük kurallarını inceleyen ekran; gerçek ses dinleme veya yeni TTS sesi üretme bu aşamada yok. Kontroller sahte olay üretsin ve kullanıcı tarafından tetiklenebilsin. M08 sonunda sentetik entegrasyon için M09'a devir.
