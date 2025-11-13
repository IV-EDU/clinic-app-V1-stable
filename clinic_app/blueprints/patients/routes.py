from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import date, datetime

from flask import Blueprint, flash, redirect, request, send_file, url_for, jsonify

from clinic_app.services.database import db
from clinic_app.services.i18n import T
from clinic_app.services.patients import migrate_patients_drop_unique_short_id, next_short_id
from clinic_app.services.payments import (
    bal_class_nonneg,
    cents_guard,
    money,
    overall_remaining,
    parse_money_to_cents,
    validate_payment_fields,
)
from clinic_app.services.ui import render_page
from clinic_app.services.security import require_permission

bp = Blueprint("patients", __name__)


@bp.route("/", methods=["GET"])
@require_permission("patients:view")
def index():
    """Redirect to patients list (main dashboard)."""
    return redirect(url_for("index"))


@bp.route("/patients/new", methods=["GET", "POST"])
@require_permission("patients:edit")
def new_patient():
    if request.method == "POST":
        short_id_in = (request.form.get("short_id") or "").strip()
        short_id_check = short_id_in or None
        full = (request.form.get("full_name") or "").strip()
        phone_raw = (request.form.get("phone") or "").strip()
        phone = phone_raw or None
        notes = (request.form.get("notes") or "").strip()
        if not full:
            flash(T("name") + " ?", "err")
            return render_page("patients/new.html", show_back=True)
        conn = db()
        confirm_dup = (request.form.get("confirm_dup") or "") == "1"
        n_name = re.sub(r"\s+", " ", full).strip().lower()
        cur = conn.cursor()
        dups = cur.execute(
            """
            SELECT id, full_name, phone, short_id FROM patients
            WHERE lower(trim(replace(full_name,'  ',' '))) = ?
               OR (phone IS NOT NULL AND phone = ?)
               OR (short_id IS NOT NULL AND short_id = ?)
            LIMIT 5
            """,
            (n_name, phone, short_id_check),
        ).fetchall()
        if dups and not confirm_dup:
            duplicates = [dict(r) for r in dups]
            form_values = {
                "short_id": short_id_in,
                "full_name": full,
                "phone": phone_raw,
                "notes": notes,
            }
            conn.close()
            return render_page(
                "patients/duplicate_confirm.html",
                duplicates=duplicates,
                form_values=form_values,
                show_back=True,
            )
        sid = short_id_in or next_short_id(conn)
        pid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO patients(id,short_id,full_name,phone,notes) VALUES (?,?,?,?,?)",
            (pid, sid, full, phone, notes),
        )
        conn.commit()
        migrate_patients_drop_unique_short_id(conn)
        conn.close()
        flash(T("created_patient"), "ok")
        return redirect(url_for("index"))
    return render_page("patients/new.html", show_back=True)


@bp.route("/patients/<pid>")
@require_permission("patients:view")
def patient_detail(pid):
    conn = db()
    cur = conn.cursor()
    p = cur.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        return "Patient not found", 404
    pays = cur.execute(
        "SELECT * FROM payments WHERE patient_id=? ORDER BY paid_at DESC",
        (pid,),
    ).fetchall()
    pays_fmt = []
    for r in pays:
        d = dict(r)
        d["amount_fmt"] = money(d.get("amount_cents") or 0)
        d["discount_fmt"] = money(d.get("discount_cents") or 0)
        d["total_fmt"] = money(d.get("total_amount_cents") or 0)
        pays_fmt.append(d)
    overall_cents = overall_remaining(conn, pid)
    overall_fmt = money(overall_cents)
    overall_class = bal_class_nonneg(overall_cents)
    html = render_page(
        "patients/detail.html",
        p=p,
        pays=pays_fmt,
        overall_fmt=overall_fmt,
        overall_class=overall_class,
        show_back=True,
    )
    conn.close()
    return html


@bp.route("/patients/<pid>/edit", methods=["GET", "POST"])
@require_permission("patients:edit")
def edit_patient(pid):
    conn = db()
    cur = conn.cursor()
    p = cur.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        return "Patient not found", 404
    if request.method == "POST":
        short_id_in = (request.form.get("short_id") or "").strip()
        full = (request.form.get("full_name") or "").strip()
        phone_raw = (request.form.get("phone") or "").strip()
        phone = phone_raw or None
        notes = (request.form.get("notes") or "").strip()
        sid = short_id_in if short_id_in else (p["short_id"] if p else None)
        cur.execute(
            "UPDATE patients SET short_id=?, full_name=?, phone=?, notes=? WHERE id=?",
            (sid, full, phone, notes, pid),
        )
        conn.commit()
        migrate_patients_drop_unique_short_id(conn)
        conn.close()
        flash(T("updated_patient"), "ok")
        return redirect(url_for("patients.patient_detail", pid=pid))
    html = render_page("patients/edit.html", p=p, show_back=True)
    conn.close()
    return html


@bp.route("/patients/<pid>/excel-entry", methods=["GET"])
@require_permission("payments:edit")
def excel_entry_get(pid):
    conn = db()
    p = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        return "Patient not found", 404
    conn.close()
    form = {
        "visit_type": "none",
        "paid_at": date.today().isoformat(),
        "method": "cash",
        "total_amount": "",
        "discount": "",
        "down_payment": "",
        "remaining_amount": "",
    }
    return render_page(
        "payments/form.html",
        p=p,
        today=date.today().isoformat(),
        form=form,
        action=url_for("patients.excel_entry_post", pid=p["id"]),
        submit_label=T("submit_add_payment"),
        show_back=True,
        show_id_header=False,
    )


@bp.route("/patients/<pid>/excel-entry", methods=["POST"])
@require_permission("payments:edit")
def excel_entry_post(pid):
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
            action=url_for("patients.excel_entry_post", pid=pid),
            submit_label=T("submit_add_payment"),
            show_back=True,
            show_id_header=False,
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
            action=url_for("patients.excel_entry_post", pid=pid),
            submit_label=T("submit_add_payment"),
            show_back=True,
            show_id_header=False,
        )

    treatment = (request.form.get("treatment_type") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    paid_at = (request.form.get("paid_at") or date.today().isoformat())
    method = (request.form.get("method") or "cash").strip()

    conn = db()
    conn.execute(
        """
      INSERT INTO payments(id, patient_id, paid_at, amount_cents, method, note, treatment,
                           remaining_cents, total_amount_cents, examination_flag, followup_flag, discount_cents)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            str(uuid.uuid4()),
            pid,
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
        ),
    )
    conn.commit()
    migrate_patients_drop_unique_short_id(conn)
    conn.close()
    flash(T("payment_recorded"), "ok")
    return redirect(url_for("patients.patient_detail", pid=pid))


@bp.route("/patients/<pid>/delete", methods=["GET"])
@require_permission("patients:delete")
def delete_patient_confirm(pid):
    conn = db()
    p = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not p:
        return "Patient not found", 404
    return render_page("patients/delete_confirm.html", p=p, show_back=True)


@bp.route("/patients/<pid>/delete", methods=["POST"])
@require_permission("patients:delete")
def delete_patient(pid):
    conn = db()
    conn.execute("DELETE FROM patients WHERE id=?", (pid,))
    conn.commit()
    migrate_patients_drop_unique_short_id(conn)
    conn.close()
    flash(T("deleted_patient_ok"), "ok")
    return redirect(url_for("index"))


@bp.route("/export/patients.csv")
@require_permission("patients:edit")
def export_patients_csv():
    conn = db()
    rows = conn.execute(
        "SELECT short_id, full_name, phone, notes, created_at, id FROM patients ORDER BY full_name",
    ).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["short_id", "full_name", "phone", "notes", "overall_balance", "created_at"])
    for r in rows:
        bal = overall_remaining(conn, r["id"])
        w.writerow(
            [r["short_id"], r["full_name"], r["phone"], r["notes"], f"{bal/100:.2f}", r["created_at"]]
        )
    conn.close()
    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    return send_file(
        io.BytesIO(buf.read().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"patients-{ts}.csv",
    )


@bp.route("/patients/search", methods=["GET"])
@require_permission("appointments:edit")
def search_patients():
    """API endpoint to search patients for appointment form autocomplete."""
    query = (request.args.get("q") or "").strip()
    if not query or len(query) < 2:
        return jsonify([])
    
    conn = db()
    try:
        # Search by name, phone, or short_id (file number)
        search_term = f"%{query.lower()}%"
        rows = conn.execute(
            """
            SELECT id, full_name, phone, short_id
            FROM patients
            WHERE lower(full_name) LIKE ?
               OR lower(phone) LIKE ?
               OR lower(short_id) LIKE ?
            ORDER BY full_name
            LIMIT 10
            """,
            (search_term, search_term, search_term)
        ).fetchall()
        
        patients = []
        for row in rows:
            patients.append({
                "id": row["id"],
                "full_name": row["full_name"],
                "phone": row["phone"],
                "short_id": row["short_id"]
            })
        
        return jsonify(patients)
    finally:
        conn.close()
