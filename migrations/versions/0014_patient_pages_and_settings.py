"""Add patient page numbers and admin settings."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "0014_patient_pages_and_settings"
down_revision = "0013_payments_doctor_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add patient_pages table and admin settings for file numbers."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # Create patient_pages table (many-to-one relationship)
    if not inspector.has_table("patient_pages"):
        op.create_table(
            "patient_pages",
            sa.Column("id", sa.String(36), primary_key=True, default=sa.func.uuid()),
            sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
            sa.Column("page_number", sa.String(50), nullable=False, comment="Physical notebook page number"),
            sa.Column("notebook_name", sa.String(100), nullable=True, comment="Notebook identifier (optional)"),
            sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now(), onupdate=sa.func.now()),
            sa.UniqueConstraint("patient_id", "page_number", name="uq_patient_page"),
            sa.Index("ix_patient_pages_patient_id", "patient_id"),
            sa.Index("ix_patient_pages_page_number", "page_number"),
        )
    
    # Add page_number column to patients table for backward compatibility
    patients_cols = {col["name"] for col in inspector.get_columns("patients")}
    if "primary_page_number" not in patients_cols:
        op.add_column("patients", sa.Column("primary_page_number", sa.String(50), nullable=True))
        op.create_index("ix_patients_primary_page_number", "patients", ["primary_page_number"])
    
    # Add admin settings table if it doesn't exist
    if not inspector.has_table("admin_settings"):
        op.create_table(
            "admin_settings",
            sa.Column("id", sa.String(36), primary_key=True, default=sa.func.uuid()),
            sa.Column("setting_key", sa.String(100), nullable=False, unique=True),
            sa.Column("setting_value", sa.Text(), nullable=True),
            sa.Column("setting_type", sa.String(20), nullable=False, default="string"),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.func.now(), onupdate=sa.func.now()),
            sa.Index("ix_admin_settings_key", "setting_key"),
        )
    
    # Insert default admin settings
    op.execute(
        """
        INSERT OR IGNORE INTO admin_settings (setting_key, setting_value, setting_type, description)
        VALUES 
        ('enable_file_numbers', 'false', 'boolean', 'Enable file number functionality (true/false)'),
        ('page_number_mode', 'manual', 'string', 'Page number entry mode: manual, auto, or disabled'),
        ('default_notebook_name', 'Main Notebook', 'string', 'Default notebook name for page numbers')
        """
    )
    
    # Add trigger for updated_at on patient_pages
    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS patient_pages_updated_at
        AFTER UPDATE ON patient_pages
        BEGIN
            UPDATE patient_pages SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
        END
        """
    )


def downgrade() -> None:
    """Remove patient_pages table and admin settings."""
    # Drop trigger first
    op.execute("DROP TRIGGER IF EXISTS patient_pages_updated_at")
    
    # Drop patient_pages table
    op.drop_table("patient_pages")
    
    # Remove primary_page_number column from patients
    op.drop_column("patients", "primary_page_number")
    
    # Remove admin_settings table
    op.drop_table("admin_settings")