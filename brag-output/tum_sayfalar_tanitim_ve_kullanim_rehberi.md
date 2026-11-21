# FreyaTTS Automotive Cockpit — Tüm Sayfalar Tanıtım ve Kullanım Rehberi

<!--
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
-->

Bu rehber, **FreyaTTS Automotive Cockpit** bünyesindeki 4 ana operasyonel kategoriye dağılmış **20 bağımsız modül ve sayfanın** teknik mimarisini, arka uç bağlantılarını, görsel arayüzünü ve adım adım kullanımını kapsamaktadır.

---

## 🎛️ Bölüm 1: Ses & Yapay Zekâ Hattı (F₀–F₆ Nöral Boru Hattı)

### 1. Görüşme Kokpiti (VoiceTab)
* **Ekran Görüntüsü:** [01_gorusme_kokpiti.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/01_gorusme_kokpiti.png)
* **Aşama:** F₀–F₆ Uçtan Uca Hat
* **Arka Uç Bağlantısı:** `WebSocket /ws/voice` ↔ `backend/session.py` (Metin modu için `POST /api/voice/chat-turn`)
* **İşlevi:** Canlı mikrofon veya WebRTC SIP çağrısı üzerinden müşteriyle konuşan ana arayüzdür. 214ms TTFA (Time-to-first-audio) gecikmesiyle çalışır.
* **Nasıl Kullanılır?**
  1. Sağ üstteki **[Görüşmeyi Başlat]** butonuna tıklayın. Mikrofon izni verildiğinde SIP/6001 oturumu açılır; donanım kilitliyse otomatik metin moduna geçer.
  2. Müşteri sesli konuştuğunda canlı dalga formu titreşir; transkript anında ekrana düşer.
  3. Alternatif olarak alttaki **Hızlı Müşteri Sorusu Simülasyon Çipleri**ne (*"Fren balatası değişimi ne kadar sürer?"*) tıklanarak veya metin kutusuna yazılarak asistan Leyla tetiklenir.
  4. Sağdaki bilgi panelinden çıkarılan niyet (`intent`) ve istasyon ataması gerçek zamanlı izlenir.

---

### 2. Araç İçi DSP & Gürültü Paneli (CarDenoiserPanel)
* **Ekran Görüntüsü:** [02_arac_ici_dsp.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/02_arac_ici_dsp.png)
* **Aşama:** F₀ Giriş Süzgeci
* **Arka Uç Bağlantısı:** `POST /api/dsp/process` ↔ `backend/routers/audio_dsp.py`
* **İşlevi:** Araç seyir halindeyken oluşan motor uğultusu (sub-bass), rüzgâr ve tekerlek sürtünme seslerini temizler.
* **Nasıl Kullanılır?**
  1. Test alanından **Kabin Simülasyonu**nu (Şehir İçi 50km/s, Otoyol 120km/s) seçin.
  2. 120 Hz Butterworth Yüksek Geçiren Filtre (HPF) ve Spektral Çıkarım eşiğini ayarlayın.
  3. Gürültülü ham ses ile filtrelenmiş sesin SNR (+14.8 dB) farkını spektrum grafiğinden kıyaslayın.

---

### 3. A/B Test & ASR Ayarı (ABTestingPanel)
* **Ekran Görüntüsü:** [03_ab_test_ayari.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/03_ab_test_ayari.png)
* **Aşama:** F₁ (VAD) & F₂ (ASR)
* **Arka Uç Bağlantısı:** `GET /api/ab/experiments` & `POST /api/ab/evaluate` ↔ `backend/ab_testing.py`
* **İşlevi:** Farklı konuşma tanıma (Faster-Whisper large-v3-turbo vs distil-whisper) ve VAD modellerini karşılaştırarak WER (Kelime Hata Oranı) ölçümü yapar.
* **Nasıl Kullanılır?**
  1. Deney listesinden aktif varyantı (Kontrol A vs Test B) seçin.
  2. Akustik test cümlesini çalıştırarak transkripsiyon gecikmesi (ms) ve Z-Test istatistiksel güven aralığını gözlemleyin.

---

### 4. Sözlük & Fonetik Paneli (LexiconPanel)
* **Ekran Görüntüsü:** [04_sozluk_fonetik.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/04_sozluk_fonetik.png)
* **Aşama:** F₄ Normalizasyon & Sezer Chunker
* **Arka Uç Bağlantısı:** `GET /api/lexicon` & `POST /api/lexicon/entry` ↔ `config/lexicon.json`
* **İşlevi:** Yabancı veya kısaltma otomotiv terimlerinin (Quattro, TSI, dCi, OBD, triger, amortisör) Türkçede doğru telaffuz edilmesini sağlar.
* **Nasıl Kullanılır?**
  1. Terim arama kutusuna örneğin `Quattro` yazın.
  2. Fonetik karşılığını (`kı-vat-ro`) ve TTS okunuşunu dinleyin.
  3. Yeni bir teknik terim ekleyip **[Fonetik Kuralı Kaydet]** butonuna basarak tüm hatta anında uygulayın.

---

### 5. Otomotiv Ontolojisi Paneli (OntologyPanel)
* **Ekran Görüntüsü:** [05_otomotiv_ontolojisi.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/05_otomotiv_ontolojisi.png)
* **Aşama:** F₃–F₄ Bilgi Grafı (Graph Knowledge)
* **Arka Uç Bağlantısı:** `GET /api/ontology/schema` ↔ `backend/ontology/`
* **İşlevi:** Araç segmentleri (B-Hatchback, C-SUV), şanzıman türleri (DSG, EAT8, Manuel) ve servis paketleri arasındaki ilişkisel bağı yönetir.
* **Nasıl Kullanılır?**
  1. Sol menüden araç modelini seçin (örneğin *Peugeot 3008 1.5 BlueHDi*).
  2. Ontoloji grafında motora bağlı parçaları, önerilen bakım periyotlarını ve işçilik sürelerini inceleyin.

---

### 6. Ses Laboratuvarı (LabTab)
* **Ekran Görüntüsü:** [06_ses_laboratuvari.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/06_ses_laboratuvari.png)
* **Aşama:** F₅ Nöral ODE Akustik Sentezleyici & F₆ İletim
* **Arka Uç Bağlantısı:** `POST /api/tts/synthesize` ↔ `backend/routers/text_speech.py`
* **İşlevi:** FreyaTTS Leyla kadın sesi motorunun perde, konuşma hızı (WSOLA) ve batched ODE çıkarım parametrelerini test etme laboratuvarıdır.
* **Nasıl Kullanılır?**
  1. Metin giriş alanına özel bir otomotiv anons cümlesi yazın.
  2. Ses hızı (0.8x - 1.4x) ve perde kaydırıcılarını ayarlayın.
  3. **[Nöral Sentezle]** butonuna tıklayarak doğrudan WAV ses çıktısını hoparlörden dinleyin ve gecikmeyi ölçün.

---

## 🚗 Bölüm 2: Ekspertiz & Atölye Operasyonları

### 7. Ekspertiz Raporları (InspectionPanel)
* **Ekran Görüntüsü:** [07_ekspertiz_raporlari.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/07_ekspertiz_raporlari.png)
* **Arka Uç Bağlantısı:** `GET /api/inspections` & `POST /api/inspections/generate-pdf` ↔ `backend/report_generator.py`
* **İşlevi:** Tamamlanan ekspertizlerin TSE-HYB uyumlu PDF raporlarını üretir, motor/mekanik/kaporta kondisyon skorlarını sunar.
* **Nasıl Kullanılır?**
  1. Listeden araç plakasını seçin.
  2. Boya/değişen şemasını, OBD hata dökümünü ve dyno test sonuçlarını inceleyin.
  3. **[PDF Rapor Üret]** veya **[WhatsApp ile Müşteriye İlet]** aksiyonunu tetikleyin.

---

### 8. Randevu Takvimi (AppointmentsTab)
* **Ekran Görüntüsü:** [08_randevu_takvimi.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/08_randevu_takvimi.png)
* **Arka Uç Bağlantısı:** `GET /api/appointments` & `POST /api/appointments` ↔ `backend/routers/scheduling.py`
* **İşlevi:** Asistan Leyla'nın telefon görüşmelerinde otomatik oluşturduğu servis ve ekspertiz randevularını takvim üzerinde gösterir.
* **Nasıl Kullanılır?**
  1. Günlük/haftalık takvim görünümünde rezerve slotları inceleyin.
  2. Randevu üzerine tıklayarak müşteri adı, plaka, atanan lift ve öngörülen bakım paketini görüntüleyin.
  3. Sürükle-bırak ile randevu saatini revize edin veya iptal durumunu güncelleyin.

---

### 9. Sıra & Lift Durumu (QueueLiftPanel)
* **Ekran Görüntüsü:** [09_sira_lift_durumu.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/09_sira_lift_durumu.png)
* **Arka Uç Bağlantısı:** `GET /api/workshop/lifts` ↔ `backend/lift_bay_capacity_scheduler.py`
* **İşlevi:** Atölyedeki 4 ana lift istasyonunun (Lift-1 Mekanik, Lift-2 Ağır Bakım, Lift-3 Ekspertiz, Lift-4 Hızlı Servis) anlık doluluğunu yönetir.
* **Nasıl Kullanılır?**
  1. Canlı lift doluluk kartlarını kontrol edin.
  2. Bekleme kuyruğundaki araçları uygun istasyona atayın.
  3. Bakımı tamamlanan aracı **[Teslime Gönder]** diyerek lifti bir sonraki randevu için boşa çıkarın.

---

### 10. Araç Teşhis & OBD-II (DiagnosticPanel)
* **Ekran Görüntüsü:** [10_arac_teshis_obd2.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/10_arac_teshis_obd2.png)
* **Arka Uç Bağlantısı:** `GET /api/diagnostics/dtc/{code}` ↔ `backend/diagnostics.py`
* **İşlevi:** OBD-II cihazından gelen standart DTC hata kodlarını (P0300, P0420 vb.) açıklar ve kritik emniyet kurallarını tetikler.
* **Nasıl Kullanılır?**
  1. Hata kodu kutusuna `P0300` yazıp sorgulayın.
  2. Sistem "Silindir Ateşleme Teklemesi" teşhisini, katalitik konvertör hasar riskini ve çekici gereksinimini listeler.
  3. M06 Emniyet Kilidinin devreye girip müşteriye aracı sürmeme tavsiyesi verdiğini doğrulayın.

---

### 11. Araç Kataloğu & Fiyatlar (VehiclesTab)
* **Ekran Görüntüsü:** [11_arac_katalog_fiyatlar.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/11_arac_katalog_fiyatlar.png)
* **Arka Uç Bağlantısı:** `GET /api/vehicles` & `POST /api/quotes` ↔ `backend/routers/crm.py`
* **İşlevi:** Servis veritabanındaki kayıtlı araçları, kasko değerlerini ve sabit paket fiyatlarını (M01 Kilitli Fiyat) yönetir.
* **Nasıl Kullanılır?**
  1. Araç listesinden marka/model seçin (örneğin *Fiat Egea 1.6 Multijet*).
  2. Standart periyodik bakım paket fiyatını, parça maliyetlerini ve indirim kurallarını görüntüleyin.

---

### 12. Teknisyen Dikte (TechnicianDictationPanel)
* **Ekran Görüntüsü:** [12_teknisyen_dikte.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/12_teknisyen_dikte.png)
* **Arka Uç Bağlantısı:** `POST /api/technician/dictate` ↔ `backend/technician_dictation.py`
* **İşlevi:** Atölye ustalarının elleri kirliyken mikrofonla söyledikleri araç kusurlarını metne döker ve iş emrine ekler.
* **Nasıl Kullanılır?**
  1. **[Dikteyi Başlat]** butonuna basın ve araç başındayken konuşun (*"Sağ ön salıncak burcu aşınmış, sol amortisörde yağ sızıntısı var"*).
  2. Faster-Whisper Türkçe ASR ile ses yazıya dökülür ve ilgili iş emri kartına otomatik eklenir.

---

## 📞 Bölüm 3: Telefoni & Santral Entegrasyonu

### 13. Operatör Kokpiti - Dahili 6002 (OperatorPanel)
* **Ekran Görüntüsü:** [13_operator_kokpiti.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/13_operator_kokpiti.png)
* **Arka Uç Bağlantısı:** `GET /api/operator/calls` & `POST /api/operator/intervene` ↔ `backend/ami.py`
* **İşlevi:** Asistan Leyla'nın yürüttüğü aktif görüşmeleri çağrı merkezi operatörünün canlı izlemesini (listen-in), operatör fısıltısını (whisper) ve çağrıyı devralmasını (barge-in) sağlar.
* **Nasıl Kullanılır?**
  1. Aktif çağrı listesinde konuşma süresi ve anlık duygu skorunu izleyin.
  2. İhtiyaç halinde **[Fısılda]** butonuna basarak müşteriye duyurmadan sadece Leyla'ya talimat iletin veya **[Çağrıyı Devral]** diyerek görüşmeyi operatör kulaklığına aktarın.

---

### 14. Giden Çağrılar - Outbound (OutboundPanel)
* **Ekran Görüntüsü:** [14_giden_cagrilar.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/14_giden_cagrilar.png)
* **Arka Uç Bağlantısı:** `POST /api/outbound/campaign` ↔ `backend/outbound_dialer.py`
* **İşlevi:** Randevu teyidi, bakım zamanı gelen araç sahiplerini arama veya ekspertiz sonrası memnuniyet anketi için otomatik arama kampanyaları düzenler.
* **Nasıl Kullanılır?**
  1. Kampanya tipini seçin (*"1 Gün Önce Randevu Hatırlatma"*).
  2. Aranacak müşteri listesini yükleyin ve arama saat aralığını belirleyin.
  3. **[Kampanyayı Başlat]** butonuna tıklayın; Asterisk AMI üzerinden aramalar sırayla başlatılır.

---

### 15. Görüşme Geçmişi (HistoryTab)
* **Ekran Görüntüsü:** [15_gorusme_gecmisi.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/15_gorusme_gecmisi.png)
* **Arka Uç Bağlantısı:** `GET /api/conversations` ↔ `backend/routers/telephony.py`
* **İşlevi:** Gerçekleşen tüm geçmiş çağrıların ses kayıtlarını, diyalog transkriptlerini, niyet çıkarımlarını ve F0–F6 gecikme metriklerini arşivler.
* **Nasıl Kullanılır?**
  1. Arama kutusundan plaka veya telefon numarasıyla filtreleme yapın.
  2. Çağrı detayında görüşme kaydını dinleyin ve KVKK maskelemesinin (PII redaction) uygulandığını teyit edin.

---

### 16. Bildirimler & WhatsApp (NotificationPanel)
* **Ekran Görüntüsü:** [16_bildirimler_whatsapp.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/16_bildirimler_whatsapp.png)
* **Arka Uç Bağlantısı:** `POST /api/whatsapp/webhook` ↔ `backend/whatsapp_webhook.py`
* **İşlevi:** Çift yönlü WhatsApp mesajlaşması, randevu konumu gönderimi ve TSE ekspertiz raporlarının PDF teslimatını yönetir.
* **Nasıl Kullanılır?**
  1. Gelen mesaj akışında müşterinin WhatsApp yanıtlarını izleyin.
  2. Müşteriye servis adresi ve canlı yol tarifi linkini tek tıkla şablon mesaj olarak gönderin.

---

## 🛡️ Bölüm 4: Gözetim, Güvenlik & Sistem

### 17. Supervisor & FQICI Kalite Paneli (SupervisorPanel)
* **Ekran Görüntüsü:** [17_supervisor_fqici.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/17_supervisor_fqici.png)
* **Arka Uç Bağlantısı:** `GET /api/quality/overview` ↔ `backend/supervisor/`
* **İşlevi:** Görüşmeleri 5 temel boyutta (FQICI: Doğruluk, Nezaket, Güvenlik, Niyet Yakalama, Çözüm Hızı) yapay zekâ denetimine tabi tutar.
* **Nasıl Kullanılır?**
  1. Kalite panosundaki FQICI Genel Skorunu (%94.2) inceleyin.
  2. 22 farklı niyet kategorisinin yönlendirme başarı oranlarını ve olası sapmaları denetleyin.

---

### 18. Analitik & KPI Paneli (AnalyticsPanel)
* **Ekran Görüntüsü:** [18_analitik_kpi.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/18_analitik_kpi.png)
* **Arka Uç Bağlantısı:** `GET /api/analytics/kpi` ↔ `backend/analytics.py`
* **İşlevi:** Çağrı tamamlama oranları, ortalama ilk ses gecikmesi (TTFA: p50/p95/p99) ve randevuya dönüşüm yüzdelerini görselleştirir.
* **Nasıl Kullanılır?**
  1. Haftalık veya aylık zaman aralığını seçin.
  2. Gecikme bütçesi dağılımını (F0-F6 breakdown) ve müşteri memnuniyet (CSAT) tahminini raporlayın.

---

### 19. Sistem & Donanım Sağlığı (SystemTab)
* **Ekran Görüntüsü:** [19_sistem_sagligi.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/19_sistem_sagligi.png)
* **Arka Uç Bağlantısı:** `GET /api/health` ↔ `backend/routers/core_system.py`
* **İşlevi:** NVIDIA GPU VRAM kullanımı, CUDA çekirdek sıcaklığı, Ollama LLM çalışma durumu ve Asterisk PBX bağlantısını canlı izler.
* **Nasıl Kullanılır?**
  1. GPU sıcaklığı ve VRAM barını kontrol edin.
  2. Model yükleme/boşaltma durumunu kontrol ederek yedek sunucuya geçiş (failover) mekanizmasını test edin.

---

### 20. M01–M11 Kalite ve Emniyet Kapıları (MilestonePanel)
* **Ekran Görüntüsü:** [20_m01_m11_kapilari.png](file:///c:/Users/seydieryilmaz/Desktop/FreyaTTS_Automotive_PoC/brag-output/screens/20_m01_m11_kapilari.png)
* **Arka Uç Bağlantısı:** `GET /api/milestones` ↔ `backend/milestones.py`
* **İşlevi:** Sistemin üretim öncesi 11 zorunlu kurumsal güvenlik ve kalite kapısını (M01 Sabit Fiyat, M02 KVKK Redaction, M06 Çekici Emniyeti, M08 Fısıltı vb.) denetler.
* **Nasıl Kullanılır?**
  1. 11 kapının yeşil onay durumunu (`PASSED`) inceleyin.
  2. Herhangi bir kapıda simülasyon testi çalıştırarak olası güvenlik açıklarının sisteme sızmasını önleyin.
