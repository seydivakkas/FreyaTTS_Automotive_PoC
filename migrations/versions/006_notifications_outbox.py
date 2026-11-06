"""Create notifications table for M10 outbox messaging.

Revision ID: 006
Revises: 005
Create Date: 2026-11-01 22:20:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient_type", sa.String(length=32), nullable=False),
        sa.Column("recipient", sa.String(length=120), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="sms"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("sent_at", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_notifications_status_created_at",
        "notifications",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_notifications_appointment_id",
        "notifications",
        ["appointment_id"],
    )


def downgrade():
    op.drop_index("ix_notifications_appointment_id", table_name="notifications")
    op.drop_index("ix_notifications_status_created_at", table_name="notifications")
    op.drop_table("notifications")

