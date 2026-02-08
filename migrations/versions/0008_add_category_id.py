"""Add category_id to expense_receipts table."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0008_add_category_id"
down_revision = "0007_expense_receipt_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add category_id column to expense_receipts table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    
    # Add category_id column to expense_receipts table
    if 'expense_receipts' in existing_tables:
        columns = [col['name'] for col in inspector.get_columns('expense_receipts')]
        
        if 'category_id' not in columns:
            op.add_column('expense_receipts', 
                         sa.Column('category_id', sa.String(), nullable=True))
            
            # Create foreign key constraint to expense_categories
            try:
                op.create_foreign_key(
                    'fk_expense_receipts_category_id',
                    'expense_receipts',
                    'expense_categories',
                    ['category_id'],
                    ['id'],
                    ondelete='SET NULL'
                )
            except NotImplementedError:
                # SQLite cannot alter constraints in-place; skip FK but keep column for compatibility.
                pass
            
            # Create index for better query performance
            op.create_index('idx_expense_receipts_category', 'expense_receipts', ['category_id'])


def downgrade() -> None:
    """Remove category_id column from expense_receipts table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    if 'expense_receipts' in inspector.get_table_names():
        # Drop index
        if 'idx_expense_receipts_category' in [idx['name'] for idx in inspector.get_indexes('expense_receipts')]:
            op.drop_index('idx_expense_receipts_category', 'expense_receipts')
        
        # Drop foreign key
        if 'fk_expense_receipts_category_id' in [fk['name'] for fk in inspector.get_foreign_keys('expense_receipts')]:
            op.drop_constraint('fk_expense_receipts_category_id', 'expense_receipts', type_='foreignkey')
        
        # Drop column
        if 'category_id' in [col['name'] for col in inspector.get_columns('expense_receipts')]:
            op.drop_column('expense_receipts', 'category_id')
