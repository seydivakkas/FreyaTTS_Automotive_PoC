# Kodlama ve entegrasyon sırası (ses testleri SON KAPI)

**Global sıra:** (1) işlev ve portlar → (2) UI entegrasyonu → (3) sözleşme/regresyon + sentetik entegrasyon → (4) son gerçek ses ve telefon kabulü. Kritik invariants için hafif testler her aşamada uygulanabilir; gerçek ses kullanımı son kapıdadır.

| Faz | İş paketi | Tamamlama tanımı | Bağımlılık | Gerçek ses? |
|---|---|---|---|---|
| M00 | Kaynak envanteri & ADR: A01-YT v0.5, 320 test seti, Freya manifest | Legacy dosyalar ve sürümleri kayda alınır, çift kod yolu yok | — | Hayır |
| M01 | Çekirdek tipler + event schema + audit ID | JSONSchema, deterministik olay akışı, hata semantiği | M00 | Hayır |
| M02 | Session FSM + interruption controller | Yanlış state transition reddi, late chunk ignore, double-hangup idempotent | M01 | Hayır |
| M03 | Automotive domain (CRM fake, booking policy, slots) | Sahte müsaitlik, müşteri onayı olmadan rezervasyon yok | M02 | Hayır |
| M04 | Türkçe NLP + evidence-backed lexicon + A01-YT adaptörü | Sözlük promotion yalnızca reviewer onayından sonra; 320 metin fikstürü uyumlu | M01 | Hayır |
| M05 | Prosody clause planner + Freya adapter port | Matematik/saat/marka parçalanmaz; dummy audio chunk | M04 | Hayır |
| M06 | Media queue + codec format contracts + buffer flush | Sahte PCM, backpressure, flush, format mismatch işlenir | M02,M05 | Hayır |
| M07 | STT/VAD/LLM provider portları + fake providers | Fake transcript ve fake TTS ile kesilebilir simülasyon | M03,M06 | Hayır |
| M08 | API, giriş, operator UI ve telaffuz review UI | Ses olmadan tamamı tıklanabilir; doğru hata/boş/loading hâlleri | M04–M07 | Hayır |
| M09 | Simulated end-to-end workflows + CI | Randevu, fiyat, handoff, timeout, barge-in, stale event senaryoları pass | M08 | Sentetik |
| M10 | Gerçek bileşen adaptörlerinin kablolanması | Freya/Whisper/VAD/Asterisk yapılandırma ve sağlık probe; gerçek çağrı başlatılmaz | M09 | Gerçek medya kapalı |
| **M11** | **Nihai akustik, GPU ve telefon kabulü** | 320 A/B 640 WAV, YouTube izinli kliplerden referans, dinleme, speaker sim, RTF/TTFA, G.711, barge-in, saha görüşmesi | M10 | **Evet, yalnız burada** |

## Her faz için zorunlu teslim

1. Değişen modül ve API sözleşmelerini gösteren `docs/decisions` ADR güncellemesi.
2. Sürüm kontrollü ilgili iş akışı ekranı ve sahte veri örneği (M08 aşamasında birleştirme).
3. Simülatörün doğru sonuç, hata, timeout ve iptal davranışı.
4. Geri alma/flag kapama planı; gerçek servisi zorunlu import etme.
5. README doğruluğu, semantik sürüm, değişiklik kaydı; ölçülmemiş performans iddiası yok.

## Nihai testin başlamasını engelleyen kapılar

- [ ] M00–M10 teslimleri gözden geçirilmiş, API sözleşmeleri sabit, bağımlılıklar kilitli.
- [ ] Sözlük yalnız onaylı telaffuzları üretime alıyor; lisans kapsama işaretleri doğru.
- [ ] 320 test metni, 50 hedef, kaynak manifestleri korunmuş.
- [ ] Barge-in eski generation output'una izin vermiyor; tamamlayıcı FMS/queue-flush var.
- [ ] Randevu ancak arka uç onayıyla kesinleşiyor; failure path uygulanmış.
- [ ] Operatör paneli, simüle telefon ve bütün hata ekranları çalışıyor.
- [ ] Müşteri testleri öncesi yasal, gizlilik ve sahaya çıkış şartları tamam.
