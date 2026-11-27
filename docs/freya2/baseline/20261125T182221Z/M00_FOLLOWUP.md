# M00 takip doğrulaması

- İzole çalışma kopyasında uygulama içe aktarıldı. Lifespan, model çıkarımı ve dış bağlantılar başlatılmadan 243 kayıtlı HTTP/WebSocket rota girdisi ve 223 OpenAPI yolu çıkarıldı. OpenAPI, istek/yanıt şemalarını içerir. Rota listesi bağımlılık adlarını içerir.
- TSX taramasında 130 doğrudan çağrı noktası bulundu. Yol şekli eşleşmeleri ve açık kayıtlar UI_API_BINDINGS.json dosyasında. Sonuç: 130 rota eşleşmesi. Altı birleştirilmiş yol elle doğrulandı. Bu tarama dinamik çağrıları ve yetkinin davranışsal doğrulamasını kapsamaz.
- Web, tek kullanımlık oturum biletiyle açılır. `backend/main.py:198–221` mono PCM16 ve 8/16/24/44,1/48 kHz giriş kontrolünü yapar.
- AudioSocket, `backend/audiosocket_server.py:425,492–521` üzerinden 8 kHz ve 20 ms pacing kullanır. `backend/session.py:1002–1034` çıkışı kanal hızına çevirir ve eski nesli uygulama sınırında engeller.
- `backend/session.py:465–483` kısmi altyazı yayınlar. Final ses ve doğrudan metin girişleri farklı işleyicilerden Supervisor veya Dialogue'a ulaşır. `backend/session.py:534–567,632–694`.
- Model varsayılanları ve yerelde erişilebilen Silero dosyasının doğrulaması MODEL_REFERENCES.json içinde. Diğer model kimlikleri etkin çalışma zamanı örneğinden doğrulanmadı.

## Karar

M00 HOLD. Uygulama rota kaydı ve kısmi UI eşlemesi doğrulandı. Kritik UI yetki ve iş işlemi eşlemesi, ortamda seçilen model kimlikleri ve kanal regresyonları açık. G4/G5 ve fiziksel oynatma değerlendirilmedi.

## Mevcut çekirdek ve uyumluluk

- `automotive_voice/core/` ses ve olay tiplerini, kimlikleri, iptali ve oturum yöneticisini içeriyor. `contracts/` mevcut JSON Schema yüzeyi. `tests/milestones/test_m01.py` ve sonraki milestone sözleşme testleri M01 uyumluluk değerlendirmesinin girdileri.
- Canlı iki giriş `backend/session.py` içindeki VoiceSession üzerinde birleşiyor. VoiceSession yerel oynatma nesli ile kontrol neslini ayrı ayrı kontrol ediyor. Yeni M01 tasarımında mevcut şemalar ve canlı sınır için eşleme çıkarılmalı. Yeniden kullanılabilecek tipler belirlenmeden ikinci çekirdek tasarlanmasın.
- Varsayılan Hugging Face ve Ollama dizinlerinde yerel önbellek adayları görüldü. Etkin ortamın hangi kopyayı seçtiği henüz doğrulanmadı.

## Randevu yazma sınırı

- `backend/routers/crm.py:1025–1044` HTTP Basic bağımlılığıyla randevu oluşturma ve iptal işleyicilerini korur. Oluşturma `book` üzerinden rezervasyon yapar ve saat çakışmasını HTTP 409'a çevirir.
- `backend/routers/crm.py:1047–1118` değişiklik önizlemesini okuma uç noktasında hesaplar. Yazma aşaması `BEGIN IMMEDIATE` ile açılır, hedefin uygunluğunu yeniden değerlendirir ve gönderilmiş önizleme sürümünü kontrol eder.
- `backend/dialogue.py:1457–1520` sesli randevu akışında açık onayı değerlendirir ve başarılı kayıt sonucunu işaretler. HTTP yazma yetkisiyle sesli onay ayrı giriş sözleşmeleridir.

## Kanal regresyonu

Birleşik oturum ve codec testi 75 saniye sınırına ulaştı. İzole tekrar çalıştırmada medya biçimi ve AudioSocket paket/ön tampon sözleşmesi için 2 test geçti, 3 test seçilmedi. Oturum süitinin sonucu açık. Kanıt: evidence/m00/20261125T182221Z/SESSION_CODEC_REGRESSION.json.
