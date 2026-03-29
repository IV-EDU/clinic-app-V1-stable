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


def test_treatment_card_shows_send_payment_correction_buttons_for_create_capable_user(logged_in_client):
    patient_id, _, child_id = _seed_patient_with_treatment(with_child=True)

    resp = logged_in_client.get(f"/patients/{patient_id}")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert f"/reception/entries/new-payment-correction?patient_id={patient_id}&amp;payment_id=" in body
    assert child_id in body


def test_treatment_card_hides_send_payment_correction_button_without_reception_create_permission(client):
    role_id = _create_role("Patient Viewer No Payment Correction", ["patients:view", "payments:view"])
    _create_user("patient-viewer-payment-correction", "password123", [role_id])
    _login(client, "patient-viewer-payment-correction", "password123")
    patient_id, _, _ = _seed_patient_with_treatment(with_child=True)

    resp = client.get(f"/patients/{patient_id}")
    assert resp.status_code == 200
    assert "Send Payment Correction" not in resp.data.decode("utf-8")


def test_new_payment_correction_get_requires_create_and_patient_visibility(client):
    patient_id, treatment_id, _ = _seed_patient_with_treatment()
    resp = client.get(f"/reception/entries/new-payment-correction?patient_id={patient_id}&payment_id={treatment_id}")
    assert resp.status_code in (302, 401)

    role_id = _create_role("Reception Create Without Patient View Payment Correction", ["reception_entries:create"])
    _create_user("reception-no-patient-view-payment-correction", "password123", [role_id])
    _login(client, "reception-no-patient-view-payment-correction", "password123")
    blocked = client.get(f"/reception/entries/new-payment-correction?patient_id={patient_id}&payment_id={treatment_id}")
    assert blocked.status_code == 403


def test_new_payment_correction_get_returns_404_for_invalid_patient_payment_pair(logged_in_client):
    patient_id, _, _ = _seed_patient_with_treatment()
    resp = logged_in_client.get(f"/reception/entries/new-payment-correction?patient_id={patient_id}&payment_id=missing-payment")
    assert resp.status_code == 404


def test_valid_new_payment_correction_post_creates_locked_draft_for_child_payment(logged_in_client):
    patient_id, treatment_id, child_id = _seed_patient_with_treatment(with_child=True)
    page = logged_in_client.get(
        f"/reception/entries/new-payment-correction?patient_id={patient_id}&payment_id={child_id}"
    )
    token = _extract_csrf(page)

    resp = logged_in_client.post(
        "/reception/entries/new-payment-correction",
        data={
            "csrf_token": token,
            "patient_id": patient_id,
            "payment_id": child_id,
            "amount": "25",
            "visit_date": "2026-03-22",
            "method": "transfer",
            "doctor_id": ANY_DOCTOR_ID,
            "note": "route payment correction",
        },
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith("/reception?view=desk")

    entries = list_entries(submitted_by_user_id="admin-test", limit=20)
    created = next(entry for entry in entries if entry["draft_type"] == "edit_payment")
    assert created["source"] == "treatment_card"
    assert created["locked_patient_id"] == patient_id
    assert created["locked_treatment_id"] == treatment_id
    assert created["locked_payment_id"] == child_id
    assert created["target_payment_id"] is None
    assert created["payload_json"]["current"]["payment_id"] == child_id
    assert created["payload_json"]["proposed"]["method"] == "transfer"


def test_invalid_new_payment_correction_post_rerenders_with_sticky_values(logged_in_client):
    patient_id, _, child_id = _seed_patient_with_treatment(with_child=True)
    page = logged_in_client.get(
        f"/reception/entries/new-payment-correction?patient_id={patient_id}&payment_id={child_id}"
    )
    token = _extract_csrf(page)

    resp = logged_in_client.post(
        "/reception/entries/new-payment-correction",
        data={
            "csrf_token": token,
            "patient_id": patient_id,
            "payment_id": child_id,
            "amount": "",
            "visit_date": "2026-03-21",
            "method": "transfer",
            "doctor_id": "",
            "note": "sticky correction note",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 400
    body = resp.data.decode("utf-8")
    assert "Payment amount is required." in body
    assert "Doctor is required." in body
    assert 'value="2026-03-21"' in body
    assert "sticky correction note" in body


def test_owner_can_resubmit_returned_payment_correction(client):
    owner_role_id = _create_role("Reception Payment Correction Owner", ["reception_entries:create", "patients:view"])
    review_role_id = _create_role("Reception Payment Correction Reviewer", ["reception_entries:review"])
    owner_user_id = _create_user("payment-correction-owner", "password123", [owner_role_id])
    _create_user("payment-correction-reviewer", "password123", [review_role_id])
    patient_id, treatment_id, child_id = _seed_patient_with_treatment(with_child=True)

    conn = raw_db()
    try:
        child = conn.execute("SELECT amount_cents, paid_at, method, note FROM payments WHERE id=?", (child_id,)).fetchone()
    finally:
        conn.close()

    entry = list_entries(submitted_by_user_id=owner_user_id, limit=1)
    if entry:
        assert False, "Expected no pre-existing payment correction drafts"

    from clinic_app.services.reception_entries import create_entry

    created = create_entry(
        {
            "draft_type": "edit_payment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "locked_payment_id": child_id,
            "doctor_id": ANY_DOCTOR_ID,
            "doctor_label": ANY_DOCTOR_LABEL,
            "visit_date": child["paid_at"],
            "paid_today": "20",
            "payload_json": {
                "current": {
                    "payment_id": child_id,
                    "treatment_id": treatment_id,
                    "amount_cents": int(child["amount_cents"] or 0),
                    "visit_date": child["paid_at"],
                    "method": child["method"] or "cash",
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "note": child["note"] or "",
                    "is_initial_payment": 0,
                },
                "proposed": {
                    "amount": "20",
                    "visit_date": child["paid_at"],
                    "method": "cash",
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "note": "Draft note",
                },
            },
        },
        actor_user_id=owner_user_id,
    )

    reviewer_client = client.application.test_client()
    _login(reviewer_client, "payment-correction-reviewer", "password123")
    page = reviewer_client.get(f"/reception/entries/{created['id']}")
    token = _extract_csrf(page)
    reviewer_client.post(
        f"/reception/entries/{created['id']}/return",
        data={"csrf_token": token, "return_reason": "Fix the amount"},
        follow_redirects=False,
    )

    owner_client = client.application.test_client()
    _login(owner_client, "payment-correction-owner", "password123")
    edit_page = owner_client.get(f"/reception/entries/{created['id']}/edit")
    assert edit_page.status_code == 200
    edit_token = _extract_csrf(edit_page)
    resp = owner_client.post(
        f"/reception/entries/{created['id']}/edit",
        data={
            "csrf_token": edit_token,
            "amount": "18",
            "visit_date": "2026-03-23",
            "method": "card",
            "doctor_id": ANY_DOCTOR_ID,
            "note": "Final payment note",
        },
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    updated = next(entry for entry in list_entries(submitted_by_user_id=owner_user_id, limit=20) if entry["id"] == created["id"])
    assert updated["status"] == "edited"
    assert updated["last_action"] == "edited"
    assert updated["return_reason"] is None
    assert updated["locked_payment_id"] == child_id
    assert updated["paid_today_cents"] == 1800
