"""Add parent_payment_id to support treatment-based payments."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017_treatment_payments"
down_revision = "0016_audit_patient_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add parent_payment_id column to payments table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("payments")}

    if "parent_payment_id" not in cols:
        op.add_column(
            "payments",
            sa.Column("parent_payment_id", sa.Text(), nullable=True),
        )
        # Create index for faster queries
        op.execute(
            "CREATE INDEX IF NOT EXISTS idx_payments_parent ON payments(parent_payment_id)"
        )
        # Add foreign key constraint (self-referencing)
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_payments_parent_exists
            BEFORE INSERT ON payments
            WHEN NEW.parent_payment_id IS NOT NULL
            BEGIN
                SELECT CASE
                    WHEN NOT EXISTS (
                        SELECT 1 FROM payments WHERE id = NEW.parent_payment_id
                    )
                    THEN RAISE(ABORT, 'Parent payment does not exist')
                END;
            END;
            """
        )


def downgrade() -> None:
    """Remove parent_payment_id column."""
    op.execute("DROP TRIGGER IF EXISTS trg_payments_parent_exists")
    op.execute("DROP INDEX IF EXISTS idx_payments_parent")
    op.drop_column("payments", "parent_payment_id")
