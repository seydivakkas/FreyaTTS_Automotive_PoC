# M08 doğrulama raporu — 31 Ekim 2026

## Yapılan gerçek kontroller

| Kontrol | Sonuç | Not |
|---|---|---|
| M01–M07 regresyonu | PASS, 332/332 | Eski 60 Python kaynak modülü byte-for-byte aynı |
| M08 yeni otomatik testler | PASS, 30/30 | Yönetim, HTTP, güvenlik, evidence gate |
| Genel test toplamı | PASS, 362/362 | Linux / Python 3.13 |
| Sürüm JSON sözleşmeleri | PASS, 28/28 | Draft 2020-12 yapısal denetim |
| 320 golden text SHA-256 | PASS | `7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e` |
| API / statik dosya HTTP | PASS | localhost HTTP 200, CSP, nosniff |
| POST CSRF / Origin / Host negatifleri | PASS | 403, 422 / kapalı sınırlar |
| Barge-in, açık fake ACK, timeout | PASS | `INTERRUPTING` -> `LISTENING` ya da timeout -> `FAILED` |
| 3 A01-YT kaynak envanteri | PASS | Kaynak başlıkları ve sözlü izin beyanı; ses yok |
| Read-only A01-YT source / review overlay | PASS | Kaynak anotasyon tablosu mutasyonsuz |
| WAV kanıtı, hash, yol güvenliği | PASS | Yalnızca sentetik test WAV fikstürü; gerçekte 0 klip |
| 320 vakalık UI önizleme | PASS | Mock JSON kullanılarak Chromium DOM/CSS ekran testi |
| ZIP temiz klasöre çıkarma / test | Paketleme sonrasında | Derlemenin bir parçası |
| Windows 3.11 / Edge fiziksel kabul | HOLD | Çalıştırılmadı |
| Gerçek ses / PBX / YouTube kaydı | HOLD | M11'e ertelendi |

## Gerçekte oluşan iz

- 1 sentetik oturum oluşturuldu; `THINKING`, `SPEAKING`, `INTERRUPTING` ve sahte ACK ile `LISTENING` kontrol edildi.
- Adaptör health M07'dendir ve `mock_only=true`.
- Sözlüğe yeni gerçek telaffuz eklenmedi. 0 klip / 0 onay korunuyor.
- 320 metin vakası sadece daha önce hesaplanmış M04 golden raporunun **görüntülenmesidir**: 163 dönüşüm, 29 review, bunun içinde 16 karakter uyumsuzluğu.
- Yeni ses üretimi sıfır; RTF, MOS, WER, CER veya üretim gecikmesi hakkında ölçüm iddiası yoktur.

## Teknik borç ve üretim HOLD

Operatör erişim kimliği, rol yönetimi, TLS, veri koruma, kalıcı olay günlüğü ve crash recovery yok. Sadece localhost üzerinde güvenilir tek geliştirici prototipi. Gerçek tarayıcı ile localhost otomasyon erişimi bu çalışma ortamında kısıtlandığı için UI görüntüleri bağımlılığı olmayan DOM içine mock JSON enjekte edilerek alındı; localhost HTTP endpoint'leri ayrıca gerçek TCP üzerinden test edildi. Bu **Windows/Edge fiili entegrasyon kabulü değildir**.
