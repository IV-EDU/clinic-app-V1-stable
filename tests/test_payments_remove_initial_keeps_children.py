import uuid

from clinic_app.services.database import db
from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, ANY_DOCTOR_LABEL


def test_remove_initial_payment_keeps_child_payments(logged_in_client, get_csrf_token):
    conn = db()
    try:
        pid = f"patient-{uuid.uuid4()}"
        treatment_id = f"treat-{uuid.uuid4()}"
        child_id = f"pay-{uuid.uuid4()}"
        conn.execute(
            "INSERT INTO patients(id, short_id, full_name, phone, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            (pid, f"P{uuid.uuid4().hex[:6]}", "Remove Initial", "01000000000"),
        )
        conn.execute(
            """
            INSERT INTO payments(
                id, patient_id, parent_payment_id, paid_at, amount_cents, method, note, treatment,
                doctor_id, doctor_label,
                remaining_cents, total_amount_cents, examination_flag, followup_flag, discount_cents
            ) VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
            """,
            (
                treatment_id,
                pid,
                "2026-02-01",
                4000,
                "cash",
                "",
                "Initial removal",
                ANY_DOCTOR_ID,
                ANY_DOCTOR_LABEL,
                6000,
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
                "child",
                ANY_DOCTOR_ID,
                ANY_DOCTOR_LABEL,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    page = logged_in_client.get(f"/patients/{pid}")
    token = get_csrf_token(page)

    resp = logged_in_client.post(
        f"/patients/{pid}/treatments/{treatment_id}/initial/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    conn = db()
    try:
        parent = conn.execute(
            "SELECT amount_cents, remaining_cents FROM payments WHERE id=?",
            (treatment_id,),
        ).fetchone()
        child = conn.execute("SELECT id FROM payments WHERE id=?", (child_id,)).fetchone()
        assert parent is not None
        assert int(parent["amount_cents"] or 0) == 0
        assert int(parent["remaining_cents"] or 0) == 7000
        assert child is not None
    finally:
        conn.close()
