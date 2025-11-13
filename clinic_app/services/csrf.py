"""Helpers for validating CSRF tokens on JSON endpoints."""

from __future__ import annotations

from typing import Mapping, MutableMapping

from flask import current_app, request
from flask_wtf.csrf import CSRFError, validate_csrf


def ensure_csrf_token(payload: MutableMapping[str, object] | Mapping[str, object] | None = None) -> None:
    """Validate CSRF token from header or JSON payload.

    Flask-WTF automatically inspects form data, but JSON APIs need custom handling.
    This helper mirrors Flask-WTF's behaviour while allowing clients to supply the
    token via header *or* a `csrf_token` field inside the JSON body.
    """

    token = request.headers.get("X-CSRFToken") or request.headers.get("X-CSRF-Token")
    if not token and payload and isinstance(payload, MutableMapping):
        token = payload.get("csrf_token")
        if token:
            payload.pop("csrf_token", None)
    if not token:
        raise CSRFError("The CSRF token is missing.")
    validate_csrf(token, secret_key=current_app.secret_key)
