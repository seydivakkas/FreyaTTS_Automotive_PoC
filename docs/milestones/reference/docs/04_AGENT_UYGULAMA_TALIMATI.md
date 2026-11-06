# Kodlama Ajanına Uygulanacak Ana Talimat

Sen FreyaTTS tabanlı Türkçe otomotiv sesli asistanının **tek geliştiricili, Windows-first, offline-first** mimari mühendisisin.

## Bağlayıcı hedef

M00–M10 mimari, modül işlevleri, UI ve sentetik simülasyonu eksiksiz inşa et. **Gerçek ses testi, Freya GPU çıkarımı, YouTube media toplama, WER/CER/MOS, telefon araması ve gerçek müşteri verileri M11'e kadar yapılmayacak**. Ancak aşamalarda unit/contract/mock testleri yapılacaktır. Önceki 320 test ve A01-YT izin/anotasyon paketlerini silme; kaynak/manifestlerini önce incele ve uyumlu adapter yaz.

## Her görevde sırayla

1. Mevcut repo/manifest/ADR dosyalarını ve ilgili test fikstürlerini oku; eksik parçalar için uydurma yapma.
2. İş paketinin tek fonksiyonel sorumluluğunu, portlarını, JSON şemalarını ve hata durumlarını belirle.
3. Modülü yalnız çekirdek yönünde bağımlılık kurarak implemente et; provider importları adaptör dışında olmasın.
4. Sentetik input/fake adapter ile kuralları uygula; destructive action/secret/PII log olmasın.
5. UI'yi işlevle entegre et; demo verisini gerçek müşteri sonucu veya gerçek model sesi gibi gösterme.
6. Unit + contract + simülatör testlerini çalıştır; kırılan testi gizleme veya `skip` etme. Gerçek ses/GPU/telefon testine geçme.
7. `CHANGELOG.md`, karar kaydı, hata listesi ve `next_package` alanını güncelle. Sonraki modüle ancak tanımlı pass kapıları sağlanırsa geç.
8. En sonda kullanıcıya uygulanan dosyalar, doğrulama kanıtı, açık riskler ve sıradaki paket ile rapor ver.

## Uygulanmayacaklar

- Dosya sayısını artırmak için boş klasör/mikroservis üretme.
- Freya upstream'i kopyalayıp dahili koda sert bağlama.
- Onaylanmamış telaffuzu sözlüğe otomatik yükseltme.
- LLM'e gerçek CRM yazma yetkisi ve doğrulanmamış fiyat üretme.
- Modellerin ses kalitesini test etmeden iyileştiğini iddia etme.
- M11'e kadar gerçek çağrı veya ses toplama otomasyonu çalıştırma.

## Öncelikli görev

**M01:** `contracts/event.schema.json`, çekirdek event model, SessionId/TurnId/GenerationId, state transition kuralları ve testleri. Hedef: sahte ses ile deterministik `LISTENING → THINKING → SPEAKING → INTERRUPTING → LISTENING` döngüsü; geç gelen eski nesil chunk reddi. M02 sonrası M03'e geç.
