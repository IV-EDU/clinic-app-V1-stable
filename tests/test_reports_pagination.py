import re
import uuid
from datetime import date, timedelta

from clinic_app.services.database import db
from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, ANY_DOCTOR_LABEL


def _insert_patient(name_prefix: str = "Report Page") -> str:
    conn = db()
    try:
        pid = f"patient-{uuid.uuid4()}"
        conn.execute(
            "INSERT INTO patients(id, short_id, full_name, phone, created_at) VALUES (?, ?, ?, ?, ?)",
            (pid, f"P{uuid.uuid4().hex[:6]}", f"{name_prefix} {pid[-6:]}", "01012345678", "2024-01-01"),
        )
        conn.commit()
        return pid
    finally:
        conn.close()


def _insert_payment(
    patient_id: str,
    paid_at: str,
    amount_cents: int = 10000,
    total_amount_cents: int = 10000,
    doctor_id: str = ANY_DOCTOR_ID,
    doctor_label: str = ANY_DOCTOR_LABEL,
) -> None:
    conn = db()
    try:
        pay_id = f"pay-{uuid.uuid4()}"
        conn.execute(
            """
            INSERT INTO payments(
                id, patient_id, paid_at, amount_cents, method, note, treatment,
                doctor_id, doctor_label,
                remaining_cents, total_amount_cents, examination_flag, followup_flag, discount_cents
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0)
            """,
            (
                pay_id,
                patient_id,
                paid_at,
                amount_cents,
                "cash",
                "",
                "Pagination test",
                doctor_id,
                doctor_label,
                max(total_amount_cents - amount_cents, 0),
                total_amount_cents,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_collections_daily_paginates_and_preserves_filters(logged_in_client):
    pid = _insert_patient("Collections Daily")
    start_day = date(2024, 1, 1)
    for i in range(80):
        _insert_payment(pid, (start_day + timedelta(days=i)).isoformat(), amount_cents=5000)

    resp = logged_in_client.get(f"/collections?tab=daily&doctor={ANY_DOCTOR_ID}&page=2")
    html = resp.data.decode("utf-8")
    assert resp.status_code == 200
    # 80 grouped daily rows => page 2 contains 30 rows
    assert html.count('data-kind="day"') == 30
    assert "Page 2 / 2" in html
    assert f"doctor={ANY_DOCTOR_ID}" in html
    assert "tab=daily" in html


def test_collections_monthly_paginates(logged_in_client):
    pid = _insert_patient("Collections Monthly")
    for i in range(70):
        year = 2017 + (i // 12)
        month = (i % 12) + 1
        _insert_payment(pid, f"{year:04d}-{month:02d}-15", amount_cents=7000)

    resp = logged_in_client.get("/collections?tab=monthly&page=2", follow_redirects=True)
    html = resp.data.decode("utf-8")
    assert resp.status_code == 200
    # 70 grouped monthly rows => page 2 contains 20 rows
    assert html.count('data-kind="month"') == 20
    assert "Page 2 / 2" in html
    assert "tab=monthly" in html


def test_collections_doctors_paginates_and_keeps_doctor(logged_in_client):
    pid = _insert_patient("Collections Doctor")
    start_day = date(2024, 5, 1)
    for i in range(75):
        _insert_payment(pid, (start_day + timedelta(days=i)).isoformat(), amount_cents=4000)

    resp = logged_in_client.get(f"/collections/doctors?tab=daily&doctor={ANY_DOCTOR_ID}&page=2")
    html = resp.data.decode("utf-8")
    assert resp.status_code == 200
    assert html.count('data-kind="day"') == 25
    assert "Page 2 / 2" in html
    assert f"doctor={ANY_DOCTOR_ID}" in html


def test_receivables_paginates_but_summary_count_stays_full(logged_in_client):
    owing_count = 80
    for _ in range(owing_count):
        pid = _insert_patient("Receivables")
        # leave a positive remainder
        _insert_payment(
            pid,
            "2024-08-01",
            amount_cents=5000,
            total_amount_cents=20000,
        )

    resp = logged_in_client.get("/receivables?page=2")
    html = resp.data.decode("utf-8")
    assert resp.status_code == 200
    # page 2 contains 30 visible patient rows (exclude JS template strings from nav search)
    patient_links = re.findall(r'href="/patients/patient-[^"]+"', html)
    assert len(patient_links) == 30
    assert "Page 2 / 2" in html
    # Summary count should remain full filtered rows (not page size).
    box_values = re.findall(r'<div class="box-value">([^<]+)</div>', html)
    assert len(box_values) >= 2
    assert box_values[1].strip() == str(owing_count)
    assert 'target="_blank"' in html


def test_invalid_page_falls_back_to_first_page(logged_in_client):
    pid = _insert_patient("Invalid Page")
    start_day = date(2024, 9, 1)
    for i in range(60):
        _insert_payment(pid, (start_day + timedelta(days=i)).isoformat(), amount_cents=3000)

    resp = logged_in_client.get("/collections?tab=daily&page=abc")
    html = resp.data.decode("utf-8")
    assert resp.status_code == 200
    assert "Page 1 / 2" in html
