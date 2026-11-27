# Freya v2 için yeniden geliştirme paketi

Bu klasörü yeni çalışma dizinine taşıyın. Aşağıdaki istemi kodlama aracına verin.

> Bu klasördeki belgelerden hareketle Windows üzerinde yerel çalışan Türkçe otomotiv ekspertiz asistanını yeni bir projede geliştir. Önce 01, 02 ve 03 ile ürün ve çalışma sınırlarını çıkar. Her özellik için ekran → API veya ses mesajı → iş kuralı → veri değişimi → kabul senaryosu eşlemesi yap. Önce web üzerinden uçtan uca tek bir gerçek randevu tamamla. Ardından telefon kanalını ve diğer operatör ekranlarını bağla. Eski proje klasörüne erişimin olduğunu varsayma. Referans parçaları davranışı tarif eder; yeni projenin dosya düzenini kendin kur. Her teslimde çalıştırdığın testleri, kullanılan gerçek veya taklit bağımlılıkları ve henüz ölçülmemiş noktaları kaydet.

| Dosya | Boyut | Ne zaman okunur? |
|---|---|---|
| [01 · Ürün ve uygulama sırası](01-Urun.md) | 14 KB | **Her şeyden önce.** Özelliklerin gerçeklik düzeyi, ölçülmüş değerler, kabul senaryoları ve kopyalanmaması gereken davranışlar |
| [02 · Mimari](02-Mimari.md) | 400 KB | Süreçler, ses motoru, M01–M11, supervisor ve analiz kuyruğunu kurarken |
| [03 · Diyalog ve taşıma](03-Diyalog.md) | 211 KB | Türkçe durum geçişlerini, teyidi, iptali, DTMF ve ses protokolünü uygularken. Baştaki "Davranış tarifi" bölümü koddan önce okunur |
| [04 · HTTP](04-HTTP.md) | 276 KB | İstemci ve sunucu arasında yöntem, yol, veri tipi ve hata sözleşmesini kurarken. Baştaki erişim modeli tablosu kimlik kurallarını özetler |
| [05 · Veri](05-Veri.md) | 126 KB | SQLite tabloları, ilişkiler, indeksler ve sürüm geçişlerini kurarken |
| [06 · Ayarlar](06-Ayarlar.md) | 445 KB | Model, santral, bağımlılık ve özellik bayraklarını seçerken |
| [07 · Arayüz](07-Arayuz.md) | 88 KB | Gezinme, tema, yerleşim ve uygulama kabuğunu tasarlarken |
| [08 · Ekranlar](08-Ekranlar.md) | 718 KB | Ekran özelinde işlem, form, ses yakalama ve geri bildirimleri bağlarken |
| [09 · Sözleşmeler](09-Sozlesmeler.md) | 33 KB | Olay ve adaptör yüklerini doğrularken |
| [10 · Sözlük](10-Sozluk.md) | 2,7 MB | Türkçe telaffuz ve otomotiv eş adları için kaynak veri gerektiğinde |
| [11 · Doğrulama](11-Dogrulama.md) | 171 KB | Kurulum, gerçek model deneyi ve fiziksel kabulü planlarken |
| [12 · Test kataloğu](12-Test-katalogu.md) | 71 KB | Alan bazlı regresyon senaryolarını seçerken |
| [13 · Alan servisleri](13-Alan-servisleri.md) | 1,2 MB | HTTP işlemlerinin yetki, hata ve kalıcılık ayrıntıları gerektiğinde |

Büyük ekleri bütünüyle tek isteme yüklemek yerine ilgili başlığı açın. Eski depo yolları kaynak kökenini belirtir. Model ağırlıkları, çalışma veritabanı, ses kayıtları ve kurulum parolaları ayrı işletim girdileridir.


## Paketin kaynağı ve kapsamı

- Kaynak: referans depo, commit `6273981` (21.11.2026). Paketteki 316 dosya dökümü bu commit ile satır satır karşılaştırıldı; hepsi aynı.
- Pakette **yok** (ayrıca temin edilir): FreyaTTS kopyası (`vendor/FreyaTTS`) ve model ağırlıkları, `data/a01yt/a01yt_v05_readonly.sqlite3`, işletim veritabanı, ses kayıtları, `.env` gizli değerleri, `experimental/` ve `archive/` kaynakları, `brag-output/` tanıtım dosyaları, Python test dosyalarının gövdesi (12 belgesinde yalnız test adları var; Playwright testleri tam).
- Sonradan eklenenler: 01 belgesinin ürün, ölçüm ve kabul bölümleri; 03 başındaki davranış tarifi; 04 başındaki erişim modeli; 06 sonundaki başlatma dosyaları ve model tablosu; 10 sonundaki aynı içerikli dosyalar; 11 sonundaki sabit test verisi ve ölçüm yöntemi; 12 sonundaki deneysel testler ve yeni sürüme eklenecek testler.

## Bu paketle çalışma kuralları

1. **Kod dökümü davranış kanıtıdır, tasarım değildir.** 02–13'teki kod, hatalarıyla birlikte eski sürümdür. Dosya düzenini, sınıf adlarını ve düzenli ifade zincirlerini kopyalamayın; davranışı alın.
2. **Önce 01'deki "Kopyalanmaması gereken davranışlar" tablosunu okuyun.** Orada K1–K11 olarak işaretlenen davranışlar yeni sürümde bilinçli olarak farklı olacaktır. Kod ile 01 çelişirse 01 geçerlidir.
3. **Dürüstlük kuralları zorunludur** (01). Ölçülmeyen değer "—" gösterilir; taklit sağlayıcı gerçek teslimat gibi sunulmaz.
4. **Bayt bayt korunacak tek veri** `data/fixtures/legacy_320_cases.json` dosyasıdır (SHA-256 11 belgesinde). Kopyaladıktan sonra özeti doğrulayın.
5. **Büyük dosyaları bütün olarak yüklemeyin.** 10 ve 13 birlikte 3,9 MB'tır; dosya adını içeren başlığı (`### yol/dosya.py`) arayıp yalnız o bölümü açın. Belgelerin satır sonu CRLF'dir; kod bloklarını kopyalarken hedef dosyanın satır sonunu kullanın.
6. **Her teslimde** çalıştırılan testleri, kullanılan gerçek ve taklit bağımlılıkları ve ölçülmemiş noktaları yazın. Ölçüm değerini 01'deki referans tablosuyla yan yana verin.

## Yeni klasörde ilk doğrulama

1. 06 belgesindeki yapılandırma, kilit dosyaları ve kurulum betiklerinden ortamı kurun. Model ağırlıkları için ilk indirmeye erişim gerekir.
2. 02 belgesindeki ortak çekirdeği, 03’teki canlı çağrı yoluyla ilişkilendirin. İlk randevunun onay ve kalıcılık koşullarını birim testinde doğrulayın.
3. 01'deki A1–A10 kabul senaryolarını otomatik teste çevirin ve geçirin. Bu adım bitmeden telefon kanalına geçmeyin.
4. 11’deki CI akışını ve 12’deki tarayıcı senaryolarını çalıştırın. Sonuçlara ortamı, kullanılan adaptörü ve test edilen ses kanalını yazın.
5. 11'deki akustik ölçümü 320 cümleyle alın ve 01'deki referans değerlerle karşılaştırın.
