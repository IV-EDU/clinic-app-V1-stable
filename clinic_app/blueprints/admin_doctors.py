"""Admin interface for doctor management including colors."""

from __future__ import annotations

import re

from flask import Blueprint, flash, redirect, render_template, request, url_for

from clinic_app.services.appointments import doctor_choices
from clinic_app.services.doctor_colors import (
    DEFAULT_COLORS,
    delete_doctor_color,
    get_all_doctors_with_colors,
    init_doctor_colors_table,
    set_doctor_color,
)
from clinic_app.services.security import require_permission

bp = Blueprint("admin_doctors", __name__, url_prefix="/admin/doctors")

_HEX_COLOR = re.compile(r"^#([0-9a-fA-F]{6})$")


def _valid_color(value: str) -> bool:
    return bool(_HEX_COLOR.fullmatch(value or ""))


def _known_doctors() -> dict[str, str]:
    return {slug: label for slug, label in doctor_choices()}


@bp.route("/", methods=["GET"])
@require_permission("admin.user.manage")
def index():
    """Redirect to doctor colors management."""
    return redirect(url_for("admin_doctors.doctor_colors"))


@bp.route("/colors", methods=["GET", "POST"])
@require_permission("admin.user.manage")
def doctor_colors():
    init_doctor_colors_table()
    if request.method == "POST":
        doctor_id = (request.form.get("doctor_id") or "").strip()
        action = request.form.get("action") or "update_color"
        doctors = _known_doctors()
        if doctor_id not in doctors:
            flash("Unknown doctor identifier.", "err")
            return redirect(url_for("admin_doctors.doctor_colors"))

        if action == "delete_color":
            delete_doctor_color(doctor_id)
            flash(f"{doctors[doctor_id]} color reset to default.", "ok")
        else:
            color = (request.form.get("color") or "").strip()
            if not _valid_color(color):
                flash("Invalid color value.", "err")
            else:
                set_doctor_color(doctor_id, color)
                flash(f"{doctors[doctor_id]} color updated.", "ok")
        return redirect(url_for("admin_doctors.doctor_colors"))

    doctors = get_all_doctors_with_colors()
    return render_template("admin/doctors/colors.html", doctors=doctors)


@bp.route("/colors/reset", methods=["POST"])
@require_permission("admin.user.manage")
def reset_colors():
    """Reset all doctor colors to defaults."""

    doctors = _known_doctors()
    for doctor_id, color in DEFAULT_COLORS.items():
        if doctor_id in doctors and doctor_id != "default":
            set_doctor_color(doctor_id, color)
    flash("All doctor colors reset to defaults.", "ok")
    return redirect(url_for("admin_doctors.doctor_colors"))
