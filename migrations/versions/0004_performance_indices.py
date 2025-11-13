"""Add performance indices for appointment queries."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0004_performance_indices"
down_revision = "0003_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add performance indices for appointment queries."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # Check if appointments table exists
    if "appointments" not in inspector.get_table_names():
        return
    
    existing_indices = {idx["name"] for idx in inspector.get_indexes("appointments")}
    
    # Create index for doctor_id + starts_at (for efficient doctor-specific and time-based queries)
    if "idx_appointments_doctor_start" not in existing_indices:
        op.create_index("idx_appointments_doctor_start", "appointments", ["doctor_id", "starts_at"])
    
    # Create index for patient_id (for patient-specific appointment queries)
    if "idx_appointments_patient" not in existing_indices:
        op.create_index("idx_appointments_patient", "appointments", ["patient_id"])
    
    # Create index for status (for status-based filtering)
    if "idx_appointments_status" not in existing_indices:
        op.create_index("idx_appointments_status", "appointments", ["status"])


def downgrade() -> None:
    """Remove performance indices."""
    op.drop_index("idx_appointments_status", "appointments")
    op.drop_index("idx_appointments_patient", "appointments")
    op.drop_index("idx_appointments_doctor_start", "appointments")