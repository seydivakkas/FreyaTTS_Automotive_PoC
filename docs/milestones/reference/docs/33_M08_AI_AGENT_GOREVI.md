# M08 AI Coding Agent — Local Operator Console & Pronunciation Review UI

M07 ZIP'inin içeriğini yeni ana kaynak olarak kullan, **M01–M07 kaynaklarının mevcut davranışını ve 320 vaka SHA değerini koru**.

1. M08 başlığı `Operator Console / Offline Simulation UI`. Windows-first, local-only, varsayılan dinleme adresi `127.0.0.1`; mikrofon/kamera/telefon açma.
2. M07 `HealthSnapshot.safe_metadata`, M02 reducer ve M06 MediaBuffer olaylarını server-side durum mağazasından oku; frontend'de PII/transkript/dış API kimliği saklama.
3. Görünümler: session timeline, Turn/Generation, durum ve efekt denetimi, adapter health/circuit/retry, queue/XOFF/flush ACK bekleme, golden text normalization/lexicon review, kullanıcı onayları.
4. Anlamlı operator actions: sentetik `SESSION_OPENED`, `TRANSCRIPT_FINAL` (opak ref), `LLM_RESPONSE_READY` (opak ref), `VAD_SPEECH_STARTED`, sahte PBX `confirm_flush` (açık 'FAKE ACK' etiketi) ve `HANGUP`.
5. UI'de `FakeTransport.confirm_flush()` gerçek ACK diye gösterilemez; ses üretimine dair herhangi bir oynat düğmesi gerçek ses varmış gibi davranamaz.
6. Yetkisiz CRM/randevu kesinleşmesi veya onaysız A01-YT telaffuz kuralı uygulanması yasak.
7. Önce ekran işlevleri, erişilebilirlik, metin okunurluğu, error/empty/loading states ve testler; UI bitiminde M09 sentetik bütünleşik testlere geç.
8. Üretim için dış ağ erişimi, müşteri PII, gerçek SIP, canlı Freya, YouTube ses referansı, GPU ve kalite testi **HOLD**.
9. Test raporlarında ölçülmemiş ses/latency değerlerini gerçek sonuç diye yazma. Windows gerçek test koşulmadıysa bunu açık tut.
