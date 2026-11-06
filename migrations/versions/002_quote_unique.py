"""One current service quote per vehicle."""

from alembic import op

revision = "002"
down_revision = "001"


def upgrade():
    with op.batch_alter_table("quotes") as batch:
        batch.create_unique_constraint("uq_quotes_vehicle_id", ["vehicle_id"])


def downgrade():
    with op.batch_alter_table("quotes") as batch:
        batch.drop_constraint("uq_quotes_vehicle_id", type_="unique")
