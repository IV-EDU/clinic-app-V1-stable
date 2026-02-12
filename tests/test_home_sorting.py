import re
import uuid
from html import unescape

from clinic_app.services.database import db
from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, ANY_DOCTOR_LABEL


def _insert_patient(full_name: str, created_at: str) -> str:
    conn = db()
    try:
        pid = f"patient-{uuid.uuid4()}"
        conn.execute(
            "INSERT INTO patients(id, short_id, full_name, phone, created_at) VALUES (?, ?, ?, ?, ?)",
            (pid, f"P{uuid.uuid4().hex[:6]}", full_name, "01000000000", created_at),
        )
        conn.commit()
        return pid
    finally:
        conn.close()


def _insert_payment(patient_id: str, paid_at: str, amount_cents: int = 10000) -> None:
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
                "Sort test",
                ANY_DOCTOR_ID,
                ANY_DOCTOR_LABEL,
                0,
                amount_cents,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _assert_order(html: str, ordered_names: list[str]) -> None:
    positions = []
    for name in ordered_names:
        pos = html.find(name)
        assert pos >= 0, f"Expected patient name not found in page: {name}"
        positions.append(pos)
    assert positions == sorted(positions), f"Unexpected order: {ordered_names}"


def _seed_sort_cases() -> dict[str, str]:
    p_latest_payment = _insert_patient("SortCase Latest Payment", "2024-01-01")
    p_oldest_payment = _insert_patient("SortCase Oldest Payment", "2026-01-01")
    p_no_payment_new = _insert_patient("SortCase No Payment New", "2026-02-01")
    p_no_payment_old = _insert_patient("SortCase No Payment Old", "2023-01-01")

    _insert_payment(p_latest_payment, "2025-02-01")
    _insert_payment(p_oldest_payment, "2024-02-01")

    return {
        "latest_payment": "SortCase Latest Payment",
        "oldest_payment": "SortCase Oldest Payment",
        "no_payment_new": "SortCase No Payment New",
        "no_payment_old": "SortCase No Payment Old",
    }


def test_home_default_sort_is_payment_first_then_new_patients(logged_in_client):
    names = _seed_sort_cases()
    resp = logged_in_client.get("/patients")
    html = resp.data.decode("utf-8")
    assert resp.status_code == 200

    _assert_order(
        html,
        [
            names["latest_payment"],
            names["oldest_payment"],
            names["no_payment_new"],
            names["no_payment_old"],
        ],
    )
    assert "Oldest first" in html


def test_home_old_sort_is_payment_first_then_old_patients(logged_in_client):
    names = _seed_sort_cases()
    resp = logged_in_client.get("/patients?sort=old")
    html = resp.data.decode("utf-8")
    assert resp.status_code == 200

    _assert_order(
        html,
        [
            names["oldest_payment"],
            names["latest_payment"],
            names["no_payment_old"],
            names["no_payment_new"],
        ],
    )
    assert "Newest first" in html


def test_home_invalid_sort_falls_back_to_new(logged_in_client):
    names = _seed_sort_cases()
    resp = logged_in_client.get("/patients?sort=invalid")
    html = resp.data.decode("utf-8")
    assert resp.status_code == 200

    _assert_order(
        html,
        [
            names["latest_payment"],
            names["oldest_payment"],
            names["no_payment_new"],
            names["no_payment_old"],
        ],
    )


def test_home_search_keeps_selected_sort(logged_in_client):
    names = _seed_sort_cases()
    resp = logged_in_client.get("/patients?q=SortCase&sort=old")
    html = resp.data.decode("utf-8")
    assert resp.status_code == 200

    _assert_order(
        html,
        [
            names["oldest_payment"],
            names["latest_payment"],
            names["no_payment_old"],
            names["no_payment_new"],
        ],
    )
    assert 'name="sort" value="old"' in html


def test_home_links_preserve_sort_in_toggle_and_pagination(logged_in_client):
    for i in range(51):
        _insert_patient(f"PageCase {i:02d}", f"2024-01-{(i % 28) + 1:02d}")

    resp = logged_in_client.get("/patients?sort=old")
    html = resp.data.decode("utf-8")
    assert resp.status_code == 200

    assert "Newest first" in html
    assert re.search(r'href="[^"]*sort=new[^"]*"', html)
    assert re.search(r'href="[^"]*page=2[^"]*sort=old[^"]*"', html)


def test_home_sort_preference_is_remembered_across_plain_home(logged_in_client):
    resp_old = logged_in_client.get("/patients?sort=old")
    assert resp_old.status_code == 200
    assert 'name="sort" value="old"' in resp_old.data.decode("utf-8")

    resp_plain = logged_in_client.get("/patients")
    html_plain = resp_plain.data.decode("utf-8")
    assert resp_plain.status_code == 200
    assert 'name="sort" value="old"' in html_plain
    assert "Newest first" in html_plain


def test_patient_open_link_carries_return_to_and_back_restores_page_sort(logged_in_client):
    for i in range(80):
        _insert_patient(f"BackNavCase {i:02d}", f"2024-01-{(i % 28) + 1:02d}")

    home = logged_in_client.get("/patients?page=2&sort=old")
    home_html = unescape(home.data.decode("utf-8"))
    assert home.status_code == 200

    open_link_match = re.search(r'href="(/patients/[^"]*return_to=[^"]+)"', home_html)
    assert open_link_match, "Expected patient open link with return_to"
    patient_href = open_link_match.group(1)
    assert "return_to=/patients" in patient_href
    assert "page%3D2" in patient_href
    assert "sort%3Dold" in patient_href

    detail = logged_in_client.get(patient_href)
    detail_html = unescape(detail.data.decode("utf-8"))
    assert detail.status_code == 200
    back_href = re.search(r'class="[^"]*back-btn[^"]*" href="([^"]+)"', detail_html)
    if not back_href:
        back_href = re.search(r'href="([^"]+)" class="[^"]*back-btn[^"]*"', detail_html)
    assert back_href, "Expected back button in patient detail"
    assert "page=2" in back_href.group(1)
    assert "sort=old" in back_href.group(1)


def test_patient_back_uses_remembered_return_after_detail_without_return_to(logged_in_client):
    pid = _insert_patient("BackRememberCase", "2024-01-01")

    first_detail = logged_in_client.get(f"/patients/{pid}?return_to=%2Fpatients%3Fpage%3D3%26sort%3Dold")
    assert first_detail.status_code == 200

    plain_detail = logged_in_client.get(f"/patients/{pid}")
    plain_html = unescape(plain_detail.data.decode("utf-8"))
    assert plain_detail.status_code == 200
    back_href = re.search(r'class="[^"]*back-btn[^"]*" href="([^"]+)"', plain_html)
    if not back_href:
        back_href = re.search(r'href="([^"]+)" class="[^"]*back-btn[^"]*"', plain_html)
    assert back_href, "Expected back button in patient detail"
    assert "page=3" in back_href.group(1)
    assert "sort=old" in back_href.group(1)


def test_patient_detail_rejects_external_return_to(logged_in_client):
    pid = _insert_patient("BackSafetyCase", "2024-01-01")
    detail = logged_in_client.get(f"/patients/{pid}?return_to=https://evil.com/path")
    html = unescape(detail.data.decode("utf-8"))
    assert detail.status_code == 200
    back_href = re.search(r'class="[^"]*back-btn[^"]*" href="([^"]+)"', html)
    if not back_href:
        back_href = re.search(r'href="([^"]+)" class="[^"]*back-btn[^"]*"', html)
    assert back_href, "Expected back button in patient detail"
    assert "evil.com" not in back_href.group(1)


def test_home_button_stays_plain_home_and_keeps_sort_preference(logged_in_client):
    pid = _insert_patient("BackHomeCase", "2024-01-01")

    logged_in_client.get("/patients?sort=old")
    detail = logged_in_client.get(f"/patients/{pid}")
    detail_html = unescape(detail.data.decode("utf-8"))
    assert detail.status_code == 200
    assert re.search(r'class="[^"]*home-btn[^"]*" href="/"', detail_html) or \
           re.search(r'href="/" class="[^"]*home-btn[^"]*"', detail_html)

    # Note: sort preference is now tied to /patients, not /
    patients_list = logged_in_client.get("/patients")
    patients_html = patients_list.data.decode("utf-8")
    assert patients_list.status_code == 200
    assert 'name="sort" value="old"' in patients_html
