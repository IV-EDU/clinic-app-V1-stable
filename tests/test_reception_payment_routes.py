from __future__ import annotations

import re
from uuid import uuid4

from werkzeug.security import generate_password_hash

from clinic_app.services.database import db as raw_db
from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, ANY_DOCTOR_LABEL
from clinic_app.services.reception_entries import list_entries


def _extract_csrf(response) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.data.decode("utf-8"))
    assert match, "CSRF token not found"
    return match.group(1)


def _create_role(name: str, permission_codes: list[str]) -> int:
    conn = raw_db()
    try:
        conn.execute(
            "INSERT INTO roles(name, description) VALUES (?, ?)",
            (name, f"{name} test role"),
        )
        role_id = conn.execute("SELECT id FROM roles WHERE name=?", (name,)).fetchone()["id"]
        for code in permission_codes:
            perm = conn.execute("SELECT id FROM permissions WHERE code=?", (code,)).fetchone()
            assert perm is not None, f"Permission {code} missing"
            conn.execute(
                "INSERT INTO role_permissions(role_id, permission_id) VALUES (?, ?)",
                (role_id, perm["id"]),
            )
        conn.commit()
        return role_id
    finally:
        conn.close()


def _create_user(username: str, password: str, role_ids: list[int] | None = None) -> str:
    conn = raw_db()
    try:
        user_id = f"user-{uuid4()}"
        conn.execute(
            """
            INSERT INTO users(id, username, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 'assistant', 1, datetime('now'), datetime('now'))
            """,
            (user_id, username, generate_password_hash(password)),
        )
        for role_id in role_ids or []:
            conn.execute(
                "INSERT INTO user_roles(user_id, role_id) VALUES (?, ?)",
                (user_id, role_id),
            )
        conn.commit()
        return user_id
    finally:
        conn.close()


def _login(client, username: str, password: str):
    login_page = client.get("/auth/login")
    token = _extract_csrf(login_page)
    resp = client.post(
        "/auth/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)


def _seed_patient_with_treatment(*, with_child: bool = False) -> tuple[str, str, str | None]:
    patient_id = f"patient-{uuid4()}"
    treatment_id = f"treatment-{uuid4()}"
    child_id = f"payment-{uuid4()}" if with_child else None
    conn = raw_db()
    try:
        conn.execute(
            """
            INSERT INTO patients(id, short_id, full_name, phone, notes, primary_page_number, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (patient_id, f"P-{uuid4().hex[:6]}", "Payment Draft Patient", "01077777777", "", "91"),
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
                "Locked Filling",
                ANY_DOCTOR_ID,
                ANY_DOCTOR_LABEL,
                14000,
                20000,
                1000,
            ),
        )
        if child_id:
            conn.execute(
                """
                INSERT INTO payments(
                    id, patient_id, parent_payment_id, paid_at, amount_cents, method, note, treatment,
                    doctor_id, doctor_label, remaining_cents, total_amount_cents, examination_flag,
                    followup_flag, discount_cents
                ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, 0, 0, 0, 0, 0)
                """,
                (
                    child_id,
                    patient_id,
                    treatment_id,
                    "2026-03-18",
                    2000,
                    "cash",
                    "",
                    ANY_DOCTOR_ID,
                    ANY_DOCTOR_LABEL,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return patient_id, treatment_id, child_id


def test_treatment_card_shows_send_payment_draft_button_for_create_capable_user(logged_in_client):
    patient_id, _, _ = _seed_patient_with_treatment()

    resp = logged_in_client.get(f"/patients/{patient_id}")
    assert resp.status_code == 200
    assert "Send Payment Draft" in resp.data.decode("utf-8")


def test_treatment_card_hides_send_payment_draft_button_without_reception_create_permission(client):
    role_id = _create_role("Patient Viewer Only", ["patients:view", "payments:view"])
    _create_user("patient-viewer", "password123", [role_id])
    _login(client, "patient-viewer", "password123")
    patient_id, _, _ = _seed_patient_with_treatment()

    resp = client.get(f"/patients/{patient_id}")
    assert resp.status_code == 200
    assert "Send Payment Draft" not in resp.data.decode("utf-8")


def test_new_payment_get_requires_create_and_patient_visibility(client):
    patient_id, treatment_id, _ = _seed_patient_with_treatment()
    resp = client.get(f"/reception/entries/new-payment?patient_id={patient_id}&treatment_id={treatment_id}")
    assert resp.status_code in (302, 401)

    role_id = _create_role("Reception Create Without Patient View", ["reception_entries:create"])
    _create_user("reception-no-patient-view", "password123", [role_id])
    _login(client, "reception-no-patient-view", "password123")
    blocked = client.get(f"/reception/entries/new-payment?patient_id={patient_id}&treatment_id={treatment_id}")
    assert blocked.status_code == 403


def test_new_payment_get_returns_404_for_invalid_patient_treatment_pair(logged_in_client):
    patient_id, _, _ = _seed_patient_with_treatment()
    resp = logged_in_client.get(f"/reception/entries/new-payment?patient_id={patient_id}&treatment_id=missing-treatment")
    assert resp.status_code == 404


def test_new_payment_get_rejects_child_payment_context(logged_in_client):
    patient_id, _, child_id = _seed_patient_with_treatment(with_child=True)
    resp = logged_in_client.get(f"/reception/entries/new-payment?patient_id={patient_id}&treatment_id={child_id}")
    assert resp.status_code == 400


def test_valid_new_payment_post_creates_locked_draft(logged_in_client):
    patient_id, treatment_id, _ = _seed_patient_with_treatment()
    page = logged_in_client.get(f"/reception/entries/new-payment?patient_id={patient_id}&treatment_id={treatment_id}")
    token = _extract_csrf(page)

    resp = logged_in_client.post(
        "/reception/entries/new-payment",
        data={
            "csrf_token": token,
            "patient_id": patient_id,
            "treatment_id": treatment_id,
            "amount": "35",
            "visit_date": "2026-03-20",
            "method": "card",
            "doctor_id": ANY_DOCTOR_ID,
            "note": "route payment draft",
        },
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith("/reception?view=desk")

    entries = list_entries(submitted_by_user_id="admin-test", limit=20)
    created = next(entry for entry in entries if entry["draft_type"] == "new_payment")
    assert created["source"] == "treatment_card"
    assert created["locked_patient_id"] == patient_id
    assert created["locked_treatment_id"] == treatment_id
    assert created["target_patient_id"] is None
    assert created["target_treatment_id"] is None
    assert created["target_payment_id"] is None
    assert created["patient_name"] == "Payment Draft Patient"
    assert created["page_number"] == "91"
    assert created["payload_json"]["method"] == "card"


def test_invalid_new_payment_post_rerenders_with_sticky_values(logged_in_client):
    patient_id, treatment_id, _ = _seed_patient_with_treatment()
    page = logged_in_client.get(f"/reception/entries/new-payment?patient_id={patient_id}&treatment_id={treatment_id}")
    token = _extract_csrf(page)

    resp = logged_in_client.post(
        "/reception/entries/new-payment",
        data={
            "csrf_token": token,
            "patient_id": patient_id,
            "treatment_id": treatment_id,
            "amount": "",
            "visit_date": "2026-03-21",
            "method": "transfer",
            "doctor_id": "",
            "note": "sticky note",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 400
    body = resp.data.decode("utf-8")
    assert "Payment amount is required." in body
    assert "Doctor is required." in body
    assert 'value="2026-03-21"' in body
    assert "sticky note" in body


def test_new_payment_post_blocks_overpayment_against_current_remaining(logged_in_client):
    patient_id, treatment_id, _ = _seed_patient_with_treatment()
    page = logged_in_client.get(f"/reception/entries/new-payment?patient_id={patient_id}&treatment_id={treatment_id}")
    token = _extract_csrf(page)

    resp = logged_in_client.post(
        "/reception/entries/new-payment",
        data={
            "csrf_token": token,
            "patient_id": patient_id,
            "treatment_id": treatment_id,
            "amount": "500",
            "visit_date": "2026-03-20",
            "method": "cash",
            "doctor_id": ANY_DOCTOR_ID,
            "note": "",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 400
    assert "Paid today cannot be greater than the amount due." in resp.data.decode("utf-8")
