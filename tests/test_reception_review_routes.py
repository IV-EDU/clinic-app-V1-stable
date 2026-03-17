from __future__ import annotations

import re
from uuid import uuid4

from werkzeug.security import generate_password_hash

from clinic_app.services.database import db as raw_db
from clinic_app.services.reception_entries import create_entry, get_entry, list_entry_events, return_entry


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


def _create_draft(*, patient_name: str, actor_user_id: str) -> dict:
    return create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": patient_name,
            "doctor_id": "any-doctor",
            "doctor_label": "Any Doctor",
        },
        actor_user_id=actor_user_id,
    )


def _count_patients() -> int:
    conn = raw_db()
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM patients").fetchone()["c"]
    finally:
        conn.close()


def _count_payments() -> int:
    conn = raw_db()
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM payments").fetchone()["c"]
    finally:
        conn.close()


def test_create_only_user_cannot_open_manager_queue(client):
    create_role_id = _create_role("Reception Desk Only", ["reception_entries:create"])
    _create_user("desk-only-user", "password123", [create_role_id])
    _login(client, "desk-only-user", "password123")

    resp = client.get("/reception?view=queue")
    assert resp.status_code == 403


def test_review_user_can_load_manager_queue_and_queue_excludes_closed_items(client, admin_user):
    review_role_id = _create_role("Reception Review Team", ["reception_entries:review"])
    reviewer_user_id = _create_user("review-queue-user", "password123", [review_role_id])
    _login(client, "review-queue-user", "password123")

    new_entry = _create_draft(patient_name="Queue New", actor_user_id="admin-test")
    returned_entry = _create_draft(patient_name="Queue Returned", actor_user_id="admin-test")
    closed_entry = _create_draft(patient_name="Queue Rejected", actor_user_id="admin-test")

    return_entry(returned_entry["id"], actor_user_id=reviewer_user_id, reason="Fix phone")
    conn = raw_db()
    try:
        conn.execute(
            "UPDATE reception_entries SET status='rejected', last_action='rejected', rejection_reason='Closed' WHERE id=?",
            (closed_entry["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.get("/reception?view=queue")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Pending manager queue" in body
    assert "Queue New" in body
    assert "Queue Returned" in body
    assert "Queue Rejected" not in body
    assert body.index("Queue Returned") < body.index("Queue New")


def test_create_only_user_cannot_open_someone_elses_detail(client, admin_user):
    helper_role_id = _create_role("Reception Create Team", ["reception_entries:create"])
    _create_user("helper-one", "password123", [helper_role_id])
    entry = _create_draft(patient_name="Private Draft", actor_user_id="admin-test")

    _login(client, "helper-one", "password123")
    resp = client.get(f"/reception/entries/{entry['id']}")
    assert resp.status_code == 403


def test_review_user_can_hold_draft_and_create_event(client, admin_user):
    review_role_id = _create_role("Reception Hold Team", ["reception_entries:review"])
    _create_user("review-hold-user", "password123", [review_role_id])
    _login(client, "review-hold-user", "password123")

    entry = _create_draft(patient_name="Hold Draft", actor_user_id="admin-test")
    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    resp = client.post(
        f"/reception/entries/{entry['id']}/hold",
        data={"csrf_token": token, "hold_note": "Need callback"},
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    updated = get_entry(entry["id"])
    assert updated["status"] == "held"
    assert updated["last_action"] == "held"
    assert updated["hold_reason"] == "Need callback"
    assert list_entry_events(entry["id"])[0]["action"] == "held"


def test_return_requires_reason(client, admin_user):
    review_role_id = _create_role("Reception Return Team", ["reception_entries:review"])
    _create_user("review-return-user", "password123", [review_role_id])
    _login(client, "review-return-user", "password123")

    entry = _create_draft(patient_name="Return Draft", actor_user_id="admin-test")
    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    resp = client.post(
        f"/reception/entries/{entry['id']}/return",
        data={"csrf_token": token, "return_reason": ""},
        follow_redirects=False,
    )

    assert resp.status_code == 400
    body = resp.data.decode("utf-8")
    assert "Return reason is required." in body
    unchanged = get_entry(entry["id"])
    assert unchanged["status"] == "new"


def test_review_user_can_return_draft_and_reception_sees_returned_state(logged_in_client, client):
    review_role_id = _create_role("Reception Return Team 2", ["reception_entries:review"])
    _create_user("review-return-user-2", "password123", [review_role_id])

    entry = _create_draft(patient_name="Returned Draft", actor_user_id="admin-test")

    _login(client, "review-return-user-2", "password123")
    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    resp = client.post(
        f"/reception/entries/{entry['id']}/return",
        data={"csrf_token": token, "return_reason": "Fix total"},
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    updated = get_entry(entry["id"])
    assert updated["status"] == "edited"
    assert updated["last_action"] == "returned"
    assert updated["return_reason"] == "Fix total"
    assert list_entry_events(entry["id"])[0]["action"] == "returned"

    desk = logged_in_client.get("/reception")
    body = desk.data.decode("utf-8")
    assert "Returned Draft" in body
    assert "Returned" in body
    assert "Fix total" in body


def test_reject_requires_reason_and_valid_reject_closes_draft(client, admin_user):
    review_role_id = _create_role("Reception Reject Team", ["reception_entries:review"])
    _create_user("review-reject-user", "password123", [review_role_id])
    _login(client, "review-reject-user", "password123")

    entry = _create_draft(patient_name="Reject Draft", actor_user_id="admin-test")
    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)

    bad = client.post(
        f"/reception/entries/{entry['id']}/reject",
        data={"csrf_token": token, "reject_reason": ""},
        follow_redirects=False,
    )
    assert bad.status_code == 400
    assert "Rejection reason is required." in bad.data.decode("utf-8")

    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    good = client.post(
        f"/reception/entries/{entry['id']}/reject",
        data={"csrf_token": token, "reject_reason": "Duplicate request"},
        follow_redirects=False,
    )

    assert good.status_code in (302, 303)
    updated = get_entry(entry["id"])
    assert updated["status"] == "rejected"
    assert updated["last_action"] == "rejected"
    assert updated["rejection_reason"] == "Duplicate request"
    assert list_entry_events(entry["id"])[0]["action"] == "rejected"


def test_review_only_user_cannot_approve_draft(client, admin_user):
    review_role_id = _create_role("Reception Review No Approve", ["reception_entries:review"])
    _create_user("review-no-approve", "password123", [review_role_id])
    _login(client, "review-no-approve", "password123")

    entry = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Approve Blocked",
            "doctor_id": "any-doctor",
            "doctor_label": "Any Doctor",
            "total_amount": "200",
            "paid_today": "50",
            "money_received_today": True,
            "visit_date": "2026-03-17",
            "treatment_text": "Filling",
        },
        actor_user_id="admin-test",
    )
    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    resp = client.post(
        f"/reception/entries/{entry['id']}/approve",
        data={"csrf_token": token, "confirm_approve": "1"},
        follow_redirects=False,
    )

    assert resp.status_code == 403


def test_approve_requires_final_confirmation(client, admin_user):
    approve_role_id = _create_role("Reception Approver", ["reception_entries:approve"])
    _create_user("approver-user", "password123", [approve_role_id])
    _login(client, "approver-user", "password123")

    entry = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Needs Confirm",
            "phone": "01011111111",
            "page_number": "55",
            "doctor_id": "any-doctor",
            "doctor_label": "Any Doctor",
            "visit_date": "2026-03-17",
            "treatment_text": "Cleaning",
            "total_amount": "200",
        },
        actor_user_id="admin-test",
    )
    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    resp = client.post(
        f"/reception/entries/{entry['id']}/approve",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    assert resp.status_code == 400
    assert "Final approval confirmation is required." in resp.data.decode("utf-8")
    unchanged = get_entry(entry["id"])
    assert unchanged["status"] == "new"


def test_approve_posts_new_patient_and_treatment(client, admin_user):
    approve_role_id = _create_role("Reception Approver Full", ["reception_entries:approve"])
    _create_user("approver-full", "password123", [approve_role_id])
    _login(client, "approver-full", "password123")

    before_patients = _count_patients()
    before_payments = _count_payments()
    entry = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Approved Patient",
            "phone": "01022222222",
            "page_number": "88",
            "doctor_id": "any-doctor",
            "doctor_label": "Any Doctor",
            "visit_date": "2026-03-17",
            "visit_type": "exam",
            "treatment_text": "Root Canal",
            "total_amount": "300",
            "discount_amount": "50",
            "paid_today": "100",
            "money_received_today": True,
            "payload_json": {"note": "Approval note"},
        },
        actor_user_id="admin-test",
    )

    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    resp = client.post(
        f"/reception/entries/{entry['id']}/approve",
        data={"csrf_token": token, "confirm_approve": "1"},
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    assert _count_patients() == before_patients + 1
    assert _count_payments() == before_payments + 1

    approved = get_entry(entry["id"])
    assert approved["status"] == "approved"
    assert approved["last_action"] == "approved"
    assert approved["target_patient_id"]
    assert approved["target_treatment_id"]
    assert approved["target_payment_id"] == approved["target_treatment_id"]
    assert list_entry_events(entry["id"])[0]["action"] == "approved"

    conn = raw_db()
    try:
        patient = conn.execute(
            "SELECT full_name, phone, primary_page_number FROM patients WHERE id=?",
            (approved["target_patient_id"],),
        ).fetchone()
        payment = conn.execute(
            """
            SELECT patient_id, treatment, amount_cents, total_amount_cents, discount_cents, remaining_cents, doctor_label
            FROM payments WHERE id=?
            """,
            (approved["target_treatment_id"],),
        ).fetchone()
    finally:
        conn.close()

    assert patient["full_name"] == "Approved Patient"
    assert patient["phone"] == "01022222222"
    assert patient["primary_page_number"] == "88"
    assert payment["patient_id"] == approved["target_patient_id"]
    assert payment["treatment"] == "Root Canal"
    assert int(payment["amount_cents"] or 0) == 10000
    assert int(payment["total_amount_cents"] or 0) == 30000
    assert int(payment["discount_cents"] or 0) == 5000
    assert int(payment["remaining_cents"] or 0) == 15000
    assert payment["doctor_label"] == "Any Doctor"


def test_approve_blocks_draft_without_total_amount(client, admin_user):
    approve_role_id = _create_role("Reception Approver Missing Total", ["reception_entries:approve"])
    _create_user("approver-no-total", "password123", [approve_role_id])
    _login(client, "approver-no-total", "password123")

    before_patients = _count_patients()
    before_payments = _count_payments()
    entry = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "No Total Patient",
            "doctor_id": "any-doctor",
            "doctor_label": "Any Doctor",
            "visit_date": "2026-03-17",
            "treatment_text": "No Total Treatment",
        },
        actor_user_id="admin-test",
    )

    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    resp = client.post(
        f"/reception/entries/{entry['id']}/approve",
        data={"csrf_token": token, "confirm_approve": "1"},
        follow_redirects=False,
    )

    assert resp.status_code == 400
    assert "Total amount is required before approval." in resp.data.decode("utf-8")
    assert _count_patients() == before_patients
    assert _count_payments() == before_payments
    unchanged = get_entry(entry["id"])
    assert unchanged["status"] == "new"
