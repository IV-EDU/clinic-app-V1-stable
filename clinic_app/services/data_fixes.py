"""Small, safe data fixes applied at app startup.

These are intentionally conservative: they only fill missing values and do not
change business meaning.
"""

from __future__ import annotations

import sqlite3

from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, ANY_DOCTOR_LABEL


def backfill_missing_payment_doctors(db_path: str) -> int:
    """Ensure all payments have a doctor_id.

    Older clinic databases may contain payments with an empty/NULL doctor_id.
    We treat those as "Any Doctor" so filtering and reporting stay consistent.
    """

    if not db_path:
        return 0

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        try:
            cur = conn.execute(
                """
                UPDATE payments
                   SET doctor_id=?, doctor_label=?
                 WHERE doctor_id IS NULL OR TRIM(doctor_id)=''
                """,
                (ANY_DOCTOR_ID, ANY_DOCTOR_LABEL),
            )
            updated = int(cur.rowcount or 0)
            conn.commit()
            return updated
        except sqlite3.OperationalError:
            # Payments table might not exist yet (first run before migrations).
            return 0
    finally:
        conn.close()

