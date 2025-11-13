"""UI helper utilities shared across blueprints."""

from __future__ import annotations

import time
from typing import Any

from flask import g, render_template, request, session, url_for
from flask_wtf.csrf import generate_csrf

from .i18n import T, dir_attr, get_lang
from .security import user_has_permission


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
    return render_template(
        template_name,
        lang=lang,
        dir=dir_attr(lang),
        t=T,
        show_back=show_back,
        current_user=getattr(g, "current_user", None),
        user_has_permission=user_has_permission,
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
