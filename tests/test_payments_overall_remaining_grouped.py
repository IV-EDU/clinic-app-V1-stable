import uuid

from clinic_app.services.database import db
from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, ANY_DOCTOR_LABEL
from clinic_app.services.payments import overall_remaining


def test_overall_remaining_uses_grouped_treatment_math(app):
    conn = db()
    try:
        pid = f"patient-{uuid.uuid4()}"
        treatment_id = f"treat-{uuid.uuid4()}"
        child_id = f"pay-{uuid.uuid4()}"
        conn.execute(
            "INSERT INTO patients(id, short_id, full_name, phone, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            (pid, f"P{uuid.uuid4().hex[:6]}", "Grouped Remaining", "01000000000"),
        )
        conn.execute(
            """
            INSERT INTO payments(
                id, patient_id, parent_payment_id, paid_at, amount_cents, method, note, treatment,
                doctor_id, doctor_label,
                remaining_cents, total_amount_cents, examination_flag, followup_flag, discount_cents
            ) VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, ?, 0, ?, 0, 0, 0)
            """,
            (
                treatment_id,
                pid,
                "2026-02-01",
                2000,
                "cash",
                "",
                "Grouped Treatment",
                ANY_DOCTOR_ID,
                ANY_DOCTOR_LABEL,
                10000,
            ),
        )
        conn.execute(
            """
            INSERT INTO payments(
                id, patient_id, parent_payment_id, paid_at, amount_cents, method, note, treatment,
                doctor_id, doctor_label,
                remaining_cents, total_amount_cents, examination_flag, followup_flag, discount_cents
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, 0, 0, 0, 0, 0)
            """,
            (
                child_id,
                pid,
                treatment_id,
                "2026-02-02",
                3000,
                "cash",
                "",
                ANY_DOCTOR_ID,
                ANY_DOCTOR_LABEL,
            ),
        )
        conn.commit()
        assert overall_remaining(conn, pid) == 5000
    finally:
        conn.close()
