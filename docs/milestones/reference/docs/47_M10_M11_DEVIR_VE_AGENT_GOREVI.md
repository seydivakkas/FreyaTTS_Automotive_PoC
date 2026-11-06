# M10 → M11 devir sözleşmesi

## Giriş kabul şartları

- M01–M09 regresyonları yeşil kalacak.
- M10 SQLite durum + outbox atomik kaydı, restart fail-closed, FIFO ACK ve consumer dedup sözleşmeleri korunacak.
- M10 20 sentetik senaryo, M04/M05 speech sunum katmanı ve UI dry-run raporu PASS olacak.
- Referans kodları sesli metinde otomatik okunmayacak; ham/yanlış marka okunuşu zorla uygulanmayacak.

## M11 uygulanacak gerçek kabul işleri — şu an YAPILMADI

1. Windows 11/Python 3.11 kurulum; Edge; veri dizini izinleri ve crash/recovery.
2. FreyaTTS model checksum, voice/seed profilinin sabitliği ve GPU VRAM sınırı; 320 cümlede planlı A/B WAV.
3. Yetkili A01-YT gerçek klip, transkript/word alignment, insan onayı ve sadece approved lexicon export.
4. STT gerçek ses yakalama, VAD barge-in ve doğal konuşma zamanlaması.
5. Gerçek Asterisk sürüm matrisine göre AudioSocket/chan_websocket, codec/20 ms pacing, kuyruk temizleme ACK ve gerçek çağrı kapanışı.
6. İşlem uçlarında canlı CRM / booking idempotency ve belirsiz işlem yeniden sorgulama.
7. Gerektiğinde TTS quality (MOS), ASR WER/CER, playout TTFA/RTF, CPU/VRAM, p95 gecikme, 2+ eşzamanlı oturum ve müşteri deneyimi değerlendirmesi.
8. Üretim günlüğü / RBAC / KVKK / saklama süreleri / şifreleme / denetim izleri.

## AI kodlama ajanı emri

M10 ZIP'i tek kanonik kod tabanı olarak al. **Önce fonksiyonel özellikler, sonra UI, sonra sentetik test; gerçek ses ve fiziksel telefon en son**. M11 başlamadan önce M10 HOLD'ların her biri için test planı ve geri dönüş mekanizması oluştur. M10 deneme komutlarını gerçek bağlantı açacak biçimde değiştirme. Doğrulanmamış sonuç için PASS yazma.
