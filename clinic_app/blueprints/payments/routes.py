from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime
from pathlib import Path

from flask import Blueprint, flash, redirect, request, send_file, url_for, current_app, g, render_template

from clinic_app.services.database import db
from clinic_app.services.audit import write_event
from clinic_app.services.i18n import T, get_lang, translate_text
from clinic_app.services.patients import migrate_patients_drop_unique_short_id
from clinic_app.services.payments import (
    cents_guard,
    money,
    money_input,
    parse_money_to_cents,
    validate_payment_fields,
    add_payment_to_treatment,
)
from clinic_app.services.pdf_enhanced import generate_payment_receipt_pdf
from clinic_app.services.doctor_colors import (
    ANY_DOCTOR_ID,
    ANY_DOCTOR_LABEL,
    DEFAULT_COLOR,
    get_active_doctor_options,
)
from clinic_app.services.ui import render_page
from clinic_app.services.security import require_permission
from clinic_app.services.errors import record_exception

bp = Blueprint("payments", __name__)


def _doctor_options() -> list[dict[str, str]]:
    options = get_active_doctor_options(include_any=True)
    if not options:
        options = [
            {
                "doctor_id": ANY_DOCTOR_ID,
                "doctor_label": ANY_DOCTOR_LABEL,
                "color": DEFAULT_COLOR,
            }
        ]
    return options


@bp.route("/", methods=["GET"])
@require_permission("payments:view")
def index():
    """Redirect to patients list (payments are accessed through patients)."""
    return redirect(url_for("index"))


def get_payment_and_patient(pay_id: str):
    conn = db()
    cur = conn.cursor()
    pay = cur.execute("SELECT * FROM payments WHERE id=?", (pay_id,)).fetchone()
    p = cur.execute("SELECT * FROM patients WHERE id=?", (pay["patient_id"],)).fetchone() if pay else None
    return conn, cur, p, pay


def _receipt_context(pid: str, pay_id: str):
    """Load payment + patient data and shape values for receipt views."""
    conn, cur, p, pay = get_payment_and_patient(pay_id)
    if not pay or not p or p["id"] != pid:
        conn.close()
        return None

    payment = dict(pay)
    patient = dict(p)
    paid_cents = int(payment.get("amount_cents") or 0)
    parent_payment_id = (payment.get("parent_payment_id") or "").strip()

    treatment_payment = payment
    treatment_id = pay_id
    if parent_payment_id:
        parent = cur.execute(
            """
            SELECT * FROM payments
             WHERE id=?
               AND patient_id=?
               AND (parent_payment_id IS NULL OR parent_payment_id = '')
            """,
            (parent_payment_id, pid),
        ).fetchone()
        if parent:
            treatment_payment = dict(parent)
            treatment_id = parent_payment_id

    total_cents = int(treatment_payment.get("total_amount_cents") or 0)
    discount_cents = int(treatment_payment.get("discount_cents") or 0)
    initial_cents = int(treatment_payment.get("amount_cents") or 0)
    child_sum_row = cur.execute(
        """
        SELECT COALESCE(SUM(amount_cents),0) AS child_paid
          FROM payments
         WHERE parent_payment_id=?
           AND patient_id=?
        """,
        (treatment_id, pid),
    ).fetchone()
    child_paid_cents = int((child_sum_row["child_paid"] or 0) if child_sum_row else 0)
    paid_so_far_cents = initial_cents + child_paid_cents
    due_cents = max(total_cents - discount_cents, 0)
    remaining_cents = max(due_cents - paid_so_far_cents, 0)
    currency = current_app.config.get("CURRENCY_LABEL", "EGP")

    def fmt(cents: int) -> str:
        base = money(cents)
        return f"{base} {currency}" if currency else base

    clinic = {
        "name": current_app.config.get("CLINIC_NAME") or "",
        "address": current_app.config.get("CLINIC_ADDRESS", ""),
        "phone": current_app.config.get("CLINIC_PHONE", ""),
    }

    treatment_name = (payment.get("treatment") or "").strip() or (
        treatment_payment.get("treatment") or ""
    )

    receipt = {
        "number": (pay_id or "")[-8:].upper(),
        "date": payment.get("paid_at") or date.today().isoformat(),
        "method": payment.get("method") or "",
        "doctor": payment.get("doctor_label") or ANY_DOCTOR_LABEL,
        "treatment": treatment_name,
        "notes": payment.get("note") or "",
        "total": fmt(total_cents),
        "discount": fmt(discount_cents),
        "paid": fmt(paid_cents),
        "remaining": fmt(remaining_cents),
        "paid_so_far": fmt(paid_so_far_cents),
        "is_child_payment": bool(parent_payment_id),
        "treatment_id": treatment_id,
    }

    snapshot = {
        "total": fmt(total_cents),
        "discount": fmt(discount_cents),
        "paid_so_far": fmt(paid_so_far_cents),
        "remaining": fmt(remaining_cents),
    }

    conn.close()
    return {
        "patient": {
            "id": pid,
            "name": patient.get("full_name") or "",
            "file_no": patient.get("short_id") or "",
            "phone": patient.get("phone") or "",
        },
        "clinic": clinic,
        "receipt": receipt,
        "snapshot": snapshot,
        "payment_id": pay_id,
        "raw_payment": payment,
        "raw_treatment": treatment_payment,
        "raw_patient": patient,
        "lang": get_lang(),
    }


def _bool_param(name: str, default: bool) -> bool:
    raw = request.args.get(name)
    if raw is None:
        return default
    return str(raw).lower() == "true"


def _lang_param(fallback: str) -> str:
    raw = (request.args.get("lang") or "").lower()
    if raw in ("en", "ar"):
        return raw
    return fallback


def _requested_lang_dir() -> tuple[str, str]:
    lang = (request.args.get("lang") or "").strip().lower()
    if lang not in {"en", "ar"}:
        lang = get_lang()
    return lang, ("rtl" if lang == "ar" else "ltr")


def _translator(lang: str):
    def tx(key: str, **fmt):
        return translate_text(lang, key, **fmt)

    return tx


def _receipt_scope() -> str:
    scope = (request.args.get("scope") or "payment_only").strip().lower()
    if scope not in {"payment_only", "payment_snapshot"}:
        scope = "payment_only"
    return scope


def _is_modal_request() -> bool:
    return (request.headers.get("X-Modal") or "").strip().lower() in {"1", "true", "yes"}


def _visit_type_flags(raw_value: str) -> tuple[int, int]:
    value = (raw_value or "none").strip().lower()
    if value not in {"none", "exam", "followup"}:
        value = "none"
    return (1 if value == "exam" else 0, 1 if value == "followup" else 0)


def _treatment_form_values(treatment) -> dict:
    treatment_label = (treatment["treatment"] or "").strip()
    is_consultation_visit = treatment_label in {T("consultation_visit_name"), "Consultation visit", "زيارة استشارة"}
    vt = (
        "none"
        if is_consultation_visit
        else (
            "exam"
            if (treatment["examination_flag"] or 0) == 1
            else ("followup" if (treatment["followup_flag"] or 0) == 1 else "none")
        )
    )
    return {
        "visit_type": vt,
        "is_consultation_visit": "1" if is_consultation_visit else "",
        "total_amount": money_input(treatment["total_amount_cents"] or 0),
        "discount": money_input(treatment["discount_cents"] or 0),
        "down_payment": money_input(treatment["amount_cents"] or 0),
        "treatment_type": treatment["treatment"] or "",
        "notes": treatment["note"] or "",
        "paid_at": treatment["paid_at"] or date.today().isoformat(),
        "method": treatment["method"] or "cash",
        "doctor_id": treatment["doctor_id"] or "",
    }


def _render_treatment_form_modal(*, p, form, doctor_options, doctor_error, action):
    return render_template(
        "payments/treatment_form_modal_fragment.html",
        p=p,
        today=date.today().isoformat(),
        form=form,
        doctor_options=doctor_options,
        doctor_error=doctor_error,
        action=action,
        submit_label=T("update"),
    )


def _render_child_payment_form_modal(*, p, form, doctor_options, doctor_error, action):
    return render_template(
        "payments/edit_payment_modal_fragment.html",
        p=p,
        today=date.today().isoformat(),
        form=form,
        doctor_options=doctor_options,
        doctor_error=doctor_error,
        action=action,
    )


@bp.route("/patients/<pid>/payments/<pay_id>/edit", methods=["GET"])
@require_permission("payments:edit")
def edit_payment_get(pid, pay_id):
    conn, cur, p, pay = get_payment_and_patient(pay_id)
    if not pay or not p or p["id"] != pid:
        conn.close()
        return "Payment not found", 404
    pay_dict = dict(pay)
    base_total_cents = pay["total_amount_cents"] or 0
    vt = (
        "exam"
        if (pay["examination_flag"] or 0) == 1
        else ("followup" if (pay["followup_flag"] or 0) == 1 else "none")
    )
    doctor_options = _doctor_options()
    form = {
        "visit_type": vt,
        "total_amount": money_input(max(base_total_cents, 0)),
        "discount": money_input(pay["discount_cents"] or 0),
        "down_payment": money_input(pay["amount_cents"] or 0),
        "remaining_amount": money_input(
            max(((pay["total_amount_cents"] or 0) - (pay["discount_cents"] or 0) - (pay["amount_cents"] or 0)), 0)
        ),
        "treatment_type": pay["treatment"] or "",
        "notes": pay["note"] or "",
        "paid_at": pay["paid_at"],
        "method": pay["method"] or "cash",
        "doctor_id": pay_dict.get("doctor_id") or ANY_DOCTOR_ID,
    }
    html = render_page(
        "payments/form.html",
        p=p,
        today=date.today().isoformat(),
        form=form,
        doctor_options=doctor_options,
        doctor_error=None,
        action=url_for("payments.edit_payment_post", pid=p["id"], pay_id=pay_id),
        submit_label=T("update"),
        show_back=True,
        show_id_header=True,
    )
    conn.close()
    return html


@bp.route("/patients/<pid>/payments/<pay_id>/edit", methods=["POST"])
@require_permission("payments:edit")
def edit_payment_post(pid, pay_id):
    doctor_options = _doctor_options()
    doctor_lookup = {opt["doctor_id"]: opt for opt in doctor_options}
    doctor_id_raw = (request.form.get("doctor_id") or "").strip()

    doctor_error = None
    if not doctor_id_raw:
        doctor_error = T("doctor_required")

    # Safety fallback for internal logic
    if not doctor_id_raw or doctor_id_raw not in doctor_lookup:
        doctor_id_raw = ANY_DOCTOR_ID
    is_modal = _is_modal_request()

    conn, cur, p, pay = get_payment_and_patient(pay_id)
    if not pay or not p or p["id"] != pid:
        conn.close()
        return "Payment not found", 404

    parent_payment_id = (pay["parent_payment_id"] or "").strip()
    is_treatment_parent = parent_payment_id == ""

    form_values = {
        "amount": request.form.get("amount", money_input(pay["amount_cents"] or 0)),
        "paid_at": request.form.get("paid_at", pay["paid_at"] or date.today().isoformat()),
        "method": request.form.get("method", pay["method"] or "cash"),
        "note": request.form.get("note", pay["note"] or ""),
        "doctor_id": request.form.get("doctor_id", pay["doctor_id"] or ANY_DOCTOR_ID),
    }

    if doctor_error:
        if is_modal:
            html = _render_child_payment_form_modal(
                p=p,
                form=form_values,
                doctor_options=doctor_options,
                doctor_error=doctor_error,
                action=url_for("payments.edit_payment_post", pid=pid, pay_id=pay_id),
            )
            conn.close()
            return html, 422
        conn.close()
        flash(T("doctor_required"), "err")
        return redirect(url_for("patients.patient_detail", pid=pid))

    amount_cents_raw = parse_money_to_cents(request.form.get("amount") or "")
    if amount_cents_raw < 0:
        if is_modal:
            html = _render_child_payment_form_modal(
                p=p,
                form=form_values,
                doctor_options=doctor_options,
                doctor_error=None,
                action=url_for("payments.edit_payment_post", pid=pid, pay_id=pay_id),
            )
            conn.close()
            return html, 422
        conn.close()
        flash(T("err_money_too_large"), "err")
        return redirect(url_for("patients.patient_detail", pid=pid))

    try:
        amount_cents = cents_guard(amount_cents_raw, "Paid Today")
    except ValueError:
        if is_modal:
            html = _render_child_payment_form_modal(
                p=p,
                form=form_values,
                doctor_options=doctor_options,
                doctor_error=None,
                action=url_for("payments.edit_payment_post", pid=pid, pay_id=pay_id),
            )
            conn.close()
            return html, 422
        conn.close()
        flash(T("err_money_too_large"), "err")
        return redirect(url_for("patients.patient_detail", pid=pid))

    paid_at = (request.form.get("paid_at") or date.today().isoformat())
    method = (request.form.get("method") or "cash").strip()
    note = (request.form.get("note") or "").strip()
    doctor_label = doctor_lookup.get(doctor_id_raw, {"doctor_label": ANY_DOCTOR_LABEL}).get("doctor_label") or ANY_DOCTOR_LABEL

    cur.execute(
        """
        UPDATE payments
           SET paid_at=?, amount_cents=?, method=?, note=?, doctor_id=?, doctor_label=?
         WHERE id=?
        """,
        (paid_at, amount_cents, method, note, doctor_id_raw, doctor_label, pay_id),
    )

    # Recompute remaining for the treatment parent (either this row, or its parent).
    treatment_id = pay_id if is_treatment_parent else parent_payment_id
    parent_row = cur.execute(
        "SELECT total_amount_cents, discount_cents, amount_cents FROM payments WHERE id=? AND patient_id=?",
        (treatment_id, pid),
    ).fetchone()
    child_sum_row = cur.execute(
        "SELECT COALESCE(SUM(amount_cents),0) AS child_paid FROM payments WHERE parent_payment_id=? AND patient_id=?",
        (treatment_id, pid),
    ).fetchone()
    if parent_row:
        total_cents = int(parent_row["total_amount_cents"] or 0)
        discount_cents = int(parent_row["discount_cents"] or 0)
        initial_cents = int(parent_row["amount_cents"] or 0)
        child_paid_cents = int((child_sum_row["child_paid"] or 0) if child_sum_row else 0)
        due_cents = max(total_cents - discount_cents, 0)
        remaining_cents = max(due_cents - (initial_cents + child_paid_cents), 0)
        cur.execute("UPDATE payments SET remaining_cents=? WHERE id=?", (remaining_cents, treatment_id))

    conn.commit()

    try:
        actor = getattr(g, "current_user", None)
        actor_id = getattr(actor, "id", None)
        write_event(
            actor_id,
            "payment_update",
            entity="payment",
            entity_id=pay_id,
            meta={
                "patient_id": pid,
                "paid_at": paid_at,
                "amount_cents": amount_cents,
                "method": method,
                "doctor_id": doctor_id_raw,
                "doctor_label": doctor_label,
                "remaining_cents": remaining_cents,
                "prev_paid_at": pay["paid_at"],
                "prev_amount_cents": pay["amount_cents"],
                "prev_method": pay["method"],
                "prev_doctor_id": pay["doctor_id"],
                "prev_doctor_label": pay["doctor_label"],
            },
        )
    except Exception:
        pass

    migrate_patients_drop_unique_short_id(conn)
    conn.close()
    if is_modal:
        return "", 204
    flash(T("updated_payment_ok"), "ok")
    return redirect(url_for("patients.patient_detail", pid=pid))


@bp.route("/patients/<pid>/payments/<pay_id>/edit-modal", methods=["GET"])
@require_permission("payments:edit")
def edit_payment_modal(pid, pay_id):
    conn, cur, p, pay = get_payment_and_patient(pay_id)
    if not pay or not p or p["id"] != pid:
        conn.close()
        return "Payment not found", 404
    doctor_options = _doctor_options()
    form = {
        "amount": money_input(pay["amount_cents"] or 0),
        "note": pay["note"] or "",
        "paid_at": pay["paid_at"] or date.today().isoformat(),
        "method": pay["method"] or "cash",
        # Older clinic DBs may have empty doctor_id; treat that as Any Doctor.
        "doctor_id": (pay["doctor_id"] or ANY_DOCTOR_ID),
    }
    html = _render_child_payment_form_modal(
        p=p,
        form=form,
        doctor_options=doctor_options,
        doctor_error=None,
        action=url_for("payments.edit_payment_post", pid=p["id"], pay_id=pay_id),
    )
    conn.close()
    return html


@bp.route("/patients/<pid>/treatments/new", methods=["POST"])
@require_permission("payments:edit")
def create_treatment(pid: str):
    doctor_options = _doctor_options()
    doctor_lookup = {opt["doctor_id"]: opt for opt in doctor_options}
    doctor_id_raw = (request.form.get("doctor_id") or "").strip()
    # Safety default: never store a blank doctor. If missing/invalid, use Any Doctor.
    if not doctor_id_raw or doctor_id_raw not in doctor_lookup:
        doctor_id_raw = ANY_DOCTOR_ID

    is_consultation_visit = str(request.form.get("is_consultation_visit") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    exam, follow = _visit_type_flags(request.form.get("visit_type") or "none")
    if is_consultation_visit:
        exam, follow = 0, 0
        total_cents = 0
        discount_cents = 0
        down_cents = 0
        due_cents = 0
        rem_cents = 0
        treatment_name = T("consultation_visit_name")
    else:
        total_cents_raw = parse_money_to_cents(request.form.get("total_amount") or "")
        discount_cents_raw = parse_money_to_cents(request.form.get("discount") or "")
        down_cents_raw = parse_money_to_cents(request.form.get("down_payment") or "")

        ok, info = validate_payment_fields(
            total_cents_raw, discount_cents_raw, down_cents_raw, bool(exam)
        )
        if not ok:
            flash(T(info), "err")
            return redirect(url_for("patients.patient_detail", pid=pid))

        try:
            total_cents = cents_guard(total_cents_raw, "Total")
            discount_cents = cents_guard(discount_cents_raw, "Discount")
            down_cents = cents_guard(down_cents_raw, "Paid Today")
        except ValueError:
            flash(T("err_money_too_large"), "err")
            return redirect(url_for("patients.patient_detail", pid=pid))

        due_cents = max(total_cents - discount_cents, 0)
        rem_cents = max(due_cents - down_cents, 0)
        treatment_name = (request.form.get("treatment_type") or "").strip()

    notes = (request.form.get("notes") or "").strip()
    paid_at = (request.form.get("paid_at") or date.today().isoformat())
    method = (request.form.get("method") or "cash").strip()
    doctor_label = doctor_lookup.get(doctor_id_raw, {"doctor_label": ANY_DOCTOR_LABEL}).get("doctor_label") or ANY_DOCTOR_LABEL

    conn = db()
    try:
        patient = conn.execute("SELECT id FROM patients WHERE id=?", (pid,)).fetchone()
        if not patient:
            return "Patient not found", 404

        treatment_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO payments(
                id, patient_id, parent_payment_id, paid_at, amount_cents, method, note, treatment,
                doctor_id, doctor_label,
                remaining_cents, total_amount_cents, examination_flag, followup_flag, discount_cents
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                treatment_id,
                pid,
                None,
                paid_at,
                down_cents,
                method,
                notes,
                treatment_name,
                doctor_id_raw,
                doctor_label,
                rem_cents,
                total_cents,
                exam,
                follow,
                discount_cents,
            ),
        )
        conn.commit()

        try:
            actor = getattr(g, "current_user", None)
            actor_id = getattr(actor, "id", None)
            write_event(
                actor_id,
                "treatment_create",
                entity="payment",
                entity_id=treatment_id,
                meta={
                    "patient_id": pid,
                    "paid_at": paid_at,
                    "amount_cents": down_cents,
                    "method": method,
                    "doctor_id": doctor_id_raw,
                    "doctor_label": doctor_label,
                    "remaining_cents": rem_cents,
                    "total_amount_cents": total_cents,
                    "discount_cents": discount_cents,
                    "treatment_type": treatment_name,
                    "visit_type": "exam" if exam else ("followup" if follow else "none"),
                },
            )
        except Exception:
            pass


    finally:
        migrate_patients_drop_unique_short_id(conn)
        conn.close()

    flash(T("payment_recorded"), "ok")
    return redirect(url_for("patients.patient_detail", pid=pid))


@bp.route("/patients/<pid>/treatments/<treatment_id>/edit-modal", methods=["GET"])
@require_permission("payments:edit")
def edit_treatment_modal(pid: str, treatment_id: str):
    conn = db()
    try:
        p = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
        treatment = conn.execute(
            """
            SELECT * FROM payments
             WHERE id=? AND patient_id=?
               AND (parent_payment_id IS NULL OR parent_payment_id = '')
            """,
            (treatment_id, pid),
        ).fetchone()
        if not p or not treatment:
            return "Treatment not found", 404
        form = _treatment_form_values(treatment)
        return _render_treatment_form_modal(
            p=p,
            form=form,
            doctor_options=_doctor_options(),
            doctor_error=None,
            action=url_for("payments.edit_treatment_post", pid=pid, treatment_id=treatment_id),
        )
    finally:
        conn.close()


@bp.route("/patients/<pid>/treatments/<treatment_id>/edit", methods=["POST"])
@require_permission("payments:edit")
def edit_treatment_post(pid: str, treatment_id: str):
    doctor_options = _doctor_options()
    doctor_lookup = {opt["doctor_id"]: opt for opt in doctor_options}
    doctor_id_raw = (request.form.get("doctor_id") or "").strip()
    # Safety default: never store a blank doctor. If missing/invalid, use Any Doctor.
    if not doctor_id_raw or doctor_id_raw not in doctor_lookup:
        doctor_id_raw = ANY_DOCTOR_ID
    doctor_error = None
    is_modal = _is_modal_request()

    conn = db()
    try:
        p = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
        treatment = conn.execute(
            """
            SELECT * FROM payments
             WHERE id=? AND patient_id=?
               AND (parent_payment_id IS NULL OR parent_payment_id = '')
            """,
            (treatment_id, pid),
        ).fetchone()
        if not p or not treatment:
            return "Treatment not found", 404

        form_values = dict(request.form)
        if doctor_error:
            if is_modal:
                return _render_treatment_form_modal(
                    p=p,
                    form=form_values,
                    doctor_options=doctor_options,
                    doctor_error=doctor_error,
                    action=url_for("payments.edit_treatment_post", pid=pid, treatment_id=treatment_id),
                ), 422
            flash(T("doctor_required"), "err")
            return redirect(url_for("patients.patient_detail", pid=pid))

        is_consultation_visit = str(request.form.get("is_consultation_visit") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        exam, follow = _visit_type_flags(request.form.get("visit_type") or "none")
        if is_consultation_visit:
            exam, follow = 0, 0
            total_cents = 0
            discount_cents = 0
            down_cents = int(treatment["amount_cents"] or 0)
        else:
            total_cents_raw = parse_money_to_cents(request.form.get("total_amount") or "")
            discount_cents_raw = parse_money_to_cents(request.form.get("discount") or "")
            if discount_cents_raw < 0:
                discount_cents_raw = 0
            if discount_cents_raw > total_cents_raw:
                if is_modal:
                    return _render_treatment_form_modal(
                        p=p,
                        form=form_values,
                        doctor_options=doctor_options,
                        doctor_error=None,
                        action=url_for(
                            "payments.edit_treatment_post", pid=pid, treatment_id=treatment_id
                        ),
                    ), 422
                flash(T("err_discount_gt_total"), "err")
                return redirect(url_for("patients.patient_detail", pid=pid))

            try:
                total_cents = cents_guard(total_cents_raw, "Total")
                discount_cents = cents_guard(discount_cents_raw, "Discount")
            except ValueError:
                if is_modal:
                    return _render_treatment_form_modal(
                        p=p,
                        form=form_values,
                        doctor_options=doctor_options,
                        doctor_error=None,
                        action=url_for(
                            "payments.edit_treatment_post", pid=pid, treatment_id=treatment_id
                        ),
                    ), 422
                flash(T("err_money_too_large"), "err")
                return redirect(url_for("patients.patient_detail", pid=pid))
            down_cents = int(treatment["amount_cents"] or 0)

        child_row = conn.execute(
            """
            SELECT COALESCE(SUM(amount_cents),0) AS child_paid
              FROM payments
             WHERE parent_payment_id=?
               AND patient_id=?
            """,
            (treatment_id, pid),
        ).fetchone()
        child_paid = int((child_row["child_paid"] or 0) if child_row else 0)
        due_cents = max(total_cents - discount_cents, 0)
        remaining_cents = max(due_cents - (down_cents + child_paid), 0)

        if is_consultation_visit:
            treatment_name = T("consultation_visit_name")
        else:
            treatment_name = (request.form.get("treatment_type") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        paid_at = (request.form.get("paid_at") or date.today().isoformat())
        method = (request.form.get("method") or "cash").strip()
        doctor_label = doctor_lookup.get(doctor_id_raw, {"doctor_label": ANY_DOCTOR_LABEL}).get("doctor_label") or ANY_DOCTOR_LABEL

        conn.execute(
            """
            UPDATE payments
               SET paid_at=?, method=?, note=?, treatment=?,
                   doctor_id=?, doctor_label=?,
                   remaining_cents=?, total_amount_cents=?, examination_flag=?, followup_flag=?, discount_cents=?
             WHERE id=?
            """,
            (
                paid_at,
                method,
                notes,
                treatment_name,
                doctor_id_raw,
                doctor_label,
                remaining_cents,
                total_cents,
                exam,
                follow,
                discount_cents,
                treatment_id,
            ),
        )
        conn.commit()

        try:
            actor = getattr(g, "current_user", None)
            actor_id = getattr(actor, "id", None)
            write_event(
                actor_id,
                "treatment_update",
                entity="payment",
                entity_id=treatment_id,
                meta={
                    "patient_id": pid,
                    "paid_at": paid_at,
                    "amount_cents": down_cents,
                    "method": method,
                    "doctor_id": doctor_id_raw,
                    "doctor_label": doctor_label,
                    "remaining_cents": remaining_cents,
                    "total_amount_cents": total_cents,
                    "discount_cents": discount_cents,
                    "treatment_type": treatment_name,
                    "visit_type": "exam" if exam else ("followup" if follow else "none"),
                    "prev_paid_at": treatment["paid_at"],
                    "prev_amount_cents": treatment["amount_cents"],
                    "prev_method": treatment["method"],
                    "prev_doctor_id": treatment["doctor_id"],
                    "prev_doctor_label": treatment["doctor_label"],
                },
            )
        except Exception:
            pass

    finally:
        migrate_patients_drop_unique_short_id(conn)
        conn.close()

    if is_modal:
        return "", 204
    flash(T("updated_payment_ok"), "ok")
    return redirect(url_for("patients.patient_detail", pid=pid))


@bp.route("/patients/<pid>/payments/<pay_id>/delete", methods=["GET"])
@require_permission("payments:delete")
def delete_payment_confirm(pid, pay_id):
    conn, cur, p, pay = get_payment_and_patient(pay_id)
    if not pay or not p or p["id"] != pid:
        conn.close()
        return "Payment not found", 404
    html = render_page(
        "payments/delete_confirm.html",
        p=p,
        pay=pay,
        pay_amount=money(pay["amount_cents"] or 0),
        show_back=True,
    )
    conn.close()
    return html


@bp.route("/patients/<pid>/payments/<pay_id>/delete", methods=["POST"])
@require_permission("payments:delete")
def delete_payment(pid, pay_id):
    conn, cur, p, pay = get_payment_and_patient(pay_id)
    if not pay or not p or p["id"] != pid:
        conn.close()
        return "Payment not found", 404
    snap = dict(pay)
    # If this payment is a treatment (parent row), delete its child payments too.
    try:
        parent_payment_id = (pay["parent_payment_id"] or "").strip()
    except Exception:
        parent_payment_id = ""

    is_treatment_parent = parent_payment_id == ""
    if is_treatment_parent:
        cur.execute("DELETE FROM payments WHERE parent_payment_id=? AND patient_id=?", (pay_id, pid))

    cur.execute("DELETE FROM payments WHERE id=?", (pay_id,))
    conn.commit()
    try:
        actor = getattr(g, "current_user", None)
        actor_id = getattr(actor, "id", None)
        write_event(
            actor_id,
            "payment_delete",
            entity="payment",
            entity_id=pay_id,
            meta={
                "patient_id": pid,
                "paid_at": snap.get("paid_at") or "",
                "amount_cents": snap.get("amount_cents") or 0,
                "method": snap.get("method") or "",
                "doctor_id": snap.get("doctor_id") or "",
                "doctor_label": snap.get("doctor_label") or "",
                "remaining_cents": snap.get("remaining_cents") or 0,
                "total_amount_cents": snap.get("total_amount_cents") or 0,
                "discount_cents": snap.get("discount_cents") or 0,
                "visit_type": (
                    "exam"
                    if (snap.get("examination_flag") or 0) == 1
                    else ("followup" if (snap.get("followup_flag") or 0) == 1 else "none")
                ),
            },
        )
    except Exception:
        pass
    migrate_patients_drop_unique_short_id(conn)
    conn.close()
    flash(T("deleted_payment_ok"), "ok")
    return redirect(url_for("patients.patient_detail", pid=pid))


@bp.route("/patients/<pid>/treatments/<treatment_id>/initial/delete", methods=["POST"])
@require_permission("payments:delete")
def remove_initial_payment(pid, treatment_id):
    conn = db()
    cur = conn.cursor()
    try:
        treatment = cur.execute(
            """
            SELECT *
              FROM payments
             WHERE id=?
               AND patient_id=?
               AND (parent_payment_id IS NULL OR parent_payment_id = '')
            """,
            (treatment_id, pid),
        ).fetchone()
        if not treatment:
            return "Treatment not found", 404

        child_paid_row = cur.execute(
            """
            SELECT COALESCE(SUM(amount_cents), 0) AS child_paid_cents
              FROM payments
             WHERE parent_payment_id=?
               AND patient_id=?
            """,
            (treatment_id, pid),
        ).fetchone()
        child_paid_cents = int((child_paid_row["child_paid_cents"] or 0) if child_paid_row else 0)

        total_cents = int(treatment["total_amount_cents"] or 0)
        discount_cents = int(treatment["discount_cents"] or 0)
        due_cents = max(total_cents - discount_cents, 0)
        remaining_cents = max(due_cents - child_paid_cents, 0)

        cur.execute(
            "UPDATE payments SET amount_cents=?, remaining_cents=? WHERE id=?",
            (0, remaining_cents, treatment_id),
        )
        conn.commit()

        try:
            actor = getattr(g, "current_user", None)
            actor_id = getattr(actor, "id", None)
            write_event(
                actor_id,
                "payment_initial_remove",
                entity="payment",
                entity_id=treatment_id,
                meta={
                    "patient_id": pid,
                    "remaining_cents": remaining_cents,
                    "child_paid_cents": child_paid_cents,
                },
            )
        except Exception:
            pass

        migrate_patients_drop_unique_short_id(conn)
        flash(T("removed_initial_payment_ok"), "ok")
        return redirect(url_for("patients.patient_detail", pid=pid))
    finally:
        conn.close()


@bp.route("/patients/<pid>/treatments/<treatment_id>/summary", methods=["GET"])
@require_permission("payments:view")
def treatment_summary_print(pid: str, treatment_id: str):
    """Printable treatment summary (parent payment + its child payments)."""
    conn = db()
    try:
        patient = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
        if not patient:
            return "Patient not found", 404

        treatment = conn.execute(
            """
            SELECT *
              FROM payments
             WHERE id=?
               AND patient_id=?
               AND (parent_payment_id IS NULL OR parent_payment_id = '')
            """,
            (treatment_id, pid),
        ).fetchone()
        if not treatment:
            return "Treatment not found", 404

        child_rows = conn.execute(
            """
            SELECT *
              FROM payments
             WHERE parent_payment_id=?
             ORDER BY paid_at DESC, created_at DESC
            """,
            (treatment_id,),
        ).fetchall()

        total_cents = int(treatment["total_amount_cents"] or 0)
        discount_cents = int(treatment["discount_cents"] or 0)
        parent_paid_cents = int(treatment["amount_cents"] or 0)
        child_paid_cents = sum(int(r["amount_cents"] or 0) for r in child_rows)
        paid_cents = parent_paid_cents + child_paid_cents
        due_cents = max(total_cents - discount_cents, 0)
        remaining_cents = max(due_cents - paid_cents, 0)

        payments = []
        if parent_paid_cents > 0:
            payments.append(
                {
                    "paid_at": treatment["paid_at"],
                    "amount_fmt": money(parent_paid_cents),
                    "method": treatment["method"] or "",
                    "note": treatment["note"] or "",
                    "is_initial": True,
                }
            )
        for r in child_rows:
            payments.append(
                {
                    "paid_at": r["paid_at"],
                    "amount_fmt": money(r["amount_cents"] or 0),
                    "method": r["method"] or "",
                    "note": r["note"] or "",
                    "is_initial": False,
                }
            )

        return render_template(
            "payments/treatment_summary_print.html",
            patient=dict(patient),
            treatment=dict(treatment),
            payments=payments,
            totals={
                "total_fmt": money(total_cents),
                "discount_fmt": money(discount_cents),
                "paid_fmt": money(paid_cents),
                "remaining_fmt": money(remaining_cents),
            },
        )
    finally:
        conn.close()


@bp.route("/patients/<pid>/payments/<pay_id>/receipt/view", methods=["GET"])
@require_permission("payments:view")
def view_payment_receipt(pid, pay_id):
    """Render a clean HTML view of the payment receipt (bilingual + RTL)."""
    ctx = _receipt_context(pid, pay_id)
    if ctx is None:
        flash(T("receipt_not_found"), "err")
        return redirect(url_for("patients.patient_detail", pid=pid))
    requested_lang, _requested_dir = _requested_lang_dir()
    tx = _translator(requested_lang)
    scope = _receipt_scope()

    return render_page(
        "payments/receipt.html",
        receipt=ctx["receipt"],
        snapshot=ctx["snapshot"],
        patient=ctx["patient"],
        clinic=ctx["clinic"],
        p=ctx["patient"],
        payment_id=ctx["payment_id"],
        scope=scope,
        lang_override=requested_lang,
        t_override=tx,
        show_back=True,
    )


@bp.route("/patients/<pid>/payments/<pay_id>/view-modal", methods=["GET"])
@require_permission("payments:view")
def view_payment_receipt_modal(pid, pay_id):
    ctx = _receipt_context(pid, pay_id)
    if ctx is None:
        return "Receipt not found", 404
    requested_lang, requested_dir = _requested_lang_dir()
    tx = _translator(requested_lang)
    scope = _receipt_scope()
    pdf_logo_url = None
    try:
        pdf_logo_url = url_for("admin_settings.theme_pdf_logo", _ts=int(datetime.utcnow().timestamp()))
    except Exception:
        pdf_logo_url = None

    return render_template(
        "payments/view_receipt_modal_fragment.html",
        receipt=ctx["receipt"],
        snapshot=ctx["snapshot"],
        patient=ctx["patient"],
        clinic=ctx["clinic"],
        raw_payment=ctx["raw_payment"],
        scope=scope,
        lang=requested_lang,
        dir=requested_dir,
        pdf_logo_url=pdf_logo_url,
        t=tx,
    )


@bp.route("/patients/<pid>/treatments/<treatment_id>/view-modal", methods=["GET"])
@require_permission("payments:view")
def view_treatment_modal(pid: str, treatment_id: str):
    requested_lang, requested_dir = _requested_lang_dir()
    tx = _translator(requested_lang)
    conn = db()
    try:
        patient = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
        treatment = conn.execute(
            """
            SELECT * FROM payments
             WHERE id=?
               AND patient_id=?
               AND (parent_payment_id IS NULL OR parent_payment_id = '')
            """,
            (treatment_id, pid),
        ).fetchone()
        if not patient or not treatment:
            return "Treatment not found", 404

        child_rows = conn.execute(
            """
            SELECT * FROM payments
             WHERE parent_payment_id=?
               AND patient_id=?
             ORDER BY paid_at DESC, created_at DESC
            """,
            (treatment_id, pid),
        ).fetchall()

        total_cents = int(treatment["total_amount_cents"] or 0)
        discount_cents = int(treatment["discount_cents"] or 0)
        initial_cents = int(treatment["amount_cents"] or 0)
        child_paid_cents = sum(int(row["amount_cents"] or 0) for row in child_rows)
        paid_cents = initial_cents + child_paid_cents
        due_cents = max(total_cents - discount_cents, 0)
        remaining_cents = max(due_cents - paid_cents, 0)

        treatment_label = (treatment["treatment"] or "").strip()
        is_consultation_visit = treatment_label in {
            tx("consultation_visit_name"),
            "Consultation visit",
            "زيارة استشارة",
        }
        if is_consultation_visit:
            visit_type_key = "vt_none"
        elif (treatment["examination_flag"] or 0) == 1:
            visit_type_key = "vt_exam"
        elif (treatment["followup_flag"] or 0) == 1:
            visit_type_key = "vt_follow"
        else:
            visit_type_key = "vt_none"

        currency = current_app.config.get("CURRENCY_LABEL", "EGP")

        def fmt(cents: int) -> str:
            base = money(cents)
            return f"{base} {currency}" if currency else base

        payments = []
        if initial_cents > 0:
            payments.append(
                {
                    "paid_at": treatment["paid_at"],
                    "amount_fmt": fmt(initial_cents),
                    "method": treatment["method"] or "",
                    "note": treatment["note"] or "",
                    "is_initial": True,
                    "doctor_label": treatment["doctor_label"] or ANY_DOCTOR_LABEL,
                }
            )
        for row in child_rows:
            payments.append(
                {
                    "paid_at": row["paid_at"],
                    "amount_fmt": fmt(int(row["amount_cents"] or 0)),
                    "method": row["method"] or "",
                    "note": row["note"] or "",
                    "is_initial": False,
                    "doctor_label": row["doctor_label"] or ANY_DOCTOR_LABEL,
                }
            )

        pdf_logo_url = None
        try:
            pdf_logo_url = url_for("admin_settings.theme_pdf_logo", _ts=int(datetime.utcnow().timestamp()))
        except Exception:
            pdf_logo_url = None

        return render_template(
            "payments/view_treatment_modal_fragment.html",
            patient=patient,
            treatment=treatment,
            payments=payments,
            clinic={
                "name": current_app.config.get("CLINIC_NAME") or "",
                "address": current_app.config.get("CLINIC_ADDRESS", ""),
                "phone": current_app.config.get("CLINIC_PHONE", ""),
            },
            pdf_logo_url=pdf_logo_url,
            visit_type_key=visit_type_key,
            lang=requested_lang,
            dir=requested_dir,
            t=tx,
            totals={
                "total_fmt": fmt(total_cents),
                "discount_fmt": fmt(discount_cents),
                "paid_fmt": fmt(paid_cents),
                "remaining_fmt": fmt(remaining_cents),
            },
        )
    finally:
        conn.close()


@bp.route("/patients/<pid>/treatments/<treatment_id>/print-modal", methods=["GET"])
@require_permission("payments:view")
def print_treatment_modal(pid: str, treatment_id: str):
    requested_lang, requested_dir = _requested_lang_dir()
    tx = _translator(requested_lang)
    conn = db()
    try:
        patient = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
        treatment = conn.execute(
            """
            SELECT * FROM payments
             WHERE id=?
               AND patient_id=?
               AND (parent_payment_id IS NULL OR parent_payment_id = '')
            """,
            (treatment_id, pid),
        ).fetchone()
        if not patient or not treatment:
            return "Treatment not found", 404

        child_rows = conn.execute(
            """
            SELECT * FROM payments
             WHERE parent_payment_id=?
               AND patient_id=?
             ORDER BY paid_at DESC, created_at DESC
            """,
            (treatment_id, pid),
        ).fetchall()

        total_cents = int(treatment["total_amount_cents"] or 0)
        discount_cents = int(treatment["discount_cents"] or 0)
        initial_cents = int(treatment["amount_cents"] or 0)
        child_paid_cents = sum(int(row["amount_cents"] or 0) for row in child_rows)
        paid_cents = initial_cents + child_paid_cents
        due_cents = max(total_cents - discount_cents, 0)
        remaining_cents = max(due_cents - paid_cents, 0)

        treatment_label = (treatment["treatment"] or "").strip()
        is_consultation_visit = treatment_label in {
            tx("consultation_visit_name"),
            "Consultation visit",
            "زيارة استشارة",
        }
        if is_consultation_visit:
            visit_type_key = "vt_none"
        elif (treatment["examination_flag"] or 0) == 1:
            visit_type_key = "vt_exam"
        elif (treatment["followup_flag"] or 0) == 1:
            visit_type_key = "vt_follow"
        else:
            visit_type_key = "vt_none"

        currency = current_app.config.get("CURRENCY_LABEL", "EGP")

        def fmt(cents: int) -> str:
            base = money(cents)
            return f"{base} {currency}" if currency else base

        payments = []
        if initial_cents > 0:
            payments.append(
                {
                    "paid_at": treatment["paid_at"],
                    "amount_fmt": fmt(initial_cents),
                    "method": treatment["method"] or "",
                    "note": treatment["note"] or "",
                    "is_initial": True,
                    "doctor_label": treatment["doctor_label"] or ANY_DOCTOR_LABEL,
                }
            )
        for row in child_rows:
            payments.append(
                {
                    "paid_at": row["paid_at"],
                    "amount_fmt": fmt(int(row["amount_cents"] or 0)),
                    "method": row["method"] or "",
                    "note": row["note"] or "",
                    "is_initial": False,
                    "doctor_label": row["doctor_label"] or ANY_DOCTOR_LABEL,
                }
            )

        clinic = {
            "name": current_app.config.get("CLINIC_NAME") or "",
            "address": current_app.config.get("CLINIC_ADDRESS", ""),
            "phone": current_app.config.get("CLINIC_PHONE", ""),
        }
        pdf_logo_url = None
        try:
            pdf_logo_url = url_for("admin_settings.theme_pdf_logo", _ts=int(datetime.utcnow().timestamp()))
        except Exception:
            pdf_logo_url = None

        return render_template(
            "payments/print_treatment_modal_fragment.html",
            patient=patient,
            treatment=treatment,
            clinic=clinic,
            pdf_logo_url=pdf_logo_url,
            payments=payments,
            visit_type_key=visit_type_key,
            lang=requested_lang,
            dir=requested_dir,
            t=tx,
            totals={
                "total_fmt": fmt(total_cents),
                "discount_fmt": fmt(discount_cents),
                "paid_fmt": fmt(paid_cents),
                "remaining_fmt": fmt(remaining_cents),
            },
        )
    finally:
        conn.close()


@bp.route("/patients/<pid>/payments/<pay_id>/print", methods=["GET"])
@bp.route("/patients/<pid>/payments/<pay_id>/print/<format_type>", methods=["GET"])
@require_permission("payments:view")
def print_payment_receipt(pid, pay_id, format_type="full"):
    """Generate and serve payment receipt PDF with print options support"""
    try:
        ctx = _receipt_context(pid, pay_id)
        if ctx is None:
            flash(T("receipt_not_found"), "err")
            return redirect(url_for("patients.patient_detail", pid=pid))

        # Validate format type (keep only the reliable ones)
        valid_formats = ["full"]
        if format_type not in valid_formats:
            flash(T("receipt_format"), "err")
            return redirect(url_for("patients.patient_detail", pid=pid))

        # Validate required data
        pay_dict = dict(ctx["raw_payment"])
        patient_dict = dict(ctx["raw_patient"])
        if not pay_dict.get("amount_cents") or pay_dict["amount_cents"] <= 0:
            flash(T("amount_required"), "err")
            return redirect(url_for("patients.patient_detail", pid=pid))
        if not patient_dict.get("full_name"):
            flash(T("patient_not_found"), "err")
            return redirect(url_for("patients.patient_detail", pid=pid))

        current_lang = _lang_param(ctx["lang"])

        # Minimal print options (user-controlled via modal)
        include_payment_notes = _bool_param("include_payment_notes", _bool_param("include_notes", False))
        include_treatment_notes = _bool_param("include_treatment_notes", _bool_param("include_treatment", False))
        print_options = {
            "include_qr": _bool_param("include_qr", True),
            "include_notes": include_payment_notes,
            "include_treatment": include_treatment_notes,
            "watermark": _bool_param("watermark", False),
        }

        payment_data = dict(pay_dict)
        payment_data["id"] = pay_id
        if not payment_data.get("doctor_label"):
            payment_data["doctor_label"] = ANY_DOCTOR_LABEL

        patient_data = {
            "full_name": patient_dict.get("full_name"),
            "short_id": patient_dict.get("short_id"),
            "phone": patient_dict.get("phone"),
            "address": patient_dict.get("address", ""),
        }

        treatment_details = {
            "clinic_name": ctx["clinic"].get("name") or translate_text(current_lang, "payment_summary"),
            "clinic_address": ctx["clinic"].get("address", ""),
            "clinic_phone": ctx["clinic"].get("phone", ""),
            "language": current_lang,
        }

        # Generate PDF with print options
        pdf_data = generate_payment_receipt_pdf(
            payment_data,
            patient_data,
            treatment_details,
            format_type,
            current_lang,
            print_options
        )

        # Create filename with safe characters
        safe_name = "".join(c for c in patient_data.get("short_id", "") if c.isalnum() or c in ('-', '_')).rstrip()
        filename = f"receipt_{safe_name}_{format_type}.pdf"

        # Send PDF to client
        return send_file(
            io.BytesIO(pdf_data),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )

    except ValueError as ve:
        flash(f"Invalid data format: {str(ve)}", "err")
        return redirect(url_for("patients.patient_detail", pid=pid))
    except IOError as ioe:
        record_exception("payments.print_receipt", ioe)
        flash("File operation error while generating receipt", "err")
        return redirect(url_for("patients.patient_detail", pid=pid))
    except Exception as exc:
        record_exception("payments.print_receipt", exc)
        flash(f"Error generating receipt: {str(exc)}", "err")
        return redirect(url_for("patients.patient_detail", pid=pid))


@bp.route("/patients/<pid>/payments/<pay_id>/print/preview", methods=["GET"])
@bp.route("/patients/<pid>/payments/<pay_id>/print/<format_type>/preview", methods=["GET"])
@require_permission("payments:view")
def preview_payment_receipt(pid, pay_id, format_type="full"):
    """Preview payment receipt PDF in browser"""
    try:
        ctx = _receipt_context(pid, pay_id)
        if ctx is None:
            return "Payment not found", 404

        valid_formats = ["full"]
        if format_type not in valid_formats:
            return "Invalid format", 400

        current_lang = _lang_param(ctx["lang"])

        payment_data = dict(ctx["raw_payment"])
        payment_data["id"] = pay_id
        if not payment_data.get("doctor_label"):
            payment_data["doctor_label"] = ANY_DOCTOR_LABEL

        patient_data = {
            "full_name": ctx["raw_patient"].get("full_name"),
            "short_id": ctx["raw_patient"].get("short_id"),
            "phone": ctx["raw_patient"].get("phone"),
            "address": ctx["raw_patient"].get("address", ""),
        }

        treatment_details = {
            "clinic_name": ctx["clinic"].get("name") or translate_text(current_lang, "payment_summary"),
            "clinic_address": ctx["clinic"].get("address", ""),
            "clinic_phone": ctx["clinic"].get("phone", ""),
            "language": current_lang,
        }

        include_payment_notes = _bool_param("include_payment_notes", _bool_param("include_notes", False))
        include_treatment_notes = _bool_param("include_treatment_notes", _bool_param("include_treatment", False))
        print_options = {
            "include_qr": _bool_param("include_qr", True),
            "include_notes": include_payment_notes,
            "include_treatment": include_treatment_notes,
            "watermark": _bool_param("watermark", False),
        }

        pdf_data = generate_payment_receipt_pdf(
            payment_data,
            patient_data,
            treatment_details,
            format_type,
            current_lang,
            print_options,
        )
        
        # Send PDF to browser for preview (no download)
        return send_file(
            io.BytesIO(pdf_data),
            mimetype='application/pdf',
            as_attachment=False
        )
        
    except Exception as exc:
        record_exception("payments.preview_receipt", exc)
        flash(T("receipt_generation_error", error=str(exc)), "err")
        return redirect(url_for("patients.patient_detail", pid=pid))


@bp.route("/export/payments.csv")
@require_permission("payments:edit")
def export_payments_csv():
    conn = db()
    rows = conn.execute(
        """
      SELECT pay.id, p.short_id, p.full_name, pay.paid_at, pay.amount_cents, pay.method, pay.note,
             pay.treatment, pay.remaining_cents, pay.total_amount_cents, pay.examination_flag, pay.followup_flag,
             pay.discount_cents, pay.doctor_id, pay.doctor_label
      FROM payments pay JOIN patients p ON p.id = pay.patient_id
      ORDER BY pay.paid_at DESC
    """,
    ).fetchall()
    conn.close()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "payment_id",
            "patient_short_id",
            "patient_name",
            "doctor_id",
            "doctor_label",
            "paid_at",
            "paid_today",
            "method",
            "note",
            "treatment",
            "discount",
            "remaining",
            "total_amount",
            "examination",
            "followup",
        ]
    )
    for r in rows:
        capped_remaining = max(
            ((r["total_amount_cents"] or 0) - (r["discount_cents"] or 0) - (r["amount_cents"] or 0)),
            0,
        )
        w.writerow(
            [
                r["id"],
                r["short_id"],
                r["full_name"],
                r["doctor_id"],
                r["doctor_label"],
                r["paid_at"],
                money(r["amount_cents"] or 0),
                r["method"],
                r["note"],
                r["treatment"] or "",
                money(r["discount_cents"] or 0),
                money(capped_remaining),
                money(r["total_amount_cents"] or 0),
                1 if (r["examination_flag"] or 0) == 1 else 0,
                1 if (r["followup_flag"] or 0) == 1 else 0,
            ]
        )
    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    return send_file(
        io.BytesIO(buf.read().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"payments-{ts}.csv",
    )


# =============================================================================
# Treatment-based payment routes
# =============================================================================


@bp.route("/patients/<pid>/treatments/<treatment_id>/payment", methods=["POST"])
@require_permission("payments:edit")
def add_payment_to_treatment_route(pid, treatment_id):
    """Add a new payment to an existing treatment."""
    import uuid

    conn = db()
    
    # Verify treatment exists and belongs to this patient
    treatment = conn.execute(
        "SELECT * FROM payments WHERE id = ? AND patient_id = ? AND (parent_payment_id IS NULL OR parent_payment_id = '')",
        (treatment_id, pid)
    ).fetchone()
    
    if not treatment:
        conn.close()
        return "Treatment not found", 404

    doctor_options = _doctor_options()
    doctor_lookup = {opt["doctor_id"]: opt for opt in doctor_options}
    doctor_id_raw = (request.form.get("doctor_id") or "").strip()
    treatment_doctor_id = (treatment["doctor_id"] or "").strip()
    treatment_doctor_label = treatment["doctor_label"] or ANY_DOCTOR_LABEL
    if not doctor_id_raw:
        doctor_id_raw = treatment_doctor_id
    if doctor_id_raw not in doctor_lookup:
        doctor_id_raw = treatment_doctor_id if treatment_doctor_id in doctor_lookup else ANY_DOCTOR_ID
    selected_doctor = doctor_lookup.get(doctor_id_raw, {"doctor_label": treatment_doctor_label})
    doctor_label = selected_doctor.get("doctor_label") or treatment_doctor_label or ANY_DOCTOR_LABEL

    amount_cents = parse_money_to_cents(request.form.get("amount") or "")
    paid_at = (request.form.get("paid_at") or date.today().isoformat())
    method = (request.form.get("method") or "cash").strip()
    note = (request.form.get("note") or "").strip()

    payment_id = add_payment_to_treatment(
        conn,
        treatment_id,
        pid,
        amount_cents,
        paid_at,
        method,
        note,
        doctor_id_raw,
        doctor_label,
    )

    # Audit log
    try:
        actor = getattr(g, "current_user", None)
        actor_id = getattr(actor, "id", None)
        write_event(
            actor_id,
            "payment_add_to_treatment",
            entity="payment",
            entity_id=payment_id,
            meta={
                "patient_id": pid,
                "treatment_id": treatment_id,
                "amount_cents": amount_cents,
                "paid_at": paid_at,
                "method": method,
            },
        )
    except Exception:
        pass

    conn.close()
    flash(T("payment_recorded"), "ok")
    return redirect(url_for("patients.patient_detail", pid=pid))


@bp.route("/patients/<pid>/treatments/<treatment_id>/payment-modal", methods=["GET"])
@require_permission("payments:edit")
def add_payment_to_treatment_modal(pid, treatment_id):
    """Show modal for adding payment to a treatment."""
    conn = db()
    p = conn.execute("SELECT * FROM patients WHERE id = ?", (pid,)).fetchone()
    treatment = conn.execute(
        "SELECT * FROM payments WHERE id = ? AND patient_id = ? AND (parent_payment_id IS NULL OR parent_payment_id = '')",
        (treatment_id, pid)
    ).fetchone()
    conn.close()
    
    if not p or not treatment:
        return "Treatment not found", 404

    doctor_options = _doctor_options()
    
    return render_template(
        "payments/add_payment_to_treatment_modal.html",
        p=p,
        treatment=treatment,
        treatment_name=treatment["treatment"] or "Untitled Treatment",
        today=date.today().isoformat(),
        doctor_options=doctor_options,
        action=url_for("payments.add_payment_to_treatment_route", pid=pid, treatment_id=treatment_id),
    )
