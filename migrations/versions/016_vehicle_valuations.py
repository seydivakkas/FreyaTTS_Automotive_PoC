"""Create vehicle_valuations table for dynamic vehicle valuation and trade-in offers.

Revision ID: 016
Revises: 015
Create Date: 2026-11-02 06:10:00.000000

ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlı olarak paylaşılmıştır.
"""

from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "015"


def upgrade():
    op.create_table(
        "vehicle_valuations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "appointment_id",
            sa.String(),
            sa.ForeignKey("appointments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("plate", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("brand", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("model", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("model_year", sa.Integer(), nullable=False, server_default="2020"),
        sa.Column("fuel_type", sa.String(length=32), nullable=False, server_default="benzin"),
        sa.Column("transmission", sa.String(length=32), nullable=False, server_default="otomatik"),
        sa.Column("mileage_km", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("body_condition_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("tramer_amount_tl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("is_heavy_damage", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("base_benchmark_tl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("estimated_market_value_tl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("cash_buy_offer_tl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("trade_in_offer_tl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("valuation_range_min_tl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("valuation_range_max_tl", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="quoted"),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index(
        "ix_vehicle_valuations_plate",
        "vehicle_valuations",
        ["plate"],
    )
    op.create_index(
        "ix_vehicle_valuations_conversation_id",
        "vehicle_valuations",
        ["conversation_id"],
    )
    op.create_index(
        "ix_vehicle_valuations_created_at",
        "vehicle_valuations",
        ["created_at"],
    )


def downgrade():
    op.drop_index("ix_vehicle_valuations_created_at", table_name="vehicle_valuations")
    op.drop_index("ix_vehicle_valuations_conversation_id", table_name="vehicle_valuations")
    op.drop_index("ix_vehicle_valuations_plate", table_name="vehicle_valuations")
    op.drop_table("vehicle_valuations")

