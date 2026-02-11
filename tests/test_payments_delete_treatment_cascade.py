import uuid

from clinic_app.services.database import db
from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, ANY_DOCTOR_LABEL


def test_delete_treatment_cascades_child_payments(logged_in_client, get_csrf_token):
    conn = db()
    try:
        pid = f"patient-{uuid.uuid4()}"
        conn.execute(
            "INSERT INTO patients(id, short_id, full_name, phone, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            (pid, f"P{uuid.uuid4().hex[:6]}", "Cascade Test", "01000000000"),
        )

        treatment_id = f"treat-{uuid.uuid4()}"
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
                10000,
                "cash",
                "",
                "Root treatment",
                ANY_DOCTOR_ID,
                ANY_DOCTOR_LABEL,
                10000,
            ),
        )

        child_id = f"pay-{uuid.uuid4()}"
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
                2500,
                "cash",
                "child",
                ANY_DOCTOR_ID,
                ANY_DOCTOR_LABEL,
            ),
        )

        conn.commit()
    finally:
        conn.close()

    confirm = logged_in_client.get(f"/patients/{pid}/payments/{treatment_id}/delete")
    token = get_csrf_token(confirm)

    resp = logged_in_client.post(
        f"/patients/{pid}/payments/{treatment_id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    conn = db()
    try:
        parent = conn.execute("SELECT id FROM payments WHERE id=?", (treatment_id,)).fetchone()
        child = conn.execute("SELECT id FROM payments WHERE id=?", (child_id,)).fetchone()
        assert parent is None
        assert child is None
    finally:
        conn.close()

