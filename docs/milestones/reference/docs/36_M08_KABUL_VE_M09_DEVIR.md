# M08 kabul ve M09 devir

## M08 kabul kapıları

- [x] Önceki M01–M07 testleri değişmeden korunmalı.
- [x] Dış bağımlılığı olmayan tarayıcı arayüzü, aynı-origin API, statik dosyalar.
- [x] Tek oturum otoritesi M01/M02; operatör UI alternatif state store oluşturmamalı.
- [x] Sağlık M07 `HealthSnapshot.safe_metadata` üzerinden.
- [x] M06 flush ACK yalnızca `FakeTransport.confirm_flush` sonucunda.
- [x] Yanlış sinyal sırası, terminal oturum, flush timeout olumsuz senaryoları.
- [x] `Host`, `Origin`, CSRF ve tarayıcı CSP güvenlik sınırları.
- [x] A01-YT `mode=ro`, overlay inceleme auditi; onaysız okunuş uygulanmamalı.
- [x] 320 golden fikstürün hash ve içerik bütünlüğü.
- [x] Windows için başlatma/check `.ps1` betikleri ve belgeler.
- [ ] Windows/Python 3.11/Edge fiilen çalıştırma (HOLD).
- [ ] Gerçek Freya, YouTube ses klipleri, gerçek telefon, PBX ACK ve kalite değerlendirmesi (M11 HOLD).

## M09 — Synthetic End-to-End Integration (henüz uygulanmadı)

M09 girdisi olarak M08 servisinin `api/snapshot` metaveri görünümü, `api/action` kontrollü senaryoları, review overlay ve M01–M07 portlarını kullan. Senaryolar için sabit fixture'lar kullan; her sonuç terminal state, generation monotonicity, no stale output, fake ACK ordering, CRM idempotency ve replay etkisizliği kontrollerini kapsasın. Olayların RAM içi kayıtta kaybolduğunu ve yeniden başlatmada kurtarma garantisi olmadığını ayrı göstergede tut.

Öncelik: M08 UI kabul → M09 deterministik sentetik uçtan uca test → M10 gerçek adaptör hazırlığı (çalıştırılmadan) → M11 en son gerçek ses ve telefon kabulü.
