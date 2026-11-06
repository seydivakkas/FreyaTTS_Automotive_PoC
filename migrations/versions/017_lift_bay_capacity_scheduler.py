"""Create inspection_bays, technicians, and bay_schedules tables for lift bay capacity scheduling.

Revision ID: 017
Revises: 016
Create Date: 2026-11-02 08:15:00.000000

ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlı olarak paylaşılmıştır.
"""

from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"


def upgrade():
    # 1. inspection_bays
    op.create_table(
        "inspection_bays",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("bay_number", sa.Integer(), nullable=False, unique=True),
        sa.Column("bay_type", sa.String(length=64), nullable=False, server_default="mechanic_underbody"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="idle"),
        sa.Column(
            "current_appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("current_vehicle_plate", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index("ix_inspection_bays_bay_type", "inspection_bays", ["bay_type"])
    op.create_index("ix_inspection_bays_status", "inspection_bays", ["status"])
    op.create_index("ix_inspection_bays_bay_number", "inspection_bays", ["bay_number"])

    # 2. technicians
    op.create_table(
        "technicians",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False, server_default="Uzman Teknisyen"),
        sa.Column("specialties_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("daily_capacity", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index("ix_technicians_is_active", "technicians", ["is_active"])

    # 3. bay_schedules
    op.create_table(
        "bay_schedules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "bay_id",
            sa.String(),
            sa.ForeignKey("inspection_bays.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "technician_id",
            sa.String(),
            sa.ForeignKey("technicians.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("package_type", sa.String(length=64), nullable=False, server_default="standart_ekspertiz"),
        sa.Column("stage_name", sa.String(length=120), nullable=False),
        sa.Column("stage_index", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("starts_at", sa.String(length=40), nullable=False),
        sa.Column("ends_at", sa.String(length=40), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="scheduled"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index("ix_bay_schedules_appointment_id", "bay_schedules", ["appointment_id"])
    op.create_index("ix_bay_schedules_bay_id", "bay_schedules", ["bay_id"])
    op.create_index("ix_bay_schedules_starts_at", "bay_schedules", ["starts_at"])
    op.create_index("ix_bay_schedules_status", "bay_schedules", ["status"])


def downgrade():
    op.drop_table("bay_schedules")
    op.drop_table("technicians")
    op.drop_table("inspection_bays")

