# M05 Coding Agent görevi — Ses üretmeden prozodi ve clause planner

## Değişmez kısıtlar

Öncelik: özellik/mimari, sonra UI, sentetik uçtan uca doğrulama, en son gerçek ses, YouTube, GPU, telefon. M01-M04 public API ve 320 golden veri değişmeyecek. Asla doğrulanmamış telaffuz kurallarını Freya sözlüğüne sokma.

## Kodlama planı

1. `src/automotive_voice/prosody/` altında `Clause`, `ClausePlan`, `PhraseBoundary`, `TTSInput` immutable dataclass sözleşmeleri.
2. Normalize edilmiş metni türsel spanlara ayır; para miktarı, saat, tarih ve özel ad/ek parçalarını bölme. `review_required` true ise TTS çağrısını üretme.
3. Her clause'a M01 `SessionId / TurnId / GenerationId` bağla; her TTS parçasında cancellation kontrolü.
4. Kısa ve uzun cümle, parantez, noktalama, çoklu randevu ve kötü niyetli metin için deterministik sentetik test yaz.
5. `MockTTS` yalnız metin ve durum bilgisi üretsin; WAV/audio oluşturmasın.
6. Devirde M06 codec/buffer/telephony portları için açık komut sözleşmesi hazırla.

## Kabul

M01-M05 regresyon PASS, 320 dosyası hash sabit, yeni JSON şemaları geçerli, fake audio-signal testleri dışında gerçek ses yok, Windows-first talimatları tamam.
