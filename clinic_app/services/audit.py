"""Append-only audit logging."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from flask import g, request

import sqlalchemy as sa

from clinic_app.extensions import db

SENSITIVE_KEYS = {"notes", "note", "diagnosis", "treatment", "details"}
PAYMENT_ACTIONS = {"payment_create", "payment_update", "payment_delete"}


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


def _setting_value(session, key: str) -> str | None:
    try:
        row = session.execute(
            sa.text("SELECT setting_value FROM admin_settings WHERE setting_key = :k LIMIT 1"),
            {"k": key},
        ).first()
        if not row:
            return None
        return str(row[0]) if row[0] is not None else None
    except Exception:
        return None


def _snapshots_enabled(session) -> bool:
    raw = _setting_value(session, "audit_payments_snapshots_enabled")
    if raw is None:
        return True
    return str(raw).strip().lower() == "true"


def _load_patient_snapshot_fields(session, patient_id: str) -> tuple[str, str, str]:
    try:
        row = session.execute(
            sa.text(
                """
                SELECT full_name, short_id, primary_page_number
                  FROM patients
                 WHERE id = :pid
                 LIMIT 1
                """
            ),
            {"pid": patient_id},
        ).first()
        if row:
            return (str(row[0] or ""), str(row[1] or ""), str(row[2] or ""))
    except Exception:
        # Backwards compatibility if primary_page_number doesn't exist.
        try:
            row = session.execute(
                sa.text(
                    """
                    SELECT full_name, short_id
                      FROM patients
                     WHERE id = :pid
                     LIMIT 1
                    """
                ),
                {"pid": patient_id},
            ).first()
            if row:
                return (str(row[0] or ""), str(row[1] or ""), "")
        except Exception:
            pass
    return ("", "", "")


def _write_payment_snapshot(
    session,
    *,
    audit_log_id: int,
    audit_ts_epoch: int,
    patient_id: str,
) -> None:
    full_name, short_id, primary_page = _load_patient_snapshot_fields(session, patient_id)
    session.execute(
        sa.text(
            """
            INSERT OR IGNORE INTO audit_patient_snapshots
                (audit_log_id, audit_ts_epoch, patient_id, patient_full_name, patient_short_id, patient_primary_page_number)
            VALUES
                (:audit_log_id, :audit_ts_epoch, :patient_id, :patient_full_name, :patient_short_id, :patient_primary_page_number)
            """
        ),
        {
            "audit_log_id": audit_log_id,
            "audit_ts_epoch": audit_ts_epoch,
            "patient_id": patient_id or None,
            "patient_full_name": full_name,
            "patient_short_id": short_id,
            "patient_primary_page_number": primary_page,
        },
    )


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
    now = datetime.now(timezone.utc)
    session = db.session()
    try:
        ts_iso = now.isoformat()
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
                "ts": ts_iso,
                "result": result,
                "meta": payload,
            },
        )

        audit_log_id: int | None = None
        try:
            audit_log_id = int(session.execute(sa.text("SELECT last_insert_rowid()")).scalar_one())
        except Exception:
            audit_log_id = None

        if (
            audit_log_id
            and entity == "payment"
            and action in PAYMENT_ACTIONS
            and _snapshots_enabled(session)
            and isinstance(meta, Mapping)
        ):
            pid = str(meta.get("patient_id") or "").strip()
            if pid:
                try:
                    _write_payment_snapshot(
                        session,
                        audit_log_id=audit_log_id,
                        audit_ts_epoch=int(now.timestamp()),
                        patient_id=pid,
                    )
                except Exception:
                    # Never block core workflow if snapshot write fails.
                    pass

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
