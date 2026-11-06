"""Create inspection_lifts and inspection_queues tables, add package_type to appointments.

Revision ID: 011
Revises: 010
Create Date: 2026-11-02 01:12:00.000000

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"


def upgrade():
    # 1. Inspection Lifts table
    op.create_table(
        "inspection_lifts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("lift_number", sa.Integer(), nullable=False, unique=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="idle",
        ),
        sa.Column(
            "current_appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "current_vehicle_plate",
            sa.String(length=32),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "package_type",
            sa.String(length=64),
            nullable=False,
            server_default="standart_ekspertiz",
        ),
        sa.Column("started_at", sa.String(length=40), nullable=True),
        sa.Column(
            "estimated_duration_min",
            sa.Integer(),
            nullable=False,
            server_default="45",
        ),
        sa.Column(
            "notes",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index(
        "ix_inspection_lifts_status",
        "inspection_lifts",
        ["status"],
    )
    op.create_index(
        "ix_inspection_lifts_lift_number",
        "inspection_lifts",
        ["lift_number"],
    )

    # 2. Inspection Queue table
    op.create_table(
        "inspection_queues",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("queue_number", sa.Integer(), nullable=False),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "vehicle_id",
            sa.String(),
            sa.ForeignKey("vehicles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("plate", sa.String(length=32), nullable=False),
        sa.Column("customer", sa.String(length=120), nullable=False),
        sa.Column(
            "package_type",
            sa.String(length=64),
            nullable=False,
            server_default="standart_ekspertiz",
        ),
        sa.Column(
            "duration_minutes",
            sa.Integer(),
            nullable=False,
            server_default="45",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="waiting",
        ),
        sa.Column(
            "lift_id",
            sa.String(),
            sa.ForeignKey("inspection_lifts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("check_in_at", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.String(length=40), nullable=True),
        sa.Column("completed_at", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_inspection_queues_status",
        "inspection_queues",
        ["status"],
    )
    op.create_index(
        "ix_inspection_queues_check_in_at",
        "inspection_queues",
        ["check_in_at"],
    )

    # 3. Add package_type column to appointments
    with op.batch_alter_table("appointments") as batch_op:
        batch_op.add_column(
            sa.Column(
                "package_type",
                sa.String(length=64),
                nullable=False,
                server_default="standart_ekspertiz",
            )
        )


def downgrade():
    with op.batch_alter_table("appointments") as batch_op:
        batch_op.drop_column("package_type")
    op.drop_index("ix_inspection_queues_check_in_at", table_name="inspection_queues")
    op.drop_index("ix_inspection_queues_status", table_name="inspection_queues")
    op.drop_table("inspection_queues")
    op.drop_index("ix_inspection_lifts_lift_number", table_name="inspection_lifts")
    op.drop_index("ix_inspection_lifts_status", table_name="inspection_lifts")
    op.drop_table("inspection_lifts")

