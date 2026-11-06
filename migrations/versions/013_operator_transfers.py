"""Create operator_transfers table for live warm transfers and screen-pop.

Revision ID: 013
Revises: 012
Create Date: 2026-11-02 02:35:00.000000

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"


def upgrade():
    op.create_table(
        "operator_transfers",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("caller_channel", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("operator_extension", sa.String(length=32), nullable=False, server_default="6002"),
        sa.Column("customer_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("vehicle_plate", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("whisper_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="initiated"),
        sa.Column("sip_headers_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("completed_at", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_operator_transfers_status",
        "operator_transfers",
        ["status"],
    )
    op.create_index(
        "ix_operator_transfers_conversation_id",
        "operator_transfers",
        ["conversation_id"],
    )
    op.create_index(
        "ix_operator_transfers_created_at",
        "operator_transfers",
        ["created_at"],
    )


def downgrade():
    op.drop_index("ix_operator_transfers_created_at", table_name="operator_transfers")
    op.drop_index("ix_operator_transfers_conversation_id", table_name="operator_transfers")
    op.drop_index("ix_operator_transfers_status", table_name="operator_transfers")
    op.drop_table("operator_transfers")

