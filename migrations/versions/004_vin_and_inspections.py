"""Add vin to vehicles and create inspection_reports table."""

from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"


def upgrade():
    with op.batch_alter_table("vehicles") as batch:
        batch.add_column(
            sa.Column("vin", sa.String(), nullable=False, server_default="")
        )

    op.create_table(
        "inspection_reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "vehicle_id",
            sa.String(),
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("mileage_km", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("inspected_at", sa.String(), nullable=False),
    )


def downgrade():
    op.drop_table("inspection_reports")
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("vin")

