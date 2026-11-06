"""Create vehicle_diagnostics table for OBD-II telemetry and proactive maintenance.

Revision ID: 010
Revises: 009
Create Date: 2026-11-01 23:35:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"


def upgrade():
    op.create_table(
        "vehicle_diagnostics",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "vehicle_id",
            sa.String(),
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dtc_code", sa.String(length=16), nullable=False),
        sa.Column(
            "severity",
            sa.String(length=32),
            nullable=False,
            server_default="warning",
        ),
        sa.Column(
            "system_category",
            sa.String(length=64),
            nullable=False,
            server_default="engine",
        ),
        sa.Column("description_tr", sa.String(length=255), nullable=False),
        sa.Column("recommended_action", sa.Text(), nullable=False),
        sa.Column(
            "current_mileage_km",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "next_service_km",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "maintenance_status",
            sa.String(length=32),
            nullable=False,
            server_default="normal",
        ),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            server_default="obd_dongle",
        ),
        sa.Column(
            "is_resolved",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "owner_phone",
            sa.String(length=40),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "owner_name",
            sa.String(length=120),
            nullable=False,
            server_default="",
        ),
        sa.Column("last_notified_at", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_vehicle_diagnostics_vehicle_id",
        "vehicle_diagnostics",
        ["vehicle_id"],
    )
    op.create_index(
        "ix_vehicle_diagnostics_dtc_code",
        "vehicle_diagnostics",
        ["dtc_code"],
    )
    op.create_index(
        "ix_vehicle_diagnostics_severity",
        "vehicle_diagnostics",
        ["severity"],
    )


def downgrade():
    op.drop_index("ix_vehicle_diagnostics_severity", table_name="vehicle_diagnostics")
    op.drop_index("ix_vehicle_diagnostics_dtc_code", table_name="vehicle_diagnostics")
    op.drop_index("ix_vehicle_diagnostics_vehicle_id", table_name="vehicle_diagnostics")
    op.drop_table("vehicle_diagnostics")

