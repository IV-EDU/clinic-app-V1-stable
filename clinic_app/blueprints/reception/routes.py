from __future__ import annotations

from datetime import date

from flask import Blueprint, abort, flash, redirect, request, url_for
from flask_login import current_user, login_required

from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, get_active_doctor_options
from clinic_app.services.i18n import T
from clinic_app.services.payments import money_input, parse_money_to_cents
from clinic_app.services.reception_entries import (
    approve_new_payment_entry,
    approve_new_treatment_entry,
    create_entry,
    get_entry,
    get_locked_treatment_context,
    hold_entry,
    list_entries,
    list_entry_events,
    list_queue_entries,
    reject_entry,
    resubmit_returned_entry,
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


def _approval_confirmation_key(entry: dict) -> str:
    if entry.get("draft_type") == "new_payment":
        return "reception_payment_approve_confirmation_label"
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
    return (
        _can_create()
        and entry.get("submitted_by_user_id") == current_user.id
        and entry.get("draft_type") == "new_treatment"
        and entry.get("source") == "reception_desk"
        and entry.get("status") == "edited"
        and entry.get("last_action") == "returned"
    )


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
    payload = entry.get("payload_json") or {}
    if entry.get("draft_type") == "new_payment" and entry.get("locked_patient_id") and entry.get("locked_treatment_id"):
        locked_treatment_context = get_locked_treatment_context(
            entry["locked_patient_id"],
            entry["locked_treatment_id"],
        )
    return {
        "show_back": False,
        "entry": entry,
        "entry_events": events,
        "locked_treatment_context": locked_treatment_context,
        "entry_payload": payload if isinstance(payload, dict) else {},
        "can_review_reception": _can_review(),
        "can_approve_reception": _can_approve(),
        "can_create_reception": _can_create(),
        "action_errors": action_errors or [],
        "action_form": action_form or {"hold_note": "", "return_reason": "", "reject_reason": "", "confirm_approve": ""},
        "approval_confirmation_key": _approval_confirmation_key(entry),
    }


def _edit_context(
    entry: dict,
    *,
    form_data: dict[str, str] | None = None,
    errors: list[str] | None = None,
) -> dict:
    if not _can_edit_returned_entry(entry):
        abort(403)
    return {
        "show_back": False,
        "entry": entry,
        "doctor_options": _doctor_options(),
        "reception_form": form_data or _entry_form_data(entry),
        "reception_errors": errors or [],
        "return_reason": entry.get("return_reason") or "",
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
    status_code: int = 200,
):
    return (
        render_page(
            "reception/edit.html",
            **_edit_context(entry, form_data=form_data, errors=errors),
        ),
        status_code,
    )


def _render_new_payment(
    locked_context: dict,
    *,
    form_data: dict[str, str] | None = None,
    errors: list[str] | None = None,
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
    return render_page(
        "reception/new_payment.html",
        show_back=False,
        doctor_options=_doctor_options(),
        payment_form=_payment_form_data(context),
        payment_errors=[],
        locked_treatment=context,
    )


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


@bp.route("/reception/entries/<entry_id>/edit", methods=["GET"])
@login_required
def edit_reception_entry(entry_id: str):
    if not _can_create():
        abort(403)
    entry = _find_entry_or_404(entry_id)
    return render_page(
        "reception/edit.html",
        **_edit_context(entry),
    )


@bp.route("/reception/entries/<entry_id>/edit", methods=["POST"])
@login_required
def submit_reception_entry_edit(entry_id: str):
    if not _can_create():
        abort(403)
    entry = _find_entry_or_404(entry_id)
    form_data = _read_form_data()
    payload = _entry_payload_from_form_data(form_data)
    errors, _warnings, _normalized = validate_entry_payload(payload)
    if errors:
        return _render_edit(entry, form_data=form_data, errors=errors, status_code=400)
    try:
        resubmit_returned_entry(entry_id, payload, actor_user_id=current_user.id)
    except ValueError as exc:
        refreshed_entry = _find_entry_or_404(entry_id)
        return _render_edit(refreshed_entry, form_data=form_data, errors=[str(exc)], status_code=400)
    flash(T("reception_draft_resubmitted"), "ok")
    return redirect(url_for("reception.index", view="desk"))


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
    confirm_approve = (request.form.get("confirm_approve") or "").strip().lower()
    if confirm_approve not in {"1", "true", "yes", "on"}:
        return _render_detail(
            entry,
            action_errors=[T("reception_approve_confirmation_required")],
            action_form={"hold_note": "", "return_reason": "", "reject_reason": "", "confirm_approve": ""},
            status_code=400,
        )
    try:
        if entry.get("draft_type") == "new_payment":
            approve_new_payment_entry(entry_id, actor_user_id=current_user.id)
            success_key = "reception_payment_draft_approved"
        else:
            approve_new_treatment_entry(entry_id, actor_user_id=current_user.id)
            success_key = "reception_draft_approved"
    except ValueError as exc:
        refreshed_entry = _find_entry_or_404(entry_id)
        return _render_detail(
            refreshed_entry,
            action_errors=[str(exc)],
            action_form={"hold_note": "", "return_reason": "", "reject_reason": "", "confirm_approve": "1"},
            status_code=400,
        )
    flash(T(success_key), "ok")
    return redirect(url_for("reception.reception_entry_detail", entry_id=entry_id))
