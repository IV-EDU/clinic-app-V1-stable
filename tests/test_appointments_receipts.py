from datetime import date
from pathlib import Path
import re
import uuid

from clinic_app.services.appointments import doctor_choices
from clinic_app.services.database import db


def _make_patient(full_name: str = "Test Patient", short_id: str = "P0001"):
    conn = db()
    pid = f"patient-{uuid.uuid4()}"
    conn.execute(
        "INSERT INTO patients(id, short_id, full_name, phone, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
        (pid, short_id, full_name, "0101010101"),
    )
    conn.commit()
    conn.close()
    return pid


def _schedule_appointment(patient_id: str, doctor_id: str, doctor_label: str, starts_at: str, ends_at: str) -> str:
    conn = db()
    try:
        appt_id = f"appt-{uuid.uuid4()}"
        patient = conn.execute("SELECT full_name, phone FROM patients WHERE id=?", (patient_id,)).fetchone()
        conn.execute(
            """
            INSERT INTO appointments(
                id, patient_id, patient_name, patient_phone, doctor_id, doctor_label,
                title, notes, starts_at, ends_at, status, room, reminder_minutes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', NULL, 0, datetime('now'), datetime('now'))
            """,
            (
                appt_id,
                patient_id,
                patient["full_name"],
                patient["phone"],
                doctor_id,
                doctor_label,
                "Scheduled visit",
                None,
                starts_at,
                ends_at,
            ),
        )
        conn.commit()
        return appt_id
    finally:
        conn.close()


def test_appointment_overlap_conflict(logged_in_client, get_csrf_token, app):
    _make_patient()
    day = date.today().isoformat()
    with app.app_context():
        doctor_slug = doctor_choices()[0][0]
    form_page = logged_in_client.get("/appointments/new")
    token = get_csrf_token(form_page)
    payload = {
        "csrf_token": token,
        "day": day,
        "start_time": "09:00",
        "duration_minutes": "30",
        "doctor_id": doctor_slug,
        "title": "Cleaning",
        "patient_lookup": "P0001",
    }
    resp_ok = logged_in_client.post("/appointments/new", data=payload, follow_redirects=False)
    assert resp_ok.status_code in (302, 303)

    resp_conflict = logged_in_client.post("/appointments/new", data=payload, follow_redirects=False)
    assert resp_conflict.status_code == 409


def test_receipt_serial_pdf_and_reprint(logged_in_client, get_csrf_token):
    _make_patient()
    page = logged_in_client.get("/receipts/new")
    token = get_csrf_token(page)
    payload = {
        "csrf_token": token,
        "patient_lookup": "P0001",
        "amount": "150",
        "locale": "en",
        "description": "Initial payment",
    }
    resp = logged_in_client.post("/receipts/new", data=payload, follow_redirects=False)
    assert resp.status_code in (302, 303)

    page = logged_in_client.get("/receipts/new")
    token = get_csrf_token(page)
    payload["csrf_token"] = token
    payload["amount"] = "200"
    resp2 = logged_in_client.post("/receipts/new", data=payload, follow_redirects=False)
    assert resp2.status_code in (302, 303)

    conn = db()
    rows = conn.execute(
        "SELECT id, number, pdf_path, locale, reprint_count FROM receipts ORDER BY issued_at DESC"
    ).fetchall()
    conn.close()
    assert len(rows) >= 2
    number_latest = rows[0]["number"]
    number_prev = rows[1]["number"]
    assert number_latest != number_prev
    assert re.match(r"R-\d{4}-\d{6}", number_latest)
    pdf_path = Path(rows[0]["pdf_path"])
    assert pdf_path.exists()
    assert pdf_path.read_bytes().startswith(b"%PDF")

    list_page = logged_in_client.get("/receipts")
    token = get_csrf_token(list_page)
    resp_reprint = logged_in_client.post(
        f"/receipts/{rows[0]['id']}/reprint",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert resp_reprint.status_code in (302, 303)
    conn = db()
    new_count = conn.execute("SELECT reprint_count FROM receipts WHERE id=?", (rows[0]["id"],)).fetchone()
    conn.close()
    assert new_count["reprint_count"] >= 1


def test_move_appointment_endpoint(logged_in_client, get_csrf_token, app):
    patient_id = _make_patient(short_id="P0911")
    with app.app_context():
        doctors = dict(doctor_choices())
    doctor_ids = list(doctors.keys())
    doctor_a = doctor_ids[0]
    doctor_b = doctor_ids[-1] if len(doctor_ids) > 1 else doctor_ids[0]
    base_day = "2025-01-02"
    appt_id = _schedule_appointment(
        patient_id,
        doctor_a,
        doctors[doctor_a],
        f"{base_day}T09:00:00",
        f"{base_day}T09:30:00",
    )
    _schedule_appointment(
        patient_id,
        doctor_a,
        doctors[doctor_a],
        f"{base_day}T10:00:00",
        f"{base_day}T10:30:00",
    )

    page = logged_in_client.get("/patients/new")
    token = get_csrf_token(page)

    conflict = logged_in_client.post(
        "/appointments/move",
        json={
            "appointment_id": appt_id,
            "target_doctor": doctor_a,
            "target_time": "10:00",
        },
        headers={"X-CSRFToken": token},
    )
    assert conflict.status_code == 409

    success = logged_in_client.post(
        "/appointments/move",
        json={
            "appointment_id": appt_id,
            "target_doctor": doctor_b,
            "target_time": "11:00",
        },
        headers={"X-CSRFToken": token},
    )
    assert success.status_code == 200
    payload = success.get_json()
    assert payload["success"] is True
    assert payload["appointment"]["doctor_id"] == doctor_b
    assert payload["appointment"]["starts_at"].startswith(f"{base_day}T11:00")

    conn = db()
    row = conn.execute("SELECT doctor_id, starts_at FROM appointments WHERE id=?", (appt_id,)).fetchone()
    conn.close()
    assert row["doctor_id"] == doctor_b
    assert row["starts_at"].startswith(f"{base_day}T11:00")
