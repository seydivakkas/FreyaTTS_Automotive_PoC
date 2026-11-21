# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""
FreyaTTS Otomotiv Sesli Asistanı ve Atölye Operasyon Kokpiti
Kapsamlı Sistem Mimarisi, Arayüz Özellikleri ve Arka Uç Entegrasyon Sunum Belgesi Üreteci (.docx)
"""

import sys
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import parse_xml, OxmlElement
from docx.oxml.ns import nsdecls, qn

# Renk Paleti (Hex)
HEX_PRIMARY = "0F2942"      # Derin Lacivert
HEX_SECONDARY = "0D7A73"    # Zümrüt / Teal
HEX_TEXT_DARK = "1E293B"    # Koyu Grafit / Metin
HEX_MUTED = "64748B"        # Açık Gri / Alt Açıklama
HEX_BG_LIGHT = "F8FAFC"     # Açık Arka Plan
HEX_CALLOUT_BG = "F1F5F9"   # Bilgi Kutusu Arka Planı
HEX_BORDER = "CBD5E1"       # Çerçeve Rengi
HEX_ALERT_BORDER = "DC2626" # Uyarı Çerçeve
HEX_SUCCESS = "059669"      # Başarı Yeşili
HEX_WHITE = "FFFFFF"

COLOR_PRIMARY = RGBColor(15, 41, 66)
COLOR_SECONDARY = RGBColor(13, 122, 115)
COLOR_TEXT_DARK = RGBColor(30, 41, 59)
COLOR_MUTED = RGBColor(100, 116, 139)

def set_cell_shading(cell, color_hex):
    """Hücre arka plan rengini ayarlar."""
    shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
    cell._tc.get_or_add_tcPr().append(shading_elm)

def set_cell_margins(cell, top=120, bottom=120, left=160, right=160):
    """Hücre iç kenar boşluklarını (padding) ayarlar (dxa cinsinden)."""
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
    """Tablo kenarlıklarını profesyonel ve sade bir stille biçimlendirir."""
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
    """Bilgi kutusunun sol kenarına kalın renkli çizgi çeker."""
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
    """Vurgu / Uyarı / Not kutusu ekler."""
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
    
    # Boş paragraf bırak
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(6)

def add_heading_1(doc, text):
    """Ana başlık (Heading 1)"""
    p = doc.add_paragraph(style='Heading 1')
    p.paragraph_format.space_before = Pt(18)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.keep_with_next = True
    run = p.add_run(text)
    run.font.name = "Arial"
    run.font.size = Pt(17)
    run.bold = True
    run.font.color.rgb = COLOR_PRIMARY
    
    # Altına ince dekoratif çizgi tablosu
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
    """İkinci düzey başlık (Heading 2)"""
    p = doc.add_paragraph(style='Heading 2')
    p.paragraph_format.space_before = Pt(14)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    run = p.add_run(text)
    run.font.name = "Arial"
    run.font.size = Pt(13.5)
    run.bold = True
    run.font.color.rgb = COLOR_SECONDARY
    return p

def add_heading_3(doc, text):
    """Üçüncü düzey başlık (Heading 3)"""
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
    """Metin paragrafı ekler."""
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
    """Madde işareti ekler."""
    p = doc.add_paragraph(style='List Bullet')
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.line_spacing = 1.15
    if bold_prefix:
        r_pre = p.add_run(bold_prefix)
        r_pre.font.name = "Arial"
        r_pre.font.size = Pt(9.5)
        r_pre.bold = True
        r_pre.font.color.rgb = COLOR_PRIMARY
    r_body = p.add_run(text)
    r_body.font.name = "Arial"
    r_body.font.size = Pt(9.5)
    r_body.font.color.rgb = COLOR_TEXT_DARK
    return p

def add_styled_table(doc, headers, rows, col_widths=None):
    """Şık başlık ve arka planlı tablo üretir."""
    table = doc.add_table(rows=len(rows) + 1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    set_table_borders(table)

    # Başlık Satırı
    hdr_cells = table.rows[0].cells
    for i, header_text in enumerate(headers):
        cell = hdr_cells[i]
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        set_cell_shading(cell, HEX_PRIMARY)
        set_cell_margins(cell, top=140, bottom=140, left=140, right=140)
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        run = p.add_run(header_text)
        run.bold = True
        run.font.name = "Arial"
        run.font.size = Pt(9.5)
        run.font.color.rgb = RGBColor(255, 255, 255)

    # Veri Satırları
    for r_idx, row_data in enumerate(rows):
        row_cells = table.rows[r_idx + 1].cells
        bg_color = HEX_BG_LIGHT if r_idx % 2 == 1 else HEX_WHITE
        for c_idx, cell_value in enumerate(row_data):
            cell = row_cells[c_idx]
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            set_cell_shading(cell, bg_color)
            set_cell_margins(cell, top=100, bottom=100, left=140, right=140)
            p = cell.paragraphs[0]
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.15
            run = p.add_run(str(cell_value))
            run.font.name = "Arial"
            run.font.size = Pt(9)
            run.font.color.rgb = COLOR_TEXT_DARK

    # Kolon genişlikleri
    if col_widths:
        for row in table.rows:
            for idx, width in enumerate(col_widths):
                row.cells[idx].width = Inches(width)

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(6)
    return table

def configure_document_properties(doc):
    """Sayfa boyutu, kenar boşlukları, üst/alt bilgi ayarlar."""
    for section in doc.sections:
        section.top_margin = Inches(0.85)
        section.bottom_margin = Inches(0.85)
        section.left_margin = Inches(0.85)
        section.right_margin = Inches(0.85)
        section.page_width = Inches(8.5)
        section.page_height = Inches(11.0)
        
        # Üstbilgi
        header = section.header
        hp = header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        hrun = hp.add_run("FreyaTTS Otomotiv Sesli Asistanı · Sistem Mimarisi & Arayüz Dokümantasyonu")
        hrun.font.name = "Arial"
        hrun.font.size = Pt(8.5)
        hrun.font.color.rgb = COLOR_MUTED

        # Altbilgi
        footer = section.footer
        fp = footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        frun1 = fp.add_run("ÖZEL LİSANS — Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) · Tüm Hakları Saklıdır")
        frun1.font.name = "Arial"
        frun1.font.size = Pt(8.5)
        frun1.font.color.rgb = COLOR_MUTED

def main():
    doc = docx.Document()
    configure_document_properties(doc)

    # =========================================================================
    # KAPAK SAYFASI (ELEGANT PRESENTATION COVER)
    # =========================================================================
    p_badge = doc.add_paragraph()
    p_badge.paragraph_format.space_before = Pt(24)
    p_badge.paragraph_format.space_after = Pt(8)
    r_badge = p_badge.add_run("KURUMSAL MİMARİ VE OPERASYON KOKPİTİ DOKÜMANTASYONU")
    r_badge.font.name = "Arial"
    r_badge.font.size = Pt(9.5)
    r_badge.bold = True
    r_badge.font.color.rgb = COLOR_SECONDARY

    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(4)
    p_title.paragraph_format.space_after = Pt(8)
    r_title = p_title.add_run("FreyaTTS Otomotiv Sesli Asistanı & Atölye Operasyon Kokpiti")
    r_title.font.name = "Arial"
    r_title.font.size = Pt(24)
    r_title.bold = True
    r_title.font.color.rgb = COLOR_PRIMARY

    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_before = Pt(0)
    p_sub.paragraph_format.space_after = Pt(24)
    r_sub = p_sub.add_run(
        "20 Arayüz Paneli, Uçtan Uca F0–F6 Ses Boru Hattı, REST/WebSocket Arka Uç Bağlantıları, "
        "Asterisk VoIP/SIP Entegrasyonu, SQLite WAL Veritabanı ve KVKK Uyum Mimarisi"
    )
    r_sub.font.name = "Arial"
    r_sub.font.size = Pt(13)
    r_sub.font.color.rgb = COLOR_MUTED

    # Kapak Bilgi Tablosu
    cover_meta = [
        ["Doküman Sürümü", "v2.4.0 (Üretim Öncesi Kabul Sürümü)"],
        ["Tarih", "14 Kasım 2026"],
        ["Geliştirici & Yazar", "Seydi Eryılmaz (@seydivakkas)"],
        ["Hedef Donanım", "Yerel Windows 11 Pro / NVIDIA GeForce RTX 4070 (8 GB+ VRAM)"],
        ["Yapay Zekâ Altyapısı", "FreyaTTS ODE (Euler/Heun) + Leyla SFT + Faster-Whisper + Ollama (Qwen2.5 7B)"],
        ["Telefoni Altyapısı", "Asterisk 20+ PJSIP / AudioSocket TCP 9092 / Dahili 6002 Operator Transfer"],
    ]
    add_styled_table(doc, ["Parametre / Alan", "Sistem Spesifikasyonu ve Değeri"], cover_meta, col_widths=[2.4, 4.4])

    # Lisans Kutusu
    add_callout(
        doc,
        "ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR\n"
        "Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)\n\n"
        "Bu yazılım, arayüz bileşenleri, veri modelleri ve ilgili tüm dokümanlar (\"Yazılım\") yalnızca "
        "görüntüleme ve teknik değerlendirme amacıyla hazırlanmıştır. Yazarın açık yazılı izni olmaksızın "
        "kopyalanamaz, çoğaltılamaz, dağıtılamaz, alt lisanslanamaz, ticari amaçla kullanılamaz veya tersine mühendisliğe tabi tutulamaz.",
        title="⚠️ MÜLKİYET VE YASAL UYARI",
        border_color=HEX_ALERT_BORDER,
        fill_color="FFF1F2"
    )

    doc.add_page_break()

    # =========================================================================
    # BÖLÜM 1: YÖNETİCİ ÖZETİ VE SİSTEM VİZYONU
    # =========================================================================
    add_heading_1(doc, "1. Yönetici Özeti ve Sistem Mimarisi")
    add_paragraph(
        doc,
        "FreyaTTS Automotive PoC, otomotiv ekspertiz merkezleri, yetkili servisler ve araç muayene istasyonları "
        "için sıfırdan geliştirilmiş, ultra-düşük gecikmeli (<800ms Time-to-First-Audio), %100 yerel donanımda çalışan "
        "ve Türkçenin fonetik ve morfolojik yapısına tam uyarlanmış yeni nesil bir yapay zekâ sesli asistanı ve "
        "merkezi atölye operasyon kokpitidir."
    )
    add_paragraph(
        doc,
        "Sistem yalnızca bir çağrı merkezi botu veya sesli yanıt sistemi (IVR) değildir; araç kabulünden lift yönetimine, "
        "OBD-II arıza teşhisinden ekspertiz raporlarının dijital teslimine, giden arama kampanyalarından (outbound dialer) "
        "canlı operatör fısıltı koçluğuna kadar tüm satış sonrası servis döngüsünü orkestre eden birleşik bir platformdur."
    )

    add_heading_2(doc, "1.1. Dört Temel Operasyonel Sütun")
    add_bullet(doc, "120 Hz Butterworth HPF, spektral gürültü bastırma (18 dB), Silero VAD, Faster-Whisper ASR, Ollama Qwen2.5 7B LLM ve FreyaTTS ODE Euler/Heun ses sentezleyicisi ile uçtan uca yerel işletim.", "1. Ses & Yapay Zekâ Hattı (F0–F6): ")
    add_bullet(doc, "Lift bay kapasite planlayıcısı, teknisyen eller serbest dikte modülü, OBD-II DTC arıza kodları ve tek gerçek kaynaklı dinamik paket fiyatlandırması.", "2. Ekspertiz & Atölye Yönetimi: ")
    add_bullet(doc, "Asterisk AMI protokolü ile Dahili 6002 sıcak aktarım, canlı araya girme/fısıltı (whisper), çift yönlü WhatsApp botu ve otomatik randevu teyit aramaları.", "3. Telefoni & Santral Masası: ")
    add_bullet(doc, "FQICI diyalog kalite denetimi, p50/p95/p99 gecikme persentilleri, 11 deterministik mühendislik kalite kapısı (M01–M11) ve KVKK unutulma hakkı imha motoru.", "4. Gözetim & KVKK Uyum Yönetimi: ")

    add_callout(
        doc,
        "Sistem 'Reel (Canlı) Mod' ve 'Demo Modu' olmak üzere iki izole çalışma rejimine sahiptir. "
        "Reel modda yalnızca SQLite WAL tabanlı operasyonel veritabanı kullanılırken, Demo modunda "
        "bağımsız bir bellek/dosya alanı açılarak canlı müşteri verilerinin testlerden ve sunumlardan etkilenmesi engellenir.",
        title="ℹ️ MOD İZOLASYONU GÜVENCESİ"
    )

    # =========================================================================
    # BÖLÜM 2: UÇTAN UCA SES BORU HATTI (F0 – F6)
    # =========================================================================
    add_heading_1(doc, "2. Uçtan Uca Ses ve Diyalog Boru Hattı (F0 – F6)")
    add_paragraph(
        doc,
        "Geleneksel bulut tabanlı sesli asistanlar 2500–4000ms gecikme ile çalışırken, FreyaTTS otomotiv hattında "
        "gecikme bütçesi sıkı bir biçimde 800ms'nin altına indirilmiştir. Bu başarı, her aşaması C++/CUDA veya "
        "optimize edilmiş Python ile çalışan 7 aşamalı boru hattı mimarisi (F0–F6) ile sağlanır:"
    )

    pipeline_table = [
        ["Aşama", "Adı ve Teknolojisi", "Gecikme Bütçesi", "Teknik İşlev ve Çözülen Problem"],
        ["F0", "Araç İçi DSP & Gürültü Filtresi\n(Butterworth + Spectral Gate)", "12 ms", "120 Hz yüksek geçiren filtre ile motor uğultusu ve yol rezonansı elenir; spektral bastırma ile araç içi gürültü 18 dB düşürülür; AGC -16 dBFS seviyesine dengeler."],
        ["F1", "Akustik VAD & Konuşma Tespiti\n(Silero VAD + Pitch Slope)", "35 ms", "Müşterinin konuşmaya başladığı veya durakladığı anı milisaniye hassasiyetinde algılar. 35ms dinamik aralık ile cümle bitişindeki soru tonlamalarını ve araya girmeleri (barge-in) yönetir."],
        ["F2", "Otomotiv Odaklı ASR (STT)\n(Faster-Whisper large-v3-turbo)", "180 ms", "float16 CUDA üzerinde çalışır. Otomotiv prompt enjeksiyonu ve fonetik sözlük sayesinde 'Passat 1.5 TSI', 'DSG şanzıman' gibi teknik terimleri %98+ doğrulukla metne döker."],
        ["F3", "Supervisor & Niyet Yönlendirici\n(22 Niyet Rotalama & FQICI)", "40 ms", "Müşteri ifadesini 22 niyet sınıfına (randevu alma, iptal, fiyat sorma, OBD arıza, operatör devri vb.) ve karar DAG adımlarına ayrıştırır."],
        ["F4", "LLM & Diyalog Durum Makinesi\n(Ollama Qwen2.5 7B, 8 GPU Katmanı)", "220 ms", "Kayan pencereli hafıza, tek gerçek kaynak (Single Source of Truth) araç veritabanı ve DTMF çift-modlu teyit mantığıyla yapılandırılmış Türkçe yanıt üretir."],
        ["F5", "FreyaTTS ODE Hızlı Sentezleyici\n(Euler/Heun 32-Step + Leyla SFT)", "140 ms", "Otomotiv müşteri temsilcisi 'Leyla' ses modelini 32 difüzyon adımında çözer. Bağımsız sabit tohumlama ile f0 perde kaymasını ve ses çatallanmasını önler."],
        ["F6", "Ses İletimi ve Ağ Akışı\n(AudioSocket TCP 9092 / WebSocket)", "25 ms", "Üretilen 8 kHz / 16 kHz PCM akışını Asterisk telefon kanalına veya web arayüzüne WSOLA hız koruması ve konfor gürültüsü ile kesintisiz iletir."],
        ["TOPLAM", "Uçtan Uca Time-to-First-Audio (TTFA)", "< 652 ms", "İnsan algısı konuşma eşiği olan 800 ms sınırının altında akıcı ve doğal diyalog."],
    ]
    add_styled_table(doc, pipeline_table[0], pipeline_table[1:], col_widths=[0.8, 2.0, 1.1, 2.9])

    # =========================================================================
    # BÖLÜM 3: ARAYÜZ KOKPİTİ VE TÜM PANELLERİN DETAYI
    # =========================================================================
    add_heading_1(doc, "3. Arayüz Kokpiti ve 20 Panelin Detaylı İncelenmesi")
    add_paragraph(
        doc,
        "FreyaTTS Kokpiti, modern koyu tema (#0F172A slate zemin), yüksek okunabilirlik ve reaktif durum "
        "yönetimine sahip 20 panelden oluşur. Paneller 4 ana operasyonel kategori altında gruplandırılmıştır."
    )

    # -------------------------------------------------------------------------
    # KATEGORİ 1: SES & YAPAY ZEKÂ HATTI
    # -------------------------------------------------------------------------
    add_heading_2(doc, "3.1. Kategori I: Ses & Yapay Zekâ Hattı (7 Panel)")

    add_heading_3(doc, "1. Görüşme Kokpiti (VoiceTab.tsx)")
    add_paragraph(doc, "Müşteri ile yapay zekâ asistanı Leyla arasındaki canlı sesli diyaloğun yürütüldüğü, test edildiği ve adım adım izlendiği ana operasyon ekranıdır.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "Mikrofon başlatma, sessize alma ve tek tıkla görüşmeyi sonlandırma kontrolleri.", "Kullanıcı Deneyimi: ")
    add_bullet(doc, "Canlı ses dalga formu (waveform) ve frekans spektrum görselleştiricisi (HTML5 Canvas).", "Görselleştirme: ")
    add_bullet(doc, "F0'dan F6'ya kadar her tur için yanan boru hattı durum adımları (Pipeline Stepper).", "Boru Hattı Takibi: ")
    add_bullet(doc, "Anlık telemetri göstergeleri: İlk ses gecikmesi (first_audio_ms), STT süresi, LLM süresi, TTS süresi ve RTF (Real-Time Factor).", "Metrikler: ")
    add_bullet(doc, "Müşteri konuşmaya başladığında asistanın sesini anında kesen çift aşamalı akustik 'Barge-In' butonu ve göstergesi.", "Araya Girme: ")
    add_paragraph(doc, "Tarayıcı, WebSocket bilet endpoint'inden ('POST /api/session-ticket') geçici tek kullanımlık bir token alır ve 'ws://host:port/ws/voice?ticket=...' üzerinden çift yönlü ikili ses akışı başlatır. Her turda 'backend/session.py' içindeki VoiceSession sınıfı tetiklenir.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "2. Araç İçi DSP & Gürültü Paneli (CarDenoiserPanel.tsx)")
    add_paragraph(doc, "Otomobil içi kabin gürültüsü, motor devri (RPM), rüzgar ve yol sesleri altında asistanın konuşmayı kusursuz anlayabilmesi için tasarlanan sinyal işleme test merkezidir.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "120 Hz Butterworth 2. Derece Yüksek Geçiren Filtre (HPF) ile kabin içi alçak frekanslı rezonansların kesilmesi.", "Filtre Zinciri: ")
    add_bullet(doc, "Spektral gürültü bastırma (18 dB bastırma, -42 dBFS gürültü kapısı).", "Gürültü Kapısı: ")
    add_bullet(doc, "Otomatik Kazanç Kontrolü (AGC) ile mikrofona uzak veya yakın konuşan müşterilerin sesinin -16 dBFS seviyesine çekilmesi.", "Kazanç Kontrolü: ")
    add_bullet(doc, "Ham WAV dosyası yükleme, filtreleme işleminden geçirme ve öncesi/sonrası spektrogram karşılaştırması.", "Test Yeteneği: ")
    add_paragraph(doc, "'POST /api/dsp/process' ve 'POST /api/dsp/denoise-car-audio' uç noktaları üzerinden 'backend/routers/audio_dsp.py' modülüne bağlanır. DSP zinciri 'scipy.signal' ve 'librosa' ile optimize edilmiştir.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "3. A/B Test & ASR Ayarı Paneli (ABTestingPanel.tsx)")
    add_paragraph(doc, "Farklı VAD eşikleri, ASR promptları, selamlama metinleri ve TTS ses hızlarının dönüşüm oranları ve gecikme üzerindeki etkisini bilimsel olarak ölçümleyen A/B test motorudur.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "Deney kataloğu (Aktif, Duraklatılmış, Tamamlanmış) ve hedef metrik seçimi (Randevu Dönüşüm Oranı, İlk Ses Gecikmesi, MOS Puanı).", "Deney Yönetimi: ")
    add_bullet(doc, "A ve B varyantlarının gerçek görüşmelere rastgele veya hash tabanlı deterministik atanması.", "Varyant Atama: ")
    add_bullet(doc, "İki oranlı Z-Testi (Two-proportion Z-Test) ve p-değeri hesabı; istatistiksel anlamlılığa ulaşıldığında kazanan varyantı otomatik öneren analitik rapor.", "İstatistik Motoru: ")
    add_paragraph(doc, "'GET/POST /api/ab/experiments', 'GET /api/ab/reports/{id}' uç noktaları üzerinden 'backend/ab_testing.py' ve veritabanındaki 'ab_experiments', 'ab_assignments' tablolarına bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "4. Supervisor & FQICI Kalite Paneli (SupervisorPanel.tsx)")
    add_paragraph(doc, "Konuşmaların arka plandaki Niyet Yönlendirici (F3 Router) kararlarını, LLM planlama adımlarını ve FQICI (Freya Quality & Intent Compliance Index) kalite puanlarını denetleyen gözetim masasıdır.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "22 adet resmi otomotiv niyet sınıfının (Intent Catalogue) açıklamaları ve sorumlu yapay zekâ ajanları.", "Niyet Kataloğu: ")
    add_bullet(doc, "Görüşmelerin niyet karar izleri (Traces DAG), niyet puanları ve delil metinleri.", "Karar İzleri: ")
    add_bullet(doc, "İnsan denetmen için FQICI doğrulama kuyruğu (AnalysisQueuePanel) — Kabul, Düzelt, Reddet veya Ek Delil İste.", "Denetim Kuyruğu: ")
    add_bullet(doc, "Model Başarım Matrisi: Makro F1, Mikro F1, Çoklu Niyet Tam Eşleşme, Acil Durum Yakalama (Recall) ve Kapsam Dışı Yanlış Kabul (OOD False Accept).", "Kalite Metrikleri: ")
    add_paragraph(doc, "'GET /api/quality/overview', 'POST /api/quality/review', 'GET /api/quality/traces' uç noktaları üzerinden 'backend/routers/operator_qa.py' modülüne bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "5. Sözlük & Fonetik Paneli (LexiconPanel.tsx)")
    add_paragraph(doc, "Otomotiv marka, model, motor kodu, şanzıman ve argo terimlerin doğru telaffuz edilmesini ve STT/TTS tarafından hatasız anlaşılmasını sağlayan fonetik yönetim merkezidir.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "Marka, Model, Motor, Şanzıman, Kısaltma ve Genel Otomotiv kategorilerine ayrılmış yüzlerce terim.", "Kategori Yapısı: ")
    add_bullet(doc, "Örnek Fonetik Çeviriler: '1.5 TSI' -> 'bir nokta beş te se ı', 'BMW' -> 'be me ve', 'DSG' -> 'de se ge', 'E-Tech' -> 'i tek'.", "Kural Motoru: ")
    add_bullet(doc, "Arayüzden anında yeni terim ekleme, arama ve silme; tek tıkla arka uç normalizer kurallarını çalışma zamanında yeniden derleme.", "Dinamik Güncelleme: ")
    add_paragraph(doc, "'GET /api/lexicon', 'POST /api/lexicon/term', 'DELETE /api/lexicon/term/{term}' uç noktaları üzerinden 'config/lexicon.json' ve 'backend/normalizer_rules.py' modülüne bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "6. Otomotiv Ontolojisi Paneli (OntologyPanel.tsx)")
    add_paragraph(doc, "NVIDIA Auto-Ontology prensiplerine göre yapılandırılmış, otomotiv semantik ilişkilerini, OBD-II teşhis ağacını ve tek gerçek kaynaklı servis paketlerini modelleyen graf panosudur.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "Düğümler (Nodes) ve Kenarlar (Edges) ile modellenmiş semantik otomotiv kavram grafı.", "Semantik Graf: ")
    add_bullet(doc, "OBD-II arıza kodlarının belirtileri, önerilen eylemleri ve ilgili ekspertiz paketleri ile eşleştirilmesi.", "Arıza Ontolojisi: ")
    add_bullet(doc, "Standart, Kapsamlı, Motor & Mekanik, Ekspertiz Plus gibi servis paketlerinin tek kaynak (Single Source of Truth) fiyat ve süre tanımları.", "Tek Gerçek Kaynak: ")
    add_paragraph(doc, "'GET /api/ontology/schema', 'GET /api/ontology/packages', 'GET /api/ontology/dtc' uç noktaları üzerinden bilgi grafına erişir.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "7. Ses Laboratuvarı (LabTab.tsx)")
    add_paragraph(doc, "FreyaTTS ODE (Euler/Heun difüzyon temelli) hızlı sentezleyici motorunun parametrelerini doğrudan test etme ve ses üretme laboratuvarıdır.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "Metin girişi yapıldığında anında fonetik normalizasyon önizlemesi görme.", "Normalizasyon Önizleme: ")
    add_bullet(doc, "ODE Adım Sayısı (Steps: 16–64), Sıcaklık (Temperature: 0.1–1.0) ve WSOLA ses hızı katsayısı (0.8x–1.5x) ayar kaydırıcıları.", "Sentez Ayarları: ")
    add_bullet(doc, "Üretilen Leyla sesini anında tarayıcıda dinleme ve WAV formatında indirme.", "Oynatma & İndirme: ")
    add_paragraph(doc, "'POST /api/tts/synthesize', 'POST /api/text/normalize' uç noktaları üzerinden 'backend/routers/text_speech.py' ve 'vendor/FreyaTTS' kütüphanesine bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    # -------------------------------------------------------------------------
    # KATEGORİ 2: EKSPERTİZ & ATÖLYE YÖNETİMİ
    # -------------------------------------------------------------------------
    add_heading_2(doc, "3.2. Kategori II: Ekspertiz & Atölye Yönetimi (6 Panel)")

    add_heading_3(doc, "8. Ekspertiz Raporları Paneli (InspectionPanel.tsx)")
    add_paragraph(doc, "Araç muayene bulgularını listeleyen, 100 üzerinden ağırlıklı ekspertiz skoru hesaplayan, fotoğrafları arşivleyen ve dijital imzalı PDF raporları üreten modüldür.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "Motor, Kaporta/Boya, Ön Takım/Mekanik, Fren ve Elektronik alt sistem bulgu kartları.", "101 Nokta Muayene: ")
    add_bullet(doc, "Bulguların ağırlığına göre otomatik düşen genel araç kondisyon skoru.", "Skorlama Motoru: ")
    add_bullet(doc, "Tek tıkla resmi Maslak Ekspertiz şablonunda kurumsal PDF üretme, SHA-256 dijital mührü basma ve müşteriye güvenli indirme linki oluşturma.", "PDF Rapor & İmza: ")
    add_paragraph(doc, "'GET/POST /api/inspections', 'GET /api/inspections/{id}/pdf' uç noktaları ile 'backend/db.py' içindeki 'InspectionReport' tablosuna bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "9. Randevu Takvimi Paneli (AppointmentsTab.tsx)")
    add_paragraph(doc, "Servis saat dilimlerini (30 dakikalık slotlar) yöneten, randevuları listeleyen ve sürükle-bırak (drag-and-drop) ile saat taşıma imkanı sunan interaktif takvimdir.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "Tarih ve saat bazlı interaktif takvim ızgarası.", "Görünüm: ")
    add_bullet(doc, "Herhangi bir randevuyu tutup başka bir boş slota bırakarak anında saatini değiştirme (Reschedule).", "Sürükle-Bırak Taşıma: ")
    add_bullet(doc, "Hedef slot doluysa anında kırmızı uyarı veren ve çakışmayı engelleyen slot kilidi.", "Çakışma Koruması: ")
    add_bullet(doc, "Onaylı, Bekleyen ve İptal Edilen randevuları filtreleme; randevu kartında müşteri adı, telefon numarası ve araç plakası dökümü.", "Filtreleme & Arama: ")
    add_paragraph(doc, "'GET /api/appointments/calendar', 'POST /api/appointments/{id}/reschedule', 'POST /api/appointments' uç noktaları üzerinden 'backend/routers/crm.py' ve 'appointments', 'slots' tablolarına bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "10. Sıra & Lift Durumu Paneli (QueueLiftPanel.tsx)")
    add_paragraph(doc, "Fiziksel atölye liftlerinin (Lift 1: Mekanik, Lift 2: Kaporta/Boya, Lift 3: Dyno/Fren) anlık doluluk durumunu ve araç bekleme kuyruğunu yönetir.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "Her lift için Boşta (Idle), Meşgul (Busy) veya Bakımda (Maintenance) durum rozetleri, mevcut araç plakası ve kalan tahmini süre.", "Lift İstasyonları: ")
    add_bullet(doc, "Beklemede, Muayenede ve Tamamlandı statülerinde FIFO (First In First Out) veya öncelikli araç kuyruk listesi.", "Canlı Sıra Kuyruğu: ")
    add_bullet(doc, "Sıradaki aracı lifte alırken hoparlörden otomatik Türkçe ses anonsu çalma ('34 ABC 77 plakalı araç Lift 2'ye alınmıştır').", "Sesli Anons Entegrasyonu: ")
    add_paragraph(doc, "'GET /api/lifts', 'POST /api/lifts/{id}/status', 'GET /api/queue', 'POST /api/queue/call-next' uç noktaları üzerinden 'backend/routers/scheduling.py' modülüne bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "11. Araç Teşhis & OBD-II Paneli (DiagnosticPanel.tsx)")
    add_paragraph(doc, "Araçların OBD-II dongle veya servis soketinden okunan diagnostik hata kodlarını (DTC) ve canlı sensör telemetrisini işleyen paneldir.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "P0300 (Rastgele Ateşleme Hatası), P0420 (Katalizör Verimi Düşük) vb. arıza kodlarının Türkçe anlamı ve aciliyet derecesi (Kritik, Uyarı, Bilgi).", "DTC Kod Listesi: ")
    add_bullet(doc, "Motor devri (RPM), soğutma suyu sıcaklığı, yakıt basıncı gibi canlı sensör parametreleri.", "Sensör Telemetrisi: ")
    add_bullet(doc, "Kritik bir DTC algılandığında sistemin araç sahibine otomatik giden arama veya SMS ile randevu daveti tetiklemesi.", "Proaktif Uyarı Tetikleme: ")
    add_paragraph(doc, "'GET /api/diagnostics', 'POST /api/diagnostics/ingest' uç noktaları ile 'backend/db.py' içindeki 'VehicleDiagnostic' tablosuna bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "12. Araç Kataloğu & Fiyatlar Paneli (VehiclesTab.tsx)")
    add_paragraph(doc, "Sistemde kayıtlı araç modellerini, plaka/VIN eşleşmelerini, ekspertiz fiyat tekliflerini ve kurumsal filo cari hesaplarını yöneten finansal paneldir.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "Araç markası, modeli, plakası ve 17 haneli şasi numarası (VIN) kayıtları.", "Araç Kataloğu: ")
    add_bullet(doc, "Her araç için belirlenmiş kuruş cinsinden fiyat teklifi (Quote) tanımları.", "Paket Fiyatları: ")
    add_bullet(doc, "Oto galerileri ve filo kiralama şirketleri için cari hesap bakiyesi, kredi limiti, iskonto oranı ve randevu borçlanma/iade defteri (Ledger).", "Kurumsal Cari Hesaplar: ")
    add_paragraph(doc, "'GET/POST /api/vehicles', 'GET /api/quotes', 'GET /api/corporate/accounts' uç noktaları üzerinden 'backend/routers/crm.py' modülüne bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "13. Teknisyen Dikte Paneli (TechnicianDictationPanel.tsx)")
    add_paragraph(doc, "Lift başında elleri kirli olan ustanın klavye/fare kullanmadan mikrofona konuşarak ekspertiz bulgularını kaydetmesini sağlayan sesli dikte modülüdür.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "Usta mikrofona konuşur ('Sol ön çamurluk boyalı, motor kulağı aşınmış, triger kayışı çatlak').", "Hands-Free Dikte: ")
    add_bullet(doc, "Faster-Whisper STT Türkçe ses tanıma ile anında transkript çıkarır.", "Hızlı Transkripsiyon: ")
    add_bullet(doc, "Arka plandaki LLM parser, ustanın serbest konuşmasını parçalara ayırarak JSON bulgu listesine (Parça, Durum, Ciddiyet) dönüştürür ve ekspertiz raporuna işler.", "LLM Yapısal Çıkarım: ")
    add_paragraph(doc, "'POST /api/technician/dictate', 'POST /api/technician/parse-findings' uç noktaları üzerinden çalışır.", bold_prefix="Arka Uç Bağlantısı: ")

    # -------------------------------------------------------------------------
    # KATEGORİ 3: TELEFONİ & SANTRAL MASASI
    # -------------------------------------------------------------------------
    add_heading_2(doc, "3.3. Kategori III: Telefoni & Santral Masası (4 Panel)")

    add_heading_3(doc, "14. Operatör Kokpiti (Dahili 6002) (OperatorPanel.tsx)")
    add_paragraph(doc, "Çağrı merkezi operatörünün yapay zekâyı izlediği, zorlu çağrılara müdahale ettiği ve KVKK veri imha taleplerini yürüttüğü en kapsamlı telefoni masasıdır.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "Gelen çağrı yapay zekânın güven sınırını aştığında Asterisk AMI köprüsüyle operatörün dahili 6002 telefonuna canlı aktarılır; ekranda müşteri adı, araç plakası ve görüşme özetiyle pop-up açılır.", "1. SIP Warm Transfer: ")
    add_bullet(doc, "Operatör müşteriye duyulmadan asistanın kulağına fısıldayabilir (Whisper) veya tek tıkla çağrıyı yapay zekâdan devralabilir (Takeover).", "2. Canlı Müdahale & Fısıltı: ")
    add_bullet(doc, "Görüşmelerin kalite eşiklerini (MOS puanı, paket kaybı, gecikme) anlık denetler.", "3. Kalite Kapısı 5: ")
    add_bullet(doc, "Yapay zekânın anlamakta zorlandığı veya tekrar ettiği çağrıları listeler; operatör ses kaydını dinler ve doğru terimi tek tıkla otomotiv sözlüğüne ekler.", "4. Başarısız Görüşmeler & Sözlük Besleme: ")
    add_bullet(doc, "30 günü aşan transkriptlerin denetimi, unutulma hakkı (KVKK m. 11) talebi açma, bağlı tüm verileri silme ve resmi SHA-256 imzalı İmha Tutanağı üretme.", "5. KVKK Silme & Saklama Konsolu: ")
    add_paragraph(doc, "'GET/POST /api/transfers', 'GET /api/operator/live-sessions', 'GET /api/conversations/unclear', 'POST /api/kvkk/erasure-requests' uç noktaları ile 'backend/routers/telephony.py' ve 'backend/routers/compliance.py' modüllerine bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "15. Giden Çağrılar Paneli (OutboundPanel.tsx)")
    add_paragraph(doc, "Otomatik arama kampanyaları (Randevu teyit, periyodik bakım hatırlatma, geri bildirim) düzenleyen ve çağrı robotunu yöneten paneldir.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "Giden arama kuyruğu ve arama sonucu istatistikleri (Ulaşıldı, Meşgul, Telesekreter, Randevu Teyit Edildi, İptal Edildi).", "Kampanya Listesi: ")
    add_bullet(doc, "Asterisk Call-File veya AMI Originate yöntemi ile otomatik arama başlatma.", "Arama Motoru: ")
    add_bullet(doc, "Türkçeleştirilmiş Answering Machine Detection (AMD) ile telesekreter 'bip' sesini veya otomatik operatör anonsunu algılayıp insan sesinden ayırt etme.", "AMD Telesekreter Tespiti: ")
    add_paragraph(doc, "'GET /api/outbound/campaigns', 'POST /api/outbound/originate' uç noktaları ile 'backend/outbound_dialer.py' modülüne bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "16. Görüşme Geçmişi Paneli (HistoryTab.tsx)")
    add_paragraph(doc, "Tamamlanan tüm müşteri görüşmelerinin kronolojik transkript dökümünü, ses kayıtlarını ve gecikme analizlerini içeren arşiv ekranıdır.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "Tarih, kanal (Telefon, Web, WhatsApp) ve sonuca göre arama geçmişi.", "Kronolojik Liste: ")
    add_bullet(doc, "Görüşmenin Opus veya WAV formatında güvenli ses oynatıcısı.", "Ses Kaydı Dinleme: ")
    add_bullet(doc, "Her bir diyalog turu için kullanıcı metni, asistan yanıtı, STT süresi, LLM süresi ve TTS sentez süresi.", "Tur Telemetrisi: ")
    add_bullet(doc, "Şüpheli veya problemli bir çağrıyı tek tıkla 'Supervisor Kalite' paneline denetim için aktarma.", "Kaliteye İnceleme Gönderme: ")
    add_paragraph(doc, "'GET /api/conversations', 'GET /api/conversations/{id}', 'GET /api/conversations/{id}/audio' uç noktaları üzerinden 'conversations' ve 'turns' tablolarına bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "17. Bildirimler & WhatsApp Paneli (NotificationPanel.tsx)")
    add_paragraph(doc, "Müşterilere ve kurumsal galerilere giden SMS ve WhatsApp mesajlarının kuyruğunu yöneten, teslim durumlarını izleyen ve çift yönlü WhatsApp botunu denetleyen modüldür.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "Veritabanı transaction'ı ile mesajın asla kaybolmamasını garanti eden Outbox tablosu (Pending, Sent, Failed).", "Transactional Outbox: ")
    add_bullet(doc, "Twilio WhatsApp API veya Mock sağlayıcı desteği; randevu onaylandığında şube Google Maps konum pini ile otomatik teyit mesajı.", "WhatsApp Webhook: ")
    add_bullet(doc, "Müşteri WhatsApp'tan sesli mesaj attığında Whisper STT ile metne çevirip randevu değişikliği veya iptalini diyalog motoruna işletme.", "Sesli Mesaj Transkripsiyonu: ")
    add_paragraph(doc, "'GET /api/notifications/outbox', 'POST /api/webhook/whatsapp' uç noktaları üzerinden 'backend/notifications.py' modülüne bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    # -------------------------------------------------------------------------
    # KATEGORİ 4: GÖZETİM, ANALİTİK & SİSTEM SAĞLIĞI
    # -------------------------------------------------------------------------
    add_heading_2(doc, "3.4. Kategori IV: Gözetim, Analitik & Sistem Sağlığı (4 Panel)")

    add_heading_3(doc, "18. Analitik & KPI Panosu (AnalyticsPanel.tsx)")
    add_paragraph(doc, "Tüm sistem operasyonunun performansını, gecikme SLA uyumunu ve iş metriklerini gerçek veritabanı kayıtlarından hesaplayan yönetici panosudur.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "Randevu oluşturma dönüşüm oranı (Conversion Rate) ve randevu iptal oranı (Cancellation Rate).", "İş Dönüşüm Metrikleri: ")
    add_bullet(doc, "STT, LLM, TTS ve İlk Ses (TTFA) için p50 (medyan), p95 ve p99 gecikme persentilleri.", "Gecikme Bütçesi Dağılımı: ")
    add_bullet(doc, "Haftalık operasyonel özet raporu ve 'openpyxl' ile üretilen biçimlendirilmiş, çok sekmeli kurumsal Excel (.xlsx) indirme imkanı.", "Otomatik Raporlama & Excel: ")
    add_paragraph(doc, "'GET /api/analytics/kpis', 'GET /api/analytics/weekly-summary', 'GET /api/analytics/weekly-excel' uç noktaları ile 'backend/analytics.py' ve 'backend/report_generator.py' modüllerine bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "19. Sistem & Donanım Sağlığı Paneli (SystemTab.tsx)")
    add_paragraph(doc, "NVIDIA GeForce RTX 4070 GPU VRAM durumunu, sıcaklık seviyelerini ve yapay zekâ modellerinin hazır bulunuşluğunu izleyen donanım gözetim masasıdır.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "FreyaTTS CUDA (TTS), Faster-Whisper (STT), Silero VAD ve Ollama (Qwen2.5) modellerinin READY / LOADED durum rozetleri.", "Bileşen Sağlık Rozetleri: ")
    add_bullet(doc, "GPU VRAM %90'ı veya sıcaklık 85°C'yi aştığında devreye girerek yeni oturumları güvenli bir şekilde operatöre aktaran veya CPU önbelleğine alan sigorta mekanizması.", "GPU Circuit Breaker: ")
    add_bullet(doc, "Modelleri tek tıkla belleğe yükleme ve boşaltma butonları.", "Model Kontrolü: ")
    add_paragraph(doc, "'GET /api/readiness', 'POST /api/models/load', 'GET /api/hardware/gpu' uç noktaları ile 'backend/gpu_health_circuit_breaker.py' modülüne bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    add_heading_3(doc, "20. M01–M11 Deterministik Kalite Kapıları Paneli (MilestonePanel.tsx)")
    add_paragraph(doc, "Sistemin üretim öncesi 11 kritik mühendislik aşamasını (kabul kriterlerini) başarıyla tamamladığını kanıtlayan deterministik test doğrulama panosudur.", bold_prefix="Amacı ve İşlevi: ")
    add_bullet(doc, "M01 (Fonetik Normalizasyon) ile M11 (Acoustic Evaluation & WER/CER) arasındaki tüm aşamalar yeşil rozetle listelenir.", "11 Aşama Listesi: ")
    add_bullet(doc, "Her bir aşama için bağımsız testleri arayüzden tek tıkla yeniden koşturma ve doğrulama sertifikasını inceleme imkanı.", "Doğrulama ve Kanıt: ")
    add_paragraph(doc, "'GET /api/milestones', 'POST /api/milestones/{id}/verify' uç noktaları üzerinden 'tests/milestones/' test dizinine bağlanır.", bold_prefix="Arka Uç Bağlantısı: ")

    doc.add_page_break()

    # =========================================================================
    # BÖLÜM 4: ARKA UÇ MİMARİSİ VE SERVİSLER
    # =========================================================================
    add_heading_1(doc, "4. Arka Uç Mimarisi, Servisler ve Protokoller")
    add_paragraph(
        doc,
        "Arka uç altyapısı, FastAPI tabanlı asenkron mikro-servis mimarisiyle inşa edilmiştir. "
        "Yüksek eşzamanlılık (concurrency) ve düşük gecikme için threading, asyncio ve TCP socket yapıları bir arada kullanılır."
    )

    arch_table = [
        ["Katman / Servis", "Protokol / Port", "Kullanılan Teknoloji", "Sorumluluk ve Mimari Rolü"],
        ["FastAPI Web & REST", "HTTP/1.1 (Port 8000)", "FastAPI + Uvicorn + Pydantic v2", "Tüm CRUD işlemleri, takvim, analitik, KVKK, dikte ve denetim uç noktalarını sunar."],
        ["WebSocket Ses Akışı", "WS (Port 8000 /ws/voice)", "Starlette WebSocket + Ticket Auth", "Tarayıcı Görüşme Kokpiti ile 16 kHz PCM ikili ses paketlerinin iki yönlü ultra hızlı akışı."],
        ["AudioSocket TCP Sunucusu", "TCP (Port 9092)", "Asenkron TCP Socket Sunucusu", "Asterisk PBX santralinden gelen canlı telefon sesini karşılar ve ses boru hattına bağlar."],
        ["Asterisk AMI Köprüsü", "TCP (Port 5038)", "Asterisk Manager Interface (AMI)", "Operatöre sıcak aktarım (Redirect/Bridge), kanal durumu izleme ve giden arama tetikleme."],
        ["Yapay Zekâ Motorları", "Yerel Bellek / CUDA", "PyTorch 2.4+ / CTranslate2 / Ollama", "FreyaTTS ODE, Faster-Whisper, Silero VAD ve Qwen2.5 7B modellerinin GPU üzerinde işletimi."],
        ["Transactional Outbox", "SQLite Transaction", "SQLAlchemy ORM + Background Loop", "SMS ve WhatsApp bildirimlerinin veri kaybı olmadan kuyruğa alınması ve garantili teslimi."],
        ["KVKK İmha Motoru", "Kriptografik Modül", "SHA-256 + HMAC + Regex Guard", "30 gün transkript denetimi, otomatik anonimleştirme ve dijital imha tutanağı üretimi."],
    ]
    add_styled_table(doc, arch_table[0], arch_table[1:], col_widths=[1.5, 1.4, 1.6, 2.3])

    # =========================================================================
    # BÖLÜM 5: VERİTABANI VARLIK-İLİŞKİ MODELLERİ (26 TABLO)
    # =========================================================================
    add_heading_1(doc, "5. Veritabanı Varlık-İlişki Modelleri (SQLAlchemy)")
    add_paragraph(
        doc,
        "Veritabanı motoru olarak SQLite WAL (Write-Ahead Logging) modu seçilmiştir. "
        "Foreign Key bütünlüğü ('PRAGMA foreign_keys=ON') ve 15 saniyelik kilit zaman aşımı sayesinde "
        "yüksek eşzamanlı okuma ve yazma işlemlerinde sıfır kilitlenme yaşanır. Sistemde 26 temel tablo bulunur:"
    )

    db_table_data = [
        ["Tablo Adı", "Temel Alanlar (Sütunlar)", "İlişkili Tablolar", "İşlevi ve Amacı"],
        ["conversations", "id, channel, status, operator_notes, created_at, resolved_at", "turns, appointments", "Oturum bazında tüm telefon, web ve WhatsApp görüşmelerinin üst kaydı."],
        ["turns", "id, conversation_id, role, text, metrics, created_at", "conversations", "Görüşme içi kullanıcı ve asistan diyalog turları, gecikme metrikleri."],
        ["vehicles", "id, description, plate, vin", "appointments, quotes", "Müşteri ve filo araçlarının marka, model, plaka ve şasi bilgisi."],
        ["slots", "id, starts_at, duration_minutes", "appointments", "Atölye randevu zaman dilimleri (30 dk), çakışma önleyici tekil anahtar."],
        ["appointments", "id, slot_id, vehicle_id, customer, customer_phone, status, package_type", "slots, vehicles, corporate", "Kesinleşmiş veya bekleyen randevu kayıtları, müşteri irtibatı."],
        ["inspection_reports", "id, vehicle_id, appointment_id, score, findings_json, pdf_path", "vehicles, appointments", "101 nokta ekspertiz muayene bulguları, genel araç puanı ve PDF yolu."],
        ["vehicle_diagnostics", "id, vehicle_id, dtc_code, severity, system_category, description_tr", "vehicles", "OBD-II soketinden okunan arıza kodları ve sensör telemetrisi."],
        ["quotes", "id, vehicle_id, amount_kurus", "vehicles", "Araç bazlı ekspertiz fiyat teklifleri (kuruş cinsinden)."],
        ["inspection_lifts", "id, name, lift_number, status, current_vehicle_plate", "appointments", "Atölyedeki fiziksel liftlerin doluluk ve meşguliyet durumu."],
        ["inspection_queues", "id, queue_number, plate, customer, package_type, status", "appointments, lifts", "Atölye önünde bekleyen araçların FIFO işlem sırası."],
        ["corporate_accounts", "id, name, tax_id, balance_kurus, credit_limit_kurus, discount_percent", "corporate_ledger", "Oto galerileri ve filoların cari hesapları, limit ve iskonto tanımları."],
        ["corporate_ledger", "id, account_id, appointment_id, entry_type, amount_kurus", "corporate_accounts", "Kurumsal cari hesap borç/alacak ve randevu iade hareketleri defteri."],
        ["ab_experiments", "id, name, experiment_type, status, variants_json, target_metric", "ab_assignments", "A/B test deney tanımları, varyant konfigürasyonları."],
        ["ab_assignments", "id, conversation_id, experiment_id, variant_id, outcome, turns_count", "conversations, ab_experiments", "Görüşmelerin A/B varyantlarına atanması ve sonuç metrikleri."],
        ["notifications", "id, appointment_id, recipient, channel, message, status, attempts", "appointments", "SMS ve WhatsApp mesajlarının Transactional Outbox gönderim kuyruğu."],
        ["outbound_calls", "id, appointment_id, phone, customer, call_type, status, outcome", "appointments", "Otomatik dış arama kampanyaları ve randevu teyit çağrıları."],
        ["operator_transfers", "id, conversation_id, caller_channel, operator_extension, status", "conversations", "Dahili 6002 operatör aktarım kayıtları, fısıltı metni ve SIP başlıkları."],
        ["whatsapp_messages", "id, from_phone, customer_name, raw_content, transcription", "appointments", "WhatsApp üzerinden gelen metin/ses mesajları ve niyet çıkarımları."],
        ["call_analytics", "id, conversation_id, caller_phone, csat_score, sentiment, lead_score", "conversations", "Görüşme sonrası müşteri duygu analizi, CSAT ve lead puanlaması."],
        ["audio_archives", "id, conversation_id, caller_phone, codec, file_path, sha256_hash", "conversations", "Şifreli/mühürlü ses kayıtları arşivi, 2 yıllık yasal saklama süresi."],
        ["kvkk_erasure_requests", "id, identifier_type, identifier_value, status, certificate_sha256", "Tüm tablolar", "KVKK Madde 11 unutulma hakkı talepleri ve resmi imha sertifikaları."],
    ]
    add_styled_table(doc, db_table_data[0], db_table_data[1:], col_widths=[1.5, 2.2, 1.2, 1.9])

    # =========================================================================
    # BÖLÜM 6: REST API VE GERÇEK ZAMANLI UÇ NOKTA REFERANSI
    # =========================================================================
    add_heading_1(doc, "6. REST API ve Gerçek Zamanlı Uç Nokta Referansı")
    add_paragraph(
        doc,
        "Arayüzün arka uç ile haberleştiği tüm uç noktalar HTTP Basic Authentication ('admin:password') "
        "ile korunmaktadır. Aşağıdaki tabloda en kritik arayüz uç noktaları listelenmiştir:"
    )

    api_table_data = [
        ["HTTP Metodu", "Endpoint Yolu", "İlgili Arayüz Paneli", "Açıklama ve Döndürülen Veri"],
        ["GET", "/api/readiness", "Sistem, CockpitHeader", "GPU, VRAM, STT, TTS ve LLM servislerinin hazır bulunuşluk durumu."],
        ["POST", "/api/session-ticket", "Görüşme Kokpiti", "WebSocket ses oturumu için 30 saniye geçerli güvenli bilet üretir."],
        ["WS", "/ws/voice", "Görüşme Kokpiti", "Çift yönlü 16 kHz PCM ses akışı, VAD araya girme ve canlı transkript."],
        ["GET", "/api/appointments/calendar", "Randevu Takvimi", "Belirli tarih aralığındaki tüm randevuları ve boş slotları döner."],
        ["POST", "/api/appointments/{id}/reschedule", "Randevu Takvimi", "Randevuyu sürükle-bırak ile yeni bir slota taşır (çakışma kontrollü)."],
        ["POST", "/api/dsp/denoise-car-audio", "Araç İçi DSP & Gürültü", "Yüklenen ses dosyasına 120Hz HPF ve spektral filtre uygular."],
        ["GET", "/api/conversations/unclear", "Operatör (6002)", "Anlaşılamayan veya düşük güvenli diyalog turlarını listeler."],
        ["POST", "/api/conversations/{id}/feedback-lexicon", "Operatör (6002)", "Hatalı anlaşılan kelimeyi tek tıkla telaffuz sözlüğüne ekler."],
        ["GET", "/api/kvkk/transcript-retention-audit", "Operatör (KVKK Sekmesi)", "30 günü aşan transkriptlerin uyumluluk denetimini raporlar."],
        ["POST", "/api/kvkk/transcript-retention-purge", "Operatör (KVKK Sekmesi)", "Süresi dolmuş transkriptleri toplu olarak anonimleştirir/imha eder."],
        ["POST", "/api/kvkk/erasure-requests", "Operatör (KVKK Sekmesi)", "Unutulma hakkı talebi açar ve bağlı kayıtların etki analizini çıkarır."],
        ["POST", "/api/kvkk/erasure-requests/{id}/execute", "Operatör (KVKK Sekmesi)", "Verileri kalıcı olarak imha eder ve SHA-256 sertifikası üretir."],
        ["GET", "/api/kvkk/erasure-requests/{id}/certificate", "Operatör (KVKK Sekmesi)", "Resmi KVKK İmha Tutanağını metin veya JSON formatında teslim eder."],
        ["GET", "/api/analytics/kpis", "Analitik & KPI", "Gerçek iptal, dönüşüm ve p50/p95/p99 gecikme persentillerini döner."],
        ["GET", "/api/analytics/weekly-excel", "Analitik & KPI", "Tüm operasyonun çok sekmeli biçimlendirilmiş Excel raporunu indirir."],
        ["POST", "/api/technician/parse-findings", "Teknisyen Dikte", "Ustanın ses kaydından yapılandırılmış parça bulgu JSON'ı çıkarır."],
    ]
    add_styled_table(doc, api_table_data[0], api_table_data[1:], col_widths=[0.8, 2.2, 1.5, 2.3])

    # =========================================================================
    # BÖLÜM 7: DETERMINISTIC ENGINEERING MILESTONES (M01 – M11)
    # =========================================================================
    add_heading_1(doc, "7. Deterministik Mühendislik Kalite Kapıları (M01 – M11)")
    add_paragraph(
        doc,
        "Sistemin endüstriyel kararlılığı, rastlantısal başarıya değil, otomatik testlerle korunan "
        "11 adet aşılmaz kalite kapısına (Quality Gates) dayanmaktadır:"
    )

    milestone_data = [
        ["Kapı", "Aşama Başlığı", "Kabul Kriteri ve Eşik Değeri", "Doğrulama Yöntemi"],
        ["M01", "Fonetik Normalizasyon", "Otomotiv terimleri ve sayı gruplarında sıfır hata.", "Normalizer test paketi."],
        ["M02", "Gürültü Kararlılığı", "Araç içi kabin gürültüsünde WER < %5 artış toleransı.", "Acoustic evaluation testi."],
        ["M03", "Ses Aktivite Tespiti (VAD)", "Konuşma başlangıcı < 35 ms, yanlış kesme < %1.", "Silero VAD stres testi."],
        ["M04", "ASR Terim Doğruluğu", "Marka/şanzıman terimlerinde %95+ kelime tanıma.", "Otomotiv sözlük kıyası."],
        ["M05", "Diyalog Durum Makinesi", "Dönüşüm kaybı olmaksızın çoklu araç ve randevu yönetimi.", "E2E workflow testleri."],
        ["M06", "ODE Hızlı Sentezleyici", "Tek nefeste < 150 ms ses üretimi, ses çatallanması yok.", "PyTorch benchmark."],
        ["M07", "Ses İletim Akışı", "AudioSocket TCP üzerinde sıfır paket kaybı ve arabelleksiz iletim.", "TCP stres testi."],
        ["M08", "Asterisk Santral Köprüsü", "AMI üzerinden < 500 ms içinde operatöre pürüzsüz aktarım.", "SIP warm transfer testi."],
        ["M09", "WhatsApp & Outbox Entegrasyonu", "Transactional Outbox ile sıfır mesaj kaybı garantisi.", "Webhook & retry testi."],
        ["M10", "Gözetim & FQICI Denetimi", "22 niyet yönlendirmede Makro F1 > 0.92 başarım.", "XGBoost & supervisor testi."],
        ["M11", "Akustik Donanım Kabulü", "RTX 4070 VRAM < 7.2 GB ve donanım koruma sigortası.", "Circuit breaker testi."],
    ]
    add_styled_table(doc, milestone_data[0], milestone_data[1:], col_widths=[0.7, 1.8, 2.3, 2.0])

    # =========================================================================
    # BÖLÜM 8: DONANIM GEREKSİNİMLERİ VE DAĞITIM BÜTÇESİ
    # =========================================================================
    add_heading_1(doc, "8. Donanım Gereksinimleri, Dağıtım ve Performans Bütçesi")
    add_paragraph(
        doc,
        "FreyaTTS mimarisi, pahalı sunucu kümeleri veya bulut API bağımlılıkları gerektirmeden, "
        "tek bir standart iş istasyonunda veya yerel atölye sunucusunda çalışacak şekilde optimize edilmiştir:"
    )

    hw_table = [
        ["Donanım Bileşeni", "Asgari İhtiyaç", "Önerilen / Test Edilen Sistem", "Sistemdeki Rolü"],
        ["Ekran Kartı (GPU)", "NVIDIA RTX 3060 (6 GB VRAM)", "NVIDIA GeForce RTX 4070 (8 GB+ VRAM)", "FreyaTTS ODE, Faster-Whisper ve Ollama GPU katmanları."],
        ["İşlemci (CPU)", "6 Çekirdekli x86_64", "AMD Ryzen 7 veya Intel Core i7 (8+ Çekirdek)", "AudioSocket TCP sunucusu, DSP Butterworth filtreleme ve SQLite."],
        ["Sistem Belleği (RAM)", "16 GB DDR4/DDR5", "32 GB DDR5 RAM", "Model önbelleği ve yüksek eşzamanlı oturum arabellekleri."],
        ["Depolama Alanı", "20 GB Boş Alan (SSD)", "M.2 NVMe SSD (PCIe 4.0)", "Model ağırlıkları, SQLite WAL veritabanı ve 2 yıllık ses arşivi."],
        ["İşletim Sistemi", "Windows 10/11 x64 / Ubuntu 22.04", "Windows 11 Pro (Yerel İş İstasyonu)", "FastAPI backend, Vite frontend ve yerel donanım sürücüleri."],
    ]
    add_styled_table(doc, hw_table[0], hw_table[1:], col_widths=[1.5, 1.5, 1.8, 2.0])

    add_callout(
        doc,
        "Proje Python 3.10+ ve modern Node.js/Vite ortamında çalıştırılır. "
        "Backend 'uvicorn backend.main:app --port 8000' komutu ile başlatılırken, "
        "arayüz 'npm run build' ile derlenip doğrudan FastAPI üzerinden veya Vite geliştirme sunucusunda ('npm run dev') kullanılabilir. "
        "Sistemdeki tüm 1074 adet otomatik birim ve entegrasyon testi 173 saniyede %100 başarıyla tamamlanmaktadır.",
        title="🚀 DAĞITIM VE BAŞLATMA ÖZETİ",
        border_color=HEX_SECONDARY
    )

    output_path = "c:\\Users\\seydieryilmaz\\Desktop\\FreyaTTS_Automotive_PoC\\FreyaTTS_Automotive_PoC_Mimari_ve_Arayuz_Sunumu.docx"
    doc.save(output_path)
    print(f"BAŞARILI: Doküman oluşturuldu -> {output_path}")

if __name__ == "__main__":
    main()
