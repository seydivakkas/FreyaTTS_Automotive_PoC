# Mimari Kapılar ve Nihai Ses Kabulü

## A. Mimari aşamada otomatik kontrol (gerçek medya YOK)

- **Şema uyumu:** `schema_version` geçerli; tüm olaylarda session, turn, generation, monotonik sequence.
- **Session FSM:** Yanlış geçişleri reddet; peş peşe hangup idempotent; eski generation/turn mesajları ignore.
- **Barge-in:** FakeSpeechStart üretilince active generation invalidated, fake playout queue emptied; `interrupt` sonrasında eski chunk'a izin verme.
- **Normalization:** 320 golden metin üzerinden semantik sayı, fiyat, plaka, saat ve model-name span kontrolü. İki defa normalizasyonun anlamı bozmaması hedefi.
- **Lexicon evidence:** `review_status=approved` olmayan kayıt uygulamaya çıkamaz; onaycının kimliği ve kaynak zaman kodu tutulur.
- **Domain policy:** Sahte CRM availability != confirmation; double create guard; unknown price -> no fabricated amount.
- **Codec:** Her PCM chunk metadata'sında sample rate/encoding/kanal sayısı bulunur; uyuşmayan adaptörler dönüştürür veya açık hata verir.
- **Security:** API anahtarları plain log'a yazılmaz; müşteri PII maskeleme, kayıt saklama politikası, hata ve kısıtlı eylem.
- **UI:** Üç panel ve inceleme ekranları için loading, empty, error, cancellation ve safe-handoff durumları.

## B. Nihai gerçek medya/saha kabulünde ayrı ölçülecekler

| Metrik | Analiz | Hedef / karar |
|---|---|---|
| 320 test / A-B | 640 WAV, aynı seed + checkpoint + steps | Tam ve tekrarlanabilir çıktı |
| Telaffuz | Marka/model+ek insan dinleme | Hedef >%95, daha sonra alan ekibiyle onaylanır |
| MOS/DMOS | Kör değerlendirme, çift dinleyici | Başlangıç ölçümünden sonra hedef tanımı |
| WER/CER | Aynı ASR ve aynı 8 kHz koşulu | Önce/sonra, kategori bazlı; 0 hedefi yok |
| Ses kimliği | Speaker similarity + kör dinleme | Orijinal Leyla'yla fark sınırlı |
| TTFA, RTF | RTX 4070 gerçek cihaz, p50/p95 | Ölçüm öncesi performans garantisi yok |
| Barge-in | VAD başlangıcı → sesin durması | Hedef p95 <300 ms; saha doğrulaması gerekir |
| Telefon kalitesi | G.711/Opus, jitter, packet loss | Codec ve ağ rejimleri ayrı değerlendirilir |
| Randevu | CRM sonucuna göre doğruluk | Kanıtsız confirmed 0 |

**Pazarlama/üretim iddiası:** Mimari kapılardan geçmek ses kalitesi, kapasite, KVKK uyumluluğu veya production-ready sertifikası değildir.
