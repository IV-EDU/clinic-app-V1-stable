from __future__ import annotations

from clinic_app.services.database import db as raw_db
from clinic_app.services.reception_entries import (
    create_entry,
    get_entry,
    list_entries,
    list_entry_events,
    validate_entry_payload,
)


def _seed_patient(patient_id: str, full_name: str = "Locked Patient") -> None:
    conn = raw_db()
    try:
        conn.execute(
            """
            INSERT INTO patients (id, short_id, full_name, phone, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (patient_id, "P-LOCKED", full_name, "01000000000", ""),
        )
        conn.commit()
    finally:
        conn.close()


def test_create_entry_stores_unlocked_new_treatment(app, admin_user):
    entry = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "New Patient",
            "page_number": "12",
            "phone": "01012345678",
            "visit_date": "2026-03-17",
            "visit_type": "exam",
            "treatment_text": "Cleaning",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
            "money_received_today": True,
            "paid_today": "100",
            "total_amount": "250",
            "discount_amount": "",
            "payload_json": {"mode": "test"},
        },
        actor_user_id="admin-test",
    )

    assert entry is not None
    assert entry["draft_type"] == "new_treatment"
    assert entry["source"] == "reception_desk"
    assert entry["status"] == "new"
    assert entry["discount_amount_cents"] == 0
    assert entry["paid_today_cents"] == 10000
    assert entry["total_amount_cents"] == 25000
    assert entry["money_received_today"] == 1
    assert entry["payload_json"] == {"mode": "test"}
    assert entry["warnings_json"] == []

    events = list_entry_events(entry["id"])
    assert len(events) == 1
    assert events[0]["action"] == "submitted"
    assert events[0]["to_status"] == "new"


def test_create_entry_stores_locked_patient_correction(app, admin_user):
    _seed_patient("patient-locked-1")

    entry = create_entry(
        {
            "draft_type": "edit_patient",
            "source": "patient_file",
            "locked_patient_id": "patient-locked-1",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
            "money_received_today": False,
            "payload_json": {"fields": ["phone"]},
        },
        actor_user_id="admin-test",
    )

    assert entry["locked_patient_id"] == "patient-locked-1"
    assert entry["patient_name"] is None
    assert entry["warnings_json"] == [
        "Phone is missing.",
        "Page number is missing.",
        "Total amount is missing.",
        "Remaining amount is unknown.",
    ]


def test_validate_requires_patient_name_when_unlocked():
    errors, warnings, normalized = validate_entry_payload(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
        }
    )

    assert "Patient name is required when patient context is not locked." in errors
    assert normalized["locked_patient_id"] is None
    assert "Phone is missing." in warnings


def test_validate_requires_doctor():
    errors, _, _ = validate_entry_payload(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "No Doctor",
        }
    )

    assert "Doctor is required." in errors


def test_validate_requires_paid_today_when_money_received():
    errors, _, _ = validate_entry_payload(
        {
            "draft_type": "new_payment",
            "source": "reception_desk",
            "patient_name": "Money Case",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
            "money_received_today": True,
        }
    )

    assert "Paid today is required when money was received today." in errors


def test_validate_blocks_paid_over_total():
    errors, _, _ = validate_entry_payload(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Overpaid",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
            "money_received_today": True,
            "paid_today": "300",
            "total_amount": "250",
            "discount_amount": "0",
        }
    )

    assert "Paid today cannot be greater than the amount due." in errors


def test_blank_discount_normalizes_to_zero():
    errors, _, normalized = validate_entry_payload(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Discount Test",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
            "discount_amount": "",
        }
    )

    assert errors == []
    assert normalized["discount_amount_cents"] == 0


def test_list_entries_returns_newest_first(app, admin_user):
    older = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Older Draft",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
        },
        actor_user_id="admin-test",
    )
    newer = create_entry(
        {
            "draft_type": "new_payment",
            "source": "reception_desk",
            "patient_name": "Newer Draft",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
        },
        actor_user_id="admin-test",
    )

    rows = list_entries(submitted_by_user_id="admin-test", limit=10)
    ids = [row["id"] for row in rows]
    assert ids.index(newer["id"]) < ids.index(older["id"])


def test_get_entry_decodes_json_fields(app, admin_user):
    created = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Json Draft",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
            "payload_json": {"source": "unit-test"},
            "match_summary_json": {"matches": []},
        },
        actor_user_id="admin-test",
    )

    fetched = get_entry(created["id"])
    assert fetched is not None
    assert fetched["payload_json"] == {"source": "unit-test"}
    assert fetched["match_summary_json"] == {"matches": []}
    assert isinstance(fetched["warnings_json"], list)
