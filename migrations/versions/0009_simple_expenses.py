"""Add simple expenses table for easy expense tracking."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from datetime import datetime, timezone


revision = "0009_simple_expenses"
down_revision = "0008_add_category_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create simple expenses table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    
    # Create simple_expenses table
    if 'simple_expenses' not in existing_tables:
        op.create_table(
            'simple_expenses',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('receipt_date', sa.String(), nullable=False),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('created_by', sa.String(), nullable=False),
            sa.Column('created_at', sa.String(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT')
        )
        op.create_index('idx_simple_expenses_date', 'simple_expenses', ['receipt_date'])
        op.create_index('idx_simple_expenses_created_by', 'simple_expenses', ['created_by'])


def downgrade() -> None:
    """Remove simple expenses table."""
    op.drop_index('idx_simple_expenses_created_by', 'simple_expenses')
    op.drop_index('idx_simple_expenses_date', 'simple_expenses')
    op.drop_table('simple_expenses')