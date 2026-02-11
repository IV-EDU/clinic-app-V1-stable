"""UI helper utilities shared across blueprints."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

from flask import g, render_template, request, session, url_for
from flask_wtf.csrf import generate_csrf

from .i18n import T, dir_attr, get_lang
from .security import user_has_permission
from .theme_settings import get_theme_variables
from .patient_pages import AdminSettingsService


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


def _safe_internal_url(raw: str | None, default: str = "/") -> str:
    if not raw:
        return default
    try:
        val = str(raw).strip()
    except Exception:
        return default
    if not val:
        return default
    try:
        parsed = urlparse(val)
    except Exception:
        return default
    if parsed.scheme or parsed.netloc:
        return default
    if not val.startswith("/"):
        return default
    path = parsed.path or "/"
    if not path.startswith("/"):
        return default
    if parsed.query:
        return f"{path}?{parsed.query}"
    return path


def back_url(p: Any = None) -> str:
    try:
        if request.endpoint == "patients.patient_detail":
            return_to = _safe_internal_url(request.args.get("return_to"), default="")
            if return_to:
                session["patients_home_return_url"] = return_to
                sep = "&" if "?" in return_to else "?"
                return f"{return_to}{sep}_ts={int(time.time())}"
            remembered = _safe_internal_url(session.get("patients_home_return_url"), default="")
            if remembered:
                sep = "&" if "?" in remembered else "?"
                return f"{remembered}{sep}_ts={int(time.time())}"
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
    lang_override = str(ctx.pop("lang_override", "") or "").strip().lower()
    if lang_override in ("en", "ar"):
        lang = lang_override
    else:
        lang = get_lang()
    t_override = ctx.pop("t_override", None)
    translator = t_override if callable(t_override) else T
    show_back = ctx.pop("show_back", False)
    theme_vars = get_theme_variables()

    # Global toggle: whether file number + page number fields are shown.
    try:
        settings = AdminSettingsService.get_all_settings()
        raw_flag = settings.get("enable_file_numbers", True)
        if isinstance(raw_flag, str):
            show_file_numbers = raw_flag.lower() == "true"
        else:
            show_file_numbers = bool(raw_flag)
    except Exception:
        show_file_numbers = True

    theme_css_parts = []
    if theme_vars:
        overrides = []
        primary = theme_vars.get("primary_color")
        accent = theme_vars.get("accent_color")
        base_font = theme_vars.get("base_font_size")
        text_color = theme_vars.get("text_color")
        btn_text_color = theme_vars.get("btn_text_color")
        metric_text_color = theme_vars.get("metric_text_color")
        page_bg_tint = theme_vars.get("page_bg_tint")
        card_bg_tint = theme_vars.get("card_bg_tint")

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
        if metric_text_color:
            overrides.append(f"--metric-color: {metric_text_color};")

        # Button text color: auto-contrast from primary, with manual override
        def _parse_hex_color(val: Any):
            try:
                s = str(val or "").strip()
                if not s.startswith("#"):
                    return None
                h = s[1:]
                if len(h) == 3:
                    h = "".join(c * 2 for c in h)
                if len(h) != 6:
                    return None
                r = int(h[0:2], 16)
                g = int(h[2:4], 16)
                b = int(h[4:6], 16)
                return r, g, b
            except Exception:
                return None

        def _auto_btn_for(primary_val: Any) -> str | None:
            rgb = _parse_hex_color(primary_val)
            if not rgb:
                return None
            r, g, b = rgb
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            return "#111827" if lum > 180 else "#ffffff"

        def _too_close(c1: Any, c2: Any) -> bool:
            rgb1 = _parse_hex_color(c1)
            rgb2 = _parse_hex_color(c2)
            if not rgb1 or not rgb2:
                return False
            l1 = 0.299 * rgb1[0] + 0.587 * rgb1[1] + 0.114 * rgb1[2]
            l2 = 0.299 * rgb2[0] + 0.587 * rgb2[1] + 0.114 * rgb2[2]
            return abs(l1 - l2) < 80

        def _lighten_for_bg(val: Any, mix: float = 0.85) -> str | None:
            rgb = _parse_hex_color(val)
            if not rgb:
                return None
            r, g, b = rgb
            # Mix a high percentage of white with the chosen color to keep it very light
            def _mix(c: int) -> int:
                return int(min(255, c + (255 - c) * mix))

            lr, lg, lb = _mix(r), _mix(g), _mix(b)
            return f"#{lr:02x}{lg:02x}{lb:02x}"

        if primary:
            auto_btn = _auto_btn_for(primary)
            chosen_btn = None
            if btn_text_color:
                # If manual color is too close to the button background, fall back to auto for safety
                if auto_btn and _too_close(btn_text_color, primary):
                    chosen_btn = auto_btn
                else:
                    chosen_btn = btn_text_color
            elif auto_btn:
                chosen_btn = auto_btn
            if chosen_btn:
                overrides.append(f"--btn-text-on-primary: {chosen_btn};")

        # Very light horizontal 3-stop page tint (color → light → color)
        if page_bg_tint:
            safe_bg = _lighten_for_bg(page_bg_tint) or page_bg_tint
            overrides.append(
                f"--page-bg: linear-gradient(90deg, {safe_bg} 0%, #fdfdfd 52%, {safe_bg} 100%);"
            )

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
        t=translator,
        show_back=show_back,
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
        show_file_numbers=show_file_numbers,
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
