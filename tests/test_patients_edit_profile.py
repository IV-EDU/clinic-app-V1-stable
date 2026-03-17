from __future__ import annotations

import re
from uuid import uuid4

from clinic_app.services.database import db as raw_db


def _extract_csrf(response) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.data.decode("utf-8"))
    assert match, "CSRF token not found"
    return match.group(1)


def _seed_patient_profile(*, full_name: str = "Live Edit Patient") -> str:
    patient_id = f"patient-{uuid4()}"
    conn = raw_db()
    try:
        conn.execute(
            """
            INSERT INTO patients(id, short_id, full_name, phone, notes, primary_page_number, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (patient_id, f"P-{uuid4().hex[:6]}", full_name, "01010000000", "Original note", "10"),
        )
        conn.execute(
            """
            INSERT INTO patient_phones(id, patient_id, phone, phone_normalized, label, is_primary)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (f"phone-{uuid4()}", patient_id, "01010000000", "01010000000", None),
        )
        conn.execute(
            """
            INSERT INTO patient_pages(id, patient_id, page_number, notebook_name)
            VALUES (?, ?, ?, ?)
            """,
            (f"page-{uuid4()}", patient_id, "10", "Notebook A"),
        )
        conn.commit()
    finally:
        conn.close()
    return patient_id


def test_live_patient_edit_route_uses_shared_profile_update_helper(logged_in_client):
    patient_id = _seed_patient_profile()
    edit_page = logged_in_client.get(f"/patients/{patient_id}/edit")
    token = _extract_csrf(edit_page)

    resp = logged_in_client.post(
        f"/patients/{patient_id}/edit",
        data={
            "csrf_token": token,
            "short_id": "P123456",
            "full_name": "Live Edit Patient Updated",
            "phone": "01030000000",
            "extra_phone_number": "01040000000",
            "primary_page_number": "44",
            "primary_notebook_name": "Notebook B",
            "primary_notebook_color": "#123456",
            "extra_page_number": "45",
            "extra_notebook_name": "Notebook C",
            "extra_notebook_color": "#654321",
            "notes": "Updated live note",
        },
        follow_redirects=False,
    )

    assert resp.status_code in (302, 303)
    assert resp.headers["Location"].endswith(f"/patients/{patient_id}")

    conn = raw_db()
    try:
        patient = conn.execute(
            "SELECT short_id, full_name, phone, notes, primary_page_number FROM patients WHERE id=?",
            (patient_id,),
        ).fetchone()
        phones = conn.execute(
            "SELECT phone FROM patient_phones WHERE patient_id=? ORDER BY is_primary DESC, rowid ASC",
            (patient_id,),
        ).fetchall()
        pages = conn.execute(
            "SELECT page_number, notebook_name FROM patient_pages WHERE patient_id=? ORDER BY rowid ASC",
            (patient_id,),
        ).fetchall()
    finally:
        conn.close()

    assert patient["short_id"] == "P123456"
    assert patient["full_name"] == "Live Edit Patient Updated"
    assert patient["phone"] == "01030000000"
    assert patient["notes"] == "Updated live note"
    assert patient["primary_page_number"] == "44"
    assert [row["phone"] for row in phones] == ["01030000000", "01040000000"]
    assert [(row["page_number"], row["notebook_name"]) for row in pages] == [
        ("44", "Notebook B"),
        ("45", "Notebook C"),
    ]


def test_live_patient_edit_route_blocks_duplicate_phone_and_page_values(logged_in_client):
    patient_id = _seed_patient_profile(full_name="Live Edit Invalid")
    edit_page = logged_in_client.get(f"/patients/{patient_id}/edit")
    token = _extract_csrf(edit_page)

    resp = logged_in_client.post(
        f"/patients/{patient_id}/edit",
        data={
            "csrf_token": token,
            "short_id": "P000777",
            "full_name": "Live Edit Invalid Updated",
            "phone": "01050000000",
            "extra_phone_number": "01050000000",
            "primary_page_number": "70",
            "extra_page_number": "70",
            "notes": "Should fail",
        },
        follow_redirects=False,
    )

    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Duplicate phone numbers are not allowed." in body
    assert "Duplicate page numbers are not allowed." in body

    conn = raw_db()
    try:
        patient = conn.execute(
            "SELECT full_name, phone, notes, primary_page_number FROM patients WHERE id=?",
            (patient_id,),
        ).fetchone()
    finally:
        conn.close()

    assert patient["full_name"] == "Live Edit Invalid"
    assert patient["phone"] == "01010000000"
    assert patient["notes"] == "Original note"
    assert patient["primary_page_number"] == "10"
