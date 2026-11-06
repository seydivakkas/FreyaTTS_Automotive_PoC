# M03 Doğrulama Raporu — 31 Ekim 2026

## Test ortamı

- İşletim sistemi: Linux çalışma konteyneri; **Windows henüz ayrıca sınanmadı**.
- Python: 3.13. Standart kütüphane temelli testler + isteğe bağlı `jsonschema` 4.26 doğrulaması.
- Yöntem: `PYTHONPATH=src python -m unittest discover -s tests -q`, `PYTHONPATH=src python -m automotive_voice.m03_demo`.

## Ölçülmüş sonuçlar

| Doğrulama | Ölçülen sonuç |
|---|---|
| Toplam otomatik test | **117/117 PASS** |
| Önceki M01/M02 testleri | **52/52 PASS** (kaynak/test dosyaları değişmeden) |
| Yeni M03 testleri | **65/65 PASS** |
| JSON Draft 2020-12 sözleşmeleri | 4 şema yüklendi ve doğrulandı |
| M03 sentetik 3-tur demo | PASS: fiyat -> teklif -> açık onay -> 1 sahte rezervasyon |
| Önceki 320 metin fixture dosyası | **byte-for-byte aynı**; SHA-256 `7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e` |
| Ses üretimi / Freya GPU / YouTube WAV | Çalıştırılmadı |
| Gerçek CRM veya Asterisk / SIP | Bağlanmadı |
| Windows 3.11 gerçek ortam doğrulaması | Yapılmadı |

## Negatif testlerden örnekler

- Kimlik doğrulaması veya CRM veri yetkisi olmayan istekte araç/fiyat sorgulama ve rezervasyon yok.
- Pazarlama opt-in seçeneği, CRM işlem yetkisini tek başına açmıyor.
- Kaynağı olmayan/eskimiş fiyat için yeni fiyat üretilmiyor.
- Geçmiş veya timezone'suz randevu reddediliyor; `AVAILABLE` öncesi müşteri onayı istenmiyor.
- `CONFIRM` olmadan rezervasyon yok; `UNKNOWN` veya `UNAVAILABLE` için başarılı rezervasyon mesajı yok.
- Mükerrer `CONFIRM`, sahte backend'de yalnız tek rezervasyon oluşturuyor.
- Aynı idempotency anahtarının farklı slot için tekrar kullanımı hata.
- Belirsiz commit sonucu yeni rezervasyon yerine mutabakat sorgusu yapılıyor.
- Güncelliğini yitiren `generation_id` ile M02'ye LLM yanıt olayı veya rezervasyon girişimi yapılmıyor.
- Handoff, geç gelen yanıt, bilinmeyen transkript referansı ve kapanmış oturum testleri geçiyor.
- M02 audit kaydında yanıt/transkript içeriği yok.

## Açık riskler / GO-NO-GO

`M03_MOCK_PASS / M03_PRODUCTION_HOLD`: İki ayrı otoritenin (M02 state ve gerçek rezervasyon backend'i) atomik commit garantisi yoktur. Fake idempotency, gerçek servis tarafındaki kalıcı idempotency olmadan aynı sonucu garanti etmez. Gerçek KVKK kimlik/doğrulama, secret-store şifreleme, değişmez audit, kalıcı outbox, telephony ve ses işleme **nihai testlere/ilgili iş paketlerine ertelenmiştir**.

Bu rapor sadece statik ve sentetik Python mantığını doğrular; müşterilerle konuşmaya hazır olduğunu iddia etmez.
