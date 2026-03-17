from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, request, url_for
from flask_login import current_user, login_required

from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, get_active_doctor_options
from clinic_app.services.i18n import T
from clinic_app.services.reception_entries import create_entry, list_entries, validate_entry_payload
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


def _has_manager_visibility() -> bool:
    return current_user.is_authenticated and (
        current_user.has_permission("reception_entries:review")
        or current_user.has_permission("reception_entries:approve")
    )


def _doctor_options() -> list[dict[str, str]]:
    return get_active_doctor_options(include_any=True)


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


def _recent_entries_for_current_user(limit: int = 20) -> list[dict]:
    entries = list_entries(submitted_by_user_id=current_user.id, limit=limit)
    for entry in entries:
        entry["status_label"] = T(_status_label_key(entry))
        payload = entry.get("payload_json") or {}
        entry["note"] = (payload.get("note") if isinstance(payload, dict) else "") or ""
    return entries


@bp.route("/reception", methods=["GET"])
@login_required
def index():
    if not _can_access_reception():
        abort(403)

    can_create = _can_create()
    can_review = _has_manager_visibility()
    form_data = _default_form_data()
    entries = _recent_entries_for_current_user() if can_create else []
    summary = _build_summary(entries) if can_create else {"open_drafts": 0, "returned": 0, "waiting_review": 0}

    return render_page(
        "reception/index.html",
        show_back=False,
        can_create_reception=can_create,
        can_review_reception=can_review,
        doctor_options=_doctor_options(),
        reception_form=form_data,
        reception_errors=[],
        reception_entries=entries,
        reception_summary=summary,
    )


@bp.route("/reception/entries", methods=["POST"])
@login_required
def create_reception_entry():
    if not _can_create():
        abort(403)

    form_data = {
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
    payload = {
        "draft_type": "new_treatment",
        "source": "reception_desk",
        "patient_intent": "unknown",
        **form_data,
        "doctor_label": next(
            (
                doctor["doctor_label"]
                for doctor in _doctor_options()
                if doctor["doctor_id"] == form_data["doctor_id"]
            ),
            "",
        ),
        "payload_json": {"note": form_data["note"]} if form_data["note"] else {},
    }

    errors, _warnings, _normalized = validate_entry_payload(payload)
    if not errors:
        create_entry(payload, actor_user_id=current_user.id)
        flash(T("reception_draft_saved"), "ok")
        return redirect(url_for("reception.index"))

    entries = _recent_entries_for_current_user()
    summary = _build_summary(entries)
    return render_page(
        "reception/index.html",
        show_back=False,
        can_create_reception=True,
        can_review_reception=_has_manager_visibility(),
        doctor_options=_doctor_options(),
        reception_form=form_data,
        reception_errors=errors,
        reception_entries=entries,
        reception_summary=summary,
    ), 200
