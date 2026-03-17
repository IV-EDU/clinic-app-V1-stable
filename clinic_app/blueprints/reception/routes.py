from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, request, url_for
from flask_login import current_user, login_required

from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, get_active_doctor_options
from clinic_app.services.i18n import T
from clinic_app.services.reception_entries import (
    create_entry,
    get_entry,
    hold_entry,
    list_entries,
    list_entry_events,
    list_queue_entries,
    reject_entry,
    return_entry,
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


def _has_manager_visibility() -> bool:
    return current_user.is_authenticated and (
        current_user.has_permission("reception_entries:review")
        or current_user.has_permission("reception_entries:approve")
    )


def _can_review() -> bool:
    return _has_manager_visibility()


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


def _find_entry_or_404(entry_id: str) -> dict:
    entry = get_entry(entry_id)
    if not entry:
        abort(404)
    return _decorate_entry(entry)


def _can_access_entry(entry: dict) -> bool:
    if _can_review():
        return True
    return _can_create() and entry.get("submitted_by_user_id") == current_user.id


def _detail_context(
    entry: dict,
    *,
    action_errors: list[str] | None = None,
    action_form: dict[str, str] | None = None,
) -> dict:
    if not _can_access_entry(entry):
        abort(403)
    events = list_entry_events(entry["id"])
    return {
        "show_back": False,
        "entry": entry,
        "entry_events": events,
        "can_review_reception": _can_review(),
        "can_create_reception": _can_create(),
        "action_errors": action_errors or [],
        "action_form": action_form or {"hold_note": "", "return_reason": "", "reject_reason": ""},
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


@bp.route("/reception", methods=["GET"])
@login_required
def index():
    if not _can_access_reception():
        abort(403)

    view = (request.args.get("view") or "").strip().lower()
    if view == "queue":
        context = _build_queue_context()
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
        return redirect(url_for("reception.index", view="desk"))

    return (
        render_page(
            "reception/index.html",
            **_build_desk_context(form_data=form_data, errors=errors),
        ),
        200,
    )


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
