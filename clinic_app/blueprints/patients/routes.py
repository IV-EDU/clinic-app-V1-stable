from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import date, datetime

from flask import Blueprint, flash, g, redirect, request, send_file, url_for, jsonify, render_template

from clinic_app.services.database import db
from clinic_app.services.i18n import T
from clinic_app.services.audit import write_event
from clinic_app.services.patients import (
    migrate_patients_drop_unique_short_id,
    next_short_id,
    merge_patient_records,
    MergeConflict,
)
from clinic_app.services.patient_pages import PatientPageService, AdminSettingsService
from clinic_app.extensions import csrf
from clinic_app.services.csrf import ensure_csrf_token
from clinic_app.services.payments import (
    bal_class_nonneg,
    cents_guard,
    money,
    overall_remaining,
    parse_money_to_cents,
    validate_payment_fields,
)
from clinic_app.services.doctor_colors import (
    ANY_DOCTOR_ID,
    ANY_DOCTOR_LABEL,
    DEFAULT_COLOR,
    get_active_doctor_options,
    get_deleted_doctors,
)
from clinic_app.services.ui import render_page
from clinic_app.services.security import require_permission

bp = Blueprint("patients", __name__)


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


def _doctor_maps(options: list[dict[str, str]]) -> tuple[dict[str, str], dict[str, str], str, str]:
    label_map = {opt["doctor_id"]: opt.get("doctor_label") or opt["doctor_id"] for opt in options}
    color_map = {opt["doctor_id"]: opt.get("color") or DEFAULT_COLOR for opt in options}
    default_label = label_map.get(ANY_DOCTOR_ID, ANY_DOCTOR_LABEL)
    default_color = color_map.get(ANY_DOCTOR_ID, DEFAULT_COLOR)
    return label_map, color_map, default_label, default_color


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
        primary_page = (request.form.get("primary_page_number") or "").strip() or None
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
            "INSERT INTO patients(id,short_id,full_name,phone,notes,primary_page_number) VALUES (?,?,?,?,?,?)",
            (pid, sid, full, phone, notes, primary_page),
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
    doctor_options = _doctor_options()
    doctor_label_map, doctor_color_map, default_label, default_color = _doctor_maps(
        doctor_options
    )
    deleted_ids = {d["doctor_id"] for d in get_deleted_doctors()}
    deleted_ids = {d["doctor_id"] for d in get_deleted_doctors()}
    pays_fmt = []
    for r in pays:
        d = dict(r)
        d["amount_fmt"] = money(d.get("amount_cents") or 0)
        d["discount_fmt"] = money(d.get("discount_cents") or 0)
        d["total_fmt"] = money(d.get("total_amount_cents") or 0)
        original_doctor_id = (d.get("doctor_id") or "").strip() or ANY_DOCTOR_ID
        is_deleted = original_doctor_id in deleted_ids
        display_doctor_id = ANY_DOCTOR_ID if is_deleted else original_doctor_id
        if is_deleted:
            display_label = ANY_DOCTOR_LABEL
        else:
            display_label = (
                d.get("doctor_label")
                or doctor_label_map.get(display_doctor_id)
                or default_label
            )
        d["doctor_id"] = display_doctor_id
        d["doctor_label"] = display_label
        d["doctor_color"] = doctor_color_map.get(display_doctor_id, default_color)
        pays_fmt.append(d)
    overall_cents = overall_remaining(conn, pid)
    overall_fmt = money(overall_cents)
    overall_class = bal_class_nonneg(overall_cents)
    # Suggested merge targets based on similar names (first 2 parts).
    merge_suggestions = []
    try:
        full_name = p["full_name"] or ""
        n = re.sub(r"\s+", " ", full_name.strip().lower())
        parts = n.split(" ")
        first_two = " ".join(parts[:2]).strip()
        if first_two:
            like = first_two + "%"
            rows_sugg = cur.execute(
                """
                SELECT id, short_id, full_name, phone
                  FROM patients
                 WHERE id<>? AND lower(full_name) LIKE ?
                 ORDER BY full_name
                 LIMIT 10
                """,
                (pid, like),
            ).fetchall()
            merge_suggestions = [dict(r) for r in rows_sugg]
    except Exception:
        merge_suggestions = []
    # Page numbers for this patient (physical notebook pages).
    try:
        pages = PatientPageService.get_patient_pages(pid)
    except Exception:
        pages = []

    # Primary page number (may not exist on very old databases).
    try:
        primary_page = p["primary_page_number"]
    except Exception:
        primary_page = None

    html = render_page(
        "patients/detail.html",
        p=p,
        pays=pays_fmt,
        overall_fmt=overall_fmt,
        overall_class=overall_class,
        page_numbers=pages,
        primary_page_number=primary_page,
        merge_suggestions=merge_suggestions,
        show_back=True,
    )
    conn.close()
    return html


@bp.route("/patients/<pid>/quickview", methods=["GET"])
@require_permission("patients:view")
def patient_quickview(pid):
    """Small HTML fragment for Admin quick-view modals (no iframe)."""
    conn = db()
    cur = conn.cursor()
    p = cur.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        return "Not found", 404

    # Primary page number (may not exist on very old databases).
    try:
        primary_page = p["primary_page_number"]
    except Exception:
        primary_page = None

    overall_cents = overall_remaining(conn, pid)
    overall_fmt = money(overall_cents)
    overall_class = bal_class_nonneg(overall_cents)

    recent = []
    try:
        pays = cur.execute(
            "SELECT paid_at, method, total_amount_cents, remaining_cents FROM payments WHERE patient_id=? ORDER BY paid_at DESC LIMIT 6",
            (pid,),
        ).fetchall()
        for r in pays or []:
            d = dict(r)
            d["total_fmt"] = money(d.get("total_amount_cents") or 0)
            d["remaining_fmt"] = money(d.get("remaining_cents") or 0)
            recent.append(d)
    except Exception:
        recent = []

    html = render_template(
        "patients/quickview_fragment.html",
        p=p,
        primary_page_number=primary_page,
        overall_fmt=overall_fmt,
        overall_class=overall_class,
        recent_payments=recent,
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
        primary_page = (request.form.get("primary_page_number") or "").strip() or None
        notes = (request.form.get("notes") or "").strip()
        sid = short_id_in if short_id_in else (p["short_id"] if p else None)
        cur.execute(
            "UPDATE patients SET short_id=?, full_name=?, phone=?, notes=?, primary_page_number=? WHERE id=?",
            (sid, full, phone, notes, primary_page, pid),
        )
        conn.commit()
        migrate_patients_drop_unique_short_id(conn)
        conn.close()
        flash(T("updated_patient"), "ok")
        return redirect(url_for("patients.patient_detail", pid=pid))
    html = render_page(
        "patients/edit.html",
        p=p,
        show_back=True,
        action=url_for("patients.edit_patient", pid=pid),
    )
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
    doctor_options = _doctor_options()
    form = {
        "visit_type": "none",
        "paid_at": date.today().isoformat(),
        "method": "cash",
        "total_amount": "",
        "discount": "",
        "down_payment": "",
        "remaining_amount": "",
        "doctor_id": "",
    }
    return render_page(
        "payments/form.html",
        p=p,
        today=date.today().isoformat(),
        form=form,
        doctor_options=doctor_options,
        doctor_error=None,
        action=url_for("patients.excel_entry_post", pid=p["id"]),
        submit_label=T("submit_add_payment"),
        show_back=True,
        show_id_header=False,
    )


@bp.route("/patients/<pid>/excel-entry/modal", methods=["GET"])
@require_permission("payments:edit")
def excel_entry_modal(pid):
    conn = db()
    p = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        return "Patient not found", 404
    conn.close()
    doctor_options = _doctor_options()
    form = {
        "visit_type": "none",
        "paid_at": date.today().isoformat(),
        "method": "cash",
        "total_amount": "",
        "discount": "",
        "down_payment": "",
        "remaining_amount": "",
        "doctor_id": "",
    }
    return render_template(
        "payments/form_modal_fragment.html",
        p=p,
        today=date.today().isoformat(),
        form=form,
        doctor_options=doctor_options,
        doctor_error=None,
        action=url_for("patients.excel_entry_post", pid=p["id"]),
        submit_label=T("submit_add_payment"),
    )


@bp.route("/patients/<pid>/edit/modal", methods=["GET"])
@require_permission("patients:edit")
def edit_patient_modal(pid):
    conn = db()
    cur = conn.cursor()
    p = cur.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        return "Patient not found", 404
    conn.close()
    # Determine whether page numbers should be shown in the UI.
    try:
        settings = AdminSettingsService.get_all_settings()
        raw_flag = settings.get("enable_file_numbers", True)
        if isinstance(raw_flag, str):
            show_file_numbers = raw_flag.lower() == "true"
        else:
            show_file_numbers = bool(raw_flag)
    except Exception:
        show_file_numbers = True
    return render_template(
        "patients/edit_modal_fragment.html",
        p=p,
        action=url_for("patients.edit_patient", pid=pid),
        show_file_numbers=show_file_numbers,
    )


@bp.route("/patients/<pid>/excel-entry", methods=["POST"])
@require_permission("payments:edit")
def excel_entry_post(pid):
    doctor_options = _doctor_options()
    doctor_lookup = {opt["doctor_id"]: opt for opt in doctor_options}
    doctor_id_raw = (request.form.get("doctor_id") or "").strip()
    doctor_error = None if doctor_id_raw and doctor_id_raw in doctor_lookup else T("doctor_required")

    conn = db()
    p = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not p:
        return "Patient not found", 404

    def _render_form(form_values):
        return render_page(
            "payments/form.html",
            p=p,
            today=date.today().isoformat(),
            form=form_values,
            action=url_for("patients.excel_entry_post", pid=pid),
            submit_label=T("submit_add_payment"),
            show_back=True,
            show_id_header=False,
            doctor_options=doctor_options,
            doctor_error=doctor_error,
        )

    if doctor_error:
        flash(T("doctor_required"), "err")
        form = dict(request.form)
        return _render_form(form)

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
        form = dict(request.form)
        return _render_form(form)

    due_cents = info
    rem_cents_raw = max(due_cents - down_cents_raw, 0)

    try:
        total_cents = cents_guard(total_cents_raw, "Total")
        discount_cents = cents_guard(discount_cents_raw, "Discount")
        down_cents = cents_guard(down_cents_raw, "Paid Today")
        rem_cents = cents_guard(rem_cents_raw, "Remaining")
    except ValueError:
        flash(T("err_money_too_large"), "err")
        form = dict(request.form)
        return _render_form(form)

    treatment = (request.form.get("treatment_type") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    paid_at = (request.form.get("paid_at") or date.today().isoformat())
    method = (request.form.get("method") or "cash").strip()

    selected_doctor = doctor_lookup.get(doctor_id_raw, {"doctor_label": ANY_DOCTOR_LABEL})
    doctor_label = selected_doctor.get("doctor_label") or ANY_DOCTOR_LABEL

    conn = db()
    payment_id = str(uuid.uuid4())
    conn.execute(
        """
      INSERT INTO payments(id, patient_id, paid_at, amount_cents, method, note, treatment,
                           doctor_id, doctor_label,
                           remaining_cents, total_amount_cents, examination_flag, followup_flag, discount_cents)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            payment_id,
            pid,
            paid_at,
            down_cents,
            method,
            notes,
            treatment,
            doctor_id_raw,
            doctor_label,
            rem_cents,
            total_cents,
            1 if exam else 0,
            1 if follow else 0,
            discount_cents,
        ),
    )
    conn.commit()
    try:
        actor = getattr(g, "current_user", None)
        actor_id = getattr(actor, "id", None)
        write_event(
            actor_id,
            "payment_create",
            entity="payment",
            entity_id=payment_id,
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
                "visit_type": "exam" if exam else ("followup" if follow else "none"),
            },
        )
    except Exception:
        # Never block core workflow if auditing fails.
        pass
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
    # Delete patient and any schedules linked to them
    conn.execute("DELETE FROM appointments WHERE patient_id=?", (pid,))
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
@require_permission("patients:view")
def search_patients():
    """API endpoint to search patients for appointment form autocomplete."""
    query = (request.args.get("q") or "").strip()

    if not query or len(query) < 2:
        return jsonify([])
    
    try:
        # Use the new page number search service if available
        results = PatientPageService.search_patients_by_page(query)
        
        patients = []
        for row in results:
            # Get additional patient details
            conn = db()
            patient_detail = conn.execute(
                """
                SELECT p.id, p.full_name, p.phone, p.short_id, p.created_at,
                       a.start_time as last_visit
                FROM patients p
                LEFT JOIN (
                    SELECT patient_id, MAX(start_time) as start_time
                    FROM appointments
                    WHERE patient_id IS NOT NULL
                    GROUP BY patient_id
                ) a ON p.id = a.patient_id
                WHERE p.id = ?
                """,
                (row["id"],)
            ).fetchone()
            conn.close()
            
            if not patient_detail:
                continue
                
            # Calculate age based on created_at (approximate)
            age = None
            if patient_detail["created_at"]:
                from datetime import datetime
                try:
                    if isinstance(patient_detail["created_at"], str):
                        created_date = datetime.fromisoformat(patient_detail["created_at"])
                    else:
                        created_date = patient_detail["created_at"]
                    age_years = (datetime.now() - created_date).days // 365
                    age = age_years if age_years > 0 else None
                except Exception:
                    age = None
            
            # Generate initials for avatar
            initials = ''
            try:
                if patient_detail["full_name"]:
                    names = patient_detail["full_name"].split()
                    initials = ''.join([name[0].upper() for name in names[:2]])
                else:
                    initials = '?'
            except Exception:
                initials = '?'
            
            # Format last visit
            last_visit = None
            if patient_detail["last_visit"]:
                try:
                    from datetime import datetime
                    if isinstance(patient_detail["last_visit"], str):
                        last_visit_date = datetime.fromisoformat(patient_detail["last_visit"])
                    else:
                        last_visit_date = patient_detail["last_visit"]
                    last_visit = last_visit_date.strftime("%b %d, %Y")
                except Exception:
                    last_visit = None
            
            patient_data = {
                "id": patient_detail["id"],
                "full_name": patient_detail["full_name"] or "Unknown Patient",
                "phone": patient_detail["phone"] or "No phone",
                "short_id": patient_detail["short_id"] or "N/A",
                "age": age,
                "initials": initials,
                "last_visit": last_visit,
                "page_numbers": row["page_numbers"].split(",") if row["page_numbers"] else []
            }
            patients.append(patient_data)

        return jsonify(patients)
    except Exception as e:
        # Fallback to original search if page number service fails
        conn = db()
        try:
            search_term = f"%{query.lower()}%"
            
            rows = conn.execute(
                """
                SELECT p.id, p.full_name, p.phone, p.short_id, p.created_at,
                       a.start_time as last_visit
                FROM patients p
                LEFT JOIN (
                    SELECT patient_id, MAX(start_time) as start_time
                    FROM appointments
                    WHERE patient_id IS NOT NULL
                    GROUP BY patient_id
                ) a ON p.id = a.patient_id
                WHERE lower(p.full_name) LIKE ?
                   OR lower(p.phone) LIKE ?
                   OR lower(p.short_id) LIKE ?
                ORDER BY p.full_name
                LIMIT 10
                """,
                (search_term, search_term, search_term)
            ).fetchall()
            
            patients = []
            for row in rows:
                # Calculate age based on created_at (approximate)
                age = None
                if row["created_at"]:
                    from datetime import datetime
                    try:
                        if isinstance(row["created_at"], str):
                            created_date = datetime.fromisoformat(row["created_at"])
                        else:
                            created_date = row["created_at"]
                        age_years = (datetime.now() - created_date).days // 365
                        age = age_years if age_years > 0 else None
                    except Exception:
                        age = None
                
                # Generate initials for avatar
                initials = ''
                try:
                    if row["full_name"]:
                        names = row["full_name"].split()
                        initials = ''.join([name[0].upper() for name in names[:2]])
                    else:
                        initials = '?'
                except Exception:
                    initials = '?'
                
                # Format last visit
                last_visit = None
                if row["last_visit"]:
                    try:
                        from datetime import datetime
                        if isinstance(row["last_visit"], str):
                            last_visit_date = datetime.fromisoformat(row["last_visit"])
                        else:
                            last_visit_date = row["last_visit"]
                        last_visit = last_visit_date.strftime("%b %d, %Y")
                    except Exception:
                        last_visit = None
                
                patient_data = {
                    "id": row["id"],
                    "full_name": row["full_name"] or "Unknown Patient",
                    "phone": row["phone"] or "No phone",
                    "short_id": row["short_id"] or "N/A",
                    "age": age,
                    "initials": initials,
                    "last_visit": last_visit,
                    "page_numbers": []
                }
                patients.append(patient_data)

            return jsonify(patients)
        except Exception:
            return jsonify([])
        finally:
            conn.close()


@bp.route("/patients/<pid>/pages/add", methods=["POST"])
@require_permission("patients:edit")
def add_patient_page_form(pid):
    """Add a page number (physical notebook page) to a patient."""
    page_number = (request.form.get("page_number") or "").strip()
    notebook = (request.form.get("notebook_name") or "").strip() or None

    if not page_number:
        flash(T("page_number_required") if T else "Please enter a page number.", "err")
        return redirect(url_for("patients.patient_detail", pid=pid))

    try:
        PatientPageService.add_page_to_patient(pid, page_number, notebook_name=notebook)
        flash(T("page_number_added") if T else "Page number added.", "ok")
    except Exception:
        flash(T("page_number_add_failed") if T else "Could not add page number.", "err")
    return redirect(url_for("patients.patient_detail", pid=pid))


@bp.route("/patients/<pid>/pages/delete", methods=["POST"])
@require_permission("patients:edit")
def delete_patient_page_form(pid):
    """Remove a page number from a patient."""
    page_number = (request.form.get("page_number") or "").strip()
    if not page_number:
        flash(T("page_number_required") if T else "Please enter a page number.", "err")
        return redirect(url_for("patients.patient_detail", pid=pid))

    try:
        removed = PatientPageService.remove_page_from_patient(pid, page_number)
        if removed:
            flash(T("page_number_removed") if T else "Page number removed.", "ok")
        else:
            flash(T("page_number_not_found") if T else "Page number not found.", "err")
    except Exception:
        flash(T("page_number_remove_failed") if T else "Could not remove page number.", "err")
    return redirect(url_for("patients.patient_detail", pid=pid))


@bp.route("/patients/<pid>/merge", methods=["POST"])
@require_permission("patients:merge")
def merge_patient(pid):
    """Merge this patient's records into another patient file."""
    target_short_id = (request.form.get("target_short_id") or "").strip()
    merge_diag_flag = bool(request.form.get("merge_diag_images"))

    if not target_short_id:
        flash(T("merge_target_required") if T else "Please enter a target file number.", "err")
        return redirect(url_for("patients.patient_detail", pid=pid))

    conn = db()
    cur = conn.cursor()
    try:
        src = cur.execute(
            "SELECT id, short_id, full_name, phone FROM patients WHERE id=?", (pid,)
        ).fetchone()
        if not src:
            flash("Source patient not found.", "err")
            return redirect(url_for("index"))

        tgt = cur.execute(
            "SELECT id, short_id, full_name, phone FROM patients WHERE short_id=?",
            (target_short_id,),
        ).fetchall()
        if not tgt:
            flash(
                T("merge_target_not_found") if T else "Target file number not found.",
                "err",
            )
            return redirect(url_for("patients.patient_detail", pid=pid))
        if len(tgt) > 1:
            flash(
                T("merge_target_ambiguous") if T else "More than one patient has this file number. Please make the file number unique first.",
                "err",
            )
            return redirect(url_for("patients.patient_detail", pid=pid))

        target_row = tgt[0]
        if target_row["id"] == src["id"]:
            flash(
                T("merge_same_patient") if T else "Cannot merge a patient into itself.",
                "err",
            )
            return redirect(url_for("patients.patient_detail", pid=pid))

        try:
            # Perform the merge inside a transaction.
            merge_patient_records(conn, dict(src), dict(target_row), merge_diag=merge_diag_flag)

            # After a successful merge, remove any remaining diagnosis/medical
            # rows for the source (if they were not moved) and delete the
            # source patient record itself so the data fully migrates.
            src_id = src["id"]
            for tbl in ("diagnosis", "diagnosis_event", "medical", "medical_event"):
                try:
                    cur.execute(f"DELETE FROM {tbl} WHERE patient_id=?", (src_id,))
                except Exception:
                    # Table may not exist; ignore.
                    continue
            cur.execute("DELETE FROM patients WHERE id=?", (src_id,))

            conn.commit()
        except MergeConflict as mc:
            conn.rollback()
            if mc.code == "target_has_diagnosis":
                msg = (
                    T("merge_target_has_diag")
                    if T
                    else "Cannot merge diagnosis/medical/images because the target patient already has diagnosis or medical data."
                )
            else:
                msg = T("merge_conflict") if T else "Merge could not be completed safely."
            flash(msg, "err")
            return redirect(url_for("patients.patient_detail", pid=pid))
        except Exception:
            conn.rollback()
            flash(T("merge_unexpected_error") if T else "Unexpected error while merging patients.", "err")
            return redirect(url_for("patients.patient_detail", pid=pid))

        flash(T("merge_patient_ok") if T else "Patient records merged successfully.", "ok")
        return redirect(url_for("patients.patient_detail", pid=target_row["id"]))
    finally:
        conn.close()


@bp.route("/api/patients/<pid>/pages", methods=["GET"])
@require_permission("patients:view")
def get_patient_pages(pid):
    """Get all page numbers for a patient."""
    try:
        pages = PatientPageService.get_patient_pages(pid)
        return jsonify(pages)
    except Exception:
        return jsonify([]), 500


@bp.route("/api/patients/<pid>/pages", methods=["POST"])
@require_permission("patients:edit")
def add_patient_page(pid):
    """Add a page number to a patient."""
    data = request.get_json()
    if not data or "page_number" not in data:
        return jsonify({"error": "Page number is required"}), 400
    
    try:
        page_id = PatientPageService.add_page_to_patient(
            pid,
            data["page_number"],
            data.get("notebook_name")
        )
        return jsonify({"id": page_id, "status": "success"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/patients/<pid>/pages/<page_number>", methods=["DELETE"])
@require_permission("patients:edit")
def remove_patient_page(pid, page_number):
    """Remove a page number from a patient."""
    try:
        success = PatientPageService.remove_page_from_patient(pid, page_number)
        if success:
            return jsonify({"status": "success"})
        else:
            return jsonify({"error": "Page not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/admin/patient-settings", methods=["GET"])
@require_permission("admin.user.manage")
def get_admin_settings():
    """Get all admin settings."""
    try:
        settings = AdminSettingsService.get_all_settings()
        return jsonify({"success": True, "settings": settings})
    except Exception as exc:
        return jsonify({"success": False, "errors": [str(exc) or "Failed to load settings"]}), 500


@bp.route("/api/admin/patient-settings", methods=["POST"])
@require_permission("admin.user.manage")
@csrf.exempt
def update_admin_settings():
    """Update admin settings."""
    data = request.get_json() or {}
    # Validate CSRF token from header / JSON for JSON API calls.
    ensure_csrf_token(data)

    # ensure_csrf_token may remove csrf_token from the payload.
    data.pop("csrf_token", None)

    if not data:
        return jsonify({"success": False, "errors": ["No data provided"]}), 400

    try:
        AdminSettingsService.update_settings(data)
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"success": False, "errors": [str(exc) or "Failed to save settings"]}), 500


@bp.route("/api/admin/patient-settings/page-numbers", methods=["GET"])
@require_permission("admin.user.manage")
def get_page_number_settings():
    """Get page number related settings."""
    try:
        settings = {
            "file_number_enabled": AdminSettingsService.is_file_number_enabled(),
            "page_number_mode": AdminSettingsService.get_page_number_mode(),
            "default_notebook_name": AdminSettingsService.get_default_notebook_name()
        }
        return jsonify(settings)
    except Exception:
        return jsonify({}), 500
