"""Appointments schedule and receipt tracking."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_appointments_receipts"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "appointments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("patient_id", sa.Text(), nullable=True),
        sa.Column("patient_name", sa.Text(), nullable=True),
        sa.Column("patient_phone", sa.Text(), nullable=True),
        sa.Column("doctor_id", sa.Text(), nullable=False),
        sa.Column("doctor_label", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.Text(), nullable=False),
        sa.Column("ends_at", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="scheduled", nullable=False),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("room", sa.Text(), nullable=True),
        sa.Column("reminder_minutes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.Text(), server_default=sa.text("(datetime('now'))"), nullable=False),
        sa.Column("updated_at", sa.Text(), server_default=sa.text("(datetime('now'))"), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('scheduled','checked_in','in_progress','done','no_show','cancelled')",
            name="ck_appointments_status",
        ),
    )
    op.create_index(
        "idx_appointments_doctor_start",
        "appointments",
        ["doctor_id", "starts_at"],
        unique=True,
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_appointments_day ON appointments(substr(starts_at, 1, 10))")

    op.create_table(
        "receipt_sequences",
        sa.Column("year_key", sa.Text(), primary_key=True),
        sa.Column("last_number", sa.Integer(), nullable=False),
    )

    op.create_table(
        "receipts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("patient_id", sa.Text(), nullable=False),
        sa.Column("appointment_id", sa.Text(), nullable=True),
        sa.Column("issued_by_user_id", sa.Text(), nullable=True),
        sa.Column("number", sa.Text(), nullable=False, unique=True),
        sa.Column("issued_at", sa.Text(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locale", sa.Text(), nullable=False, server_default="en"),
        sa.Column("qr_payload", sa.Text(), nullable=True),
        sa.Column("pdf_path", sa.Text(), nullable=False),
        sa.Column("reprint_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reprinted_at", sa.Text(), nullable=True),
        sa.Column("meta_json", sa.Text(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["issued_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_receipts_patient", "receipts", ["patient_id"])
    op.create_index("idx_receipts_issued_at", "receipts", ["issued_at"])

    op.create_table(
        "receipt_reprints",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("receipt_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("reprinted_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["receipt_id"], ["receipts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )


def downgrade() -> None:
    op.drop_table("receipt_reprints")
    op.drop_index("idx_receipts_issued_at", table_name="receipts")
    op.drop_index("idx_receipts_patient", table_name="receipts")
    op.drop_table("receipts")
    op.drop_table("receipt_sequences")
    op.execute("DROP INDEX IF EXISTS idx_appointments_day")
    op.drop_index("idx_appointments_doctor_start", table_name="appointments")
    op.drop_table("appointments")
