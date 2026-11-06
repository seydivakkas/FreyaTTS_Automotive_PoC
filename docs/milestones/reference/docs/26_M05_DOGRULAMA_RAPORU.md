# M05 doğrulama raporu — 2026-10-31

**Kapsam:** Linux/Python 3.13 üzerinde kaynak kodu `PYTHONPATH=src`; toplam 237/237 otomatik test PASS (M01–M04 193, yeni M05 44). Sözleşmeler 3 yeni Draft 2020-12 şema dahil test edildi.

**Golden corpus:** Değişmeyen 320 cümle SHA-256 `7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e`.

**M05 metinsel karşılaştırma:** 291 `READY`, 29 `REVIEW_REQUIRED`, 356 clause, 202 korunmuş span, 325 TTS'ye aday mock input, 0 onaylı A01-YT kuralı. `READY` ses niteliği anlamına gelmez.

**Sentetik barge-in:** 2 clause kuyruğa alındı, ilk clause verildi, `SessionManager.interrupt()` sonrası kalan eski `generation_id` clause reddedildi. Bu yalnızca mock metinsel teslim kontrolüdür; gerçek transport tamponu test edilmedi.

**HOLD:** Gerçek Freya ses/kimlik, GPU/TTFA/RTF, WER/CER, MOS, çağrı kaydı, Asterisk WebSocket/flush ACK, üretim dayanıklılığı, kalıcı outbox, Windows/Python3.11 fiziksel doğrulama.
