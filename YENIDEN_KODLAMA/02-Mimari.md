# Mimari ve alt sistemler

Aşağıdaki bölümler sürümün proje içi belgeleridir. İçlerindeki kaynak yolları eski depo düzenini gösterir. Ölçümler önceki çalıştırmalara aittir.

## Kaynak belge · docs/ARCHITECTURE.md

# Freya Otomotiv Asistanı

## Çalışma sınırı

Windows üzerinde FastAPI (127.0.0.1:8000), Ollama (127.0.0.1:11434) ve yerel modeller çalışır. Asterisk ayrı Linux ortamındadır. İlk kurulum model indirir; görüşme sırasında harici STT/LLM hizmeti kullanılmaz. Model önbelleği hazırlanırsa HF_HUB_OFFLINE=1 ile çalıştırılabilir.

## Bileşenler

- `backend/main.py`: FastAPI uygulaması, yaşam döngüsü (model yükleme, kayıt temizliği) ve router kaydı. Uç noktalar `backend/routers/` altındadır; kayıt sırası korunur ve catch-all `generic_resources` en sonda kaydedilir.
- `backend/db.py`: SQLite, yabancı anahtarlar, WAL, kayıt modelleri ve atomik randevu işlemi. Slot tekilliği yarış koşullarında da uygulanır. Ücret kuruş olarak tutulur.
- `backend/text.py`: Türkçe tarih, telefon ve plaka ön işlemesi; otomotiv normalizasyonu; yapılandırılabilir sözlük ve güvenli yan cümle sınırları. Desteklenmeyen semboller hata üretir. Genel amaçlı Türkçe morfoloji motoru değildir.
- `backend/models.py`: FreyaTTS, faster-whisper, Silero ve Ollama adaptörleri. FreyaTTS'nin sabitlenmiş sürümündeki `_synth_one` API'si kullanılır; dahili normalizasyon tekrar çalıştırılmaz. Ses kimliği için seed 9 korunur; sessiz çıktıda başka sese geçilmez.
- `backend/session.py`: 16 kHz giriş, VAD, STT, transkript, tur kimlikleri, iptal ve ses oynatma. Sentez kuyruğu en fazla iki iş alır; CUDA işi iptal edilemese de eski tur oynatılamaz.
- `backend/dialogue.py`: Randevu durum makinesi (backend yürütür). LLM'in veritabanı araçlarına doğrudan erişimi yoktur.
- `backend/telephony.py`: AudioSocket UUID ve paket ayrıştırma; çift yönlü 8 kHz PCM16, her paket 20 ms. Alıcı TCP paket sınırlarına güvenmez.
- `backend/qa_telemetry_operator.py`, `backend/acoustic_evaluation.py`: kalite kapısı ve akustik geri tanıma ölçümü.
- `frontend`: React yönetim paneli. AudioWorklet mikrofon yakalar; mikrofon ve asistan oynatması ayrı AudioContext kullanır.
- `experimental/`, `archive/`: canlı yola bağlı olmayan kod ve eski PoC dosyaları; üretim davranışının kanıtı değildir.

## Router düzeni

`backend/routers/` altında dokuz alan modülü ve catch-all vardır: `core_system` (sağlık, hazırlık, model yükleme), `text_speech` (normalizasyon, sentez, sözlük, A/B), `operator_qa` (operatör ve kalite), `telephony` (bildirim, giden arama, AudioSocket, aktarım, WhatsApp webhook), `crm` (araç, muayene, randevu, görüşme, teknisyen dikte), `scheduling` (lift, sıra, servis yeri), `audio_dsp`, `compliance` (KVKK, ses arşivi), `observability` (GPU, SIP, metrik), `generic_resources`. Kaynak: `backend/main.py` `include_router` listesi.

## Kural öncelikli diyalog

Gelen aramada tur metni önce seçenek numarası ve katalog/ad kurallarıyla çözülür (`_rule_extract`); kurallar yeterliyse LLM çağrılmaz. Kuralların okuyamadığı söz kalırsa veya kural yolu hata verirse LLM yolu aynen çalışır. İki yol aynı durum makinesine (`_apply_extract`) gider. Randevu için müşteri onayı her durumda zorunludur. Kaynak: `backend/dialogue.py`.

## Ön ısıtma

Model yüklemesi sırasında TTS bir kez ısıtılır (ilk sentez ön ısıtmasız yaklaşık 10,7 s ölçülmüştü, kaynak: `backend/models.py` açıklaması) ve karşılama metinleri ile sabit istemler yan cümle bazında sentezlenip sınırlı bir önbelleğe konur; aktif A/B deneylerinin seed'leri de ısıtılır. Hata yüklemeyi başarısız kılmaz. Önbellekteki karşılamanın ilk sesi tek çalıştırmada yaklaşık 15 ms ölçüldü (`docs/measured-latency.json`; SLA değildir).

## Güvenlik modeli

- REST: HTTP Basic, kullanıcı `admin`, parola `.env` içindeki `ADMIN_PASSWORD` (sabit zamanlı karşılaştırma; parola boşsa 503). Varsayılan adres yalnızca localhost'tur; uzak erişim için HTTPS ters vekili gerekir.
- WebSocket: `POST /api/session-ticket` ile alınan tek kullanımlık, 30 saniyelik bilet.
- Webhook: `X-Webhook-Token` başlığı `WHATSAPP_WEBHOOK_TOKEN` ile gövde işlenmeden önce doğrulanır.
- Gizli anahtarların (`AMI_SECRET`, `WHATSAPP_WEBHOOK_TOKEN`, `AUDIO_ARCHIVE_MASTER_KEY`, `LINK_SIGNING_KEY`) kodda varsayılanı yoktur; boşsa ilgili özellik kapalıdır. İmzalı rapor bağlantıları HMAC ile doğrulanır.
- AudioSocket şifreli değildir; yalnızca güvenilir özel ağda ve `PBX_ALLOWED_IPS` izin listesiyle kullanılır.
- Yükleme boyutu sınırları: `backend/security_utils.py`.

## Veri

UTC tarihler ISO 8601 olarak yazılır; arayüz İstanbul saatini gösterir. Transkript görüşme silinince kademeli silinir. Ham giriş sesi varsayılan kapalıdır (`RECORD_AUDIO`); açılırsa `recordings/*.wav` dosyaları `RETENTION_DAYS` sonunda saatlik temizlikle silinir. Saklama süresi yalnızca bu kayıtları kapsar; transkript ve diğer kişisel veriler için bir saklama süresi uygulanmaz. KVKK maddeleri hukuki incelemede olup kesinleşmemiştir. Demo modu (`DEMO_MODE=1`) verisini `data/demo` altında tutar ve işletim verisine erişmez.

## API ve medya sözleşmesi

OpenAPI: `/docs`. Sağlık: `/api/health`; ayrıntılı hazırlık: `/api/readiness`. Model yükleme: `POST /api/models/load`. Metin: `POST /api/normalize`, `POST /api/synthesize`. Veri: `vehicles`, `quotes`, `slots`, `appointments`, `conversations` kaynakları `/api` altındadır.

`POST /api/session-ticket` sonrası `/ws/voice?ticket=...` açılır. İlk JSON: `{"sample_rate":48000,"encoding":"pcm_s16le","channels":1}`. Giriş hızı 8000/16000/24000/44100/48000 olabilir. Sonraki ikili mesajlar little-endian PCM16’dır. Sunucu 16 kHz mono PCM16 gönderir; JSON olayları `session`, `transcript`, `status`, `playback`, `metrics`, `error`, `completed` tiplerindedir. `playback` pause/resume/flush ile istemci oynatma kuyruğunu yönetir.

AudioSocket 0x10: 8 kHz, 16 bit mono, little-endian; başlık uzunluğu big-endian. UUID 16 bayttır; Asterisk UNIQUEID yerine gerçek UUID gerekir. Son kısa çerçeve sıfırla tamamlanır. Saat kaçırıldığında telafi paketi yağmuru oluşturulmaz.

## Ölçümlerin anlamı

`model_load_ms` ses modelleri ve Ollama ısıtmasını kapsar. `llm_first_token_ms` ve `llm_total_ms` gerçek HTTP akışından ölçülür. `stt_ms` tanıma süresidir. `endpoint_ms` son sesli VAD bloğundan sonlandırmaya kadar geçen süredir. `first_audio_ms` son sesli bloktan ilk sesin sunucuda hazır olmasına kadardır; ağ ve tarayıcı/PBX oynatma gecikmesi buna dahil değildir. `barge_in_signal_ms` durdurma sinyalinin gönderilme süresidir; karşı uçta sesin duyulur biçimde kesildiğini tek başına kanıtlamaz. Yan cümleler sınırlı kuyrukla önden sentezlenir; ilk parça oynarken sonraki parça hazırlanır.

## Sınırlar

Eşzamanlı görüşme ölçülmedi; testler tek görüşmeyle yapıldı. Müşterinin açık onayı olmadan kayıt yapılmaz. Randevu yalnızca sunulan seçenek numarasından seçilir; serbest takvim tarihi pazarlığı ilk sürümde yoktur. Mevcut veritabanına kaydedilmemiş araç için işlem yapılmaz. Takip kaydı oluşturulur, dış bir çalışana bildirim gönderilmez. Dış CRM yoktur. Giden çağrı ve operatör aktarımı sahte AMI istemcisiyle çalışır (`backend/ami.py` `MockAMIClient`); gerçek arama/aktarım yapılmaz. Bildirim sağlayıcısı da sahtedir; gerçek SMS/WhatsApp gönderilmez.

Yan cümle içinde token seviyesinde TTS yoktur. LLM akışı şemalı alan çıkarımı içindir; JSON tamamlanıp doğrulandıktan sonra backend yanıt üretir. Gecikme azaltımı için doğrulanmamış işlem sonucunu erken seslendirme yapılmaz.

## Kaldırılan iddialar

Önceki belgelerdeki şu ifadeler kaynaksız olduğu için kaldırıldı: 1095 test ve katman dağılımı, ilk ses (TTFA) süreleri, MOS/ABX/F0 değerleri, VAD doğruluk yüzdesi, barge-in milisaniye değeri, LoRA varyant sonuçları, "Faster-Whisper CPU" profili, 64 sözlük kuralı, "97 görüşme doğrulandı", "pilot hazır", Asterisk "entegre" ve "TSE onaylı" ifadeleri, "15 dakikadan 3 dakikaya" kazanımı, "%100 PASS" ve `experimental/` modülleri için ajan iddiaları. Güncel değerler yalnızca `data/acoustic/latest.json`, `docs/measured-latency.json` ve test çıktısından gelir.



## Kaynak belge · docs/milestones/INTEGRATION.md

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



## Kaynak belge · docs/SUPERVISOR.md

# Supervisor ve niyet yönlendirici V1

Web görüşmesinde final ASR metni, 22 niyetli katalog ve deterministik politika üzerinden değerlendirilir. Güvenlik ve açık temsilci isteği kuralları önce çalışır. Model önerileri yazma, acil durum veya insan aktarımı yetkisi vermez. Niyetler, henüz doğrulanmamış slotlar ve uygulama adımları ayrı nesnelerdir.

## Entegrasyon noktaları

| Katman | Kod yolu | Bağlantı |
| --- | --- | --- |
| Ses turu | `backend/session.py`, `backend/audio.py`, `backend/models.py` | Silero turu sonlandırır, faster-whisper final metni çıkarır. Supervisor yalnızca web oturumunda final metni alır. Yanıt mevcut FreyaTTS ve ses kuyruğuyla seslendirilir. |
| Diyalog ve takvim | `backend/dialogue.py`, `backend/db.py` | Mevcut randevu durum makinesi varsayılan ses yoludur. Guarded mod aynı SQLite takvimindeki boşluğu yalnızca okur. |
| Telefon | `backend/audiosocket_server.py`, `backend/ami.py`, `asterisk/extensions.conf` | Mevcut AudioSocket/AMI zinciri Supervisor V1'e bağlanmadı. |
| Supervisor | `backend/supervisor/` | Katalog, kural katmanı, bağlam, plan, araç erişimi, iz ve çevrimdışı eğitim ayrıdır. |
| Kalite | `backend/qa_telemetry_operator.py`, `backend/supervisor/quality.py` | Mevcut telemetri ses kalitesini izler. Niyet incelemesi yerel iz ve operatör onayıyla sağlanır. FQICI ayrı bir kapanış kuyruğudur. Pilot seçenekleri [uzman inceleme planının Aşama 3 bölümünde](UZMAN_INCELEME_PLANI.md#aşama-3-kapsam-kararı-yarım-gün-karar-sizin) yer alır. |
| Yönetim paneli | `backend/routers/supervisor.py`, `frontend/src/SupervisorPanel.tsx` | Kimlik doğrulamalı karar incelemesi, veri dışa aktarma ve deney raporları. |

## Etkinleştirme

1. Uygulamanın SQLite veritabanını normal işletim prosedürüyle `alembic upgrade head` komutuyla güncelleyin. Supervisor şeması `022` revizyonudur.
2. `SUPERVISOR_MODE=shadow` ile web oturumlarında karar izlemeyi açın. Mevcut diyalog yanıtı üretilmeye devam eder.
3. Koruyucu davranışları sınamak için `SUPERVISOR_MODE=guarded` kullanın. Bu mod doğrulanmamış alanlarda açıklama ister, kayıt sorgularında kimlik doğrulaması ister ve yerel takvimde boş saat olup olmadığını okuyabilir. Mevcut web görüşmesinde müşteri kimliği ve işleme bağlı onay kaynağı bulunmadığı için canlı yazma ve operatör aktarımı bağlı değildir.
4. Geri almak için `SUPERVISOR_MODE=off` ayarını kullanıp uygulamayı yeniden başlatın. Bu varsayılan moddur. Panel kayıtlarına erişim yönetici kimlik doğrulaması gerektirir.

`SUPERVISOR_LLM_FALLBACK=true` yalnızca belirsiz final metinlerinde yerel Ollama'ya şemalı öneri sorar. 127.0.0.1 veya ::1 üzerindeki Ollama adresi gerekir. Zaman aşımı, erişim hatası veya şema hatasında açıklama istenir. Yerel model ile canlı bir görüşme bu teslimin ölçümüne dahil edilmedi.

Tool Gateway, işleme ve alanlara bağlı kısa ömürlü doğrulama/onay belgesi bekler. Kayıt sahibi ve güncel durum yerel işlem içinde yeniden kontrol edilir. İşlem ile idempotency makbuzu aynı SQLite transaction'ında saklanır. Zaman aşımı sonucu belirsizse aynı anahtarla yeniden sorgulama veya yeniden deneme yapılır. V1 web adaptörü canlı yazma araçlarını kaydetmez.

## Kalite incelemesi

**Supervisor Kalite** sekmesinde katalog, görüşme kararları, gerekçeler, plan ve bağımlılıkları, model sürümleri ve regresyon durumu bulunur. İz kaydı ASR kökenini, niyetleri, skorları, sabit gerekçe kodlarını ve planı saklar. Ham metin ve slot değerleri Supervisor izine yazılmaz.

Operatör bir kararı kabul edebilir, etiketleri düzeltebilir, reddedebilir veya ek kanıt isteyebilir. Eğitim örneği eklemek için izinli, anonimleştirilmiş metin ve operatör beyanı gerekir. Desen tabanlı kontrol yaygın kimlik bilgilerini yakalar. Ad, adres ve dolaylı tanımlayıcıları temizleme sorumluluğu inceleyendedir. Aynı müşteri veya senaryo için aynı anonim grup UUID'si ve bölüm kullanılmalıdır. Sistem aynı görüşmenin ya da grup UUID'sinin bölümler arasında dağılmasını ve yinelenen metni engeller.

JSONL dışa aktarma yalnızca onaylanmış örnekleri içerir. Kaynak iz ve örnek, transkript saklama süresi veya ilgili silme işlemi sonunda yerel veritabanından kaldırılır. Dışa aktarılan kopyalar ayrı yönetilir. Eğitim ve model etkinleştirme ayrı işlemlerdir.

## Yerel deney ve doğrulama

Deney bağımlılıkları canlı ses yolundan ayrıdır. Deneyde kullanılan sürümler scikit-learn 1.9.1, joblib 1.6.0, psutil 7.2.2 ve XGBoost 3.2.0. XGBoost sadece karşılaştırma için gerekir.

```powershell
uv pip install --python .venv/Scripts/python.exe scikit-learn==1.9.1 joblib==1.6.0 psutil==7.2.2
uv pip install --python .venv/Scripts/python.exe xgboost==3.2.0
.venv\Scripts\python.exe -m backend.supervisor.train --synthetic --output data/supervisor/evaluations/baseline
.venv\Scripts\python.exe -m backend.supervisor.train --synthetic --kind xgboost --baseline-manifest data/supervisor/evaluations/baseline/manifest.json --output data/supervisor/evaluations/xgboost
.venv\Scripts\python.exe -m backend.supervisor.train --dataset data/supervisor/intent-reviewed.jsonl --output data/supervisor/reviewed-baseline
.venv\Scripts\python.exe -m pytest -q --basetemp data/pytest-supervisor --junitxml=data/supervisor/regression.xml
```

Manifest veri parmak izini, bölümleri, etiket sırasını, eşikleri, sürümleri ve test sonuçlarını kaydeder. Eşikler doğrulama bölümünde seçilir. Karşılaştırma CLI'si aynı veri, bölüm, katalog ve seed kullanan baseline manifestini ister. Sentetik sonuçlar gerçek çağrı başarımı veya üretim kabulü göstermez.

İlk sentetik ölçüm 47 eğitim, 26 doğrulama ve 26 test örneğiyle yapıldı. Baseline makro F1 0,333 ve p95 5,86 ms, XGBoost makro F1 0,083 ve p95 11,24 ms verdi. Her iki model de üç kapsam dışı örneğin tamamını kabul etti. Her iki modelin de tam eşleşme skoru sıfırdı. Gerçek 8 kHz veri ve bağımsız insan onaylı test seti bekleniyor.

Üretim modeli için yalnızca insan incelemeli veriyle eğitilmiş baseline kabul edilir. Yerel, güvenilir artefaktın yolu `SUPERVISOR_MODEL_PATH`, açıkça onaylanmış SHA-256 özeti `SUPERVISOR_MODEL_SHA256` ile verilir. Ayarları kaldırıp yeniden başlatmak kurallı çalışmaya döndürür. Sentetik modeller ve XGBoost challenger deney çıktıları üretimde yüklenmez.

Asterisk AudioSocket ve gerçek SIP çağrısı bu aşamada fiziksel olarak sınanmadı. M11 kabul koşulları için gerçek telefon görüşmesi, insan sesi ve 8 kHz kayıtlarla ayrı doğrulama gerekir.



## Kaynak belge · docs/fqici/02_durable_queue.md

# FQICI Prompt 2 — Kalıcı kapanış kuyruğu

`023` revizyonu FQICI kapsamı, doğrulanmış olay ve analiz işi tablolarını ekler. Uygulamayı açmadan önce normal migration prosedürüyle `alembic upgrade head` çalıştırılır. Web için `FQICI_ENABLED=true` ile pilot açılır. Varsayılan kapalıdır. Uygulama yeniden başlatıldığında ayar okunur.

Web görüşmesi ve sunucu kodunun açıkça `synthetic=True` ile başlattığı AudioSocket adaptörü pilot kapsamına alınır. Üretim AudioSocket dinleyicisi bu işareti vermez. Bir taşıyıcı UUID’sinin veya istemci mesajının sentetik kaynak ilan etme yetkisi yoktur. Web kökeni demo modunda `DEMO`, diğer durumlarda `UNKNOWN` kalır.

## Veri akışı

1. Freya görüşmesi ile FQICI kapsamı aynı SQLite transaction’ında yazılır. Oturum denetleyicisi kapanışı mevcut M10 günlüğünde kalıcılaştırır.
2. Başlangıçta mevcut oturum kurtarması çalışır. FQICI daha sonra yerel event bus tarafından onaylanmış kayıtlar dahil, kalıcı terminal kayıtları okur. Çalışma sırasında okuyucu arka planda tekrar tarar. Kapsam kaydı var fakat başlangıçta kullanılabilir terminal kayıt yoksa kurtarma olayı sonuç durumunu `UNKNOWN` olarak taşır. Başlangıç kurtarması tek uygulama sunucusu varsayımını mevcut M10 akışıyla paylaşır.
3. FQICI alımı olay, ilk snapshot ve iş satırını tek transaction’da işler. 500 bekleyen iş sınırı doluysa olay ve bekleyen kapsam işareti kalıcılaşır. Yer açılınca tekrar kuyruğa alınır. Geç kanıtlar iki saniyelik sessizlik penceresinde, en fazla 30 saniyeye kadar birleştirilir. Bu değerler kapasite ölçümü değildir.
4. İşçiler işlem başına artan kira belirteci alır. Süresi dolan iş yeniden alınabilir. Eski belirteçle bitirme reddedilir. Üç deneme sonunda süresi dolan veya yeniden denenebilir hata alan iş terminal hata durumuna gider.
5. Saat alanı veya zaman bilgisi kanonik kanıta dahildir. Journal olayı saat alanını sağlayamadığında monotonic alan boş bırakılır. Olay gövdesi kapalı alan listesiyle doğrulanır. FQICI ham metin veya ses kopyalamaz. Mevcut periyodik saklama işi süresi dolan veya silinmiş olarak işaretlenmiş görüşmelerin FQICI kapsamını, olaylarını ve işlerini kaldırır.

Prompt 2, terminal olay üreticisini canlı web pilotuna ve sentetik AudioSocket test girişine bağlar. Araç timeout ve commit sözleşmeleri sentetik alım testlerinde kullanılır. İş sahipliği API’si kullanılabilir durumdadır. Bulguları hesaplayan worker, canlı araç olaylarının kapsamı ve dışa aktarma Prompt 3 ve sonraki aşamalara aittir. Fiziksel SIP kabulü HOLD.

## Doğrulama

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_fqici_queue.py tests/test_session.py tests/test_audiosocket_server.py tests/milestones/test_m10.py --basetemp data/pytest-fqici-p2
```

Testler SQLite üzerinde on tekrar ve iki eşzamanlı tüketici, gerçek alt süreçlerle yeniden teslim, yarım transaction geri alımı, kurtarılan oturum, kuyruk doluluğu, geç kanıt, ayrı kural sürümü, saat alanı, izinli alan doğrulaması ve yerel sentetik TCP AudioSocket kapanışını kapsar.


## Ortak çekirdeğin yeniden kurulması

Backend içindeki çağrı yolu ile M01–M11 referans akışlarını bağlarken aşağıdaki modülleri kullanın. core oturum kimliği ve olay sırasını, conversation sinyallerden durum ve etkilerin türetilmesini, dialogue karar ile kayıt katmanının ayrılmasını tarif eder. domain/booking.py uyarınca teyit duyurusu için müşterinin onayı, confirmed sonucu ve dolu referans birlikte gerekir. ports ve adapters dış sisteme geçiş sınırını tanımlar. Bir modülün canlı kullanımını belirlemek için 03 ve 13 içindeki çağıranına bakın. Demo ve rapor giriş noktaları bağımsız çalıştırılır.

### automotive_voice/__init__.py

~~~~python
"""Architecture-first mocked core, NOT a live telephone/TTS service."""
~~~~

### automotive_voice/adapters/fake.py

~~~~python
"""Only mock frames; NOT a voice model or acoustic test."""
from automotive_voice.ports.contracts import AudioChunk, AudioFormat
import struct

class FakeTTS:
    async def synthesize(self, text: str, generation_id: int):
        fmt = AudioFormat(sample_rate=48000,channels=1,sample_width_bits=32,encoding="float32")
        for seq, _token in enumerate(text.split()):
            # Exactly 10 ms of synthetic silence. No model inference and no speech.
            payload = struct.pack("<" + "f" * 480, *([0.0] * 480))
            yield AudioChunk(generation_id=generation_id,seq=seq,payload=payload,audio_format=fmt)

class FakeMediaOutput:
    def __init__(self):
        self.items: list[AudioChunk] = []
        self.flush_count = 0

    async def enqueue(self, chunk: AudioChunk) -> None:
        self.items.append(chunk)

    async def flush(self) -> None:
        self.items.clear()
        self.flush_count += 1
~~~~

### automotive_voice/adapters/lifecycle/__init__.py

~~~~python
"""M07 deterministic fake adapter lifecycle and synthetic streaming contracts."""
from .clock import MockClock
from .breaker import CircuitBreaker
from .contracts import (AdapterKind, AdapterState, CircuitState, ResultCode, Deadline,
                        RetryPolicy, SyntheticCommand, SyntheticResult, AdapterReceipt,
                        HealthSnapshot, LifecyclePort)
from .runtime import SyntheticAdapter
from .supervisor import AdapterSupervisor
from .streaming import SyntheticStreamBridge,StreamReceipt
__all__ = ['MockClock','CircuitBreaker','AdapterKind','AdapterState','CircuitState','ResultCode','Deadline',
           'RetryPolicy','SyntheticCommand','SyntheticResult','AdapterReceipt','HealthSnapshot',
           'LifecyclePort','SyntheticAdapter','AdapterSupervisor','SyntheticStreamBridge','StreamReceipt']
~~~~

### automotive_voice/adapters/lifecycle/breaker.py

~~~~python
"""Bounded deterministic circuit breaker; exactly one HALF_OPEN probe at a time."""
from __future__ import annotations
from automotive_voice.adapters.lifecycle.contracts import CircuitState
class CircuitBreaker:
    def __init__(self, threshold:int=2, cooldown_ns:int=1_000_000_000):
        if type(threshold) is not int or threshold<1 or type(cooldown_ns) is not int or cooldown_ns<1:
            raise ValueError('positive circuit threshold and cooldown required')
        self.threshold=threshold;self.cooldown_ns=cooldown_ns
        self.state=CircuitState.CLOSED;self.failures=0;self.opened_at_ns=None;self.probe_in_progress=False
    def allow(self,now_ns:int)->bool:
        if self.state is CircuitState.OPEN:
            if now_ns-self.opened_at_ns < self.cooldown_ns:return False
            self.state=CircuitState.HALF_OPEN;self.probe_in_progress=False
        if self.state is CircuitState.HALF_OPEN:
            if self.probe_in_progress:return False
            self.probe_in_progress=True
        return True
    def success(self):
        self.state=CircuitState.CLOSED;self.failures=0;self.opened_at_ns=None;self.probe_in_progress=False
    def failure(self,now_ns:int):
        self.failures+=1
        if self.state is CircuitState.HALF_OPEN or self.failures>=self.threshold:
            self.state=CircuitState.OPEN;self.opened_at_ns=now_ns
        self.probe_in_progress=False
    def abandon_probe(self):
        if self.state is CircuitState.HALF_OPEN:self.probe_in_progress=False
~~~~

### automotive_voice/adapters/lifecycle/clock.py

~~~~python
"""Explicit virtual monotonic clock; no wall clock, await sleep or background scheduling."""
from __future__ import annotations
class MockClock:
    def __init__(self, start_ns:int=0):
        if type(start_ns) is not int or start_ns < 0: raise ValueError('nonnegative start_ns required')
        self._now=start_ns
    def now_ns(self)->int:return self._now
    def advance(self, delta_ns:int)->int:
        if type(delta_ns) is not int or delta_ns < 0:raise ValueError('nonnegative delta_ns required')
        if self._now+delta_ns > 2**63-1:raise OverflowError('monotonic clock overflow')
        self._now+=delta_ns
        return self._now
~~~~

### automotive_voice/adapters/lifecycle/contracts.py

~~~~python
"""M07: typed control-plane contracts. No network, audio payload, PII or real wall clocks."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Protocol
import re
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId

SAFE = re.compile(r'^[a-zA-Z0-9_.:/-]{1,128}$')
class AdapterKind(str, Enum):
    STT = 'stt'
    TTS = 'tts'
    LLM = 'llm'
    TELEPHONY = 'telephony'
class AdapterState(str, Enum):
    CREATED = 'created'
    STARTING = 'starting'
    READY = 'ready'
    DEGRADED = 'degraded'
    STOPPING = 'stopping'
    STOPPED = 'stopped'
    FAILED = 'failed'
class CircuitState(str, Enum):
    CLOSED = 'closed'
    OPEN = 'open'
    HALF_OPEN = 'half_open'
class ResultCode(str, Enum):
    OK = 'ok'
    TRANSIENT_FAILURE = 'transient_failure'
    PERMANENT_FAILURE = 'permanent_failure'
    TIMED_OUT = 'timed_out'
    STALE = 'stale_generation'
    CANCELLED = 'cancelled'
    DISCONNECTED = 'disconnected'
    RETRY_EXHAUSTED = 'retry_exhausted'

@dataclass(frozen=True, slots=True)
class Deadline:
    mono_ns: int
    def __post_init__(self):
        if type(self.mono_ns) is not int or not 0 < self.mono_ns <= 2**63-1:
            raise ValueError('positive monotonic_ns required')
    def expired(self, now_ns: int) -> bool:
        return now_ns >= self.mono_ns
    def safe_metadata(self) -> dict:
        return {"deadline_mono_ns":self.mono_ns}

@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_ns: int = 100_000_000
    max_delay_ns: int = 2_000_000_000
    def __post_init__(self):
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 16:
            raise ValueError('max_attempts must be 1..16')
        if any(type(x) is not int or x <= 0 for x in (self.base_delay_ns,self.max_delay_ns)) or self.max_delay_ns < self.base_delay_ns:
            raise ValueError('invalid retry bounds')
    def delay_after(self, failed_attempt:int) -> int:
        if type(failed_attempt) is not int or failed_attempt < 1: raise ValueError('invalid failed attempt')
        return min(self.max_delay_ns, self.base_delay_ns * (2**min(failed_attempt-1, 30)))
    def safe_metadata(self)->dict:
        return {"max_attempts":self.max_attempts,"base_delay_ns":self.base_delay_ns,"max_delay_ns":self.max_delay_ns}

@dataclass(frozen=True, slots=True)
class SyntheticCommand:
    """Reference-only request, with per-adapter/session monotonically increasing sequence."""
    command_id: str
    kind: AdapterKind
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    sequence: int
    payload_ref: str
    deadline: Deadline
    idempotent: bool = True
    def __post_init__(self):
        if not isinstance(self.kind,AdapterKind) or not isinstance(self.session_id,SessionId) or not isinstance(self.turn_id,TurnId) or not isinstance(self.generation_id,GenerationId):
            raise TypeError('adapter kind and strong IDs required')
        if not SAFE.fullmatch(self.command_id) or not SAFE.fullmatch(self.payload_ref):
            raise ValueError('command_id/payload_ref must be opaque ASCII tokens (no raw text)')
        if type(self.sequence) is not int or not 0 <= self.sequence <= 2**63-1:
            raise ValueError('sequence must be a nonnegative integer')
        if not isinstance(self.deadline,Deadline) or type(self.idempotent) is not bool:
            raise TypeError('deadline / idempotent invalid')
    def safe_metadata(self)->dict:
        return {"command_id":self.command_id,"kind":self.kind.value,"session_id":str(self.session_id),
                "turn_id":int(self.turn_id),"generation_id":int(self.generation_id),
                "sequence":self.sequence,"payload_ref":self.payload_ref,
                "deadline_mono_ns":self.deadline.mono_ns,"idempotent":self.idempotent}

@dataclass(frozen=True, slots=True)
class AdapterReceipt:
    accepted: bool
    reason: str
    command_id: str

@dataclass(frozen=True, slots=True)
class SyntheticResult:
    command_id: str
    kind: AdapterKind
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    code: ResultCode
    attempts: int
    output_ref: str | None = None
    def __post_init__(self):
        if self.output_ref is not None and not SAFE.fullmatch(self.output_ref):
            raise ValueError('unsafe opaque output reference')
    def safe_metadata(self)->dict:
        return {"command_id":self.command_id,"kind":self.kind.value,"session_id":str(self.session_id),
                "turn_id":int(self.turn_id),"generation_id":int(self.generation_id),
                "code":self.code.value,"attempts":self.attempts,"output_ref":self.output_ref}

@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    kind: AdapterKind
    state: AdapterState
    circuit: CircuitState
    queued: int
    in_flight: int
    completed: int
    last_error_code: str | None
    observed_mono_ns: int
    mock_only: bool = True
    def safe_metadata(self)->dict:
        return {"kind":self.kind.value,"state":self.state.value,"circuit":self.circuit.value,
                "queued":self.queued,"in_flight":self.in_flight,"completed":self.completed,
                "last_error_code":self.last_error_code,"observed_mono_ns":self.observed_mono_ns,
                "mock_only":self.mock_only}

class LifecyclePort(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def health(self) -> HealthSnapshot: ...
    async def submit(self, command:SyntheticCommand) -> AdapterReceipt: ...
    async def tick(self) -> tuple[SyntheticResult,...]: ...
~~~~

### automotive_voice/adapters/lifecycle/runtime.py

~~~~python
"""M07 deterministic fake adapter runtime: retry, fault scripts, cancellation, bounded work.

No actual STT/TTS/LLM/telephony call; all outputs are opaque synthetic refs.
"""
from __future__ import annotations
import asyncio
from collections import deque
from dataclasses import dataclass
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.core.session import State
from .clock import MockClock
from .breaker import CircuitBreaker
from .contracts import (AdapterKind,AdapterState,AdapterReceipt,SyntheticCommand,SyntheticResult,
                        HealthSnapshot,RetryPolicy,ResultCode)

@dataclass(slots=True)
class _Work:
    command: SyntheticCommand
    attempts: int=0
    ready_at_ns: int=0
    complete_at_ns: int | None=None
    outcome: str='ok'

class SyntheticAdapter:
    """Reusable fake STT/TTS/LLM/telephony adapter. Single reactor lock, no real I/O.

    `tick` must be explicitly called after advancing the MockClock. Faults are
    preloaded in attempt order. Completion always revalidates the M01 token.
    """
    def __init__(self,kind:AdapterKind,manager:SessionManager,clock:MockClock,*,
                 retry:RetryPolicy|None=None,max_pending:int=32,max_inflight:int=2,
                 latency_ns:int=20_000_000,replay_limit:int=256,
                 breaker_threshold:int=3,breaker_cooldown_ns:int=250_000_000):
        if not isinstance(kind,AdapterKind):raise TypeError('kind required')
        for value in (max_pending,max_inflight,replay_limit):
            if type(value) is not int or value<1:raise ValueError('positive capacities required')
        if type(latency_ns) is not int or latency_ns<0:raise ValueError('nonnegative latency required')
        self.kind=kind;self.manager=manager;self.clock=clock
        self.retry=retry or RetryPolicy();self.max_pending=max_pending
        self.max_inflight=max_inflight;self.latency_ns=latency_ns;self.replay_limit=replay_limit
        self.breaker=CircuitBreaker(breaker_threshold,breaker_cooldown_ns)
        self.state=AdapterState.CREATED;self.last_error_code=None
        self._jobs:dict[str,_Work]={};self._inflight:set[str]=set();self._terminal:dict[str,tuple[SyntheticCommand,SyntheticResult]]={}
        self._terminal_order:deque[str]=deque();self._last_seq:dict[str,int]={}
        self._faults:dict[str,tuple[str,...]]={};self._lock=asyncio.Lock()
        self._disconnected=False
    def inject_faults(self,command_id:str,attempts:list[str]|tuple[str,...]):
        if not isinstance(command_id,str) or not isinstance(attempts,(list,tuple)) or any(x not in ('ok','transient','permanent','disconnect','timeout') for x in attempts):
            raise ValueError('supported scripted faults: ok/transient/permanent/disconnect/timeout')
        self._faults[command_id]=tuple(attempts)
    def health(self)->HealthSnapshot:
        return HealthSnapshot(self.kind,self.state,self.breaker.state,
             len(self._jobs)-len(self._inflight),len(self._inflight),len(self._terminal),self.last_error_code,self.clock.now_ns())
    async def start(self):
        async with self._lock:
            if self.state is AdapterState.READY:return
            if self.state not in (AdapterState.CREATED,AdapterState.STOPPED,AdapterState.FAILED,AdapterState.DEGRADED):
                raise RuntimeError('invalid adapter start transition')
            self.state=AdapterState.STARTING
            # Explicit virtual start, no real side effect.
            self._disconnected=False
            self.breaker.success()
            self.last_error_code=None;self.state=AdapterState.READY
    async def reconnect(self):
        async with self._lock:
            if self.state is not AdapterState.DEGRADED:raise RuntimeError('reconnect requires degraded state')
            self._disconnected=False;self.state=AdapterState.READY
            self.breaker.success();self.last_error_code=None
    async def stop(self):
        async with self._lock:
            if self.state is AdapterState.STOPPED:return
            self.state=AdapterState.STOPPING
            for job in tuple(self._jobs.values()):self._finish(job,ResultCode.CANCELLED)
            self._inflight.clear();self._disconnected=False;self.state=AdapterState.STOPPED
    async def _active(self,cmd:SyntheticCommand)->bool:
        try:
            snap=await self.manager.snapshot(str(cmd.session_id))
            tok=await self.manager.current_token(str(cmd.session_id))
            return (snap.turn_id==cmd.turn_id and snap.generation_id==cmd.generation_id
                    and snap.state not in (State.IDLE,State.ENDED,State.FAILED,State.HANDOFF)
                    and not tok.cancelled and tok.generation_id==cmd.generation_id)
        except (LookupError,ValueError):return False
    async def expected_sequence(self,sid:str)->int:
        """Authoritative sequence allocator for this adapter/session."""
        async with self._lock:
            return self._last_seq.get(sid,-1)+1

    async def submit(self,cmd:SyntheticCommand)->AdapterReceipt:
        if not isinstance(cmd,SyntheticCommand) or cmd.kind is not self.kind:raise TypeError('matching synthetic command required')
        async with self._lock:
            old=self._jobs.get(cmd.command_id)
            if old is not None:
                return AdapterReceipt(old.command==cmd,'duplicate_ignored' if old.command==cmd else 'conflicting_replay',cmd.command_id)
            terminal=self._terminal.get(cmd.command_id)
            if terminal is not None:
                return AdapterReceipt(terminal[0]==cmd,'duplicate_ignored' if terminal[0]==cmd else 'conflicting_replay',cmd.command_id)
            if self.state is not AdapterState.READY:return AdapterReceipt(False,'adapter_not_ready',cmd.command_id)
            if cmd.deadline.expired(self.clock.now_ns()):return AdapterReceipt(False,'deadline_expired',cmd.command_id)
            if not await self._active(cmd):return AdapterReceipt(False,'stale_generation',cmd.command_id)
            sid=str(cmd.session_id)
            expect=self._last_seq.get(sid,-1)+1
            if cmd.sequence != expect:
                return AdapterReceipt(False,'sequence_gap' if cmd.sequence>expect else 'stale_sequence',cmd.command_id)
            if len(self._jobs)>=self.max_pending:return AdapterReceipt(False,'backpressure',cmd.command_id)
            self._last_seq[sid]=cmd.sequence
            self._jobs[cmd.command_id]=_Work(cmd,ready_at_ns=self.clock.now_ns())
            return AdapterReceipt(True,'accepted_mock',cmd.command_id)
    def _finish(self,job:_Work,code:ResultCode)->SyntheticResult:
        cmd=job.command
        output=f'mock-{cmd.kind.value}:{cmd.command_id}' if code is ResultCode.OK else None
        result=SyntheticResult(cmd.command_id,cmd.kind,cmd.session_id,cmd.turn_id,cmd.generation_id,code,job.attempts,output)
        self._jobs.pop(cmd.command_id,None)
        if cmd.command_id in self._inflight:self.breaker.abandon_probe()
        self._inflight.discard(cmd.command_id)
        self._terminal[cmd.command_id]=(cmd,result);self._terminal_order.append(cmd.command_id)
        while len(self._terminal_order)>self.replay_limit:
            self._terminal.pop(self._terminal_order.popleft(),None)
        return result
    async def cancel_session(self,sid:str)->tuple[SyntheticResult,...]:
        async with self._lock:
            return tuple(self._finish(job,ResultCode.CANCELLED) for job in list(self._jobs.values()) if str(job.command.session_id)==sid)
    async def tick(self)->tuple[SyntheticResult,...]:
        async with self._lock:
            now=self.clock.now_ns();result=[]
            # Drop expired/stale work first, including in-flight responses.
            for job in list(self._jobs.values()):
                if not await self._active(job.command):result.append(self._finish(job,ResultCode.STALE))
                elif job.command.deadline.expired(now):result.append(self._finish(job,ResultCode.TIMED_OUT))
            # Consume all ready in-flight completions. The scripted fault resolves
            # only here, so stale callbacks can never leak an old generation.
            for cid in tuple(self._jobs):
                if cid not in self._inflight:continue
                job=self._jobs.get(cid)
                if job is None or job.complete_at_ns is None or now<job.complete_at_ns:continue
                self._inflight.discard(cid);job.complete_at_ns=None
                if not await self._active(job.command):result.append(self._finish(job,ResultCode.STALE));self.breaker.abandon_probe();continue
                outcome=job.outcome
                if outcome=='ok':
                    self.breaker.success();result.append(self._finish(job,ResultCode.OK));continue
                self.last_error_code=outcome
                if outcome=='disconnect':
                    self._disconnected=True;self.state=AdapterState.DEGRADED
                    self.breaker.failure(now)
                elif outcome=='permanent':
                    self.breaker.failure(now)
                    result.append(self._finish(job,ResultCode.PERMANENT_FAILURE));continue
                elif outcome=='timeout':
                    self.breaker.failure(now)
                    result.append(self._finish(job,ResultCode.TIMED_OUT));continue
                else:self.breaker.failure(now)
                if not job.command.idempotent or job.attempts>=self.retry.max_attempts:
                    result.append(self._finish(job,ResultCode.DISCONNECTED if outcome=='disconnect' else ResultCode.RETRY_EXHAUSTED));continue
                job.ready_at_ns=now+self.retry.delay_after(job.attempts)
                if job.ready_at_ns>=job.command.deadline.mono_ns:
                    result.append(self._finish(job,ResultCode.TIMED_OUT))
            if self.state is not AdapterState.READY or self._disconnected:return tuple(result)
            slots=self.max_inflight-len(self._inflight)
            for job in list(self._jobs.values()):
                if slots<=0:break
                if job.complete_at_ns is not None or job.ready_at_ns>now:continue
                if not self.breaker.allow(now):break
                job.attempts+=1
                outcomes=self._faults.get(job.command.command_id,())
                job.outcome=outcomes[job.attempts-1] if job.attempts<=len(outcomes) else 'ok'
                job.complete_at_ns=now+self.latency_ns
                self._inflight.add(job.command.command_id);slots-=1
            # A zero-latency attempt is completed on the next explicit tick. This
            # preserves deterministic event-loop boundaries and cancellation gates.
            return tuple(result)
    def read_result(self,command_id:str)->SyntheticResult|None:
        pair=self._terminal.get(command_id)
        return pair[1] if pair else None
~~~~

### automotive_voice/adapters/lifecycle/streaming.py

~~~~python
"""M05 clause -> fake TTS -> M06 20ms PCM metadata, without any sound bytes.

Fake TTS success is NOT proof of TTS synthesis; only an explicit virtual-clock
completion yields synthetic metadata. This stage does not emit fake PBX ACKs.
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.core.session import State
from automotive_voice.prosody.mock_tts import MockTTS
from automotive_voice.prosody.contracts import TTSInput
from automotive_voice.audio.queue import MediaBuffer
from automotive_voice.audio.contracts import MediaFormat,Codec,AudioChunkMetadata
from .clock import MockClock
from .runtime import SyntheticAdapter
from .contracts import AdapterKind,Deadline,ResultCode,SyntheticCommand,SyntheticResult

@dataclass(frozen=True,slots=True)
class StreamReceipt:
    accepted:bool
    reason:str
    command_id:str|None=None

class SyntheticStreamBridge:
    def __init__(self,manager:SessionManager,clock:MockClock,tts_adapter:SyntheticAdapter,
                 mock_tts:MockTTS,buffer:MediaBuffer,*,deadline_budget_ns:int=3_000_000_000,
                 seen_limit:int=2048,max_pending:int=64):
        if tts_adapter.kind is not AdapterKind.TTS:raise ValueError('TTS adapter required')
        if type(seen_limit) is not int or seen_limit<1 or type(max_pending) is not int or max_pending<1 or type(deadline_budget_ns) is not int or deadline_budget_ns<1:
            raise ValueError('invalid bounds')
        self.manager=manager;self.clock=clock;self.adapter=tts_adapter;self.mock_tts=mock_tts;self.buffer=buffer
        self.deadline_budget_ns=deadline_budget_ns;self.seen_limit=seen_limit;self.max_pending=max_pending
        self._held:TTSInput|None=None
        self._pending:dict[str,TTSInput]={}
        self._consumed:set[str]=set();self._consumed_order:deque[str]=deque()
        self._chunk_seq:dict[tuple[str,int,int],int]={}
    def _command_id(self,item:TTSInput)->str:
        return f'clause:{item.session_id}:{int(item.turn_id)}:{int(item.generation_id)}:{item.clause_index}'
    async def submit_next_clause(self)->StreamReceipt:
        if len(self._pending)>=self.max_pending:return StreamReceipt(False,'bridge_backpressure')
        item=self._held
        if item is None:item=await self.mock_tts.pop_next()
        if item is None:return StreamReceipt(False,'no_active_clause')
        sid=str(item.session_id);key=self._command_id(item)
        if key in self._consumed or key in self._pending:
            self._held=None
            return StreamReceipt(False,'duplicate_clause',key)
        seq=await self.adapter.expected_sequence(sid)
        cmd=SyntheticCommand(key,AdapterKind.TTS,item.session_id,item.turn_id,item.generation_id,
                             seq,f'clause_sha:{item.text_sha256[:32]}',
                             Deadline(self.clock.now_ns()+self.deadline_budget_ns))
        receipt=await self.adapter.submit(cmd)
        if receipt.accepted and receipt.reason=='accepted_mock':
            self._pending[key]=item;self._held=None
        elif receipt.reason in ('backpressure','adapter_not_ready','stale_sequence','sequence_gap'):
            self._held=item
        else:
            self._held=None  # stale/deadline/sequence failures are fail-closed
        return StreamReceipt(receipt.accepted,receipt.reason,key)
    async def materialize_metadata(self,result:SyntheticResult)->StreamReceipt:
        """A successful fake TTS callback maps to one 20ms metadata frame, never WAV."""
        if not isinstance(result,SyntheticResult) or result.kind is not AdapterKind.TTS:
            return StreamReceipt(False,'wrong_adapter_result')
        item=self._pending.get(result.command_id)
        if item is None:return StreamReceipt(False,'unknown_or_replayed_completion',result.command_id)
        if self.adapter.read_result(result.command_id)!=result:
            return StreamReceipt(False,'unverified_fake_completion',result.command_id)
        if result.code is not ResultCode.OK:
            self._pending.pop(result.command_id,None)
            return StreamReceipt(False,f'fake_tts_{result.code.value}',result.command_id)
        sid=str(item.session_id)
        snap=await self.manager.snapshot(sid)
        if (snap.state is not State.SPEAKING or snap.turn_id!=item.turn_id or
                snap.generation_id!=item.generation_id or
                not await self.manager.accepts_chunk(sid,int(item.generation_id))):
            self._pending.pop(result.command_id,None)
            return StreamReceipt(False,'stale_completion',result.command_id)
        key=(sid,int(item.turn_id),int(item.generation_id));seq=self._chunk_seq.get(key,0)
        chunk=AudioChunkMetadata(item.session_id,item.turn_id,item.generation_id,
             f'mock-tts:{int(item.turn_id)}:{int(item.generation_id)}',seq,320,20,
             self.clock.now_ns(),MediaFormat(Codec.PCM_S16LE,16000),item.clause_index)
        receipt=await self.buffer.enqueue(chunk)
        if not receipt.accepted:return StreamReceipt(False,receipt.reason,result.command_id)
        self._chunk_seq[key]=seq+1
        self._pending.pop(result.command_id,None)
        self._consumed.add(result.command_id);self._consumed_order.append(result.command_id)
        while len(self._consumed_order)>self.seen_limit:
            self._consumed.discard(self._consumed_order.popleft())
        return StreamReceipt(True,'mock_metadata_queued',result.command_id)
    def pending_count(self)->int:return len(self._pending)
    def abandon_generation(self,sid:str):
        if self._held is not None and str(self._held.session_id)==sid:self._held=None
        for key,item in list(self._pending.items()):
            if str(item.session_id)==sid:self._pending.pop(key,None)
~~~~

### automotive_voice/adapters/lifecycle/supervisor.py

~~~~python
"""M07 lightweight adapter supervisor. M02 and M03 remain authoritative.

Does not infer CRM decisions, fabricate flush ACKs or open any network.
"""
from __future__ import annotations
import asyncio
from automotive_voice.conversation.effects import Effect,EffectKind
from automotive_voice.audio.coordinator import MediaCoordinator
from .clock import MockClock
from .runtime import SyntheticAdapter
from .contracts import (AdapterKind,AdapterReceipt,SyntheticCommand,Deadline,RetryPolicy)
from automotive_voice.core.session_manager import SessionManager

EFFECT_ROUTE={EffectKind.REQUEST_LLM:AdapterKind.LLM,EffectKind.START_TTS:AdapterKind.TTS,
              EffectKind.QUEUE_AUDIO:AdapterKind.TELEPHONY}

class AdapterSupervisor:
    def __init__(self,manager:SessionManager,clock:MockClock,*,media:MediaCoordinator|None=None,
                 retry:RetryPolicy|None=None,max_pending:int=32,max_inflight:int=2):
        self.manager=manager;self.clock=clock;self.media=media
        self.adapters={kind:SyntheticAdapter(kind,manager,clock,retry=retry,
                  max_pending=max_pending,max_inflight=max_inflight) for kind in AdapterKind}
        self._lock=asyncio.Lock()
    async def start_all(self):
        for adapter in self.adapters.values():await adapter.start()
    async def stop_all(self):
        for adapter in self.adapters.values():await adapter.stop()
    async def cancel_session(self,sid:str):
        return {kind:await a.cancel_session(sid) for kind,a in self.adapters.items()}
    async def dispatch_effect(self,effect:Effect,*,deadline_ns:int|None=None)->AdapterReceipt:
        if not isinstance(effect,Effect):raise TypeError('Effect required')
        sid=str(effect.session_id)
        if effect.kind in (EffectKind.CANCEL_GENERATION,EffectKind.TERMINATE_CALL,EffectKind.START_HANDOFF):
            await self.cancel_session(sid)
            if effect.kind is EffectKind.TERMINATE_CALL and self.media is not None:
                await self.media.terminate(sid)
            return AdapterReceipt(True,'mock_lifecycle_cancelled',effect.effect_id)
        if effect.kind is EffectKind.FLUSH_MEDIA:
            await self.cancel_session(sid)
            if self.media is None:return AdapterReceipt(False,'media_coordinator_missing',effect.effect_id)
            await self.media.request_flush(effect)
            return AdapterReceipt(True,'mock_flush_requested_ack_not_proven',effect.effect_id)
        kind=EFFECT_ROUTE.get(effect.kind)
        if kind is None:return AdapterReceipt(False,'unsupported_effect',effect.effect_id)
        if not effect.reference:return AdapterReceipt(False,'opaque_reference_required',effect.effect_id)
        async with self._lock:
            seq=await self.adapters[kind].expected_sequence(sid)
            # Duplicate effect should be routed to the runtime for a replay check
            # rather than incrementing the sequence.
            existing=self.adapters[kind]._jobs.get(effect.effect_id)
            term=self.adapters[kind]._terminal.get(effect.effect_id)
            if existing is not None:seq=existing.command.sequence
            elif term is not None:seq=term[0].sequence
            if existing is not None:deadline=existing.command.deadline
            elif term is not None:deadline=term[0].deadline
            else:deadline=Deadline(deadline_ns if deadline_ns is not None else self.clock.now_ns()+5_000_000_000)
            cmd=SyntheticCommand(effect.effect_id,kind,effect.session_id,effect.turn_id,
                                 effect.generation_id,seq,effect.reference,deadline,
                                 idempotent=(kind is not AdapterKind.TELEPHONY))
            receipt=await self.adapters[kind].submit(cmd)
            return receipt
    async def tick_all(self):
        return {kind:await a.tick() for kind,a in self.adapters.items()}
    def health(self):return {kind.value:a.health() for kind,a in self.adapters.items()}
~~~~

### automotive_voice/audio/__init__.py

~~~~python
from .contracts import Codec, MediaFormat, AudioChunkMetadata, FlushRequest, FlushAck
from .queue import MediaBuffer, MediaReceipt
from .coordinator import MediaCoordinator, DispatchResult
from .ports import AudioBufferPort
__all__=['Codec','MediaFormat','AudioChunkMetadata','FlushRequest','FlushAck','MediaBuffer','MediaReceipt','MediaCoordinator','DispatchResult','AudioBufferPort']
~~~~

### automotive_voice/audio/contracts.py

~~~~python
"""M06 metadata-only media contracts. No audio synthesis, decoding, or sockets.

RTP clock for G.722 is 8000 but decoded sample rate is 16000. G.722 is
negotiation metadata only: packetization/byte validation requires a real codec
implementation in the final acceptance phase.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from uuid import UUID
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId
from automotive_voice.core.audio import AudioFormat

class Codec(str, Enum):
    PCM_S16LE = 'pcm_s16le'
    ALAW = 'alaw'
    MULAW = 'mulaw'
    G722 = 'g722'

@dataclass(frozen=True, slots=True)
class MediaFormat:
    codec: Codec
    sample_rate_hz: int
    channels: int = 1
    rtp_clock_hz: int | None = None

    def __post_init__(self):
        if not isinstance(self.codec, Codec) or type(self.sample_rate_hz) is not int or self.channels != 1 or type(self.channels) is not int:
            raise ValueError('invalid media format')
        if self.codec == Codec.G722:
            if self.sample_rate_hz != 16000 or self.rtp_clock_hz != 8000:
                raise ValueError('G.722 requires 16k decoded / 8k RTP clock; metadata-only')
        else:
            encoding = self.codec.value
            AudioFormat(self.sample_rate_hz, self.channels, 16 if encoding == 'pcm_s16le' else 8, encoding)
            if self.rtp_clock_hz is not None and self.rtp_clock_hz != self.sample_rate_hz:
                raise ValueError('RTP clock mismatch')

    @property
    def payload_supported(self) -> bool:
        return self.codec != Codec.G722

    def expected_bytes(self, sample_count: int) -> int | None:
        if type(sample_count) is not int or sample_count <= 0:
            raise ValueError('sample_count must be positive')
        return None if not self.payload_supported else sample_count * (2 if self.codec == Codec.PCM_S16LE else 1)

    def safe_metadata(self) -> dict:
        return dict(codec=self.codec.value, sample_rate_hz=self.sample_rate_hz,
                    channels=self.channels, rtp_clock_hz=self.rtp_clock_hz)

@dataclass(frozen=True, slots=True)
class AudioChunkMetadata:
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    stream_id: str
    seq: int
    sample_count: int
    duration_ms: int
    timestamp_mono_ns: int
    fmt: MediaFormat
    clause_index: int

    def __post_init__(self):
        if not all((isinstance(self.session_id, SessionId), isinstance(self.turn_id, TurnId),
                    isinstance(self.generation_id, GenerationId), isinstance(self.fmt, MediaFormat))):
            raise TypeError('strong ids and MediaFormat required')
        if not isinstance(self.stream_id, str) or not (1 <= len(self.stream_id) <= 128) or not self.stream_id.isascii() or not all(c.isalnum() or c in '._:-' for c in self.stream_id):
            raise ValueError('unsafe stream ID')
        for name in ('seq','sample_count','duration_ms','timestamp_mono_ns','clause_index'):
            v = getattr(self,name)
            if type(v) is not int or v < (1 if name in ('sample_count','duration_ms') else 0):
                raise ValueError('invalid '+name)
        if self.duration_ms > 2000 or self.sample_count * 1000 != self.fmt.sample_rate_hz * self.duration_ms:
            raise ValueError('inconsistent chunk sample_count/duration; no fractional samples')

    def safe_metadata(self) -> dict:
        return {'session_id':str(self.session_id), 'turn_id':int(self.turn_id),
                'generation_id':int(self.generation_id), 'stream_id':self.stream_id,
                'seq':self.seq,'sample_count':self.sample_count,'duration_ms':self.duration_ms,
                'timestamp_mono_ns':self.timestamp_mono_ns,'clause_index':self.clause_index,
                'media_format':self.fmt.safe_metadata()}

@dataclass(frozen=True, slots=True)
class FlushRequest:
    flush_request_id: str
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId  # NEW generation after M02 interrupt

    def __post_init__(self):
        try: UUID(self.flush_request_id)
        except (TypeError, ValueError, AttributeError) as exc: raise ValueError('flush_request_id must be UUID') from exc
        if not (isinstance(self.session_id,SessionId) and isinstance(self.turn_id,TurnId) and isinstance(self.generation_id,GenerationId)):
            raise TypeError('strong identifiers required')

@dataclass(frozen=True, slots=True)
class FlushAck:
    flush_request_id: str
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    adapter_id: str
    confirmed_by_adapter: bool
    adapter_kind: str = 'fake'  # 'fake' NEVER means PBX confirmed

    def __post_init__(self):
        try: UUID(self.flush_request_id)
        except (ValueError, TypeError, AttributeError) as exc: raise ValueError('invalid ACK UUID') from exc
        if not (isinstance(self.session_id, SessionId) and isinstance(self.turn_id,TurnId) and isinstance(self.generation_id,GenerationId)):
            raise TypeError('strong identifiers required')
        if not self.adapter_id or not self.adapter_id.isascii() or len(self.adapter_id) > 64:
            raise ValueError('invalid adapter identifier')
        if type(self.confirmed_by_adapter) is not bool or self.adapter_kind not in ('fake','asterisk'):
            raise ValueError('invalid ACK provenance')

    @property
    def real_pbx_proven(self) -> bool:
        return False  # No real network in M06, not even for a fake 'asterisk' claim
~~~~

### automotive_voice/audio/coordinator.py

~~~~python
"""M06 glue between M02 effects and a *fake* media transport.

No fabricated PBX acknowledgments. Caller supplies M02 monotonic sequence.
"""
from __future__ import annotations
from dataclasses import dataclass
from automotive_voice.audio.contracts import FlushRequest, FlushAck
from automotive_voice.audio.queue import MediaBuffer
from automotive_voice.core.session import State
from automotive_voice.conversation.effects import Effect, EffectKind
from automotive_voice.conversation.signals import ConversationSignal,SignalKind
from automotive_voice.conversation.reducer import ConversationReducer,ReductionResult,Decision
from automotive_voice.telephony.transport import FakeTransport

@dataclass(frozen=True,slots=True)
class DispatchResult:
    accepted: bool
    reason: str

class MediaCoordinator:
    def __init__(self,reducer:ConversationReducer,buffer:MediaBuffer,transport:FakeTransport):
        self.reducer=reducer;self.buffer=buffer;self.transport=transport
        self._pending:dict[str,FlushRequest]={}

    async def send_next(self,sid:str)->DispatchResult:
        if not self.transport.can_send(sid):return DispatchResult(False,'transport_backpressure')
        chunk=await self.buffer.pop_next(sid)
        if chunk is None:return DispatchResult(False,'no_active_chunk')
        # Revalidate current M01 state immediately before fake transport delivery.
        snap=await self.reducer.manager.snapshot(sid)
        if snap.state is not State.SPEAKING or snap.turn_id != chunk.turn_id or snap.generation_id != chunk.generation_id or not await self.reducer.manager.accepts_chunk(sid,int(chunk.generation_id)):
            return DispatchResult(False,'became_stale')
        ok=await self.transport.send_metadata(chunk)
        if not ok:
            await self.buffer.return_front(chunk)
        return DispatchResult(ok,'sent_mock_metadata' if ok else 'transport_backpressure_after_dequeue')

    async def request_flush(self,effect:Effect)->FlushRequest:
        if not isinstance(effect,Effect) or effect.kind != EffectKind.FLUSH_MEDIA:
            raise ValueError('FLUSH_MEDIA effect required')
        sid=str(effect.session_id)
        snap=await self.reducer.manager.snapshot(sid)
        if snap.state is not State.INTERRUPTING or snap.turn_id!=effect.turn_id or snap.generation_id!=effect.generation_id:
            raise ValueError('flush effect no longer matches M02 state')
        request=FlushRequest(effect.effect_id,effect.session_id,effect.turn_id,effect.generation_id)
        old=self._pending.get(sid)
        if old is not None:
            if old != request:raise ValueError('conflicting pending flush')
            return old
        await self.buffer.begin_flush(sid)
        await self.transport.request_flush(request)
        self._pending[sid]=request
        return request

    async def accept_fake_ack(self,ack:FlushAck,*,sequence:int,mono_ns:int)->ReductionResult:
        """Only accepts explicit fake adapter receipt; never claims actual PBX success."""
        if not isinstance(ack,FlushAck) or not ack.confirmed_by_adapter or ack.adapter_kind!='fake':
            raise ValueError('not a verified fake adapter receipt')
        sid=str(ack.session_id)
        pending=self._pending.get(sid)
        if pending is None or (pending.flush_request_id,pending.session_id,pending.turn_id,pending.generation_id)!=(ack.flush_request_id,ack.session_id,ack.turn_id,ack.generation_id):
            raise ValueError('wrong or replayed flush ACK')
        if ack.adapter_id!=self.transport.adapter_id:raise ValueError('wrong transport adapter')
        if not self.transport.has_confirmed(ack):raise ValueError('unissued or forged fake ACK')
        snap=await self.reducer.manager.snapshot(sid)
        if snap.state!=State.INTERRUPTING or snap.turn_id!=ack.turn_id or snap.generation_id!=ack.generation_id:
            raise ValueError('ACK after state changed')
        signal=ConversationSignal.create(SignalKind.MEDIA_FLUSH_ACK,sid,int(ack.turn_id),int(ack.generation_id),sequence,
                     flush_request_id=ack.flush_request_id,mono_ns=mono_ns)
        result=await self.reducer.handle(signal)
        if result.decision == Decision.APPLIED:
            self.transport.consume_confirmation(ack)
            self._pending.pop(sid,None)
            await self.buffer.end_flush(sid)
        return result

    async def terminate(self,sid:str):
        self._pending.pop(sid,None)
        await self.buffer.close(sid)
        await self.transport.terminate(sid)
~~~~

### automotive_voice/audio/ports.py

~~~~python
"""Implementation-neutral media queue port for later real runtime adapters."""
from __future__ import annotations
from typing import Protocol
from .contracts import AudioChunkMetadata
from .queue import MediaReceipt

class AudioBufferPort(Protocol):
    async def enqueue(self, item: AudioChunkMetadata) -> MediaReceipt: ...
    async def pop_next(self, sid: str) -> AudioChunkMetadata | None: ...
    async def begin_flush(self, sid: str) -> int: ...
    async def end_flush(self, sid: str) -> None: ...
    async def close(self, sid: str) -> None: ...
~~~~

### automotive_voice/audio/queue.py

~~~~python
"""Bounded per-session metadata queue; capacity/sequence/generation gates.

No payloads or sockets. Stale buffered metadata is revalidated at dequeue;
there is no atomic guarantee with external PBX writes (final phase HOLD).
"""
from __future__ import annotations
import asyncio
from collections import deque
from dataclasses import dataclass
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.core.session import State
from .contracts import AudioChunkMetadata

@dataclass(frozen=True, slots=True)
class MediaReceipt:
    accepted: bool
    reason: str
    pending_chunks: int
    pending_ms: int

class MediaBuffer:
    def __init__(self, manager: SessionManager, *, max_chunks_per_session: int = 64,
                 max_ms_per_session: int = 2000, max_seen_per_session: int = 256):
        for value in (max_chunks_per_session, max_ms_per_session, max_seen_per_session):
            if type(value) is not int or value < 1: raise ValueError('positive bounds required')
        self.manager=manager
        self.max_chunks_per_session=max_chunks_per_session
        self.max_ms_per_session=max_ms_per_session
        self.max_seen_per_session=max_seen_per_session
        self._queues: dict[str, deque[AudioChunkMetadata]]={}
        self._locks: dict[str,asyncio.Lock]={}
        self._expected: dict[tuple[str,int,int,str],int]={}
        self._seen: dict[tuple[str,int,int,str,int],AudioChunkMetadata]={}
        self._seen_fifo: dict[str,deque[tuple[str,int,int,str,int]]]={}
        self._blocked: set[str]=set()
        self._registry_lock=asyncio.Lock()

    async def _lock(self,sid: str) -> asyncio.Lock:
        async with self._registry_lock:
            return self._locks.setdefault(sid,asyncio.Lock())

    async def _active(self,item: AudioChunkMetadata) -> bool:
        try:
            snap=await self.manager.snapshot(str(item.session_id))
            token=await self.manager.current_token(str(item.session_id))
            return snap.state==State.SPEAKING and snap.turn_id==item.turn_id and snap.generation_id==item.generation_id and not token.cancelled and token.generation_id==item.generation_id
        except (LookupError, ValueError): return False

    def _receipt(self,sid: str,ok: bool,reason:str) -> MediaReceipt:
        q=self._queues.get(sid,())
        return MediaReceipt(ok,reason,len(q),sum(x.duration_ms for x in q))

    async def enqueue(self,item: AudioChunkMetadata) -> MediaReceipt:
        if not isinstance(item,AudioChunkMetadata): raise TypeError('AudioChunkMetadata required')
        sid=str(item.session_id)
        lock=await self._lock(sid)
        async with lock:
            if sid in self._blocked: return self._receipt(sid,False,'flush_pending')
            if not await self._active(item): return self._receipt(sid,False,'stale_generation_or_state')
            key=(sid,int(item.turn_id),int(item.generation_id),item.stream_id)
            replay_key=(*key,item.seq)
            old=self._seen.get(replay_key)
            if old is not None:
                return self._receipt(sid,old==item,'duplicate_ignored' if old==item else 'conflicting_replay')
            expected=self._expected.get(key,0)
            if item.seq!=expected:
                return self._receipt(sid,False,'sequence_gap' if item.seq>expected else 'stale_sequence')
            q=self._queues.setdefault(sid,deque())
            if len(q)>=self.max_chunks_per_session or sum(x.duration_ms for x in q)+item.duration_ms>self.max_ms_per_session:
                return self._receipt(sid,False,'backpressure')
            q.append(item);self._expected[key]=expected+1;self._seen[replay_key]=item
            fifo=self._seen_fifo.setdefault(sid,deque());fifo.append(replay_key)
            while len(fifo)>self.max_seen_per_session:
                self._seen.pop(fifo.popleft(),None)
            return self._receipt(sid,True,'queued')

    async def pop_next(self,sid:str) -> AudioChunkMetadata | None:
        lock=await self._lock(sid)
        async with lock:
            if sid in self._blocked: return None
            q=self._queues.setdefault(sid,deque())
            while q:
                item=q.popleft()
                if await self._active(item): return item
            return None


    async def return_front(self,item: AudioChunkMetadata)->bool:
        """Restore a popped chunk if a mock transport rejects before delivery.

        Caller must retry; no sequence counter changes. Never revive stale media.
        """
        sid=str(item.session_id)
        lock=await self._lock(sid)
        async with lock:
            if sid in self._blocked or not await self._active(item):return False
            q=self._queues.setdefault(sid,deque())
            if len(q)>=self.max_chunks_per_session or sum(x.duration_ms for x in q)+item.duration_ms>self.max_ms_per_session:return False
            if q and q[0].seq <= item.seq and q[0].stream_id==item.stream_id and q[0].generation_id==item.generation_id:return False
            q.appendleft(item)
            return True

    async def discard_stale(self,sid: str) -> int:
        lock=await self._lock(sid)
        async with lock:
            q=self._queues.setdefault(sid,deque())
            kept=deque()
            for item in q:
                if await self._active(item): kept.append(item)
            count=len(q)-len(kept);self._queues[sid]=kept
            return count

    async def begin_flush(self,sid:str) -> int:
        """Local queue invalidation, deliberately NOT a PBX ACK."""
        lock=await self._lock(sid)
        async with lock:
            self._blocked.add(sid)
            q=self._queues.setdefault(sid,deque())
            n=len(q);q.clear();return n

    async def end_flush(self,sid:str):
        lock=await self._lock(sid)
        async with lock: self._blocked.discard(sid)

    async def close(self,sid:str):
        lock=await self._lock(sid)
        async with lock:
            self._blocked.add(sid)
            self._queues.setdefault(sid,deque()).clear()

    async def metrics(self,sid:str) -> MediaReceipt:
        lock=await self._lock(sid)
        async with lock:return self._receipt(sid,True,'snapshot')
~~~~

### automotive_voice/conversation/__init__.py

~~~~python
"""M02 deterministic inbound conversation signal reducer."""
from .signals import ConversationSignal, SignalKind
from .reducer import ConversationReducer, ReductionResult, Decision, AuditRecord
from .effects import Effect, EffectKind

__all__ = ["ConversationSignal", "SignalKind", "ConversationReducer", "ReductionResult", "Decision", "AuditRecord", "Effect", "EffectKind"]
~~~~

### automotive_voice/conversation/effects.py

~~~~python
"""Transport-independent effects. No network or audio side effects in reducer."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from uuid import uuid5, NAMESPACE_URL
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId


class EffectKind(str, Enum):
    REQUEST_LLM = "request_llm"
    START_TTS = "start_tts"
    QUEUE_AUDIO = "queue_audio"
    CANCEL_GENERATION = "cancel_generation"
    FLUSH_MEDIA = "flush_media"
    START_HANDOFF = "start_handoff"
    TERMINATE_CALL = "terminate_call"


@dataclass(frozen=True, slots=True)
class Effect:
    effect_id: str
    kind: EffectKind
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    related_event_id: str
    reference: str | None = None

    @classmethod
    def from_signal(cls, signal, kind: EffectKind, turn_id: int, generation_id: int,
                    reference: str | None = None) -> 'Effect':
        uid = str(uuid5(NAMESPACE_URL, f"freya-m02:{signal.session_id}:{signal.event_id}:{kind.value}"))
        return cls(uid, kind, signal.session_id, TurnId(turn_id), GenerationId(generation_id), signal.event_id, reference)
~~~~

### automotive_voice/conversation/reducer.py

~~~~python
"""Deterministic, per-session M02 reducer built on M01 SessionManager.

Signal receipt is separate from effect delivery. Neither transport ACK nor durable
outbox is implied by queuing an effect. Inputs carry references, never transcript
text/audio/PII. The only source of session state is M01 SessionManager.
"""
from __future__ import annotations
import asyncio
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid5, NAMESPACE_URL
from automotive_voice.core.session import State
from automotive_voice.core.session_manager import (SessionManager, SessionOutboxFullError,
                                                   UnknownSessionError)
from automotive_voice.core.event_bus import EventBus
from .signals import ConversationSignal, SignalKind
from .effects import Effect, EffectKind


class Decision(str, Enum):
    APPLIED = "applied"
    IGNORED = "ignored"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class AuditRecord:
    event_id: str
    session_id: str
    sequence: int
    kind: SignalKind
    decision: Decision
    reason: str
    state: State | None


@dataclass(frozen=True, slots=True)
class ReductionResult:
    decision: Decision
    reason: str
    state: State | None
    effects: tuple[Effect, ...]
    input_sequence: int


@dataclass(slots=True)
class _Runtime:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    expected_input: int = 0
    last_mono_ns: int = -1
    seen_ids: set[str] = field(default_factory=set)
    seen_order: deque[str] = field(default_factory=deque)
    pending_effects: deque[Effect] = field(default_factory=deque)
    audit: deque[AuditRecord] = field(default_factory=lambda: deque(maxlen=1024))
    pending_flush_id: str | None = None
    flush_deadline_mono_ns: int | None = None
    deferred_transcript_ref: str | None = None
    deferred_handoff: bool = False
    vad_active: bool = False


class ConversationReducer:
    def __init__(self, manager: SessionManager | None = None, *, effect_capacity: int = 256,
                 dedup_capacity: int = 4096, audit_capacity: int = 1024,
                 flush_timeout_ms: int = 1500):
        for name, value in (("effect_capacity", effect_capacity),
                            ("dedup_capacity", dedup_capacity), ("audit_capacity", audit_capacity),
                            ("flush_timeout_ms", flush_timeout_ms)):
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.manager = manager or SessionManager(EventBus())
        self.effect_capacity = effect_capacity
        self.dedup_capacity = dedup_capacity
        self.audit_capacity = audit_capacity
        self.flush_timeout_ns = flush_timeout_ms * 1_000_000
        self._runtimes: dict[str, _Runtime] = {}
        self._directory_lock = asyncio.Lock()

    async def _runtime(self, sid: str) -> _Runtime:
        async with self._directory_lock:
            if sid not in self._runtimes:
                r = _Runtime()
                r.audit = deque(maxlen=self.audit_capacity)
                self._runtimes[sid] = r
            return self._runtimes[sid]

    async def _state(self, sid: str):
        try:
            return await self.manager.snapshot(sid)
        except UnknownSessionError:
            return None

    async def handle(self, signal: ConversationSignal) -> ReductionResult:
        if not isinstance(signal, ConversationSignal):
            raise TypeError("ConversationSignal required")
        # Do not allocate a runtime for arbitrary unknown external session IDs.
        if signal.kind != SignalKind.SESSION_OPENED and str(signal.session_id) not in self._runtimes:
            existing = await self._state(str(signal.session_id))
            if existing is None:
                return ReductionResult(Decision.REJECTED, "unknown_session", None, (), -1)
        rt = await self._runtime(str(signal.session_id))
        async with rt.lock:
            snap = await self._state(str(signal.session_id))
            state = snap.state if snap else None

            def result(decision: Decision, reason: str, effects=(), *, consume=False):
                if consume:
                    rt.expected_input += 1
                    rt.last_mono_ns = signal.occurred_mono_ns
                    if signal.event_id not in rt.seen_ids:
                        rt.seen_ids.add(signal.event_id)
                        rt.seen_order.append(signal.event_id)
                        while len(rt.seen_order) > self.dedup_capacity:
                            rt.seen_ids.discard(rt.seen_order.popleft())
                rt.audit.append(AuditRecord(signal.event_id, str(signal.session_id),
                              signal.sequence, signal.kind, decision, reason, state))
                return ReductionResult(decision, reason, state, tuple(effects), signal.sequence)

            if signal.sequence < rt.expected_input:
                return result(Decision.IGNORED, "replayed_sequence")
            if signal.sequence > rt.expected_input:
                return result(Decision.REJECTED, "sequence_gap")
            if signal.event_id in rt.seen_ids:
                return result(Decision.IGNORED, "duplicate_event_id", consume=True)
            if signal.occurred_mono_ns < rt.last_mono_ns:
                return result(Decision.REJECTED, "monotonic_clock_regression")
            if snap is None and signal.kind != SignalKind.SESSION_OPENED:
                return result(Decision.REJECTED, "unknown_session")
            if snap is not None and signal.kind == SignalKind.SESSION_OPENED:
                return result(Decision.IGNORED, "session_already_open", consume=True)
            if snap is None and (signal.turn_id != 0 or signal.generation_id != 0):
                return result(Decision.REJECTED, "invalid_open_identifiers")
            if snap is not None and state in (State.ENDED, State.FAILED):
                return result(Decision.IGNORED, "terminal_session", consume=True)
            if snap is not None and signal.kind not in (SignalKind.HANGUP,) and (
                    int(signal.turn_id) != int(snap.turn_id) or
                    int(signal.generation_id) != int(snap.generation_id)):
                return result(Decision.IGNORED, "stale_turn_or_generation", consume=True)

            def effect(kind: EffectKind, t: int, g: int, ref: str | None = None):
                return Effect.from_signal(signal, kind, t, g, ref)

            # Compute which side effects will be queued before mutating the M01 state.
            planned: list[Effect] = []
            pending_flush_id = rt.pending_flush_id
            ack_followup = None
            deferred_ref = rt.deferred_transcript_ref
            sid = str(signal.session_id)
            t = int(snap.turn_id) if snap else 0
            g = int(snap.generation_id) if snap else 0
            action = "ignore"
            reason = "invalid_state_for_signal"

            if signal.kind == SignalKind.SESSION_OPENED:
                action = "open"
            elif signal.kind == SignalKind.HANGUP:
                action = "end"
                planned = [effect(EffectKind.TERMINATE_CALL, t, g)]
            elif signal.kind == SignalKind.VAD_SPEECH_STARTED:
                if state == State.LISTENING:
                    action = "vad_listen"
                elif state == State.THINKING:
                    action = "abort_thinking"
                    planned = [effect(EffectKind.CANCEL_GENERATION, t, g)]
                elif state == State.SPEAKING:
                    action = "interrupt"
                    planned = [effect(EffectKind.CANCEL_GENERATION, t, g),
                               effect(EffectKind.FLUSH_MEDIA, t, g + 1)]
                else:
                    reason = "vad_not_accepted_in_state"
            elif signal.kind == SignalKind.TRANSCRIPT_FINAL:
                if state == State.LISTENING:
                    action = "turn"
                    planned = [effect(EffectKind.REQUEST_LLM, t + 1, g + 1, signal.reference)]
                elif state == State.INTERRUPTING and rt.pending_flush_id:
                    if rt.deferred_handoff:
                        reason = "handoff_pending_no_transcript"
                    elif rt.deferred_transcript_ref is None:
                        action = "defer_transcript"
                    else:
                        reason = "transcript_already_deferred"
            elif signal.kind == SignalKind.LLM_RESPONSE_READY:
                if state == State.THINKING:
                    action = "speak"
                    planned = [effect(EffectKind.START_TTS, t, g, signal.reference)]
            elif signal.kind == SignalKind.AUDIO_CHUNK_READY:
                if state == State.SPEAKING and await self.manager.accepts_chunk(sid, g):
                    action = "chunk"
                    planned = [effect(EffectKind.QUEUE_AUDIO, t, g, signal.reference)]
            elif signal.kind == SignalKind.PLAYOUT_FINISHED:
                if state == State.SPEAKING:
                    action = "playout"
            elif signal.kind == SignalKind.HANDOFF_REQUESTED:
                if state in (State.LISTENING, State.THINKING):
                    action = "handoff"
                    if state == State.THINKING:
                        planned.append(effect(EffectKind.CANCEL_GENERATION, t, g))
                    planned.append(effect(EffectKind.START_HANDOFF, t, g))
                elif state == State.SPEAKING:
                    action = "interrupt_handoff"
                    planned = [effect(EffectKind.CANCEL_GENERATION, t, g),
                               effect(EffectKind.FLUSH_MEDIA, t, g + 1)]
                elif state == State.INTERRUPTING and not rt.deferred_handoff:
                    action = "defer_handoff"
            elif signal.kind in (SignalKind.MEDIA_FLUSH_ACK, SignalKind.MEDIA_FLUSH_TIMEOUT):
                if state == State.INTERRUPTING and rt.pending_flush_id == signal.flush_request_id:
                    if signal.kind == SignalKind.MEDIA_FLUSH_TIMEOUT:
                        action = "timeout"
                        planned = [effect(EffectKind.TERMINATE_CALL, t, g)]
                    else:
                        action = "ack"
                        ack_followup = "handoff" if rt.deferred_handoff else "turn" if deferred_ref else None
                        if ack_followup == "turn":
                            planned = [effect(EffectKind.REQUEST_LLM, t + 1, g + 1, deferred_ref)]
                        elif ack_followup == "handoff":
                            planned = [effect(EffectKind.START_HANDOFF, t, g)]
                else:
                    reason = "unmatched_flush_request"
            if action == "ignore":
                return result(Decision.IGNORED, reason, consume=True)
            if action not in ("end", "timeout") and len(rt.pending_effects) + len(planned) > self.effect_capacity:
                return result(Decision.REJECTED, "effect_queue_full")
            # No external callbacks or network effects inside this lock. M01 is the
            # authority for state mutation and bounded event-outbox rollback.
            try:
                if action == "open":
                    await self.manager.create(sid)
                    snap = await self.manager.start(sid)
                elif action == "end":
                    snap = await self.manager.end(sid)
                elif action == "turn":
                    snap = await self.manager.begin_turn(sid)
                elif action == "speak":
                    snap = await self.manager.begin_response(sid)
                elif action == "playout":
                    snap = await self.manager.finish_playout(sid)
                elif action in ("interrupt", "interrupt_handoff"):
                    snap = await self.manager.interrupt(sid)
                elif action == "abort_thinking":
                    snap = await self.manager.abort_thinking(sid)
                elif action == "handoff":
                    snap = await self.manager.request_handoff(sid)
                elif action == "timeout":
                    snap = await self.manager.fail(sid, "media_flush_timeout")
                elif action == "ack":
                    snap = await self.manager.complete_interrupt_with_followup(sid, ack_followup)
            except SessionOutboxFullError:
                if action not in ("end", "timeout"):
                    return result(Decision.REJECTED, "state_or_outbox_rejected")
                # The safe end state takes precedence over audit delivery.
                snap = await self.manager.emergency_close(sid, fail=(action == "timeout"))
                action = "emergency_closed_no_m01_event"
            except ValueError:
                return result(Decision.REJECTED, "state_or_outbox_rejected")

            if action in ("interrupt", "interrupt_handoff"):
                rt.pending_flush_id = planned[-1].effect_id
                rt.flush_deadline_mono_ns = signal.occurred_mono_ns + self.flush_timeout_ns
                rt.deferred_transcript_ref = None
                rt.deferred_handoff = action == "interrupt_handoff"
                rt.vad_active = action == "interrupt"
            elif action == "defer_transcript":
                rt.deferred_transcript_ref = signal.reference
            elif action == "defer_handoff":
                rt.deferred_handoff = True
                rt.deferred_transcript_ref = None
            elif action in ("ack", "timeout", "end", "emergency_closed_no_m01_event"):
                rt.pending_flush_id = None
                rt.flush_deadline_mono_ns = None
                rt.deferred_transcript_ref = None
                rt.deferred_handoff = False
                rt.vad_active = False
            elif action in ("vad_listen", "abort_thinking"):
                rt.vad_active = True
            elif action in ("turn", "playout", "handoff"):
                rt.vad_active = False
            # Drop queued stale output commands before placing terminal transport
            # command. This only controls the volatile command queue, not PBX.
            if action in ("end", "timeout", "emergency_closed_no_m01_event"):
                rt.pending_effects.clear()
            rt.pending_effects.extend(planned)
            out = result(Decision.APPLIED, action, planned, consume=True)
            # result() emits an immutable audit log, but state belongs to M01.
            rt.audit[-1] = AuditRecord(signal.event_id, sid, signal.sequence,
                                      signal.kind, Decision.APPLIED, action, snap.state)
            return ReductionResult(Decision.APPLIED, action, snap.state, tuple(planned), signal.sequence)

    async def poll_flush_timeouts(self, now_mono_ns: int) -> dict[str, ReductionResult]:
        """Explicit deterministic watchdog tick (no background timer).

        A scheduler must call this regularly; M02 does not secretly run tasks.
        Passing a synthetic monotonic timestamp makes timeout tests reproducible.
        """
        if type(now_mono_ns) is not int or now_mono_ns < 0:
            raise ValueError("now_mono_ns must be nonnegative integer")
        outcomes: dict[str, ReductionResult] = {}
        for sid in tuple(self._runtimes):
            rt = await self._runtime(sid)
            async with rt.lock:
                flush_id = rt.pending_flush_id
                deadline = rt.flush_deadline_mono_ns
                expected = rt.expected_input
                mono = max(now_mono_ns, rt.last_mono_ns)
            if flush_id is None or deadline is None or now_mono_ns < deadline:
                continue
            snap = await self._state(sid)
            if snap is None or snap.state != State.INTERRUPTING:
                continue
            signal_id = str(uuid5(NAMESPACE_URL, f"freya-m02-timeout:{sid}:{flush_id}"))
            signal = ConversationSignal.create(SignalKind.MEDIA_FLUSH_TIMEOUT, sid,
                        int(snap.turn_id), int(snap.generation_id), expected,
                        flush_request_id=flush_id, event_id=signal_id, mono_ns=mono)
            outcomes[sid] = await self.handle(signal)
        return outcomes

    async def try_snapshot(self, session_id: str):
        """Public read-only snapshot; None until SESSION_OPENED is accepted."""
        return await self._state(str(session_id))

    async def pending_effects(self, session_id: str) -> tuple[Effect, ...]:
        rt = await self._runtime(session_id)
        async with rt.lock:
            return tuple(rt.pending_effects)

    async def drain_effects(self, session_id: str, limit: int | None = None) -> tuple[Effect, ...]:
        """Transfers volatile effects to caller; NOT delivery acknowledgment."""
        rt = await self._runtime(session_id)
        async with rt.lock:
            n = len(rt.pending_effects) if limit is None else limit
            if type(n) is not int or n < 0:
                raise ValueError("limit must be nonnegative integer")
            return tuple(rt.pending_effects.popleft() for _ in range(min(n, len(rt.pending_effects))))

    async def audit_records(self, session_id: str) -> tuple[AuditRecord, ...]:
        rt = await self._runtime(session_id)
        async with rt.lock:
            return tuple(rt.audit)

    async def pending_flush_id(self, session_id: str) -> str | None:
        rt = await self._runtime(session_id)
        async with rt.lock:
            return rt.pending_flush_id

    async def expected_sequence(self, session_id: str) -> int:
        rt = await self._runtime(session_id)
        async with rt.lock:
            return rt.expected_input
~~~~

### automotive_voice/conversation/signals.py

~~~~python
"""M02 external control signals; no raw audio or personal transcripts in events."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import time
from uuid import UUID, uuid4
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId


class SignalKind(str, Enum):
    SESSION_OPENED = "session_opened"
    VAD_SPEECH_STARTED = "vad_speech_started"
    TRANSCRIPT_FINAL = "transcript_final"
    LLM_RESPONSE_READY = "llm_response_ready"
    AUDIO_CHUNK_READY = "audio_chunk_ready"
    PLAYOUT_FINISHED = "playout_finished"
    MEDIA_FLUSH_ACK = "media_flush_ack"
    MEDIA_FLUSH_TIMEOUT = "media_flush_timeout"
    HANDOFF_REQUESTED = "handoff_requested"
    HANGUP = "hangup"


_REF_KINDS = {SignalKind.TRANSCRIPT_FINAL, SignalKind.LLM_RESPONSE_READY, SignalKind.AUDIO_CHUNK_READY}
_FLUSH_KINDS = {SignalKind.MEDIA_FLUSH_ACK, SignalKind.MEDIA_FLUSH_TIMEOUT}


@dataclass(frozen=True, slots=True)
class ConversationSignal:
    event_id: str
    kind: SignalKind
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    sequence: int
    occurred_at_utc: str
    occurred_mono_ns: int
    reference: str | None = None
    flush_request_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SignalKind):
            raise ValueError("Unsupported signal kind")
        try:
            UUID(self.event_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("event_id must be UUID") from exc
        SessionId(self.session_id); TurnId(self.turn_id); GenerationId(self.generation_id)
        for key in ("sequence", "occurred_mono_ns"):
            v = getattr(self, key)
            if type(v) is not int or v < 0 or v > 2**63-1:
                raise ValueError(f"Invalid {key}")
        try:
            dt = datetime.fromisoformat(self.occurred_at_utc.replace('Z', '+00:00'))
            if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
                raise ValueError("not UTC")
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("occurred_at_utc must be UTC") from exc
        if self.kind in _REF_KINDS:
            if not isinstance(self.reference, str) or not (1 <= len(self.reference) <= 128) or not self.reference.isascii() or not all(c.isalnum() or c in "_-.:/" for c in self.reference):
                raise ValueError("A non-PII safe reference is required")
        elif self.reference is not None:
            raise ValueError("Reference is unexpected for this signal")
        if self.kind in _FLUSH_KINDS:
            try:
                UUID(self.flush_request_id)
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError("Flush ack/timeout requires UUID flush_request_id") from exc
        elif self.flush_request_id is not None:
            raise ValueError("Unexpected flush_request_id")

    @classmethod
    def create(cls, kind: SignalKind, session_id: str, turn_id: int, generation_id: int,
               sequence: int, *, reference: str | None = None, flush_request_id: str | None = None,
               event_id: str | None = None, mono_ns: int | None = None) -> 'ConversationSignal':
        return cls(str(uuid4()) if event_id is None else event_id, kind, SessionId(session_id),
                   TurnId(turn_id), GenerationId(generation_id), sequence,
                   datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                   time.monotonic_ns() if mono_ns is None else mono_ns,
                   reference, flush_request_id)
~~~~

### automotive_voice/core/audio.py

~~~~python
"""Strictly typed audio metadata; no codec decode, resampling or real audio."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
from automotive_voice.core.identifiers import SessionId, GenerationId

AudioEncoding = Literal["pcm_s16le", "float32", "alaw", "mulaw"]
_WIDTH = {"pcm_s16le": 16, "float32": 32, "alaw": 8, "mulaw": 8}

@dataclass(frozen=True, slots=True)
class AudioFormat:
    sample_rate: int
    channels: int
    sample_width_bits: int
    encoding: AudioEncoding

    def __post_init__(self) -> None:
        if type(self.sample_rate) is not int or self.sample_rate not in (8000, 16000, 48000):
            raise ValueError("Unsupported sample rate; explicit conversion required")
        if type(self.channels) is not int or self.channels != 1:
            raise ValueError("Only explicit mono audio is supported in M01")
        if self.encoding not in _WIDTH or type(self.sample_width_bits) is not int or self.sample_width_bits != _WIDTH[self.encoding]:
            raise ValueError("Encoding and sample width mismatch")
        if self.encoding in ("alaw", "mulaw") and self.sample_rate != 8000:
            raise ValueError("G.711 A-law/µ-law telephony requires 8 kHz in this contract")

    @property
    def bytes_per_sample(self) -> int:
        return self.sample_width_bits // 8

    def assert_compatible(self, other: "AudioFormat") -> None:
        if self != other:
            raise ValueError("Audio formats differ; caller must explicitly convert")

@dataclass(frozen=True, slots=True)
class AudioFrame:
    session_id: SessionId
    stream_id: str
    generation_id: GenerationId
    seq: int
    sample_count: int
    timestamp_mono_ns: int
    audio_format: AudioFormat
    payload: bytes

    def __post_init__(self) -> None:
        SessionId(self.session_id)
        if not isinstance(self.stream_id, str) or not (1 <= len(self.stream_id) <= 128):
            raise ValueError("stream_id required (<=128 characters)")
        GenerationId(self.generation_id)
        for name in ("seq", "sample_count", "timestamp_mono_ns"):
            val = getattr(self, name)
            if type(val) is not int or val < 0 or (name == "sample_count" and val == 0):
                raise ValueError(f"{name} invalid")
        if not isinstance(self.audio_format, AudioFormat):
            raise TypeError("audio_format must be AudioFormat")
        if not isinstance(self.payload, bytes):
            raise TypeError("payload must be immutable bytes")
        if len(self.payload) != self.sample_count * self.audio_format.channels * self.audio_format.bytes_per_sample:
            raise ValueError("sample_count/payload length mismatch")
~~~~

### automotive_voice/core/cancellation.py

~~~~python
"""Per-session cooperative cancellation and optional asyncio task cancellation."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from automotive_voice.core.identifiers import GenerationId

class StaleGenerationError(RuntimeError): pass

@dataclass(slots=True)
class CancellationToken:
    generation_id: GenerationId
    _cancelled: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _tasks: set[asyncio.Task] = field(default_factory=set, repr=False)

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    async def wait_cancelled(self) -> None:
        await self._cancelled.wait()

    def register_task(self, task: asyncio.Task) -> None:
        if self.cancelled:
            task.cancel()
            raise StaleGenerationError("Generation already cancelled")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def cancel(self) -> None:
        if self.cancelled:
            return
        self._cancelled.set()
        for task in tuple(self._tasks):
            if not task.done():
                task.cancel()

class CancellationController:
    """Caller serializes methods under its session lock (SessionManager)."""
    def __init__(self, initial: GenerationId = GenerationId(0)) -> None:
        self._token = CancellationToken(GenerationId(initial))

    @property
    def current(self) -> CancellationToken:
        return self._token

    def is_current(self, generation_id: int) -> bool:
        return self._token.generation_id == generation_id and not self._token.cancelled

    def token_for(self, generation_id: int) -> CancellationToken:
        if not self.is_current(generation_id):
            raise StaleGenerationError("Stale or cancelled generation")
        return self._token

    def advance(self, generation_id: GenerationId) -> CancellationToken:
        if int(generation_id) <= int(self._token.generation_id):
            raise ValueError("New generation must increase monotonically")
        self._token.cancel()
        self._token = CancellationToken(GenerationId(generation_id))
        return self._token

    def cancel_current(self) -> None:
        self._token.cancel()
~~~~

### automotive_voice/core/event_bus.py

~~~~python
"""Bounded, in-process, at-most-once fanout with atomic backpressure.

No durable storage. Publish does not invoke subscribers; consumers drain queues.
An event cannot be partially enqueued among subscribers on queue overflow.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from automotive_voice.core.events import EventEnvelope

class EventBusError(Exception): pass
class EventBusFull(EventBusError): pass
class EventBusClosed(EventBusError): pass
class EventOrderingError(EventBusError): pass

@dataclass(slots=True)
class Subscription:
    name: str
    _queue: asyncio.Queue[EventEnvelope]
    _closed: bool = False

    def get_nowait(self) -> EventEnvelope:
        return self._queue.get_nowait()

    async def get(self) -> EventEnvelope:
        # call with timeout/cancellation in long-running clients; M01 does not
        # guarantee wake-up for readers already blocked when unsubscribed.
        if self._closed and self._queue.empty():
            raise EventBusClosed("Subscription is closed")
        return await self._queue.get()

    @property
    def pending(self) -> int:
        return self._queue.qsize()

class EventBus:
    def __init__(self, default_capacity: int = 128):
        if type(default_capacity) is not int or default_capacity < 1:
            raise ValueError("default_capacity must be positive")
        self._capacity = default_capacity
        self._subs: dict[str, Subscription] = {}
        self._last_sequence: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def subscribe(self, name: str, capacity: int | None = None) -> Subscription:
        cap = self._capacity if capacity is None else capacity
        if not isinstance(name, str) or not name.strip() or type(cap) is not int or cap < 1:
            raise ValueError("Subscription name/capacity invalid")
        async with self._lock:
            if self._closed:
                raise EventBusClosed("Event bus closed")
            if name in self._subs:
                raise ValueError("Subscription name already used")
            sub = Subscription(name, asyncio.Queue(maxsize=cap))
            self._subs[name] = sub
            return sub

    async def unsubscribe(self, name: str) -> None:
        async with self._lock:
            sub = self._subs.pop(name, None)
            if sub is not None:
                sub._closed = True

    async def publish(self, event: EventEnvelope) -> None:
        if not isinstance(event, EventEnvelope):
            raise TypeError("publish requires EventEnvelope")
        async with self._lock:
            if self._closed:
                raise EventBusClosed("Event bus closed")
            sid = str(event.session_id)
            prev = self._last_sequence.get(sid, -1)
            if event.sequence != prev + 1:
                raise EventOrderingError(f"Session {sid}: expected sequence {prev + 1}, got {event.sequence}")
            # Fanout preflight: do not send to one consumer if another is full.
            if any(sub._queue.full() for sub in self._subs.values()):
                raise EventBusFull("A subscription has reached its bounded capacity")
            for sub in self._subs.values():
                sub._queue.put_nowait(event)
            self._last_sequence[sid] = event.sequence

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            for sub in self._subs.values():
                sub._closed = True
            self._subs.clear()

    def last_published_sequence(self, session_id: str) -> int:
        return self._last_sequence.get(session_id, -1)
~~~~

### automotive_voice/core/events.py

~~~~python
"""Versioned, JSON-safe event envelopes and wire decoding.

Datetime = UTC wall clock for audit; monotonic ns = elapsed-time ordering within
one process. Monotonic values are not comparable across process restarts.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import time
from uuid import UUID, uuid4
from typing import Any, Mapping
from types import MappingProxyType
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId

SCHEMA_VERSION = "1.0"

class EventType(str, Enum):
    SESSION_STARTED = "session_started"
    TURN_STARTED = "turn_started"
    USER_SPEECH_STARTED = "user_speech_started"
    TRANSCRIPT_FINAL = "transcript_final"
    RESPONSE_STARTED = "response_started"
    AUDIO_CHUNK_ENQUEUED = "audio_chunk_enqueued"
    PLAYOUT_FINISHED = "playout_finished"
    INTERRUPTED = "interrupted"
    INTERRUPTION_COMPLETED = "interruption_completed"
    HANDOFF_REQUESTED = "handoff_requested"
    SESSION_ENDED = "session_ended"
    SESSION_FAILED = "session_failed"
    STATE_CHANGED = "state_changed"
    ERROR = "error"

_FIELDS = {"schema_version", "event_id", "event_type", "session_id", "turn_id", "generation_id", "sequence", "occurred_at_utc", "occurred_mono_ns", "payload"}

def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value

def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(v) for v in value]
    return value

def _json_payload(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError("payload must be an object with string keys")
    try:
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
        return json.loads(encoded)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("payload must be strictly JSON serializable") from exc

@dataclass(frozen=True, slots=True)
class EventEnvelope:
    schema_version: str
    event_id: str
    event_type: EventType
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    sequence: int
    occurred_at_utc: str
    occurred_mono_ns: int
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported schema_version")
        try:
            UUID(self.event_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Invalid event_id UUID") from exc
        if not isinstance(self.event_type, EventType):
            raise ValueError("event_type must be EventType")
        SessionId(self.session_id); TurnId(self.turn_id); GenerationId(self.generation_id)
        if type(self.sequence) is not int or self.sequence < 0 or self.sequence > 2**63-1:
            raise ValueError("sequence must be a non-negative integer")
        if type(self.occurred_mono_ns) is not int or self.occurred_mono_ns < 0:
            raise ValueError("occurred_mono_ns must be non-negative")
        try:
            ts = datetime.fromisoformat(self.occurred_at_utc.replace('Z','+00:00'))
            if ts.utcoffset() is None or ts.utcoffset().total_seconds() != 0:
                raise ValueError()
        except (TypeError, ValueError) as exc:
            raise ValueError("occurred_at_utc must be an offset-aware UTC ISO timestamp") from exc
        object.__setattr__(self, "payload", _freeze(_json_payload(dict(self.payload))))

    @classmethod
    def create(cls, event_type: EventType, session_id: SessionId, turn_id: TurnId,
               generation_id: GenerationId, sequence: int,
               payload: dict[str, Any] | None = None) -> "EventEnvelope":
        return cls(SCHEMA_VERSION, str(uuid4()), event_type, SessionId(session_id),
                   TurnId(turn_id), GenerationId(generation_id), sequence,
                   datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
                   time.monotonic_ns(), payload or {})

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "event_id": self.event_id,
                "event_type": self.event_type.value, "session_id": str(self.session_id),
                "turn_id": int(self.turn_id), "generation_id": int(self.generation_id),
                "sequence": self.sequence, "occurred_at_utc": self.occurred_at_utc,
                "occurred_mono_ns": self.occurred_mono_ns, "payload": _thaw(self.payload)}

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> "EventEnvelope":
        if not isinstance(obj, dict) or set(obj) != _FIELDS:
            raise ValueError("Event envelope field set mismatch")
        return cls(obj['schema_version'], obj['event_id'], EventType(obj['event_type']),
                   SessionId(obj['session_id']), TurnId(obj['turn_id']),
                   GenerationId(obj['generation_id']), obj['sequence'],
                   obj['occurred_at_utc'], obj['occurred_mono_ns'], obj['payload'])
~~~~

### automotive_voice/core/identifiers.py

~~~~python
"""Strongly checked, serializable identifiers. No model/network dependency."""
from __future__ import annotations
import re
from uuid import uuid4

_VALID_SESSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

class SessionId(str):
    def __new__(cls, value: str) -> "SessionId":
        if not isinstance(value, str) or _VALID_SESSION.fullmatch(value) is None:
            raise ValueError("SessionId must be 1..128 safe ASCII characters")
        return str.__new__(cls, value)

    @classmethod
    def new(cls) -> "SessionId":
        return cls(str(uuid4()))

class _SequenceId(int):
    def __new__(cls, value: int):
        if (not isinstance(value, int) or isinstance(value, bool)) or value < 0 or value > 2**63 - 1:
            raise ValueError(f"{cls.__name__} must be a non-negative signed 64-bit integer")
        return int.__new__(cls, value)

class TurnId(_SequenceId):
    """Session-local conversational turn, starting at zero."""

class GenerationId(_SequenceId):
    """Session-local cancelable response generation, starting at zero."""
~~~~

### automotive_voice/core/session.py

~~~~python
from dataclasses import dataclass, field
from enum import Enum

class State(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    INTERRUPTING = "INTERRUPTING"
    HANDOFF = "HANDOFF"
    FAILED = "FAILED"
    ENDED = "ENDED"

ALLOWED = {
    State.IDLE: {State.LISTENING, State.ENDED},
    State.LISTENING: {State.THINKING, State.HANDOFF, State.ENDED, State.FAILED},
    State.THINKING: {State.SPEAKING, State.HANDOFF, State.LISTENING, State.FAILED, State.ENDED},
    State.SPEAKING: {State.LISTENING, State.INTERRUPTING, State.ENDED, State.FAILED},
    State.INTERRUPTING: {State.LISTENING, State.ENDED, State.FAILED},
    State.HANDOFF: {State.ENDED, State.FAILED},
    State.FAILED: {State.ENDED},
    State.ENDED: set(),
}

@dataclass
class Session:
    session_id: str
    state: State = State.IDLE
    turn_id: int = 0
    generation_id: int = 0
    history: list[State] = field(default_factory=list)

    def move(self, target: State) -> None:
        if target == self.state and target == State.ENDED:
            return  # idempotent teardown
        if target not in ALLOWED[self.state]:
            raise ValueError(f"Invalid state transition: {self.state} -> {target}")
        self.state = target
        self.history.append(target)

    def new_turn(self) -> int:
        if self.state != State.LISTENING:
            raise ValueError("New turn only from listening")
        self.turn_id += 1
        self.generation_id += 1
        self.move(State.THINKING)
        return self.generation_id

    def interrupt(self) -> int:
        if self.state != State.SPEAKING:
            raise ValueError("Barge-in only while speaking")
        self.move(State.INTERRUPTING)
        self.generation_id += 1
        return self.generation_id

    def accepts_chunk(self, generation_id: int) -> bool:
        return self.state == State.SPEAKING and generation_id == self.generation_id
~~~~

### automotive_voice/core/session_manager.py

~~~~python
"""M01 in-memory session authority + bounded per-session event outbox.

All mutations are per-session locked and emit exactly one ordered envelope. The
outbox is retained across bus backpressure; delivery is best-effort in-memory,
not durable/exactly-once. M02 may replace the provisional legacy FSM.
"""
from __future__ import annotations
import asyncio
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Callable
from automotive_voice.core.session import Session, State
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId
from automotive_voice.core.events import EventEnvelope, EventType
from automotive_voice.core.event_bus import EventBus
from automotive_voice.core.cancellation import CancellationController, CancellationToken

class UnknownSessionError(LookupError): pass
class SessionAlreadyExistsError(ValueError): pass
class SessionOutboxFullError(RuntimeError): pass

@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    session_id: SessionId
    state: State
    turn_id: TurnId
    generation_id: GenerationId
    last_sequence: int
    pending_events: int

@dataclass(slots=True)
class _ManagedSession:
    value: Session
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    outbox: deque[EventEnvelope] = field(default_factory=deque)
    last_sequence: int = -1
    cancellation: CancellationController = field(default_factory=CancellationController)

class SessionManager:
    def __init__(self, bus: EventBus, max_pending_events: int = 256):
        if type(max_pending_events) is not int or max_pending_events < 1:
            raise ValueError("max_pending_events must be positive")
        self.bus = bus
        self._pending_limit = max_pending_events
        self._sessions: dict[SessionId, _ManagedSession] = {}
        self._directory_lock = asyncio.Lock()

    async def create(self, session_id: str | None = None) -> SessionSnapshot:
        sid = SessionId.new() if session_id is None else SessionId(session_id)
        async with self._directory_lock:
            if sid in self._sessions:
                raise SessionAlreadyExistsError(f"Session already exists: {sid}")
            managed = _ManagedSession(Session(sid))
            self._sessions[sid] = managed
            return self._snapshot(managed)

    def _entry(self, session_id: str) -> _ManagedSession:
        sid = SessionId(session_id)
        try:
            return self._sessions[sid]
        except KeyError as exc:
            raise UnknownSessionError(sid) from exc

    @staticmethod
    def _snapshot(managed: _ManagedSession) -> SessionSnapshot:
        s = managed.value
        return SessionSnapshot(SessionId(s.session_id), s.state, TurnId(s.turn_id),
                               GenerationId(s.generation_id), managed.last_sequence,
                               len(managed.outbox))

    async def snapshot(self, session_id: str) -> SessionSnapshot:
        m = self._entry(session_id)
        async with m.lock:
            return self._snapshot(m)

    async def _apply(self, session_id: str, event_type: EventType,
                     mutation: Callable[[Session], None],
                     payload: dict | None = None,
                     *, idempotent_ended: bool = False) -> SessionSnapshot:
        m = self._entry(session_id)
        async with m.lock:
            if idempotent_ended and m.value.state == State.ENDED:
                return self._snapshot(m)
            if len(m.outbox) >= self._pending_limit:
                raise SessionOutboxFullError("Outbox full; dispatch before more transitions")
            # Apply to a separate copy before committing: validation failures
            # must not mutate the source or assign event sequence IDs.
            new = replace(m.value, history=list(m.value.history))
            old_generation = new.generation_id
            mutation(new)
            event = EventEnvelope.create(event_type, SessionId(new.session_id),
                    TurnId(new.turn_id), GenerationId(new.generation_id),
                    m.last_sequence + 1, payload or {})
            m.value = new
            m.last_sequence += 1
            m.outbox.append(event)
            if new.state in (State.ENDED, State.FAILED, State.HANDOFF):
                m.cancellation.cancel_current()
            elif new.generation_id > old_generation:
                m.cancellation.advance(GenerationId(new.generation_id))
            return self._snapshot(m)

    async def start(self, session_id: str) -> SessionSnapshot:
        return await self._apply(session_id, EventType.SESSION_STARTED,
                                 lambda s: s.move(State.LISTENING), {"to": "LISTENING"})

    async def begin_turn(self, session_id: str) -> SessionSnapshot:
        return await self._apply(session_id, EventType.TURN_STARTED,
                                 lambda s: s.new_turn(), {"to": "THINKING"})

    async def begin_response(self, session_id: str) -> SessionSnapshot:
        return await self._apply(session_id, EventType.RESPONSE_STARTED,
                                 lambda s: s.move(State.SPEAKING), {"to": "SPEAKING"})

    async def finish_playout(self, session_id: str) -> SessionSnapshot:
        return await self._apply(session_id, EventType.PLAYOUT_FINISHED,
                                 lambda s: s.move(State.LISTENING), {"to": "LISTENING"})

    async def interrupt(self, session_id: str) -> SessionSnapshot:
        return await self._apply(session_id, EventType.INTERRUPTED,
                                 lambda s: s.interrupt(), {"to": "INTERRUPTING", "reason": "barge_in"})

    async def complete_interrupt(self, session_id: str) -> SessionSnapshot:
        return await self._apply(session_id, EventType.INTERRUPTION_COMPLETED,
                                 lambda s: s.move(State.LISTENING), {"to": "LISTENING"})

    async def request_handoff(self, session_id: str) -> SessionSnapshot:
        return await self._apply(session_id, EventType.HANDOFF_REQUESTED,
                                 lambda s: s.move(State.HANDOFF), {"to": "HANDOFF"})

    async def fail(self, session_id: str, reason_code: str) -> SessionSnapshot:
        if not reason_code or len(reason_code) > 64:
            raise ValueError("reason_code required")
        return await self._apply(session_id, EventType.SESSION_FAILED,
                                 lambda s: s.move(State.FAILED), {"code": reason_code})

    async def end(self, session_id: str, *, closure_reason: str | None = None) -> SessionSnapshot:
        payload = {"to": "ENDED"}
        if closure_reason is not None:
            if closure_reason not in {"normal", "disconnect", "transport_error"}:
                raise ValueError("invalid closure reason")
            payload["closure_reason"] = closure_reason
        return await self._apply(session_id, EventType.SESSION_ENDED,
                                 lambda s: s.move(State.ENDED), payload, idempotent_ended=True)

    async def emergency_close(self, session_id: str, *, fail: bool = False) -> SessionSnapshot:
        """Fail-closed terminal path when RAM outbox is saturated.

        Intentionally emits NO EventEnvelope when the bounded outbox has no room.
        Caller MUST record an independent diagnostic and send a terminate command.
        This is a safety fallback, not a durable or fully audited transaction.
        """
        managed = self._entry(session_id)
        async with managed.lock:
            if managed.value.state in (State.ENDED, State.FAILED):
                return self._snapshot(managed)
            new = replace(managed.value, history=list(managed.value.history))
            new.move(State.FAILED if fail and new.state != State.IDLE else State.ENDED)
            managed.value = new
            managed.cancellation.cancel_current()
            return self._snapshot(managed)

    async def abort_thinking(self, session_id: str) -> SessionSnapshot:
        """Drop an unspoken LLM answer after user speech; invalidate old generation.

        Additive M02-compatible API; leaves the M01 public methods unchanged.
        """
        def mutation(s: Session) -> None:
            if s.state != State.THINKING:
                raise ValueError("abort_thinking only valid in THINKING")
            s.move(State.LISTENING)
            s.generation_id += 1
        return await self._apply(session_id, EventType.STATE_CHANGED, mutation,
                                 {"to": "LISTENING", "reason": "thinking_interrupted"})

    async def complete_interrupt_with_followup(self, session_id: str,
                                                 followup: str | None = None) -> SessionSnapshot:
        """Atomically commit flush completion + optional new turn/handoff.

        Prevents a partially committed LISTENING state if second transition
        fails due to M01 outbox backpressure. The caller MUST validate that a
        matching transport flush ACK was received before invoking this method.
        """
        if followup not in (None, "turn", "handoff"):
            raise ValueError("followup must be None, turn, or handoff")
        managed = self._entry(session_id)
        async with managed.lock:
            count = 1 + int(followup is not None)
            if len(managed.outbox) + count > self._pending_limit:
                raise SessionOutboxFullError("Outbox full; atomic flush completion deferred")
            new = replace(managed.value, history=list(managed.value.history))
            if new.state != State.INTERRUPTING:
                raise ValueError("Must be INTERRUPTING before flush ACK")
            start_gen = new.generation_id
            new.move(State.LISTENING)
            sequence = managed.last_sequence + 1
            events = [EventEnvelope.create(EventType.INTERRUPTION_COMPLETED,
                SessionId(new.session_id), TurnId(new.turn_id), GenerationId(new.generation_id),
                sequence, {"to": "LISTENING", "transport_ack": True})]
            if followup == "turn":
                new.new_turn()
                events.append(EventEnvelope.create(EventType.TURN_STARTED, SessionId(new.session_id),
                    TurnId(new.turn_id), GenerationId(new.generation_id), sequence + 1,
                    {"to": "THINKING", "source": "deferred_transcript"}))
            elif followup == "handoff":
                new.move(State.HANDOFF)
                events.append(EventEnvelope.create(EventType.HANDOFF_REQUESTED, SessionId(new.session_id),
                    TurnId(new.turn_id), GenerationId(new.generation_id), sequence + 1,
                    {"to": "HANDOFF", "source": "deferred_handoff"}))
            managed.value = new
            managed.last_sequence += len(events)
            managed.outbox.extend(events)
            if new.state == State.HANDOFF:
                managed.cancellation.cancel_current()
            elif new.generation_id > start_gen:
                managed.cancellation.advance(GenerationId(new.generation_id))
            return self._snapshot(managed)

    async def accepts_chunk(self, session_id: str, generation_id: int) -> bool:
        m = self._entry(session_id)
        async with m.lock:
            return m.value.accepts_chunk(generation_id) and m.cancellation.is_current(generation_id)

    async def current_token(self, session_id: str) -> CancellationToken:
        m = self._entry(session_id)
        async with m.lock:
            if m.value.state in (State.ENDED, State.FAILED):
                raise ValueError("Terminal session has no active generation")
            return m.cancellation.current

    async def register_task(self, session_id: str, generation_id: int, task: asyncio.Task) -> None:
        m = self._entry(session_id)
        async with m.lock:
            m.cancellation.token_for(generation_id).register_task(task)

    async def dispatch_pending(self, session_id: str) -> int:
        """Drain in order; on subscriber backpressure, preserve unsent items."""
        m = self._entry(session_id)
        count = 0
        async with m.lock:
            while m.outbox:
                event = m.outbox[0]
                await self.bus.publish(event)
                m.outbox.popleft()
                count += 1
        return count
~~~~

### automotive_voice/dialogue/__init__.py

~~~~python
from .models import (Intent, CaseKind, CaseReceipt, Availability, BookingStatus, Commitment, AccessContext,
    AppointmentSlot, DialogueInput, VehicleRecord, PriceQuote, BookingReceipt, PolicyDecision)
from .storage import ReferenceStore, MissingReferenceError, StoredResponse, StoredTranscript
from .ports import FakeCRM, FakeBookingService, CRMPort, InspectionBookingPort
from .policy import DialoguePolicy
from .coordinator import DialogueCoordinator, CoordinationResult

from .booking_state import BookingStateMachine, BookingStateError
~~~~

### automotive_voice/dialogue/booking_state.py

~~~~python
"""Explicit booking-only transition graph; no audio, LLM, or CRM side effects."""
from .models import BookingStatus

class BookingStateError(ValueError):
    pass

class BookingStateMachine:
    _ALLOWED = {
        BookingStatus.IDLE: {BookingStatus.AWAITING_CONFIRMATION, BookingStatus.UNAVAILABLE,
                             BookingStatus.UNKNOWN, BookingStatus.HANDOFF},
        BookingStatus.AWAITING_CONFIRMATION: {BookingStatus.CONFIRMING, BookingStatus.DECLINED,
                             BookingStatus.UNKNOWN, BookingStatus.UNAVAILABLE, BookingStatus.HANDOFF},
        BookingStatus.CONFIRMING: {BookingStatus.CONFIRMED, BookingStatus.UNAVAILABLE,
                                   BookingStatus.UNKNOWN, BookingStatus.HANDOFF},
        BookingStatus.CONFIRMED: {BookingStatus.HANDOFF},
        BookingStatus.UNAVAILABLE: {BookingStatus.AWAITING_CONFIRMATION, BookingStatus.UNAVAILABLE,
                                     BookingStatus.UNKNOWN, BookingStatus.HANDOFF},
        BookingStatus.UNKNOWN: {BookingStatus.AWAITING_CONFIRMATION, BookingStatus.UNAVAILABLE,
                                 BookingStatus.UNKNOWN, BookingStatus.CONFIRMED, BookingStatus.HANDOFF},
        BookingStatus.DECLINED: {BookingStatus.AWAITING_CONFIRMATION, BookingStatus.UNAVAILABLE,
                                  BookingStatus.UNKNOWN, BookingStatus.HANDOFF},
        BookingStatus.HANDOFF: set(),
    }

    @classmethod
    def transition(cls, source: BookingStatus, target: BookingStatus) -> BookingStatus:
        if not isinstance(source, BookingStatus) or not isinstance(target, BookingStatus):
            raise BookingStateError('BookingStatus required')
        if target == source:
            return source
        if target not in cls._ALLOWED[source]:
            raise BookingStateError(f'Invalid booking transition: {source.value} -> {target.value}')
        return target
~~~~

### automotive_voice/dialogue/coordinator.py

~~~~python
"""Bridge REQUEST_LLM -> deterministic business policy -> M02 safe response ref.

No actual LLM is called. A future NLG adapter may paraphrase approved semantic
results; it must not change prices, booking status or booking confirmation.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Callable
from automotive_voice.conversation import ConversationReducer, ConversationSignal, SignalKind, Decision
from automotive_voice.conversation.effects import Effect, EffectKind
from automotive_voice.core.session import State
from .models import AccessContext
from .policy import DialoguePolicy
from .storage import ReferenceStore, MissingReferenceError

@dataclass(frozen=True, slots=True)
class CoordinationResult:
    status: str
    action: str
    response_ref: str | None = None

class DialogueCoordinator:
    def __init__(self, reducer: ConversationReducer, policy: DialoguePolicy, store: ReferenceStore,
                 *, clock_ns: Callable[[], int] | None = None):
        self.reducer, self.policy, self.store = reducer, policy, store
        self.clock_ns = clock_ns
        self._locks: dict[str, asyncio.Lock] = {}

    async def process(self, effect: Effect, access: AccessContext) -> CoordinationResult:
        if effect.kind != EffectKind.REQUEST_LLM:
            raise ValueError('only REQUEST_LLM effect accepted')
        sid = str(effect.session_id)
        lock = self._locks.setdefault(sid, asyncio.Lock())
        async with lock:
            async def current() -> bool:
                snap = await self.reducer.try_snapshot(sid)
                return bool(snap and snap.state == State.THINKING and
                            int(snap.turn_id) == int(effect.turn_id) and
                            int(snap.generation_id) == int(effect.generation_id))
            if not await current():
                return CoordinationResult('stale', 'stale_generation')
            try:
                inp = self.store.get_input(sid, effect.reference or '')
            except MissingReferenceError:
                # No text is invented when an opaque reference is missing.
                return CoordinationResult('missing_reference', 'missing_transcript')
            try:
                decision = await self.policy.handle(sid, inp, access, is_current=current)
            except Exception:
                if not await current():
                    return CoordinationResult('stale', 'stale_generation')
                safe_ref = self.store.put_response(sid, 'İşlemi şu anda doğrulayamıyorum. Temsilciye aktarılabilirsiniz.', 'business_unknown')
                from .models import PolicyDecision, BookingStatus
                decision = PolicyDecision(safe_ref, BookingStatus.UNKNOWN, 'business_unknown')
            if decision.action == 'stale_generation' or not await current():
                return CoordinationResult('stale', 'stale_generation')
            kind = SignalKind.HANDOFF_REQUESTED if decision.handoff_requested else SignalKind.LLM_RESPONSE_READY
            signal = ConversationSignal.create(kind, sid, int(effect.turn_id), int(effect.generation_id),
                await self.reducer.expected_sequence(sid), reference=decision.response_ref,
                mono_ns=self.clock_ns() if self.clock_ns is not None else None)
            result = await self.reducer.handle(signal)
            return CoordinationResult('applied' if result.decision == Decision.APPLIED else result.decision.value,
                                      decision.action, decision.response_ref if result.decision == Decision.APPLIED else None)
~~~~

### automotive_voice/dialogue/models.py

~~~~python
"""M03 value objects. Avoid raw transcripts or PII in event/audit envelopes."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class Intent(str, Enum):
    GREETING = 'greeting'
    VEHICLE_LOOKUP = 'vehicle_lookup'
    CREATE_CRM_CASE = 'create_crm_case'
    PRICE_LOOKUP = 'price_lookup'
    REQUEST_INSPECTION = 'request_inspection'
    CONFIRM = 'confirm'
    RECHECK_BOOKING = 'recheck_booking'
    DECLINE = 'decline'
    HANDOFF = 'handoff'
    UNKNOWN = 'unknown'

class CaseKind(str, Enum):
    EXPERTISE_INFO = "expertise_info"
    PRICE_REQUEST = "price_request"
    CALLBACK = "callback"

class Availability(str, Enum):
    AVAILABLE = 'available'
    UNAVAILABLE = 'unavailable'
    UNKNOWN = 'unknown'

class BookingStatus(str, Enum):
    IDLE = 'idle'
    AWAITING_CONFIRMATION = 'awaiting_confirmation'
    CONFIRMING = 'confirming'
    CONFIRMED = 'confirmed'
    UNAVAILABLE = 'unavailable'
    UNKNOWN = 'unknown'
    DECLINED = 'declined'
    HANDOFF = 'handoff'

class Commitment(str, Enum):
    CONFIRMED = 'confirmed'
    UNAVAILABLE = 'unavailable'
    UNKNOWN = 'unknown'

@dataclass(frozen=True, slots=True)
class AccessContext:
    authenticated: bool = False
    crm_processing_allowed: bool = False
    marketing_opt_in: bool = False
    # Explicit consent is recorded separately; these flags are demo inputs,
    # not a claim of legal sufficiency under applicable privacy law.

@dataclass(frozen=True, slots=True)
class AppointmentSlot:
    start_at: str
    location_id: str
    def __post_init__(self):
        if not self.location_id or len(self.location_id) > 48 or not all(c.isascii() and (c.isalnum() or c in '_-') for c in self.location_id):
            raise ValueError('invalid location_id')
        try:
            dt = datetime.fromisoformat(self.start_at)
        except (TypeError, ValueError) as e:
            raise ValueError('invalid slot ISO 8601') from e
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError('appointment slot must include timezone offset')

@dataclass(frozen=True, slots=True)
class DialogueInput:
    intent: Intent
    vehicle_id: str | None = None
    slot: AppointmentSlot | None = None
    case_kind: CaseKind | None = None
    def __post_init__(self):
        if not isinstance(self.intent, Intent):
            raise ValueError('invalid intent')
        if self.vehicle_id is not None and (len(self.vehicle_id) > 48 or not self.vehicle_id or not all(c.isascii() and (c.isalnum() or c in '_-') for c in self.vehicle_id)):
            raise ValueError('invalid vehicle_id')
        if self.slot and self.intent != Intent.REQUEST_INSPECTION:
            raise ValueError('slot only valid for inspection request')
        if self.case_kind is not None and (self.intent != Intent.CREATE_CRM_CASE or not isinstance(self.case_kind, CaseKind)):
            raise ValueError('case_kind only valid for CRM case')

@dataclass(frozen=True, slots=True)
class VehicleRecord:
    vehicle_id: str
    brand: str
    model: str
    year: int
    verified: bool = True

@dataclass(frozen=True, slots=True)
class PriceQuote:
    vehicle_id: str
    amount_try: int
    source_ref: str
    valid_until: datetime
    verified: bool = True
    def __post_init__(self):
        if type(self.amount_try) is not int or self.amount_try < 0:
            raise ValueError('positive quote amount expected')
        if not self.source_ref or self.valid_until.tzinfo is None:
            raise ValueError('verifiable quote reference and aware expiry needed')

@dataclass(frozen=True, slots=True)
class BookingReceipt:
    status: Commitment
    reference_id: str | None = None
    def __post_init__(self):
        if self.status == Commitment.CONFIRMED and not self.reference_id:
            raise ValueError('confirmed booking requires reference_id')
        if self.status != Commitment.CONFIRMED and self.reference_id is not None:
            raise ValueError('unconfirmed booking must not expose confirmation ID')

@dataclass(frozen=True, slots=True)
class PolicyDecision:
    response_ref: str | None
    booking_status: BookingStatus
    action: str
    handoff_requested: bool = False
    # No raw text/PII here; only code and opaque reference.

@dataclass(frozen=True, slots=True)
class CaseReceipt:
    accepted: bool
    reference_id: str | None
    def __post_init__(self):
        if bool(self.reference_id) != self.accepted:
            raise ValueError('case reference required only when accepted')
~~~~

### automotive_voice/dialogue/policy.py

~~~~python
"""Deterministic business rules: no LLM can manufacture price or booking status."""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable, Awaitable
from .models import (AccessContext, AppointmentSlot, Availability, BookingStatus,
                     Commitment, DialogueInput, Intent, PolicyDecision)
from .ports import CRMPort, InspectionBookingPort
from .booking_state import BookingStateMachine
from .storage import ReferenceStore

CurrentCheck = Callable[[], Awaitable[bool]]

@dataclass(slots=True)
class _BookingSession:
    booking_status: BookingStatus = BookingStatus.IDLE
    vehicle_id: str | None = None
    pending_slot: AppointmentSlot | None = None
    offer_serial: int = 0
    case_requests: dict[str, str] = field(default_factory=dict)
    idempotency_key: str | None = None
    confirmed_reference: str | None = None
    unknown_count: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def change(self, target: BookingStatus) -> None:
        self.booking_status = BookingStateMachine.transition(self.booking_status, target)

class DialoguePolicy:
    def __init__(self, crm: CRMPort, booking: InspectionBookingPort,
                 store: ReferenceStore, *, now: Callable[[], datetime] | None = None):
        self.crm, self.booking, self.store = crm, booking, store
        self.now = now or (lambda: datetime.now(timezone.utc))
        self._sessions: dict[str, _BookingSession] = {}

    def _session(self, sid: str) -> _BookingSession:
        return self._sessions.setdefault(sid, _BookingSession())

    async def _get_vehicle(self, vehicle_id: str):
        try:
            return await self.crm.get_vehicle(vehicle_id)
        except Exception:
            return None  # fail closed: identity/vehicle is not verified

    def snapshot(self, sid: str) -> dict[str, object]:
        s = self._session(sid)
        return {'booking_status': s.booking_status.value, 'has_pending_slot': bool(s.pending_slot),
                'has_confirmation': bool(s.confirmed_reference), 'unknown_count': s.unknown_count}

    def _respond(self, sid: str, s: _BookingSession, code: str, text: str,
                 *, handoff: bool = False) -> PolicyDecision:
        ref = None if handoff else self.store.put_response(sid, text, code)
        return PolicyDecision(ref, s.booking_status, code, handoff)

    async def handle(self, sid: str, inp: DialogueInput, access: AccessContext,
                     *, is_current: CurrentCheck | None = None) -> PolicyDecision:
        if not isinstance(inp, DialogueInput) or not isinstance(access, AccessContext):
            raise TypeError('typed input/access required')
        s = self._session(sid)
        async with s.lock:
            if is_current is not None and not await is_current():
                return PolicyDecision(None, s.booking_status, 'stale_generation')
            if inp.intent == Intent.HANDOFF:
                s.change(BookingStatus.HANDOFF)
                s.pending_slot = None
                return self._respond(sid, s, 'handoff', '', handoff=True)
            if inp.intent == Intent.GREETING:
                return self._respond(sid, s, 'greeting', 'Merhaba, araç bilgisi ve ekspertiz randevusu konusunda yardımcı olabilirim.')
            if inp.intent == Intent.UNKNOWN:
                s.unknown_count += 1
                if s.unknown_count >= 2:
                    s.change(BookingStatus.HANDOFF)
                    return self._respond(sid, s, 'fallback_handoff', '', handoff=True)
                return self._respond(sid, s, 'clarify', 'İsteğinizi anlayamadım. Araç bilgisi, fiyat veya ekspertiz randevusu mu istiyorsunuz?')
            s.unknown_count = 0
            if inp.intent == Intent.DECLINE:
                if s.booking_status == BookingStatus.AWAITING_CONFIRMATION:
                    s.change(BookingStatus.DECLINED)
                    s.pending_slot = None
                    s.idempotency_key = None
                    return self._respond(sid, s, 'declined', 'Randevu talebini oluşturmadım.')
                return self._respond(sid, s, 'no_offer', 'Onay bekleyen bir randevunuz bulunmuyor.')
            # Never retrieve private CRM information or create appointments before access authorization.
            if not access.authenticated:
                return self._respond(sid, s, 'identity_required', 'İşleme devam etmek için kimlik doğrulaması gerekiyor.')
            if not access.crm_processing_allowed:
                return self._respond(sid, s, 'data_permission_required', 'Araç bilgilerinizle işlem yapabilmem için uygun veri işleme yetkisi gerekiyor. Dilerseniz temsilciye aktarabilirim.')
            if inp.intent == Intent.RECHECK_BOOKING:
                if not s.idempotency_key:
                    return self._respond(sid, s, 'nothing_to_recheck', 'Sorgulanabilecek bir randevu işlemi yok.')
                try:
                    outcome = await self.booking.lookup(s.idempotency_key)
                except Exception:
                    outcome = None
                if outcome is not None and outcome.status == Commitment.CONFIRMED and outcome.reference_id:
                    s.change(BookingStatus.CONFIRMED)
                    s.confirmed_reference = outcome.reference_id
                    return self._respond(sid, s, 'booking_reconciled', f'Randevu doğrulandı. Referans: {outcome.reference_id}.')
                s.change(BookingStatus.UNKNOWN)
                return self._respond(sid, s, 'recheck_unknown', 'Randevunun sonucu doğrulanamadı. Yeni bir kayıt denemesi yapmadan temsilciye başvurabilirsiniz.')
            if inp.intent == Intent.CREATE_CRM_CASE:
                if not inp.vehicle_id or inp.case_kind is None:
                    return self._respond(sid, s, 'crm_case_details_missing', 'Talep kaydı için araç ve konu bilgisi gerekiyor.')
                vehicle = await self._get_vehicle(inp.vehicle_id)
                if vehicle is None or not vehicle.verified:
                    return self._respond(sid, s, 'vehicle_unverified', 'Araç doğrulanmadığı için CRM talebi açamıyorum.')
                if is_current is not None and not await is_current():
                    return PolicyDecision(None, s.booking_status, 'stale_generation')
                key = sha256(f'crm-case|{sid}|{inp.vehicle_id}|{inp.case_kind.value}'.encode()).hexdigest()
                try:
                    receipt = await self.crm.create_case(inp.vehicle_id, inp.case_kind, key)
                except Exception:
                    return self._respond(sid, s, 'crm_case_unknown', 'CRM talebinizin kaydedildiği doğrulanamadı.')
                if receipt.accepted and receipt.reference_id:
                    s.case_requests[key] = receipt.reference_id
                    return self._respond(sid, s, 'crm_case_created', f'Talebiniz CRM sisteminde kaydedildi. Takip referansı: {receipt.reference_id}.')
                return self._respond(sid, s, 'crm_case_unavailable', 'CRM talebiniz kaydedilemedi.')
            if inp.intent == Intent.VEHICLE_LOOKUP:
                if inp.vehicle_id is None:
                    return self._respond(sid, s, 'need_vehicle', 'Hangi araç için işlem yapmak istiyorsunuz?')
                v = await self._get_vehicle(inp.vehicle_id)
                if v is None or not v.verified:
                    return self._respond(sid, s, 'vehicle_unverified', 'Araç bilgisi doğrulanamadı. Temsilciye aktarabilirim.')
                return self._respond(sid, s, 'vehicle_verified', f'Doğrulanmış araç kaydı: {v.year} {v.brand} {v.model}.')
            if inp.intent == Intent.PRICE_LOOKUP:
                if not inp.vehicle_id:
                    return self._respond(sid, s, 'need_vehicle', 'Fiyat sorgulamak için araç bilgisi gerekiyor.')
                v = await self._get_vehicle(inp.vehicle_id)
                if v is None or not v.verified:
                    return self._respond(sid, s, 'vehicle_unverified', 'Bu aracın doğrulanmış kaydı yok; fiyat bildiremiyorum.')
                try:
                    quote = await self.crm.get_price_quote(inp.vehicle_id)
                except Exception:
                    quote = None
                current = self.now()
                if (quote is None or quote.vehicle_id != inp.vehicle_id or not quote.verified
                        or quote.valid_until <= current or not quote.source_ref):
                    return self._respond(sid, s, 'price_unavailable', 'Bu araç için güncel ve doğrulanmış fiyat bilgisi bulunmuyor.')
                return self._respond(sid, s, 'price_verified',
                    f'Sistemde doğrulanmış tahmini araç değeri {quote.amount_try:,} Türk lirasıdır.'.replace(',', '.') + ' Bu tutar kesin satış teklifi değildir.')
            if inp.intent == Intent.REQUEST_INSPECTION:
                if not inp.vehicle_id or inp.slot is None:
                    return self._respond(sid, s, 'need_slot', 'Ekspertiz için araç, tarih, saat ve lokasyon bilgisi gerekiyor.')
                v = await self._get_vehicle(inp.vehicle_id)
                if v is None or not v.verified:
                    return self._respond(sid, s, 'vehicle_unverified', 'Araç doğrulanmadan ekspertiz randevusu açamam.')
                if inp.slot.start_at and datetime.fromisoformat(inp.slot.start_at) <= self.now():
                    return self._respond(sid, s, 'slot_past', 'Geçmiş tarihli randevu oluşturamam. Yeni bir zaman belirtin.')
                if s.booking_status == BookingStatus.CONFIRMED:
                    if s.vehicle_id == inp.vehicle_id and s.pending_slot == inp.slot:
                        return self._respond(sid, s, 'already_confirmed', f'Bu randevu daha önce doğrulandı. Referans: {s.confirmed_reference}.')
                    return self._respond(sid, s, 'booking_exists', 'Zaten kesinleşmiş bir randevunuz var. Değişiklik için temsilciye aktarabilirim.')
                if s.booking_status == BookingStatus.UNKNOWN and s.idempotency_key:
                    return self._respond(sid, s, 'reconcile_first', 'Önceki randevu denemesinin sonucu belirsiz. Önce kayıt durumunu doğrulamamız gerekiyor.')
                try:
                    state = await self.booking.check_availability(inp.vehicle_id, inp.slot)
                except Exception:
                    state = Availability.UNKNOWN
                if is_current is not None and not await is_current():
                    return PolicyDecision(None, s.booking_status, 'stale_generation')
                s.vehicle_id, s.pending_slot, s.confirmed_reference = inp.vehicle_id, inp.slot, None
                s.idempotency_key = None  # replace an uncommitted offer, not an uncertain commit
                if state == Availability.UNAVAILABLE:
                    s.change(BookingStatus.UNAVAILABLE)
                    return self._respond(sid, s, 'slot_unavailable', 'İstenen tarih ve saatte ekspertiz müsait değil. Başka zaman seçebilirsiniz.')
                if state == Availability.UNKNOWN:
                    s.change(BookingStatus.UNKNOWN)
                    return self._respond(sid, s, 'slot_unknown', 'Randevu uygunluğu henüz doğrulanamadı. Randevu oluşturulmadı.')
                if state != Availability.AVAILABLE:
                    raise ValueError('unexpected availability state')
                s.change(BookingStatus.AWAITING_CONFIRMATION)
                s.offer_serial += 1
                s.idempotency_key = sha256(f'{sid}|{s.offer_serial}|{inp.vehicle_id}|{inp.slot.start_at}|{inp.slot.location_id}'.encode()).hexdigest()
                return self._respond(sid, s, 'offer_confirmation',
                    f'{inp.slot.start_at} tarihinde, {inp.slot.location_id} lokasyonunda ekspertiz için müsaitlik var. Randevu talebini onaylıyor musunuz? Henüz oluşturulmadı.')
            if inp.intent == Intent.CONFIRM:
                if s.booking_status == BookingStatus.CONFIRMED and s.confirmed_reference:
                    return self._respond(sid, s, 'already_confirmed', f'Randevunuz zaten onaylı. Referans: {s.confirmed_reference}.')
                if s.booking_status != BookingStatus.AWAITING_CONFIRMATION or not s.idempotency_key or not s.pending_slot or not s.vehicle_id:
                    return self._respond(sid, s, 'no_offer', 'Onay bekleyen doğrulanmış bir randevu talebi bulunmuyor.')
                if datetime.fromisoformat(s.pending_slot.start_at) <= self.now():
                    s.change(BookingStatus.UNAVAILABLE)
                    s.idempotency_key = None
                    return self._respond(sid, s, 'slot_expired', 'Seçilen saat artık geçmiş durumda. Yeni bir randevu saati belirtin.')
                if is_current is not None and not await is_current():
                    return PolicyDecision(None, s.booking_status, 'stale_generation')
                s.change(BookingStatus.CONFIRMING)
                try:
                    result = await self.booking.commit(s.vehicle_id, s.pending_slot, s.idempotency_key)
                except Exception:
                    s.change(BookingStatus.UNKNOWN)
                    return self._respond(sid, s, 'booking_service_error', 'Randevu kaydı doğrulanamadı. Oluşturulduğunu söyleyemem.')
                if result.status == Commitment.CONFIRMED and result.reference_id:
                    s.change(BookingStatus.CONFIRMED)
                    s.confirmed_reference = result.reference_id
                    return self._respond(sid, s, 'booking_confirmed', f'Ekspertiz randevunuz oluşturuldu. Onay referansı: {result.reference_id}.')
                s.change(BookingStatus.UNAVAILABLE if result.status == Commitment.UNAVAILABLE else BookingStatus.UNKNOWN)
                code = 'booking_unavailable' if result.status == Commitment.UNAVAILABLE else 'booking_unknown'
                return self._respond(sid, s, code, 'Randevu kaydı onaylanmadı. Kesinleşmiş randevunuz bulunmuyor.')
            return self._respond(sid, s, 'unsupported', 'Bu işlem şu anda desteklenmiyor. Temsilciye aktarabilirim.')
~~~~

### automotive_voice/dialogue/ports.py

~~~~python
"""Business-authoritative replaceable ports, with deterministic no-network fakes."""
from __future__ import annotations
from typing import Protocol
from uuid import uuid5, NAMESPACE_URL
from .models import VehicleRecord, PriceQuote, AppointmentSlot, Availability, BookingReceipt, Commitment, CaseKind, CaseReceipt

class CRMPort(Protocol):
    async def get_vehicle(self, vehicle_id: str) -> VehicleRecord | None: ...
    async def get_price_quote(self, vehicle_id: str) -> PriceQuote | None: ...
    async def create_case(self, vehicle_id: str, kind: CaseKind, idempotency_key: str) -> CaseReceipt: ...

class InspectionBookingPort(Protocol):
    async def check_availability(self, vehicle_id: str, slot: AppointmentSlot) -> Availability: ...
    async def commit(self, vehicle_id: str, slot: AppointmentSlot, idempotency_key: str) -> BookingReceipt: ...
    async def lookup(self, idempotency_key: str) -> BookingReceipt: ...

class FakeCRM:
    def __init__(self, vehicles: dict[str, VehicleRecord] | None = None, quotes: dict[str, PriceQuote] | None = None):
        self.vehicles = vehicles or {}
        self.quotes = quotes or {}
        self.vehicle_reads = 0
        self.price_reads = 0
        self.cases: dict[str, CaseReceipt] = {}
        self.case_creations = 0

    async def get_vehicle(self, vehicle_id: str) -> VehicleRecord | None:
        self.vehicle_reads += 1
        return self.vehicles.get(vehicle_id)

    async def get_price_quote(self, vehicle_id: str) -> PriceQuote | None:
        self.price_reads += 1
        return self.quotes.get(vehicle_id)

    async def create_case(self, vehicle_id: str, kind: CaseKind, idempotency_key: str) -> CaseReceipt:
        if idempotency_key in self.cases:
            return self.cases[idempotency_key]
        if vehicle_id not in self.vehicles or not self.vehicles[vehicle_id].verified:
            return CaseReceipt(False, None)
        ref = "CASE-" + uuid5(NAMESPACE_URL, idempotency_key).hex[:12].upper()
        receipt = CaseReceipt(True, ref)
        self.cases[idempotency_key] = receipt
        self.case_creations += 1
        return receipt

class FakeBookingService:
    def __init__(self, availability: dict[tuple[str, str, str], Availability] | None = None):
        self.availability = availability or {}
        self.receipts: dict[str, BookingReceipt] = {}
        self.request_fingerprints: dict[str, tuple[str, str, str]] = {}
        self.commit_calls = 0
        self.creations = 0

    @staticmethod
    def key(vehicle_id: str, slot: AppointmentSlot) -> tuple[str, str, str]:
        return vehicle_id, slot.start_at, slot.location_id

    async def check_availability(self, vehicle_id: str, slot: AppointmentSlot) -> Availability:
        return self.availability.get(self.key(vehicle_id, slot), Availability.UNKNOWN)

    async def commit(self, vehicle_id: str, slot: AppointmentSlot, idempotency_key: str) -> BookingReceipt:
        self.commit_calls += 1
        fingerprint = self.key(vehicle_id, slot)
        if idempotency_key in self.request_fingerprints and self.request_fingerprints[idempotency_key] != fingerprint:
            raise ValueError('idempotency key reused for another booking')
        if idempotency_key in self.receipts:
            return self.receipts[idempotency_key]
        status = await self.check_availability(vehicle_id, slot)
        if status == Availability.AVAILABLE:
            ref = 'EX-' + uuid5(NAMESPACE_URL, idempotency_key).hex[:12].upper()
            outcome = BookingReceipt(Commitment.CONFIRMED, ref)
            self.creations += 1
        elif status == Availability.UNAVAILABLE:
            outcome = BookingReceipt(Commitment.UNAVAILABLE)
        else:
            outcome = BookingReceipt(Commitment.UNKNOWN)
        # This is a deterministic test double; a real service must guarantee
        # the idempotency key transactionally on its own server side.
        self.receipts[idempotency_key] = outcome
        self.request_fingerprints[idempotency_key] = fingerprint
        return outcome

    async def lookup(self, idempotency_key: str) -> BookingReceipt:
        return self.receipts.get(idempotency_key, BookingReceipt(Commitment.UNKNOWN))
~~~~

### automotive_voice/dialogue/storage.py

~~~~python
"""Bounded ephemeral mock secure store. Not encryption, persistence or production KMS."""
from __future__ import annotations
import threading
from collections import OrderedDict
from dataclasses import dataclass
from uuid import uuid4
from .models import DialogueInput

@dataclass(frozen=True, repr=False)
class StoredTranscript:
    text: str
    parsed: DialogueInput

@dataclass(frozen=True, repr=False)
class StoredResponse:
    text: str
    category: str

class MissingReferenceError(LookupError):
    pass

class ReferenceStore:
    def __init__(self, *, capacity: int = 2048):
        if type(capacity) is not int or capacity < 1:
            raise ValueError('capacity must be positive')
        self._cap = capacity
        self._lock = threading.RLock()
        self._values: OrderedDict[tuple[str, str], object] = OrderedDict()

    def _put(self, sid: str, prefix: str, value: object) -> str:
        reference = f'{prefix}:{uuid4().hex}'
        with self._lock:
            self._values[(sid, reference)] = value
            while len(self._values) > self._cap:
                self._values.popitem(last=False)
        return reference

    def put_input(self, session_id: str, value: DialogueInput) -> str:
        if not isinstance(value, DialogueInput):
            raise TypeError('DialogueInput required')
        return self._put(session_id, 'transcript', value)

    def put_transcript(self, session_id: str, raw_text: str, parsed: DialogueInput) -> str:
        if not isinstance(raw_text, str) or not 1 <= len(raw_text) <= 4096:
            raise ValueError('raw transcript length 1..4096 required')
        if not isinstance(parsed, DialogueInput):
            raise TypeError('parsed DialogueInput required')
        return self._put(session_id, 'transcript', StoredTranscript(raw_text, parsed))

    def get_transcript(self, session_id: str, ref: str) -> str:
        with self._lock:
            v = self._values.get((session_id, ref))
        if not isinstance(v, StoredTranscript):
            raise MissingReferenceError('raw transcript missing for session')
        return v.text

    def get_input(self, session_id: str, ref: str) -> DialogueInput:
        with self._lock:
            v = self._values.get((session_id, ref))
        if isinstance(v, StoredTranscript):
            return v.parsed
        if not isinstance(v, DialogueInput):
            raise MissingReferenceError('input reference missing for this session')
        return v

    def put_response(self, session_id: str, text: str, category: str) -> str:
        if not text or not category:
            raise ValueError('response requires text and category')
        return self._put(session_id, 'response', StoredResponse(text, category))

    def get_response(self, session_id: str, ref: str) -> StoredResponse:
        with self._lock:
            v = self._values.get((session_id, ref))
        if not isinstance(v, StoredResponse):
            raise MissingReferenceError('response reference missing for this session')
        return v

    def erase_session(self, sid: str) -> None:
        with self._lock:
            for k in tuple(self._values):
                if k[0] == sid:
                    del self._values[k]
~~~~

### automotive_voice/domain/booking.py

~~~~python
"""The LLM is never authoritative about confirmed bookings."""
from dataclasses import dataclass

@dataclass(frozen=True)
class BookingOutcome:
    status: str
    reference_id: str | None


def can_announce_booking(outcome: BookingOutcome, user_confirmed: bool) -> bool:
    return bool(user_confirmed and outcome.status == "confirmed" and outcome.reference_id)
~~~~

### automotive_voice/e2e/__init__.py

~~~~python
"""M09 deterministic, metadata-only cross-module acceptance harness."""
from .runner import ScenarioRunner, SCENARIOS
__all__ = ('ScenarioRunner','SCENARIOS')
~~~~

### automotive_voice/e2e/runner.py

~~~~python
"""M09 integration of the ACTUAL M01–M08 contracts. No WAV, sockets, models, SIP or wall delays.

Each run constructs one M01 authority with M02–M07 adapters. Transcripts are
in memory in the test fixture and never copied into a trace or telemetry.
Completion of M03 business policy is distinct from readiness of a TTS clause.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from automotive_voice.core.event_bus import EventBus
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.resilience.durable import DurableJournal, DurableSessionManager
from automotive_voice.core.session import State
from automotive_voice.conversation.reducer import ConversationReducer, Decision
from automotive_voice.conversation.signals import ConversationSignal, SignalKind
from automotive_voice.conversation.effects import EffectKind
from automotive_voice.dialogue import (ReferenceStore, DialoguePolicy, DialogueCoordinator, FakeCRM,
    FakeBookingService, VehicleRecord, PriceQuote, AccessContext, Availability, AppointmentSlot)
from automotive_voice.dialogue.models import BookingReceipt, Commitment
from automotive_voice.nlp.nlu import DeterministicNLU, ParseContext
from automotive_voice.nlp.bridge import NLUReferenceBridge
from automotive_voice.nlp.normalizer import TurkishAutomotiveNormalizer
from automotive_voice.prosody import ProsodyClausePlanner, MockTTS, ProsodyCoordinator
from automotive_voice.readiness.presentation import PolicySpeechPresenter
from automotive_voice.audio.queue import MediaBuffer
from automotive_voice.audio.coordinator import MediaCoordinator
from automotive_voice.telephony.transport import FakeTransport
from automotive_voice.adapters.lifecycle.clock import MockClock
from automotive_voice.adapters.lifecycle.supervisor import AdapterSupervisor
from automotive_voice.adapters.lifecycle.streaming import SyntheticStreamBridge
from automotive_voice.adapters.lifecycle.contracts import AdapterKind, ResultCode

FIXED_NOW = datetime(2026, 10, 31, 18, 0, tzinfo=timezone.utc)
TR_TZ = timezone(timedelta(hours=3))
SLOT = AppointmentSlot('2026-11-03T14:30:00+03:00', 'TRABZON')
ACCESS = AccessContext(authenticated=True, crm_processing_allowed=True)
NO_ACCESS = AccessContext(authenticated=False, crm_processing_allowed=False)

SCENARIOS = (
    'price_verified', 'price_expired', 'booking_confirmed', 'booking_declined',
    'booking_unknown', 'duplicate_confirmation', 'crm_case', 'handoff',
    'barge_in_ack', 'barge_in_timeout', 'xoff_backpressure', 'late_generation',
    'adapter_disconnect', 'llm_retry', 'booking_commit_unknown', 'wrong_fake_ack',
    'hangup_cancels', 'multi_session', 'unauthorized', 'ambiguous_time',
)

@dataclass(frozen=True)
class ScenarioResult:
    name: str
    passed: bool
    checks: dict[str,bool]
    sessions: tuple[dict[str,Any],...]
    trace: tuple[dict[str,Any],...]
    notes: tuple[str,...]
    def to_dict(self)->dict:
        return {'scenario':self.name,'passed':self.passed,'checks':dict(self.checks),
                'sessions':list(self.sessions),'trace':list(self.trace),'notes':list(self.notes),
                'audio_bytes_generated':0,'real_pbx_connected':False,'real_crm_connected':False,
                'real_model_called':False,'production_ready':False}

class ScenarioRunner:
    """Fresh deterministic world for each run; no external dependencies.

    Methods are serial in a run. Multi-session runs share ONE manager/reducer,
    but retain independent booking sessions and generation counters.
    """
    def __init__(self, *, m10_presentation: bool = False, durable_journal: DurableJournal | None = None):
        self.clock=MockClock()
        self.manager=(DurableSessionManager(EventBus(),durable_journal) if durable_journal is not None
                      else SessionManager(EventBus()))
        self.reducer=ConversationReducer(self.manager,flush_timeout_ms=1500)
        self.store=ReferenceStore()
        self.crm=FakeCRM({'veh1':VehicleRecord('veh1','Nissan','Qashqai',2024)},
                {'veh1':PriceQuote('veh1',1250000,'fixture-price',FIXED_NOW+timedelta(days=20))})
        self.booking=FakeBookingService({FakeBookingService.key('veh1',SLOT):Availability.AVAILABLE})
        self.policy=DialoguePolicy(self.crm,self.booking,self.store,now=lambda:FIXED_NOW)
        self.dialogue=DialogueCoordinator(self.reducer,self.policy,self.store,clock_ns=self.clock.now_ns)
        self.nlu=NLUReferenceBridge(DeterministicNLU(),self.store)
        self.normalizer=TurkishAutomotiveNormalizer()
        self.mock_tts=MockTTS(self.manager)
        self.prosody=ProsodyCoordinator(self.store,self.normalizer,ProsodyClausePlanner(),self.mock_tts,
            presentation=PolicySpeechPresenter() if m10_presentation else None)
        self.buffer=MediaBuffer(self.manager)
        self.transport=FakeTransport(adapter_id='m09-fake-only')
        self.media=MediaCoordinator(self.reducer,self.buffer,self.transport)
        self.supervisor=AdapterSupervisor(self.manager,self.clock,media=self.media)
        self.stream=SyntheticStreamBridge(self.manager,self.clock,
            self.supervisor.adapters[AdapterKind.TTS],self.mock_tts,self.buffer)
        self.trace:list[dict[str,Any]]=[]
        self.notes:list[str]=[]
        self._opened=False
    def log(self,sid:str,step:str,outcome:str,**meta):
        # Whitelist only booleans, counters, state names, and diagnostic codes.
        self.trace.append({'ms':self.clock.now_ns()//1_000_000,'session':sid,
                'step':step,'outcome':outcome,**meta})
    def context(self,sid:str)->ParseContext:
        return ParseContext(vehicle_aliases={'qashqai':'veh1','nissan':'veh1'},
                location_aliases={'trabzon':'TRABZON'},
                as_of=FIXED_NOW.astimezone(TR_TZ),
                awaiting_confirmation=self.policy.snapshot(sid)['booking_status']=='awaiting_confirmation')
    async def init(self):
        if isinstance(self.manager, DurableSessionManager) and not self.manager._restored:
            await self.manager.restore_fail_closed()
        if not self._opened:
            await self.supervisor.start_all();self._opened=True
    async def emit(self,sid:str,kind:SignalKind,ref:str|None=None,*,flush_id:str|None=None):
        snap=await self.reducer.try_snapshot(sid)
        self.clock.advance(1_000_000)
        event=ConversationSignal.create(kind,sid,int(snap.turn_id) if snap else 0,
               int(snap.generation_id) if snap else 0,await self.reducer.expected_sequence(sid),
               reference=ref,flush_request_id=flush_id,mono_ns=self.clock.now_ns())
        out=await self.reducer.handle(event)
        self.log(sid,kind.value,out.decision.value,state=out.state.value if out.state else None)
        return out
    async def open(self,sid:str):
        await self.init()
        out=await self.emit(sid,SignalKind.SESSION_OPENED)
        assert out.decision is Decision.APPLIED
    async def _finish_adapter(self,kind:AdapterKind)->tuple:
        # No real time advances. Start job then advance virtual time and complete.
        await self.supervisor.tick_all()
        self.clock.advance(25_000_000)
        result=await self.supervisor.tick_all()
        return result[kind]
    async def user(self,sid:str,transcript:str,*,access:AccessContext=ACCESS,
                   auto_playout:bool=True,stream:bool=True)->dict:
        """Process a synthetic STT event through M04 -> M02 -> M07 -> M03 -> M05 -> M06.

        When a policy response is review-blocked, no audio is sent; optional
        playout is a *control-plane fixture transition*, explicitly recorded.
        """
        incoming=self.nlu.resolve(sid,transcript,self.context(sid))
        in_effect=await self.emit(sid,SignalKind.TRANSCRIPT_FINAL,incoming.ref)
        if in_effect.decision is not Decision.APPLIED:
            return {'status':'signal_rejected','reason':in_effect.reason}
        request=next(e for e in in_effect.effects if e.kind is EffectKind.REQUEST_LLM)
        rec=await self.supervisor.dispatch_effect(request)
        if not rec.accepted:return {'status':'adapter_rejected','reason':rec.reason}
        llm_results=await self._finish_adapter(AdapterKind.LLM)
        if not any(r.command_id==request.effect_id and r.code is ResultCode.OK for r in llm_results):
            return {'status':'adapter_not_complete'}
        result=await self.dialogue.process(request,access)
        self.log(sid,'policy',result.action,has_response=bool(result.response_ref),
             requires_clarification=incoming.parse.requires_clarification)
        tts_state='not_requested';sent=0
        if result.status=='applied' and result.response_ref:
            pending=await self.reducer.pending_effects(sid)
            start=next(e for e in pending if e.kind is EffectKind.START_TTS)
            planning=await self.prosody.process(start)
            tts_state=planning.status
            self.log(sid,'prosody',tts_state,clauses=planning.queued_clauses,
                     warning_codes=list(planning.warning_codes))
            if planning.status=='queued' and stream:
                sent=await self.pump(sid)
        await self.reducer.drain_effects(sid)
        if auto_playout and result.response_ref:
            # If text requires review, this advances the mock *state machine* only.
            # It does not pretend that a customer heard an actual prompt.
            played=await self.emit(sid,SignalKind.PLAYOUT_FINISHED)
            if played.decision is not Decision.APPLIED:
                raise AssertionError('invalid_playout:'+played.reason)
            if tts_state=='review_required':
                self.log(sid,'control_only_playout','no_audio_verified')
        return {'status':result.status,'action':result.action,
                'tts':tts_state,'sent_metadata':sent,'intent':incoming.parse.dialogue_input.intent.value,
                'requires_clarification':incoming.parse.requires_clarification}
    async def pump(self,sid:str,*,max_clauses:int=80)->int:
        delivered=0
        for _ in range(max_clauses):
            submission=await self.stream.submit_next_clause()
            if not submission.accepted:
                if submission.reason!='no_active_clause':self.log(sid,'stream_rejected',submission.reason)
                break
            outcomes=await self._finish_adapter(AdapterKind.TTS)
            for outcome in outcomes:
                if outcome.command_id!=submission.command_id:continue
                receipt=await self.stream.materialize_metadata(outcome)
                self.log(sid,'fake_tts',receipt.reason)
                if receipt.accepted:
                    send=await self.media.send_next(sid)
                    self.log(sid,'fake_transport',send.reason)
                    delivered+=int(send.accepted)
        return delivered
    async def interrupt(self,sid:str):
        out=await self.emit(sid,SignalKind.VAD_SPEECH_STARTED)
        if out.decision is not Decision.APPLIED:return out
        for effect in out.effects:
            r=await self.supervisor.dispatch_effect(effect)
            assert r.accepted, r.reason
        await self.reducer.drain_effects(sid)
        self.stream.abandon_generation(sid)
        await self.mock_tts.discard_stale()
        return out
    async def fake_ack(self,sid:str):
        pending=await self.reducer.pending_flush_id(sid)
        if not pending:raise ValueError('no_pending_flush')
        ack=await self.transport.confirm_flush(sid,pending)
        if ack is None:raise ValueError('not_confirmed_by_fake_transport')
        self.clock.advance(1_000_000)
        result=await self.media.accept_fake_ack(ack,sequence=await self.reducer.expected_sequence(sid),mono_ns=self.clock.now_ns())
        self.log(sid,'FAKE_ACK',result.decision.value,real_pbx_proven=False)
        return result
    async def expire_flush(self,sid:str):
        self.clock.advance(1_600_000_000)
        outcomes=await self.reducer.poll_flush_timeouts(self.clock.now_ns())
        for session,out in outcomes.items():
            for effect in out.effects:
                await self.supervisor.dispatch_effect(effect)
            self.log(session,'flush_timeout',out.decision.value,state=out.state.value)
        return outcomes.get(sid)
    async def hangup(self,sid:str):
        out=await self.emit(sid,SignalKind.HANGUP)
        for eff in out.effects:await self.supervisor.dispatch_effect(eff)
        await self.reducer.drain_effects(sid)
        return out
    async def session_summary(self,sid:str)->dict:
        snap=await self.reducer.try_snapshot(sid)
        audits=await self.reducer.audit_records(sid)
        return {'id':sid,'state':snap.state.value,'turn':int(snap.turn_id),
                'generation':int(snap.generation_id),'audit_events':len(audits),
                'booking_status':self.policy.snapshot(sid)['booking_status'],
                'pending_flush':bool(await self.reducer.pending_flush_id(sid)),
                'fake_transport_sent':self.transport.stats(sid).sent,
                'transport_paused':self.transport.stats(sid).paused}
    async def run(self,name:str)->ScenarioResult:
        if name not in SCENARIOS:raise ValueError('unknown_scenario')
        checks:dict[str,bool]={}
        self.notes=[]
        sid='m09-'+name.replace('_','-')
        await self.open(sid)
        try:
            if name in ('price_verified','price_expired','unauthorized'):
                if name=='price_expired':
                    self.crm.quotes['veh1']=PriceQuote('veh1',1250000,'stale-quote',FIXED_NOW-timedelta(days=1))
                outcome=await self.user(sid,'Nissan Qashqai aracımın fiyatı nedir?',
                         access=NO_ACCESS if name=='unauthorized' else ACCESS)
                checks['right_policy']=outcome['action']==('identity_required' if name=='unauthorized' else 'price_unavailable' if name=='price_expired' else 'price_verified')
                checks['no_booking']=self.booking.creations==0
            elif name in ('booking_confirmed','booking_declined','duplicate_confirmation','booking_unknown'):
                if name=='booking_unknown':
                    self.booking.availability.clear()
                first=await self.user(sid,'Qashqai için Trabzon 03.11.2026 saat 14:30 ekspertiz randevusu istiyorum.')
                checks['offer_gate']=first['action']==('slot_unknown' if name=='booking_unknown' else 'offer_confirmation')
                checks['no_early_booking']=self.booking.creations==0
                if name=='booking_unknown':
                    checks['unknown_not_confirmed']=self.policy.snapshot(sid)['booking_status']=='unknown'
                else:
                    next_text='hayır' if name=='booking_declined' else 'evet'
                    last=await self.user(sid,next_text)
                    checks['confirmation_step']=last['action']==('declined' if name=='booking_declined' else 'booking_confirmed')
                    if name=='duplicate_confirmation':
                        replay=await self.user(sid,'evet')
                        checks['repeat_not_second_booking']=self.booking.creations==1 and replay['action']!='booking_confirmed'
                    checks['booking_count']=self.booking.creations==(0 if name=='booking_declined' else 1)
            elif name=='crm_case':
                r=await self.user(sid,'Nissan Qashqai için geri ara talep kaydı oluştur')
                checks['crm_created']=r['action']=='crm_case_created' and self.crm.case_creations==1
            elif name=='handoff':
                r=await self.user(sid,'Beni bir temsilciye aktar')
                checks['handoff_policy']=r['action']=='handoff'
                checks['handoff_terminal']=(await self.reducer.try_snapshot(sid)).state is State.HANDOFF
            elif name=='barge_in_ack':
                await self.user(sid,'merhaba',auto_playout=False)
                out=await self.interrupt(sid)
                checks['barge_in_applied']=out.decision is Decision.APPLIED
                checks['ack_barrier']=(await self.reducer.try_snapshot(sid)).state is State.INTERRUPTING
                ack=await self.fake_ack(sid)
                checks['fake_ack_only']=ack.decision is Decision.APPLIED and (await self.reducer.try_snapshot(sid)).state is State.LISTENING
            elif name=='barge_in_timeout':
                await self.user(sid,'merhaba',auto_playout=False)
                await self.interrupt(sid)
                out=await self.expire_flush(sid)
                checks['watchdog_fails_closed']=bool(out and out.state is State.FAILED)
            elif name=='xoff_backpressure':
                await self.user(sid,'merhaba',auto_playout=False,stream=False)
                self.transport.xoff(sid)
                sent=await self.pump(sid)
                checks['no_send_under_xoff']=sent==0 and self.transport.stats(sid).paused
                self.transport.xon(sid)
                sent2=await self.media.send_next(sid)
                checks['resume_without_loss']=sent2.accepted
                await self.emit(sid,SignalKind.PLAYOUT_FINISHED)
            elif name=='late_generation':
                await self.user(sid,'merhaba',auto_playout=False,stream=False)
                r=await self.stream.submit_next_clause()
                await self.supervisor.tick_all()
                await self.interrupt(sid)
                self.clock.advance(25_000_000)
                late=await self.supervisor.tick_all()
                has_ok=any(x.code is ResultCode.OK and x.command_id==r.command_id for x in late[AdapterKind.TTS])
                checks['old_generation_not_delivered']=not has_ok
                checks['stale_chunk_rejected']=not await self.manager.accepts_chunk(sid,1)
            elif name=='llm_retry':
                incoming=self.nlu.resolve(sid,'merhaba',self.context(sid))
                out=await self.emit(sid,SignalKind.TRANSCRIPT_FINAL,incoming.ref)
                eff=next(x for x in out.effects if x.kind is EffectKind.REQUEST_LLM)
                llm=self.supervisor.adapters[AdapterKind.LLM]
                llm.inject_faults(eff.effect_id,['transient','ok'])
                receipt=await self.supervisor.dispatch_effect(eff)
                await self.supervisor.tick_all()
                self.clock.advance(25_000_000)
                await self.supervisor.tick_all()
                self.clock.advance(100_000_000)
                await self.supervisor.tick_all()
                self.clock.advance(25_000_000)
                res=await self.supervisor.tick_all()
                results=[x for x in res[AdapterKind.LLM] if x.command_id==eff.effect_id]
                checks['retry_one_recover']=receipt.accepted and len(results)==1 and results[0].code is ResultCode.OK and results[0].attempts==2
                policy=await self.dialogue.process(eff,ACCESS)
                checks['business_after_retry']=policy.status=='applied' and policy.action=='greeting'
                self.log(sid,'LLM retry','completed',attempts=results[0].attempts if results else 0)
            elif name=='booking_commit_unknown':
                first=await self.user(sid,'Qashqai için Trabzon 03.11.2026 saat 14:30 ekspertiz istiyorum')
                async def uncertain(vehicle_id,slot,idempotency_key):
                    self.booking.commit_calls+=1
                    return BookingReceipt(Commitment.UNKNOWN)
                self.booking.commit=uncertain
                second=await self.user(sid,'evet')
                third=await self.user(sid,'randevu durumu')
                checks['offer_and_unknown']=first['action']=='offer_confirmation' and second['action']=='booking_unknown'
                checks['recheck_no_duplicate']=third['action']=='recheck_unknown' and self.booking.commit_calls==1 and self.booking.creations==0
            elif name=='wrong_fake_ack':
                await self.user(sid,'merhaba',auto_playout=False)
                await self.interrupt(sid)
                wrong=await self.transport.confirm_flush(sid,'00000000-0000-0000-0000-000000000001')
                checks['wrong_ack_rejected']=wrong is None and (await self.reducer.try_snapshot(sid)).state is State.INTERRUPTING
                valid=await self.fake_ack(sid)
                checks['explicit_fake_ack_only']=valid.decision is Decision.APPLIED
            elif name=='hangup_cancels':
                await self.user(sid,'merhaba',auto_playout=False,stream=False)
                submitted=await self.stream.submit_next_clause()
                await self.supervisor.tick_all()
                await self.hangup(sid)
                self.clock.advance(25_000_000)
                res=await self.supervisor.tick_all()
                checks['hangup_terminal']=(await self.reducer.try_snapshot(sid)).state is State.ENDED
                checks['no_late_tts']=not any(x.command_id==submitted.command_id and x.code is ResultCode.OK for x in res[AdapterKind.TTS])
            elif name=='adapter_disconnect':
                adapter=self.supervisor.adapters[AdapterKind.TTS]
                await adapter.stop()
                checks['isolated_degradation']=self.supervisor.adapters[AdapterKind.LLM].state.value=='ready'
                await adapter.start()
                checks['recovered']=adapter.state.value=='ready'
            elif name=='multi_session':
                other='m09-secondary'
                await self.open(other)
                a=await self.user(sid,'Qashqai fiyatı nedir?')
                b=await self.user(other,'Qashqai için Trabzon 03.11.2026 saat 14:30 ekspertiz istiyorum')
                checks['separate_policy']=a['action']=='price_verified' and b['action']=='offer_confirmation'
                checks['independent_turns']=(await self.reducer.try_snapshot(sid)).turn_id==(await self.reducer.try_snapshot(other)).turn_id
                checks['no_cross_booking']=self.booking.creations==0
            elif name=='ambiguous_time':
                r=await self.user(sid,'Qashqai için Trabzon 03.11.2026 saat 14:30 veya 15:30 ekspertiz istiyorum')
                checks['ambiguity_flagged']=r['requires_clarification']
                checks['no_booking']=self.booking.creations==0
            else:raise AssertionError(name)
        except Exception as exc:
            # Type only: no raw transcript/PII in result.
            self.notes.append('harness_exception:'+type(exc).__name__)
            checks['no_exception']=False
        summaries=[]
        for session in (sid,'m09-secondary') if name=='multi_session' else (sid,):
            summaries.append(await self.session_summary(session))
        self.notes.append('All audio/media is metadata only; M08 read-model is a report projection.')
        self.notes.append('Volatile events do not survive process restarts; persistence HOLD.')
        return ScenarioResult(name,bool(checks) and all(checks.values()),checks,tuple(summaries),tuple(self.trace[-100:]),tuple(self.notes))

async def run_catalog()->dict:
    results=[]
    for name in SCENARIOS:
        results.append((await ScenarioRunner().run(name)).to_dict())
    return {'suite':'M09 deterministic synthetic E2E','scenario_count':len(results),
            'passed':sum(r['passed'] for r in results),'failed':sum(not r['passed'] for r in results),
            'results':results,'audio_bytes_generated':0,'real_pbx_connected':False,
            'production_ready':False}
~~~~

### automotive_voice/m01_demo.py

~~~~python
"""M01 structured event demo: no speech, model weights, or SIP traffic."""
import asyncio
import json
from automotive_voice.core.event_bus import EventBus
from automotive_voice.core.session_manager import SessionManager

async def run() -> None:
    bus = EventBus(default_capacity=32)
    observer = await bus.subscribe("local-demo")
    manager = SessionManager(bus)
    await manager.create("example-m01")
    await manager.start("example-m01")
    await manager.begin_turn("example-m01")
    await manager.begin_response("example-m01")
    old_generation_valid_before = await manager.accepts_chunk("example-m01", 1)
    await manager.interrupt("example-m01")
    old_generation_valid_after = await manager.accepts_chunk("example-m01", 1)
    await manager.complete_interrupt("example-m01")
    await manager.end("example-m01")
    count = await manager.dispatch_pending("example-m01")
    envelopes = [observer.get_nowait().to_dict() for _ in range(count)]
    print(json.dumps({"mode": "synthetic-only", "events_published": count,
                      "old_generation_accepted_before": old_generation_valid_before,
                      "old_generation_accepted_after": old_generation_valid_after,
                      "sequence": [e["sequence"] for e in envelopes],
                      "event_types": [e["event_type"] for e in envelopes],
                      "session": "example-m01", "final_state": "ENDED"}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    asyncio.run(run())
~~~~

### automotive_voice/m02_demo.py

~~~~python
"""Mock M02 demonstration. No microphone, video, Freya model, SIP or remote calls."""
import asyncio
from automotive_voice.conversation import ConversationReducer, ConversationSignal, SignalKind
from automotive_voice.core.session import State


async def main():
    reducer = ConversationReducer(flush_timeout_ms=1500)
    session_id = 'm02-local-demo'

    async def send(kind, ref=None, flush=None):
        snap = await reducer.try_snapshot(session_id)
        event = ConversationSignal.create(
            kind, session_id, int(snap.turn_id) if snap else 0,
            int(snap.generation_id) if snap else 0,
            await reducer.expected_sequence(session_id),
            reference=ref, flush_request_id=flush)
        out = await reducer.handle(event)
        print(f'{kind.value:22s} => {out.state.value if out.state else None:14s}'
              f' / {out.reason:24s} / effects={[e.kind.value for e in out.effects]}')
        return out

    await send(SignalKind.SESSION_OPENED)
    await send(SignalKind.VAD_SPEECH_STARTED)
    await send(SignalKind.TRANSCRIPT_FINAL,'transcript:001')
    await send(SignalKind.LLM_RESPONSE_READY,'response:001')
    await send(SignalKind.AUDIO_CHUNK_READY,'audio:001')
    interrupted = await send(SignalKind.VAD_SPEECH_STARTED)
    await send(SignalKind.TRANSCRIPT_FINAL,'transcript:002')
    await send(SignalKind.MEDIA_FLUSH_ACK,flush=interrupted.effects[-1].effect_id)
    await send(SignalKind.LLM_RESPONSE_READY,'response:002')
    await send(SignalKind.PLAYOUT_FINISHED)
    await send(SignalKind.HANGUP)
    final = await reducer.manager.snapshot(session_id)
    assert final.state == State.ENDED
    events = await reducer.manager.dispatch_pending(session_id)
    print(f'M01 published: {events}; audit entries: {len(await reducer.audit_records(session_id))}')
    print('Demo uses only synthetic references; no real audio or customer data.')

if __name__ == '__main__':
    asyncio.run(main())
~~~~

### automotive_voice/m03_demo.py

~~~~python
"""M03 fully synthetic two-phase vehicle booking; no network, voice or real CRM."""
import asyncio
from datetime import datetime, timezone, timedelta
from automotive_voice.conversation import ConversationReducer, ConversationSignal, SignalKind
from automotive_voice.dialogue import (ReferenceStore, DialogueInput, DialoguePolicy,
    DialogueCoordinator, FakeCRM, FakeBookingService, VehicleRecord, PriceQuote, AccessContext,
    AppointmentSlot, Availability, Intent)

async def main():
    sid = 'm03-automotive-local-demo'
    store = ReferenceStore()
    reducer = ConversationReducer()
    when = datetime.now(timezone.utc)
    slot = AppointmentSlot((when + timedelta(days=3)).astimezone(timezone(timedelta(hours=3))).replace(hour=14,minute=30,second=0,microsecond=0).isoformat(), 'TRABZON')
    crm = FakeCRM({'demo-car':VehicleRecord('demo-car','Nissan','Qashqai',2024)},
                  {'demo-car':PriceQuote('demo-car',1250000,'synthetic-quote',when+timedelta(days=3))})
    booking = FakeBookingService({FakeBookingService.key('demo-car',slot):Availability.AVAILABLE})
    policy = DialoguePolicy(crm,booking,store)
    coord = DialogueCoordinator(reducer,policy,store)
    access = AccessContext(authenticated=True, crm_processing_allowed=True)

    async def emit(kind,ref=None):
        snap = await reducer.try_snapshot(sid)
        signal = ConversationSignal.create(kind,sid,int(snap.turn_id) if snap else 0,
                 int(snap.generation_id) if snap else 0,
                 await reducer.expected_sequence(sid),reference=ref)
        return await reducer.handle(signal)

    await emit(SignalKind.SESSION_OPENED)
    for input_item in [DialogueInput(Intent.PRICE_LOOKUP,'demo-car'),
                       DialogueInput(Intent.REQUEST_INSPECTION,'demo-car',slot),
                       DialogueInput(Intent.CONFIRM)]:
        ref=store.put_input(sid,input_item)
        out=await emit(SignalKind.TRANSCRIPT_FINAL,ref)
        response=await coord.process(out.effects[0],access)
        assert response.status == 'applied',response
        print(input_item.intent.value, ':',store.get_response(sid,response.response_ref).text)
        await emit(SignalKind.PLAYOUT_FINISHED)
    assert booking.creations == 1
    await emit(SignalKind.HANGUP)
    print('PASS: 3 turns; 1 confirmed synthetic booking; real audio/phone not used')

if __name__ == '__main__':
    asyncio.run(main())
~~~~

### automotive_voice/m04_report.py

~~~~python
"""Deterministic, text-only golden set impact report. No model/GPU/audio."""
from __future__ import annotations
import csv
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from .nlp import TurkishAutomotiveNormalizer, A01YTReadOnlyAdapter

ROOT = Path(__file__).resolve().parents[1]

def build_report(output: Path | None = None) -> dict:
    dataset = ROOT/'data/fixtures/legacy_320_cases.json'
    data = json.loads(dataset.read_text(encoding='utf-8'))
    if len(data) != 320 or len({r['id'] for r in data}) != 320:
        raise ValueError('golden 320 fixture has changed')
    a01_db = ROOT/'data/a01yt/a01yt_v05_readonly.sqlite3'
    lex = A01YTReadOnlyAdapter(a01_db).load()
    normalizer = TurkishAutomotiveNormalizer(lexicon=lex, vocab_path=ROOT/'data/a01yt/freya_char_vocab.json')
    rows=[]
    for entry in data:
        norm = normalizer.normalize(entry['text'])
        rows.append({'id':entry['id'], 'category':entry['category'],
                     'changed':int(norm.spoken_text != norm.display_text),
                     'review_required':int(norm.review_required),
                     'unsupported_chars':''.join(norm.unsupported_chars),
                     'warning_codes':';'.join(norm.warnings),
                     'applied_rules':';'.join(norm.rules_applied),
                     'original':norm.display_text,'prepared':norm.spoken_text})
    with sqlite3.connect(a01_db) as conn:
        source_count=conn.execute('SELECT count(*) FROM sources').fetchone()[0]
        segments=conn.execute('SELECT count(*) FROM segments').fetchone()[0]
        approved_annotations=conn.execute("SELECT count(*) FROM annotations WHERE status='approved'").fetchone()[0]
    metrics = {'input_count':len(rows), 'input_sha256':sha256(dataset.read_bytes()).hexdigest(),
               'changed_texts':sum(r['changed'] for r in rows),
               'review_required':sum(r['review_required'] for r in rows),
               'unsupported_char_cases':sum(bool(r['unsupported_chars']) for r in rows),
               'a01yt_sources':source_count,'a01yt_segments':segments,
               'a01yt_approved_annotations':approved_annotations,
               'active_lexicon_rules':len(lex.rules),
               'voice_quality_measured':False,'audio_generated':False,
               'interpretation':'Text transformations are NOT evidence of pronunciation or speech quality improvement.'}
    if output is not None:
        output.mkdir(parents=True,exist_ok=True)
        (output/'m04_320_summary.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        with (output/'m04_320_compare.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    return metrics

def main():
    print(json.dumps(build_report(ROOT/'data/reports'),ensure_ascii=False,indent=2))

if __name__=='__main__': main()
~~~~

### automotive_voice/m05_demo.py

~~~~python
"""No-audio demonstration of M04 -> M05 -> fake TTS -> interruption."""
import asyncio
import json
from pathlib import Path
from .core.event_bus import EventBus
from .core.session_manager import SessionManager
from .nlp import TurkishAutomotiveNormalizer, A01YTReadOnlyAdapter
from .prosody import ProsodyClausePlanner, MockTTS

ROOT=Path(__file__).resolve().parents[1]
async def main():
    sid='m05-text-demo'
    mgr=SessionManager(EventBus())
    await mgr.create(sid)
    await mgr.start(sid)
    await mgr.begin_turn(sid)
    snap=await mgr.begin_response(sid)
    lex=A01YTReadOnlyAdapter(ROOT/'data/a01yt/a01yt_v05_readonly.sqlite3').load()
    normalizer=TurkishAutomotiveNormalizer(lexicon=lex, vocab_path=ROOT/'data/a01yt/freya_char_vocab.json')
    planner=ProsodyClausePlanner(lexicon=lex)
    p=planner.plan(normalizer.normalize('Randevu üç kasım iki bin yirmi altı saat on dört otuzda. Bunu onaylıyor musunuz?'),
                   session_id=snap.session_id,turn_id=snap.turn_id,generation_id=snap.generation_id)
    tts=MockTTS(mgr)
    receipt=await tts.enqueue(p)
    delivered=await tts.pop_next()
    await mgr.interrupt(sid)
    late=await tts.pop_next()
    out={'plan':p.safe_metadata(),'mock_enqueue':receipt.__dict__ if hasattr(receipt,'__dict__') else
         {'accepted':receipt.accepted,'reason':receipt.reason,'count':receipt.count},
         'first_clause_dispatched':delivered is not None,
         'old_generation_clause_after_barge_in':late is not None,
         'audio_generated':False}
    print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':
    asyncio.run(main())
~~~~

### automotive_voice/m05_report.py

~~~~python
"""M05 320-golden text-only planning report. Never produces audio."""
from __future__ import annotations
from collections import Counter
from hashlib import sha256
import csv
import json
from pathlib import Path
from .nlp import TurkishAutomotiveNormalizer, A01YTReadOnlyAdapter
from .core.identifiers import SessionId, TurnId, GenerationId
from .prosody import ProsodyClausePlanner

ROOT = Path(__file__).resolve().parents[1]
LEGACY_SHA256 = '7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e'

def build_report(output: Path | None = None) -> dict:
    fixture = ROOT/'data/fixtures/legacy_320_cases.json'
    digest = sha256(fixture.read_bytes()).hexdigest()
    if digest != LEGACY_SHA256:
        raise ValueError('legacy 320 SHA-256 mismatch')
    rows_in = json.loads(fixture.read_text(encoding='utf-8'))
    if len(rows_in) != 320 or len({e['id'] for e in rows_in}) != 320:
        raise ValueError('legacy 320 fixture altered')
    lex = A01YTReadOnlyAdapter(ROOT/'data/a01yt/a01yt_v05_readonly.sqlite3').load()
    n = TurkishAutomotiveNormalizer(lexicon=lex, vocab_path=ROOT/'data/a01yt/freya_char_vocab.json')
    p = ProsodyClausePlanner(lexicon=lex)
    rows=[]
    for entry in rows_in:
        normalization=n.normalize(entry['text'])
        plan=p.plan(normalization,session_id=SessionId('m05-report'), turn_id=TurnId(1),generation_id=GenerationId(1))
        rows.append({'case_id':entry['id'],'category':entry['category'],
                     'status':plan.status.value,'clauses':len(plan.clauses),
                     'protected_spans':len(plan.protected_spans),
                     'tts_input_count':len(plan.tts_inputs()),
                     'warning_codes':';'.join(plan.warning_codes),
                     'breaks':';'.join(c.break_kind.value for c in plan.clauses)})
    statuses=Counter(r['status'] for r in rows)
    summary={'fixture_count':320,'fixture_sha256':digest,
             'ready_plans':statuses['ready'], 'review_required_plans':statuses['review_required'],
             'total_text_clauses':sum(r['clauses'] for r in rows),
             'eligible_mock_tts_inputs':sum(r['tts_input_count'] for r in rows),
             'total_protected_spans':sum(r['protected_spans'] for r in rows),
             'active_approved_lexicon_rules':len(lex.rules),
             'real_tts_calls':0,'audio_files_generated':0,
             'claims_about_audio_quality':'none; text-only deterministic simulation'}
    if output is not None:
        output.mkdir(parents=True,exist_ok=True)
        (output/'m05_320_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        with (output/'m05_320_clause_report.csv').open('w',newline='',encoding='utf-8-sig') as f:
            writer=csv.DictWriter(f, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    return summary

def main():
    print(json.dumps(build_report(ROOT/'data/reports'),ensure_ascii=False,indent=2))

if __name__=='__main__': main()
~~~~

### automotive_voice/m06_demo.py

~~~~python
"""M06 deterministic metadata-only barge-in demonstration."""
import asyncio
import json
from automotive_voice.audio import (AudioChunkMetadata, Codec, MediaFormat,
                                     MediaBuffer, MediaCoordinator)
from automotive_voice.telephony import FakeTransport
from automotive_voice.conversation import (ConversationReducer, ConversationSignal,
                                            SignalKind, Decision)
from automotive_voice.core.identifiers import SessionId,TurnId,GenerationId

async def main():
    r=ConversationReducer();sid='m06-demo'
    async def step(kind,ref=None):
        snap=await r.try_snapshot(sid)
        signal=ConversationSignal.create(kind,sid,int(snap.turn_id) if snap else 0,int(snap.generation_id) if snap else 0,
                        await r.expected_sequence(sid),reference=ref)
        return await r.handle(signal)
    await step(SignalKind.SESSION_OPENED)
    await step(SignalKind.TRANSCRIPT_FINAL,ref='transcript:1')
    await step(SignalKind.LLM_RESPONSE_READY,ref='response:1')
    q=MediaBuffer(r.manager);t=FakeTransport()
    coordinator=MediaCoordinator(r,q,t)
    frame=AudioChunkMetadata(SessionId(sid),TurnId(1),GenerationId(1),'tts-out',0,320,20,0,MediaFormat(Codec.PCM_S16LE,16000),0)
    assert (await q.enqueue(frame)).accepted
    delivered=await coordinator.send_next(sid)
    interrupted=await step(SignalKind.VAD_SPEECH_STARTED)
    request=await coordinator.request_flush(interrupted.effects[-1])
    stale=await q.enqueue(frame)
    ack=await t.confirm_flush(sid,request.flush_request_id)
    result=await coordinator.accept_fake_ack(ack,sequence=await r.expected_sequence(sid),mono_ns=10**20//1000)
    print(json.dumps({'accepted_mock_chunk':delivered.accepted,'stale_chunk_reason':stale.reason,
                      'flush_id':request.flush_request_id,'fake_ack_applied':result.decision==Decision.APPLIED,
                      'end_state':result.state.value,'real_audio_generated':False,
                      'actual_pbx_flush_proven':ack.real_pbx_proven},ensure_ascii=False,indent=2))

if __name__=='__main__':asyncio.run(main())
~~~~

### automotive_voice/m07_demo.py

~~~~python
"""M07 metadata-only synthetic stream + barge-in demo; no real WAV, model or PBX."""
from __future__ import annotations
import asyncio
import json
from automotive_voice.core.event_bus import EventBus
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.core.identifiers import SessionId,TurnId,GenerationId
from automotive_voice.conversation import ConversationReducer,ConversationSignal,SignalKind,Decision
from automotive_voice.conversation.effects import EffectKind
from automotive_voice.prosody import MockTTS
from automotive_voice.prosody.contracts import ClausePlan,Clause,BreakKind,PlanStatus
from automotive_voice.audio import MediaBuffer,MediaCoordinator
from automotive_voice.telephony import FakeTransport
from automotive_voice.adapters.lifecycle import (MockClock,AdapterKind,AdapterSupervisor,SyntheticStreamBridge,ResultCode)

async def main()->dict:
    c=MockClock();manager=SessionManager(EventBus());reducer=ConversationReducer(manager)
    sid='m07-demo'
    async def signal(kind,ref=None):
        snap=await reducer.try_snapshot(sid)
        return await reducer.handle(ConversationSignal.create(kind,sid,
            int(snap.turn_id) if snap else 0,int(snap.generation_id) if snap else 0,
            await reducer.expected_sequence(sid),reference=ref,mono_ns=c.now_ns()))
    await signal(SignalKind.SESSION_OPENED)
    await signal(SignalKind.TRANSCRIPT_FINAL,'ref:customer')
    await signal(SignalKind.LLM_RESPONSE_READY,'ref:policy-approved-reply')
    text='Merhaba dünya'
    plan=ClausePlan(SessionId(sid),TurnId(1),GenerationId(1),text,PlanStatus.READY,(
        Clause(0,0,7,'Merhaba',BreakKind.PAUSE,110,'continuation'),
        Clause(1,8,13,'dünya',BreakKind.FINAL,0,'statement')),(),())
    q=MockTTS(manager);assert (await q.enqueue(plan)).accepted
    b=MediaBuffer(manager);t=FakeTransport(adapter_id='m07-fake-pbx')
    media=MediaCoordinator(reducer,b,t)
    supervisor=AdapterSupervisor(manager,c,media=media)
    await supervisor.start_all()
    bridge=SyntheticStreamBridge(manager,c,supervisor.adapters[AdapterKind.TTS],q,b)
    assert (await bridge.submit_next_clause()).accepted
    await supervisor.tick_all();c.advance(20_000_000)
    first=(await supervisor.tick_all())[AdapterKind.TTS][0]
    first_media=await bridge.materialize_metadata(first)
    dispatched=await media.send_next(sid)
    assert first_media.accepted and dispatched.accepted
    assert (await bridge.submit_next_clause()).accepted
    await supervisor.tick_all() # second TTS generation now in-flight
    interrupted=await signal(SignalKind.VAD_SPEECH_STARTED)
    for e in interrupted.effects:
        if e.kind in (EffectKind.CANCEL_GENERATION,EffectKind.FLUSH_MEDIA):
            assert (await supervisor.dispatch_effect(e)).accepted
    c.advance(20_000_000)
    late=supervisor.adapters[AdapterKind.TTS].read_result('clause:m07-demo:1:1:1')
    assert late is not None and late.code is ResultCode.CANCELLED
    assert (await manager.snapshot(sid)).state.value=='INTERRUPTING'
    request=media._pending[sid]
    assert not t._confirmed
    # Explicit test-only acknowledgement; never auto-confirmed by supervisor.
    ack=await t.confirm_flush(sid,request.flush_request_id)
    ack_result=await media.accept_fake_ack(ack,sequence=await reducer.expected_sequence(sid),mono_ns=c.now_ns())
    assert ack_result.decision is Decision.APPLIED
    return {
        'adapter_states':{key:value.state.value for key,value in supervisor.health().items()},
        'initial_synthetic_metadata_sent':dispatched.accepted,
        'stale_tts_result':late.code.value,
        'flush_state_after_request':'INTERRUPTING',
        'explicit_fake_ack_applied':True,
        'final_state':ack_result.state.value,
        'actual_pbx_ack_proven':ack.real_pbx_proven,
        'audio_bytes_generated':0,
        'network_calls':0
    }

if __name__=='__main__':print(json.dumps(asyncio.run(main()),ensure_ascii=False,indent=2))
~~~~

### automotive_voice/m09_demo.py

~~~~python
"""M09 offline synthetic acceptance: python -m automotive_voice.m09_demo."""
import asyncio
import json
from automotive_voice.e2e.runner import run_catalog

def main():
    report=asyncio.run(run_catalog())
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))
    if report['failed']:raise SystemExit(1)
if __name__=='__main__':main()
~~~~

### automotive_voice/m10_demo.py

~~~~python
"""M10 offline resilience run: all M09 policies with durable M01 and safer TTS presentation.

No GPU, socket, STT, Freya model, PBX or audio bytes. Use --output for report.
"""
import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from automotive_voice.e2e import ScenarioRunner, SCENARIOS
from automotive_voice.resilience.durable import DurableJournal, DurableSessionManager
from automotive_voice.core.event_bus import EventBus

async def run():
    cases=[]
    for name in SCENARIOS:
        with tempfile.TemporaryDirectory(prefix='m10_sim_') as d:
            journal=DurableJournal(Path(d)/'events.sqlite3')
            try:
                result=await ScenarioRunner(m10_presentation=True,durable_journal=journal).run(name)
                blocked=sum(e.get('step')=='prosody' and e.get('outcome')=='review_required' for e in result.trace)
                cases.append({'scenario':name,'passed':bool(result.passed),
                              'speech_review_blocked':blocked,
                              'durable_outbox':journal.counts()['pending_outbox']})
            finally: journal.close()
    with tempfile.TemporaryDirectory(prefix='m10_recovery_') as d:
        path=Path(d)/'events.sqlite3';j=DurableJournal(path)
        try:
            m=DurableSessionManager(EventBus(),j)
            await m.restore_fail_closed();await m.create('m10-restart-check')
            await m.start('m10-restart-check')
        finally:j.close()
        j=DurableJournal(path)
        try:
            restored=DurableSessionManager(EventBus(),j)
            failclosed=await restored.restore_fail_closed()
            snap=await restored.snapshot('m10-restart-check')
            recovery={'forced_terminal_count':failclosed,'terminal_state':snap.state.value,
                      'manual_reconciliation_required':True}
        finally:j.close()
    return {'mode':'M10_DRY_RUN','passed':sum(c['passed'] for c in cases),
            'total':len(cases),'speech_review_blocked':sum(c['speech_review_blocked'] for c in cases),
            'real_network_connections':0,'audio_bytes':0,'production_ready':False,
            'recovery':recovery,'scenarios':cases}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',default=None,help='Write UTF-8 JSON report to local file')
    a=parser.parse_args()
    report=asyncio.run(run())
    if a.output:
        out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    raise SystemExit(0 if report['passed']==report['total'] and
                     report['recovery']['terminal_state']=='FAILED' else 1)
if __name__=='__main__':main()
~~~~

### automotive_voice/m11/__init__.py

~~~~python
"""M11 physical evidence gates; all device/network tests are explicitly opted into."""
~~~~

### automotive_voice/m11/__main__.py

~~~~python
"""M11 local acceptance CLI. Optional real actions require --enable-physical.

Never installs packages, downloads media or opens a phone call automatically.
"""
from __future__ import annotations
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import wave
import csv
from pathlib import Path
from .acceptance import (Gate,Status,now,evidence_ref,hash_file,save_gate,
                         write_summary,wav_info,error_rates,validate_pbx_trace,validate_voice_reviews)

PROJECT=Path(__file__).resolve().parents[2]
DEFAULT_FOLDER=PROJECT/'data'/'m11'/'results'

def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n',encoding='utf-8')

def gate(folder,name,status,checks,metrics=None,evidence=(),physical=False):
    val=Gate(name,Status(status),tuple(checks),metrics or {},tuple(evidence),now(),physical)
    path=save_gate(folder,val)
    print(f'{name}: {status} | '+', '.join(checks)+f' | {path}')
    return status

def preflight(args):
    checks=[];details={'system':platform.platform(), 'python':platform.python_version(),
                       'windows':sys.platform=='win32','ffmpeg_available':bool(shutil.which('ffmpeg'))}
    try:
        import torch
        details['torch_version']=torch.__version__
        details['cuda_available']=bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            details['gpu']=torch.cuda.get_device_name(0)
            details['gpu_vram_bytes']=torch.cuda.get_device_properties(0).total_memory
    except ImportError:details['cuda_available']=False
    model=Path(args.model_dir) if args.model_dir else None
    details['model_files_present']=bool(model and all((model/f).is_file() for f in ('config.json','model.safetensors')))
    if details['model_files_present']:
        details['model_sha256']=hash_file(model/'model.safetensors')
        details['model_config_sha256']=hash_file(model/'config.json')
    checkout=Path(args.freya_checkout) if args.freya_checkout else None
    details['freya_checkout_present']=bool(checkout and (checkout/'freyatts'/'pipeline.py').is_file())
    details['official_model_id']='freyavoice/freya-tts'
    checks.extend(k for k,ok in [('windows_11',sys.platform=='win32'),
               ('python_3_11',sys.version_info[:2]==(3,11)),
               ('ffmpeg',details['ffmpeg_available']),
               ('cuda_gpu',details['cuda_available']),
               ('local_freya_model',details['model_files_present']),
               ('local_freya_checkout',details['freya_checkout_present'])] if not ok)
    out=args.folder/'preflight_details.json';dump(out,details)
    # Edge/driver real testing is a separate manual gate. Preflight never establishes it.
    return gate(args.folder,'windows_edge','HOLD',checks or ['edge_and_audio_device_manual_checks_required'],
                details,(evidence_ref(out),))

def _sample_cases(args):
    cases=json.loads((PROJECT/'data'/'fixtures'/'legacy_320_cases.json').read_text(encoding='utf-8'))
    assert len(cases)==320, 'golden corpus unexpectedly changed'
    if args.mode=='smoke':
        # Capture all smoke data but cap to 12 for GPU warm-up.
        return [c for c in cases if c['tier']=='smoke'][:12]
    return cases

def tts(args):
    if not args.enable_physical:
        return gate(args.folder,'freya_leyla','HOLD',['physical_inference_requires_explicit_enable_flag'])
    model=Path(args.model_dir)
    checkout=Path(args.freya_checkout)
    for f in ('config.json','model.safetensors'):
        if not (model/f).is_file():raise ValueError('local model missing '+f)
    if not (checkout/'freyatts'/'pipeline.py').is_file():raise ValueError('Freya source checkout missing')
    if not args.allow_cpu:
        import torch
        if not torch.cuda.is_available():
            return gate(args.folder,'freya_leyla','HOLD',['cuda_not_available'])
    # Explicit local checkout avoids accidentally importing another model's code.
    sys.path.insert(0,str(checkout.resolve()))
    import numpy as np
    from freyatts import FreyaTTS
    from automotive_voice.nlp.normalizer import TurkishAutomotiveNormalizer
    from automotive_voice.nlp.a01yt_adapter import A01YTReadOnlyAdapter
    lex=A01YTReadOnlyAdapter(PROJECT/'data'/'a01yt'/'a01yt_v05_readonly.sqlite3').load()
    normalizer=TurkishAutomotiveNormalizer(lex,PROJECT/'data'/'a01yt'/'freya_char_vocab.json')
    runtime=FreyaTTS.from_pretrained(str(model.resolve()), device='cpu' if args.allow_cpu else 'cuda')
    cases=_sample_cases(args)
    rows=[];blocked=[];failed=[]
    model_sha=hash_file(model/'model.safetensors')
    outdir=args.output_dir
    outdir.mkdir(parents=True,exist_ok=True)
    for case in cases:
        normalized=normalizer.normalize(case['text'])
        if normalized.review_required:
            blocked.append({'id':case['id'],'warnings':normalized.warnings,
                            'unsupported_chars':normalized.unsupported_chars})
            continue
        for version,spoken in (('raw',case['text']),('prepared',normalized.spoken_text)):
            t0=time.perf_counter()
            try:
                wav=runtime.synthesize(spoken,steps=args.steps,seed=args.seed)
            except (ValueError,RuntimeError,KeyError) as exc:
                failed.append({'id':case['id'],'variant':version,'error_type':type(exc).__name__})
                continue
            elapsed=time.perf_counter()-t0
            arr=np.asarray(wav,dtype=np.float32)
            if arr.ndim!=1 or arr.size==0 or not np.isfinite(arr).all():raise ValueError('bad generated audio')
            arr=np.clip(arr,-1,1)
            out=outdir/(case['id']+'_'+version+'.wav')
            pcm=(arr*32767).astype('<i2').tobytes()
            with wave.open(str(out),'wb') as h:
                h.setnchannels(1);h.setsampwidth(2);h.setframerate(48000);h.writeframes(pcm)
            info=wav_info(out)
            rows.append({'id':case['id'],'variant':version,'wav':str(out.resolve()),
                         'sha256':hash_file(out),'duration_s':round(info['duration_seconds'],4),
                         'inference_s':round(elapsed,4),
                         'rtf':round(elapsed/info['duration_seconds'],4),'seed':args.seed,
                         'steps':args.steps, 'model_sha256':model_sha})
    path=args.folder/'freya_leyla_measurements.json';dump(path,{'mode':args.mode,
         'model_dir':str(model.resolve()),'model_sha256':model_sha,
         'seed':args.seed,'steps':args.steps,'generated':len(rows),'blocked':blocked,'failed':failed,'rows':rows})
    # A/B waveform presence alone cannot demonstrate human-scored voice identity.
    checks=[f'generated_{len(rows)}_waves',f'blocked_{len(blocked)}_cases',f'failed_{len(failed)}_variants',
            'voice_identity_and_pronunciation_human_review_pending']
    return gate(args.folder,'freya_leyla','HOLD',checks,
                {'generated':len(rows),'target_wavs':640,'blocked':len(blocked),'failed':len(failed),'seed':args.seed},
                [evidence_ref(path)],physical=True)

def voice_review(args):
    source=args.folder/'freya_leyla_measurements.json'
    if not source.is_file() or not args.manifest.is_file():
        return gate(args.folder,'freya_leyla','HOLD',['full_corpus_or_human_review_manifest_missing'])
    measurements=json.loads(source.read_text(encoding='utf-8'))
    reviews=[json.loads(x) for x in args.manifest.read_text(encoding='utf-8').splitlines() if x.strip()]
    try:
        verdict=validate_voice_reviews(measurements,reviews)
    except (ValueError,KeyError,OSError) as exc:
        return gate(args.folder,'freya_leyla','FAIL',['voice_review_validation_failed',str(exc)[:100]],
                evidence=(evidence_ref(source),evidence_ref(args.manifest)),physical=True)
    status='PASS' if verdict['all_pass'] else 'FAIL'
    return gate(args.folder,'freya_leyla',status,
                ['all_320_ab_pairs_human_reviewed','wav_hashes_verified',
                 'leyla_voice_and_pronunciation_reviewed'],verdict,
                (evidence_ref(source),evidence_ref(args.manifest)),physical=True)

def stt(args):
    if not args.enable_physical:
        return gate(args.folder,'stt_vad','HOLD',['physical_stt_requires_explicit_enable_flag'])
    if not args.manifest.is_file():return gate(args.folder,'stt_vad','HOLD',['missing_labeled_audio_manifest'])
    try:from faster_whisper import WhisperModel
    except ImportError:return gate(args.folder,'stt_vad','HOLD',['faster_whisper_not_installed'])
    if not args.model_dir.is_dir():return gate(args.folder,'stt_vad','HOLD',['local_stt_model_missing'])
    model=WhisperModel(str(args.model_dir.resolve()),device=args.device,compute_type=args.compute_type,local_files_only=True)
    pairs=[];rows=[]
    for line in args.manifest.read_text(encoding='utf-8').splitlines():
        if not line.strip():continue
        rec=json.loads(line)
        audio=Path(rec['audio_path'])
        info=wav_info(audio)
        if not rec['reference'].strip():raise ValueError('missing human reference')
        segments,meta=model.transcribe(str(audio),language='tr',vad_filter=True,beam_size=5)
        actual=' '.join(x.text.strip() for x in segments)
        pairs.append((rec['reference'],actual))
        rows.append({'audio_sha256':hash_file(audio),'audio_seconds':info['duration_seconds'],
                     'reference':rec['reference'],'transcription':actual})
    metrics=error_rates(pairs)
    path=args.folder/'stt_vad_measurements.json';dump(path,{'metrics':metrics,'samples':rows,
          'vad_acoustic_barge_in_measured':False})
    return gate(args.folder,'stt_vad','HOLD',['stt_wer_cer_measured','real_vad_barge_in_unmeasured'],
                {**metrics,'recordings':len(rows)},[evidence_ref(path)],physical=True)

def codec(args):
    if not args.enable_physical:
        return gate(args.folder,'codec','HOLD',['physical_codec_requires_explicit_enable_flag'])
    if not args.input_wav or not args.input_wav.is_file():
        return gate(args.folder,'codec','HOLD',['real_input_wav_missing'])
    if not shutil.which('ffmpeg'):return gate(args.folder,'codec','HOLD',['ffmpeg_missing'])
    inp=wav_info(args.input_wav)
    out=args.output_dir;out.mkdir(parents=True,exist_ok=True)
    cases=[]
    for name,fmt,rate,bps in [('slin16','s16le',16000,2),('slin8','s16le',8000,2),
                               ('ulaw','mulaw',8000,1),('alaw','alaw',8000,1)]:
        path=out/(name+'.raw')
        proc=subprocess.run(['ffmpeg','-nostdin','-hide_banner','-loglevel','error','-y',
                     '-i',str(args.input_wav),'-ac','1','-ar',str(rate),'-f',fmt,str(path)],
                     capture_output=True,text=True,timeout=90)
        if proc.returncode: raise RuntimeError('ffmpeg: '+proc.stderr[:300])
        frame=rate*20//1000*bps
        nbytes=path.stat().st_size
        if nbytes<=0: raise ValueError('empty codec output')
        frames=nbytes//frame;leftover=nbytes%frame
        cases.append({'codec':name,'rate':rate,'frame_ms':20,'payload_bytes_per_frame':frame,
              'full_frames':frames,'tail_bytes':leftover,'hash':hash_file(path),
              'duration_seconds':round(nbytes/(rate*bps),4)})
    report=args.folder/'codec_measurements.json';dump(report,{'source':evidence_ref(args.input_wav),
              'cases':cases,'input_duration_s':inp['duration_seconds']})
    # Encoding a file is NOT a live 20ms pacing / roundtrip phone validation.
    return gate(args.folder,'codec','HOLD',['ffmpeg_encoding_measured',
            'real_transport_playout_and_pacing_pending'],{'codecs':len(cases)},[evidence_ref(report)],physical=True)

def youtube(args):
    if not args.manifest.is_file():return gate(args.folder,'a01yt_references','HOLD',['real_reference_manifest_missing'])
    sources={row['id'] for row in csv.DictReader((PROJECT/'data'/'a01yt'/'sources_verbal_permission_v05.csv').open(encoding='utf-8-sig',newline=''))}
    rows=[];errors=[];unique=set()
    for i,line in enumerate(args.manifest.read_text(encoding='utf-8').splitlines(),1):
        if not line.strip():continue
        try:
            r=json.loads(line)
            if r['source_id'] not in sources:raise ValueError('unrecognized source')
            if r.get('review_status')!='approved' or not r.get('reviewer') or not r.get('reviewed_at_utc'):
                raise ValueError('human approval missing')
            if r.get('origin')!='direct_from_rights_holder':raise ValueError('origin is not direct')
            if not (isinstance(r.get('start_ms'),int) and isinstance(r.get('end_ms'),int)
                    and 0<=r['start_ms']<r['end_ms']):raise ValueError('timecode invalid')
            if not r.get('transcript') or not r.get('spoken_tr') or not r.get('canonical'):
                raise ValueError('annotation incomplete')
            path=Path(r['audio_path'])
            info=wav_info(path)
            if r['clip_sha256'].lower()!=hash_file(path):raise ValueError('clip checksum mismatch')
            if r['end_ms']-r['start_ms']>info['duration_seconds']*1000+250:
                raise ValueError('time range exceeds clip')
            rows.append({'source_id':r['source_id'],'canonical':r['canonical'],
                   'clip_sha256':r['clip_sha256'],'reviewer':r['reviewer']})
            unique.add(r['canonical'].casefold())
        except (KeyError,OSError,ValueError,TypeError) as exc:
            errors.append(f'line_{i}_{str(exc)[:65]}')
    path=args.folder/'a01yt_reference_audit.json';dump(path,{'audited_count':len(rows),
                     'unique_targets':len(unique),'errors':errors,'rows':rows})
    status='FAIL' if errors else 'PASS' if len(unique)>=50 else 'HOLD'
    checks=['real_clips_approved_'+str(len(rows)),'unique_targets_'+str(len(unique))]
    if errors:checks+=errors[:5]
    if len(unique)<50:checks+=['initial_50_not_complete']
    return gate(args.folder,'a01yt_references',status,checks,{'approved_clips':len(rows),
             'unique_targets':len(unique)},[evidence_ref(path),evidence_ref(args.manifest)],physical=True)

def pbx(args):
    if not args.trace.is_file():return gate(args.folder,'asterisk_pbx','HOLD',['no_real_asterisk_trace'])
    if not args.enable_physical:
        return gate(args.folder,'asterisk_pbx','HOLD',['physical_pbx_requires_explicit_enable_flag'])
    if not args.capture_file or not args.capture_file.is_file() or not args.observer_record or not args.observer_record.is_file():
        return gate(args.folder,'asterisk_pbx','HOLD',['independent_live_capture_and_observer_record_required'])
    try:
        trace=[json.loads(x) for x in args.trace.read_text(encoding='utf-8').splitlines() if x.strip()]
        details=validate_pbx_trace(trace)
        # Independent raw capture and observer record are required in addition to an exported event list.
        capture=args.capture_file.read_text(encoding='utf-8',errors='replace')
        if not all(token in capture for token in ('MEDIA_START','FLUSH_MEDIA','QUEUE_DRAINED',details['channel_id'])):
            raise ValueError('raw PBX capture does not corroborate trace')
        observer=json.loads(args.observer_record.read_text(encoding='utf-8'))
        if (observer.get('channel_id')!=details['channel_id'] or not observer.get('observer')
              or observer.get('mock') is not False
              or type(observer.get('heard_old_audio_ms_after_speech_start')) not in (int,float)
              or abs(observer['heard_old_audio_ms_after_speech_start']-details['heard_old_audio_ms_after_speech_start'])>20):
            raise ValueError('missing or conflicting independent listener evidence')
        import math
        samples=observer.get('measurements_ms')
        if (not isinstance(samples,list) or len(samples)<30 or
            any(type(v) not in (int,float) or v<0 or v>30000 for v in samples)):
            return gate(args.folder,'asterisk_pbx','HOLD',['at_least_30_independent_real_interruptions_required'],
                        {'observed':len(samples) if isinstance(samples,list) else 0},
                        [evidence_ref(args.trace),evidence_ref(args.capture_file),evidence_ref(args.observer_record)],physical=True)
        p95=sorted(samples)[math.ceil(0.95*len(samples))-1]
        details['interruptions']=len(samples)
        details['p95_old_audio_ms']=p95
        status='PASS' if p95<=400 and details['latency_target_met'] else 'FAIL'
        checks=['same_channel_and_ordered_queue_drain_verified',
                'raw_capture_and_independent_observer_correlated']
    except (ValueError,KeyError,TypeError) as exc:
        status='FAIL';details={};checks=['trace_invalid',str(exc)[:120]]
    return gate(args.folder,'asterisk_pbx',status,checks,details,
                [evidence_ref(args.trace),evidence_ref(args.capture_file),evidence_ref(args.observer_record)],physical=True)

def manual(args):
    # Reviewer-attested physical gates. Other gates require automated data contracts.
    allowed={'windows_edge','safety_privacy'}
    if args.gate not in allowed:raise ValueError('manual override forbidden for this gate')
    if not args.enable_physical:raise ValueError('explicit real-world reviewer opt-in required')
    if not args.reviewer.strip() or len(args.reviewer)<3 or len(args.statement.strip())<20:
        raise ValueError('reviewer and substantive observation required')
    if not args.evidence.is_file() or args.evidence.stat().st_size==0:
        raise ValueError('real evidence file required')
    check={'reviewer':args.reviewer.strip(),'observation':args.statement.strip(),
           'observed_at_utc':now(),'evidence_sha256':hash_file(args.evidence)}
    out=args.folder/(args.gate+'_attestation.json')
    dump(out,check)
    return gate(args.folder,args.gate,args.status,
                ('human_reviewed_physical_evidence',),check,
                (evidence_ref(out),evidence_ref(args.evidence)),physical=True)

def legacy(args):
    result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-q'],
                          cwd=PROJECT,env={**os.environ,'PYTHONPATH':str(PROJECT/'src')},
                          capture_output=True,text=True,timeout=90)
    path=args.folder/'regression_output.txt';path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
    fixture=PROJECT/'data'/'fixtures'/'legacy_320_cases.json'
    count=len(json.loads(fixture.read_text(encoding='utf-8')))
    status='PASS' if result.returncode==0 and count==320 else 'FAIL'
    return gate(args.folder,'legacy_regression',status,
                ['unittest_exit_'+str(result.returncode),'golden_count_'+str(count)],
                {'golden_count':count,'legacy_suite_exit':result.returncode},
                [evidence_ref(path),evidence_ref(fixture)])

def report(args):
    result=write_summary(args.folder,args.output)
    from .html_report import create_html
    create_html(result,args.output.with_suffix('.html'))
    print('M11 PHYSICAL ACCEPTANCE:',result['overall'], 'production_ready:',result['production_ready'])
    for g in result['gates']:
        print(' ',g['name'],g['status'],','.join(g['checks']))
    print('Report:',args.output,'HTML:',args.output.with_suffix('.html'))
    return result['overall']

def main():
    parser=argparse.ArgumentParser(description='M11 physical acceptance. NO real service action without explicit opt-in.')
    parser.add_argument('--folder',type=Path,default=DEFAULT_FOLDER)
    commands=parser.add_subparsers(dest='cmd',required=True)
    p=commands.add_parser('preflight');p.add_argument('--model-dir');p.add_argument('--freya-checkout')
    p=commands.add_parser('tts');p.add_argument('--enable-physical',action='store_true')
    p.add_argument('--allow-cpu',action='store_true');p.add_argument('--model-dir',type=Path,required=True)
    p.add_argument('--freya-checkout',type=Path,required=True);p.add_argument('--output-dir',type=Path,default=PROJECT/'data'/'m11'/'audio')
    p.add_argument('--mode',choices=['smoke','full'],default='smoke')
    p.add_argument('--steps',type=int,choices=[16,32,64],default=32);p.add_argument('--seed',type=int,default=9)
    p=commands.add_parser('voice-review');p.add_argument('--manifest',type=Path,required=True)
    p=commands.add_parser('stt');p.add_argument('--enable-physical',action='store_true')
    p.add_argument('--model-dir',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--device',choices=['cuda','cpu'],default='cuda');p.add_argument('--compute-type',default='float16')
    p=commands.add_parser('codec');p.add_argument('--enable-physical',action='store_true')
    p.add_argument('--input-wav',type=Path);p.add_argument('--output-dir',type=Path,default=PROJECT/'data'/'m11'/'codec')
    p=commands.add_parser('a01yt');p.add_argument('--manifest',type=Path,required=True)
    p=commands.add_parser('pbx');p.add_argument('--trace',type=Path,required=True);p.add_argument('--enable-physical',action='store_true')
    p.add_argument('--capture-file',type=Path);p.add_argument('--observer-record',type=Path)
    p=commands.add_parser('manual');p.add_argument('--gate',choices=['windows_edge','safety_privacy'],required=True)
    p.add_argument('--status',choices=['PASS','FAIL','HOLD'],required=True)
    p.add_argument('--enable-physical',action='store_true');p.add_argument('--reviewer',required=True)
    p.add_argument('--statement',required=True);p.add_argument('--evidence',type=Path,required=True)
    commands.add_parser('legacy')
    p=commands.add_parser('report');p.add_argument('--output',type=Path,default=PROJECT/'data'/'m11'/'M11_ACCEPTANCE.json')
    a=parser.parse_args()
    if a.cmd=='preflight':preflight(a)
    elif a.cmd=='tts':tts(a)
    elif a.cmd=='voice-review':voice_review(a)
    elif a.cmd=='stt':stt(a)
    elif a.cmd=='codec':codec(a)
    elif a.cmd=='a01yt':youtube(a)
    elif a.cmd=='pbx':pbx(a)
    elif a.cmd=='manual':manual(a)
    elif a.cmd=='legacy':legacy(a)
    elif a.cmd=='report':report(a)

if __name__=='__main__':main()
~~~~

### automotive_voice/m11/acceptance.py

~~~~python
"""M11 auditable, fail-closed acceptance verdicts. No fake measurements become PASS.

All gate records are inspectable JSON with SHA256 evidence references. The ledger
only establishes file integrity/field validation; human provenance and live
hardware authenticity must also be checked by the independent reviewer.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from hashlib import sha256
from enum import Enum
from typing import Iterable
import json
import unicodedata
import re
import wave

GATES = ('windows_edge', 'freya_leyla', 'stt_vad', 'codec', 'asterisk_pbx',
         'a01yt_references', 'safety_privacy', 'legacy_regression')

class Status(str, Enum):
    PASS = 'PASS'
    FAIL = 'FAIL'
    HOLD = 'HOLD'

@dataclass(frozen=True)
class Gate:
    name: str
    status: Status
    checks: tuple[str,...]
    metrics: dict
    evidence: tuple[dict,...]
    run_at_utc: str
    physical: bool = False

    def __post_init__(self):
        if self.name not in GATES: raise ValueError('unknown gate')
        if not isinstance(self.status, Status): raise TypeError('invalid status')
        if self.status is Status.PASS and not self.evidence:
            raise ValueError('PASS requires inspectable evidence')
        if self.name != 'legacy_regression' and self.status is Status.PASS and not self.physical:
            raise ValueError('physical PASS requires real-world evidence')

    def to_dict(self):
        d = asdict(self)
        d['status'] = self.status.value
        return d


def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')

def hash_file(path: Path) -> str:
    digest = sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def evidence_ref(path: Path, *, label: str = 'local_file') -> dict:
    if not path.is_file(): raise FileNotFoundError(str(path))
    return {'path': str(path.resolve()), 'sha256':hash_file(path), 'bytes':path.stat().st_size,'label':label}

def save_gate(folder: Path, gate: Gate) -> Path:
    folder.mkdir(parents=True,exist_ok=True)
    path = folder / f'{gate.name}.json'
    path.write_text(json.dumps(gate.to_dict(),ensure_ascii=False,indent=2,sort_keys=True)+'\n', encoding='utf-8')
    return path

def load_gate(folder: Path, name: str) -> Gate:
    path = folder / f'{name}.json'
    if not path.is_file():
        return Gate(name,Status.HOLD,('no_evidence_submitted',),{},(),now())
    raw = json.loads(path.read_text(encoding='utf-8'))
    if raw.get('name')!=name: raise ValueError('gate identity mismatch')
    gate=Gate(name,Status(raw['status']),tuple(raw['checks']),raw['metrics'],
              tuple(raw['evidence']),raw['run_at_utc'],raw.get('physical',False))
    if gate.status is Status.PASS:
        for item in gate.evidence:
            p=Path(item['path'])
            if not p.is_file() or p.stat().st_size!=item['bytes'] or hash_file(p)!=item['sha256']:
                raise ValueError('evidence damaged: '+name)
    return gate

def summary(folder:Path)->dict:
    gates=[]
    for name in GATES:
        try:gate=load_gate(folder,name)
        except (OSError,ValueError,KeyError,TypeError) as e:
            gate=Gate(name,Status.FAIL,('evidence_invalid',str(e)[:120]),{},(),now())
        gates.append(gate.to_dict())
    status= ('FAIL' if any(g['status']=='FAIL' for g in gates)
             else 'PASS' if all(g['status']=='PASS' for g in gates) else 'HOLD')
    return {'schema_version':'m11-acceptance-1','overall':status,
            'production_ready':False,  # physical acceptance != production security certification
            'gates':gates,'created_utc':now()}


def write_summary(folder:Path, output:Path):
    result=summary(folder)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


def wav_info(path:Path)->dict:
    with wave.open(str(path),'rb') as wav:
        if wav.getnchannels()!=1 or wav.getsampwidth()!=2:raise ValueError('16-bit mono PCM WAV required')
        frames=wav.getnframes(); rate=wav.getframerate()
        if frames<1 or rate not in (8000,16000,48000):raise ValueError('invalid WAV length/rate')
        return {'rate':rate,'frames':frames,'duration_seconds':frames/rate}


def norm_words(s: str)->list[str]:
    return re.findall(r'[\w]+',unicodedata.normalize('NFC',s).replace('I','ı').replace('İ','i').lower(),flags=re.UNICODE)

def distance(a:list,b:list)->int:
    prev=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        cur=[i]
        for j,y in enumerate(b,1):
            cur.append(min(prev[j]+1,cur[-1]+1,prev[j-1]+(x!=y)))
        prev=cur
    return prev[-1]

def error_rates(pairs:Iterable[tuple[str,str]])->dict:
    wd=wn=cd=cn=0
    for expected,actual in pairs:
        gold=norm_words(expected);hyp=norm_words(actual)
        wd+=distance(gold,hyp);wn+=len(gold)
        g=''.join(gold);h=''.join(hyp)
        cd+=distance(list(g),list(h));cn+=len(g)
    if not wn or not cn:raise ValueError('nonempty reference required')
    return {'wer':round(wd/wn,6),'cer':round(cd/cn,6),
            'word_errors':wd,'reference_words':wn,
            'char_errors':cd,'reference_chars':cn}


def validate_pbx_trace(trace:list[dict])->dict:
    """Asterisk real-trace gate. QUEUE_DRAINED is not proof of acoustic stop.

    Requires an independently captured MEDIA_START and physical interruption
    measurement, aligned to the same channel and ordered flush commands.
    """
    if not trace or any(not isinstance(x,dict) for x in trace):
        raise ValueError('nonempty structured trace required')
    if any(x.get('provenance')!='asterisk_live' or x.get('mock') is not False for x in trace):
        raise ValueError('fake or unproven trace')
    chan={x.get('channel_id') for x in trace}
    if len(chan)!=1 or not next(iter(chan)):raise ValueError('mixed/invalid channels')
    times=[x.get('mono_ns') for x in trace]
    if any(type(v)!=int or v<0 for v in times) or times!=sorted(times) or len(set(times))!=len(times):
        raise ValueError('trace must be strictly ordered')
    events=[x.get('event') for x in trace]
    required=('MEDIA_START','REPORT_QUEUE_DRAINED','FLUSH_MEDIA','QUEUE_DRAINED','HANGUP')
    if any(events.count(e)!=1 for e in required):raise ValueError('missing or duplicate PBX event')
    indices=[events.index(e) for e in required]
    if indices!=sorted(indices):raise ValueError('invalid flush event order')
    media=trace[events.index('MEDIA_START')]
    if media.get('codec') not in ('ulaw','alaw','slin8','slin16','g722'):
        raise ValueError('invalid live codec')
    if media.get('ptime_ms')!=20:raise ValueError('20 ms packetization not evidenced')
    interruption=next((x for x in trace if x.get('event')=='MEASURED_INTERRUPTION'),None)
    if not interruption:raise ValueError('physical interruption measurement absent')
    measured=interruption.get('heard_old_audio_ms_after_speech_start')
    if type(measured) not in (int,float) or measured<0 or measured>30000:
        raise ValueError('invalid measured interruption')
    return {'channel_id':next(iter(chan)),'codec':media['codec'],
            'heard_old_audio_ms_after_speech_start':measured,
            'queue_drained_observed':True,'pass_target_ms':400,
            'latency_target_met':measured<=400}


def validate_voice_reviews(measurements:dict,reviews:list[dict],*,expected_cases:int=320)->dict:
    """Review a fully generated A/B corpus; no AI guess or mock audio allowed."""
    if measurements.get('mode')!='full' or measurements.get('blocked') or measurements.get('failed'):
        raise ValueError('not a fully available 320-pair physical corpus')
    rows=measurements.get('rows') or []
    cases={}
    for row in rows:
        identifier=row['id']
        if row.get('variant') not in ('raw','prepared') or row['variant'] in cases.setdefault(identifier,{}):
            raise ValueError('invalid or duplicate TTS variant')
        if hash_file(Path(row['wav']))!=row['sha256'] or wav_info(Path(row['wav']))['rate']!=48000:
            raise ValueError('audio fingerprint/rate mismatch')
        cases[identifier][row['variant']]=row
    if len(cases)!=expected_cases or any(len(v)!=2 for v in cases.values()) or len(reviews)!=expected_cases:
        raise ValueError('exactly expected complete A/B comparisons required')
    seen=set(); identity_failures=[];pronunciation_failures=[]
    for r in reviews:
        cid=r.get('case_id')
        if cid not in cases or cid in seen:raise ValueError('unknown or duplicate case in review')
        seen.add(cid)
        if (r.get('raw_sha256')!=cases[cid]['raw']['sha256'] or
                r.get('prepared_sha256')!=cases[cid]['prepared']['sha256'] or
                not r.get('reviewer') or not r.get('reviewed_at_utc') or
                len(r.get('notes') or '')<10):
            raise ValueError('unattributed or mismatched human review')
        if type(r.get('leyla_identity_pass')) is not bool or type(r.get('prepared_pronunciation_pass')) is not bool:
            raise ValueError('explicit human bool decisions required')
        if not r['leyla_identity_pass']:identity_failures.append(cid)
        if not r['prepared_pronunciation_pass']:pronunciation_failures.append(cid)
    return {'reviewed_cases':expected_cases,'identity_failures':identity_failures,
            'pronunciation_failures':pronunciation_failures,
            'all_pass':not identity_failures and not pronunciation_failures}
~~~~

### automotive_voice/m11/html_report.py

~~~~python
"""Offline HTML acceptance summary; no JS/CDN. Evidence references stay in local JSON."""
from html import escape
from pathlib import Path

def create_html(data:dict,path:Path)->None:
    labels={
        'windows_edge':'Windows 11 / Edge','freya_leyla':'FreyaTTS / Leyla',
        'stt_vad':'STT / VAD','codec':'Audio / Codec',
        'asterisk_pbx':'Asterisk / PBX','a01yt_references':'A01-YT Referanslar',
        'safety_privacy':'Güvenlik / KVKK','legacy_regression':'M01–M10 Regresyon'}
    rows=[]
    for g in data['gates']:
        status=g['status'];reason=', '.join(g['checks']) or '—'
        rows.append('<tr><td>'+escape(labels.get(g['name'],g['name']))+'</td>'
                    '<td><span class="state '+escape(status.lower())+'">'+escape(status)+'</span></td>'
                    '<td>'+escape(reason)+'</td></tr>')
    html='''<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>M11 Fiziksel Kabul</title><style>
:root{color-scheme:light dark;font-family:system-ui,-apple-system,'Segoe UI',sans-serif}
body{max-width:1040px;margin:50px auto;padding:0 22px;line-height:1.55}
h1{font-size:1.7rem}p{max-width:80ch;color:gray}table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:13px 12px;border-bottom:1px solid #8886;vertical-align:top}
th{font-weight:650}.state{display:inline-block;padding:3px 9px;border-radius:7px;background:#8882;font-weight:650}
.pass{color:#157750}.fail{color:#bb3535}.hold{color:#a16b18}
.note{margin-top:24px;border-left:3px solid #8889;padding-left:15px}
</style></head><body><h1>FreyaTTS · M11 Fiziksel Kabul</h1>
<p>Kanıta dayalı laboratuvar kabulü. M01–M10 yazılım testlerinin geçmesi gerçek model, ses ve telefon kabulü değildir.</p>
<h2>Genel karar: <span class="state STATE">VERDICT</span></h2>
<table><thead><tr><th>Kabul alanı</th><th>Durum</th><th>Bulgu / eksik kanıt</th></tr></thead><tbody>ROWS</tbody></table>
<div class="note"><strong>Not:</strong> PASS olan bir kapının ham kanıtı JSON dosyasındaki SHA-256 referanslarıyla ayrıca denetlenmelidir. HOLD/FAIL durumda gerçek çağrı yayınına geçilmez. Production readiness: false.</div>
</body></html>'''
    html=html.replace('STATE',escape(data['overall'].lower())).replace('VERDICT',escape(data['overall'])).replace('ROWS',''.join(rows))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(html,encoding='utf-8')
~~~~

### automotive_voice/mock_demo.py

~~~~python
"""Deterministic state-machine demo. No WAV or external data."""
import asyncio
from automotive_voice.core.session import Session,State
from automotive_voice.adapters.fake import FakeMediaOutput, FakeTTS

async def run():
    s = Session("synthetic-session-001")
    s.move(State.LISTENING)
    gen = s.new_turn()
    s.move(State.SPEAKING)
    out = FakeMediaOutput()
    async for chunk in FakeTTS().synthesize("Yarın müsaitliği kontrol ediyorum",gen):
        if s.accepts_chunk(chunk.generation_id):
            await out.enqueue(chunk)
    before = len(out.items)
    s.interrupt()
    await out.flush()
    stale = s.accepts_chunk(gen)
    s.move(State.LISTENING)
    s.move(State.ENDED)
    print({"simulation":True,"queued_before_interrupt":before,"queue_after_flush":len(out.items),"old_generation_accepted":stale,"final_state":s.state.value})

if __name__ == '__main__':
    asyncio.run(run())
~~~~

### automotive_voice/nlp/__init__.py

~~~~python
"""M04 deterministic NLP contracts; no audio or model weights."""
from .normalizer import TurkishAutomotiveNormalizer, NormalizationResult
from .lexicon import AutomotiveLexicon, LexiconRule, LexiconError
from .nlu import DeterministicNLU, ParseContext, ParseResult
__all__ = ['TurkishAutomotiveNormalizer', 'NormalizationResult', 'AutomotiveLexicon', 'LexiconRule', 'LexiconError', 'DeterministicNLU', 'ParseContext', 'ParseResult']
from .a01yt_adapter import A01YTReadOnlyAdapter
__all__.append('A01YTReadOnlyAdapter')
from .bridge import NLUReferenceBridge, InputReference
__all__ += ['NLUReferenceBridge', 'InputReference']
~~~~

### automotive_voice/nlp/a01yt_adapter.py

~~~~python
"""Read-only A01-YT SQLite snapshot adapter; never licenses or synthesizes audio.

Only observation rows with review provenance, media-import metadata and a
source-specific permission basis are candidates. Empty v0.5 observations =>
empty lexicon. Approval is still an application review decision.
"""
from __future__ import annotations
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from .lexicon import AutomotiveLexicon, LexiconRule, LexiconError, tr_key

class A01YTReadOnlyAdapter:
    def __init__(self, sqlite_path: str | Path):
        self.path = Path(sqlite_path)
        if not self.path.is_file():
            raise FileNotFoundError(self.path)

    def load(self) -> AutomotiveLexicon:
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as cx:
            cx.row_factory = sqlite3.Row
            cx.execute('PRAGMA query_only = ON')
            rows = cx.execute('''
                SELECT a.id AS annotation_id, a.canonical, a.spoken_tr, a.context,
                       a.reviewer, a.reviewed_at, s.id AS clip_id, s.clip_sha256, s.audio_status,
                       s.transcript_final, s.transcript_reviewer,
                       so.url, so.rights_basis, so.rights_evidence,
                       so.platform_authorized, so.audio_use_authorized,
                       so.media_origin, so.permission_claim_status,
                       so.permitted_scope, so.verified_by, so.attribution
                FROM annotations a
                JOIN segments s ON s.id = a.segment_id
                JOIN sources so ON so.id = s.source_id
                WHERE a.status = 'approved'
                ORDER BY a.id
            ''').fetchall()
        by_term: dict[str, list[sqlite3.Row]] = {}
        for r in rows:
            valid = (not r['context'] and bool(r['reviewer']) and bool(r['reviewed_at'])
              and bool(r['transcript_reviewer']) and bool(r['transcript_final'])
              and r['audio_status'] == 'imported' and bool(r['clip_id']) and bool(re.fullmatch(r'[0-9a-fA-F]{64}', r['clip_sha256'] or ''))
              and bool(r['audio_use_authorized']) and bool(r['verified_by'])
              and bool(r['rights_evidence']) and bool(r['attribution'])
              and r['rights_basis'] in ('cc_by', 'written_permission', 'verbal_permission', 'owned')
              and r['permission_claim_status'] in ('user_attested', 'documented', 'verified')
              and r['permitted_scope'] in ('pronunciation_reference','tts_lexicon_reference','reference_and_training')
              and (r['media_origin'] == 'direct_from_rights_holder' or bool(r['platform_authorized'])))
            if valid:
                by_term.setdefault(tr_key(r['canonical']), []).append(r)
        rules = []
        for term, observations in sorted(by_term.items()):
            if len({tr_key(r['spoken_tr']) for r in observations}) != 1:
                # Conflicting observations must not be auto-resolved.
                continue
            first = observations[0]
            evidence = tuple({'annotation_id':r['annotation_id'], 'clip_id':r['clip_id'],
                              'source_url':r['url'], 'clip_sha256':r['clip_sha256']}
                             for r in observations)
            try:
                rules.append(LexiconRule(first['canonical'], first['spoken_tr'], True,
                    first['url'], first['reviewer'], evidence))
            except LexiconError:
                continue
        return AutomotiveLexicon(tuple(rules))
~~~~

### automotive_voice/nlp/bridge.py

~~~~python
"""M04 NLU -> unchanged M03 ReferenceStore with reference-only M02 event payloads."""
from __future__ import annotations
from dataclasses import dataclass
from automotive_voice.dialogue.storage import ReferenceStore
from .nlu import DeterministicNLU, ParseContext, ParseResult

@dataclass(frozen=True, slots=True)
class InputReference:
    ref: str
    parse: ParseResult

class NLUReferenceBridge:
    def __init__(self, parser: DeterministicNLU, store: ReferenceStore):
        self.parser, self.store = parser, store

    def resolve(self, session_id: str, transcript: str, context: ParseContext) -> InputReference:
        if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 100:
            raise ValueError('invalid session id')
        parsed = self.parser.parse(transcript, context)
        # No raw transcript is stored; to store raw text, an explicitly authorized
        # secure application port would have to be introduced separately.
        ref = self.store.put_input(session_id, parsed.dialogue_input)
        return InputReference(ref, parsed)
~~~~

### automotive_voice/nlp/lexicon.py

~~~~python
"""Evidence-gated, single-pass automotive pronunciation overlay.

A01-YT approval is required. A user permission claim is NOT a pronunciation
observation. Never synthesize foreign-name readings from spelling.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import unicodedata


class LexiconError(ValueError):
    pass


def tr_key(value: str) -> str:
    return unicodedata.normalize('NFC', value).translate(str.maketrans({'I': 'ı', 'İ': 'i'})).lower()


def _safe_reading(value: str) -> bool:
    return (bool(value.strip()) and len(value) <= 160
            and all(c.isalpha() or c in ' -' for c in value))


@dataclass(frozen=True, slots=True)
class LexiconRule:
    canonical: str
    spoken_tr: str
    approved: bool
    source_ref: str
    reviewer: str
    evidence: tuple[dict, ...] = ()
    aliases: tuple[str, ...] = ()
    suffix_map: dict[str, str] = field(default_factory=dict)
    context: str = ''

    def __post_init__(self):
        if not self.canonical.strip() or not _safe_reading(self.spoken_tr):
            raise LexiconError('invalid canonical or Turkish reading')
        if self.approved:
            if not (self.source_ref.strip() and self.reviewer.strip() and self.evidence):
                raise LexiconError('approved pronunciation must have reviewer, source and evidence')
            for evidence in self.evidence:
                if not isinstance(evidence, dict) or not all(evidence.get(k) for k in ('annotation_id', 'clip_id', 'source_url')):
                    raise LexiconError('evidence must identify source, clip and annotation')
        for suffix, replacement in self.suffix_map.items():
            if not re.fullmatch(r"['’][A-Za-zÇĞİÖŞÜçğıöşü]{1,8}", suffix):
                raise LexiconError('invalid explicit suffix key')
            if not re.fullmatch(r"[A-Za-zÇĞİÖŞÜçğıöşü]{1,10}", replacement):
                raise LexiconError('invalid explicit spoken suffix')

    def as_dict(self) -> dict:
        return {'canonical': self.canonical, 'spoken_tr': self.spoken_tr,
                'approved': self.approved, 'source_ref': self.source_ref,
                'reviewer': self.reviewer, 'evidence': list(self.evidence),
                'aliases': list(self.aliases), 'suffix_map': dict(self.suffix_map),
                'context': self.context}


@dataclass(frozen=True, slots=True)
class LexiconApplication:
    text: str
    hits: tuple[str, ...]
    review_required: tuple[str, ...]


class AutomotiveLexicon:
    def __init__(self, rules: tuple[LexiconRule, ...] = ()):
        self.rules = rules
        index: dict[str, LexiconRule] = {}
        for rule in rules:
            for alias in (rule.canonical, *rule.aliases):
                key = tr_key(alias)
                if not alias.strip() or (key in index and index[key] != rule):
                    raise LexiconError('duplicate or conflicting lexicon form')
                index[key] = rule
        self._by_name = index
        # One regex: no cascading replacement and no partial match inside model names.
        names = sorted({name for r in rules for name in (r.canonical, *r.aliases)}, key=len, reverse=True)
        self._pattern = (re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(n) for n in names) +
                                    r")(?:['’](?:[A-Za-zÇĞİÖŞÜçğıöşü]+))?(?!\w)", re.I)
                         if names else None)

    @classmethod
    def from_a01yt_export(cls, path: str | Path) -> 'AutomotiveLexicon':
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if data.get('schema_version') != 1 or not isinstance(data.get('approved_rules'), list):
            raise LexiconError('unsupported A01-YT export')
        if data.get('conflicts'):
            # Do not quietly accept a snapshot containing conflicting readings.
            raise LexiconError('source export has pronunciation conflicts')
        rules = []
        for entry in data['approved_rules']:
            if entry.get('context'):
                continue   # context-sensitive readings require a later contract
            evidences = tuple(entry.get('evidence', ()))
            source_ref = entry.get('source_ref') or (evidences[0].get('source_url') if evidences else '')
            reviewer = entry.get('reviewer') or entry.get('reviewed_by') or ''
            # v0.5's exports do not carry reviewer. Do not fabricate approval.
            if not reviewer:
                raise LexiconError('approved export is missing reviewer provenance')
            rules.append(LexiconRule(canonical=entry['canonical'], spoken_tr=entry['spoken_tr'],
                                     approved=True, source_ref=source_ref, reviewer=reviewer,
                                     evidence=evidences, aliases=tuple(entry.get('aliases', ())),
                                     suffix_map=dict(entry.get('suffix_map', {}))))
        return cls(tuple(rules))

    def apply(self, text: str) -> LexiconApplication:
        if self._pattern is None:
            return LexiconApplication(text, (), ())
        hits: list[str] = []
        reviews: list[str] = []
        def replace(match: re.Match) -> str:
            literal = match.group()
            base = re.split("['’]", literal, maxsplit=1)[0]
            rule = self._by_name.get(tr_key(base))
            if rule is None:  # re.I may match Turkish I in a non-Turkish way
                return literal
            if not rule.approved or rule.context:
                reviews.append('unapproved:' + rule.canonical)
                return literal
            suffix = literal[len(base):]
            if suffix:
                mapping = rule.suffix_map.get(suffix) or rule.suffix_map.get(suffix.replace('’', "'"))
                if mapping is None:
                    reviews.append('suffix_requires_review:' + literal)
                    return literal
                replacement = rule.spoken_tr + mapping
            else:
                replacement = rule.spoken_tr
            hits.append(rule.canonical)
            return replacement
        result = self._pattern.sub(replace, text)
        return LexiconApplication(result, tuple(hits), tuple(dict.fromkeys(reviews)))

    def approved_export(self) -> dict:
        return {'schema_version': 1, 'rules': [r.as_dict() for r in self.rules if r.approved]}
~~~~

### automotive_voice/nlp/nlu.py

~~~~python
"""Conservative, deterministic NLU -> unchanged M03 DialogueInput API.

No LLM, no guessed vehicle identity, no implied booking confirmation, and no
implicit timezone or location. Transcripts stay outside event/audit payloads.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta, timezone
import re
import unicodedata
from automotive_voice.dialogue.models import AppointmentSlot, CaseKind, DialogueInput, Intent
from .lexicon import tr_key

DATE_ISO = re.compile(r'(?<!\d)(?P<y>20\d{2})-(?P<m>\d{2})-(?P<d>\d{2})(?!\d)')
DATE_TR = re.compile(r'(?<!\d)(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>20\d{2})(?!\d)')
TIME = re.compile(r'(?<!\d)(?:saat\s+)?(?P<h>\d{1,2}):(?P<m>\d{2})(?!\d)', re.I)


@dataclass(frozen=True, slots=True)
class ParseContext:
    """All IDs originate from trusted app state, never generated from ASR text."""
    vehicle_aliases: dict[str, str] = field(default_factory=dict)
    location_aliases: dict[str, str] = field(default_factory=dict)
    as_of: datetime | None = None  # aware clock with authoritative customer timezone offset
    timezone_offset_minutes: int | None = None  # required for absolute-date slot without as_of
    awaiting_confirmation: bool = False

    def __post_init__(self):
        if self.as_of is not None and (self.as_of.tzinfo is None or self.as_of.utcoffset() is None):
            raise ValueError('as_of must be timezone-aware')
        if self.timezone_offset_minutes is not None and not -720 <= self.timezone_offset_minutes <= 840:
            raise ValueError('invalid UTC offset')
        if self.as_of is not None and self.timezone_offset_minutes is not None:
            if self.as_of.utcoffset() != timedelta(minutes=self.timezone_offset_minutes):
                raise ValueError('conflicting as_of timezone and explicit timezone offset')
        for mapping in (self.vehicle_aliases, self.location_aliases):
            if any(not isinstance(k, str) or not isinstance(v, str) for k, v in mapping.items()):
                raise ValueError('alias mapping must contain strings')


@dataclass(frozen=True, slots=True)
class ParseResult:
    dialogue_input: DialogueInput
    matched_rules: tuple[str, ...]
    warnings: tuple[str, ...]
    requires_clarification: bool
    # No raw ASR, customer names, phone numbers or verbatim transcript in this result.

    def safe_diagnostics(self) -> dict:
        return {'intent': self.dialogue_input.intent.value,
                'has_vehicle_id': self.dialogue_input.vehicle_id is not None,
                'has_slot': self.dialogue_input.slot is not None,
                'matched_rules': list(self.matched_rules),
                'warning_codes': list(self.warnings),
                'requires_clarification': self.requires_clarification}


class DeterministicNLU:
    _patterns = (
        (Intent.HANDOFF, (r'\btemsilci(?:ye|yi|yle|nin|den)?\b', r'\binsanla\s+görüş', r'\bmüşteri\s+hizmetleri\b')),
        (Intent.RECHECK_BOOKING, (r'\brandevum\s+ne\s+oldu\b', r'\brandevu\s+durumu\b')),
        (Intent.CREATE_CRM_CASE, (r'\bgeri\s+ara', r'\btalep\s+kayd[ıi]\b')),
        (Intent.REQUEST_INSPECTION, (r'\bekspertiz\b', r'\brandevu\s+(?:al|oluştur|ist)')),
        (Intent.PRICE_LOOKUP, (r'\bfiyat(?:ı|i|lar|ları)?\b', r'\bdeğer\b', r'\bteklif\b')),
        (Intent.VEHICLE_LOOKUP, (r'\baraç\s+bilgi', r'\bmodel\s+bilgi', r'\bhangi\s+araç\b')),
    )

    def parse(self, transcript: str, context: ParseContext) -> ParseResult:
        if not isinstance(transcript, str) or not transcript.strip():
            raise ValueError('non-empty ASR text expected')
        if not isinstance(context, ParseContext):
            raise TypeError('typed context required')
        if len(transcript) > 2000:
            raise ValueError('transcript too long')
        text = tr_key(unicodedata.normalize('NFC', transcript)).replace('’', "'")
        warnings: list[str] = []
        matches = []
        if re.search(r'\b(?:vazgeçtim|iptal\s+et|istemiyorum)\b', text):
            matches.append(Intent.DECLINE)
        for intent, patterns in self._patterns:
            if any(re.search(p, text) for p in patterns):
                matches.append(intent)
        # A handoff is explicit and should win even when the request mentions pricing.
        if Intent.HANDOFF in matches:
            intent = Intent.HANDOFF
        elif len(set(matches)) > 1:
            intent = Intent.UNKNOWN
            warnings.append('multi_intent_requires_clarification')
        elif matches:
            intent = matches[0]
        elif context.awaiting_confirmation and re.fullmatch(r'\s*(?:evet|onaylıyorum|onaylıyorum\s+evet|tamam\s+onaylıyorum)[.!?\s]*', text):
            intent = Intent.CONFIRM
        elif context.awaiting_confirmation and re.fullmatch(r'\s*(?:hayır|istemiyorum|vazgeçtim)[.!?\s]*', text):
            intent = Intent.DECLINE
        elif re.fullmatch(r'\s*(?:merhaba|selam|iyi\s+günler)[.!?\s]*', text):
            intent = Intent.GREETING
        else:
            intent = Intent.UNKNOWN
            warnings.append('intent_not_resolved')

        vehicle_id = None
        location_id = None
        if intent in (Intent.PRICE_LOOKUP, Intent.VEHICLE_LOOKUP, Intent.REQUEST_INSPECTION, Intent.CREATE_CRM_CASE):
            vehicles = [value for name, value in context.vehicle_aliases.items()
                        if re.search(r'(?<!\w)' + re.escape(tr_key(name)) + r'(?!\w)', text)]
            if len(set(vehicles)) == 1:
                vehicle_id = vehicles[0]
            elif len(set(vehicles)) > 1:
                warnings.append('ambiguous_vehicle')
            else:
                warnings.append('vehicle_not_resolved')
            places = [value for name, value in context.location_aliases.items()
                      if re.search(r'(?<!\w)' + re.escape(tr_key(name)) + r'(?!\w)', text)]
            if len(set(places)) == 1:
                location_id = places[0]
            elif len(set(places)) > 1:
                warnings.append('ambiguous_location')

        slot = None
        if intent == Intent.REQUEST_INSPECTION:
            day = None
            found_dates = list(DATE_ISO.finditer(text)) + list(DATE_TR.finditer(text))
            m_iso = next((m for m in found_dates if m.re is DATE_ISO), None)
            m_tr = next((m for m in found_dates if m.re is DATE_TR), None)
            if len(found_dates) > 1 or (found_dates and re.search(r'\byarın\b', text)):
                warnings.append('ambiguous_date')
            elif m_iso or m_tr:
                m = m_iso or m_tr
                try:
                    day = date(int(m['y']), int(m['m']), int(m['d']))
                except ValueError:
                    warnings.append('invalid_date')
            elif re.search(r'\byarın\b', text):
                if context.as_of is None:
                    warnings.append('relative_date_without_anchor')
                else:
                    day = context.as_of.date() + timedelta(days=1)
            else:
                warnings.append('date_missing')
            clocks = list(TIME.finditer(text))
            clock = clocks[0] if len(clocks) == 1 else None
            if len(clocks) > 1:
                warnings.append('ambiguous_time')
            elif clock is None:
                warnings.append('time_missing')
            else:
                hh, mm = int(clock['h']), int(clock['m'])
                if hh > 23 or mm > 59:
                    warnings.append('invalid_time')
            if location_id is None:
                warnings.append('location_not_resolved')
            offset = (context.as_of.utcoffset() if context.as_of is not None else
                      timedelta(minutes=context.timezone_offset_minutes) if context.timezone_offset_minutes is not None else None)
            if offset is None:
                warnings.append('timezone_not_resolved')
            if day is not None and clock is not None and hh <= 23 and mm <= 59 and offset is not None and location_id:
                tz = timezone(offset)
                stamp = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz).isoformat()
                try:
                    slot = AppointmentSlot(start_at=stamp, location_id=location_id)
                except ValueError:
                    warnings.append('invalid_slot')

        case_kind = None
        if intent == Intent.CREATE_CRM_CASE:
            if re.search(r'\bgeri\s+ara', text):
                case_kind = CaseKind.CALLBACK
            elif re.search(r'\bfiyat(?:ı|i|lar|ları)?\b', text):
                case_kind = CaseKind.PRICE_REQUEST
            else:
                case_kind = CaseKind.EXPERTISE_INFO
        # Avoid passing a vehicle id for intents that do not use it.
        dto = DialogueInput(intent=intent, vehicle_id=vehicle_id, slot=slot, case_kind=case_kind)
        if intent == Intent.CONFIRM and not context.awaiting_confirmation:
            raise AssertionError('confirmation context invariant')
        return ParseResult(dto, tuple(dict.fromkeys(i.value for i in matches)),
                           tuple(dict.fromkeys(warnings)),
                           bool(warnings) or (intent == Intent.REQUEST_INSPECTION and (slot is None or vehicle_id is None)))
~~~~

### automotive_voice/nlp/normalizer.py

~~~~python
"""Conservative Turkish TTS normalizer (no audio, no guessed pronunciation).

Spoken output is separate from display text. No unreviewed lexicon candidate
can replace a brand. Ambiguous or invalid numeric tokens remain visible and
are flagged, not silently coerced.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import json
import re
import unicodedata
from .lexicon import AutomotiveLexicon

ONES = ('', 'bir', 'iki', 'üç', 'dört', 'beş', 'altı', 'yedi', 'sekiz', 'dokuz')
TENS = ('', 'on', 'yirmi', 'otuz', 'kırk', 'elli', 'altmış', 'yetmiş', 'seksen', 'doksan')
SCALES = ('', 'bin', 'milyon', 'milyar', 'trilyon')
MONTHS = ('', 'ocak', 'şubat', 'mart', 'nisan', 'mayıs', 'haziran',
          'temmuz', 'ağustos', 'eylül', 'ekim', 'kasım', 'aralık')
# All boundaries explicitly exclude partial alphanumeric model, VIN or telephone matches.
PRICE = re.compile(r'(?<![\w.,])(?P<val>(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?)\s*(?P<currency>TL|TRY|₺|Türk\s+lirası)(?!\w)', re.I)
DATE_ISO = re.compile(r'(?<![\w\d])(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?![\w\d])')
DATE_TR = re.compile(r'(?<![\w\d])(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{4})(?![\w\d])')
CLOCK = re.compile(r"(?<![\w\d])(?P<h>\d{1,2}):(?P<m>\d{2})(?P<suffix>['’](?:da|de|ta|te|a|e))?(?![\w\d])", re.I)
ENGINE = re.compile(r'(?<!\w)(?P<major>\d)[,.](?P<minor>\d)\s*(?P<unit>TSI|TDI|TFSI|TCe|dCi|CDI|HDI)(?!\w)', re.I)
KM = re.compile(r'(?<![\w\d])(?P<val>\d{1,3}(?:\.\d{3})+|\d+)\s*(?:km|kilometre)(?!\w)', re.I)
YEAR_MODEL = re.compile(r'(?<!\w)(?P<year>(?:19|20)\d{2})\s+model(?!\w)', re.I)
INVALID_DATELIKE = re.compile(r'(?<!\w)\d{1,2}/\d{1,2}/\d{4}(?!\w)')
DANGLING_DECIMAL = re.compile(r'(?<!\w)\d+(?:,\d{3,}|\.\d{1,2})(?![\d\w])')
# Standalone integers only. Do not rewrite identifiers, ranges, phone numbers,
# dates or units. Freya native may handle remaining forms later.
SINGLE_INTEGER = re.compile(r'(?<![\w\d.,:/+-])(?P<num>\d{1,15})(?![\w\d.,:/+-])')
WEIRD_CONTROL = {'\u200b', '\u200c', '\u200d', '\u202a', '\u202b', '\u202d', '\u202e', '\u2066', '\u2067', '\u2068', '\u2069'}


def int_to_tr(value: int) -> str:
    if type(value) is not int or not 0 <= value < 10**15:
        raise ValueError('number out of supported range')
    if value == 0:
        return 'sıfır'
    groups = []
    while value:
        groups.append(value % 1000)
        value //= 1000
    output = []
    for index in reversed(range(len(groups))):
        n = groups[index]
        if not n:
            continue
        words = []
        h, tens, unit = n // 100, n % 100 // 10, n % 10
        if h:
            if h > 1:
                words.append(ONES[h])
            words.append('yüz')
        if tens:
            words.append(TENS[tens])
        if unit:
            words.append(ONES[unit])
        if index == 1 and n == 1:
            words.clear()
        output.extend(words)
        if index:
            output.append(SCALES[index])
    return ' '.join(output)


def clock_locative(spoken: str) -> str:
    ending = spoken[-1]
    vowel = next((c for c in reversed(spoken) if c in 'aeıioöuü'), 'a')
    return ('t' if ending in 'fstkçşhp' else 'd') + ('a' if vowel in 'aıou' else 'e')


def clock_dative(spoken: str) -> str:
    ending = spoken[-1]
    vowel = next((c for c in reversed(spoken) if c in 'aeıioöuü'), 'a')
    return ('y' if ending in 'aeıioöuü' else '') + ('a' if vowel in 'aıou' else 'e')


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    display_text: str
    spoken_text: str
    rules_applied: tuple[str, ...]
    warnings: tuple[str, ...]
    unsupported_chars: tuple[str, ...]
    review_required: bool
    # Do not send display_text/spoken_text to telemetry or event envelopes.

    def as_dict(self) -> dict:
        return {'display_text': self.display_text, 'spoken_text': self.spoken_text,
                'rules_applied': list(self.rules_applied), 'warnings': list(self.warnings),
                'unsupported_chars': list(self.unsupported_chars), 'review_required': self.review_required}


class TurkishAutomotiveNormalizer:
    def __init__(self, lexicon: AutomotiveLexicon | None = None, vocab_path: str | Path | None = None):
        self.lexicon = lexicon or AutomotiveLexicon()
        self.vocab = set(json.loads(Path(vocab_path).read_text(encoding='utf-8'))) if vocab_path else None

    def normalize(self, text: str, *, strict: bool = False) -> NormalizationResult:
        if not isinstance(text, str) or not text.strip():
            raise ValueError('nonempty text required')
        if len(text) > 5000:
            raise ValueError('text too long')
        display = unicodedata.normalize('NFC', text)
        warnings: list[str] = []
        rules: list[str] = []
        if any(c in WEIRD_CONTROL or (unicodedata.category(c) == 'Cc' and c not in '\n\t') for c in display):
            warnings.append('unsafe_control_characters')
        spoken = display

        def substitute(pattern, name, fn):
            nonlocal spoken
            def wrap(match):
                replacement = fn(match)
                if replacement != match.group():
                    rules.append(name)
                return replacement
            spoken = pattern.sub(wrap, spoken)

        def read_date(m):
            try:
                d = date(int(m['y']), int(m['m']), int(m['d']))
            except ValueError:
                warnings.append('invalid_date')
                return m.group()
            return f'{int_to_tr(d.day)} {MONTHS[d.month]} {int_to_tr(d.year)}'
        substitute(DATE_ISO, 'date_iso', read_date)
        substitute(DATE_TR, 'date_tr', read_date)
        if INVALID_DATELIKE.search(spoken):
            warnings.append('ambiguous_date_separator')

        def read_price(m):
            raw = m['val']
            integer, _, decimal = raw.partition(',')
            try:
                amount = int(integer.replace('.', ''))
                whole = int_to_tr(amount)
            except ValueError:
                warnings.append('price_out_of_range')
                return m.group()
            result = whole + ' Türk lirası'
            if decimal and int(decimal):
                result += ' ve ' + int_to_tr(int(decimal.ljust(2, '0'))) + ' kuruş'
            return result
        substitute(PRICE, 'currency', read_price)

        def read_clock(m):
            hour, minute = int(m['h']), int(m['m'])
            if hour > 23 or minute > 59:
                warnings.append('invalid_time')
                return m.group()
            spoken_clock = int_to_tr(hour) + (' ' + int_to_tr(minute) if minute else '')
            if m['suffix']:
                suffix = m['suffix'].lstrip("'’").lower()
                spoken_clock += clock_locative(spoken_clock) if suffix in ('da', 'de', 'ta', 'te') else clock_dative(spoken_clock)
            return spoken_clock
        substitute(CLOCK, 'clock', read_clock)

        def read_engine(m):
            return f"{int_to_tr(int(m['major']))} nokta {int_to_tr(int(m['minor']))} {m['unit']}"
        substitute(ENGINE, 'engine', read_engine)
        def read_km(m):
            try:
                return int_to_tr(int(m['val'].replace('.', ''))) + ' kilometre'
            except ValueError:
                warnings.append('distance_out_of_range')
                return m.group()
        substitute(KM, 'distance', read_km)
        substitute(YEAR_MODEL, 'model_year', lambda m: int_to_tr(int(m['year'])) + ' model')

        lex = self.lexicon.apply(spoken)
        spoken = lex.text
        if lex.hits:
            rules.extend('lexicon:' + term for term in lex.hits)
        warnings.extend(lex.review_required)

        # Only safe presentation punctuation. Never transliterate names here.
        spoken = spoken.replace('!', '.').replace('…', ',').replace('—', ',').replace('–', '-')
        spoken = re.sub(r'\s+', ' ', spoken).strip()
        if DANGLING_DECIMAL.search(spoken):
            warnings.append('ambiguous_numeric_notation')
        if any(c.isdigit() for c in spoken):
            warnings.append('unexpanded_numeric_token')
        unsupported = tuple(sorted(set(ch for ch in spoken if ch not in self.vocab))) if self.vocab is not None else ()
        if unsupported:
            warnings.append('unsupported_freya_characters')
        warnings = list(dict.fromkeys(warnings))
        review = bool(warnings)
        if strict and review:
            raise ValueError('normalization requires review: ' + ','.join(warnings))
        return NormalizationResult(display, spoken, tuple(rules), tuple(warnings), unsupported, review)
~~~~

### automotive_voice/operator/__init__.py

~~~~python
"""M08 offline-first, loopback-only operator console. All outputs are synthetic."""
~~~~

### automotive_voice/operator/__main__.py

~~~~python
"""Launch M08 offline operator UI: python -m automotive_voice.operator."""
from __future__ import annotations
import argparse
from pathlib import Path
from .runtime import ConsoleRuntime
from .server import ConsoleHTTP

def main():
    parser=argparse.ArgumentParser(description='Freya M08 offline MOCK operator console')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--instance',default=None,help='Writable local review/audit overlay directory')
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[2]
    data=project/'data'
    instance=Path(args.instance).resolve() if args.instance else project/'var'
    app=ConsoleHTTP(ConsoleRuntime(data,instance/'m08_reviews.sqlite3'),port=args.port)
    print(f'Freya M08 MOCK-ONLY local console: http://127.0.0.1:{app.port}',flush=True)
    print('No audio, SIP, external network, model or real booking services.',flush=True)
    try:app.serve_forever()
    except KeyboardInterrupt:app.shutdown()

if __name__=='__main__':main()
~~~~

### automotive_voice/operator/review_store.py

~~~~python
"""A01-YT read-only source adapter + local operator audit overlay.

No modification of the A01-YT database. Approvals require physically accessible,
checksum-verified recorded audio plus finalized human transcription and license scope.
The overlay does not promote rules into Freya's approved production lexicon.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import sqlite3
from contextlib import contextmanager, closing
import wave
from datetime import datetime, timezone
from uuid import uuid4

class ReviewError(ValueError):
    pass

class PronunciationReviewStore:
    def __init__(self, source_db: str | Path, overlay_db: str | Path):
        self.source_db=Path(source_db).resolve(strict=True)
        self.overlay_db=Path(overlay_db).resolve()
        self.overlay_db.parent.mkdir(parents=True,exist_ok=True)
        with self._overlay() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS operator_review (
              id TEXT PRIMARY KEY, annotation_id TEXT NOT NULL, decision TEXT NOT NULL
              CHECK(decision IN ('approved','rejected')), reviewer TEXT NOT NULL,
              reason_code TEXT NOT NULL, source_sha256 TEXT, reviewed_at TEXT NOT NULL)''')
            conn.execute('CREATE INDEX IF NOT EXISTS operator_review_by_annotation ON operator_review(annotation_id,reviewed_at)')

    @contextmanager
    def _source(self):
        with closing(sqlite3.connect(f'file:{self.source_db.as_posix()}?mode=ro',uri=True)) as conn:
            conn.row_factory=sqlite3.Row
            yield conn

    @contextmanager
    def _overlay(self):
        with closing(sqlite3.connect(self.overlay_db)) as conn:
            conn.row_factory=sqlite3.Row
            with conn:
                yield conn

    def sources(self):
        with self._source() as conn:
            data=conn.execute('''SELECT id,title,creator,url,rights_basis,permission_claim_status,
              permitted_scope,audio_use_authorized FROM sources ORDER BY id''').fetchall()
        return [dict(x) for x in data]

    def items(self):
        with self._source() as conn:
            data=conn.execute('''SELECT a.id,a.canonical,a.spoken_tr,a.status,a.reviewer,a.kind,
                  s.id AS segment_id,s.source_id,s.start_sec,s.end_sec,s.audio_status,
                  s.clip_sha256,s.clip_path,s.transcript_final,s.transcript_reviewer,
                  p.permitted_scope,p.audio_use_authorized,p.title
                  FROM annotations a JOIN segments s ON s.id=a.segment_id
                  JOIN sources p ON p.id=s.source_id ORDER BY p.id,s.start_sec,a.id LIMIT 200''').fetchall()
        with self._overlay() as conn:
            reviews=conn.execute('''SELECT annotation_id,decision,reviewer,reason_code,reviewed_at
                  FROM operator_review ORDER BY reviewed_at,id''').fetchall()
        latest={x['annotation_id']:dict(x) for x in reviews}
        out=[]
        for item in data:
            entry=dict(item)
            # Clip paths never leave backend; do not leak transcript text or arbitrary file paths.
            entry.pop('clip_path')
            entry.pop('transcript_final')
            entry['transcript_checked']=bool(item['transcript_final'] and item['transcript_reviewer'])
            entry['has_clip_reference']=bool(item['clip_path'] and item['clip_sha256'])
            entry['review']=latest.get(item['id'])
            out.append(entry)
        return out

    def _evidence(self, annotation_id: str):
        with self._source() as conn:
            item=conn.execute('''SELECT a.id,a.canonical,a.spoken_tr,
                s.clip_path,s.clip_sha256,s.transcript_final,s.transcript_reviewer,
                p.audio_use_authorized,p.permitted_scope
                FROM annotations a JOIN segments s ON s.id=a.segment_id
                JOIN sources p ON p.id=s.source_id WHERE a.id=?''',(annotation_id,)).fetchone()
        if item is None: raise ReviewError('unknown_annotation')
        if not item['audio_use_authorized'] or 'pronunciation' not in (item['permitted_scope'] or '').lower():
            raise ReviewError('source_permission_scope_not_accepted')
        if not item['transcript_final'] or not item['transcript_reviewer']:
            raise ReviewError('human_transcript_required')
        if not item['canonical'] or not item['spoken_tr']:
            raise ReviewError('pronunciation_required')
        rel=item['clip_path']
        if not rel or not item['clip_sha256']:raise ReviewError('audio_evidence_required')
        p=Path(rel)
        # Refuse absolute paths, traversal and symlinks to files outside the approved source directory.
        if p.is_absolute(): raise ReviewError('source_path_outside_evidence_root')
        base=self.source_db.parent
        try:full=(base/p).resolve(strict=True)
        except (OSError,ValueError):raise ReviewError('audio_evidence_missing')
        if not full.is_relative_to(base):raise ReviewError('source_path_outside_evidence_root')
        if not full.is_file() or full.stat().st_size>50_000_000:raise ReviewError('audio_evidence_invalid')
        with full.open('rb') as stream:
            digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest.lower()!=item['clip_sha256'].lower():raise ReviewError('audio_evidence_checksum_mismatch')
        if full.suffix.lower()!='.wav':raise ReviewError('decoded_wav_required')
        try:
            with wave.open(str(full),'rb') as wav:
                if wav.getcomptype()!='NONE' or wav.getsampwidth()!=2 or wav.getnchannels()!=1 or wav.getframerate() not in (8000,16000,48000) or wav.getnframes()<160:
                    raise ReviewError('invalid_pcm_audio_evidence')
        except (wave.Error,EOFError, OSError) as exc:
            raise ReviewError('invalid_pcm_audio_evidence') from exc
        return digest

    def decide(self, annotation_id: str, decision: str, *, reviewer: str, reason_code: str) -> dict:
        if not isinstance(annotation_id,str) or len(annotation_id)>128 or not annotation_id.isascii():
            raise ReviewError('invalid_annotation_id')
        if decision not in ('approved','rejected'):raise ReviewError('invalid_decision')
        if not isinstance(reviewer,str) or not 1<=len(reviewer)<=48 or not reviewer.isascii() or not reviewer.replace('_','').replace('-','').isalnum():
            raise ReviewError('invalid_reviewer')
        if reason_code not in ('verified_evidence','incorrect_reading','insufficient_evidence','duplicate','other'):
            raise ReviewError('invalid_reason_code')
        if decision=='approved':
            if reason_code!='verified_evidence':raise ReviewError('approval_requires_verified_evidence')
            digest=self._evidence(annotation_id)
        else:
            with self._source() as conn:
                exists=conn.execute('SELECT 1 FROM annotations WHERE id=?',(annotation_id,)).fetchone()
            if not exists:raise ReviewError('unknown_annotation')
            digest=None
        record={'id':str(uuid4()),'annotation_id':annotation_id,'decision':decision,
                'reviewer':reviewer,'reason_code':reason_code,'source_sha256':digest,
                'reviewed_at':datetime.now(timezone.utc).isoformat()}
        with self._overlay() as conn:
            conn.execute('''INSERT INTO operator_review
                (id,annotation_id,decision,reviewer,reason_code,source_sha256,reviewed_at)
                VALUES (:id,:annotation_id,:decision,:reviewer,:reason_code,:source_sha256,:reviewed_at)''',record)
        return record
~~~~

### automotive_voice/operator/runtime.py

~~~~python
"""M08 read-model and operator actions wired into genuine M01-M07 mock contracts.

Only fake adapters, opaque references, and synthetic control. No microphone, model,
phone, audio payload, SIP, external network or real customer data.
"""
from __future__ import annotations
import asyncio
import csv
import json
from collections import deque
from pathlib import Path
from uuid import uuid4
from automotive_voice.core.event_bus import EventBus
from automotive_voice.core.session_manager import SessionManager
from automotive_voice.conversation.reducer import ConversationReducer, Decision
from automotive_voice.conversation.signals import ConversationSignal, SignalKind
from automotive_voice.audio.queue import MediaBuffer
from automotive_voice.audio.coordinator import MediaCoordinator
from automotive_voice.telephony.transport import FakeTransport
from automotive_voice.adapters.lifecycle.clock import MockClock
from automotive_voice.adapters.lifecycle.supervisor import AdapterSupervisor
from .review_store import PronunciationReviewStore
from automotive_voice.readiness.contracts import AdapterConfig,AdapterType,OfflineReadiness
from automotive_voice.e2e import ScenarioRunner, SCENARIOS

ACTIONS={
    'open': SignalKind.SESSION_OPENED,
    'vad': SignalKind.VAD_SPEECH_STARTED,
    'transcript': SignalKind.TRANSCRIPT_FINAL,
    'llm': SignalKind.LLM_RESPONSE_READY,
    'playout': SignalKind.PLAYOUT_FINISHED,
    'hangup': SignalKind.HANGUP,
    'handoff': SignalKind.HANDOFF_REQUESTED,
}

class ConsoleRuntime:
    def __init__(self, data_root: str | Path, overlay_path: str | Path):
        root=Path(data_root)
        self.review=PronunciationReviewStore(root/'a01yt'/'a01yt_v05_readonly.sqlite3',overlay_path)
        self.golden_summary=json.loads((root/'reports'/'m04_320_summary.json').read_text(encoding='utf-8'))
        with (root/'reports'/'m04_320_compare.csv').open(encoding='utf-8-sig',newline='') as stream:
            self.golden_cases=list(csv.DictReader(stream))
        self.clock=MockClock()
        self.manager=SessionManager(EventBus())
        self.reducer=ConversationReducer(self.manager)
        self.buffer=MediaBuffer(self.manager)
        self.transport=FakeTransport(adapter_id='m08-test-only-fake-pbx')
        self.media=MediaCoordinator(self.reducer,self.buffer,self.transport)
        self.supervisor=AdapterSupervisor(self.manager,self.clock,media=self.media)
        self.sessions:list[str]=[]
        self.activities=deque(maxlen=160)
        self._lock=asyncio.Lock()
        self._ready=False
        self._reference_index=0
        self.scenario_reports=deque(maxlen=12)

    async def initialize(self):
        async with self._lock:
            if not self._ready:
                await self.supervisor.start_all()
                self._ready=True

    def _activity(self,category,session,decision,reason):
        self.activities.appendleft({'clock_ms':self.clock.now_ns()//1_000_000,
                 'kind':category,'session':session,'decision':decision,'reason':reason})

    async def _signal(self,kind:SignalKind,sid:str):
        snap=await self.reducer.try_snapshot(sid)
        if kind is SignalKind.SESSION_OPENED:
            turn=generation=seq=0
        else:
            if snap is None:raise ValueError('unknown_session')
            turn=int(snap.turn_id);generation=int(snap.generation_id)
            seq=await self.reducer.expected_sequence(sid)
        reference=None
        if kind in (SignalKind.TRANSCRIPT_FINAL,SignalKind.LLM_RESPONSE_READY):
            self._reference_index+=1
            reference=f'm08_synthetic_ref_{self._reference_index:05d}'
        self.clock.advance(1_000_000)
        signal=ConversationSignal.create(kind,sid,turn,generation,seq,
                    reference=reference,mono_ns=self.clock.now_ns())
        outcome=await self.reducer.handle(signal)
        self._activity(kind.value,sid,outcome.decision.value,outcome.reason)
        accepted_all=True
        for eff in outcome.effects:
            receipt=await self.supervisor.dispatch_effect(eff)
            accepted_all=accepted_all and receipt.accepted
            self._activity('effect:'+eff.kind.value,sid,
                      'accepted' if receipt.accepted else 'rejected',receipt.reason)
        # Effects are handed to the supervisor, but not durably committed. Drain the
        # volatile M02 hand-off queue only after successful mock dispatch, per effect.
        if outcome.effects and accepted_all:
            # Explicitly avoid counting a delivery to a real transport.
            await self.reducer.drain_effects(sid,len(outcome.effects))
        return {'decision':outcome.decision.value,'reason':outcome.reason,
                'state':outcome.state.value if outcome.state else None}

    async def act(self,action:str,sid:str|None=None,**kwargs):
        async with self._lock:
            if action=='open':
                sid='sim-'+uuid4().hex[:12]
                result=await self._signal(SignalKind.SESSION_OPENED,sid)
                if result['decision']==Decision.APPLIED.value:self.sessions.insert(0,sid)
                return {'session_id':sid,**result}
            if action=='tick':
                delta=kwargs.get('delta_ms',20)
                if type(delta) is not int or delta not in (20,100,1600):
                    raise ValueError('invalid_tick_delta')
                self.clock.advance(delta*1_000_000)
                ticks=await self.supervisor.tick_all()
                count=sum(len(v) for v in ticks.values())
                expired=await self.reducer.poll_flush_timeouts(self.clock.now_ns())
                for item_sid,out in expired.items():
                    self._activity('flush_timeout',item_sid,out.decision.value,out.reason)
                    for eff in out.effects:
                        receipt=await self.supervisor.dispatch_effect(eff)
                        self._activity('effect:'+eff.kind.value,item_sid,'accepted' if receipt.accepted else 'rejected',receipt.reason)
                self._activity('clock_advance','-', 'ok',f'{delta}ms; {count} mock results')
                return {'advanced_ms':delta,'results':count,'flush_timeouts':len(expired)}
            if action=='run_scenario':
                name=kwargs.get('scenario')
                if type(name) is not str or name not in SCENARIOS:
                    raise ValueError('unknown_scenario')
                report=(await ScenarioRunner().run(name)).to_dict()
                self.scenario_reports.appendleft(report)
                self._activity('M09 scenario','-', 'passed' if report['passed'] else 'failed',name)
                return {'scenario':name,'passed':report['passed'],'checks':report['checks']}
            if action=='review':
                result=self.review.decide(kwargs.get('annotation_id',''),
                    kwargs.get('decision',''),reviewer=kwargs.get('reviewer',''),
                    reason_code=kwargs.get('reason_code',''))
                self._activity('review','-',result['decision'],result['annotation_id'])
                return {'annotation_id':result['annotation_id'],'decision':result['decision']}
            if sid not in self.sessions:raise ValueError('unknown_console_session')
            if action=='fake_ack':
                pending=await self.reducer.pending_flush_id(sid)
                if not pending:raise ValueError('no_pending_flush')
                # Explicit confirmation by M06 fake transport is the only valid path.
                ack=await self.transport.confirm_flush(sid,pending)
                if ack is None:raise ValueError('fake_adapter_did_not_confirm')
                self.clock.advance(1_000_000)
                outcome=await self.media.accept_fake_ack(ack,sequence=await self.reducer.expected_sequence(sid),mono_ns=self.clock.now_ns())
                self._activity('FAKE_ACK_only',sid,outcome.decision.value,outcome.reason)
                for eff in outcome.effects:
                    receipt=await self.supervisor.dispatch_effect(eff)
                    self._activity('effect:'+eff.kind.value,sid,'accepted' if receipt.accepted else 'rejected',receipt.reason)
                if outcome.effects: await self.reducer.drain_effects(sid,len(outcome.effects))
                return {'decision':outcome.decision.value,'reason':outcome.reason,
                        'real_pbx_proven':False,'state':outcome.state.value}
            if action in ('xoff','xon'):
                (self.transport.xoff if action=='xoff' else self.transport.xon)(sid)
                self._activity('transport_'+action,sid,'applied','fake_transport_only')
                return {'decision':'applied','reason':'fake_transport_only'}
            kind=ACTIONS.get(action)
            if kind is None or kind is SignalKind.SESSION_OPENED:raise ValueError('unsupported_action')
            return await self._signal(kind,sid)

    async def snapshot(self):
        async with self._lock:
            sessions=[]
            for sid in self.sessions[:50]:
                snap=await self.reducer.try_snapshot(sid)
                if snap is None:continue
                audit=await self.reducer.audit_records(sid)
                m=await self.buffer.metrics(sid)
                t=self.transport.stats(sid)
                sessions.append({'session_id':sid,'state':snap.state.value,
                      'turn_id':int(snap.turn_id),'generation_id':int(snap.generation_id),
                      'last_sequence':snap.last_sequence,'pending_events':snap.pending_events,
                      'pending_flush_id':await self.reducer.pending_flush_id(sid),
                      'queued_chunks':m.pending_chunks,'queued_ms':m.pending_ms,
                      'transport_queued':t.queued_at_transport,'transport_paused':t.paused,
                      'audit_count':len(audit)})
            counts={'sessions':len(self.sessions),'active':sum(s['state'] not in ('ENDED','FAILED') for s in sessions),
                'waiting_flush':sum(bool(s['pending_flush_id']) for s in sessions),
                'mock_tts_results':sum(h.completed for h in self.supervisor.health().values())}
            return {'mode':'OFFLINE MOCK ONLY','simulation_time_ms':self.clock.now_ns()//1_000_000,
                 'counts':counts,'sessions':sessions,
                 'scenario_catalog':list(SCENARIOS),'scenario_reports':list(self.scenario_reports),
                 'adapters':[x.safe_metadata() for x in self.supervisor.health().values()],
                 'timeline':list(self.activities),'golden_summary':self.golden_summary,
                 'golden_cases':self.golden_cases,'sources':self.review.sources(),
                 'annotations':self.review.items(),
                 'audio_bytes_generated':0,'real_pbx_connected':False,
                 'production_ready':False,
                 'm10_readiness':OfflineReadiness.evaluate([
                     AdapterConfig(AdapterType.FREYA,'freyatts-local',model_path=str(Path.cwd()/'models'/'freya')),
                     AdapterConfig(AdapterType.STT,'whisper-local',model_path=str(Path.cwd()/'models'/'whisper')),
                     AdapterConfig(AdapterType.LLM,'ollama-local',endpoint='http://127.0.0.1:11434'),
                     AdapterConfig(AdapterType.PBX,'asterisk-websocket',endpoint='ws://127.0.0.1:8088',codec='slin16',sample_rate_hz=16000)]),
                 'durable_outbox_in_console':False}
~~~~

### automotive_voice/operator/server.py

~~~~python
"""Loopback-only HTTP API for an explicitly synthetic operator console.

Server is not an authentication boundary for untrusted users; Windows-first local
single-operator development only. Does not expose raw transcripts or recordings.
"""
from __future__ import annotations
import asyncio
from concurrent.futures import TimeoutError as FutureTimeout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import secrets
import threading
from urllib.parse import urlsplit
from .runtime import ConsoleRuntime
from .review_store import ReviewError

STATIC={'/':'index.html','/index.html':'index.html','/app.css':'app.css','/app.js':'app.js'}
MIME={'index.html':'text/html; charset=utf-8','app.css':'text/css; charset=utf-8',
      'app.js':'application/javascript; charset=utf-8'}

class ConsoleHTTP:
    def __init__(self,runtime:ConsoleRuntime,host:str='127.0.0.1',port:int=8765):
        if host!='127.0.0.1':raise ValueError('M08 must listen on 127.0.0.1 only')
        self.runtime=runtime
        self.csrf=secrets.token_urlsafe(32)
        self.loop=asyncio.new_event_loop()
        self.thread=threading.Thread(target=self.loop.run_forever,daemon=True)
        self.thread.start()
        self.call(self.runtime.initialize())
        self.http=ThreadingHTTPServer((host,port),self._handler())
        self.http.daemon_threads=True
        self.host=host
        self.port=self.http.server_address[1]

    def call(self,coro):
        try:return asyncio.run_coroutine_threadsafe(coro,self.loop).result(timeout=10)
        except FutureTimeout as exc:raise RuntimeError('operator_action_timeout') from exc

    def _handler(self):
        outer=self
        class Handler(BaseHTTPRequestHandler):
            server_version='Freya-M08-Local/0.8'
            sys_version=''
            def log_message(self,fmt,*args):
                # Suppress potential sensitive request payloads and URL parameters.
                return
            def _security_headers(self):
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('X-Frame-Options','DENY')
                self.send_header('Referrer-Policy','no-referrer')
                self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            def _respond(self,status,body,content_type='application/json; charset=utf-8'):
                blob=(json.dumps(body,ensure_ascii=False,sort_keys=True).encode('utf-8')
                      if not isinstance(body,bytes) else body)
                self.send_response(status)
                self._security_headers()
                self.send_header('Content-Type',content_type)
                self.send_header('Content-Length',str(len(blob)))
                self.end_headers()
                try:self.wfile.write(blob)
                except (ConnectionAbortedError,BrokenPipeError):pass
            def _same_host(self):
                host=self.headers.get('Host','')
                return host in (f'127.0.0.1:{outer.port}',f'localhost:{outer.port}')
            def _route(self):return urlsplit(self.path).path
            def _drain(self):
                try:
                    ln=int(self.headers.get('Content-Length','0'))
                    if 0<ln<=65536:self.rfile.read(ln)
                except Exception:pass
            def do_GET(self):
                if not self._same_host():return self._respond(403,{'error':'invalid_host'})
                path=self._route()
                if path=='/api/bootstrap':
                    return self._respond(200,{'csrf':outer.csrf,'version':'M09-v1','mock_only':True})
                if path=='/api/snapshot':
                    try:return self._respond(200,outer.call(outer.runtime.snapshot()))
                    except Exception:return self._respond(500,{'error':'snapshot_unavailable'})
                name=STATIC.get(path)
                if name is None:return self._respond(404,{'error':'not_found'})
                src=files('automotive_voice.operator').joinpath('static',name)
                return self._respond(200,src.read_bytes(),MIME[name])
            def do_POST(self):
                if not self._same_host():
                    self._drain()
                    return self._respond(403,{'error':'invalid_host'})
                origin=self.headers.get('Origin')
                if origin is not None and origin!=f'http://{self.headers.get("Host")}' :
                    self._drain()
                    return self._respond(403,{'error':'invalid_origin'})
                if self.headers.get('X-Console-CSRF')!=outer.csrf:
                    self._drain()
                    return self._respond(403,{'error':'csrf_required'})
                if self._route()!='/api/action':
                    self._drain()
                    return self._respond(404,{'error':'not_found'})
                if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':
                    self._drain()
                    return self._respond(415,{'error':'json_required'})
                try:
                    length=int(self.headers.get('Content-Length','-1'))
                except ValueError:length=-1
                if length<2 or length>4096:return self._respond(413,{'error':'invalid_body_size'})
                try:
                    payload=json.loads(self.rfile.read(length))
                    if not isinstance(payload,dict):raise ValueError('object_required')
                    if any(key not in ('action','session_id','delta_ms','annotation_id','decision','reviewer','reason_code','scenario') for key in payload):
                        raise ValueError('unknown_argument')
                    action=payload.pop('action')
                    if not isinstance(action,str):raise ValueError('invalid_action')
                    result=outer.call(outer.runtime.act(action,payload.pop('session_id',None),**payload))
                    return self._respond(200,{'ok':True,'result':result})
                except (ValueError,ReviewError,TypeError) as exc:
                    return self._respond(422,{'ok':False,'error':str(exc)[:100]})
                except Exception:
                    return self._respond(500,{'ok':False,'error':'action_failed'})
            def do_OPTIONS(self):return self._respond(405,{'error':'not_supported'})
        return Handler

    def serve_forever(self):
        try:self.http.serve_forever(poll_interval=0.15)
        finally:self.shutdown()

    def shutdown(self):
        # call from another thread if serve_forever is running.
        self.http.server_close()
        self.loop.call_soon_threadsafe(self.loop.stop)
        if threading.current_thread()!=self.thread:self.thread.join(timeout=2)
~~~~

### automotive_voice/operator/static/app.css

~~~~css
:root{--bg:#f6f8fb;--surface:#fff;--side:#122338;--side2:#1a3148;--text:#192939;--muted:#778596;--border:#e5ebf0;--accent:#176e8e;--accent-dark:#0c526e;--accent-bg:#e6f3f7;--green:#16805e;--green-bg:#e6f6ee;--yellow:#a66b19;--yellow-bg:#fdf4e1;--red:#ad4a49;--red-bg:#fff0ef;--radius:12px;font-family:Inter,Segoe UI,system-ui,-apple-system,sans-serif;font-synthesis:none}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-size:14px;line-height:1.5}button{font:inherit;cursor:pointer}button:disabled{opacity:.45;cursor:not-allowed}button:focus-visible,.nav-item:focus-visible{outline:3px solid #77bbd6;outline-offset:2px}.shell{display:grid;grid-template-columns:244px minmax(0,1fr);min-height:100vh}.sidebar{background:var(--side);color:#e7f0f8;display:flex;flex-direction:column;min-height:100vh;padding:30px 15px 21px;position:sticky;top:0;height:100vh}.brand{display:flex;align-items:center;gap:12px;padding:0 13px;margin-bottom:27px}.brandmark{display:grid;place-items:center;width:39px;height:39px;background:#49a7bd;color:white;font-family:Georgia,serif;font-style:italic;font-size:31px;border-radius:10px}.brand strong{display:block;font-size:21px;letter-spacing:-.8px;line-height:1.05;font-weight:750}.brand small{color:#91acc0;font-size:9px;letter-spacing:2px;font-weight:700}.env{background:#1e3b50;color:#a5dddc;border:1px solid #2b4b5b;padding:9px 11px;border-radius:8px;margin:0 9px 34px;font-size:10px;font-weight:800;letter-spacing:1.1px;display:flex;align-items:center;gap:7px}.env-code{margin-left:auto;color:#82bdcb}.dot,.mini-dot{height:7px;width:7px;background:#4bccb0;display:inline-block;border-radius:50%}.nav-label{font-size:10px;color:#728fa7;letter-spacing:1.4px;margin:0 13px 13px;font-weight:750}.nav-item{width:100%;background:transparent;color:#a7bbca;border:0;border-radius:8px;padding:11px 15px;display:flex;gap:13px;align-items:center;text-align:left;font-size:13px;font-weight:600;margin:3px 0}.nav-item:hover{background:#1b344a;color:white}.nav-item.active{background:#23435a;color:#f1fbff}.nav-symbol{font-size:21px;width:23px;line-height:1;text-align:center;font-weight:400}.side-end{margin-top:auto;padding:0 8px}.side-panel{border:1px solid #365063;background:#1a3044;padding:16px;border-radius:10px}.side-panel-title{color:#78b9c9;letter-spacing:1.1px;font-size:10px;font-weight:800;display:block;margin-bottom:8px}.side-panel strong{font-size:13px}.side-panel p{font-size:11px;color:#a5b9c8;line-height:1.6;margin:6px 0 0}.version{display:block;color:#728fa7;font-size:10px;padding:17px 5px 0}.main{min-width:0;display:flex;flex-direction:column}.topbar{height:64px;background:white;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:0 39px}.crumb{display:flex;gap:13px;font-size:12px;font-weight:600;color:#52657a}.crumb span:first-child{color:#99a4b0}.sep{color:#d2dce4}.top-right{display:flex;align-items:center;gap:16px;font-size:11px;color:#8695a3}.connection{color:var(--green);font-weight:700;display:flex;gap:7px;align-items:center}.divider-v{width:1px;height:18px;background:#e1e7ec}.content{padding:39px;flex:1;width:100%;max-width:1570px;margin:0 auto}.page.hidden,.hidden{display:none!important}.heading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:26px}.heading h1{font-size:28px;font-weight:750;letter-spacing:-1.0px;margin:5px 0 6px;line-height:1.2}.heading p{color:var(--muted);margin:0;font-size:13px}.eyebrow{font-size:10px;color:#3a8c9f;font-weight:800;letter-spacing:1.45px}.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;border-radius:8px;border:1px solid var(--border);background:white;color:#475e72;font-weight:700;font-size:12px;padding:11px 15px;min-height:38px;transition:background .15s;white-space:normal;text-align:center}.btn:hover:not(:disabled){background:#ecf3f7}.btn.primary{background:var(--accent);color:white;border-color:var(--accent)}.btn.primary:hover:not(:disabled){background:var(--accent-dark)}.btn.outline{background:#fff;border-color:#d7e2e9}.btn.outline.accent{background:var(--accent-bg);color:var(--accent-dark);border-color:#c6e0ea}.btn.outline.danger{color:#a64846;border-color:#edd3d0}.btn.small{min-height:30px;padding:6px 10px;font-size:11px}.notice{background:#eef6f9;border:1px solid #d9ecf3;color:#466577;padding:14px 17px;display:flex;align-items:flex-start;gap:12px;border-radius:10px;margin-bottom:24px;font-size:12px;line-height:1.6}.notice strong{color:#264e63}.notice-icon{border-radius:50%;width:21px;height:21px;flex-shrink:0;display:grid;place-items:center;background:#cee8ef;color:#246780;font-weight:800}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-bottom:21px}.stat{background:white;border:1px solid var(--border);border-radius:var(--radius);padding:21px 22px;min-height:127px}.stat-label{color:#77889a;font-size:12px;font-weight:600}.stat-value{font-size:29px;font-weight:780;letter-spacing:-1px;margin:9px 0 3px}.stat-footer{font-size:11px;color:#94a1ad}.stat-value.good{color:var(--green)}.stat-value.warn{color:var(--yellow)}.two-cols{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px}.panel{background:white;border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;margin-bottom:20px}.two-cols .panel{margin-bottom:0}.panel-head{display:flex;align-items:center;justify-content:space-between;padding:19px 21px 16px;border-bottom:1px solid #edf1f4;gap:12px}.panel-head h2{font-size:14px;font-weight:750;margin:0}.panel-head p{font-size:11px;color:var(--muted);margin:4px 0 0}.muted-pill,.top-tag{background:#f0f4f7;border-radius:30px;color:#6e7f8d;padding:5px 9px;font-size:10px;font-weight:750;white-space:nowrap}.top-tag{background:#e8f4f7;color:#34758a}.text-btn{color:var(--accent);border:0;background:transparent;font-size:12px;font-weight:700}.adapter-list{padding:4px 21px 7px}.adapter-row,.event-row{display:flex;align-items:center;gap:11px;padding:12px 0;border-bottom:1px solid #f0f3f6}.adapter-row:last-child,.event-row:last-child{border:0}.service-icon{display:grid;place-items:center;height:35px;width:35px;background:#eaf3f6;border-radius:10px;color:#176e8e;font-size:12px;font-weight:800;flex:none}.service-name{font-size:12px;font-weight:700}.service-meta,.event-meta{color:var(--muted);font-size:11px}.service-info{flex:1;min-width:0}.status{font-size:10px;font-weight:800;padding:5px 8px;background:var(--green-bg);border-radius:30px;color:var(--green);text-transform:uppercase}.status.warning{background:var(--yellow-bg);color:var(--yellow)}.status.error{background:var(--red-bg);color:var(--red)}.event-list{padding:3px 20px 10px}.event-bullet{height:8px;width:8px;flex:none;background:#91aabd;border-radius:50%}.event-bullet.success{background:#36ae86}.event-bullet.warning{background:#dfa55a}.event-text{flex:1;min-width:0}.event-text strong{font-size:11px;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.event-text small{color:#8e9ca9;font-size:10px}.event-time{font-size:10px;color:#a0aebb}.session-list-row{display:flex;gap:15px;align-items:center;border-bottom:1px solid #edf1f4;padding:14px 22px}.session-list-row:last-child{border:0}.session-list-row button{border:0;background:transparent;color:var(--accent);font-size:11px;font-weight:750;white-space:nowrap}.session-id{font-size:12px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;color:#344d5e;font-weight:650;overflow-wrap:anywhere}.session-detail{display:flex;flex:1;gap:11px;align-items:center}.state-chip{border-radius:6px;padding:5px 10px;background:#eaf0f3;color:#536b7a;font-size:10px;font-weight:850;letter-spacing:.35px}.state-chip.interrupt{background:var(--yellow-bg);color:var(--yellow)}.state-chip.speaking{background:#e4f3f8;color:#116783}.state-chip.terminal{background:var(--red-bg);color:var(--red)}.empty{text-align:center;padding:38px 20px;color:#8c9aaa}.empty-symbol{font-size:30px;color:#acc7d3;margin-bottom:12px}.empty strong{font-size:13px;color:#547083;display:block}.empty p{font-size:12px;margin:4px 0}.session-layout{display:grid;grid-template-columns:360px minmax(0,1fr);gap:20px}.session-layout>.panel{min-height:280px}.session-choice{display:block;width:100%;border:0;border-bottom:1px solid #edf1f4;background:#fff;text-align:left;padding:13px 20px}.session-choice:last-child{border:0}.session-choice:hover,.session-choice.selected{background:#eff7fa}.session-choice .session-id{display:block;margin-bottom:5px}.session-choice .sub{display:flex;align-items:center;justify-content:space-between;color:var(--muted);font-size:11px}.controller .panel-head{padding-bottom:16px}.control-title{font-size:10px;font-weight:800;color:#8a99a7;letter-spacing:1.2px;padding:17px 22px 8px}.action-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;padding:0 22px 19px}.action-grid .btn{font-size:11px;min-height:46px}.control-footer{border-top:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;padding:13px 21px;font-size:12px;font-weight:700;color:#718396}.control-footer>div{display:flex;gap:6px}.detail-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;padding:20px}.detail-box{padding:12px;background:#f5f8fa;border-radius:8px}.detail-box span{display:block;font-size:10px;color:#91a0ad}.detail-box strong{display:block;font-size:13px;overflow-wrap:anywhere;margin-top:4px}.media-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;padding:18px 22px}.media-card{padding:13px;background:#f7f9fb;border:1px solid #e9eff3;border-radius:8px}.media-card span{font-size:10px;color:#8595a2;display:block}.media-card strong{font-size:15px;display:block;margin-top:5px}.source-row{padding:15px 21px;border-bottom:1px solid #eef2f5}.source-row:last-child{border:0}.source-row h3{font-size:12px;line-height:1.4;margin:0 0 4px}.source-row .meta{color:#8b99a7;font-size:11px}.source-row .source-foot{margin-top:9px;display:flex;gap:6px;flex-wrap:wrap}.pill{display:inline-block;padding:4px 8px;background:#f1f5f7;border-radius:5px;font-size:10px;color:#6e7f8e}.pill.ok{background:var(--green-bg);color:var(--green)}.pill.warn{background:var(--yellow-bg);color:var(--yellow)}.pronun-summary{padding:23px}.pronun-summary .big{font-size:36px;font-weight:750;line-height:1.25}.pronun-summary p{color:#8494a0;font-size:12px}.progress-track{height:7px;background:#e9eff2;border-radius:5px;margin:17px 0 0}.progress-bar{height:100%;width:0;background:var(--green);border-radius:5px}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:650px}th{color:#8795a2;text-align:left;font-size:10px;letter-spacing:.5px;font-weight:750;background:#fafbfd;padding:12px 16px;white-space:nowrap}td{border-top:1px solid #eef1f4;padding:12px 16px;font-size:11px;color:#4c5f71;word-break:break-word;vertical-align:middle}td:nth-child(2){font-weight:700;color:#2b475a}td code{font-size:10px;background:#f4f7f9;padding:4px;border-radius:4px}footer{padding:22px 39px;color:#a1acb8;font-size:10px;border-top:1px solid #e6ebef;display:flex;justify-content:space-between}.toast{position:fixed;bottom:24px;right:24px;max-width:440px;background:#122d41;color:white;padding:14px 20px;border-radius:9px;box-shadow:0 12px 36px #182f4355;font-size:12px;z-index:10}.toast.error{background:#8d3434}.skeleton{color:#93a6b7}.mono{font-family:ui-monospace,Consolas,monospace}.muted{color:var(--muted)}
@media(max-width:1050px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.session-layout{grid-template-columns:1fr}.action-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.media-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:760px){.shell{grid-template-columns:1fr}.sidebar{position:static;min-height:auto;height:auto;padding:15px 15px 7px}.brand{margin-bottom:10px}.env{margin-bottom:12px}.nav-label,.side-end{display:none}.sidebar nav{display:flex;overflow-x:auto;gap:5px}.nav-item{flex:0 0 auto;width:auto;white-space:nowrap;padding:9px 10px;font-size:11px}.nav-symbol{display:none}.topbar{padding:0 20px;height:47px}.top-right{display:none}.content{padding:22px 15px}.heading{align-items:flex-start;flex-direction:column}.heading h1{font-size:23px}.two-cols{grid-template-columns:1fr}.metrics{gap:10px}.stat{padding:14px;min-height:101px}.stat-value{font-size:25px}.action-grid{padding:0 15px 17px}.detail-grid{grid-template-columns:repeat(2,1fr)}footer{padding:15px;flex-direction:column;gap:5px}}

.golden-filter-label{display:flex;align-items:center;gap:9px;color:#748697;font-size:11px;font-weight:600}select{font:inherit;background:white;border:1px solid #dce4eb;border-radius:7px;padding:7px 8px;color:#345269;max-width:215px}.golden-summary{display:flex;flex-wrap:wrap;gap:20px;padding:15px 20px;border-bottom:1px solid var(--border);font-size:11px;color:#8494a2}.golden-summary strong{color:#355267;font-size:14px;margin-right:4px}#golden-rows td:nth-child(3),#golden-rows td:nth-child(4){min-width:220px;max-width:330px;font-weight:400;line-height:1.55}

/* M09 scenario review: keyboard-accessible buttons, no third-party assets */
.scenario-grid{padding:18px;display:grid;grid-template-columns:repeat(auto-fit,minmax(205px,1fr));gap:10px}
.scenario-run{justify-content:space-between;text-align:left;min-height:49px;flex-wrap:wrap}
.scenario-run small{font-size:10px;color:var(--accent)}
.scenario-report{padding:18px 22px;border-top:1px solid var(--border)}
.scenario-report-head{display:flex;gap:15px;justify-content:space-between;align-items:center;margin-bottom:10px}
.scenario-checks{display:flex;flex-wrap:wrap;gap:6px}
.scenario-report details{margin-top:12px}
.scenario-report summary{cursor:pointer;color:var(--accent);font-size:12px;font-weight:700}
~~~~

### automotive_voice/operator/static/app.js

~~~~js
/* M08 vanilla JS, local-only. No external assets, microphone, PII or real audio. */
'use strict';
let csrf = null;
let snapshot = null;
let selectedSession = null;
let activeView = 'overview';
let pending = false;
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const el = id => document.getElementById(id);
const labels = {overview:'Genel bakış',sessions:'Oturumlar',pronunciation:'Telaffuz inceleme',audit:'Olay günlüğü',scenarios:'M09 Senaryolar',readiness:'M10 Hazırlık'};
function toast(message,error=false) { const e=el('toast'); e.textContent=message; e.classList.toggle('error',error); e.classList.remove('hidden'); clearTimeout(toast.timer); toast.timer=setTimeout(()=>e.classList.add('hidden'),4200); }
async function getJSON(url) { const r=await fetch(url,{cache:'no-store'}); const d=await r.json(); if(!r.ok)throw new Error(d.error||'request_failed');return d; }
async function action(name,extra={}) { if(pending)return;pending=true;try {
  const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-Console-CSRF':csrf},body:JSON.stringify({action:name,...extra})});
  const d=await r.json();if(!r.ok)throw new Error(d.error||'action_failed');
  if(name==='open')selectedSession=d.result.session_id;
  toast(name==='fake_ack'?'Yalnızca sahte taşıma ACK doğrulandı.':name==='run_scenario'?`${d.result.scenario} · ${d.result.passed?'PASS':'FAIL'}`:`${name} • ${d.result.reason||'uygulandı'}`);
  await refresh();
} catch(e){toast(e.message,true);}finally{pending=false;}}
function showView(name){activeView=name;document.querySelectorAll('.page').forEach(x=>x.classList.toggle('hidden',x.id!=='view-'+name));document.querySelectorAll('.nav-item').forEach(x=>x.classList.toggle('active',x.dataset.view===name));el('view-crumb').textContent=labels[name];}
function statusCls(state){return ['READY','CLOSED','LISTENING'].includes(state)?'': ['SPEAKING'].includes(state)?'speaking': ['INTERRUPTING','DEGRADED','OPEN'].includes(state)?'interrupt': ['ENDED','FAILED'].includes(state)?'terminal':'';}
function healthRow(a){const ok=a.state==='ready'&&a.circuit==='closed';return `<div class="adapter-row"><div class="service-icon">${esc(({tts:'TS',stt:'ST',llm:'LM',telephony:'PB'})[a.kind]||'AD')}</div><div class="service-info"><div class="service-name">${esc(a.kind.toUpperCase())} <span class="service-meta">· synthetic</span></div><div class="service-meta">Devre: ${esc(a.circuit)} · Bekleyen: ${a.queued} · Aktif: ${a.in_flight} · Tamamlanan: ${a.completed}</div></div><span class="status ${ok?'':'warning'}">${esc(a.state)}</span></div>`;}
function activityRow(e){const good=e.decision==='applied'||e.decision==='accepted'||e.decision==='ok';const warn=e.decision==='rejected'||e.decision==='ignored';return `<div class="event-row"><span class="event-bullet ${good?'success':warn?'warning':''}"></span><div class="event-text"><strong>${esc(e.kind)}</strong><small>${esc(e.session)} · ${esc(e.decision)} · ${esc(e.reason)}</small></div><span class="event-time">${e.clock_ms} ms</span></div>`;}
function empty(title,detail){return `<div class="empty"><div class="empty-symbol">◌</div><strong>${esc(title)}</strong><p>${esc(detail)}</p></div>`;}
function renderOverview(d){
 const c=d.counts; el('metrics').innerHTML=`
  <div class="stat"><div class="stat-label">Toplam oturum</div><div class="stat-value">${c.sessions}</div><div class="stat-footer">Sentetik oturum sayısı</div></div>
  <div class="stat"><div class="stat-label">Aktif oturum</div><div class="stat-value good">${c.active}</div><div class="stat-footer">Terminal olmayan durumlar</div></div>
  <div class="stat"><div class="stat-label">Flush onayı bekleyen</div><div class="stat-value ${c.waiting_flush?'warn':''}">${c.waiting_flush}</div><div class="stat-footer">Yalnızca sahte ACK kabul edilir</div></div>
  <div class="stat"><div class="stat-label">Sanal zaman</div><div class="stat-value">${d.simulation_time_ms}<small style="font-size:13px;color:#94a4b0"> ms</small></div><div class="stat-footer">Gerçek gecikme ölçümü değildir</div></div>`;
 el('adapter-list').innerHTML=d.adapters.map(healthRow).join('');
 el('recent-events').innerHTML=d.timeline.length?'<div class="event-list">'+d.timeline.slice(0,6).map(activityRow).join('')+'</div>':empty('Henüz olay bulunmuyor','Yeni bir sentetik oturum başlatın.');
 el('overview-sessions').innerHTML=d.sessions.length?d.sessions.slice(0,8).map(s=>`<div class="session-list-row"><div class="session-detail"><span class="session-id">${esc(s.session_id)}</span><span class="state-chip ${statusCls(s.state)}">${esc(s.state)}</span><span class="muted">Tur ${s.turn_id} · Nesil ${s.generation_id}</span></div><button data-open-session="${esc(s.session_id)}">Yönet</button></div>`).join(''):empty('Aktif simülasyon yok','Oturum oluşturarak VAD, STT ve LLM durumlarını inceleyebilirsiniz.');
}
function renderSessions(d){el('session-count').textContent=d.sessions.length;
 if(selectedSession && !d.sessions.some(s=>s.session_id===selectedSession))selectedSession=null;
 if(!selectedSession && d.sessions.length)selectedSession=d.sessions[0].session_id;
 el('session-list').innerHTML=d.sessions.length?d.sessions.map(s=>`<button class="session-choice ${s.session_id===selectedSession?'selected':''}" data-select-session="${esc(s.session_id)}"><span class="session-id">${esc(s.session_id)}</span><span class="sub"><span>${esc(s.state)}</span><span>T${s.turn_id} · G${s.generation_id}</span></span></button>`).join(''):empty('Oturum yok','Yeni oturum düğmesini kullanın.');
 const s=d.sessions.find(s=>s.session_id===selectedSession);
 el('selected-session-description').textContent=s?s.session_id:'Bir oturum seçin';
 el('state-badge').textContent=s?s.state:'—';el('state-badge').className='state-chip '+(s?statusCls(s.state):'');
 el('session-detail').innerHTML=s?`<div class="detail-grid"><div class="detail-box"><span>TurnId</span><strong>${s.turn_id}</strong></div><div class="detail-box"><span>GenerationId</span><strong>${s.generation_id}</strong></div><div class="detail-box"><span>M01 olay kuyruğu</span><strong>${s.pending_events}</strong></div><div class="detail-box"><span>M02 audit kayıtları</span><strong>${s.audit_count}</strong></div></div>`:empty('Oturum seçin','İşlemler yalnızca oluşturduğunuz sentetik oturumlarda çalışır.');
 el('action-controls').querySelectorAll('button').forEach(b=>{b.disabled=!s || ['ENDED','FAILED'].includes(s.state) ||(b.dataset.action==='fake_ack'&&!s.pending_flush_id);});
 const m=s?[
 ['Flush bariyeri',s.pending_flush_id?'FAKE ACK bekleniyor':'Bekleyen yok'],
 ['Medya kuyruğu',s.queued_chunks+' parça · '+s.queued_ms+' ms'],
 ['Transport',s.transport_paused?'XOFF / kilitli':'XON / uygun'],
 ['Taşıma kuyruğu',s.transport_queued+' metadata']]:[['Flush bariyeri','—'],['Medya kuyruğu','—'],['Transport','—'],['Taşıma kuyruğu','—']];
 el('media-summary').innerHTML='<div class="media-grid">'+m.map(x=>`<div class="media-card"><span>${esc(x[0])}</span><strong>${esc(x[1])}</strong></div>`).join('')+'</div>';
}
function renderPronunciation(d){el('sources').innerHTML=d.sources.length?d.sources.map(s=>`<div class="source-row"><h3>${esc(s.title)}</h3><div class="meta">${esc(s.creator)} · ${esc(s.id)}</div><div class="source-foot"><span class="pill warn">${esc(s.permission_claim_status)}</span><span class="pill">${esc(s.rights_basis)}</span></div></div>`).join(''):empty('Kaynak bulunamadı','A01-YT veritabanına erişilemiyor.');
 const total=d.annotations.length;const approved=d.annotations.filter(a=>a.review?.decision==='approved').length;
 el('pronunciation-summary').innerHTML=`<div class="pronun-summary"><div class="big">${approved}<span style="font-size:16px;color:#9eacb8;font-weight:500"> / ${total}</span></div><strong>Yerel operatör tarafından onaylanan kayıt</strong><p>Kaynakta ses/transkript kanıtı olmadan onay verilemez. Aktif M04 telaffuz sözlüğü bu ekranla değişmez.</p><div class="progress-track"><div class="progress-bar" style="width:${total?100*approved/total:0}%"></div></div></div>`;
 el('annotation-count').textContent=total+' kayıt';
 el('annotations').innerHTML=total?'<div class="table-wrap"><table><thead><tr><th>Kaynak</th><th>Terim / okunuş</th><th>Aralık</th><th>Kanıt</th><th>Karar</th></tr></thead><tbody>'+d.annotations.map(a=>`<tr><td>${esc(a.source_id)}</td><td>${esc(a.canonical)}<br><span class="muted">${esc(a.spoken_tr)}</span></td><td>${esc(a.start_sec)}–${esc(a.end_sec)} sn</td><td>${a.has_clip_reference&&a.transcript_checked?'Kontrol edilebilir':'Eksik'}</td><td>${esc(a.review?.decision||'bekliyor')}<div style="margin-top:6px;display:flex;gap:5px"><button class="btn small" data-approve="${esc(a.id)}">Onayla*</button><button class="btn small" data-reject="${esc(a.id)}">Reddet</button></div></td></tr>`).join('')+'</tbody></table></div>':empty('İnceleme kuyruğu boş','Henüz gerçek sesle ilişkilendirilmiş anotasyon bulunmuyor. Ses veya kanıt uydurulmadı.');
}

function renderGolden(d){
 const summary=d.golden_summary||{}, cases=d.golden_cases||[];
 el('golden-stats').innerHTML=`<div class="golden-summary"><span><strong>${summary.input_count||0}</strong> kaynak cümle</span><span><strong>${summary.changed_texts||0}</strong> değişen</span><span><strong>${summary.review_required||0}</strong> inceleme</span><span><strong>${summary.unsupported_char_cases||0}</strong> karakter uyumsuzluğu</span></div>`;
 const filter=el('golden-filter').value;
 const subset=cases.filter(c=>filter==='all'||filter==='review'&&c.review_required==='1'||filter==='changed'&&c.changed==='1');
 el('golden-rows').innerHTML=subset.map(c=>`<tr><td class="mono">${esc(c.id)}</td><td>${esc(c.category)}</td><td>${esc(c.original)}</td><td>${esc(c.prepared)}</td><td><span class="pill ${c.review_required==='1'?'warn':'ok'}">${c.review_required==='1'?'İnceleme':'Hazır'}</span></td></tr>`).join('')||'<tr><td colspan="5">Bu filtreyle eşleşen vaka yok.</td></tr>';
}
function renderScenarios(d){
 el('scenario-count').textContent=d.scenario_catalog.length+' senaryo';
 el('scenario-catalog').innerHTML=d.scenario_catalog.map(n=>`<button class="btn outline scenario-run" data-scenario="${esc(n)}" ${pending?'disabled':''}><span>${esc(n.replaceAll('_',' '))}</span><small>Çalıştır</small></button>`).join('');
 el('scenario-reports').innerHTML=(d.scenario_reports||[]).length?d.scenario_reports.map(r=>`<section class="scenario-report"><div class="scenario-report-head"><strong>${esc(r.scenario)}</strong><span class="pill ${r.passed?'ok':'warn'}">${r.passed?'PASS':'FAIL'}</span></div><div class="scenario-checks">${Object.entries(r.checks).map(([k,v])=>`<span class="pill ${v?'ok':'warn'}">${v?'✓':'✕'} ${esc(k)}</span>`).join('')}</div><div class="muted" style="padding:10px 0">Oturumlar: ${r.sessions.map(s=>esc(s.id)+' · '+esc(s.state)+' · T'+s.turn).join(' | ')}</div><details><summary>Olay izleri (${r.trace.length})</summary><div class="table-wrap"><table><thead><tr><th>ms</th><th>Olay</th><th>Karar</th><th>Oturum</th></tr></thead><tbody>${r.trace.map(t=>`<tr><td>${t.ms}</td><td>${esc(t.step)}</td><td>${esc(t.outcome)}</td><td>${esc(t.session)}</td></tr>`).join('')}</tbody></table></div></details></section>`).join(''):empty('Henüz senaryo çalıştırılmadı','Yukarıdan bir sentetik test seçin.');
}
function renderReadiness(d){
 const r=d.m10_readiness;
 el('m10-readiness').innerHTML=r? r.adapters.map(a=>`<div class="adapter-row"><div class="service-icon">${esc(a.adapter.substring(0,2).toUpperCase())}</div><div class="service-info"><div class="service-name">${esc(a.adapter.toUpperCase())} · DRY RUN</div><div class="service-meta">${a.findings.length?a.findings.map(esc).join(' · '):'Yapılandırma tutarlı; gerçek bağlantı doğrulanmadı'}</div></div><span class="status warning">HOLD</span></div>`).join('') : empty('Denetim alınamadı','M10 sözleşme sonuçları bulunmuyor.');
}
function renderAudit(d){el('audit-rows').innerHTML=d.timeline.length?d.timeline.map(e=>`<tr><td class="mono">${e.clock_ms} ms</td><td>${esc(e.kind)}</td><td><code>${esc(e.session)}</code></td><td>${esc(e.decision)}</td><td>${esc(e.reason)}</td></tr>`).join(''):'<tr><td colspan="5">Henüz olay kaydı yok.</td></tr>';}
async function refresh(){try{snapshot=await getJSON('/api/snapshot');renderOverview(snapshot);renderSessions(snapshot);renderPronunciation(snapshot);renderGolden(snapshot);renderScenarios(snapshot);renderReadiness(snapshot);renderAudit(snapshot);}catch(e){toast('Durum verileri alınamadı: '+e.message,true);}}
document.addEventListener('click',e=>{
 const view=e.target.closest('[data-view]');if(view){showView(view.dataset.view);return;}
 const go=e.target.closest('[data-goto]');if(go){showView(go.dataset.goto);return;}
 const select=e.target.closest('[data-select-session]');if(select){selectedSession=select.dataset.selectSession;renderSessions(snapshot);return;}
 const open=e.target.closest('[data-open-session]');if(open){selectedSession=open.dataset.openSession;showView('sessions');renderSessions(snapshot);return;}
 const button=e.target.closest('[data-action]');if(button){if(selectedSession)action(button.dataset.action,{session_id:selectedSession});return;}
 const scenario=e.target.closest('[data-scenario]');if(scenario){action('run_scenario',{scenario:scenario.dataset.scenario});return;}
 const tick=e.target.closest('[data-tick]');if(tick){action('tick',{delta_ms:Number(tick.dataset.tick)});return;}
 const approve=e.target.closest('[data-approve]');if(approve){action('review',{annotation_id:approve.dataset.approve,decision:'approved',reviewer:'operator_01',reason_code:'verified_evidence'});return;}
 const reject=e.target.closest('[data-reject]');if(reject){action('review',{annotation_id:reject.dataset.reject,decision:'rejected',reviewer:'operator_01',reason_code:'insufficient_evidence'});return;}
});
async function boot(){try{const start=await getJSON('/api/bootstrap');csrf=start.csrf;await refresh();document.querySelectorAll('#create-overview,#create-sessions').forEach(b=>b.addEventListener('click',()=>action('open')));el('refresh-log').addEventListener('click',refresh);el('golden-filter').addEventListener('change',()=>{if(snapshot)renderGolden(snapshot)});setInterval(()=>{if(!document.hidden&&!pending)refresh();},4000);}catch(e){toast('Konsol başlatılamadı: '+e.message,true);}}
boot();
~~~~

### automotive_voice/operator/static/index.html

~~~~html
<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Freya | Operatör Konsolu</title>
  <link rel="stylesheet" href="/app.css"/>
  <script defer src="/app.js"></script>
</head>
<body>
<div class="shell">
  <aside class="sidebar" aria-label="Ana menü">
    <div class="brand"><span class="brandmark">f</span><div><strong>freya</strong><small>OPERATIONS</small></div></div>
    <div class="env"><span class="dot"></span> YEREL · SENTETİK <span class="env-code">M10</span></div>
    <div class="nav-label">ÇALIŞMA ALANI</div>
    <nav id="menu" aria-label="Çalışma bölümleri">
      <button class="nav-item active" data-view="overview"><span class="nav-symbol">▦</span> Genel bakış</button>
      <button class="nav-item" data-view="sessions"><span class="nav-symbol">◉</span> Oturumlar</button>
      <button class="nav-item" data-view="pronunciation"><span class="nav-symbol">≋</span> Telaffuz inceleme</button>
      <button class="nav-item" data-view="scenarios"><span class="nav-symbol">▤</span> M09 Senaryolar</button>
      <button class="nav-item" data-view="readiness"><span class="nav-symbol">◇</span> M10 Hazırlık</button>
      <button class="nav-item" data-view="audit"><span class="nav-symbol">≡</span> Olay günlüğü</button>
    </nav>
    <div class="side-end">
      <div class="side-panel"><span class="side-panel-title">Test ortamı</span><strong>Çevrimdışı mod</strong><p>Model, mikrofon, gerçek SIP ve müşteri kayıtları kapalı.</p></div>
      <span class="version">M01–M08 çekirdeği · M09 sentetik entegrasyon</span>
    </div>
  </aside>
  <main class="main">
    <header class="topbar"><div class="crumb"><span>Freya / Console</span><span class="sep">/</span><span id="view-crumb">Genel bakış</span></div><div class="top-right"><span class="connection"><span class="mini-dot"></span> Localhost</span><span class="divider-v"></span><span>Mock environment</span></div></header>
    <div class="content">
      <section class="page" id="view-overview">
        <div class="heading"><div><div class="eyebrow">OPERASYON MERKEZİ · M08</div><h1>Sistem genel bakışı</h1><p>Oturum, adaptör ve medya kontrolünü tek yerden takip edin.</p></div><button class="btn primary" id="create-overview">+ Yeni sentetik oturum</button></div>
        <div class="notice"><div class="notice-icon">i</div><div><strong>Bu konsol yalnızca bir simülasyondur.</strong> Gerçek Freya sesi üretilmez, çağrı başlatılmaz ve PBX onayı alınmaz. Veriler geçici bellek ve yerel inceleme kayıtlarından gelir.</div></div>
        <div class="metrics" id="metrics" aria-live="polite"><div class="stat skeleton">Veriler yükleniyor…</div></div>
        <div class="two-cols">
          <section class="panel"><div class="panel-head"><div><h2>Adaptör durumu</h2><p>Deterministik sahte servisler</p></div><span class="muted-pill">4 adaptör</span></div><div class="adapter-list" id="adapter-list"></div></section>
          <section class="panel"><div class="panel-head"><div><h2>Son olaylar</h2><p>Oturum geçişleri ve efekt yönlendirme</p></div><button class="text-btn" data-goto="audit">Tümünü gör</button></div><div id="recent-events"></div></section>
        </div>
        <section class="panel"><div class="panel-head"><div><h2>Aktif oturumlar</h2><p>Konuşma durumu ve üretim kimlikleri</p></div><button class="text-btn" data-goto="sessions">Oturum paneli</button></div><div id="overview-sessions"></div></section>
      </section>
      <section class="page hidden" id="view-sessions">
        <div class="heading"><div><div class="eyebrow">SENTETİK ÇAĞRI SİMÜLATÖRÜ</div><h1>Oturum yönetimi</h1><p>M02 durum makinesini gerçek sinyal sözleşmeleriyle çalıştırın.</p></div><button class="btn primary" id="create-sessions">+ Yeni oturum</button></div>
        <div class="notice"><div class="notice-icon">!</div><div><strong>Deneysel kontrol alanı:</strong> Buradaki tüm sinyaller simülasyondur. “FAKE ACK” gerçek Asterisk tampon onayı değildir.</div></div>
        <div class="session-layout"><section class="panel"><div class="panel-head"><h2>Oturumlar</h2><span class="muted-pill" id="session-count">0</span></div><div id="session-list"></div></section>
          <section class="panel controller"><div class="panel-head"><div><h2>Kontrol masası</h2><p id="selected-session-description">Bir oturum seçin</p></div><span id="state-badge" class="state-chip">—</span></div>
            <div id="session-detail"><div class="empty"><div class="empty-symbol">◉</div><strong>Henüz oturum seçilmedi</strong><p>Yeni bir sentetik oturum oluşturarak başlayın.</p></div></div>
            <div class="control-title">SENTETİK OLAYLAR</div>
            <div class="action-grid" id="action-controls">
              <button class="btn outline" data-action="vad">VAD: Konuşma başladı</button>
              <button class="btn outline" data-action="transcript">STT: Son transkript</button>
              <button class="btn outline" data-action="llm">LLM: Yanıt hazır</button>
              <button class="btn outline" data-action="playout">Oynatma tamamlandı</button>
              <button class="btn outline accent" data-action="fake_ack">FAKE ACK · Tampon temizlendi</button>
              <button class="btn outline" data-action="handoff">Temsilciye aktar</button>
              <button class="btn outline" data-action="xoff">MEDIA_XOFF</button>
              <button class="btn outline" data-action="xon">MEDIA_XON</button>
              <button class="btn outline danger" data-action="hangup">Çağrıyı sonlandır</button>
            </div>
            <div class="control-footer"><span>Sanal zaman</span><div><button class="btn small" data-tick="20">+20 ms</button><button class="btn small" data-tick="100">+100 ms</button><button class="btn small" data-tick="1600">+1,6 sn</button></div></div>
          </section></div>
        <section class="panel"><div class="panel-head"><div><h2>Medya güvenliği</h2><p>Yerel kuyruk ve M06 FakeTransport</p></div><span class="muted-pill">Metadata only</span></div><div id="media-summary"></div></section>
      </section>
      <section class="page hidden" id="view-pronunciation">
        <div class="heading"><div><div class="eyebrow">A01-YT · KANIT ODAKLI İNCELEME</div><h1>Telaffuz referansları</h1><p>Kaynakların durumunu ve insan onayına açık anotasyonları izleyin.</p></div><span class="top-tag">Salt-okunur kaynak</span></div>
        <div class="notice"><div class="notice-icon">i</div><div><strong>Kaynak bağlantısı, ses kanıtı değildir.</strong> Onay yalnızca gerçek klip, SHA-256 eşleşmesi, yetkili kullanım kapsamı ve düzeltilmiş transkript ile verilebilir. İnceleme kararları ayrı SQLite dosyasına kaydedilir; üretim sözlüğü otomatik değişmez.</div></div>
        <div class="two-cols"><section class="panel"><div class="panel-head"><div><h2>Kaynak envanteri</h2><p>A01-YT v0.5 kayıtları</p></div></div><div id="sources"></div></section>
        <section class="panel"><div class="panel-head"><div><h2>İnceleme durumu</h2><p>Kanıt ve onay kapısı</p></div></div><div id="pronunciation-summary"></div></section></div>
        <section class="panel"><div class="panel-head"><div><h2>320 golden metin kontrolü</h2><p>Önceki M04 sonuçları · yeni ses kalitesi ölçümü değildir</p></div><label class="golden-filter-label">Görüntüle <select id="golden-filter"><option value="review">İnceleme gerektirenler</option><option value="all">Tüm 320 vaka</option><option value="changed">Değişen metinler</option></select></label></div><div id="golden-stats"></div><div class="table-wrap"><table><thead><tr><th>ID</th><th>Kategori</th><th>Orijinal metin</th><th>Normalize edilmiş</th><th>Durum</th></tr></thead><tbody id="golden-rows"></tbody></table></div></section>
        <section class="panel"><div class="panel-head"><div><h2>İnceleme kuyruğu</h2><p>İnsan onayına gönderilmiş telaffuz önerileri</p></div><span class="muted-pill" id="annotation-count">0 kayıt</span></div><div id="annotations"></div></section>
      </section>
      <section class="page hidden" id="view-scenarios">
        <div class="heading"><div><div class="eyebrow">M09 · SENTETİK ENTEGRASYON</div><h1>Uçtan uca senaryo kontrolü</h1><p>M01–M08 modüllerinin gerçek sözleşmelerini sahte servislerle sınayın.</p></div><span class="top-tag">Ses yok · Ağ yok</span></div>
        <div class="notice"><div class="notice-icon">i</div><div><strong>Sadece denetim ortamı.</strong> Senaryolar her çalıştırmada yeni, bağımsız bir oturum dünyası kurar. Oluşturulan onaylar gerçek randevu veya telefon işlemi değildir. Yerel raporlar yeniden başlatmada silinir.</div></div>
        <section class="panel"><div class="panel-head"><div><h2>Senaryolar</h2><p>Deterministik testler · 16 iş ve hata senaryosu</p></div><span class="muted-pill" id="scenario-count">16</span></div><div class="scenario-grid" id="scenario-catalog"></div></section>
        <section class="panel"><div class="panel-head"><div><h2>Sonuç ve doğrulamalar</h2><p>Karar kuralları, generation, flush ACK ve izolasyon</p></div></div><div id="scenario-reports"></div></section>
      </section>
      <section class="page hidden" id="view-readiness">
        <div class="heading"><div><div class="eyebrow">M10 · DRY RUN</div><h1>Gerçek adaptörlere hazırlık</h1><p>Model ve telefon bağlantısı açmadan çevrimdışı sözleşme denetimi.</p></div><span class="top-tag">Bağlantılar kapalı</span></div>
        <div class="notice"><div class="notice-icon">i</div><div><strong>Üretim etkinleştirmesi devre dışı.</strong> Bu kontrol GPU, mikrofon, ses dosyası, CRM, SIP veya ağ bağlantısı başlatmaz. Kalıcı outbox bu konsolda etkin değildir; M10 ayrı dry-run çekirdeğinde doğrulanır.</div></div>
        <section class="panel"><div class="panel-head"><div><h2>Bağlantı sözleşmeleri</h2><p>Fiziksel bağlantı veya gerçek sağlık kontrolü değildir</p></div></div><div id="m10-readiness" class="adapter-list"></div></section>
        <section class="panel"><div class="panel-head"><div><h2>Hazırlık sınırları</h2><p>Son fiziksel kabul aşamasına ertelenen işler</p></div></div><div style="padding:20px;color:#61798a;line-height:1.9;font-size:12px">GPU ve FreyaTTS yüklemesi · STT mikrofonu · PBX ve gerçek FLUSH ACK · codec/streaming ve ağ gecikmesi · YouTube ses kanıtı · Windows/Edge fiziksel kabul.</div></section>
      </section>
      <section class="page hidden" id="view-audit">
        <div class="heading"><div><div class="eyebrow">GÖZLEMLENEBİLİRLİK</div><h1>Olay günlüğü</h1><p>Sinyal, efekt, durum reddi ve timeout kayıtlarının görünümü.</p></div><button class="btn outline" id="refresh-log">↻ Yenile</button></div>
        <div class="notice"><div class="notice-icon">i</div><div><strong>Volatil günlük:</strong> Bu tablo uygulama belleğinde tutulur ve yeniden başlatmada temizlenir. Kalıcı olay kurtarma M08 kapsamı dışında.</div></div>
        <section class="panel"><div class="panel-head"><div><h2>Olay akışı</h2><p>En yeni olaylar üstte; en fazla 160 kayıt</p></div><span class="muted-pill">PII içermeyen referanslar</span></div><div class="table-wrap"><table><thead><tr><th>Sanal zaman</th><th>Olay</th><th>Oturum</th><th>Karar</th><th>Açıklama</th></tr></thead><tbody id="audit-rows"></tbody></table></div></section>
      </section>
    </div>
    <footer>Freya Automotive · Local development console <span>Gerçek servis bağlantısı yok · M10</span></footer>
  </main>
</div>
<div id="toast" role="status" aria-live="polite" class="toast hidden"></div>
</body>
</html>
~~~~

### automotive_voice/ports/contracts.py

~~~~python
"""Backward-compatible mock TTS ports; M01 canonical AudioFormat lives in core."""
from dataclasses import dataclass
from typing import AsyncIterator, Protocol
from automotive_voice.core.audio import AudioFormat

@dataclass(frozen=True)
class AudioChunk:
    generation_id: int
    seq: int
    payload: bytes
    audio_format: AudioFormat

class TTSPort(Protocol):
    async def synthesize(self, text: str, generation_id: int) -> AsyncIterator[AudioChunk]: ...

class MediaOutput(Protocol):
    async def enqueue(self, chunk: AudioChunk) -> None: ...
    async def flush(self) -> None: ...
~~~~

### automotive_voice/prosody/__init__.py

~~~~python
from .contracts import (BreakKind, PlanStatus, SpanKind, Clause, PhraseBoundary,
                        ClausePlan, TTSInput)
from .planner import ProsodyClausePlanner, PlannerLimits
from .mock_tts import MockTTS, QueueReceipt
from .coordinator import ProsodyCoordinator, PlanningResult
__all__ = ['BreakKind', 'PlanStatus', 'SpanKind', 'Clause', 'PhraseBoundary',
           'ClausePlan', 'TTSInput', 'ProsodyClausePlanner', 'PlannerLimits',
           'MockTTS', 'QueueReceipt', 'ProsodyCoordinator', 'PlanningResult']
~~~~

### automotive_voice/prosody/contracts.py

~~~~python
"""M05 immutable text-only TTS contracts. No audio buffers or transport objects."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import hashlib
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId

class BreakKind(str, Enum):
    SENTENCE = 'sentence'
    PAUSE = 'pause'
    LIMIT = 'limit'
    FINAL = 'final'

class PlanStatus(str, Enum):
    READY = 'ready'
    REVIEW_REQUIRED = 'review_required'

class SpanKind(str, Enum):
    MONEY = 'money'
    DATE = 'date'
    TIME = 'time'
    ENGINE = 'engine'
    MODEL = 'model'
    DISTANCE = 'distance'
    MODEL_YEAR = 'model_year'
    APPROVED_LEXICON = 'approved_lexicon'

@dataclass(frozen=True, slots=True)
class PhraseBoundary:
    start: int
    end: int
    kind: SpanKind
    evidence: str = ''  # non-sensitive rule tag, NEVER source transcript

    def __post_init__(self) -> None:
        if type(self.start) is not int or type(self.end) is not int or self.start < 0 or self.end <= self.start:
            raise ValueError('invalid protected span offsets')
        if not isinstance(self.kind, SpanKind):
            raise TypeError('SpanKind required')

@dataclass(frozen=True, slots=True)
class Clause:
    index: int
    start: int
    end: int
    text: str
    break_kind: BreakKind
    pause_after_ms: int
    delivery_hint: str

    def __post_init__(self) -> None:
        if (type(self.index) is not int or self.index < 0 or self.start < 0 or
            self.end <= self.start or not self.text or
            self.text != self.text.strip() or self.pause_after_ms < 0 or
            self.delivery_hint not in {'statement', 'question', 'continuation'}):
            raise ValueError('invalid clause')
        if not isinstance(self.break_kind, BreakKind):
            raise TypeError('BreakKind required')

@dataclass(frozen=True, slots=True)
class TTSInput:
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    clause_index: int
    clause_count: int
    text: str  # kept in local processing memory, not events/telemetry
    text_sha256: str
    break_kind: BreakKind
    pause_after_ms: int
    delivery_hint: str

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, SessionId) or not isinstance(self.turn_id, TurnId) or not isinstance(self.generation_id, GenerationId):
            raise TypeError('strong session, turn, generation identifiers required')
        if (type(self.clause_index) is not int or type(self.clause_count) is not int or
            not (0 <= self.clause_index < self.clause_count) or not self.text or
            hashlib.sha256(self.text.encode('utf-8')).hexdigest() != self.text_sha256):
            raise ValueError('invalid or corrupted text-only TTS input')

    def safe_metadata(self) -> dict:
        return {'session_id': str(self.session_id), 'turn_id': int(self.turn_id),
                'generation_id': int(self.generation_id), 'clause_index': self.clause_index,
                'clause_count': self.clause_count, 'text_sha256': self.text_sha256,
                'break_kind': self.break_kind.value, 'delivery_hint': self.delivery_hint}

@dataclass(frozen=True, slots=True)
class ClausePlan:
    session_id: SessionId
    turn_id: TurnId
    generation_id: GenerationId
    spoken_text: str  # private; never serialized into event payloads or logs
    status: PlanStatus
    clauses: tuple[Clause, ...]
    protected_spans: tuple[PhraseBoundary, ...]
    warning_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, SessionId) or not isinstance(self.turn_id, TurnId) or not isinstance(self.generation_id, GenerationId):
            raise TypeError('M01 identity types required')
        if not self.spoken_text or not isinstance(self.status, PlanStatus):
            raise ValueError('invalid clause plan')
        if self.warning_codes and self.status is PlanStatus.READY:
            raise ValueError('warning-bearing plan cannot be ready')
        for i, c in enumerate(self.clauses):
            if i != c.index or self.spoken_text[c.start:c.end] != c.text:
                raise ValueError('clause offsets/text mismatch')
        if ''.join(self.spoken_text.split()) != ''.join(''.join(c.text.split()) for c in self.clauses):
            raise ValueError('clauses must preserve all non-whitespace characters')
        for span in self.protected_spans:
            if span.end > len(self.spoken_text):
                raise ValueError('protected span outside text')
            if not any(c.start <= span.start and span.end <= c.end for c in self.clauses):
                raise ValueError('protected span split across clauses')

    @property
    def review_required(self) -> bool:
        return self.status is PlanStatus.REVIEW_REQUIRED

    def tts_inputs(self) -> tuple[TTSInput, ...]:
        """No TTS inputs if text has any unresolved pronunciation/formatting warning."""
        if self.review_required:
            return ()
        return tuple(TTSInput(self.session_id, self.turn_id, self.generation_id,
                              c.index, len(self.clauses), c.text,
                              hashlib.sha256(c.text.encode('utf-8')).hexdigest(),
                              c.break_kind, c.pause_after_ms, c.delivery_hint)
                     for c in self.clauses)

    def safe_metadata(self) -> dict:
        return {'session_id': str(self.session_id), 'turn_id': int(self.turn_id),
                'generation_id': int(self.generation_id), 'status': self.status.value,
                'clause_count': len(self.clauses), 'protected_span_count': len(self.protected_spans),
                'warning_codes': list(self.warning_codes)}
~~~~

### automotive_voice/prosody/coordinator.py

~~~~python
"""Bridge M02 START_TTS refs -> M03 response store -> M04 -> M05 mock queue.

No LLM, no Freya runtime, no audio. Fail closed on missing, stale or
review-required text; store is session scoped, events carry only opaque refs.
"""
from __future__ import annotations
from dataclasses import dataclass
from automotive_voice.conversation.effects import Effect, EffectKind
from automotive_voice.dialogue.storage import ReferenceStore, MissingReferenceError
from automotive_voice.nlp.normalizer import TurkishAutomotiveNormalizer
from .planner import ProsodyClausePlanner
from .mock_tts import MockTTS

@dataclass(frozen=True, slots=True)
class PlanningResult:
    status: str
    reason: str
    queued_clauses: int
    warning_codes: tuple[str, ...] = ()

class ProsodyCoordinator:
    def __init__(self, store: ReferenceStore, normalizer: TurkishAutomotiveNormalizer,
                 planner: ProsodyClausePlanner, mock_tts: MockTTS, *, presentation=None):
        self.store = store
        self.normalizer = normalizer
        self.planner = planner
        self.mock_tts = mock_tts
        self.presentation = presentation

    async def process(self, effect: Effect) -> PlanningResult:
        if not isinstance(effect, Effect) or effect.kind is not EffectKind.START_TTS:
            raise ValueError('M02 START_TTS effect required')
        sid = str(effect.session_id)
        if not await self.mock_tts._active(sid, effect.turn_id, effect.generation_id):
            return PlanningResult('rejected', 'stale_generation_or_wrong_state', 0)
        try:
            response = self.store.get_response(sid, effect.reference or '')
        except MissingReferenceError:
            return PlanningResult('rejected', 'missing_response_reference', 0)
        try:
            spoken_text = response.text
            if self.presentation is not None:
                candidate = self.presentation.render(response)
                if candidate.warnings:
                    return PlanningResult('review_required','presentation_gate',0,candidate.warnings)
                spoken_text = candidate.speech_text
            normalized = self.normalizer.normalize(spoken_text)
            plan = self.planner.plan(normalized, session_id=effect.session_id,
                                     turn_id=effect.turn_id, generation_id=effect.generation_id)
        except (TypeError, ValueError):
            return PlanningResult('rejected', 'invalid_tts_text', 0)
        if plan.review_required:
            # No content or forbidden character in logs/audit.
            return PlanningResult('review_required', 'unresolved_text', 0, plan.warning_codes)
        receipt = await self.mock_tts.enqueue(plan)
        return PlanningResult('queued' if receipt.accepted else 'rejected', receipt.reason,
                              receipt.count)
~~~~

### automotive_voice/prosody/mock_tts.py

~~~~python
"""Text-only queue for M05. Consumers MUST revalidate generation at emission time."""
from __future__ import annotations
import asyncio
from collections import deque
from dataclasses import dataclass
from automotive_voice.core.session import State
from automotive_voice.core.session_manager import SessionManager
from .contracts import ClausePlan, TTSInput

@dataclass(frozen=True, slots=True)
class QueueReceipt:
    accepted: bool
    reason: str
    count: int

class MockTTS:
    """No waveforms, sockets, audio codecs, or synthesis imports.

    Uses per-instance bounded storage. A stale item may be queued when interruption
    races with enqueue; pop_next always checks the current M01 generation again.
    """
    def __init__(self, manager: SessionManager, max_pending: int = 128, dedup_capacity: int = 4096):
        if (type(max_pending) is not int or max_pending < 1 or
            type(dedup_capacity) is not int or dedup_capacity < max_pending):
            raise ValueError('invalid queue or dedup capacity')
        self.manager = manager
        self.max_pending = max_pending
        self.dedup_capacity = dedup_capacity
        self._known: dict[tuple[str, int, int, int], str] = {}
        self._known_order: deque[tuple[str, int, int, int]] = deque()
        self._queue: deque[TTSInput] = deque()
        self._lock = asyncio.Lock()

    async def _active(self, sid: str, t: int, g: int) -> bool:
        try:
            snap = await self.manager.snapshot(sid)
            if snap.state is not State.SPEAKING or snap.turn_id != t or snap.generation_id != g:
                return False
            token = await self.manager.current_token(sid)
            return not token.cancelled and token.generation_id == g
        except (LookupError, ValueError):
            return False

    async def enqueue(self, plan: ClausePlan) -> QueueReceipt:
        if not isinstance(plan, ClausePlan):
            raise TypeError('ClausePlan required')
        if plan.review_required:
            return QueueReceipt(False, 'review_required', 0)
        if not await self._active(plan.session_id, plan.turn_id, plan.generation_id):
            return QueueReceipt(False, 'stale_generation_or_wrong_state', 0)
        items = plan.tts_inputs()
        async with self._lock:
            to_queue = []
            for item in items:
                key = (str(item.session_id), int(item.turn_id), int(item.generation_id), item.clause_index)
                prior = self._known.get(key)
                if prior is not None and prior != item.text_sha256:
                    return QueueReceipt(False, 'conflicting_replay', 0)
                if prior is None:
                    to_queue.append((key, item))
            if not to_queue:
                return QueueReceipt(True, 'duplicate_ignored', 0)
            if len(self._queue) + len(to_queue) > self.max_pending:
                return QueueReceipt(False, 'backpressure', 0)
            for key, item in to_queue:
                self._queue.append(item)
                self._known[key] = item.text_sha256
                self._known_order.append(key)
            # Bounded replay window, not a durable at-most-once guarantee.
            while len(self._known_order) > self.dedup_capacity:
                self._known.pop(self._known_order.popleft(), None)
        return QueueReceipt(True, 'queued_mock_text', len(to_queue))

    async def pop_next(self) -> TTSInput | None:
        async with self._lock:
            while self._queue:
                item = self._queue.popleft()
                if await self._active(item.session_id, item.turn_id, item.generation_id):
                    return item
        return None

    async def discard_stale(self) -> int:
        async with self._lock:
            retained = deque()
            for item in self._queue:
                if await self._active(item.session_id, item.turn_id, item.generation_id):
                    retained.append(item)
            removed = len(self._queue) - len(retained)
            self._queue = retained
            return removed

    @property
    def pending_count(self) -> int:
        return len(self._queue)
~~~~

### automotive_voice/prosody/planner.py

~~~~python
"""Deterministic Turkish clause planner over M04 normalized text.

Protects typed multi-token spans and never converts an unapproved pronunciation.
Punctuation/whitespace splitting is advisory text planning, not acoustic control.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId
from automotive_voice.nlp.normalizer import (NormalizationResult, TurkishAutomotiveNormalizer,
                                            CLOCK, YEAR_MODEL, KM)
from automotive_voice.nlp.lexicon import AutomotiveLexicon, tr_key
from .contracts import (Clause, ClausePlan, PhraseBoundary, SpanKind,
                        BreakKind, PlanStatus)

WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*|[^\s]", re.UNICODE)
NUMBER = frozenset(('sıfır bir iki üç dört beş altı yedi sekiz dokuz on yirmi otuz kırk elli '
                    'altmış yetmiş seksen doksan yüz bin milyon milyar trilyon').split())
MONTHS = frozenset(('ocak şubat mart nisan mayıs haziran temmuz ağustos eylül ekim kasım aralık').split())
ENGINES = frozenset(('tsi tdi tfsi tce dci cdi hdi').split())
MODELS = ('Nissan Qashqai', 'Qashqai', 'Peugeot', 'Citroën', 'Škoda', 'Volkswagen',
          'Passat', 'Kamiq', 'Tiguan', 'Mercedes-Benz')
SUFFIXES = ('da', 'de', 'ta', 'te', 'ya', 'ye')

@dataclass(frozen=True, slots=True)
class PlannerLimits:
    max_words: int = 16
    max_chars: int = 160
    max_clauses: int = 80

    def __post_init__(self):
        for value in (self.max_words, self.max_chars, self.max_clauses):
            if type(value) is not int or value < 1:
                raise ValueError('planner limits must be positive integers')


def _number(value: str, allow_suffix: bool = False) -> bool:
    v = tr_key(value)
    if v in NUMBER:
        return True
    return allow_suffix and any(v == n + s for n in NUMBER for s in SUFFIXES)


def _protected(text: str, lexicon: AutomotiveLexicon, display: str) -> tuple[PhraseBoundary, ...]:
    tokens = list(WORD.finditer(text))
    norm = [tr_key(t.group()) for t in tokens]
    spans: list[PhraseBoundary] = []
    def put(i: int, j: int, kind: SpanKind):
        if 0 <= i < j <= len(tokens):
            spans.append(PhraseBoundary(tokens[i].start(), tokens[j-1].end(), kind, kind.value))

    for i, token in enumerate(norm):
        # Number words + Türk lirası (+ ve ... kuruş), one indivisible currency amount.
        if token == 'türk' and i + 1 < len(norm) and norm[i+1] == 'lirası':
            start = i
            while start > 0 and _number(norm[start-1]):
                start -= 1
            if start != i:
                stop = i + 2
                if stop + 2 < len(norm) and norm[stop] == 've':
                    cursor = stop + 1
                    while cursor < len(norm) and _number(norm[cursor]):
                        cursor += 1
                    if cursor > stop + 1 and cursor < len(norm) and norm[cursor] == 'kuruş':
                        stop = cursor + 1
                put(start, stop, SpanKind.MONEY)
        if token in MONTHS:
            before = i
            while before > 0 and i - before < 3 and _number(norm[before-1]):
                before -= 1
            after = i + 1
            while after < len(norm) and after - i <= 6 and _number(norm[after]):
                after += 1
            if before < i:
                put(before, after, SpanKind.DATE)
        if token == 'saat' and i + 1 < len(norm) and _number(norm[i+1]):
            after = i + 1
            while after < len(norm) and after - i <= 5 and _number(norm[after], allow_suffix=True):
                after += 1
            if after > i + 1:
                put(i, after, SpanKind.TIME)
        if token == 'nokta' and i and i + 2 < len(norm) and _number(norm[i-1]) and _number(norm[i+1]) and tokens[i+2].group().lower() in ENGINES:
            put(i-1, i+3, SpanKind.ENGINE)

    # Known names are protected as spellings only, NEVER rewritten or approved here.
    # Multiword approved lexicon readings are also protected, with no guessed variants.
    names = [(name, SpanKind.MODEL) for name in MODELS]
    names += [(rule.spoken_tr, SpanKind.APPROVED_LEXICON)
              for rule in lexicon.rules if rule.approved and not rule.context]
    for name, kind in names:
        parts = [tr_key(t.group()) for t in WORD.finditer(name)]
        if not parts:
            continue
        for i in range(len(norm) - len(parts) + 1):
            segment = norm[i:i+len(parts)]
            if (segment == parts or (segment[:-1] == parts[:-1] and
                (segment[-1].startswith(parts[-1] + "'") or segment[-1].startswith(parts[-1] + '’')))):
                put(i, i+len(parts), kind)

    # M04 can expand a bare 14:30 into "on dört otuz" without the cue "saat".
    # Recover only syntactically typed, already-normalized source expressions.
    # Never guess an isolated number phrase is a time, distance, or model year.
    renderer = TurkishAutomotiveNormalizer(lexicon=lexicon)
    for pattern, kind in ((CLOCK, SpanKind.TIME), (YEAR_MODEL, SpanKind.MODEL_YEAR),
                          (KM, SpanKind.DISTANCE)):
        for raw in pattern.finditer(display):
            rendered = renderer.normalize(raw.group()).spoken_text
            if rendered != raw.group() and rendered:
                for hit in re.finditer(r'(?<!\w)' + re.escape(rendered) + r'(?!\w)', text, re.I):
                    spans.append(PhraseBoundary(hit.start(), hit.end(), kind, kind.value))

    # Merge overlaps for atomicity; canonical kind prioritizes first discovered.
    spans.sort(key=lambda s: (s.start, -s.end, s.kind.value))
    merged: list[PhraseBoundary] = []
    for s in spans:
        if merged and s.start < merged[-1].end:
            p = merged[-1]
            merged[-1] = PhraseBoundary(p.start, max(p.end, s.end), p.kind, 'overlap_union')
        else:
            merged.append(s)
    return tuple(merged)


class ProsodyClausePlanner:
    def __init__(self, *, lexicon: AutomotiveLexicon | None = None,
                 limits: PlannerLimits | None = None):
        self.lexicon = lexicon or AutomotiveLexicon()
        self.limits = limits or PlannerLimits()

    def plan(self, normalized: NormalizationResult, *, session_id: SessionId,
             turn_id: TurnId, generation_id: GenerationId) -> ClausePlan:
        if not isinstance(normalized, NormalizationResult):
            raise TypeError('M04 NormalizationResult required')
        if not isinstance(session_id, SessionId) or not isinstance(turn_id, TurnId) or not isinstance(generation_id, GenerationId):
            raise TypeError('M01 typed identifiers required')
        text = normalized.spoken_text
        if not text or len(text) > 5000:
            raise ValueError('invalid spoken text length')
        spans = _protected(text, self.lexicon, normalized.display_text)
        tokens = list(WORD.finditer(text))
        # Boundaries must never bisect protected spans or parentheses/quotes.
        protected_inside = lambda pos: any(s.start < pos < s.end for s in spans)
        depth = 0
        candidates: dict[int, BreakKind] = {}
        for m in tokens:
            v = m.group()
            if v in '([{':
                depth += 1
            if v in ')]}':
                depth = max(0, depth - 1)
            if depth == 0 and not protected_inside(m.end()):
                if v in ('.', '?', '!'):
                    candidates[m.end()] = BreakKind.SENTENCE
                elif v in (',', ';', ':'):
                    candidates[m.end()] = BreakKind.PAUSE
        # A chunk is assembled token by token and cut at preferred punctuation,
        # or the last non-protected word boundary within limits.
        clauses: list[Clause] = []
        warnings = list(normalized.warnings)
        i = 0
        while i < len(tokens):
            begin = tokens[i].start()
            j = i
            last_valid: tuple[int, BreakKind] | None = None
            preferred: tuple[int, BreakKind] | None = None
            while j < len(tokens):
                end = tokens[j].end()
                span = text[begin:end]
                words = len(re.findall(r"[^\W_]+(?:['’][^\W_]+)*", span))
                too_long = (len(span) > self.limits.max_chars or words > self.limits.max_words)
                if too_long and last_valid is not None:
                    break
                if not protected_inside(end):
                    kind = candidates.get(end, BreakKind.LIMIT)
                    last_valid = (j, kind)
                    if kind in (BreakKind.SENTENCE, BreakKind.PAUSE):
                        preferred = (j, kind)
                        break
                j += 1
                if too_long and last_valid is None:
                    # One indivisible span can be larger than the limit; keep it
                    # intact but block all TTS until manually reviewed.
                    while j < len(tokens) and protected_inside(tokens[j-1].end()):
                        j += 1
            if preferred is not None:
                cut, kind = preferred
            elif j >= len(tokens):
                cut, kind = len(tokens)-1, BreakKind.FINAL
            elif last_valid is not None:
                cut, kind = last_valid
            else:
                cut, kind = j-1, BreakKind.LIMIT
            if cut < i:
                cut = i
            end = tokens[cut].end()
            content = text[begin:end].strip()
            if len(content) > self.limits.max_chars or len(content.split()) > self.limits.max_words:
                warnings.append('overlong_atomic_span')
            if len(clauses) + 1 > self.limits.max_clauses:
                raise ValueError('too_many_clauses')
            if kind is BreakKind.FINAL:
                pause_ms = 0
            elif kind is BreakKind.SENTENCE:
                pause_ms = 260 if content.endswith('?') else 240
            elif kind is BreakKind.PAUSE:
                pause_ms = 110
            else:
                pause_ms = 80
            hint = ('question' if content.endswith('?') else
                    'continuation' if kind in (BreakKind.PAUSE, BreakKind.LIMIT) else 'statement')
            clauses.append(Clause(len(clauses), begin, end, content, kind, pause_ms, hint))
            i = cut + 1
        if clauses and clauses[-1].break_kind != BreakKind.FINAL:
            last = clauses[-1]
            clauses[-1] = Clause(last.index, last.start, last.end, last.text,
                                 BreakKind.FINAL, 0, 'question' if last.text.endswith('?') else 'statement')
        warnings = tuple(dict.fromkeys(warnings))
        return ClausePlan(session_id, turn_id, generation_id, text,
                          PlanStatus.REVIEW_REQUIRED if normalized.review_required or warnings else PlanStatus.READY,
                          tuple(clauses), spans, warnings)
~~~~

### automotive_voice/readiness/__init__.py

~~~~python
"""M10 real-adapter contracts, all dry-run only."""
~~~~

### automotive_voice/readiness/contracts.py

~~~~python
"""Offline real-adapter configuration capability checks; no socket ever opened."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlsplit
import os
import re

class AdapterType(str,Enum):
    FREYA='freya'
    STT='stt'
    LLM='llm'
    PBX='pbx'

@dataclass(frozen=True)
class AdapterConfig:
    kind: AdapterType
    implementation: str
    endpoint: str | None = None
    model_path: str | None = None
    secret_env: str | None = None
    enabled: bool = False
    timeout_ms: int = 5000
    max_retries: int = 0
    sample_rate_hz: int | None = None
    codec: str | None = None

@dataclass(frozen=True)
class ReadinessResult:
    adapter: str
    ready_for_activation: bool
    dry_run_only: bool
    findings: tuple[str,...]
    def as_dict(self):
        return {'adapter':self.adapter,'ready_for_activation':self.ready_for_activation,
                'dry_run_only':self.dry_run_only,'findings':list(self.findings)}

ALLOWED={
    AdapterType.FREYA:{'freyatts-local'},
    AdapterType.STT:{'whisper-local'},
    AdapterType.LLM:{'ollama-local','openai-compatible'},
    AdapterType.PBX:{'asterisk-websocket','asterisk-audiosocket'},
}

class OfflineReadiness:
    """Config validation only. No resolve, connect, probe, model load or path traversal."""
    @staticmethod
    def check(cfg:AdapterConfig)->ReadinessResult:
        issues=[]
        if not isinstance(cfg,AdapterConfig):raise TypeError('AdapterConfig required')
        if cfg.implementation not in ALLOWED[cfg.kind]:issues.append('implementation_not_allowlisted')
        if type(cfg.timeout_ms) is not int or not 100<=cfg.timeout_ms<=120000:issues.append('invalid_timeout')
        if type(cfg.max_retries) is not int or not 0<=cfg.max_retries<=3:issues.append('invalid_retry_budget')
        if cfg.kind in (AdapterType.FREYA,AdapterType.STT):
            if cfg.model_path is None or not Path(cfg.model_path).is_absolute():issues.append('absolute_model_path_required')
            elif not Path(cfg.model_path).is_dir():issues.append('model_directory_missing')
        if cfg.kind in (AdapterType.LLM,AdapterType.PBX):
            if not cfg.endpoint:issues.append('endpoint_required')
            else:
                u=urlsplit(cfg.endpoint)
                if u.scheme not in ('http','https','ws','wss') or not u.hostname or u.username or u.password or u.fragment:
                    issues.append('unsafe_endpoint')
                if u.hostname and u.hostname not in ('localhost','127.0.0.1','::1'):
                    issues.append('external_endpoint_not_tested')
                if u.scheme in ('http','ws') and u.hostname not in ('localhost','127.0.0.1','::1'):
                    issues.append('unencrypted_remote_transport')
        if cfg.kind==AdapterType.PBX:
            if cfg.codec not in ('slin8','slin16','ulaw','alaw','g722'):
                issues.append('unsupported_pbx_codec')
            if cfg.sample_rate_hz not in (8000,16000):issues.append('unsupported_pbx_sample_rate')
            if cfg.codec in ('ulaw','alaw') and cfg.sample_rate_hz!=8000:issues.append('codec_sample_rate_mismatch')
            if cfg.codec=='g722' and cfg.sample_rate_hz!=16000:issues.append('codec_sample_rate_mismatch')
        if cfg.secret_env:
            if not re.fullmatch(r'[A-Z][A-Z0-9_]{2,63}',cfg.secret_env):
                issues.append('invalid_secret_env_name')
            elif cfg.enabled and not os.environ.get(cfg.secret_env):
                issues.append('secret_missing_in_environment')
        if cfg.enabled:
            issues.append('real_activation_explicitly_disabled_in_M10')
        # Not even a clean local config counts as a verified real connection.
        return ReadinessResult(cfg.kind.value,False,True,tuple(dict.fromkeys(issues)))

    @classmethod
    def evaluate(cls, configs:list[AdapterConfig])->dict:
        kinds=[c.kind for c in configs]
        if len(kinds)!=4 or len(set(kinds))!=4:raise ValueError('exactly one config for each of four adapters')
        results=[cls.check(c) for c in configs]
        return {'mode':'M10_DRY_RUN','external_connections':0,'audio_bytes':0,'production_ready':False,
                'adapters':[r.as_dict() for r in results]}
~~~~

### automotive_voice/readiness/presentation.py

~~~~python
"""Evidence-preserving M03 display-to-speech adapter.

Keeps source response intact for display/audit and supplies separate safe speech.
Only fixed policy categories are allowed. Unreviewed brand readings remain gated.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import re
from automotive_voice.dialogue.storage import StoredResponse

@dataclass(frozen=True)
class SpeechCandidate:
    display_text: str
    speech_text: str
    rewritten: bool
    warnings: tuple[str,...] = ()

class PolicySpeechPresenter:
    PRICE=re.compile(r'(?<![\w])([0-9]{1,3}(?:\.[0-9]{3})+|[0-9]+) Türk lirasıdır\.')
    OFFER=re.compile(r'^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[+-][0-9]{2}:[0-9]{2}) tarihinde, ([A-Z_]{2,40}) lokasyonunda ')
    ID_REF=re.compile(r'(?<!\w)(?:Onay referansı|Referans|Takip referansı):\s*([\w-]{1,100})\.')
    KNOWN_LOCATIONS={'TRABZON':'Trabzon'}

    def render(self,response:StoredResponse)->SpeechCandidate:
        source=response.text
        text=source
        warnings=[]
        if response.category=='price_verified':
            text,count=self.PRICE.subn(lambda m:m.group(1)+' TL.',text)
            if count!=1:warnings.append('price_format_requires_review')
        elif response.category=='offer_confirmation':
            match=self.OFFER.search(text)
            if match:
                try:
                    dt=datetime.fromisoformat(match.group(1))
                    if dt.tzinfo is None:raise ValueError('timezone required')
                    loc=self.KNOWN_LOCATIONS.get(match.group(2))
                    if not loc:raise ValueError('unmapped location')
                    rendered=f'{dt.day:02d}.{dt.month:02d}.{dt.year} tarihinde, saat {dt.hour:02d}:{dt.minute:02d} için {loc} servis noktasında '
                    text=rendered+text[match.end():].replace('ekspertiz için müsaitlik','ekspertiz müsaitliği',1)
                except ValueError:
                    warnings.append('slot_display_requires_review')
            else:warnings.append('slot_display_requires_review')
        elif response.category in ('booking_confirmed','booking_reconciled','already_confirmed',
                                   'crm_case_created'):
            # Hide opaque identifiers in *speech* but preserve in display.
            text,count=self.ID_REF.subn('Referans bilgisi operatör ekranında görüntüleniyor.',text)
            if count!=1:warnings.append('opaque_reference_requires_review')
        return SpeechCandidate(source,text,text!=source,tuple(warnings))
~~~~

### automotive_voice/resilience/__init__.py

~~~~python
"""M10 durable control plane. No real media or external network."""
~~~~

### automotive_voice/resilience/durable.py

~~~~python
"""SQLite-authoritative session transitions and at-least-once event outbox.

No network, no production automatic recovery. New process fails open calls closed:
nonterminal sessions become FAILED or ENDED and are never resumed. M02 runtime,
booking confirmation, flush ACK and effect queues are NOT recoverable here.
"""
from __future__ import annotations
from collections import deque
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from automotive_voice.core.session import Session, State
from automotive_voice.core.session_manager import (SessionManager, SessionSnapshot, _ManagedSession,
    SessionAlreadyExistsError, SessionOutboxFullError)
from automotive_voice.core.identifiers import SessionId, TurnId, GenerationId
from automotive_voice.core.events import EventEnvelope, EventType

TERMINAL = (State.ENDED, State.FAILED, State.HANDOFF)

class DurableConflict(RuntimeError):
    pass

class DurableJournal:
    """Single-process connection, SQLite WAL, synchronous FULL, atomic snapshots+outbox."""
    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(str(path), timeout=5, isolation_level=None)
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY, state TEXT NOT NULL, turn_id INTEGER NOT NULL,
            generation_id INTEGER NOT NULL, last_sequence INTEGER NOT NULL,
            recovery_required INTEGER NOT NULL DEFAULT 0
          );
          CREATE TABLE IF NOT EXISTS outbox (
            session_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL UNIQUE,
            envelope TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('pending','acked')),
            PRIMARY KEY (session_id, sequence),
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
          );
          CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox (status,session_id,sequence);
        ''')

    def close(self):
        self.db.close()

    def insert_session(self, sid: SessionId):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('INSERT INTO sessions VALUES (?, ?, 0, 0, -1, 0)', (str(sid), State.IDLE.value))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def append(self, new: Session, previous: Session, expected_seq: int,
               events: list[EventEnvelope], *, recovery: bool=False):
        """CAS, monotonic counters, contiguous events; all or nothing."""
        if not events or any(e.session_id != new.session_id for e in events):
            raise DurableConflict('event scope missing')
        if any(e.sequence != expected_seq + i + 1 for i,e in enumerate(events)):
            raise DurableConflict('noncontiguous event sequence')
        # The journal must never retain raw customer text or audio. Even safe event
        # payloads should carry opaque refs and diagnostic codes only.
        prohibited={'transcript','raw_text','customer_name','phone_number','email',
                    'vin','audio_bytes','recording','customer_address'}
        def has_sensitive_key(value):
            if isinstance(value,dict):
                return any(str(k).lower() in prohibited or has_sensitive_key(v) for k,v in value.items())
            if isinstance(value,list):return any(has_sensitive_key(v) for v in value)
            return False
        if any(has_sensitive_key(e.to_dict()['payload']) for e in events):
            raise DurableConflict('sensitive_payload_key_rejected')
        if new.turn_id < previous.turn_id or new.generation_id < previous.generation_id:
            raise DurableConflict('turn or generation regression')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT state,turn_id,generation_id,last_sequence,recovery_required FROM sessions WHERE session_id=?', (new.session_id,)).fetchone()
            if row is None or row[:4] != (previous.state.value,previous.turn_id,previous.generation_id,expected_seq):
                raise DurableConflict('stale snapshot or changed sequence')
            if row[4] and not recovery:
                raise DurableConflict('session recovery hold')
            result=self.db.execute('UPDATE sessions SET state=?,turn_id=?,generation_id=?,last_sequence=?,recovery_required=? WHERE session_id=?',
                (new.state.value,new.turn_id,new.generation_id,events[-1].sequence,int(bool(row[4] or recovery)),new.session_id))
            if result.rowcount!=1:raise DurableConflict('lost update')
            for e in events:
                self.db.execute('INSERT INTO outbox VALUES (?,?,?,?,?)',
                    (str(e.session_id),e.sequence,e.event_id,json.dumps(e.to_dict(),sort_keys=True,ensure_ascii=False), 'pending'))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def read_all(self):
        rows=self.db.execute('SELECT session_id,state,turn_id,generation_id,last_sequence,recovery_required FROM sessions ORDER BY session_id').fetchall()
        for sid,st,turn,gen,seq,hold in rows:
            events=[EventEnvelope.from_dict(json.loads(r[0])) for r in
                self.db.execute("SELECT envelope FROM outbox WHERE session_id=? AND status='pending' ORDER BY sequence", (sid,)).fetchall()]
            acked=self.db.execute("SELECT MAX(sequence) FROM outbox WHERE session_id=? AND status='acked'",(sid,)).fetchone()[0]
            yield (sid, State(st),turn,gen,seq,bool(hold),events,acked if acked is not None else -1)

    def ack(self, sid: str, sequence: int):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT status FROM outbox WHERE session_id=? AND sequence=?',(sid,sequence)).fetchone()
            if row is None or row[0]!='pending':raise DurableConflict('event not pending')
            earlier=self.db.execute("SELECT 1 FROM outbox WHERE session_id=? AND sequence<? AND status='pending' LIMIT 1",
                                    (sid,sequence)).fetchone()
            if earlier:raise DurableConflict('earlier_event_unacknowledged')
            self.db.execute("UPDATE outbox SET status='acked' WHERE session_id=? AND sequence=?",(sid,sequence))
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def counts(self) -> dict:
        sessions=self.db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
        pending=self.db.execute("SELECT COUNT(*) FROM outbox WHERE status='pending'").fetchone()[0]
        recovery=self.db.execute('SELECT COUNT(*) FROM sessions WHERE recovery_required=1').fetchone()[0]
        return {'sessions':sessions,'pending_outbox':pending,'recovery_holds':recovery}


class DurableSessionManager(SessionManager):
    """M01 public API with durable commit before memory mutation.

    Must call await restore_fail_closed() on a new manager BEFORE receiving events.
    This intentionally ends abandoned sessions; M02 and external tool effects are
    never automatically reissued across restart.
    """
    def __init__(self, bus, journal: DurableJournal, max_pending_events: int=256):
        super().__init__(bus,max_pending_events)
        self.journal=journal
        self._restored=False

    async def restore_fail_closed(self) -> int:
        async with self._directory_lock:
            if self._restored: return 0
            recovered=0
            for sid,st,turn,gen,seq,hold,events,acked in list(self.journal.read_all()):
                managed=_ManagedSession(Session(sid,state=st,turn_id=turn,generation_id=gen))
                managed.last_sequence=seq
                managed.outbox=deque(events)
                if st in TERMINAL:managed.cancellation.cancel_current()
                elif gen:managed.cancellation.advance(GenerationId(gen))
                self._sessions[SessionId(sid)]=managed
                # Fresh bus must start from last durably ACKed sequence, not -1.
                self.bus._last_sequence[sid]=acked
                if st not in (State.ENDED,State.FAILED):
                    old=replace(managed.value, history=list(managed.value.history))
                    new=replace(old, history=list(old.history))
                    target=State.ENDED if st==State.IDLE else State.FAILED
                    new.move(target)
                    e=EventEnvelope.create(EventType.SESSION_ENDED if target==State.ENDED else EventType.SESSION_FAILED,
                        SessionId(sid),TurnId(turn),GenerationId(gen),seq+1,{'code':'unclean_restart','requires_manual_reconcile':True})
                    self.journal.append(new,old,seq,[e],recovery=True)
                    managed.value=new
                    managed.last_sequence+=1
                    managed.outbox.append(e)
                    managed.cancellation.cancel_current()
                    recovered+=1
            self._restored=True
            return recovered

    async def create(self,session_id: str|None=None)->SessionSnapshot:
        if not self._restored:raise RuntimeError('restore_fail_closed first')
        sid=SessionId.new() if session_id is None else SessionId(session_id)
        async with self._directory_lock:
            if sid in self._sessions:raise SessionAlreadyExistsError(str(sid))
            self.journal.insert_session(sid)
            m=_ManagedSession(Session(sid))
            self._sessions[sid]=m
            return self._snapshot(m)

    async def _apply(self,session_id,event_type,mutation,payload=None,*,idempotent_ended=False):
        m=self._entry(session_id)
        async with m.lock:
            if idempotent_ended and m.value.state==State.ENDED:return self._snapshot(m)
            if len(m.outbox)>=self._pending_limit:raise SessionOutboxFullError('durable outbox full')
            old=m.value
            new=replace(old,history=list(old.history))
            old_gen=new.generation_id
            mutation(new)
            event=EventEnvelope.create(event_type,SessionId(new.session_id),TurnId(new.turn_id),
                GenerationId(new.generation_id),m.last_sequence+1,payload or {})
            self.journal.append(new,old,m.last_sequence,[event])
            m.value=new; m.last_sequence+=1;m.outbox.append(event)
            if new.state in TERMINAL:m.cancellation.cancel_current()
            elif new.generation_id>old_gen:m.cancellation.advance(GenerationId(new.generation_id))
            return self._snapshot(m)

    async def complete_interrupt_with_followup(self,session_id:str,followup:str|None=None):
        if followup not in (None,'turn','handoff'):raise ValueError('invalid followup')
        m=self._entry(session_id)
        async with m.lock:
            n=1+int(followup is not None)
            if len(m.outbox)+n>self._pending_limit:raise SessionOutboxFullError('outbox full')
            old=m.value;new=replace(old,history=list(old.history))
            if new.state!=State.INTERRUPTING:raise ValueError('not interrupting')
            new.move(State.LISTENING)
            first=EventEnvelope.create(EventType.INTERRUPTION_COMPLETED,SessionId(new.session_id),
                TurnId(new.turn_id),GenerationId(new.generation_id),m.last_sequence+1,
                {'to':'LISTENING','transport_ack':True})
            events=[first]
            if followup=='turn':
                new.new_turn()
                events.append(EventEnvelope.create(EventType.TURN_STARTED,SessionId(new.session_id),
                    TurnId(new.turn_id),GenerationId(new.generation_id),m.last_sequence+2,
                    {'to':'THINKING','source':'deferred_transcript'}))
            elif followup=='handoff':
                new.move(State.HANDOFF)
                events.append(EventEnvelope.create(EventType.HANDOFF_REQUESTED,SessionId(new.session_id),
                    TurnId(new.turn_id),GenerationId(new.generation_id),m.last_sequence+2,
                    {'to':'HANDOFF','source':'deferred_handoff'}))
            self.journal.append(new,old,m.last_sequence,events)
            m.value=new;m.last_sequence+=len(events);m.outbox.extend(events)
            if new.state in TERMINAL:m.cancellation.cancel_current()
            elif new.generation_id>old.generation_id:m.cancellation.advance(GenerationId(new.generation_id))
            return self._snapshot(m)

    async def emergency_close(self,session_id:str,*,fail:bool=False):
        m=self._entry(session_id)
        async with m.lock:
            if m.value.state in (State.ENDED,State.FAILED):return self._snapshot(m)
            old=m.value;new=replace(old,history=list(old.history))
            target=State.FAILED if fail and new.state!=State.IDLE else State.ENDED
            new.move(target)
            e=EventEnvelope.create(EventType.SESSION_FAILED if target==State.FAILED else EventType.SESSION_ENDED,
                SessionId(new.session_id),TurnId(new.turn_id),GenerationId(new.generation_id),
                m.last_sequence+1,{'code':'emergency_close','forced':True})
            self.journal.append(new,old,m.last_sequence,[e],recovery=True)
            m.value=new;m.last_sequence+=1;m.outbox.append(e);m.cancellation.cancel_current()
            return self._snapshot(m)

    async def dispatch_pending(self,session_id:str)->int:
        m=self._entry(session_id)
        count=0
        async with m.lock:
            while m.outbox:
                e=m.outbox[0]
                await self.bus.publish(e)
                # If process dies here, duplicate replay is possible. Consumers MUST dedup by event_id.
                self.journal.ack(session_id,e.sequence)
                m.outbox.popleft();count+=1
        return count
~~~~

### automotive_voice/telephony/__init__.py

~~~~python
from .transport import FakeTransport, FakeTransportStats, TransportPort, AsteriskCommandEncoder
__all__=['FakeTransport','FakeTransportStats','TransportPort','AsteriskCommandEncoder']
~~~~

### automotive_voice/telephony/transport.py

~~~~python
"""M06 transport ports: fake-only behavior; Asterisk JSON is a dry-run encoder.

Sending FLUSH_MEDIA is not evidence of PBX-side completion. No real sockets.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
from collections import deque
from automotive_voice.audio.contracts import AudioChunkMetadata, FlushRequest, FlushAck

class TransportPort(Protocol):
    async def send_metadata(self, chunk: AudioChunkMetadata) -> bool: ...
    async def request_flush(self, request: FlushRequest) -> None: ...

@dataclass(frozen=True, slots=True)
class FakeTransportStats:
    sent: int
    queued_at_transport: int
    paused: bool

class FakeTransport:
    """Explicit synthetic playback queue; confirm_flush() models a fake ACK."""
    def __init__(self, *, max_items: int = 128, adapter_id: str = 'fake-asterisk'):
        if type(max_items) is not int or max_items < 1: raise ValueError('max_items must be positive')
        self.max_items=max_items;self.adapter_id=adapter_id
        self._media: dict[str,deque[AudioChunkMetadata]]={}
        self._pending: dict[str,FlushRequest]={}
        self._xoff: set[str]=set()
        self._closed: set[str]=set()
        self._confirmed: dict[str,FlushAck]={}
        self._sent=0

    async def send_metadata(self,chunk:AudioChunkMetadata)->bool:
        sid=str(chunk.session_id)
        if not isinstance(chunk,AudioChunkMetadata):raise TypeError('AudioChunkMetadata required')
        if sid in self._xoff or sid in self._closed or sid in self._pending: return False
        q=self._media.setdefault(sid,deque())
        if len(q)>=self.max_items:return False
        q.append(chunk);self._sent+=1
        return True

    async def request_flush(self,request:FlushRequest)->None:
        sid=str(request.session_id)
        if sid in self._pending:
            if self._pending[sid]!=request: raise ValueError('concurrent or conflicting flush')
            return
        self._pending[sid]=request

    async def confirm_flush(self,sid:str,request_id:str)->FlushAck | None:
        """Explicit test-only proof; does NOT represent PBX confirmation."""
        request=self._pending.get(sid)
        if request is None or request.flush_request_id != request_id:return None
        self._media.setdefault(sid,deque()).clear()
        self._pending.pop(sid)
        ack=FlushAck(request.flush_request_id,request.session_id,request.turn_id,
                     request.generation_id,self.adapter_id,True,'fake')
        self._confirmed[request.flush_request_id]=ack
        return ack

    def has_confirmed(self,ack:FlushAck)->bool:
        return self._confirmed.get(ack.flush_request_id)==ack
    def consume_confirmation(self,ack:FlushAck)->None:
        if not self.has_confirmed(ack):raise ValueError('ACK not issued by this fake transport')
        self._confirmed.pop(ack.flush_request_id,None)
    def xoff(self,sid:str):self._xoff.add(sid)
    def xon(self,sid:str):
        if sid not in self._pending and sid not in self._closed:self._xoff.discard(sid)
    def can_send(self,sid:str)->bool:
        return sid not in self._xoff and sid not in self._closed and sid not in self._pending and len(self._media.get(sid,())) < self.max_items
    def stats(self,sid:str)->FakeTransportStats:
        return FakeTransportStats(self._sent,len(self._media.get(sid,())),sid in self._xoff or sid in self._closed or sid in self._pending)
    async def terminate(self,sid:str):
        self._media.setdefault(sid,deque()).clear()
        self._pending.pop(sid,None);self._xoff.add(sid);self._closed.add(sid)
        for key,ack in list(self._confirmed.items()):
            if str(ack.session_id)==sid:self._confirmed.pop(key,None)

class AsteriskCommandEncoder:
    """Validate/format commands only. Does not open a connection or acknowledge anything.

    Requires chan_websocket with JSON support (not all Asterisk builds).
    FLUSH_MEDIA may not emit a generic explicit ACK on every version. A later
    real adapter must verify version-specific correlation/queue-drain semantics.
    """
    @staticmethod
    def flush_json(request:FlushRequest)->dict:
        if not isinstance(request,FlushRequest):raise TypeError('FlushRequest required')
        return {'command':'FLUSH_MEDIA','correlation_id':request.flush_request_id}

    @staticmethod
    def hangup_json()->dict:
        return {'command':'HANGUP'}
~~~~
