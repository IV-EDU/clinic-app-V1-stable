from __future__ import annotations

import re
from uuid import uuid4

from werkzeug.security import generate_password_hash

from clinic_app.services.database import db as raw_db
from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, ANY_DOCTOR_LABEL
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


def _insert_reception_event(
    *,
    entry_id: str,
    action: str,
    actor_user_id: str,
    created_at: str,
    note: str | None = None,
    to_status: str | None = None,
):
    conn = raw_db()
    try:
        conn.execute(
            """
            INSERT INTO reception_entry_events (
                id, entry_id, action, actor_user_id,
                from_status, to_status, note, meta_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                entry_id,
                action,
                actor_user_id,
                None,
                to_status,
                note,
                "{}",
                created_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _set_entry_status(
    entry_id: str,
    *,
    status: str,
    last_action: str,
    reason_field: str | None = None,
    reason: str | None = None,
):
    conn = raw_db()
    try:
        if reason_field:
            conn.execute(
                f"UPDATE reception_entries SET status=?, last_action=?, {reason_field}=? WHERE id=?",
                (status, last_action, reason, entry_id),
            )
        else:
            conn.execute(
                "UPDATE reception_entries SET status=?, last_action=? WHERE id=?",
                (status, last_action, entry_id),
            )
        conn.commit()
    finally:
        conn.close()


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


def _seed_patient_with_treatment(*, remaining_cents: int = 14000) -> tuple[str, str]:
    patient_id = f"patient-{uuid4()}"
    treatment_id = f"treatment-{uuid4()}"
    conn = raw_db()
    try:
        conn.execute(
            """
            INSERT INTO patients(id, short_id, full_name, phone, notes, primary_page_number, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (patient_id, f"P-{uuid4().hex[:6]}", "Review Payment Patient", "01044444444", "", "73"),
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
                "Review Payment Treatment",
                ANY_DOCTOR_ID,
                ANY_DOCTOR_LABEL,
                remaining_cents,
                20000,
                1000,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return patient_id, treatment_id


def _seed_child_payment(patient_id: str, treatment_id: str, *, amount_cents: int = 2000) -> str:
    child_id = f"payment-{uuid4()}"
    conn = raw_db()
    try:
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
                amount_cents,
                "cash",
                "",
                ANY_DOCTOR_ID,
                ANY_DOCTOR_LABEL,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return child_id


def _seed_patient_profile(
    *,
    full_name: str = "Correction Patient",
    phone: str = "01012121212",
    page_number: str = "18",
    short_id: str | None = None,
) -> str:
    patient_id = f"patient-{uuid4()}"
    conn = raw_db()
    try:
        conn.execute(
            """
            INSERT INTO patients(id, short_id, full_name, phone, notes, primary_page_number, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (patient_id, short_id or f"P-{uuid4().hex[:6]}", full_name, phone, "Original note", page_number),
        )
        conn.execute(
            """
            INSERT INTO patient_phones(id, patient_id, phone, phone_normalized, label, is_primary)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (f"phone-{uuid4()}", patient_id, phone, phone, None),
        )
        conn.execute(
            """
            INSERT INTO patient_pages(id, patient_id, page_number, notebook_name)
            VALUES (?, ?, ?, ?)
            """,
            (f"page-{uuid4()}", patient_id, page_number, "Notebook A"),
        )
        conn.commit()
    finally:
        conn.close()
    return patient_id


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


def test_review_user_can_return_draft_and_reception_sees_returned_state(client):
    owner_role_id = _create_role("Reception Desk Owner Returned", ["reception_entries:create"])
    review_role_id = _create_role("Reception Return Team 2", ["reception_entries:review"])
    owner_user_id = _create_user("desk-owner-returned", "password123", [owner_role_id])
    _create_user("review-return-user-2", "password123", [review_role_id])

    entry = _create_draft(patient_name="Returned Draft", actor_user_id=owner_user_id)

    reviewer_client = client.application.test_client()
    _login(reviewer_client, "review-return-user-2", "password123")
    page = reviewer_client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    resp = reviewer_client.post(
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

    owner_client = client.application.test_client()
    _login(owner_client, "desk-owner-returned", "password123")
    desk = owner_client.get("/reception")
    body = desk.data.decode("utf-8")
    assert "Returned Draft" in body
    assert "Returned" in body
    assert "Fix total" in body
    assert "Edit Draft" in body


def test_owner_can_open_edit_page_for_returned_draft(client):
    owner_role_id = _create_role("Reception Desk Owner Edit", ["reception_entries:create"])
    review_role_id = _create_role("Reception Return Team 3", ["reception_entries:review"])
    owner_user_id = _create_user("desk-owner-edit", "password123", [owner_role_id])
    _create_user("review-return-user-3", "password123", [review_role_id])

    entry = _create_draft(patient_name="Edit Me", actor_user_id=owner_user_id)
    reviewer_client = client.application.test_client()
    _login(reviewer_client, "review-return-user-3", "password123")
    page = reviewer_client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    reviewer_client.post(
        f"/reception/entries/{entry['id']}/return",
        data={"csrf_token": token, "return_reason": "Please update note"},
        follow_redirects=False,
    )

    owner_client = client.application.test_client()
    _login(owner_client, "desk-owner-edit", "password123")
    resp = owner_client.get(f"/reception/entries/{entry['id']}/edit")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Edit returned draft" in body
    assert "Please update note" in body
    assert 'value="Edit Me"' in body


def test_owner_cannot_open_edit_page_for_non_returned_draft(client):
    owner_role_id = _create_role("Reception Desk Owner Non Returned", ["reception_entries:create"])
    owner_user_id = _create_user("desk-owner-non-returned", "password123", [owner_role_id])
    entry = _create_draft(patient_name="Not Returned Yet", actor_user_id=owner_user_id)
    owner_client = client.application.test_client()
    _login(owner_client, "desk-owner-non-returned", "password123")
    resp = owner_client.get(f"/reception/entries/{entry['id']}/edit")
    assert resp.status_code == 403


def test_non_owner_gets_403_on_edit_page(client):
    helper_role_id = _create_role("Reception Edit Helper", ["reception_entries:create"])
    other_user_id = _create_user("edit-owner", "password123", [helper_role_id])
    _create_user("edit-viewer", "password123", [helper_role_id])
    entry = _create_draft(patient_name="Other User Draft", actor_user_id=other_user_id)

    review_role_id = _create_role("Reception Return Team 4", ["reception_entries:review"])
    _create_user("review-return-user-4", "password123", [review_role_id])
    _login(client, "review-return-user-4", "password123")
    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    client.post(
        f"/reception/entries/{entry['id']}/return",
        data={"csrf_token": token, "return_reason": "Owner must fix"},
        follow_redirects=False,
    )

    _login(client, "edit-viewer", "password123")
    resp = client.get(f"/reception/entries/{entry['id']}/edit")
    assert resp.status_code == 403


def test_valid_edit_post_resubmits_returned_draft_and_requeues_it(client):
    owner_role_id = _create_role("Reception Desk Owner Resubmit", ["reception_entries:create"])
    review_role_id = _create_role("Reception Return Team 5", ["reception_entries:review"])
    owner_user_id = _create_user("desk-owner-resubmit", "password123", [owner_role_id])
    _create_user("review-return-user-5", "password123", [review_role_id])

    older = _create_draft(patient_name="Older Waiting", actor_user_id=owner_user_id)
    entry = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Resubmit Me",
            "doctor_id": "any-doctor",
            "doctor_label": "Any Doctor",
            "total_amount": "100",
            "payload_json": {"note": "old note"},
        },
        actor_user_id=owner_user_id,
    )

    reviewer_client = client.application.test_client()
    _login(reviewer_client, "review-return-user-5", "password123")
    page = reviewer_client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    reviewer_client.post(
        f"/reception/entries/{entry['id']}/return",
        data={"csrf_token": token, "return_reason": "Fix total and note"},
        follow_redirects=False,
    )

    owner_client = client.application.test_client()
    _login(owner_client, "desk-owner-resubmit", "password123")
    edit_page = owner_client.get(f"/reception/entries/{entry['id']}/edit")
    edit_token = _extract_csrf(edit_page)
    resp = owner_client.post(
        f"/reception/entries/{entry['id']}/edit",
        data={
            "csrf_token": edit_token,
            "patient_name": "Resubmit Me",
            "phone": "01012300000",
            "page_number": "45",
            "visit_date": "2026-03-18",
            "visit_type": "followup",
            "treatment_text": "Updated Treatment",
            "doctor_id": "any-doctor",
            "money_received_today": "1",
            "paid_today": "50",
            "total_amount": "150",
            "discount_amount": "10",
            "note": "fixed note",
        },
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith("/reception?view=desk")

    updated = get_entry(entry["id"])
    assert updated["last_action"] == "edited"
    assert updated["status"] == "edited"
    assert updated["return_reason"] is None
    assert updated["payload_json"] == {"note": "fixed note"}
    assert list_entry_events(entry["id"])[0]["action"] == "edited"

    desk = owner_client.get("/reception?view=desk")
    desk_body = desk.data.decode("utf-8")
    assert "Fix total and note" not in desk_body
    assert "Waiting review" in desk_body
    assert desk_body.index("Resubmit Me") < desk_body.index("Older Waiting")

    queue = reviewer_client.get("/reception?view=queue")
    queue_body = queue.data.decode("utf-8")
    assert "Resubmit Me" in queue_body
    assert "Fix total and note" not in queue_body
    assert queue_body.index("Resubmit Me") < queue_body.index("Older Waiting")


def test_invalid_edit_post_rerenders_with_sticky_values(client):
    owner_role_id = _create_role("Reception Desk Owner Sticky", ["reception_entries:create"])
    review_role_id = _create_role("Reception Return Team 6", ["reception_entries:review"])
    owner_user_id = _create_user("desk-owner-sticky", "password123", [owner_role_id])
    _create_user("review-return-user-6", "password123", [review_role_id])

    entry = _create_draft(patient_name="Sticky Edit", actor_user_id=owner_user_id)
    reviewer_client = client.application.test_client()
    _login(reviewer_client, "review-return-user-6", "password123")
    page = reviewer_client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    reviewer_client.post(
        f"/reception/entries/{entry['id']}/return",
        data={"csrf_token": token, "return_reason": "Doctor missing"},
        follow_redirects=False,
    )

    owner_client = client.application.test_client()
    _login(owner_client, "desk-owner-sticky", "password123")
    edit_page = owner_client.get(f"/reception/entries/{entry['id']}/edit")
    edit_token = _extract_csrf(edit_page)
    resp = owner_client.post(
        f"/reception/entries/{entry['id']}/edit",
        data={
            "csrf_token": edit_token,
            "patient_name": "Sticky Edited",
            "doctor_id": "",
            "money_received_today": "1",
            "paid_today": "",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 400
    body = resp.data.decode("utf-8")
    assert "Doctor is required." in body
    assert "Paid today is required when money was received today." in body
    assert 'value="Sticky Edited"' in body

    unchanged = get_entry(entry["id"])
    assert unchanged["last_action"] == "returned"
    assert unchanged["return_reason"] == "Doctor missing"


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


def test_manager_detail_shows_existing_patient_routing_options(client, admin_user):
    approve_role_id = _create_role("Reception Approver Routing Detail", ["reception_entries:approve"])
    _create_user("approver-routing-detail", "password123", [approve_role_id])
    _login(client, "approver-routing-detail", "password123")
    _seed_patient_profile(
        full_name="Routing Candidate",
        phone="01022233344",
        page_number="88",
        short_id="P-ROUTE1",
    )
    entry = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Routing Candidate",
            "phone": "01022233344",
            "page_number": "88",
            "doctor_id": "any-doctor",
            "doctor_label": "Any Doctor",
            "visit_date": "2026-03-17",
            "treatment_text": "Routing Review Treatment",
            "total_amount": "300",
        },
        actor_user_id="admin-test",
    )

    resp = client.get(f"/reception/entries/{entry['id']}")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Approval route" in body
    assert "Create new patient" in body
    assert "Attach to existing patient" in body
    assert "Possible existing patients" in body
    assert "Routing Candidate" in body
    assert "/reception/api/patients/search" in body


def test_reception_patient_search_returns_matches_for_manager_review(client, admin_user):
    review_role_id = _create_role("Reception Review Search", ["reception_entries:review"])
    _create_user("review-search-user", "password123", [review_role_id])
    _login(client, "review-search-user", "password123")
    patient_id = _seed_patient_profile(
        full_name="Search Match",
        phone="01055577788",
        page_number="909",
        short_id="P-SEARCH",
    )

    resp = client.get("/reception/api/patients/search?q=01055577788")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload
    match = next(item for item in payload if item["id"] == patient_id)
    assert match == {
        "id": patient_id,
        "full_name": "Search Match",
        "short_id": "P-SEARCH",
        "phone": "01055577788",
        "page_number": "909",
    }


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


def test_approve_can_attach_new_treatment_to_existing_patient(client, admin_user):
    approve_role_id = _create_role("Reception Approver Attach Existing", ["reception_entries:approve"])
    _create_user("approver-attach-existing", "password123", [approve_role_id])
    _login(client, "approver-attach-existing", "password123")
    existing_patient_id = _seed_patient_profile(
        full_name="Existing Routing Patient",
        phone="01077788899",
        page_number="501",
        short_id="P-EXIST1",
    )

    before_patients = _count_patients()
    before_payments = _count_payments()
    entry = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Existing Routing Patient",
            "phone": "01077788899",
            "page_number": "501",
            "doctor_id": "any-doctor",
            "doctor_label": "Any Doctor",
            "visit_date": "2026-03-17",
            "visit_type": "exam",
            "treatment_text": "Attach Existing Treatment",
            "total_amount": "300",
            "discount_amount": "25",
            "paid_today": "50",
            "money_received_today": True,
            "payload_json": {"note": "Do not edit patient profile"},
        },
        actor_user_id="admin-test",
    )

    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    resp = client.post(
        f"/reception/entries/{entry['id']}/approve",
        data={
            "csrf_token": token,
            "approval_route": "attach_existing",
            "target_patient_id": existing_patient_id,
            "confirm_approve": "1",
        },
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    assert _count_patients() == before_patients
    assert _count_payments() == before_payments + 1

    approved = get_entry(entry["id"])
    assert approved["status"] == "approved"
    assert approved["target_patient_id"] == existing_patient_id
    assert approved["target_treatment_id"]

    conn = raw_db()
    try:
        patient = conn.execute(
            "SELECT full_name, phone, primary_page_number FROM patients WHERE id=?",
            (existing_patient_id,),
        ).fetchone()
        payment = conn.execute(
            """
            SELECT patient_id, treatment, amount_cents, total_amount_cents, discount_cents, remaining_cents
            FROM payments WHERE id=?
            """,
            (approved["target_treatment_id"],),
        ).fetchone()
    finally:
        conn.close()

    assert patient["full_name"] == "Existing Routing Patient"
    assert patient["phone"] == "01077788899"
    assert patient["primary_page_number"] == "501"
    assert payment["patient_id"] == existing_patient_id
    assert payment["treatment"] == "Attach Existing Treatment"
    assert int(payment["amount_cents"] or 0) == 5000
    assert int(payment["total_amount_cents"] or 0) == 30000
    assert int(payment["discount_cents"] or 0) == 2500
    assert int(payment["remaining_cents"] or 0) == 22500


def test_attach_existing_requires_target_patient_id(client, admin_user):
    approve_role_id = _create_role("Reception Approver Attach Missing", ["reception_entries:approve"])
    _create_user("approver-attach-missing", "password123", [approve_role_id])
    _login(client, "approver-attach-missing", "password123")
    entry = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Attach Missing",
            "phone": "01010101010",
            "page_number": "41",
            "doctor_id": "any-doctor",
            "doctor_label": "Any Doctor",
            "visit_date": "2026-03-17",
            "treatment_text": "Attach Missing Treatment",
            "total_amount": "200",
        },
        actor_user_id="admin-test",
    )

    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    resp = client.post(
        f"/reception/entries/{entry['id']}/approve",
        data={
            "csrf_token": token,
            "approval_route": "attach_existing",
            "confirm_approve": "1",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 400
    assert "Choose an existing patient before approval." in resp.data.decode("utf-8")
    unchanged = get_entry(entry["id"])
    assert unchanged["status"] == "new"
    assert unchanged["target_patient_id"] is None


def test_attach_existing_blocks_when_selected_patient_is_deleted(client, admin_user):
    approve_role_id = _create_role("Reception Approver Attach Stale", ["reception_entries:approve"])
    _create_user("approver-attach-stale", "password123", [approve_role_id])
    _login(client, "approver-attach-stale", "password123")
    existing_patient_id = _seed_patient_profile(
        full_name="Deleted Routing Patient",
        phone="01033344455",
        page_number="63",
        short_id="P-DELETE",
    )
    entry = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Deleted Routing Patient",
            "phone": "01033344455",
            "page_number": "63",
            "doctor_id": "any-doctor",
            "doctor_label": "Any Doctor",
            "visit_date": "2026-03-17",
            "treatment_text": "Deleted Patient Treatment",
            "total_amount": "220",
        },
        actor_user_id="admin-test",
    )

    conn = raw_db()
    try:
        conn.execute("DELETE FROM patient_phones WHERE patient_id=?", (existing_patient_id,))
        conn.execute("DELETE FROM patient_pages WHERE patient_id=?", (existing_patient_id,))
        conn.execute("DELETE FROM patients WHERE id=?", (existing_patient_id,))
        conn.commit()
    finally:
        conn.close()

    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    resp = client.post(
        f"/reception/entries/{entry['id']}/approve",
        data={
            "csrf_token": token,
            "approval_route": "attach_existing",
            "target_patient_id": existing_patient_id,
            "confirm_approve": "1",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 400
    assert "The selected live patient no longer exists. Review the draft again before approving." in resp.data.decode("utf-8")
    unchanged = get_entry(entry["id"])
    assert unchanged["status"] == "new"
    assert unchanged["target_patient_id"] is None


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


def test_manager_can_open_new_payment_draft_detail(client, admin_user):
    review_role_id = _create_role("Reception Review Payment Detail", ["reception_entries:review"])
    _create_user("review-payment-detail", "password123", [review_role_id])
    _login(client, "review-payment-detail", "password123")
    patient_id, treatment_id = _seed_patient_with_treatment()
    entry = create_entry(
        {
            "draft_type": "new_payment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "patient_name": "Review Payment Patient",
            "phone": "01044444444",
            "page_number": "73",
            "treatment_text": "Review Payment Treatment",
            "doctor_id": ANY_DOCTOR_ID,
            "doctor_label": ANY_DOCTOR_LABEL,
            "visit_date": "2026-03-18",
            "paid_today": "40",
            "total_amount": "200",
            "discount_amount": "10",
            "payload_json": {
                "submitted_amount_cents": 4000,
                "treatment_remaining_cents_at_submit": 14000,
                "treatment_total_paid_cents_at_submit": 5000,
                "method": "card",
            },
        },
        actor_user_id="admin-test",
    )

    resp = client.get(f"/reception/entries/{entry['id']}")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Review Payment Patient" in body
    assert "Remaining at submission" in body
    assert "Current remaining" in body


def test_manager_sees_edit_action_and_can_open_pending_new_treatment_edit_page(client, admin_user):
    review_role_id = _create_role("Reception Review Pending Treatment Edit", ["reception_entries:review"])
    _create_user("review-pending-treatment-edit", "password123", [review_role_id])
    _login(client, "review-pending-treatment-edit", "password123")
    entry = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Manager Editable Treatment",
            "phone": "01099911122",
            "page_number": "84",
            "doctor_id": "any-doctor",
            "doctor_label": "Any Doctor",
            "visit_date": "2026-03-19",
            "visit_type": "exam",
            "treatment_text": "Pending Crown",
            "total_amount": "300",
            "discount_amount": "20",
            "paid_today": "50",
            "money_received_today": True,
        },
        actor_user_id="admin-test",
    )

    detail = client.get(f"/reception/entries/{entry['id']}")
    assert detail.status_code == 200
    detail_body = detail.data.decode("utf-8")
    assert "Edit draft" in detail_body

    edit_page = client.get(f"/reception/entries/{entry['id']}/edit")
    assert edit_page.status_code == 200
    body = edit_page.data.decode("utf-8")
    assert "Edit pending treatment draft" in body
    assert 'value="Manager Editable Treatment"' in body


def test_manager_can_open_edit_pages_for_all_supported_pending_locked_drafts(client, admin_user):
    review_role_id = _create_role("Reception Review All Pending Edit", ["reception_entries:review"])
    _create_user("review-all-pending-edit", "password123", [review_role_id])
    _login(client, "review-all-pending-edit", "password123")
    patient_id, treatment_id = _seed_patient_with_treatment()
    child_id = _seed_child_payment(patient_id, treatment_id)
    patient_profile_id = _seed_patient_profile(full_name="Manager Edit Patient")

    new_payment = create_entry(
        {
            "draft_type": "new_payment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "patient_name": "Review Payment Patient",
            "phone": "01044444444",
            "page_number": "73",
            "treatment_text": "Review Payment Treatment",
            "doctor_id": ANY_DOCTOR_ID,
            "doctor_label": ANY_DOCTOR_LABEL,
            "visit_date": "2026-03-18",
            "paid_today": "40",
            "total_amount": "200",
            "discount_amount": "10",
            "payload_json": {
                "submitted_amount_cents": 4000,
                "treatment_remaining_cents_at_submit": 14000,
                "treatment_total_paid_cents_at_submit": 5000,
                "method": "card",
            },
        },
        actor_user_id="admin-test",
    )
    edit_payment = create_entry(
        {
            "draft_type": "edit_payment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "locked_payment_id": child_id,
            "doctor_id": ANY_DOCTOR_ID,
            "doctor_label": ANY_DOCTOR_LABEL,
            "visit_date": "2026-03-22",
            "paid_today": "18",
            "payload_json": {
                "current": {
                    "payment_id": child_id,
                    "treatment_id": treatment_id,
                    "amount_cents": 2000,
                    "visit_date": "2026-03-18",
                    "method": "cash",
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "note": "",
                    "is_initial_payment": 0,
                },
                "proposed": {
                    "amount": "18",
                    "visit_date": "2026-03-22",
                    "method": "card",
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "note": "Payment correction note",
                },
            },
        },
        actor_user_id="admin-test",
    )
    edit_treatment = create_entry(
        {
            "draft_type": "edit_treatment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "doctor_id": ANY_DOCTOR_ID,
            "doctor_label": ANY_DOCTOR_LABEL,
            "payload_json": {
                "proposed": {
                    "treatment_text": "Updated Review Treatment",
                    "visit_date": "2026-03-25",
                    "visit_type": "followup",
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "total_amount": "260",
                    "discount_amount": "10",
                    "note": "Treatment correction note",
                }
            },
        },
        actor_user_id="admin-test",
    )
    edit_patient = create_entry(
        {
            "draft_type": "edit_patient",
            "source": "patient_file",
            "locked_patient_id": patient_profile_id,
            "payload_json": {
                "current": {
                    "short_id": "P-ORIG",
                    "full_name": "Manager Edit Patient",
                    "primary_phone": "01012121212",
                    "phones": [{"phone": "01012121212", "label": None, "is_primary": 1}],
                    "primary_page_number": "18",
                    "pages": [{"page_number": "18", "notebook_name": "Notebook A", "notebook_color": ""}],
                    "notes": "Original note",
                },
                "proposed": {
                    "full_name": "Manager Edit Patient Updated",
                    "phones": [{"phone": "01034343434", "label": None, "is_primary": 1}],
                    "pages": [{"page_number": "44", "notebook_name": "Notebook B", "notebook_color": ""}],
                    "notes": "Updated note",
                },
                "note": "Reception correction note",
            },
        },
        actor_user_id="admin-test",
    )

    new_payment_page = client.get(f"/reception/entries/{new_payment['id']}/edit")
    assert new_payment_page.status_code == 200
    assert "Edit pending payment draft" in new_payment_page.data.decode("utf-8")

    edit_payment_page = client.get(f"/reception/entries/{edit_payment['id']}/edit")
    assert edit_payment_page.status_code == 200
    assert "Edit pending payment correction" in edit_payment_page.data.decode("utf-8")

    edit_treatment_page = client.get(f"/reception/entries/{edit_treatment['id']}/edit")
    assert edit_treatment_page.status_code == 200
    assert "Edit pending treatment correction" in edit_treatment_page.data.decode("utf-8")

    edit_patient_page = client.get(f"/reception/entries/{edit_patient['id']}/edit")
    assert edit_patient_page.status_code == 200
    assert "Edit pending patient correction" in edit_patient_page.data.decode("utf-8")


def test_create_only_user_cannot_edit_someone_elses_normal_pending_draft(client, admin_user):
    create_role_id = _create_role("Reception Create Pending Edit Blocked", ["reception_entries:create"])
    other_user_id = _create_user("pending-edit-owner", "password123", [create_role_id])
    _create_user("pending-edit-viewer", "password123", [create_role_id])
    entry = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Other Pending Draft",
            "doctor_id": "any-doctor",
            "doctor_label": "Any Doctor",
            "visit_date": "2026-03-20",
            "treatment_text": "Pending Draft",
            "total_amount": "180",
        },
        actor_user_id=other_user_id,
    )

    _login(client, "pending-edit-viewer", "password123")
    resp = client.get(f"/reception/entries/{entry['id']}/edit")
    assert resp.status_code == 403


def test_manager_cannot_edit_closed_draft(client, admin_user):
    review_role_id = _create_role("Reception Review Closed Edit", ["reception_entries:review"])
    _create_user("review-closed-edit", "password123", [review_role_id])
    _login(client, "review-closed-edit", "password123")
    entry = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Closed Draft",
            "doctor_id": "any-doctor",
            "doctor_label": "Any Doctor",
            "treatment_text": "Closed Crown",
            "total_amount": "200",
        },
        actor_user_id="admin-test",
    )

    conn = raw_db()
    try:
        conn.execute(
            "UPDATE reception_entries SET status='approved', last_action='approved' WHERE id=?",
            (entry["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    resp = client.get(f"/reception/entries/{entry['id']}/edit")
    assert resp.status_code == 403


def test_manager_can_approve_locked_new_payment_draft(client, admin_user):
    approve_role_id = _create_role("Reception Payment Approver", ["reception_entries:approve"])
    _create_user("payment-approver", "password123", [approve_role_id])
    _login(client, "payment-approver", "password123")
    patient_id, treatment_id = _seed_patient_with_treatment()
    before_payments = _count_payments()
    entry = create_entry(
        {
            "draft_type": "new_payment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "patient_name": "Review Payment Patient",
            "phone": "01044444444",
            "page_number": "73",
            "treatment_text": "Review Payment Treatment",
            "doctor_id": ANY_DOCTOR_ID,
            "doctor_label": ANY_DOCTOR_LABEL,
            "visit_date": "2026-03-18",
            "paid_today": "40",
            "total_amount": "200",
            "discount_amount": "10",
            "payload_json": {
                "submitted_amount_cents": 4000,
                "treatment_remaining_cents_at_submit": 14000,
                "treatment_total_paid_cents_at_submit": 5000,
                "method": "transfer",
                "note": "approval payment note",
            },
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
    assert _count_payments() == before_payments + 1
    approved = get_entry(entry["id"])
    assert approved["status"] == "approved"
    assert approved["target_patient_id"] == patient_id
    assert approved["target_treatment_id"] == treatment_id
    assert approved["target_payment_id"]
    assert list_entry_events(entry["id"])[0]["action"] == "approved"

    conn = raw_db()
    try:
        child = conn.execute(
            "SELECT parent_payment_id, amount_cents, method FROM payments WHERE id=?",
            (approved["target_payment_id"],),
        ).fetchone()
        parent = conn.execute(
            "SELECT remaining_cents FROM payments WHERE id=?",
            (treatment_id,),
        ).fetchone()
    finally:
        conn.close()

    assert child["parent_payment_id"] == treatment_id
    assert int(child["amount_cents"] or 0) == 4000
    assert child["method"] == "transfer"
    assert int(parent["remaining_cents"] or 0) == 10000


def test_new_payment_approval_failure_when_remaining_shrinks_leaves_draft_pending(client, admin_user):
    approve_role_id = _create_role("Reception Payment Approver 2", ["reception_entries:approve"])
    _create_user("payment-approver-2", "password123", [approve_role_id])
    _login(client, "payment-approver-2", "password123")
    patient_id, treatment_id = _seed_patient_with_treatment()
    entry = create_entry(
        {
            "draft_type": "new_payment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "patient_name": "Review Payment Patient",
            "phone": "01044444444",
            "page_number": "73",
            "treatment_text": "Review Payment Treatment",
            "doctor_id": ANY_DOCTOR_ID,
            "doctor_label": ANY_DOCTOR_LABEL,
            "visit_date": "2026-03-18",
            "paid_today": "120",
            "total_amount": "200",
            "discount_amount": "10",
            "payload_json": {
                "submitted_amount_cents": 12000,
                "treatment_remaining_cents_at_submit": 14000,
                "treatment_total_paid_cents_at_submit": 5000,
                "method": "cash",
            },
        },
        actor_user_id="admin-test",
    )

    conn = raw_db()
    try:
        conn.execute(
            """
            INSERT INTO payments(
                id, patient_id, parent_payment_id, paid_at, amount_cents, method, note, treatment,
                doctor_id, doctor_label, remaining_cents, total_amount_cents, examination_flag,
                followup_flag, discount_cents
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, 0, 0, 0, 0, 0)
            """,
            (
                f"pay-{uuid4()}",
                patient_id,
                treatment_id,
                "2026-03-19",
                5000,
                "cash",
                "",
                ANY_DOCTOR_ID,
                ANY_DOCTOR_LABEL,
            ),
        )
        conn.execute("UPDATE payments SET remaining_cents=? WHERE id=?", (9000, treatment_id))
        conn.commit()
    finally:
        conn.close()

    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    resp = client.post(
        f"/reception/entries/{entry['id']}/approve",
        data={"csrf_token": token, "confirm_approve": "1"},
        follow_redirects=False,
    )

    assert resp.status_code == 400
    body = resp.data.decode("utf-8")
    assert "Paid today cannot be greater than the amount due." in body
    unchanged = get_entry(entry["id"])
    assert unchanged["status"] == "new"
    assert unchanged["target_payment_id"] is None


def test_reapproving_new_payment_draft_is_blocked(client, admin_user):
    approve_role_id = _create_role("Reception Payment Approver 3", ["reception_entries:approve"])
    _create_user("payment-approver-3", "password123", [approve_role_id])
    _login(client, "payment-approver-3", "password123")
    patient_id, treatment_id = _seed_patient_with_treatment()
    entry = create_entry(
        {
            "draft_type": "new_payment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "patient_name": "Review Payment Patient",
            "doctor_id": ANY_DOCTOR_ID,
            "doctor_label": ANY_DOCTOR_LABEL,
            "visit_date": "2026-03-18",
            "paid_today": "20",
            "total_amount": "200",
            "discount_amount": "10",
            "payload_json": {
                "submitted_amount_cents": 2000,
                "treatment_remaining_cents_at_submit": 14000,
                "treatment_total_paid_cents_at_submit": 5000,
            },
        },
        actor_user_id="admin-test",
    )

    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    first = client.post(
        f"/reception/entries/{entry['id']}/approve",
        data={"csrf_token": token, "confirm_approve": "1"},
        follow_redirects=False,
    )
    assert first.status_code in (302, 303)

    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    second = client.post(
        f"/reception/entries/{entry['id']}/approve",
        data={"csrf_token": token, "confirm_approve": "1"},
        follow_redirects=False,
    )
    assert second.status_code == 400
    assert "Cannot approve a closed draft." in second.data.decode("utf-8")


def test_manager_can_edit_held_new_payment_draft_without_live_write(client, admin_user):
    review_role_id = _create_role("Reception Review Edit Held Payment", ["reception_entries:review"])
    _create_user("review-edit-held-payment", "password123", [review_role_id])
    _login(client, "review-edit-held-payment", "password123")
    patient_id, treatment_id = _seed_patient_with_treatment()
    before_payments = _count_payments()
    entry = create_entry(
        {
            "draft_type": "new_payment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "patient_name": "Review Payment Patient",
            "phone": "01044444444",
            "page_number": "73",
            "treatment_text": "Review Payment Treatment",
            "doctor_id": ANY_DOCTOR_ID,
            "doctor_label": ANY_DOCTOR_LABEL,
            "visit_date": "2026-03-18",
            "paid_today": "40",
            "total_amount": "200",
            "discount_amount": "10",
            "payload_json": {
                "submitted_amount_cents": 4000,
                "treatment_remaining_cents_at_submit": 14000,
                "treatment_total_paid_cents_at_submit": 5000,
                "method": "cash",
            },
        },
        actor_user_id="admin-test",
    )

    detail = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(detail)
    hold = client.post(
        f"/reception/entries/{entry['id']}/hold",
        data={"csrf_token": token, "hold_note": "Need manager fix"},
        follow_redirects=False,
    )
    assert hold.status_code in (302, 303)

    edit_page = client.get(f"/reception/entries/{entry['id']}/edit")
    edit_token = _extract_csrf(edit_page)
    resp = client.post(
        f"/reception/entries/{entry['id']}/edit",
        data={
            "csrf_token": edit_token,
            "amount": "35",
            "visit_date": "2026-03-21",
            "method": "transfer",
            "doctor_id": ANY_DOCTOR_ID,
            "note": "Manager adjusted amount",
        },
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith(f"/reception/entries/{entry['id']}")
    assert _count_payments() == before_payments

    updated = get_entry(entry["id"])
    assert updated["status"] == "edited"
    assert updated["last_action"] == "edited"
    assert updated["hold_reason"] is None
    assert updated["reviewed_by_user_id"] is not None
    assert updated["paid_today_cents"] == 3500
    assert updated["visit_date"] == "2026-03-21"
    assert updated["payload_json"]["method"] == "transfer"
    assert updated["payload_json"]["note"] == "Manager adjusted amount"
    assert list_entry_events(entry["id"])[0]["meta_json"] == {"manager_edit": True}


def test_manager_edit_new_payment_validation_error_keeps_draft_pending(client, admin_user):
    review_role_id = _create_role("Reception Review Invalid Payment Edit", ["reception_entries:review"])
    _create_user("review-invalid-payment-edit", "password123", [review_role_id])
    _login(client, "review-invalid-payment-edit", "password123")
    patient_id, treatment_id = _seed_patient_with_treatment()
    entry = create_entry(
        {
            "draft_type": "new_payment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "patient_name": "Review Payment Patient",
            "phone": "01044444444",
            "page_number": "73",
            "treatment_text": "Review Payment Treatment",
            "doctor_id": ANY_DOCTOR_ID,
            "doctor_label": ANY_DOCTOR_LABEL,
            "visit_date": "2026-03-18",
            "paid_today": "40",
            "total_amount": "200",
            "discount_amount": "10",
            "payload_json": {
                "submitted_amount_cents": 4000,
                "treatment_remaining_cents_at_submit": 14000,
                "treatment_total_paid_cents_at_submit": 5000,
                "method": "cash",
            },
        },
        actor_user_id="admin-test",
    )

    edit_page = client.get(f"/reception/entries/{entry['id']}/edit")
    edit_token = _extract_csrf(edit_page)
    resp = client.post(
        f"/reception/entries/{entry['id']}/edit",
        data={
            "csrf_token": edit_token,
            "amount": "200",
            "visit_date": "2026-03-21",
            "method": "transfer",
            "doctor_id": ANY_DOCTOR_ID,
            "note": "Too high",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 400
    body = resp.data.decode("utf-8")
    assert "Paid today cannot be greater than the amount due." in body
    assert 'value="200"' in body

    unchanged = get_entry(entry["id"])
    assert unchanged["status"] == "new"
    assert unchanged["paid_today_cents"] == 4000


def test_manager_can_open_edit_payment_draft_detail(client, admin_user):
    review_role_id = _create_role("Reception Review Edit Payment Detail", ["reception_entries:review"])
    _create_user("review-edit-payment-detail", "password123", [review_role_id])
    _login(client, "review-edit-payment-detail", "password123")
    patient_id, treatment_id = _seed_patient_with_treatment()
    child_id = _seed_child_payment(patient_id, treatment_id)
    entry = create_entry(
        {
            "draft_type": "edit_payment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "locked_payment_id": child_id,
            "doctor_id": ANY_DOCTOR_ID,
            "doctor_label": ANY_DOCTOR_LABEL,
            "visit_date": "2026-03-22",
            "paid_today": "18",
            "payload_json": {
                "current": {
                    "payment_id": child_id,
                    "treatment_id": treatment_id,
                    "amount_cents": 2000,
                    "visit_date": "2026-03-18",
                    "method": "cash",
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "note": "",
                    "is_initial_payment": 0,
                },
                "proposed": {
                    "amount": "18",
                    "visit_date": "2026-03-22",
                    "method": "card",
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "note": "Payment correction note",
                },
            },
        },
        actor_user_id="admin-test",
    )

    resp = client.get(f"/reception/entries/{entry['id']}")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Payment correction" in body
    assert "Current remaining" in body


def test_manager_can_approve_initial_payment_correction_draft(client, admin_user):
    approve_role_id = _create_role("Reception Edit Payment Approver Parent", ["reception_entries:approve"])
    _create_user("edit-payment-approver-parent", "password123", [approve_role_id])
    _login(client, "edit-payment-approver-parent", "password123")
    patient_id, treatment_id = _seed_patient_with_treatment()
    entry = create_entry(
        {
            "draft_type": "edit_payment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "locked_payment_id": treatment_id,
            "doctor_id": ANY_DOCTOR_ID,
            "doctor_label": ANY_DOCTOR_LABEL,
            "visit_date": "2026-03-23",
            "paid_today": "60",
            "payload_json": {
                "current": {
                    "payment_id": treatment_id,
                    "treatment_id": treatment_id,
                    "amount_cents": 5000,
                    "visit_date": "2026-03-17",
                    "method": "cash",
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "note": "",
                    "is_initial_payment": 1,
                },
                "proposed": {
                    "amount": "60",
                    "visit_date": "2026-03-23",
                    "method": "card",
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "note": "Updated initial payment",
                },
            },
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
    approved = get_entry(entry["id"])
    assert approved["status"] == "approved"
    assert approved["target_patient_id"] == patient_id
    assert approved["target_treatment_id"] == treatment_id
    assert approved["target_payment_id"] == treatment_id

    conn = raw_db()
    try:
        parent = conn.execute(
            "SELECT amount_cents, paid_at, method, note, treatment, total_amount_cents, remaining_cents FROM payments WHERE id=?",
            (treatment_id,),
        ).fetchone()
    finally:
        conn.close()

    assert int(parent["amount_cents"] or 0) == 6000
    assert parent["paid_at"] == "2026-03-23"
    assert parent["method"] == "card"
    assert parent["note"] == "Updated initial payment"
    assert parent["treatment"] == "Review Payment Treatment"
    assert int(parent["total_amount_cents"] or 0) == 20000
    assert int(parent["remaining_cents"] or 0) == 13000


def test_manager_can_approve_child_payment_correction_draft(client, admin_user):
    approve_role_id = _create_role("Reception Edit Payment Approver Child", ["reception_entries:approve"])
    _create_user("edit-payment-approver-child", "password123", [approve_role_id])
    _login(client, "edit-payment-approver-child", "password123")
    patient_id, treatment_id = _seed_patient_with_treatment()
    child_id = _seed_child_payment(patient_id, treatment_id)
    entry = create_entry(
        {
            "draft_type": "edit_payment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "locked_payment_id": child_id,
            "doctor_id": ANY_DOCTOR_ID,
            "doctor_label": ANY_DOCTOR_LABEL,
            "visit_date": "2026-03-24",
            "paid_today": "18",
            "payload_json": {
                "current": {
                    "payment_id": child_id,
                    "treatment_id": treatment_id,
                    "amount_cents": 2000,
                    "visit_date": "2026-03-18",
                    "method": "cash",
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "note": "",
                    "is_initial_payment": 0,
                },
                "proposed": {
                    "amount": "18",
                    "visit_date": "2026-03-24",
                    "method": "transfer",
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "note": "Updated child payment",
                },
            },
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
    approved = get_entry(entry["id"])
    assert approved["status"] == "approved"
    assert approved["target_payment_id"] == child_id

    conn = raw_db()
    try:
        child = conn.execute(
            "SELECT amount_cents, paid_at, method, note, parent_payment_id FROM payments WHERE id=?",
            (child_id,),
        ).fetchone()
        parent = conn.execute(
            "SELECT remaining_cents FROM payments WHERE id=?",
            (treatment_id,),
        ).fetchone()
    finally:
        conn.close()

    assert int(child["amount_cents"] or 0) == 1800
    assert child["paid_at"] == "2026-03-24"
    assert child["method"] == "transfer"
    assert child["note"] == "Updated child payment"
    assert child["parent_payment_id"] == treatment_id
    assert int(parent["remaining_cents"] or 0) == 12200


def test_edit_payment_approval_failure_when_live_payment_changes_leaves_draft_pending(client, admin_user):
    approve_role_id = _create_role("Reception Edit Payment Approver Stale", ["reception_entries:approve"])
    _create_user("edit-payment-approver-stale", "password123", [approve_role_id])
    _login(client, "edit-payment-approver-stale", "password123")
    patient_id, treatment_id = _seed_patient_with_treatment()
    child_id = _seed_child_payment(patient_id, treatment_id)
    entry = create_entry(
        {
            "draft_type": "edit_payment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "locked_payment_id": child_id,
            "doctor_id": ANY_DOCTOR_ID,
            "doctor_label": ANY_DOCTOR_LABEL,
            "visit_date": "2026-03-24",
            "paid_today": "18",
            "payload_json": {
                "current": {
                    "payment_id": child_id,
                    "treatment_id": treatment_id,
                    "amount_cents": 2000,
                    "visit_date": "2026-03-18",
                    "method": "cash",
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "note": "",
                    "is_initial_payment": 0,
                },
                "proposed": {
                    "amount": "18",
                    "visit_date": "2026-03-24",
                    "method": "card",
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "note": "Updated child payment",
                },
            },
        },
        actor_user_id="admin-test",
    )

    conn = raw_db()
    try:
        conn.execute("UPDATE payments SET amount_cents=? WHERE id=?", (2500, child_id))
        conn.commit()
    finally:
        conn.close()

    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    resp = client.post(
        f"/reception/entries/{entry['id']}/approve",
        data={"csrf_token": token, "confirm_approve": "1"},
        follow_redirects=False,
    )

    assert resp.status_code == 400
    assert "The live payment changed after this draft was created." in resp.data.decode("utf-8")
    unchanged = get_entry(entry["id"])
    assert unchanged["status"] == "new"
    assert unchanged["target_payment_id"] is None


def test_manager_can_open_edit_patient_draft_detail(client, admin_user):
    review_role_id = _create_role("Reception Review Patient Detail", ["reception_entries:review"])
    _create_user("review-patient-detail", "password123", [review_role_id])
    _login(client, "review-patient-detail", "password123")
    patient_id = _seed_patient_profile(full_name="Patient Detail Source")
    entry = create_entry(
        {
            "draft_type": "edit_patient",
            "source": "patient_file",
            "locked_patient_id": patient_id,
            "payload_json": {
                "current": {
                    "short_id": "P-ORIG",
                    "full_name": "Patient Detail Source",
                    "primary_phone": "01012121212",
                    "phones": [{"phone": "01012121212", "label": None, "is_primary": 1}],
                    "primary_page_number": "18",
                    "pages": [{"page_number": "18", "notebook_name": "Notebook A", "notebook_color": ""}],
                    "notes": "Original note",
                },
                "proposed": {
                    "full_name": "Patient Detail Updated",
                    "phones": [{"phone": "01034343434", "label": None, "is_primary": 1}],
                    "pages": [{"page_number": "44", "notebook_name": "Notebook B", "notebook_color": ""}],
                    "notes": "Updated note",
                },
                "note": "Reception correction note",
            },
        },
        actor_user_id="admin-test",
    )

    resp = client.get(f"/reception/entries/{entry['id']}")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Current patient profile" in body
    assert "Proposed patient profile" in body
    assert "Patient Detail Source" in body
    assert "Patient Detail Updated" in body


def test_manager_can_approve_edit_patient_draft(client, admin_user):
    approve_role_id = _create_role("Reception Approve Patient Correction", ["reception_entries:approve"])
    _create_user("approve-patient-correction", "password123", [approve_role_id])
    _login(client, "approve-patient-correction", "password123")
    patient_id = _seed_patient_profile(full_name="Correction Source")
    entry = create_entry(
        {
            "draft_type": "edit_patient",
            "source": "patient_file",
            "locked_patient_id": patient_id,
            "payload_json": {
                "current": {
                    "short_id": "P-ORIG",
                    "full_name": "Correction Source",
                    "primary_phone": "01012121212",
                    "phones": [{"phone": "01012121212", "label": None, "is_primary": 1}],
                    "primary_page_number": "18",
                    "pages": [{"page_number": "18", "notebook_name": "Notebook A", "notebook_color": ""}],
                    "notes": "Original note",
                },
                "proposed": {
                    "full_name": "Correction Final",
                    "phones": [
                        {"phone": "01056565656", "label": None, "is_primary": 1},
                        {"phone": "01078787878", "label": None, "is_primary": 0},
                    ],
                    "pages": [
                        {"page_number": "77", "notebook_name": "Notebook C", "notebook_color": ""},
                        {"page_number": "78", "notebook_name": "Notebook D", "notebook_color": ""},
                    ],
                    "notes": "Approved correction note",
                },
                "note": "Reception correction note",
            },
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
    approved = get_entry(entry["id"])
    assert approved["status"] == "approved"
    assert approved["target_patient_id"] == patient_id
    assert list_entry_events(entry["id"])[0]["action"] == "approved"

    conn = raw_db()
    try:
        patient = conn.execute(
            "SELECT full_name, phone, notes, primary_page_number FROM patients WHERE id=?",
            (patient_id,),
        ).fetchone()
        phones = conn.execute(
            "SELECT phone FROM patient_phones WHERE patient_id=? ORDER BY is_primary DESC, rowid ASC",
            (patient_id,),
        ).fetchall()
        pages = conn.execute(
            "SELECT page_number FROM patient_pages WHERE patient_id=? ORDER BY rowid ASC",
            (patient_id,),
        ).fetchall()
    finally:
        conn.close()

    assert patient["full_name"] == "Correction Final"
    assert patient["phone"] == "01056565656"
    assert patient["notes"] == "Approved correction note"
    assert patient["primary_page_number"] == "77"
    assert [row["phone"] for row in phones] == ["01056565656", "01078787878"]
    assert [row["page_number"] for row in pages] == ["77", "78"]


def test_reapproving_edit_patient_draft_is_blocked(client, admin_user):
    approve_role_id = _create_role("Reception Approve Patient Correction 2", ["reception_entries:approve"])
    _create_user("approve-patient-correction-2", "password123", [approve_role_id])
    _login(client, "approve-patient-correction-2", "password123")
    patient_id = _seed_patient_profile(full_name="Reapprove Patient")
    entry = create_entry(
        {
            "draft_type": "edit_patient",
            "source": "patient_file",
            "locked_patient_id": patient_id,
            "payload_json": {
                "current": {
                    "short_id": "P-ORIG",
                    "full_name": "Reapprove Patient",
                    "primary_phone": "01012121212",
                    "phones": [{"phone": "01012121212", "label": None, "is_primary": 1}],
                    "primary_page_number": "18",
                    "pages": [{"page_number": "18", "notebook_name": "Notebook A", "notebook_color": ""}],
                    "notes": "Original note",
                },
                "proposed": {
                    "full_name": "Reapprove Patient Updated",
                    "phones": [{"phone": "01099900000", "label": None, "is_primary": 1}],
                    "pages": [{"page_number": "90", "notebook_name": "Notebook A", "notebook_color": ""}],
                    "notes": "Updated note",
                },
            },
        },
        actor_user_id="admin-test",
    )

    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    first = client.post(
        f"/reception/entries/{entry['id']}/approve",
        data={"csrf_token": token, "confirm_approve": "1"},
        follow_redirects=False,
    )
    assert first.status_code in (302, 303)

    page = client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    second = client.post(
        f"/reception/entries/{entry['id']}/approve",
        data={"csrf_token": token, "confirm_approve": "1"},
        follow_redirects=False,
    )
    assert second.status_code == 400
    assert "Cannot approve a closed draft." in second.data.decode("utf-8")


def test_returned_edit_patient_draft_can_be_opened_and_resubmitted_by_owner(client, admin_user):
    owner_role_id = _create_role("Reception Patient Correction Owner", ["reception_entries:create"])
    review_role_id = _create_role("Reception Patient Correction Reviewer", ["reception_entries:review"])
    owner_user_id = _create_user("patient-correction-owner", "password123", [owner_role_id])
    _create_user("patient-correction-reviewer", "password123", [review_role_id])
    patient_id = _seed_patient_profile(full_name="Returned Correction")
    entry = create_entry(
        {
            "draft_type": "edit_patient",
            "source": "patient_file",
            "locked_patient_id": patient_id,
            "payload_json": {
                "current": {
                    "short_id": "P-ORIG",
                    "full_name": "Returned Correction",
                    "primary_phone": "01012121212",
                    "phones": [{"phone": "01012121212", "label": None, "is_primary": 1}],
                    "primary_page_number": "18",
                    "pages": [{"page_number": "18", "notebook_name": "Notebook A", "notebook_color": ""}],
                    "notes": "Original note",
                },
                "proposed": {
                    "full_name": "Returned Correction Draft",
                    "phones": [{"phone": "01056565656", "label": None, "is_primary": 1}],
                    "pages": [{"page_number": "56", "notebook_name": "Notebook A", "notebook_color": ""}],
                    "notes": "Draft note",
                },
            },
        },
        actor_user_id=owner_user_id,
    )

    reviewer_client = client.application.test_client()
    _login(reviewer_client, "patient-correction-reviewer", "password123")
    page = reviewer_client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    reviewer_client.post(
        f"/reception/entries/{entry['id']}/return",
        data={"csrf_token": token, "return_reason": "Fix phone and page"},
        follow_redirects=False,
    )

    owner_client = client.application.test_client()
    _login(owner_client, "patient-correction-owner", "password123")
    edit_page = owner_client.get(f"/reception/entries/{entry['id']}/edit")
    assert edit_page.status_code == 200
    body = edit_page.data.decode("utf-8")
    assert "Edit returned patient correction" in body
    assert "Fix phone and page" in body

    edit_token = _extract_csrf(edit_page)
    resp = owner_client.post(
        f"/reception/entries/{entry['id']}/edit",
        data={
            "csrf_token": edit_token,
            "patient_id": patient_id,
            "full_name": "Returned Correction Final",
            "phone": "01034343434",
            "primary_page_number": "34",
            "notes": "Updated after return",
            "reception_note": "Owner fixed it",
        },
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    updated = get_entry(entry["id"])
    assert updated["status"] == "edited"
    assert updated["last_action"] == "edited"
    assert updated["return_reason"] is None
    assert updated["patient_name"] == "Returned Correction Final"
    assert updated["phone"] == "01034343434"
    assert updated["page_number"] == "34"


def test_non_owner_cannot_edit_returned_edit_patient_draft_and_held_is_blocked(client, admin_user):
    owner_role_id = _create_role("Reception Patient Correction Owner 2", ["reception_entries:create"])
    review_role_id = _create_role("Reception Patient Correction Reviewer 2", ["reception_entries:review"])
    owner_user_id = _create_user("patient-correction-owner-2", "password123", [owner_role_id])
    _create_user("patient-correction-other", "password123", [owner_role_id])
    _create_user("patient-correction-reviewer-2", "password123", [review_role_id])
    patient_id = _seed_patient_profile(full_name="Held Correction")
    entry = create_entry(
        {
            "draft_type": "edit_patient",
            "source": "patient_file",
            "locked_patient_id": patient_id,
            "payload_json": {
                "current": {
                    "short_id": "P-ORIG",
                    "full_name": "Held Correction",
                    "primary_phone": "01012121212",
                    "phones": [{"phone": "01012121212", "label": None, "is_primary": 1}],
                    "primary_page_number": "18",
                    "pages": [{"page_number": "18", "notebook_name": "Notebook A", "notebook_color": ""}],
                    "notes": "Original note",
                },
                "proposed": {
                    "full_name": "Held Correction Draft",
                    "phones": [{"phone": "01098989898", "label": None, "is_primary": 1}],
                    "pages": [{"page_number": "98", "notebook_name": "Notebook A", "notebook_color": ""}],
                    "notes": "Draft note",
                },
            },
        },
        actor_user_id=owner_user_id,
    )

    reviewer_client = client.application.test_client()
    _login(reviewer_client, "patient-correction-reviewer-2", "password123")
    page = reviewer_client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    reviewer_client.post(
        f"/reception/entries/{entry['id']}/return",
        data={"csrf_token": token, "return_reason": "Owner only"},
        follow_redirects=False,
    )

    other_client = client.application.test_client()
    _login(other_client, "patient-correction-other", "password123")
    forbidden = other_client.get(f"/reception/entries/{entry['id']}/edit")
    assert forbidden.status_code == 403

    page = reviewer_client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    reviewer_client.post(
        f"/reception/entries/{entry['id']}/hold",
        data={"csrf_token": token, "hold_note": "Do not edit yet"},
        follow_redirects=False,
    )

    owner_client = client.application.test_client()
    _login(owner_client, "patient-correction-owner-2", "password123")
    held_resp = owner_client.get(f"/reception/entries/{entry['id']}/edit")
    assert held_resp.status_code == 403


def test_create_only_user_history_shows_only_own_workflow_events(client):
    create_role_id = _create_role("Reception History Create", ["reception_entries:create"])
    reviewer_role_id = _create_role("Reception History Reviewer", ["reception_entries:review"])
    owner_user_id = _create_user("history-owner", "password123", [create_role_id])
    other_user_id = _create_user("history-other", "password123", [create_role_id])
    reviewer_user_id = _create_user("history-reviewer", "password123", [reviewer_role_id])

    own_entry = _create_draft(patient_name="History Own Draft", actor_user_id=owner_user_id)
    other_entry = _create_draft(patient_name="History Other Draft", actor_user_id=other_user_id)

    return_entry(own_entry["id"], actor_user_id=reviewer_user_id, reason="Fix own draft")
    _insert_reception_event(
        entry_id=other_entry["id"],
        action="rejected",
        actor_user_id=reviewer_user_id,
        created_at="2026-03-29T08:00:00+00:00",
        note="Other rejected",
        to_status="rejected",
    )
    _set_entry_status(
        other_entry["id"],
        status="rejected",
        last_action="rejected",
        reason_field="rejection_reason",
        reason="Other rejected",
    )

    owner_client = client.application.test_client()
    _login(owner_client, "history-owner", "password123")
    resp = owner_client.get("/reception?view=history")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Reception history" in body
    assert "History Own Draft" in body
    assert "Fix own draft" in body
    assert "History Other Draft" not in body
    assert "Other rejected" not in body


def test_review_user_history_shows_grouped_events_notes_and_closed_drafts(client):
    create_role_id = _create_role("Reception History Create 2", ["reception_entries:create"])
    reviewer_role_id = _create_role("Reception History Reviewer 2", ["reception_entries:review"])
    first_user_id = _create_user("history-user-a", "password123", [create_role_id])
    second_user_id = _create_user("history-user-b", "password123", [create_role_id])
    reviewer_user_id = _create_user("history-reviewer-2", "password123", [reviewer_role_id])

    returned_entry = _create_draft(patient_name="Returned History Draft", actor_user_id=first_user_id)
    held_entry = _create_draft(patient_name="Held History Draft", actor_user_id=second_user_id)
    approved_entry = _create_draft(patient_name="Approved History Draft", actor_user_id=second_user_id)

    return_entry(returned_entry["id"], actor_user_id=reviewer_user_id, reason="Fix total")
    _set_entry_status(
        held_entry["id"],
        status="held",
        last_action="held",
        reason_field="hold_reason",
        reason="Need callback",
    )
    _insert_reception_event(
        entry_id=held_entry["id"],
        action="held",
        actor_user_id=reviewer_user_id,
        created_at="2026-03-29T10:00:00+00:00",
        note="Need callback",
        to_status="held",
    )
    _set_entry_status(approved_entry["id"], status="approved", last_action="approved")
    _insert_reception_event(
        entry_id=approved_entry["id"],
        action="approved",
        actor_user_id=reviewer_user_id,
        created_at="2026-03-29T12:00:00+00:00",
        to_status="approved",
    )

    conn = raw_db()
    try:
        conn.execute(
            "UPDATE reception_entry_events SET created_at=? WHERE entry_id=? AND action='returned'",
            ("2026-03-30T11:30:00+00:00", returned_entry["id"]),
        )
        conn.execute(
            "UPDATE reception_entry_events SET created_at=? WHERE entry_id=? AND action='submitted'",
            ("2026-03-28T08:00:00+00:00", approved_entry["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    _login(client, "history-reviewer-2", "password123")
    resp = client.get("/reception?view=history")

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Returned History Draft" in body
    assert "Held History Draft" in body
    assert "Approved History Draft" in body
    assert "Fix total" in body
    assert "Need callback" in body
    assert "Approved" in body
    assert "history-reviewer-2" in body
    assert "2026-03-30" in body
    assert "2026-03-29" in body
    assert body.index("2026-03-30") < body.index("2026-03-29")
    assert body.index("Returned History Draft") < body.index("Approved History Draft")
