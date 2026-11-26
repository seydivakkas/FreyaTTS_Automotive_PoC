# M00 — TypeScript AST ve API eşlemesi ikinci inceleme

**Taban SHA:** `6f5867af52dd8d3fd706dc6c9ddd4a42a2dd360f`. Salt okunur arşiv kaynağı: [GitHub Actions 45727418191](https://github.com/seydivakkas/FreyaTTS_Automotive_PoC/actions/runs/45727418191) (geçici audit dalı; taban/H01/plan commitleri sabitlenmiş; yalnız izlenen kaynak ve belgeler). İnceleme yerel izole kopyada TypeScript compiler API ile yapıldı; model, gerçek DB ve PBX açılmadı.

## API ve arayüz

- Python AST ile 232 dekoratörlü rota (HTTP/WS).
- Depodaki `scripts/check_ui_routes.py` içindeki çağrı ayrıştırıcı ve taban Python AST rotaları karşılaştırıldı: 127 frontend çağrı noktası, 118 belirli rota, 6 `GET /api/{resource}` rotasının gerçek izinli kaynak anahtarına, 3 dinamik ortak yardımcılara. Uyumlu olmayan sabit yol tespit edilmedi.
- `backend/routers/generic_resources.py` içindeki kaynak sözlüğünde 21 anahtar var. Genel rota her rastgele kaynak adına açık kabul edilmedi.
- 3 dinamik çağrı: `frontend/src/api.ts:133` gerçek `fetch("/api/" + path,...)` sarmalayıcısı, `api.ts:150` rawApi delegasyonu, `main.tsx:78` sabit readiness/vehicles/slots/appointments/conversations/quotes dizisindeki her öğe. Bu üçü ayrı iş API'si değildir.
- 43 TS/TSX dosyası; 33 TSX. TypeScript AST 415 yerel kontrol/olaylı özel bileşen öğesi buldu (87 salt label hariç). 94 öğede API çağrı adayı, 62 öğede prop/WS/başka eylem adayı, 348 öğede yerel state işlemi; kategoriler örtüşür. Bunlar 387 önceki lexical kayıttan farklı tarama kapsamıdır; eski UI kimlikleri korunur, iki sayı toplanmaz.
- 31 öğede doğrudan olay yok; 26 form içindeki yerleşik input/submit öğesi. Form dışındaki 5 öğe: AnalysisQueuePanel:80 summary, AnalyticsPanel:795 rapor Excel linki, SupervisorPanel:173/234 summary, LabTab:465 audioUrl bağlantısı.
- 4 özel olay manuel okundu: OperatorPanel:2152/2247 `stopPropagation` (modal dış tıklamayı önleme), OperatorPanel:2201 clipboard yazımı (önceki kaynakta sonuç beklenmeden başarı gösteriliyor; H01.15 riski), TechnicianDictationPanel:299 dosya input.click() (yerel dosya seçimi). API işlemi gibi sınıflandırılmadı.
- AST inceleme kayıtlarının SHA-256 özeti: `2a5cf4ce532b2228679e88f39510ee8a89acc10ce6953496bcc0233024425107` (yerel JSON, bu committe tam kayıt dosyası yok). Önceki UI_CONTROL_SUPPLEMENT_01..04 ham kaynak kayıtları ve M00_SUPPLEMENT_STATUS.json korunuyor.

## Kalan işler

G03: PASS değil. API auth/yan etki ve kontrol → prop → üst bileşen → API/WS çözümlemesinin tüm dinamik varyantlarının doğrulaması tamamlanmadı. 415 AST öğesinin mevcut UI kimliklerine eksiksiz birebir eşlemesi açık.

G05: önceki PIPELINE_EDGE_SUPPLEMENT.md ana canlı akışı açıklıyor; alternatif ve hata yollarının tamamı doğrulanmadı.

G08: 14 bileşik API yüzeyinin tek hedef sahip veya gerekçeli çoklu alan ayrımı ve regresyon kapsamı doğrulanmadı.

**M00 genel HOLD; M01_READY=false.** Bu belge bir kaynak inceleme kanıtı; çalışma zamanı kabulü değil. Taban karar dosyası veya kaynak kod değiştirilmedi.