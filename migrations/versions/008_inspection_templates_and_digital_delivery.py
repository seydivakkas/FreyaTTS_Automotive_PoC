"""Add inspection findings, photos, pdf_path, and digital delivery fields.

Revision ID: 008
Revises: 007
Create Date: 2026-11-01 23:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"


def upgrade():
    with op.batch_alter_table("inspection_reports") as batch:
        batch.add_column(
            sa.Column(
                "appointment_id",
                sa.String(),
                sa.ForeignKey(
                    "appointments.id",
                    name="fk_inspection_reports_appointment_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "technician_name",
                sa.String(length=120),
                nullable=False,
                server_default="Uzman Teknisyen",
            )
        )
        batch.add_column(
            sa.Column(
                "findings_json",
                sa.Text(),
                nullable=False,
                server_default="{}",
            )
        )
        batch.add_column(
            sa.Column(
                "photos_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            )
        )
        batch.add_column(
            sa.Column(
                "pdf_path",
                sa.String(length=255),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "delivered_at",
                sa.String(length=40),
                nullable=True,
            )
        )
        batch.create_index(
            "ix_inspection_reports_appointment_id",
            ["appointment_id"],
        )
        batch.create_index(
            "ix_inspection_reports_vehicle_id",
            ["vehicle_id"],
        )


def downgrade():
    with op.batch_alter_table("inspection_reports") as batch:
        batch.drop_index("ix_inspection_reports_vehicle_id")
        batch.drop_index("ix_inspection_reports_appointment_id")
        batch.drop_column("delivered_at")
        batch.drop_column("pdf_path")
        batch.drop_column("photos_json")
        batch.drop_column("findings_json")
        batch.drop_column("technician_name")
        batch.drop_column("appointment_id")
