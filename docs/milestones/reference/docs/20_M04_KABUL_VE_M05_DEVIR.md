# M04 Kabul / M05 Devri

## M04 kabul kapsamı

- [x] M01-M03 regresyonları korunur.
- [x] Standard library temelinde Türkçe sayı, fiyat, tarih, saat, motor ve kilometre metin ön işleme.
- [x] Hata, Unicode ve Freya tokenizer OOV fail-closed.
- [x] A01-YT okuma-only SQLite portu; onaylı ses kaydı olmayan kaynaktan telaffuz üretilmez.
- [x] Explicit suffix map ve geçerli kanıtlı lexicon kuralı.
- [x] Deterministik mock NLU, güvenilir araç/lokasyon ve timezone portları.
- [x] M03 `DialogueInput`/`ReferenceStore` bağlama; M02 olaylarında opak ref.
- [x] Golden 320 metin karşılaştırması, kaynak SHA-256 sabit.
- [x] JSON Schema ve sentetik olumsuz senaryo testleri.

## Bilinçli olarak bekleyen konular

1. Gerçek YouTube sesinden akustik telaffuz çıkarımı, insan onayı, gerçek clip SHA yeniden doğrulaması.
2. Temel FreyaTTS'nin model ağırlıkları, telaffuz ve Leyla sesi kalite deneyleri; MOS/WER/CER/RTF.
3. Kodlu NLU kapsamının model/genel doğal dil başarımına genellenmesi; gerçek kullanıcı ASR varyantları.
4. Türkçe tüm çekim ekleri, bağlama göre marka telaffuzu, tüm tarih/fiyat biçimleri.
5. Kalıcı audit/outbox, KVKK uyumluluğu, çoklu iş parçacığı ve kalıcı servislere dayanıklılık.
6. Windows 3.11, yerel GPU ve gerçek telefon fiziksel kabulü.

## Kabul işareti

`M04_TEXT_CONTRACTS_PASS / M01_M03_REGRESSION_PASS / A01YT_APPROVED_LEXICON_EMPTY / AUDIO_NOT_RUN / PRODUCTION_HOLD`.

## M05 — Prosody / Clause Planner & TTS Input Contract

- `NormalizationResult` içindeki `review_required=True` çıktılar TTS'ye sessizce gönderilmeyecek.
- Kesilebilir cümle planlama, Türkçe sözcük ve anlam sınırları, alıntı ve fiyat bütünlüğü.
- Phrase/Clause kimlikleri `GenerationId` ile bağlanacak.
- Freya model adaptörü dummy/mock olacak; model ağırlığı yüklenmeyecek.
- M01-M04 regresyon, golden 320, cancellation / stale output, replay testleri yeşil kalacak.
- Tasarım -> UI -> sentetik entegrasyon -> en son fiziksel ses ve telefon sırası değişmez.
