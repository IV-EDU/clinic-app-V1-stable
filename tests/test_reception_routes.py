from __future__ import annotations

import re
from uuid import uuid4

from werkzeug.security import generate_password_hash

from clinic_app.services.database import db as raw_db
from clinic_app.services.reception_entries import create_entry


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


def _count_reception_entries() -> int:
    conn = raw_db()
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM reception_entries").fetchone()
        return row["c"]
    finally:
        conn.close()


def _count_reception_events() -> int:
    conn = raw_db()
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM reception_entry_events").fetchone()
        return row["c"]
    finally:
        conn.close()


def test_create_capable_user_can_load_reception(logged_in_client):
    resp = logged_in_client.get("/reception")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Reception Desk" in body
    assert "New submission" in body


def test_user_without_reception_permission_gets_403(client):
    _create_user("plain-user", "password123", [])
    _login(client, "plain-user", "password123")
    resp = client.get("/reception")
    assert resp.status_code == 403


def test_review_only_user_sees_manager_placeholder(client):
    review_role_id = _create_role("Reception Reviewer", ["reception_entries:review"])
    _create_user("reviewer-user", "password123", [review_role_id])
    _login(client, "reviewer-user", "password123")

    resp = client.get("/reception")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Manager queue coming next" in body
    assert "New submission" not in body


def test_valid_reception_post_creates_entry_and_event(logged_in_client):
    before_entries = _count_reception_entries()
    before_events = _count_reception_events()

    page = logged_in_client.get("/reception")
    token = _extract_csrf(page)
    resp = logged_in_client.post(
        "/reception/entries",
        data={
            "csrf_token": token,
            "patient_name": "Reception Route Patient",
            "phone": "01012345678",
            "page_number": "22",
            "visit_date": "2026-03-17",
            "visit_type": "exam",
            "treatment_text": "Cleaning",
            "doctor_id": "any-doctor",
            "money_received_today": "1",
            "paid_today": "100",
            "total_amount": "200",
            "discount_amount": "20",
            "note": "Route note",
        },
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith("/reception")
    assert _count_reception_entries() == before_entries + 1
    assert _count_reception_events() == before_events + 1


def test_invalid_reception_post_rerenders_with_errors_and_sticky_values(logged_in_client):
    before_entries = _count_reception_entries()
    page = logged_in_client.get("/reception")
    token = _extract_csrf(page)
    resp = logged_in_client.post(
        "/reception/entries",
        data={
            "csrf_token": token,
            "patient_name": "Sticky Patient",
            "doctor_id": "",
            "phone": "",
            "page_number": "",
            "money_received_today": "1",
            "paid_today": "",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Doctor is required." in body
    assert "Paid today is required when money was received today." in body
    assert 'value="Sticky Patient"' in body
    assert _count_reception_entries() == before_entries


def test_reception_page_shows_current_users_entries_only(logged_in_client):
    create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Visible Draft",
            "doctor_id": "any-doctor",
            "doctor_label": "Any Doctor",
        },
        actor_user_id="admin-test",
    )

    helper_role_id = _create_role("Reception Helper", ["reception_entries:create"])
    other_user_id = _create_user("other-helper", "password123", [helper_role_id])
    create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Hidden Draft",
            "doctor_id": "any-doctor",
            "doctor_label": "Any Doctor",
        },
        actor_user_id=other_user_id,
    )

    resp = logged_in_client.get("/reception")
    body = resp.data.decode("utf-8")
    assert "Visible Draft" in body
    assert "Hidden Draft" not in body
