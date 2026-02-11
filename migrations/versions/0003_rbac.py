"""RBAC tables and user metadata expansion."""

from __future__ import annotations

from datetime import datetime, UTC

from alembic import op
import sqlalchemy as sa


revision = "0003_rbac"
down_revision = "0002_appointments_receipts"
branch_labels = None
depends_on = None


ROLES = (
    ("Admin", "Full administrative access"),
    ("Doctor", "Clinical operations"),
    ("Reception", "Front-desk operations"),
)


LEGACY_PERMISSIONS = (
    ("patients:view", "View patients"),
    ("patients:edit", "Edit patients"),
    ("patients:delete", "Delete patients"),
    ("payments:view", "View payments"),
    ("payments:edit", "Edit payments"),
    ("payments:delete", "Delete payments"),
    ("reports:view", "View reports"),
    ("appointments:view", "View appointments"),
    ("appointments:edit", "Edit appointments"),
    ("receipts:view", "View receipts"),
    ("receipts:issue", "Issue receipts"),
    ("receipts:reprint", "Reprint receipts"),
    ("diagnostics:view", "View diagnosis"),
    ("backup:create", "Create backups"),
    ("backup:restore", "Restore backups"),
    ("users:manage", "Manage legacy users"),
)

SPEC_PERMISSIONS = (
    ("patient.view", "View patients (new)"),
    ("appointment.manage", "Manage appointments"),
    ("receipt.manage", "Issue receipts"),
    ("diagnosis.manage", "Edit diagnosis"),
    ("admin.user.manage", "Manage users"),
)

PERMISSIONS = LEGACY_PERMISSIONS + SPEC_PERMISSIONS


ROLE_PERMISSIONS = {
    "Admin": [code for code, _ in PERMISSIONS],
    "Doctor": [
        "patients:view",
        "patients:edit",
        "payments:view",
        "payments:edit",
        "reports:view",
        "appointments:view",
        "appointments:edit",
        "receipts:view",
        "receipts:issue",
        "diagnostics:view",
        "patient.view",
        "appointment.manage",
        "receipt.manage",
        "diagnosis.manage",
    ],
    "Reception": [
        "patients:view",
        "payments:view",
        "appointments:view",
        "receipts:view",
        "receipts:issue",
        "patient.view",
        "appointment.manage",
        "receipt.manage",
    ],
}


LEGACY_ROLE_MAP = {
    "admin": "Admin",
    "doctor": "Doctor",
    "assistant": "Reception",
}


def _ensure_user_columns() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "users" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("users")}
    columns_to_add: list[tuple[str, sa.Column]] = []
    if "full_name" not in existing:
        columns_to_add.append(("full_name", sa.Column("full_name", sa.Text(), nullable=True)))
    if "phone" not in existing:
        columns_to_add.append(("phone", sa.Column("phone", sa.Text(), nullable=True)))
    if "updated_at" not in existing:
        columns_to_add.append(("updated_at", sa.Column("updated_at", sa.Text(), nullable=True)))
    for name, column in columns_to_add:
        op.add_column("users", column)
    if columns_to_add:
        from datetime import UTC
        now = datetime.now(UTC).isoformat()
        bind.execute(sa.text("UPDATE users SET updated_at = COALESCE(updated_at, :now)"), {"now": now})
        bind.execute(sa.text("UPDATE users SET full_name = COALESCE(full_name, username)"))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _ensure_user_columns()

    if "roles" not in inspector.get_table_names():
        op.create_table(
            "roles",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.Text(), nullable=False, unique=True),
            sa.Column("description", sa.Text(), nullable=True),
        )

    if "permissions" not in inspector.get_table_names():
        op.create_table(
            "permissions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.Text(), nullable=False, unique=True),
            sa.Column("description", sa.Text(), nullable=True),
        )

    if "role_permissions" not in inspector.get_table_names():
        op.create_table(
            "role_permissions",
            sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
            sa.Column(
                "permission_id",
                sa.Integer(),
                sa.ForeignKey("permissions.id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )

    if "user_roles" not in inspector.get_table_names():
        op.create_table(
            "user_roles",
            sa.Column(
                "user_id",
                sa.Text(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "role_id",
                sa.Integer(),
                sa.ForeignKey("roles.id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )

    # Seed roles and permissions
    for name, desc in ROLES:
        bind.execute(
            sa.text("INSERT OR IGNORE INTO roles(name, description) VALUES (:name, :description)"),
            {"name": name, "description": desc},
        )

    for code, desc in PERMISSIONS:
        bind.execute(
            sa.text("INSERT OR IGNORE INTO permissions(code, description) VALUES (:code, :description)"),
            {"code": code, "description": desc},
        )

    role_ids = {
        name: bind.execute(sa.text("SELECT id FROM roles WHERE name = :name"), {"name": name}).scalar()
        for name, _ in ROLES
    }
    perm_ids = {
        code: bind.execute(sa.text("SELECT id FROM permissions WHERE code = :code"), {"code": code}).scalar()
        for code, _ in PERMISSIONS
    }

    for role_name, codes in ROLE_PERMISSIONS.items():
        role_id = role_ids.get(role_name)
        if not role_id:
            continue
        for code in codes:
            perm_id = perm_ids.get(code)
            if not perm_id:
                continue
            bind.execute(
                sa.text(
                    "INSERT OR IGNORE INTO role_permissions(role_id, permission_id) VALUES (:r, :p)"
                ),
                {"r": role_id, "p": perm_id},
            )

    # Map existing users to roles based on legacy column
    user_cols = {col["name"] for col in inspector.get_columns("users")}
    if "role" in user_cols:
        for legacy_value, target_role in LEGACY_ROLE_MAP.items():
            role_id = role_ids.get(target_role)
            if not role_id:
                continue
            bind.execute(
                sa.text(
                    "INSERT OR IGNORE INTO user_roles(user_id, role_id) "
                    "SELECT id, :role_id FROM users WHERE lower(role)=:legacy AND is_active=1"
                ),
                {"role_id": role_id, "legacy": legacy_value},
            )


def downgrade() -> None:
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")

    with op.batch_alter_table("users") as batch:
        batch.drop_column("updated_at")
        batch.drop_column("phone")
        batch.drop_column("full_name")
