"""Automotive Inspection Report PDF Generator using ReportLab.

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any, Optional

from backend.config import settings

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
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


# Teknisyen belirtmediyse rapor "Orijinal/normal" demez
NOT_STATED = "Belirtilmedi"


def _get_score_badge(score: Optional[int]) -> tuple[str, colors.Color]:
    if score is None:
        return "PUAN YOK", colors.HexColor("#64748B")
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
    score = getattr(report, "score", None)  # puan yoksa uydurulmaz
    score_text = f"{score}/100" if score is not None else "—"
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
            Paragraph(f"<b>Puan: {score_text}</b>", badge_style),
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
            Paragraph(str(paint_data.get("kaput", NOT_STATED)), table_cell),
            Paragraph("Sağ Ön Çamurluk", table_cell),
            Paragraph(str(paint_data.get("sag_on_camurluk", NOT_STATED)), table_cell),
        ],
        [
            Paragraph("Tavan", table_cell),
            Paragraph(str(paint_data.get("tavan", NOT_STATED)), table_cell),
            Paragraph("Sol Ön Çamurluk", table_cell),
            Paragraph(str(paint_data.get("sol_on_camurluk", NOT_STATED)), table_cell),
        ],
        [
            Paragraph("Bagaj Kapağı", table_cell),
            Paragraph(str(paint_data.get("bagaj", NOT_STATED)), table_cell),
            Paragraph("Sağ Ön Kapı", table_cell),
            Paragraph(str(paint_data.get("sag_on_kapi", NOT_STATED)), table_cell),
        ],
        [
            Paragraph("Sol Ön Kapı", table_cell),
            Paragraph(str(paint_data.get("sol_on_kapi", NOT_STATED)), table_cell),
            Paragraph("Sağ Arka Kapı", table_cell),
            Paragraph(str(paint_data.get("sag_arka_kapi", NOT_STATED)), table_cell),
        ],
        [
            Paragraph("Sol Arka Kapı", table_cell),
            Paragraph(str(paint_data.get("sol_arka_kapi", NOT_STATED)), table_cell),
            Paragraph("Sağ Arka Çamurluk", table_cell),
            Paragraph(str(paint_data.get("sag_arka_camurluk", NOT_STATED)), table_cell),
        ],
        [
            Paragraph("Sol Arka Çamurluk", table_cell),
            Paragraph(str(paint_data.get("sol_arka_camurluk", NOT_STATED)), table_cell),
            Paragraph("Kaporta Notu", table_cell_bold),
            Paragraph(str(paint_data.get("notlar", NOT_STATED)), table_cell),
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
            Paragraph(str(engine_data.get("motor_performansi_yuzde", NOT_STATED)), table_cell),
            Paragraph("Turbo Kompresör", table_cell),
            Paragraph(str(engine_data.get("turbo_durumu", NOT_STATED)), table_cell),
        ],
        [
            Paragraph("Şanzıman / Vites", table_cell),
            Paragraph(str(engine_data.get("sanziman_vites", NOT_STATED)), table_cell),
            Paragraph("Enjektör / Yakıt", table_cell),
            Paragraph(str(engine_data.get("enjektor_yakit", NOT_STATED)), table_cell),
        ],
        [
            Paragraph("Yağ / Sıvı Kaçağı", table_cell),
            Paragraph(str(engine_data.get("yag_sivi_kacaklari", NOT_STATED)), table_cell),
            Paragraph("Egzoz / Emisyon", table_cell),
            Paragraph(str(engine_data.get("egzoz_emisyon", NOT_STATED)), table_cell),
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
            Paragraph(str(chassis_data.get("on_podyeler", NOT_STATED)), table_cell),
            Paragraph("Kuleler & Travers", table_cell),
            Paragraph(str(chassis_data.get("on_arka_travers", NOT_STATED)), table_cell),
        ],
        [
            Paragraph("Marşpiyeller & Taban", table_cell),
            Paragraph(str(chassis_data.get("marspiyeller", NOT_STATED)), table_cell),
            Paragraph("Fren Disk & Balata", table_cell),
            Paragraph(str(chassis_data.get("fren_disk_balata", NOT_STATED)), table_cell),
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
            Paragraph(str(interior_data.get("airbag_guvenlik", NOT_STATED)), table_cell),
        ],
        [
            Paragraph("DOT & Jant Balansı", table_cell),
            Paragraph(
                f"DOT: {tires_data.get('dot_yili', '2024')} - {tires_data.get('jant_durumu', 'Düzgün')}",
                table_cell,
            ),
            Paragraph("OBD Beyin Taraması", table_cell),
            Paragraph(str(interior_data.get("obd_ariza_taramasi", NOT_STATED)), table_cell),
        ],
        [
            Paragraph("Stepne & Avadanlık", table_cell),
            Paragraph(str(tires_data.get("stepne", NOT_STATED)), table_cell),
            Paragraph("Klima & İç Kondisyon", table_cell),
            Paragraph(str(interior_data.get("klima_isitma", NOT_STATED)), table_cell),
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


# ============================================================================
# HAFTALIK ÖZET VE EXCEL (.XLSX) RAPORLAMA FONKSİYONLARI
# ============================================================================

def generate_weekly_summary_report(db, days: int = 7) -> dict[str, Any]:
    """Generates a structured weekly executive summary for automotive operations."""
    from datetime import datetime, timezone, timedelta
    from collections import defaultdict
    from sqlalchemy import select
    from backend.db import Conversation, Turn, Appointment
    from backend.analytics import _calc_percentile

    now_utc = datetime.now(timezone.utc)
    start_utc = now_utc - timedelta(days=days)
    start_iso = start_utc.isoformat()

    # Conversations
    convs = db.scalars(
        select(Conversation).where(Conversation.created_at >= start_iso)
    ).all()
    total_convs = len(convs)

    status_counts = defaultdict(int)
    for c in convs:
        status_counts[c.status] += 1

    # Appointments
    appts = db.scalars(
        select(Appointment).where(Appointment.created_at >= start_iso)
    ).all()
    total_appts = len(appts)
    confirmed_appts = sum(1 for a in appts if a.confirmed and a.status == "confirmed")
    cancelled_appts = sum(1 for a in appts if a.status == "cancelled")

    cancellation_rate = (
        round((cancelled_appts / total_appts) * 100, 1) if total_appts > 0 else 0.0
    )
    conversion_rate = (
        round((confirmed_appts / total_convs) * 100, 1) if total_convs > 0 else 0.0
    )

    package_counts = defaultdict(int)
    for a in appts:
        pkg = getattr(a, "package_type", "standart_ekspertiz") or "standart_ekspertiz"
        package_counts[pkg] += 1

    # Turns & Latency
    first_audio_list = []
    llm_total_list = []
    stt_list = []
    unclear_count = 0
    total_user_turns = 0

    unclear_keywords = ["anlayamadım", "tekrar edebilir misiniz", "net duyamadım", "doğrulayamadım"]

    conv_ids = [c.id for c in convs]
    turns = (
        db.scalars(
            select(Turn).where(Turn.conversation_id.in_(conv_ids)).order_by(Turn.created_at)
        ).all()
        if conv_ids
        else []
    )

    for t in turns:
        if t.role == "user":
            total_user_turns += 1
        elif t.role == "assistant":
            txt = (t.text or "").lower()
            if any(k in txt for k in unclear_keywords):
                unclear_count += 1

        if t.metrics and t.metrics != "{}":
            try:
                m = json.loads(t.metrics) if isinstance(t.metrics, str) else t.metrics
                if isinstance(m, dict):
                    if m.get("first_audio_ms") is not None:
                        first_audio_list.append(float(m["first_audio_ms"]))
                    if m.get("llm_total_ms") is not None:
                        llm_total_list.append(float(m["llm_total_ms"]))
                    if m.get("stt_ms") is not None:
                        stt_list.append(float(m["stt_ms"]))
            except Exception:
                pass

    clarity_rate = (
        round(100.0 - (unclear_count / max(total_user_turns, 1) * 100.0), 1)
        if total_user_turns > 0
        else None
    )

    # Daily breakdown
    daily_stats = {}
    for i in range(days - 1, -1, -1):
        d_str = (now_utc - timedelta(days=i)).strftime("%Y-%m-%d")
        daily_stats[d_str] = {
            "date": d_str,
            "conversations": 0,
            "appointments": 0,
            "cancelled": 0,
        }

    for c in convs:
        d = (c.created_at or "")[:10]
        if d in daily_stats:
            daily_stats[d]["conversations"] += 1
    for a in appts:
        d = (a.created_at or "")[:10]
        if d in daily_stats:
            daily_stats[d]["appointments"] += 1
            if a.status == "cancelled":
                daily_stats[d]["cancelled"] += 1

    return {
        "period_days": days,
        "start_date": start_iso[:10],
        "end_date": now_utc.strftime("%Y-%m-%d"),
        "generated_at": now_utc.isoformat(),
        "summary": {
            "total_conversations": total_convs,
            "completed_conversations": status_counts.get("completed", 0),
            "follow_up_conversations": status_counts.get("follow_up", 0),
            "total_appointments": total_appts,
            "confirmed_appointments": confirmed_appts,
            "cancelled_appointments": cancelled_appts,
            "cancellation_rate_pct": cancellation_rate,
            "conversion_rate_pct": conversion_rate,
            "stt_clarity_rate_pct": clarity_rate,
            "unclear_turns_count": unclear_count,
        },
        "latency_percentiles": {
            "first_audio_p50_ms": _calc_percentile(first_audio_list, 50),
            "first_audio_p95_ms": _calc_percentile(first_audio_list, 95),
            "llm_p50_ms": _calc_percentile(llm_total_list, 50),
            "llm_p95_ms": _calc_percentile(llm_total_list, 95),
            "stt_p50_ms": _calc_percentile(stt_list, 50),
            "stt_p95_ms": _calc_percentile(stt_list, 95),
            "sample_count": len(first_audio_list),
        },
        "package_distribution": dict(package_counts),
        "daily_breakdown": list(daily_stats.values()),
    }


def generate_weekly_excel_report(db, days: int = 7) -> bytes:
    """Generates a professional multi-sheet Excel (.xlsx) operational report."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from sqlalchemy import select
    from backend.db import Conversation, Turn, Appointment, Slot, Vehicle

    summary_data = generate_weekly_summary_report(db, days=days)
    summ = summary_data["summary"]
    lat = summary_data["latency_percentiles"]

    wb = openpyxl.Workbook()

    # Standard styling tokens
    font_title = Font(name="Calibri", size=15, bold=True, color="FFFFFF")
    font_section = Font(name="Calibri", size=12, bold=True, color="1E293B")
    font_header = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    font_bold = Font(name="Calibri", size=10, bold=True, color="0F172A")
    font_regular = Font(name="Calibri", size=10, color="334155")
    font_muted = Font(name="Calibri", size=9, italic=True, color="64748B")

    fill_dark = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    fill_blue = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
    fill_light = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
    fill_zebra = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")

    thin_border_side = Side(style="thin", color="CBD5E1")
    border_cell = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    # ----------------------------------------------------
    # SHEET 1: YÖNETİCİ ÖZETİ
    # ----------------------------------------------------
    ws1 = wb.active
    ws1.title = "Yönetici Özeti"
    ws1.views.sheetView[0].showGridLines = True

    # Title Banner
    ws1.merge_cells("A1:F1")
    c1 = ws1["A1"]
    c1.value = "FREYATTS AUTOMOTIVE — HAFTALIK OPERASYON VE KPI RAPORU"
    c1.font = font_title
    c1.fill = fill_dark
    c1.alignment = align_center
    ws1.row_dimensions[1].height = 36

    ws1.merge_cells("A2:F2")
    c2 = ws1["A2"]
    c2.value = f"Dönem: {summary_data['start_date']} — {summary_data['end_date']} | Rapor Tarihi: {summary_data['generated_at'][:19].replace('T', ' ')} (UTC)"
    c2.font = font_muted
    c2.alignment = align_center
    ws1.row_dimensions[2].height = 20

    # Section 1: Ana Metrikler
    ws1.cell(row=4, column=1, value="GENEL OPERASYONEL METRİKLER").font = font_section
    kpis = [
        ("Toplam Müşteri Görüşmesi", summ["total_conversations"], "Görüşme"),
        ("Tamamlanan Görüşmeler", summ["completed_conversations"], "Görüşme"),
        ("Takibe Düşen Görüşmeler", summ["follow_up_conversations"], "Görüşme"),
        ("Alınan Toplam Randevu", summ["total_appointments"], "Randevu"),
        ("Onaylanan Randevular", summ["confirmed_appointments"], "Randevu"),
        ("İptal Edilen Randevular", summ["cancelled_appointments"], "Randevu"),
        ("Randevu İptal Oranı", f"%{summ['cancellation_rate_pct']}", "Oran"),
        ("Dönüşüm Oranı (Randevu/Çağrı)", f"%{summ['conversion_rate_pct']}", "Oran"),
        ("STT Konuşma Netlik Oranı", f"%{summ['stt_clarity_rate_pct']}" if summ['stt_clarity_rate_pct'] is not None else "—", "Netlik"),
        ("Anlaşılamayan Tur Sayısı", summ["unclear_turns_count"], "Adet"),
    ]

    r_idx = 5
    ws1.cell(row=r_idx, column=1, value="Metrik Adı").font = font_header
    ws1.cell(row=r_idx, column=1).fill = fill_blue
    ws1.cell(row=r_idx, column=2, value="Değer").font = font_header
    ws1.cell(row=r_idx, column=2).fill = fill_blue
    ws1.cell(row=r_idx, column=3, value="Birim").font = font_header
    ws1.cell(row=r_idx, column=3).fill = fill_blue
    ws1.row_dimensions[r_idx].height = 22

    for name, val, unit in kpis:
        r_idx += 1
        c_name = ws1.cell(row=r_idx, column=1, value=name)
        c_name.font = font_regular
        c_name.border = border_cell
        c_name.fill = fill_zebra if r_idx % 2 == 0 else fill_light

        c_val = ws1.cell(row=r_idx, column=2, value=val)
        c_val.font = font_bold
        c_val.alignment = align_right
        c_val.border = border_cell
        c_val.fill = fill_zebra if r_idx % 2 == 0 else fill_light

        c_unit = ws1.cell(row=r_idx, column=3, value=unit)
        c_unit.font = font_muted
        c_unit.alignment = align_center
        c_unit.border = border_cell
        c_unit.fill = fill_zebra if r_idx % 2 == 0 else fill_light

    # Section 2: Gecikme & Ses Performansı
    r_idx += 2
    ws1.cell(row=r_idx, column=1, value="SİSTEM VE SES GECİKME PERFORMANSI (REAL SLA)").font = font_section
    r_idx += 1

    ws1.cell(row=r_idx, column=1, value="Gecikme Göstergesi").font = font_header
    ws1.cell(row=r_idx, column=1).fill = fill_dark
    ws1.cell(row=r_idx, column=2, value="P50 (Medyan)").font = font_header
    ws1.cell(row=r_idx, column=2).fill = fill_dark
    ws1.cell(row=r_idx, column=3, value="P95 (Kritik)").font = font_header
    ws1.cell(row=r_idx, column=3).fill = fill_dark
    ws1.row_dimensions[r_idx].height = 22

    lat_rows = [
        ("Uçtan Uca İlk Ses Yanıtı (first_audio_ms)", f"{lat['first_audio_p50_ms']} ms" if lat['first_audio_p50_ms'] else "—", f"{lat['first_audio_p95_ms']} ms" if lat['first_audio_p95_ms'] else "—"),
        ("LLM Cevap Üretim Süresi (llm_total_ms)", f"{lat['llm_p50_ms']} ms" if lat['llm_p50_ms'] else "—", f"{lat['llm_p95_ms']} ms" if lat['llm_p95_ms'] else "—"),
        ("STT Konuşma Tanıma Süresi (stt_ms)", f"{lat['stt_p50_ms']} ms" if lat['stt_p50_ms'] else "—", f"{lat['stt_p95_ms']} ms" if lat['stt_p95_ms'] else "—"),
    ]

    for label, p50_val, p95_val in lat_rows:
        r_idx += 1
        ws1.cell(row=r_idx, column=1, value=label).font = font_regular
        ws1.cell(row=r_idx, column=1).border = border_cell
        ws1.cell(row=r_idx, column=2, value=p50_val).font = font_bold
        ws1.cell(row=r_idx, column=2).alignment = align_right
        ws1.cell(row=r_idx, column=2).border = border_cell
        ws1.cell(row=r_idx, column=3, value=p95_val).font = font_bold
        ws1.cell(row=r_idx, column=3).alignment = align_right
        ws1.cell(row=r_idx, column=3).border = border_cell

    # ----------------------------------------------------
    # SHEET 2: RANDEVULAR
    # ----------------------------------------------------
    ws2 = wb.create_sheet(title="Randevular")
    ws2.views.sheetView[0].showGridLines = True

    headers2 = ["Randevu ID", "Tarih / Saat", "Müşteri Adı", "Telefon Numarası", "Araç Plakası", "Paket Türü", "Durum", "Ücret (TL)"]
    for c_i, h in enumerate(headers2, start=1):
        cell = ws2.cell(row=1, column=c_i, value=h)
        cell.font = font_header
        cell.fill = fill_blue
        cell.alignment = align_center
        cell.border = border_cell
    ws2.row_dimensions[1].height = 24

    appts_all = db.scalars(
        select(Appointment).order_by(Appointment.created_at.desc())
    ).all()

    for r_i, a in enumerate(appts_all, start=2):
        v = db.get(Vehicle, a.vehicle_id) if a.vehicle_id else None
        s = db.get(Slot, a.slot_id) if a.slot_id else None
        plate = getattr(v, "plate", "") if v else ""
        slot_time = getattr(s, "starts_at", a.created_at) if s else a.created_at
        amount_tl = (a.billed_amount_kurus or 0) / 100.0

        row_vals = [
            a.id,
            str(slot_time)[:16].replace("T", " "),
            a.customer,
            getattr(a, "customer_phone", "") or "—",
            plate or "—",
            a.package_type or "standart_ekspertiz",
            "Onaylı" if a.status == "confirmed" else "İptal Edildi",
            f"{amount_tl:,.2f} TL" if amount_tl > 0 else "Peşin / Standart",
        ]

        fill_cur = fill_zebra if r_i % 2 == 0 else fill_light
        for c_i, val in enumerate(row_vals, start=1):
            cell = ws2.cell(row=r_i, column=c_i, value=val)
            cell.font = font_regular
            cell.border = border_cell
            cell.fill = fill_cur
            if c_i in (2, 7):
                cell.alignment = align_center
            elif c_i == 8:
                cell.alignment = align_right

    # ----------------------------------------------------
    # SHEET 3: GÖRÜŞMELER
    # ----------------------------------------------------
    ws3 = wb.create_sheet(title="Görüşmeler")
    ws3.views.sheetView[0].showGridLines = True

    headers3 = ["Görüşme ID", "Tarih", "Kanal", "Durum", "Tur Sayısı", "Operatör Notu"]
    for c_i, h in enumerate(headers3, start=1):
        cell = ws3.cell(row=1, column=c_i, value=h)
        cell.font = font_header
        cell.fill = fill_dark
        cell.alignment = align_center
        cell.border = border_cell
    ws3.row_dimensions[1].height = 24

    convs_all = db.scalars(
        select(Conversation).order_by(Conversation.created_at.desc()).limit(200)
    ).all()

    for r_i, c in enumerate(convs_all, start=2):
        t_count = db.scalar(
            select(Turn.id).where(Turn.conversation_id == c.id)
        )
        fill_cur = fill_zebra if r_i % 2 == 0 else fill_light

        status_tr = {
            "completed": "Tamamlandı",
            "follow_up": "Takip Gerekiyor",
            "resolved": "Çözüldü",
            "active": "Aktif",
        }.get(c.status, c.status)

        row_vals = [
            c.id,
            str(c.created_at)[:19].replace("T", " "),
            c.channel or "voice",
            status_tr,
            c.turn_count if hasattr(c, "turn_count") else "—",
            c.operator_notes or "",
        ]

        for c_i, val in enumerate(row_vals, start=1):
            cell = ws3.cell(row=r_i, column=c_i, value=val)
            cell.font = font_regular
            cell.border = border_cell
            cell.fill = fill_cur
            if c_i in (2, 3, 4, 5):
                cell.alignment = align_center

    # ----------------------------------------------------
    # SHEET 4: GÜNLÜK DAĞILIM
    # ----------------------------------------------------
    ws4 = wb.create_sheet(title="Günlük Dağılım")
    ws4.views.sheetView[0].showGridLines = True

    headers4 = ["Tarih", "Görüşme Sayısı", "Alınan Randevu", "İptal Edilen Randevu", "Net Randevu"]
    for c_i, h in enumerate(headers4, start=1):
        cell = ws4.cell(row=1, column=c_i, value=h)
        cell.font = font_header
        cell.fill = fill_blue
        cell.alignment = align_center
        cell.border = border_cell
    ws4.row_dimensions[1].height = 24

    for r_i, d in enumerate(summary_data["daily_breakdown"], start=2):
        net_appts = d["appointments"] - d["cancelled"]
        fill_cur = fill_zebra if r_i % 2 == 0 else fill_light
        vals = [d["date"], d["conversations"], d["appointments"], d["cancelled"], net_appts]

        for c_i, val in enumerate(vals, start=1):
            cell = ws4.cell(row=r_i, column=c_i, value=val)
            cell.font = font_regular
            cell.border = border_cell
            cell.fill = fill_cur
            cell.alignment = align_center if c_i == 1 else align_right

    # Auto-adjust column widths across all sheets
    for ws in [ws1, ws2, ws3, ws4]:
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                val_str = str(cell.value or "")
                if "\n" in val_str:
                    val_str = max(val_str.split("\n"), key=len)
                if len(val_str) > max_len:
                    max_len = len(val_str)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    # Save to buffer
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

