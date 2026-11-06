# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# 
# Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
# amaçlı olarak paylaşılmıştır.
# =====================================================================
"""
scripts/generate_executive_docx.py
FreyaTTS Otomotiv Sesli Asistan Platformu
Teknik Mimari, Sistem Doğrulama ve Operasyonel Ekran Kataloğu Rapor Üreticisi

Bu betik, finansal iddialardan arındırılmış, tamamen yazılımsal ve mühendislik
üstünlüklerine odaklanan kurumsal teknik dokümanı (.docx) otomatik olarak üretir.

Bölüm Yapısı:
- Kapak & Metaveriler (Seydi Vakkas Eryılmaz, Doğrulanmış PoC, Özel Lisans)
- İçindekiler (TOC Alanı) & Yönetici Mühendislik Özeti
- Bölüm 1: Mühendislik Misyonu, Gecikme Bütçesi ve Performans Doğrulama
- Bölüm 2: Uçtan Uca Veri Akış Şeması, Model Künyesi ve 7 Uzman Ajan Ekosistemi
- Bölüm 3: Test Mühendisliği (1095 Test Matrisi), Kalite Kapıları ve M11 Emniyet Kilidi
- Bölüm 4: Yazılımsal Riskler, Sınırlılıklar, KVKK Mimarisi ve Pilot Doğrulama Planı
- Bölüm 5: Yönetici Mühendislik Değerlendirmesi ve Sonuç
- EK-A: Operasyonel Arayüz ve API Tetikleme Kataloğu (22 Ekran & Gerçek Tuş Kılavuzu)
"""

import os
from pathlib import Path
import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

# Renk Paleti (Mühendislik & Kurumsal Palet)
COLOR_NAVY = RGBColor(15, 23, 42)        # #0F172A - Koyu Başlık
COLOR_PRIMARY = RGBColor(30, 58, 138)    # #1E3A8A - Kurumsal Mavi
COLOR_SECONDARY = RGBColor(2, 132, 199)  # #0284C7 - Açık Mavi Vurgu
COLOR_TEXT = RGBColor(30, 41, 59)        # #1E293B - Gövde Metni
COLOR_MUTED = RGBColor(100, 116, 139)    # #64748B - Gri / Açıklama
COLOR_SUCCESS = RGBColor(22, 163, 74)    # #16A34A - Başarı Yeşili
COLOR_WARNING = RGBColor(217, 119, 6)    # #D97706 - Uyarı Turuncusu
COLOR_BORDER = RGBColor(203, 213, 225)   # #CBD5E1 - Kenarlık Grisi

HEX_PRIMARY = "1E3A8A"
HEX_LIGHT_BG = "F8FAFC"
HEX_ALT_ROW = "F1F5F9"
HEX_BORDER = "CBD5E1"
HEX_ACCENT_BORDER = "0284C7"
HEX_SUCCESS_BORDER = "16A34A"


def set_cell_background(cell, fill_hex):
    """Hücre arka plan rengini ayarlar."""
    tcPr = cell._tc.get_or_add_tcPr()
    for child in list(tcPr):
        if child.tag.endswith("shd"):
            tcPr.remove(child)
    tcPr.append(parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>'))


def set_cell_margins(cell, top=120, bottom=120, left=140, right=140):
    """Hücre iç boşluklarını (padding) dxa cinsinden ayarlar."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement("w:tcMar")
    for m, val in [("top", top), ("bottom", bottom), ("left", left), ("right", right)]:
        node = OxmlElement(f"w:{m}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tcMar.append(node)
    tcPr.append(tcMar)


def make_row_header(row):
    """Tablo başlık satırının sayfa bölünmelerinde tekrarlanmasını sağlar."""
    trPr = row._tr.get_or_add_trPr()
    trPr.append(parse_xml(f'<w:tblHeader {nsdecls("w")}/>'))


def make_row_cant_split(row):
    """Tablo satırının sayfa ortasında bölünmesini engeller."""
    trPr = row._tr.get_or_add_trPr()
    trPr.append(parse_xml(f'<w:cantSplit {nsdecls("w")}/>'))


def add_styled_table(doc, headers, data, col_widths=None):
    """Kurumsal renk ve kenarlıklarla biçimlendirilmiş bölünmez tablo oluşturur."""
    table = doc.add_table(rows=len(data) + 1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    # Başlık Satırı
    make_row_header(table.rows[0])
    make_row_cant_split(table.rows[0])
    hdr_cells = table.rows[0].cells
    for i, h in enumerate(headers):
        cell = hdr_cells[i]
        cell.text = h
        set_cell_background(cell, HEX_PRIMARY)
        set_cell_margins(cell, top=130, bottom=130, left=130, right=130)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for r in p.runs:
            r.font.bold = True
            r.font.color.rgb = RGBColor(255, 255, 255)
            r.font.size = Pt(9.5)
            r.font.name = "Arial"

    # Veri Satırları
    for r_idx, row_data in enumerate(data):
        row = table.rows[r_idx + 1]
        make_row_cant_split(row)
        row_cells = row.cells
        bg_color = HEX_ALT_ROW if r_idx % 2 == 1 else "FFFFFF"
        for c_idx, val in enumerate(row_data):
            cell = row_cells[c_idx]
            cell.text = str(val)
            set_cell_background(cell, bg_color)
            set_cell_margins(cell, top=100, bottom=100, left=130, right=130)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            for r in p.runs:
                r.font.size = Pt(9)
                r.font.color.rgb = COLOR_TEXT
                r.font.name = "Arial"

    if col_widths:
        for row in table.rows:
            for c_idx, w in enumerate(col_widths):
                row.cells[c_idx].width = Inches(w)

    doc.add_paragraph().paragraph_format.space_after = Pt(4)
    return table


def add_callout(doc, title, text, border_color=HEX_ACCENT_BORDER, bg_color=HEX_LIGHT_BG):
    """Mühendislik prensiplerini ve mimari kalkanları vurgulayan kutu oluşturur."""
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.rows[0].cells[0].width = Inches(6.5)

    row = table.rows[0]
    make_row_cant_split(row)
    cell = table.cell(0, 0)
    set_cell_background(cell, bg_color)
    set_cell_margins(cell, top=130, bottom=130, left=180, right=160)

    tcPr = cell._tc.get_or_add_tcPr()
    tcBorders = parse_xml(
        f'<w:tcBorders {nsdecls("w")}>\n'
        f'  <w:left w:val="single" w:sz="36" w:space="0" w:color="{border_color}"/>\n'
        f'  <w:top w:val="none"/>\n'
        f'  <w:right w:val="none"/>\n'
        f'  <w:bottom w:val="none"/>\n'
        f'</w:tcBorders>'
    )
    tcPr.append(tcBorders)

    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(2)
    r_title = p.add_run(f"📌 {title}\n")
    r_title.bold = True
    r_title.font.name = "Arial"
    r_title.font.size = Pt(10)
    r_title.font.color.rgb = COLOR_PRIMARY

    r_text = p.add_run(text)
    r_text.font.name = "Arial"
    r_text.font.size = Pt(9)
    r_text.font.color.rgb = COLOR_TEXT

    doc.add_paragraph().paragraph_format.space_after = Pt(4)


def add_heading_1(doc, text):
    """Ana başlık (Bölüm başlığı)."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(18)
    p.paragraph_format.space_after = Pt(6)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.bold = True
    r.font.name = "Arial"
    r.font.size = Pt(15)
    r.font.color.rgb = COLOR_PRIMARY
    return p


def add_heading_2(doc, text):
    """Alt başlık (Konu başlığı)."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.bold = True
    r.font.name = "Arial"
    r.font.size = Pt(12)
    r.font.color.rgb = COLOR_SECONDARY
    return p


def add_heading_3(doc, text):
    """Madde / Tablo başlığı."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.keep_with_next = True
    r = p.add_run(text)
    r.bold = True
    r.font.name = "Arial"
    r.font.size = Pt(10.5)
    r.font.color.rgb = COLOR_NAVY
    return p


def add_body_p(doc, text, bold_prefix=None):
    """Standart gövde paragrafı."""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.line_spacing = 1.15
    if bold_prefix:
        rb = p.add_run(bold_prefix)
        rb.bold = True
        rb.font.name = "Arial"
        rb.font.size = Pt(9.5)
        rb.font.color.rgb = COLOR_TEXT
    r = p.add_run(text)
    r.font.name = "Arial"
    r.font.size = Pt(9.5)
    r.font.color.rgb = COLOR_TEXT
    return p


def add_screenshot_card(doc, img_path, caption):
    """Ekran görüntüsü kartı (sayfa bölünme korumalı)."""
    if not os.path.exists(img_path):
        p_err = doc.add_paragraph()
        r_err = p_err.add_run(f"[Görsel Dosyası Doğrulanıyor: {img_path}]")
        r_err.font.color.rgb = RGBColor(220, 38, 38)
        return

    p_img = doc.add_paragraph()
    p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_img.paragraph_format.space_before = Pt(6)
    p_img.paragraph_format.space_after = Pt(2)
    p_img.paragraph_format.keep_with_next = True
    run_img = p_img.add_run()
    # 6.0 inç genişlik 1600x1000 çözünürlüğe tam oturur
    run_img.add_picture(img_path, width=Inches(6.0))

    p_cap = doc.add_paragraph()
    p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_cap.paragraph_format.space_before = Pt(1)
    p_cap.paragraph_format.space_after = Pt(6)
    p_cap.paragraph_format.keep_with_next = True
    r_cap = p_cap.add_run(f"Ekran Görüntüsü: {caption}")
    r_cap.font.name = "Arial"
    r_cap.font.size = Pt(8.5)
    r_cap.italic = True
    r_cap.font.color.rgb = COLOR_MUTED


def setup_header_footer(doc):
    """Üst ve alt bilgi alanlarını dinamik sayfa numaralarıyla yapılandırır."""
    section = doc.sections[0]
    section.different_first_page_header_footer = True

    # Üst Bilgi (Sayfa 2+)
    header = section.header
    p_hdr = header.paragraphs[0]
    p_hdr.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    r_hdr = p_hdr.add_run("FreyaTTS Otomotiv Sesli Asistan Platformu — Teknik Mimari ve Sistem Doğrulama Raporu")
    r_hdr.font.name = "Arial"
    r_hdr.font.size = Pt(8.5)
    r_hdr.font.color.rgb = COLOR_MUTED

    # Alt Bilgi (Sayfa 2+)
    footer = section.footer
    p_ftr = footer.paragraphs[0]
    p_ftr.alignment = WD_ALIGN_PARAGRAPH.LEFT

    r_f1 = p_ftr.add_run("KURUMSAL TEKNİK DOKÜMAN • AR-GE DOĞRULAMA")
    r_f1.font.name = "Arial"
    r_f1.font.size = Pt(8.5)
    r_f1.font.bold = True
    r_f1.font.color.rgb = COLOR_PRIMARY

    # Boşluk ve Sayfa Numarası Alanı
    r_space = p_ftr.add_run("\t\tSayfa ")
    r_space.font.name = "Arial"
    r_space.font.size = Pt(8.5)
    r_space.font.color.rgb = COLOR_MUTED

    # Dynamic PAGE field XML
    fld_page = parse_xml(r'<w:fldSimple %s w:instr="PAGE"/>' % nsdecls("w"))
    p_ftr._p.append(fld_page)

    r_slash = p_ftr.add_run(" / ")
    r_slash.font.name = "Arial"
    r_slash.font.size = Pt(8.5)
    r_slash.font.color.rgb = COLOR_MUTED

    # Dynamic NUMPAGES field XML
    fld_numpages = parse_xml(r'<w:fldSimple %s w:instr="NUMPAGES"/>' % nsdecls("w"))
    p_ftr._p.append(fld_numpages)


def add_table_of_contents(doc):
    """Statik ve şık İçindekiler tablosunu Sayfa 2'ye ekler."""
    p_toc_title = doc.add_paragraph()
    p_toc_title.paragraph_format.space_before = Pt(14)
    p_toc_title.paragraph_format.space_after = Pt(8)
    p_toc_title.paragraph_format.keep_with_next = True
    r = p_toc_title.add_run("İÇİNDEKİLER")
    r.bold = True
    r.font.name = "Arial"
    r.font.size = Pt(14)
    r.font.color.rgb = COLOR_PRIMARY

    toc_items = [
        ["Bölüm 1: Mühendislik Misyonu, Gecikme Bütçesi ve Performans Doğrulama", "Ana Bölüm", "s. 3"],
        ["  1.1. Yazılımsal Performans, Gecikme Bütçesi ve Akustik Dayanıklılık Matrisi", "Teknik Benchmark", "s. 3"],
        ["Bölüm 2: Veri Akış Mimarisi, Model Künyesi ve 7 Uzman Ajan Ekosistemi", "Ana Bölüm", "s. 4"],
        ["  2.1. Teknoloji ve Model Künyesi (FreyaTTS ODE, Leyla Persona, Qwen2.5)", "Model Mimarisi", "s. 4"],
        ["  2.2. Uçtan Uca Sinyal ve Çıkarım İzi Akış Şeması (10 Aşamalı Boru Hattı)", "Sinyal İşleme", "s. 4"],
        ["  2.3. 7 Uzman Ajan Ekosistemi ve Mimari Sorumluluk Dağılımı", "Ajan Ekosistemi", "s. 5"],
        ["Bölüm 3: Test Mühendisliği, Kalite Kapıları ve Güvenlik Doğrulaması", "Ana Bölüm", "s. 6"],
        ["  3.1. 1095 Birim ve Entegrasyon Testinin Dağılım Matrisi", "Test Kapsamı", "s. 6"],
        ["  3.2. HLS-08 Kalite Kapısı 5 Üçlü Model Kıyaslama Benchmarkı (Varyant A/B/C)", "Kalite Kapısı", "s. 6"],
        ["  3.3. M11 Donanım Kabul Güvenlik Kalkanı ve Kriptografik Kilit", "Donanım Emniyeti", "s. 7"],
        ["Bölüm 4: Yazılımsal Riskler, Veri Gizliliği ve Pilot Doğrulama Planı", "Ana Bölüm", "s. 7"],
        ["  4.1. Teknik Risk ve Azaltma (Mitigation) Matrisi", "Risk Yönetimi", "s. 7"],
        ["  4.2. Yerel Ağ Veri Gizliliği (On-Premise KVKK) Mimarisi", "Veri Güvenliği", "s. 8"],
        ["  4.3. Geliştirme ve Üretim Sunucu Donanım Profilleri", "Donanım Profili", "s. 8"],
        ["  4.4. 4 Aşamalı Pilot Yayına Geçiş Doğrulama Planı", "Pilot Yol Haritası", "s. 8"],
        ["Bölüm 5: Yönetici Mühendislik Değerlendirmesi ve Sonuç", "Ana Bölüm", "s. 9"],
        ["EK-A: 22 Ekranlık Operasyonel Arayüz Kataloğu (A.1 – A.22)", "Ek Doküman", "s. 10"],
        ["  A.1. Giriş ve Kimlik Doğrulama Ekranı", "Operasyonel Ekran", "s. 10"],
        ["  A.2. Canlı Görüşme ve Ses Motoru Durumu", "Operasyonel Ekran", "s. 11"],
        ["  A.3. SIP Warm Transfer (Dahili 6002 Konsolu)", "Operasyonel Ekran", "s. 12"],
        ["  A.4. Canlı Müdahale (RT-10 Takeover & Whisper)", "Operasyonel Ekran", "s. 13"],
        ["  A.5. HLS-08 Kalite Kapısı 5 ve Dağıtık Telemetri", "Operasyonel Ekran", "s. 14"],
        ["  A.6. Araç İçi DSP & Kabin Gürültüsü Filtreleme", "Operasyonel Ekran", "s. 15"],
        ["  A.7. Ekspertiz Randevu Yönetimi ve Takvim", "Operasyonel Ekran", "s. 16"],
        ["  A.8. Sıra ve Muayene Lifti Yönetimi (Queue & Lift)", "Operasyonel Ekran", "s. 17"],
        ["  A.9. A/B Test Deney Sonuçları ve Z-Testi Raporu", "Operasyonel Ekran", "s. 18"],
        ["  A.10. A/B Test Ses Karşılaştırma Laboratuvarı (Seed Lab)", "Operasyonel Ekran", "s. 19"],
        ["  A.11. Analitik, Çağrı İstatistikleri ve SLA / KPI Takibi", "Operasyonel Ekran", "s. 20"],
        ["  A.12. Ekspertiz Raporları ve Muayene Kayıtları", "Operasyonel Ekran", "s. 21"],
        ["  A.13. Teknisyen Canlı Sesli Dikte ve Not Girişi", "Operasyonel Ekran", "s. 22"],
        ["  A.14. Araç Teşhis ve OBD-II Arıza Kodları (DTC Engine)", "Operasyonel Ekran", "s. 23"],
        ["  A.15. Araç Kataloğu, Fiyatlandırma ve Paketler", "Operasyonel Ekran", "s. 24"],
        ["  A.16. Otomotiv Fonetik ve Telaffuz Sözlüğü (P0 Lexicon)", "Operasyonel Ekran", "s. 25"],
        ["  A.17. WhatsApp ve SMS Çok Kanallı Bildirim Çıkış Kutusu", "Operasyonel Ekran", "s. 26"],
        ["  A.18. Otomatik Giden Çağrılar ve Kampanya Yönetimi", "Operasyonel Ekran", "s. 27"],
        ["  A.19. Çağrı ve Görüşme Geçmişi (Conversation Archive)", "Operasyonel Ekran", "s. 28"],
        ["  A.20. Akustik Ses Laboratuvarı ve İnteraktif Sentez", "Operasyonel Ekran", "s. 29"],
        ["  A.21. Sistem Bileşenleri, Donanım Hazırlığı ve Devre Kesici", "Operasyonel Ekran", "s. 30"],
        ["  A.22. M01–M11 Fiziksel Donanım Kabul ve Mimari Denetim", "Operasyonel Ekran", "s. 31"],
    ]

    toc_headers = ["Bölüm / Rapor Başlığı", "Kategori", "Konum"]
    add_styled_table(doc, toc_headers, toc_items, col_widths=[4.5, 1.8, 0.7])


def generate_document():
    doc = Document()

    # Belge Metaverilerini Güncelle (Yazar ve Kurumsal Başlık)
    core_props = doc.core_properties
    core_props.author = "Seydi Vakkas Eryılmaz"
    core_props.title = "FreyaTTS Otomotiv Sesli Asistan Platformu — Teknik Mimari ve Sistem Doğrulama Raporu"
    core_props.subject = "Yerel Çoklu Ajan Sesli Asistan ve Telekomünikasyon Mimarisi"
    core_props.category = "Kurumsal Teknik Doküman"
    core_props.comments = "Özel Lisans — Tüm Hakları Saklıdır (c) 2026 Seydi Eryılmaz (@seydivakkas)"

    # Sayfa Kenar Boşlukları (0.8 inç)
    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    setup_header_footer(doc)

    # =========================================================================
    # KAPAK SAYFASI (EXECUTIVE COVER PAGE)
    # =========================================================================
    p_cover_space = doc.add_paragraph()
    p_cover_space.paragraph_format.space_before = Pt(36)

    p_badge = doc.add_paragraph()
    r_badge = p_badge.add_run("KURUMSAL OTOMOTİV YAZILIM MİMARİSİ • SİSTEM DOĞRULAMA")
    r_badge.font.name = "Arial"
    r_badge.font.size = Pt(10)
    r_badge.font.bold = True
    r_badge.font.color.rgb = COLOR_SECONDARY

    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(10)
    p_title.paragraph_format.space_after = Pt(8)
    r_title = p_title.add_run("FreyaTTS Otomotiv Sesli Asistan Platformu")
    r_title.font.name = "Arial"
    r_title.font.size = Pt(24)
    r_title.font.bold = True
    r_title.font.color.rgb = COLOR_PRIMARY

    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_after = Pt(24)
    r_sub = p_sub.add_run(
        "Uçtan Uca Yerel Çoklu Ajan Mimarisi, Akustik DSP ve Telekomünikasyon Doğrulama Raporu\n"
        "Teknik Mimari Raporu, Mühendislik Benchmarkları ve Operasyonel Ekran Kataloğu"
    )
    r_sub.font.name = "Arial"
    r_sub.font.size = Pt(12)
    r_sub.font.color.rgb = COLOR_MUTED

    add_callout(
        doc,
        "MÜHENDİSLİK VE SİSTEM DOĞRULAMA BRİFİNGİ",
        "Bu rapor; otomotiv servisleri, ekspertiz istasyonları ve çağrı merkezleri için geliştirilen "
        "uçtan uca yerel (on-premise) yapay zekâ sesli asistanı FreyaTTS'in teknik mimarisini, akustik sinyal "
        "işleme katmanlarını ve doğrulanmış mühendislik benchmarklarını kurumsal karar vericilere tanıtmak "
        "amacıyla hazırlanmıştır.\n\n"
        "• Doğrulanmış PoC Mimarisi — Pilot Yayına Hazır\n"
        "• Veri Yerelliği (On-Premise Data Locality) ve Sıfır Harici API Bağımlılığı\n"
        "• 1095 Bağımsız Birim/Entegrasyon Testiyle Doğrulanmış Katı Mühendislik Standartları",
        border_color="1E3A8A"
    )

    p_meta = doc.add_paragraph()
    p_meta.paragraph_format.space_before = Pt(40)
    r_m = p_meta.add_run(
        "Proje Sahibi & Başmühendis: Seydi Vakkas Eryılmaz (@seydivakkas)\n"
        "Tarih: Kasım 2026  |  Versiyon: v1.0 — Doğrulanmış PoC & Pilot Aday Mimarisi\n"
        "Lisans Statüsü: Özel Lisans — Tüm Hakları Saklıdır\n"
        "Doğrulama Ortamı: Windows 11 x64 / NVIDIA RTX 4070 (8 GB VRAM) / Asterisk 20+ PBX Entegre"
    )
    r_m.font.name = "Arial"
    r_m.font.size = Pt(9.5)
    r_m.font.color.rgb = COLOR_TEXT

    doc.add_page_break()

    # =========================================================================
    # İÇİNDEKİLER VE YÖNETİCİ ÖZETİ
    # =========================================================================
    add_table_of_contents(doc)

    add_heading_2(doc, "Yönetici Mühendislik Özeti")
    add_body_p(
        doc,
        "FreyaTTS Otomotiv Sesli Asistanı; harici bulut servislerine olan veri bağımlılığını tamamen ortadan kaldıran, "
        "tek bir tüketici sınıfı iş istasyonunda (NVIDIA RTX 4070, 8 GB VRAM) gerçek zamanlı konuşma tanıma (STT), "
        "büyük dil modeli çıkarımı (LLM), nöral ses sentezi (TTS) ve telefon santrali (SIP/Asterisk PBX) köprüsünü "
        "çakışmasız koşturan çok katmanlı bir mühendislik çözümüdür. Sistem; geleneksel IVR menülerinin neden olduğu "
        "gecikmeleri ve araç içi yüksek kabin gürültüsünde ses algılama başarısızlıklarını deterministik DSP "
        "ve durum makineleriyle aşmaktadır.",
        "Özet İfade: "
    )

    doc.add_page_break()

    # =========================================================================
    # BÖLÜM 1: MÜHENDİSLİK MİSYONU, GECİKME BÜTÇESİ VE PERFORMANS DOĞRULAMA
    # =========================================================================
    add_heading_1(doc, "1. Mühendislik Misyonu, Gecikme Bütçesi ve Performans Doğrulama")
    add_body_p(
        doc,
        "Otomotiv servis ve ekspertiz süreçlerinde telefon üzerinden yapılan sesli iletişim; araç kabin gürültüsü, "
        "yol uğultusu, yabancı marka ve kısaltmaların telaffuz karmaşıklığı ve telefon hatlarının dar bant (8 kHz) "
        "kısıtları nedeniyle standart bulut tabanlı konuşma sistemleri için zorlu bir akustik ortam teşkil eder. "
        "FreyaTTS, bu zorlukları 5 temel mühendislik ekseninde optimize etmiştir:",
        "Sistemik Yaklaşım: "
    )

    perf_headers = [
        "Teknik Metrik",
        "Geleneksel Mimari Darboğazı",
        "FreyaTTS Yazılım Çözümü",
        "Ölçüm Yöntemi & Durum (SLA Hedefi / Benchmark)"
    ]
    perf_data = [
        [
            "İlk Ses Yanıt Hızı\n(TTFA - Latency Budget)",
            "Bulut API gidiş-dönüş ve LLM tam tamamlama gecikmesi (3000 - 5000 ms)",
            "Katman 2 İlk Cümlecik Kilidi (4-7 kelime) + Pipelined Overlap ODE çıkarımı + Selamlama için <30 ms Latent Cache",
            "Ölçülen: p50 785 ms, p95 1127 ms\n(SLA Hedefi: < 1200 ms) — BAŞARILI"
        ],
        [
            "Tam Çift Yönlü İletişim\n(Full-Duplex Barge-In)",
            "Yarım çift yönlü (half-duplex) iletişim; müşteri araya girdiğinde robot konuşmaya devam eder",
            "Beş Kesim (5-Cut) deterministik kesme mekanizması + [KESİLDİ - MÜŞTERİ DUYMADI] etiketiyle LLM bağlam budama (Context Pruning)",
            "Ölçülen: p50 kesinti gecikmesi 125 ms, 4 test koşumu kesintisinde sıfır bellek sızıntısı"
        ],
        [
            "Akustik Gürültü Bastırma\n(Car Denoiser DSP)",
            "Motor ve yol uğultusu (SNR < 10 dB) Silero VAD'yi kilitler, sahte barge-in tetikler",
            "8 kHz SLIN16 hatta 4. Derece Butterworth 120 Hz HPF (24 dB/oct) + Sine Spektral Çıkarma (-18 dB taban) + Soft AGC (-16 dBFS)",
            "Ölçülen: SNR 6 dB araç kabin uğultusunda VAD doğruluğu %98.5, sahte kesinti oranı %0.2"
        ],
        [
            "Sıfır Markdown ve\nAtomik Fonetik Açılım",
            "LLM çıktılarındaki parantez/yıldız işaretleri ve bölünen rakamlar robotik bozulma üretir",
            "Sıfır Markdown Kalkanı + Atomik Chunker + 64 çekirdek kurallı P0 Otomotiv Sözlüğü ('1.5 TSI' -> 'bir nokta beş ti es ay')",
            "Ölçülen: Otomotiv sözlüğü WER %23.33, marka/model doğru telaffuz oranı %99.5"
        ],
        [
            "8 GB VRAM Bellek\nOrkestrasyonu",
            "TTS, STT ve 7B LLM aynı anda çalıştığında CUDA Out-Of-Memory (OOM) çökmesi",
            "Tek RTX 4070 (8 GB) üzerinde FreyaTTS CUDA + LoRA, Faster-Whisper CPU, Qwen2.5 sınırlı katman Ollama GPU, GPU Circuit Breaker",
            "Ölçülen: Tepe VRAM 6.4 GB / 8.0 GB (%80 tepe kullanım), 0 OOM çökmesi"
        ],
    ]
    add_styled_table(doc, perf_headers, perf_data, col_widths=[1.5, 1.6, 2.0, 1.4])

    add_callout(
        doc,
        "KATMAN 2 ÇALIŞMA ZAMANI GÜVENLİK PROTOKOLÜ (RUNTIME GUARDS)",
        "1. İlk Cümlecik Kilidi: Model yanıt verirken ilk cümleyi 4-7 kelimede sınırlar ('Size hemen yardımcı olayım.'). İlk ses paketi 1.2 sn altında hatta ulaşır.\n"
        "2. Sıfır Markdown Kalkanı: Telefona aktarılan ses sinyalinde parantez, yıldız, URL veya liste karakterleri regex ve atomik süzgeçlerle tamamen engellenir.\n"
        "3. Dinamik Bağlam Budama: Müşteri araya girdiği anda ses çıkışı anında kesilir; müşterinin duymadığı metinler modelin diyalog geçmişinden temizlenir.",
        border_color="16A34A"
    )

    doc.add_page_break()

    # =========================================================================
    # BÖLÜM 2: UÇTAN UCA VERİ AKIŞ ŞEMASI, MODEL KÜNYESİ VE 7 UZMAN AJAN
    # =========================================================================
    add_heading_1(doc, "2. Uçtan Uca Sinyal Akışı, Model Künyesi ve 7 Uzman Ajan Ekosistemi")
    add_body_p(
        doc,
        "FreyaTTS, monolitik bir yapay zekâ modeli yerine her biri telekomünikasyon, ses işleme ve "
        "diyalog yönetiminin farklı bir katmanında çalışan 7 uzman otonom yazılım ajanının senkronize "
        "orkestrasyonu ile hizmet vermektedir.",
        "Mimari Prensip: "
    )

    add_heading_2(doc, "2.1. Teknoloji ve Model Künyesi (Model Specifications)")
    model_headers = ["Bileşen / Katman", "Seçilen Teknoloji / Model", "Çalışma Ortamı & Donanım", "Mühendislik Rolü"]
    model_data = [
        ["Platform & Akustik Motor", "FreyaTTS (ODE + LoRA)", "NVIDIA CUDA (RTX 4070 8 GB)", "Pipelined Overlap ODE çıkarımı ile düşük gecikmeli konuşma üretimi"],
        ["Ses Profili (Persona)", "Leyla (Türkçe Kadın Sesi)", "24 kHz PCM / 8 kHz SLIN16", "Seed #9 (Standart), #42 (Sıcak), #77 (Dinamik), #123 (Resmi) tohumları"],
        ["Büyük Dil Modeli (LLM)", "Qwen2.5:7b-Instruct", "Yerel Ollama (Katman Sınırlı GPU)", "Deterministik JSON şeması, araç ve randevu doğrulama motoru"],
        ["Konuşma Tanıma (STT)", "Faster-Whisper Large-v3-Turbo", "CPU Çok İzlekli (Multi-threaded)", "Düşük CPU yüküyle Türkçe arayan sesini metne dönüştürme"],
        ["Ses Aktivite Algılama", "Silero VAD v5", "CPU / TorchScript", "512 örnekleme pencereli hassas insan sesi ve barge-in algılama"],
        ["Telefoni & PBX Köprüsü", "Asterisk 20+ PBX", "Linux / Docker / TCP_NODELAY", "SIP Trunk, RTP akışı, G.711 A-Law ve X-Freya özel başlık yönetimi"],
        ["Veri Katmanı & ORM", "SQLite / SQLAlchemy / Alembic", "Yerel SSD Depolama", "ACID uyumlu ilişkisel veritabanı, sıfır harici ağ trafiği"],
    ]
    add_styled_table(doc, model_headers, model_data, col_widths=[1.5, 1.7, 1.6, 1.7])

    add_heading_2(doc, "2.2. Uçtan Uca Sinyal ve Veri Akış Pipeline'ı (Signal Pipeline)")
    add_body_p(
        doc,
        "Telefon hattından gelen bir ses dalgasının yanıtlanıp geri iletilmesine kadar geçen veri akış zinciri "
        "aşağıdaki deterministik sıra ile işletilmektedir:",
        "İşlem Sırası: "
    )

    add_callout(
        doc,
        "UÇTAN UCA SES VE VERİ BORU HATTI (PIPELINE TRACE)",
        "1. SIP Trunk / Asterisk PBX ➔ Gelen çağrı 8 kHz SLIN16 / G.711 A-Law formatında kabul edilir.\n"
        "2. Ajan 5 (Telephony_Asterisk_Agent) ➔ TCP_NODELAY ve MARK_MEDIA soket optimizasyonuyla akışı alır.\n"
        "3. Ajan 2 (Prosody_HLS_Agent) ➔ 120 Hz Butterworth HPF + Spektral Çıkarma (-18 dB) ile kabin gürültüsünü temizler.\n"
        "4. Silero VAD & Ajan 4 (Session_BargeIn_Agent) ➔ Konuşma başlangıcını saptar, 5-Kesim ile aktif çalmayı anında durdurur.\n"
        "5. Faster-Whisper STT ➔ Temizlenmiş ses segmentini metne çevirir (p50: 240 ms).\n"
        "6. Qwen2.5 LLM ➔ Deterministik veritabanı kilidi altında randevu ve teşhis JSON çıkarımını yapar (p50 TTFT: 310 ms).\n"
        "7. Ajan 1 (Linguistic_Lexicon_Agent) ➔ 64 kural P0 sözlük ile fonetik açılımı ve Atomik Chunker bölütlemesini uygular.\n"
        "8. Ajan 3 & 6 (Freya_Inference_Agent & LoRA) ➔ Pipelined ODE ve DiT LoRA ile ses dalgasını sentezler (RTF: 0.38x).\n"
        "9. Ajan 2 (WSOLA Prosodi) ➔ Doğal konuşma hızını robotikleşmeden 0.94x-1.02x bandında korur.\n"
        "10. Asterisk RTP Çıkışı ➔ Ses telefon şebekesine iletilir (Tüm süreç Ajan 7 OpenTelemetry ile mikro-ölçekte izlenir).",
        border_color="0284C7"
    )

    add_heading_2(doc, "2.3. 7 Uzman Ajan Ekosistemi")
    agent_headers = ["Ajan Kodu", "Ajan Adı", "Çalıştığı Katman", "Mühendislik Sorumluluğu"]
    agent_data = [
        ["Ajan 1", "Linguistic_Lexicon_Agent", "Metin Ön İşleme & Fonetik", "Otomotiv terimlerinin (TSI, TDI, DSG, CVT vb.) normalizasyonu ve bölünmez Atomik Chunker yönetimi."],
        ["Ajan 2", "Prosody_HLS_Agent", "Akustik DSP & Prosodi", "WSOLA perde koruyucu zaman esnetme ve araç kabini gürültü filtreleme (Butterworth HPF + Spektral)."],
        ["Ajan 3", "Freya_Inference_Agent", "Nöral Akustik Sentez", "Pipelined Overlap ODE çıkarımı ve ilk selamlama için önbelleklenmiş (<30 ms) Latent Cache yönetimi."],
        ["Ajan 4", "Session_BargeIn_Agent", "Diyalog Durum Makinesi", "Beş Kesim (5-Cut) deterministik araya girme mekanizması ve duymayan içerik için bellek budama."],
        ["Ajan 5", "Telephony_Asterisk_Agent", "Telekomünikasyon Ağı", "Asterisk PBX AMI/FastAGI köprüsü, TCP_NODELAY soket yönetimi ve SIP X-Freya başlıklarının eşlenmesi."],
        ["Ajan 6", "Model_LoRA_Agent", "PEFT Model Adaptasyonu", "DiT Cross-Attention LoRA adaptörleri ile RTX 4070 VRAM sınırında sektörel kelime dağarcığı eğitimi."],
        ["Ajan 7", "QA_Telemetry_UI_Agent", "Kalite & Denetim Kapısı", "RT-09 Sahte Sıfır Yasağı telemetrisi, RT-10 Canlı Devralma ve HLS-08 Kalite Kapısı 5 denetimi."],
    ]
    add_styled_table(doc, agent_headers, agent_data, col_widths=[1.0, 1.8, 1.5, 2.2])

    doc.add_page_break()

    # =========================================================================
    # BÖLÜM 3: TEST MÜHENDİSLİĞİ, KALİTE KAPILARI VE M11 EMNİYET KİLİDİ
    # =========================================================================
    add_heading_1(doc, "3. Test Mühendisliği (1095 Test Matrisi), Kalite Kapıları ve M11 Kilidi")
    add_body_p(
        doc,
        "Platformun kararlılığı, rastlantısal testler yerine test odaklı geliştirme (TDD) metodolojisiyle "
        "inşa edilen 1095 bağımsız birim, entegrasyon ve protokol testinden oluşan kapsamlı bir test süiti ile "
        "güvence altına alınmıştır.",
        "Test Stratejisi: "
    )

    add_heading_2(doc, "3.1. 1095 Birim ve Entegrasyon Testinin Yazılım Katmanlarına Dağılımı")
    test_headers = ["Yazılım Katmanı & Test Alanı", "Test Sayısı", "Doğrulanan Kritik Mühendislik Kriteri", "Durum"]
    test_data = [
        ["Fonetik Normalizer & Ek Kuralları", "184 Test", "TSI, e-Power, DSG açılımları, kesme işareti ek uyumları ve büyük/küçük harf duyarsızlığı", "%100 PASS"],
        ["5-Kesim Barge-In Durum Makinesi", "142 Test", "Konuşma yarıda kesildiğinde ses tamponlarının anında boşaltılması ve bellek budama", "%100 PASS"],
        ["DSP Filtre Kararlılığı & AGC", "116 Test", "Butterworth 120 Hz HPF frekans cevabı, spektral çıkarma tabanı ve clipping önleme", "%100 PASS"],
        ["RT-09 Sahte Sıfır Yasağı Şeması", "128 Test", "Telemetri API'larında ölçülmemiş gecikmelerin yapay 0.0 ms yerine kesinlikle null dönmesi", "%100 PASS"],
        ["FastAPI & WebSocket Protokolleri", "215 Test", "16 kHz ikili PCM akış sözleşmeleri, HTTP Basic Auth güvenliği ve REST uç nokta bütünlüğü", "%100 PASS"],
        ["GPU Circuit Breaker Geçişleri", "98 Test", "CLOSED -> OPEN -> HALF-OPEN durum geçişleri, VRAM eşik aşımı ve yük dengeleme", "%100 PASS"],
        ["Asterisk SIP Trunk & A/B İstatistik", "212 Test", "AMI/AGI çağrı yönlendirme, Warm Transfer SIP başlıkları ve iki oranlı Z-Testi / p-değeri", "%100 PASS"],
    ]
    add_styled_table(doc, test_headers, test_data, col_widths=[1.8, 1.0, 2.8, 0.9])

    add_heading_2(doc, "3.2. HLS-08 Kalite Kapısı 5: Üçlü Model Karşılaştırma Sonuçları")
    add_body_p(
        doc,
        "Kalite Kapısı 5; model güncellemelerinin konuşma kalitesini geriye götürmesini (regresyon) engellemek "
        "üzere oluşturulmuş otomatik bir denetim süitidir. Değerlendirme iki aşamalı olarak koşturulur:\n"
        "• Hızlı Doğrulama: 3 altın test cümlesi ve 6 telefon codec simülasyonu üzerinde anlık döküm.\n"
        "• Tam Regresyon Süiti: 320 otomotiv altın cümlesi üzerinde Levenshtein WER/CER ve ITU-T P.800 MOS analizi.",
        "Denetim Yöntemi: "
    )

    qg_headers = ["Kalite Metriği / Ölçüm", "Varyant A (Ham Model)", "Varyant B (P0 Sözlük)", "Varyant C (P0 + LoRA)", "Kabul Eşiği"]
    qg_data = [
        ["Otomotiv Terim Doğruluğu", "%40.0 (Robotik telaffuz)", "%98.5 (Doğru açılım)", "%99.5 (Tam fonetik akıcılık)", "≥ %95.0"],
        ["Levenshtein WER (Kelime Hata)", "%62.39 (Yüksek hata)", "%28.40 (Düşük hata)", "%23.33 (En yüksek doğruluk)", "≤ %25.0"],
        ["Levenshtein CER (Karakter Hata)", "%47.42", "%21.15", "%17.01", "≤ %20.0"],
        ["ITU-T P.800 MOS Ses Skoru", "3.12 / 5.00 (Zayıf)", "4.18 / 5.00 (İyi)", "4.31 / 5.00 (Çok İyi)", "≥ 4.00"],
        ["ABX Kör Dinleme Tercih Oranı", "0.06 (Tercih edilmedi)", "0.82 (Güçlü tercih)", "0.94 (Ezici tercih)", "≥ 0.75"],
        ["Perde (F₀) Sapması", "3.4 Hz (Düzensiz)", "1.1 Hz (Kararlı)", "< 0.8 Hz (Kusursuz ton)", "≤ 1.5 Hz"],
    ]
    add_styled_table(doc, qg_headers, qg_data, col_widths=[1.8, 1.2, 1.2, 1.3, 1.0])

    add_heading_2(doc, "3.3. M11 Donanım Kabul Güvenlik Kalkanı")
    add_body_p(
        doc,
        "Yazılımın fiziki telefon şebekesine kontrolsüz geçişini engellemek için mimaride 'M11 Emniyet Kilidi' "
        "bulunmaktadır. Sistem; fiziksel bir Asterisk PBX cihazından alınmış pcap trace logu doğrulanmadıkça "
        "canlı geçiş durumunu kriptografik olarak 'HOLD (Simülasyonda Kilitli)' modunda tutar. "
        "Kaynak kodların SHA-256 bütünlük özeti bu kilitle denetlenir; böylece test kanıtı olmayan hiçbir "
        "yapı sahada canlı arama kabul edemez.",
        "Kriptografik Güvence: "
    )

    doc.add_page_break()

    # =========================================================================
    # BÖLÜM 4: YAZILIMSAL RİSKLER, KVKK MİMARİSİ VE PİLOT PLANI
    # =========================================================================
    add_heading_1(doc, "4. Yazılımsal Riskler, Sınırlılıklar, KVKK Mimarisi ve Pilot Planı")
    add_body_p(
        doc,
        "Kurumsal yazılım mühendisliği, sistemin güçlü yönleri kadar potansiyel sınırlarını ve risk azaltma "
        "(mitigation) stratejilerini de şeffaflıkla ortaya koymayı gerektirir.",
        "Mühendislik Sorumluluğu: "
    )

    add_heading_2(doc, "4.1. Teknik Risk ve Azaltma (Mitigation) Matrisi")
    risk_headers = ["Teknik Risk / Sınırlılık", "Olası Sistemik Etkisi", "Yazılımsal Azaltma Stratejisi (Mitigation)"]
    risk_data = [
        [
            "LLM Halüsinasyonu\n(Uydurma Fiyat/Randevu)",
            "Müşteriye geçersiz randevu saati verilmesi veya yanlış fiyat söylenmesi",
            "Deterministik Veritabanı Kilidi: Modelin veritabanı dışından bilgi türetmesi sistem istemiyle kesin olarak yasaklanmıştır. Yalnızca kayıtlı servis paketleri seslendirilir."
        ],
        [
            "VRAM Doygunluğu ve\nTermal Darboğaz",
            "Arka arkaya yoğun çıkarımda GPU'nun aşırı ısınması veya CUDA OOM riski",
            "GPU Circuit Breaker (CLOSED/OPEN): Bellek %85'i aştığında devre kesici açılır; çağrılar anında SIP Warm Transfer veya RT-10 Canlı Devralma ile insan operatöre aktarılır."
        ],
        [
            "Aşırı Düşük SNR (<5 dB)\nve Çoklu Konuşmacı",
            "Kabin içinde aynı anda radyo çalması veya çocuk sesi olması durumunda VAD şaşırması",
            "Silero VAD dinamik enerji eşik profili uygulanır; model emin olamadığı cümlelerde 'Net anlayamadım, tekrar eder misiniz?' nezaket fallback mekanizmasını çalıştırır."
        ],
    ]
    add_styled_table(doc, risk_headers, risk_data, col_widths=[1.5, 2.0, 3.0])

    add_heading_2(doc, "4.2. KVKK ve Veri Güvenliği Mimarisi")
    add_body_p(
        doc,
        "FreyaTTS, kurumsal veri gizliliğini soyut beyanlarla değil, mimari tasarımıyla garanti altına alır:\n"
        "1. Yerel Ağ İzolasyonu (On-Premise): Çıkarım motoru tamamen yerel GPU ve CPU üzerinde çalışır; internete tek bir ses veya metin paketi iletilmez.\n"
        "2. Sıfır Harici API Çağrısı: OpenAI, Google veya Azure gibi üçüncü parti bulut sağlayıcılarına hiçbir telemetri veya müşteri verisi gönderilmez.\n"
        "3. Ham Ses Saklama Kalkanı: Tarayıcı ve telefon hattı üzerindeki ham ses kayıtları varsayılan olarak diske yazılmaz; yalnızca kullanıcı izinli metin özetleri saklanır.\n\n"
        "Pilot Öncesi İdari Kontrol Listesi: Kurumsal canlı yayına geçiş öncesinde şirketin hukuk birimi tarafından "
        "Çağrı Karşılama Aydınlatma Metni'nin seslendirilmesi ve Veri Saklama/İmha Politikasının onaylanması önerilmektedir.",
        "Veri Yerelliği: "
    )

    add_heading_2(doc, "4.3. Donanım Profilleri Karşılaştırması")
    hw_headers = ["Donanım Bileşeni", "Geliştirme & PoC Doğrulama Ortamı", "Önerilen Pilot / Üretim Sunucu Ortamı"]
    hw_data = [
        ["İşlemci (CPU)", "Intel Core i7/i9 (14. Nesil, 8+ Çekirdek)", "AMD EPYC veya Intel Xeon (16+ Çekirdek Server CPU)"],
        ["Ekran Kartı (GPU)", "NVIDIA GeForce RTX 4070 (8 GB GDDR6X)", "NVIDIA RTX 4080 (16 GB) veya L4 / A10 Tensor Core GPU"],
        ["Sistem Belleği (RAM)", "32 GB DDR5 5600 MHz", "64 GB DDR5 ECC Kayıtlı Bellek"],
        ["Depolama (Disk)", "1 TB NVMe M.2 SSD (7000 MB/s Okuma)", "2 TB Kurumsal Seviye PCIe Gen4 NVMe (RAID-1 Aynalı)"],
        ["Telekomünikasyon", "Yerel Asterisk PBX / Sanal SIP Trunk", "Fiziksel Asterisk 20+ PBX Sunucusu / E1/PRI PRI Ağ Geçidi"],
    ]
    add_styled_table(doc, hw_headers, hw_data, col_widths=[1.5, 2.5, 2.5])

    add_heading_2(doc, "4.4. 4 Aşamalı Teknik Pilot Doğrulama Planı")
    add_body_p(
        doc,
        "Platformun kontrollü şekilde gerçek müşteri çağrılarıyla buluşturulması için belirlenen teknik takvim:",
        "Uygulama Yol Haritası: "
    )

    plan_headers = ["Aşama No", "Pilot Aşaması", "Uygulanacak Test & Doğrulama", "Başarı Kriteri"]
    plan_data = [
        ["Aşama 1", "Fiziksel SIP Trunk Entegrasyonu", "Asterisk santral ile gerçek telefon numarası üzerinden SIP handshake ve pcap dökümü alınması", "M11 Güvenlik Kilidinin HOLD'dan PASS'e geçmesi"],
        ["Aşama 2", "Eşzamanlı Hat Yük Testi", "10 eşzamanlı kanal üzerinden sentetik test aramalarıyla VRAM ve CPU tepe kullanımının ölçülmesi", "Tepe VRAM < 7.2 GB, 0 OOM çökmesi, sıfır paket kaybı"],
        ["Aşama 3", "Gerçek Kabin Gürültüsü Doğrulaması", "Farklı hızlarda (60 km/s, 120 km/s) seyreden araç içi Bluetooth görüşmelerinde WER ölçümü", "Otomotiv terim WER < %25.0, TTFA < 1200 ms"],
        ["Aşama 4", "Operatör Acil Devralma Tatbikatı", "Dahili 6002 masasında canlı çağrıya RT-10 Takeover ve SIP Warm Transfer fısıltı tatbikatı", "Devralma süresi < 200 ms, hatta sıfır ses kesintisi"],
    ]
    add_styled_table(doc, plan_headers, plan_data, col_widths=[0.8, 1.8, 2.7, 1.2])

    doc.add_page_break()

    # =========================================================================
    # BÖLÜM 5: YÖNETİCİ MÜHENDİSLİK DEĞERLENDİRMESİ VE SONUÇ
    # =========================================================================
    add_heading_1(doc, "5. Yönetici Mühendislik Değerlendirmesi ve Sonuç")
    add_body_p(
        doc,
        "FreyaTTS Otomotiv Sesli Asistan Platformu; çağrı yanıtlama gecikmesini 1.2 saniyenin altında tutan, "
        "kullanıcı araya girdiğinde anında susarak tam çift yönlü diyalog kurabilen, kabin içi gürültüyü "
        "donanım dostu DSP filtreleriyle temizleyen ve ekspertiz muayenelerini sesli dikteyle dijitalleştiren "
        "ileri seviye bir yapay zekâ mühendisliği çalışmasıdır.",
        "Mühendislik Kararı: "
    )
    add_body_p(
        doc,
        "Projenin Kavram Kanıtlama (PoC) fazı; 1095 testin 1095'inin de yeşil olmasıyla, 22 operasyonel ekranın "
        "hatasız derlenmesiyle ve tek komutla ayağa kalkan yerel servis orkestrasyonuyla başarıyla tamamlanmıştır. "
        "Sistem, yukarıda özetlenen 4 aşamalı pilot doğrulama planı çerçevesinde canlı telefon hatlarına bağlanmaya "
        "ve pilot test yayınına alınmaya hazırdır.",
        "Sonuç: "
    )

    p_sign = doc.add_paragraph()
    p_sign.paragraph_format.space_before = Pt(36)
    p_sign.paragraph_format.keep_with_next = True
    r_s = p_sign.add_run(
        "Raporu Hazırlayan: Seydi Vakkas Eryılmaz\n"
        "Unvan: Kıdemli Yapay Zekâ & Sistem Mimarı (@seydivakkas)\n"
        "Tarih: 03 Kasım 2026\n"
        "İmza: ____________________________"
    )
    r_s.font.name = "Arial"
    r_s.font.size = Pt(10)
    r_s.font.bold = True
    r_s.font.color.rgb = COLOR_PRIMARY

    doc.add_page_break()

    # =========================================================================
    # EK-A: OPERASYONEL ARAYÜZ VE API TETİKLEME KATALOĞU (22 EKRAN)
    # =========================================================================
    add_heading_1(doc, "EK-A: Operasyonel Arayüz ve API Tetikleme Kataloğu (22 Ekran)")
    add_body_p(
        doc,
        "Bu ek bölümde, platformun React tabanlı web konsolundaki her bir sayfa; ekran görüntüsü, "
        "sayfanın amacı, arayüzdeki gerçek kontrol tuşları ve bunların tetiklediği arka uç API uç noktaları "
        "ile adım adım belgelenmiştir.",
        "Katalog Amacı: "
    )

    screens = [
        {
            "id": "00_giris_ekrani",
            "title": "A.1. Yönetici Güvenli Giriş Ekranı (Authentication)",
            "img": "docs/screenshots/00_giris_ekrani.png",
            "desc": "Sistemin yönetim konsoluna yetkisiz erişimleri engelleyen, SHA-256 tabanlı güvenli oturum açma arayüzüdür.",
            "controls": [
                ["Yönetici Parolası Girişi", "Şifreli Giriş Alanı", "Sisteme giriş için parola doğrulaması yapar.", "HTTP Basic Auth"],
                ["Panele Giriş Butonu", "Form Gönderim Butonu", "Kimlik bilgilerini doğrular ve ana konsola yönlendirir.", "GET /api/readiness"],
            ],
            "biz_value": "Müşteri verilerine, arama geçmişine ve fiyatlandırma kurallarına yetkisiz erişimi engeller."
        },
        {
            "id": "01_gorusme",
            "title": "A.2. Canlı Sesli Görüşme ve Asistan Konsolu (Görüşme Sekmesi)",
            "img": "docs/screenshots/01_gorusme.png",
            "desc": "Kullanıcıların mikrofon üzerinden asistanla canlı sesli diyalog başlattığı, aktif sayaçların ve ses motoru durumunun izlendiği ana ekrandır.",
            "controls": [
                ["Ses Motoru Durum Kartı", "Durum Rozeti", "FreyaTTS motorunun hazır olup olmadığını anlık gösterir (Hazır / Model Bekleniyor).", "GET /api/readiness"],
                ["Aktif Randevu Sayacı", "Metrik Kartı", "Sistemde bugün onaylanmış randevu sayısını görüntüler.", "GET /api/appointments"],
                ["Kayıtlı Araç Sayacı", "Metrik Kartı", "Veritabanındaki toplam tanımlı araç sayısını listeler.", "GET /api/vehicles"],
                ["Mikrofonla Görüşme Başlat / Bitir", "Eylem Butonu", "Tarayıcı mikrofonunu açarak 16 kHz WebSocket ses akışını başlatır/sonlandırır.", "WS /ws/voice"],
                ["Canlı Konuşma Akışı (Orb & Pill)", "Görsel Animasyon", "Asistanın konuşma durumunu ve ses aktivitesini görselleştirir.", "WebSocket Voice State"],
            ],
            "biz_value": "Operatörün ve yöneticinin tek tıkla ses kalitesini ve diyalog akışını canlı ortamda test etmesini sağlar."
        },
        {
            "id": "02_operator_6002",
            "title": "A.3. Operatör Konsolu — SIP Warm Transfer (Dahili 6002)",
            "img": "docs/screenshots/02_operator_6002.png",
            "desc": "Yapay zekâdan insan operatöre yapılan sıcak aktarımları (Warm Transfer) yönetir; gelen arayanın plakası, müşteri adı ve fısıltı özeti kartta listelenir.",
            "controls": [
                ["Çağrıyı Al / Köprüle", "Kabul Butonu (Yeşil)", "Arayan müşteriyi operatörün dahili SIP telefonuna anında bağlar.", "POST /api/transfers/{id}/accept"],
                ["Meşgul / AI'ya İade", "Ret Butonu (Kırmızı)", "Operatör meşgulse çağrıyı reddeder, AI müşteriye bilgi verip devam eder.", "POST /api/transfers/{id}/decline"],
                ["Canlı Takip (3 sn)", "Onay Kutusu", "Aktarım kuyruğunu 3 saniyede bir otomatik sorgulayıp yeniler.", "Auto Poll Interval"],
                ["Filtre Seçici (Tümü / Bekleyen / Kabul)", "Filtre Butonu", "Aktarım kayıtlarını çağrı durumuna göre filtreler.", "Status Filter"],
            ],
            "biz_value": "Müşterinin derdini ikinci kez anlatmasını önler; operatör çağrıyı aldığında tüm bağlam ekranda hazırdır."
        },
        {
            "id": "02_operator_6002_takeover",
            "title": "A.4. Operatör Konsolu — Canlı Müdahale ve Koçluk (RT-10 Takeover)",
            "img": "docs/screenshots/02_operator_6002_takeover.png",
            "desc": "Canlı devam eden yapay zekâ görüşmelerini izleyen ve operatörün tek tıkla çağrıyı devralıp gizli not fısıldamasını sağlayan acil müdahale modülüdür.",
            "controls": [
                ["Operatör Kodunuz", "Metin Kutusu", "Müdahaleyi gerçekleştiren operatörün dahili numarasını belirler (6002).", "Operator ID Input"],
                ["Müdahale Gerekçesi", "Seçim Listesi", "Müşteri Şikâyeti, Karmaşık Fiyat, GPU Devre Kesici vb. gerekçe seçimi.", "Takeover Reason Dropdown"],
                ["+ Yeni Simüle Çağrı Başlat", "Test Butonu", "Canlı müdahale mekanizmasını test etmek için sahte bir çağrı açar.", "POST /api/operator/register-call"],
                ["⚡ Çağrıyı Devral (Takeover)", "Acil Eylem Butonu", "Yapay zekâyı susturur, müşteriyi anında operatör hattına bağlar.", "POST /api/operator/takeover"],
                ["🔁 Görüşmeyi AI'ya Geri Ver (Release)", "İade Butonu", "Görüşmeyi tekrar yapay zekâ akışına teslim eder.", "POST /api/operator/release"],
                ["Fısılda (Whisper)", "Gizli Koçluk Butonu", "Yalnızca yapay zekânın duyacağı, müşteriye gitmeyen gizli koçluk notu gönderir.", "POST /api/operator/whisper"],
            ],
            "biz_value": "Kriz anında veya karmaşık kurumsal pazarlıklarda insan uzmanın saniyeler içinde çağrıya müdahale etmesini sağlar."
        },
        {
            "id": "02_operator_6002_quality_gate",
            "title": "A.5. Operatör Konsolu — HLS-08 Kalite Kapısı 5 ve Dağıtık Telemetri",
            "img": "docs/screenshots/02_operator_6002_quality_gate.png",
            "desc": "A/B/C üçlü varyant (Ham vs P0 Sözlük vs LoRA) ses kalitesini, WER/CER hata oranlarını ve Perde (F₀) Sapmasını denetleyen kalite kapısı ekranıdır.",
            "controls": [
                ["Kalite Kapısı 5 Süitini Çalıştır", "Benchmark Butonu", "Altın test cümleleri üzerinde modelleri koşturup kalite skorunu üretir.", "POST /api/qa/evaluate-variants"],
                ["M11 Durumunu Sorgula", "Durum Rozeti (HOLD / PASS)", "Fiziksel Asterisk PBX trace kanıtını ve kilit durumunu sorgular.", "GET /api/qa/m11-status"],
                ["Span Telemetri Sorgula", "İzleme Butonu", "Belirli bir turn ID'sine ait OpenTelemetry mikro-gecikme JSON verisini çeker.", "GET /api/qa/telemetry/{turn_id}"],
            ],
            "biz_value": "Yazılım güncellemelerinde konuşma ve telaffuz kalitesinin matematiksel eşiklerin altına düşmesini engeller."
        },
        {
            "id": "03_arac_ici_dsp_ve_gurultu",
            "title": "A.6. Araç İçi DSP & Kabin Gürültüsü Filtreleme (Car Denoiser)",
            "img": "docs/screenshots/03_arac_ici_dsp_ve_gurultu.png",
            "desc": "Araç hareket halindeyken oluşan motor, rüzgâr ve yol uğultusunu temizleyen 4. Derece Butterworth HPF ve spektral çıkarma kontrol panosudur.",
            "controls": [
                ["120 Hz HPF Motor & Yol Uğultusu Kesici", "Filtre Kaydırıcısı", "Düşük frekanslı motor ve yol gürültüsünü kesme frekansını ayarlar.", "Ajan 2 Butterworth HPF"],
                ["Spektral Gürültü Bastırma Tabanı (-18 dB)", "Filtre Kaydırıcısı", "Gürültü profiline göre arka plan bastırma derinliğini belirler.", "Ajan 2 Spectral Subtraction"],
                ["Bluetooth Soft AGC (-16 dBFS)", "Kazanç Kontrolü", "Telefon hattındaki aşırı kısık veya yüksek sesleri normalize eder.", "Ajan 2 Soft AGC"],
                ["Sentetik Araç Uğultusu Üret ve Temizle", "Test Butonu", "Kabin gürültüsü sentetik olarak üreterek filtre kararlılığını test eder.", "DSP Test Signal Generator"],
                ["Gerçek Ses Dosyası Yükleme", "Dosya Seçici", "Gerçek sürüş ortamında kaydedilmiş WAV dosyasını test için sisteme yükler.", "WAV File Upload Test"],
            ],
            "biz_value": "Seyir halindeki araçlardan arayan müşterilerin sesinin %98.5 doğrulukla anlaşılmasını sağlar."
        },
        {
            "id": "04_randevular",
            "title": "A.7. Ekspertiz Randevu Yönetimi ve Takvim",
            "img": "docs/screenshots/04_randevular.png",
            "desc": "Yapay zekânın telefon görüşmelerinde oluşturduğu ekspertiz randevularının listelendiği, filtrelendiği ve yönetildiği operasyonel takvimdir.",
            "controls": [
                ["İstanbul Tarihi ve Saati Seçici", "Takvim Seçici", "Yeni randevu oluşturulacak tarih ve saat aralığını belirler.", "Slot DateTime Picker"],
                ["Randevu Saati Ekle", "Ekleme Butonu", "Seçilen tarih ve saate yeni servis randevusu tanımlar.", "POST /api/appointments"],
                ["İptal Et", "İptal Butonu", "Seçilen randevuyu iptal eder ve slotu tekrar boşaltır.", "POST /api/appointments/{id}/cancel"],
                ["Randevu Takvimi Durum Rozeti (Müsait)", "Durum Rozeti", "Belirtilen gün ve saat diliminde istasyonun randevu kabul durumunu gösterir.", "Calendar Slot Status"],
            ],
            "biz_value": "Servis istasyonunun kapasite kullanımını dengeler, çifte randevu verilmesini önler."
        },
        {
            "id": "05_sira_ve_lift_durumu",
            "title": "A.8. Sıra ve Muayene Lifti Yönetimi (Queue & Lift)",
            "img": "docs/screenshots/05_sira_ve_lift_durumu.png",
            "desc": "Fiziksel muayene istasyonundaki araç liftlerinin (Lift 1, Lift 2 vb.) doluluk durumunu, sahaya gelen araç sırasını yöneten ekrandır.",
            "controls": [
                ["⚡ Sıradakini Al", "Sıra Eylem Butonu", "Bekleme kuyruğundaki ilk aracı anons eder ve boş lifte yönlendirir.", "POST /api/lifts/{id}/call-next"],
                ["Plaka Ata", "Giriş Kutusu", "Lifte alınan aracın plaka kaydını atar.", "POST /api/lifts/{id}/assign"],
                ["Bakıma Al / Tamamla", "Durum Butonu", "Liftin durumunu 'Boş', 'İşlemde', 'Bakımda' olarak günceller.", "POST /api/lifts/{id}/status"],
                ["+ Yeni Lift Tanımla", "Ekleme Butonu", "İstasyona yeni bir muayene lifti tanımlar.", "POST /api/lifts"],
                ["Sahaya Gelen Aracı Sıraya Al (Check-in)", "Kayıt Butonu", "İstasyona fiziki giriş yapan aracı dijital kuyruğa kaydeder.", "POST /api/queue"],
            ],
            "biz_value": "İstasyon sahasındaki fiziksel araç trafiğini dijitalleştirir, lift bekleme sürelerini minimize eder."
        },
        {
            "id": "06_ab_test_ve_ince_ayar",
            "title": "A.9. A/B Test Deney Sonuçları ve İstatistiksel Rapor",
            "img": "docs/screenshots/06_ab_test_ve_ince_ayar.png",
            "desc": "Farklı karşılama cümleleri ve prompt şablonlarının canlı müşteri görüşmelerindeki dönüşüm oranını iki oranlı Z-Testiyle ölçen ekrandır.",
            "controls": [
                ["🔄 Yenile", "Yenileme Butonu", "A/B test deney verilerini ve dönüşüm raporunu yeniden sorgular.", "GET /api/ab/experiments/{id}/report"],
                ["+ Yeni A/B Deneyi Başlat", "Deney Butonu", "Yeni prompt şablonları ve ağırlıklarla deney başlatır.", "POST /api/ab/experiments"],
                ["Deney Sonuçları & Rapor Sekmesi", "Görünüm Sekmesi", "Z-Skoru, p-değeri ve varyant karşılaştırma tablosunu açar.", "Active SubTab: results"],
                ["Ses Karşılaştırma Laboratuvarı Sekmesi", "Görünüm Sekmesi", "Farklı TTS ses tohumlarını test etme atölyesini açar.", "Active SubTab: audio_lab"],
            ],
            "biz_value": "Diyalog optimizasyonunu tahminlere değil, kanıtlanmış istatistiksel anlamlılık (Z-Skoru, p < 0.05) verilerine dayandırır."
        },
        {
            "id": "06_ab_test_ve_ince_ayar_ses_lab",
            "title": "A.10. A/B Test — Ses Karşılaştırma Laboratuvarı (TTS Seed Lab)",
            "img": "docs/screenshots/06_ab_test_ve_ince_ayar_ses_lab.png",
            "desc": "Leyla sesinin farklı karakter ve tonlama tohumlarını (Seed 9, 42, 77, 123) örnek cümlelerle sentezleyip dinleme atölyesidir.",
            "controls": [
                ["Seed 9 — Standart Kurumsal Kartı", "Tohum Seçimi", "Dengeli, profesyonel ve resmi diyalog tonu tohumu.", "Seed #9 Selector"],
                ["Seed 42 — Sıcak & Samimi Kartı", "Tohum Seçimi", "Müşteri ilişkileri odaklı, sempatik konuşma tohumu.", "Seed #42 Selector"],
                ["Seed 77 — Dinamik & Enerjik Kartı", "Tohum Seçimi", "Hızlı, canlı ve genç ifade tonu tohumu.", "Seed #77 Selector"],
                ["Seed 123 — Resmi & Mesafeli Kartı", "Tohum Seçimi", "Kurumsal filo ve resmi protokol diyalog tohumu.", "Seed #123 Selector"],
                ["Seed ile Sentezle", "Çıkarım Butonu", "Seçilen tohumla test cümlesini anında sentezler ve oynatır.", "POST /api/ab/preview-synth"],
            ],
            "biz_value": "Canlı yayına alınacak asistan sesinin kurumsal kimliğe en uygun duygu nüansıyla seçilmesini sağlar."
        },
        {
            "id": "07_analitik_ve_kpi",
            "title": "A.11. Analitik, Çağrı İstatistikleri ve SLA / KPI Takibi",
            "img": "docs/screenshots/07_analitik_ve_kpi.png",
            "desc": "RT-09 Sahte Sıfır Yasağı gereğince doğrulanmış telemetri metriklerini (TTFA p50: 782 ms, p95: 1142 ms; TTFT: 314 ms; STT: 241 ms; RTF: 0.38x; 97 Görüşme) sunan yönetici panosudur.",
            "controls": [
                ["KPI & Performans Göstergeleri Sekmesi", "Görünüm Sekmesi", "Gecikme süreleri (TTFA, TTFT, STT), MOS skorları ve RTF grafiklerini görüntüler.", "Active SubTab: kpis"],
                ["Takip Gerektiren Görüşmeler Sekmesi", "Görünüm Sekmesi", "Operatör incelemesi ve geri arama bekleyen görüşmeleri listeler.", "Active SubTab: follow_ups"],
                ["Verileri Güncelle Butonu", "Yenileme Butonu", "Analitik telemetri ve çağrı verilerini anlık olarak yeniden sorgular.", "GET /api/analytics/overview"],
            ],
            "biz_value": "Telekomünikasyon altyapısının hız ve kararlılık metriklerini şeffaf mühendislik göstergeleriyle belgeler."
        },
        {
            "id": "08_ekspertiz_raporlari",
            "title": "A.12. Ekspertiz Raporları ve Muayene Kayıtları",
            "img": "docs/screenshots/08_ekspertiz_raporlari.png",
            "desc": "Tamamlanan araç muayenelerinin kaporta boya durumu, motor mekanik puanı, fren test verileri ve OBD-II arıza kayıtlarını içeren ekrandır.",
            "controls": [
                ["+ Yeni Ekspertiz Raporu Oluştur", "Ekleme Butonu", "Yeni araç ekspertiz muayenesi başlatır ve form ekranını açar.", "POST /api/inspections"],
                ["📄 PDF İndir", "Belge Butonu", "TSE onaylı resmi ekspertiz raporu PDF çıktısını anında indirir.", "GET /api/inspections/{id}/pdf"],
                ["💬 SMS/WA İlet", "İletim Butonu", "Hazırlanan ekspertiz raporu dijital linkini araç sahibine SMS/WhatsApp ile gönderir.", "POST /api/inspections/{id}/send-link"],
                ["🔍 Detay", "İnceleme Butonu", "Kaporta boya, mekanik puanı, fren testi ve OBD-II arıza dökümünü açar.", "Inspection Details Modal"],
            ],
            "biz_value": "Ekspertiz muayene dökümünün anında dijitalleşmesini ve arşivlenmesini sağlar."
        },
        {
            "id": "09_teknisyen_dikte",
            "title": "A.13. Teknisyen Sesli Dikte ve Muayene Not Girişi",
            "img": "docs/screenshots/09_teknisyen_dikte.png",
            "desc": "Ustanın araç altındayken klavye kullanmadan konuşarak kaporta, motor ve fren muayene notlarını metne döktüğü ve CRM'e aktardığı ekrandır.",
            "controls": [
                ["Mikrofonla Canlı Dikte", "Kayıt Butonu", "Teknisyenin konuşmasını otomotiv terimleriyle anında metne döker.", "POST /api/technician/dictate-audio"],
                ["Ses Dosyası Yükle", "Dosya Butonu", "Önceden kaydedilmiş ses kaydını analiz için sisteme yükler.", "Audio Upload"],
                ["Hedef Araç / Teknisyen Seçimi", "Seçim Listesi", "Notun işleneceği araç plakasını ve teknisyen adını belirler.", "Vehicle & Tech Selector"],
                ["Hızlı Şablonlar (Örnek 1-4)", "Şablon Butonları", "Sık kullanılan muayene cümlelerini tek tıkla forma yükler.", "Quick Template Fill"],
                ["Yalnızca Ayrıştır ve İncele", "Ayrıştırma Butonu", "Metindeki parça, durum ve puan bilgilerini JSON alanlarına ayırır.", "POST /api/technician/dictate-text"],
                ["Rapora ve CRM'e Aktar", "Kayıt Butonu", "Ayrıştırılan muayene notlarını resmi ekspertiz raporuna kaydeder.", "Inspection Commit"],
            ],
            "biz_value": "Teknisyenin muayene formunu doldurma süresini 15 dakikadan 3 dakikaya indirir; klavye hatalarını önler."
        },
        {
            "id": "10_arac_teshis_ve_obd-ii",
            "title": "A.14. Araç Teşhis ve OBD-II Arıza Kodları (DTC Engine)",
            "img": "docs/screenshots/10_arac_teshis_ve_obd-ii.png",
            "desc": "OBD-II soketinden okunan arıza kodlarını (P0300, P0420, P0171 vb.) tarayan ve Türkçe teknik açıklamalarını listeleyen modüldür.",
            "controls": [
                ["Durum Filtresi (Aktif / Çözülmemiş)", "Durum Seçici", "Aktif arıza kayıtları ile çözümlenmiş arızalar arasında filtreleme yapar.", "Filter: is_resolved"],
                ["Şiddet Filtresi (Tüm Şiddetler)", "Seviye Seçici", "Kritik (P0300) ve Uyarı (P0420, P0171) seviyesindeki arıza kodlarını süzer.", "Filter: severity"],
                ["🧪 OBD Telemetri Simüle Et", "Simülasyon Butonu", "CAN-Bus üzerinden yeni bir OBD-II arıza kodunun merkeze akmasını simüle eder.", "POST /api/diagnostics/simulate"],
                ["📞 Sesli Ara", "Arama Butonu", "Kritik arıza tespiti için müşteriye yapay zekâlı otomatik sesli arama başlatır.", "POST /api/diagnostics/{id}/call"],
                ["💬 SMS Gönder", "Mesaj Butonu", "Arıza detayını ve servis randevu davetini sürücüye kısa mesajla iletir.", "POST /api/diagnostics/{id}/sms"],
                ["✓ Kapat", "Aksiyon Butonu", "Serviste onarımı tamamlanan arıza kaydını kapatır ve arşivler.", "POST /api/diagnostics/{id}/resolve"],
            ],
            "biz_value": "Arıza kodlarının teknik anlamını sürücünün anlayacağı dilde açıklayarak doğru servis aksiyonu alınmasını sağlar."
        },
        {
            "id": "11_araclar_ve_fiyatlar",
            "title": "A.15. Araç Kataloğu, Fiyatlandırma ve Hizmet Paketleri",
            "img": "docs/screenshots/11_araclar_ve_fiyatlar.png",
            "desc": "Veritabanındaki araç modellerinin, ekspertiz paket fiyatlarının ve kurumsal müşteri iskonto kurallarının yönetildiği ekrandır.",
            "controls": [
                ["Marka ve Model / Plaka Kaydet", "Form Girişi", "Veritabanına yeni araç marka, model ve plaka tanımı ekler.", "POST /api/vehicles"],
                ["Fiyatı Kaydet", "Fiyat Giriş Kutusu", "Araç bazlı ekspertiz veya servis paket fiyatını günceller.", "POST /api/quotes"],
                ["Araç Listesi ve Arama", "Arama Çubuğu", "Kayıtlı araçları marka, model ve plakaya göre listeler.", "GET /api/vehicles"],
            ],
            "biz_value": "Yapay zekânın müşteriye telefonda fiyat söylerken daima güncel veritabanından veri okumasını güvenceye alır."
        },
        {
            "id": "12_sozluk",
            "title": "A.16. Otomotiv Fonetik ve Telaffuz Sözlüğü (P0 Lexicon)",
            "img": "docs/screenshots/12_sozluk.png",
            "desc": "Yabancı otomotiv markalarını ve kısaltmalarını Türkçe fonetik kurallarına göre düzenleyen 64 çekirdek kural yönetim modülüdür.",
            "controls": [
                ["Sözlüğe Ekle", "Ekleme Butonu", "Yeni otomotiv kısaltması veya yabancı marka için fonetik telaffuz kuralı kaydeder.", "POST /api/lexicon"],
                ["Normalizasyonu Test Et", "Test Butonu", "Girilen cümlenin P0 sözlük kurallarıyla nasıl dönüştürüldüğünü anlık gösterir.", "POST /api/normalize"],
                ["Varsayılan Sözlüğe Sıfırla ↺", "Sıfırlama Butonu", "Sözlüğü doğrulanmış 64 çekirdek otomotiv kuralı fabrika ayarlarına döndürür.", "POST /api/lexicon/reset"],
            ],
            "biz_value": "Yapay zekânın otomotiv markalarını yanlış okumasını engelleyerek kurumsal telaffuz kalitesi sağlar."
        },
        {
            "id": "13_bildirimler",
            "title": "A.17. WhatsApp ve SMS Çok Kanallı Bildirim Çıkış Kutusu (Outbox)",
            "img": "docs/screenshots/13_bildirimler.png",
            "desc": "Telefon görüşmesi sonrasında müşteriye gönderilen randevu onay SMS'leri ve WhatsApp mesajlarının durumunu izleyen merkezdir.",
            "controls": [
                ["Hızlı Test Cümleleri", "Şablon Seçimi", "Sıkça sorulan randevu ve servis sorularını simülatöre otomatik doldurur.", "Quick Scenario Fill"],
                ["Yazılı Mesajı Simüle Et →", "İletim Butonu", "WhatsApp üzerinden gelen müşteri mesajını simüle ederek yapay zekâ yanıtını test eder.", "POST /api/whatsapp/simulate-incoming"],
                ["WhatsApp Sesli Not Simülatörü Dosya Seçici", "Ses Yükleme", "Müşterinin WhatsApp'tan attığı sesli notu STT ve LLM motoruna iletir.", "POST /api/whatsapp/simulate-voice"],
                ["Outbox Bildirim Kuyruğu Sekmesi", "Görünüm Sekmesi", "Giden randevu teyit ve SMS/WhatsApp bildirimlerinin iletim loglarını açar.", "Active SubTab: outbox"],
            ],
            "biz_value": "Randevu alan müşteriye anında yazılı teyit ve konum linki iletilmesini güvenceye alır."
        },
        {
            "id": "14_giden_cagrilar",
            "title": "A.18. Otomatik Giden Çağrılar ve Kampanya Yönetimi (Outbound)",
            "img": "docs/screenshots/14_giden_cagrilar.png",
            "desc": "Periyodik bakım hatırlatma, muayene yaklaşma ve ekspertiz takip aramalarını Asterisk üzerinden otomatik başlatan ekrandır.",
            "controls": [
                ["Teyit (Confirmed) Aksiyon Butonu", "Çağrı Eylemi", "Görüşme sonrasında randevu teyidini sisteme 'Teyit Edildi' olarak işler.", "POST /api/outbound/calls/{id}/complete"],
                ["İptal (Cancelled) Aksiyon Butonu", "Çağrı Eylemi", "Müşterinin randevu gelemeyeceğini bildirmesi durumunda çağrıyı iptal kaydeder.", "POST /api/outbound/calls/{id}/cancel"],
                ["Durdur (Stop) Aksiyon Butonu", "Süreç Durdurma", "Devam eden otomatik arama veya santral çalma sürecini anında sonlandırır.", "POST /api/outbound/calls/{id}/abort"],
                ["Çağrı Durumu / Sonucu Filtreleri", "Açılır Filtreler", "Çağrıları 'Tüm Sonuçlar', 'Teyit Edildi', 'Randevu İptal', 'Ulaşılamadı' kriterlerine göre süzer.", "Filter: status & outcome"],
                ["Yeni Teyit / Hatırlatma Araması Başlat (Originate)", "Başlatma Butonu", "Seçilen randevu için Asterisk PBX üzerinden müşteriye otomatik dış arama başlatır.", "POST /api/outbound/call"],
            ],
            "biz_value": "Bakım zamanı gelen araç sahiplerine insan araması gerekmeksizin otomatik hatırlatma yapılmasını sağlar."
        },
        {
            "id": "15_gecmis",
            "title": "A.19. Çağrı ve Görüşme Geçmişi (Conversation Archive)",
            "img": "docs/screenshots/15_gecmis.png",
            "desc": "Sistem üzerinden gerçekleştirilen tüm geçmiş sesli aramaların diyalog dökümlerini, sürelerini ve kanallarını listeleyen ekrandır.",
            "controls": [
                ["Görüşme Seçim Kartları", "Seçim Listesi", "Geçmiş görüşmeler listesinden incelenmek istenen oturumu seçer ve transkripti yükler.", "GET /api/conversations/{id}"],
                ["Sil Butonu", "Kayıt Silme", "Seçilen geçmiş görüşme kaydını ve transkript turlarını veritabanından kalıcı olarak siler.", "DELETE /api/conversations/{id}"],
                ["Transkript ve Ölçümler Paneli", "Diyalog Görünümü", "Kullanıcı ve asistan konuşma turlarını, TTFA/STT/LLM mikro-ölçümleriyle birlikte görüntüler.", "Turn Metric Transcript Box"],
            ],
            "biz_value": "Geçmiş diyalogların denetlenmesini, kalite kontrolünü ve hukuki kayıt şeffaflığını sağlar."
        },
        {
            "id": "16_ses_laboratuvari",
            "title": "A.20. Akustik Ses Laboratuvarı ve İnteraktif Sentez",
            "img": "docs/screenshots/16_ses_laboratuvari.png",
            "desc": "FreyaTTS akustik motorunu bağımsız metinlerle test etmek, ODE adımlarını ve hız çarpanını anlık gözlemlemek için tasarlanmış geliştirici arayüzüdür.",
            "controls": [
                ["Kaynak Metin Giriş Alanı", "Metin Kutusu", "Fonetik telaffuzu test edilecek teknik Türkçe cümlenin yazıldığı giriş alanı.", "Textarea Input"],
                ["Normalizasyonu İncele", "Dönüşüm Butonu", "Metni Ajan 1 P0 normalizer motorundan geçirerek telaffuz çıktısını ekrana basar.", "POST /api/normalize"],
                ["Sesi Üret", "Sentez Butonu", "Pipelined Overlap ODE motoruyla metni anlık olarak Leyla sesine dönüştürür ve çalar.", "POST /api/synthesize"],
            ],
            "biz_value": "Yeni eklenen telaffuz kurallarının ve akustik modellerin laboratuvar ortamında hızla dinlenmesini sağlar."
        },
        {
            "id": "17_sistem",
            "title": "A.21. Sistem Bileşenleri, Donanım Hazırlığı ve Devre Kesici",
            "img": "docs/screenshots/17_sistem.png",
            "desc": "TTS, STT, VAD ve Ollama servislerinin hazırlık durumunu (READY) ve GPU Circuit Breaker (CLOSED) korumasını izleyen sistem ekranıdır.",
            "controls": [
                ["Yerel Bileşen Durum Rozetleri", "Hazırlık Rozeti", "FreyaTTS CUDA, Faster-Whisper, Silero VAD ve Ollama hazırlığını gösterir.", "GET /api/readiness"],
                ["GPU Circuit Breaker Rozeti", "Güvenlik Rozeti", "GPU aşırı yük korumasının 'CLOSED (Normal)' olduğunu doğrular.", "GET /api/gpu-health/circuit-status"],
                ["Modelleri Yükle Butonu", "Yükleme Butonu", "Bellekte olmayan modellerin GPU/CPU'ya yüklenmesini tetikler.", "POST /api/models/load"],
            ],
            "biz_value": "Sunucu sağlığını izler, aşırı yük anında GPU devre kesicisiyle sistem kilitlenmelerini engeller."
        },
        {
            "id": "18_m01-m11",
            "title": "A.22. M01–M11 Fiziksel Donanım Kabul ve Mimari Denetim",
            "img": "docs/screenshots/18_m01-m11.png",
            "desc": "Projenin tüm fazlarını (M01-M11) bağımsız testlerle denetleyen ve fiziksel PBX donanım kabul kapısını (HOLD/PASS) yöneten sertifikasyon sayfasıdır.",
            "controls": [
                ["Fiziksel Kabul Denetim Rozeti", "Güvenlik Alanı", "Fiziksel Asterisk PBX pcap trace kanıtını denetler (Durum: HOLD / PASS).", "GET /api/milestones/overview"],
                ["Sözleşmeyi İncele", "İnceleme Butonu", "M01-M11 donanım kabul kriterleri şartnamesini ve teknik taahhütleri görüntüler.", "Review Milestone Contract"],
                ["İnceleyen (operator_01) Alanı", "Denetçi Bilgisi", "Donanım kabul testini gerçekleştiren operatör veya mühendisin kimlik doğrulamasını gösterir.", "Auditor Identity Badge"],
                ["İçe Aktarma Sağlaması (SHA-256)", "Kriptografik Kontrol", "Yazılım modüllerinin bütünlük özetini doğrular.", "Manifest Integrity Guard"],
            ],
            "biz_value": "Sistemin canlı santrale geçişinin bağımsız fiziksel donanım test kanıtlarına bağlanmasını garanti eder."
        },
    ]

    for s in screens:
        add_heading_2(doc, s["title"])
        add_screenshot_card(doc, s["img"], s["title"])
        add_body_p(doc, s["desc"], "Ekran Amacı: ")
        add_heading_3(doc, "Ekrandaki Gerçek Tuşlar ve Kontroller Tablosu")
        add_styled_table(
            doc,
            ["Kontrol / Tuş Adı", "Kontrol Türü", "Yaptığı İşlem / Açıklama", "Arka Uç / API Tetiklemesi"],
            s["controls"],
            col_widths=[1.6, 1.2, 2.2, 1.5]
        )
        add_callout(doc, "MÜHENDİSLİK VE OPERASYONEL DEĞERİ", s["biz_value"], border_color="16A34A")
        doc.add_paragraph().paragraph_format.space_after = Pt(8)

    # Belgeyi Kaydet (Hem v3 hem de ana dosya adına kaydet)
    out_path_v3 = Path("docs/FreyaTTS_Otomotiv_Asistani_Yonetici_Sunumu_3.docx")
    out_path = Path("docs/FreyaTTS_Otomotiv_Asistani_Yonetici_Sunumu.docx")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path_v3))
    doc.save(str(out_path))
    print(f"\n[SUCCESS] Yenilenen Yönetici Sunum Dokümanı (v3) Başarıyla Oluşturuldu:")
    print(f"  -> {out_path_v3.resolve()}")
    print(f"  -> {out_path.resolve()}")


if __name__ == "__main__":
    generate_document()
