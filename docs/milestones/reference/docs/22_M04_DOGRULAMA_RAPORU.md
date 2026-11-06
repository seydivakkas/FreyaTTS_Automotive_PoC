# M04 Doğrulama Raporu — 31.10.2026

## Test kapsamı

- M01/M02/M03 regresyon: **117**.
- M04 yeni birim, A01-YT SQLite, NLU, Unicode, JSON Schema ve referans köprüsü: **76**.
- Toplam: **193/193 PASS**. Çalıştırılan ortam: Linux / Python 3.13. Windows/Python 3.11 ek fiziksel doğrulama yapılmadı.

## 320 metin üzerinde ölçülen metin etkisi

| Ölçüm | Sayı |
|---|---:|
| Orijinal golden vaka | 320 |
| Metin değişen | 163 |
| İnceleme gerektiren | 29 |
| Bunların içinde Freya karakter OOV içeren | 16 |
| A01-YT kaynak beyanı | 3 |
| Gerçek ses segmenti | 0 |
| İnsan onaylı segment anotasyonu | 0 |
| Freya ön işleme aktif telaffuz kuralı | 0 |

Golden fixture SHA-256: `7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e`. M03 paketine göre **değişmedi**.

### Yorum

Bu ölçümler **metinsel dönüştürme** sayılarıdır. `163 metin değişti` ifadesi `163 telaffuz düzeldi` anlamına gelmez. Gerçek ses, GPU, YouTube transkriptleri, MOS, WER/CER ve Asterisk kabul deneyleri **çalıştırılmadı**. 29 inceleme vakası, 16 OOV vakasını kapsar; 29 + 16 şeklinde toplanmaz.

## Kabul

`M04_MOCK_TEXT_PASS / M01_M03_REGRESSION_PASS / A01YT_LEXICON_EMPTY / GOLDEN_SHA_MATCH / REAL_AUDIO_HOLD / PRODUCTION_HOLD`.

## Açık mühendislik riskleri

- M04, Türkçenin her çekim ve sözcük türünü kapsayan tam bir morfoloji çözücüsü değildir.
- 320 vakanın hiçbiri insanın duyarak okunuşu doğruladığı bir akustik kabul ölçümünü temsil etmez.
- SQLite kaynak kaydı iznin beyanını saklar; kaynak sesinin varlığını veya hak sahibi kimliğini bağımsız olarak kanıtlamaz.
- Onaylı clip için veritabanı hash metadata'sı kontrol edilir; ses dosyasının gerçek SHA karşılaştırması içe alma katmanında gereklidir.
- Genel tarih/gün/saat semantiğinde zaman dilimi, DST, resmî tatil ve lokasyon çalışma saatleri gerçek entegrasyonda ayrıca doğrulanmalıdır.
- Randevu durumu ve fiyat iş kararlarının otoritesi M03'te kalır.
