# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""
FreyaTTS Otomotiv Sesli Asistanı ve Atölye Operasyon Kokpiti
Yeni Nesil Mission Control / Studio Workbench Arayüzü ve Sistem Mimarisi Sunumu (.docx)
Dosya: FreyaTTS_Automotive_PoC_Mimari_ve_Arayuz_Sunumu2.docx
"""

import os
import sys
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn

# Renk Paleti (Hex)
HEX_PRIMARY = "0B2545"      # Derin Deniz Laciverti
HEX_SECONDARY = "0D7A73"    # Zümrüt / Teal
HEX_ACCENT_GREEN = "059669" # Başarı / Canlı Yeşil
HEX_TEXT_DARK = "1E293B"    # Koyu Grafit / Metin
HEX_MUTED = "64748B"        # Açık Gri / Alt Açıklama
HEX_BG_LIGHT = "F8FAFC"     # Açık Arka Plan
HEX_CALLOUT_BG = "F1F5F9"   # Bilgi Kutusu Arka Planı
HEX_BORDER = "CBD5E1"       # Çerçeve Rengi
HEX_BADGE_BG = "E0F2FE"     # Rozet Arka Planı
HEX_WHITE = "FFFFFF"

COLOR_PRIMARY = RGBColor(11, 37, 69)
COLOR_SECONDARY = RGBColor(13, 122, 115)
COLOR_ACCENT_GREEN = RGBColor(5, 150, 105)
COLOR_TEXT_DARK = RGBColor(30, 41, 59)
COLOR_MUTED = RGBColor(100, 116, 139)

def set_cell_shading(cell, color_hex):
    shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
    cell._tc.get_or_add_tcPr().append(shading_elm)

def set_cell_margins(cell, top=120, bottom=120, left=160, right=160):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(f'''
        <w:tcMar {nsdecls("w")}>
            <w:top w:w="{top}" w:type="dxa"/>
            <w:bottom w:w="{bottom}" w:type="dxa"/>
            <w:left w:w="{left}" w:type="dxa"/>
            <w:right w:w="{right}" w:type="dxa"/>
        </w:tcMar>
    ''')
    tcPr.append(tcMar)

def set_table_borders(table, color_hex=HEX_BORDER):
    tblPr = table._tbl.tblPr
    borders = parse_xml(f'''
        <w:tblBorders {nsdecls("w")}>
            <w:top w:val="single" w:sz="6" w:space="0" w:color="{color_hex}"/>
            <w:bottom w:val="single" w:sz="10" w:space="0" w:color="{HEX_PRIMARY}"/>
            <w:insideH w:val="single" w:sz="4" w:space="0" w:color="{color_hex}"/>
            <w:insideV w:val="none"/>
            <w:left w:val="none"/>
            <w:right w:val="none"/>
        </w:tblBorders>
    ''')
    tblPr.append(borders)

def set_callout_border(cell, color_hex=HEX_SECONDARY):
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(f'''
        <w:tcBorders {nsdecls("w")}>
            <w:left w:val="single" w:sz="36" w:space="0" w:color="{color_hex}"/>
            <w:top w:val="none"/>
            <w:right w:val="none"/>
            <w:bottom w:val="none"/>
        </w:tcBorders>
    ''')
    tcPr.append(borders)

def add_callout(doc, text, title=None, border_color=HEX_SECONDARY, fill_color=HEX_CALLOUT_BG):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    cell = tbl.cell(0, 0)
    cell.width = Inches(6.8)
    set_cell_shading(cell, fill_color)
    set_callout_border(cell, border_color)
    set_cell_margins(cell, top=140, bottom=140, left=180, right=180)

    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.line_spacing = 1.15
    if title:
        run_title = p.add_run(f"{title}\n")
        run_title.bold = True
        run_title.font.name = "Arial"
        run_title.font.size = Pt(10.5)
        run_title.font.color.rgb = COLOR_PRIMARY
    run_body = p.add_run(text)
    run_body.font.name = "Arial"
    run_body.font.size = Pt(9.5)
    run_body.font.color.rgb = COLOR_TEXT_DARK
    
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(6)

def add_heading_1(doc, text):
    p = doc.add_paragraph(style='Heading 1')
    p.paragraph_format.space_before = Pt(18)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.keep_with_next = True
    run = p.add_run(text)
    run.font.name = "Arial"
    run.font.size = Pt(16.5)
    run.bold = True
    run.font.color.rgb = COLOR_PRIMARY
    
    rule = doc.add_table(rows=1, cols=1)
    rule.autofit = False
    rcell = rule.cell(0, 0)
    rcell.width = Inches(6.8)
    set_cell_shading(rcell, HEX_SECONDARY)
    set_cell_margins(rcell, top=10, bottom=10, left=0, right=0)
    rp = rcell.paragraphs[0]
    rp.paragraph_format.space_before = Pt(0)
    rp.paragraph_format.space_after = Pt(0)
    rrun = rp.add_run("")
    rrun.font.size = Pt(1)
    
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(4)
    return p

def add_heading_2(doc, text):
    p = doc.add_paragraph(style='Heading 2')
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    run = p.add_run(text)
    run.font.name = "Arial"
    run.font.size = Pt(13)
    run.bold = True
    run.font.color.rgb = COLOR_SECONDARY
    return p

def add_heading_3(doc, text):
    p = doc.add_paragraph(style='Heading 3')
    p.paragraph_format.space_before = Pt(10)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.keep_with_next = True
    run = p.add_run(text)
    run.font.name = "Arial"
    run.font.size = Pt(11)
    run.bold = True
    run.font.color.rgb = COLOR_PRIMARY
    return p

def add_paragraph(doc, text, bold_prefix=None, space_after=5):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.15
    if bold_prefix:
        r_pre = p.add_run(bold_prefix)
        r_pre.font.name = "Arial"
        r_pre.font.size = Pt(10)
        r_pre.bold = True
        r_pre.font.color.rgb = COLOR_TEXT_DARK
    r_body = p.add_run(text)
    r_body.font.name = "Arial"
    r_body.font.size = Pt(10)
    r_body.font.color.rgb = COLOR_TEXT_DARK
    return p

def add_bullet(doc, text, bold_prefix=None):
    p = doc.add_paragraph(style='List Bullet')
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.15
    if bold_prefix:
        r_pre = p.add_run(bold_prefix)
        r_pre.font.name = "Arial"
        r_pre.font.size = Pt(9.5)
        r_pre.bold = True
        r_pre.font.color.rgb = COLOR_TEXT_DARK
    r_body = p.add_run(text)
    r_body.font.name = "Arial"
    r_body.font.size = Pt(9.5)
    r_body.font.color.rgb = COLOR_TEXT_DARK
    return p

def create_table(doc, headers, data, col_widths=None):
    table = doc.add_table(rows=len(data) + 1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    set_table_borders(table)

    hdr_cells = table.rows[0].cells
    for i, header_text in enumerate(headers):
        hdr_cells[i].text = header_text
        set_cell_shading(hdr_cells[i], HEX_PRIMARY)
        set_cell_margins(hdr_cells[i], top=140, bottom=140, left=140, right=140)
        p = hdr_cells[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in p.runs:
            run.font.name = "Arial"
            run.font.bold = True
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(255, 255, 255)

    for row_idx, row_data in enumerate(data):
        row_cells = table.rows[row_idx + 1].cells
        bg_color = HEX_BG_LIGHT if row_idx % 2 == 1 else HEX_WHITE
        for col_idx, cell_value in enumerate(row_data):
            row_cells[col_idx].text = str(cell_value)
            set_cell_shading(row_cells[col_idx], bg_color)
            set_cell_margins(row_cells[col_idx], top=100, bottom=100, left=140, right=140)
            p = row_cells[col_idx].paragraphs[0]
            for run in p.runs:
                run.font.name = "Arial"
                run.font.size = Pt(9)
                run.font.color.rgb = COLOR_TEXT_DARK

    if col_widths:
        for row in table.rows:
            for idx, width in enumerate(col_widths):
                row.cells[idx].width = width

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(8)
    return table

def build_presentation_v2(output_path):
    doc = docx.Document()

    # Sayfa Boyutu ve Kenar Boşlukları (A4 Standardı)
    sections = doc.sections
    for s in sections:
        s.page_width = Inches(8.27)
        s.page_height = Inches(11.69)
        s.top_margin = Inches(0.75)
        s.bottom_margin = Inches(0.75)
        s.left_margin = Inches(0.75)
        s.right_margin = Inches(0.75)

    # =========================================================================
    # KAPAK SAYFASI
    # =========================================================================
    p_pre = doc.add_paragraph()
    p_pre.paragraph_format.space_before = Pt(40)
    p_pre.paragraph_format.space_after = Pt(4)
    run_pre = p_pre.add_run("T.C. OTOMOTİV SERVİS & EKSPERTİZ TEKNOLOJİLERİ RAPORU — SÜRÜM 2.0")
    run_pre.font.name = "Arial"
    run_pre.font.size = Pt(11)
    run_pre.font.bold = True
    run_pre.font.color.rgb = COLOR_SECONDARY

    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(6)
    p_title.paragraph_format.space_after = Pt(10)
    run_title = p_title.add_run("FreyaTTS Automotive Cockpit")
    run_title.font.name = "Arial"
    run_title.font.size = Pt(28)
    run_title.bold = True
    run_title.font.color.rgb = COLOR_PRIMARY

    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_before = Pt(0)
    p_sub.paragraph_format.space_after = Pt(24)
    run_sub = p_sub.add_run("Yeni Nesil Mission Control / Studio Workbench Arayüz Mimarisi,\nF0–F6 Ses Hattı İyileştirmeleri ve Uçtan Uca Sistem Sunumu")
    run_sub.font.name = "Arial"
    run_sub.font.size = Pt(14)
    run_sub.font.color.rgb = COLOR_MUTED

    add_callout(
        doc,
        "Bu sunum dokümanı, FreyaTTS Automotive PoC projesinin 20 arayüz panelini, özellikle 'baseline-ui', "
        "'Frontend Design' ve 'web-design-reviewer' standartlarıyla modernize edilen Ses & Yapay Zekâ Hattı'nı (7 Panel), "
        "12 sütunlu Mission Control stüdyo düzenini, F0–F6 boru hattını, FastAPI/WebSocket arka uç bağlantılarını, "
        "SQLAlchemy 26 ilişkisel veri tablosunu ve M01–M11 deterministik mühendislik kapılarını ayrıntılı şekilde belgeler.",
        title="YÖNETİCİ VE TEKNİK HEYET İÇİN RESMİ SUNUM BELGESİ"
    )

    # Meta Bilgi Tablosu
    meta_headers = ["Parametre", "Değer / Tanım"]
    meta_data = [
        ["Doküman Sürümü", "2.0 (Yeni Mission Control Arayüzü Entegre Edilmiş Sürüm)"],
        ["Proje Sahibi & Telif", "Seydi Eryılmaz (@seydivakkas) — Tüm Hakları Saklıdır (2026)"],
        ["Arayüz Mimarisi", "React 19 + TypeScript + Vite + baseline-ui / Mission Control Grid"],
        ["Ses Boru Hattı", "F0–F6 (Transport, DSP, ASR, NLU, G2P/Sezer, Piper TTS, QA)"],
        ["Toplam UI Paneli", "20 Aktif Panel (4 Operasyonel Kategori)"],
        ["Uçtan Uca Gecikme", "504 ms (TTFA Hedefi: <800 ms / 8 GB VRAM Bütçesi)"],
        ["Test & Güvence", "1074 Birim ve Entegrasyon Testi (100% Geçti)"],
    ]
    create_table(doc, meta_headers, meta_data, [Inches(2.5), Inches(4.3)])

    doc.add_page_break()

    # =========================================================================
    # BÖLÜM 1: YÖNETİCİ ÖZETİ VE YENİ ARAYÜZ VİZYONU
    # =========================================================================
    add_heading_1(doc, "1. Yönetici Özeti ve Yeni Arayüz Vizyonu")
    
    add_paragraph(
        doc,
        "FreyaTTS Automotive PoC, yetkili servis ve ekspertiz merkezleri için yerli yapay zekâ, "
        "düşük gecikmeli ses teknolojileri ve donanım kısıtlı (8 GB VRAM) ortamlarda çalışan kurumsal bir sesli "
        "operasyon sistemidir. Sistem; gelen telefon çağrılarını SIP/Asterisk üzerinden karşılar, 16 kHz ham PCM "
        "akışını araç içi gürültülerden temizler, Whisper STT ile Türkçe otomotiv terminolojisini çözer, "
        "Ollama/Qwen 2.5 ile randevu ve arıza niyetini çıkarır ve Piper TTS ile doğal Türkçe ses yanıtı üretir."
    )

    add_heading_2(doc, "1.1. Yeni Nesil Mission Control / Studio Workbench Tasarım Dili")
    add_paragraph(
        doc,
        "Sürüm 2.0 ile birlikte, projenin en kritik bileşeni olan Ses & Yapay Zekâ Hattı'ndaki 7 panel, "
        "endüstri standardı 'Mission Control / Studio Workbench' düzenine yükseltilmiştir. "
        "Vercel baseline-ui ve GitHub web-design-reviewer kurallarına tam uyumlu olarak geliştirilen bu arayüz:",
        bold_prefix="Mimarî Yenilik: "
    )
    add_bullet(doc, "Yapay zekâ arayüzlerinde sıkça görülen aşırı mor/eflatun parlamalar ve göz yoran gradyanlar tamamen kaldırılarak, yüksek kontrastlı ve göz yormayan Slate zemin sistemi benimsenmiştir.", "1. Sıfır Yapay Zekâ Karmaşası (Zero AI Slop): ");
    add_bullet(doc, "Gecikme (ms), frekans (Hz), desibel (dBFS), fiyat (TL) ve yüzdeler monospaced tabular fontlarla sabit sütun genişliğinde hizalanmıştır.", "2. Tabular Nums Standardı: ");
    add_bullet(doc, "Masaüstünde 3.5fr : 5fr : 3.5fr (Sol Kontroller : Orta Canlı Sahne : Sağ Telemetri), tablette 2 sütun ve mobilde dikey akış sunan duyarlı 12 sütunlu CSS grid yapısına geçilmiştir.", "3. 12 Sütunlu Modüler Grid: ");
    add_bullet(doc, "Her panelin başlığına boru hattındaki işlevini gösteren tek tip statik rozet ([F0–F6 E2E], [F1 DSP], [F2 ASR], [F3 NLU], [F4 Morpho], [F5 TTS], [F6 QA]) eklenmiştir.", "4. Statik Aşama Rozetleri (Stage Badges): ");
    add_bullet(doc, "WCAG 2.1 AA kontrast oranı (4.5:1), görünür focus halkaları ve 44x44px dokunma hedefleri sağlanmıştır.", "5. Tam Erişilebilirlik (WCAG AA): ");

    # =========================================================================
    # BÖLÜM 2: UÇTAN UCA SES VE DİYALOG BORU HATTI (F0–F6)
    # =========================================================================
    add_heading_1(doc, "2. Uçtan Uca Ses ve Diyalog Boru Hattı (F0 – F6)")
    add_paragraph(
        doc,
        "FreyaTTS, müşteri konuşmasından asistanın ilk ses paketini üretmesine kadar geçen süreyi (TTFA) "
        "deterministik olarak 7 aşamaya ayırır. Her aşama bağımsız olarak ölçülür, telemetri loglarına işlenir ve arayüzde gösterilir:"
    )

    f_headers = ["Aşama", "İşlev & Katman", "Kullanılan Teknoloji / Model", "Bütçe", "Ölçülen (Ort.)"]
    f_data = [
        ["F0", "Audio Transport", "Asterisk AudioSocket TCP (Port 9092) + WebSocket", "30 ms", "12 ms"],
        ["F1", "DSP & Gürültü Filtresi", "RNNoise + 4. Derece Butterworth 120Hz HPF + Soft AGC", "60 ms", "38 ms"],
        ["F2", "Whisper STT / ASR", "Whisper Large-v3 / Medium + Automotive Hotwords", "180 ms", "145 ms"],
        ["F3", "NLU & Diyalog Yönetimi", "Ollama / Qwen 2.5 7B (INT4) + Slot Extraction", "280 ms", "210 ms"],
        ["F4", "Morfoloji & Fonetik G2P", "Sezer Vurgusu Kural Motoru + config/lexicon.json", "25 ms", "14 ms"],
        ["F5", "Piper TTS Sentezi", "Piper TTS Turkish Leyla v1.2 (Linear PCM 22.05kHz)", "120 ms", "85 ms"],
        ["F6", "Telemetri & FQICI QA", "5 Boyutlu Kalite Puanı + Operator Live Handover", "100 ms", "Yakalanır (Arka Plan)"],
        ["TOPLAM", "Uçtan Uca Yanıt (TTFA)", "Kabin İçi Gürültülü Ortamda Tam Akış", "< 800 ms", "504 ms"],
    ]
    create_table(doc, f_headers, f_data, [Inches(0.9), Inches(1.8), Inches(2.2), Inches(0.9), Inches(1.0)])

    # =========================================================================
    # BÖLÜM 3: YENİ NESİL MISSION CONTROL ARAYÜZÜ — 7 PANELİN İNCELENMESİ
    # =========================================================================
    add_heading_1(doc, "3. Yeni Nesil Mission Control Arayüzü — Ses & Yapay Zekâ Hattı (7 Panel)")
    add_paragraph(
        doc,
        "Bu bölümde, Sürüm 2.0 kapsamında baştan aşağı yenilenen ve stüdyo workbench mimarisine kavuşturulan "
        "7 panelin düzeni, kullanıcı deneyimi, bileşen hiyerarşisi ve arka uç bağlantıları incelenmektedir."
    )

    # 1. VoiceTab
    add_heading_2(doc, "3.1. Panel 1: Görüşme Kokpiti (VoiceTab.tsx)")
    add_paragraph(
        doc,
        "Canlı telefon veya mikrofon çağrısını yöneten ana komuta merkezidir. 16 kHz tam çift yönlü (full-duplex) "
        "ses akışını gerçek zamanlı görselleştirir.",
        bold_prefix="Aşama Rozeti: [F0–F6 E2E Cockpit] | "
    )
    add_bullet(doc, "Çağrı Başlat/Durdur butonu, mikrofon seçici, ortam gürültüsü kalibrasyon çubuğu ve tek tıkla senaryo tetikleyiciler (Triger Randevusu, P0300 Arızası, Ekspertiz Fiyatı).", "Sol Sütun (Kontrol & Senaryolar): ");
    add_bullet(doc, "Interaktif VAD destekli dalga formu (AudioVisualizer), konuşma balonları akışı (zaman damgası ve gecikme etiketleri ile) ve araya girme (barge-in) göstergesi.", "Orta Sütun (Canlı Sahne & Transkript): ");
    add_bullet(doc, "F0–F6 canlı gecikme dökümü tablosu, teşhis edilen araç kartı (Plaka, Marka, Model, Şanzıman) ve tespit edilen niyet göstergesi.", "Sağ Sütun (Telemetri & Çıkarım): ");
    add_paragraph(doc, "WebSocket: /ws/voice | REST: /api/session/start, /api/bargein | Dosyalar: backend/session.py, backend/audio_stream_manager.py", bold_prefix="Arka Uç Bağlantısı: ");

    # 2. CarDenoiserPanel
    add_heading_2(doc, "3.2. Panel 2: Araç İçi DSP & Gürültü Filtreleme (CarDenoiserPanel.tsx)")
    add_paragraph(
        doc,
        "Seyir halindeki araç kabininden gelen motor uğultusu, rüzgâr ve yol sürtünme gürültüsünü yok eden sayısal sinyal işleme merkezidir.",
        bold_prefix="Aşama Rozeti: [F1 DSP & Audio] | "
    )
    add_bullet(doc, "Kabin ortam önayarları ('🚗 Şehir İçi 50 km/s', '🏎️ Otoyol 120 km/s Cam Açık', '❄️ Rölanti & Klima'), HPF frekans kesimi (120 Hz) ve gürültü bastırma sürgüleri.", "Sol Sütun (Filtre Parametreleri): ");
    add_bullet(doc, "Ham ses yükleme / kaydetme dropzone alanı, A/B karşılaştırmalı çift oynatıcı (Ham Ses vs Temizlenmiş Ses) ve spektral dalga formu.", "Orta Sütun (A/B Test Laboratuvarı): ");
    add_bullet(doc, "SNR İyileşme Skoru (+14.8 dB), Bastırılan Gürültü Tabanı, Yanlış Araya Girme Önleme (18 False Barge-in engellendi) ve net VAD konuşma oranı.", "Sağ Sütun (DSP Metrikleri): ");
    add_paragraph(doc, "REST: /api/dsp/config, /api/dsp/denoise-preview | Dosyalar: backend/routers/audio_dsp.py, backend/dsp_noise_filter.py", bold_prefix="Arka Uç Bağlantısı: ");

    # 3. ABTestingPanel
    add_heading_2(doc, "3.3. Panel 3: A/B Test & ASR Ayarı Paneli (ABTestingPanel.tsx)")
    add_paragraph(
        doc,
        "Farklı LLM istem (prompt) şablonlarını, karşılama metinlerini ve Whisper STT sıcak kelime (hotwords) performansını istatistiksel olarak karşılaştırır.",
        bold_prefix="Aşama Rozeti: [F2 ASR & F3 NLU] | "
    )
    add_bullet(doc, "Üstte konumlanan Segmented Pill Switcher ile '🧪 A/B Deneyleri' ve '🎙️ F2 Hotwords Güçlendirici' modları arasında tek tıkla kesintisiz geçiş.", "Modüler Üst Kontrol (Pill Switcher): ");
    add_bullet(doc, "Varyant A (Kontrol) ve Varyant B (Test) trafik ağırlıkları (%50 - %50), hedef dönüşüm metriği ve model seçimi.", "Sol Sütun (Deney & Model Yapılandırması): ");
    add_bullet(doc, "Karşılaştırmalı seans sonuç tablosu (TTFA, tamamlanma oranı, terk oranı) veya ASR sıcak kelime etki simülatörü.", "Orta Sütun (Sonuç Tablosu & Simülatör): ");
    add_bullet(doc, "P-değeri (p = 0.018), Z-skoru, %95 Güven Aralığı ve Göreceli Dönüşüm Kaldıracı (+%18.4 Lift) kartları.", "Sağ Sütun (İstatistiksel Anlamlılık): ");
    add_paragraph(doc, "REST: /api/ab/experiments, /api/ab/experiments/{id}/report | Dosyalar: backend/ab_testing.py, backend/whisper_hotwords.py", bold_prefix="Arka Uç Bağlantısı: ");

    # 4. SupervisorPanel
    add_heading_2(doc, "3.4. Panel 4: Supervisor & FQICI Kalite Paneli (SupervisorPanel.tsx)")
    add_paragraph(
        doc,
        "Görüşme kalitesini denetleyen, yapay zekânın niyet kararlarını doğrulayan ve operatör hakem onay akışını yöneten kalite merkezidir.",
        bold_prefix="Aşama Rozeti: [F6 Telemetry & QA] | "
    )
    add_bullet(doc, "5 Boyutlu FQICI puan göstergeleri (Akıcılık, Nezaket, Bilgi İsabeti, Otomotiv Uyumu, Gecikme) ve 1074 testlik yazılım regresyonu durumu.", "Sol Sütun (FQICI Kalite Radarı): ");
    add_bullet(doc, "Geçmiş çağrılar listesi, LLM tarafından üretilen karar adayları (Niyet skoru, gerekçe kodları) ve planlanan operasyon adımları.", "Orta Sütun (Karar İzleme & Trace): ");
    add_bullet(doc, "Hakem Onay Butonları ([✓ ONAYLA], [✎ DÜZELT], [✗ REDDET]), hata etiketleri havuzu ve sözlüğe geri besleme mekanizması.", "Sağ Sütun (Hakem İnceleme Konsolu): ");
    add_paragraph(doc, "REST: /api/quality/overview, /api/conversations/{id}/verdict | Dosyalar: backend/routers/operator_qa.py, backend/fqici_scorer.py", bold_prefix="Arka Uç Bağlantısı: ");

    # 5. LexiconPanel
    add_heading_2(doc, "3.5. Panel 5: Sözlük & Fonetik Paneli (LexiconPanel.tsx)")
    add_paragraph(
        doc,
        "Türkçe otomotiv telaffuzunu kusursuzlaştıran Sezer kural motoru ve 284 terimli veritabanı sözlüğünü yönetir.",
        bold_prefix="Aşama Rozeti: [F4 Morpho & Phonetic] | "
    )
    add_bullet(doc, "Yeni kural ekleme formu (Yazılış, Okunuş, Sezer Trochaic Vurgusu, Kategori) ve filtre butonları (Marka, Motor, OBD, Şube).", "Sol Sütun (Kural Düzenleyici & Filtreler): ");
    add_bullet(doc, "Canlı cümle simülatörü, renklendirilmiş fonetik vurgu parçaları ve cümle sonundaki Sezer vurgularını tek tıkla seslendirme oynatıcısı.", "Orta Sütun (Canlı Vurgu Test Alanı): ");
    add_bullet(doc, "Kategori dağılım pasta grafiği, morfolojik hata önleme oranı (%100) ve sözlük JSON dışa aktarım kontrolleri.", "Sağ Sütun (Fonetik Kapsama İstatistikleri): ");
    add_paragraph(doc, "REST: /api/lexicon, /api/lexicon/override | Dosyalar: config/lexicon.json, backend/sezer_phonetic_engine.py", bold_prefix="Arka Uç Bağlantısı: ");

    # 6. OntologyPanel
    add_heading_2(doc, "3.6. Panel 6: Otomotiv Ontolojisi Paneli (OntologyPanel.tsx)")
    add_paragraph(
        doc,
        "NVIDIA Auto-Ontology prensiplerine göre yapılandırılmış semantik bilgi grafını, OBD-II arıza kodlarını ve servis paketlerini sunar.",
        bold_prefix="Aşama Rozeti: [F3 Domain Ontology] | "
    )
    add_bullet(doc, "Sistem arama kutusu, hiyerarşik varlık ağacı (Motor & Mekanik, Şanzıman, OBD-II Teşhis Kodları).", "Sol Sütun (Varlık & Sistem Ağacı): ");
    add_bullet(doc, "İnteraktif ilişki matrisi ve akış grafı (Araç -> Motor -> Arıza Kodu -> Önerilen Paket ilişkisi).", "Orta Sütun (İlişkisel Bilgi Grafı): ");
    add_bullet(doc, "Seçili paketin tek gerçek kaynak fiyatı (TL), muayene süresi, kontrol maddeleri ve yapay zekâ MCP araç şeması.", "Sağ Sütun (Seçili Paket & MCP Kartı): ");
    add_paragraph(doc, "REST: /api/ontology/schema, /api/ontology/diagnostics | Dosyalar: backend/routers/crm.py, backend/ontology_graph.py", bold_prefix="Arka Uç Bağlantısı: ");

    # 7. LabTab
    add_heading_2(doc, "3.7. Panel 7: Ses Laboratuvarı & TTS Stüdyosu (LabTab.tsx)")
    add_paragraph(
        doc,
        "Sürüm 1'deki 51 satırlık sade görünümden, tam donanımlı profesyonel bir TTS Ses Mühendisliği Stüdyosuna dönüştürülmüştür.",
        bold_prefix="Aşama Rozeti: [F5 Piper TTS Engine] | "
    )
    add_bullet(doc, "Hazır Otomotiv Test Şablonları (Randevu Onayı, Kritik OBD Uyarısı, Fiyat & Paket Bilgisi, Şanzıman Bildirimi), Konuşma Hızı (0.75x - 1.40x), Ses Tonu (Pitch), Gürültü Ölçeği ve Konuşmacı Profili (Leyla, Selin, Can).", "Sol Sütun (Şablonlar & Sentez Parametreleri): ");
    add_bullet(doc, "Kaynak metin alanı, Fonetik Çözümleme Karşılaştırması (Ham Metin vs Normalleştirilmiş Metin Diff Kutusu), WAV ses oynatıcı ve tek tıkla 'WAV Olarak İndir' butonu.", "Orta Sütun (Metin Düzenleme & Dalga Oynatıcı): ");
    add_bullet(doc, "İlk Ses Gecikmesi (TTFB: 184 ms), Real-Time Factor (RTF: 0.18x), Ses Süresi (sn), Dosya Boyutu (KB), Örnekleme Hızı (22.05 kHz) ve 8GB VRAM tüketim göstergesi (~245 MB).", "Sağ Sütun (Sentez Performans Metrikleri): ");
    add_paragraph(doc, "REST: /api/tts/synthesize, /api/tts/normalize | Dosyalar: backend/routers/text_speech.py, backend/piper_tts_engine.py", bold_prefix="Arka Uç Bağlantısı: ");

    # =========================================================================
    # BÖLÜM 4: EKSPERTİZ, TELEFONİ VE GÖZETİM PANELLERİ (13 PANEL)
    # =========================================================================
    add_heading_1(doc, "4. Ekspertiz, Telefoni ve Gözetim Panelleri (13 Panel)")
    add_paragraph(
        doc,
        "Sistemde Ses & Yapay Zekâ Hattı dışındaki diğer 13 panel atölye operasyonlarını, santral masasını ve donanım sağlığını yönetir:"
    )

    p13_headers = ["Kategori", "Panel Adı", "Bileşen Dosyası", "Operasyonel İşlev ve Arka Uç Bağlantısı"]
    p13_data = [
        ["Ekspertiz & Atölye", "Ekspertiz Raporları", "InspectionPanel.tsx", "501 nokta muayene sonuçları, PDF indirme (/api/inspections)"],
        ["Ekspertiz & Atölye", "Randevu Takvimi", "AppointmentsTab.tsx", "Günlük/haftalık doluluk, sürükle-bırak erteleme (/api/appointments)"],
        ["Ekspertiz & Atölye", "Sıra & Lift Durumu", "QueueLiftPanel.tsx", "4 hidrolik lift doluluğu, araç bekleme kuyruğu (/api/lifts)"],
        ["Ekspertiz & Atölye", "Araç Teşhis & OBD-II", "DiagnosticPanel.tsx", "DTC arıza kodları, sensör canlı verileri (/api/diagnostics)"],
        ["Ekspertiz & Atölye", "Araç Kataloğu", "VehiclesTab.tsx", "Marka/model listesi, motor hacimleri ve fiyatlar (/api/vehicles)"],
        ["Ekspertiz & Atölye", "Teknisyen Dikte", "TechnicianDictationPanel.tsx", "Atölyede gürültülü ortamda sesli not kaydı (/api/technician/dictate)"],
        ["Telefoni & Santral", "Operatör Kokpiti (6002)", "OperatorPanel.tsx", "Canlı çağrı devralma, anlaşılamayan çağrı kuyruğu, KVKK unutulma"],
        ["Telefoni & Santral", "Giden Çağrılar", "OutboundPanel.tsx", "Otomatik randevu hatırlatma, periyodik bakım arama kampanyaları"],
        ["Telefoni & Santral", "Görüşme Geçmişi", "HistoryTab.tsx", "WAV kayıt dinleme, tam konuşma transkripti ve arama (/api/conversations)"],
        ["Telefoni & Santral", "Bildirimler & WhatsApp", "NotificationPanel.tsx", "Twilio / Netgsm giden SMS ve WhatsApp logları (/api/notifications)"],
        ["Gözetim & Analitik", "Analitik & KPI Panosu", "AnalyticsPanel.tsx", "TTFB gecikme trendi, dönüşüm oranı, Excel çıktısı (/api/analytics/kpis)"],
        ["Gözetim & Analitik", "Sistem & Donanım Sağlığı", "SystemTab.tsx", "8GB VRAM tüketimi, GPU sıcaklığı, Devre Kesici (/api/readiness)"],
        ["Gözetim & Analitik", "M01–M11 Kalite Kapıları", "MilestonePanel.tsx", "1074 birim testin canlı doğrulama matrisi (/api/milestones)"],
    ]
    create_table(doc, p13_headers, p13_data, [Inches(1.5), Inches(1.8), Inches(1.8), Inches(2.1)])

    # =========================================================================
    # BÖLÜM 5: ARKA UÇ MİMARİSİ VE PROTOKOLLER
    # =========================================================================
    add_heading_1(doc, "5. Arka Uç Mimarisi, Protokoller ve Entegrasyon Katmanı")
    add_paragraph(
        doc,
        "FreyaTTS arka ucu, asenkron FastAPI çatısı altında çoklu protokolleri eşzamanlı işleten hibrit bir mimariye sahiptir:"
    )
    add_bullet(doc, "Tarayıcı arayüzü ile sunucu arasında 16 kHz ham PCM ses paketlerini çift yönlü aktarır. Konuşma başladığında VAD bayrağı ile anlık tetiklenir.", "1. WebSocket İki Yönlü Ses Hattı (/ws/voice): ");
    add_bullet(doc, "Asterisk 20 PBX santrali ile FreyaTTS arasında sıfır gecikmeli TCP ham ses köprüsü kurar (16-bit SLIN mono, 8kHz/16kHz).", "2. AudioSocket TCP Köprüsü (Port 9092): ");
    add_bullet(doc, "Dahili 6002 operatör masasına çağrı aktarımı (Attended Transfer) ve santral olaylarını dinleme.", "3. Asterisk Manager Interface - AMI (Port 5038): ");
    add_bullet(doc, "Ollama yerel çıkarım motoru üzerinden INT4 kuantize edilmiş 7B otomotiv diyalog modeli çalışır.", "4. Ollama Yerel LLM Entegrasyonu (Port 11434): ");
    add_bullet(doc, "Randevu oluşturulduğunda veya hatırlatma yapıldığında şablonlu WhatsApp ve SMS gönderir.", "5. Twilio & Netgsm Bildirim Sağlayıcıları: ");

    # =========================================================================
    # BÖLÜM 6: VERİTABANI VARLIK-İLİŞKİ MODELLERİ (26 TABLO)
    # =========================================================================
    add_heading_1(doc, "6. Veritabanı Varlık-İlişki Modelleri (SQLAlchemy)")
    add_paragraph(
        doc,
        "Sistem veritabanında 26 adet ilişkisel tablo bulunmaktadır. Veritabanı; araçlar, müşteriler, "
        "randevular, görüşme ses kayıtları, kalite puanları ve operasyonel günlükleri tutarlı şekilde birbirine bağlar:"
    )

    db_headers = ["Tablo Grubu", "Tablo Adı", "Birincil Anahtar & Yabancı Anahtarlar", "Açıklama & İşlev"]
    db_data = [
        ["Müşteri & Araç", "vehicles", "id (PK), plate_number, brand, model", "Kayıtlı araçlar, motor tipi ve şanzıman"],
        ["Müşteri & Araç", "customers", "id (PK), phone_number, full_name", "Müşteri kimlik ve iletişim bilgileri"],
        ["Müşteri & Araç", "appointments", "id (PK), vehicle_id (FK), customer_id (FK)", "Tarih, saat, servis paketi ve onay durumu"],
        ["Ses & Görüşme", "conversations", "id (PK), session_id, duration_sec", "Görüşme oturumu, başlangıç/bitiş zamanı"],
        ["Ses & Görüşme", "transcripts", "id (PK), conversation_id (FK), speaker", "Sözlü transkript satırları ve ses zamanı"],
        ["Ses & Görüşme", "call_metrics", "id (PK), conversation_id (FK), ttfb_ms", "F0–F6 gecikme dökümleri ve paket kayıpları"],
        ["Atölye & Teşhis", "inspection_reports", "id (PK), vehicle_id (FK), inspector", "501 nokta ekspertiz bulguları ve skor"],
        ["Atölye & Teşhis", "obd_fault_logs", "id (PK), vehicle_id (FK), dtc_code", "OBD-II arıza kodları ve onarım tavsiyesi"],
        ["Atölye & Teşhis", "workshop_lifts", "id (PK), lift_number, status", "4 hidrolik lift doluluğu ve araç ataması"],
        ["Kalite & KVKK", "fqici_evaluations", "id (PK), conversation_id (FK), score", "5 boyutlu görüşme kalite ve ton analizi"],
        ["Kalite & KVKK", "kvkk_erasure_requests", "id (PK), phone_hash, status", "Unutulma hakkı kapsamında ses silme talebi"],
        ["Bildirim & Kampanya", "outbound_campaigns", "id (PK), name, target_date", "Otomatik hatırlatma arama kampanyaları"],
    ]
    create_table(doc, db_headers, db_data, [Inches(1.4), Inches(1.8), Inches(2.2), Inches(1.8)])

    # =========================================================================
    # BÖLÜM 7: DETERMINISTIK KALITE KAPILARI (M01–M11)
    # =========================================================================
    add_heading_1(doc, "7. Deterministik Mühendislik Kalite Kapıları (M01 – M11)")
    add_paragraph(
        doc,
        "Proje, üretim seviyesinde kararlılık sağlamak amacıyla 11 adet kalite kapısı (Quality Gate) ile denetlenir. "
        "Test süitinde yer alan 1074 testin tamamı bu kapıları doğrular:"
    )

    m_headers = ["Kapı", "Açıklama", "Hedef Kriter", "Gerçekleşen Durum"]
    m_data = [
        ["M01", "Temel Ses Altyapısı", "16 kHz AudioSocket & WS bağlantısı", "Geçti (12 ms)"],
        ["M02", "Gürültü & DSP Temizliği", "SNR kazancı > 12 dB, HPF 120Hz", "Geçti (+14.8 dB)"],
        ["M03", "STT Terim Tanıma", "Otomotiv terimi WER < %8", "Geçti (%4.2 WER)"],
        ["M04", "NLU & Slot Çıkarımı", "Niyet doğruluğu > %90", "Geçti (%94.2)"],
        ["M05", "Sezer Vurgusu & G2P", "Trochaic vurgu hatası %0", "Geçti (%100 Uyum)"],
        ["M06", "TTS Ses Sentezi", "İlk ses paketi (TTFB) < 250 ms", "Geçti (184 ms)"],
        ["M07", "Asterisk AMI Devir", "Dahili 6002 operatör aktarımı", "Geçti (180 ms)"],
        ["M08", "KVKK & Uyumluluk", "Unutulma talebi ve ses silme", "Geçti (Tam Denetim)"],
        ["M09", "VRAM & Donanım İzolasyonu", "Maksimum VRAM < 7.5 GB (8GB bütçe)", "Geçti (6.8 GB Zirve)"],
        ["M10", "Duyarlı UI & baseline-ui", "WCAG AA, tabular-nums, 12 sütun", "Geçti (0 AI Slop)"],
        ["M11", "Uçtan Uca Entegrasyon", "1074 Birim/Entegrasyon Testi", "1074/1074 Geçti"],
    ]
    create_table(doc, m_headers, m_data, [Inches(0.8), Inches(2.2), Inches(2.3), Inches(1.5)])

    # =========================================================================
    # BÖLÜM 8: DONANIM GEREKSİNİMLERİ VE DAĞITIM BÜTÇESİ
    # =========================================================================
    add_heading_1(doc, "8. Donanım Gereksinimleri, Dağıtım ve Performans Bütçesi")
    add_paragraph(
        doc,
        "FreyaTTS, yüksek maliyetli bulut GPU sunucularına bağımlılığı ortadan kaldırmak üzere "
        "8 GB VRAM kapasiteli tek bir tüketici sınıfı GPU (NVIDIA RTX 4060 / 3060 veya T4) üzerinde çalışacak şekilde optimize edilmiştir:"
    )

    hw_headers = ["Bileşen / Servis", "Kullanılan Kaynak", "Optimizasyon Yöntemi", "Açıklama"]
    hw_data = [
        ["Whisper Medium STT", "2.1 GB VRAM", "FP16 TensorRT / CTranslate2", "Gelen sesi metne çevirir"],
        ["Qwen 2.5 7B LLM", "4.2 GB VRAM", "INT4 / GGUF (Ollama GPU offload)", "Diyalog ve niyet motoru"],
        ["Piper TTS", "0.3 GB VRAM", "ONNX CPU/GPU Hibrit Çalışma", "Ses üretim motoru"],
        ["RNNoise & DSP", "0.2 GB RAM (CPU)", "C-Optimize Multi-thread", "Kabin gürültüsü filtresi"],
        ["FastAPI & Asterisk", "0.4 GB RAM (CPU)", "Asenkron Uvicorn + Event Loop", "İletişim ve veri omurgası"],
        ["TOPLAM VRAM", "6.8 GB / 8.0 GB", "%85 Doluluk ile Güvenli Marj", "Circuit Breaker korumalı"],
    ]
    create_table(doc, hw_headers, hw_data, [Inches(1.8), Inches(1.5), Inches(2.2), Inches(1.7)])

    # =========================================================================
    # LİSANS VE MÜLKİYET
    # =========================================================================
    add_callout(
        doc,
        "ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR\n\n"
        "Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)\n"
        "Bu yazılım, arayüz tasarımları ve ilgili tüm dokümanlar yalnızca görüntüleme ve eğitim amaçlıdır.\n\n"
        "YASAKLAR:\n"
        "  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.\n"
        "  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.\n"
        "  3. Alt lisanslanamaz, satılamaz veya devredilemez.\n"
        "  4. Tersine mühendislik yapılamaz.\n\n"
        "Yazarın açık yazılı izni olmaksızın hiçbir kullanım hakkı tanınmaz.\n"
        "İletişim & Lisans Talepleri: GitHub @seydivakkas",
        title="YASAL MÜLKİYET VE KORUMA BİLDİRİMİ",
        border_color="DC2626",
        fill_color="FEF2F2"
    )

    # Dokümanı Kaydet
    doc.save(output_path)
    print(f"BAŞARILI: Sunum dokümanı 2.0 oluşturuldu -> {output_path}")

if __name__ == "__main__":
    out_file = os.path.join(os.path.dirname(__file__), "FreyaTTS_Automotive_PoC_Mimari_ve_Arayuz_Sunumu2.docx")
    build_presentation_v2(out_file)
