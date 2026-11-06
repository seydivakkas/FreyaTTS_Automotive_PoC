# M10 — Güvenlik İncelemesi ve Açık HOLD'lar

**Kabul kapsamı:** SQL transaction bütünlüğü; sequence/turn/generation monotonicity; bekleyen event'lerin restart sonrası durumu; belirsiz iş etkilerinin otomatik yeniden yürütülmemesi; en az bir olay kuyruğu doluluğu ve disk hatası enjeksiyonu; localhost operatör paneli; config allowlist.

**Açık riskler:**

1. **Distributed exactly-once yok.** Bus publish/SQLite ACK aralığında tekrar olay oluşabilir; gerçek müşteri servisine yazma etkileri için ayrı idempotent external outbox şart.
2. **M02 reducer ve M03 booking state yeniden yüklenmez.** Koruyucu yaklaşım unfinished sessions'ı `FAILED` durumuna geçirir; müşteriyle konuşmayı otomatik sürdürmez. External booking varsa teyit için servis üzerinden uzlaştırma gerekir.
3. **DB şifrelenmedi.** Testte yalnızca referans ve teknik event kullanıldı; üretim verisi için işletim sistemi izinleri, disk şifreleme, retention ve KVKK uyumu zorunlu.
4. **Gerçek Freya, STT, LLM ve PBX çalıştırılmadı.** Donanım, gecikme, codec, PBX flush davranışı ve Windows/Python 3.11/Edge kabulü HOLD.
5. **Onaylı A01-YT telaffuz kanıtı 0.** M10 metin formatının düzelmiş olması yabancı marka okunuşunu doğrulamaz.
6. **Sanal saat ve gerçek monoton saat ayrımı** oturum sonlandırma/timeout için uçtan uca gerçek ortamda tekrar ele alınmalıdır.
7. **Operatör paneli tek kullanıcılı localhost aracıdır.** Prod kimlik doğrulaması, RBAC ve güvenli çok kullanıcılı erişim henüz yok.
8. **SQLite dosyası yedekleme, corruption recovery ve çok süreçli liderlik** ölçülmedi.

Karar: **M10 DRY-RUN PASS; PHYSICAL/PRODUCTION ACCEPTANCE HOLD.**
