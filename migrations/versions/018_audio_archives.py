"""Create audio_archives table for legal retention and compression compliance.

Revision ID: 018
Revises: 017
Create Date: 2026-11-02 09:35:00.000000

ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim amaçlı olarak paylaşılmıştır.
"""

from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"


def upgrade():
    op.create_table(
        "audio_archives",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("call_session_id", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("caller_phone", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("codec", sa.String(length=20), nullable=False, server_default="opus"),
        sa.Column("channels", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("sample_rate", sa.Integer(), nullable=False, server_default="8000"),
        sa.Column("duration_sec", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("raw_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compressed_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compression_ratio_percent", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("sha256_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("raw_sha256_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("hmac_signature", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("file_path", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("retention_years", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("expires_at", sa.String(length=40), nullable=True),
        sa.Column("is_redacted", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.String(length=40), nullable=False),
    )
    op.create_index("ix_audio_archives_conversation_id", "audio_archives", ["conversation_id"])
    op.create_index("ix_audio_archives_call_session_id", "audio_archives", ["call_session_id"])
    op.create_index("ix_audio_archives_status", "audio_archives", ["status"])
    op.create_index("ix_audio_archives_created_at", "audio_archives", ["created_at"])
    op.create_index("ix_audio_archives_expires_at", "audio_archives", ["expires_at"])


def downgrade():
    op.drop_index("ix_audio_archives_expires_at", table_name="audio_archives")
    op.drop_index("ix_audio_archives_created_at", table_name="audio_archives")
    op.drop_index("ix_audio_archives_status", table_name="audio_archives")
    op.drop_index("ix_audio_archives_call_session_id", table_name="audio_archives")
    op.drop_index("ix_audio_archives_conversation_id", table_name="audio_archives")
    op.drop_table("audio_archives")

