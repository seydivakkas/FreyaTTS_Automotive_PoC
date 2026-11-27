# Ürün ve kabul akışı

Leyla, müşterinin Türkçe konuşarak bir ekspertiz randevusu almasını sağlar. Operatör aynı işletmenin araç kataloğunu, hizmet fiyatını, saatlerini ve görüşme sonrasındaki işleri yönetir. İlk kurulumda işletme kayıtlarını operatör girer. Demo ayrı bir veri dizini kullanır ve panel bunu görünür kılar.

## Ürün sınırı

| Konu | Karar |
|---|---|
| Çalışma yeri | Tek Windows bilgisayar. Görüşme sırasında harici STT, LLM veya TTS hizmeti çağrılmaz. |
| Donanım | Referans: RTX 4070 Laptop, 8 GB VRAM. Tepe kullanım 7.478 MiB ölçüldü (yaklaşık 1.770 MiB'ı masaüstü uygulamalarıydı). Daha küçük kartta LLM katman sayısını düşürün. |
| Modeller | TTS: FreyaTTS (yerel kopya, `vendor/FreyaTTS`), CUDA. STT: faster-whisper `large-v3-turbo`, CUDA, float16. LLM: Ollama `qwen2.5:7b`, 8 GPU katmanı. VAD: Silero. |
| Kanallar | Tarayıcı mikrofonu (WebSocket) ve Asterisk AudioSocket (8 kHz PCM16). İkisi aynı diyalog motorunu kullanır. |
| Kullanıcılar | Müşteri (sesli), tek yönetici hesabı `admin` (panel). Rol ayrımı yoktur. |
| Dil ve saat | Arayüz ve konuşma Türkçe. Saklama UTC ISO 8601, gösterim ve konuşma `Europe/Istanbul`. Para kuruş tamsayısıyla saklanır, `TRY` gösterilir. |
| Eşzamanlılık | Yapılandırma üst sınırı 50 görüşme. Ölçüm yalnızca tek görüşmeyle yapıldı; web kanalı tek hat kilidiyle çalışır. |

## Özellik envanteri ve gerçeklik düzeyi

Yeni sürümde her ekranın durumunu panelde aynı etiketle gösterin. Etiketler: **Gerçek** (gerçek veri ve gerçek işlem), **Taklit** (varsayılan sağlayıcı sahte, dış dünyaya bir şey gitmez), **Statik** (koda gömülü tablo, canlı veri değil), **Kapalı** (bayrakla kapalı gelir), **Doğrulanmadı** (kod var, gerçek ortamda denenmedi).

| Sekme (gezinme kimliği) | Durum | Not |
|---|---|---|
| Görüşme | Gerçek | Gerçek modellerle uçtan uca randevu. İnsan sesiyle ve gürültüde ölçülmedi. Ses veri seti üreticisi bu sekmede. |
| Araç İçi DSP & Gürültü | Gerçek, ölçülmedi | Yüksek geçiren süzgeç, spektral bastırma, AGC, oda kalibrasyonu. Gürültüde tanımaya etkisi ölçülmedi. |
| A/B Test & İnce Ayar | Kısmen etkisiz | Canlı oturum ses tohumunu 9'a kilitler (`backend/session.py:88`). Arayüz 42, 77 ve 123 seçeneklerini sunmaya devam eder. Yeni sürümde ya kilidi kaldırın ya seçenekleri. |
| Sözlük | Gerçek | Telaffuz ve eş ad kuralları. |
| Otomotiv Ontolojisi | Doğrulanmadı | `backend/ontology/` ve MCP sunucusu. Bu paket hazırlanırken çalıştırılmadı. |
| Ses laboratuvarı | Gerçek | Normalizasyon ve sentez denemesi. |
| Ekspertiz Raporları | Gerçek | PDF üretimi, imzalı ve süreli müşteri bağlantısı. |
| Randevular | Gerçek | Takvim, önizlemeli taşıma, iptal. |
| Sıra & Lift Durumu | Gerçek | Varsayılan istasyon ve teknisyen kayıtları tohumlanır. |
| Araç Teşhis & OBD-II | Statik | SAE J2012 arıza kodu bilgi tabanı koda gömülü. |
| Araçlar ve fiyatlar | Gerçek | Asistanın kullandığı tek fiyat kaynağı bu olmalıdır. |
| Teknisyen Dikte | Gerçek, yerel değil | Tarayıcının `SpeechRecognition` hizmetini kullanır; çoğu tarayıcıda ses buluta gider. Arayüzde bunu belirtin. |
| Operatör (6002) | Taklit | AMI varsayılanı sahte istemcidir (`is_real=False`). Gerçek aktarım yoktur. |
| Giden Çağrılar | Taklit | Aynı sahte AMI. Kayıt "simüle" olarak görünmelidir. |
| Geçmiş | Gerçek | Görüşme ve tur kayıtları. |
| Bildirimler | Taklit | Varsayılan sahte sağlayıcı. Twilio sağlayıcısı kodda var, gerçek hesapla denenmedi ve bayrakla kapalı. |
| Supervisor Kalite | Kapalı | `SUPERVISOR_MODE=off`. Kullanılabilir eğitilmiş model yok (sentetik makro F1 0,333). |
| Analitik & KPI | Gerçek | Ölçüm yoksa "—" gösterilir. |
| Sistem | Gerçek | Model yükleme, hazırlık, ekran kartı durumu. |
| M01–M11 | Gerçek | M11 fiziksel telefon kabulü HOLD. |
| (servis) Araç değerleme | Statik | 2020 baz fiyat tablosu; canlı piyasa verisi değildir. |
| (servis) Arayan hafızası | Gerçek, riskli | Bkz. "Kopyalanmaması gereken davranışlar" K9. |
| (servis) KVKK silme, transkript imhası | Kapalı | `KVKK_ERASURE_ENABLED=false`, `AUTO_PURGE_TRANSCRIPTS=false`. Hukuki inceleme yapılmadı. |

## Ölçülmüş değerler (referans sürüm)

Yeni sürümün ilk kabulünde aynı yöntemle ölçün ve bu değerlerden kötü olmamasını hedefleyin. Ölçüm sentetik TTS sesiyle yapıldı; insan sesi değildir.

| Ölçüt | Değer | Kaynak ve tarih |
|---|---|---|
| Kelime hata oranı, telefon bandı | %18,07 | `scripts/acoustic_benchmark.py --all`, 320 cümle, 12.11.2026 |
| Karakter hata oranı, telefon bandı | %7,23 | aynı |
| Otomotiv terim doğruluğu, telefon bandı | %48,04 (eşik %95, **FAIL**) | aynı |
| Kelime / karakter / terim, stüdyo 48 kHz | %16,73 / %6,76 / %52,94 | aynı |
| Sentez gerçek zaman oranı (RTF) | ortalama 0,54, en kötü 2,59 | aynı |
| F0 medyanı | 284,3 Hz | aynı |
| Karşılamada ilk ses | ~15 ms (önceden sentezlenmiş) | `docs/measured-latency.json`, 06.11.2026, tek çalıştırma |
| İsim turu / araç turu / onay turu | ~1,4 s / ~3,2 s / ~3,2 s | aynı |
| LLM gerektiren tur | ~6 s (hedef 1,2 s) | aynı |
| STT | ~0,3–1,5 s | aynı |
| Ana kabul cümlesi | 6 denemenin 2'si geçti | aynı |

En çok kaçan terimler: Qashqai, TSI, TDI, Renault, TCe, Peugeot, dCi, TFSI, HDi, CDI, Citroën, Škoda. Bu, ürünün asıl kalite sorunudur.

## İlk uçtan uca teslim

1. Yönetici giriş yapar, araç ve ekspertiz hizmet bedeli tanımlar, İstanbul saatine göre ileri tarihli bir müsaitlik açar.
2. Müşteri web mikrofonunu açar. Panel tek kullanımlık bilet alır. Model yüklenirken durum bilgisi gösterir. Hat doluysa mevcut görüşme sürer.
3. Asistan marka/modeli katalogla eşler, eksik bilgiyi sorar, uygun saatleri numaralandırır. Eşleşmeyen araç ya da tanımsız fiyat için bilgi üretmez.
4. Müşteri seçenek belirtir. Asistan plaka ve randevu ayrıntılarını toplar, son teyidi ister. Açık onay alınana kadar saat seçimi taslaktır. Çakışmada başarı mesajı vermeden yeni seçim ister.
5. Kayıt başarıyla tamamlanınca referans söyler. Operatör randevuyu ve görüşme geçmişini görür. Aynı işlemin tekrarı ikinci randevu üretmemelidir.

### İlk teslimin kabul senaryoları

Her satırı otomatik teste çevirin. "Veri" sütunu testin sonunda veritabanında bakılacak durumdur.

| # | Verilen | Müşteri | Beklenen yanıt | Veri |
|---|---|---|---|---|
| A1 | Katalogda "Toyota Corolla 1.5", fiyatı 3.000 TL, saat 5 gün sonra 14.00 | "Corolla için ekspertiz randevusu istiyorum" | Saati gerçek tarihiyle söyler ("26 Kasım Perşembe 14.00"); "yarın" demez | Randevu yok |
| A2 | A1'in devamı, plaka verildi | "Evet, onaylıyorum" | Gerçek referans (`FRY-…`) | 1 randevu, `confirmed`, telefon ve plaka dolu |
| A3 | Aynı araç, fiyatı tanımsız | Fiyat sorar | Fiyatın tanımlı olmadığını söyler, operatöre yönlendirir | Randevu yok |
| A4 | Katalogda olmayan araç | "Tesla Model 3" | Aracın katalogda olmadığını söyler; model uydurmaz | Randevu yok |
| A5 | Onay sorusu soruldu | "Hayır, uygun değil" | Randevu oluşturmaz, başka saat önerir | Randevu yok |
| A6 | A2 tamamlandı | "Teşekkürler, iyi günler" | Vedalaşır; yeni bir referans veya "oluşturuldu" cümlesi kurmaz | Hâlâ 1 randevu |
| A7 | Aynı görüşmede onay iki kez gelir | "Evet onaylıyorum" ×2 | İkincisi yeni kayıt açmaz | 1 randevu |
| A8 | Seçilen saat bu arada doldu | Onay | Başarı demez, yeni saat sunar | Randevu yok |
| A9 | Hiç müsait saat yok | Randevu ister | Saat olmadığını söyler, geri arama kaydı açar | Takip kaydı var |
| A10 | Model yüklenmedi | Mikrofon açılır | "Modeller hazırlanıyor" durumu, sessiz bekleme yok | — |

## Bir sonraki teslimler

- **Telefon ve operatör.** Aynı diyalog motoruna AudioSocket bağla. Ses bölme, DTMF, kesme, bağlantı kopması ve hat kilidinin bırakılmasını test et. Aktarım ve geri arama kaydını santral sonucuyla ilişkilendir.
- **Atölye.** Randevu taşıma ve iptali, sıra ve lift, ekspertiz raporu, teknisyen diktesi, OBD-II ve kurumsal hesapları ilgili ekran ile veri kaydına bağla.
- **İletişim.** Gelen webhook, bildirim kuyruğu ve giden çağrı sonuçlarını kaydet. Taklit sağlayıcı sonucunu müşteriye gerçek teslimat olarak sunma.
- **Kalite ve yönetişim.** Sözlük, ontoloji, ses laboratuvarı, A/B, analitik, supervisor ve kalıcı inceleme kuyruğunu tamamla. Ölçüm bulunmayan metriği “—” göster. Çağrı sonrasında yapılan incelemenin canlı tur zamanlamasını bozmamasını doğrula.

## Dürüstlük kuralları

Referans sürüm bu kuralları birkaç kez çiğnedi ve geri düzeltti. Yeni sürümde baştan uygulayın ve her biri için test yazın.

1. Ölçülmeyen değer gösterilmez. Süre, oran veya skor yoksa "—" yazılır; sabit sayı "canlı" etiketiyle gönderilmez.
2. Çalışmayan bileşen adı arayüzde geçmez (ör. canlı yolda olmayan zaman ölçekleme, eğitilmemiş adaptör).
3. Taklit sağlayıcı varken asistan "SMS gönderiyorum", "aktarıyorum" demez. Aktarım başarısızsa "talebinizi kaydettim, sizi arayacağız" der ve takip kaydı açar.
4. Asistan katalogda olmayan araç, tanımsız fiyat, var olmayan saat veya oluşmamış randevu referansı söylemez.
5. Test ve demo verisi gerçek akışa sızmaz. Demo yalnızca başlangıç seçeneğidir; çalışan sunucuda veritabanı değiştirilmez.
6. Belgelerdeki her ölçüm tarih, donanım, yöntem ve örnek sayısıyla yazılır.

## Kopyalanmaması gereken davranışlar

02–13 arasındaki kod dökümleri bu hataları da içerir. Aşağıdakiler referans sürümde (commit `6273981`) bulunur. "Çalıştırıldı" satırları yalıtılmış geçici veritabanında denendi; "Okundu" satırları koddan çıkarıldı.

| # | Davranış | Yer | Kanıt | Doğrusu |
|---|---|---|---|---|
| K1 | Fiyat tanımsızken "2.500 TL" söylenir | `backend/dialogue.py:943`, `:1096`, `:1349` | Çalıştırıldı | Fiyat yoksa söyleme, operatöre yönlendir (A3) |
| K2 | Hangi gün olursa olsun "yarın" denir; saat çözülemezse "10.00" | `dialogue.py:976`, `:1003`, `:1015`, `:1094`, `:1347` | Çalıştırıldı: 5 gün sonraki saat için "Yarın 14.00" | Gerçek yerel tarih ve gün adı (A1) |
| K3 | Görüşme bitmişse (`done`) her söze "Randevunuz oluşturulmuştur. Referansınız TEST-001." | `dialogue.py:1025-1031` | Çalıştırıldı | İptal, ret veya hata ile bitmiş görüşmede bu cümle yanlıştır. Gerçek sonucu söyle (A6) |
| K4 | Test cümlelerine göre yazılmış özel dallar: yalnız "Toyota" denince "Toyota'nın modeli nedir?"; "saat dokuz" denince takvime bakmadan "09.00 dolu"; tetikleyici sözcük listesinde sabit model adları | `dialogue.py:899-922`, `:979` | Okundu | Genel kural: marka tek başına geldiyse katalogdaki o markanın modellerini sor; dolu/boş bilgisini takvimden oku |
| K5 | İlk boş saat tek seçenek olarak sunulur, numaralı seçenek yoktur | `dialogue.py:961-976` | Okundu | Üç seçeneği numaralandır (A1, 03 belgesi) |
| K6 | Konuşmada söylenen telefon veya plakayla arayan profili yüklenir, müşteri adı oradan alınır | `dialogue.py:1043-1066`, `backend/caller_memory.py` | Okundu | Profil yalnız doğrulanmış arayan numarasıyla (santral bilgisi) yüklenmeli; ad sesli teyit edilmeden kullanılmamalı |
| K7 | Arayan profili (ad, telefon, plaka, garanti, bakım geçmişi) KVKK silme kapsamında değil | `backend/kvkk_compliance.py` (CallerProfile geçmez) | Okundu | Profil, silme ve saklama süresine dahil edilmeli; açık rıza kaydı tutulmalı |
| K8 | A/B ses tohumu canlıda 9'a kilitli, arayüz başka tohum seçtiriyor | `session.py:88`, `ABTestingPanel.tsx:987` | Okundu | İkisinden biri |
| K9 | Gezinme ve kenar çubuğu donanım adını sabit yazar ("RTX 4070") | `nav.ts:206`, `SidebarNav.tsx:178` | Okundu | Sistem durumundan oku |
| K10 | Yüzlerce satırlık sıraya duyarlı düzenli ifade zinciri; olumlu sözcüğün olumsuzdan önce denetlendiği hata iki kez ortaya çıktı | `dialogue.py:1021-1648` | Okundu | Niyetleri tek bir sıralı tabloda tanımlayın; olumsuzluk her zaman önce; her niyetin testi olsun (03 belgesi) |
| K11 | Ekspertiz fotoğrafları kimlik doğrulamasız indirilebilir; koruma yalnız rastgele dosya adı | `backend/routers/crm.py:808` | Okundu | PDF'teki gibi Basic veya imzalı, süreli bağlantı |

Önceki incelemede bulunup referans sürümde düzeltilmiş olanlar (tekrar etmeyin): her cümlenin iki kez çalınması; erteleme isteğinde eski randevunun onaysız iptali; "hayır kalsın" yanıtının iptal sayılması; ad alt dizgisiyle başkasının randevusuna erişim; çalışan sunucuda demo/gerçek veritabanı değiştirme; konuşma tanımada sözcük listesiyle gerçek cümlelerin silinmesi; sabit süreli "canlı" telemetri; tek karakterle KVKK toplu silme; varsayılan açık otomatik transkript imhası.

## Sürüm farkı yaratabilecek kararlar

Eski README saklamayı yalnızca WAV temizliği olarak anlatır. Güncel kodda transkript saklama süresi (`TRANSCRIPT_RETENTION_DAYS`, 30 gün) ve varsayılanı kapalı otomatik temizlik bayrağı (`AUTO_PURGE_TRANSCRIPTS`) da bulunur. Yeni kurulumda bu iki politikayı ayrı yapılandırın ve otomatik imhayı hukuki onay olmadan açmayın. K1–K3 bu bölümün eski sürümünde öneri olarak geçiyordu; yukarıda çalıştırılarak doğrulandı ve kabul senaryosuna (A1, A3, A6) bağlandı.

## Kapsam dışı (yeni sürümde de bilinçli olarak yok)

- Rol bazlı yetki ve çok kullanıcılı denetim izi.
- Gerçek SMS/WhatsApp hesabı, gerçek Asterisk/SIP hattı (kod hazır, kabul HOLD).
- Eğitilmiş ses adaptörü (LoRA) ve eğitilmiş niyet modeli.
- Bulutta çalışma, çok şubeli işletme.
