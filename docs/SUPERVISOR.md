# Supervisor ve niyet yönlendirici V1

Web görüşmesinde final ASR metni, 22 niyetli katalog ve deterministik politika üzerinden değerlendirilir. Güvenlik ve açık temsilci isteği kuralları önce çalışır. Model önerileri yazma, acil durum veya insan aktarımı yetkisi vermez. Niyetler, henüz doğrulanmamış slotlar ve uygulama adımları ayrı nesnelerdir.

## Entegrasyon noktaları

| Katman | Kod yolu | Bağlantı |
| --- | --- | --- |
| Ses turu | `backend/session.py`, `backend/audio.py`, `backend/models.py` | Silero turu sonlandırır, faster-whisper final metni çıkarır. Supervisor yalnızca web oturumunda final metni alır. Yanıt mevcut FreyaTTS ve ses kuyruğuyla seslendirilir. |
| Diyalog ve takvim | `backend/dialogue.py`, `backend/db.py` | Mevcut randevu durum makinesi varsayılan ses yoludur. Guarded mod aynı SQLite takvimindeki boşluğu yalnızca okur. |
| Telefon | `backend/audiosocket_server.py`, `backend/ami.py`, `asterisk/extensions.conf` | Mevcut AudioSocket/AMI zinciri Supervisor V1'e bağlanmadı. |
| Supervisor | `backend/supervisor/` | Katalog, kural katmanı, bağlam, plan, araç erişimi, iz ve çevrimdışı eğitim ayrıdır. |
| Kalite | `backend/qa_telemetry_operator.py`, `backend/supervisor/quality.py` | Mevcut telemetri ses kalitesini izler. Depoda bağımsız FQICI sistemi bulunmadığı için niyet incelemesi yerel iz ve operatör onayıyla sağlanır. |
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
