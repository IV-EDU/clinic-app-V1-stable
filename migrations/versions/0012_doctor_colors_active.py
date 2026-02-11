"""Add is_active to doctor_colors for soft delete."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0012_doctor_colors_active"
down_revision = "0011_doctor_colors_label"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "doctor_colors" not in tables:
        return
    cols = {c["name"] for c in inspector.get_columns("doctor_colors")}
    if "is_active" not in cols:
        op.add_column("doctor_colors", sa.Column("is_active", sa.Integer(), nullable=True, server_default="1"))
        op.execute("UPDATE doctor_colors SET is_active = 1 WHERE is_active IS NULL")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "doctor_colors" not in tables:
        return
    cols = {c["name"] for c in inspector.get_columns("doctor_colors")}
    if "is_active" in cols:
        op.drop_column("doctor_colors", "is_active")
