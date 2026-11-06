# Freya Otomotiv Asistanı

## Çalışma sınırı

Windows üzerinde FastAPI (127.0.0.1:8000), Ollama (127.0.0.1:11434) ve yerel modeller çalışır. Asterisk ayrı Linux ortamındadır. İlk kurulum model indirir; görüşme sırasında harici STT/LLM hizmeti kullanılmaz. Model önbelleği hazırlanırsa HF_HUB_OFFLINE=1 ile çalıştırılabilir.

## Bileşenler

- `backend/db.py`: SQLite, yabancı anahtarlar, WAL, kayıt modelleri ve atomik randevu işlemi. Slot tekilliği yarış koşullarında da uygulanır. Ücret kuruş olarak tutulur.
- `backend/text.py`: Türkçe tarih, telefon ve plaka ön işlemesi; PoC’deki otomotiv normalizasyonu; yapılandırılabilir sözlük ve güvenli yan cümle sınırları. Desteklenmeyen semboller hata üretir. Bu katman genel amaçlı bir Türkçe morfoloji motoru değildir.
- `backend/models.py`: FreyaTTS, faster-whisper, Silero ve Ollama adaptörleri. FreyaTTS’nin sabitlenmiş sürümündeki `_synth_one` API’si kullanılır; dahili normalizasyon tekrar çalıştırılmaz. Ses kimliği için seed 9 korunur; sessiz çıktıda başka sese geçilmez.
- `backend/session.py`: Tek aktif görüşme, 16 kHz giriş, VAD, STT, transkript, tur kimlikleri, iptal ve ses oynatma. Sentez kuyruğu en fazla iki iş alır. CUDA işi iptal edilemese de eski tur oynatılamaz.
- `backend/dialogue.py`: LLM’den şemalı alan çıkarımı; backend tarafından yürütülen randevu durum makinesi. LLM’nin veritabanı araçlarına doğrudan erişimi yoktur. Seçenekler o anda kayıtlı araç ve müsait saatlerden gelir.
- `backend/telephony.py`: AudioSocket UUID ve paket ayrıştırma; tam çift yönlü 8 kHz PCM16. Her ses paketi 20 ms’dir. Alıcı TCP paket sınırlarına güvenmez.
- `frontend`: React yönetim paneli. AudioWorklet mikrofon yakalar. Mikrofon ve asistan oynatması ayrı AudioContext kullanır; kullanıcı araya girdiğinde mikrofon çalışmaya devam eder.

## Güvenlik ve veri

Yönetici adı `admin`, parola `.env` dosyasındadır. REST erişimi HTTP Basic ile korunur; varsayılan adres yalnızca localhost’tur. Uzak erişim için HTTPS ters vekili gerekir. WebSocket biletleri tek kullanımlık ve 30 saniyeliktir. AudioSocket şifreli değildir; yalnızca güvenilir özel ağda ve IP izin listesiyle kullanılır.

UTC tarihler veritabanına ISO 8601 olarak yazılır; arayüz İstanbul saatini gösterir. Transkript görüşme silinince kademeli silinir. Ham giriş sesi varsayılan kapalıdır; açılırsa WAV kayıtları retention süresi sonunda temizlenir. Yapılandırılmış ses kaydı tüm giriş kanalını içerir; kullanıcıya uygun bilgilendirme yapılmalıdır.

## API ve medya sözleşmesi

OpenAPI: `/docs`. Sağlık: `/api/health`; ayrıntılı hazırlık: `/api/readiness`. Model yükleme: `POST /api/models/load`. Metin: `POST /api/normalize`, `POST /api/synthesize`. Veri: `vehicles`, `quotes`, `slots`, `appointments`, `conversations` kaynakları `/api` altındadır.

`POST /api/session-ticket` sonrası `/ws/voice?ticket=...` açılır. İlk JSON: `{"sample_rate":48000,"encoding":"pcm_s16le","channels":1}`. Giriş hızı 8000/16000/24000/44100/48000 olabilir. Sonraki ikili mesajlar little-endian PCM16’dır. Sunucu 16 kHz mono PCM16 gönderir; JSON olayları `session`, `transcript`, `status`, `playback`, `metrics`, `error`, `completed` tiplerindedir. `playback` pause/resume/flush ile istemci oynatma kuyruğunu yönetir.

AudioSocket 0x10: 8 kHz, 16 bit mono, little-endian; başlık uzunluğu big-endian. UUID 16 bayttır; Asterisk UNIQUEID yerine gerçek UUID gerekir. Son kısa çerçeve sıfırla tamamlanır. Saat kaçırıldığında telafi paketi yağmuru oluşturulmaz.

## Ölçümlerin anlamı

`model_load_ms` ses modelleri ve Ollama ısıtmasını kapsar. `llm_first_token_ms` ve `llm_total_ms` gerçek HTTP akışından ölçülür. `stt_ms` tanıma süresidir. `endpoint_ms` son sesli VAD bloğundan sonlandırmaya kadar geçen süredir. `first_audio_ms` son sesli bloktan ilk sesin sunucuda hazır olmasına kadardır; ağ ve tarayıcı/PBX oynatma gecikmesi buna dahil değildir. `barge_in_signal_ms` durdurma sinyalinin gönderilme süresidir; karşı uçta sesin duyulur biçimde kesildiğini tek başına kanıtlamaz. Yan cümleler sınırlı kuyrukla önden sentezlenir; ilk parça oynarken sonraki parça hazırlanır.

## Sınırlar

Tek aktif görüşme desteklenir. Müşterinin açık onayı olmadan kayıt yapılmaz. Randevu yalnızca sunulan seçenek numarasından seçilir; serbest takvim tarihi pazarlığı ilk sürümde yoktur. Mevcut veritabanına kaydedilmemiş araç için işlem yapılmaz. Takip kaydı oluşturulur, dış bir çalışana bildirim gönderilmez. İnce ayar, giden çağrı ve dış CRM bu sürümde yoktur.

Yan cümle içinde token seviyesinde TTS yoktur. LLM akışı şemalı alan çıkarımı içindir; JSON tamamlanıp doğrulandıktan sonra backend yanıt üretir. Gecikme azaltımı için doğrulanmamış işlem sonucunu erken seslendirme yapılmaz.
