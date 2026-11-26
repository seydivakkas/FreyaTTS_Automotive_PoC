# M00 raporu — taban durum ve özellik envanteri

**Karar: HOLD** (engelleyici FAIL yok; G03, G05, G08 kısmi). H01'e giriş koşulu (M00-G00 ve M00-G07 PASS) **sağlandı**. `m01_ready: false`.

## Özet

| Alan | Sonuç |
| --- | --- |
| Taban | `master` `6f5867a`, temiz ağaç, 759 izlenen dosya |
| API | 232 HTTP/WS uç, tamamı statik olarak kayıtlı router'larda |
| Arayüz | 43 bileşen dosyası; arka uçla eşleşmeyen `/api` çağrısı bulunmadı (bileşen düzeyi) |
| Veritabanı | 34 tablo (göç) + `caller_profiles` (yalnız ORM) |
| Yapılandırma | 87 kayıt (ortam değişkeni + ayar alanı) |
| Deneyler | 33 modül |
| Testler | 85 test dosyası |
| Taban test (tanımlı ortam, torch yok) | 44 toplama hatası: 43 torch, 1 python-multipart |
| CI eşdeğeri tanı (CPU torch + python-multipart) | **1533 geçti, 21 başarısız, 5 atlandı** |
| GitHub CI kırmızı nedeni | `python-multipart` bağımlılığı tanımlı değil → 44 dosya toplanamıyor |

## Öne çıkan bulgular

1. **CI'nın kırmızı olma nedeni** `python-multipart` eksikliği (yeni bulgu, RISK-0002). Tek satırlık bağımlılık düzeltmesiyle toplama hataları kalkıyor.
2. **X8 doğrulandı:** iki modül düzeyinde `import torch` (RISK-0001).
3. **Çoklu araç randevu hatası (P7) doğrulandı:** iki test başarısız (RISK-0004).
4. **Kimliksiz özel kayıt (P4) ve otomatik profil** kodda görüldü (RISK-0003).
5. **ADR-F3-01:** veritabanında doğum yılı alanı yok; karar gereği plaka son 3–4 hanesi kullanılacak (RISK-0013).
6. **Yapay zekâ bildirimi** karşılama metinlerinde yok (RISK-0012).

## Sapmalar (paket kuralından)

- Paket "paket kurulumu yapılmaz" der. Testleri çalıştırmak için **depo dışındaki yalıtılmış bir kopyada** `uv sync --frozen --extra test` ile tanımlı test ortamı kuruldu; tanı için CI'nın kurduğu CPU torch ve eksik `python-multipart` eklendi. Depo, kilit dosyası ve kullanıcı ortamı değişmedi. Tanı sonuçları "CI eşdeğeri tanı" olarak ayrı etiketlidir.
- Bağımsız inceleme yapılmadı; kapı kararlarını ajan verdi.

## Açık kalanlar (HOLD nedenleri)

- **G03:** arayüz kontrol (buton) düzeyinde eşlenmedi.
- **G05:** hat izi dosya/sembol düzeyinde; çağrı grafiği ve kenar biçimleri ayrıntılı değil.
- **G08:** özellik kaydı anahtar sözcük eşleşmesiyle; hedef sahipler kısmen UNRESOLVED.

Bu boşluklar M08 (test altyapısı) ve G2/G3 öncesinde kapatılmalıdır; H01'i engellemez.
