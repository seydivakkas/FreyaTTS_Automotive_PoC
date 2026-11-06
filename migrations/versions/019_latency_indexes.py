"""Add missing hot-path indexes (turns, appointments, corporate_ledger).

Revision ID: 019
Revises: 018
Create Date: 2026-11-06 10:00:00.000000
"""

from alembic import op

revision = "019"
down_revision = "018"

_INDEXES = (
    ("ix_turns_conversation_id", "turns", ["conversation_id"]),
    ("ix_appointments_vehicle_id", "appointments", ["vehicle_id"]),
    ("ix_appointments_status", "appointments", ["status"]),
    ("ix_appointments_created_at", "appointments", ["created_at"]),
    ("ix_corporate_ledger_account_id", "corporate_ledger", ["account_id"]),
)


def upgrade():
    for name, table, cols in _INDEXES:
        op.create_index(name, table, cols)


def downgrade():
    for name, table, _ in reversed(_INDEXES):
        op.drop_index(name, table_name=table)
