from __future__ import annotations

import re
from uuid import uuid4

from werkzeug.security import generate_password_hash

from clinic_app.services.database import db as raw_db
from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, ANY_DOCTOR_LABEL
from clinic_app.services.reception_entries import create_entry, get_entry, list_entries


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
            (patient_id, f"P-{uuid4().hex[:6]}", "Treatment Draft Patient", "01066666666", "", "61"),
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
                "Original treatment note",
                "Locked Crown",
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


def test_treatment_card_shows_send_treatment_correction_button_for_create_capable_user(logged_in_client):
    patient_id, _, _ = _seed_patient_with_treatment()

    resp = logged_in_client.get(f"/patients/{patient_id}")
    assert resp.status_code == 200
    assert "Send Treatment Correction" in resp.data.decode("utf-8")


def test_treatment_card_hides_send_treatment_correction_button_without_reception_create_permission(client):
    role_id = _create_role("Patient Viewer No Treatment Correction", ["patients:view", "payments:view"])
    _create_user("patient-viewer-treatment", "password123", [role_id])
    _login(client, "patient-viewer-treatment", "password123")
    patient_id, _, _ = _seed_patient_with_treatment()

    resp = client.get(f"/patients/{patient_id}")
    assert resp.status_code == 200
    assert "Send Treatment Correction" not in resp.data.decode("utf-8")


def test_new_treatment_correction_get_requires_create_and_patient_visibility(client):
    patient_id, treatment_id, _ = _seed_patient_with_treatment()
    resp = client.get(f"/reception/entries/new-treatment-correction?patient_id={patient_id}&treatment_id={treatment_id}")
    assert resp.status_code in (302, 401)

    role_id = _create_role("Reception Create Without Patient View Treatment", ["reception_entries:create"])
    _create_user("reception-no-patient-view-treatment", "password123", [role_id])
    _login(client, "reception-no-patient-view-treatment", "password123")
    blocked = client.get(f"/reception/entries/new-treatment-correction?patient_id={patient_id}&treatment_id={treatment_id}")
    assert blocked.status_code == 403


def test_new_treatment_correction_get_rejects_invalid_or_child_context(logged_in_client):
    patient_id, _, _ = _seed_patient_with_treatment()
    missing = logged_in_client.get(
        f"/reception/entries/new-treatment-correction?patient_id={patient_id}&treatment_id=missing-treatment"
    )
    assert missing.status_code == 404

    patient_id, _, child_id = _seed_patient_with_treatment(with_child=True)
    child = logged_in_client.get(
        f"/reception/entries/new-treatment-correction?patient_id={patient_id}&treatment_id={child_id}"
    )
    assert child.status_code == 400


def test_valid_new_treatment_correction_post_creates_locked_draft(logged_in_client):
    patient_id, treatment_id, _ = _seed_patient_with_treatment()
    page = logged_in_client.get(
        f"/reception/entries/new-treatment-correction?patient_id={patient_id}&treatment_id={treatment_id}"
    )
    token = _extract_csrf(page)

    resp = logged_in_client.post(
        "/reception/entries/new-treatment-correction",
        data={
            "csrf_token": token,
            "patient_id": patient_id,
            "treatment_id": treatment_id,
            "treatment_text": "Locked Crown Updated",
            "visit_date": "2026-03-20",
            "visit_type": "followup",
            "doctor_id": ANY_DOCTOR_ID,
            "total_amount": "260",
            "discount_amount": "20",
            "note": "Updated through correction route",
        },
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith("/reception?view=desk")

    entries = list_entries(submitted_by_user_id="admin-test", limit=20)
    created = next(entry for entry in entries if entry["draft_type"] == "edit_treatment")
    assert created["source"] == "treatment_card"
    assert created["locked_patient_id"] == patient_id
    assert created["locked_treatment_id"] == treatment_id
    assert created["target_patient_id"] is None
    assert created["target_treatment_id"] is None
    assert created["patient_name"] == "Treatment Draft Patient"
    assert created["page_number"] == "61"
    assert created["payload_json"]["current"]["treatment_text"] == "Locked Crown"
    assert created["payload_json"]["proposed"]["treatment_text"] == "Locked Crown Updated"


def test_invalid_new_treatment_correction_post_rerenders_with_sticky_values(logged_in_client):
    patient_id, treatment_id, _ = _seed_patient_with_treatment()
    page = logged_in_client.get(
        f"/reception/entries/new-treatment-correction?patient_id={patient_id}&treatment_id={treatment_id}"
    )
    token = _extract_csrf(page)

    resp = logged_in_client.post(
        "/reception/entries/new-treatment-correction",
        data={
            "csrf_token": token,
            "patient_id": patient_id,
            "treatment_id": treatment_id,
            "treatment_text": "Sticky Treatment",
            "visit_date": "2026-03-21",
            "visit_type": "none",
            "doctor_id": "",
            "total_amount": "40",
            "discount_amount": "0",
            "note": "sticky note",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 400
    body = resp.data.decode("utf-8")
    assert "Doctor is required." in body
    assert "Total amount minus discount cannot be less than the amount already paid." in body
    assert 'value="Sticky Treatment"' in body
    assert "sticky note" in body


def test_owner_can_resubmit_returned_treatment_correction(client):
    owner_role_id = _create_role("Reception Treatment Correction Owner", ["reception_entries:create", "patients:view"])
    review_role_id = _create_role("Reception Treatment Correction Reviewer", ["reception_entries:review"])
    owner_user_id = _create_user("treatment-correction-owner", "password123", [owner_role_id])
    _create_user("treatment-correction-reviewer", "password123", [review_role_id])
    patient_id, treatment_id, _ = _seed_patient_with_treatment()
    entry = create_entry(
        {
            "draft_type": "edit_treatment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "payload_json": {
                "proposed": {
                    "treatment_text": "Draft Crown",
                    "visit_date": "2026-03-20",
                    "visit_type": "exam",
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "total_amount": "250",
                    "discount_amount": "10",
                    "note": "Draft note",
                }
            },
        },
        actor_user_id=owner_user_id,
    )

    reviewer_client = client.application.test_client()
    _login(reviewer_client, "treatment-correction-reviewer", "password123")
    page = reviewer_client.get(f"/reception/entries/{entry['id']}")
    token = _extract_csrf(page)
    reviewer_client.post(
        f"/reception/entries/{entry['id']}/return",
        data={"csrf_token": token, "return_reason": "Fix totals"},
        follow_redirects=False,
    )

    owner_client = client.application.test_client()
    _login(owner_client, "treatment-correction-owner", "password123")
    edit_page = owner_client.get(f"/reception/entries/{entry['id']}/edit")
    assert edit_page.status_code == 200
    edit_token = _extract_csrf(edit_page)
    resp = owner_client.post(
        f"/reception/entries/{entry['id']}/edit",
        data={
            "csrf_token": edit_token,
            "treatment_text": "Final Crown",
            "visit_date": "2026-03-22",
            "visit_type": "followup",
            "doctor_id": ANY_DOCTOR_ID,
            "total_amount": "260",
            "discount_amount": "10",
            "note": "Final note",
        },
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    updated = get_entry(entry["id"])
    assert updated["status"] == "edited"
    assert updated["last_action"] == "edited"
    assert updated["return_reason"] is None
    assert updated["treatment_text"] == "Final Crown"


def test_manager_detail_shows_treatment_correction_comparison(client, admin_user):
    review_role_id = _create_role("Reception Review Treatment Detail", ["reception_entries:review"])
    _create_user("review-treatment-detail", "password123", [review_role_id])
    _login(client, "review-treatment-detail", "password123")
    patient_id, treatment_id, _ = _seed_patient_with_treatment()
    entry = create_entry(
        {
            "draft_type": "edit_treatment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "payload_json": {
                "proposed": {
                    "treatment_text": "Updated Crown",
                    "visit_date": "2026-03-21",
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

    resp = client.get(f"/reception/entries/{entry['id']}")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Treatment correction" in body
    assert "Locked Crown" in body
    assert "Updated Crown" in body
    assert "Current remaining" in body


def test_manager_can_approve_locked_treatment_correction_draft(client, admin_user):
    approve_role_id = _create_role("Reception Treatment Approver", ["reception_entries:approve"])
    _create_user("treatment-approver", "password123", [approve_role_id])
    _login(client, "treatment-approver", "password123")
    patient_id, treatment_id, _ = _seed_patient_with_treatment()
    entry = create_entry(
        {
            "draft_type": "edit_treatment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "payload_json": {
                "proposed": {
                    "treatment_text": "Updated Crown",
                    "visit_date": "2026-03-21",
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
    assert approved["target_payment_id"] is None

    conn = raw_db()
    try:
        treatment = conn.execute(
            """
            SELECT treatment, paid_at, total_amount_cents, discount_cents, remaining_cents, followup_flag, note
            FROM payments WHERE id=?
            """,
            (treatment_id,),
        ).fetchone()
    finally:
        conn.close()

    assert treatment["treatment"] == "Updated Crown"
    assert treatment["paid_at"] == "2026-03-21"
    assert int(treatment["total_amount_cents"] or 0) == 26000
    assert int(treatment["discount_cents"] or 0) == 1000
    assert int(treatment["remaining_cents"] or 0) == 20000
    assert int(treatment["followup_flag"] or 0) == 1
    assert treatment["note"] == "Treatment correction note"


def test_approve_treatment_correction_blocks_invalid_money_after_live_change(client, admin_user):
    approve_role_id = _create_role("Reception Treatment Approver Invalid", ["reception_entries:approve"])
    _create_user("treatment-approver-invalid", "password123", [approve_role_id])
    _login(client, "treatment-approver-invalid", "password123")
    patient_id, treatment_id, _ = _seed_patient_with_treatment()
    entry = create_entry(
        {
            "draft_type": "edit_treatment",
            "source": "treatment_card",
            "locked_patient_id": patient_id,
            "locked_treatment_id": treatment_id,
            "payload_json": {
                "proposed": {
                    "treatment_text": "Updated Crown",
                    "visit_date": "2026-03-21",
                    "visit_type": "none",
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "total_amount": "120",
                    "discount_amount": "0",
                    "note": "Too low after live change",
                }
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
                f"payment-{uuid4()}",
                patient_id,
                treatment_id,
                "2026-03-19",
                9000,
                "cash",
                "",
                ANY_DOCTOR_ID,
                ANY_DOCTOR_LABEL,
            ),
        )
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
    assert "Total amount minus discount cannot be less than the amount already paid." in resp.data.decode("utf-8")
    unchanged = get_entry(entry["id"])
    assert unchanged["status"] == "new"
