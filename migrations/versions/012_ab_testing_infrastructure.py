"""Create ab_experiments and ab_assignments tables.

Revision ID: 012
Revises: 011
Create Date: 2026-11-02 01:35:00.000000

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"


def upgrade():
    op.create_table(
        "ab_experiments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "experiment_type",
            sa.String(length=40),
            nullable=False,
            server_default="composite",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "variants_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "target_metric",
            sa.String(length=40),
            nullable=False,
            server_default="conversion_rate",
        ),
        sa.Column(
            "created_at",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.String(length=40),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_ab_experiments_status",
        "ab_experiments",
        ["status"],
    )

    op.create_table(
        "ab_assignments",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "experiment_id",
            sa.String(),
            sa.ForeignKey("ab_experiments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("variant_id", sa.String(length=64), nullable=False),
        sa.Column(
            "outcome",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("first_audio_ms", sa.Float(), nullable=True),
        sa.Column("tts_total_ms", sa.Float(), nullable=True),
        sa.Column("llm_total_ms", sa.Float(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column(
            "turns_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("created_at", sa.String(length=40), nullable=False),
        sa.Column("completed_at", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_ab_assignments_experiment_id",
        "ab_assignments",
        ["experiment_id"],
    )
    op.create_index(
        "ix_ab_assignments_variant_id",
        "ab_assignments",
        ["variant_id"],
    )
    op.create_index(
        "ix_ab_assignments_outcome",
        "ab_assignments",
        ["outcome"],
    )


def downgrade():
    op.drop_index("ix_ab_assignments_outcome", table_name="ab_assignments")
    op.drop_index("ix_ab_assignments_variant_id", table_name="ab_assignments")
    op.drop_index("ix_ab_assignments_experiment_id", table_name="ab_assignments")
    op.drop_table("ab_assignments")

    op.drop_index("ix_ab_experiments_status", table_name="ab_experiments")
    op.drop_table("ab_experiments")

