# FreyaTTS PoC · Canlı sesle ekspertiz randevusu

## PoC gösterimi

Bir müşteri gerçek mikrofona “Yarın sabah Corolla için ekspertiz istiyorum. Plakam otuz dört Adana Bursa Ceyhan yüz yirmi üç” der. Freya randevu talebini anlar, Corolla’yı katalogla eşler, plaka adayını çözer ve takvimden saat sunar. Müşteri “C değil, Denizli’nin D’si” dediğinde taslak plaka 34 ABD 123 olur. Asistan güncel plakayı, aracı, tarihi, saati, paketi ve fiyatı okuyup açık onay ister. Operatör takvimde tek kayıt ve aynı referansı görür.

Ana kabul web üzerinden gerçek insan sesiyle yapılır. Asterisk zorunluysa aynı senaryolar gerçek hat üzerinden ayrı bir kabul koşusunda tekrarlanır. Motor sesiyle arıza teşhisi ve atölye otomasyonu ayrı PoC kapsamlarıdır. Bu çalışmada araç içi yol, klima ve motor sesi konuşma tanımayı etkileyen arka plan koşullarıdır.

## Mevcut kodda başlangıç noktaları

- `backend/session.py:366` ses turunu STT, diyalog ve TTS’ye bağlar. Metin girişi de aynı diyalog motoruna ulaşır. Bu iki giriş, ses tanıma hatalarıyla karar hatalarını ayırmak için kullanılabilir.
- `backend/dialogue.py:62` plaka çıkarıcısı yazılı sayı–harf–sayı biçimine dayanır. Kelimeyle sayı, şehirle harf kodlama, “A çift B” ve “sonu 124” gibi düzeltmeler için davranış sözleşmesi eklenmeli.
- `backend/dialogue.py:98` mevcut yapılandırılmış çıkarım şemasında müşteri, araç açıklaması ve seçenek bilgisi var. Plaka, randevu niyeti, tarih aralığı, düzeltme ve onay kapsamı için açık sözleşme gerekiyor.
- `backend/dialogue.py:891` algılanan plaka ile profil getirme veya oluşturma yolunu çağırıyor. Kimlik ve randevu yazma kuralları incelenirken bu yolu da kapsa. Doğrulama öncesi aday plaka oturum taslağında kalmalı.
- Niyet etiketlerini mevcut Supervisor niyet sözlüğüne eşle. Yeni bir bağımsız yönlendirici yaratmadan önce mevcut etiketlerin canlı çağrı yolunda hangi kararlara bağlandığını ölç.
- İlk Randevu Rehberi operatör kurulumuna hizmet eder. Sesli PoC’nin testleri rehber, mikrofon ve kalıcı kayıt katmanlarını ayrı ayrı doğrular.

## Canlı karar zinciri

~~~mermaid
flowchart TD
    U["Müşteri konuşur"] --> A["PCM, VAD ve tur sınırı"]
    A --> B["Geçici yazı ve tamamlanmış ASR turu"]
    B --> C{"Tur anlaşılır mı?"}
    C -->|Hayır| R["Asistan belirsiz parçayı tekrar ister"]
    R --> U
    C -->|Evet| D["Niyet ve alan adayları, düzeltme, kanıt metni"]
    D --> E{"Politika ve görüşme durumu"}
    E -->|Bilgi| F["Katalogdan yanıtla, mevcut taslağı koru"]
    E -->|Belirsiz veya eksik| R
    E -->|Vazgeçme| X["Güncel teklifi kapat, mevcut kayıt korunur"]
    E -->|Randevu veya düzeltme| G["Plaka ve araç doğrulama, tarih çözümleme"]
    F --> U
    G --> H["Takvimden geçerli seçenekleri bul"]
    H --> I["Asistan tarih, araç, plaka, paket ve fiyatı özetler"]
    I --> J{"Yanıt güncel özetin açık onayı mı?"}
    J -->|Düzeltme| G
    J -->|Belirsiz| R
    J -->|Hayır| X
    J -->|Evet| K["İşlem içinde koşulları tekrar denetle"]
    K -->|Saat doldu| H
    K -->|Başarılı| L["Tek kayıt ve referans"]
    L --> M["Asistan referansı söyler, panel kaydı gösterir"]
~~~

### Ses ve alan çıkarımı

1. Web ve telefon için aynı tur zarfını kullan. Giriş kanalı, örnekleme hızı, tur kimliği, konuşma bitiş anı ve girişte kayıp bilgisi kaydedilsin. Geçici transkript kullanıcıya canlı geri bildirim sağlar. Karar motoru tamamlanmış turu işler. Müşteri araya girince ilgili TTS kuyruğunu kes ve önceki ses parçalarının sonraki tura taşmasını önle.
2. Serbest konuşma ASR ayarıyla plaka toplama ayarını ayrı ölç. Plaka beklenirken bağlamsal sözlük ve gerektiğinde kısa bir yeniden çözümleme denenebilir. Plakayı il kodu, harf grubu, seri numarası olarak ayrı çöz. Ham ifade ve normalize aday ayrı tutulur. Belirsizliği açıkça sor. “Ortadaki harf Bursa’nın B’si mi, Denizli’nin D’si mi?”
3. Araç için marka, model ve gerekiyorsa yıl çıkar. “Toyota için” yanıtında katalogdaki uygun modelleri kullanarak tek bir ayırıcı soru sor. “Yarın” ifadesini tur anı ve `Europe/Istanbul` ile takvimin kullanacağı mutlak tarihe çöz. “Sabah” bir zaman aralığıdır. Saat önerisi gerçek takvimden gelir.
4. Güven kararını modelin kendine verdiği puana bağlama. Beklenen alan, kural doğrulaması, katalog adaylarının sayısı, ASR belirsizliği ve taşıdığı metin kanıtı birlikte değerlendirilir. Ardışık iki başarısız alan denemesinde web’de yazıyla giriş, çağrıda operatöre geçiş öner.

### Niyet ve karar sözleşmesi

LLM çıktısını JSON ve katı doğrulamayla al. Asgari alanlar `turn_id`, `intent`, `secondary_intents`, `entities`, `edits`, `confirmation_signal` ve her çıkarımın `evidence_text` değeri. Aktif durum ve beklenen alan çıktıya karar bağlamı sağlar. “Evet, sizi duyuyorum” olumlu ifade olabilir, rezervasyon onayı değildir. “İptal etmeyin, saati değiştirin” olumsuz iptal ve olumlu saat değişikliği olarak ele alınır. “Fiyatı söyleyin, uygunsa ayıralım” fiyat yanıtı ve daha sonra randevu taslağı anlamına gelir.

Doğal konuşmayı, niyeti ve alıntılanabilir alan adaylarını LLM yorumlar. Kod, hangi geçişin izinli olduğunu ve hangi verinin kaydedileceğini belirler. Çıktı geçersiz, zaman aşımında veya çelişkiliyse asistan kısa bir netleştirme sorusu sorar. Operasyon aşamaları `intent → collect → offer → confirm → commit → done`. Açık kullanıcı düzeltmesi alan sürümünü artırır, eski özetin onay yetkisini düşürür. Hata durumunda aynı onay yeniden gelirse idempotency anahtarı aynı referansı döndürür. Son slot yarışında veritabanı yalnızca bir isteği kabul eder. Kayıt sonucundan önce başarı cümlesi kurulmaz.

### Model seçimi

Mevcut `qwen2.5:7b` yapılandırması başlangıç çizgisi. Aynı yerel donanımda ölçülecek üç kol kur: mevcut çağrı, aynı model ve katı JSON/bağlam/kurallı onay, donanıma sığan bir alternatif yerel aday. Prompt, şema, ASR metni, bağlam ve takvim fikstürü sürümlensin. LLM karşılaştırmasında bunlar aynı tutulur. Modelin işini görmek için önce doğru insan transkripti, sonra aynı sesin ASR çıktısı verilir. Fark ASR kaynaklı düşüşü gösterir. Önce JSON geçerliliği, kritik yanlış işlemler ve alan/niyet doğruluğu. Bu koşulları geçen adaylardan p95 gecikme ile VRAM’i daha iyi olanı seç. Canlı kullanım için seçim sonucunu insan sesinde teyit et.

## 512 yazılı regresyon yolu

[Mermaid ağaçları](POC_SOHBET_AGACLARI.md) ve [asistan–müşteri konuşmaları](POC_SOHBET_512.jsonl) bu planla birlikte hazır. Sekiz aile, sekiz ara durum ve sekiz açılış ifadesi 512 yol verir. Açılışlar karşılama varyasyonudur. Aile ve ara durum çarpımı 64 davranış kombinasyonu sağlar. Bekleme, erken “evet”, işlemi onaylamadığını belirtme, yan konuşma, söz kesme, tekrarlatma ve anlaşılmayan ses kapsamda. Yazılı test demetinin hedefi beklenen işlem, işlemin zamanlaması, kayıt sayısı ve kayıt alanlarıdır.

Test fikstürü zamanı `2026-11-20T14:00:00+03:00` olarak dondur. Corolla için standart ekspertiz bedeli 2.500 TL. Yeni randevu ailelerinde 21 Kasım 09.00 dolu, 10.00 açık. Taşıma ve iptal ailelerinde ayrı test veritabanında aynı araç ve telefonla 21 Kasım 11.00’da bir aktif kaynak randevu ekle. Her yol ayrı oturum ve temiz veritabanı ile başlar. JSONL içindeki asistan metinleri referans diyalogdur. Test çalıştırıcısı bunları uygulamaya yanıt olarak enjekte etmez. Müşteri turlarını verip asistanın geçişini, doğrulanmış alanlarını, DB farkını ve onay zamanını kontrol eder. Ses olay etiketleri, WAV karşılığı hazırlanıncaya kadar simüle edilmiş giriş olayıdır.

Sonraki demette dondurulmuş regresyon verisine yeni aileler ekle. Bunlar açık iptal onayı, işlem sırasında saat yarışması, onay özeti sonrası plaka düzeltmesi, ikinci onayın tekrarı, birden çok plaka, harf ve sayıları şaşırtan örnekler, katalogda araç yok, servis zaman aşımı ve kullanıcının fikrini değiştirmesi. Her ailede müşterinin doğal olarak ürettiği cümleleri kullan. İnsan sesli kabul verisini prompt yazarken kullanılan konuşmalardan ve konuşmacılardan ayır.

## Teslim sırası ve kabul eşikleri

| Sıra | Teslim | Ölçüm |
|---|---|---|
| 1 | Dondurulmuş fikstür, durum/alan/DB olayları ve mevcut sistemin referans ölçümü | Her başarısız örnek ses, ASR, alan, niyet, takvim, yazma veya TTS katmanıyla ilişkilendirilebilir |
| 2 | Plaka ayrıştırma, harf kodlama, kapsama bağlı düzeltme ve yeniden okuma | Bölüm hataları ile tam plaka eşleşmesi ölçülür. Yanlış plaka ile kaydedilen randevu hedefi 0 |
| 3 | Yapılandırılmış niyet ve durum geçişleri, model değerlendirmesi | PoC çekirdek niyetleri için macro-F1 hedefi ≥0,90. Test mesajına ve duruma göre onaysız yazma hedefi 0 |
| 4 | Takvim kontrolü, özet, revizyon ve atomik yazma | 512 yolun kritik işlem beklentileri geçer. Tekrarlanan onay ve slot yarışında çift kayıt hedefi 0 |
| 5 | Gerçek insan sesi ile kör kabul ve demo | Örnek hedef 12 konuşmacı × 6 senaryo = 72 canlı vaka. Her kanal ve ortam ayrı raporlanır. Onay öncesi sıfır yazma, tamamlanan kayıtlarda doğru plaka ve saat, temiz seste en az %90 görev tamamlama, ilk duyulur yanıt için sıcak p95 ≤2,5 sn hedeflenir |

Canlı testte sessiz oda, araç içinde klima/yol sesi ve telefon hattını ayrı etiketle. “İlk denemede plaka doğru” ile “düzeltme sonunda doğru plaka” iki ayrı oran. Gecikme için son kullanıcı sesi ile ilk duyulur asistan PCM’i arasını ölç. VAD, ASR, LLM, DB ve TTS sürelerini aynı tur kimliğiyle kaydet. p50/p95 için örnek sayısını ve sıcak/soğuk koşulu yaz. Teknik günlüklerde ham plaka, telefon ve ses varsayılan olarak maskeli veya kayıtsız olsun. İnceleme için tutulan insan seslerinin katılımcı onayı ve saklama süresi belirlenir.

Demo oturumu üç kısa çağrıdan oluşabilir. Gürültü içinde plaka düzeltip tek randevu oluşturma. Dolu saate alternatif teklif edip yeni saati doğrulama. “Evet, sizi duyuyorum” ile kayda geçmeyip açık vazgeçmede kapanma. Her çağrının sonunda operatör takvim sonucunu ve kişisel verileri maskeleyen karar özetini görür.
