"""Initial local assistant schema, frozen independently of ORM evolution."""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None


def upgrade():
    op.create_table(
        "vehicles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("plate", sa.String(), nullable=False),
    )
    op.create_table(
        "quotes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "vehicle_id", sa.String(), sa.ForeignKey("vehicles.id"), nullable=False
        ),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
    )
    op.create_table(
        "slots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("starts_at", sa.String(), nullable=False, unique=True),
    )
    op.create_table(
        "appointments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("slot_id", sa.String(), sa.ForeignKey("slots.id"), unique=True),
        sa.Column(
            "vehicle_id", sa.String(), sa.ForeignKey("vehicles.id"), nullable=False
        ),
        sa.Column("customer", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "turns",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metrics", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )


def downgrade():
    for name in [
        "turns",
        "conversations",
        "appointments",
        "slots",
        "quotes",
        "vehicles",
    ]:
        op.drop_table(name)
