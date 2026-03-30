from __future__ import annotations

from collections import OrderedDict
from datetime import date

from flask import Blueprint, abort, flash, jsonify, redirect, request, url_for
from flask_login import current_user, login_required

from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, ANY_DOCTOR_LABEL, get_active_doctor_options
from clinic_app.services.i18n import T
from clinic_app.services.payments import money_input, parse_money_to_cents
from clinic_app.services.reception_entries import (
    approve_edit_payment_entry,
    approve_edit_treatment_entry,
    approve_edit_patient_entry,
    approve_new_payment_entry,
    approve_new_treatment_entry,
    create_entry,
    get_reception_review_patient,
    get_entry,
    get_locked_patient_context,
    get_locked_payment_context,
    get_locked_treatment_context,
    list_reception_candidate_patients,
    list_history_events,
    hold_entry,
    list_entries,
    list_entry_events,
    list_queue_entries,
    reject_entry,
    resubmit_returned_entry,
    return_entry,
    search_reception_review_patients,
    update_pending_entry,
    validate_entry_payload,
)
from clinic_app.services.ui import render_page

bp = Blueprint("reception", __name__)

RECEPTION_ACCESS_CODES = (
    "reception_entries:create",
    "reception_entries:review",
    "reception_entries:approve",
)


def _can_access_reception() -> bool:
    return current_user.is_authenticated and any(
        current_user.has_permission(code) for code in RECEPTION_ACCESS_CODES
    )


def _can_create() -> bool:
    return current_user.is_authenticated and current_user.has_permission("reception_entries:create")


def _can_view_patients() -> bool:
    return current_user.is_authenticated and current_user.has_permission("patients:view")


def _has_manager_visibility() -> bool:
    return current_user.is_authenticated and (
        current_user.has_permission("reception_entries:review")
        or current_user.has_permission("reception_entries:approve")
    )


def _can_review() -> bool:
    return _has_manager_visibility()


def _can_approve() -> bool:
    return current_user.is_authenticated and current_user.has_permission("reception_entries:approve")


def _doctor_options() -> list[dict[str, str]]:
    return get_active_doctor_options(include_any=True)


def _doctor_label_for(doctor_id: str) -> str:
    return next(
        (
            doctor["doctor_label"]
            for doctor in _doctor_options()
            if doctor["doctor_id"] == doctor_id
        ),
        "",
    )


def _default_form_data() -> dict[str, str]:
    return {
        "patient_name": "",
        "phone": "",
        "page_number": "",
        "visit_date": "",
        "visit_type": "exam",
        "treatment_text": "",
        "doctor_id": ANY_DOCTOR_ID,
        "money_received_today": "",
        "paid_today": "",
        "total_amount": "",
        "discount_amount": "",
        "note": "",
    }


def _default_payment_form_data() -> dict[str, str]:
    return {
        "amount": "",
        "visit_date": date.today().isoformat(),
        "method": "cash",
        "doctor_id": ANY_DOCTOR_ID,
        "note": "",
    }


def _entry_form_data(entry: dict | None = None) -> dict[str, str]:
    if not entry:
        return _default_form_data()
    payload = entry.get("payload_json") or {}
    note = payload.get("note") if isinstance(payload, dict) else ""
    paid_today = ""
    if entry.get("paid_today_cents") is not None:
        paid_today = f"{(entry['paid_today_cents'] or 0) / 100:.2f}".rstrip("0").rstrip(".")
    total_amount = ""
    if entry.get("total_amount_cents") is not None:
        total_amount = f"{(entry['total_amount_cents'] or 0) / 100:.2f}".rstrip("0").rstrip(".")
    discount_amount = ""
    if entry.get("discount_amount_cents") is not None:
        discount_amount = f"{(entry['discount_amount_cents'] or 0) / 100:.2f}".rstrip("0").rstrip(".")
    return {
        "patient_name": entry.get("patient_name") or "",
        "phone": entry.get("phone") or "",
        "page_number": entry.get("page_number") or "",
        "visit_date": entry.get("visit_date") or "",
        "visit_type": entry.get("visit_type") or "exam",
        "treatment_text": entry.get("treatment_text") or "",
        "doctor_id": entry.get("doctor_id") or ANY_DOCTOR_ID,
        "money_received_today": "1" if entry.get("money_received_today") else "",
        "paid_today": paid_today,
        "total_amount": total_amount,
        "discount_amount": discount_amount,
        "note": note or "",
    }


def _payment_form_data(context: dict | None = None, entry: dict | None = None) -> dict[str, str]:
    form_data = _default_payment_form_data()
    if context:
        form_data["doctor_id"] = context.get("doctor_id") or ANY_DOCTOR_ID
        form_data["visit_date"] = context.get("paid_at") or form_data["visit_date"]
    if entry:
        payload = entry.get("payload_json") or {}
        form_data["amount"] = money_input(entry.get("paid_today_cents"))
        form_data["visit_date"] = entry.get("visit_date") or form_data["visit_date"]
        form_data["doctor_id"] = entry.get("doctor_id") or form_data["doctor_id"]
        if isinstance(payload, dict):
            form_data["method"] = payload.get("method") or form_data["method"]
            form_data["note"] = payload.get("note") or ""
    return form_data


def _payment_correction_form_data(locked_payment: dict | None = None, entry: dict | None = None) -> dict[str, str]:
    payload = (entry or {}).get("payload_json") or {}
    proposed = payload.get("proposed") if isinstance(payload, dict) else None
    source = proposed if isinstance(proposed, dict) else (locked_payment or {})
    amount_cents = source.get("amount_cents")
    return {
        "amount": money_input(amount_cents),
        "visit_date": source.get("visit_date") or source.get("paid_at") or date.today().isoformat(),
        "method": source.get("method") or "cash",
        "doctor_id": source.get("doctor_id") or ANY_DOCTOR_ID,
        "note": source.get("note") or "",
    }
    

def _read_payment_correction_form_data() -> dict[str, str]:
    return _read_payment_form_data()


def _patient_payload_from_context(current_patient: dict | None) -> dict[str, object]:
    current_patient = current_patient or {}
    phones = []
    for row in current_patient.get("phones") or []:
        phone = (row.get("phone") or "").strip()
        if not phone:
            continue
        phones.append(
            {
                "phone": phone,
                "label": (row.get("label") or "").strip() or None,
                "is_primary": 1 if row.get("is_primary") else 0,
            }
        )
    if not phones and (current_patient.get("primary_phone") or "").strip():
        phones.append(
            {
                "phone": (current_patient.get("primary_phone") or "").strip(),
                "label": None,
                "is_primary": 1,
            }
        )

    pages = []
    for row in current_patient.get("pages") or []:
        page_number = (row.get("page_number") or "").strip()
        if not page_number:
            continue
        pages.append(
            {
                "page_number": page_number,
                "notebook_name": (row.get("notebook_name") or "").strip() or None,
                "notebook_color": (row.get("notebook_color") or "").strip(),
            }
        )
    if not pages and (current_patient.get("primary_page_number") or "").strip():
        pages.append(
            {
                "page_number": (current_patient.get("primary_page_number") or "").strip(),
                "notebook_name": None,
                "notebook_color": "",
            }
        )

    return {
        "short_id": (current_patient.get("short_id") or "").strip(),
        "full_name": (current_patient.get("full_name") or current_patient.get("patient_name") or "").strip(),
        "primary_phone": phones[0]["phone"] if phones else "",
        "phones": phones,
        "primary_page_number": pages[0]["page_number"] if pages else "",
        "pages": pages,
        "notes": (current_patient.get("notes") or "").strip(),
    }


def _patient_correction_form_data(current_patient: dict | None = None, entry: dict | None = None) -> dict[str, object]:
    payload = (entry or {}).get("payload_json") or {}
    proposed = payload.get("proposed") if isinstance(payload, dict) else None
    current = payload.get("current") if isinstance(payload, dict) else None

    source = proposed if isinstance(proposed, dict) else _patient_payload_from_context(current_patient)
    source_phones = list(source.get("phones") or [])
    source_pages = list(source.get("pages") or [])
    return {
        "short_id": (current or {}).get("short_id") if isinstance(current, dict) else (_patient_payload_from_context(current_patient).get("short_id") or ""),
        "full_name": source.get("full_name") or "",
        "phone_rows": source_phones,
        "page_rows": source_pages,
        "notes": source.get("notes") or "",
        "reception_note": (payload.get("note") or "") if isinstance(payload, dict) else "",
    }


def _read_patient_correction_form_data(current_patient: dict | None = None) -> dict[str, object]:
    phone_rows: list[dict[str, object]] = []
    primary_phone = (request.form.get("phone") or "").strip()
    if primary_phone:
        phone_rows.append({"phone": primary_phone, "label": None, "is_primary": 1})
    extra_numbers = request.form.getlist("extra_phone_number")
    extra_labels = request.form.getlist("extra_phone_label")
    for index, phone_raw in enumerate(extra_numbers):
        phone = (phone_raw or "").strip()
        if not phone:
            continue
        label = (extra_labels[index] if index < len(extra_labels) else "").strip() or None
        phone_rows.append({"phone": phone, "label": label, "is_primary": 0})

    page_rows: list[dict[str, object]] = []
    primary_page = (request.form.get("primary_page_number") or "").strip()
    primary_notebook_name = (request.form.get("primary_notebook_name") or "").strip() or None
    primary_notebook_color = (request.form.get("primary_notebook_color") or "").strip()
    if primary_page:
        page_rows.append(
            {
                "page_number": primary_page,
                "notebook_name": primary_notebook_name,
                "notebook_color": primary_notebook_color,
            }
        )
    extra_pages = request.form.getlist("extra_page_number")
    extra_notebook_names = request.form.getlist("extra_notebook_name")
    extra_notebook_colors = request.form.getlist("extra_notebook_color")
    row_count = max(len(extra_pages), len(extra_notebook_names), len(extra_notebook_colors))
    for index in range(row_count):
        page_number = (extra_pages[index] if index < len(extra_pages) else "").strip()
        if not page_number:
            continue
        notebook_name = (extra_notebook_names[index] if index < len(extra_notebook_names) else "").strip() or None
        notebook_color = (extra_notebook_colors[index] if index < len(extra_notebook_colors) else "").strip()
        page_rows.append(
            {
                "page_number": page_number,
                "notebook_name": notebook_name,
                "notebook_color": notebook_color,
            }
        )

    return {
        "short_id": (current_patient or {}).get("short_id") or "",
        "full_name": (request.form.get("full_name") or "").strip(),
        "phone_rows": phone_rows,
        "page_rows": page_rows,
        "notes": (request.form.get("notes") or "").strip(),
        "reception_note": (request.form.get("reception_note") or "").strip(),
    }


def _patient_correction_entry_payload_from_form_data(
    form_data: dict[str, object],
    current_patient: dict,
    *,
    locked_patient_id: str,
) -> dict:
    proposed_payload = {
        "full_name": form_data.get("full_name") or "",
        "phones": form_data.get("phone_rows") or [],
        "pages": form_data.get("page_rows") or [],
        "notes": form_data.get("notes") or "",
    }
    current_payload = _patient_payload_from_context(current_patient)
    primary_phone = ""
    phone_rows = form_data.get("phone_rows") or []
    if phone_rows:
        primary_phone = (phone_rows[0].get("phone") or "").strip()
    primary_page = ""
    page_rows = form_data.get("page_rows") or []
    if page_rows:
        primary_page = (page_rows[0].get("page_number") or "").strip()
    return {
        "draft_type": "edit_patient",
        "source": "patient_file",
        "patient_intent": "existing",
        "locked_patient_id": locked_patient_id,
        "patient_name": (form_data.get("full_name") or "").strip(),
        "phone": primary_phone,
        "page_number": primary_page,
        "doctor_id": ANY_DOCTOR_ID,
        "doctor_label": _doctor_label_for(ANY_DOCTOR_ID) or ANY_DOCTOR_LABEL,
        "payload_json": {
            "current": current_payload,
            "proposed": proposed_payload,
            "note": (form_data.get("reception_note") or "").strip(),
        },
    }


def _patient_file_treatment_entry_payload_from_form_data(
    form_data: dict[str, str],
    current_patient: dict,
    *,
    locked_patient_id: str,
) -> dict:
    primary_phone = str(current_patient.get("primary_phone") or "").strip()
    if not primary_phone:
        phones = current_patient.get("phones") or []
        if phones:
            primary_phone = str((phones[0] or {}).get("phone") or "").strip()

    primary_page = str(current_patient.get("primary_page_number") or "").strip()
    if not primary_page:
        pages = current_patient.get("pages") or []
        if pages:
            primary_page = str((pages[0] or {}).get("page_number") or "").strip()

    return {
        "draft_type": "new_treatment",
        "source": "patient_file",
        "patient_intent": "existing",
        "locked_patient_id": locked_patient_id,
        **form_data,
        "patient_name": str(current_patient.get("patient_name") or current_patient.get("full_name") or "").strip(),
        "phone": primary_phone,
        "page_number": primary_page,
        "doctor_label": _doctor_label_for(form_data["doctor_id"]),
        "payload_json": {"note": form_data["note"]} if form_data["note"] else {},
    }


def _read_form_data() -> dict[str, str]:
    return {
        "patient_name": (request.form.get("patient_name") or "").strip(),
        "phone": (request.form.get("phone") or "").strip(),
        "page_number": (request.form.get("page_number") or "").strip(),
        "visit_date": (request.form.get("visit_date") or "").strip(),
        "visit_type": (request.form.get("visit_type") or "").strip(),
        "treatment_text": (request.form.get("treatment_text") or "").strip(),
        "doctor_id": (request.form.get("doctor_id") or "").strip(),
        "money_received_today": (request.form.get("money_received_today") or "").strip(),
        "paid_today": (request.form.get("paid_today") or "").strip(),
        "total_amount": (request.form.get("total_amount") or "").strip(),
        "discount_amount": (request.form.get("discount_amount") or "").strip(),
        "note": (request.form.get("note") or "").strip(),
    }


def _read_payment_form_data() -> dict[str, str]:
    return {
        "amount": (request.form.get("amount") or "").strip(),
        "visit_date": (request.form.get("visit_date") or "").strip(),
        "method": (request.form.get("method") or "").strip(),
        "doctor_id": (request.form.get("doctor_id") or "").strip(),
        "note": (request.form.get("note") or "").strip(),
    }


def _entry_payload_from_form_data(form_data: dict[str, str]) -> dict:
    return {
        "draft_type": "new_treatment",
        "source": "reception_desk",
        "patient_intent": "unknown",
        **form_data,
        "doctor_label": _doctor_label_for(form_data["doctor_id"]),
        "payload_json": {"note": form_data["note"]} if form_data["note"] else {},
    }


def _payment_entry_payload_from_form_data(
    form_data: dict[str, str],
    locked_context: dict[str, str | int],
) -> dict:
    raw_amount = form_data.get("amount") or ""
    amount_cents = parse_money_to_cents(raw_amount)
    return {
        "draft_type": "new_payment",
        "source": "treatment_card",
        "patient_intent": "existing",
        "locked_patient_id": locked_context["patient_id"],
        "locked_treatment_id": locked_context["treatment_id"],
        "patient_name": locked_context.get("patient_name") or "",
        "phone": locked_context.get("phone") or "",
        "page_number": locked_context.get("page_number") or "",
        "visit_date": form_data.get("visit_date") or "",
        "treatment_text": locked_context.get("treatment_text") or "",
        "doctor_id": form_data["doctor_id"],
        "doctor_label": _doctor_label_for(form_data["doctor_id"]),
        "money_received_today": True,
        "paid_today": raw_amount,
        "total_amount": money_input(int(locked_context.get("total_amount_cents") or 0)),
        "discount_amount": money_input(int(locked_context.get("discount_amount_cents") or 0)),
        "payload_json": {
            "submitted_amount_cents": amount_cents,
            "treatment_remaining_cents_at_submit": int(locked_context.get("remaining_cents") or 0),
            "treatment_total_paid_cents_at_submit": int(locked_context.get("total_paid_cents") or 0),
            "method": form_data.get("method") or "cash",
            "note": form_data.get("note") or "",
        },
    }


def _status_label_key(entry: dict) -> str:
    if entry.get("last_action") == "returned":
        return "reception_status_returned"
    status = (entry.get("status") or "").strip().lower()
    if status in {"new", "edited"}:
        return "reception_status_waiting_review"
    if status == "held":
        return "reception_status_held"
    if status == "approved":
        return "reception_status_approved"
    if status == "rejected":
        return "reception_status_rejected"
    return "status"


def _build_summary(entries: list[dict]) -> dict[str, int]:
    open_drafts = 0
    returned = 0
    waiting_review = 0
    for entry in entries:
        status = (entry.get("status") or "").strip().lower()
        last_action = (entry.get("last_action") or "").strip().lower()
        if status not in {"approved", "rejected"}:
            open_drafts += 1
        if last_action == "returned":
            returned += 1
        if status in {"new", "edited"} and last_action != "returned":
            waiting_review += 1
    return {
        "open_drafts": open_drafts,
        "returned": returned,
        "waiting_review": waiting_review,
    }


def _review_status_label(entry: dict) -> str:
    return T(_status_label_key(entry))


def _entry_reason(entry: dict) -> str:
    if entry.get("last_action") == "returned":
        return entry.get("return_reason") or ""
    if entry.get("status") == "held":
        return entry.get("hold_reason") or ""
    if entry.get("status") == "rejected":
        return entry.get("rejection_reason") or ""
    return ""


def _decorate_entry(entry: dict) -> dict:
    entry["status_label"] = _review_status_label(entry)
    payload = entry.get("payload_json") or {}
    entry["note"] = (payload.get("note") if isinstance(payload, dict) else "") or ""
    entry["action_reason"] = _entry_reason(entry)
    return entry


def _draft_type_label(entry: dict) -> str:
    draft_type = (entry.get("draft_type") or "").strip().lower()
    if draft_type == "new_payment":
        return T("reception_history_kind_new_payment")
    if draft_type == "edit_payment":
        return T("reception_payment_correction_kind")
    if draft_type == "edit_patient":
        return T("reception_patient_correction_kind")
    if draft_type == "edit_treatment":
        return T("reception_treatment_correction_kind")
    if draft_type == "new_visit_only":
        return T("reception_history_kind_visit_only")
    return T("reception_history_kind_new_treatment")


def _source_label(entry: dict) -> str:
    source = (entry.get("source") or "").strip().lower()
    if source == "patient_file":
        return T("reception_history_source_patient_file")
    if source == "treatment_card":
        return T("reception_history_source_treatment_card")
    return T("reception_history_source_desk")


def _history_action_label(event: dict) -> str:
    action = (event.get("action") or "").strip().lower()
    return T(f"reception_history_action_{action}") if action in {
        "submitted",
        "edited",
        "returned",
        "held",
        "rejected",
        "approved",
    } else action.replace("_", " ").title()


def _decorate_history_event(event: dict) -> dict:
    event["action_label"] = _history_action_label(event)
    event["draft_type_label"] = _draft_type_label(event)
    event["source_label"] = _source_label(event)
    event["actor_label"] = (event.get("actor_username") or event.get("actor_user_id") or "").strip()
    event["patient_label"] = (event.get("patient_name") or "").strip() or T("reception_unknown_patient")
    event["summary_label"] = event.get("draft_type_label") or T("reception_history_kind_new_treatment")
    treatment_text = (event.get("treatment_text") or "").strip()
    if treatment_text and event.get("draft_type") not in {"edit_patient", "edit_payment", "edit_treatment"}:
        event["summary_label"] = treatment_text
    event["date_group"] = (event.get("created_at") or "")[:10] or ""
    event["can_open_detail"] = _can_access_entry(event)
    return event


def _group_history_events(events: list[dict]) -> list[dict]:
    groups: OrderedDict[str, list[dict]] = OrderedDict()
    for event in events:
        groups.setdefault(event.get("date_group") or "", []).append(event)
    return [
        {"date": date_label, "events": grouped_events}
        for date_label, grouped_events in groups.items()
    ]


def _approval_confirmation_key(entry: dict) -> str:
    if entry.get("draft_type") == "new_payment":
        return "reception_payment_approve_confirmation_label"
    if entry.get("draft_type") == "edit_payment":
        return "reception_edit_payment_approve_confirmation_label"
    if entry.get("draft_type") == "edit_patient":
        return "reception_patient_approve_confirmation_label"
    if entry.get("draft_type") == "edit_treatment":
        return "reception_treatment_approve_confirmation_label"
    return "reception_approve_confirmation_label"


def _recent_entries_for_current_user(limit: int = 20) -> list[dict]:
    entries = list_entries(submitted_by_user_id=current_user.id, limit=limit)
    for entry in entries:
        _decorate_entry(entry)
    return entries


def _build_desk_context(
    *,
    form_data: dict[str, str] | None = None,
    errors: list[str] | None = None,
) -> dict:
    can_create = _can_create()
    can_review = _has_manager_visibility()
    form_data = form_data or _default_form_data()
    entries = _recent_entries_for_current_user() if can_create else []
    summary = _build_summary(entries) if can_create else {"open_drafts": 0, "returned": 0, "waiting_review": 0}
    return {
        "show_back": False,
        "reception_view": "desk",
        "can_create_reception": can_create,
        "can_review_reception": can_review,
        "doctor_options": _doctor_options(),
        "reception_form": form_data,
        "reception_errors": errors or [],
        "reception_entries": entries,
        "reception_summary": summary,
        "queue_entries": [],
    }


def _build_queue_context() -> dict:
    if not _can_review():
        abort(403)
    queue_entries = list_queue_entries(limit=50)
    for entry in queue_entries:
        _decorate_entry(entry)
    return {
        "show_back": False,
        "reception_view": "queue",
        "can_create_reception": _can_create(),
        "can_review_reception": True,
        "doctor_options": _doctor_options(),
        "reception_form": _default_form_data(),
        "reception_errors": [],
        "reception_entries": _recent_entries_for_current_user() if _can_create() else [],
        "reception_summary": _build_summary(_recent_entries_for_current_user()) if _can_create() else {"open_drafts": 0, "returned": 0, "waiting_review": 0},
        "queue_entries": queue_entries,
    }


def _build_history_context() -> dict:
    history_events = list_history_events(
        submitted_by_user_id=None if _can_review() else current_user.id,
        limit=200,
    )
    for event in history_events:
        _decorate_history_event(event)
    return {
        "show_back": False,
        "reception_view": "history",
        "can_create_reception": _can_create(),
        "can_review_reception": _can_review(),
        "doctor_options": _doctor_options(),
        "reception_form": _default_form_data(),
        "reception_errors": [],
        "reception_entries": _recent_entries_for_current_user() if _can_create() else [],
        "reception_summary": _build_summary(_recent_entries_for_current_user()) if _can_create() else {"open_drafts": 0, "returned": 0, "waiting_review": 0},
        "queue_entries": [],
        "history_groups": _group_history_events(history_events),
    }


def _find_entry_or_404(entry_id: str) -> dict:
    entry = get_entry(entry_id)
    if not entry:
        abort(404)
    return _decorate_entry(entry)


def _can_access_entry(entry: dict) -> bool:
    if _can_review():
        return True
    return _can_create() and entry.get("submitted_by_user_id") == current_user.id


def _can_edit_returned_entry(entry: dict) -> bool:
    is_returned_treatment = (
        _can_create()
        and entry.get("submitted_by_user_id") == current_user.id
        and entry.get("draft_type") == "new_treatment"
        and entry.get("source") in {"reception_desk", "patient_file"}
        and entry.get("status") == "edited"
        and entry.get("last_action") == "returned"
    )
    is_returned_patient_correction = (
        _can_create()
        and entry.get("submitted_by_user_id") == current_user.id
        and entry.get("draft_type") == "edit_patient"
        and entry.get("source") == "patient_file"
        and entry.get("status") == "edited"
        and entry.get("last_action") == "returned"
    )
    is_returned_treatment_correction = (
        _can_create()
        and entry.get("submitted_by_user_id") == current_user.id
        and entry.get("draft_type") == "edit_treatment"
        and entry.get("source") == "treatment_card"
        and entry.get("status") == "edited"
        and entry.get("last_action") == "returned"
    )
    is_returned_payment_correction = (
        _can_create()
        and entry.get("submitted_by_user_id") == current_user.id
        and entry.get("draft_type") == "edit_payment"
        and entry.get("source") == "treatment_card"
        and entry.get("status") == "edited"
        and entry.get("last_action") == "returned"
    )
    return (
        is_returned_treatment
        or is_returned_patient_correction
        or is_returned_payment_correction
        or is_returned_treatment_correction
    )


def _can_manager_edit_entry(entry: dict) -> bool:
    if not _can_review():
        return False
    supports_manager_edit = (
        (entry.get("draft_type") == "new_treatment" and entry.get("source") in {"reception_desk", "patient_file"})
        or (entry.get("draft_type") == "new_payment" and entry.get("source") == "treatment_card")
        or (entry.get("draft_type") == "edit_patient" and entry.get("source") == "patient_file")
        or (entry.get("draft_type") == "edit_payment" and entry.get("source") == "treatment_card")
        or (entry.get("draft_type") == "edit_treatment" and entry.get("source") == "treatment_card")
    )
    return supports_manager_edit and entry.get("status") in {"new", "edited", "held"}


def _edit_mode(entry: dict) -> str | None:
    if _can_manager_edit_entry(entry):
        return "manager_edit"
    if _can_edit_returned_entry(entry):
        return "resubmit"
    return None


def _manager_edit_page_copy(entry: dict) -> dict[str, str]:
    if entry.get("draft_type") == "new_payment":
        return {
            "page_title_key": "reception_manager_edit_new_payment_title",
            "page_subtitle_key": "reception_manager_edit_new_payment_subtitle",
        }
    if entry.get("draft_type") == "edit_payment":
        return {
            "page_title_key": "reception_manager_edit_payment_title",
            "page_subtitle_key": "reception_manager_edit_payment_subtitle",
        }
    if entry.get("draft_type") == "edit_patient":
        return {
            "page_title_key": "reception_manager_edit_patient_title",
            "page_subtitle_key": "reception_manager_edit_patient_subtitle",
        }
    if entry.get("draft_type") == "edit_treatment":
        return {
            "page_title_key": "reception_manager_edit_treatment_title",
            "page_subtitle_key": "reception_manager_edit_treatment_subtitle",
        }
    return {
        "page_title_key": "reception_manager_edit_treatment_entry_title",
        "page_subtitle_key": "reception_manager_edit_treatment_entry_subtitle",
    }


def _detail_context(
    entry: dict,
    *,
    action_errors: list[str] | None = None,
    action_form: dict[str, str] | None = None,
) -> dict:
    if not _can_access_entry(entry):
        abort(403)
    events = list_entry_events(entry["id"])
    locked_treatment_context = None
    locked_patient_context = None
    locked_payment_context = None
    payload = entry.get("payload_json") or {}
    if entry.get("draft_type") in {"new_payment", "edit_payment", "edit_treatment"} and entry.get("locked_patient_id") and entry.get("locked_treatment_id"):
        locked_treatment_context = get_locked_treatment_context(
            entry["locked_patient_id"],
            entry["locked_treatment_id"],
        )
    if entry.get("draft_type") == "edit_payment" and entry.get("locked_patient_id") and entry.get("locked_payment_id"):
        locked_payment_context = get_locked_payment_context(
            entry["locked_patient_id"],
            entry["locked_payment_id"],
        )
    if entry.get("draft_type") in {"edit_patient", "new_treatment"} and entry.get("source") == "patient_file" and entry.get("locked_patient_id"):
        locked_patient_context = get_locked_patient_context(entry["locked_patient_id"])
    base_action_form = {
        "hold_note": "",
        "return_reason": "",
        "reject_reason": "",
        "confirm_approve": "",
        "approval_route": "create_new",
        "target_patient_id": "",
    }
    if action_form:
        base_action_form.update(action_form)
    approval_patient_candidates: list[dict] = []
    selected_approval_patient = None
    if entry.get("draft_type") == "new_treatment" and entry.get("source") == "reception_desk":
        approval_patient_candidates = list_reception_candidate_patients(entry)
        selected_patient_id = (base_action_form.get("target_patient_id") or "").strip()
        if selected_patient_id:
            selected_approval_patient = get_reception_review_patient(selected_patient_id)
    return {
        "show_back": False,
        "entry": entry,
        "entry_events": events,
        "locked_treatment_context": locked_treatment_context,
        "locked_patient_context": locked_patient_context,
        "locked_payment_context": locked_payment_context,
        "entry_payload": payload if isinstance(payload, dict) else {},
        "can_review_reception": _can_review(),
        "can_approve_reception": _can_approve(),
        "can_create_reception": _can_create(),
        "action_errors": action_errors or [],
        "action_form": base_action_form,
        "approval_confirmation_key": _approval_confirmation_key(entry),
        "approval_patient_candidates": approval_patient_candidates,
        "selected_approval_patient": selected_approval_patient,
        "can_edit_reception_entry": _can_manager_edit_entry(entry),
    }


def _edit_context(
    entry: dict,
    *,
    form_data: dict[str, str] | None = None,
    errors: list[str] | None = None,
    page_title_key: str,
    page_subtitle_key: str,
    submit_label_key: str,
    back_href: str,
    form_action: str | None = None,
    locked_patient: dict | None = None,
) -> dict:
    return {
        "show_back": False,
        "entry": entry,
        "doctor_options": _doctor_options(),
        "reception_form": form_data or _entry_form_data(entry),
        "reception_errors": errors or [],
        "return_reason": entry.get("return_reason") or "",
        "page_title_key": page_title_key,
        "page_subtitle_key": page_subtitle_key,
        "submit_label": T(submit_label_key),
        "back_href": back_href,
        "form_action": form_action,
        "locked_patient": locked_patient,
    }


def _patient_correction_context(
    current_patient: dict,
    *,
    entry: dict | None = None,
    form_data: dict[str, object] | None = None,
    errors: list[str] | None = None,
    page_title_key: str,
    page_subtitle_key: str,
    submit_label_key: str,
    form_action: str,
    back_href: str,
) -> dict:
    return {
        "show_back": False,
        "entry": entry,
        "current_patient": current_patient,
        "patient_correction_form": form_data or _patient_correction_form_data(current_patient=current_patient, entry=entry),
        "patient_correction_errors": errors or [],
        "page_title_key": page_title_key,
        "page_subtitle_key": page_subtitle_key,
        "submit_label": T(submit_label_key),
        "form_action": form_action,
        "return_reason": (entry or {}).get("return_reason") or "",
        "back_href": back_href,
    }


def _payment_correction_entry_payload_from_form_data(
    form_data: dict[str, str],
    locked_payment: dict[str, object],
) -> dict:
    treatment_context = locked_payment.get("treatment_context") or {}
    current_payload = {
        "payment_id": locked_payment.get("payment_id") or "",
        "treatment_id": locked_payment.get("treatment_id") or "",
        "is_initial_payment": 1 if locked_payment.get("is_initial_payment") else 0,
        "amount_cents": int(locked_payment.get("amount_cents") or 0),
        "visit_date": locked_payment.get("paid_at") or "",
        "method": locked_payment.get("method") or "cash",
        "doctor_id": locked_payment.get("doctor_id") or "",
        "doctor_label": locked_payment.get("doctor_label") or "",
        "note": locked_payment.get("note") or "",
        "treatment_remaining_cents": int((treatment_context or {}).get("remaining_cents") or 0),
        "treatment_total_paid_cents": int((treatment_context or {}).get("total_paid_cents") or 0),
    }
    amount_raw = form_data.get("amount") or ""
    return {
        "draft_type": "edit_payment",
        "source": "treatment_card",
        "patient_intent": "existing",
        "locked_patient_id": locked_payment["patient_id"],
        "locked_treatment_id": locked_payment["treatment_id"],
        "locked_payment_id": locked_payment["payment_id"],
        "patient_name": (treatment_context or {}).get("patient_name") or "",
        "phone": (treatment_context or {}).get("phone") or "",
        "page_number": (treatment_context or {}).get("page_number") or "",
        "visit_date": form_data.get("visit_date") or "",
        "treatment_text": (treatment_context or {}).get("treatment_text") or "",
        "doctor_id": form_data["doctor_id"],
        "doctor_label": _doctor_label_for(form_data["doctor_id"]),
        "money_received_today": True,
        "paid_today": amount_raw,
        "payload_json": {
            "current": current_payload,
            "proposed": {
                "payment_id": locked_payment["payment_id"],
                "treatment_id": locked_payment["treatment_id"],
                "amount": amount_raw,
                "visit_date": form_data.get("visit_date") or "",
                "method": form_data.get("method") or "cash",
                "doctor_id": form_data["doctor_id"],
                "doctor_label": _doctor_label_for(form_data["doctor_id"]),
                "note": form_data.get("note") or "",
            },
        },
    }


def _payment_correction_context(
    locked_payment: dict,
    *,
    entry: dict | None = None,
    form_data: dict[str, str] | None = None,
    errors: list[str] | None = None,
    page_title_key: str,
    page_subtitle_key: str,
    submit_label_key: str,
    form_action: str,
    back_href: str,
) -> dict:
    return {
        "show_back": False,
        "entry": entry,
        "locked_payment": locked_payment,
        "locked_treatment": locked_payment.get("treatment_context") or {},
        "doctor_options": _doctor_options(),
        "payment_form": form_data or _payment_correction_form_data(locked_payment, entry),
        "payment_errors": errors or [],
        "page_title_key": page_title_key,
        "page_subtitle_key": page_subtitle_key,
        "submit_label": T(submit_label_key),
        "form_action": form_action,
        "return_reason": (entry or {}).get("return_reason") or "",
        "back_href": back_href,
    }


def _treatment_correction_form_data(locked_treatment: dict | None = None, entry: dict | None = None) -> dict[str, str]:
    payload = (entry or {}).get("payload_json") or {}
    proposed = payload.get("proposed") if isinstance(payload, dict) else None
    source = proposed if isinstance(proposed, dict) else (locked_treatment or {})
    return {
        "treatment_text": source.get("treatment_text") or "",
        "visit_date": source.get("visit_date") or source.get("paid_at") or date.today().isoformat(),
        "visit_type": source.get("visit_type") or "none",
        "doctor_id": source.get("doctor_id") or ANY_DOCTOR_ID,
        "total_amount": money_input(source.get("total_amount_cents")),
        "discount_amount": money_input(source.get("discount_amount_cents")),
        "note": source.get("note") or "",
    }


def _read_treatment_correction_form_data() -> dict[str, str]:
    return {
        "treatment_text": (request.form.get("treatment_text") or "").strip(),
        "visit_date": (request.form.get("visit_date") or "").strip(),
        "visit_type": (request.form.get("visit_type") or "").strip(),
        "doctor_id": (request.form.get("doctor_id") or "").strip(),
        "total_amount": (request.form.get("total_amount") or "").strip(),
        "discount_amount": (request.form.get("discount_amount") or "").strip(),
        "note": (request.form.get("note") or "").strip(),
    }


def _treatment_correction_entry_payload_from_form_data(
    form_data: dict[str, str],
    locked_treatment: dict[str, object],
) -> dict:
    current_payload = {
        "patient_id": locked_treatment.get("patient_id") or "",
        "treatment_id": locked_treatment.get("treatment_id") or "",
        "treatment_text": locked_treatment.get("treatment_text") or "",
        "visit_date": locked_treatment.get("paid_at") or "",
        "visit_type": locked_treatment.get("visit_type") or "none",
        "doctor_id": locked_treatment.get("doctor_id") or "",
        "doctor_label": locked_treatment.get("doctor_label") or "",
        "total_amount_cents": int(locked_treatment.get("total_amount_cents") or 0),
        "discount_amount_cents": int(locked_treatment.get("discount_amount_cents") or 0),
        "note": locked_treatment.get("note") or "",
        "total_paid_cents": int(locked_treatment.get("total_paid_cents") or 0),
        "remaining_cents": int(locked_treatment.get("remaining_cents") or 0),
    }
    return {
        "draft_type": "edit_treatment",
        "source": "treatment_card",
        "patient_intent": "existing",
        "locked_patient_id": locked_treatment["patient_id"],
        "locked_treatment_id": locked_treatment["treatment_id"],
        "patient_name": locked_treatment.get("patient_name") or "",
        "phone": locked_treatment.get("phone") or "",
        "page_number": locked_treatment.get("page_number") or "",
        "visit_date": form_data.get("visit_date") or "",
        "visit_type": form_data.get("visit_type") or "none",
        "treatment_text": form_data.get("treatment_text") or "",
        "doctor_id": form_data["doctor_id"],
        "doctor_label": _doctor_label_for(form_data["doctor_id"]),
        "total_amount": form_data.get("total_amount") or "",
        "discount_amount": form_data.get("discount_amount") or "",
        "payload_json": {
            "current": current_payload,
            "proposed": {
                "treatment_text": form_data.get("treatment_text") or "",
                "visit_date": form_data.get("visit_date") or "",
                "visit_type": form_data.get("visit_type") or "none",
                "doctor_id": form_data["doctor_id"],
                "doctor_label": _doctor_label_for(form_data["doctor_id"]),
                "total_amount": form_data.get("total_amount") or "",
                "discount_amount": form_data.get("discount_amount") or "",
                "note": form_data.get("note") or "",
            },
        },
    }


def _treatment_correction_context(
    locked_treatment: dict,
    *,
    entry: dict | None = None,
    form_data: dict[str, str] | None = None,
    errors: list[str] | None = None,
    page_title_key: str,
    page_subtitle_key: str,
    submit_label_key: str,
    form_action: str,
    back_href: str,
) -> dict:
    return {
        "show_back": False,
        "entry": entry,
        "locked_treatment": locked_treatment,
        "doctor_options": _doctor_options(),
        "treatment_correction_form": form_data or _treatment_correction_form_data(locked_treatment, entry),
        "treatment_correction_errors": errors or [],
        "page_title_key": page_title_key,
        "page_subtitle_key": page_subtitle_key,
        "submit_label": T(submit_label_key),
        "form_action": form_action,
        "return_reason": (entry or {}).get("return_reason") or "",
        "back_href": back_href,
    }


def _render_detail(
    entry: dict,
    *,
    action_errors: list[str] | None = None,
    action_form: dict[str, str] | None = None,
    status_code: int = 200,
):
    return (
        render_page(
            "reception/detail.html",
            **_detail_context(entry, action_errors=action_errors, action_form=action_form),
        ),
        status_code,
    )


def _render_edit(
    entry: dict,
    *,
    form_data: dict[str, str] | None = None,
    errors: list[str] | None = None,
    page_title_key: str,
    page_subtitle_key: str,
    submit_label_key: str,
    back_href: str,
    status_code: int = 200,
    form_action: str | None = None,
    locked_patient: dict | None = None,
):
    return (
        render_page(
            "reception/edit.html",
            **_edit_context(
                entry,
                form_data=form_data,
                errors=errors,
                page_title_key=page_title_key,
                page_subtitle_key=page_subtitle_key,
                submit_label_key=submit_label_key,
                back_href=back_href,
                form_action=form_action,
                locked_patient=locked_patient,
            ),
        ),
        status_code,
    )


def _render_new_payment(
    locked_context: dict,
    *,
    form_data: dict[str, str] | None = None,
    errors: list[str] | None = None,
    page_title_key: str = "reception_new_payment_title",
    page_subtitle_key: str = "reception_new_payment_subtitle",
    submit_label_key: str = "reception_create_payment_draft",
    form_action: str | None = None,
    back_href: str | None = None,
    return_reason: str = "",
    status_code: int = 200,
):
    return (
        render_page(
            "reception/new_payment.html",
            show_back=False,
            doctor_options=_doctor_options(),
            payment_form=form_data or _payment_form_data(locked_context),
            payment_errors=errors or [],
            locked_treatment=locked_context,
            page_title_key=page_title_key,
            page_subtitle_key=page_subtitle_key,
            submit_label=T(submit_label_key),
            form_action=form_action or url_for("reception.create_new_payment_entry"),
            back_href=back_href or url_for("patients.patient_detail", pid=locked_context["patient_id"]),
            return_reason=return_reason,
        ),
        status_code,
    )


def _render_payment_correction(
    locked_payment: dict,
    *,
    entry: dict | None = None,
    form_data: dict[str, str] | None = None,
    errors: list[str] | None = None,
    page_title_key: str,
    page_subtitle_key: str,
    submit_label_key: str,
    form_action: str,
    back_href: str,
    status_code: int = 200,
):
    return (
        render_page(
            "reception/edit_payment.html",
            **_payment_correction_context(
                locked_payment,
                entry=entry,
                form_data=form_data,
                errors=errors,
                page_title_key=page_title_key,
                page_subtitle_key=page_subtitle_key,
                submit_label_key=submit_label_key,
                form_action=form_action,
                back_href=back_href,
            ),
        ),
        status_code,
    )


def _render_patient_correction(
    current_patient: dict,
    *,
    entry: dict | None = None,
    form_data: dict[str, object] | None = None,
    errors: list[str] | None = None,
    page_title_key: str,
    page_subtitle_key: str,
    submit_label_key: str,
    form_action: str,
    back_href: str,
    status_code: int = 200,
):
    return (
        render_page(
            "reception/edit_patient.html",
            **_patient_correction_context(
                current_patient,
                entry=entry,
                form_data=form_data,
                errors=errors,
                page_title_key=page_title_key,
                page_subtitle_key=page_subtitle_key,
                submit_label_key=submit_label_key,
                form_action=form_action,
                back_href=back_href,
            ),
        ),
        status_code,
    )


def _render_treatment_correction(
    locked_treatment: dict,
    *,
    entry: dict | None = None,
    form_data: dict[str, str] | None = None,
    errors: list[str] | None = None,
    page_title_key: str,
    page_subtitle_key: str,
    submit_label_key: str,
    form_action: str,
    back_href: str,
    status_code: int = 200,
):
    return (
        render_page(
            "reception/edit_treatment.html",
            **_treatment_correction_context(
                locked_treatment,
                entry=entry,
                form_data=form_data,
                errors=errors,
                page_title_key=page_title_key,
                page_subtitle_key=page_subtitle_key,
                submit_label_key=submit_label_key,
                form_action=form_action,
                back_href=back_href,
            ),
        ),
        status_code,
    )


def _locked_treatment_context_or_abort(patient_id: str, treatment_id: str) -> dict:
    context = get_locked_treatment_context(patient_id, treatment_id)
    if context:
        return context
    from clinic_app.services.database import db as raw_db

    conn = raw_db()
    try:
        payment = conn.execute(
            "SELECT id, patient_id, parent_payment_id FROM payments WHERE id=?",
            (treatment_id,),
        ).fetchone()
    finally:
        conn.close()
    if payment and (payment["parent_payment_id"] or "").strip():
        abort(400)
    abort(404)


def _locked_payment_context_or_abort(patient_id: str, payment_id: str) -> dict:
    context = get_locked_payment_context(patient_id, payment_id)
    if context:
        return context
    abort(404)


def _locked_patient_context_or_abort(patient_id: str) -> dict:
    context = get_locked_patient_context(patient_id)
    if context:
        return context
    abort(404)


@bp.route("/reception", methods=["GET"])
@login_required
def index():
    if not _can_access_reception():
        abort(403)

    view = (request.args.get("view") or "").strip().lower()
    if view == "queue":
        context = _build_queue_context()
    elif view == "history":
        context = _build_history_context()
    elif view == "desk":
        context = _build_desk_context()
    elif _can_create():
        context = _build_desk_context()
    elif _can_review():
        context = _build_queue_context()
    else:
        abort(403)
    return render_page(
        "reception/index.html",
        **context,
    )


@bp.route("/reception/entries", methods=["POST"])
@login_required
def create_reception_entry():
    if not _can_create():
        abort(403)

    form_data = _read_form_data()
    payload = _entry_payload_from_form_data(form_data)

    errors, _warnings, _normalized = validate_entry_payload(payload)
    if not errors:
        create_entry(payload, actor_user_id=current_user.id)
        flash(T("reception_draft_saved"), "ok")
        return redirect(url_for("reception.index", view="desk"))

    return (
        render_page(
            "reception/index.html",
            **_build_desk_context(form_data=form_data, errors=errors),
        ),
        200,
    )


@bp.route("/reception/entries/new-treatment", methods=["GET"])
@login_required
def new_treatment_entry():
    if not _can_create() or not _can_view_patients():
        abort(403)
    patient_id = (request.args.get("patient_id") or "").strip()
    if not patient_id:
        abort(404)
    current_patient = _locked_patient_context_or_abort(patient_id)
    return render_page(
        "reception/edit.html",
        **_edit_context(
            {},
            page_title_key="reception_new_treatment_title",
            page_subtitle_key="reception_new_treatment_subtitle",
            submit_label_key="reception_create_treatment_draft",
            back_href=url_for("patients.patient_detail", pid=patient_id),
            form_action=url_for("reception.create_new_treatment_entry"),
            locked_patient=current_patient,
        ),
    )


@bp.route("/reception/entries/new-treatment", methods=["POST"])
@login_required
def create_new_treatment_entry():
    if not _can_create() or not _can_view_patients():
        abort(403)
    patient_id = (request.form.get("patient_id") or "").strip()
    if not patient_id:
        abort(404)
    current_patient = _locked_patient_context_or_abort(patient_id)
    form_data = _read_form_data()
    payload = _patient_file_treatment_entry_payload_from_form_data(
        form_data,
        current_patient,
        locked_patient_id=patient_id,
    )
    errors, _warnings, _normalized = validate_entry_payload(payload)
    if errors:
        return (
            render_page(
                "reception/edit.html",
                **_edit_context(
                    {},
                    form_data=form_data,
                    errors=errors,
                    page_title_key="reception_new_treatment_title",
                    page_subtitle_key="reception_new_treatment_subtitle",
                    submit_label_key="reception_create_treatment_draft",
                    back_href=url_for("patients.patient_detail", pid=patient_id),
                    form_action=url_for("reception.create_new_treatment_entry"),
                    locked_patient=current_patient,
                ),
            ),
            400,
        )
    create_entry(payload, actor_user_id=current_user.id)
    flash(T("reception_new_treatment_draft_saved"), "ok")
    return redirect(url_for("reception.index", view="desk"))


@bp.route("/reception/entries/new-payment", methods=["GET"])
@login_required
def new_payment_entry():
    if not _can_create() or not _can_view_patients():
        abort(403)
    patient_id = (request.args.get("patient_id") or "").strip()
    treatment_id = (request.args.get("treatment_id") or "").strip()
    if not patient_id or not treatment_id:
        abort(404)
    context = _locked_treatment_context_or_abort(patient_id, treatment_id)
    return _render_new_payment(context)[0]


@bp.route("/reception/entries/new-payment", methods=["POST"])
@login_required
def create_new_payment_entry():
    if not _can_create() or not _can_view_patients():
        abort(403)
    patient_id = (request.form.get("patient_id") or "").strip()
    treatment_id = (request.form.get("treatment_id") or "").strip()
    if not patient_id or not treatment_id:
        abort(404)
    context = _locked_treatment_context_or_abort(patient_id, treatment_id)
    form_data = _read_payment_form_data()
    payload = _payment_entry_payload_from_form_data(form_data, context)
    errors, _warnings, _normalized = validate_entry_payload(payload)
    if errors:
        return _render_new_payment(context, form_data=form_data, errors=errors, status_code=400)
    create_entry(payload, actor_user_id=current_user.id)
    flash(T("reception_payment_draft_saved"), "ok")
    return redirect(url_for("reception.index", view="desk"))


@bp.route("/reception/entries/new-payment-correction", methods=["GET"])
@login_required
def new_payment_correction_entry():
    if not _can_create() or not _can_view_patients():
        abort(403)
    patient_id = (request.args.get("patient_id") or "").strip()
    payment_id = (request.args.get("payment_id") or "").strip()
    if not patient_id or not payment_id:
        abort(404)
    locked_payment = _locked_payment_context_or_abort(patient_id, payment_id)
    return render_page(
        "reception/edit_payment.html",
        **_payment_correction_context(
            locked_payment,
            page_title_key="reception_payment_correction_title",
            page_subtitle_key="reception_payment_correction_subtitle",
            submit_label_key="reception_payment_save_draft",
            form_action=url_for("reception.create_new_payment_correction_entry"),
            back_href=url_for("patients.patient_detail", pid=patient_id),
        ),
    )


@bp.route("/reception/entries/new-payment-correction", methods=["POST"])
@login_required
def create_new_payment_correction_entry():
    if not _can_create() or not _can_view_patients():
        abort(403)
    patient_id = (request.form.get("patient_id") or "").strip()
    payment_id = (request.form.get("payment_id") or "").strip()
    if not patient_id or not payment_id:
        abort(404)
    locked_payment = _locked_payment_context_or_abort(patient_id, payment_id)
    form_data = _read_payment_correction_form_data()
    payload = _payment_correction_entry_payload_from_form_data(form_data, locked_payment)
    errors, _warnings, _normalized = validate_entry_payload(payload)
    if errors:
        return _render_payment_correction(
            locked_payment,
            form_data=form_data,
            errors=errors,
            page_title_key="reception_payment_correction_title",
            page_subtitle_key="reception_payment_correction_subtitle",
            submit_label_key="reception_payment_save_draft",
            form_action=url_for("reception.create_new_payment_correction_entry"),
            back_href=url_for("patients.patient_detail", pid=patient_id),
            status_code=400,
        )
    create_entry(payload, actor_user_id=current_user.id)
    flash(T("reception_payment_correction_draft_saved"), "ok")
    return redirect(url_for("reception.index", view="desk"))


@bp.route("/reception/entries/new-treatment-correction", methods=["GET"])
@login_required
def new_treatment_correction_entry():
    if not _can_create() or not _can_view_patients():
        abort(403)
    patient_id = (request.args.get("patient_id") or "").strip()
    treatment_id = (request.args.get("treatment_id") or "").strip()
    if not patient_id or not treatment_id:
        abort(404)
    locked_treatment = _locked_treatment_context_or_abort(patient_id, treatment_id)
    return render_page(
        "reception/edit_treatment.html",
        **_treatment_correction_context(
            locked_treatment,
            page_title_key="reception_treatment_correction_title",
            page_subtitle_key="reception_treatment_correction_subtitle",
            submit_label_key="reception_treatment_save_draft",
            form_action=url_for("reception.create_new_treatment_correction_entry"),
            back_href=url_for("patients.patient_detail", pid=patient_id),
        ),
    )


@bp.route("/reception/entries/new-treatment-correction", methods=["POST"])
@login_required
def create_new_treatment_correction_entry():
    if not _can_create() or not _can_view_patients():
        abort(403)
    patient_id = (request.form.get("patient_id") or "").strip()
    treatment_id = (request.form.get("treatment_id") or "").strip()
    if not patient_id or not treatment_id:
        abort(404)
    locked_treatment = _locked_treatment_context_or_abort(patient_id, treatment_id)
    form_data = _read_treatment_correction_form_data()
    payload = _treatment_correction_entry_payload_from_form_data(form_data, locked_treatment)
    errors, _warnings, _normalized = validate_entry_payload(payload)
    if errors:
        return _render_treatment_correction(
            locked_treatment,
            form_data=form_data,
            errors=errors,
            page_title_key="reception_treatment_correction_title",
            page_subtitle_key="reception_treatment_correction_subtitle",
            submit_label_key="reception_treatment_save_draft",
            form_action=url_for("reception.create_new_treatment_correction_entry"),
            back_href=url_for("patients.patient_detail", pid=patient_id),
            status_code=400,
        )
    create_entry(payload, actor_user_id=current_user.id)
    flash(T("reception_treatment_draft_saved"), "ok")
    return redirect(url_for("reception.index", view="desk"))


@bp.route("/reception/entries/new-patient-correction", methods=["GET"])
@login_required
def new_patient_correction_entry():
    if not _can_create() or not _can_view_patients():
        abort(403)
    patient_id = (request.args.get("patient_id") or "").strip()
    if not patient_id:
        abort(404)
    current_patient = _locked_patient_context_or_abort(patient_id)
    return render_page(
        "reception/edit_patient.html",
        **_patient_correction_context(
            current_patient,
            page_title_key="reception_patient_correction_title",
            page_subtitle_key="reception_patient_correction_subtitle",
            submit_label_key="reception_patient_save_draft",
            form_action=url_for("reception.create_new_patient_correction_entry"),
            back_href=url_for("patients.patient_detail", pid=patient_id),
        ),
    )


@bp.route("/reception/entries/new-patient-correction", methods=["POST"])
@login_required
def create_new_patient_correction_entry():
    if not _can_create() or not _can_view_patients():
        abort(403)
    patient_id = (request.form.get("patient_id") or "").strip()
    if not patient_id:
        abort(404)
    current_patient = _locked_patient_context_or_abort(patient_id)
    form_data = _read_patient_correction_form_data(current_patient)
    payload = _patient_correction_entry_payload_from_form_data(
        form_data,
        current_patient,
        locked_patient_id=patient_id,
    )
    errors, _warnings, _normalized = validate_entry_payload(payload)
    if errors:
        return _render_patient_correction(
            current_patient,
            form_data=form_data,
            errors=errors,
            page_title_key="reception_patient_correction_title",
            page_subtitle_key="reception_patient_correction_subtitle",
            submit_label_key="reception_patient_save_draft",
            form_action=url_for("reception.create_new_patient_correction_entry"),
            back_href=url_for("patients.patient_detail", pid=patient_id),
            status_code=400,
        )
    create_entry(payload, actor_user_id=current_user.id)
    flash(T("reception_patient_draft_saved"), "ok")
    return redirect(url_for("reception.index", view="desk"))


@bp.route("/reception/entries/<entry_id>", methods=["GET"])
@login_required
def reception_entry_detail(entry_id: str):
    if not _can_access_reception():
        abort(403)
    entry = _find_entry_or_404(entry_id)
    if not _can_access_entry(entry):
        abort(403)
    return render_page(
        "reception/detail.html",
        **_detail_context(entry),
    )


@bp.route("/reception/api/patients/search", methods=["GET"])
@login_required
def reception_patient_search():
    if not _has_manager_visibility():
        abort(403)
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify([])
    return jsonify(search_reception_review_patients(query, limit=8))


@bp.route("/reception/entries/<entry_id>/edit", methods=["GET"])
@login_required
def edit_reception_entry(entry_id: str):
    if not (_can_create() or _can_review()):
        abort(403)
    entry = _find_entry_or_404(entry_id)
    mode = _edit_mode(entry)
    if not mode:
        abort(403)
    is_manager_edit = mode == "manager_edit"
    if entry.get("draft_type") == "new_treatment" and entry.get("source") == "patient_file":
        current_patient = get_locked_patient_context(entry.get("locked_patient_id") or "") or {
            "patient_id": entry.get("locked_patient_id") or "",
            "patient_name": entry.get("patient_name") or "",
            "full_name": entry.get("patient_name") or "",
            "primary_phone": entry.get("phone") or "",
            "phones": ([{"phone": entry.get("phone") or "", "label": None, "is_primary": 1}] if entry.get("phone") else []),
            "primary_page_number": entry.get("page_number") or "",
            "pages": ([{"page_number": entry.get("page_number") or "", "notebook_name": None, "notebook_color": ""}] if entry.get("page_number") else []),
            "notes": "",
        }
        copy = _manager_edit_page_copy(entry) if is_manager_edit else {
            "page_title_key": "reception_edit_title",
            "page_subtitle_key": "reception_edit_subtitle",
        }
        return render_page(
            "reception/edit.html",
            **_edit_context(
                entry,
                page_title_key=copy["page_title_key"],
                page_subtitle_key=copy["page_subtitle_key"],
                submit_label_key="reception_manager_save_draft" if is_manager_edit else "reception_resubmit_draft",
                back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]) if is_manager_edit else url_for("reception.index", view="desk"),
                locked_patient=current_patient,
            ),
        )
    if entry.get("draft_type") == "edit_payment":
        locked_payment = get_locked_payment_context(
            entry.get("locked_patient_id") or "",
            entry.get("locked_payment_id") or "",
        ) or {
            "patient_id": entry.get("locked_patient_id") or "",
            "payment_id": entry.get("locked_payment_id") or "",
            "treatment_id": entry.get("locked_treatment_id") or "",
            "paid_at": entry.get("visit_date") or "",
            "amount_cents": entry.get("paid_today_cents") or 0,
            "method": ((entry.get("payload_json") or {}).get("current") or {}).get("method") or "cash",
            "note": ((entry.get("payload_json") or {}).get("current") or {}).get("note") or "",
            "doctor_id": entry.get("doctor_id") or "",
            "doctor_label": entry.get("doctor_label") or "",
            "is_initial_payment": 1 if (entry.get("locked_payment_id") or "") == (entry.get("locked_treatment_id") or "") else 0,
            "treatment_context": get_locked_treatment_context(
                entry.get("locked_patient_id") or "",
                entry.get("locked_treatment_id") or "",
            ) or {},
        }
        return render_page(
            "reception/edit_payment.html",
            **_payment_correction_context(
                locked_payment,
                entry=entry,
                page_title_key="reception_manager_edit_payment_title" if is_manager_edit else "reception_edit_payment_title",
                page_subtitle_key="reception_manager_edit_payment_subtitle" if is_manager_edit else "reception_edit_payment_subtitle",
                submit_label_key="reception_manager_save_draft" if is_manager_edit else "reception_resubmit_draft",
                form_action=url_for("reception.submit_reception_entry_edit", entry_id=entry["id"]),
                back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]) if is_manager_edit else url_for("reception.index", view="desk"),
            ),
        )
    if entry.get("draft_type") == "edit_patient":
        current_patient = get_locked_patient_context(entry.get("locked_patient_id") or "") or {
            "patient_id": entry.get("locked_patient_id") or "",
            **((entry.get("payload_json") or {}).get("current") or {}),
        }
        return render_page(
            "reception/edit_patient.html",
            **_patient_correction_context(
                current_patient,
                entry=entry,
                page_title_key="reception_manager_edit_patient_title" if is_manager_edit else "reception_edit_patient_title",
                page_subtitle_key="reception_manager_edit_patient_subtitle" if is_manager_edit else "reception_edit_patient_subtitle",
                submit_label_key="reception_manager_save_draft" if is_manager_edit else "reception_resubmit_draft",
                form_action=url_for("reception.submit_reception_entry_edit", entry_id=entry["id"]),
                back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]) if is_manager_edit else url_for("reception.index", view="desk"),
            ),
        )
    if entry.get("draft_type") == "edit_treatment":
        locked_treatment = get_locked_treatment_context(
            entry.get("locked_patient_id") or "",
            entry.get("locked_treatment_id") or "",
        ) or {
            "patient_id": entry.get("locked_patient_id") or "",
            "treatment_id": entry.get("locked_treatment_id") or "",
            "patient_name": entry.get("patient_name") or "",
            "phone": entry.get("phone") or "",
            "page_number": entry.get("page_number") or "",
            **((entry.get("payload_json") or {}).get("current") or {}),
        }
        return render_page(
            "reception/edit_treatment.html",
            **_treatment_correction_context(
                locked_treatment,
                entry=entry,
                page_title_key="reception_manager_edit_treatment_title" if is_manager_edit else "reception_edit_treatment_title",
                page_subtitle_key="reception_manager_edit_treatment_subtitle" if is_manager_edit else "reception_edit_treatment_subtitle",
                submit_label_key="reception_manager_save_draft" if is_manager_edit else "reception_resubmit_draft",
                form_action=url_for("reception.submit_reception_entry_edit", entry_id=entry["id"]),
                back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]) if is_manager_edit else url_for("reception.index", view="desk"),
            ),
        )
    if entry.get("draft_type") == "new_payment":
        locked_treatment = get_locked_treatment_context(
            entry.get("locked_patient_id") or "",
            entry.get("locked_treatment_id") or "",
        ) or {
            "patient_id": entry.get("locked_patient_id") or "",
            "treatment_id": entry.get("locked_treatment_id") or "",
            "patient_name": entry.get("patient_name") or "",
            "phone": entry.get("phone") or "",
            "page_number": entry.get("page_number") or "",
            "treatment_text": entry.get("treatment_text") or "",
            "doctor_id": entry.get("doctor_id") or "",
            "doctor_label": entry.get("doctor_label") or "",
            "paid_at": entry.get("visit_date") or "",
            "total_amount_cents": entry.get("total_amount_cents") or 0,
            "discount_amount_cents": entry.get("discount_amount_cents") or 0,
            "remaining_cents": ((entry.get("payload_json") or {}).get("treatment_remaining_cents_at_submit") or 0),
            "total_paid_cents": ((entry.get("payload_json") or {}).get("treatment_total_paid_cents_at_submit") or 0),
        }
        copy = _manager_edit_page_copy(entry)
        return render_page(
            "reception/new_payment.html",
            show_back=False,
            doctor_options=_doctor_options(),
            payment_form=_payment_form_data(locked_treatment, entry),
            payment_errors=[],
            locked_treatment=locked_treatment,
            page_title_key=copy["page_title_key"],
            page_subtitle_key=copy["page_subtitle_key"],
            submit_label=T("reception_manager_save_draft"),
            form_action=url_for("reception.submit_reception_entry_edit", entry_id=entry["id"]),
            back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]),
            return_reason=entry.get("return_reason") or "",
        )
    copy = _manager_edit_page_copy(entry) if is_manager_edit else {
        "page_title_key": "reception_edit_title",
        "page_subtitle_key": "reception_edit_subtitle",
    }
    return render_page(
        "reception/edit.html",
        **_edit_context(
            entry,
            page_title_key=copy["page_title_key"],
            page_subtitle_key=copy["page_subtitle_key"],
            submit_label_key="reception_manager_save_draft" if is_manager_edit else "reception_resubmit_draft",
            back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]) if is_manager_edit else url_for("reception.index", view="desk"),
        ),
    )


@bp.route("/reception/entries/<entry_id>/edit", methods=["POST"])
@login_required
def submit_reception_entry_edit(entry_id: str):
    if not (_can_create() or _can_review()):
        abort(403)
    entry = _find_entry_or_404(entry_id)
    mode = _edit_mode(entry)
    if not mode:
        abort(403)
    is_manager_edit = mode == "manager_edit"
    if entry.get("draft_type") == "new_treatment" and entry.get("source") == "patient_file":
        current_patient = get_locked_patient_context(entry.get("locked_patient_id") or "") or {
            "patient_id": entry.get("locked_patient_id") or "",
            "patient_name": entry.get("patient_name") or "",
            "full_name": entry.get("patient_name") or "",
            "primary_phone": entry.get("phone") or "",
            "phones": ([{"phone": entry.get("phone") or "", "label": None, "is_primary": 1}] if entry.get("phone") else []),
            "primary_page_number": entry.get("page_number") or "",
            "pages": ([{"page_number": entry.get("page_number") or "", "notebook_name": None, "notebook_color": ""}] if entry.get("page_number") else []),
            "notes": "",
        }
        form_data = _read_form_data()
        payload = _patient_file_treatment_entry_payload_from_form_data(
            form_data,
            current_patient,
            locked_patient_id=entry.get("locked_patient_id") or "",
        )
        errors, _warnings, _normalized = validate_entry_payload(payload)
        copy = _manager_edit_page_copy(entry) if is_manager_edit else {
            "page_title_key": "reception_edit_title",
            "page_subtitle_key": "reception_edit_subtitle",
        }
        if errors:
            return _render_edit(
                entry,
                form_data=form_data,
                errors=errors,
                page_title_key=copy["page_title_key"],
                page_subtitle_key=copy["page_subtitle_key"],
                submit_label_key="reception_manager_save_draft" if is_manager_edit else "reception_resubmit_draft",
                back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]) if is_manager_edit else url_for("reception.index", view="desk"),
                status_code=400,
                locked_patient=current_patient,
            )
        try:
            update_pending_entry(entry_id, payload, actor_user_id=current_user.id, mode=mode)
        except ValueError as exc:
            refreshed_entry = _find_entry_or_404(entry_id)
            refreshed_patient = get_locked_patient_context(refreshed_entry.get("locked_patient_id") or "") or current_patient
            return _render_edit(
                refreshed_entry,
                form_data=form_data,
                errors=[str(exc)],
                page_title_key=copy["page_title_key"],
                page_subtitle_key=copy["page_subtitle_key"],
                submit_label_key="reception_manager_save_draft" if is_manager_edit else "reception_resubmit_draft",
                back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]) if is_manager_edit else url_for("reception.index", view="desk"),
                status_code=400,
                locked_patient=refreshed_patient,
            )
        flash(T("reception_draft_updated" if is_manager_edit else "reception_draft_resubmitted"), "ok")
        return redirect(url_for("reception.reception_entry_detail", entry_id=entry_id) if is_manager_edit else url_for("reception.index", view="desk"))
    if entry.get("draft_type") == "edit_payment":
        locked_payment = get_locked_payment_context(
            entry.get("locked_patient_id") or "",
            entry.get("locked_payment_id") or "",
        ) or {
            "patient_id": entry.get("locked_patient_id") or "",
            "payment_id": entry.get("locked_payment_id") or "",
            "treatment_id": entry.get("locked_treatment_id") or "",
            "paid_at": entry.get("visit_date") or "",
            "amount_cents": entry.get("paid_today_cents") or 0,
            "method": ((entry.get("payload_json") or {}).get("current") or {}).get("method") or "cash",
            "note": ((entry.get("payload_json") or {}).get("current") or {}).get("note") or "",
            "doctor_id": entry.get("doctor_id") or "",
            "doctor_label": entry.get("doctor_label") or "",
            "is_initial_payment": 1 if (entry.get("locked_payment_id") or "") == (entry.get("locked_treatment_id") or "") else 0,
            "treatment_context": get_locked_treatment_context(
                entry.get("locked_patient_id") or "",
                entry.get("locked_treatment_id") or "",
            ) or {},
        }
        form_data = _read_payment_correction_form_data()
        payload = _payment_correction_entry_payload_from_form_data(form_data, locked_payment)
        errors, _warnings, _normalized = validate_entry_payload(payload)
        if errors:
            return _render_payment_correction(
                locked_payment,
                entry=entry,
                form_data=form_data,
                errors=errors,
                page_title_key="reception_manager_edit_payment_title" if is_manager_edit else "reception_edit_payment_title",
                page_subtitle_key="reception_manager_edit_payment_subtitle" if is_manager_edit else "reception_edit_payment_subtitle",
                submit_label_key="reception_manager_save_draft" if is_manager_edit else "reception_resubmit_draft",
                form_action=url_for("reception.submit_reception_entry_edit", entry_id=entry["id"]),
                back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]) if is_manager_edit else url_for("reception.index", view="desk"),
                status_code=400,
            )
        try:
            update_pending_entry(entry_id, payload, actor_user_id=current_user.id, mode=mode)
        except ValueError as exc:
            refreshed_entry = _find_entry_or_404(entry_id)
            refreshed_payment = get_locked_payment_context(
                refreshed_entry.get("locked_patient_id") or "",
                refreshed_entry.get("locked_payment_id") or "",
            ) or locked_payment
            return _render_payment_correction(
                refreshed_payment,
                entry=refreshed_entry,
                form_data=form_data,
                errors=[str(exc)],
                page_title_key="reception_manager_edit_payment_title" if is_manager_edit else "reception_edit_payment_title",
                page_subtitle_key="reception_manager_edit_payment_subtitle" if is_manager_edit else "reception_edit_payment_subtitle",
                submit_label_key="reception_manager_save_draft" if is_manager_edit else "reception_resubmit_draft",
                form_action=url_for("reception.submit_reception_entry_edit", entry_id=entry["id"]),
                back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]) if is_manager_edit else url_for("reception.index", view="desk"),
                status_code=400,
            )
        flash(T("reception_draft_updated" if is_manager_edit else "reception_draft_resubmitted"), "ok")
        return redirect(url_for("reception.reception_entry_detail", entry_id=entry_id) if is_manager_edit else url_for("reception.index", view="desk"))
    if entry.get("draft_type") == "edit_patient":
        current_patient = get_locked_patient_context(entry.get("locked_patient_id") or "") or {
            "patient_id": entry.get("locked_patient_id") or "",
            **((entry.get("payload_json") or {}).get("current") or {}),
        }
        form_data = _read_patient_correction_form_data(current_patient)
        payload = _patient_correction_entry_payload_from_form_data(
            form_data,
            current_patient,
            locked_patient_id=entry.get("locked_patient_id") or "",
        )
        errors, _warnings, _normalized = validate_entry_payload(payload)
        if errors:
            return _render_patient_correction(
                current_patient,
                entry=entry,
                form_data=form_data,
                errors=errors,
                page_title_key="reception_manager_edit_patient_title" if is_manager_edit else "reception_edit_patient_title",
                page_subtitle_key="reception_manager_edit_patient_subtitle" if is_manager_edit else "reception_edit_patient_subtitle",
                submit_label_key="reception_manager_save_draft" if is_manager_edit else "reception_resubmit_draft",
                form_action=url_for("reception.submit_reception_entry_edit", entry_id=entry["id"]),
                back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]) if is_manager_edit else url_for("reception.index", view="desk"),
                status_code=400,
            )
        try:
            update_pending_entry(entry_id, payload, actor_user_id=current_user.id, mode=mode)
        except ValueError as exc:
            refreshed_entry = _find_entry_or_404(entry_id)
            refreshed_patient = get_locked_patient_context(refreshed_entry.get("locked_patient_id") or "") or current_patient
            return _render_patient_correction(
                refreshed_patient,
                entry=refreshed_entry,
                form_data=form_data,
                errors=[str(exc)],
                page_title_key="reception_manager_edit_patient_title" if is_manager_edit else "reception_edit_patient_title",
                page_subtitle_key="reception_manager_edit_patient_subtitle" if is_manager_edit else "reception_edit_patient_subtitle",
                submit_label_key="reception_manager_save_draft" if is_manager_edit else "reception_resubmit_draft",
                form_action=url_for("reception.submit_reception_entry_edit", entry_id=entry["id"]),
                back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]) if is_manager_edit else url_for("reception.index", view="desk"),
                status_code=400,
            )
        flash(T("reception_draft_updated" if is_manager_edit else "reception_draft_resubmitted"), "ok")
        return redirect(url_for("reception.reception_entry_detail", entry_id=entry_id) if is_manager_edit else url_for("reception.index", view="desk"))
    if entry.get("draft_type") == "edit_treatment":
        locked_treatment = get_locked_treatment_context(
            entry.get("locked_patient_id") or "",
            entry.get("locked_treatment_id") or "",
        ) or {
            "patient_id": entry.get("locked_patient_id") or "",
            "treatment_id": entry.get("locked_treatment_id") or "",
            "patient_name": entry.get("patient_name") or "",
            "phone": entry.get("phone") or "",
            "page_number": entry.get("page_number") or "",
            **((entry.get("payload_json") or {}).get("current") or {}),
        }
        form_data = _read_treatment_correction_form_data()
        payload = _treatment_correction_entry_payload_from_form_data(form_data, locked_treatment)
        errors, _warnings, _normalized = validate_entry_payload(payload)
        if errors:
            return _render_treatment_correction(
                locked_treatment,
                entry=entry,
                form_data=form_data,
                errors=errors,
                page_title_key="reception_manager_edit_treatment_title" if is_manager_edit else "reception_edit_treatment_title",
                page_subtitle_key="reception_manager_edit_treatment_subtitle" if is_manager_edit else "reception_edit_treatment_subtitle",
                submit_label_key="reception_manager_save_draft" if is_manager_edit else "reception_resubmit_draft",
                form_action=url_for("reception.submit_reception_entry_edit", entry_id=entry["id"]),
                back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]) if is_manager_edit else url_for("reception.index", view="desk"),
                status_code=400,
            )
        try:
            update_pending_entry(entry_id, payload, actor_user_id=current_user.id, mode=mode)
        except ValueError as exc:
            refreshed_entry = _find_entry_or_404(entry_id)
            refreshed_treatment = get_locked_treatment_context(
                refreshed_entry.get("locked_patient_id") or "",
                refreshed_entry.get("locked_treatment_id") or "",
            ) or locked_treatment
            return _render_treatment_correction(
                refreshed_treatment,
                entry=refreshed_entry,
                form_data=form_data,
                errors=[str(exc)],
                page_title_key="reception_manager_edit_treatment_title" if is_manager_edit else "reception_edit_treatment_title",
                page_subtitle_key="reception_manager_edit_treatment_subtitle" if is_manager_edit else "reception_edit_treatment_subtitle",
                submit_label_key="reception_manager_save_draft" if is_manager_edit else "reception_resubmit_draft",
                form_action=url_for("reception.submit_reception_entry_edit", entry_id=entry["id"]),
                back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]) if is_manager_edit else url_for("reception.index", view="desk"),
                status_code=400,
            )
        flash(T("reception_draft_updated" if is_manager_edit else "reception_draft_resubmitted"), "ok")
        return redirect(url_for("reception.reception_entry_detail", entry_id=entry_id) if is_manager_edit else url_for("reception.index", view="desk"))
    if entry.get("draft_type") == "new_payment":
        locked_treatment = get_locked_treatment_context(
            entry.get("locked_patient_id") or "",
            entry.get("locked_treatment_id") or "",
        ) or {
            "patient_id": entry.get("locked_patient_id") or "",
            "treatment_id": entry.get("locked_treatment_id") or "",
            "patient_name": entry.get("patient_name") or "",
            "phone": entry.get("phone") or "",
            "page_number": entry.get("page_number") or "",
            "treatment_text": entry.get("treatment_text") or "",
            "doctor_id": entry.get("doctor_id") or "",
            "doctor_label": entry.get("doctor_label") or "",
            "paid_at": entry.get("visit_date") or "",
            "total_amount_cents": entry.get("total_amount_cents") or 0,
            "discount_amount_cents": entry.get("discount_amount_cents") or 0,
            "remaining_cents": ((entry.get("payload_json") or {}).get("treatment_remaining_cents_at_submit") or 0),
            "total_paid_cents": ((entry.get("payload_json") or {}).get("treatment_total_paid_cents_at_submit") or 0),
        }
        form_data = _read_payment_form_data()
        payload = _payment_entry_payload_from_form_data(form_data, locked_treatment)
        errors, _warnings, _normalized = validate_entry_payload(payload)
        copy = _manager_edit_page_copy(entry)
        if errors:
            return _render_new_payment(
                locked_treatment,
                form_data=form_data,
                errors=errors,
                page_title_key=copy["page_title_key"],
                page_subtitle_key=copy["page_subtitle_key"],
                submit_label_key="reception_manager_save_draft",
                form_action=url_for("reception.submit_reception_entry_edit", entry_id=entry["id"]),
                back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]),
                return_reason=entry.get("return_reason") or "",
                status_code=400,
            )
        try:
            update_pending_entry(entry_id, payload, actor_user_id=current_user.id, mode=mode)
        except ValueError as exc:
            refreshed_entry = _find_entry_or_404(entry_id)
            refreshed_treatment = get_locked_treatment_context(
                refreshed_entry.get("locked_patient_id") or "",
                refreshed_entry.get("locked_treatment_id") or "",
            ) or locked_treatment
            return _render_new_payment(
                refreshed_treatment,
                form_data=form_data,
                errors=[str(exc)],
                page_title_key=copy["page_title_key"],
                page_subtitle_key=copy["page_subtitle_key"],
                submit_label_key="reception_manager_save_draft",
                form_action=url_for("reception.submit_reception_entry_edit", entry_id=entry["id"]),
                back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]),
                return_reason=refreshed_entry.get("return_reason") or "",
                status_code=400,
            )
        flash(T("reception_draft_updated"), "ok")
        return redirect(url_for("reception.reception_entry_detail", entry_id=entry_id))
    form_data = _read_form_data()
    payload = _entry_payload_from_form_data(form_data)
    errors, _warnings, _normalized = validate_entry_payload(payload)
    copy = _manager_edit_page_copy(entry) if is_manager_edit else {
        "page_title_key": "reception_edit_title",
        "page_subtitle_key": "reception_edit_subtitle",
    }
    if errors:
        return _render_edit(
            entry,
            form_data=form_data,
            errors=errors,
            page_title_key=copy["page_title_key"],
            page_subtitle_key=copy["page_subtitle_key"],
            submit_label_key="reception_manager_save_draft" if is_manager_edit else "reception_resubmit_draft",
            back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]) if is_manager_edit else url_for("reception.index", view="desk"),
            status_code=400,
        )
    try:
        update_pending_entry(entry_id, payload, actor_user_id=current_user.id, mode=mode)
    except ValueError as exc:
        refreshed_entry = _find_entry_or_404(entry_id)
        return _render_edit(
            refreshed_entry,
            form_data=form_data,
            errors=[str(exc)],
            page_title_key=copy["page_title_key"],
            page_subtitle_key=copy["page_subtitle_key"],
            submit_label_key="reception_manager_save_draft" if is_manager_edit else "reception_resubmit_draft",
            back_href=url_for("reception.reception_entry_detail", entry_id=entry["id"]) if is_manager_edit else url_for("reception.index", view="desk"),
            status_code=400,
        )
    flash(T("reception_draft_updated" if is_manager_edit else "reception_draft_resubmitted"), "ok")
    return redirect(url_for("reception.reception_entry_detail", entry_id=entry_id) if is_manager_edit else url_for("reception.index", view="desk"))


@bp.route("/reception/entries/<entry_id>/hold", methods=["POST"])
@login_required
def hold_reception_entry(entry_id: str):
    if not _can_review():
        abort(403)
    entry = _find_entry_or_404(entry_id)
    hold_note = (request.form.get("hold_note") or "").strip()
    hold_entry(entry_id, actor_user_id=current_user.id, note=hold_note)
    flash(T("reception_draft_held"), "ok")
    return redirect(url_for("reception.reception_entry_detail", entry_id=entry_id))


@bp.route("/reception/entries/<entry_id>/return", methods=["POST"])
@login_required
def return_reception_entry(entry_id: str):
    if not _can_review():
        abort(403)
    entry = _find_entry_or_404(entry_id)
    reason = (request.form.get("return_reason") or "").strip()
    if not reason:
        return _render_detail(
            entry,
            action_errors=[T("reception_return_reason_required")],
            action_form={"hold_note": "", "return_reason": reason, "reject_reason": ""},
            status_code=400,
        )
    return_entry(entry_id, actor_user_id=current_user.id, reason=reason)
    flash(T("reception_draft_returned"), "ok")
    return redirect(url_for("reception.reception_entry_detail", entry_id=entry_id))


@bp.route("/reception/entries/<entry_id>/reject", methods=["POST"])
@login_required
def reject_reception_entry(entry_id: str):
    if not _can_review():
        abort(403)
    entry = _find_entry_or_404(entry_id)
    reason = (request.form.get("reject_reason") or "").strip()
    if not reason:
        return _render_detail(
            entry,
            action_errors=[T("reception_reject_reason_required")],
            action_form={"hold_note": "", "return_reason": "", "reject_reason": reason},
            status_code=400,
        )
    reject_entry(entry_id, actor_user_id=current_user.id, reason=reason)
    flash(T("reception_draft_rejected"), "ok")
    return redirect(url_for("reception.reception_entry_detail", entry_id=entry_id))


@bp.route("/reception/entries/<entry_id>/approve", methods=["POST"])
@login_required
def approve_reception_entry(entry_id: str):
    if not _can_approve():
        abort(403)
    entry = _find_entry_or_404(entry_id)
    approval_route = (request.form.get("approval_route") or "").strip().lower()
    target_patient_id = (request.form.get("target_patient_id") or "").strip()
    confirm_approve = (request.form.get("confirm_approve") or "").strip().lower()
    if confirm_approve not in {"1", "true", "yes", "on"}:
        return _render_detail(
            entry,
            action_errors=[T("reception_approve_confirmation_required")],
            action_form={
                "hold_note": "",
                "return_reason": "",
                "reject_reason": "",
                "confirm_approve": "",
                "approval_route": approval_route or "create_new",
                "target_patient_id": target_patient_id,
            },
            status_code=400,
        )
    try:
        if entry.get("draft_type") == "new_payment":
            approve_new_payment_entry(entry_id, actor_user_id=current_user.id)
            success_key = "reception_payment_draft_approved"
        elif entry.get("draft_type") == "edit_payment":
            approve_edit_payment_entry(entry_id, actor_user_id=current_user.id)
            success_key = "reception_payment_correction_draft_approved"
        elif entry.get("draft_type") == "edit_patient":
            approve_edit_patient_entry(entry_id, actor_user_id=current_user.id)
            success_key = "reception_patient_draft_approved"
        elif entry.get("draft_type") == "edit_treatment":
            approve_edit_treatment_entry(entry_id, actor_user_id=current_user.id)
            success_key = "reception_treatment_draft_approved"
        else:
            approve_new_treatment_entry(
                entry_id,
                actor_user_id=current_user.id,
                approval_route=approval_route or "create_new",
                target_patient_id=target_patient_id or None,
            )
            success_key = "reception_draft_approved"
    except ValueError as exc:
        refreshed_entry = _find_entry_or_404(entry_id)
        return _render_detail(
            refreshed_entry,
            action_errors=[str(exc)],
            action_form={
                "hold_note": "",
                "return_reason": "",
                "reject_reason": "",
                "confirm_approve": "1",
                "approval_route": approval_route or "create_new",
                "target_patient_id": target_patient_id,
            },
            status_code=400,
        )
    flash(T(success_key), "ok")
    return redirect(url_for("reception.reception_entry_detail", entry_id=entry_id))
