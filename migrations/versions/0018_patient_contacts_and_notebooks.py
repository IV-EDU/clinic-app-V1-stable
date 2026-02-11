"""Add multiple patient phones and optional notebook colors."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0018_patient_contacts_and_notebooks"
down_revision = "0017_treatment_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("patient_phones"):
        op.create_table(
            "patient_phones",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
            sa.Column("phone", sa.Text(), nullable=False),
            sa.Column("phone_normalized", sa.String(40), nullable=False),
            sa.Column("label", sa.String(60), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.UniqueConstraint("patient_id", "phone_normalized", name="uq_patient_phones_patient_phone"),
        )
        op.create_index("ix_patient_phones_patient_id", "patient_phones", ["patient_id"])
        op.create_index("ix_patient_phones_phone_normalized", "patient_phones", ["phone_normalized"])

    if not inspector.has_table("notebooks"):
        op.create_table(
            "notebooks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False, unique=True),
            sa.Column("color", sa.String(7), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
        )
        op.create_index("ix_notebooks_active", "notebooks", ["active"])

    # Backfill one phone row from existing primary patient phone.
    op.execute(
        """
        INSERT OR IGNORE INTO patient_phones (id, patient_id, phone, phone_normalized, label, is_primary)
        SELECT lower(hex(randomblob(16))), p.id, p.phone, trim(p.phone), 'Primary', 1
          FROM patients p
         WHERE p.phone IS NOT NULL
           AND trim(p.phone) <> ''
        """
    )


def downgrade() -> None:
    op.drop_index("ix_notebooks_active", table_name="notebooks")
    op.drop_table("notebooks")
    op.drop_index("ix_patient_phones_phone_normalized", table_name="patient_phones")
    op.drop_index("ix_patient_phones_patient_id", table_name="patient_phones")
    op.drop_table("patient_phones")
