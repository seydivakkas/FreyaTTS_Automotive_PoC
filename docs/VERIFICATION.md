> Bu dosya 31 Ekim ilk sürüm kaydıdır. 1 Kasım M01–M11 entegrasyonu, 496 test ve sanal mikrofon sonucu için [güncel entegrasyon kaydına](milestones/INTEGRATION.md) bakın.

# Doğrulama kaydı — 31 Ekim 2026

Bu dosya tamamlanan kontrolleri gerçek donanım/telefon doğrulamasından ayırır. Önceki PoC WAV dosyaları yeni uygulamanın başarılı çalıştığının kanıtı sayılmaz.

## Geçen kontroller

- Python 3.11.15 ortamı oluşturuldu; SQLite Alembic başlangıç migration’ı uygulandı.
- 29 backend testi geçti: dört otomotiv ifadesi, tarih/saat/plaka, para ve ek uyumu, desteklenmeyen karakter, sayı/motor öbeği sınırları, yeniden örnekleme, son çerçevenin korunması, parçalı AudioSocket paketi, bağlantı kesilmesi, pacing, açık onay, tekrar gönderim, saat çakışması, iptal, kimlik doğrulama, tek kullanımlık WebSocket bileti, sentez kuyruğu/iptal, eski turun sesinin engellenmesi ve sonraki parçanın önceden sentezlenmesi.
- React TypeScript kontrolü ve Vite üretim derlemesi geçti.
- Chromium’da 1440 ve 390 piksel görünüm testleri geçti. Giriş ve altı yönetim ekranı açıldı; normalizasyon sonucu görüldü; yatay taşma kontrol edildi. Mobil ekran görüntüsü ayrıca görsel olarak incelendi.
- Gerçek yerel `qwen2.5:7b` ile alan çıkarımı ve randevu akışı izole SQLite veritabanında tamamlandı. Kayıtlı fiyat yokluğu açıkça aktarıldı; onaydan sonra yalnızca bir randevu oluştu.

## Ölçülen Ollama süreleri

| İşlem | İlk token | Tam yanıt |
|---|---:|---:|
| İlk istek, soğuk model | 65.656 ms | 69.750 ms |
| Sonraki istek | 328 ms | 1.609 ms |

Bunlar tek çalıştırmanın ölçümleridir; SLA veya p95 değildir. LLM modeli 8 GPU katmanı ve 4096 bağlamla CPU/GPU arasında paylaşıldı. Uygulamanın model yükleme akışına ilk görüşmeden önce Ollama ısıtması eklendi. İşlem onayı LLM çağrısı gerektirmez. Ölçüm ham çıktısı `data/dialogue-smoke.json` dosyasındadır.

## Donanım ve kalan doğrulamalar

- RTX 4070 Laptop GPU, 8188 MiB VRAM görüldü.
- PyTorch 2.8.0+cu128 kuruldu ve CUDA kullanılabilirliği doğrulandı. FreyaTTS, AudioVAE, faster-whisper small/int8 ve Silero gerçek modelleri yüklendi.
- Dört araştırma cümlesinde ikişer gerçek çalışma yapıldı. Son çalışmada model hazırlığı 9.484 ms sürdü. Sıcak sentez kısa cümlelerde 618–666 ms, bölünmüş karmaşık cümlede 1.923 ms; RTF 0,135–0,145 aralığındaydı. STT 1.712–2.460 ms sürdü. Bunlar tek donanımdaki örnek ölçümlerdir, dağılım veya SLA değildir.
- `benchmark-results.json` ham TTS/STT ölçümlerini ve geri tanınan metinleri içerir. Marka/model ve kısaltma ifadelerinde önemli geri tanıma hataları ve tekrarlar görüldü. Bu deney TTS ve STT’yi birlikte sınar; hatayı yalnızca bir modele atfetmez. Telaffuz ve doğallık için insan dinleme kabulü henüz geçilmiş değildir.
- Gerçek mikrofonla insan tarafından tamamlanan sesli randevu henüz doğrulanmadı. Ekran testleri bu sesli kabul testinin yerine geçmez.
- WSL Ubuntu 22.04 mevcut; `asterisk` yürütülebilir dosyası kurulu değil. Gerçek Asterisk dahili araması ve SIP hattındaki duyulabilir söz kesme gecikmesi bu ortamda doğrulanmadı.
- Telefon protokolü birim testleri gerçek PBX, ağ jitter’ı veya uçtan uca ses kalitesini kanıtlamaz.

## Tekrarlama

README içindeki test, `scripts.smoke_dialogue` ve `scripts.benchmark` komutlarını kullanın. Tarayıcı testleri çalışan backend ister. Gerçek ses denemesinde önce araç ve gelecek saat kaydı girin; model yükleyin; mikrofonla randevuyu tamamlayın. Ardından transkript, randevu ve gecikme ölçümlerini inceleyin.

Asterisk doğrulaması için dialplan’a 700 dahilisini ekleyin, UUID ve AudioSocket modüllerini kontrol edin, izin listesini düzenleyin ve bir SIP softphone ile arayın. Cümle başı/sonu, kullanıcı söz kesmesi, sessizlik, kapatma ve yeniden arama senaryolarını ayrı dinleyin.
