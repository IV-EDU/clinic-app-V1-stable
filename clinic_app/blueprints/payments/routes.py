from __future__ import annotations

import csv
import io
from datetime import date, datetime
from pathlib import Path

from flask import Blueprint, flash, redirect, request, send_file, url_for, current_app, g

from clinic_app.services.database import db
from clinic_app.services.i18n import T, get_lang
from clinic_app.services.patients import migrate_patients_drop_unique_short_id
from clinic_app.services.payments import (
    cents_guard,
    money,
    money_input,
    parse_money_to_cents,
    validate_payment_fields,
)
from clinic_app.services.pdf_enhanced import generate_payment_receipt_pdf
from clinic_app.services.ui import render_page
from clinic_app.services.security import require_permission
from clinic_app.services.errors import record_exception

bp = Blueprint("payments", __name__)


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

    total_cents = payment.get("total_amount_cents") or 0
    discount_cents = payment.get("discount_cents") or 0
    paid_cents = payment.get("amount_cents") or 0
    remaining_cents = max(total_cents - discount_cents - paid_cents, 0)
    currency = current_app.config.get("CURRENCY_LABEL", "EGP")

    def fmt(cents: int) -> str:
        base = money(cents)
        return f"{base} {currency}" if currency else base

    clinic = {
        "name": current_app.config.get("CLINIC_NAME", T("app_title")),
        "address": current_app.config.get("CLINIC_ADDRESS", ""),
        "phone": current_app.config.get("CLINIC_PHONE", ""),
    }

    receipt = {
        "number": (pay_id or "")[-8:].upper(),
        "date": payment.get("paid_at") or date.today().isoformat(),
        "method": payment.get("method") or "",
        "treatment": payment.get("treatment") or "",
        "notes": payment.get("note") or "",
        "total": fmt(total_cents),
        "discount": fmt(discount_cents),
        "paid": fmt(paid_cents),
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
        "payment_id": pay_id,
        "raw_payment": payment,
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


@bp.route("/patients/<pid>/payments/<pay_id>/edit", methods=["GET"])
@require_permission("payments:edit")
def edit_payment_get(pid, pay_id):
    conn, cur, p, pay = get_payment_and_patient(pay_id)
    if not pay or not p or p["id"] != pid:
        conn.close()
        return "Payment not found", 404
    base_total_cents = (pay["total_amount_cents"] or 0) - (100 * 100 if (pay["examination_flag"] or 0) == 1 else 0)
    vt = (
        "exam"
        if (pay["examination_flag"] or 0) == 1
        else ("followup" if (pay["followup_flag"] or 0) == 1 else "none")
    )
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
    }
    html = render_page(
        "payments/form.html",
        p=p,
        today=date.today().isoformat(),
        form=form,
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
    vt = (request.form.get("visit_type") or "none")
    exam = vt == "exam"
    follow = vt == "followup"

    base_cents = parse_money_to_cents(request.form.get("total_amount") or "")
    total_eff = request.form.get("total_amount_effective")
    total_cents_raw = (
        parse_money_to_cents(total_eff) if total_eff else base_cents + (100 * 100 if exam else 0)
    )
    discount_cents_raw = parse_money_to_cents(request.form.get("discount") or "")
    down_cents_raw = parse_money_to_cents(request.form.get("down_payment") or "")

    ok, info = validate_payment_fields(total_cents_raw, discount_cents_raw, down_cents_raw, exam)
    if not ok:
        flash(T(info), "err")
        conn = db()
        p = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
        conn.close()
        form = dict(request.form)
        return render_page(
            "payments/form.html",
            p=p,
            today=date.today().isoformat(),
            form=form,
            action=url_for("payments.edit_payment_post", pid=pid, pay_id=pay_id),
            submit_label=T("update"),
            show_back=True,
            show_id_header=True,
        )

    due_cents = info
    rem_cents_raw = max(due_cents - down_cents_raw, 0)

    try:
        total_cents = cents_guard(total_cents_raw, "Total")
        discount_cents = cents_guard(discount_cents_raw, "Discount")
        down_cents = cents_guard(down_cents_raw, "Paid Today")
        rem_cents = cents_guard(rem_cents_raw, "Remaining")
    except ValueError:
        flash(T("err_money_too_large"), "err")
        conn = db()
        p = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
        conn.close()
        form = dict(request.form)
        return render_page(
            "payments/form.html",
            p=p,
            today=date.today().isoformat(),
            form=form,
            action=url_for("payments.edit_payment_post", pid=pid, pay_id=pay_id),
            submit_label=T("update"),
            show_back=True,
            show_id_header=True,
        )

    treatment = (request.form.get("treatment_type") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    paid_at = (request.form.get("paid_at") or date.today().isoformat())
    method = (request.form.get("method") or "cash").strip()

    conn, cur, p, pay = get_payment_and_patient(pay_id)
    if not pay or not p or p["id"] != pid:
        conn.close()
        return "Payment not found", 404
    cur.execute(
        """
        UPDATE payments
        SET paid_at=?, amount_cents=?, method=?, note=?, treatment=?,
            remaining_cents=?, total_amount_cents=?, examination_flag=?, followup_flag=?, discount_cents=?
        WHERE id=?
        """,
        (
            paid_at,
            down_cents,
            method,
            notes,
            treatment,
            rem_cents,
            total_cents,
            1 if exam else 0,
            1 if follow else 0,
            discount_cents,
            pay_id,
        ),
    )
    conn.commit()
    migrate_patients_drop_unique_short_id(conn)
    conn.close()
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
    cur.execute("DELETE FROM payments WHERE id=?", (pay_id,))
    conn.commit()
    migrate_patients_drop_unique_short_id(conn)
    conn.close()
    flash(T("deleted_payment_ok"), "ok")
    return redirect(url_for("patients.patient_detail", pid=pid))


@bp.route("/patients/<pid>/payments/<pay_id>/receipt/view", methods=["GET"])
@require_permission("payments:view")
def view_payment_receipt(pid, pay_id):
    """Render a clean HTML view of the payment receipt (bilingual + RTL)."""
    ctx = _receipt_context(pid, pay_id)
    if ctx is None:
        flash(T("receipt_not_found"), "err")
        return redirect(url_for("patients.patient_detail", pid=pid))

    return render_page(
        "payments/receipt.html",
        receipt=ctx["receipt"],
        patient=ctx["patient"],
        clinic=ctx["clinic"],
        p=ctx["patient"],
        payment_id=ctx["payment_id"],
        show_back=True,
    )


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
        print_options = {
            "include_qr": _bool_param("include_qr", True),
            "include_notes": _bool_param("include_notes", True),
            "include_treatment": _bool_param("include_treatment", True),
            "watermark": _bool_param("watermark", False),
        }

        payment_data = dict(pay_dict)
        payment_data["id"] = pay_id

        patient_data = {
            "full_name": patient_dict.get("full_name"),
            "short_id": patient_dict.get("short_id"),
            "phone": patient_dict.get("phone"),
            "address": patient_dict.get("address", ""),
        }

        treatment_details = {
            "clinic_name": ctx["clinic"].get("name", "Dental Clinic"),
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

        patient_data = {
            "full_name": ctx["raw_patient"].get("full_name"),
            "short_id": ctx["raw_patient"].get("short_id"),
            "phone": ctx["raw_patient"].get("phone"),
            "address": ctx["raw_patient"].get("address", ""),
        }

        treatment_details = {
            "clinic_name": ctx["clinic"].get("name", "Dental Clinic"),
            "clinic_address": ctx["clinic"].get("address", ""),
            "clinic_phone": ctx["clinic"].get("phone", ""),
            "language": current_lang,
        }

        print_options = {
            "include_qr": _bool_param("include_qr", True),
            "include_notes": _bool_param("include_notes", True),
            "include_treatment": _bool_param("include_treatment", True),
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
             pay.discount_cents
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
