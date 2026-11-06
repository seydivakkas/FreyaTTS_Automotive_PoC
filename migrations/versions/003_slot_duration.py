"""Add duration_minutes to slots table."""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"


def upgrade():
    with op.batch_alter_table("slots") as batch:
        batch.add_column(
            sa.Column(
                "duration_minutes", sa.Integer(), nullable=False, server_default="30"
            )
        )


def downgrade():
    with op.batch_alter_table("slots") as batch:
        batch.drop_column("duration_minutes")

