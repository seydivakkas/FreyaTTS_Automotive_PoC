"""Create call_analytics and ruhsat_scans tables.

Revision ID: 015
Revises: 014
Create Date: 2026-11-02 05:46:00.000000

ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlı olarak paylaşılmıştır.
"""

from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"


def upgrade():
    # 1. call_analytics table
    op.create_table(
        "call_analytics",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("caller_phone", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("caller_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("executive_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("intent", sa.String(length=64), nullable=False, server_default="unknown"),
        sa.Column("csat_score", sa.Float(), nullable=False, server_default="3.0"),
        sa.Column("sentiment", sa.String(length=32), nullable=False, server_default="neutral"),
        sa.Column("lead_score", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("lead_tier", sa.String(length=16), nullable=False, server_default="WARM"),
        sa.Column("objections_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("topics_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("recommended_action", sa.Text(), nullable=False, server_default=""),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index(
        "ix_call_analytics_conversation_id",
        "call_analytics",
        ["conversation_id"],
    )
    op.create_index(
        "ix_call_analytics_lead_tier",
        "call_analytics",
        ["lead_tier"],
    )
    op.create_index(
        "ix_call_analytics_created_at",
        "call_analytics",
        ["created_at"],
    )

    # 2. ruhsat_scans table
    op.create_table(
        "ruhsat_scans",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "vehicle_id",
            sa.String(),
            sa.ForeignKey("vehicles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("from_phone", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("plate", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("vin", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("engine_code", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("model_year", sa.Integer(), nullable=True),
        sa.Column("brand_model", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("document_serial", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("owner_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("raw_extracted_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index(
        "ix_ruhsat_scans_plate",
        "ruhsat_scans",
        ["plate"],
    )
    op.create_index(
        "ix_ruhsat_scans_vin",
        "ruhsat_scans",
        ["vin"],
    )
    op.create_index(
        "ix_ruhsat_scans_from_phone",
        "ruhsat_scans",
        ["from_phone"],
    )
    op.create_index(
        "ix_ruhsat_scans_created_at",
        "ruhsat_scans",
        ["created_at"],
    )


def downgrade():
    op.drop_index("ix_ruhsat_scans_created_at", table_name="ruhsat_scans")
    op.drop_index("ix_ruhsat_scans_from_phone", table_name="ruhsat_scans")
    op.drop_index("ix_ruhsat_scans_vin", table_name="ruhsat_scans")
    op.drop_index("ix_ruhsat_scans_plate", table_name="ruhsat_scans")
    op.drop_table("ruhsat_scans")

    op.drop_index("ix_call_analytics_created_at", table_name="call_analytics")
    op.drop_index("ix_call_analytics_lead_tier", table_name="call_analytics")
    op.drop_index("ix_call_analytics_conversation_id", table_name="call_analytics")
    op.drop_table("call_analytics")

