from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, flash, g, redirect, request, url_for, jsonify

from clinic_app.services.appointments import (
    AppointmentError,
    AppointmentOverlap,
    AppointmentNotFound,
    create_appointment,
    doctor_choices,
    list_for_day,
    update_appointment,
    update_status,
    format_time_range,
    get_multi_doctor_schedule,
    get_date_cards_for_range,
    auto_generate_time_slot,
    validate_time_slot_overlap,
    get_consecutive_slots,
)
from clinic_app.services.doctor_colors import get_doctor_colors
from clinic_app.services.i18n import T
from clinic_app.services.security import require_permission
from clinic_app.services.ui import render_page
from clinic_app.services.errors import record_exception

bp = Blueprint("appointments", __name__)


def _selected_day() -> str:
    return request.args.get("day") or date.today().isoformat()


_RANGE_PRESETS = {
    "today": 0,
    "next3": 3,
    "next7": 7,
    "all": None,
}

_SHOW_PRESETS = {"upcoming", "past", "all"}


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
        ("today", T("appointments_range_today")),
        ("next3", T("appointments_range_next3")),
        ("next7", T("appointments_range_next7")),
        ("all", T("appointments_range_all")),
    ]


def _show_choices() -> list[tuple[str, str]]:
    return [
        ("upcoming", T("appointments_show_upcoming")),
        ("past", T("appointments_show_past")),
        ("all", T("appointments_show_all")),
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
    """Main appointments page - defaults to simplified view."""
    try:
        day = _selected_day()
        # Default to simplified view
        return redirect(url_for("appointments.simple_view", day=day))
    except Exception as exc:
        record_exception("appointments.index", exc)
        raise




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
    try:
        day = _selected_day()
        doctor = request.args.get("doctor") or "all"
        range_key = request.args.get("range") or "today"
        search = _search_query()
        show_mode = (request.args.get("show") or "upcoming").lower()
        if show_mode not in _SHOW_PRESETS:
            show_mode = "upcoming"
        doctor_id = doctor if doctor != "all" else None
        range_key, end_day = _resolve_range(day, range_key)
        range_label = _choice_label(range_key, _range_choices(), T("appointments_range_today"))
        show_label = _choice_label(show_mode, _show_choices(), T("appointments_show_upcoming"))
        try:
            appts = list_for_day(day, doctor_id=doctor_id, end_day=end_day, search=search or None, show=show_mode)
            status_counts: dict[str, int] = {}
            for appt in appts:
                status_counts[appt["status"]] = status_counts.get(appt["status"], 0) + 1
            stats = [
                ("appointments_total_label", len(appts)),
                ("appointment_status_scheduled", status_counts.get("scheduled", 0)),
                ("appointment_status_done", status_counts.get("done", 0)),
            ]
        except AppointmentError as exc:
            flash(T(str(exc)), "err")
            appts = []
            stats = []
        doctor_colors = get_doctor_colors()
        try:
            date_cards = get_date_cards_for_range(day, end_day or None, doctor if doctor != "all" else None)
        except AppointmentError:
            date_cards = []
        return render_page(
            "appointments/table_view_pro.html",
            day=day,
            doctor=doctor,
            doctors=[("all", T("appointments_doctor_all"))] + doctor_choices(),
            appts=appts,
            stats=stats,
            selected_doctor=doctor,
            selected_show=show_mode,
            show_choices=_show_choices(),
            selected_show_label=show_label,
            show_mode=show_mode,
            search_query=search,
            selected_range=range_key,
            range_choices=_range_choices(),
            range_label=range_label,
            end_day=end_day,
            date_cards=date_cards,
            doctor_colors=doctor_colors,
            current_view="table",
            show_back=True,
        )
    except Exception as exc:
        record_exception("appointments.table", exc)
        raise


@bp.route("/appointments/new", methods=["GET", "POST"], endpoint="new")
@require_permission("appointments:edit")
def new_appointment():
    try:
        day = request.args.get("day") or date.today().isoformat()
        doctor = request.args.get("doctor") or doctor_choices()[0][0]
        appointment_id = request.form.get("appointment_id") if request.method == "POST" else request.args.get("appointment_id")
        editing = bool(appointment_id)
        patient_card = None
        existing = None
        if editing:
            from clinic_app.services.appointments import get_appointment_by_id

            existing = get_appointment_by_id(appointment_id)
            if existing:
                day = existing["starts_at"][:10]
                doctor = existing["doctor_id"]
                patient_card = {
                    "id": existing.get("patient_id"),
                    "name": existing.get("patient_name"),
                    "phone": existing.get("patient_phone"),
                    "short_id": existing.get("patient_short_id"),
                }
            else:
                editing = False
                appointment_id = None
        if request.method == "POST":
            try:
                actor = getattr(g, "current_user", None)
                if appointment_id:
                    update_appointment(appointment_id, request.form.to_dict(), actor_id=getattr(actor, "id", None))
                else:
                    appointment_id = create_appointment(request.form.to_dict(), actor_id=getattr(actor, "id", None))
                flash(T("appointments_submit"), "ok")
                return redirect(url_for("appointments.index", day=request.form.get("day") or day))
            except AppointmentOverlap:
                flash(T("appointment_conflict"), "err")
                form_defaults = request.form.to_dict()
                card_ctx = patient_card
                if not card_ctx and form_defaults.get("patient_id"):
                    card_ctx = {
                        "id": form_defaults.get("patient_id"),
                        "name": form_defaults.get("patient_name"),
                        "phone": form_defaults.get("patient_phone"),
                        "short_id": form_defaults.get("patient_short_id"),
                    }
                return (
                    render_page(
                        "appointments/form.html",
                        doctors=doctor_choices(),
                        defaults=form_defaults,
                        editing=editing,
                        patient_card=card_ctx,
                        show_back=True,
                    ),
                    409,
                )
            except AppointmentError as exc:
                flash(T(str(exc)), "err")
                form_defaults = request.form.to_dict()
                card_ctx = patient_card
                if not card_ctx and form_defaults.get("patient_id"):
                    card_ctx = {
                        "id": form_defaults.get("patient_id"),
                        "name": form_defaults.get("patient_name"),
                        "phone": form_defaults.get("patient_phone"),
                        "short_id": form_defaults.get("patient_short_id"),
                    }
                return (
                    render_page(
                        "appointments/form.html",
                        doctors=doctor_choices(),
                        defaults=form_defaults,
                        editing=editing,
                        patient_card=card_ctx,
                        show_back=True,
                    ),
                    400,
                )
            except AppointmentNotFound:
                flash(T("appointment_not_found") if T("appointment_not_found") != "appointment_not_found" else "Appointment not found", "err")
                return redirect(url_for("appointments.index", day=day))
        defaults = {
            "day": day,
            "start_time": request.args.get("start_time") or "09:00",
            "doctor_id": doctor,
            "appointment_id": appointment_id,
        }
        if existing:
            defaults.update(
                {
                    "start_time": existing["starts_at"][11:16],
                    "doctor_id": existing["doctor_id"],
                    "title": existing.get("title"),
                    "notes": existing.get("notes"),
                    "patient_id": existing.get("patient_id"),
                    "patient_name": existing.get("patient_name"),
                    "patient_phone": existing.get("patient_phone"),
                    "patient_short_id": existing.get("patient_short_id"),
                }
            )
        if not patient_card and defaults.get("patient_id"):
            patient_card = {
                "id": defaults.get("patient_id"),
                "name": defaults.get("patient_name"),
                "phone": defaults.get("patient_phone"),
                "short_id": defaults.get("patient_short_id"),
            }
        return render_page(
            "appointments/form.html",
            doctors=doctor_choices(),
            defaults=defaults,
            editing=editing,
            patient_card=patient_card,
            show_back=True,
        )
    except Exception as exc:
        record_exception("appointments.new", exc)
        raise


@bp.route("/appointments/<appt_id>/status", methods=["POST"], endpoint="status")
@require_permission("appointments:edit")
def change_status(appt_id):
    try:
        print(f"DEBUG: Status change request for appointment {appt_id}")
        print(f"DEBUG: Request method: {request.method}")
        print(f"DEBUG: Request form data: {dict(request.form)}")
        print(f"DEBUG: Request headers: {dict(request.headers)}")

        new_status = (request.form.get("status") or request.json.get("status") if request.is_json else None) or "scheduled"
        print(f"DEBUG: New status: {new_status}")

        try:
            update_status(appt_id, new_status)
            print(f"DEBUG: Status update successful")
            # JSON/Fetch clients
            wants_json = request.is_json or "application/json" in (request.headers.get("Accept") or "")
            if wants_json:
                return jsonify({"ok": True, "status": new_status})
            flash(T("appointment_status_" + new_status), "ok")
        except AppointmentError as exc:
            print(f"DEBUG: AppointmentError: {exc}")
            wants_json = request.is_json or "application/json" in (request.headers.get("Accept") or "")
            if wants_json:
                return jsonify({"ok": False, "error": str(exc)}), 400
            flash(T(str(exc)), "err")
        return redirect(request.form.get("next") or url_for("appointments.index"))
    except Exception as exc:
        print(f"DEBUG: Exception in status change: {exc}")
        record_exception("appointments.status", exc)
        wants_json = request.is_json or "application/json" in (request.headers.get("Accept") or "")
        if wants_json:
            return jsonify({"ok": False, "error": "server_error"}), 500
        raise


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


@bp.route("/appointments/multi-doctor", methods=["GET"], endpoint="multi_doctor")
@require_permission("appointments:view")
def appointments_multi_doctor():
    """Clean multi-doctor view showing all doctors' schedules side by side."""
    try:
        day = _selected_day()
        range_key = request.args.get("range") or "today"
        search = _search_query()
        show_mode = (request.args.get("show") or "upcoming").lower()
        if show_mode not in _SHOW_PRESETS:
            show_mode = "upcoming"
        range_key, end_day = _resolve_range(day, range_key)
        range_label = _choice_label(range_key, _range_choices(), T("appointments_range_today"))
        show_label = _choice_label(show_mode, _show_choices(), T("appointments_show_upcoming"))
        all_appointments = get_multi_doctor_schedule(day, end_day, search or None, show_mode)
        doctor_colors = get_doctor_colors()
        try:
            date_cards = get_date_cards_for_range(day, end_day or None, None)
        except AppointmentError:
            date_cards = []

        return render_page(
            "appointments/multi_doctor_pro.html",
            day=day,
            end_day=end_day,
            all_appointments=all_appointments,
            doctor_colors=doctor_colors,
            selected_range=range_key,
            range_label=range_label,
            range_choices=_range_choices(),
            selected_show=show_mode,
            selected_show_label=show_label,
            show_choices=_show_choices(),
            search_query=search,
            date_cards=date_cards,
            current_view="multidoctor",
            show_back=True,
        )
    except Exception as exc:
        record_exception("appointments.multi_doctor", exc)
        raise


# API endpoints for enhanced functionality

@bp.route("/api/appointments/consecutive-slots", methods=["GET"], endpoint="api_consecutive_slots")
@require_permission("appointments:view")
def api_consecutive_slots():
    """API endpoint to get consecutive available time slots for a doctor."""
    try:
        doctor_id = request.args.get("doctor_id")
        day = request.args.get("day")
        start_time = request.args.get("start_time", "09:00")
        count = int(request.args.get("count", 3))

        if not doctor_id or not day:
            return jsonify({"error": "doctor_id and day are required"}), 400

        slots = get_consecutive_slots(doctor_id, day, start_time, count)
        return jsonify({"slots": slots})
    except Exception as exc:
        record_exception("api.consecutive_slots", exc)
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/api/appointments/validate-slot", methods=["GET"], endpoint="api_validate_slot")
@require_permission("appointments:view")
def api_validate_slot():
    """API endpoint to validate if a time slot is available."""
    try:
        doctor_id = request.args.get("doctor_id")
        day = request.args.get("day")
        start_time = request.args.get("start_time")
        end_time = request.args.get("end_time")
        exclude_appointment_id = request.args.get("exclude_id")

        if not all([doctor_id, day, start_time, end_time]):
            return jsonify({"error": "doctor_id, day, start_time, and end_time are required"}), 400

        has_conflict = validate_time_slot_overlap(doctor_id, start_time, end_time, day, exclude_appointment_id)
        return jsonify({"available": not has_conflict})
    except Exception as exc:
        record_exception("api.validate_slot", exc)
        return jsonify({"error": "Internal server error"}), 500


@bp.route("/api/appointments/auto-generate-end", methods=["GET"], endpoint="api_auto_generate_end")
@require_permission("appointments:view")
def api_auto_generate_end():
    """API endpoint to auto-generate end time from start time."""
    try:
        start_time = request.args.get("start_time")
        duration_minutes = request.args.get("duration")

        if not start_time:
            return jsonify({"error": "start_time is required"}), 400

        duration = int(duration_minutes) if duration_minutes else None
        end_time = auto_generate_time_slot(start_time, duration)
        return jsonify({"end_time": end_time})
    except Exception as exc:
        record_exception("api.auto_generate_end", exc)
        return jsonify({"error": "Internal server error"}), 500
