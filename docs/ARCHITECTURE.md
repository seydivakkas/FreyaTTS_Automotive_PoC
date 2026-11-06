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
