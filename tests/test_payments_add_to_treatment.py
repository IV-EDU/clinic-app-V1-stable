from __future__ import annotations

import re
from uuid import uuid4

from clinic_app.services.database import db as raw_db
from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, ANY_DOCTOR_LABEL
from clinic_app.services.payments import add_payment_to_treatment


def _extract_csrf(response) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.data.decode("utf-8"))
    assert match, "CSRF token not found"
    return match.group(1)


def _seed_patient_and_treatment() -> tuple[str, str]:
    patient_id = f"patient-{uuid4()}"
    treatment_id = f"treatment-{uuid4()}"
    conn = raw_db()
    try:
        conn.execute(
            """
            INSERT INTO patients(id, short_id, full_name, phone, notes, primary_page_number, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (patient_id, f"P-{uuid4().hex[:6]}", "Payment Helper Patient", "01055555555", "", "81"),
        )
        conn.execute(
            """
            INSERT INTO payments(
                id, patient_id, parent_payment_id, paid_at, amount_cents, method, note, treatment,
                doctor_id, doctor_label, remaining_cents, total_amount_cents, examination_flag,
                followup_flag, discount_cents
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
            """,
            (
                treatment_id,
                patient_id,
                "2026-03-17",
                5000,
                "cash",
                "",
                "Payment Helper Treatment",
                ANY_DOCTOR_ID,
                ANY_DOCTOR_LABEL,
                14000,
                20000,
                1000,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return patient_id, treatment_id


def test_add_payment_to_treatment_updates_parent_remaining_and_returns_summary(app, admin_user):
    patient_id, treatment_id = _seed_patient_and_treatment()
    conn = raw_db()
    try:
        result = add_payment_to_treatment(
            conn,
            treatment_id,
            patient_id,
            4000,
            "2026-03-18",
            "card",
            "helper note",
            ANY_DOCTOR_ID,
            ANY_DOCTOR_LABEL,
        )
        conn.commit()

        parent = conn.execute(
            "SELECT remaining_cents FROM payments WHERE id=?",
            (treatment_id,),
        ).fetchone()
        child = conn.execute(
            "SELECT parent_payment_id, amount_cents, method, note FROM payments WHERE id=?",
            (result["payment_id"],),
        ).fetchone()
    finally:
        conn.close()

    assert result["remaining_cents"] == 10000
    assert result["total_paid_cents"] == 9000
    assert child["parent_payment_id"] == treatment_id
    assert int(child["amount_cents"] or 0) == 4000
    assert child["method"] == "card"
    assert child["note"] == "helper note"
    assert int(parent["remaining_cents"] or 0) == 10000


def test_add_payment_to_treatment_blocks_overpayment(app, admin_user):
    patient_id, treatment_id = _seed_patient_and_treatment()
    conn = raw_db()
    try:
        try:
            add_payment_to_treatment(
                conn,
                treatment_id,
                patient_id,
                15000,
                "2026-03-18",
                "cash",
                "",
                ANY_DOCTOR_ID,
                ANY_DOCTOR_LABEL,
            )
            assert False, "Expected overpayment validation error"
        except ValueError as exc:
            assert "Paid today cannot be greater than the amount due." in str(exc)
    finally:
        conn.close()


def test_add_payment_route_updates_parent_remaining(logged_in_client):
    patient_id, treatment_id = _seed_patient_and_treatment()
    page = logged_in_client.get(f"/patients/{patient_id}")
    token = _extract_csrf(page)

    resp = logged_in_client.post(
        f"/patients/{patient_id}/treatments/{treatment_id}/payment",
        data={
            "csrf_token": token,
            "amount": "30",
            "paid_at": "2026-03-18",
            "method": "transfer",
            "note": "route helper",
            "doctor_id": ANY_DOCTOR_ID,
        },
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    conn = raw_db()
    try:
        parent = conn.execute(
            "SELECT remaining_cents FROM payments WHERE id=?",
            (treatment_id,),
        ).fetchone()
        child = conn.execute(
            "SELECT amount_cents, method FROM payments WHERE parent_payment_id=? ORDER BY paid_at DESC, rowid DESC LIMIT 1",
            (treatment_id,),
        ).fetchone()
    finally:
        conn.close()

    assert int(parent["remaining_cents"] or 0) == 11000
    assert int(child["amount_cents"] or 0) == 3000
    assert child["method"] == "transfer"
