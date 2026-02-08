"""Allow legacy manager role and add patients:merge permission.

This migration fixes:
- users.role CHECK constraint so selecting "Manager" does not fail.
- adds a dedicated permission for merging patients and grants it to Admin/Manager.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0015_manager_role_and_merge_permission"
down_revision = "0014_patient_pages_and_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # Add new permission (RBAC) if the RBAC tables exist.
    if {"roles", "permissions", "role_permissions"}.issubset(tables):
        bind.execute(
            sa.text(
                "INSERT OR IGNORE INTO permissions(code, description) VALUES (:code, :desc)"
            ),
            {"code": "patients:merge", "desc": "Merge patients"},
        )
        role_ids = {
            name: bind.execute(
                sa.text("SELECT id FROM roles WHERE name=:name"), {"name": name}
            ).scalar()
            for name in ("Admin", "Manager")
        }
        perm_id = bind.execute(
            sa.text("SELECT id FROM permissions WHERE code=:code"),
            {"code": "patients:merge"},
        ).scalar()
        if perm_id:
            for role_id in role_ids.values():
                if not role_id:
                    continue
                bind.execute(
                    sa.text(
                        "INSERT OR IGNORE INTO role_permissions(role_id, permission_id) VALUES (:r, :p)"
                    ),
                    {"r": role_id, "p": perm_id},
                )

    # Expand legacy CHECK constraint on users.role to allow manager.
    if "users" in tables:
        with op.batch_alter_table("users", recreate="always") as batch_op:
            try:
                batch_op.drop_constraint("ck_users_role", type_="check")
            except Exception:
                # SQLite reflection sometimes fails to expose check constraint names.
                pass
            batch_op.create_check_constraint(
                "ck_users_role",
                "role IN ('admin','doctor','assistant','manager')",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" in tables:
        with op.batch_alter_table("users", recreate="always") as batch_op:
            try:
                batch_op.drop_constraint("ck_users_role", type_="check")
            except Exception:
                pass
            batch_op.create_check_constraint(
                "ck_users_role",
                "role IN ('admin','doctor','assistant')",
            )

    # Keep the permission row (do not delete) to avoid breaking existing configs.
