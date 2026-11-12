"""Add Supervisor routing traces, reviewed examples and write receipts."""

import sqlalchemy as sa
from alembic import op

revision = "022"
down_revision = "021"


def upgrade():
    op.create_table(
        "supervisor_traces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("review_status", sa.String(24), nullable=False),
        sa.Column("review_labels", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_supervisor_traces_conversation_id", "supervisor_traces", ["conversation_id"])
    op.create_index("ix_supervisor_traces_created_at", "supervisor_traces", ["created_at"])
    op.create_table(
        "intent_training_candidates",
        sa.Column("trace_id", sa.String(36), sa.ForeignKey("supervisor_traces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("text_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("group_id", sa.String(36), nullable=False),
        sa.Column("split", sa.String(12), nullable=False),
        sa.Column("example", sa.Text(), nullable=False),
    )
    op.create_index("ix_intent_training_candidates_group_id", "intent_training_candidates", ["group_id"])
    op.create_table(
        "supervisor_write_receipts",
        sa.Column("key", sa.String(36), primary_key=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )


def downgrade():
    op.drop_table("supervisor_write_receipts")
    op.drop_table("intent_training_candidates")
    op.drop_table("supervisor_traces")
