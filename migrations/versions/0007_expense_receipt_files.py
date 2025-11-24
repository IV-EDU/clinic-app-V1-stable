"""Add file attachment support to expense receipts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from datetime import datetime, timezone


revision = "0007_expense_receipt_files"
down_revision = "0006_expense_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add file attachment fields to expense receipts."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    
    # Add file attachment fields to existing expense_receipts table
    if 'expense_receipts' in existing_tables:
        # Check if columns already exist
        columns = [col['name'] for col in inspector.get_columns('expense_receipts')]
        
        if 'receipt_file_path' not in columns:
            op.add_column('expense_receipts', 
                         sa.Column('receipt_file_path', sa.String(), nullable=True))
        
        if 'receipt_file_original_name' not in columns:
            op.add_column('expense_receipts', 
                         sa.Column('receipt_file_original_name', sa.String(), nullable=True))
        
        if 'receipt_file_type' not in columns:
            op.add_column('expense_receipts', 
                         sa.Column('receipt_file_type', sa.String(), nullable=True))
        
        if 'receipt_file_size' not in columns:
            op.add_column('expense_receipts', 
                         sa.Column('receipt_file_size', sa.Integer(), nullable=True))
        
        if 'receipt_file_hash' not in columns:
            op.add_column('expense_receipts', 
                         sa.Column('receipt_file_hash', sa.String(), nullable=True))
        
        if 'receipt_status' not in columns:
            op.add_column('expense_receipts', 
                         sa.Column('receipt_status', sa.String(), nullable=False, default='pending'))
        
        if 'approval_date' not in columns:
            op.add_column('expense_receipts', 
                         sa.Column('approval_date', sa.String(), nullable=True))
        
        if 'approved_by' not in columns:
            op.add_column('expense_receipts', 
                         sa.Column('approved_by', sa.String(), nullable=True))
        
        if 'approval_notes' not in columns:
            op.add_column('expense_receipts', 
                         sa.Column('approval_notes', sa.Text(), nullable=True))
    
    # Create expense_receipts_attachments table for multiple files per receipt
    if 'expense_receipts_attachments' not in existing_tables:
        op.create_table(
            'expense_receipts_attachments',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('expense_receipt_id', sa.String(), nullable=False),
            sa.Column('filename', sa.String(), nullable=False),
            sa.Column('original_filename', sa.String(), nullable=False),
            sa.Column('file_path', sa.String(), nullable=False),
            sa.Column('file_type', sa.String(), nullable=False),
            sa.Column('file_size', sa.Integer(), nullable=False),
            sa.Column('file_hash', sa.String(), nullable=False),
            sa.Column('mime_type', sa.String(), nullable=True),
            sa.Column('upload_date', sa.String(), nullable=False),
            sa.Column('uploaded_by', sa.String(), nullable=False),
            sa.Column('is_primary', sa.Integer(), nullable=False, default=0),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['expense_receipt_id'], ['expense_receipts.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ondelete='RESTRICT')
        )
        op.create_index('idx_expense_attachments_receipt', 'expense_receipts_attachments', ['expense_receipt_id'])
        op.create_index('idx_expense_attachments_hash', 'expense_receipts_attachments', ['file_hash'])
    
    # Add default categories if expense_categories table exists but is empty
    if 'expense_categories' in existing_tables:
        existing_categories = set()
        try:
            result = bind.execute(sa.text("SELECT name FROM expense_categories"))
            existing_categories = {row[0] for row in result.fetchall()}
        except:
            pass
        
        if not existing_categories:
            defaults = [
                ('Travel', 'Transportation and travel expenses', '#e74c3c'),
                ('Meals', 'Business meals and entertainment', '#f39c12'),
                ('Office Supplies', 'Office materials and supplies', '#3498db'),
                ('Software', 'Software licenses and subscriptions', '#9b59b6'),
                ('Equipment', 'Equipment purchases and maintenance', '#1abc9c'),
                ('Maintenance', 'Equipment maintenance and repairs', '#e67e22'),
                ('Utilities', 'Utility bills and services', '#34495e'),
                ('Professional Services', 'Consulting and professional fees', '#95a5a6')
            ]
            
            for name, description, color in defaults:
                if name not in existing_categories:
                    op.execute(
                        f"""INSERT INTO expense_categories (name, description, color) VALUES ('{name}', '{description}', '{color}')"""
                    )


def downgrade() -> None:
    """Remove file attachment support from expense receipts."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # Drop the attachments table
    if 'expense_receipts_attachments' in inspector.get_table_names():
        op.drop_table('expense_receipts_attachments')
    
    # Remove columns from expense_receipts table
    columns_to_drop = [
        'receipt_file_path',
        'receipt_file_original_name', 
        'receipt_file_type',
        'receipt_file_size',
        'receipt_file_hash',
        'receipt_status',
        'approval_date',
        'approved_by',
        'approval_notes'
    ]
    
    if 'expense_receipts' in inspector.get_table_names():
        for column in columns_to_drop:
            if column in [col['name'] for col in inspector.get_columns('expense_receipts')]:
                op.drop_column('expense_receipts', column)