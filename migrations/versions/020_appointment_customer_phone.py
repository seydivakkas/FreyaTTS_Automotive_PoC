# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""Add customer_phone column to appointments table.

Revision ID: 020
Revises: 019
Create Date: 2026-11-08 21:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "020"
down_revision = "019"


def upgrade():
    with op.batch_alter_table("appointments") as batch_op:
        batch_op.add_column(
            sa.Column(
                "customer_phone",
                sa.String(length=40),
                nullable=False,
                server_default="",
            )
        )
        batch_op.create_index(
            "ix_appointments_customer_phone",
            ["customer_phone"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("appointments") as batch_op:
        batch_op.drop_index("ix_appointments_customer_phone")
        batch_op.drop_column("customer_phone")
