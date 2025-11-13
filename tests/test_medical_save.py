import re

from clinic_app.services.database import db


def _create_patient():
    conn = db()
    try:
        conn.execute(
            "INSERT INTO patients(id, short_id, full_name, created_at) VALUES (?, ?, ?, datetime('now'))",
            ("med-p1", "M001", "Med Patient"),
        )
        conn.commit()
    finally:
        conn.close()


def _csrf_from_page(client):
    resp = client.get("/patients/med-p1/medical/")
    assert resp.status_code == 200
    match = re.search(r'const CSRF_TOKEN = "([^"]+)"', resp.data.decode("utf-8"))
    assert match, "CSRF token not found"
    return match.group(1)


def test_med_save_requires_csrf(logged_in_client):
    _create_patient()
    resp = logged_in_client.post(
        "/patients/med-p1/medical/api/save",
        json={"medical_notes": "test"},
    )
    assert resp.status_code == 400


def test_med_save_succeeds_with_csrf(logged_in_client):
    _create_patient()
    token = _csrf_from_page(logged_in_client)
    payload = {
        "medical_notes": "needs follow-up",
        "allergies_flag": True,
        "allergies": "penicillin",
    }
    resp = logged_in_client.post(
        "/patients/med-p1/medical/api/save",
        json=payload,
        headers={"X-CSRFToken": token},
    )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    conn = db()
    try:
        row = conn.execute(
            "SELECT problems, allergies_flag, allergies FROM medical WHERE patient_id=?",
            ("med-p1",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["problems"] == payload["medical_notes"]
    assert row["allergies_flag"] == 1
    assert row["allergies"] == "penicillin"
