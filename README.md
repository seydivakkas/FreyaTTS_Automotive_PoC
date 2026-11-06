# Freya • Yerel otomotiv sesli asistanı

M01–M11 ZIP kaynakları güncel M11 sürümü temel alınarak entegre edildi. Canlı bağlantılar, arşiv karmaları ve kapsam: [M01–M11 entegrasyon kaydı](docs/milestones/INTEGRATION.md). Paneldeki **M01–M11** sekmesi sözleşme, telaffuz ve kalıcı olay incelemesini sunar.

Türkçe ekspertiz randevusu için yerel STT → Ollama → FreyaTTS uygulaması. Web mikrofonu ve Asterisk AudioSocket aynı görüşme motorunu kullanır. Araç ve fiyat kayıtları, müsait saatler, randevular, transkriptler ve ses laboratuvarı Türkçe yönetim panelindedir.

## Kurulum ve başlatma

Windows PowerShell, Git, Node.js 22+, `uv`, Ollama ve NVIDIA sürücüsü gerekir. Python 3.11 `uv` tarafından hazırlanır. İlk kurulum CUDA PyTorch dahil birkaç GB indirebilir.

```powershell
.\scripts\setup.ps1
.\scripts\prepare_models.ps1
.\scripts\start.ps1
```

Panel: http://127.0.0.1:8000 — kullanıcı `admin`; oluşturulan parola `.env` içindeki `ADMIN_PASSWORD` değeridir. Parola konsola yazdırılmaz. API belgeleri: http://127.0.0.1:8000/docs. Panelde **Sistem → Modelleri yükle** ile çalışan sunucuya ses modellerini yükleyin. Hazırlama betiği önbelleği doldurur; kendi süreci kapanınca modelleri bellekte tutmaz.

Kurulum FreyaTTS kaynaklarını proje içindeki `vendor/FreyaTTS` dizinine alır ve `146d36c1cb6660646be57d31339db4eed9315de3` sürümünü kullanır. Masaüstündeki başka bir FreyaTTS klasörüne ihtiyaç yoktur. Python bağımlılıklarının otoritesi `uv.lock`, arayüzün otoritesi `frontend/package-lock.json` dosyasıdır. `requirements.txt` dış araçlar için kilitten dışa aktarılmıştır; CUDA indisiyle kurulum için `uv` önerilir.

## İlk randevu

1. **Araçlar ve fiyatlar** bölümünden gerçek araç kaydını ve varsa ekspertiz fiyatını girin. Fiyatın anlamı araç satış değeri değildir; ekspertiz hizmet bedelidir.
2. **Randevular** bölümünde gelecekteki müsait saatleri ekleyin. Tarihler İstanbul saatidir.
3. **Görüşme** bölümünden mikrofonu başlatın. Adınızı ve kayıtlı marka/modeli söyleyin.
4. Sunulan seçenek numarasını söyleyin. Son teyitte **“Evet, onaylıyorum.”** diyerek kaydı tamamlayın.

Başlangıçta veritabanı boştur; örnek fiyat veya müşteri otomatik oluşturulmaz. Fiyat yoksa asistan bunu söyler. Ölçüm yoksa analitik ekranı `0` yerine `—` gösterir.

Sunum için örnek veri ayrı tutulur: `.venv\Scripts\python scripts\seed_demo_telemetry.py` yalnızca `data/demo/` altına yazar, `.\scripts\start_demo.ps1` veya `BASLAT.bat --demo` paneli bu veriyle açar. Demo modunda her ekranda uyarı bandı görünür. Demo gecikme değerleri gerçek ölçüm değildir, performans kanıtı olarak kullanılamaz. Mikrofon için localhost veya HTTPS gerekir. Echo cancellation etkindir; hoparlör geri beslemesini azaltmak için kulaklıkla deneyin.

## Çalışma ve telefon

Varsayılan profil: FreyaTTS CUDA, faster-whisper `large-v3-turbo` CUDA/float16, Ollama `qwen2.5:7b` sekiz GPU katmanı, tek görüşme. 8 GB VRAM'li RTX 4070'te tüm modeller yüklü ve aynı anda çalışırken tepe kullanım 7.478 MiB ölçüldü (bunun yaklaşık 1.770 MiB'ı masaüstü uygulamalarıydı); VRAM kullanan başka uygulamalar kapalı tutulmalıdır. VRAM yetmezse `STT_MODEL=small`, `STT_DEVICE=cpu`, `STT_COMPUTE_TYPE=int8` ile daha düşük doğrulukla CPU'ya dönülebilir. `.env` ayarlarıyla değiştirilebilir. Model veya donanım hataları hazırlık ekranında görünür; yapay ses veya sahte ölçümle değiştirilmez.

Asterisk Linux’ta çalışmalıdır. `asterisk/extensions.conf` içindeki 700 dahili örneğini mevcut dialplan’a ekleyin. Asterisk’ten ulaşılabilen Windows adresini, `AUDIOSOCKET_HOST` ve `PBX_ALLOWED_IPS` değerlerini birlikte yapılandırın. Uzak santral için Windows güvenlik duvarında yalnızca santral IP’sine TCP 9092 açın. 8 kHz PCM16 için `slin16` codec adını kullanmayın; bu ad 16 kHz anlamına gelir. UUID üretimi için `func_uuid`, medya için `app_audiosocket` modülleri gerekir.

## Doğrulama

```powershell
.venv\Scripts\python -m pytest -q --basetemp=data/pytest
.venv\Scripts\python -m scripts.smoke_dialogue
.venv\Scripts\python -m scripts.benchmark
.venv\Scripts\python -m scripts.voice_acceptance
.venv\Scripts\python -m scripts.acoustic_benchmark
cd frontend
npm run build
npx playwright install chromium
npx playwright test
```

`smoke_dialogue` gerçek Ollama’yı ve `data/dialogue-smoke/` altında her çalıştırmada ayrı test veritabanını kullanır; işletim verilerini değiştirmez. `benchmark` gerçek TTS/STT çalıştırır; `data/benchmark` altında 48/8 kHz WAV ve JSON ölçümleri üretir. `voice_acceptance`, ayrı veritabanı ve 8011 portuyla gerçek modelleri tarayıcıdaki sanal mikrofon üzerinden sınar; girdiler gerçek FreyaTTS ile üretilir. İnsan mikrofon kaydı ve telefon hattındaki kalite ayrıca dinlenmelidir. `acoustic_benchmark` gerçek TTS sesini telefon hattı dönüşümünden geçirip STT ile geri tanır; sonuç `data/acoustic/latest.json` dosyasına yazılır ve Kalite Kapısı 5 bunu okur. WER/CER ve terim doğruluğu TTS ile STT'nin birleşik sonucudur. ABX ve MOS ölçülmez, bu yüzden kapı `HOLD` veya `FAIL` verir, `PASS` veremez. F0 sapması için sesleri dinleyip onayladıktan sonra `--save-baseline` ile taban kayıt alın. Bu komutlar taklit model kullanmaz. Birim testleri için modeller gerekmez. `pytest`, `tests/conftest.py` sayesinde işletim veritabanına ve `data/` altındaki çalışma dosyalarına yazmaz; `DATABASE_URL` ve `DATA_DIR` geçici klasöre yönlendirilir, yönlendirme kurulamazsa testler başlamaz.

Geliştirme: backend’i başlatıp `frontend` altında `npm run dev` çalıştırın. Arayüz değişikliklerinden sonra tek portlu sunum için `npm run build` gerekir. Yedek almadan migration downgrade çalıştırmayın; sürüm düşürme tabloları siler.

Mimari ve protokol: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Doğrulama kanıtları ve kalan sınırlar: [docs/VERIFICATION.md](docs/VERIFICATION.md).

Eski `automotive_freya_poc.py`, `run_poc.bat`, örnek WAV dosyaları ve eski test çıktısı karşılaştırma için `archive/` klasöründe korunmuştur. Eski çıktı dosyası yeni uygulamanın doğrulama raporu değildir.

