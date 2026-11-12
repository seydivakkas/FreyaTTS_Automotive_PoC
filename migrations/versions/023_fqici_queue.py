"""Persist FQICI scopes, sanitized events, and leased analysis runs."""

import sqlalchemy as sa
from alembic import op

revision = "023"
down_revision = "022"


def upgrade():
    op.create_table(
        "fqici_scopes",
        sa.Column("id", sa.String(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("transport", sa.String(12), nullable=False),
        sa.Column("origin", sa.String(12), nullable=False),
        sa.Column("transport_id", sa.String(36)),
        sa.Column("terminal_seen", sa.Boolean(), nullable=False),
        sa.Column("dirty_since_ms", sa.BigInteger()),
        sa.Column("ready_at_ms", sa.BigInteger()),
    )
    op.create_table(
        "fqici_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope_id", sa.String(), sa.ForeignKey("fqici_scopes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("producer", sa.String(24), nullable=False),
        sa.Column("source_event_id", sa.String(36), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("producer", "source_event_id", name="uq_fqici_source_event"),
    )
    op.create_table(
        "fqici_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope_id", sa.String(), sa.ForeignKey("fqici_scopes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("rule_version", sa.String(32), nullable=False),
        sa.Column("event_ids", sa.Text(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("available_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("fence", sa.Integer(), nullable=False),
        sa.Column("lease_until_ms", sa.BigInteger()),
        sa.UniqueConstraint("scope_id", "evidence_hash", "rule_version", name="uq_fqici_run_snapshot"),
    )
    for table, columns in (
        ("fqici_scopes", ("terminal_seen", "ready_at_ms")),
        ("fqici_events", ("scope_id",)),
        ("fqici_runs", ("scope_id", "state")),
    ):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    op.drop_table("fqici_runs")
    op.drop_table("fqici_events")
    op.drop_table("fqici_scopes")
