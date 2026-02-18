from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import date, datetime
from typing import Any

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
    get_treatments_for_patient,
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


def _is_modal_request() -> bool:
    return (request.headers.get("X-Modal") or "").strip().lower() in {"1", "true", "yes"}


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _normalize_phone_digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _sanitize_notebook_color(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"#[0-9a-fA-F]{6}", raw):
        return raw.lower()
    return ""

def _page_color_notebook_key(patient_id: str, page_number: str) -> str:
    """Internal notebook key used to persist per-page color without exposing notebook names."""
    pid_compact = (patient_id or "").replace("-", "")
    page = (page_number or "").strip()
    key = f"pc:{pid_compact}:{page}"
    # `patient_pages.notebook_name` is limited to 100 chars in migration 0014.
    if len(key) > 100:
        keep = max(0, 100 - (len(f"pc:{pid_compact}:")))
        key = f"pc:{pid_compact}:{page[:keep]}"
    return key


def _collect_phone_entries(form_data) -> tuple[list[dict[str, Any]], str | None]:
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_entry(phone_raw: str, label_raw: str) -> bool:
        phone = (phone_raw or "").strip()
        if not phone:
            return False
        normalized = _normalize_phone_digits(phone)
        if not normalized:
            return False
        if normalized in seen:
            return True
        seen.add(normalized)
        entries.append(
            {
                "phone": phone,
                "phone_normalized": normalized,
                "label": (label_raw or "").strip() or None,
            }
        )
        return False

    duplicate_found = add_entry(form_data.get("phone"), form_data.get("phone_label"))
    extra_numbers = form_data.getlist("extra_phone_number")
    extra_labels = form_data.getlist("extra_phone_label")
    row_count = max(len(extra_numbers), len(extra_labels))
    for index in range(row_count):
        number_val = extra_numbers[index] if index < len(extra_numbers) else ""
        label_val = extra_labels[index] if index < len(extra_labels) else ""
        duplicate_found = add_entry(number_val, label_val) or duplicate_found

    if duplicate_found:
        return entries, T("duplicate_phone_in_file")
    return entries, None


def _collect_page_entries(form_data) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen_pages: set[str] = set()

    def add_page(page_raw: str, notebook_raw: str, color_raw: str) -> None:
        page_number = (page_raw or "").strip()
        if not page_number:
            return
        page_key = page_number.lower()
        if page_key in seen_pages:
            return
        seen_pages.add(page_key)
        entries.append(
            {
                "page_number": page_number,
                "notebook_name": (notebook_raw or "").strip() or None,
                "notebook_color": _sanitize_notebook_color(color_raw),
            }
        )

    add_page(
        form_data.get("primary_page_number"),
        form_data.get("primary_notebook_name"),
        form_data.get("primary_notebook_color"),
    )

    page_numbers = form_data.getlist("extra_page_number")
    notebook_names = form_data.getlist("extra_notebook_name")
    notebook_colors = form_data.getlist("extra_notebook_color")
    row_count = max(len(page_numbers), len(notebook_names), len(notebook_colors))
    for index in range(row_count):
        page_val = page_numbers[index] if index < len(page_numbers) else ""
        notebook_val = notebook_names[index] if index < len(notebook_names) else ""
        color_val = notebook_colors[index] if index < len(notebook_colors) else ""
        add_page(page_val, notebook_val, color_val)

    return entries


def _save_patient_phones(conn, patient_id: str, phones: list[dict[str, Any]]) -> None:
    if not _table_exists(conn, "patient_phones"):
        return
    conn.execute("DELETE FROM patient_phones WHERE patient_id=?", (patient_id,))
    for index, phone_entry in enumerate(phones):
        conn.execute(
            """
            INSERT INTO patient_phones(id, patient_id, phone, phone_normalized, label, is_primary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                patient_id,
                phone_entry["phone"],
                phone_entry["phone_normalized"],
                phone_entry.get("label"),
                1 if index == 0 else 0,
            ),
        )


def _save_patient_pages(conn, patient_id: str, pages: list[dict[str, str]]) -> None:
    if not _table_exists(conn, "patient_pages"):
        return
    conn.execute("DELETE FROM patient_pages WHERE patient_id=?", (patient_id,))
    for page_entry in pages:
        conn.execute(
            """
            INSERT OR IGNORE INTO patient_pages(id, patient_id, page_number, notebook_name)
            VALUES (?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                patient_id,
                page_entry["page_number"],
                page_entry.get("notebook_name"),
            ),
        )


def _upsert_notebooks_from_pages(conn, pages: list[dict[str, str]]) -> None:
    if not _table_exists(conn, "notebooks"):
        return
    for page_entry in pages:
        notebook_name = (page_entry.get("notebook_name") or "").strip()
        if not notebook_name:
            continue
        notebook_color = (page_entry.get("notebook_color") or "").strip()
        if notebook_color:
            conn.execute(
                """
                INSERT INTO notebooks(id, name, color, active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(name) DO UPDATE SET
                    color=excluded.color,
                    active=1,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (str(uuid.uuid4()), notebook_name, notebook_color),
            )
        else:
            conn.execute(
                """
                INSERT INTO notebooks(id, name, active)
                VALUES (?, ?, 1)
                ON CONFLICT(name) DO UPDATE SET
                    active=1,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (str(uuid.uuid4()), notebook_name),
            )


def _load_patient_phones(conn, patient_id: str, primary_phone: str | None) -> list[dict[str, Any]]:
    if not _table_exists(conn, "patient_phones"):
        return ([{"phone": primary_phone, "label": None, "is_primary": 1}] if primary_phone else [])
    rows = conn.execute(
        """
        SELECT id, phone, label, is_primary
          FROM patient_phones
         WHERE patient_id=?
         ORDER BY is_primary DESC, created_at ASC
        """,
        (patient_id,),
    ).fetchall()
    if rows:
        return [dict(r) for r in rows]
    return ([{"phone": primary_phone, "label": None, "is_primary": 1}] if primary_phone else [])


@bp.route("/", methods=["GET"])
@require_permission("patients:view")
def index():
    """Redirect to patients list (main dashboard)."""
    return redirect(url_for("index"))


@bp.route("/patients/new", methods=["GET", "POST"])
@require_permission("patients:edit")
def new_patient():
    try:
        notebook_options = AdminSettingsService.get_notebooks()
    except Exception:
        notebook_options = []

    if request.method == "POST":
        short_id_in = (request.form.get("short_id") or "").strip()
        short_id_check = short_id_in or None
        full = (request.form.get("full_name") or "").strip()
        phone_entries, phone_error = _collect_phone_entries(request.form)
        page_entries = _collect_page_entries(request.form)
        phone = phone_entries[0]["phone"] if phone_entries else None
        primary_page = page_entries[0]["page_number"] if page_entries else None
        notes = (request.form.get("notes") or "").strip()
        if not full:
            flash(T("name") + " ?", "err")
            return render_page(
                "patients/new.html",
                show_back=True,
                notebook_options=notebook_options,
                form_values=request.form,
                phone_rows=phone_entries,
                page_rows=page_entries,
            )
        if phone_error:
            flash(phone_error, "err")
            return render_page(
                "patients/new.html",
                show_back=True,
                notebook_options=notebook_options,
                form_values=request.form,
                phone_rows=phone_entries,
                page_rows=page_entries,
            )
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
                "phone": phone or "",
                "notes": notes,
                "primary_page_number": primary_page or "",
                "primary_notebook_name": (request.form.get("primary_notebook_name") or "").strip(),
                "primary_notebook_color": (request.form.get("primary_notebook_color") or "").strip(),
            }
            conn.close()
            return render_page(
                "patients/duplicate_confirm.html",
                duplicates=duplicates,
                form_values=form_values,
                phone_rows=phone_entries,
                page_rows=page_entries,
                show_back=True,
            )
        sid = short_id_in or next_short_id(conn)
        pid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO patients(id,short_id,full_name,phone,notes,primary_page_number) VALUES (?,?,?,?,?,?)",
            (pid, sid, full, phone, notes, primary_page),
        )
        _save_patient_phones(conn, pid, phone_entries)
        _save_patient_pages(conn, pid, page_entries)
        _upsert_notebooks_from_pages(conn, page_entries)
        conn.commit()
        migrate_patients_drop_unique_short_id(conn)
        conn.close()
        flash(T("created_patient"), "ok")
        return redirect(url_for("index"))
    return render_page(
        "patients/new.html",
        show_back=True,
        notebook_options=notebook_options,
        form_values={},
        phone_rows=[],
        page_rows=[],
    )


@bp.route("/patients/<pid>")
@require_permission("patients:view")
def patient_detail(pid):
    conn = db()
    cur = conn.cursor()
    p = cur.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        return "Patient not found", 404
    
    # Get treatments with grouped payments
    treatments = get_treatments_for_patient(conn, pid)
    
    doctor_options = _doctor_options()
    doctor_label_map, doctor_color_map, default_label, default_color = _doctor_maps(
        doctor_options
    )
    deleted_ids = {d["doctor_id"] for d in get_deleted_doctors()}
    
    # Format treatments for display
    treatments_fmt = []
    for t in treatments:
        d = dict(t)
        filter_doctor_ids: set[str] = set()
        # Format money values
        d["total_amount_fmt"] = money(d.get("total_amount_cents") or 0)
        d["total_paid_fmt"] = money(d.get("total_paid_cents") or 0)
        d["remaining_fmt"] = money(d.get("remaining_cents") or 0)
        d["discount_fmt"] = money(d.get("discount_cents") or 0)
        d["amount_fmt"] = money(d.get("amount_cents") or 0)
        
        # Format child payments
        for payment in d.get("payments", []):
            payment["amount_fmt"] = money(payment.get("amount_cents") or 0)
            # Handle doctor display for child payments
            original_doctor_id = (payment.get("doctor_id") or "").strip() or ANY_DOCTOR_ID
            is_deleted = original_doctor_id in deleted_ids
            display_doctor_id = ANY_DOCTOR_ID if is_deleted else original_doctor_id
            if is_deleted:
                payment["doctor_label"] = ANY_DOCTOR_LABEL
            else:
                payment["doctor_label"] = (
                    payment.get("doctor_label")
                    or doctor_label_map.get(display_doctor_id)
                    or default_label
                )
            payment["doctor_color"] = doctor_color_map.get(display_doctor_id, default_color)
            payment["display_doctor_id"] = display_doctor_id
            if display_doctor_id and display_doctor_id != ANY_DOCTOR_ID:
                filter_doctor_ids.add(display_doctor_id)
        
        # Handle doctor display for treatment
        original_doctor_id = (d.get("doctor_id") or "").strip() or ANY_DOCTOR_ID
        is_deleted = original_doctor_id in deleted_ids
        display_doctor_id = ANY_DOCTOR_ID if is_deleted else original_doctor_id
        if is_deleted:
            d["doctor_label"] = ANY_DOCTOR_LABEL
        else:
            d["doctor_label"] = (
                d.get("doctor_label")
                or doctor_label_map.get(display_doctor_id)
                or default_label
            )
        d["doctor_color"] = doctor_color_map.get(display_doctor_id, default_color)
        d["display_doctor_id"] = display_doctor_id
        if display_doctor_id and display_doctor_id != ANY_DOCTOR_ID:
            filter_doctor_ids.add(display_doctor_id)

        treatment_label = (d.get("treatment") or "").strip()
        is_consultation_visit = treatment_label in {
            T("consultation_visit_name"),
            "Consultation visit",
            "زيارة استشارة",
        }
        if is_consultation_visit:
            d["visit_type_key"] = "vt_none"
        elif (d.get("examination_flag") or 0) == 1:
            d["visit_type_key"] = "vt_exam"
        elif (d.get("followup_flag") or 0) == 1:
            d["visit_type_key"] = "vt_follow"
        else:
            d["visit_type_key"] = "vt_none"

        d["filter_doctor_ids_csv"] = ",".join(sorted(filter_doctor_ids))
        
        treatments_fmt.append(d)
    
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
    try:
        phone_rows = _load_patient_phones(conn, pid, p["phone"])
    except Exception:
        phone_rows = ([{"phone": p["phone"], "label": None, "is_primary": 1}] if p["phone"] else [])

    # Primary page number (may not exist on very old databases).
    try:
        primary_page = p["primary_page_number"]
    except Exception:
        primary_page = None

    html = render_page(
        "patients/detail.html",
        p=p,
        treatments=treatments_fmt,
        pays=treatments_fmt,  # Backwards compatibility
        doctor_options=doctor_options,
        today=date.today().isoformat(),
        overall_fmt=overall_fmt,
        overall_class=overall_class,
        page_numbers=pages,
        phone_numbers=phone_rows,
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

    try:
        notebook_options = AdminSettingsService.get_notebooks()
    except Exception:
        notebook_options = []

    try:
        existing_pages = PatientPageService.get_patient_pages(pid)
    except Exception:
        existing_pages = []
    existing_phones = _load_patient_phones(conn, pid, p["phone"])

    if request.method == "POST":
        short_id_in = (request.form.get("short_id") or "").strip()
        full = (request.form.get("full_name") or "").strip()
        phone_entries, phone_error = _collect_phone_entries(request.form)
        page_entries = _collect_page_entries(request.form)
        # Persist page color even when the UI hides notebook names.
        for entry in page_entries:
            if entry.get("notebook_color") and not (entry.get("notebook_name") or "").strip():
                entry["notebook_name"] = _page_color_notebook_key(pid, entry.get("page_number") or "")
        phone = phone_entries[0]["phone"] if phone_entries else None
        primary_page = page_entries[0]["page_number"] if page_entries else None
        notes = (request.form.get("notes") or "").strip()
        if not full:
            flash(T("name") + " ?", "err")
            html = render_page(
                "patients/edit.html",
                p=p,
                show_back=True,
                action=url_for("patients.edit_patient", pid=pid),
                notebook_options=notebook_options,
                phone_rows=phone_entries,
                page_rows=page_entries,
            )
            conn.close()
            return html
        if phone_error:
            flash(phone_error, "err")
            html = render_page(
                "patients/edit.html",
                p=p,
                show_back=True,
                action=url_for("patients.edit_patient", pid=pid),
                notebook_options=notebook_options,
                phone_rows=phone_entries,
                page_rows=page_entries,
            )
            conn.close()
            return html

        sid = short_id_in if short_id_in else (p["short_id"] if p else None)
        cur.execute(
            "UPDATE patients SET short_id=?, full_name=?, phone=?, notes=?, primary_page_number=? WHERE id=?",
            (sid, full, phone, notes, primary_page, pid),
        )
        _save_patient_phones(conn, pid, phone_entries)
        _save_patient_pages(conn, pid, page_entries)
        _upsert_notebooks_from_pages(conn, page_entries)
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
        notebook_options=notebook_options,
        phone_rows=existing_phones,
        page_rows=existing_pages,
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
    existing_phones = _load_patient_phones(conn, pid, p["phone"])
    try:
        existing_pages = PatientPageService.get_patient_pages(pid)
    except Exception:
        existing_pages = []
    try:
        notebook_options = AdminSettingsService.get_notebooks()
    except Exception:
        notebook_options = []
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
        notebook_options=notebook_options,
        phone_rows=existing_phones,
        page_rows=existing_pages,
    )


@bp.route("/patients/<pid>/excel-entry", methods=["POST"])
@require_permission("payments:edit")
def excel_entry_post(pid):
    doctor_options = _doctor_options()
    doctor_lookup = {opt["doctor_id"]: opt for opt in doctor_options}
    doctor_id_raw = (request.form.get("doctor_id") or "").strip()
    # Safety default: never store a blank doctor. If missing/invalid, use Any Doctor.
    if not doctor_id_raw or doctor_id_raw not in doctor_lookup:
        doctor_id_raw = ANY_DOCTOR_ID
    doctor_error = None

    conn = db()
    p = conn.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not p:
        return "Patient not found", 404

    is_modal = _is_modal_request()

    def _render_form(form_values, status_code=200):
        if is_modal:
            return render_template(
                "payments/form_modal_fragment.html",
                p=p,
                today=date.today().isoformat(),
                form=form_values,
                doctor_options=doctor_options,
                doctor_error=doctor_error,
                action=url_for("patients.excel_entry_post", pid=pid),
                submit_label=T("submit_add_payment"),
            ), status_code
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
        if not is_modal:
            flash(T("doctor_required"), "err")
        form = dict(request.form)
        return _render_form(form, status_code=422)

    vt = (request.form.get("visit_type") or "none")
    exam = vt == "exam"
    follow = vt == "followup"

    base_cents = parse_money_to_cents(request.form.get("total_amount") or "")
    total_cents_raw = base_cents
    discount_cents_raw = parse_money_to_cents(request.form.get("discount") or "")
    down_cents_raw = parse_money_to_cents(request.form.get("down_payment") or "")

    ok, info = validate_payment_fields(total_cents_raw, discount_cents_raw, down_cents_raw, exam)
    if not ok:
        if not is_modal:
            flash(T(info), "err")
        form = dict(request.form)
        return _render_form(form, status_code=422)

    due_cents = info
    rem_cents_raw = max(due_cents - down_cents_raw, 0)

    try:
        total_cents = cents_guard(total_cents_raw, "Total")
        discount_cents = cents_guard(discount_cents_raw, "Discount")
        down_cents = cents_guard(down_cents_raw, "Paid Today")
        rem_cents = cents_guard(rem_cents_raw, "Remaining")
    except ValueError:
        if not is_modal:
            flash(T("err_money_too_large"), "err")
        form = dict(request.form)
        return _render_form(form, status_code=422)

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
    if is_modal:
        return "", 204
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
            digits = _normalize_phone_digits(query)
            search_digits = f"%{digits}%" if digits else ""
            has_pages = _table_exists(conn, "patient_pages")
            has_phones = _table_exists(conn, "patient_phones")

            where_parts = [
                "lower(p.full_name) LIKE ?",
                "lower(p.phone) LIKE ?",
                "lower(p.short_id) LIKE ?",
            ]
            params: list[str] = [search_term, search_term, search_term]
            if digits:
                where_parts.append(
                    "replace(replace(replace(replace(replace(p.phone,' ',''),'-',''),'+',''),'(',''),')','') LIKE ?"
                )
                params.append(search_digits)
            if has_pages:
                where_parts.append(
                    """
                    EXISTS (
                        SELECT 1
                        FROM patient_pages pg
                        WHERE pg.patient_id = p.id
                          AND (
                               lower(pg.page_number) LIKE ?
                               OR (lower(pg.notebook_name) LIKE ? AND lower(pg.notebook_name) NOT LIKE 'pc:%')
                          )
                    )
                    """
                )
                params.extend([search_term, search_term])
            if has_phones:
                if digits:
                    where_parts.append(
                        """
                        EXISTS (
                            SELECT 1
                            FROM patient_phones ph
                            WHERE ph.patient_id = p.id
                              AND (
                                   lower(ph.phone) LIKE ?
                                   OR lower(ph.phone_normalized) LIKE ?
                                   OR replace(replace(replace(replace(replace(ph.phone,' ',''),'-',''),'+',''),'(',''),')','') LIKE ?
                                   OR replace(replace(replace(replace(replace(ph.phone_normalized,' ',''),'-',''),'+',''),'(',''),')','') LIKE ?
                              )
                        )
                        """
                    )
                    params.extend([search_term, search_digits, search_digits, search_digits])
                else:
                    where_parts.append(
                        """
                        EXISTS (
                            SELECT 1
                            FROM patient_phones ph
                            WHERE ph.patient_id = p.id
                              AND (lower(ph.phone) LIKE ?)
                        )
                        """
                    )
                    params.append(search_term)

            rows = conn.execute(
                f"""
                SELECT p.id, p.full_name, p.phone, p.short_id, p.created_at,
                       a.start_time as last_visit
                FROM patients p
                LEFT JOIN (
                    SELECT patient_id, MAX(start_time) as start_time
                    FROM appointments
                    WHERE patient_id IS NOT NULL
                    GROUP BY patient_id
                ) a ON p.id = a.patient_id
                WHERE {" OR ".join(where_parts)}
                ORDER BY p.full_name
                LIMIT 10
                """,
                tuple(params),
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
    notebook_color = _sanitize_notebook_color(request.form.get("notebook_color") or "")
    if notebook_color and not notebook:
        notebook = _page_color_notebook_key(pid, page_number)

    if not page_number:
        flash(T("page_number_required") if T else "Please enter a page number.", "err")
        return redirect(url_for("patients.patient_detail", pid=pid))

    try:
        PatientPageService.add_page_to_patient(pid, page_number, notebook_name=notebook)
        conn = db()
        try:
            _upsert_notebooks_from_pages(
                conn,
                [
                    {
                        "page_number": page_number,
                        "notebook_name": notebook,
                        "notebook_color": notebook_color,
                    }
                ],
            )
            conn.commit()
        finally:
            conn.close()
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
