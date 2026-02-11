"""Add doctor_label column to doctor_colors for custom doctor entries."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_doctor_colors_label"
down_revision = "0010_theme_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("doctor_colors")} if "doctor_colors" in inspector.get_table_names() else set()
    if "doctor_label" not in columns and "doctor_colors" in inspector.get_table_names():
        op.add_column("doctor_colors", sa.Column("doctor_label", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("doctor_colors")} if "doctor_colors" in inspector.get_table_names() else set()
    if "doctor_label" in columns:
        op.drop_column("doctor_colors", "doctor_label")
