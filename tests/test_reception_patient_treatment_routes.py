from __future__ import annotations

import re
from uuid import uuid4

from werkzeug.security import generate_password_hash

from clinic_app.services.database import db as raw_db
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


def _seed_patient_profile(*, full_name: str = "Treatment Route Patient") -> str:
    patient_id = f"patient-{uuid4()}"
    conn = raw_db()
    try:
        conn.execute(
            """
            INSERT INTO patients(id, short_id, full_name, phone, notes, primary_page_number, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (patient_id, f"P-{uuid4().hex[:6]}", full_name, "01076767676", "Original note", "31"),
        )
        conn.execute(
            """
            INSERT INTO patient_phones(id, patient_id, phone, phone_normalized, label, is_primary)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (f"phone-{uuid4()}", patient_id, "01076767676", "01076767676", None),
        )
        conn.execute(
            """
            INSERT INTO patient_pages(id, patient_id, page_number, notebook_name)
            VALUES (?, ?, ?, ?)
            """,
            (f"page-{uuid4()}", patient_id, "31", "Notebook A"),
        )
        conn.commit()
    finally:
        conn.close()
    return patient_id


def _count_payments() -> int:
    conn = raw_db()
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM payments").fetchone()["c"]
    finally:
        conn.close()


def test_patient_detail_shows_send_treatment_draft_button_for_create_capable_user(logged_in_client):
    patient_id = _seed_patient_profile()

    resp = logged_in_client.get(f"/patients/{patient_id}")
    assert resp.status_code == 200
    assert "Send Treatment Draft" in resp.data.decode("utf-8")


def test_patient_detail_hides_send_treatment_draft_button_without_reception_create_permission(client):
    role_id = _create_role("Patient Viewer No Treatment Draft", ["patients:view"])
    _create_user("patient-viewer-treatment-draft", "password123", [role_id])
    _login(client, "patient-viewer-treatment-draft", "password123")
    patient_id = _seed_patient_profile()

    resp = client.get(f"/patients/{patient_id}")
    assert resp.status_code == 200
    assert "Send Treatment Draft" not in resp.data.decode("utf-8")


def test_new_treatment_get_requires_create_and_patient_visibility(client):
    patient_id = _seed_patient_profile()
    resp = client.get(f"/reception/entries/new-treatment?patient_id={patient_id}")
    assert resp.status_code in (302, 401)

    role_id = _create_role("Reception Create Only Treatment Draft", ["reception_entries:create"])
    _create_user("reception-create-only-treatment", "password123", [role_id])
    _login(client, "reception-create-only-treatment", "password123")
    blocked = client.get(f"/reception/entries/new-treatment?patient_id={patient_id}")
    assert blocked.status_code == 403


def test_new_treatment_get_returns_404_for_invalid_patient(logged_in_client):
    resp = logged_in_client.get("/reception/entries/new-treatment?patient_id=missing-patient")
    assert resp.status_code == 404


def test_valid_new_treatment_post_creates_locked_patient_file_draft(logged_in_client):
    patient_id = _seed_patient_profile(full_name="Treatment Draft Create Patient")
    before_payments = _count_payments()
    page = logged_in_client.get(f"/reception/entries/new-treatment?patient_id={patient_id}")
    token = _extract_csrf(page)

    resp = logged_in_client.post(
        "/reception/entries/new-treatment",
        data={
            "csrf_token": token,
            "patient_id": patient_id,
            "visit_date": "2026-03-30",
            "visit_type": "followup",
            "treatment_text": "Locked Follow-up Crown",
            "doctor_id": "any-doctor",
            "money_received_today": "1",
            "paid_today": "60",
            "total_amount": "250",
            "discount_amount": "10",
            "note": "Patient-file draft note",
        },
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith("/reception?view=desk")
    assert _count_payments() == before_payments

    entries = list_entries(submitted_by_user_id="admin-test", limit=20)
    created = next(
        entry for entry in entries if entry["draft_type"] == "new_treatment" and entry["source"] == "patient_file"
    )
    assert created["locked_patient_id"] == patient_id
    assert created["patient_intent"] == "existing"
    assert created["target_patient_id"] is None
    assert created["patient_name"] == "Treatment Draft Create Patient"
    assert created["phone"] == "01076767676"
    assert created["page_number"] == "31"
    assert created["visit_type"] == "followup"
    assert created["treatment_text"] == "Locked Follow-up Crown"
    assert created["paid_today_cents"] == 6000
    assert created["payload_json"]["note"] == "Patient-file draft note"


def test_invalid_new_treatment_post_rerenders_with_sticky_values(logged_in_client):
    patient_id = _seed_patient_profile(full_name="Treatment Draft Invalid Patient")
    page = logged_in_client.get(f"/reception/entries/new-treatment?patient_id={patient_id}")
    token = _extract_csrf(page)

    resp = logged_in_client.post(
        "/reception/entries/new-treatment",
        data={
            "csrf_token": token,
            "patient_id": patient_id,
            "visit_date": "2026-03-31",
            "visit_type": "exam",
            "treatment_text": "Sticky Locked Treatment",
            "doctor_id": "",
            "money_received_today": "1",
            "paid_today": "",
            "total_amount": "110",
            "discount_amount": "0",
            "note": "sticky treatment note",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 400
    body = resp.data.decode("utf-8")
    assert "Doctor is required." in body
    assert "Paid today is required when money was received today." in body
    assert "Locked patient summary" in body
    assert 'value="Sticky Locked Treatment"' in body
    assert "sticky treatment note" in body
