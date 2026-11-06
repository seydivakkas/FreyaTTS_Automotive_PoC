# Windows 11 — M11 adım adım

## 0. Güvenli hazırlık

Önce projeyi ayrı bir Windows çalışma dizinine çıkart; gerçek müşteri/CRM işlemleri için ayrıca onaylanmış test ortamı kullan. Python 3.11 ve FFmpeg'i sistem PATH üzerinden doğrula. `nvidia-smi` çalışmalı. Freya kaynak repo ve model dosyalarının bulunduğu yerel dizinleri kendin belirle; hash ile kaydet. `pip install -e ".[validation]"` yalnız M01–M11 test bağımlılıklarını sağlar, Freya/Whisper model bağımlılıklarını **kurmaz**. Bunlar ayrı, kullanıcı kontrolünde yüklenmelidir.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[validation]"
.\scripts\check_m11.ps1 -Python ".\.venv\Scripts\python.exe" -ModelDir "D:\Models\freya-small" -FreyaCheckout "D:\src\FreyaTTS"
```

`check_m11.ps1` **yalnız test ve offline preflight** çalıştırır; hiçbir modele/telefona bağlanmaz. Linux üzerinde de çalıştırılabilir ama Windows kapısı HOLD olur.

## 1. Freya gerçek smoke (açık onayla)

Önce [FreyaTTS resmi kurulumunu](https://github.com/freyavoiceai/FreyaTTS) gözden geçir; modelin VoxCPM2/AudioVAE2 gereksinimini karşıla. Repo ve model sürümü dondur. Başlangıçta 12 cümlelik smoke, ardından inceleme kapısından geçen tam test. Dosyalar `data/m11/audio` içine kaydedilir.

```powershell
.\scripts\m11_tts_smoke.ps1 -ModelDir "D:\Models\freya-small" -FreyaCheckout "D:\src\FreyaTTS" -Python ".\.venv\Scripts\python.exe"
# Aynı ortam doğrulandıktan sonra:
.\scripts\m11_tts_smoke.ps1 -ModelDir "D:\Models\freya-small" -FreyaCheckout "D:\src\FreyaTTS" -Python ".\.venv\Scripts\python.exe" -Full
```

Bu betik model yükler ve WAV üretir; **yalnızca belirtilen Windows makinesinde** çalıştırılmalıdır. `synthesize` tam cümle çağrısını ölçer; streaming TTFA/ilk parça hazır olma ölçümü değildir. Her iki variant için aynı seed ve steps kullanılır. İnceleme kapısına takılan vakalar atlanır, sebepleri raporlanır; bu nedenle 640 WAV'ın otomatik tamamlanması vaat edilmez.

## 2. Türkçe STT ve VAD

Gerçek bir konuşmacının rızasıyla kaydedilmiş, transkripti insan tarafından düzeltmiş mono PCM WAV seti ve yerel Whisper modeli gerekir. `data/m11/templates/stt_manifest_example.jsonl` alanlarını izle. `faster-whisper` ayrı kurulur.

```powershell
.\.venv\Scripts\python.exe -m automotive_voice.m11 stt --enable-physical --model-dir "D:\Models\whisper" --manifest "D:\sesler\stt_manifest.jsonl" --device cuda
```

Komut WER/CER hesaplar. Gerçek VAD barge-in zamanlaması bu komutta **ölçülmez**; ayrıca PBX ve mikrofon deneyi gerekir. Tam STT/VAD kabulü bu aşamada HOLD.

## 3. Codec / gerçek ses ile dönüşüm

```powershell
.\.venv\Scripts\python.exe -m automotive_voice.m11 codec --enable-physical --input-wav "D:\sesler\riza_alinmis_ornek.wav"
```

FFmpeg ile PCM 16k/8k, G.711 μ-law/A-law dosyaları hazırlanır; ses çözme ve telefon yolu ölçümü yapılmadan codec kapısı HOLD.

## 4. Asterisk canlı görüşme ve söz kesilme

Kontrollü test numarası, hedef sürüm, uygun dialplan, yetkilendirilmiş kanal açılmalı. `MEDIA_START`, `REPORT_QUEUE_DRAINED`, `FLUSH_MEDIA`, `QUEUE_DRAINED`, `HANGUP` sırası aynı `channel_id` üzerinden derlenmeli; fiziksel eski sesin durma süresi bağımsız ölçülmeli. `data/m11/templates/pbx_trace_example.jsonl` yalnız alan şablonudur, gerçek kanıt değildir. Sahte olay izini PASS yapmak yasaktır.

```powershell
.\.venv\Scripts\python.exe -m automotive_voice.m11 pbx --enable-physical --trace "D:\logs\gercek_pbx_olaylari.jsonl" --capture-file "D:\logs\pbx_raw.log" --observer-record "D:\logs\independent_observer.json"
```

## 5. A01-YT ilk 50 izinli referans

İzin beyanları 3 kaynağa aittir. YouTube seslerini izinsiz teknik yöntemlerle çekmek yerine hak sahiplerinden doğrudan verilen özgün dosyalar kullanılır. Her klip mono PCM 16-bit WAV, SHA-256, video/source id, start/end zaman kodu, insan transkripti/okunuşu, reviewer ve onay tarihi taşımalıdır.

```powershell
.\.venv\Scripts\python.exe -m automotive_voice.m11 a01yt --manifest "D:\Sesler\first50_reviewed.jsonl"
```

Örnek şema: `data/m11/templates/a01yt_record_example.jsonl`. Bu komut ses çıkartmaz; eldeki gerçek anotasyon kayıtlarının dosya/kanıt bütünlüğünü inceler.

## 6. Fiziksel ortam ve KVKK kabulü

Gerçek Windows/Edge ve güvenlik denetimi tamamlandıktan sonra reviewer, gözlem tutanağını **manuel** onaylayabilir. Bu komut donanımın gerçekte test edildiğini kendiliğinden kanıtlamaz; tutanağı SHA ile bağlar.

```powershell
.\.venv\Scripts\python.exe -m automotive_voice.m11 manual --gate windows_edge --status PASS --enable-physical --reviewer "Test Sorumlusu" --statement "Windows 11 ve Edge üzerinde yerel panel, GPU ve kayıt izinleri fiziksel olarak test edildi." --evidence "D:\logs\windows_kabul_tutanagi.txt"
```

En son `scripts/m11_report.ps1` çalıştır. Eksik kapılar `HOLD` olarak kalır. Hiçbir kapıyı sırf yazılım testleri PASS diye zorla geçirme.

Bağımsız gözlem tutanağı örneği: `{"channel_id":"<REAL_ID>","observer":"<INDEPENDENT_TESTER>","mock":false,"heard_old_audio_ms_after_speech_start":250}`. Bu değer kullanıcı tarafından gerçek laboratuvar gözlemine göre doldurulmalı; örnek sayı sonuç olarak kullanılamaz. Ham Asterisk capture, kanal kimliği ve `MEDIA_START`, `FLUSH_MEDIA`, `QUEUE_DRAINED` kayıtlarını içermelidir. JSON dosyaları tek başlarına gerçekliği kriptografik olarak kanıtlamaz; dış laboratuvar denetimi gereklidir.

## 1A. Leyla ses kimliğini ve telaffuzu insan dinlemesiyle onaylama

Tüm 320 A/B çiftinin WAV dosyaları (640 dosya) tamamlandıktan ve M04/M05 inceleme bekleyen vakaları kanıtlı biçimde çözüldükten sonra `data/m11/templates/leyla_review_example.jsonl` şemasında her vaka için bir dinleyici değerlendirmesi oluştur. Ses dosyası SHA-256 değerleri `freya_leyla_measurements.json` içinde bulunur. `leyla_identity_pass` ve `prepared_pronunciation_pass` gerçek dinlemeye dayanmalı; örnek şablondaki değerler kullanılmamalıdır.

```powershell
.\.venv\Scripts\python.exe -m automotive_voice.m11 voice-review --manifest "D:\Sesler\leyla_review_320.jsonl"
```

Bu aşama tam 320 A/B karşılaştırması, 640 mevcut ve hash'ı doğru 48 kHz WAV, 320 insan onayı ve tüm vakalarda Leyla kimliği/telaffuz kontrolü olmadan PASS üretemez. İnceleme yapıldıktan sonra `m11_report.ps1` ile durumu yeniden oluştur.

Asterisk PBX PASS için bağımsız dinleme kaydında ayrıca `measurements_ms` adlı **en az 30 gerçek kesilme ölçümü** bulunmalıdır. p95 değeri 400 ms üstündeyse kabul başarısız; daha az gözlem varsa HOLD.
