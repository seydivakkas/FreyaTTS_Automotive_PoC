# Kurulum, doğrulama ve kayıtlı sınırlar

Aşağıdaki bölümler sürümün proje içi belgeleridir. İçlerindeki kaynak yolları eski depo düzenini gösterir. Ölçümler önceki çalıştırmalara aittir.

## Kaynak belge · README.md

# Freya • Yerel otomotiv sesli asistanı

![License: All Rights Reserved](https://img.shields.io/badge/license-All%20Rights%20Reserved-red?style=flat-square)

M01–M11 ZIP kaynakları güncel M11 sürümü temel alınarak entegre edildi. Canlı bağlantılar, arşiv karmaları ve kapsam: [M01–M11 entegrasyon kaydı](docs/milestones/INTEGRATION.md). Paneldeki **M01–M11** sekmesi sözleşme, telaffuz ve kalıcı olay incelemesini sunar.

Türkçe ekspertiz randevusu için yerel STT → Ollama → FreyaTTS uygulaması. Web mikrofonu ve Asterisk AudioSocket aynı görüşme motorunu kullanır. Araç ve fiyat kayıtları, müsait saatler, randevular, transkriptler ve ses laboratuvarı Türkçe yönetim panelindedir.

## Kurulum ve başlatma

Windows PowerShell, Git, Node.js 22+, `uv`, Ollama ve NVIDIA sürücüsü gerekir. Python 3.11 `uv` tarafından hazırlanır. İlk kurulum CUDA PyTorch dahil birkaç GB indirebilir.

```powershell
.\scripts\setup.ps1
.\scripts\prepare_models.ps1
.\scripts\start.ps1
```

`BASLAT.bat` (veya `scripts\start.ps1`) sunucuyu başlatır. `BASLAT.bat --dev` yönetici parolasını panoya kopyalar (varsayılan olarak kopyalanmaz); `BASLAT.bat --demo` örnek veriyle açar (aşağıda).

Panel: http://127.0.0.1:8000 — kullanıcı `admin`; oluşturulan parola `.env` içindeki `ADMIN_PASSWORD` değeridir. Parola konsola yazdırılmaz. API belgeleri: http://127.0.0.1:8000/docs. Panelde **Sistem → Modelleri yükle** ile çalışan sunucuya ses modellerini yükleyin. Hazırlama betiği önbelleği doldurur; kendi süreci kapanınca modelleri bellekte tutmaz.

### Gizli anahtarlar (`.env`)

Kodda varsayılan gizli değer yoktur; boş bırakılan anahtarın özelliği kapalı kalır. `scripts\setup.ps1` yeni `.env` oluştururken rastgele üretir; kaynak: `.env.example`, `backend/config.py`.

| Anahtar | Kullanım |
|---|---|
| `ADMIN_PASSWORD` | REST için HTTP Basic (`admin`). Boşsa korumalı uç noktalar 503 verir. |
| `AMI_SECRET` | Asterisk AMI (giden çağrı, aktarım). |
| `WHATSAPP_WEBHOOK_TOKEN` | Gelen webhook; istek `X-Webhook-Token` başlığıyla gelmeli, gövde işlenmeden önce doğrulanır. |
| `AUDIO_ARCHIVE_MASTER_KEY` | Ses arşivi HMAC mührü; boşsa arşiv oluşturma/doğrulama reddedilir. |
| `LINK_SIGNING_KEY` | İmzalı müşteri bağlantıları (rapor PDF); boşsa imzalı erişim kapalıdır. |

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
.venv\Scripts\python -m pytest -q
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

Dizinler: `experimental/` canlı çağrı yoluna bağlı olmayan modülleri ve testlerini içerir (bkz. `experimental/README.md`); üretim davranışının kanıtı sayılmaz. `archive/` eski PoC dosyalarıdır. Ekran görüntüleri `scripts/capture_screenshots.py` ile demo sunucusundan alınır (Python `playwright` projenin bağımlılığı değildir; ayrıca kurulmalıdır); görüntüler demo verisidir.

## Bilinen sınırlar

Kaynaklar: `docs/VERIFICATION.md`, `data/acoustic/latest.json`, `docs/measured-latency.json`.

- PoC'tur; pilota hazır değildir. İnsan sesiyle ve gerçek Asterisk/telefon hattıyla test yapılmadı (M11 `HOLD`).
- AMI ve bildirim sağlayıcısı sahte istemcidir: gerçek aktarım, giden arama ve SMS/WhatsApp gönderimi yoktur.
- Otomotiv terim doğruluğu kapı eşiğinin çok altındadır; ABX ve F0 tabanı ölçülmedi; LoRA adaptörü yoktur.
- LLM gerektiren turlarda ilk ses 1,2 s hedefinin üstündedir (tek çalıştırma örneği, SLA değildir).
- KVKK maddeleri hukuki incelemede; `RETENTION_DAYS` yalnızca ses kayıtlarını (`recordings/*.wav`) temizler.
- Eşzamanlı görüşme ölçülmedi; testler tek görüşmeyle yapıldı (`max_concurrent_calls` üst sınırı 50).

Eski `automotive_freya_poc.py`, `run_poc.bat`, örnek WAV dosyaları ve eski test çıktısı karşılaştırma için `archive/` klasöründe korunmuştur. Eski çıktı dosyası yeni uygulamanın doğrulama raporu değildir.

## Lisans

**ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR**  
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlı olarak paylaşılmıştır.  
Kopyalanamaz, çoğaltılamaz, dağıtılamaz, ticari/ticari olmayan projelerde kullanılamaz veya tersine mühendislik yapılamaz. Detaylı bilgi için [LICENSE](LICENSE) dosyasına bakınız.





## Kaynak belge · docs/VERIFICATION.md

# Doğrulama kaydı

Durum: PoC. Bu dosya yalnızca ölçülmüş veya komutla yeniden üretilebilir kanıtları içerir. Önceki sürümün (31 Ekim) ölçümleri güncel profille (large-v3-turbo, kural öncelikli diyalog, ön ısıtma) uyuşmadığı için kaldırıldı.

## Doğrulananlar

| Konu | Kanıt | Kaynak |
|---|---|---|
| Otomatik testler | Toplanan test sayısı `pytest --collect-only -q` son satırıdır; geçen sayısı için `pytest -q` çalıştırın | `pyproject.toml` `testpaths` (`tests`, `experimental/tests`) |
| Akustik geri tanıma | 320 örnek, TTS -> 8 kHz telefon bandı -> STT; WER %18,7, CER %7,6, otomotiv terim doğruluğu %48,04; STT large-v3-turbo CUDA float16 | `data/acoustic/latest.json` (ölçüm 2026-11-06), `scripts/acoustic_benchmark.py` |
| Kalite kapısı | WER ve CER eşik içinde (PASS); terim doğruluğu eşiğin (%95) altında (FAIL); ABX ve F0 tabanı ölçülmedi (HOLD); genel durum FAIL | `abc_evaluator.run_benchmark_suite([], acoustic_report=...)` |
| Gerçek model tarayıcı testi | Sanal mikrofon, gerçek modeller; müşteri sesi sentetik TTS sesidir. Ana kabul testi son 6 çalıştırmanın 2'sinde geçti; kısaltılmış araç cümlesiyle 4 çalıştırmanın 4'ünde geçti (araç adımı kararsız) | `docs/measured-latency.json`, `scripts/voice_acceptance.py` |
| Gecikme (tek çalıştırma) | Karşılama ilk sesi ~15 ms (önbellekte), isim turu ~1,4 s, araç turu ~3,2 s, seçim/onay ~3,2 s, LLM gerektiren turlar ~6 s, STT ~0,3-1,5 s | `docs/measured-latency.json` |
| VRAM | Tepe 7478 / 8188 MiB (yaklaşık 1770 MiB masaüstü uygulamaları dahil); P5 ön ısıtmadan önce ölçüldü | `docs/measured-latency.json` |
| Kural öncelikli diyalog, ön ısıtma | Kod ve testlerle doğrulanır | `backend/dialogue.py`, `backend/models.py`, `tests/test_p5_latency.py` |
| Telefon protokolü | AudioSocket paket ayrıştırma ve 8 kHz akışı birim testleriyle sınandı | `tests/test_audiosocket_server.py` |

Gecikme değerleri tek çalıştırma örneğidir: SLA değildir, dağılım değildir. WER/CER ve terim doğruluğu TTS ile STT'nin birleşik sonucudur; hata tek bir modele atfedilemez.

## Doğrulanmayanlar

- İnsan sesiyle uçtan uca görüşme.
- Gerçek Asterisk ve SIP hattı: M11 kayıtlarında kanıt gönderilmemiş kapılar `HOLD` (`data/m11/M11_ACCEPTANCE.json`, `docs/milestones/current-acceptance.json`).
- Gerçek SMS/WhatsApp sağlayıcısı: sağlayıcı sahtedir.
- Gerçek aktarım ve giden arama: AMI istemcisi sahtedir.
- ABX (konuşmacı benzerliği), MOS ve F0 tabanı; ses doğallığı için dinleme kabulü.
- LoRA adaptörü: yoktur.
- LLM gerektiren turlarda 1,2 s ilk ses hedefi: karşılanmıyor (~6 s).
- KVKK maddeleri: hukuki incelemede; saklama süresi yalnızca ses kayıtlarını kapsar.
- P5 ön ısıtma sonrası VRAM ve gecikme yeniden ölçülmedi.

## Tekrarlama

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m scripts.acoustic_benchmark
.venv\Scripts\python -m scripts.voice_acceptance
.venv\Scripts\python scripts\generate_executive_docx.py
```

Akustik ve sesli kabul komutları gerçek modeller ve GPU ister. `generate_executive_docx.py` `tools` ekstrasını gerektirir (`uv sync --frozen --inexact --extra tools`).



## Kaynak belge · experimental/README.md

# experimental/

Bu klasördeki kod canlı çağrı yoluna (`backend.main` -> `app`) BAĞLI DEĞİLDİR.
`backend.main` içe aktarım grafiği çıkarılarak doğrulandı: aşağıdaki modüller
çalışma zamanında hiçbir yerden içe aktarılmıyor, yalnızca kendi testleri ve
birbirleri tarafından kullanılıyor.

| Modül | Not |
|---|---|
| `five_cuts_bargein_controller.py` | Beş kesimli barge-in denetleyicisi; canlı yolda `backend.audiosocket_server.TwoStageBargeInController` kullanılıyor. |
| `prosody_wsola_streamer.py` | WSOLA tabanlı örtüşmeli cümlecik akışı; canlı TTS yolunda çağrılmıyor. |
| `streaming_chunker_guard.py` | Akış parçalayıcı/çifte normalizasyon koruması; canlı yolda kullanılmıyor. |
| `asr_mapper.py` | ASR çıktısı kanonikleştirme; canlı yolda kullanılmıyor. |
| `normalizer.py` | Eski TTS normalleştiricisi; canlı yolda kullanılmıyor (canlı metin işleme `backend.text` ve `backend.automotive_frontend` içinde). |
| `legacy_src/` | Eski `src/` yeniden dışa aktarım (shim) dosyaları; her biri yalnızca `backend.*` modülünü yeniden dışa aktarıyordu, hiçbir canlı kod bunları içe aktarmıyor. |

Testler `experimental/tests/` altındadır ve `pyproject.toml` içindeki `testpaths`
ile toplanmaya devam eder. İçe aktarım yolu `experimental.<modül>` biçimindedir.

Bu modüller üretim davranışının kanıtı sayılmamalıdır. Bir modülü canlı yola almak
için önce `backend/` altına taşıyın ve ilgili testleri `tests/` altına geri alın.

Not: `backend.qa_telemetry_operator` canlı yoldadır (`backend.main` ve
`backend.acoustic_evaluation` içe aktarır) ve burada DEĞİLDİR; `compute_itu_mos`
canlı yolda çağrılmaz ve bir ölçüm değildir (bkz. işlevin docstring'i).


## Kabulün yürütülmesi

CI önce birim testlerini, boş veritabanına migration uygulamasını, model ile migration tutarlılığını ve UI rota denetimini çalıştırır. Ardından frontend derlenir ve test sunucusunda ui.spec.ts koşar. 12. belgedeki diğer Playwright paketlerini ayrıca seçin. Model ağırlıklarıyla çalışan sanal mikrofon deneyini ve gerçek santral denemesini ayrı sonuçlar olarak kaydedin. Demo hazırlanırken veri dizini ayrımını aşağıdaki betiklerden yeniden kurun.

### .github/workflows/ci.yml

~~~~yml
name: Local assistant checks
on: [push, pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    env:
      # Yalnizca CI icin tek kullanimlik degerler; gercek gizli anahtar degildir.
      ADMIN_PASSWORD: ci-only-disposable
      LINK_SIGNING_KEY: ci-only-link-signing-key
      AUDIO_ARCHIVE_MASTER_KEY: ci-only-archive-master-key
      AMI_SECRET: ci-only-ami-secret
      WHATSAPP_WEBHOOK_TOKEN: ci-only-webhook-token
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: npm
          cache-dependency-path: frontend/package-lock.json
      # backend.main modul duzeyinde torch iceri aktarir (gpu_health_circuit_breaker, sft_leyla).
      # Kilit dosyasi CUDA (cu128) tekerlegini sabitler; CI'da yalnizca CPU torch yuklenir
      # (--extra models tum ses modeli yiginini ve GB'larca CUDA kutuphanesini indirirdi).
      # Surum kilit dosyasindakiyle ayni tutulur: torch==2.8.0.
      - run: uv sync --frozen --extra test
      - run: uv pip install "torch==2.8.0" --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
      - run: uv run --no-sync pytest -q
      - run: uv run --no-sync alembic upgrade head
      - run: uv run --no-sync alembic check
      - run: uv run --no-sync python scripts/check_ui_routes.py
      - run: npm ci
        working-directory: frontend
      - run: npm run build
        working-directory: frontend
      - run: npx playwright install --with-deps chromium
        working-directory: frontend
      - name: Start test server
        run: |
          printf 'ADMIN_PASSWORD=%s\nLINK_SIGNING_KEY=%s\nAUDIO_ARCHIVE_MASTER_KEY=%s\nAMI_SECRET=%s\nWHATSAPP_WEBHOOK_TOKEN=%s\n' \
            "$ADMIN_PASSWORD" "$LINK_SIGNING_KEY" "$AUDIO_ARCHIVE_MASTER_KEY" "$AMI_SECRET" "$WHATSAPP_WEBHOOK_TOKEN" > .env
          uv run --no-sync uvicorn backend.main:app --host 127.0.0.1 --port 8000 > /tmp/freya-server.log 2>&1 &
          for i in $(seq 1 60); do
            if curl -fsS -o /dev/null http://127.0.0.1:8000/; then echo "Sunucu hazir"; exit 0; fi
            sleep 2
          done
          echo "Sunucu 120 sn icinde hazir olmadi"; cat /tmp/freya-server.log; exit 1
      - run: npx playwright test tests/ui.spec.ts
        working-directory: frontend
      - name: Sunucu gunlugu
        if: failure()
        run: cat /tmp/freya-server.log || true
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: browser-failures
          path: frontend/test-results
~~~~

### scripts/check_ui_routes.py

~~~~python
"""Arayuzdeki api("...") cagrilarini FastAPI rotalariyla karsilastirir.

Sunucu baslatilmaz; `backend.main` yalnizca rota tablosunu okumak icin iceri aktarilir
(gecici DATABASE_URL ve DATA_DIR ile). Uyumsuzluk varsa cikis kodu 1 olur.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALL = re.compile(r"\b(api|rawApi)\s*(?:<[^()]*?>)?\s*\(\s*")
FETCH = re.compile(r"\bfetch\s*\(\s*(?=[`\"']/api/)")
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def read_string(src: str, i: int):
    """src[i] bir tirnak ise (metin, bitis_indeksi) doner; sablon ifadeleri {} olur."""
    quote = src[i]
    i += 1
    out = []
    while i < len(src) and src[i] != quote:
        ch = src[i]
        if ch == "\\":
            out.append(src[i + 1])
            i += 2
        elif quote == "`" and src.startswith("${", i):
            depth, i = 1, i + 2
            while i < len(src) and depth:
                depth += {"{": 1, "}": -1}.get(src[i], 0)
                i += 1
            out.append("{}")
        else:
            out.append(ch)
            i += 1
    return "".join(out), i + 1


def skip_expr(src: str, i: int):
    """Dize olmayan bir ifadeyi ust duzey ',', ')' veya '+' gorene kadar atlar."""
    depth = 0
    while i < len(src):
        ch = src[i]
        if ch in "\"'`":
            _, i = read_string(src, i)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif ch in ",+" and depth == 0:
            break
        i += 1
    return i


def parse_path(src: str, i: int):
    """`"a/" + id + "/b"` bicimli birlesimi okur; (yol, indeks) doner."""
    parts = []
    while True:
        while src[i].isspace():
            i += 1
        if src[i] in "\"'`":
            text, i = read_string(src, i)
            parts.append(text)
        else:
            parts.append("{}")
            i = skip_expr(src, i)
        while src[i].isspace():
            i += 1
        if src[i] == "+":
            i += 1
            continue
        return "".join(parts), i


def frontend_calls():
    calls = []
    for file in sorted((ROOT / "frontend" / "src").rglob("*.ts*")):
        src = file.read_text(encoding="utf8")
        for match in CALL.finditer(src):
            i = match.end()
            if i >= len(src) or src[i] in ")":
                continue
            try:
                path, i = parse_path(src, i)
            except IndexError:
                continue
            method = "GET"
            rest = src[i:i + 40]
            m = re.match(r"\s*,\s*[\"'](\w+)[\"']", rest)
            if m and m.group(1).upper() in METHODS:
                method = m.group(1).upper()
            line = src.count("\n", 0, match.start()) + 1
            calls.append((file.relative_to(ROOT).as_posix(), line, method, path))
        for match in FETCH.finditer(src):
            path, _ = parse_path(src, match.end())
            line = src.count("\n", 0, match.start()) + 1
            calls.append((file.relative_to(ROOT).as_posix(), line, "?", path.removeprefix("/api/")))
    return calls


def normalize(path: str):
    path = path.split("?", 1)[0].strip("/")
    return ["{}" if (s.startswith("{") and s.endswith("}")) or s == "{}" else s
            for s in re.sub(r"\{[^}]*\}", "{}", path).split("/") if s != ""]


def flat_routes(routes):
    """include_router ile eklenen rotaları (yeni FastAPI'de tembel _IncludedRouter) düzleştirir."""
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            yield from flat_routes(original.routes)
        else:
            yield route


def backend_routes():
    tmp = tempfile.mkdtemp(prefix="freya-routes-")
    os.environ["DATABASE_URL"] = "sqlite:///" + Path(tmp, "routes.db").as_posix()
    os.environ["DATA_DIR"] = tmp
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    from backend.main import app

    routes = []
    for route in flat_routes(app.routes):
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        if path.startswith("/api/"):
            routes.append((normalize(path[len("/api/"):]), set(methods), path))
    return routes


def segs_match(call, route):
    return len(call) == len(route) and all(a == b or a == "{}" or b == "{}" for a, b in zip(call, route))


def main():
    routes = backend_routes()
    specific = [r for r in routes if r[0] and r[0][0] != "{}"]
    generic = [r for r in routes if not r[0] or r[0][0] == "{}"]
    problems, generic_only = [], []
    calls = frontend_calls()
    for file, line, method, path in calls:
        segs = normalize(path)
        hits = [r for r in specific if segs_match(segs, r[0])]
        ok = [r for r in hits if method == "?" or method in r[1]]
        if ok:
            continue
        generic_ok = [r for r in generic if segs_match(segs, r[0]) and (method == "?" or method in r[1])]
        if generic_ok:
            generic_only.append((file, line, method, path))
        elif hits:
            allowed = sorted(set().union(*(r[1] for r in hits)) - {"HEAD", "OPTIONS"})
            problems.append((file, line, method, path, "yontem uyumsuz, rota yontemleri: " + ",".join(allowed)))
        else:
            problems.append((file, line, method, path, "rota yok"))
    print(f"Arayuz cagrisi: {len(calls)}, API rotasi: {len(routes)}")
    for file, line, method, path in generic_only:
        print(f"UYARI {file}:{line} {method} {path} yalnizca genel /api/{{...}} rotasina eslesti")
    for file, line, method, path, why in problems:
        print(f"UYUMSUZ {file}:{line} {method} /api/{path} -> {why}")
    if problems:
        print(f"{len(problems)} uyumsuzluk bulundu")
        return 1
    print("Tum arayuz cagrilari bir backend rotasina eslesiyor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
~~~~

### scripts/seed_demo_db.py

~~~~python
"""
Demo veritabanına test koşusu için dondurulmuş fixture yazar.

Çalıştır:
    .venv\Scripts\python.exe scripts/seed_demo_db.py

Yazar:
  - Toyota Corolla aracını (plaka boş, diyalog doldurur)
  - 2.500 TL (250.000 kuruş) standart ekspertiz paketi
  - Yarın: 09:00 DOLU, 10:00 AÇIK, 11:00 AÇIK
  - 09:00 slotuna yer tutucu randevu (başka müşteri)

Alembic migration uygulanmış ve tablolar mevcut olmalı.
"""
import sqlite3
import os
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Istanbul")
DB_PATH = "data/demo/assistant.db"


def uid():
    return str(uuid.uuid4())


def now_utc():
    return datetime.now(ZoneInfo("UTC")).isoformat()


def seed():
    if not os.path.exists(DB_PATH):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        print(f"[!] Demo DB bulunamadı: {DB_PATH}")
        print("    Önce: BASLAT.bat --demo  (ya da alembic upgrade head ile tabloları oluştur)")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # PRAGMA
    cur.execute("PRAGMA foreign_keys=ON")

    tomorrow = (datetime.now(TZ) + timedelta(days=1))
    t_09 = tomorrow.replace(hour=9,  minute=0, second=0, microsecond=0)
    t_10 = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    t_11 = tomorrow.replace(hour=11, minute=0, second=0, microsecond=0)
    date_str = tomorrow.strftime("%Y-%m-%d")

    # Mevcut test slotlarını temizle (sadece yarın)
    cur.execute(
        "DELETE FROM appointments WHERE slot_id IN "
        "(SELECT id FROM slots WHERE starts_at LIKE ? AND id NOT IN "
        "(SELECT slot_id FROM appointments WHERE idempotency_key NOT LIKE 'seed-%'))",
        (f"{date_str}%",)
    )
    cur.execute("DELETE FROM slots WHERE starts_at LIKE ? AND id NOT IN "
                "(SELECT slot_id FROM appointments WHERE slot_id IS NOT NULL)",
                (f"{date_str}%",))

    # Corolla var mı?
    cur.execute("SELECT id FROM vehicles WHERE description LIKE '%orolla%' LIMIT 1")
    row = cur.fetchone()
    if row:
        vehicle_id = row[0]
        print(f"[OK] Mevcut Corolla kullanılıyor: {vehicle_id[:8]}...")
    else:
        vehicle_id = uid()
        cur.execute(
            "INSERT INTO vehicles (id, description, plate, vin) VALUES (?, ?, ?, ?)",
            (vehicle_id, "Toyota Corolla", "", "")
        )
        print(f"[+] Corolla eklendi: {vehicle_id[:8]}...")

    # Mevcut quote var mı?
    cur.execute("SELECT id FROM quotes WHERE vehicle_id=? LIMIT 1", (vehicle_id,))
    if not cur.fetchone():
        quote_id = uid()
        cur.execute(
            "INSERT INTO quotes (id, vehicle_id, amount_kurus) VALUES (?, ?, ?)",
            (quote_id, vehicle_id, 250000)
        )
        print(f"[+] Quote eklendi: 2.500 TL")

    # Slotlar
    slots = {}
    for label, dt in [("09", t_09), ("10", t_10), ("11", t_11)]:
        iso = dt.isoformat()
        cur.execute("SELECT id FROM slots WHERE starts_at=?", (iso,))
        row = cur.fetchone()
        if row:
            slots[label] = row[0]
            print(f"[OK] Slot {label}:00 mevcut: {slots[label][:8]}...")
        else:
            slot_id = uid()
            cur.execute("INSERT INTO slots (id, starts_at) VALUES (?, ?)", (slot_id, iso))
            slots[label] = slot_id
            print(f"[+] Slot {label}:00 eklendi")

    # 09:00'ı doldur (yer tutucu)
    cur.execute("SELECT id FROM appointments WHERE slot_id=? AND idempotency_key='seed-occupied-09'", (slots["09"],))
    if not cur.fetchone():
        occ_id = uid()
        cur.execute(
            "INSERT INTO appointments (id, slot_id, vehicle_id, customer, idempotency_key, confirmed, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (occ_id, slots["09"], vehicle_id, "Mevcut Müşteri", "seed-occupied-09", 1, "confirmed", now_utc())
        )
        print(f"[+] 09:00 randevusu dolduruldu (seed-occupied-09)")
    else:
        print(f"[OK] 09:00 zaten dolu")

    # 10:00 ve 11:00 açık olmalı
    for label in ["10", "11"]:
        cur.execute(
            "SELECT id FROM appointments WHERE slot_id=? AND idempotency_key != 'seed-occupied-09'",
            (slots[label],)
        )
        rows = cur.fetchall()
        if rows:
            print(f"[!] {label}:00 slotunda {len(rows)} beklenmedik randevu var — siliniyor")
            for r in rows:
                cur.execute("DELETE FROM appointments WHERE id=?", (r[0],))

    conn.commit()
    conn.close()

    print(f"\n✓ Demo DB hazır: {DB_PATH}")
    print(f"  Corolla: {vehicle_id[:8]}...")
    print(f"  Tarih  : {date_str}")
    print(f"  09:00  : DOLU (seed-occupied-09)")
    print(f"  10:00  : AÇIK")
    print(f"  11:00  : AÇIK")
    print(f"  Fiyat  : 2.500 TL (250.000 kuruş)")


if __name__ == "__main__":
    seed()
~~~~

### scripts/seed_demo_telemetry.py

~~~~python
# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""
seed_demo_telemetry.py
Deterministik Demo ve Telemetri Veri Enjektörü (v3 - Final Polish)

UYARI: Buradaki tüm görüşme, gecikme ve müşteri kayıtları örnek veridir; gerçek
ölçüm olarak sunulamaz. Betik her zaman DEMO_MODE ile çalışır ve yalnızca
data/demo/ altına yazar; işletim veritabanına erişemez.

Bu betik sunum ve ekran görüntüsü alımı öncesinde demo veritabanını ve aktif
bellek durumlarını deterministik olarak hazırlar:
1. Örnek telemetri:
   - 97 Görüşme: Web: 18 | Tel: 54 | Dış: 25
   - Ort. Süre: 68 sn | Ort. Tur: 4.2
   - TTFA p50: ~780 ms, p95: ~1120 ms; TTFT: ~310 ms; STT: ~240 ms; RTF: 0.38x; 4 barge-in
2. 3.3 SIP Warm Transfer (1 bekleyen fısıltı, 2 tamamlanmış aktarım)
3. 3.4 Canlı Müdahale (RT-10 Takeover aktif simüle çağrı)
4. 3.8 Sıra & Lift Durumu (Canlı Kuyrukta 2 araç: 34 EKP 2026, 06 DEF 456; Tahmini Bekleme: 18 dk; Lift #1 DOLU)
5. 3.9 A/B Test (Kontrol A ve Varyant B oturumları, Z-Skoru ve p-değeri)
6. 3.12 Ekspertiz Raporları (3 farklı araç: Qashqai, Passat, Civic)
7. 3.14 OBD-II DTC Teşhis Kayıtları (P0300, P0420, P0171)
8. 3.15 Araçlar ve Fiyatlar (Tüm araçlar için ekspertiz fiyatları dolu)
9. 3.18 Giden Çağrılar (Teyit Edilen: 38, 60 devam eden · 2 iptal; zengin müşteri listesi)
10. 3.19 Çağrı Geçmişi (Teknik diyaloglar)
"""

import os
import sys
import json
import uuid
import math
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path
import httpx
from sqlalchemy import select, delete

# Ensure root dir in path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# backend içe aktarılmadan önce ayarlanmalıdır: veritabanı motoru o anda belirlenir.
os.environ["DEMO_MODE"] = "1"

from alembic import command
from alembic.config import Config

from backend.db import (
    engine,
    Session,
    Vehicle,
    Quote,
    InspectionReport,
    VehicleDiagnostic,
    Appointment,
    Conversation,
    Turn,
    OperatorTransfer,
    ABExperiment,
    ABAssignment,
    CallAnalytics,
    InspectionLift,
    InspectionQueue,
    OutboundCall,
)
from backend.analytics import get_analytics_overview
from backend.ab_testing import seed_default_experiment, get_experiment_report
from backend.config import settings


def seed_telemetry_and_conversations(db):
    """97 adet görüşme ve bunlara ait RT-09 uyumlu deterministik telemetri turları oluşturur."""
    print("[*] 97 görüşme ve RT-09 telemetri turları enjekte ediliyor (Web: 18, Tel: 54, Dış: 25)...")

    # Mevcut demo verilerini temizleyelim (demo_ ile başlayanlar)
    db.execute(delete(Turn).where(Turn.conversation_id.like("demo_conv_%")))
    db.execute(delete(Conversation).where(Conversation.id.like("demo_conv_%")))
    db.commit()

    now_utc = datetime.now(timezone.utc)
    random.seed(42)

    # Toplam 97 görüşme kanalları: 18 web, 54 phone, 25 outbound
    channels = ["web"] * 18 + ["phone"] * 54 + ["outbound"] * 25
    random.shuffle(channels)

    # 97 adet için TTFA, TTFT, STT dizileri
    first_audio_vals = []
    for i in range(97):
        if i < 48:
            val = 620.0 + (i / 47.0) * (780.0 - 620.0) + random.uniform(-10, 10)
        elif i < 90:
            val = 780.0 + ((i - 48) / 42.0) * (1120.0 - 780.0) + random.uniform(-10, 10)
        else:
            val = 1120.0 + ((i - 90) / 6.0) * 80.0 + random.uniform(0, 15)
        first_audio_vals.append(round(val, 1))
    first_audio_vals.sort()

    llm_ft_vals = []
    for i in range(97):
        if i < 48:
            val = 240.0 + (i / 47.0) * (310.0 - 240.0) + random.uniform(-5, 5)
        else:
            val = 310.0 + ((i - 48) / 48.0) * 180.0 + random.uniform(-5, 5)
        llm_ft_vals.append(round(val, 1))
    llm_ft_vals.sort()

    stt_vals = []
    for i in range(97):
        if i < 48:
            val = 180.0 + (i / 47.0) * (240.0 - 180.0) + random.uniform(-5, 5)
        else:
            val = 240.0 + ((i - 48) / 48.0) * 120.0 + random.uniform(-5, 5)
        stt_vals.append(round(val, 1))
    stt_vals.sort()

    rtf_vals = [round(0.35 + (i % 7) * 0.01 + random.uniform(-0.01, 0.01), 3) for i in range(97)]
    barge_in_indices = {12, 34, 58, 83}  # Tam 4 adet barge-in

    sample_dialogues = [
        ("Merhaba, 34 TST 89 plakalı aracım için ekspertiz randevusu almak istiyorum.",
         "Merhaba Murat Bey! 34 TST 89 plakalı Nissan Qashqai aracınız için yarın saat 14:30 ve 16:00 uygundur. Hangi saati tercih edersiniz?"),
        ("1.5 TSI Passat aracımın periyodik muayene öncesi genel kontrolünü yaptırabilir miyim?",
         "Tabii ki! 1.5 TSI motorlu Passat aracınız için 101 nokta ekspertiz ve OBD-II arıza tespit randevunuzu hemen oluşturabilirim."),
        ("Fren disklerinde sürtünme sesi geliyor, acil kontrol gerek.",
         "Fren güvenliği birinci önceliğimizdir. Aracınızı en yakın liftimize almak üzere bugün saat 15:00 için acil teşhis kaydı açıyorum."),
        ("OBD cihazım P0420 hatası verdi, katalitik konvertör durumuna bakabilir misiniz?",
         "P0420 arıza kodu katalizör sistem verimi eşiğiyle ilgilidir. Egzoz emisyon ve oksijen sensörü kontrolleri randevunuza dahil edilmiştir."),
        ("Satın almayı düşündüğüm Honda Civic için tam kapsamlı ekspertiz raporu alabilir miyiz?",
         "Elbette! Kaporta, boya, şasi, motor mekanik ve OBD-II elektronik kontrolünü içeren Full Ekspertiz paketimiz mevcuttur."),
    ]

    for idx in range(97):
        conv_id = f"demo_conv_{idx+1:02d}"
        conv_dt = now_utc - timedelta(days=(idx % 14), hours=(idx % 8), minutes=idx * 5)
        c_status = "resolved" if idx > 12 else ("active" if idx < 3 else "follow_up")

        conv = Conversation(
            id=conv_id,
            channel=channels[idx],
            status=c_status,
            operator_notes=f"Deterministik test oturumu #{idx+1}" if c_status == "resolved" else "",
            created_at=conv_dt.isoformat(),
            resolved_at=(conv_dt + timedelta(seconds=68)).isoformat() if c_status == "resolved" else None,
        )
        db.add(conv)

        # Tur sayısı ortalama 4.2 olacak şekilde: çoğu 4, bazıları 5 veya 6 tur
        num_turns = 4 if idx % 5 != 0 else (6 if idx % 10 == 0 else 5)
        t_delta = 68.0 / max(1, num_turns - 1)

        d_idx = idx % len(sample_dialogues)
        user_text, asst_text = sample_dialogues[d_idx]

        for t_i in range(num_turns):
            is_user = (t_i % 2 == 0)
            t_created = conv_dt + timedelta(seconds=t_i * t_delta)

            m_dict = {}
            if not is_user:
                m_dict = {
                    "first_audio_ms": first_audio_vals[idx],
                    "llm_first_token_ms": llm_ft_vals[idx],
                    "llm_total_ms": round(llm_ft_vals[idx] + 280.0, 1),
                    "stt_ms": stt_vals[idx],
                    "tts_ms": round(290.0 + (idx % 10) * 6.0, 1),
                    "rtf": rtf_vals[idx],
                }
                if idx in barge_in_indices and t_i == 1:
                    m_dict["barge_in_signal_ms"] = 125.0

            turn = Turn(
                id=f"demo_turn_{idx+1:02d}_{t_i+1}",
                conversation_id=conv_id,
                role="user" if is_user else "assistant",
                text=user_text if is_user else asst_text,
                metrics=json.dumps(m_dict) if m_dict else "{}",
                created_at=t_created.isoformat(),
            )
            db.add(turn)

    db.commit()
    print("[OK] 97 görüşme ve telemetri turları kaydedildi.")


def seed_sip_warm_transfers(db):
    """3.3 SIP Warm Transfer için 1 bekleyen (whispering) ve 2 kabul edilmiş aktarım oluşturur."""
    print("[*] 3.3 SIP Warm Transfer kayıtları enjekte ediliyor...")
    db.execute(delete(OperatorTransfer).where(OperatorTransfer.id.like("demo_transfer_%")))
    db.commit()

    now_utc = datetime.now(timezone.utc)

    # 1 Bekleyen Transfer (Fısıltı aşamasında)
    pending_tr = OperatorTransfer(
        id="demo_transfer_pending_01",
        conversation_id="demo_conv_01",
        caller_channel="SIP/Trunk-01/05325551234",
        operator_extension="6002",
        customer_name="Murat Demir",
        vehicle_plate="34 BJK 1903",
        summary="Müşteri 14:30 randevusunu 16:00 olarak revize etmek istiyor ve rot-balans kontrolü talep ediyor.",
        whisper_text="Fısıltı: Müşteri 14:30 randevusunu 16:00 olarak teyit etmek istiyor.",
        status="whispering",
        sip_headers_json=json.dumps({
            "X-Freya-Caller-ID": "05325551234",
            "X-Freya-Intent": "appointment_reschedule",
            "X-Freya-Priority": "HIGH",
        }),
        duration_seconds=8.4,
        created_at=(now_utc - timedelta(seconds=6)).isoformat(),
        completed_at=None,
    )
    db.add(pending_tr)

    # 2 Kabul edilmiş (Accepted) Transfer
    accepted_tr_1 = OperatorTransfer(
        id="demo_transfer_acc_01",
        conversation_id="demo_conv_02",
        caller_channel="SIP/Trunk-02/05339998877",
        operator_extension="6002",
        customer_name="Ayşe Kaya",
        vehicle_plate="34 BCF 1234",
        summary="Volkswagen Golf 1.5 eTSI DSG kavrama titremesi şikayeti ile bağlandı. Randevusu oluşturuldu.",
        whisper_text="Fısıltı: Müşteri kavrama garantisi sorguluyor.",
        status="accepted",
        sip_headers_json=json.dumps({"X-Freya-Intent": "warranty_inquiry"}),
        duration_seconds=142.5,
        created_at=(now_utc - timedelta(minutes=25)).isoformat(),
        completed_at=(now_utc - timedelta(minutes=22)).isoformat(),
    )
    db.add(accepted_tr_1)

    accepted_tr_2 = OperatorTransfer(
        id="demo_transfer_acc_02",
        conversation_id="demo_conv_03",
        caller_channel="SIP/Trunk-01/05423334455",
        operator_extension="6002",
        customer_name="Kemal Sunar",
        vehicle_plate="06 TST 4431",
        summary="Filo ekspertiz indirimi talebi. Kurumsal cariye yönlendirildi.",
        whisper_text="Fısıltı: Filo yöneticisi, 5 araçlık paket soruyor.",
        status="accepted",
        sip_headers_json=json.dumps({"X-Freya-Intent": "fleet_discount"}),
        duration_seconds=98.0,
        created_at=(now_utc - timedelta(hours=1, minutes=10)).isoformat(),
        completed_at=(now_utc - timedelta(hours=1, minutes=8)).isoformat(),
    )
    db.add(accepted_tr_2)

    db.commit()
    print("[OK] SIP Warm Transfer kayıtları eklendi.")


def seed_lifts_and_queue(db):
    """3.8 Sıra & Lift Durumu: Lift #1 DOLU (İŞLEMDE), 2 bekleyen araç (34 EKP 2026, 06 DEF 456), Tahmini Bekleme: 18 dk."""
    print("[*] 3.8 Sıra & Lift Durumu verileri enjekte ediliyor...")
    now_utc = datetime.now(timezone.utc)

    # Mevcut kuyruk ve liftleri temizleyip yeniden yapılandıralım
    db.execute(delete(InspectionQueue))
    db.execute(delete(InspectionLift))
    db.commit()

    # Lift 1: Dolu (İşlemde)
    lift1 = InspectionLift(
        id="lift_01",
        name="Mekanik & Alt Takım Lifti",
        lift_number=1,
        status="busy",
        current_vehicle_plate="34 BJK 1903",
        package_type="101 Nokta Mekanik Muayene",
        started_at=(now_utc - timedelta(minutes=15)).isoformat(),
        estimated_duration_min=30,
        notes="İşlemde: Rot-balans ve fren hortumları inceleniyor",
        created_at=now_utc.isoformat(),
    )
    db.add(lift1)

    # Lift 2: Boş (Hazır)
    lift2 = InspectionLift(
        id="lift_02",
        name="Kaporta & Boya Ekspertizi Lifti",
        lift_number=2,
        status="idle",
        current_vehicle_plate=None,
        package_type=None,
        started_at=None,
        estimated_duration_min=25,
        notes="Müsait / Sıradaki aracı bekliyor",
        created_at=now_utc.isoformat(),
    )
    db.add(lift2)

    # Lift 3: Boş (Hazır)
    lift3 = InspectionLift(
        id="lift_03",
        name="OBD-II & Elektronik Teşhis İstasyonu",
        lift_number=3,
        status="idle",
        current_vehicle_plate=None,
        package_type=None,
        started_at=None,
        estimated_duration_min=20,
        notes="Müsait / Kalibrasyon tamamlandı",
        created_at=now_utc.isoformat(),
    )
    db.add(lift3)

    # Canlı Bekleme Kuyruğu: 2 Araç
    q1 = InspectionQueue(
        id="queue_01",
        queue_number=1,
        plate="34 EKP 2026",
        customer="Emre Kaya",
        package_type="101 Nokta Genel Muayene",
        duration_minutes=25,
        status="waiting",
        check_in_at=(now_utc - timedelta(minutes=12)).isoformat(),
    )
    db.add(q1)

    q2 = InspectionQueue(
        id="queue_02",
        queue_number=2,
        plate="06 DEF 456",
        customer="Deniz Fırat",
        package_type="OBD-II & Hibrit Sistem Teşhisi",
        duration_minutes=25,
        status="waiting",
        check_in_at=(now_utc - timedelta(minutes=6)).isoformat(),
    )
    db.add(q2)

    db.commit()
    print("[OK] Liftler ve Sıra Kuyruğu (2 bekleyen araç, Lift #1 DOLU) kaydedildi.")


def seed_ab_experiment_metrics(db):
    """3.9 A/B Test için Kontrol (A) ve Varyant (B) oturumları, Z-Skoru ve p-değeri oluşturur."""
    print("[*] 3.9 A/B Test istatistiksel verileri enjekte ediliyor...")
    exp = seed_default_experiment(db)

    db.execute(delete(ABAssignment).where(ABAssignment.experiment_id == exp.id))
    db.execute(delete(Conversation).where(Conversation.id.like("demo_ab_%")))
    db.commit()

    now_utc = datetime.now(timezone.utc)

    # 97 görüşmeden ilk 25'i kontrol, sonraki 30'u varyant b olarak eşleştirilir
    # Böylece toplam görüşme sayısı tam olarak 97'de kalır (Web: 18, Tel: 54, Dış: 25)
    for i in range(25):
        conv_id = f"demo_conv_{i+1:02d}"
        assign = ABAssignment(
            id=f"demo_assign_ctrl_{i+1:02d}",
            conversation_id=conv_id,
            experiment_id=exp.id,
            variant_id="control",
            outcome="converted" if i < 11 else "abandoned",
            first_audio_ms=790.0,
            duration_seconds=75.0,
            turns_count=4,
            created_at=(now_utc - timedelta(days=2, hours=i)).isoformat(),
            completed_at=(now_utc - timedelta(days=2, hours=i)).isoformat(),
        )
        db.add(assign)

    for j in range(30):
        conv_id = f"demo_conv_{j+26:02d}"
        assign = ABAssignment(
            id=f"demo_assign_varb_{j+1:02d}",
            conversation_id=conv_id,
            experiment_id=exp.id,
            variant_id="variant_b",
            outcome="converted" if j < 22 else "abandoned",
            first_audio_ms=750.0,
            duration_seconds=64.0,
            turns_count=4,
            created_at=(now_utc - timedelta(days=1, hours=j % 12)).isoformat(),
            completed_at=(now_utc - timedelta(days=1, hours=j % 12)).isoformat(),
        )
        db.add(assign)

    db.commit()
    report = get_experiment_report(db, exp.id)
    comp = report["comparisons"][0] if report.get("comparisons") else {}
    print(f"[OK] A/B Test Raporu: Z-Skoru: {comp.get('z_score')}, p-değeri: {comp.get('p_value')}")


def seed_inspections_and_diagnostics(db):
    """3.12 Ekspertiz Raporları ve 3.14 OBD-II DTC Bulguları: 3 farklı araç (Qashqai, Passat, Civic)."""
    print("[*] 3.12 Ekspertiz (3 farklı araç) ve 3.14 OBD-II DTC teşhis kayıtları enjekte ediliyor...")

    # Araç 1: Nissan Qashqai
    v1 = db.scalars(select(Vehicle).where(Vehicle.plate == "32 ABX 435")).first()
    if not v1:
        v1 = Vehicle(id="demo_veh_qashqai", description="Nissan Qashqai 1.3 DIG-T", plate="32 ABX 435", vin="SJNFAAJ11U1234567")
        db.add(v1)

    # Araç 2: Volkswagen Passat
    v2 = db.scalars(select(Vehicle).where(Vehicle.plate == "34 ABC 123")).first()
    if not v2:
        v2 = Vehicle(id="demo_veh_passat", description="Volkswagen Passat 1.5 TSI", plate="34 ABC 123", vin="WVWZZZ3CZWE987654")
        db.add(v2)

    # Araç 3: Honda Civic
    v3 = db.scalars(select(Vehicle).where(Vehicle.plate == "06 CAN 01")).first()
    if not v3:
        v3 = Vehicle(id="demo_veh_civic", description="Honda Civic 1.5 VTEC", plate="06 CAN 01", vin="SHHFK7760JU456789")
        db.add(v3)

    db.commit()

    db.execute(delete(InspectionReport).where(InspectionReport.id.like("demo_insp_%")))
    db.execute(delete(VehicleDiagnostic).where(VehicleDiagnostic.id.like("demo_dtc_%")))
    db.commit()

    now_utc = datetime.now(timezone.utc)

    # 3 Farklı Araç için Ekspertiz Raporları
    r1 = InspectionReport(
        id="demo_insp_01",
        vehicle_id=v1.id,
        technician_name="Murat Usta (Baş Teknisyen)",
        summary="Motor ve yürüyen aksam mükemmel kondisyonda. Sağ ön çamurluk boyalı, şasi ve podyeler hatasız.",
        mileage_km=48500,
        score=92,
        findings_json=json.dumps({
            "paint_body": {"kaput": "Orijinal", "tavan": "Orijinal", "sag_on_camurluk": "Boyalı"},
            "engine_mechanical": {"motor_performansi_yuzde": 95, "turbo_durumu": "Mükemmel", "sanziman_vites": "Kusursuz"},
            "chassis_frame": {"on_podyeler": "Orijinal / İşlemsiz", "fren_disk_balata": "İyi Durumda (%85)"},
            "tires_wheels": {"on_sol_dis_mm": 6.8, "arka_sol_dis_mm": 6.5, "dot_yili": "2024"},
        }, ensure_ascii=False),
        photos_json="[]",
        pdf_path="reports/demo_32ABX435_full_inspection.pdf",
        delivered_at=(now_utc - timedelta(hours=3)).isoformat(),
        inspected_at=(now_utc - timedelta(hours=4)).isoformat(),
    )
    db.add(r1)

    r2 = InspectionReport(
        id="demo_insp_02",
        vehicle_id=v2.id,
        technician_name="Selim Usta (Kaporta & Boya)",
        summary="Volkswagen Passat 1.5 TSI ekspertiz kontrolü: Bagaj kapağında lokal boya tespit edildi. DSG kavrama ve şanzıman adaptasyonu mükemmel.",
        mileage_km=92000,
        score=84,
        findings_json=json.dumps({
            "paint_body": {"bagaj_kapagi": "Lokal Boyalı", "arka_tampon": "Plastik Onarım", "kaput": "Orijinal"},
            "engine_mechanical": {"motor_performansi_yuzde": 91, "turbo_durumu": "Normal", "yag_sivi_kacaklari": "Kuru / Temiz"},
            "chassis_frame": {"on_podyeler": "Orijinal", "fren_disk_balata": "Yeni (%90)"},
        }, ensure_ascii=False),
        photos_json="[]",
        pdf_path="reports/demo_34ABC123_inspection.pdf",
        delivered_at=(now_utc - timedelta(days=1)).isoformat(),
        inspected_at=(now_utc - timedelta(days=1, hours=2)).isoformat(),
    )
    db.add(r2)

    r3 = InspectionReport(
        id="demo_insp_03",
        vehicle_id=v3.id,
        technician_name="Ahmet Usta (Diyagnostik & OBD)",
        summary="Honda Civic 1.5 VTEC: OBD-II taramasında aktif arıza kodu yok. VTEC zamanlaması kusursuz, CVT şanzıman ve yürüyen aksam tam not aldı.",
        mileage_km=31200,
        score=96,
        findings_json=json.dumps({
            "paint_body": {"tum_parcalar": "Tamamen Orijinal (Hatasız)"},
            "engine_mechanical": {"motor_performansi_yuzde": 98, "turbo_durumu": "Mükemmel"},
            "interior_electronics": {"obd_ariza_taramasi": "0 Hata Kodu", "airbag_guvenlik": "Aktif / Hatasız"},
        }, ensure_ascii=False),
        photos_json="[]",
        pdf_path="reports/demo_06CAN01_inspection.pdf",
        delivered_at=(now_utc - timedelta(days=3)).isoformat(),
        inspected_at=(now_utc - timedelta(days=3, hours=1)).isoformat(),
    )
    db.add(r3)

    # 3 OBD-II DTC Bulgusu
    dtc1 = VehicleDiagnostic(
        id="demo_dtc_01",
        vehicle_id=v1.id,
        dtc_code="P0300",
        severity="critical",
        system_category="engine",
        description_tr="Rastgele / Çoklu Silindir Ateşleme Hatası (Random/Multiple Cylinder Misfire Detected)",
        recommended_action="Buji ve ateşleme bobinlerinin derhal osiloskop ile test edilmesi, enjektör yakıt püskürtme basıncının ölçülmesi önerilir.",
        current_mileage_km=48500,
        next_service_km=50000,
        maintenance_status="critical",
        source="obd_telemetry",
        is_resolved=False,
        owner_phone="05325551234",
        owner_name="Murat Demir",
        last_notified_at=(now_utc - timedelta(hours=1)).isoformat(),
        created_at=(now_utc - timedelta(hours=2)).isoformat(),
    )
    db.add(dtc1)

    dtc2 = VehicleDiagnostic(
        id="demo_dtc_02",
        vehicle_id=v2.id,
        dtc_code="P0420",
        severity="warning",
        system_category="exhaust",
        description_tr="Katalizör Sistem Verimi Eşik Değerin Altında (Bank 1)",
        recommended_action="Katalitik konvertör gözenek tıkanıklığı ve aşağı akış (downstream) oksijen sensörü voltaj dalgalanması kontrol edilmelidir.",
        current_mileage_km=92000,
        next_service_km=100000,
        maintenance_status="warning",
        source="obd_dongle",
        is_resolved=False,
        owner_phone="05339998877",
        owner_name="Ayşe Kaya",
        last_notified_at=None,
        created_at=(now_utc - timedelta(hours=4)).isoformat(),
    )
    db.add(dtc2)

    dtc3 = VehicleDiagnostic(
        id="demo_dtc_03",
        vehicle_id=v3.id,
        dtc_code="P0171",
        severity="warning",
        system_category="fuel_air",
        description_tr="Sistem Aşırı Fakir Karışım (System Too Lean - Bank 1)",
        recommended_action="Emme manifoldu hava kaçağı testi (duman testi) ve kütle hava akış (MAF) sensörü temizliği yapılmalıdır.",
        current_mileage_km=31200,
        next_service_km=40000,
        maintenance_status="warning",
        source="obd_dongle",
        is_resolved=True,
        owner_phone="05423334455",
        owner_name="Can Öztürk",
        last_notified_at=(now_utc - timedelta(days=2)).isoformat(),
        created_at=(now_utc - timedelta(days=3)).isoformat(),
    )
    db.add(dtc3)

    db.commit()
    print("[OK] Ekspertiz (3 araç) ve OBD-II DTC kayıtları eklendi.")


def seed_vehicles_and_quotes(db):
    """3.15 Araçlar ve Fiyatlar: Toyota Corolla, Renault Clio, Honda Civic, Ford Focus fiyatları eksiksiz dolu."""
    print("[*] 3.15 Araçlar ve Ekspertiz Fiyatları (Quote) dolduruluyor...")

    # Standart araç katalog listesi
    catalog = [
        ("veh-qashqai-1", "Nissan Qashqai 1.3 DIG-T", "32 ABX 435", 450000),      # 4.500 TL
        ("veh-passat-1", "Volkswagen Passat 1.5 TSI", "34 ABC 123", 495000),      # 4.950 TL
        ("veh-corolla-1", "Toyota Corolla 1.8 Hybrid", "34 PIN 01", 425000),     # 4.250 TL
        ("veh-clio-1", "Renault Clio 1.0 TCe", "34 WA 123", 350000),             # 3.500 TL
        ("veh-civic-1", "Honda Civic 1.5 VTEC", "06 CAN 01", 480000),             # 4.800 TL
        ("veh-focus-1", "Ford Focus 1.5 EcoBlue", "35 VCS 99", 420000),           # 4.200 TL
        ("veh-golf-1", "Volkswagen Golf 1.5 eTSI", "34 BCF 1234", 460000),        # 4.600 TL
    ]

    # Fazlalık test araçlarını temizleyelim, temiz bir liste kalsın
    db.execute(delete(Quote))
    db.commit()

    for v_id, desc, plate, kurus in catalog:
        veh = db.scalars(select(Vehicle).where(Vehicle.plate == plate)).first()
        if not veh:
            veh = Vehicle(id=v_id, description=desc, plate=plate, vin=f"VIN{plate.replace(' ', '')}026")
            db.add(veh)
            db.flush()
        else:
            veh.description = desc

        # Fiyat kaydı (Quote) ekle
        q = Quote(
            id=f"quote_{veh.id}",
            vehicle_id=veh.id,
            amount_kurus=kurus,
        )
        db.add(q)

    db.commit()
    print("[OK] Araçlar ve ekspertiz fiyatları kaydedildi.")


def seed_outbound_calls(db):
    """3.18 Giden Çağrılar: Teyit Edilen: 38, 60 devam eden · 2 iptal (Toplam: 100 çağrı), zengin müşteri listesi."""
    print("[*] 3.18 Giden Çağrılar enjekte ediliyor (38 teyit, 60 devam eden, 2 iptal)...")
    db.execute(delete(OutboundCall))
    db.commit()

    now_utc = datetime.now(timezone.utc)

    # 100 adet çağrı için müşteri isimleri ve telefonlar
    first_names = ["Murat", "Ahmet", "Mehmet", "Mustafa", "Ali", "Can", "Burak", "Emre", "Serkan", "Hakan",
                   "Ayşe", "Fatma", "Zeynep", "Elif", "Selin", "Gizem", "Büşra", "Ece", "Derya", "Merve"]
    last_names = ["Demir", "Yılmaz", "Kaya", "Çelik", "Şahin", "Öztürk", "Arslan", "Doğan", "Kılıç", "Aslan",
                  "Çetin", "Kara", "Koç", "Kurt", "Özdemir", "Simsek", "Acar", "Yıldız", "Güler", "Polat"]
    area_codes = ["0532", "0533", "0535", "0542", "0544", "0553", "0505", "0530"]

    call_types = ["appointment_confirmation", "reminder", "follow_up", "feedback_survey"]

    # 38 Teyit Edildi (completed + confirmed)
    # 60 Devam Eden (in-progress + pending)
    # 2 Randevu İptal (cancelled + cancelled)
    call_configs = (
        [("completed", "confirmed")] * 38 +
        [("in-progress", "pending")] * 60 +
        [("cancelled", "cancelled")] * 2
    )

    # Mevcut randevuları alalım (foreign key için)
    apps = db.scalars(select(Appointment)).all()
    if not apps:
        # Randevu yoksa 1 adet örnek randevu oluşturalım
        sample_vehicle = db.scalars(select(Vehicle)).first()
        sample_app = Appointment(
            id="app_sample_demo",
            vehicle_id=sample_vehicle.id,
            customer="Örnek Müşteri",
            idempotency_key="demo_sample_appointment",
            confirmed=True,
            status="confirmed",
        )
        db.add(sample_app)
        db.flush()
        apps = [sample_app]

    for i, (status, outcome) in enumerate(call_configs):
        fn = first_names[i % len(first_names)]
        ln = last_names[(i * 3 + 7) % len(last_names)]
        customer = f"{fn} {ln}"

        ac = area_codes[(i * 2 + 3) % len(area_codes)]
        phone = f"{ac} {random.randint(200, 999)} {random.randint(10, 99)} {random.randint(10, 99)}"
        c_type = call_types[i % len(call_types)]

        dt = now_utc - timedelta(hours=(i % 48), minutes=(i * 11) % 60)
        app_id = apps[i % len(apps)].id

        call = OutboundCall(
            id=f"demo_outbound_{i+1:03d}",
            appointment_id=app_id,
            customer=customer,
            phone=phone,
            call_type=c_type,
            status=status,
            outcome=outcome,
            action_id=f"ACT-2026-{i+1:04d}",
            attempts=1 if status == "completed" else 0,
            created_at=dt.isoformat(),
            completed_at=(dt + timedelta(minutes=2)).isoformat() if status == "completed" else None,
        )
        db.add(call)

    db.commit()
    print("[OK] 100 giden çağrı (38 teyit, 60 devam eden, 2 iptal) başarıyla kaydedildi.")


def register_live_call_in_server():
    """Çalışan FastAPI sunucusuna HTTP üzerinden canlı simüle çağrı kaydeder (3.4 Takeover için)."""
    print("[*] 3.4 Canlı Müdahale (Takeover) simüle çağrısı FastAPI'ye kaydediliyor...")
    url = "http://127.0.0.1:8000/api/operator/register-call"
    password = settings.admin_password
    auth = ("admin", password)

    # 8000 portundaki sunucu işletim modunda olabilir; ona sahte çağrı kaydedilmez.
    try:
        ready = httpx.get("http://127.0.0.1:8000/api/readiness", auth=auth, timeout=5.0)
        if ready.status_code != 200 or ready.json().get("demo_mode") is not True:
            print("[*] Çalışan demo sunucusu yok; canlı simüle çağrı kaydedilmedi.")
            return
    except httpx.HTTPError:
        print("[*] Çalışan demo sunucusu yok; canlı simüle çağrı kaydedilmedi.")
        return

    payload = {
        "session_id": "call_sim_active_01",
        "caller_id": "0532 555 12 34",
        "initial_turn_id": "turn_demo_live_01",
        "mos_score": 4.41,
        "rtf": 0.17,
    }

    try:
        r = httpx.post(url, json=payload, auth=auth, timeout=5.0)
        if r.status_code == 200:
            print("[OK] Canlı simüle çağrı başarıyla kaydedildi: call_sim_active_01")
        else:
            print(f"[!] register-call yanıtı: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"[!] Sunucuya HTTP ile bağlanılamadı ({e}); backend henüz açık değilse sunucu başladığında yüklenecektir.")


def main():
    print("=" * 65)
    print("  FREYATTS DEMO VERI YUKLEYICI (ornek veri, gercek olcum degildir)")
    print("=" * 65)

    if not settings.demo_mode or Path(engine.url.database).parent.name != "demo":
        sys.exit(f"Demo veritabanı dışında çalışılamaz: {engine.url.database}")

    alembic_config = Config(str(ROOT / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(alembic_config, "head")

    with Session() as db:
        seed_telemetry_and_conversations(db)
        seed_sip_warm_transfers(db)
        seed_lifts_and_queue(db)
        seed_ab_experiment_metrics(db)
        seed_inspections_and_diagnostics(db)
        seed_vehicles_and_quotes(db)
        seed_outbound_calls(db)

        # Doğrulama: Analitik çıktısını kontrol et
        ov = get_analytics_overview(db)
        print("\n--- Yüklenen örnek telemetri (gerçek ölçüm değildir) ---")
        print(f"Toplam Görüşme: {ov['summary']['total_conversations']} (Kanal: {ov['summary']['channels']})")
        print(f"Ortalama Süre: {ov['summary']['avg_duration_seconds']} sn | Ortalama Tur: {ov['summary']['avg_turns_per_conversation']}")
        print(f"İlk Ses Gecikmesi (TTFA) p50: {ov['latency_kpis']['first_audio_ms']['p50']} ms (Hedef: ~780 ms)")
        print(f"İlk Ses Gecikmesi (TTFA) p95: {ov['latency_kpis']['first_audio_ms']['p95']} ms (Hedef: ~1120 ms)")
        print(f"LLM İlk Token (TTFT) p50: {ov['latency_kpis']['llm_ms']['p50_first_token']} ms (Hedef: ~310 ms)")
        print(f"STT Gecikmesi p50: {ov['latency_kpis']['stt_ms']['p50']} ms (Hedef: ~240 ms)")
        print(f"TTS RTF Ortalaması: {ov['latency_kpis']['tts_ms']['avg_rtf']}x (Hedef: ~0.38x)")
        print(f"Barge-In Kesinti Sayısı: {ov['latency_kpis']['barge_in_count']} (Hedef: 4)")

    # Canlı çağrıyı kaydet
    register_live_call_in_server()
    print("\n[TAMAMLANDI] Deterministik demo seed işlemi başarıyla tamamlandı.")


if __name__ == "__main__":
    main()
~~~~

### scripts/check_demo_db.py

~~~~python
"""Demo veritabanı durumunu inceler ve eksik fixture'ları ekler."""
import sqlite3
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Istanbul")
DB_PATH = "data/demo/assistant.db"

def inspect_db():
    if not os.path.exists(DB_PATH):
        print(f"[HATA] Demo DB bulunamadı: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f"Tablolar: {tables}")

    for t in ["vehicles", "quotes", "slots", "appointments"]:
        if t in tables:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            print(f"  {t}: {cur.fetchone()[0]} kayit")
        else:
            print(f"  {t}: TABLO YOK")

    # Corolla var mı?
    if "vehicles" in tables:
        cur.execute("SELECT id, description, plate FROM vehicles WHERE description LIKE '%orolla%'")
        rows = cur.fetchall()
        if rows:
            print(f"\nCorolla araçları:")
            for r in rows:
                print(f"  id={r[0][:8]}... desc={r[1]} plate={r[2]!r}")
        else:
            print("\n[!] Corolla bulunamadı")

    # Yarın sabahın slotları var mı?
    if "slots" in tables:
        tomorrow = (datetime.now(TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
        cur.execute("SELECT id, starts_at FROM slots WHERE starts_at LIKE ? ORDER BY starts_at", (f"{tomorrow}%",))
        slots = cur.fetchall()
        if slots:
            print(f"\nYarın ({tomorrow}) slotları:")
            for s in slots:
                # Bu slotta randevu var mı?
                cur.execute("SELECT id, status, confirmed FROM appointments WHERE slot_id=?", (s[0],))
                apps = cur.fetchall()
                status = f"DOLU ({apps[0][1]})" if apps else "AÇIK"
                print(f"  {s[1]} → {status}")
        else:
            print(f"\n[!] Yarın ({tomorrow}) için slot bulunamadı")

    conn.close()

if __name__ == "__main__":
    inspect_db()
~~~~

### scripts/smoke_dialogue.py

~~~~python
"""Exercise the real local Ollama model against an isolated test database."""

import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import Base, Vehicle, Slot, Appointment
import backend.dialogue as module
from backend.models import models


async def main():
    folder = Path("data/dialogue-smoke")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (str(uuid.uuid4()) + ".db")
    engine = create_engine("sqlite:///" + str(path))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        if not db.query(Vehicle).count():
            db.add(Vehicle(description="Volkswagen Passat", plate="TEST"))
            db.add(
                Slot(
                    starts_at=(
                        datetime.now(timezone.utc) + timedelta(days=2)
                    ).isoformat()
                )
            )
            db.commit()
    module.Session = factory
    d = module.Dialogue("local-ollama-smoke")
    results = []
    for text in [
        "Adım Ada Yılmaz. Aracım Volkswagen Passat.",
        "Birinci seçenek.",
        "Evet, onaylıyorum.",
    ]:
        answer = await d.answer(text)
        results.append(
            {"user": text, "assistant": answer, "metrics": models.last_llm_metrics}
        )
    with factory() as db:
        count = db.query(Appointment).count()
    report = {"results": results, "appointments": count, "completed": d.done}
    Path("data/dialogue-smoke.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    engine.dispose()
    assert d.done and count == 1


if __name__ == "__main__":
    asyncio.run(main())
~~~~

### scripts/voice_acceptance.py

~~~~python
"""Isolated real-model browser acceptance, with a fresh database per run."""

import asyncio
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

KEEP_DATABASES = 3


def prune_old_databases(folder: Path, keep: int = KEEP_DATABASES):
    """Gecici klasorde yalnizca en yeni `keep` kabul veritabanini birakir."""
    files = sorted(folder.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(old) + suffix).unlink()
            except OSError:
                pass


async def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    # Depoyu sisirmemek icin %TEMP% altinda tutulur; son 3 veritabani saklanir.
    folder = Path(tempfile.gettempdir()) / "freya-acceptance"
    folder.mkdir(parents=True, exist_ok=True)
    database = folder / (str(uuid.uuid4()) + ".db")
    os.environ["DATABASE_URL"] = "sqlite:///" + database.as_posix()
    os.environ["AUDIOSOCKET_PORT"] = "9093"
    os.environ["REAL_MODELS"] = "1"
    os.environ["VOICE_TEST_URL"] = "http://127.0.0.1:8011"
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    import uvicorn
    from backend.main import app

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=8011, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            if task.done():
                await task
                raise RuntimeError("Kabul sunucusu başlatılamadı")
            await asyncio.sleep(0.1)
        command = (
            ["cmd.exe", "/d", "/c", "npx playwright test tests/voice.spec.ts"]
            if os.name == "nt"
            else ["npx", "playwright", "test", "tests/voice.spec.ts"]
        )
        process = await asyncio.create_subprocess_exec(*command, cwd=root / "frontend")
        code = await process.wait()
    finally:
        server.should_exit = True
        await task
    print(f"Kabul testi veritabanı: {database}")
    prune_old_databases(folder)
    if code:
        raise SystemExit(code)


if __name__ == "__main__":
    asyncio.run(main())
~~~~

### scripts/acoustic_benchmark.py

~~~~python
"""Kalite Kapısı 5 için gerçek ses ölçümü. Taklit model kullanmaz.

FreyaTTS ile ses üretir, telefon hattına çevirir ve faster-whisper ile geri tanır.
Sonuç data/acoustic/latest.json dosyasına, sesler data/acoustic/audio/ altına yazılır.
İşletim veritabanına dokunmaz.

    .venv\\Scripts\\python -m scripts.acoustic_benchmark
    .venv\\Scripts\\python -m scripts.acoustic_benchmark --all
    .venv\\Scripts\\python -m scripts.acoustic_benchmark --save-baseline

--save-baseline yalnızca sesler dinlenip onaylandıktan sonra kullanılmalıdır;
sonraki ölçümlerin F0 sapması bu kayda göre hesaplanır.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# backend içe aktarılmadan önce: işletim verisi okunmasın.
_database_dir = tempfile.TemporaryDirectory(prefix="freya-acoustic-", ignore_cleanup_errors=True)
os.environ["DEMO_MODE"] = "false"
os.environ["DATABASE_URL"] = "sqlite:///" + Path(_database_dir.name, "empty.db").as_posix()

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from backend.acoustic_evaluation import (  # noqa: E402
    baseline_path,
    build_baseline,
    build_report,
    evaluate_transcript,
    load_baseline,
    measure_f0,
    report_dir,
    report_path,
    select_cases,
    write_json,
)
from backend.audio import apply_telephony_eq_and_downsample_8k, resample  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.db import Base, Session, Vehicle, engine  # noqa: E402
from backend.models import models  # noqa: E402

FIXTURE = ROOT / "data" / "fixtures" / "legacy_320_cases.json"


def _vendor_commit() -> str | None:
    result = subprocess.run(
        ["git", "-C", str(ROOT / settings.freya_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None


async def measure_case(case: dict, audio_dir: Path) -> dict:
    row = {"id": case["id"], "category": case["category"], "text": case["text"], "channels": {}}
    try:
        start = time.perf_counter()
        audio = np.asarray(await models.synth(case["text"]), dtype=np.float32)
        elapsed = time.perf_counter() - start
    except Exception as error:
        row["error"] = f"{type(error).__name__}: {error}"
        return row

    duration = len(audio) / 48000
    row.update(tts_ms=round(elapsed * 1000), audio_seconds=round(duration, 2), rtf=round(elapsed / duration, 3))
    row["f0_hz"] = measure_f0(resample(audio, 48000, 16000), 16000)

    # Telefon hattına giden gerçek çıktı int16'dır; STT için [-1, 1] aralığına alınır.
    telephony_pcm = apply_telephony_eq_and_downsample_8k(audio)
    telephony = telephony_pcm.astype(np.float32) / 32768.0
    sf.write(audio_dir / f"{case['id']}_48k.wav", audio, 48000)
    sf.write(audio_dir / f"{case['id']}_8k.wav", telephony_pcm, 8000, subtype="PCM_16")

    for channel, wave, rate in (("studio_48k", audio, 48000), ("telephony_8k", telephony, 8000)):
        transcript = await models.transcribe(resample(wave, rate, 16000))
        row["channels"][channel] = evaluate_transcript(case["text"], transcript)
    return row


async def main(args) -> None:
    catalog = args.catalog_hotwords
    if catalog:
        Base.metadata.create_all(engine, tables=[Vehicle.__table__])
        with Session.begin() as db:
            db.add_all(Vehicle(id=f"benchmark-{i:03d}", description=name) for i, name in enumerate(catalog))
    settings.stt_catalog_hotwords = bool(catalog)

    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    selected = select_cases(cases, None if args.all else args.per_category)
    audio_dir = report_dir() / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    await asyncio.to_thread(models._load)
    # İlk sentez tembel başlatma içerir; ölçüme girmez.
    await models.synth("Merhaba.")

    rows = []
    for index, case in enumerate(selected, start=1):
        row = await measure_case(case, audio_dir)
        rows.append(row)
        telephone = row["channels"].get("telephony_8k") or {}
        print(
            f"[{index}/{len(selected)}] {case['id']} wer={telephone.get('wer')} "
            f"rtf={row.get('rtf')} f0={row.get('f0_hz')} {row.get('error') or ''}",
            flush=True,
        )

    report = build_report(
        rows,
        load_baseline(),
        provenance={
            "script": "scripts/acoustic_benchmark.py",
            "tts_model": "freyavoice/freya-tts",
            "tts_device": settings.tts_device,
            "tts_path": "models.synth",
            "freya_commit": _vendor_commit(),
            "stt_model": settings.stt_model,
            "stt_device": settings.stt_device,
            "stt_compute_type": settings.stt_compute_type,
            "stt_catalog_hints": settings.stt_catalog_hotwords,
            "stt_catalog_hotwords": catalog,
            "stt_min_rms": settings.stt_min_rms,
            "fixture": FIXTURE.name,
            "selection": "all" if args.all else f"first {args.per_category} per category",
            "lora_adapter": None,
        },
    )
    write_json(report_path(), report)
    if args.save_baseline:
        write_json(baseline_path(), build_baseline(report))

    summary = {key: report[key] for key in ("measured_at", "sample_count", "failed_synthesis", "tts", "f0")}
    summary["channels"] = report["channels"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-category", type=int, default=3, help="Her kategoriden alınacak cümle sayısı")
    parser.add_argument("--all", action="store_true", help="320 cümlenin tamamını ölç")
    parser.add_argument("--save-baseline", action="store_true", help="Sonucu F0 taban kaydı olarak kaydet")
    parser.add_argument("--catalog-hotwords", nargs="+", default=[], help="Yalıtılmış ölçüm kataloğundaki araç adları")
    try:
        asyncio.run(main(parser.parse_args()))
    finally:
        engine.dispose()
~~~~

## Sabit test verisi

Bu dosyalar ilk pakette yoktu; akustik ölçüm, M04/M05 raporları ve bazı testler bunları okur.

**Bayt bayt korunmalı:** `data/fixtures/legacy_320_cases.json` SHA-256 `7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e` olmalıdır (`automotive_voice/m05_report.py` ve `test_m04_adapter`, `test_m05_contracts` bunu denetler). Aşağıdan kopyalarken satır sonunu LF, kodlamayı BOM'suz UTF-8 tutun ve dosyanın sonunda tek satır sonu bırakın; ardından özeti doğrulayın:

```powershell
(Get-FileHash data\fixtures\legacy_320_cases.json -Algorithm SHA256).Hash
```

`data/a01yt/a01yt_v05_readonly.sqlite3` ikili dosyadır ve pakete konamaz; `automotive_voice/nlp/lexicon.py` (`from_a01yt_export`) bunu salt okunur açar. Eski depodan kopyalayın veya bu yolu kullanan M04/M11 adımlarını devre dışı bırakın.

### data/fixtures/LEGACY_IMPORT.md

```markdown
# Golden metin içe aktarma kaydı

- Kaynak: `FreyaTTS_A00_A01_Kapsamli_Deney_v2.zip` içindeki `Freya_A00_A01_Kapsamli_v2/config/cases.json`.
- Kayıt sayısı: **320**. İçerik bayt bayt değiştirilmeden kopyalandı.
- SHA-256: `7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e`.
- `oracle` alanları nihai telaffuz doğrulaması değildir. Gerçek WAV testi M11 aşamasına kadar yok.
```

### data/fixtures/legacy_320_cases.json

```json
[
  {
    "id": "PDF01",
    "category": "belge_ornegi",
    "text": "Volkswagen Passat aracınız için sizi arıyorum.",
    "tier": "smoke",
    "origin": "source_pdf",
    "oracle": "review_pending"
  },
  {
    "id": "PDF02",
    "category": "belge_ornegi",
    "text": "Aracınızın tahmini değeri bir milyon iki yüz elli bin Türk lirası.",
    "tier": "smoke",
    "origin": "source_pdf",
    "oracle": "review_pending"
  },
  {
    "id": "PDF03",
    "category": "belge_ornegi",
    "text": "Sizin için yarın saat on dört otuzda ekspertiz randevusu oluşturabiliriz.",
    "tier": "smoke",
    "origin": "source_pdf",
    "oracle": "review_pending"
  },
  {
    "id": "M01",
    "category": "fiyat",
    "text": "Aracınızın tahmini değeri 1.250.000 TL.",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "M02",
    "category": "fiyat",
    "text": "Aracınız için 1250000 ₺ teklif ediliyor.",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "M03",
    "category": "fiyat",
    "text": "Bakım ücreti 1.250,50 TL olarak görünüyor.",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "H01",
    "category": "saat",
    "text": "Yarın saat 14:30'da ekspertiz yapabiliriz.",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "H02",
    "category": "saat",
    "text": "Randevunuz 09:00'da başlayacak.",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "H03",
    "category": "saat",
    "text": "Yarın 15:00'te müsaitiz.",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "E01",
    "category": "motor",
    "text": "1.5 TSI motorlu araç stokta.",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "E02",
    "category": "motor",
    "text": "1,6 TDI motora sahip araç incelenecek.",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "V01",
    "category": "marka",
    "text": "Peugeot 308 için teklif hazırlıyorum.",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "V02",
    "category": "model",
    "text": "2023 model Nissan Qashqai hakkında bilgi vereyim.",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "V03",
    "category": "marka",
    "text": "Citroën C3 ve Škoda Octavia seçenekleri var.",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "V04",
    "category": "marka_ek",
    "text": "Qashqai'nin ekspertiz raporu hazır.",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "K01",
    "category": "mesafe",
    "text": "Araç 145.000 km yol yapmış.",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "T01",
    "category": "tarih",
    "text": "Randevuyu 2026-11-03 tarihine alalım.",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "T02",
    "category": "tarih",
    "text": "Servis 03.11.2026 tarihinde açılıyor.",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "C01",
    "category": "kontrol",
    "text": "Aracınız için sizi tekrar arıyorum!",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "C02",
    "category": "kontrol",
    "text": "Bu fiyatı onaylıyor musunuz?",
    "tier": "smoke",
    "origin": "curated_v1",
    "oracle": "review_pending"
  },
  {
    "id": "XFI01",
    "category": "finance_integer",
    "text": "Aracınızın ön değerleme bedeli 1.250.000 TL olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI02",
    "category": "finance_integer",
    "text": "Güncel teklifimiz 985.000 TL olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI03",
    "category": "finance_integer",
    "text": "İlan fiyatı 3.450.000 TL olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI04",
    "category": "finance_integer",
    "text": "Ekspertiz sonrası tahmini fiyat 750.000 TL olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI05",
    "category": "finance_integer",
    "text": "İşlemin yaklaşık tutarı 1250000 TL olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI06",
    "category": "finance_integer",
    "text": "Aracınızın ön değerleme bedeli 2.035.000 TRY olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI07",
    "category": "finance_integer",
    "text": "Güncel teklifimiz 850.500 ₺ olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI08",
    "category": "finance_integer",
    "text": "İlan fiyatı 475.000 TL olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI09",
    "category": "finance_integer",
    "text": "Ekspertiz sonrası tahmini fiyat 6.250.000 TL olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI10",
    "category": "finance_integer",
    "text": "İşlemin yaklaşık tutarı 1.099.000 TL olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI11",
    "category": "finance_integer",
    "text": "Aracınızın ön değerleme bedeli 450000 TL olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI12",
    "category": "finance_integer",
    "text": "Güncel teklifimiz 925.000 TRY olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI13",
    "category": "finance_integer",
    "text": "İlan fiyatı 2.750.000 TL olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI14",
    "category": "finance_integer",
    "text": "Ekspertiz sonrası tahmini fiyat 100.000 ₺ olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI15",
    "category": "finance_integer",
    "text": "İşlemin yaklaşık tutarı 210.000 TL olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI16",
    "category": "finance_integer",
    "text": "Aracınızın ön değerleme bedeli 1.000.000 TL olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI17",
    "category": "finance_integer",
    "text": "Güncel teklifimiz 999.999 TL olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI18",
    "category": "finance_integer",
    "text": "İlan fiyatı 22.500 TRY olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI19",
    "category": "finance_integer",
    "text": "Ekspertiz sonrası tahmini fiyat 12.000 TL olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI20",
    "category": "finance_integer",
    "text": "İşlemin yaklaşık tutarı 44.000 TL olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI21",
    "category": "finance_integer",
    "text": "Aracınızın ön değerleme bedeli 500.000 ₺ olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI22",
    "category": "finance_integer",
    "text": "Güncel teklifimiz 1.800.000 TL olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI23",
    "category": "finance_integer",
    "text": "İlan fiyatı 9.875.000 TL olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI24",
    "category": "finance_integer",
    "text": "Ekspertiz sonrası tahmini fiyat 1.245.500 TRY olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFI25",
    "category": "finance_integer",
    "text": "İşlemin yaklaşık tutarı 650000 TL olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "integer_currency"
  },
  {
    "id": "XFD01",
    "category": "finance_decimal",
    "text": "Ön kontrol bedeli 1.250,50 TL olarak listelendi.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD02",
    "category": "finance_decimal",
    "text": "Otopark ücreti 2.999,99 TL olarak listelendi.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD03",
    "category": "finance_decimal",
    "text": "Bakım için hesaplanan tutar 850,75 TL olarak listelendi.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD04",
    "category": "finance_decimal",
    "text": "Ek işlem maliyeti 125,40 TL olarak listelendi.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD05",
    "category": "finance_decimal",
    "text": "Parça fiyatı 100,01 TL olarak listelendi.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD06",
    "category": "finance_decimal",
    "text": "Ön kontrol bedeli 19,90 TL olarak listelendi.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD07",
    "category": "finance_decimal",
    "text": "Otopark ücreti 1.000,05 TL olarak listelendi.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD08",
    "category": "finance_decimal",
    "text": "Bakım için hesaplanan tutar 999,50 TL olarak listelendi.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD09",
    "category": "finance_decimal",
    "text": "Ek işlem maliyeti 2.500,25 ₺ olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD10",
    "category": "finance_decimal",
    "text": "Parça fiyatı 17.250,10 TL olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD11",
    "category": "finance_decimal",
    "text": "Ön kontrol bedeli 6.390,80 TL olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD12",
    "category": "finance_decimal",
    "text": "Otopark ücreti 250,00 TL olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD13",
    "category": "finance_decimal",
    "text": "Bakım için hesaplanan tutar 8.500,45 TL olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD14",
    "category": "finance_decimal",
    "text": "Ek işlem maliyeti 129,95 TL olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD15",
    "category": "finance_decimal",
    "text": "Parça fiyatı 65,05 TL olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD16",
    "category": "finance_decimal",
    "text": "Ön kontrol bedeli 1.499,00 TL olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD17",
    "category": "finance_decimal",
    "text": "Otopark ücreti 4.999,90 TL olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD18",
    "category": "finance_decimal",
    "text": "Bakım için hesaplanan tutar 7.250,65 ₺ olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD19",
    "category": "finance_decimal",
    "text": "Ek işlem maliyeti 45,75 TL olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD20",
    "category": "finance_decimal",
    "text": "Parça fiyatı 1.000,99 TL olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD21",
    "category": "finance_decimal",
    "text": "Ön kontrol bedeli 1.650,15 TL olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD22",
    "category": "finance_decimal",
    "text": "Otopark ücreti 700,35 TL olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD23",
    "category": "finance_decimal",
    "text": "Bakım için hesaplanan tutar 15,60 TL olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD24",
    "category": "finance_decimal",
    "text": "Ek işlem maliyeti 12.450,85 TL olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XFD25",
    "category": "finance_decimal",
    "text": "Parça fiyatı 250.999,95 TL olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "minor_unit"
  },
  {
    "id": "XCL01",
    "category": "clock",
    "text": "Randevunuz yarın 14:30'da başlayacak.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL02",
    "category": "clock",
    "text": "Ekspertiz görüşmesi yarın 09:00'da başlayacak.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL03",
    "category": "clock",
    "text": "Sizi yarın 15:00'te arayabilir miyiz?",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL04",
    "category": "clock",
    "text": "Servis kabulü yarın 08:45'te başlayacak.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL05",
    "category": "clock",
    "text": "Test sürüşü yarın 10:15'te başlayacak.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL06",
    "category": "clock",
    "text": "Randevunuz yarın 11:30'da başlayacak.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL07",
    "category": "clock",
    "text": "Ekspertiz görüşmesi yarın 16:20'de başlayacak.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL08",
    "category": "clock",
    "text": "Sizi yarın 17:00'de arayabilir miyiz?",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL09",
    "category": "clock",
    "text": "Servis kabulü yarın 13:05'te başlayacak.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL10",
    "category": "clock",
    "text": "Test sürüşü yarın 18:55'te başlayacak.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL11",
    "category": "clock",
    "text": "Randevunuz yarın 07:40'ta başlayacak.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL12",
    "category": "clock",
    "text": "Ekspertiz görüşmesi yarın 19:10'da başlayacak.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL13",
    "category": "clock",
    "text": "Sizi yarın 12:00'de arayabilir miyiz?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL14",
    "category": "clock",
    "text": "Servis kabulü yarın 22:30'da başlayacak.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL15",
    "category": "clock",
    "text": "Test sürüşü yarın 06:05'te başlayacak.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL16",
    "category": "clock",
    "text": "Randevunuz yarın 20:00'de başlayacak.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL17",
    "category": "clock",
    "text": "Ekspertiz görüşmesi yarın 21:15'te başlayacak.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL18",
    "category": "clock",
    "text": "Sizi yarın 16:00'da arayabilir miyiz?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL19",
    "category": "clock",
    "text": "Servis kabulü yarın 14:45'te başlayacak.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL20",
    "category": "clock",
    "text": "Test sürüşü yarın 09:25'te başlayacak.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL21",
    "category": "clock",
    "text": "Randevunuz yarın 10:00'da başlayacak.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL22",
    "category": "clock",
    "text": "Ekspertiz görüşmesi yarın 08:30'da başlayacak.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL23",
    "category": "clock",
    "text": "Sizi yarın 11:05'te arayabilir miyiz?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL24",
    "category": "clock",
    "text": "Servis kabulü yarın 13:50'de başlayacak.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCL25",
    "category": "clock",
    "text": "Test sürüşü yarın 15:35'te başlayacak.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "clock_suffix"
  },
  {
    "id": "XCA01",
    "category": "calendar",
    "text": "Randevu tarihi 2026-11-03 olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA02",
    "category": "calendar",
    "text": "Servis kayıt tarihi 03.11.2026 olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA03",
    "category": "calendar",
    "text": "Teklifin düzenlendiği tarih 2026-12-18 olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA04",
    "category": "calendar",
    "text": "Araç teslim planı 18.12.2026 olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA05",
    "category": "calendar",
    "text": "Değerleme görüşmesi 2027-01-05 olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA06",
    "category": "calendar",
    "text": "Randevu tarihi 05.01.2027 olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA07",
    "category": "calendar",
    "text": "Servis kayıt tarihi 2027-02-28 olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA08",
    "category": "calendar",
    "text": "Teklifin düzenlendiği tarih 28.02.2027 olarak görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA09",
    "category": "calendar",
    "text": "Araç teslim planı 2026-10-31 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA10",
    "category": "calendar",
    "text": "Değerleme görüşmesi 31.10.2026 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA11",
    "category": "calendar",
    "text": "Randevu tarihi 2027-04-23 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA12",
    "category": "calendar",
    "text": "Servis kayıt tarihi 23.04.2027 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA13",
    "category": "calendar",
    "text": "Teklifin düzenlendiği tarih 2026-09-17 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA14",
    "category": "calendar",
    "text": "Araç teslim planı 17.09.2026 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA15",
    "category": "calendar",
    "text": "Değerleme görüşmesi 2028-02-29 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA16",
    "category": "calendar",
    "text": "Randevu tarihi 29.02.2028 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA17",
    "category": "calendar",
    "text": "Servis kayıt tarihi 2026-06-15 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA18",
    "category": "calendar",
    "text": "Teklifin düzenlendiği tarih 15.06.2026 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA19",
    "category": "calendar",
    "text": "Araç teslim planı 2026-01-01 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA20",
    "category": "calendar",
    "text": "Değerleme görüşmesi 01.01.2026 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA21",
    "category": "calendar",
    "text": "Randevu tarihi 2027-07-14 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA22",
    "category": "calendar",
    "text": "Servis kayıt tarihi 14.07.2027 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA23",
    "category": "calendar",
    "text": "Teklifin düzenlendiği tarih 2026-08-30 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA24",
    "category": "calendar",
    "text": "Araç teslim planı 30.08.2026 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XCA25",
    "category": "calendar",
    "text": "Değerleme görüşmesi 2027-05-19 olarak görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "date_order"
  },
  {
    "id": "XEN01",
    "category": "engine",
    "text": "Bu araç 1.5 TSI motor seçeneğiyle listeleniyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN02",
    "category": "engine",
    "text": "İncelediğimiz otomobil 1,6 TDI motor seçeneğiyle listeleniyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN03",
    "category": "engine",
    "text": "Satıştaki model 2.0 TDI motor seçeneğiyle listeleniyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN04",
    "category": "engine",
    "text": "Ekspertize alınacak araç 1.2 TCe motor seçeneğiyle listeleniyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN05",
    "category": "engine",
    "text": "Test sürüşü aracı 1.3 TCe motor seçeneğiyle listeleniyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN06",
    "category": "engine",
    "text": "Bu araç 1.5 dCi motor seçeneğiyle listeleniyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN07",
    "category": "engine",
    "text": "İncelediğimiz otomobil 2.0 TFSI motor seçeneğiyle listeleniyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN08",
    "category": "engine",
    "text": "Satıştaki model 1.4 TSI motor seçeneğiyle listeleniyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN09",
    "category": "engine",
    "text": "Ekspertize alınacak araç 1.0 TSI motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN10",
    "category": "engine",
    "text": "Test sürüşü aracı 1.6 HDI motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN11",
    "category": "engine",
    "text": "Bu araç 1,5 TSI motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN12",
    "category": "engine",
    "text": "İncelediğimiz otomobil 2,0 TDI motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN13",
    "category": "engine",
    "text": "Satıştaki model 1.6 CDI motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN14",
    "category": "engine",
    "text": "Ekspertize alınacak araç 1.4 TDI motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN15",
    "category": "engine",
    "text": "Test sürüşü aracı 1.8 TSI motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN16",
    "category": "engine",
    "text": "Bu araç 2.5 TSI motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN17",
    "category": "engine",
    "text": "İncelediğimiz otomobil 2.2 CDI motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN18",
    "category": "engine",
    "text": "Satıştaki model 1.9 TDI motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN19",
    "category": "engine",
    "text": "Ekspertize alınacak araç 1.6 TCe motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN20",
    "category": "engine",
    "text": "Test sürüşü aracı 1.3 dCi motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN21",
    "category": "engine",
    "text": "Bu araç 1.2 TSI motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN22",
    "category": "engine",
    "text": "İncelediğimiz otomobil 1.1 TSI motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN23",
    "category": "engine",
    "text": "Satıştaki model 1.6 TFSI motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN24",
    "category": "engine",
    "text": "Ekspertize alınacak araç 2.4 TDI motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XEN25",
    "category": "engine",
    "text": "Test sürüşü aracı 1.5 HDI motor seçeneğiyle listeleniyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "decimal_engine"
  },
  {
    "id": "XMI01",
    "category": "mileage",
    "text": "Araç 145.000 km olarak kaydedilmiş.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI02",
    "category": "mileage",
    "text": "İncelenen otomobil 35.000 km olarak kaydedilmiş.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI03",
    "category": "mileage",
    "text": "Bu model 1.500 km olarak kaydedilmiş.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI04",
    "category": "mileage",
    "text": "Ön değerlendirme kaydı 223.400 km olarak kaydedilmiş.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI05",
    "category": "mileage",
    "text": "Satıştaki araç 950 km olarak kaydedilmiş.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI06",
    "category": "mileage",
    "text": "Araç 85.000 km olarak kaydedilmiş.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI07",
    "category": "mileage",
    "text": "İncelenen otomobil 240.000 km olarak kaydedilmiş.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI08",
    "category": "mileage",
    "text": "Bu model 10.000 km olarak kaydedilmiş.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI09",
    "category": "mileage",
    "text": "Ön değerlendirme kaydı 300.000 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI10",
    "category": "mileage",
    "text": "Satıştaki araç 125000 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI11",
    "category": "mileage",
    "text": "Araç 4.250 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI12",
    "category": "mileage",
    "text": "İncelenen otomobil 67.890 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI13",
    "category": "mileage",
    "text": "Bu model 250.150 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI14",
    "category": "mileage",
    "text": "Ön değerlendirme kaydı 44.444 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI15",
    "category": "mileage",
    "text": "Satıştaki araç 55.500 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI16",
    "category": "mileage",
    "text": "Araç 99.950 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI17",
    "category": "mileage",
    "text": "İncelenen otomobil 120.000 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI18",
    "category": "mileage",
    "text": "Bu model 12.345 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI19",
    "category": "mileage",
    "text": "Ön değerlendirme kaydı 175.000 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI20",
    "category": "mileage",
    "text": "Satıştaki araç 280.000 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI21",
    "category": "mileage",
    "text": "Araç 130.300 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI22",
    "category": "mileage",
    "text": "İncelenen otomobil 18.250 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI23",
    "category": "mileage",
    "text": "Bu model 199.999 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI24",
    "category": "mileage",
    "text": "Ön değerlendirme kaydı 222.000 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XMI25",
    "category": "mileage",
    "text": "Satıştaki araç 72.500 km olarak kaydedilmiş.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "thousands_distance"
  },
  {
    "id": "XVN01",
    "category": "vehicle_names",
    "text": "Volkswagen Passat aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN02",
    "category": "vehicle_names",
    "text": "Peugeot 308 aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN03",
    "category": "vehicle_names",
    "text": "Nissan Qashqai aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN04",
    "category": "vehicle_names",
    "text": "Citroën C3 aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN05",
    "category": "vehicle_names",
    "text": "Škoda Octavia aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN06",
    "category": "vehicle_names",
    "text": "Renault Clio aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN07",
    "category": "vehicle_names",
    "text": "Dacia Duster aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN08",
    "category": "vehicle_names",
    "text": "Porsche Macan aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN09",
    "category": "vehicle_names",
    "text": "Chevrolet Cruze aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN10",
    "category": "vehicle_names",
    "text": "Toyota Corolla aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN11",
    "category": "vehicle_names",
    "text": "Honda Civic aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN12",
    "category": "vehicle_names",
    "text": "Hyundai Tucson aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN13",
    "category": "vehicle_names",
    "text": "BMW X5 aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN14",
    "category": "vehicle_names",
    "text": "Mercedes-Benz C 200 aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN15",
    "category": "vehicle_names",
    "text": "Audi A3 aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN16",
    "category": "vehicle_names",
    "text": "Opel Corsa aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN17",
    "category": "vehicle_names",
    "text": "Ford Focus aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN18",
    "category": "vehicle_names",
    "text": "Fiat Egea aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN19",
    "category": "vehicle_names",
    "text": "Tesla Model Y aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN20",
    "category": "vehicle_names",
    "text": "Volvo XC40 aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN21",
    "category": "vehicle_names",
    "text": "SEAT Leon aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN22",
    "category": "vehicle_names",
    "text": "Cupra Formentor aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN23",
    "category": "vehicle_names",
    "text": "Land Rover Defender aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN24",
    "category": "vehicle_names",
    "text": "Jeep Renegade aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XVN25",
    "category": "vehicle_names",
    "text": "MINI Cooper aracınızın satış ve ekspertiz seçeneklerini açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "brand_model"
  },
  {
    "id": "XFS01",
    "category": "foreign_suffix",
    "text": "Qashqai'nin ilgili servis kaydını inceliyorum.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS02",
    "category": "foreign_suffix",
    "text": "Qashqai'ye ilgili servis kaydını inceliyorum.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS03",
    "category": "foreign_suffix",
    "text": "Qashqai'den ilgili servis kaydını inceliyorum.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS04",
    "category": "foreign_suffix",
    "text": "Qashqai'de ilgili servis kaydını inceliyorum.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS05",
    "category": "foreign_suffix",
    "text": "Peugeot'nun ilgili servis kaydını inceliyorum.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS06",
    "category": "foreign_suffix",
    "text": "Peugeot'ya ilgili servis kaydını inceliyorum.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS07",
    "category": "foreign_suffix",
    "text": "Peugeot'dan ilgili servis kaydını inceliyorum.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS08",
    "category": "foreign_suffix",
    "text": "Peugeot'da ilgili servis kaydını inceliyorum.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS09",
    "category": "foreign_suffix",
    "text": "Renault'nun ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS10",
    "category": "foreign_suffix",
    "text": "Renault'ya ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS11",
    "category": "foreign_suffix",
    "text": "Citroën'den ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS12",
    "category": "foreign_suffix",
    "text": "Citroën'de ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS13",
    "category": "foreign_suffix",
    "text": "Škoda'ya ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS14",
    "category": "foreign_suffix",
    "text": "Škoda'dan ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS15",
    "category": "foreign_suffix",
    "text": "Volkswagen'de ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS16",
    "category": "foreign_suffix",
    "text": "Volkswagen'den ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS17",
    "category": "foreign_suffix",
    "text": "Dacia'ya ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS18",
    "category": "foreign_suffix",
    "text": "Dacia'dan ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS19",
    "category": "foreign_suffix",
    "text": "Porsche'den ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS20",
    "category": "foreign_suffix",
    "text": "Porsche'ye ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS21",
    "category": "foreign_suffix",
    "text": "Chevrolet'ye ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS22",
    "category": "foreign_suffix",
    "text": "Chevrolet'den ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS23",
    "category": "foreign_suffix",
    "text": "Qashqai'nın ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS24",
    "category": "foreign_suffix",
    "text": "Peugeot'yu ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XFS25",
    "category": "foreign_suffix",
    "text": "Renault'yu ilgili servis kaydını inceliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "morphology_manual_review"
  },
  {
    "id": "XSH01",
    "category": "short_dialogue",
    "text": "Evet.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH02",
    "category": "short_dialogue",
    "text": "Hayır.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH03",
    "category": "short_dialogue",
    "text": "Elbette.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH04",
    "category": "short_dialogue",
    "text": "Anladım.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH05",
    "category": "short_dialogue",
    "text": "Bir dakika.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH06",
    "category": "short_dialogue",
    "text": "Lütfen.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH07",
    "category": "short_dialogue",
    "text": "Teşekkür ederim.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH08",
    "category": "short_dialogue",
    "text": "Rica ederim.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH09",
    "category": "short_dialogue",
    "text": "Dinliyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH10",
    "category": "short_dialogue",
    "text": "Tabii.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH11",
    "category": "short_dialogue",
    "text": "Mümkün.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH12",
    "category": "short_dialogue",
    "text": "Uygun.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH13",
    "category": "short_dialogue",
    "text": "Kontrol ediyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH14",
    "category": "short_dialogue",
    "text": "Hemen bakıyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH15",
    "category": "short_dialogue",
    "text": "Haklısınız.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH16",
    "category": "short_dialogue",
    "text": "Şimdi açıklayayım.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH17",
    "category": "short_dialogue",
    "text": "Bir saniye.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH18",
    "category": "short_dialogue",
    "text": "Sizi duyuyorum.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH19",
    "category": "short_dialogue",
    "text": "Devam edebilirsiniz.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH20",
    "category": "short_dialogue",
    "text": "Yardımcı olayım.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH21",
    "category": "short_dialogue",
    "text": "Peki.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH22",
    "category": "short_dialogue",
    "text": "Tamamdır.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH23",
    "category": "short_dialogue",
    "text": "Memnuniyetle.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH24",
    "category": "short_dialogue",
    "text": "Kontrol edelim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XSH25",
    "category": "short_dialogue",
    "text": "Başka sorunuz var mı?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "short_audio_control"
  },
  {
    "id": "XQU01",
    "category": "questions",
    "text": "Bu araç hâlâ satışta mı?",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU02",
    "category": "questions",
    "text": "Ekspertiz raporunu görebilir miyim?",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU03",
    "category": "questions",
    "text": "Fiyat teklifini bugün alabilir miyim?",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU04",
    "category": "questions",
    "text": "Servis kaydı var mı?",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU05",
    "category": "questions",
    "text": "Aracın hasar geçmişi nedir?",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU06",
    "category": "questions",
    "text": "Randevumu değiştirebilir miyim?",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU07",
    "category": "questions",
    "text": "Peugeot 308 için uygun saatiniz var mı?",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU08",
    "category": "questions",
    "text": "Volkswagen Passat için teklifiniz nedir?",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU09",
    "category": "questions",
    "text": "Fiyatı tekrar söyleyebilir misiniz?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU10",
    "category": "questions",
    "text": "Muayene ne zaman bitiyor?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU11",
    "category": "questions",
    "text": "Araç hâlâ garantili mi?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU12",
    "category": "questions",
    "text": "Test sürüşü mümkün mü?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU13",
    "category": "questions",
    "text": "Ödeme yöntemleriniz nelerdir?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU14",
    "category": "questions",
    "text": "Bu fiyat vergiler dahil mi?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU15",
    "category": "questions",
    "text": "Aracı bugün teslim alabilir miyim?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU16",
    "category": "questions",
    "text": "Kilometresi doğrulandı mı?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU17",
    "category": "questions",
    "text": "Beni daha sonra arayabilir misiniz?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU18",
    "category": "questions",
    "text": "Bu görüşme kaydediliyor mu?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU19",
    "category": "questions",
    "text": "Bir insan temsilciyle görüşebilir miyim?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU20",
    "category": "questions",
    "text": "Bana neden ulaştığınızı açıklar mısınız?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU21",
    "category": "questions",
    "text": "Randevu talebimi iptal edebilir miyim?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU22",
    "category": "questions",
    "text": "Aracın motor seçeneği hangisi?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU23",
    "category": "questions",
    "text": "Aracın yakıt türü nedir?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU24",
    "category": "questions",
    "text": "Teklifinizin geçerlilik süresi ne kadar?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XQU25",
    "category": "questions",
    "text": "Ekspertiz sonucuna göre fiyat değişir mi?",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "question_prosody"
  },
  {
    "id": "XLC01",
    "category": "long_context",
    "text": "Bilginizi doğruladıktan sonra otomobilinizin güncel piyasa değerini açıklayabilirim, ancak bunun kesin satış fiyatı olmadığını lütfen unutmayın.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC02",
    "category": "long_context",
    "text": "Volkswagen Passat için fiyat teklifini hazırlamadan önce aracın model yılını, kilometre bilgisini ve geçmiş hasar kayıtlarını teyit etmem gerekiyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC03",
    "category": "long_context",
    "text": "Müşteri temsilcimize yönlendirmeden önce şu bilgiyi paylaşmak isterim, araç için bugün verilen tahmini değer ekspertiz incelemesiyle değişebilir.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC04",
    "category": "long_context",
    "text": "Randevunuzun uygunluğunu kontrol edeceğim; eğer belirttiğiniz saat doluysa, size yakın zamanlı başka seçenekler önerebilirim.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC05",
    "category": "long_context",
    "text": "Peugeot 308 aracınızın bakımı için servis kaydı oluşturabiliriz, ancak işlemin kapsamını araç muayenesinden sonra netleştirmemiz gerekiyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC06",
    "category": "long_context",
    "text": "Nissan Qashqai hakkında konuşurken fiyat, donanım ve yakıt tüketimi gibi bilgileri birbirine karıştırmadan sırayla açıklamak istiyorum.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC07",
    "category": "long_context",
    "text": "İlk olarak aracın servis geçmişini kontrol ediyoruz, ardından kilometre ve boya değişen bilgilerini karşılaştırarak fiyat teklifini hazırlıyoruz.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC08",
    "category": "long_context",
    "text": "Randevunuzu oluşturmadan önce kişisel bilgilerinizi teyit edeceğim; istemezseniz bu görüşmeyi sonlandırabilir veya bir temsilciye aktarabilirim.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC09",
    "category": "long_context",
    "text": "Teklif almak için aracınızın plakasını şu an paylaşmanız gerekmiyor, ilk aşamada marka, model ve yılı öğrenmem yeterli.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC10",
    "category": "long_context",
    "text": "Belirttiğiniz saatte müsaitlik görünmezse başka bir gün seçebilirsiniz, uygun gördüğünüz zaman aralığını birlikte belirleyebiliriz.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC11",
    "category": "long_context",
    "text": "Aracın teknik özelliklerini açıklarken motor hacmi ile yakıt tüketimini aynı şeymiş gibi değerlendirmemek gerekir; bunlar farklı bilgilerdir.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC12",
    "category": "long_context",
    "text": "Kısa bir bilgi vermek isterim, bu görüşmedeki fiyatlar yalnızca ön değerlendirme amaçlıdır ve kesinleştirme için yetkili onayı gerekir.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC13",
    "category": "long_context",
    "text": "İsterseniz önce aracınızın ekspertiz gereksinimlerini belirleyebilir, daha sonra müsait randevu seçeneklerini tek tek değerlendirebiliriz.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC14",
    "category": "long_context",
    "text": "Test sürüşü talebi için önce aracı ve şubeyi seçiyoruz, daha sonra uygun tarih ve saati doğrulayıp talebinizi oluşturuyoruz.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC15",
    "category": "long_context",
    "text": "İkinci el araç alımında değerleme sonucu araç donanımına, bakım geçmişine, kilometreye ve ekspertiz bulgularına göre değişebilir.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC16",
    "category": "long_context",
    "text": "Sizi anlıyorum, fiyat teklifimiz beklediğinizden düşük olabilir; dilerseniz hangi bilgilerin değerlendirmeye alındığını açıklayabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC17",
    "category": "long_context",
    "text": "Size araçla ilgili eksik ya da doğrulanmamış bilgi vermek istemem, bu nedenle bazı ayrıntıları yetkili sistemden tekrar kontrol edeceğim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC18",
    "category": "long_context",
    "text": "Aracınızın model yılı ve kilometre değeri netleştiğinde bir ön teklif sunabiliriz, ancak fiyatın sonradan değişebileceğini belirtmeliyim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC19",
    "category": "long_context",
    "text": "Bugün konuştuğumuz randevu saatini sizin adınıza kesinleştirmeden önce, seçtiğiniz şubenin uygunluk bilgisini güncel olarak kontrol etmeliyim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC20",
    "category": "long_context",
    "text": "Önce aracınızın mevcut durumunu ve geçmiş işlemlerini açıklamanızı rica edeceğim, sonrasında sizi uygun ekspertiz hizmetine yönlendireceğim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC21",
    "category": "long_context",
    "text": "Satış sürecini üç adımda açıklayayım: ön değerleme, yerinde ekspertiz ve teklif onayı; her adım ayrı bir kontrol gerektirir.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC22",
    "category": "long_context",
    "text": "Şu anda sizin için işlem yapmıyorum, sadece seçenekleri açıklıyorum; randevu veya teklif oluşturmak için ayrıca onayınızı isteyeceğim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC23",
    "category": "long_context",
    "text": "Yarın için düşündüğünüz saat uygun değilse başka seçenekler gösterebilirim, böylece size en uygun zamanı birlikte bulabiliriz.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC24",
    "category": "long_context",
    "text": "Peugeot aracınızın parça ve bakım durumunu kontrol etmeden kesin bir masraf söylemem doğru olmaz, yaklaşık aralığı ayrıca paylaşabilirim.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XLC25",
    "category": "long_context",
    "text": "Son olarak tekrar belirtmek isterim, bu konuşma bir yapay zekâ asistanıyla gerçekleşmektedir ve talep ederseniz insan temsilciye aktarılabilirsiniz.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "boundary_chunking"
  },
  {
    "id": "XTT01",
    "category": "technical_terms",
    "text": "ABS kontrolü yapıldı.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT02",
    "category": "technical_terms",
    "text": "ESP sistemi etkin görünüyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT03",
    "category": "technical_terms",
    "text": "ADAS kamera kalibrasyonu gerekiyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT04",
    "category": "technical_terms",
    "text": "DSG şanzıman testi yapılacak.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT05",
    "category": "technical_terms",
    "text": "CVT şanzıman hakkında bilgi veriyorum.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT06",
    "category": "technical_terms",
    "text": "PHEV sisteminde batarya kontrolü yapılmalı.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT07",
    "category": "technical_terms",
    "text": "BEV araçlar için şarj kaydı isteniyor.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT08",
    "category": "technical_terms",
    "text": "AWD çekiş sistemi kontrol edilecek.",
    "tier": "regression",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT09",
    "category": "technical_terms",
    "text": "SUV sınıfı araç değerlendiriliyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT10",
    "category": "technical_terms",
    "text": "Euro NCAP değerlendirmesi soruldu.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT11",
    "category": "technical_terms",
    "text": "Akü 12 V olarak ölçüldü.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT12",
    "category": "technical_terms",
    "text": "Batarya kapasitesi 75 kWh olarak bildirildi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT13",
    "category": "technical_terms",
    "text": "Motor gücü 110 kW olarak belirtildi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT14",
    "category": "technical_terms",
    "text": "Motor gücü 150 HP olarak açıklandı.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT15",
    "category": "technical_terms",
    "text": "Araç 4x4 sürüş sistemine sahip.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT16",
    "category": "technical_terms",
    "text": "OBD bağlantısını kontrol edebiliriz.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT17",
    "category": "technical_terms",
    "text": "ECU yazılım güncellemesi talep edildi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT18",
    "category": "technical_terms",
    "text": "TPMS uyarısı ekranda görünüyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT19",
    "category": "technical_terms",
    "text": "LED farların ayarı yapılacak.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT20",
    "category": "technical_terms",
    "text": "Start Stop sistemi etkin.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT21",
    "category": "technical_terms",
    "text": "Hibrit araç için rejeneratif fren kontrolü istendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT22",
    "category": "technical_terms",
    "text": "Araçta ISOFIX bağlantısı bulunuyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT23",
    "category": "technical_terms",
    "text": "Şanzıman tipi e-CVT olarak listelendi.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT24",
    "category": "technical_terms",
    "text": "Araçta DSG ve TSI terimleri geçiyor.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  },
  {
    "id": "XTT25",
    "category": "technical_terms",
    "text": "VIN kodunu telefonda heceleyerek doğrulamayalım.",
    "tier": "stress",
    "origin": "curated_synthetic",
    "oracle": "review_pending",
    "focus": "acronym_review"
  }
]
```

### data/fixtures/text_contract_examples.jsonl

```json
{"id":"FREYA-DOC-001","raw":"Volkswagen Passat aracınız için sizi arıyorum.","source":"FreyaTTS_Teknik_Arastirma.pdf","purpose":"brand_context"}
{"id":"FREYA-DOC-002","raw":"Aracınızın tahmini değeri bir milyon iki yüz elli bin Türk lirası.","source":"FreyaTTS_Teknik_Arastirma.pdf","purpose":"price_context"}
{"id":"FREYA-DOC-003","raw":"Sizin için yarın saat on dört otuzda ekspertiz randevusu oluşturabiliriz.","source":"FreyaTTS_Teknik_Arastirma.pdf","purpose":"appointment_context"}
{"id":"FREYA-TEXT-004","raw":"2023 model Nissan Qashqai için 14:30'da ekspertiz alabilir miyim?","source":"architecture_design","purpose":"time_and_brand"}
{"id":"FREYA-TEXT-005","raw":"1.5 TSI motor ve 145.000 km olan aracın fiyatı 1.250.000 TL mi?","source":"architecture_design","purpose":"numeric_ambiguity"}
```

### data/a01yt/first50_targets.csv

```csv
target_id,group,canonical_target,candidate_sentence_not_transcript,evaluation_focus,source_id,start_sec,end_sec,observed_transcript,approved_pronunciation,review_status,notes
YT50-001,marka,Volkswagen,Volkswagen Passat aracınız için sizi arıyorum.,yabancı marka / Türkçe konuşma,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-002,marka,Peugeot,Peugeot 3008 için teklif verebilir miyiz?,Fransızca marka / ses uyumu,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-003,marka,Citroën,Citroën C3 modelinin fiyatını öğrenmek istiyorum.,diakritik / telaffuz,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-004,marka,Škoda,Škoda Octavia için randevu oluşturabiliriz.,desteklenmeyen büyük Š,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-005,marka,Renault,Renault Clio aracı satılık mı?,sessiz harf ve Türkçe okunuş,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-006,marka,Hyundai,Hyundai Tucson modelini inceliyoruz.,çoklu konuşmacı değişkesi,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-007,marka,Dacia,Dacia Duster için ekspertiz gerekiyor.,sesletim varyantı,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-008,marka,Porsche,Porsche Cayenne araç hakkında bilgi alabilir miyim?,yabancı özel isim,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-009,marka,Chevrolet,Chevrolet araçların motor seçenekleri nelerdir?,yabancı özel isim,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-010,marka,Mercedes-Benz,Mercedes-Benz C200 ekspertize gelecek.,tireli özel isim,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-011,model,Qashqai,Nissan Qashqai aracınız hakkında konuşmak istiyorum.,q harfi; kelime sonu,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-012,model,Passat,Passat modeliniz için uygun bir saat var.,çift s/aksan,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-013,model,Tiguan,Tiguan araçların kampanyası var mı?,yabancı model,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-014,model,T-Roc,Volkswagen T-Roc modeli mevcut mu?,tireli model,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-015,model,3008,Peugeot 3008 modelinin fiyatı nedir?,sayısal model kodu,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-016,model,C3 Aircross,Citroën C3 Aircross araç inceliyoruz.,harf sayı kodu,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-017,model,e-POWER,Nissan e-POWER hibrit teknolojisini kullandım.,İngilizce büyük harf / hibrit,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-018,model,RAV4,Toyota RAV4 test sürüşüne uygun mu?,harf+sayısal kod,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-019,model,iX1,BMW iX1 modelinin bataryası ne kadar?,harf+sayısal kod,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-020,model,quattro,Audi quattro çekiş sistemine sahip mi?,q harfi / teknik isim,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-021,ek,Qashqai’nin,Qashqai’nin kaputunu kontrol edebiliriz.,kesme / ilgi eki,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-022,ek,Qashqai’ye,Qashqai’ye uygun bakım paketi sunuyoruz.,yönelme eki,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-023,ek,Peugeot’ya,Peugeot’ya özel indirim mevcut mu?,yönelme eki,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-024,ek,Peugeot’nun,Peugeot’nun garanti şartları nelerdir?,ilgi eki,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-025,ek,Citroën’den,Citroën’den yeni model geldi.,ayrılma eki,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-026,ek,Škoda’nın,Škoda’nın motor özellikleri nedir?,ilgi eki,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-027,ek,Volkswagen’in,Volkswagen’in servis bakım ücreti ne kadar?,ilgi eki,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-028,ek,Tiguan’a,Tiguan’a uygun lastikler hangileri?,yönelme eki,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-029,ek,Renault’da,Renault’da bakım randevusu var mı?,bulunma ekinin bağlamı,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-030,ek,Passat’ta,Passat’ta yağ kaçağı olabilir mi?,bulunma eki,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-031,teknik,1.5 TSI,Bu araçta 1.5 TSI motor kullanılıyor.,ondalık motor / kısaltma,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-032,teknik,1.2 PureTech,Peugeot 1.2 PureTech benzinli motora sahip.,ondalık motor / motor ailesi,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-033,teknik,e-CVT,Toyota hibrit e-CVT şanzıman kullanıyor.,kısaltma / tire,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-034,teknik,DSG,Aracın DSG şanzımanı kontrol edilecek.,Türkçe kısaltma okunuşu,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-035,teknik,TDI,TDI motorda turbo kontrolü yapıldı.,kısaltma,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-036,teknik,AdBlue,AdBlue seviyesi düşmüş olabilir.,yabancı marka/ürün ismi,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-037,teknik,Start-Stop,Start-Stop sistemi devre dışı kalmış.,tireli teknik ifade,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-038,teknik,ABS,ABS sisteminde uyarı var.,harf harf okunuş,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-039,teknik,ESP,ESP sisteminin kontrolü yapıldı.,harf harf okunuş,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-040,teknik,mild hybrid,Mild hybrid motor seçeneğini öneriyoruz.,İngilizce teknik terim,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-041,sayi,1.250.000 TL,Tahmini satış fiyatı 1.250.000 TL.,fiyat / binlik,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-042,sayi,1250000 ₺,Araç için 1250000 ₺ teklif ediliyor.,fiyat / para birimi,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-043,sayi,14:30’da,Yarın saat 14:30’da ekspertiz randevunuz var.,saat / ek,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-044,sayi,145.000 km,Araç 145.000 km yol yapmış.,kilometre / binlik,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-045,sayi,2023 model,2023 model otomatik vites araç arıyorum.,model yılı / sayının okunuşu,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-046,diyalog,onay sorusu,Randevu talebinizi oluşturmamı ister misiniz?,soru tonlaması,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-047,diyalog,kısa ret,"Hayır, teşekkür ederim.",kısa ifade / son ek,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-048,diyalog,müsaitlik,Yarın öğleden sonra sizin için uygun olur mu?,doğal duraksama,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-049,diyalog,fiyat açıklaması,Aracınızın tahmini piyasa değeri bir milyon iki yüz elli bin Türk lirasıdır.,uzun fiyat / ritim,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
YT50-050,diyalog,yeniden yönlendirme,"Elbette, önce aracınızın güncel kilometresini öğrenebilir miyim?",karşılıklı konuşma / vurgu,,,,,,awaiting_authorized_audio,Planlanan sorgu; gerçek videoda duyulduğu iddia edilmez.
```

### data/a01yt/sources_verbal_permission_v05.csv

```csv
id,creator,title,url,rights_basis,rights_evidence,permission_claim_status,audio_use_authorized,platform_authorized,media_origin,permitted_scope,attribution
YT-PEUGEOT-001,PaylaşıYorum,Yeni Peugeot 3008 GT 1.2 Hybrid Test Sürüşü ve Detaylı İnceleme | PaylaşıYorum,https://www.youtube.com/watch?v=ieB48xTjR3M,verbal_permission,Kullanici 2026-10-31 tarihinde bu uc videonun hak sahiplerinin arkadasi oldugunu ve telefonla telafuz referansi olarak kullanim izni aldigini bildirdi. Beyan bagimsiz dogrulanmadi; platformdan indirme yetkisi cikarsanamaz.,user_attested,1,0,youtube_link,tts_lexicon_reference,PaylaşıYorum
YT-QASHQAI-001,PaylaşıYorum,2024 Makyajlı Nissan Qashqai e-Power Platinum Premium Test Sürüşü ve Detaylı İnceleme | PaylaşıYorum,https://www.youtube.com/watch?v=5BLRHiTz2ks,verbal_permission,Kullanici 2026-10-31 tarihinde bu uc videonun hak sahiplerinin arkadasi oldugunu ve telefonla telafuz referansi olarak kullanim izni aldigini bildirdi. Beyan bagimsiz dogrulanmadi; platformdan indirme yetkisi cikarsanamaz.,user_attested,1,0,youtube_link,tts_lexicon_reference,PaylaşıYorum
YT-QASHQAI-002,Alaatin61,Pratik ve Ekonomik Suv - Yeni Nissan Qashqai - TR'de ilk Kez,https://www.youtube.com/watch?v=lz0hZU8ATAQ,verbal_permission,Kullanici 2026-10-31 tarihinde bu uc videonun hak sahiplerinin arkadasi oldugunu ve telefonla telafuz referansi olarak kullanim izni aldigini bildirdi. Beyan bagimsiz dogrulanmadi; platformdan indirme yetkisi cikarsanamaz.,user_attested,1,0,youtube_link,tts_lexicon_reference,Alaatin61
```

### data/a01yt/approved_lexicon_v05_snapshot.json

```json
{
  "approved_rules": [],
  "conflicts": [],
  "generated_at": "2026-10-31T00:34:12+00:00",
  "policy": "Only globally unambiguous, human-approved observations.",
  "schema_version": 1
}
```

### data/a01yt/freya_char_vocab.json

```json
{"<FILL>": 0, "<UNK>": 1, " ": 2, "%": 3, "&": 4, "'": 5, "+": 6, ",": 7, "-": 8, ".": 9, "/": 10, "0": 11, "1": 12, "2": 13, "3": 14, "4": 15, "5": 16, "6": 17, "7": 18, "8": 19, "9": 20, ":": 21, ";": 22, ">": 23, "?": 24, "A": 25, "B": 26, "C": 27, "D": 28, "E": 29, "F": 30, "G": 31, "H": 32, "I": 33, "J": 34, "K": 35, "L": 36, "M": 37, "N": 38, "O": 39, "P": 40, "Q": 41, "R": 42, "S": 43, "T": 44, "U": 45, "V": 46, "W": 47, "X": 48, "Y": 49, "Z": 50, "a": 51, "b": 52, "c": 53, "d": 54, "e": 55, "f": 56, "g": 57, "h": 58, "i": 59, "j": 60, "k": 61, "l": 62, "m": 63, "n": 64, "o": 65, "p": 66, "r": 67, "s": 68, "t": 69, "u": 70, "v": 71, "w": 72, "x": 73, "y": 74, "z": 75, "Ç": 76, "Ö": 77, "Ü": 78, "á": 79, "â": 80, "ç": 81, "ö": 82, "ú": 83, "ü": 84, "ğ": 85, "İ": 86, "ı": 87, "Ş": 88, "ş": 89, "’": 90, "€": 91}
```

## Kabul ölçümünün yeniden alınması

Referans değerler 01 belgesindeki "Ölçülmüş değerler" tablosundadır. Yeni sürümde aynı ölçümü aynı 320 cümleyle alın ve yan yana yazın:

1. `scripts/acoustic_benchmark.py --all`: TTS ile sentez, 8 kHz telefon bandına çevirme, STT ile geri tanıma. Sonuç `data/acoustic/latest.json`. Ölçüm, sonucu işletim veritabanına yazmamak için boş geçici veritabanı kullanır.
2. Ölçümü ayrı bir veri dizinine yazmak için `DATA_DIR` verin; mevcut `latest.json` üzerine yazılmasın.
3. `--save-baseline` yalnız sesler dinlenip onaylandıktan sonra kullanılır; F0 sapması bu kayda göre hesaplanır.
4. Kalite kapısı: ölçülen kriter eşiği aşarsa FAIL, ölçülmemiş kriter varsa HOLD, hepsi ölçülüp geçerse PASS. Eşikler: WER ≤ %30, CER ≤ %25, terim doğruluğu ≥ %95, konuşmacı benzerliği (ABX) ≥ 0,8, F0 sapması ≤ 2,3 Hz.
5. Ölçüm sentetik sesle yapılır. İnsan sesi, gürültü ve aksan için ayrı kayıt seti gerekir; bu set referans sürümde yoktur.
