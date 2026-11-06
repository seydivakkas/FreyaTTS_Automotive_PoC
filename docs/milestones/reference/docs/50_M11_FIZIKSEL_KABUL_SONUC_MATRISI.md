# M11 Kabul Matrisi — 1 Kasım 2026 (mevcut çalışma ortamı)

| Kapı | Gerçek gözlem | Karar |
|---|---|---|
| M01–M10/M11 yazılım testleri | 460/460 unit, integration, mock ve M11 sözleşme testi | PASS (software only) |
| Golden set | 320 test cümlesi; M10 SHA-256 ile aynı | PASS (integrity only) |
| Windows 11 / Python 3.11 / Edge | Çalışma ortamı Linux/Python 3.13; Edge/Windows makineye erişilmedi | HOLD |
| FreyaTTS-small / Leyla | Model ağırlıkları ve CUDA cihazı burada bulunmuyor; 0 gerçek WAV | HOLD |
| STT ve VAD | Gerçek etiketli ses ve mikrofon/söz kesme deneyi yok | HOLD |
| Codec ve telefon playout | FFmpeg ikilisi mevcut; gerçek ses/çağrı zinciriyle test yok | HOLD |
| Asterisk | Yetkili canlı PBX oturumu ve akustik sonlanma izleği yok | HOLD |
| A01-YT | 3 kaynak sözlü izin beyanı kayıtlı; 0 doğrudan sağlanan ses klibi; 0 onaylı telaffuz | HOLD |
| Güvenlik/KVKK | Yerel mock güvenlik sınırları test edildi, üretim RBAC/şifreleme/retention kanıtı yok | HOLD |

**M11 genel karar: PHYSICAL ACCEPTANCE HOLD.** 460 test yalnızca bu ortamda çalıştırılabilen yazılım sözleşmelerinin testidir; gerçek fiziksel kabulü tamamlamaz. `data/m11/M11_ACCEPTANCE.json` ve `.html` mevcut, ancak kanıt referansları bu Linux çalışma ortamına aittir; Windows'a taşındığında `check_m11.ps1` ile yeniden oluşturulmalıdır.

## Mevcut kabul aracının kapsamı ve sınırları

- `tts` yalnız açık `--enable-physical` ile yerel FreyaTTS modelini yüklemeyi dener, modelin 48 kHz mono WAV dosyalarını yazar, RTF'yi ölçer; gerçek dinleme onayı üretmez. `voice-review` tam 320 A/B çifti + 640 hash-doğrulanmış WAV + 320 imzalı dinleyici kararından önce PASS vermez.
- `stt` isteğe bağlı yerel Faster-Whisper modeliyle gerçek, etiketli PCM WAV'ları işler; WER/CER üretir, VAD barge-in zamanını ölçmez. Bu kapı HOLD kalır.
- `codec` açık kullanıcı izniyle yerel ses üzerinde FFmpeg kodlamasını gerçekleştirir; gerçek medya transport round-trip / ses oynatma ölçümü yapılmadığı için HOLD kalır.
- `pbx` yalnız canlı kaynaklı olay sırası, ham çağrı günlüğü ve bağımsız dinleme kaydını birlikte değerlendirir. `FLUSH_MEDIA` tek başına PBX ACK değildir. İlgili alanlardan biri eksikse HOLD olur.
- `a01yt` yalnız klip dosyası, hash, kaynak id, zaman kodu ve insan onayını denetler. 50 özgün hedef gerçekleşmeden PASS vermez.
- `manual` yalnız `windows_edge` ve `safety_privacy` için gerçek gözlem tutanağı ile insan imzalı değerlendirmenin kaydına izin verir. İnsan tarafından doğrulanan beyanın bağımsız gerçekliğini yazılım tek başına kanıtlamaz.

**Açık risk:** M10'da kalıcı M02/M03 workflow replay ve dış servis exactly-once yok; CRM/telefon pilotundan önce idempotency ve insan denetimi zorunludur. Operatör paneli localhost geliştirici aracı olmaya devam eder.
