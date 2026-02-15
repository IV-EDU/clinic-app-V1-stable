from __future__ import annotations

import datetime
from collections import defaultdict
from datetime import date, timedelta
from uuid import uuid4

from flask import Blueprint, current_app, flash, g, redirect, request, url_for, jsonify, abort
from flask_login import current_user
from sqlalchemy import or_, text, select
from sqlalchemy.orm import selectinload

from clinic_app.services.appointments import (
    AppointmentError,
    AppointmentOverlap,
    AppointmentNotFound,
    create_appointment,
    doctor_choices,
    list_for_day,
    update_appointment,
    update_status,
    delete_appointment,
    get_appointment_by_id,
)
from clinic_app.services.doctor_colors import (
    get_doctor_colors,
    get_all_doctors_with_colors,
    get_deleted_doctors,
    ANY_DOCTOR_ID,
    ANY_DOCTOR_LABEL,
)
from clinic_app.services.i18n import T
from clinic_app.services.security import require_permission
from clinic_app.services.ui import render_page
from clinic_app.services.errors import record_exception
from clinic_app.extensions import csrf, db
from clinic_app.services.csrf import ensure_csrf_token
from clinic_app.services.arabic_search import normalize_search_query
from flask_wtf.csrf import validate_csrf
from clinic_app.models import Appointment as AppointmentModel, Patient as PatientModel, Doctor as DoctorModel
bp = Blueprint("appointments", __name__)
DEFAULT_DOCTOR_COLOR = "#2563EB"


def _selected_day() -> str:
    return request.args.get("day") or date.today().isoformat()


_RANGE_PRESETS = {
    "yesterday": -1,
    "today": 0,
    "tomorrow": 1,
    "next3": 3,
    "next7": 7,
    "all": None,
}

_SHOW_PRESETS = {"scheduled", "done", "all"}


def _resolve_range(day_str: str, key: str) -> tuple[str, str | None]:
    key = key if key in _RANGE_PRESETS else "today"
    span = _RANGE_PRESETS[key]
    if span is None:
        return key, None
    base = date.fromisoformat(day_str)
    end = base + timedelta(days=span)
    return key, end.isoformat()


def _search_query() -> str:
    return (request.args.get("q") or "").strip()


def _range_choices() -> list[tuple[str, str]]:
    return [
        ("yesterday", "Yesterday"),
        ("today", "Today"),
        ("tomorrow", "Tomorrow"),
        ("next3", "Next 3 Days"),
        ("next7", "Next 7 Days"),
        ("all", "All Dates"),
    ]


def _show_choices() -> list[tuple[str, str]]:
    return [
        ("scheduled", "Scheduled"),
        ("done", "Done"),
        ("all", "All Status"),
    ]


def _choice_label(value: str, choices: list[tuple[str, str]], fallback: str) -> str:
    for key, label in choices:
        if key == value:
            return label
    return fallback


_STATUS_ORDER = {
    "scheduled": 0,
    "checked_in": 1,
    "in_progress": 2,
    "done": 3,
    "no_show": 4,
    "cancelled": 5,
}


def _status_priority(status: str) -> int:
    return _STATUS_ORDER.get(status, 10)


STATUS_ALIASES = {
    "pending": "checked_in",
}


def _normalize_status(value: str | None) -> str:
    status = (value or "scheduled").strip().lower()
    return STATUS_ALIASES.get(status, status)


def _group_table_appointments(appts: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = {}
    for appt in appts:
        pid = appt.get("patient_id")
        key = pid or f"anon:{appt.get('patient_name')}:{appt.get('patient_phone') or ''}"
        bucket = buckets.setdefault(
            key,
            {
                "patient_id": pid,
                "patient_name": appt.get("patient_name") or "—",
                "patient_phone": appt.get("patient_phone"),
                "patient_short_id": appt.get("patient_short_id"),
                "appointments": [],
            },
        )
        bucket["appointments"].append(appt)

    groups: list[dict] = []
    for bucket in buckets.values():
        schedules = sorted(bucket["appointments"], key=lambda a: a["starts_at"])
        selected = min(
            schedules,
            key=lambda a: (_status_priority(a.get("status", "")), a["starts_at"]),
        )
        bucket["selected"] = selected
        time_display = selected.get("time_label") or format_time_range(selected["starts_at"], selected["ends_at"])
        bucket["time_display"] = time_display
        bucket["doctor_label"] = selected.get("doctor_label")
        bucket["extra_count"] = max(0, len(schedules) - 1)
        bucket["modal_payload"] = {
            "patient_name": bucket["patient_name"],
            "file_no": bucket["patient_short_id"] or "—",
            "phone": bucket["patient_phone"] or "—",
            "selected": {
                "doctor": bucket["doctor_label"],
                "time": time_display,
                "title": selected["title"],
                "status_label": T("appointment_status_" + selected["status"]),
                "notes": selected.get("notes") or "",
            },
            "schedules": [
                {
                    "id": ap["id"],
                    "title": ap["title"],
                    "doctor": ap["doctor_label"],
                    "time": ap.get("time_label") or format_time_range(ap["starts_at"], ap["ends_at"]),
                    "notes": ap.get("notes") or "",
                    "status": ap["status"],
                    "status_label": T("appointment_status_" + ap["status"]),
                    "edit_url": url_for("appointments.edit", appt_id=ap["id"]),
                }
                for ap in schedules
            ],
        }
        groups.append(bucket)

    groups.sort(key=lambda grp: grp["selected"]["starts_at"])
    return groups

@bp.route("/appointments", methods=["GET"], endpoint="index")
@require_permission("appointments:view")
def appointments_entrypoint():
    """Main appointments page - send users to the modern vanilla view."""
    try:
        return redirect(url_for("appointments.vanilla"))
    except Exception as exc:
        record_exception("appointments.index", exc)
        raise


@bp.route("/appointments/new", methods=["GET", "POST"], endpoint="new")
@require_permission("appointments:edit")
def new():
    """Legacy-friendly appointment creation form for tests and quick entry."""
    if request.method == "GET":
        return render_page(
            "appointments/new.html",
            day=_selected_day(),
            doctors=doctor_choices(),
        )

    form_data = request.form.to_dict(flat=True)
    try:
        create_appointment(form_data, actor_id=current_user.get_id() if current_user.is_authenticated else None)
        return redirect(url_for("appointments.vanilla"))
    except AppointmentOverlap:
        return jsonify({"success": False, "error": "conflict"}), 409
    except AppointmentError as exc:
        flash(T(str(exc)), "err")
        return redirect(url_for("appointments.new"))
    except Exception as exc:
        record_exception("appointments.new", exc)
        abort(500)


@bp.route("/appointments/move", methods=["POST"], endpoint="move")
@require_permission("appointments:edit")
def move():
    """Move an appointment to a new time/doctor (JSON)."""
    data = request.get_json(silent=True) or {}
    ensure_csrf_token(data)

    appt_id = data.get("appointment_id")
    target_doctor = data.get("target_doctor")
    target_time = data.get("target_time")
    if not appt_id or not target_doctor or not target_time:
        abort(400)

    appt = get_appointment_by_id(appt_id)
    if not appt:
        abort(404)

    form_data = {
        "doctor_id": target_doctor,
        "start_time": target_time,
        "day": appt["starts_at"][:10],
        "title": appt["title"],
        "notes": appt.get("notes") or "",
    }

    try:
        update_appointment(
            appt_id,
            form_data,
            actor_id=current_user.get_id() if current_user.is_authenticated else None,
        )
    except AppointmentOverlap:
        return jsonify({"success": False, "error": "conflict"}), 409

    updated = get_appointment_by_id(appt_id)
    return jsonify({"success": True, "appointment": updated}), 200




@bp.route("/appointments/simple", methods=["GET"], endpoint="simple_view")
@require_permission("appointments:view")
def appointments_simple_view():
    """Simplified appointments view - single, clean interface."""
    try:
        day = _selected_day()
        doctor = request.args.get("doctor") or "all"
        search = _search_query()
        show_mode = (request.args.get("show") or "upcoming").lower()
        if show_mode not in _SHOW_PRESETS:
            show_mode = "upcoming"

        doctor_id = doctor if doctor != "all" else None

        # Calculate navigation dates
        try:
            current_date = date.fromisoformat(day)
            previous_day = (current_date - timedelta(days=1)).isoformat()
            next_day = (current_date + timedelta(days=1)).isoformat()
            today = date.today().isoformat()
        except ValueError:
            # Invalid date format, use today
            current_date = date.today()
            day = current_date.isoformat()
            previous_day = (current_date - timedelta(days=1)).isoformat()
            next_day = (current_date + timedelta(days=1)).isoformat()
            today = day

        try:
            appts = list_for_day(day, doctor_id=doctor_id, search=search or None, show=show_mode)
            status_counts: dict[str, int] = {}
            for appt in appts:
                status_counts[appt["status"]] = status_counts.get(appt["status"], 0) + 1
        except AppointmentError as exc:
            flash(T(str(exc)), "err")
            appts = []
        except Exception as exc:
            # Handle unexpected errors gracefully
            current_app.logger.error(f"Error listing appointments for day {day}: {exc}")
            flash("An error occurred while loading appointments. Please try again.", "err")
            appts = []

        try:
            doctors_list = doctor_choices()
        except Exception as exc:
            current_app.logger.error(f"Error getting doctor choices: {exc}")
            doctors_list = []

        return render_page(
            "appointments/simple_view.html",
            day=day,
            doctor=doctor,
            doctors=[("all", T("appointments_doctor_all"))] + doctors_list,
            appts=appts,
            selected_doctor=doctor,
            search=search,
            show=show_mode,
            previous_day=previous_day,
            next_day=next_day,
            today=today,
            end_day=None,  # Simple view shows single day
        )
    except Exception as exc:
        record_exception("appointments.simple_view", exc)
        raise
@bp.route("/appointments/table", methods=["GET"], endpoint="table")
@require_permission("appointments:view")
def appointments_table():
    """Legacy route kept for older links; redirect to the modern view."""
    params = request.args.to_dict(flat=True)
    if ("start_date" not in params or params.get("start_date") in (None, "")) and params.get("day"):
        params["start_date"] = params["day"]
    params.pop("day", None)
    return redirect(url_for("appointments.vanilla", **params))


@bp.route("/appointments/<appt_id>/delete", methods=["POST"], endpoint="delete")
@require_permission("appointments:edit")
def delete_appointment(appt_id):
    try:
        # Import here to avoid circular imports
        from clinic_app.services.appointments import get_appointment_by_id, delete_appointment as delete_appt

        appointment = get_appointment_by_id(appt_id)
        if not appointment:
            flash("Appointment not found", "err")
            return redirect(request.form.get("next") or url_for("appointments.index"))

        try:
            delete_appt(appt_id)
            flash(f"Appointment for {appointment['patient_name']} has been deleted", "ok")
        except AppointmentError as exc:
            flash(T(str(exc)), "err")
        return redirect(request.form.get("next") or url_for("appointments.index"))
    except Exception as exc:
        record_exception("appointments.delete", exc)
        flash("Failed to delete appointment", "err")
        return redirect(request.form.get("next") or url_for("appointments.index"))


@bp.route("/appointments/<appt_id>/edit", methods=["GET"], endpoint="edit")
@require_permission("appointments:edit")
def edit_appointment(appt_id):
    try:
        # Import here to avoid circular imports
        from clinic_app.services.appointments import get_appointment_by_id

        appointment = get_appointment_by_id(appt_id)
        if not appointment:
            flash("Appointment not found", "err")
            return redirect(url_for("appointments.index"))

        # Redirect to the existing form with pre-filled data
        return redirect(url_for("appointments.new",
                              day=appointment['starts_at'][:10],
                              doctor=appointment['doctor_id'],
                              appointment_id=appt_id))
    except Exception as exc:
        record_exception("appointments.edit", exc)
        flash("Failed to load appointment for editing", "err")
        return redirect(url_for("appointments.index"))





# Vanilla appointments template route
def _ensure_doctor_records() -> None:
    """Ensure doctors table exists and matches configured doctors."""
    engine = db.engine
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS doctors (
                    id TEXT PRIMARY KEY,
                    doctor_label TEXT NOT NULL,
                    color TEXT
                )
                """
            )
        )

    session = db.session()
    existing = {doc.id: doc for doc in session.query(DoctorModel).all()}
    configured_doctors = get_all_doctors_with_colors()
    if not configured_doctors:
        configured_doctors = [
            {"doctor_id": slug, "doctor_label": label, "color": None}
            for slug, label in doctor_choices()
        ]
    color_lookup = {
        entry.get("doctor_id"): entry.get("color")
        for entry in configured_doctors
        if entry.get("doctor_id")
    }

    for entry in configured_doctors:
        slug = entry.get("doctor_id")
        label = entry.get("doctor_label")
        color = entry.get("color")
        if not slug or slug == "all" or not label:
            continue
        doc = existing.get(slug)
        if doc:
            updated = False
            if doc.doctor_label != label:
                doc.doctor_label = label
                updated = True
            if color and doc.color != color:
                doc.color = color
                updated = True
            if updated:
                session.add(doc)
        else:
            session.add(DoctorModel(id=slug, doctor_label=label, color=color))

    # Backfill any doctor ids already referenced in appointments
    seen_ids = set(existing.keys())
    rows = session.execute(
        select(AppointmentModel.doctor_id, AppointmentModel.doctor_label).distinct()
    ).all()
    for doc_id, doc_label in rows:
        if not doc_id or doc_id == "all" or doc_id in seen_ids:
            continue
        session.add(
            DoctorModel(
                id=doc_id,
                doctor_label=doc_label or doc_id,
                color=color_lookup.get(doc_id),
            )
        )
        seen_ids.add(doc_id)

    session.commit()


@bp.route("/appointments/vanilla", methods=["GET"], endpoint="vanilla")
@require_permission("appointments:view")
def appointments_vanilla():
    """Render the server-side appointments dashboard."""
    try:
        _ensure_doctor_records()

        today = datetime.date.today()
        today_str = today.isoformat()
        yesterday_str = (today - datetime.timedelta(days=1)).isoformat()
        tomorrow_str = (today + datetime.timedelta(days=1)).isoformat()

        use_range = request.args.get("use_range")
        search_term = (request.args.get("search_term") or "").strip()
        doctor_id = request.args.get("doctor_id")
        day_param = request.args.get("day")
        raw_start_date = request.args.get("start_date")
        raw_end_date = request.args.get("end_date")

        if raw_start_date is None:
            start_date_filter = day_param or today_str
            start_date_value = start_date_filter
        elif raw_start_date == "":
            start_date_filter = None
            start_date_value = ""
        else:
            start_date_filter = raw_start_date
            start_date_value = raw_start_date

        if raw_end_date is None or raw_end_date == "":
            end_date_value = ""
            end_date_filter = None
        else:
            end_date_value = raw_end_date
            end_date_filter = raw_end_date



        query = (
            AppointmentModel.query.options(selectinload(AppointmentModel.patient))
            .outerjoin(PatientModel, AppointmentModel.patient_id == PatientModel.id)
        )

        if start_date_filter:
            start_dt = datetime.datetime.fromisoformat(start_date_filter)
            query = query.filter(AppointmentModel.start_time >= start_dt)
            if use_range == "on" and end_date_filter:
                end_dt = datetime.datetime.fromisoformat(end_date_filter) + datetime.timedelta(days=1)
            else:
                end_dt = datetime.datetime.fromisoformat(start_date_filter) + datetime.timedelta(days=1)
            query = query.filter(AppointmentModel.start_time < end_dt)

        deleted_ids = {d["doctor_id"] for d in get_deleted_doctors()}

        if doctor_id and doctor_id != "all":
            if doctor_id == ANY_DOCTOR_ID:
                ids = [ANY_DOCTOR_ID] + list(deleted_ids)
                query = query.filter(AppointmentModel.doctor_id.in_(ids))
            else:
                query = query.filter(AppointmentModel.doctor_id == doctor_id)

        if search_term:
            normalized_term = normalize_search_query(search_term)
            like = f"%{normalized_term}%"
            query = query.filter(
                or_(
                    PatientModel.full_name.ilike(like),
                    PatientModel.phone.ilike(like),
                    PatientModel.short_id.ilike(like),
                )
            )

        filtered_appts = query.order_by(AppointmentModel.start_time.asc()).all()

        # For deleted doctors, treat their schedules as "Any Doctor" in the UI
        for appt in filtered_appts:
            if appt.doctor_id in deleted_ids:
                appt.doctor_id = ANY_DOCTOR_ID
                appt.doctor_label = ANY_DOCTOR_LABEL

        grouped_appointments: dict[str, list[AppointmentModel]] = defaultdict(list)
        for appt in filtered_appts:
            if not appt.start_time:
                continue
            grouped_appointments[appt.start_time.date().isoformat()].append(appt)

        ordered_grouped = dict(sorted(grouped_appointments.items()))

        all_patients = PatientModel.query.order_by(PatientModel.full_name.asc()).all()
        doctor_options = get_all_doctors_with_colors()
        if not doctor_options:
            doctor_options = [
                {"doctor_id": "all", "doctor_label": "All Doctors", "color": "#6B7280"}
            ]

        doctor_color_map: dict[str, str] = {}
        default_doctor_color = DEFAULT_DOCTOR_COLOR
        for doc in doctor_options:
            doc_id = doc.get("doctor_id")
            if not doc_id or doc_id == "all":
                continue
            color = doc.get("color") or default_doctor_color
            doctor_color_map[doc_id] = color

        return render_page(
            "appointments/vanilla.html",
            title="Appointments",
            grouped_appointments=ordered_grouped,
            doctors=doctor_options,
            all_patients=all_patients,
            today_str=today_str,
            yesterday_str=yesterday_str,
            tomorrow_str=tomorrow_str,
            use_range=use_range,
            selected_doctor=doctor_id or "all",
            start_date_value=start_date_value,
            end_date_value=end_date_value if use_range == "on" else "",
            doctor_color_map=doctor_color_map,
            default_doctor_color=default_doctor_color,
        )

    except Exception as exc:
        record_exception("appointments.vanilla", exc)
        today = datetime.date.today()
        return (
            render_page(
                "appointments/vanilla.html",
                title="Appointments",
                grouped_appointments={},
                doctors=get_all_doctors_with_colors(),
                all_patients=[],
                today_str=today.isoformat(),
                yesterday_str=(today - datetime.timedelta(days=1)).isoformat(),
                tomorrow_str=(today + datetime.timedelta(days=1)).isoformat(),
                use_range=request.args.get("use_range"),
                selected_doctor=request.args.get("doctor_id") or "all",
                doctor_color_map={},
                default_doctor_color=DEFAULT_DOCTOR_COLOR,
                start_date_value=request.args.get("start_date") or today.isoformat(),
                end_date_value=request.args.get("end_date") or "",
            ),
            500,
        )


# API endpoints for SSR template
@bp.route("/api/appointments/<int:appt_id>", methods=["GET"])
@bp.route("/api/appointments/<appt_id>", methods=["GET"])
@require_permission("appointments:view")
def api_get_appointment(appt_id):
    """Return appointment details for view/edit modals."""
    _ensure_doctor_records()
    appt_key = str(appt_id)
    appt = (
        AppointmentModel.query.options(
            selectinload(AppointmentModel.patient),
            selectinload(AppointmentModel.doctor),
        )
        .filter(AppointmentModel.id == appt_key)
        .first()
    )
    if not appt:
        abort(404)

    patient = appt.patient
    doctor = appt.doctor
    return jsonify(
        {
            "id": appt.id,
            "patient_id": patient.id if patient else appt.patient_id,
            "patient_name": patient.full_name if patient else appt.patient_name,
            "patient_short_id": patient.short_id if patient else None,
            "doctor_id": doctor.id if doctor else appt.doctor_id,
            "doctor_name": doctor.doctor_label if doctor else appt.doctor_label,
            "doctor_label": appt.doctor_label,
            "status": appt.status,
            "title": appt.title,
            "notes": appt.notes,
            "start_time": appt.start_time.isoformat() if appt.start_time else None,
            "end_time": appt.end_time.isoformat() if appt.end_time else None,
        }
    )


@csrf.exempt
@bp.route("/api/appointments/save", methods=["POST"])
@require_permission("appointments:edit")
def api_save_appointment():
    """Create or update an appointment."""
    _ensure_doctor_records()
    session = db.session()
    data = request.get_json() or {}
    appt_id = data.get("id")
    patient_id = data.get("patient_id")
    doctor_id = data.get("doctor_id")
    day = data.get("date")
    start_time_value = data.get("start_time")
    status = _normalize_status(data.get("status"))
    title = (data.get("title") or "Appointment").strip()
    notes = data.get("notes")

    if not all([patient_id, doctor_id, day, start_time_value]):
        return jsonify({"success": False, "error": "Missing required fields."}), 400

    try:
        start_dt = datetime.datetime.fromisoformat(f"{day}T{start_time_value}")
    except ValueError:
        return jsonify({"success": False, "error": "Invalid date or time."}), 400
    end_dt = start_dt + datetime.timedelta(minutes=30)

    try:
        patient = PatientModel.query.filter_by(id=patient_id).first()
        if not patient:
            return jsonify({"success": False, "error": "Invalid patient."}), 400

        doctor = DoctorModel.query.filter_by(id=doctor_id).first()
        if not doctor:
            doctor_entries = get_all_doctors_with_colors()
            doctor_label = None
            for entry in doctor_entries:
                if entry.get("doctor_id") == doctor_id:
                    doctor_label = entry.get("doctor_label")
                    break
            if not doctor_label:
                doctor_label = doctor_id
            doctor = DoctorModel(id=doctor_id, doctor_label=doctor_label)
            session.add(doctor)

        conflict_query = AppointmentModel.query.filter(
            AppointmentModel.doctor_id == doctor.id,
            AppointmentModel.start_time < end_dt,
            AppointmentModel.end_time > start_dt,
        )
        if appt_id:
            conflict_query = conflict_query.filter(AppointmentModel.id != str(appt_id))
        conflict = conflict_query.first()
        if conflict:
            conflict_time = conflict.start_time.strftime("%I:%M %p")
            conflict_date = conflict.start_time.strftime("%B %d, %Y")
            return jsonify(
                {
                    "success": False,
                    "error": f"{doctor.doctor_label} already has an appointment at {conflict_time} on {conflict_date}.",
                }
            ), 409

        if appt_id:
            appt = AppointmentModel.query.filter_by(id=str(appt_id)).first()
            if not appt:
                return jsonify({"success": False, "error": "Appointment not found."}), 404
        else:
            appt = AppointmentModel(id=uuid4().hex)

        appt.patient = patient
        appt.patient_id = patient.id
        appt.patient_name = patient.full_name
        appt.patient_phone = patient.phone
        appt.doctor = doctor
        appt.doctor_id = doctor.id
        appt.doctor_label = doctor.doctor_label
        appt.title = title
        appt.status = status
        appt.notes = notes
        appt.start_time = start_dt
        appt.end_time = end_dt
        current_ts = datetime.datetime.utcnow()
        if not appt.created_at:
            appt.created_at = current_ts
        appt.updated_at = current_ts

        session.add(appt)
        session.commit()
        session.refresh(appt)
        return jsonify({"success": True, "id": appt.id, "appointment": _serialize_appointment(appt)})

    except Exception as exc:
        session.rollback()
        record_exception("appointments.save", exc)
        return jsonify({"success": False, "error": "Server error while saving appointment."}), 500


@csrf.exempt
@bp.route("/api/appointments/delete", methods=["POST"])
@require_permission("appointments:edit")
def api_delete_appointment():
    """Delete an appointment."""
    session = db.session()
    data = request.get_json() or {}
    appt_id = data.get("id")
    if not appt_id:
        return jsonify({"success": False, "error": "Missing appointment id."}), 400

    try:
        appt = AppointmentModel.query.filter_by(id=str(appt_id)).first()
        if not appt:
            return jsonify({"success": False, "error": "Appointment not found."}), 404

        session.delete(appt)
        session.commit()
        return jsonify({"success": True, "id": appt_id})
    except Exception as exc:
        session.rollback()
        record_exception("appointments.delete", exc)
        return jsonify({"success": False, "error": "Server error while deleting appointment."}), 500


@csrf.exempt
@bp.route("/api/appointments/status", methods=["POST"])
@require_permission("appointments:edit")
def api_update_status():
    """Update appointment status."""
    session = db.session()
    data = request.get_json() or {}
    appt_id = data.get("id")
    status = _normalize_status(data.get("status"))
    if not appt_id or not status:
        return jsonify({"success": False, "error": "Missing id or status."}), 400

    try:
        appt = AppointmentModel.query.filter_by(id=str(appt_id)).first()
        if not appt:
            return jsonify({"success": False, "error": "Appointment not found."}), 404

        appt.status = status
        session.commit()
        return jsonify({"success": True, "status": status})
    except Exception as exc:
        session.rollback()
        record_exception("appointments.status", exc)
        return jsonify({"success": False, "error": "Server error while updating status."}), 500


@bp.route("/api/patients/search", methods=["GET"])
@require_permission("appointments:edit")
def api_patients_search():
    """Search patients for autocomplete in appointment creation."""
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify([])

    # Normalize Arabic characters for better matching
    normalized_q = normalize_search_query(query)

    # Search patients by name, phone, or short_id
    patients = PatientModel.query.filter(
        or_(
            PatientModel.full_name.ilike(f"%{normalized_q}%"),
            PatientModel.phone.ilike(f"%{normalized_q}%"),
            PatientModel.short_id.ilike(f"%{normalized_q}%"),
        )
    ).limit(10).all()

    results = []
    for patient in patients:
        results.append({
            "id": patient.id,
            "name": patient.full_name,
            "file_number": patient.short_id,
            "phone_number": patient.phone,
        })

    return jsonify(results)
def _serialize_appointment(appt: AppointmentModel) -> dict[str, str | None]:
    """Serialize an appointment for JSON responses."""
    patient = appt.patient
    doctor = appt.doctor
    start_time = appt.start_time or datetime.datetime.utcnow()
    end_time = appt.end_time or start_time
    date_iso = start_time.date().isoformat()
    return {
        "id": appt.id,
        "patient_id": patient.id if patient else appt.patient_id,
        "patient_name": patient.full_name if patient else appt.patient_name,
        "patient_short_id": patient.short_id if patient else None,
        "patient_phone": patient.phone if patient else appt.patient_phone,
        "doctor_id": doctor.id if doctor else appt.doctor_id,
        "doctor_label": doctor.doctor_label if doctor else appt.doctor_label,
        "doctor_color": (doctor.color if doctor and doctor.color else DEFAULT_DOCTOR_COLOR),
        "title": appt.title,
        "notes": appt.notes,
        "status": appt.status,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "time_display": start_time.strftime("%I:%M %p"),
        "date_iso": date_iso,
        "date_display": start_time.strftime("%A, %B %d, %Y"),
    }
