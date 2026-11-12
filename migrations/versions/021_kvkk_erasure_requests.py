# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""Add kvkk_erasure_requests table for transcript retention & erasure workflow.

Revision ID: 021
Revises: 020
Create Date: 2026-11-09 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"


def upgrade():
    op.create_table(
        "kvkk_erasure_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("identifier_type", sa.String(length=32), nullable=False),
        sa.Column("identifier_value", sa.String(length=120), nullable=False),
        sa.Column("requester_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column(
            "reason",
            sa.String(length=255),
            nullable=False,
            server_default="KVKK Madde 11 uyarınca silme talebi",
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("impact_summary_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("certificate_sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("executed_at", sa.String(length=40), nullable=True),
        sa.Column("executed_by", sa.String(length=80), nullable=False, server_default="admin"),
    )
    op.create_index(
        "ix_kvkk_erasure_requests_status",
        "kvkk_erasure_requests",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_kvkk_erasure_requests_identifier_value",
        "kvkk_erasure_requests",
        ["identifier_value"],
        unique=False,
    )
    op.create_index(
        "ix_kvkk_erasure_requests_created_at",
        "kvkk_erasure_requests",
        ["created_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_kvkk_erasure_requests_created_at", table_name="kvkk_erasure_requests")
    op.drop_index("ix_kvkk_erasure_requests_identifier_value", table_name="kvkk_erasure_requests")
    op.drop_index("ix_kvkk_erasure_requests_status", table_name="kvkk_erasure_requests")
    op.drop_table("kvkk_erasure_requests")
