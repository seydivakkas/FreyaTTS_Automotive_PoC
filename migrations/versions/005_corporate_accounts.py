"""Create corporate_accounts, corporate_ledger, and link to appointments."""

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"


def upgrade():
    op.create_table(
        "corporate_accounts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("tax_id", sa.String(), nullable=False, unique=True),
        sa.Column("phone", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "credit_limit_kurus", sa.Integer(), nullable=False, server_default="5000000"
        ),
        sa.Column(
            "balance_kurus", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "discount_percent", sa.Integer(), nullable=False, server_default="10"
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.String(), nullable=False),
    )

    op.create_table(
        "corporate_ledger",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "account_id",
            sa.String(),
            sa.ForeignKey("corporate_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("entry_type", sa.String(), nullable=False),
        sa.Column("amount_kurus", sa.Integer(), nullable=False),
        sa.Column("balance_after_kurus", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(), nullable=False),
    )

    with op.batch_alter_table("appointments") as batch:
        batch.add_column(
            sa.Column(
                "corporate_account_id",
                sa.String(),
                sa.ForeignKey(
                    "corporate_accounts.id",
                    name="fk_appointments_corporate_account_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "billed_amount_kurus",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade():
    with op.batch_alter_table("appointments") as batch:
        batch.drop_column("billed_amount_kurus")
        batch.drop_column("corporate_account_id")
    op.drop_table("corporate_ledger")
    op.drop_table("corporate_accounts")
