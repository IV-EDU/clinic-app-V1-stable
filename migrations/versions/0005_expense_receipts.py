"""Add expense receipts system for dental materials tracking."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from datetime import datetime, timezone


revision = "0005_expense_receipts"
down_revision = "0004_performance_indices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create expense receipts tables and initial data."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    
    # Create suppliers table if not exists
    if 'suppliers' not in existing_tables:
        op.create_table(
            'suppliers',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('contact_person', sa.String(), nullable=True),
            sa.Column('phone', sa.String(), nullable=True),
            sa.Column('email', sa.String(), nullable=True),
            sa.Column('address', sa.Text(), nullable=True),
            sa.Column('tax_number', sa.String(), nullable=True),
            sa.Column('is_active', sa.Integer(), nullable=False, default=1),
            sa.Column('created_at', sa.String(), nullable=True),
            sa.Column('updated_at', sa.String(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('idx_suppliers_name', 'suppliers', ['name'])
        op.create_index('idx_suppliers_active', 'suppliers', ['is_active'])

    # Create expense_categories table if not exists
    if 'expense_categories' not in existing_tables:
        op.create_table(
            'expense_categories',
            sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
            sa.Column('name', sa.String(), nullable=False, unique=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('color', sa.String(), nullable=False, default='#3498db'),
            sa.PrimaryKeyConstraint('id')
        )

    # Create materials table if not exists
    if 'materials' not in existing_tables:
        op.create_table(
            'materials',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('category_id', sa.Integer(), nullable=True),
            sa.Column('unit', sa.String(), nullable=False, default='piece'),
            sa.Column('price_per_unit', sa.Float(), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('supplier_id', sa.String(), nullable=True),
            sa.Column('is_active', sa.Integer(), nullable=False, default=1),
            sa.Column('created_at', sa.String(), nullable=True),
            sa.Column('updated_at', sa.String(), nullable=True),
            sa.ForeignKeyConstraint(['category_id'], ['expense_categories.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('idx_materials_name', 'materials', ['name'])
        op.create_index('idx_materials_category', 'materials', ['category_id'])
        op.create_index('idx_materials_supplier', 'materials', ['supplier_id'])
        op.create_index('idx_materials_active', 'materials', ['is_active'])

    # Create expense_receipts table if not exists
    if 'expense_receipts' not in existing_tables:
        op.create_table(
            'expense_receipts',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('serial_number', sa.String(), nullable=False, unique=True),
            sa.Column('supplier_id', sa.String(), nullable=False),
            sa.Column('receipt_date', sa.String(), nullable=False),
            sa.Column('total_amount', sa.Float(), nullable=False, default=0.0),
            sa.Column('tax_amount', sa.Float(), nullable=False, default=0.0),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column('receipt_image_path', sa.String(), nullable=True),
            sa.Column('created_by', sa.String(), nullable=False),
            sa.Column('created_at', sa.String(), nullable=False),
            sa.Column('updated_at', sa.String(), nullable=True),
            sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ondelete='RESTRICT'),
            sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('idx_expense_receipts_serial', 'expense_receipts', ['serial_number'], unique=True)
        op.create_index('idx_expense_receipts_supplier', 'expense_receipts', ['supplier_id'])
        op.create_index('idx_expense_receipts_date', 'expense_receipts', ['receipt_date'])
        op.create_index('idx_expense_receipts_created_by', 'expense_receipts', ['created_by'])
        op.create_index('idx_expense_receipts_supplier_date', 'expense_receipts', ['supplier_id', 'receipt_date'])

    # Create expense_receipt_items table if not exists
    if 'expense_receipt_items' not in existing_tables:
        op.create_table(
            'expense_receipt_items',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('expense_receipt_id', sa.String(), nullable=False),
            sa.Column('material_id', sa.String(), nullable=True),
            sa.Column('material_name', sa.String(), nullable=False),
            sa.Column('quantity', sa.Float(), nullable=False),
            sa.Column('unit_price', sa.Float(), nullable=False),
            sa.Column('total_price', sa.Float(), nullable=False),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(['expense_receipt_id'], ['expense_receipts.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['material_id'], ['materials.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('idx_expense_receipt_items_receipt', 'expense_receipt_items', ['expense_receipt_id'])
        op.create_index('idx_expense_receipt_items_material', 'expense_receipt_items', ['material_id'])

    # Create expense_sequences table for serial number generation if not exists
    if 'expense_sequences' not in existing_tables:
        op.create_table(
            'expense_sequences',
            sa.Column('year_key', sa.String(), nullable=False, primary_key=True),
            sa.Column('last_number', sa.Integer(), nullable=False, default=0),
            sa.UniqueConstraint('year_key')
        )

    # Create receipt_settings table if not exists
    if 'receipt_settings' not in existing_tables:
        op.create_table(
            'receipt_settings',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('setting_key', sa.String(), nullable=False, unique=True),
            sa.Column('setting_value', sa.Text(), nullable=True),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('updated_at', sa.String(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('idx_receipt_settings_key', 'receipt_settings', ['setting_key'], unique=True)

    # Insert default expense categories if they don't exist
    if 'expense_categories' in inspector.get_table_names():
        existing_categories = set()
        try:
            result = bind.execute(sa.text("SELECT name FROM expense_categories"))
            existing_categories = {row[0] for row in result.fetchall()}
        except:
            pass
        
        defaults = [
            ('Dental Materials', 'Materials used for dental procedures', '#e74c3c'),
            ('Equipment', 'Dental equipment and instruments', '#3498db'),
            ('Office Supplies', 'Office and administrative supplies', '#f39c12'),
            ('Maintenance', 'Equipment maintenance and repair', '#9b59b6')
        ]
        
        for name, description, color in defaults:
            if name not in existing_categories:
                op.execute(
                    f"""INSERT INTO expense_categories (name, description, color) VALUES ('{name}', '{description}', '{color}')"""
                )

    # Insert default receipt settings if they don't exist
    if 'receipt_settings' in inspector.get_table_names():
        existing_settings = set()
        try:
            result = bind.execute(sa.text("SELECT setting_key FROM receipt_settings"))
            existing_settings = {row[0] for row in result.fetchall()}
        except:
            pass
        
        now = datetime.now(timezone.utc).isoformat()
        defaults = [
            ('clinic-logo', 'logo.png', 'Clinic logo for receipts'),
            ('clinic-name', 'Dr. Lina Dental Clinic', 'Clinic name for receipts'),
            ('clinic-address', 'Main Street, Cairo, Egypt', 'Clinic address'),
            ('clinic-phone', '+20 XXX XXX XXXX', 'Clinic phone number'),
            ('tax-rate', '14', 'Default tax rate percentage'),
        ]
        
        for setting_key, setting_value, description in defaults:
            if setting_key not in existing_settings:
                op.execute(
                    f"""INSERT INTO receipt_settings (id, setting_key, setting_value, description, updated_at)
                    VALUES ('setting-{setting_key}', '{setting_key}', '{setting_value}', '{description}', '{now}')"""
                )


def downgrade() -> None:
    """Remove expense receipts tables."""
    # Drop tables in reverse order due to foreign key dependencies
    op.drop_index('idx_receipt_settings_key', 'receipt_settings')
    op.drop_table('receipt_settings')
    
    op.drop_index('idx_expense_receipt_items_material', 'expense_receipt_items')
    op.drop_index('idx_expense_receipt_items_receipt', 'expense_receipt_items')
    op.drop_table('expense_receipt_items')
    
    op.drop_index('idx_expense_receipts_supplier_date', 'expense_receipts')
    op.drop_index('idx_expense_receipts_created_by', 'expense_receipts')
    op.drop_index('idx_expense_receipts_date', 'expense_receipts')
    op.drop_index('idx_expense_receipts_supplier', 'expense_receipts')
    op.drop_index('idx_expense_receipts_serial', 'expense_receipts')
    op.drop_table('expense_receipts')
    
    op.drop_table('expense_sequences')
    
    op.drop_index('idx_materials_active', 'materials')
    op.drop_index('idx_materials_supplier', 'materials')
    op.drop_index('idx_materials_category', 'materials')
    op.drop_index('idx_materials_name', 'materials')
    op.drop_table('materials')
    
    op.drop_table('expense_categories')
    
    op.drop_index('idx_suppliers_active', 'suppliers')
    op.drop_index('idx_suppliers_name', 'suppliers')
    op.drop_table('suppliers')