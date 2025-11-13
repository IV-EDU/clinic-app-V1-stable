"""Add expense receipt permissions to RBAC system."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_expense_permissions"
down_revision = "0005_expense_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # Define expense permissions
    EXPENSE_PERMISSIONS = [
        ("expenses:view", "View expense receipts and related data"),
        ("expenses:edit", "Create, edit, and delete expense receipts"),
    ]
    
    # Add expense permissions if they don't exist
    for code, desc in EXPENSE_PERMISSIONS:
        bind.execute(
            sa.text("INSERT OR IGNORE INTO permissions(code, description) VALUES (:code, :description)"),
            {"code": code, "description": desc},
        )
    
    # Get permission IDs for expense permissions
    expense_permission_ids = {}
    for code, _ in EXPENSE_PERMISSIONS:
        perm_id = bind.execute(
            sa.text("SELECT id FROM permissions WHERE code = :code"), 
            {"code": code}
        ).scalar()
        if perm_id:
            expense_permission_ids[code] = perm_id
    
    # Get role IDs
    role_ids = {}
    roles = ["Admin", "Doctor", "Reception"]
    for role_name in roles:
        role_id = bind.execute(
            sa.text("SELECT id FROM roles WHERE name = :name"), 
            {"name": role_name}
        ).scalar()
        if role_id:
            role_ids[role_name] = role_id
    
    # Assign expense permissions to roles
    # Admin gets all expense permissions
    admin_id = role_ids.get("Admin")
    expenses_view_id = expense_permission_ids.get("expenses:view")
    expenses_edit_id = expense_permission_ids.get("expenses:edit")
    
    if admin_id and expenses_view_id:
        bind.execute(
            sa.text(
                "INSERT OR IGNORE INTO role_permissions(role_id, permission_id) VALUES (:r, :p)"
            ),
            {"r": admin_id, "p": expenses_view_id},
        )
    
    if admin_id and expenses_edit_id:
        bind.execute(
            sa.text(
                "INSERT OR IGNORE INTO role_permissions(role_id, permission_id) VALUES (:r, :p)"
            ),
            {"r": admin_id, "p": expenses_edit_id},
        )
    
    # Doctor gets viewing permissions
    doctor_id = role_ids.get("Doctor")
    if doctor_id and expenses_view_id:
        bind.execute(
            sa.text(
                "INSERT OR IGNORE INTO role_permissions(role_id, permission_id) VALUES (:r, :p)"
            ),
            {"r": doctor_id, "p": expenses_view_id},
        )
    
    # Reception gets viewing permissions for front desk operations
    reception_id = role_ids.get("Reception")
    if reception_id and expenses_view_id:
        bind.execute(
            sa.text(
                "INSERT OR IGNORE INTO role_permissions(role_id, permission_id) VALUES (:r, :p)"
            ),
            {"r": reception_id, "p": expenses_view_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    
    # Get expense permission IDs
    expense_permission_ids = {}
    expense_codes = ["expenses:view", "expenses:edit"]
    for code in expense_codes:
        perm_id = bind.execute(
            sa.text("SELECT id FROM permissions WHERE code = :code"), 
            {"code": code}
        ).scalar()
        if perm_id:
            expense_permission_ids[code] = perm_id
    
    # Remove role permission associations
    for perm_id in expense_permission_ids.values():
        bind.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_id = :perm_id"),
            {"perm_id": perm_id}
        )
    
    # Remove permissions
    for code in expense_codes:
        bind.execute(
            sa.text("DELETE FROM permissions WHERE code = :code"),
            {"code": code}
        )