"""Add doctor reference fields to payments table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0013_payments_doctor_fields"
down_revision = "0012_doctor_colors_active"
branch_labels = None
depends_on = None


ANY_DOCTOR_ID = "any-doctor"
ANY_DOCTOR_LABEL = "Any Doctor"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {col["name"] for col in inspector.get_columns("payments")}

    if "doctor_id" not in cols:
        op.add_column("payments", sa.Column("doctor_id", sa.Text(), nullable=True))
    if "doctor_label" not in cols:
        op.add_column("payments", sa.Column("doctor_label", sa.Text(), nullable=True))

    # Backfill existing rows to a safe default doctor
    op.execute(
        """
        UPDATE payments
        SET doctor_id = COALESCE(NULLIF(TRIM(doctor_id), ''), '{any_id}'),
            doctor_label = COALESCE(NULLIF(TRIM(doctor_label), ''), '{any_label}')
        """.format(any_id=ANY_DOCTOR_ID, any_label=ANY_DOCTOR_LABEL)
    )


def downgrade() -> None:
    op.drop_column("payments", "doctor_label")
    op.drop_column("payments", "doctor_id")
