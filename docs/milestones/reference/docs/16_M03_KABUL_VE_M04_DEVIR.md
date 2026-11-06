# M03 Teknik Kabul ve M04 Devri

## Doğrulanan kapsam

- [x] M01 ve M02 public API'leri değişmeden geri uyumlu.
- [x] Otomotiv diyalog iş politikası, açık randevu durum makinesi.
- [x] Mock CRM araç bilgisi, süresi kontrol edilen fiyat ve açık müşteri talebiyle takip kaydı.
- [x] Mock rezervasyon için AVAILABLE / UNAVAILABLE / UNKNOWN / CONFIRMED kesin ayrımı.
- [x] Açık müşteri onayı, idempotency, ikinci randevu önlemi, belirsiz sonucu recheck etme.
- [x] Kimlik, CRM yetkisi, pazarlama izninden bağımsız işlem yetkisi ve veri ref ayrımı.
- [x] M02'ye `LLM_RESPONSE_READY` veya `HANDOFF_REQUESTED` sadece güncel tur/nesil ile.
- [x] Sentetik CLI senaryosu ve güvenlik olumsuz senaryoları.
- [x] 320 eski veri vakasının dosya bütünlüğü korunur.

## Kabul kararı

`M03_MOCK_POLICY_PASS / M01_M02_REGRESSION_PASS / REAL_TTS_NOT_RUN / REAL_PBX_NOT_RUN / PRODUCTION_READINESS_HOLD`

Bu paket production-ready değildir. Mock geçiş testi gerçek servis idempotency, gerçek kullanıcı kimlik doğrulama, KVKK, kalıcı outbox veya veri güvenliği denetiminin yerine geçmez.

## M04 devri

**M04 — Türkçe Normalizer + Otomotiv Telaffuz Sözlüğü + NLU Sözleşmesi.**

- M03 `DialogueInput` şeması ve ayrı referans kasası değişmeden korunacak.
- M01/M02 52 test ve M03 yeni testler yeşil kalacak.
- Mevcut A00/A01 320 cümlesi **değiştirilmeden** golden fixture olarak tutulacak.
- A01-YT kaynak veri tabanı yalnız onaylı telaffuz anotasyonlarını sözlüğe taşıyacak.
- Metin normalizasyonu -> intent/slot çıkarma arayüzü ve çakışan marka/ek kuralları test edilecek.
- İş kritik kararların LLM'ye bırakılmaması korunacak.
- Gerçek ses üretimi, YouTube ses kesme, telefon bağlantısı, GPU ve MOS/WER en sona bırakılacak.

## Üretim öncesi kayıtlı borçlar

1. Kalıcı işlem/ses komutu outbox, işlem yeniden başlatma ve replay.
2. Dağıtık transactional idempotency, rezervasyon backend mutabakat ve gerçek API geçerlilik süresi.
3. Gerçek kimlik ispatı, PII şifreleme, saklama/silme ve yetki denetimi.
4. Gerçek NLU kalitesi, Türkçe ekler, zaman dilimi / DST / tatil / çalışma saati kuralları.
5. Gerçek ses/medya ACK ve telefon hata dayanıklılığı.
6. UI tamamlandıktan sonraki tam sentetik E2E ve fiziksel kabul.
