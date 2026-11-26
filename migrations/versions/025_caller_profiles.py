"""ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR. Telif Hakkı (c) 2026 Seydi Eryılmaz.

caller_profiles tablosu yalnız ORM'de tanımlıydı (M00 DATABASE_INVENTORY: migrasyonu
yok) ve `alembic check` CI'da başarısızdı. Tablo, create_all ile zaten oluşmuş
veritabanlarını bozmamak için yalnız yoksa oluşturulur. Şema ORM ile birebir aynıdır;
yeni alan eklenmez (doğum yılı alanı ADR-F3-01 için ayrı karar/paket konusudur).
"""

import sqlalchemy as sa
from alembic import op

revision = "025"
down_revision = "024"


def upgrade():
    bind = op.get_bind()
    if "caller_profiles" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "caller_profiles",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("phone", sa.String(40), nullable=False, server_default=""),
        sa.Column("plate", sa.String(32), nullable=False, server_default=""),
        sa.Column("name", sa.String(120), nullable=False, server_default=""),
        sa.Column("vehicle_model", sa.String(120), nullable=False, server_default=""),
        sa.Column("warranty_expires_at", sa.String(40), nullable=True),
        sa.Column("warranty_status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("maintenance_history_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("inspection_scores_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("user_preferences_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_caller_profiles_phone", "caller_profiles", ["phone"])
    op.create_index("ix_caller_profiles_plate", "caller_profiles", ["plate"])
    op.create_index("ix_caller_profiles_name", "caller_profiles", ["name"])


def downgrade():
    op.drop_index("ix_caller_profiles_name", table_name="caller_profiles")
    op.drop_index("ix_caller_profiles_plate", table_name="caller_profiles")
    op.drop_index("ix_caller_profiles_phone", table_name="caller_profiles")
    op.drop_table("caller_profiles")
