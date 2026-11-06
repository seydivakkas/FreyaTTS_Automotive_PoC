"""Create outbound_calls table for Asterisk AMI call origination.

Revision ID: 007
Revises: 006
Create Date: 2026-11-01 22:30:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"


def upgrade():
    op.create_table(
        "outbound_calls",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phone", sa.String(length=40), nullable=False),
        sa.Column("customer", sa.String(length=120), nullable=False),
        sa.Column(
            "call_type",
            sa.String(length=32),
            nullable=False,
            server_default="reminder",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "outcome",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "action_id",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("completed_at", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_outbound_calls_status_created_at",
        "outbound_calls",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_outbound_calls_appointment_id",
        "outbound_calls",
        ["appointment_id"],
    )


def downgrade():
    op.drop_index("ix_outbound_calls_appointment_id", table_name="outbound_calls")
    op.drop_index("ix_outbound_calls_status_created_at", table_name="outbound_calls")
    op.drop_table("outbound_calls")

