"""Add theme_settings table for UI theme variables."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0010_theme_settings"
down_revision = "0009_simple_expenses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "theme_settings" not in existing_tables:
        op.create_table(
            "theme_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("setting_key", sa.String(length=255), nullable=False, unique=True),
            sa.Column("setting_value", sa.Text(), nullable=True),
            sa.Column("category", sa.String(length=100), nullable=True),
            sa.Column("updated_at", sa.String(length=64), nullable=True),
        )
        op.create_index("idx_theme_settings_key", "theme_settings", ["setting_key"], unique=True)
        op.create_index("idx_theme_settings_category", "theme_settings", ["category"])


def downgrade() -> None:
    op.drop_index("idx_theme_settings_category", table_name="theme_settings")
    op.drop_index("idx_theme_settings_key", table_name="theme_settings")
    op.drop_table("theme_settings")
