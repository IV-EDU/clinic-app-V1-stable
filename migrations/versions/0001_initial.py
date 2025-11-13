"""Initial schema for Clinic App."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _create_index_if_not_exists(name: str, table: str, columns: str) -> None:
    op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table}({columns})")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "patients" not in tables:
        op.create_table(
            "patients",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("short_id", sa.Text(), nullable=True),
            sa.Column("full_name", sa.Text(), nullable=False),
            sa.Column("phone", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), server_default=sa.text("(datetime('now'))"), nullable=False),
        )
    else:
        patient_cols = {col["name"] for col in inspector.get_columns("patients")}
        if "created_at" not in patient_cols:
            op.add_column(
                "patients",
                sa.Column("created_at", sa.Text(), server_default=sa.text("(datetime('now'))"), nullable=False),
            )

    _create_index_if_not_exists("idx_patients_name", "patients", "full_name")
    _create_index_if_not_exists("idx_patients_phone", "patients", "phone")

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("username", sa.Text(), nullable=False, unique=True),
            sa.Column("password_hash", sa.Text(), nullable=False),
            sa.Column("role", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.Text(), nullable=True, server_default=sa.text("(datetime('now'))")),
            sa.Column("last_login_at", sa.Text(), nullable=True),
            sa.CheckConstraint("role IN ('admin','doctor','assistant')", name="ck_users_role"),
        )

    if "payments" not in tables:
        op.create_table(
            "payments",
            sa.Column("id", sa.Text(), primary_key=True),
            sa.Column("patient_id", sa.Text(), nullable=False),
            sa.Column("paid_at", sa.Text(), nullable=False),
            sa.Column("amount_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("method", sa.Text(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), server_default=sa.text("(datetime('now'))"), nullable=False),
            sa.Column("treatment", sa.Text(), nullable=True),
            sa.Column("remaining_cents", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("total_amount_cents", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("examination_flag", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("followup_flag", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("discount_cents", sa.Integer(), nullable=True, server_default="0"),
            sa.ForeignKeyConstraint(["patient_id"], ["patients.id"], ondelete="CASCADE"),
        )
    else:
        payment_cols = {col["name"] for col in inspector.get_columns("payments")}
        for name, col_type, default in [
            ("treatment", sa.Text(), None),
            ("remaining_cents", sa.Integer(), "0"),
            ("total_amount_cents", sa.Integer(), "0"),
            ("examination_flag", sa.Integer(), "0"),
            ("followup_flag", sa.Integer(), "0"),
            ("discount_cents", sa.Integer(), "0"),
        ]:
            if name not in payment_cols:
                op.add_column(
                    "payments",
                    sa.Column(
                        name,
                        col_type,
                        nullable=True,
                        server_default=sa.text(default) if default is not None else None,
                    ),
                )

    _create_index_if_not_exists("idx_payments_patient", "payments", "patient_id")
    _create_index_if_not_exists("idx_payments_paid_at", "payments", "paid_at")

    if "audit_log" not in tables:
        op.create_table(
            "audit_log",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("actor_user_id", sa.Text(), nullable=True),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("entity", sa.Text(), nullable=True),
            sa.Column("entity_id", sa.Text(), nullable=True),
            sa.Column("ts", sa.Text(), nullable=False, server_default=sa.text("(datetime('now'))")),
            sa.Column("result", sa.Text(), nullable=False, server_default="ok"),
            sa.Column("meta_json_redacted", sa.Text(), nullable=False, server_default="{}"),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        )

    _create_index_if_not_exists("idx_audit_ts", "audit_log", "ts")
    _create_index_if_not_exists("idx_audit_entity", "audit_log", "entity, entity_id")

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS audit_log_no_update
        BEFORE UPDATE ON audit_log
        BEGIN
            SELECT RAISE(FAIL, 'audit log is append-only');
        END;
        """
    )
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
        BEFORE DELETE ON audit_log
        BEGIN
            SELECT RAISE(FAIL, 'audit log is append-only');
        END;
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_delete")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update")
    op.execute("DROP INDEX IF EXISTS idx_audit_entity")
    op.execute("DROP INDEX IF EXISTS idx_audit_ts")
    op.drop_table("audit_log")

    op.execute("DROP INDEX IF EXISTS idx_payments_paid_at")
    op.execute("DROP INDEX IF EXISTS idx_payments_patient")
    op.drop_table("payments")
    op.drop_table("users")

    op.execute("DROP INDEX IF EXISTS idx_patients_phone")
    op.execute("DROP INDEX IF EXISTS idx_patients_name")
    op.drop_table("patients")
