# M11 — Fiziksel Kabul ve Gerçek Ses Doğrulama Planı

**Başlangıç durumu (01.11.2026):** M10 yazılım/kuru testleri PASS. Gerçek Windows, Freya, STT, Asterisk ve A01-YT klipleri çalıştırılmadı. Fiziksel kabul **HOLD**. Bu belge kullanıcıya ait Windows 11 / RTX 4070 bilgisayarında yürütülecek işlemleri tanımlar; mevcut ortamda yapılmış test gibi yorumlanamaz.

## 1. Ön koşullar ve izlenebilirlik

1. Windows 11, Python 3.11 x64, Edge; güncel NVIDIA sürücüsü ve CUDA uyumlu PyTorch kurulumu. Donanım ve ortam değerleri `preflight_details.json` altında saklanır.
2. FreyaTTS-small'ın **yerel** ve güvenilir kaynaktan alınmış `model.safetensors`, `config.json` dosyaları. `freyavoice/freya-tts` model kimliği ve upstream Git commit hash'i dondurulmalı; model SHA-256 ile belgelenmeli. Önceki model, ağırlık ve ses tohumu değiştirilmez.
3. `FreyaTTS.from_pretrained(<local_model_dir>,device='cuda')`, `synthesize(text,steps=32,seed=9)` kullanılır. Çıktı 48 kHz mono; Freya'nın bağımlılığı AudioVAE2'nin yerelde gerçekten bulunması ayrıca kontrol edilir. Yükleme sırasında bağımlılık indirebilecek üçüncü taraf paketler kullanıcı kontrolünde kurulmalıdır.
4. İlk çalıştırma 12 cümleye kadar *smoke*; tam çalışma inceleme kapısından geçen golden set çiftleriyle. İnceleme gerektiren 29 vaka **sessizce düzeltilmez veya PASS yapılmaz**.
5. Sentetik test kayıtları gerçek fiziksel ses/çağrı delili değildir. A/B dinleme değerlendirmesinde dinleyici adı, kaynak/düzeltilmiş sürüm, model SHA, ses dosyası SHA, tutarlılık ve anlaşılırlık kaydedilir.

## 2. Kabul kapıları

| Kapı | Önce / sonra | Kabul kanıtı | Mevcut durum |
|---|---|---|---|
| Windows/Edge | Preflight ve panel kabulü | İşletim sistemi, donanım, test tutanağı | HOLD |
| Freya/Leyla | 320 A/B çifti, sabit seed 9, steps 32 | 640 kayıt, gerçek süre/RTF, insan dinleme ve sabit ses kimliği | HOLD |
| STT/VAD | Etiketli konuşma ve kesme deneyi | WER/CER, VAD başlangıç/zaman ölçümü, mikrofon/geri besleme | HOLD |
| Codec | 48k→16k→8k, µ-law/A-law, 20ms | Gerçek sesi kodlama ve PBX'e karşı çözme/playout | HOLD |
| Asterisk | Canlı, yetkili test çağrısı | MEDIA_START, REPORT_QUEUE_DRAINED, FLUSH_MEDIA, QUEUE_DRAINED, gerçek duyulan ses kesilmesi, HANGUP | HOLD |
| A01-YT | Yetkili özgün kliplerden ilk 50 | Ses hash, kaynak zamanları, insan transkript ve telaffuz onayı | HOLD |
| Güvenlik/KVKK | Gözlem + erişim testi | Veri maskeleme, rıza, operatör yetkisi, retention/backup kanıtı | HOLD |
| M01–M10 regresyon | Birim ve kuru entegrasyon | Test logu + 320 golden SHA | PASS (bu M11 koşusunda yenilenecek) |

**Fiziksel kabul** için tüm kapıların kanıtlı PASS olması gerekir; ancak bu bile otomatik olarak geniş ölçekli üretim, siber güvenlik ve mevzuat sertifikasyonu anlamına gelmez. M10 risk kaydı yürürlüktedir.

## 3. Asterisk protokol notları

Resmî `chan_websocket` desteği 20.16.0 / 21.11.0 / 22.6.0 / 23.0.0 ve üstünde bulunur. JSON kontrol biçimi ise 20.18.0 / 22.8.0 / 23.2.0 ve üstünden itibaren desteklenir. Kurulan Asterisk sürümü bu eşiklerle karşılaştırılmalıdır.

`FLUSH_MEDIA` komutu *tek başına* ayrı bir `MEDIA_FLUSHED`/ACK olayı üretmez. Asterisk dokümanında, kuyruk boşalmasını denetlemek için `REPORT_QUEUE_DRAINED` komutunun `FLUSH_MEDIA` **öncesinde** gönderilmesi ve `QUEUE_DRAINED` bildiriminin izlenmesi tanımlanır. `QUEUE_DRAINED` ile **karşı tarafta eski sesin gerçekten kesildiği** ayrı akustik zaman ölçümü karıştırılmamalıdır. Geç eski `GenerationId` paketleri reddedilmeli, XOFF/XON ve hangup yarışları gözlenmelidir.

Kaynak: https://docs.asterisk.org/Configuration/Channel-Drivers/WebSocket/

## 4. Örnek hız/kalite metrikleri — ön kabul hedefleri

RTF = sentez süresi / üretilen ses süresi, TTFA = sentez isteği ile ilk kullanılabilir ses arasında geçen zaman (yalnızca tam cümle `synthesize` ölçümü **TTFA değildir**), WER/CER konuşma referansına göre hesaplanır. İlk laboratuvar hedefi olarak `p95 barge-in sonrası duyulan eski ses <= 400 ms` ve boşluk/kırpılma bulunmaması kullanılabilir; bu sayılar **proje içi önerilen hedeflerdir, doğrulanmış sonuç değildir**. P95 için en az 30 gerçek kesilme örneği gereklidir.

## 5. Risk ve geri dönüş

- Model özdeşliği/seed farklıysa `HOLD`, önceki ağırlığa dön.
- Onaysız marka okunuşu, geçersiz fiyat/tarih/saat: `HOLD`, M04 inceleme akışına dön.
- Çifte rezervasyon veya belirsiz CRM etkisi: canlı çağrıları kapat, yalnız idempotency anahtarıyla uzlaştır.
- PBX flush gözlemi eksikse `HOLD`; telefon adaptörünü fiziksel güvence vermiş sayma.
- KVKK/PII veya veri güvenliği sorunu: gerçek müşteri verisini toplama ve saklama; kayıt izinleri doğrulanmadan devam etme.

## 6. Kaynaklar

- FreyaTTS small: https://github.com/freyavoiceai/FreyaTTS ve https://huggingface.co/freyavoice/freya-tts
- Asterisk `chan_websocket`: https://docs.asterisk.org/Configuration/Channel-Drivers/WebSocket/
- M10→M11 devir: `docs/47_M10_M11_DEVIR_VE_AGENT_GOREVI.md`
