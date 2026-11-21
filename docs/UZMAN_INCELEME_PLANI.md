# FreyaTTS Otomotiv Asistanı: Uzman İncelemesi ve Düzeltme Planı

Tarih: 2026-11-12. Bu belge yalnızca tespit ve plandır; inceleme sırasında proje kodunda hiçbir şey değiştirilmedi.

## 1. Hüküm

İçinize sinmeyen şeyin somut bir karşılığı var. Son commit'ten (`e4abda4`, 7 Kasım) sonra depoya, hiçbiri commit edilmemiş büyük bir değişiklik yığını girdi: 48 dosyada yaklaşık 6.800 satır ve 39 yeni dosya. Bu yığın beş yeni özellik alanı ekledi (gerçek SMS, iptal/erteleme, takvim, KVKK silme, Supervisor/FQICI). Aynı anda, daha önce düzeltilmiş üç sorun sınıfını geri getirdi ve çalışan ses yolunu bozdu.

En önemli altı sonuç:

1. **Asistan her cümleyi iki kez seslendiriyor.** Çalıştırarak doğrulandı.
2. **Sesli iptal ve erteleme güvenli değil.** Erteleme isteği, yeni saat seçilmeden mevcut randevuyu siliyor. "Hayır tamam kalsın" yanıtı randevuyu iptal ediyor. Arayan, yalnızca adın bir parçasını söyleyerek başkasının randevusuna ulaşabiliyor. Üçü de çalıştırarak doğrulandı.
3. **Konuşma tanıma, gerçek müşteri cümlelerini sessizce siliyor.** İki araç adı ve iki virgül içeren cümle ile "video" geçen cümle boş dönüyor. Çalıştırarak doğrulandı.
4. **Test yalıtımı yeniden delindi.** Bir test, çalışırken gerçek veritabanlarına geçiyor. Bu, daha önce 97 görüşmenin silinmesine yol açan hatanın aynı sınıfı.
5. **Uydurma ölçümler geri geldi.** Arayüz, sabit yazılmış süreleri "canlı" etiketiyle gösteriyor; "WSOLA 0.98x" ve "DiT LoRA" gibi projede çalışmayan bileşenleri çalışıyor gibi sunuyor.
6. **Ölçümler bayatladı.** Kalite kapısının okuduğu rapor 6 Kasım tarihli; o tarihten sonra hem konuşma tanıma hem sentez yolu değişti. 56 cümlelik alt kümede yaptığım tekrar ölçüm, temiz sentetik seste gerileme göstermedi (Bölüm 2). Kısık, gürültülü ve insan sesiyle davranış ise hâlâ bilinmiyor.

Önerim: yeni özellik eklemeyi durdurun. Önce çalışma ağacını güvenceye alın, sonra aşağıdaki sırayla ilerleyin.

## 2. İncelemenin kapsamı

| Yapılan | Sonuç |
|---|---|
| Commit edilmemiş tüm backend farkı okundu (ses yolu, diyalog, bildirim, KVKK, telefon, veritabanı) | Bulgular Bölüm 4'te |
| Yeni modüller okundu: `backend/supervisor/`, `backend/fqici/`, `kvkk_compliance.py`, `pipeline_telemetry.py` | Bölüm 4 ve 5 |
| Arayüz farkı tarandı (ses kancası, gezinme, ardışık düzen görünümü) | Bölüm 4.3 |
| Test süiti çalıştırıldı (gerçek veritabanına geçen bir test hariç) | 1.436 geçti, 6 kırıldı, 1 bilerek atlandı (6 dakika) |
| TypeScript denetimi ve arayüz derlemesi | İkisi de hatasız |
| Beş bulgu, geçici ve yalıtılmış veritabanında çalıştırılarak sınandı | Beşi de doğrulandı |
| Akustik ölçüm, 56 cümlelik alt kümeyle, sonuç ayrı klasöre yazılarak tekrarlandı | Gerileme yok (aşağıdaki tablo) |

Yapılmayanlar: insan sesiyle deneme, gerçek Asterisk hattı, gerçek Twilio gönderimi, eşzamanlı görüşme yükü, arayüzün her sekmesinin elle gezilmesi. Bu alanlardaki bulgular kod okumasına dayanır ve öyle işaretlenmiştir.

Gerçek veritabanları inceleme boyunca korundu: `data/assistant.db` ve `data/demo/assistant.db` dosyalarının SHA-256 özetleri başta ve sonda aynıdır (`d390e58f…` ve `f0db5fb7…`).

Akustik karşılaştırma, aynı 56 cümle, telefon bandı (sentetik ses, temiz kanal):

| Ölçüt | 6 Kasım kodu | Bugünkü çalışma ağacı |
|---|---|---|
| Kelime hata oranı (WER) | %20,84 | %18,85 |
| Karakter hata oranı (CER) | %7,98 | %7,02 |
| Terim doğruluğu | %53,85 (14/26) | %53,85 (14/26) |
| Boş dönen transkript | 0 | 0 |
| F0 medyanı | 285,1 Hz | 284,7 Hz |
| Ortalama RTF | 0,565 | 0,274 |

Yorum: Yeni tanıma ayarları temiz sentetik seste zarar vermiyor, hatta WER biraz düşük. Terim doğruluğu değişmedi. RTF farkının nedeni ayrıştırılmadı; iki ölçüm farklı zamanlarda ve farklı ekran kartı yükünde alındı. Alt küme küçük (26 terim); tam 320 cümlelik ölçüm kesin sonucu verir. K5'teki silme sorunları bu ölçümde görünmez, çünkü test cümleleri o kalıpları içermiyor ve ses yüksek.

Kırılan altı test ve nedenleri:

| Test | Neden | İlgili bulgu |
|---|---|---|
| `test_api.py::test_teardown_failure_releases_single_call_capacity` | Ses bağlantısı gerçek modelleri yüklemeye başlıyor | Y3 |
| `test_voice_path_honesty.py::test_turn_emits_stt_and_llm_metrics` | `llm_total_ms` artık LLM süresini taşımıyor | Y2 |
| `test_workflow.py::test_synthesis_bounded_and_cancellation` | Senteze giden metin değişiyor ("new" yerine "New.") | Bölüm 4.3 |
| `test_appointment_reschedule_preview.py` içinde 3 test | Test, kurulu kütüphanede olmayan bir parametre kullanıyor (`TestClient(auth=…)`); hiç çalışmıyor | Bölüm 6, Aşama 3 |

Atlanan test `test_car_denoiser.py::test_system_mode_dynamic_switch`; gerçek veritabanlarına geçtiği için çalıştırılmadı (K4).

## 3. Deponun durumu

- **Dal:** `master`, son commit `e4abda4`. Uzak depo yok.
- **Commit edilmemiş:** 48 değişmiş dosya, 39 yeni dosya veya klasör. Hepsi doğrudan `master` üzerinde.
- **Veritabanı şeması:** Gerçek veritabanı `024` sürümüne yükseltilmiş. Bu sürümü tanımlayan 020–024 göç dosyaları commit edilmemiş. Kod geri alınırsa veritabanı ile kod uyumsuz kalır.
- **Gerçek veritabanı içeriği:** 1 görüşme, 0 araç, 0 müsait saat, 0 randevu. Mikrofon denemesi için gereken araç ve saat girilmemiş.
- **Artıklar:** `data/` 646 MB. Bunun büyük kısmı, depo içine yazılmış test klasörleri (`data/pytest-*`, 17 klasör), iki göç denemesi veritabanı kopyası ve geçici klasörler. `.playwright-mcp/` ve `build/` izlenmiyor ve yok sayılmıyor.

## 4. Bulgular

Her bulguda kanıt türü belirtilir: **Çalıştırıldı** (yalıtılmış ortamda denendi) veya **Okundu** (koddan görüldü, denenmedi).

### 4.1 Kritik: müşteriye zarar verir veya veri kaybettirir

**K1. Her cümle iki kez çalınıyor.** Çalıştırıldı.
- Yer: `backend/session.py:741-748`. Aynı dört satırlık blok (ölçüm kaydı, olay, `play_wave`) art arda iki kez yazılmış.
- Kanıt: Tek cümlelik yanıtta `play_wave` 2 kez çağrıldı, beklenen 1.
- Etki: Müşteri her cümleyi iki kez duyar. Her ses ölçümü de iki kez kaydedilir ve gecikme istatistiklerini bozar.
- Düzeltme: İkinci bloğu silin. "Bir cümlecik bir kez çalınır" diye test ekleyin; mevcut testler bunu yakalamıyor.

**K2. Sesli iptal ve erteleme akışı güvensiz.** Çalıştırıldı.
- **Erteleme, onaysız iptal ediyor** (`backend/dialogue.py:942`, `:985`): "Randevumu ertelemek istiyorum" denince mevcut randevu hemen iptal ediliyor, sonra yeni saat soruluyor. Müşteri kapatırsa veya saat beğenmezse randevusu yok olur. `tests/test_madde3_customer_experience.py:160` bu davranışı doğru kabul ediyor.
- **Olumsuz yanıt iptal ediyor** (`dialogue.py:860`): İptal onayında önce olumlu sözcükler aranıyor. "Hayır tamam kalsın" ve "Uygun değil, iptal etmeyin" yanıtlarının ikisi de randevuyu iptal etti. Bu, daha önce onay akışında düzeltilen hatanın aynısı.
- **Kimlik doğrulaması yok** (`dialogue.py:111`): Randevu, adın alt dizgisiyle aranıyor. Adını "Ali" diye tanıtan biri "Ali Kaya"nın randevusunu erteleyebildi. Telefon numarası web görüşmesinde müşterinin kendi beyanıdır.
- Düzeltme: Erteleme tek işlemde yapılmalı: yeni saat onaylanınca eski saat bırakılır. Onayda olumsuz ifade önce denetlenmeli. Randevuya erişim için en az iki bilgi (kayıtlı telefon ve plaka) eşleşmeli; eşleşmezse operatöre takip kaydı açılmalı.

**K3. Arayan numarası kimlik doğrulamasız kaydedilebiliyor.** Okundu.
- Yer: `backend/routers/telephony.py:255`. `/api/telephony/inbound-metadata` uç noktasında kimlik doğrulama veya IP kısıtı yok.
- Etki: Ağdan erişen herkes, bir çağrı kimliği için istediği arayan numarasını yazabilir. Bu numara K2'deki randevu aramasında kullanılıyor.
- Düzeltme: `pbx_allowed_ips` listesine ve paylaşılan bir gizli anahtara bağlayın.

**K4. Test yalıtımı delindi; çalışan sunucuda veritabanı değiştirilebiliyor.** Okundu.
- Yer: `backend/db.py:27-63` (`switch_database`), `backend/routers/core_system.py:23`, `frontend/src/main.tsx:88`, `tests/test_car_denoiser.py:426-454`.
- Sorun 1: `switch_database`, ortam ayarını yok sayıp sabit yollara geçiyor (`./data/assistant.db`, `./data/demo/assistant.db`). Test bu uç noktayı çağırıyor ve bitince demo veritabanında kalıyor. O testten sonra çalışan bütün testler gerçek demo veritabanına yazar.
- Sorun 2: Aynı test, gerçek veritabanında araç bulunmamasını şart koşuyor. Mikrofon denemesi için araç eklediğiniz anda test kırılır.
- Sorun 3: Arayüzdeki "Demo / Reel" düğmesi, süren görüşmeler varken tüm sunucunun veritabanını değiştirir ve tabloları Alembic dışında oluşturur.
- Düzeltme: Çalışma anında veritabanı değiştirmeyi kaldırın. Demo modu yalnızca başlatma seçeneği olsun (`start_demo.ps1` bunu zaten yapıyor). Testi silin.

**K5. Konuşma tanıma filtreleri gerçek konuşmayı siliyor.** Çalıştırıldı.
- Yer: `backend/models.py:293-376`.
- "Aracım Volkswagen Golf …, 2018 model, bir de Volkswagen Passat … var" cümlesi boş döndü. Kural: iki virgül ve katalogdan iki araç adı varsa metin atılır (`:370`). İki araçlı randevu özelliği bu kuralla çelişiyor.
- "Videoda gördüğüm paketi almak istiyorum" boş döndü. Kural: metinde "video", "thank you", "context," gibi parçalar geçerse tümü atılır (`:344`).
- Yaklaşık -46 dBFS düzeyindeki kısık ses, tanıma çalıştırılmadan boş sayılıyor (`:300`). Kısık konuşan veya mikrofona uzak müşteri duyulmaz.
- Katalog ipuçları (`hotwords`) tamamen kapatıldı ve ışın genişliği 3'ten 1'e indirildi (`:315-316`). 56 cümlelik alt kümede bu, temiz seste gerilemeye yol açmadı; gerçek katalogla ve insan sesiyle etkisi ölçülmedi.
- Atılan metin için ne kayıt ne uyarı var; müşteri yanıtsız kalır.
- Düzeltme: Sözcük listesiyle silmeyi kaldırın. Güven eşiği altındaki metni atmak yerine "anlayamadım" turuna çevirin ve sayacını tutun. İpuçlarını kapatma kararını akustik ölçümle verin.

**K6. KVKK silme akışı hem fazla hem eksik siliyor.** Okundu.
- **Fazla:** Kimlik değeri en az 1 karakter (`backend/schemas.py:357`) ve aramalar alt dizgiyle yapılıyor (`backend/kvkk_compliance.py:222`, `:347`). "a" veya "%" değeriyle açılan bir talep neredeyse bütün müşterileri geri dönüşsüz maskeler.
- **Eksik:** Telefonla yapılan silme, görüşme dökümlerine yalnızca ses arşivi veya çağrı analizi kaydı varsa ulaşıyor. Web görüşmelerinin dökümü, içinde ad ve telefon geçse bile kalır. `recordings/` altındaki ses dosyaları da silinmez.
- **Tutanak:** Silinen telefon veya ad, talep kaydında ve tutanakta açık metin olarak saklanıyor. "Kriptografik imha tutanağı" bir SHA-256 özetidir, imza değildir; HMAC hesaplanıyor ama saklanmıyor. "Resmi" nitelemesi hukuki inceleme olmadan kullanılmamalı.
- **Otomatik imha:** Sunucu her saat 30 günden eski dökümleri kalıcı olarak siliyor (`backend/main.py:105-116`). Çözülmemiş takip kayıtları da silinir. Hata olursa sessizce yutulur. Bu, sizin onayınız olmadan eklenmiş geri dönüşsüz bir silmedir.
- Düzeltme: Tam eşleşme ve en az uzunluk şartı; yürütmeden önce etkilenen kayıt sayısının onaylatılması; döküm ve ses dosyalarının kapsama alınması; otomatik imhanın varsayılan olarak kapalı gelmesi.

### 4.2 Yüksek: yanlış bilgi verir veya çalışan şeyi bozar

**Y1. Uydurma telemetri "canlı" etiketiyle gösteriliyor.** Okundu.
- `backend/session.py:363`, `:370`, `:736`: F0 için 2,8 ms, F1 için 6,4 ms, F6 için 8,0 ms ve "wsola_rate 0.98" sabit yazılmış; `source="live"` ile gönderiliyor.
- Arayüz: "WSOLA Hız Oranı 0.98x, Kilitli" (`AudioPipelineInspector.tsx:230`), "DiT LoRA" (`pipeline/types.ts:93`), "SLA: <600 ms" (`AudioPipelineStepper.tsx:54`). WSOLA canlı yolda değil, eğitilmiş LoRA yok, ölçülen ilk ses 1,4–6 s.
- Düzeltme: Ölçülmeyen aşama süre göstermesin. Çalışmayan bileşenlerin adlarını arayüzden çıkarın.

**Y2. `llm_total_ms` artık LLM süresi değil.** Okundu. `session.py:479` bu alana bütün diyalog adımının süresini yazıyor; kural yeterli olup LLM hiç çağrılmadığında da dolu geliyor. Analitikteki LLM gecikmesi bundan besleniyor. Bu alanı koruyan dürüstlük testi şu an kırık.

**Y3. Testler gerçek modelleri yüklüyor.** Çalıştırıldı.
- `backend/main.py:62` sunucu açılışında, `:211` her ses bağlantısında modelleri yüklüyor. Test süiti sırasında ekran kartı belleği 2,7 GB'tan 6,6 GB'a çıktı.
- `tests/test_api.py::test_teardown_failure_releases_single_call_capacity` bu yüzden kırıldı ("session" yerine "Modeller hazırlanıyor" durumu geldi).
- Etki: Testler yavaş ve ekran kartına bağımlı; CI'da çalışmaz.
- Düzeltme: Otomatik yüklemeyi bir ayara bağlayın, testlerde kapalı olsun. Başarısız yüklemenin hatası kaybolmasın.

**Y4. Karşılama 1,5–2,5 s gecikiyor.** Okundu. `session.py:178-195`: Web görüşmesi, karşılamadan önce gürültü kalibrasyonu için bekliyor. Önceki ölçümde karşılama yaklaşık 15 ms idi. Müşteri bu sürede konuşursa sesi "oda gürültüsü" sayılır ve gürültü kapısı -24 dBFS'e kadar yükselebilir; sonraki konuşma kısmen kesilir.

**Y5. A/B ses tohumu kilitlendi, arayüz hâlâ seçtiriyor.** Okundu. `session.py:89` tohumu 9'a sabitliyor. A/B sekmesi 42, 77 ve 123 seçeneklerini sunmaya devam ediyor; deney sonuçları anlamsız.

**Y6. İki ayrı diyalog beyni var ve güvenlik anlayışları çelişiyor.** Okundu.
- `backend/dialogue.py` kimlik sormadan iptal ediyor. `backend/supervisor/` aynı işlem için kimlik doğrulaması ve onay belgesi istiyor, ama hiçbir yazma aracına bağlı değil.
- `SUPERVISOR_MODE=guarded` açılırsa asistan sabit cümlelerle yanıt verir ve randevu alınamaz.
- Supervisor'ın kendi belgesi sonuçları dürüstçe yazıyor: sentetik veride makro F1 0,333, kapsam dışı üç örneğin üçü de kabul edilmiş. Kullanılabilir bir model yok.
- Değerlendirme: Supervisor ve FQICI özenle yazılmış, ama terim doğruluğu %48 olan bir PoC için erken. Yaklaşık 2.000 satır kod, 4 tablo ve 4 göç ekliyor; varsayılan olarak kapalı.

**Y7. Fiyat üç ayrı yerde tutuluyor.** Çalıştırıldı. Asistanın söylediği liste koda sabit yazılmış (`dialogue.py:1024`: 950, 1.450, 1.950, 2.600 TL). Ayrıca `queue_lift.PACKAGE_DEFINITIONS` ve "Araçlar ve fiyatlar" sekmesi var. Panelde fiyat değişirse asistan eskiyi söyler. "Ekspertiz ne kadar sürer?" sorusuna da fiyat listesiyle yanıt veriyor, çünkü "ne kadar" fiyat sorusu sayılıyor.

**Y8. "Otomatik hatırlatma" otomatik değil, SMS yanıtı işlenmiyor.** Okundu. Hatırlatma taraması yalnızca paneldeki düğmeyle çalışıyor; zamanlayıcı yok. Hatırlatma metni "EVET veya İPTAL yazarak yanıtlayın" diyor, ama gelen SMS için uç nokta yok (yalnızca WhatsApp var).

**Y9. Telefon tarafı doğrulanmadan "gerçek" sayılıyor.** Okundu.
- `backend/ami.py:458`: Ayar açıksa her çağrıda yeni bir AMI istemcisi oluşturuluyor; kalıcı bağlantı yok. `is_real` bağlantı kurulmuş olmasına bakmıyor, yani aktarım başarısızken asistan "aktarıyorum" diyebilir.
- `asterisk/extensions.conf`: Önceki "DOĞRULANMAMIŞTIR" uyarısı silindi. Dosya hâlâ gerçek bir Asterisk ile denenmedi. `[from-trunk]` altındaki `_X.` kalıbı her numarayı kabul eder.
- Anlaşılamayan üçüncü denemede asistan artık "danışmanımıza aktarıyorum" diyor (`dialogue.py:564-570`).

**Y10. Ölçümler ve belgeler bayat.** Okundu. `data/acoustic/latest.json` 6 Kasım tarihli. README, ARCHITECTURE, VERIFICATION ve yönetici belgesi yeni özelliklerden söz etmiyor; "SMS sağlayıcısı sahtedir" gibi cümleler artık koşullu doğru.

### 4.3 Orta: düzeltilmeli ama acil değil

- **İki araç algısı gevşek** (`dialogue.py:886`, `:902`): Alt dizgi araması kullanılıyor. "2018" içindeki "2", "varış" içindeki "var" eşleşir. "Başka bir araç" denince süren randevu bilgisi siliniyor.
- **Sentez öncesi büyük harf ve nokta ekleme** (`backend/text.py:246`): "Küçük harfle başlayan cümlede ses kalınlaşıyor" iddiasına dayanıyor; bunu gösteren bir ölçüm yok. Alt küme ölçümünde F0 medyanı değişmedi (285,1 ve 284,7 Hz). Eşleme tablosunda `"ğ": "ğ"` hatası var.
- **Yutulan hatalar:** Yeni kodda 17 genel `except Exception` var, 7'si yalnızca `pass`. İptal bildirimi, gelen çağrı bilgisi ve imha hataları iz bırakmıyor.
- **Hatırlatma araması** (`backend/notifications.py:600`): Kapanmış veritabanı oturumu arka plan görevine veriliyor.
- **Excel raporu:** `openpyxl` yalnızca test bağımlılığı olarak tanımlı; temiz kurulumda rapor uç noktası çalışmaz.
- **Twilio hata gövdesi** günlüğe olduğu gibi yazılıyor; içinde telefon numarası bulunur.
- **Yönetici parolası** kısa ve tahmin edilebilir. Yalnızca bu bilgisayarda kaldığı sürece kabul edilebilir.
- **Tek yönetici hesabı:** Silme ve dışa aktarma gibi işlemler kişiye bağlanamıyor.

### 4.4 Önceden bilinen ve hâlâ açık olanlar

Bunlar yeni değil, ama yeni özelliklerin hiçbiri bunlara dokunmadı:
- Terim doğruluğu %48,04 (eşik %95). Kalite kapısı FAIL.
- İnsan sesiyle ve gürültüde hiç ölçüm yok.
- Eşzamanlı görüşme ölçülmedi.
- Asterisk üzerinden gerçek çağrı yapılmadı (M11 HOLD).
- LLM gerektiren turlarda ilk ses yaklaşık 6 s (hedef 1,2 s).
- Ana kabul testi 6 denemenin 2'sinde geçti.

## 5. Kök neden

Sorun tek tek hatalardan çok çalışma biçiminde:

1. **Temel sağlam değilken üstüne kat çıkıldı.** Asistan araç adlarının yarısını yanlış anlıyor. Bu çözülmeden SMS, KVKK tutanağı, niyet sınıflandırıcı ve kalite kuyruğu eklendi.
2. **Değişiklikler ölçülmeden kabul edildi.** Konuşma tanıma ayarları ve sentez metni değişti, akustik ölçüm tekrarlanmadı.
3. **Hiçbir şey commit edilmedi.** 6.800 satır tek parça halinde duruyor; hangi değişikliğin neyi bozduğu ayrıştırılamıyor ve geri dönüş noktası yok.
4. **Testler tasarımı değil varlığı doğruluyor.** Yeni testler hatalı davranışı (erteleme sırasında iptal) doğru kabul ediyor; çift seslendirme gibi temel bir hatayı hiçbir test yakalamıyor.
5. **Kurallar sözcük listeleriyle büyüyor.** Her yeni niyet, sıraya duyarlı bir düzenli ifade daha ekliyor. `dialogue.py` 1.324 satır oldu ve aynı sınıftan hata (olumlu sözcüğün olumsuzdan önce eşleşmesi) ikinci kez ortaya çıktı.
6. **Dürüstlük kuralı korunmadı.** Daha önce temizlenen sabit ölçümler ve çalışmayan bileşen adları arayüze geri girdi.

## 6. Plan

Her aşamanın sonunda test süiti ve arayüz derlemesi geçmeli. Bir aşama geçmeden sonrakine başlanmaz.

### Aşama 0: Güvenceye alma (yarım gün)
- `data/assistant.db` ve `data/demo/assistant.db` dosyalarını proje dışına yedekleyin.
- Bugünkü çalışma ağacını, olduğu gibi, ayrı bir dala commit edin (örneğin `wip/kasim-ozellikler`). Amaç kaybetmemek; onaylamak değil.
- `.gitignore` dosyasına `data/pytest*`, `.playwright-mcp/`, `build/` ekleyin. `data/` altındaki test artıklarını silmek için sizin onayınız gerekir.
- Kabul: `git status` temiz, veritabanı özetleri değişmemiş.

### Aşama 1: Ses yolunu geri getirme (1 gün)
- K1: Çift seslendirmeyi kaldırın, testini ekleyin.
- K5: Sözcük listesiyle silmeyi ve virgül/katalog kuralını kaldırın. Enerji kapısını ve ipuçlarını ölçüme bağlayın.
- Y3: Otomatik model yüklemeyi ayara bağlayın; testlerde kapalı.
- Y4: Kalibrasyonu karşılamayı bekletmeyecek biçimde arka plana alın veya kapatın.
- Y1, Y2: Sabit süreleri ve yanlış etiketli ölçümü kaldırın.
- Kabul: `scripts.acoustic_benchmark --all` sonucu 6 Kasım değerlerinden (WER %18,70, CER %7,60, terim %48,04) kötü değil; karşılamada ilk ses 100 ms altında; `smoke_dialogue` bir randevu oluşturuyor.

### Aşama 2: Veri güvenliği (1–2 gün)
- K4: Çalışma anında veritabanı değiştirmeyi ve testini kaldırın.
- K2: Ertelemeyi tek işleme çevirin; onayda olumsuzu önce denetleyin; iki bilgili eşleşme şartı getirin.
- K3: Gelen çağrı bilgisini IP listesi ve gizli anahtarla koruyun.
- K6: Silmede tam eşleşme, en az uzunluk ve yürütme öncesi onay. Otomatik imha varsayılan olarak kapalı.
- Kabul: Bölüm 2'deki beş doğrulama senaryosu artık zararsız sonuç veriyor ve kalıcı test olarak süite ekli.

### Aşama 3: Kapsam kararı (yarım gün, karar sizin)
Her yeni özellik için üç seçenekten biri: tut, kapalı beklet, `experimental/` altına taşı.

| Özellik | Önerim | Gerekçe |
|---|---|---|
| Randevuya telefon alanı (göç 020) | Tut | Küçük, gerekli |
| Takvim ve sürükle-bırak erteleme (panel) | Tut, testlerini onar | İşlem güvenliği düşünülmüş; ama üç testi hiç çalışmıyor |
| Operatör "bugün" kutusu (göç 024) | Tut | Küçük, işe yarar |
| Twilio sağlayıcısı | Kapalı beklet | Gerçek hesapla denenmedi |
| Sesli iptal ve erteleme | Aşama 2'den sonra tut | Şu haliyle zararlı |
| İki araçlı randevu | Kapalı beklet | Tanıma doğruluğu düşükken hata üretir |
| KVKK silme ve otomatik imha | Kapalı beklet | Hukuki inceleme ve K6 düzeltmeleri gerekli |
| Supervisor ve FQICI | `experimental/` altına taşı | Canlı yola bağlı değil, modeli yok |
| Ardışık düzen görünümü (F0–F6) | Yalnızca ölçülen aşamalarla tut | Y1 |
| Demo/Reel düğmesi | Kaldır | K4 |

#### Aşama 3 kapsam kararı ve kullanım seçenekleri

- Kullanımda kalacak özellikler randevu telefon alanı, takvim, panelden erteleme, operatörün Bugün kutusu ve doğrulamalı sesli iptal/ertelemedir. Canlı ses paneli F2–F5 ölçüm noktalarını gösterir. Simülasyon kendi kaynak etiketiyle görüntülenir.
- Twilio, iki araçlı randevu, KVKK silme ve otomatik transkript imhası varsayılan olarak kapalıdır. KVKK saklama denetimi ve silme önizlemesi salt okunur kullanılabilir.
- Supervisor ve FQICI kendi modüllerinde geliştirilecek. Pilot kapsamı ve uygulama sırası için aşağıdaki seçeneklerden karar bekleniyor.

| Karar | Önerilen ilk kullanım | Alternatif |
|---|---|---|
| Supervisor | Yerel demo web görüşmelerinde gölge niyet yönlendirmesi ve operatör incelemesi. Karar kaydı müşteri yanıtını geciktirmeyecek şekilde ayrıştırıldıktan sonra pilot açılır. | Yalnızca çevrimdışı, insan etiketli görüşme setiyle başlayıp gölge pilota daha sonra geçmek. |
| FQICI | Önce kapanış kuyruğuna deterministik değerlendirme işçisi bağlamak. Demo web ve sentetik AudioSocket oturumlarında görüşme sonucu ile işlem kanıtını karşılaştırıp operatöre inceleme nedeni göstermek. | İlk teslimi kuyruk görünürlüğü, bekleme süresi ve hata sayılarıyla sınırlayıp değerlendirme işçisini sonraya almak. |
| Uygulama sırası | FQICI işçisi ve kuyruk gözlemi, ardından Supervisor gölge pilotu. | Her iki modül için önce ortak pilot veri seti ve operatör inceleme akışı hazırlamak. |

Supervisor için gölge pilot kabulü, mevcut diyalog yanıtlarının ve randevu işlemlerinin aynı kalmasını, ilk ses gecikmesinde regresyon olmamasını ve bağımsız insan etiketli sette kapsam dışı örneklerin ayrıca ölçülmesini gerektirir. FQICI için aynı kapanışın tekrar teslimi tek kalıcı değerlendirme üretmeli. Eksik işlem kanıtı bilinmiyor olarak görünmeli. Pilot veri saklama ve silme koşulları pilot açılmadan belirlenmeli. İki modülün varsayılan ayarları karar süresince kapalıdır.

### Aşama 4: Asıl sorun, terim doğruluğu (1–2 hafta)
- Sizin sesinizle ve gürültüde 50–100 cümlelik bir kayıt seti oluşturun. Bu, sizin girdinizi gerektirir.
- Bu setle temel ölçümü alın; sonra sırayla deneyin: katalog ipuçları açık/kapalı, ışın genişliği, tanıma sonrası katalog eşleştirme, sözlük okunuşları.
- Her denemeden yalnızca ölçümü iyileştireni tutun.
- Kabul: Terim doğruluğunda ölçülmüş, tekrarlanabilir artış. %95 eşiği bu PoC'ta ulaşılmaz olabilir; gerçekçi ara hedefi ilk ölçümden sonra belirleyin.

### Aşama 5: Yapıyı sadeleştirme (3–5 gün)
- `dialogue.py` içindeki niyet kurallarını tek bir sıralı tabloya toplayın: her niyet için kalıp, olumsuzluk denetimi, gereken durum ve test. Olumsuz ifade her zaman önce.
- Fiyat için tek kaynak belirleyin; asistan metni oradan üretilsin.
- Yutulan hataları günlüğe yazın.
- Tek diyalog beyni kararı: ya `dialogue.py` kalır ya Supervisor onun yerine geçer; ikisi birlikte yaşamasın.

### Aşama 6: Belgeleri gerçeğe çekme (yarım gün)
- Akustik ölçümü tam setle yenileyin, yönetici belgesini yeniden üretin.
- README, ARCHITECTURE ve VERIFICATION dosyalarına yalnızca tutulan özellikleri yazın.
- `asterisk/extensions.conf` dosyasına "doğrulanmadı" uyarısını geri koyun.

### Sonraya bırakılanlar
Gerçek SMS hesabı, Asterisk hattı, eşzamanlılık yükü, rol bazlı yetki, otomatik yedekleme. Bunlar Aşama 4 bitmeden değer üretmez.

## 7. Sizin kararınızı bekleyenler

1. Bugünkü çalışma ağacı ayrı bir dala commit edilsin mi (Aşama 0)?
2. `data/` altındaki test artıkları (yaklaşık 250 MB) ve iki göç denemesi veritabanı silinsin mi?
3. Supervisor ve FQICI için Aşama 3 tablosundaki pilot kapsamı ve uygulama sırası nasıl seçilsin?
4. KVKK otomatik imhası kapatılsın mı? Açık kalırsa, 27 Ekim tarihli demo görüşmeleri 26 Kasım'dan itibaren kalıcı olarak silinir (yalnızca sunucu demo modunda çalışırken).
5. Kendi sesinizle kayıt seti hazırlayabilir misiniz (Aşama 4)?

## 8. Bu incelemenin sınırları

- Arayüz sekmeleri tek tek elle gezilmedi; `OperatorPanel.tsx` (2.315 satır) ve `style.css` farkı satır satır okunmadı.
- `report_generator.py`, `operator_inbox.py`, `appointment_reschedule.py` ve FQICI kuyruğu yalnızca yüzeysel okundu; gözle görülen bir sorun çıkmadı.
- Twilio, Asterisk ve Ollama'lı Supervisor yolu çalıştırılmadı.
- Akustik karşılaştırma 56 cümlelik alt kümeyle yapıldı; tam set sonucu farklı olabilir.

Doğrulama betiği: `verify_findings.py` (oturumun geçici klasöründe; kalıcı teste dönüştürülmesi Aşama 2'nin parçasıdır).
