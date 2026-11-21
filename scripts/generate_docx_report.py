"""
FreyaTTS Automotive PoC - Sürüm 2.0 Ürün ve Teknik Mimari Raporu DOCX Oluşturucu
Markdown kaynak: docs/FREYA_POC_URUN_VE_TEKNIK_MIMARI_RAPORU.md
Çıktı: docs/FREYA_POC_URUN_VE_TEKNIK_MIMARI_RAPORU_v2.docx
ve kök dizinde: FreyaTTS_Automotive_PoC_Urun_ve_Teknik_Mimari_Raporu_v2.docx
"""

import os
import re
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

def set_cell_background(cell, hex_color):
    tcPr = cell._element.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    tcPr = cell._element.get_or_add_tcPr()
    tcMar = parse_xml(f'<w:tcMar {nsdecls("w")}><w:top w:w="{top}" w:type="dxa"/><w:bottom w:w="{bottom}" w:type="dxa"/><w:left w:w="{left}" w:type="dxa"/><w:right w:w="{right}" w:type="dxa"/></w:tcMar>')
    tcPr.append(tcMar)

def create_styled_table(doc, headers, rows_data, col_widths=None):
    table = doc.add_table(rows=len(rows_data) + 1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    # Header Row
    hdr_cells = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr_cells[i].text = h
        set_cell_background(hdr_cells[i], "1B365D")  # Deep Navy
        set_cell_margins(hdr_cells[i], top=140, bottom=140, left=160, right=160)
        p = hdr_cells[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in p.runs:
            run.font.bold = True
            run.font.color.rgb = RGBColor(255, 255, 255)
            run.font.size = Pt(9.5)
            run.font.name = "Segoe UI"

    # Data Rows
    for r_idx, row in enumerate(rows_data):
        row_cells = table.rows[r_idx + 1].cells
        bg_color = "F8F9FA" if r_idx % 2 == 1 else "FFFFFF"
        for c_idx, val in enumerate(row):
            if c_idx < len(row_cells):
                row_cells[c_idx].text = str(val).strip()
                set_cell_background(row_cells[c_idx], bg_color)
                set_cell_margins(row_cells[c_idx], top=100, bottom=100, left=140, right=140)
                p = row_cells[c_idx].paragraphs[0]
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                for run in p.runs:
                    run.font.size = Pt(9)
                    run.font.color.rgb = RGBColor(40, 44, 52)
                    run.font.name = "Segoe UI"

    # Set Column Widths if provided
    if col_widths:
        for row in table.rows:
            for idx, width in enumerate(col_widths):
                if idx < len(row.cells):
                    row.cells[idx].width = Inches(width)

    # Empty paragraph after table for spacing
    p_after = doc.add_paragraph()
    p_after.paragraph_format.space_before = Pt(4)
    p_after.paragraph_format.space_after = Pt(8)
    return table

def add_callout(doc, text, callout_type="NOTE"):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(8)
    p.paragraph_format.left_indent = Inches(0.25)
    p.paragraph_format.right_indent = Inches(0.25)

    badge_map = {
        "NOTE": ("NOT: ", "2B6CB0", "EBF8FF"),
        "IMPORTANT": ("ÖNEMLİ GEREKSİNİM: ", "C53030", "FFF5F5"),
        "TIP": ("İPUCU / PRATİK: ", "2F855A", "F0FFF4"),
        "WARNING": ("UYARI / SINIRLILIK: ", "DD6B20", "FFFAF0"),
        "CAUTION": ("DİKKAT / RİSK: ", "9B2C2C", "FFF5F5"),
    }
    prefix, stroke_color, fill_color = badge_map.get(callout_type, ("BİLGİ: ", "4A5568", "F7FAFC"))

    run_p = p.add_run(prefix)
    run_p.bold = True
    run_p.font.name = "Segoe UI"
    run_p.font.size = Pt(9.5)
    r = int(stroke_color[0:2], 16)
    g = int(stroke_color[2:4], 16)
    b = int(stroke_color[4:6], 16)
    run_p.font.color.rgb = RGBColor(r, g, b)

    run_t = p.add_run(text)
    run_t.font.name = "Segoe UI"
    run_t.font.size = Pt(9.5)
    run_t.font.color.rgb = RGBColor(45, 55, 72)

def build_docx():
    doc = docx.Document()

    # Sayfa yapısı: 2.54 cm margins
    for s in doc.sections:
        s.top_margin = Inches(1)
        s.bottom_margin = Inches(1)
        s.left_margin = Inches(1)
        s.right_margin = Inches(1)
        # Header / Footer
        header = s.header
        hp = header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        hrun = hp.add_run("FreyaTTS Automotive PoC • Ürün ve Teknik Mimari Raporu (Sürüm 2.0)")
        hrun.font.name = "Segoe UI"
        hrun.font.size = Pt(8)
        hrun.font.color.rgb = RGBColor(140, 150, 165)

        footer = s.footer
        fp = footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        frun = fp.add_run("Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS • TÜM HAKLAR SAKLIDIR")
        frun.font.name = "Segoe UI"
        frun.font.size = Pt(8)
        frun.font.color.rgb = RGBColor(140, 150, 165)

    # -------------------------------------------------------------
    # KAPAK / BAŞLIK BÖLÜMÜ
    # -------------------------------------------------------------
    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(12)
    p_title.paragraph_format.space_after = Pt(4)
    run_title = p_title.add_run("FreyaTTS Automotive PoC\nÜrün ve Teknik Mimari Raporu")
    run_title.bold = True
    run_title.font.name = "Segoe UI"
    run_title.font.size = Pt(24)
    run_title.font.color.rgb = RGBColor(15, 41, 66)  # Deep Navy

    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_before = Pt(2)
    p_sub.paragraph_format.space_after = Pt(12)
    run_sub = p_sub.add_run("Doğrulanabilir Yerel Türkçe Konuşma Motoru, Operatör Kokpiti ve Uçtan Uca Ekspertiz Süreç Mimarisi")
    run_sub.font.name = "Segoe UI"
    run_sub.font.size = Pt(12)
    run_sub.font.italic = True
    run_sub.font.color.rgb = RGBColor(70, 80, 95)

    # Meta Kutusu
    p_meta = doc.add_paragraph()
    p_meta.paragraph_format.space_before = Pt(4)
    p_meta.paragraph_format.space_after = Pt(18)
    r_meta = p_meta.add_run("Sürüm: 2.0 (Resmi Kabul Revizyonu)  |  Tarih: 20 Kasım 2026  |  Yazar: Seydi Eryılmaz (@seydivakkas)\nLisans: ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR (All Rights Reserved)")
    r_meta.font.name = "Segoe UI"
    r_meta.font.size = Pt(9.5)
    r_meta.bold = True
    r_meta.font.color.rgb = RGBColor(10, 108, 116)  # Teal

    # -------------------------------------------------------------
    # OKUYUCU REHBERİ
    # -------------------------------------------------------------
    p_h = doc.add_heading(level=2)
    p_h.paragraph_format.space_before = Pt(14)
    p_h.paragraph_format.space_after = Pt(4)
    p_h.add_run("Okuyucu Rehberi").font.color.rgb = RGBColor(15, 41, 66)

    create_styled_table(
        doc,
        headers=["Okur Profili", "Öncelikli Bölümler", "Temel Beklenti & Odak"],
        rows_data=[
            ["Müşteri / Demo İzleyicisi", "§2 Müşteri Deneyimi, §6 FreyaTTS, §10 Demo Akışı", "Sesli diyalog doğallığı, plaka düzeltme kabiliyeti, açık onay süreci."],
            ["Ekspertiz İşletmesi / Yönetici", "§3 Kokpit ve 20 Ekran, §5 Randevu İşlemi, §8 İşletim & Veri", "Randevu tekilliği, takvim çakışma kontrolü, lift kapasitesi ve atölye verimliliği."],
            ["Geliştirici / Değerlendirici", "§4 Mimari, §6–8 Uygulama, §9 Kanıt Matrisi, §10 Kabul Koşuları", "Kod seviyesi doğruluk, deterministik durum makinesi, API/WebSocket ve latency bütçesi."]
        ],
        col_widths=[2.0, 2.2, 2.3]
    )

    # -------------------------------------------------------------
    # 1. YÖNETİCİ ÖZETİ
    # -------------------------------------------------------------
    p_h1 = doc.add_heading(level=1)
    p_h1.paragraph_format.space_before = Pt(16)
    p_h1.paragraph_format.space_after = Pt(6)
    p_h1.add_run("1. Yönetici Özeti").font.color.rgb = RGBColor(15, 41, 66)

    p1 = doc.add_paragraph(
        "Freya, Türkçe sesli görüşmeyi takip edilebilir bir ekspertiz işlemine dönüştüren yerel bir otomotiv asistanı prototipidir. "
        "Müşteri talebini söyler, araç ve plaka bilgilerini verir, önerilen saati seçer ve özet üzerinden onaylar. "
        "Operatör görüşmeyi panelde izler ve sonucu takvimde görür."
    )
    p1.runs[0].font.name = "Segoe UI"

    p2 = doc.add_paragraph(
        "Projenin ayırt edici iddiası şudur: otomotive özgü Türkçe konuşma biçimlerini iş kuralları ve doğrulanabilir kayıtlarla birleştirmek. "
        "Bu iddia üç ayrı teknik soruya net yanıt gerektirir:"
    )
    p2.runs[0].font.name = "Segoe UI"

    bullet_pts = [
        ("1. Doğru Duymak: ", "Sözlü plakayı, marka/model adını ve fiyatı hatasız metne dökmek (Silero VAD + faster-whisper)."),
        ("2. Doğru Yorumlamak: ", "Niyet ve alan bilgisini kural öncelikli, LLM destekli deterministik işlemek (Dialogue + TurkishPlateParser)."),
        ("3. Doğru Geri Okumak: ", "Müşteriye anlaşılır, otomotiv terminolojisine ve fonetik kurallara uygun geri bildirim vermek (Türkçe Normalizasyon + FreyaTTS).")
    ]
    for b_title, b_desc in bullet_pts:
        bp = doc.add_paragraph(style='List Bullet')
        bp.paragraph_format.space_after = Pt(2)
        r_bt = bp.add_run(b_title)
        r_bt.bold = True
        r_bt.font.name = "Segoe UI"
        r_bd = bp.add_run(b_desc)
        r_bd.font.name = "Segoe UI"

    add_callout(
        doc,
        "Rapordaki tüm ölçüm değerleri docs/measured-latency.json ve docs/benchmark-results.json kaynaklıdır. "
        "Bağımsız dağılım ölçümü yapılmamıştır; tek çalıştırma örnekleri SLA değildir.",
        "NOTE"
    )

    # -------------------------------------------------------------
    # 2. MÜŞTERİ DENEYİMİ
    # -------------------------------------------------------------
    p_h2 = doc.add_heading(level=1)
    p_h2.paragraph_format.space_before = Pt(16)
    p_h2.paragraph_format.space_after = Pt(6)
    p_h2.add_run("2. Müşteri Deneyimi").font.color.rgb = RGBColor(15, 41, 66)

    p_exp = doc.add_paragraph(
        "Müşterinin ürün yüzü konuşmadır. Web mikrofonu yönetim kokpitindeki Görüşme ekranından açılır. "
        "Telefon müşterisi konuşmayı santral kanalı (Asterisk VoIP / AudioSocket) üzerinden yürütür. "
        "Bağımsız bir müşteri portalı tasarlandığında mikrofon izni, dinleme durumu, gerektiğinde metinle düzeltme, "
        "teyit özeti ve referans yeterli ilk kapsamı oluşturur. Mevcut web demo operatör panelinde yürütülür."
    )
    p_exp.runs[0].font.name = "Segoe UI"

    p_sc = doc.add_paragraph()
    r_sc = p_sc.add_run("Temel Müşteri Akışı ve Plaka Düzeltme Örneği:")
    r_sc.bold = True
    r_sc.font.name = "Segoe UI"

    create_styled_table(
        doc,
        headers=["Müşteri Söylediği İfade", "Sistem Çıktısı / Aksiyon", "Çalışan Kod Mekanizması"],
        rows_data=[
            ["'Otuz dört Adana Bursa Ceyhan yüz yirmi üç'", "Plaka adayı: 34 ABC 123", "TurkishPlateParser.parse_spoken() (Fonetik Şehir ve Sayı Eşleme)"],
            ["'C değil, Denizli'nin D'si'", "Güncellenen plaka: 34 ABD 123", "TurkishPlateParser.correct_plate() (Hedefli Harf Değiştirme)"],
            ["'Evet, sizi duyuyorum'", "Görüşme sürer, kayıt yapılmaz", "Diyalog Politikası — Erken 'Evet' reddi (Sözleşme Koruması)"],
            ["'Evet, onaylıyorum'", "Randevu kesinleşir, REF-XXX döner", "book() atomik SQL işlemi + idempotency_key kontrolü"]
        ],
        col_widths=[2.5, 2.0, 2.0]
    )

    add_callout(
        doc,
        "'Evet, sizi duyuyorum' ile 'Evet, onaylıyorum' arasındaki ayrım diyalog politikasının görevidir. "
        "Açık onay yalnızca güncel teklif aşamasında kabul edilir; diğer tüm onay benzeri ifadeler işlemi başlatmaz.",
        "IMPORTANT"
    )

    # -------------------------------------------------------------
    # 3. OPERATÖR KOKPİTİ VE 20 EKRAN
    # -------------------------------------------------------------
    p_h3 = doc.add_heading(level=1)
    p_h3.paragraph_format.space_before = Pt(16)
    p_h3.paragraph_format.space_after = Pt(6)
    p_h3.add_run("3. Operatör Kokpiti — 20 Ekran ve 4 Kategori").font.color.rgb = RGBColor(15, 41, 66)

    doc.add_paragraph(
        "Kokpit frontend/src/nav.ts içindeki resmi envantere göre 4 temel operasyonel kategoriye ayrılmıştır. "
        "Aşağıdaki tablolar her ekranın amacını, pipeline aşamasını ve arka uç bağını belgeler:"
    )

    # Kategori 1
    doc.add_heading("3.1. Operasyon & Atölye (workshop)", level=2)
    create_styled_table(
        doc,
        headers=["Ekran", "İkon", "Pipeline", "Kullanıcının Yaptığı", "Arka Plan İşlevi"],
        rows_data=[
            ["Görüşme", "🎙️", "F0–F6", "Mikrofon oturumu, konuşma ve durum takibi, metinle deneme", "/ws/voice, WebSocket bilet, VoiceSession, diyalog, F0–F6 olayları"],
            ["Randevular", "📅", "—", "Slot açma/kapatma, liste ve takvim görünümü, taşıma önizleme", "CRM + scheduling, çakışma kontrolü, book() idempotency"],
            ["Sıra & Lift Durumu", "🚗", "—", "Kuyruk takibi, lift/istasyon durumu izleme", "Lift kapasitesi, teknisyen ataması, servis süresi"],
            ["Ekspertiz Raporları", "📄", "—", "Rapor ve teslim sürecini yönetme, PDF onayı", "Rapor kaydı, PDF üretimi, HMAC imzalı indirme bağlantısı"],
            ["Araçlar ve Fiyatlar", "🏷️", "—", "Marka/model kayıtları, ekspertiz paketi ve fiyat", "CRM, katalog ve fiyat sorgusu; ücret kuruş olarak tutulur"],
            ["Teknisyen Dikte", "🎙️", "—", "Sesli bulgu girme", "Dikte transkripsiyonu ve bulgu kaydı"],
            ["Araç Teşhis & OBD-II", "🔌", "—", "DTC hata kodları ve telemetri", "Tanı uçları, OBD-II veri işleme. Fiziksel donanım kabulü ayrı"]
        ],
        col_widths=[1.5, 0.5, 0.7, 1.8, 2.0]
    )

    # Kategori 2
    doc.add_heading("3.2. Telefoni & Santral (telephony)", level=2)
    create_styled_table(
        doc,
        headers=["Ekran", "İkon", "Kullanıcının Yaptığı", "Arka Plan İşlevi"],
        rows_data=[
            ["Bildirimler & WhatsApp", "💬", "Bildirim kuyruğu ve teslim durumu", "whatsapp_webhook.py, SMS kuyruğu, X-Webhook-Token doğrulama"],
            ["Görüşme Geçmişi", "📜", "Görüşme ayrıntısı, transkript, olaylar", "Görüşme, mesaj ve gecikme metrikleri; kademeli silme"],
            ["Operatör (6002)", "🎧", "Çağrı izleme, fısıltı ve aktarım", "AMI, MockAMIClient; gerçek arama/aktarım PoC kapsamında değil"],
            ["Giden Çağrılar", "📞", "Arama hazırlama ve sonuç inceleme", "Telefoni, çağrı işi; sahte AMI ile çalışır"]
        ],
        col_widths=[1.8, 0.5, 2.0, 2.2]
    )

    # Kategori 3
    doc.add_heading("3.3. Ses & Yapay Zekâ Hattı (audio_ai)", level=2)
    create_styled_table(
        doc,
        headers=["Ekran", "İkon", "Pipeline", "Kullanıcının Yaptığı", "Arka Plan İşlevi"],
        rows_data=[
            ["Araç İçi DSP & Gürültü", "🛡️", "F0", "120 Hz HPF, spektral gürültü azaltma, AGC denemeleri", "dsp.py, car_denoiser.py giriş/çıkış sinyali ve ölçümler"],
            ["A/B Test & İnce Ayar", "⚖️", "F1–F2", "Silero VAD ve Whisper ASR varyant karşılaştırması", "ab_testing.py, z-test ve MOS konfigürasyonu"],
            ["Sözlük & Fonetik", "📖", "F4", "Terim telaffuzu, normalizasyon denemesi", "config/lexicon.json, normalizer_rules.py"],
            ["Otomotiv Ontolojisi", "🌐", "F3–F4", "Alan şeması, terimler ve veri ilişkileri", "Ontoloji modelleri, OBD-II semantik şema"],
            ["Ses Laboratuvarı", "🧪", "F5–F6", "Metin normalizasyonu, FreyaTTS sentezi, WAV dinleme", "text_speech router, FreyaTTS ODE, WSOLA"]
        ],
        col_widths=[1.5, 0.5, 0.7, 1.8, 2.0]
    )

    # Kategori 4
    doc.add_heading("3.4. Gözetim & Kalite Kapıları (governance)", level=2)
    create_styled_table(
        doc,
        headers=["Ekran", "İkon", "Pipeline", "Kullanıcının Yaptığı", "Arka Plan İşlevi"],
        rows_data=[
            ["Supervisor & FQICI", "🔍", "F3", "22 niyet üzerinde kalite incelemesi", "Supervisor sözleşmeleri, politika, supervisor.py"],
            ["Analitik & KPI", "📊", "—", "p50/p95/p99 gecikme, SLA ve başarı oranları", "analytics.py, realtime_dashboard_metrics.py"],
            ["Sistem & Donanım", "🖥️", "—", "RTX 4070 VRAM durumu, model circuit breaker", "gpu_health_circuit_breaker.py, readiness ucu"],
            ["M01–M11 Kalite Kapıları", "🎯", "—", "11 deterministik mühendislik kapısı ve test kanıtları", "milestones.py, milestone çıktıları ve raporlar"]
        ],
        col_widths=[1.5, 0.5, 0.7, 1.8, 2.0]
    )

    # -------------------------------------------------------------
    # 4. SİSTEM MİMARİSİ VE DAĞITIM
    # -------------------------------------------------------------
    doc.add_heading("4. Sistem Mimarisi ve Dağıtım", level=1)
    doc.add_paragraph(
        "Sistem Windows ana makinede React kokpit arayüzü, FastAPI arka uç sunucusu, yerel SQLite WAL veritabanı "
        "ve yerel AI model çalışma zamanlarıyla koşturulur. Asterisk VoIP santrali Linux/WSL ortamında konumlanır."
    )

    create_styled_table(
        doc,
        headers=["Bileşen Adı", "Kaynak Dosya / Konum", "Temel Görev ve Sorumluluk"],
        rows_data=[
            ["FastAPI Sunucu", "backend/main.py", "Yaşam döngüsü, router montajı, model yükleme, oturum yönetimi."],
            ["VoiceSession", "backend/session.py", "16 kHz giriş, Silero VAD, STT, kuyruk iptali, çift yönlü oynatma."],
            ["Dialogue Durum Makinesi", "backend/dialogue.py", "Randevu adımları ve kuralları. LLM veritabanına doğrudan erişemez."],
            ["TurkishPlateParser", "backend/turkish_plate.py", "Sözlü plaka çözümü, 81 il kodu, fonetik alfabe ve hedefli düzeltme."],
            ["FreyaTTS Adaptörü", "backend/models.py", "_synth_one API, seed 9 sabit persona, dahili normalizasyon tekrar çalışmaz."],
            ["Metin & Kural Motoru", "backend/text.py + normalizer_rules.py", "Türkçe sayı, tarih, fiyat ve plaka konuşma normalizasyonu."],
            ["SQLite Veritabanı", "backend/db.py", "WAL modu, yabancı anahtarlar, atomik randevu, slot tekilliği."],
            ["AudioSocket", "backend/telephony.py", "UUID doğrulama, çift yönlü 8 kHz PCM16, 20 ms paket çerçeveleme."],
            ["Güvenlik Katmanı", "backend/security_utils.py + .env", "HTTP Basic, WebSocket tek kullanımlık bilet, HMAC, PBX IP izin listesi."]
        ],
        col_widths=[1.5, 2.0, 3.0]
    )

    # -------------------------------------------------------------
    # 5. FREYATTS VE AKUSTİK PERFORMANS
    # -------------------------------------------------------------
    doc.add_heading("5. FreyaTTS — Otomotive Özgü Ses Sentezi ve Ölçümleri", level=1)
    doc.add_paragraph(
        "FreyaTTS, genel amaçlı bir seslendirici yerine otomotiv terminolojisine odaklanmış kurallarla güçlendirilmiştir. "
        "Gerçek donanımda (RTX 4070 Laptop GPU, 8188 MiB VRAM) alınan tekil çalıştırma sonuçları aşağıdadır:"
    )

    create_styled_table(
        doc,
        headers=["Ölçülen Adım / Cümle", "Ölçüm Değeri", "Teknik Not ve Açıklama"],
        rows_data=[
            ["Karşılama, İlk Ses", "~15 ms", "Önceden önbelleğe alınmış yan cümle"],
            ["İsim Turu", "~1.4 s", "ASR + diyalog değerlendirmesi"],
            ["Araç Turu (Kısa Cümle)", "~3.2 s", "Kısa cümle optimizasyonu ile"],
            ["Seçim ve Onay Turu", "~3.2 s", "Katalog sorgusu ve teyit sentezi"],
            ["LLM Gerektiren Turlar", "~6.0 s", "Ollama yerel çıkarım süresi dahil"],
            ["STT (faster-whisper)", "~0.3 – 1.5 s", "Giriş sesinin uzunluğuna bağlı tanıma süresi"],
            ["TTS Soğuk (Passat, 4.8s ses)", "1.638 ms", "İlk sentez; Real-Time Factor (RTF) 0.34"],
            ["TTS Sıcak (Passat, 4.8s ses)", "647 ms", "Isınmış model; Real-Time Factor (RTF) 0.13"],
            ["VRAM Tepe Kullanımı", "7.478 / 8.188 MiB", "Masaüstü uygulamaları ve tüm modeller devredeyken"]
        ],
        col_widths=[2.2, 1.8, 2.5]
    )

    add_callout(
        doc,
        "Passat ve Nissan Qashqai benchmark testlerinde ham ASR çıktısının 'Force Wagon Puzzle' veya 'KaşGöl' üretmesi, "
        "TTS'in kalitesini değil, sentezlenen sesin doğrudan ASR'a geri verilmesi sırasındaki ASR sınırlarını gösterir. "
        "Akustik benchmark insan kulağının dinleme puanının yerini tutamaz.",
        "WARNING"
    )

    # -------------------------------------------------------------
    # 6. KANIT MATRİSİ VE SINIRLAMALAR
    # -------------------------------------------------------------
    doc.add_heading("6. Kanıt Matrisi ve Sınırlamalar", level=1)
    create_styled_table(
        doc,
        headers=["İddia Edilen Yetenek", "Mevcut Otomatik Kanıt", "Kalan / Açık Kabul Adımı"],
        rows_data=[
            ["Sözlü plaka çözümü", "TurkishPlateParser birim testleri (81 il kodu)", "İnsan PCM → ASR → çözüm → TTS geri okuma"],
            ["Hedefli harf düzeltmesi", "correct_plate() testleri ('C değil D' → 34 ABD 123)", "Canlı mikrofonda insan telaffuzu ile doğrulama"],
            ["Erken onay reddi", "test_poc_spoken_plate_and_intent.py diyalog testi", "Canlı görüşmede 'Evet duyuyorum' konuşması"],
            ["Tekil kayıt & Idempotency", "Randevu tablosu UNIQUE kısıt ve book() testi", "Aynı onayın mikrofondan tekrar söylenmesi"],
            ["512 konuşma yolu", "Sürümlenmiş POC_SOHBET_512.jsonl ağaçları", "Tüm yolların otomatik koşucuda %100 icrası"],
            ["Asterisk VoIP santral", "AudioSocket 8 kHz PCM16 ve AMI adaptörü", "Fiziksel SIP telefon ve gerçek hat üzerinden test"]
        ],
        col_widths=[1.8, 2.3, 2.4]
    )

    # -------------------------------------------------------------
    # 7. SIRADAKİ TESLİM: 3 KOŞULU GERÇEK MİKROFON KABUL PLANI
    # -------------------------------------------------------------
    doc.add_heading("7. Sıradaki Teslim: 3 Koşulu Gerçek Mikrofon Kabul Planı", level=1)
    doc.add_paragraph(
        "Raporun en güçlü fiziksel kanıtı, geliştiricinin doğrudan kendi mikrofonuyla konuşarak "
        "aşağıdaki 3 senaryoyu gerçekleştirmesi ve veritabanı farklarını kaydetmesidir:"
    )

    create_styled_table(
        doc,
        headers=["Koşu #", "Senaryo Adı", "Kullanıcının Konuştuğu Adımlar", "Beklenen Geçme Koşulu"],
        rows_data=[
            ["K1", "Plaka Düzeltme & Onay", "Corolla için randevu iste → '34 ABC 123' söyle → 'C değil, Denizli'nin D'si' düzelt → 'Evet onaylıyorum'", "Freya '34 ABD 123' okur. 10:00 slotuna tek kayıt düşer. Referans numarası verilir."],
            ["K2", "Erken Onay & Vazgeçme", "Corolla için randevu iste → Özet sorulunca 'Evet, sizi duyuyorum' de → Ardından 'Vazgeçtim' de", "İlk cümlede de görüşme sonunda da yeni randevu oluşmaz (0 kayıt). Slot açık kalır."],
            ["K3", "Doğal İfade & Tekrar", "Kendi doğal cümlenle talep oluştur → Onayla → Kayıttan sonra 'Evet onaylıyorum' tekrar et", "İlk istek doğru anlaşılır. İkinci onay mükerrer kayıt oluşturmaz (Idempotency geçer)."]
        ],
        col_widths=[0.6, 1.8, 2.3, 1.8]
    )

    # -------------------------------------------------------------
    # 8. KALDIRILAN İDDİALAR (ŞEFFAFLIK BEYANI)
    # -------------------------------------------------------------
    doc.add_heading("8. Kaldırılan İddialar (Şeffaflık ve Dürüstlük Beyanı)", level=1)
    doc.add_paragraph(
        "Projenin önceki gayriresmi dokümantasyonlarında yer alan ve repoda deterministik kanıtı bulunmayan "
        "aşağıdaki ifadeler Sürüm 2.0 itibarıyla rapordan çıkarılmıştır:"
    )

    removed_list = [
        "'1095 test ve katman dağılımı' iddiası (gerçek sayı test paketinin anlık çıktısıdır).",
        "'TSE Onaylı' ve 'Asterisk tam entegre' beyanları (henüz fiziksel akreditasyon ve canlı hat testi yapılmamıştır).",
        "'15 dakikadan 3 dakikaya operasyonel tasarruf' iddiası (sahada zaman etüdü ölçümü bulunmamaktadır).",
        "'%100 PASS' ve 'Pilot hazır' genellemeleri (kabul testleri tamamlanmadan bu ifade kullanılamaz).",
        "Deneysel klasörlerdeki (experimental/) modüller için 'üretim ajanı' iddiaları."
    ]
    for rem in removed_list:
        p_rem = doc.add_paragraph(style='List Bullet')
        p_rem.paragraph_format.space_after = Pt(2)
        r_rem = p_rem.add_run(rem)
        r_rem.font.name = "Segoe UI"
        r_rem.font.size = Pt(9.5)

    # -------------------------------------------------------------
    # 9. LİSANS BEYANI
    # -------------------------------------------------------------
    doc.add_heading("9. Lisans ve Telif Hakları", level=1)
    lic_text = (
        "ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR\n\n"
        "Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)\n\n"
        "Bu yazılım ve ilgili tüm dosyalar ('Yazılım') yalnızca görüntüleme ve eğitim amaçlı olarak paylaşılmıştır.\n\n"
        "YASAKLAR:\n"
        "  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.\n"
        "  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.\n"
        "  3. Alt lisanslanamaz, satılamaz veya devredilemez.\n"
        "  4. Tersine mühendislik yapılamaz.\n\n"
        "İZİN VERİLEN KULLANIM:\n"
        "  - GitHub üzerinde görüntüleme ve okuma.\n"
        "  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).\n\n"
        "YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.\n"
        "İzin talepleri için: GitHub @seydivakkas"
    )
    p_lic = doc.add_paragraph()
    p_lic.paragraph_format.space_before = Pt(6)
    p_lic.paragraph_format.left_indent = Inches(0.2)
    p_lic.paragraph_format.right_indent = Inches(0.2)
    r_l = p_lic.add_run(lic_text)
    r_l.font.name = "Consolas"
    r_l.font.size = Pt(8.5)
    r_l.font.color.rgb = RGBColor(60, 64, 70)

    # Kaydet
    out1 = "docs/FREYA_POC_URUN_VE_TEKNIK_MIMARI_RAPORU_v2.docx"
    out2 = "FreyaTTS_Automotive_PoC_Urun_ve_Teknik_Mimari_Raporu_v2.docx"
    doc.save(out1)
    doc.save(out2)
    print(f"[OK] DOCX basariyla olusturuldu:\n  - {out1}\n  - {out2}")

if __name__ == "__main__":
    build_docx()
