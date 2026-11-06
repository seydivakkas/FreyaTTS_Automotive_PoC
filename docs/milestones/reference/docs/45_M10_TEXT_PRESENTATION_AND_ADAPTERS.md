# M10 — Konuşma Sunumu ve Gerçek Adaptör Portları

## Ayrım: display vs speech

M03 iş kuralları aynen kalır. `PolicySpeechPresenter` yalnızca **M03 iş kararı kesinleştikten sonra** `StoredResponse(text, category)` üzerinde çalışır; orijinal metin operatör ekranı/audit için değişmeden saklanır. `ProsodyCoordinator` içine **opsiyonel** `presentation` parametresi eklendi; varsayılan `None` olduğu için M01–M09 test akışı bozulmadı.

| M03 kategori | Yeni speech hazırlığı | Korunan kural |
|---|---|---|
| `price_verified` | `1.250.000 Türk lirasıdır.` → `1.250.000 TL.` sonra M04 | M03 doğrulanmış fiyat olmadan fiyat yok |
| `offer_confirmation` | ISO offset + sabit tanımlı konum kimliği → gün/ay/yıl + saat + servis yeri | Müsaitlik/rezervasyon statüsü değişmez, bilinmeyen yer HOLD |
| `booking_confirmed`, `booking_reconciled`, `already_confirmed`, `crm_case_created` | Rastgele referans kodu **sözlü okunmaz**, ekranda kalır | Servis doğrulaması olmadan `CONFIRMED` yok |
| diğer kategoriler | M03 metni değiştirilmez | M04/M05 `review_required` kapısı çalışır |

M04 normalizer, M05 clause planner ve A01-YT onay kapısı atlanmaz. Qashqai, Peugeot, Citroën, Škoda gibi isimler için yeni tahmini telaffuz üretilmez. M10'da 20 sentetik senaryoda `speech_review_blocked=0` bulunması **akustik doğruluk**, approved lexicon veya gerçek TTS hazır olma anlamına gelmez.

## Dört çevrimdışı adaptör sözleşmesi

`OfflineReadiness` ve `AdapterConfig` özellikleri:

- **Freya:** desteklenen yerel uygulayıcı, mutlak model dizini, işlem süre sınırı; ses üretilmez.
- **Whisper/STT:** yerel model dizini ve timeout sözleşmesi; dinleme yapılmaz.
- **LLM:** allowlist sağlayıcı ve URL/secret-env ön denetimi; istek atılmaz.
- **Asterisk PBX:** WebSocket / AudioSocket sağlayıcı adı, codec/sample-rate metaverisi; bağlantı, arama, FLUSH gerçek ACK veya DNS çözümleme yapılmaz.

Dış uç noktalar `external_endpoint_not_tested` bulgusu üretir. Düz HTTP/WS dış sunucu için güvenlik uyarısı verilir. Ortam değişkeni adları kullanılır; sır içerikleri rapora yazılmaz. `enabled=True` M10'da zorunlu `real_activation_explicitly_disabled_in_M10` bulgusu üretir. `ready_for_activation=False` tasarım gereği sabittir.

## Arayüz

M08 localhost operatör paneline `M10 Hazırlık` ekranı eklendi. Yalnızca offline yapılandırma sonuçları gösterilir; doğrudan açma/kapatma, anahtar girme, gerçek servis bağlama ya da gerçek ses oynatma kontrolleri **yoktur**. M08'in mevcut volatil simülasyon oturumları ayrıca **SQLite kalıcı yöneticiye yükseltilmedi**; kalıcılık M10 dry-run'da bağımsız olarak doğrulanır.
