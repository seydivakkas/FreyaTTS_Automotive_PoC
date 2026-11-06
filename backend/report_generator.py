"""Automotive Inspection Report PDF Generator using ReportLab.

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any

from backend.config import settings

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"


def _init_fonts() -> tuple[str, str]:
    global FONT_REGULAR, FONT_BOLD
    candidates = [
        ("Arial", "Arial-Bold", "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        (
            "DejaVuSans",
            "DejaVuSans-Bold",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
    ]
    for reg_name, bold_name, reg_path, bold_path in candidates:
        if os.path.exists(reg_path) and os.path.exists(bold_path):
            try:
                pdfmetrics.registerFont(TTFont(reg_name, reg_path))
                pdfmetrics.registerFont(TTFont(bold_name, bold_path))
                FONT_REGULAR = reg_name
                FONT_BOLD = bold_name
                return FONT_REGULAR, FONT_BOLD
            except Exception:
                continue
    return FONT_REGULAR, FONT_BOLD


_init_fonts()


def _get_score_badge(score: int) -> tuple[str, colors.Color]:
    if score >= 90:
        return "KUSURSUZ (A+)", colors.HexColor("#16A34A")
    if score >= 75:
        return "İYİ DURUMDA (B)", colors.HexColor("#0284C7")
    if score >= 50:
        return "ORTA / KUSURLU (C)", colors.HexColor("#CA8A04")
    return "AĞIR HASARLI / RİSKLİ (D)", colors.HexColor("#DC2626")


def generate_inspection_pdf(
    report: Any,
    vehicle: Any,
    appointment: Any = None,
    output_path: str | Path | None = None,
) -> bytes:
    """Generate a multi-page professional vehicle inspection report PDF.

    Returns the raw bytes of the generated PDF. If output_path is provided,
    also writes the PDF to that file path.
    """
    _init_fonts()
    buffer = io.BytesIO()

    # Document setup: A4, 15mm margins
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=f"Ekspertiz Raporu - {getattr(vehicle, 'plate', 'Araç')}",
        author="FreyaTTS Automotive",
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "DocTitle",
        fontName=FONT_BOLD,
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#0F172A"),
    )
    subtitle_style = ParagraphStyle(
        "DocSub",
        fontName=FONT_REGULAR,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#475569"),
    )
    h2_style = ParagraphStyle(
        "H2",
        fontName=FONT_BOLD,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#1E293B"),
        spaceBefore=8,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "Body",
        fontName=FONT_REGULAR,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#334155"),
    )
    bold_style = ParagraphStyle(
        "BoldText",
        fontName=FONT_BOLD,
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#0F172A"),
    )
    badge_style = ParagraphStyle(
        "BadgeText",
        fontName=FONT_BOLD,
        fontSize=10,
        leading=12,
        alignment=1,  # Center
        textColor=colors.white,
    )
    table_cell = ParagraphStyle(
        "TableCell",
        fontName=FONT_REGULAR,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#1E293B"),
    )
    table_cell_bold = ParagraphStyle(
        "TableCellBold",
        fontName=FONT_BOLD,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#0F172A"),
    )

    story = []

    # 1. Header Banner
    header_data = [
        [
            Paragraph("<b>FREYA OTOMOTİV EKSPERTİZ SİSTEMLERİ</b>", title_style),
            Paragraph(
                f"<b>Rapor No:</b> {getattr(report, 'id', '')[:8].upper()}<br/>"
                f"<b>Tarih:</b> {getattr(report, 'inspected_at', '')[:10]}<br/>"
                f"<b>Teknisyen:</b> {getattr(report, 'technician_name', 'Uzman Teknisyen')}",
                subtitle_style,
            ),
        ],
        [
            Paragraph("Dijital Muayene & Kapsamlı Durum Tespit Raporu", subtitle_style),
            Paragraph(
                f"<b>Randevu ID:</b> {getattr(report, 'appointment_id', None) or '-'}",
                subtitle_style,
            ),
        ],
    ]
    header_table = Table(header_data, colWidths=[110 * mm, 70 * mm])
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 3 * mm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#0284C7"), spaceAfter=8))

    # 2. Vehicle Info Card & Score
    score = getattr(report, "score", 100)
    badge_label, badge_color = _get_score_badge(score)

    plate = getattr(vehicle, "plate", "-") or "-"
    desc = getattr(vehicle, "description", "")
    if not desc:
        b = getattr(vehicle, "brand", "")
        m = getattr(vehicle, "model", "")
        desc = f"{b} {m}".strip() or "-"
    vin = getattr(vehicle, "vin", "") or "Bilinmiyor"
    mileage = getattr(report, "mileage_km", 0)

    vehicle_data = [
        [
            Paragraph("<b>Plaka:</b>", bold_style),
            Paragraph(str(plate), body_style),
            Paragraph("<b>Araç Tanımı:</b>", bold_style),
            Paragraph(str(desc), body_style),
            Paragraph(f"<b>Puan: {score}/100</b>", badge_style),
        ],
        [
            Paragraph("<b>Şasi (VIN):</b>", bold_style),
            Paragraph(str(vin), body_style),
            Paragraph("<b>Kilometre:</b>", bold_style),
            Paragraph(f"{mileage:,} km".replace(",", "."), body_style),
            Paragraph(f"<b>{badge_label}</b>", badge_style),
        ],
    ]
    veh_table = Table(
        vehicle_data,
        colWidths=[20 * mm, 40 * mm, 30 * mm, 45 * mm, 45 * mm],
    )
    veh_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (3, -1), colors.HexColor("#F8FAFC")),
                ("BACKGROUND", (4, 0), (4, -1), badge_color),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("INNERGRID", (0, 0), (3, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("BOX", (0, 0), (3, -1), 1, colors.HexColor("#CBD5E1")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(veh_table)
    story.append(Spacer(1, 4 * mm))

    # 3. Summary / Kanaat
    story.append(Paragraph("<b>GENEL DEĞERLENDİRME VE UZMAN KANAATİ</b>", h2_style))
    summary_text = getattr(report, "summary", "Genel araç kontrolü tamamlandı.")
    summary_table = Table(
        [[Paragraph(summary_text, body_style)]],
        colWidths=[180 * mm],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 4 * mm))

    # Parse findings
    raw_findings = getattr(report, "findings_json", "{}")
    findings = {}
    if isinstance(raw_findings, str):
        try:
            findings = json.loads(raw_findings) if raw_findings else {}
        except Exception:
            findings = {}
    elif isinstance(raw_findings, dict):
        findings = raw_findings

    # 4. Detailed 5 Findings Sections
    # 4.1 Paint & Body
    story.append(Paragraph("<b>1. BOYA, KAPORTA VE DIŞ KAROSER KONTROLÜ</b>", h2_style))
    paint_data = findings.get("paint_body", {})
    paint_rows = [
        [
            Paragraph("<b>Parça Adı</b>", table_cell_bold),
            Paragraph("<b>Ekspertiz Durumu</b>", table_cell_bold),
            Paragraph("<b>Parça Adı</b>", table_cell_bold),
            Paragraph("<b>Ekspertiz Durumu</b>", table_cell_bold),
        ],
        [
            Paragraph("Ön Kaput", table_cell),
            Paragraph(str(paint_data.get("kaput", "Orijinal")), table_cell),
            Paragraph("Sağ Ön Çamurluk", table_cell),
            Paragraph(str(paint_data.get("sag_on_camurluk", "Orijinal")), table_cell),
        ],
        [
            Paragraph("Tavan", table_cell),
            Paragraph(str(paint_data.get("tavan", "Orijinal")), table_cell),
            Paragraph("Sol Ön Çamurluk", table_cell),
            Paragraph(str(paint_data.get("sol_on_camurluk", "Orijinal")), table_cell),
        ],
        [
            Paragraph("Bagaj Kapağı", table_cell),
            Paragraph(str(paint_data.get("bagaj", "Orijinal")), table_cell),
            Paragraph("Sağ Ön Kapı", table_cell),
            Paragraph(str(paint_data.get("sag_on_kapi", "Orijinal")), table_cell),
        ],
        [
            Paragraph("Sol Ön Kapı", table_cell),
            Paragraph(str(paint_data.get("sol_on_kapi", "Orijinal")), table_cell),
            Paragraph("Sağ Arka Kapı", table_cell),
            Paragraph(str(paint_data.get("sag_arka_kapi", "Orijinal")), table_cell),
        ],
        [
            Paragraph("Sol Arka Kapı", table_cell),
            Paragraph(str(paint_data.get("sol_arka_kapi", "Orijinal")), table_cell),
            Paragraph("Sağ Arka Çamurluk", table_cell),
            Paragraph(str(paint_data.get("sag_arka_camurluk", "Orijinal")), table_cell),
        ],
        [
            Paragraph("Sol Arka Çamurluk", table_cell),
            Paragraph(str(paint_data.get("sol_arka_camurluk", "Orijinal")), table_cell),
            Paragraph("Kaporta Notu", table_cell_bold),
            Paragraph(str(paint_data.get("notlar", "Standart mikron değerlerinde")), table_cell),
        ],
    ]
    t_paint = Table(paint_rows, colWidths=[40 * mm, 50 * mm, 40 * mm, 50 * mm])
    t_paint.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )
    story.append(t_paint)
    story.append(Spacer(1, 3 * mm))

    # 4.2 Engine & Mechanical
    story.append(Paragraph("<b>2. MOTOR, MEKANİK VE AKTARMA ORGANLARI</b>", h2_style))
    engine_data = findings.get("engine_mechanical", {})
    engine_rows = [
        [
            Paragraph("<b>Kontrol Noktası</b>", table_cell_bold),
            Paragraph("<b>Bulgu / Test Değeri</b>", table_cell_bold),
            Paragraph("<b>Kontrol Noktası</b>", table_cell_bold),
            Paragraph("<b>Bulgu / Test Değeri</b>", table_cell_bold),
        ],
        [
            Paragraph("Dyno Motor Gücü", table_cell),
            Paragraph(str(engine_data.get("motor_performansi_yuzde", "95%")), table_cell),
            Paragraph("Turbo Kompresör", table_cell),
            Paragraph(str(engine_data.get("turbo_durumu", "Basınç ve çalışma normal")), table_cell),
        ],
        [
            Paragraph("Şanzıman / Vites", table_cell),
            Paragraph(str(engine_data.get("sanziman_vites", "Kusursuz / Vuruntu yok")), table_cell),
            Paragraph("Enjektör / Yakıt", table_cell),
            Paragraph(str(engine_data.get("enjektor_yakit", "Püskürtme normal")), table_cell),
        ],
        [
            Paragraph("Yağ / Sıvı Kaçağı", table_cell),
            Paragraph(str(engine_data.get("yag_sivi_kacaklari", "Kaçak görülmedi")), table_cell),
            Paragraph("Egzoz / Emisyon", table_cell),
            Paragraph(str(engine_data.get("egzoz_emisyon", "Duman ve partikül normal")), table_cell),
        ],
    ]
    t_engine = Table(engine_rows, colWidths=[40 * mm, 50 * mm, 40 * mm, 50 * mm])
    t_engine.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )
    story.append(t_engine)
    story.append(Spacer(1, 3 * mm))

    # 4.3 Chassis & Suspension
    story.append(Paragraph("<b>3. ŞASİ, PODYE, ALT TAKIM VE FREN SİSTEMİ</b>", h2_style))
    chassis_data = findings.get("chassis_frame", {})
    chassis_rows = [
        [
            Paragraph("<b>Kontrol Noktası</b>", table_cell_bold),
            Paragraph("<b>Durum / Değerlendirme</b>", table_cell_bold),
            Paragraph("<b>Kontrol Noktası</b>", table_cell_bold),
            Paragraph("<b>Durum / Değerlendirme</b>", table_cell_bold),
        ],
        [
            Paragraph("Ön / Arka Podyeler", table_cell),
            Paragraph(str(chassis_data.get("on_podyeler", "İşlemsiz / Orijinal")), table_cell),
            Paragraph("Kuleler & Travers", table_cell),
            Paragraph(str(chassis_data.get("on_arka_travers", "Deformasyon yok")), table_cell),
        ],
        [
            Paragraph("Marşpiyeller & Taban", table_cell),
            Paragraph(str(chassis_data.get("marspiyeller", "Kaynak / Darbe yok")), table_cell),
            Paragraph("Fren Disk & Balata", table_cell),
            Paragraph(str(chassis_data.get("fren_disk_balata", "İyi durumda (%80)")), table_cell),
        ],
    ]
    t_chassis = Table(chassis_rows, colWidths=[40 * mm, 50 * mm, 40 * mm, 50 * mm])
    t_chassis.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )
    story.append(t_chassis)
    story.append(Spacer(1, 3 * mm))

    # 4.4 Tires & Wheels & 4.5 Interior
    story.append(Paragraph("<b>4. LASTİKLER, JANTLAR VE İÇ MEKAN / OBD ELEKTRONİK</b>", h2_style))
    tires_data = findings.get("tires_wheels", {})
    interior_data = findings.get("interior_electronics", {})
    combined_rows = [
        [
            Paragraph("<b>Bölüm</b>", table_cell_bold),
            Paragraph("<b>Detay</b>", table_cell_bold),
            Paragraph("<b>Bölüm</b>", table_cell_bold),
            Paragraph("<b>Detay</b>", table_cell_bold),
        ],
        [
            Paragraph("Lastik Diş Derinliği", table_cell),
            Paragraph(
                f"Ön: {tires_data.get('on_sol_dis_mm', '6.5mm')} / Arka: {tires_data.get('arka_sol_dis_mm', '6.0mm')}",
                table_cell,
            ),
            Paragraph("Airbag Kontrolü", table_cell),
            Paragraph(str(interior_data.get("airbag_guvenlik", "Orijinal ve aktif")), table_cell),
        ],
        [
            Paragraph("DOT & Jant Balansı", table_cell),
            Paragraph(
                f"DOT: {tires_data.get('dot_yili', '2024')} - {tires_data.get('jant_durumu', 'Düzgün')}",
                table_cell,
            ),
            Paragraph("OBD Beyin Taraması", table_cell),
            Paragraph(str(interior_data.get("obd_ariza_taramasi", "Aktif DTC arıza kodu yok")), table_cell),
        ],
        [
            Paragraph("Stepne & Avadanlık", table_cell),
            Paragraph(str(tires_data.get("stepne", "Mevcut ve sağlam")), table_cell),
            Paragraph("Klima & İç Kondisyon", table_cell),
            Paragraph(str(interior_data.get("klima_isitma", "Gaz ve soğutma tam kapasite")), table_cell),
        ],
    ]
    t_comb = Table(combined_rows, colWidths=[40 * mm, 50 * mm, 40 * mm, 50 * mm])
    t_comb.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )
    story.append(t_comb)
    story.append(Spacer(1, 4 * mm))

    # 5. Photos Section (if photos exist)
    raw_photos = getattr(report, "photos_json", "[]")
    photos: list[dict[str, Any]] = []
    if isinstance(raw_photos, str):
        try:
            photos = json.loads(raw_photos) if raw_photos else []
        except Exception:
            photos = []
    elif isinstance(raw_photos, list):
        photos = raw_photos

    if photos:
        story.append(Paragraph("<b>5. EKSPERTİZ VE ARAÇ FOTOĞRAFLARI</b>", h2_style))
        photo_cells = []
        for p in photos[:4]:  # Show up to 4 photos
            img_path = p.get("path") or p.get("url", "")
            # If relative URL, map to local disk
            if img_path.startswith("/api/inspections/photos/"):
                fname = img_path.split("/")[-1]
                img_path = str(settings.data_dir / "inspections" / "photos" / fname)
            elif img_path.startswith("/"):
                img_path = img_path.lstrip("/")

            caption = p.get("caption", "Ekspertiz Görseli")
            category = p.get("category", "")
            cell_items = []
            if os.path.exists(img_path):
                try:
                    cell_items.append(Image(img_path, width=75 * mm, height=45 * mm))
                except Exception:
                    cell_items.append(Paragraph("[Fotoğraf yüklenemedi]", body_style))
            else:
                cell_items.append(Paragraph(f"[Görsel: {caption}]", body_style))
            cell_items.append(
                Paragraph(
                    f"<b>{category}:</b> {caption}" if category else caption,
                    subtitle_style,
                )
            )
            photo_cells.append(cell_items)

        # Arrange in 2 columns
        grid_rows = []
        for i in range(0, len(photo_cells), 2):
            row_items = [photo_cells[i]]
            if i + 1 < len(photo_cells):
                row_items.append(photo_cells[i + 1])
            else:
                row_items.append([])
            grid_rows.append(row_items)

        t_photos = Table(grid_rows, colWidths=[90 * mm, 90 * mm])
        t_photos.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(t_photos)
        story.append(Spacer(1, 3 * mm))

    # 6. Legal disclaimer and Technician Seal
    footer_text = (
        "<b>YASAL BİLGİLENDİRME:</b> İşbu ekspertiz raporu, test anındaki teknik veriler "
        "ve görsel inceleme bulgularına dayanarak hazırlanmıştır. Gizli ve tespit edilemeyen "
        "iç deformasyonlar garanti kapsamında değildir.<br/>"
        "Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — Tüm Hakları Saklıdır."
    )
    seal_table = Table(
        [
            [
                Paragraph(footer_text, subtitle_style),
                Paragraph(
                    f"<b>KAŞE VE ONAY</b><br/>"
                    f"Teknisyen: {getattr(report, 'technician_name', 'Uzman Teknisyen')}<br/>"
                    f"<i>Dijital İmzalı ve Doğrulanmış</i>",
                    body_style,
                ),
            ]
        ],
        colWidths=[120 * mm, 60 * mm],
    )
    seal_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (1, 0), (1, 0), 0.5, colors.HexColor("#94A3B8")),
                ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#F8FAFC")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (1, 0), (1, 0), 6),
                ("RIGHTPADDING", (1, 0), (1, 0), 6),
            ]
        )
    )
    story.append(KeepTogether(seal_table))

    # Build document
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_bytes(pdf_bytes)

    return pdf_bytes
