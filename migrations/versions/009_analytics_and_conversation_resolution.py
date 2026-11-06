"""Add operator_notes and resolved_at to conversations with indexes.

Revision ID: 009
Revises: 008
Create Date: 2026-11-01 23:20:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"


def upgrade():
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(
            sa.Column(
                "operator_notes",
                sa.Text(),
                nullable=False,
                server_default="",
            )
        )
        batch.add_column(
            sa.Column(
                "resolved_at",
                sa.String(length=40),
                nullable=True,
            )
        )
        batch.create_index(
            "ix_conversations_status",
            ["status"],
        )
        batch.create_index(
            "ix_conversations_created_at",
            ["created_at"],
        )


def downgrade():
    with op.batch_alter_table("conversations") as batch:
        batch.drop_index("ix_conversations_created_at")
        batch.drop_index("ix_conversations_status")
        batch.drop_column("resolved_at")
        batch.drop_column("operator_notes")

