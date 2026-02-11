import re

from clinic_app.services.database import db


def _create_patient():
    conn = db()
    try:
        conn.execute(
            "INSERT INTO patients(id, short_id, full_name, created_at) VALUES (?, ?, ?, datetime('now'))",
            ("diag-p1", "P001", "Diag Patient"),
        )
        conn.commit()
    finally:
        conn.close()


def _get_csrf_from_diag(client):
    page = client.get("/patients/diag-p1/diagnosis/")
    assert page.status_code == 200
    match = re.search(r'const CSRF_TOKEN = "([^"]+)"', page.data.decode("utf-8"))
    assert match, "CSRF token not found in diagnosis page"
    return match.group(1)


def test_diag_set_requires_csrf(logged_in_client):
    _create_patient()
    resp = logged_in_client.post(
        "/patients/diag-p1/diagnosis/api/set",
        json={"chart_type": "adult", "tooth_code": "UR1", "status": "Healthy"},
    )
    assert resp.status_code == 400


def test_diag_set_accepts_json_with_csrf(logged_in_client):
    _create_patient()
    token = _get_csrf_from_diag(logged_in_client)
    resp = logged_in_client.post(
        "/patients/diag-p1/diagnosis/api/set",
        json={
            "chart_type": "adult",
            "tooth_code": "UR1",
            "status": "Healthy",
            "note": "ok",
            "csrf_token": token,
        },
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["state"]["status"] == "Healthy"
