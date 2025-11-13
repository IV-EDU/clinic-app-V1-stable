"""Move appointments API route for drag and drop functionality."""

from __future__ import annotations

from flask import Blueprint, jsonify, request, redirect, url_for
from werkzeug.exceptions import BadRequest

from clinic_app.services.appointments import (
    AppointmentError,
    AppointmentNotFound,
    AppointmentOverlap,
    move_appointment_slot,
)
from clinic_app.services.errors import record_exception
from clinic_app.services.security import require_permission

bp = Blueprint("appointment_move", __name__, url_prefix="/appointments")


@bp.route("/", methods=["GET"])
@require_permission("appointments:view")
def index():
    """Redirect to appointments view."""
    return redirect(url_for("appointments.index"))


@bp.route("/move", methods=["POST"])
@require_permission("appointments:edit")
def move_appointment():
    """Handle drag and drop movement of appointments between doctors/time slots."""

    payload = request.get_json(silent=True) or {}
    appointment_id = (payload.get("appointment_id") or "").strip()
    target_doctor = (payload.get("target_doctor") or "").strip()
    target_time = (payload.get("target_time") or "").strip()

    if not appointment_id or not target_doctor or not target_time:
        raise BadRequest("Missing required fields: appointment_id, target_doctor, target_time")

    try:
        updated = move_appointment_slot(
            appointment_id,
            target_doctor=target_doctor,
            target_time=target_time,
        )
    except AppointmentOverlap:
        return (
            jsonify({"success": False, "error": "Another visit already occupies this slot."}),
            409,
        )
    except AppointmentNotFound:
        return jsonify({"success": False, "error": "Appointment not found."}), 404
    except AppointmentError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:  # pragma: no cover - defensive logging
        record_exception("appointment.move", exc)
        return jsonify({"success": False, "error": "Internal server error"}), 500

    return jsonify({"success": True, "appointment": updated})
