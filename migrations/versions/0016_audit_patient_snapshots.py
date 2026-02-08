"""Add audit_patient_snapshots table for purgeable patient display snapshots.

Keeps audit_log append-only and stores optional readable patient info separately,
so snapshots can be purged/expired without rewriting audit_log.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0016_audit_patient_snapshots"
down_revision = "0015_manager_role_and_merge_permission"
branch_labels = None
depends_on = None


def _create_index_if_not_exists(name: str, table: str, columns: str) -> None:
    op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table}({columns})")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "audit_patient_snapshots" not in tables:
        op.create_table(
            "audit_patient_snapshots",
            sa.Column("audit_log_id", sa.Integer(), primary_key=True),
            sa.Column("audit_ts_epoch", sa.Integer(), nullable=False),
            sa.Column("patient_id", sa.Text(), nullable=True),
            sa.Column("patient_full_name", sa.Text(), nullable=False, server_default=""),
            sa.Column("patient_short_id", sa.Text(), nullable=False, server_default=""),
            sa.Column("patient_primary_page_number", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")),
            sa.ForeignKeyConstraint(["audit_log_id"], ["audit_log.id"], ondelete="CASCADE"),
        )

    _create_index_if_not_exists("idx_audit_snapshots_ts", "audit_patient_snapshots", "audit_ts_epoch")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_audit_snapshots_ts")
    op.drop_table("audit_patient_snapshots")

