# M09 Kabul / M10 Devir

## Kabul sınırı

- [x] Önceki M01–M08 otomatik regresyonlar çalıştırıldı.
- [x] M03/M04/M05/M06/M07 gerçek Python sözleşmeleri bir M01/M02 oturum otoritesine bağlandı.
- [x] Randevu müsaitlik/iki aşamalı onay, ret, belirsiz sonuç, yinelenen talep ve fiyat geçerlilik testleri.
- [x] NLU temsilciye yönlendirme, CRM kaydı, kimlik/yetki sınırı.
- [x] Barge-in, bekleyen flush ACK, yanlış ACK, timeout, eski nesil, XOFF/XON, hangup.
- [x] Sanal saat ve retry, arıza izolasyonu, çoklu oturum.
- [x] M08 senaryo paneli: read-model, allowlist ve CSRF/Host sınırları.
- [x] M09 sonucu JSON sözleşmesi ve 320 golden SHA bütünlüğü.
- [ ] Her M03 iş yanıtı M04/M05 tarafından `READY` kabul edilmiyor. Tarih/saatlerin ISO biçimi, fiyat suffixleri ve kanıtsız özel isimler inceleme kapısına takılabilir. **Gerçek konuşma hazır kabulü BLOCKED**.
- [ ] Kalıcı outbox/audit, restart recovery, dağıtık idempotency, replay dayanıklılığı.
- [ ] Windows/Python 3.11/Edge fiziksel kurulum doğrulaması.
- [ ] Gerçek Freya, STT, PBX, codec ve YouTube ses referansları — **son aşamada M11**.

## M10 önerisi — Real Adapter Readiness & Resilience Contracts (DRY RUN)

M09 UI/özellik aşaması bitti. M10'da gerçek sistemleri açmadan, bağlantı sağlayıcılarının değiştirilebilir portlarını, konfigürasyon/doğrulama ve gizli bilgi yönetimini, startup/shutdown sırasını, kalıcı outbox ve restart recovery tasarımını, PBX sürüm yetenek matrisini, resampling/codec servis sınırlarını tasarlayıp sahte adapterlarla doğrula. Gerçek mikrofon, WAN, GPU, model veya santral testi M11'e kadar kapalı kalmalı.

M09, **sentetik davranış testi PASS; sesli çıktı hazır olma kapısı HOLD; production readiness HOLD** olarak değerlendirilmelidir.
