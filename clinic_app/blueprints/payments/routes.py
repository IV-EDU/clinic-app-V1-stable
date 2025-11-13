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


@bp.route("/patients/<pid>/payments/<pay_id>/print", methods=["GET"])
@bp.route("/patients/<pid>/payments/<pay_id>/print/<format_type>", methods=["GET"])
@require_permission("payments:view")
def print_payment_receipt(pid, pay_id, format_type="full"):
    """Generate and serve payment receipt PDF with print options support"""
    try:
        # Validate format type
        valid_formats = ["full", "summary", "treatment", "payment"]
        if format_type not in valid_formats:
            flash(f"Invalid format '{format_type}'. Valid formats: {', '.join(valid_formats)}", "err")
            return redirect(url_for("patients.patient_detail", pid=pid))

        conn, cur, p, pay = get_payment_and_patient(pay_id)
        if not pay or not p or p["id"] != pid:
            conn.close()
            flash("Payment not found", "err")
            return redirect(url_for("patients.patient_detail", pid=pid))

        # Validate required data
        pay_dict = dict(pay)
        if not pay_dict.get("amount_cents") or pay_dict["amount_cents"] <= 0:
            conn.close()
            flash("Payment has no valid amount data", "err")
            return redirect(url_for("patients.patient_detail", pid=pid))

        p_dict = dict(p)
        if not p_dict.get("full_name"):
            conn.close()
            flash("Patient has no name data", "err")
            return redirect(url_for("patients.patient_detail", pid=pid))

        # Get current language
        current_lang = get_lang()

        # Extract print options from request parameters
        include_qr = request.args.get("include_qr", "true").lower() == "true"
        include_notes = request.args.get("include_notes", "true").lower() == "true"
        include_treatment = request.args.get("include_treatment", "true").lower() == "true"
        add_watermark = request.args.get("watermark", "false").lower() == "true"
        
        # Prepare print options dict
        print_options = {
            "include_qr": include_qr,
            "include_notes": include_notes,
            "include_treatment": include_treatment,
            "watermark": add_watermark,
        }

        # Prepare payment data for PDF generation
        payment_data = dict(pay)
        payment_data["id"] = pay_id

        # Prepare patient data
        patient_data = dict(p)
        patient_data["full_name"] = p["full_name"]
        patient_data["short_id"] = p["short_id"]
        patient_data["phone"] = p["phone"]
        patient_data["address"] = getattr(p, "address", "")

        # Prepare treatment details (clinic info)
        treatment_details = {
            "clinic_name": current_app.config.get("CLINIC_NAME", "Dental Clinic"),
            "clinic_address": current_app.config.get("CLINIC_ADDRESS", ""),
            "clinic_phone": current_app.config.get("CLINIC_PHONE", ""),
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
        safe_name = "".join(c for c in p['short_id'] if c.isalnum() or c in ('-', '_')).rstrip()
        filename = f"receipt_{safe_name}_{format_type}.pdf"

        # Send PDF to client
        conn.close()
        return send_file(
            io.BytesIO(pdf_data),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=filename
        )

    except ValueError as ve:
        if 'conn' in locals():
            conn.close()
        flash(f"Invalid data format: {str(ve)}", "err")
        return redirect(url_for("patients.patient_detail", pid=pid))
    except IOError as ioe:
        if 'conn' in locals():
            conn.close()
        record_exception("payments.print_receipt", ioe)
        flash("File operation error while generating receipt", "err")
        return redirect(url_for("patients.patient_detail", pid=pid))
    except Exception as exc:
        if 'conn' in locals():
            conn.close()
        record_exception("payments.print_receipt", exc)
        flash(f"Error generating receipt: {str(exc)}", "err")
        return redirect(url_for("patients.patient_detail", pid=pid))


@bp.route("/patients/<pid>/payments/<pay_id>/print/preview", methods=["GET"])
@bp.route("/patients/<pid>/payments/<pay_id>/print/<format_type>/preview", methods=["GET"])
@require_permission("payments:view")
def preview_payment_receipt(pid, pay_id, format_type="full"):
    """Preview payment receipt PDF in browser"""
    try:
        conn, cur, p, pay = get_payment_and_patient(pay_id)
        if not pay or not p or p["id"] != pid:
            conn.close()
            return "Payment not found", 404
        
        # Get current language
        current_lang = get_lang()
        
        # Prepare data for PDF generation
        payment_data = dict(pay)
        payment_data["id"] = pay_id
        
        patient_data = dict(p)
        patient_data["full_name"] = p["full_name"]
        patient_data["short_id"] = p["short_id"]
        patient_data["phone"] = p["phone"]
        patient_data["address"] = getattr(p, "address", "")
        
        treatment_details = {
            "clinic_name": current_app.config.get("CLINIC_NAME", "Dental Clinic"),
            "clinic_address": current_app.config.get("CLINIC_ADDRESS", ""),
            "clinic_phone": current_app.config.get("CLINIC_PHONE", ""),
            "language": current_lang,
        }
        
        # Extract print options from request parameters for preview
        include_qr = request.args.get("include_qr", "true").lower() == "true"
        include_notes = request.args.get("include_notes", "true").lower() == "true"
        include_treatment = request.args.get("include_treatment", "true").lower() == "true"
        add_watermark = request.args.get("watermark", "false").lower() == "true"

        print_options = {
            "include_qr": include_qr,
            "include_notes": include_notes,
            "include_treatment": include_treatment,
            "watermark": add_watermark,
        }

        # Generate PDF using current language and selected options
        pdf_data = generate_payment_receipt_pdf(
            payment_data,
            patient_data,
            treatment_details,
            format_type,
            current_lang,
            print_options,
        )
        
        # Send PDF to browser for preview (no download)
        conn.close()
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
