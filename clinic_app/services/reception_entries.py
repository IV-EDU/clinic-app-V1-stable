"""Service helpers for Reception draft entry storage."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from clinic_app.services.database import db as raw_db
from clinic_app.services.payments import cents_guard, parse_money_to_cents


ALLOWED_DRAFT_TYPES = {
    "new_visit_only",
    "new_treatment",
    "new_payment",
    "edit_patient",
    "edit_payment",
    "edit_treatment",
}
ALLOWED_SOURCES = {"reception_desk", "patient_file", "treatment_card"}
ALLOWED_STATUSES = {"new", "edited", "held", "approved", "rejected"}
ALLOWED_PATIENT_INTENTS = {"unknown", "existing", "new_patient"}
QUEUE_STATUSES = ("new", "edited", "held")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _nullable_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _bool_flag(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    text = _text(value).lower()
    return 1 if text in {"1", "true", "yes", "on"} else 0


def _json_string(value: Any, default: Any) -> str:
    if value in (None, ""):
        return json.dumps(default, ensure_ascii=True)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return json.dumps(default, ensure_ascii=True)
        return json.dumps(parsed, ensure_ascii=True)
    return json.dumps(value, ensure_ascii=True)


def _parse_optional_money(value: Any, label: str) -> int | None:
    raw = _text(value)
    if not raw:
        return None
    cents = parse_money_to_cents(raw)
    return cents_guard(cents, label)


def _decode_row(row) -> dict[str, Any]:
    if row is None:
        return None
    data = dict(row)
    for key, empty in (
        ("payload_json", {}),
        ("warnings_json", []),
        ("match_summary_json", {}),
        ("meta_json", {}),
    ):
        if key in data:
            try:
                data[key] = json.loads(data[key] or json.dumps(empty, ensure_ascii=True))
            except (TypeError, json.JSONDecodeError):
                data[key] = empty
    return data


def _fetch_entry(conn, entry_id: str):
    return conn.execute(
        "SELECT * FROM reception_entries WHERE id=?",
        (entry_id,),
    ).fetchone()


def _insert_event(
    conn,
    *,
    entry_id: str,
    action: str,
    actor_user_id: str,
    from_status: str | None,
    to_status: str | None,
    note: str | None,
    meta_json: Any = None,
    created_at: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO reception_entry_events (
            id, entry_id, action, actor_user_id,
            from_status, to_status, note, meta_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            entry_id,
            action,
            actor_user_id,
            from_status,
            to_status,
            note,
            _json_string(meta_json, {}),
            created_at or _utc_now_iso(),
        ),
    )


def _require_active_entry(row, *, action: str) -> dict[str, Any]:
    if row is None:
        raise ValueError("Reception draft was not found.")
    entry = _decode_row(row)
    if entry["status"] in {"approved", "rejected"}:
        raise ValueError(f"Cannot {action} a closed draft.")
    return entry


def validate_entry_payload(data: dict) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []

    draft_type = _text(data.get("draft_type")) or "new_treatment"
    if draft_type not in ALLOWED_DRAFT_TYPES:
        errors.append("Invalid draft type.")

    source = _text(data.get("source")) or "reception_desk"
    if source not in ALLOWED_SOURCES:
        errors.append("Invalid entry source.")

    patient_intent = _text(data.get("patient_intent")) or "unknown"
    if patient_intent not in ALLOWED_PATIENT_INTENTS:
        errors.append("Invalid patient intent.")

    locked_patient_id = _nullable_text(data.get("locked_patient_id"))
    doctor_id = _text(data.get("doctor_id"))
    doctor_label = _text(data.get("doctor_label"))
    patient_name = _nullable_text(data.get("patient_name"))
    page_number = _nullable_text(data.get("page_number"))
    phone = _nullable_text(data.get("phone"))

    money_received_today = _bool_flag(data.get("money_received_today"))
    paid_today_cents = _parse_optional_money(data.get("paid_today"), "paid today")
    total_amount_cents = _parse_optional_money(data.get("total_amount"), "total amount")
    discount_amount_cents = _parse_optional_money(data.get("discount_amount"), "discount amount")
    if discount_amount_cents is None:
        discount_amount_cents = 0
    discount_amount_cents = max(discount_amount_cents, 0)

    if not locked_patient_id and not patient_name:
        errors.append("Patient name is required when patient context is not locked.")
    if not doctor_id or not doctor_label:
        errors.append("Doctor is required.")
    if money_received_today and paid_today_cents is None:
        errors.append("Paid today is required when money was received today.")
    if total_amount_cents is not None and paid_today_cents is not None:
        due_cents = max(total_amount_cents - discount_amount_cents, 0)
        if paid_today_cents > due_cents:
            errors.append("Paid today cannot be greater than the amount due.")

    if not phone:
        warnings.append("Phone is missing.")
    if not page_number:
        warnings.append("Page number is missing.")
    if total_amount_cents is None:
        warnings.append("Total amount is missing.")
        warnings.append("Remaining amount is unknown.")

    normalized = {
        "draft_type": draft_type,
        "source": source,
        "status": "new",
        "patient_intent": patient_intent,
        "locked_patient_id": locked_patient_id,
        "locked_treatment_id": _nullable_text(data.get("locked_treatment_id")),
        "locked_payment_id": _nullable_text(data.get("locked_payment_id")),
        "target_patient_id": _nullable_text(data.get("target_patient_id")),
        "target_treatment_id": _nullable_text(data.get("target_treatment_id")),
        "target_payment_id": _nullable_text(data.get("target_payment_id")),
        "patient_name": patient_name,
        "page_number": page_number,
        "phone": phone,
        "visit_date": _nullable_text(data.get("visit_date")),
        "visit_type": _nullable_text(data.get("visit_type")),
        "treatment_text": _nullable_text(data.get("treatment_text")),
        "doctor_id": doctor_id,
        "doctor_label": doctor_label,
        "money_received_today": money_received_today,
        "paid_today_cents": paid_today_cents,
        "total_amount_cents": total_amount_cents,
        "discount_amount_cents": discount_amount_cents,
        "payload_json": _json_string(data.get("payload_json"), {}),
        "warnings_json": _json_string(data.get("warnings_json"), warnings),
        "match_summary_json": _json_string(data.get("match_summary_json"), {}),
    }
    return errors, warnings, normalized


def create_entry(data: dict, *, actor_user_id: str) -> dict[str, Any]:
    errors, warnings, normalized = validate_entry_payload(data)
    if errors:
        raise ValueError("; ".join(errors))

    now = _utc_now_iso()
    entry_id = str(uuid4())
    conn = raw_db()
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            """
            INSERT INTO reception_entries (
                id, draft_type, source, status, patient_intent,
                locked_patient_id, locked_treatment_id, locked_payment_id,
                target_patient_id, target_treatment_id, target_payment_id,
                submitted_by_user_id, reviewed_by_user_id,
                submitted_at, updated_at, reviewed_at,
                last_action, return_reason, hold_reason, rejection_reason,
                patient_name, page_number, phone, visit_date, visit_type, treatment_text,
                doctor_id, doctor_label, money_received_today, paid_today_cents,
                total_amount_cents, discount_amount_cents,
                payload_json, warnings_json, match_summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                normalized["draft_type"],
                normalized["source"],
                normalized["status"],
                normalized["patient_intent"],
                normalized["locked_patient_id"],
                normalized["locked_treatment_id"],
                normalized["locked_payment_id"],
                normalized["target_patient_id"],
                normalized["target_treatment_id"],
                normalized["target_payment_id"],
                actor_user_id,
                None,
                now,
                now,
                None,
                "submitted",
                None,
                None,
                None,
                normalized["patient_name"],
                normalized["page_number"],
                normalized["phone"],
                normalized["visit_date"],
                normalized["visit_type"],
                normalized["treatment_text"],
                normalized["doctor_id"],
                normalized["doctor_label"],
                normalized["money_received_today"],
                normalized["paid_today_cents"],
                normalized["total_amount_cents"],
                normalized["discount_amount_cents"],
                normalized["payload_json"],
                _json_string(warnings, warnings),
                normalized["match_summary_json"],
            ),
        )
        _insert_event(
            conn,
            entry_id=entry_id,
            action="submitted",
            actor_user_id=actor_user_id,
            from_status=None,
            to_status="new",
            note=None,
            meta_json={},
            created_at=now,
        )
        conn.commit()
    finally:
        conn.close()
    return get_entry(entry_id)


def get_entry(entry_id: str) -> dict[str, Any] | None:
    conn = raw_db()
    try:
        row = conn.execute(
            "SELECT * FROM reception_entries WHERE id=?",
            (entry_id,),
        ).fetchone()
        return _decode_row(row)
    finally:
        conn.close()


def list_entries(
    *,
    status: str | None = None,
    submitted_by_user_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 50), 200))
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if submitted_by_user_id:
        clauses.append("submitted_by_user_id = ?")
        params.append(submitted_by_user_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = raw_db()
    try:
        rows = conn.execute(
            f"""
            SELECT * FROM reception_entries
            {where}
            ORDER BY submitted_at DESC, updated_at DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        return [_decode_row(row) for row in rows]
    finally:
        conn.close()


def list_queue_entries(*, limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 50), 200))
    placeholders = ", ".join("?" for _ in QUEUE_STATUSES)
    conn = raw_db()
    try:
        rows = conn.execute(
            f"""
            SELECT * FROM reception_entries
            WHERE status IN ({placeholders})
            ORDER BY submitted_at DESC, updated_at DESC
            LIMIT ?
            """,
            (*QUEUE_STATUSES, limit),
        ).fetchall()
        return [_decode_row(row) for row in rows]
    finally:
        conn.close()


def hold_entry(entry_id: str, *, actor_user_id: str, note: str | None = None) -> dict[str, Any]:
    now = _utc_now_iso()
    hold_note = _nullable_text(note)
    conn = raw_db()
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        entry = _require_active_entry(_fetch_entry(conn, entry_id), action="hold")
        conn.execute(
            """
            UPDATE reception_entries
            SET status=?,
                reviewed_by_user_id=?,
                updated_at=?,
                reviewed_at=?,
                last_action=?,
                return_reason=NULL,
                hold_reason=?,
                rejection_reason=NULL
            WHERE id=?
            """,
            ("held", actor_user_id, now, now, "held", hold_note, entry_id),
        )
        _insert_event(
            conn,
            entry_id=entry_id,
            action="held",
            actor_user_id=actor_user_id,
            from_status=entry["status"],
            to_status="held",
            note=hold_note,
            meta_json={},
            created_at=now,
        )
        conn.commit()
    finally:
        conn.close()
    return get_entry(entry_id)


def return_entry(entry_id: str, *, actor_user_id: str, reason: str) -> dict[str, Any]:
    reason_text = _nullable_text(reason)
    if not reason_text:
        raise ValueError("Return reason is required.")

    now = _utc_now_iso()
    conn = raw_db()
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        entry = _require_active_entry(_fetch_entry(conn, entry_id), action="return")
        conn.execute(
            """
            UPDATE reception_entries
            SET status=?,
                reviewed_by_user_id=?,
                updated_at=?,
                reviewed_at=?,
                last_action=?,
                return_reason=?,
                hold_reason=NULL,
                rejection_reason=NULL
            WHERE id=?
            """,
            ("edited", actor_user_id, now, now, "returned", reason_text, entry_id),
        )
        _insert_event(
            conn,
            entry_id=entry_id,
            action="returned",
            actor_user_id=actor_user_id,
            from_status=entry["status"],
            to_status="edited",
            note=reason_text,
            meta_json={},
            created_at=now,
        )
        conn.commit()
    finally:
        conn.close()
    return get_entry(entry_id)


def reject_entry(entry_id: str, *, actor_user_id: str, reason: str) -> dict[str, Any]:
    reason_text = _nullable_text(reason)
    if not reason_text:
        raise ValueError("Rejection reason is required.")

    now = _utc_now_iso()
    conn = raw_db()
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        entry = _require_active_entry(_fetch_entry(conn, entry_id), action="reject")
        conn.execute(
            """
            UPDATE reception_entries
            SET status=?,
                reviewed_by_user_id=?,
                updated_at=?,
                reviewed_at=?,
                last_action=?,
                return_reason=NULL,
                hold_reason=NULL,
                rejection_reason=?
            WHERE id=?
            """,
            ("rejected", actor_user_id, now, now, "rejected", reason_text, entry_id),
        )
        _insert_event(
            conn,
            entry_id=entry_id,
            action="rejected",
            actor_user_id=actor_user_id,
            from_status=entry["status"],
            to_status="rejected",
            note=reason_text,
            meta_json={},
            created_at=now,
        )
        conn.commit()
    finally:
        conn.close()
    return get_entry(entry_id)


def list_entry_events(entry_id: str) -> list[dict[str, Any]]:
    conn = raw_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM reception_entry_events
            WHERE entry_id=?
            ORDER BY created_at DESC
            """,
            (entry_id,),
        ).fetchall()
        return [_decode_row(row) for row in rows]
    finally:
        conn.close()
