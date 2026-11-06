# M07 Doğrulama Raporu — 31 Ekim 2026

## Kabul özeti

**M07 MOCK ADAPTER PASS / PRODUCTION HOLD / REAL AUDIO HOLD**.

| Denetim | Doğrulanan sonuç |
|---|---|
| M01–M06 regresyonları | **287/287 PASS** |
| M07 yeni testleri | **45/45 PASS** |
| Toplam | **332/332 PASS** |
| Draft 2020-12 JSON şemaları | **25**, bunun **5'i M07** |
| Eski `.py` kaynakları | **52/52 byte-byte aynı** |
| Korunan golden metin | **320 vaka** |
| Golden SHA-256 | `7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e` |
| M05 golden metin raporu | PASS |
| M06 sentetik medya demosu | PASS |
| M07 sanal saat + iptal + fake ACK demosu | PASS |
| Gerçek ses byte'ı veya WAV | **0** |
| Gerçek PBX ACK | **kanıt yok** |
| Gerçek TTS / STT / LLM / GPU / telefon testleri | **YAPILMADI** |
| Windows/Python 3.11 testi | **YAPILMADI** |

## Kodda kontrol edilen durumlar

Dört adaptörün hazır/kopuk/durmuş durumları; `RetryPolicy` sınırları; sanal saatle timeout; circuit breaker açılma ve `HALF_OPEN` probe; idempotent olmayan komutun otomatik tekrarının reddi; eski `GenerationId` ile tamamlanma engeli; replay/sequence farkları; bounded pending; M05 clause'dan yalnızca M06 metaverisi üretme; mock transport ACK bariyeri; bağımsız oturum/servis izolasyonu; sahte akış devamında capacity loss önleme.

## Demo sonucu

`M07` demosunda ilk sentetik medya metaverisi `FakeTransport` kuyruğuna kabul edildi. İkinci TTS işi barge-in sonrasında `CANCELLED` oldu; M02 `INTERRUPTING` durumunda kaldı. Test kodu `FakeTransport.confirm_flush()` çağrısını **açıkça** yaptıktan ve M06 kaynağı doğruladıktan sonra `LISTENING` durumu alındı. **Bu gerçek PBX onayı değildir.**

## Açık teknik riskler

Kalıcı olay/iş kuyruğu, crash sonrası kurtarma, dağıtık idempotency, dış servis bağlantısı, global resource quotas, gerçek codec, PBX flush garantisi ve Windows fiziksel testi henüz tamamlanmadı. Legacy M04 SQLite testleri uyarı verebilir; eski kodu değiştirmeme kararıyla korunmuştur. Zaman ve gecikme değerleri **yalnızca sanal saat**, ses performansı ölçümü değildir.
