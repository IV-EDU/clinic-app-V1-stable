"""Append-only audit logging."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from flask import g, request

import sqlalchemy as sa

from clinic_app.extensions import db

SENSITIVE_KEYS = {"notes", "note", "diagnosis", "treatment", "details"}


def _sanitize_meta(meta: Mapping[str, Any] | None) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    if not meta:
        return cleaned
    for key, value in meta.items():
        key_lower = key.lower()
        if key_lower in SENSITIVE_KEYS:
            cleaned[key] = "[redacted]"
        else:
            cleaned[key] = value
    return cleaned


def write_event(
    actor_user_id: str | None,
    action: str,
    *,
    entity: str | None = None,
    entity_id: str | None = None,
    result: str = "ok",
    meta: Mapping[str, Any] | None = None,
) -> None:
    payload = json.dumps(_sanitize_meta(meta), ensure_ascii=False)
    session = db.session()
    try:
        session.execute(
            sa.text(
                """
                INSERT INTO audit_log(actor_user_id, action, entity, entity_id, ts, result, meta_json_redacted)
                VALUES (:actor_user_id, :action, :entity, :entity_id, :ts, :result, :meta)
                """
            ),
            {
                "actor_user_id": actor_user_id,
                "action": action,
                "entity": entity,
                "entity_id": entity_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "result": result,
                "meta": payload,
            },
        )
        session.commit()
    finally:
        session.close()


def audit_view(action: str, *, entity: str | None = None, entity_id: str | None = None) -> None:
    actor = getattr(g, "current_user", None)
    actor_id = getattr(actor, "id", None)
    write_event(actor_id, action, entity=entity, entity_id=entity_id, meta={"path": request.path})


def audit_denied(action: str, *, reason: str) -> None:
    actor = getattr(g, "current_user", None)
    actor_id = getattr(actor, "id", None)
    write_event(actor_id, action, result="denied", meta={"reason": reason, "path": request.path})


def audit_rate_limit(scope: str) -> None:
    actor = getattr(g, "current_user", None)
    actor_id = getattr(actor, "id", None)
    write_event(actor_id, "rate_limit", meta={"scope": scope, "path": request.path}, result="blocked")
