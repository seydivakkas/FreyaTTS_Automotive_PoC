# M08 — Local Operator Console & Pronunciation Review UI

## Kapsam ve sınır

- Yalnızca Windows/yerel geliştirme. Python standard library ile HTTP sunucusu; HTML/CSS/vanilla JS. Başlangıç arayüzü `http://127.0.0.1:8765`.
- Dış CDN, veri aktarımı, WebRTC, SIP, gerçek telefon, mikrofon, MP3/WAV oynatma, Freya inference, GPU ve CRM yazma yok.
- `GET /api/snapshot`: gerçek M01–M07 RAM nesnelerinden okunan, PII içermeyen durumsal görüntü; M04 altın metin vakaları tarihsel sentetik fikstürdür.
- `POST /api/action`: CSRF korumalı operatör komutları. M02 `ConversationSignal` ve M07 `AdapterSupervisor` gerçekten kullanılır; `FAKE ACK` yalnızca M06 FakeTransport tarafından sağlanır.
- `GET /api/bootstrap`: CSRF kimliği (yalnızca same-origin/localhost tarayıcı çalışması için); servis yalnızca localhost üzerinden açılır.
- HTTP işleyicileri operatör çekirdeği ile tek asyncio event-loop üzerinde `run_coroutine_threadsafe` aracılığıyla konuşur. Eşzamanlı mutasyonlar `asyncio.Lock` ile sıralanır. Üretim dayanıklılığı anlamına gelmez.

## Kullanıcı ekranları

1. Genel bakış: toplam/aktif oturum, flush bekleyen oturum, sanal saat, adaptör sağlığı, olay özetleri.
2. Oturum yönetimi: oturum kimliği, state, TurnId, GenerationId, sahte M02 sinyalleri, sanal zaman, M06 metadata kuyruğu ve XOFF.
3. Telaffuz: A01-YT kaynak envanteri, 320 golden normalizasyon vakası (29 inceleme, 16 karakter), anotasyon review kuyruğu, kanıta bağlı onaylar.
4. Denetim: son 160 olayın RAM içi kısa kodlu günlüğü; transcript, PII ve audio payload yok.

## Operatör aksiyonları

- `open`, `transcript`, `llm`, `vad`, `playout`, `handoff`, `hangup` M02 reducer'a yönlendirilir.
- `fake_ack`: M02'de bekleyen flush UUID'si alınır, M06 `FakeTransport.confirm_flush` ile test ACK üretilir, `MediaCoordinator.accept_fake_ack` ile doğrulanır. Otomatik onay yoktur.
- `tick`: yalnızca 20 / 100 / 1600 sanal ms. M02 flush timeout watchdog ve M07 test iş kuyruğu tick edilir.
- `xoff` / `xon`: yalnızca FakeTransport durumunu değiştirir.
- `review`: A01-YT kaynak SQLite dosyası `mode=ro`; kararlar `var/m08_reviews.sqlite3` üzerinde ayrı kayıtlanır.

## A01-YT onay kapısı

`approved` kararı için belirli anotasyonun ilgili kaynağı, kapsamı, tamamlanmış insan transkripti, göreli ve güvenli dosya yolu, SHA-256 eşleşmesi ve çözümlenebilir mono 16-bit PCM WAV kanıtı şarttır. Ek olarak karar veren operatör `verified_evidence` nedeni ile kendisini belirtir. `rejected` için kayıt varlığı zorunludur. Bu onay **M04 üretim sözlüğüne otomatik terfi ettirilmez**; gerçek akustik değerlendirmeler M11'e bırakılır.

Mevcut A01-YT kaynağı: 3 sözlü izin bildirimi; 0 klip; 0 anotasyon; 0 onay. Panelde 'kuyruk boş' görünmesi beklendik davranıştır. Sözlü izin bildirimi gerçek platform erişim garantisi değildir.

## Güvenlik ve limitler

- Sunucu `0.0.0.0` adresine açılmayı reddeder. `Host` ve varsa `Origin` eşleşmesi aranır. İşlemler `X-Console-CSRF` gerektirir. CSP, `X-Frame-Options: DENY`, `Cache-Control: no-store`, `nosniff` uygulanır. Harici HTTP kaynakları çekilmez.
- Aktif operatör kimlik doğrulama / rol denetimi yoktur; bu yüzden konsol yalnızca **güvenilir yerel geliştirme** içindir; üretim veya çok kullanıcılı ağ servisinde kullanılamaz.
- RAM oturumları, reducer effects, timeline ve health bilgileri yeniden başlatma sonrası **kaybolur**. Yerel review overlay kalır, A01-YT kaynak dosyası değişmez.
- HTTP ve senaryo testleri Linux/Python 3.13 ile koşulmuştur. Windows/3.11, gerçek Chrome/Edge ekran kabulü ve üretim güvenliği HOLD.
