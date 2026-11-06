# M06 — Doğrulama Raporu

**Tarih:** 31 Ekim 2026  
**Karar:** `MOCK_CORE_PASS / PRODUCTION_READINESS_HOLD`  
**Ortam:** Linux, CPython 3.13; Windows PowerShell betiği hazır fakat Windows/Python 3.11 çalıştırması henüz yapılmadı.

## Gerçekleştirilen kontroller

| Denetim | Sonuç |
|---|---|
| M01–M05 otomatik regresyon | **237/237 PASS** |
| Yeni M06 otomatik testler | **50/50 PASS** |
| Toplam test | **287/287 PASS** |
| M01–M05 kaynakları | **44 eski Python modülü byte-byte değişmedi** |
| 320 vaka corpus SHA-256 | `7455fa7a59a5874165970d8980f7f7302c581d28532e2d0346a496aeda2eb17e` |
| JSON Schema Draft 2020-12 | 5 yeni M06 şeması doğrulandı |
| Metadata-only sentetik demo | PASS; gerçek ses dosyası **0** |
| Gerçek Asterisk FLUSH doğrulaması | **YAPILMADI** |
| Gerçek Freya/YouTube/Whisper, MOS/RTF/WER/CER | **YAPILMADI** |

### Sentetik demo gözlemleri

`M06` demosu M02'de `LISTENING → THINKING → SPEAKING → INTERRUPTING` geçişlerinden sonra sahte `FLUSH_MEDIA` isteği oluşturdu. Eski chunk, bekleyen flush nedeniyle reddedildi. Sadece `FakeTransport.confirm_flush()` çağrısından dönen ve koordinatörce kaynağı doğrulanan sahte ACK, M02'nin `LISTENING` durumuna geçmesine izin verdi. Gerçek PBX onayı **üretilmedi ve iddia edilmedi**.

### Kapanmamış mimari riskler

1. **RAM'de volatile state:** Oturum/olay kuyrukları ve replay bilgisi yeniden başlatmada kaybolur.
2. **Sınırlı kapasite:** Oturum başına chunk ve süre limiti mevcut; global RAM/süre/oturum limiti eksik.
3. **Ağ aktarımı atomik değil:** `pop_next` ile gerçek transport ACK arasındaki dayanıklı teslim garantisi geliştirilmedi. Sahte taşıma reddinde `return_front` var ama gerçek bağlantı kopmasında güvenilir kuyruk yerine geçmez.
4. **PBX flush semantiği:** `FLUSH_MEDIA` göndermek veya yerel kuyruk silmek, gerçek PBX'de eski sesin temizlendiğini ve hatta hiç duyulmadığını kanıtlamaz.
5. **G.722:** Yalnız format/clock sözleşmesi, gerçek payload encode/decode veya paket boyutu sınaması yok.
6. **Eski M04 SQLite kaynakları:** Test sonlarında `ResourceWarning` görülebilir; mevcut kaynak API'lerine dokunmama kararı nedeniyle ayrıca kapatılacak.
7. **Windows çalıştırması:** PowerShell doğrulama betiğinin Windows üstündeki sonucu henüz bilinmiyor.

**Sonuç:** Sentetik protokol ve mimari ilerleme için **PASS**; fiziksel medya, üretim ve operatör pilotu için **HOLD**. Sonraki M07 adapter yaşam döngüsü/izolasyon modülüdür.
