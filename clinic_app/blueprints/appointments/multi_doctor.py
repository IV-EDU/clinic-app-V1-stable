"""Multi-doctor appointments view."""

from datetime import date, timedelta

from flask import Blueprint, request, redirect, url_for

from clinic_app.services.ui import render_page
from clinic_app.services.appointments import list_for_day, doctor_choices
from clinic_app.services.doctor_colors import get_doctor_colors
from clinic_app.services.security import require_permission
from clinic_app.services.i18n import T

bp = Blueprint("multi_doctor", __name__)


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


def _search_query() -> str:
    return (request.args.get("q") or "").strip()


@bp.route("/", methods=["GET"])
@require_permission("appointments:view")
def index():
    """Redirect to multi-doctor view."""
    return redirect(url_for("multi_doctor.multi_doctor"))


@bp.route("/appointments/multi-doctor", methods=["GET"], endpoint="multi_doctor")
@require_permission("appointments:view")
def multi_doctor_view():
    try:
        day = request.args.get("day") or date.today().isoformat()
        range_key = request.args.get("range") or "today"
        search = _search_query()
        show_mode = (request.args.get("show") or "upcoming").lower()
        if show_mode not in _SHOW_PRESETS:
            show_mode = "upcoming"
        range_key, end_day = _resolve_range(day, range_key)
        
        # Get all doctors
        doctors = doctor_choices()
        
        range_label = _choice_label(range_key, _range_choices(), T("appointments_range_today"))
        show_label = _choice_label(show_mode, _show_choices(), T("appointments_show_upcoming"))
        # Get appointments for all doctors
        all_appointments = {}
        for doctor_id, doctor_label in doctors:
            appointments = list_for_day(
                day,
                doctor_id=doctor_id,
                end_day=end_day,
                search=search or None,
                show=show_mode,
            )
            appointments.sort(key=lambda appt: appt.get("starts_at") or "")
            all_appointments[doctor_id] = {
                "label": doctor_label,
                "appointments": appointments,
            }
        
        return render_page(
            "appointments/multi_doctor.html",
            day=day,
            doctors=doctors,
            doctor_colors=get_doctor_colors(),
            all_appointments=all_appointments,
            selected_range=range_key,
            selected_range_label=range_label,
            selected_show=show_mode,
            selected_show_label=show_label,
            range_choices=_range_choices(),
            show_choices=_show_choices(),
            search_query=search,
            current_view="multi",
            show_back=True,
        )
    except Exception as exc:  # pragma: no cover
        from clinic_app.services.errors import record_exception
        record_exception("multi_doctor.view", exc)
        raise
