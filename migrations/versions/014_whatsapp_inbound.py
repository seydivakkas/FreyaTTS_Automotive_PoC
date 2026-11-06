"""Create whatsapp_messages table for two-way WhatsApp/SMS management.

Revision ID: 014
Revises: 013
Create Date: 2026-11-02 03:05:00.000000

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"


def upgrade():
    op.create_table(
        "whatsapp_messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("message_sid", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("from_phone", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("customer_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("message_type", sa.String(length=32), nullable=False, server_default="text"),
        sa.Column("raw_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("transcription", sa.Text(), nullable=False, server_default=""),
        sa.Column("extracted_intent", sa.String(length=40), nullable=False, server_default="unknown"),
        sa.Column("extracted_time", sa.String(length=40), nullable=False, server_default=""),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reply_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("outbound_calls_cancelled", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index(
        "ix_whatsapp_messages_from_phone",
        "whatsapp_messages",
        ["from_phone"],
    )
    op.create_index(
        "ix_whatsapp_messages_appointment_id",
        "whatsapp_messages",
        ["appointment_id"],
    )
    op.create_index(
        "ix_whatsapp_messages_created_at",
        "whatsapp_messages",
        ["created_at"],
    )


def downgrade():
    op.drop_index("ix_whatsapp_messages_created_at", table_name="whatsapp_messages")
    op.drop_index("ix_whatsapp_messages_appointment_id", table_name="whatsapp_messages")
    op.drop_index("ix_whatsapp_messages_from_phone", table_name="whatsapp_messages")
    op.drop_table("whatsapp_messages")

