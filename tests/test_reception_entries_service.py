from __future__ import annotations

from clinic_app.services.database import db as raw_db
from clinic_app.services.reception_entries import (
    approve_new_payment_entry,
    create_entry,
    get_entry,
    get_locked_treatment_context,
    list_entries,
    list_entry_events,
    list_queue_entries,
    resubmit_returned_entry,
    return_entry,
    validate_entry_payload,
)


def _seed_patient(patient_id: str, full_name: str = "Locked Patient") -> None:
    conn = raw_db()
    try:
        conn.execute(
            """
            INSERT INTO patients (id, short_id, full_name, phone, notes, primary_page_number)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (patient_id, "P-LOCKED", full_name, "01000000000", "", "12"),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_user(user_id: str, username: str) -> None:
    conn = raw_db()
    try:
        conn.execute(
            """
            INSERT INTO users (id, username, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 'assistant', 1, datetime('now'), datetime('now'))
            """,
            (user_id, username, "test-hash"),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_parent_treatment(
    patient_id: str,
    treatment_id: str,
    *,
    amount_cents: int = 5000,
    total_amount_cents: int = 20000,
    discount_cents: int = 1000,
) -> None:
    conn = raw_db()
    try:
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
                amount_cents,
                "cash",
                "",
                "Locked Crown",
                "_any_",
                "Any Doctor",
                max(total_amount_cents - discount_cents - amount_cents, 0),
                total_amount_cents,
                discount_cents,
            ),
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
            "draft_type": "new_treatment",
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
            "draft_type": "new_treatment",
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


def test_resubmit_returned_entry_updates_draft_and_event(app, admin_user):
    _seed_user("manager-test", "manager-test")
    created = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Returned Source",
            "phone": "01011111111",
            "page_number": "14",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
            "visit_date": "2026-03-17",
            "treatment_text": "Cleaning",
            "total_amount": "200",
            "payload_json": {"note": "first"},
        },
        actor_user_id="admin-test",
    )
    submitted_at = created["submitted_at"]
    return_entry(created["id"], actor_user_id="manager-test", reason="Fix the amount")

    updated = resubmit_returned_entry(
        created["id"],
        {
            "patient_name": "Returned Updated",
            "phone": "01099999999",
            "page_number": "33",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
            "visit_date": "2026-03-18",
            "visit_type": "followup",
            "treatment_text": "Updated Cleaning",
            "money_received_today": True,
            "paid_today": "50",
            "total_amount": "220",
            "discount_amount": "20",
            "payload_json": {"note": "updated"},
        },
        actor_user_id="admin-test",
    )

    assert updated["patient_name"] == "Returned Updated"
    assert updated["status"] == "edited"
    assert updated["last_action"] == "edited"
    assert updated["return_reason"] is None
    assert updated["submitted_at"] == submitted_at
    assert updated["updated_at"] != created["updated_at"]
    assert updated["paid_today_cents"] == 5000
    assert updated["total_amount_cents"] == 22000
    assert updated["discount_amount_cents"] == 2000
    assert updated["payload_json"] == {"note": "updated"}

    events = list_entry_events(created["id"])
    assert events[0]["action"] == "edited"
    assert events[0]["meta_json"] == {"resubmitted": True}


def test_resubmit_returned_entry_rejects_non_returned_draft(app, admin_user):
    created = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Not Returned",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
        },
        actor_user_id="admin-test",
    )

    try:
        resubmit_returned_entry(
            created["id"],
            {
                "patient_name": "Still Not Returned",
                "doctor_id": "_any_",
                "doctor_label": "Any Doctor",
            },
            actor_user_id="admin-test",
        )
        assert False, "Expected ValueError for non-returned draft"
    except ValueError as exc:
        assert "Only returned drafts can be edited and resubmitted." in str(exc)


def test_resubmit_returned_entry_rejects_unsupported_draft_type(app, admin_user):
    _seed_user("manager-test", "manager-test")
    _seed_patient("payment-patient-unsupported", "Payment Draft")
    _seed_parent_treatment("payment-patient-unsupported", "treatment-unsupported")
    created = create_entry(
        {
            "draft_type": "new_payment",
            "source": "treatment_card",
            "locked_patient_id": "payment-patient-unsupported",
            "locked_treatment_id": "treatment-unsupported",
            "patient_name": "Payment Draft",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
            "paid_today": "25",
            "payload_json": {"treatment_remaining_cents_at_submit": 14000},
        },
        actor_user_id="admin-test",
    )
    return_entry(created["id"], actor_user_id="manager-test", reason="Unsupported")

    try:
        resubmit_returned_entry(
            created["id"],
            {
                "patient_name": "Payment Draft Updated",
                "doctor_id": "_any_",
                "doctor_label": "Any Doctor",
            },
            actor_user_id="admin-test",
        )
        assert False, "Expected ValueError for unsupported draft type"
    except ValueError as exc:
        assert "Only returned desk treatment drafts can be edited in this slice." in str(exc)


def test_resubmitted_draft_sorts_by_updated_at_for_desk_and_queue(app, admin_user):
    _seed_user("manager-test", "manager-test")
    older = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Older Waiting Draft",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
        },
        actor_user_id="admin-test",
    )
    returned = create_entry(
        {
            "draft_type": "new_treatment",
            "source": "reception_desk",
            "patient_name": "Returned Waiting Draft",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
            "total_amount": "100",
        },
        actor_user_id="admin-test",
    )
    return_entry(returned["id"], actor_user_id="manager-test", reason="Fix and resend")
    resubmit_returned_entry(
        returned["id"],
        {
            "patient_name": "Returned Waiting Draft",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
            "total_amount": "120",
        },
        actor_user_id="admin-test",
    )

    desk_rows = list_entries(submitted_by_user_id="admin-test", limit=10)
    queue_rows = list_queue_entries(limit=10)
    assert desk_rows[0]["id"] == returned["id"]
    assert queue_rows[0]["id"] == returned["id"]
    assert desk_rows[0]["id"] != older["id"]


def test_validate_new_payment_requires_locked_context_and_positive_amount():
    errors, warnings, normalized = validate_entry_payload(
        {
            "draft_type": "new_payment",
            "source": "treatment_card",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
            "paid_today": "0",
        }
    )

    assert "Patient context is required for payment drafts." in errors
    assert "Treatment context is required for payment drafts." in errors
    assert "Payment amount must be greater than zero." in errors
    assert warnings == []
    assert normalized["patient_intent"] == "existing"
    assert normalized["money_received_today"] == 1


def test_get_locked_treatment_context_returns_live_snapshot(app, admin_user):
    _seed_patient("payment-patient-1", "Snapshot Patient")
    _seed_parent_treatment("payment-patient-1", "treatment-1", amount_cents=5000, total_amount_cents=20000, discount_cents=1000)

    context = get_locked_treatment_context("payment-patient-1", "treatment-1")

    assert context is not None
    assert context["patient_name"] == "Snapshot Patient"
    assert context["page_number"] == "12"
    assert context["treatment_text"] == "Locked Crown"
    assert context["total_paid_cents"] == 5000
    assert context["remaining_cents"] == 14000


def test_create_locked_new_payment_stores_snapshot_and_no_generic_warnings(app, admin_user):
    _seed_patient("payment-patient-2", "Payment Draft Patient")
    _seed_parent_treatment("payment-patient-2", "treatment-2", amount_cents=6000, total_amount_cents=25000, discount_cents=2000)

    context = get_locked_treatment_context("payment-patient-2", "treatment-2")
    assert context is not None

    entry = create_entry(
        {
            "draft_type": "new_payment",
            "source": "treatment_card",
            "locked_patient_id": context["patient_id"],
            "locked_treatment_id": context["treatment_id"],
            "patient_name": context["patient_name"],
            "phone": context["phone"],
            "page_number": context["page_number"],
            "treatment_text": context["treatment_text"],
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
            "visit_date": "2026-03-18",
            "paid_today": "50",
            "total_amount": "250",
            "discount_amount": "20",
            "payload_json": {
                "submitted_amount_cents": 5000,
                "treatment_remaining_cents_at_submit": context["remaining_cents"],
                "treatment_total_paid_cents_at_submit": context["total_paid_cents"],
                "method": "cash",
                "note": "draft payment",
            },
        },
        actor_user_id="admin-test",
    )

    assert entry["draft_type"] == "new_payment"
    assert entry["source"] == "treatment_card"
    assert entry["locked_patient_id"] == "payment-patient-2"
    assert entry["locked_treatment_id"] == "treatment-2"
    assert entry["warnings_json"] == []
    assert entry["paid_today_cents"] == 5000
    assert entry["payload_json"]["treatment_remaining_cents_at_submit"] == context["remaining_cents"]


def test_approve_new_payment_entry_posts_child_payment_and_updates_remaining(app, admin_user):
    _seed_user("approver-test", "approver-test")
    _seed_patient("payment-patient-3", "Approve Payment Patient")
    _seed_parent_treatment("payment-patient-3", "treatment-3", amount_cents=5000, total_amount_cents=20000, discount_cents=1000)
    context = get_locked_treatment_context("payment-patient-3", "treatment-3")
    assert context is not None

    entry = create_entry(
        {
            "draft_type": "new_payment",
            "source": "treatment_card",
            "locked_patient_id": context["patient_id"],
            "locked_treatment_id": context["treatment_id"],
            "patient_name": context["patient_name"],
            "phone": context["phone"],
            "page_number": context["page_number"],
            "treatment_text": context["treatment_text"],
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
            "visit_date": "2026-03-18",
            "paid_today": "40",
            "total_amount": "200",
            "discount_amount": "10",
            "payload_json": {
                "submitted_amount_cents": 4000,
                "treatment_remaining_cents_at_submit": context["remaining_cents"],
                "treatment_total_paid_cents_at_submit": context["total_paid_cents"],
                "method": "card",
                "note": "service approve payment",
            },
        },
        actor_user_id="admin-test",
    )

    approved = approve_new_payment_entry(entry["id"], actor_user_id="approver-test")

    assert approved["status"] == "approved"
    assert approved["target_patient_id"] == "payment-patient-3"
    assert approved["target_treatment_id"] == "treatment-3"
    assert approved["target_payment_id"]
    assert list_entry_events(entry["id"])[0]["action"] == "approved"

    conn = raw_db()
    try:
        child = conn.execute(
            "SELECT parent_payment_id, amount_cents, method, note FROM payments WHERE id=?",
            (approved["target_payment_id"],),
        ).fetchone()
        parent = conn.execute(
            "SELECT remaining_cents FROM payments WHERE id=?",
            ("treatment-3",),
        ).fetchone()
    finally:
        conn.close()

    assert child["parent_payment_id"] == "treatment-3"
    assert int(child["amount_cents"] or 0) == 4000
    assert child["method"] == "card"
    assert child["note"] == "service approve payment"
    assert int(parent["remaining_cents"] or 0) == 10000


def test_approve_new_payment_entry_rejects_unsupported_source(app, admin_user):
    _seed_user("approver-test-2", "approver-test-2")
    _seed_patient("payment-patient-4", "Bad Source Patient")
    _seed_parent_treatment("payment-patient-4", "treatment-4")

    entry = create_entry(
        {
            "draft_type": "new_payment",
            "source": "reception_desk",
            "locked_patient_id": "payment-patient-4",
            "locked_treatment_id": "treatment-4",
            "patient_name": "Bad Source Patient",
            "doctor_id": "_any_",
            "doctor_label": "Any Doctor",
            "paid_today": "25",
            "payload_json": {"treatment_remaining_cents_at_submit": 14000},
        },
        actor_user_id="admin-test",
    )

    try:
        approve_new_payment_entry(entry["id"], actor_user_id="approver-test-2")
        assert False, "Expected ValueError for unsupported payment source"
    except ValueError as exc:
        assert "Only treatment-card payment drafts can be approved in this slice." in str(exc)
