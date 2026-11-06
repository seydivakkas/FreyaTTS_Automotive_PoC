# M01–M11 kaynak entegrasyonu — 1 Kasım 2026

## Kaynak seçimi ve izlenebilirlik

On bir ZIP bağımsız eklenti değildir; kümülatif sürümlerdir. M11, M01–M10’daki bütün `src/` yollarını içerir. M10 kaynakları ile M11’in karşılıkları aynıdır. Eski sürümlerden dosyaları üst üste yazmak yerine M11 kaynakları `automotive_voice/` paketi olarak alındı. Mevcut FastAPI backend, React arayüzü, modeller ve işletim veritabanı korundu.

`import-manifest.json` alınan dosyaların ZIP içindeki yollarını ve özgün SHA-256 değerlerini tutar. `archive-audit.json` on bir arşivin karmalarını, sürümler arasındaki farkları ve ana projeye uyarlanan dosyaları gösterir. Arşivler değiştirilmedi. Denetim `python -m scripts.audit_milestones` ile tekrarlanabilir.

Kaynak Markdown, kendi açıklamasına göre geliştirme anlatısına dayanıyor; ZIP ve fiziksel kabulü bağımsız çalıştırmış olduğunu söylemiyor. Buradaki test sonuçları bu bilgisayarda ayrıca üretildi.

## Canlı uygulamaya bağlanan parçalar

| Kaynak | Canlı bağlantı |
|---|---|
| M01 | Web ve AudioSocket’in kullandığı aynı `VoiceSession` içinde türlendirilmiş oturum/durum/üretim denetimi |
| M02 | Deterministik reducer ve flush korelasyon testleri korundu. AudioSocket’te olmayan PBX flush ACK’si üretilmedi; canlı yerel durum geçişleri M01 yöneticisinden yürür. |
| M03 | Gerçek SQLite rezervasyonunun önünde BookingStateMachine: awaiting → confirming → confirmed; belirsiz kayıt sonucu unknown ve operatör takibi |
| M04/M05 | Yönetim panelinde metin normalizasyonu, onay gereksinimi, korunan öbekler ve yan cümle sözleşmesi incelemesi |
| M06 | Gerçek çıkışta codec/örnekleme hızı ve 20 ms PCM çerçeve boyutu doğrulaması; mevcut gerçek AudioSocket protokolü korunur |
| M07 | Gerçek TTS/LLM çağrılarında sınırlı devre kesici; sentetik servisler canlı yolun dışında |
| M08 | Mevcut kimlik doğrulamalı panelde salt okunur kaynak gözlemleri ve ayrı SQLite inceleme günlüğü |
| M09 | Kaynak senaryo matrisi ve sentetik E2E regresyonları ayrı test grubunda |
| M10 | Canlı durum değişikliklerinde SQLite journal/outbox; yarım kalan oturumlar yeniden başlatmada fail-closed kapanır |
| M11 | Kabul CLI’si ve kanıt doğrulayıcıları korunur; fiziksel kabulün varsayılanı HOLD |

M04/M05 inceleme profili gerçek ses üretmez. Önceden var olan otomotiv TTS normalizer profili araştırma/deneme amacıyla korunur; A01-YT’de henüz fiziksel kanıtı bulunmayan marka okunuşları onaylanmış üretim sözlüğü olarak sunulmaz. İnceleme kararı kaynağı değiştirmez ve kendiliğinden canlı sözlüğe terfi ettirilmez.

## Uygulama ve işletim

`scripts/start.ps1`, yerel Ollama’ya ulaşamıyorsa kurulu `ollama serve` hizmetini gizli pencerede başlatır. Model yüklemesi tekilleştirilir; başarısız LLM bağlantısından sonra zaten yüklenmiş TTS/STT/VAD tekrar oluşturulmaz. Servis ve model yokluğu görünür hata olarak kalır.

Web mikrofonu ve gelen Asterisk çağrısı aynı konuşma ve rezervasyon motorunu kullanır. İşletim araçları/fiyatları/saatleri örnek ZIP fixture’larından otomatik doldurulmaz. Kaynak senaryolardaki FakeCRM/FakeBookingService canlı veritabanının yerine geçmez.

Canlı kontrol günlüğü işletim veritabanına göre ayrı dizinde tutulur: örneğin `data/assistant/sessions/<UUID>.sqlite3`. Olaylar ham transkript, müşteri adı veya ses taşımaz. Yerel olay otobüsünün teslim ACK’si, PBX tarafında sesin oynadığı veya temizlendiği anlamına gelmez. Yeniden başlatmada bekleyen randevu onayı veya dış yan etki tekrar yürütülmez; önceki aktif görüşmeler takip durumuna alınır.

Eski M08 konsolu yalnızca kaynak sentetik denemeleri için modül olarak korunmuştur. Canlı operatör arayüzü mevcut React panelindeki **M01–M11** sekmesidir. Eski raporlar `docs/milestones/reference/` altında arşivdir; M08 kaynak regresyonlarının beklediği salt okunur rapor kopyaları `data/reports/` altında bulunur. Bunlar yeni fiziksel başarı kanıtı değildir.

## Uyarlamalar

- Testler `tests/milestones/` altına alındığı için proje kök yolları düzeltildi; pytest importlib modu ile aynı adlı eski/yeni testler çakışmaz.
- `/mnt/data/...` biçimindeki eski karşılaştırma yolu yerine özgün 320 durumluk golden dosyanın sabit SHA-256 denetimi korunur.
- Kaynak A01-YT adaptörü ve Windows testlerinde SQLite bağlantıları açık kalmayacak şekilde kapatıldı.
- Yeni paket yerleşimine bağlı M11/operatör CLI kök yolları düzeltildi.
- Silero VAD çıkarımı `inference_mode` ile yapılır; uzun görüşmede autograd grafiği biriktirilmez.

## Doğrulama komutları

Birleşik regresyonda **496 test ve 44 alt test** geçti. Masaüstü (1440 px) ve mobil (390 px) panel, yeni M01–M11 sekmesi ve metin inceleme akışı Chromium’da doğrulandı. TypeScript/Vite derlemesi ve Alembic şema kontrolü geçti.

Gerçek model denemesinde bileşik “Ada Yılmaz / Volkswagen Passat” sanal mikrofon girdisi hatalı geri tanındı; asistan yeterli alanları elde edemedi ve randevu oluşturmadı. Bu deneme başarısız kabul kaydıdır; yanlış tanınan araç için kayıt yapılmaması güvenlik davranışıdır. Daha basit, alanların ayrı söylendiği bir senaryo ayrı değerlendirilir; bu ayrım marka doğruluğu sorununu ortadan kaldırmaz.

```powershell
.venv\Scripts\python -m pytest -q --basetemp=data/pytest
.venv\Scripts\python -m alembic check
.venv\Scripts\python -m scripts.audit_milestones
.venv\Scripts\python -m scripts.voice_acceptance
.venv\Scripts\python -m automotive_voice.m11 --folder data/m11/current report
```

Son komut mevcut kanıtı raporlar; eksik fiziksel kapıları PASS yapmaz. İnsan mikrofonu, insan dinlemesi ve gerçek Asterisk/PBX izleri ayrıca doğrulanmalıdır.

## Gerçek adaptörle sanal mikrofon sonucu

Kayıtlı araç adları STT’ye `initial_prompt`/`hotwords` olarak verildi; çıktı metni sonradan bir araç adına zorlanmadı. Bu değişiklikten sonra Renault Megane senaryosunda gerçek faster-whisper → Ollama → FreyaTTS ve web mikrofon taşıması üzerinden açık onayla **tek randevu** oluştu. `live-voice-results.json` yerel test veritabanının transkript ve ölçümlerini içerir. Girdi FreyaTTS ile üretilmiş sanal müşteri sesidir; insan mikrofonu değildir. Son teyit sesinin fiziksel duyulması, telefon hattı ve tüm marka/modeller bu testle kabul edilmiş sayılmaz.

Son teyit mesajına kayıtlı araç adı da eklendi; kullanıcı tanınan aracı ve saati onaydan önce kontrol edebilir. Belirsiz rezervasyon sonucu onaylanmış gibi sunulmaz; kapanış hatası tek görüşme kapasitesini kilitlemez. Her iki davranış regresyon kapsamındadır.

M11 raporlayıcısında `legacy_regression=PASS`, fiziksel kapılarda `HOLD` elde edildi. `current-acceptance.json` ve `current-acceptance.html` güncel rapor kopyalarıdır. Eski paket raporlarıyla karıştırılmamalıdır.
