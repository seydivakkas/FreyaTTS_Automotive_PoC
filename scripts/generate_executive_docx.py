# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# 
# Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
# amaçlı olarak paylaşılmıştır.
# =====================================================================
"""
scripts/generate_executive_docx.py
FreyaTTS Otomotiv Asistanı — yönetici sunumu üreticisi (PoC durum belgesi).

Belgedeki hiçbir ölçüm koda gömülü değildir. Üretim anında okunan kaynaklar:
- data/acoustic/latest.json  (WER, CER, terim doğruluğu, RTF, F0, provenance)
- pytest --collect-only -q   (test sayısı, son satır)
- backend.normalizer_rules.BASE_AUTOMOTIVE_LEXICON (sözlük kural sayısı)
- data/m11/M11_ACCEPTANCE.json veya docs/milestones/current-acceptance.json
- abc_evaluator.run_benchmark_suite([], acoustic_report=...)  (kalite kapısı)
- docs/measured-latency.json (tek çalıştırma gecikme örneği)
Kaynak yoksa değer yerine "ölçülmedi" yazılır.

Çalıştırma: .venv\Scripts\python scripts\generate_executive_docx.py  (extra: tools)
"""

import argparse
import json
import os
import re
import subprocess
import sys
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
    r_title = p.add_run(f"{title}\n")
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
    r_hdr = p_hdr.add_run("FreyaTTS Otomotiv Asistanı — Yönetici Sunumu (PoC)")
    r_hdr.font.name = "Arial"
    r_hdr.font.size = Pt(8.5)
    r_hdr.font.color.rgb = COLOR_MUTED

    # Alt Bilgi (Sayfa 2+)
    footer = section.footer
    p_ftr = footer.paragraphs[0]
    p_ftr.alignment = WD_ALIGN_PARAGRAPH.LEFT

    r_f1 = p_ftr.add_run("PoC DURUM BELGESİ")
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


# ---------------------------------------------------------------------------
# Veri kaynakları: hiçbir ölçüm koda gömülü değildir; hepsi üretim anında okunur.
# Kaynak yoksa değer yerine "ölçülmedi" yazılır.
# ---------------------------------------------------------------------------
NA = "ölçülmedi"
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # `backend` paketi betik dizininden doğrudan çalıştırılınca da bulunsun

DEFAULT_PATHS = {
    "acoustic": ROOT / "data" / "acoustic" / "latest.json",
    "m11": [ROOT / "data" / "m11" / "M11_ACCEPTANCE.json", ROOT / "docs" / "milestones" / "current-acceptance.json"],
    "latency": ROOT / "docs" / "measured-latency.json",
    "nav": ROOT / "frontend" / "src" / "nav.ts",
    "screenshots": ROOT / "docs" / "screenshots",
    "output": ROOT / "docs" / "FreyaTTS_Otomotiv_Asistani_Yonetici_Sunumu.docx",
}

BANNER = "Durum: PoC. Bu belge yalnızca ölçülen değerleri içerir."
DEMO_CAPTION = "Demo verisi; gerçek ölçüm değildir"

# Ekran görüntüleri yalnızca bu sekmeler için eklenir (dosyaları scripts/capture_screenshots.py üretir).
SCREENSHOTS = [
    ("01_gorusme.png", "Görüşme"),
    ("04_randevular.png", "Randevular"),
    ("07_analitik_ve_kpi.png", "Analitik & KPI"),
    ("17_sistem.png", "Sistem"),
]

# Sekme amaçları: yalnızca kodda var olan davranışı anlatır. Sekme listesi nav.ts'ten okunur.
TAB_PURPOSE = {
    "Görüşme": "Tarayıcı mikrofonuyla sesli görüşme ve canlı transkript",
    "Operatör (6002)": "Operatör devri ve kalite kapısı görünümü (AMI sahte istemcidir; gerçek aktarım yok)",
    "Araç İçi DSP & Gürültü": "Gürültü bastırma ayarları",
    "Randevular": "Randevu ve müsait saat yönetimi",
    "Sıra & Lift Durumu": "Sıra ve lift kapasitesi görünümü",
    "A/B Test & İnce Ayar": "Karşılama ve istem deneyleri, ses tohumu karşılaştırması",
    "Analitik & KPI": "Görüşme ve gecikme özetleri",
    "Ekspertiz Raporları": "Muayene ve rapor kayıtları",
    "Teknisyen Dikte": "Teknisyen sesli notunun yazıya çevrilmesi",
    "Araç Teşhis & OBD-II": "Arıza kodu sorgulama",
    "Araçlar ve fiyatlar": "Araç kaydı ve ekspertiz fiyatı girişi",
    "Sözlük": "Otomotiv telaffuz sözlüğü",
    "Bildirimler": "Bildirim kutusu (sağlayıcı sahtedir; gerçek SMS/WhatsApp gönderimi yok)",
    "Giden Çağrılar": "Giden çağrı kayıtları (AMI sahtedir; gerçek arama yok)",
    "Geçmiş": "Görüşme geçmişi ve transkriptler",
    "Ses laboratuvarı": "Normalizasyon ve sentez denemesi",
    "Sistem": "Model yükleme ve hazırlık durumu",
    "M01–M11": "Kabul kapıları ve entegrasyon kayıtları",
}


def read_json(path):
    """JSON okur; dosya yoksa veya bozuksa None döner (değer uydurulmaz)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def num(value, suffix="", digits=2):
    """Sayıyı Türkçe ondalık virgülle yazar; değer yoksa 'ölçülmedi'."""
    if value is None:
        return NA
    if isinstance(value, float):
        text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    else:
        text = str(value)
    return text.replace(".", ",") + suffix


def collect_test_count():
    """`pytest --collect-only -q` çıktısının son satırı; alınamazsa None."""
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT, timeout=300,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[-1] if lines else None


def lexicon_rule_count():
    try:
        from backend.normalizer_rules import BASE_AUTOMOTIVE_LEXICON
        return len(BASE_AUTOMOTIVE_LEXICON)
    except Exception:
        return None


def _rel(p):
    try:
        return str(Path(p).resolve().relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return Path(p).name


def m11_state(paths):
    """İlk var olan M11 kaydının genel durumu: (durum, kaynak, son çalışma tarihi)."""
    for p in paths:
        data = read_json(p)
        if isinstance(data, dict) and data.get("overall"):
            times = [g.get("run_at_utc") for g in data.get("gates", []) if g.get("run_at_utc")]
            return data["overall"], _rel(p), (max(times) if times else None)
    return None, None, None


def quality_gate(report):
    """Gerçek kalite kapısı: abc_evaluator.run_benchmark_suite([], acoustic_report=...)."""
    if not report:
        return None
    try:
        from backend.qa_telemetry_operator import abc_evaluator
        return abc_evaluator.run_benchmark_suite([], acoustic_report=report)
    except Exception:
        return None


def metric_status(gate, name):
    if gate is None:
        return NA
    if name in gate["quality_gate_failed"]:
        return "FAIL"
    if name in gate["quality_gate_missing"]:
        return "HOLD"
    return "PASS"


def read_tabs(nav_path):
    try:
        text = Path(nav_path).read_text(encoding="utf-8")
        block = text.split("export const TABS = [", 1)[1].split("] as const", 1)[0]
        return re.findall(r'"([^"]+)"', block) or list(TAB_PURPOSE)
    except (OSError, IndexError):
        return list(TAB_PURPOSE)


def add_bullets(doc, items):
    for item in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(2)
        run = p.add_run(item)
        run.font.name = "Arial"
        run.font.size = Pt(9.5)
        run.font.color.rgb = COLOR_TEXT


def generate_document(paths=None, test_count_line="auto"):
    """Belgeyi üretir. `paths`, DEFAULT_PATHS anahtarlarını geçersiz kılar (testler için).

    test_count_line: "auto" ise pytest toplanır; aksi halde verilen metin kullanılır (None = ölçülmedi).
    """
    cfg = dict(DEFAULT_PATHS)
    cfg.update(paths or {})
    output = Path(cfg["output"])

    report = read_json(cfg["acoustic"])
    latency = read_json(cfg["latency"])
    test_line = collect_test_count() if test_count_line == "auto" else test_count_line
    lexicon_n = lexicon_rule_count()
    m11_status, m11_src, m11_date = m11_state(cfg["m11"])
    gate = quality_gate(report)

    ch = None
    if report:
        ch = (report.get("channels") or {}).get(report.get("gate_channel"))
    prov = (report or {}).get("provenance", {})
    f0 = (report or {}).get("f0", {})

    doc = Document()
    core = doc.core_properties
    core.author = "Seydi Vakkas Eryılmaz"
    core.title = "FreyaTTS Otomotiv Sesli Asistanı — Yönetici Sunumu"
    core.subject = "PoC durum özeti"
    core.comments = "Özel Lisans — Tüm Hakları Saklıdır (c) 2026 Seydi Eryılmaz (@seydivakkas)"
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Inches(0.8)
        section.left_margin = section.right_margin = Inches(0.8)
    setup_header_footer(doc)

    # ------------------------------------------------------------------ başlık
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run("FreyaTTS Otomotiv Sesli Asistanı")
    r.bold = True
    r.font.name = "Arial"
    r.font.size = Pt(22)
    r.font.color.rgb = COLOR_NAVY
    p = doc.add_paragraph()
    r = p.add_run("Yönetici Sunumu — yerel Türkçe ekspertiz randevu asistanı")
    r.font.name = "Arial"
    r.font.size = Pt(11)
    r.font.color.rgb = COLOR_MUTED
    add_callout(doc, "Belge durumu", BANNER, border_color="D97706", bg_color="FFFBEB")

    # --------------------------------------------------------- 1. yönetici özeti
    add_heading_1(doc, "1. Yönetici özeti")
    add_bullets(doc, [
        "Sistem bir PoC'tur (kavram kanıtı). Pilota hazır değildir.",
        "Çalışan çekirdek: yerel konuşma tanıma, kural öncelikli diyalog, yerel sentez ve SQLite'a randevu kaydı.",
        (f"Ses doğruluğu (kalite kapısı): WER {metric_status(gate, 'avg_wer_pct')}, CER {metric_status(gate, 'avg_cer_pct')}, "
         f"terim doğruluğu {metric_status(gate, 'automotive_accuracy_pct')}, genel kapı {(gate or {}).get('quality_gate_5_status', NA)} (Bölüm 3)."),
        "Doğrulanmayanlar: insan sesiyle test, Asterisk üzerinden gerçek telefon testi, gerçek SMS sağlayıcısı (Bölüm 6).",
        "Pilot öncesi eksiklerin kapatılması gerekir; gerçekçi adımlar Bölüm 7'dedir.",
    ])

    # ---------------------------------------------------------- 2. neler çalışıyor
    add_heading_1(doc, "2. Neler çalışıyor (doğrulanmış)")
    works = [
        ["Tarayıcı mikrofonuyla uçtan uca randevu akışı", "Gerçek modellerle sanal mikrofon testi; müşteri sesi sentetik TTS sesidir"],
        ["Kural öncelikli diyalog: katalog ve ad kuralı yeterliyse LLM atlanır", "backend/dialogue.py; LLM yalnızca kuralların okuyamadığı söz için çağrılır"],
        ["Açılışta TTS ön ısıtma (karşılama ve sabit cümleler)", "backend/models.py; ilk ses ölçümü Bölüm 3.2'dedir"],
        ["Sese dayalı geri tanıma ölçümü (TTS, telefon bandı, STT)", "scripts/acoustic_benchmark.py; sonuç data/acoustic/latest.json"],
        ["Kalite kapısı: eşik aşımı FAIL, ölçülmeyen kriter HOLD", "backend/qa_telemetry_operator.py; PASS yalnızca tüm kriterler ölçülüp geçerse"],
        ["Otomatik testler", f"{test_line or NA} (toplanan test sayısı; pytest --collect-only -q son satırı)"],
    ]
    add_styled_table(doc, ["Özellik", "Nasıl doğrulandı / kaynak"], works, col_widths=[3.1, 3.8])

    # -------------------------------------------------------------- 3. ölçümler
    add_heading_1(doc, "3. Ölçümler")
    add_heading_2(doc, "3.1 Ses doğruluğu ve kalite kapısı")
    if report and ch and gate:
        crit = gate["quality_gate_criteria"]
        rows = [
            ["Kelime hata oranı (WER)", num(ch.get("avg_wer_pct"), " %"), f"en çok {num(crit['max_wer_pct'], ' %')}", metric_status(gate, "avg_wer_pct")],
            ["Karakter hata oranı (CER)", num(ch.get("avg_cer_pct"), " %"), f"en çok {num(crit['max_cer_pct'], ' %')}", metric_status(gate, "avg_cer_pct")],
            ["Otomotiv terim doğruluğu", num(ch.get("automotive_accuracy_pct"), " %"), f"en az {num(crit['min_automotive_accuracy_pct'], ' %')}", metric_status(gate, "automotive_accuracy_pct")],
            ["Konuşmacı benzerliği (ABX)", NA, f"en az {num(crit['min_abx_similarity'])}", metric_status(gate, "speaker_embedding_abx")],
            ["F0 sapması (tabana göre)", num(f0.get("max_drift_from_baseline_hz"), " Hz"), f"en çok {num(crit['max_f0_drift_hz'], ' Hz')}", metric_status(gate, "max_f0_drift_hz")],
            ["Genel kalite kapısı", "-", "-", gate["quality_gate_5_status"]],
        ]
        add_styled_table(doc, ["Ölçüt", "Ölçülen", "Eşik", "Durum"], rows, col_widths=[2.4, 1.3, 1.9, 1.3])
        stt = f"{prov.get('stt_model', NA)} / {prov.get('stt_device', NA)} / {prov.get('stt_compute_type', NA)}"
        add_body_p(doc, (
            f"Örnek sayısı: {num(report.get('sample_count'))}; kanal: {report.get('gate_channel', NA)}; "
            f"ölçüm zamanı: {report.get('measured_at', NA)}. "
            f"Sentez ortalama RTF: {num((report.get('tts') or {}).get('rtf_avg'))}; "
            f"F0 medyanı: {num(f0.get('median_hz'), ' Hz')}. "
            f"STT: {stt}; LoRA adaptörü: {prov.get('lora_adapter') or 'yok'}."
        ), "Ölçüm bağlamı: ")
        add_body_p(doc, (
            "WER, CER ve terim doğruluğu TTS ile STT'nin birleşik sonucudur; hata yalnızca bir modele atfedilemez. "
            "ABX ve MOS ölçülmemiştir; "
            + ("F0 taban kaydı alınmamıştır. " if f0.get("baseline_measured_at") is None else "F0 taban kaydı vardır. ")
            + "Ölçülmeyen kriter varken kapı PASS veremez."
        ), "Yorum: ")
    else:
        add_body_p(doc, f"Akustik rapor okunamadı: {NA}.")

    add_heading_2(doc, "3.2 Gecikme (tek çalıştırma örneği)")
    if latency:
        rows = [[r.get("step", NA), r.get("value", NA), r.get("note") or "-"] for r in latency.get("rows", [])]
        add_styled_table(doc, ["Adım", "Süre", "Not"], rows, col_widths=[2.6, 1.3, 3.0])
        v = latency.get("vram") or {}
        add_body_p(doc, (
            f"Tepe VRAM {num(v.get('peak_mib'))} / {num(v.get('total_mib'))} MiB; bunun yaklaşık "
            f"{num(v.get('desktop_apps_mib'))} MiB'ı masaüstü uygulamalarıdır ({v.get('note', NA)})."
        ), "Bellek: ")
        add_body_p(doc, (
            f"{latency.get('label', NA)}. Ölçüm tarihi {latency.get('measured_on', NA)}; "
            f"donanım: {latency.get('hardware', NA)}. {latency.get('method', '')}"
        ), "Etiket: ")
    else:
        add_body_p(doc, f"Gecikme ölçümleri: {NA}.")

    add_heading_2(doc, "3.3 Diğer sayımlar")
    add_styled_table(doc, ["Konu", "Değer", "Kaynak"], [
        ["Toplanan test", test_line or NA, "pytest --collect-only -q"],
        ["Sözlük kural sayısı", num(lexicon_n), "backend.normalizer_rules.BASE_AUTOMOTIVE_LEXICON"],
        ["M11 fiziksel kabul", (m11_status or NA) + (f" ({m11_date})" if m11_date else ""), m11_src or "M11 kayıt dosyası bulunamadı"],
    ], col_widths=[2.0, 2.4, 2.5])

    add_heading_2(doc, "Veri kaynağı")
    add_bullets(doc, [
        f"Akustik: {_rel(cfg['acoustic'])} ({'okundu' if report else NA}).",
        f"Gecikme: {_rel(cfg['latency'])} ({'okundu' if latency else NA}).",
        "Kalite kapısı: abc_evaluator.run_benchmark_suite([], acoustic_report=...) çıktısı.",
        f"Test sayısı: pytest --collect-only -q son satırı ({'okundu' if test_line else NA}).",
        f"Sözlük: BASE_AUTOMOTIVE_LEXICON ({'okundu' if lexicon_n is not None else NA}).",
        f"M11: {m11_src or NA}.",
    ])

    # ---------------------------------------------------------------- 4. mimari
    add_heading_1(doc, "4. Mimari")
    lora = prov.get("lora_adapter")
    arch = [
        ["Sentez (TTS)", f"FreyaTTS, {str(prov.get('tts_device', 'GPU')).upper()}"],
        ["Konuşma tanıma (STT)", f"faster-whisper {prov.get('stt_model', NA)}, {str(prov.get('stt_device', NA)).upper()}, {prov.get('stt_compute_type', NA)}"],
        ["Dil modeli", "Ollama üzerinde qwen2.5:7b (şemalı alan çıkarımı)"],
        ["Ses etkinliği", "Silero VAD"],
        ["Veri", "SQLite (WAL), Alembic migration"],
        ["Telefon girişi", "Asterisk AudioSocket (8 kHz PCM16); gerçek PBX ile doğrulanmadı"],
        ["Arayüz", "React yönetim paneli, FastAPI arka uç"],
        ["Ses adaptörü (LoRA)", f"{lora}" if lora else "Eğitilmiş adaptör yok"],
    ]
    add_styled_table(doc, ["Bileşen", "Gerçek durum"], arch, col_widths=[2.0, 4.9])
    add_body_p(doc, (
        "Görüşme sırasında harici STT/LLM hizmeti kullanılmaz. Backend randevu durum makinesini yürütür; "
        "LLM'in veritabanına doğrudan erişimi yoktur. Canlı yola bağlı olmayan kod experimental/ ve archive/ altındadır "
        "ve üretim davranışının kanıtı sayılmaz."
    ))

    # ----------------------------------------------------------- 5. doğrulama
    add_heading_1(doc, "5. Ne, nasıl doğrulandı")
    ver = (latency or {}).get("acceptance_runs") or {}
    main_run = ver.get("main_sentence") or {}
    short_run = ver.get("short_vehicle_sentence") or {}
    add_bullets(doc, [
        f"Birim ve entegrasyon testleri: {test_line or NA}.",
        "Akustik karşılaştırma: sentetik ses telefon bandına çevrilip STT ile geri tanındı (Bölüm 3.1).",
        "Gerçek model tarayıcı testi: müşteri olarak sentetik TTS sesi kullanıldı; insan sesi değildir.",
        (f"Araç adımı kararsız: ana kabul testi son {num(main_run.get('total'))} çalıştırmanın {num(main_run.get('passed'))} tanesinde geçti; "
         f"kısaltılmış araç cümlesi {num(short_run.get('total'))} çalıştırmanın {num(short_run.get('passed'))} tanesinde geçti."),
        "Telefon protokolü: birim testleri; gerçek PBX, ağ jitter'ı veya uçtan uca ses kalitesi kanıtı değildir.",
    ])

    # --------------------------------------------------------------- 6. riskler
    add_heading_1(doc, "6. Açık riskler ve eksikler")
    risks = [
        ["İnsan sesiyle test yok", "Doğal konuşma, aksan ve gürültüde davranış bilinmiyor"],
        ["Asterisk / gerçek telefon testi yok", f"M11 durumu: {m11_status or NA}; kanıt gönderilmemiş kapılar HOLD"],
        ["Gerçek SMS sağlayıcısı yok", "Bildirim sağlayıcısı sahte; gerçek mesaj gitmez"],
        ["AMI sahte", "Gerçek çağrı aktarımı ve giden arama yapılamaz"],
        ["Terim doğruluğu eşiğin çok altında", f"{num((ch or {}).get('automotive_accuracy_pct'), ' %')} ölçüldü; eşik %95 (marka ve motor kısaltmaları)"],
        ["ABX ve F0 tabanı ölçülmedi", "Ses kimliği ve doğallık için dinleme kabulü yok"],
        ["LoRA adaptörü yok", "Ses uyarlaması yapılmadı"],
        ["LLM turlarında ilk ses hedefin üstünde", "Hedef 1,2 s; LLM gerektiren turlar yaklaşık 6 s (Bölüm 3.2)"],
        ["KVKK maddeleri hukuki incelemede", "Saklama süresi yalnızca ses kayıtlarını kapsar; transkript ve diğer kişisel veri kapsam dışıdır"],
        ["Eşzamanlı görüşme ölçülmedi", "Yapılandırma üst sınırı 50 görüşmedir; VRAM ve gecikme yalnızca tek görüşmeyle sınandı"],
    ]
    add_styled_table(doc, ["Risk / eksik", "Ayrıntı"], risks, col_widths=[2.6, 4.3])

    # --------------------------------------------------------- 7. sonraki adımlar
    add_heading_1(doc, "7. Gerçekçi sonraki adımlar")
    add_bullets(doc, [
        "İnsan sesiyle kontrollü dinleme ve kabul testi; ABX/F0 tabanının kaydı.",
        "Marka ve motor terimleri için sözlük ve telaffuz iyileştirmesi; akustik ölçümün tekrarı.",
        "Gerçek Asterisk ve SIP hattıyla M11 kanıtlarının toplanması.",
        "Gerçek SMS/WhatsApp sağlayıcısı seçimi ve entegrasyonu.",
        "LLM gerektiren turlarda gecikme azaltımı; araç adımı kararlılığı.",
        "KVKK hukuki inceleme ve saklama kapsamının transkriptlere genişletilmesi.",
    ])

    # --------------------------------------------------------------- EK-A
    add_heading_1(doc, "EK-A. Yönetim paneli sekmeleri")
    tabs = read_tabs(cfg["nav"])
    add_styled_table(doc, ["Sekme", "Amaç"], [[t, TAB_PURPOSE.get(t, NA)] for t in tabs], col_widths=[2.2, 4.7])
    shots_dir = Path(cfg["screenshots"]) if cfg.get("screenshots") else None
    if shots_dir:
        for fname, title in SCREENSHOTS:
            path = shots_dir / fname
            if path.exists():
                add_screenshot_card(doc, str(path), f"{title}. {DEMO_CAPTION}")

    output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output))
    return output


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Yönetici sunumunu ölçüm dosyalarından üretir.")
    ap.add_argument("--output", type=Path)
    ap.add_argument("--acoustic", type=Path)
    ap.add_argument("--latency", type=Path)
    ap.add_argument("--no-screenshots", action="store_true")
    a = ap.parse_args()
    ov = {k: v for k, v in {"output": a.output, "acoustic": a.acoustic, "latency": a.latency}.items() if v}
    if a.no_screenshots:
        ov["screenshots"] = None
    print(generate_document(ov))
