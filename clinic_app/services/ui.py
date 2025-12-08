"""UI helper utilities shared across blueprints."""

from __future__ import annotations

import time
from typing import Any

from flask import g, render_template, request, session, url_for
from flask_wtf.csrf import generate_csrf

from .i18n import T, dir_attr, get_lang
from .security import user_has_permission
from .theme_settings import get_theme_variables


def remember_last_get() -> None:
    """Persist the last GET request so "back" links can return users."""
    try:
        if request.method == "GET" and request.endpoint != "static":
            session["last_get_url"] = request.full_path if request.query_string else request.path
    except Exception:
        # Failing to store the last URL should never break the request cycle.
        pass


def last_get_url(default_path: str = "/") -> str:
    url = session.get("last_get_url") or default_path
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}_ts={int(time.time())}"


def back_url(p: Any = None) -> str:
    try:
        if request.endpoint == "patients.patient_detail":
            return url_for("index", _ts=int(time.time()))
        if p is not None:
            pid = None
            try:
                if isinstance(p, dict):
                    pid = p.get("id") or p.get("ID")
                else:
                    try:
                        pid = p["id"] if hasattr(p, "__getitem__") else None
                    except Exception:
                        pid = getattr(p, "id", None)
            except Exception:
                pid = getattr(p, "id", None)
            if pid:
                return url_for("patients.patient_detail", pid=pid, _ts=int(time.time()))
    except Exception:
        pass
    return url_for("index", _ts=int(time.time()))


def back_to_home_url() -> str:
    return url_for("index", _ts=int(time.time()))


def render_page(template_name: str, **ctx: Any):
    lang = get_lang()
    show_back = ctx.pop("show_back", False)
    theme_vars = get_theme_variables()

    theme_css_parts = []
    if theme_vars:
        overrides = []
        primary = theme_vars.get("primary_color")
        accent = theme_vars.get("accent_color")
        base_font = theme_vars.get("base_font_size")
        text_color = theme_vars.get("text_color")
        if primary:
            overrides.append(f"--primary-color: {primary};")
        if accent:
            overrides.append(f"--accent-color: {accent};")
        if base_font:
            try:
                size_val = int(float(base_font))
                clamped = max(14, min(size_val, 18))
                overrides.append(f"font-size: clamp(14px, {clamped}px, 18px);")
            except Exception:
                pass
        if text_color:
            overrides.append(f"--ink: {text_color};")
            overrides.append(f"--text-primary: {text_color};")
        if overrides:
            theme_css_parts.append(":root { " + " ".join(overrides) + " }")
    theme_css = "\n".join(theme_css_parts) if theme_css_parts else None

    theme_logo_url = None
    logo_path = theme_vars.get("logo_path") if theme_vars else None
    if logo_path:
        try:
            theme_logo_url = url_for("admin_settings.theme_logo", _ts=int(time.time()))
        except Exception:
            theme_logo_url = None

    # Clinic brand settings (optional text next to logo)
    clinic_brand_color = theme_vars.get("clinic_brand_color") if theme_vars else None
    clinic_name = theme_vars.get("clinic_name") if theme_vars else ""
    clinic_name_enabled = False
    clinic_tagline = theme_vars.get("clinic_tagline") if theme_vars else ""
    clinic_tagline_enabled = False
    logo_scale = 100
    pdf_logo_url = None
    if theme_vars:
        raw = theme_vars.get("clinic_name_enabled", "")
        clinic_name_enabled = str(raw).lower() in {"1", "true", "yes", "on"}
        tag_raw = theme_vars.get("clinic_tagline_enabled", "")
        clinic_tagline_enabled = str(tag_raw).lower() in {"1", "true", "yes", "on"}
        try:
            logo_scale = int(float(theme_vars.get("logo_scale", 100)))
        except Exception:
            logo_scale = 100
        logo_scale = max(60, min(logo_scale, 140))
        pdf_logo_path = theme_vars.get("pdf_logo_path")
        if pdf_logo_path:
            try:
                pdf_logo_url = url_for("admin_settings.theme_pdf_logo", _external=False)
            except Exception:
                pdf_logo_url = None

    return render_template(
        template_name,
        lang=lang,
        dir=dir_attr(lang),
        t=T,
        show_back=show_back,
        current_user=getattr(g, "current_user", None),
        user_has_permission=user_has_permission,
        theme_css=theme_css,
        theme_logo_url=theme_logo_url,
        clinic_name=clinic_name,
        clinic_name_enabled=clinic_name_enabled,
        clinic_brand_color=clinic_brand_color,
        clinic_tagline=clinic_tagline,
        clinic_tagline_enabled=clinic_tagline_enabled,
        logo_scale=logo_scale,
        pdf_logo_url=pdf_logo_url,
        **ctx,
    )


def register_ui(app) -> None:
    """Attach UI helpers to the Flask app instance."""
    app.before_request(remember_last_get)
    app.jinja_env.globals.setdefault("last_get_url", last_get_url)
    app.jinja_env.globals.setdefault("back_url", back_url)
    app.jinja_env.globals.setdefault("back_to_home_url", back_to_home_url)
    app.jinja_env.globals.setdefault("csrf_token", generate_csrf)
    app.jinja_env.globals.setdefault("user_has_permission", user_has_permission)
