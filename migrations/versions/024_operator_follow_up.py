"""Record the reason and start time of operator follow-up."""

import sqlalchemy as sa
from alembic import op

revision = "024"
down_revision = "023"


def upgrade():
    op.add_column("conversations", sa.Column("follow_up_kind", sa.String(24)))
    op.add_column("conversations", sa.Column("follow_up_at", sa.String(40)))


def downgrade():
    op.drop_column("conversations", "follow_up_at")
    op.drop_column("conversations", "follow_up_kind")
