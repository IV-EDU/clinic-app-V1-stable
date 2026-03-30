"""Service helpers for Reception draft entry storage."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from clinic_app.services.arabic_search import normalize_arabic
from clinic_app.services.audit import write_event
from clinic_app.services.database import db as raw_db
from clinic_app.services.i18n import T, translate_text
from clinic_app.services.patients import (
    apply_patient_profile_update,
    get_patient_profile_snapshot,
    migrate_patients_drop_unique_short_id,
    next_short_id,
    normalize_patient_profile_update,
)
from clinic_app.services.payments import cents_guard, parse_money_to_cents
from clinic_app.services.payments import add_payment_to_treatment


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


def _payload_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _consultation_visit_name() -> str:
    try:
        return T("consultation_visit_name")
    except RuntimeError:
        return translate_text("en", "consultation_visit_name")


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


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row["name"] or "") == column_name for row in rows)


def _normalize_phone_digits(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _patient_page_expr(conn, *, alias: str = "p") -> str:
    has_primary_page = _column_exists(conn, "patients", "primary_page_number")
    has_pages_table = _table_exists(conn, "patient_pages")
    primary_expr = f"{alias}.primary_page_number" if has_primary_page else "NULL"
    if not has_pages_table:
        return primary_expr
    fallback_expr = (
        "(\n"
        "                SELECT pp.page_number\n"
        "                FROM patient_pages pp\n"
        f"                WHERE pp.patient_id = {alias}.id\n"
        "                ORDER BY pp.rowid DESC\n"
        "                LIMIT 1\n"
        "            )"
    )
    if has_primary_page:
        return f"COALESCE({primary_expr}, {fallback_expr})"
    return fallback_expr


def _visit_type_flags(raw_value: str | None) -> tuple[int, int]:
    value = (raw_value or "none").strip().lower()
    if value not in {"none", "exam", "followup"}:
        value = "none"
    return (1 if value == "exam" else 0, 1 if value == "followup" else 0)


def _visit_type_value(examination_flag: Any, followup_flag: Any, treatment_text: str | None = None) -> str:
    treatment_label = _text(treatment_text)
    if treatment_label in {"Consultation visit", "زيارة استشارة"}:
        return "none"
    if int(examination_flag or 0) == 1:
        return "exam"
    if int(followup_flag or 0) == 1:
        return "followup"
    return "none"


def _patient_profile_payload(data: dict[str, Any] | None, *, include_short_id: bool = False) -> dict[str, Any]:
    data = data or {}
    phones: list[dict[str, Any]] = []
    for row in data.get("phones") or []:
        phone = _text((row or {}).get("phone"))
        if not phone:
            continue
        phones.append(
            {
                "phone": phone,
                "label": _nullable_text((row or {}).get("label")),
                "is_primary": 1 if (row or {}).get("is_primary") else 0,
            }
        )
    if not phones and _text(data.get("primary_phone")):
        phones.append(
            {
                "phone": _text(data.get("primary_phone")),
                "label": None,
                "is_primary": 1,
            }
        )

    pages: list[dict[str, Any]] = []
    for row in data.get("pages") or []:
        page_number = _text((row or {}).get("page_number"))
        if not page_number:
            continue
        pages.append(
            {
                "page_number": page_number,
                "notebook_name": _nullable_text((row or {}).get("notebook_name")),
                "notebook_color": _text((row or {}).get("notebook_color")),
            }
        )
    if not pages and _text(data.get("primary_page_number")):
        pages.append(
            {
                "page_number": _text(data.get("primary_page_number")),
                "notebook_name": None,
                "notebook_color": "",
            }
        )

    payload = {
        "full_name": _text(data.get("full_name")),
        "primary_phone": phones[0]["phone"] if phones else "",
        "phones": phones,
        "primary_page_number": pages[0]["page_number"] if pages else "",
        "pages": pages,
        "notes": _text(data.get("notes")),
    }
    if include_short_id:
        payload["short_id"] = _text(data.get("short_id"))
    return payload


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


def _require_returned_resubmittable_entry(row, *, actor_user_id: str) -> dict[str, Any]:
    if row is None:
        raise ValueError("Reception draft was not found.")
    entry = _decode_row(row)
    if entry.get("submitted_by_user_id") != actor_user_id:
        raise ValueError("You can only edit your own returned drafts.")
    supports_resubmit = (
        (entry.get("draft_type") in {"new_treatment", "new_visit_only"} and entry.get("source") in {"reception_desk", "patient_file"})
        or (entry.get("draft_type") == "edit_patient" and entry.get("source") == "patient_file")
        or (entry.get("draft_type") == "edit_payment" and entry.get("source") == "treatment_card")
        or (entry.get("draft_type") == "edit_treatment" and entry.get("source") == "treatment_card")
    )
    if not supports_resubmit:
        raise ValueError("Only returned supported draft types can be edited in this slice.")
    if entry.get("status") != "edited" or entry.get("last_action") != "returned":
        raise ValueError("Only returned drafts can be edited and resubmitted.")
    return entry


def _require_manager_editable_entry(row) -> dict[str, Any]:
    if row is None:
        raise ValueError("Reception draft was not found.")
    entry = _decode_row(row)
    supports_manager_edit = (
        (entry.get("draft_type") in {"new_treatment", "new_visit_only"} and entry.get("source") in {"reception_desk", "patient_file"})
        or (entry.get("draft_type") == "new_payment" and entry.get("source") == "treatment_card")
        or (entry.get("draft_type") == "edit_patient" and entry.get("source") == "patient_file")
        or (entry.get("draft_type") == "edit_payment" and entry.get("source") == "treatment_card")
        or (entry.get("draft_type") == "edit_treatment" and entry.get("source") == "treatment_card")
    )
    if not supports_manager_edit:
        raise ValueError("Only supported pending draft types can be edited in this slice.")
    if entry.get("status") not in {"new", "edited", "held"}:
        raise ValueError("Only pending drafts can be edited.")
    if entry.get("status") in {"approved", "rejected"}:
        raise ValueError("Cannot edit a closed draft.")
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
    visit_date = _nullable_text(data.get("visit_date"))
    visit_type = _nullable_text(data.get("visit_type"))
    treatment_text = _nullable_text(data.get("treatment_text"))

    money_received_today = _bool_flag(data.get("money_received_today"))
    paid_today_cents = _parse_optional_money(data.get("paid_today"), "paid today")
    total_amount_cents = _parse_optional_money(data.get("total_amount"), "total amount")
    discount_amount_cents = _parse_optional_money(data.get("discount_amount"), "discount amount")
    if discount_amount_cents is None:
        discount_amount_cents = 0
    discount_amount_cents = max(discount_amount_cents, 0)
    payload_dict = _payload_dict(data.get("payload_json"))

    if draft_type == "new_payment":
        if not locked_patient_id:
            errors.append("Patient context is required for payment drafts.")
        if not _nullable_text(data.get("locked_treatment_id")):
            errors.append("Treatment context is required for payment drafts.")
        if not doctor_id or not doctor_label:
            errors.append("Doctor is required.")
        if paid_today_cents is None:
            errors.append("Payment amount is required.")
        elif paid_today_cents <= 0:
            errors.append("Payment amount must be greater than zero.")
        treatment_remaining_cents = payload_dict.get("treatment_remaining_cents_at_submit")
        if isinstance(treatment_remaining_cents, int) and paid_today_cents is not None and paid_today_cents > treatment_remaining_cents:
            errors.append("Paid today cannot be greater than the amount due.")
        patient_intent = "existing"
        money_received_today = 1
    elif draft_type == "edit_payment":
        locked_treatment_id = _nullable_text(data.get("locked_treatment_id"))
        locked_payment_id = _nullable_text(data.get("locked_payment_id"))
        if not locked_patient_id:
            errors.append("Locked patient context is required.")
        if not locked_treatment_id:
            errors.append("Locked treatment context is required.")
        if not locked_payment_id:
            errors.append("Locked payment context is required.")
        patient_intent = "existing"

        proposed_raw = payload_dict.get("proposed")
        if proposed_raw is None:
            proposed_raw = {}
        if not isinstance(proposed_raw, dict):
            errors.append("Malformed payment correction payload.")
            proposed_raw = {}

        current_payload = payload_dict.get("current")
        current_snapshot = current_payload if isinstance(current_payload, dict) else None
        live_context = None
        if locked_patient_id and locked_payment_id:
            live_context = get_locked_payment_context(locked_patient_id, locked_payment_id)
        if not current_snapshot and live_context:
            current_snapshot = _payment_correction_payload(live_context)
        if locked_patient_id and locked_payment_id and not current_snapshot:
            errors.append("Locked payment was not found.")
            current_snapshot = {}

        doctor_id = _text(proposed_raw.get("doctor_id"))
        doctor_label = _text(proposed_raw.get("doctor_label"))
        if not doctor_id or not doctor_label:
            errors.append("Doctor is required.")

        visit_date = _nullable_text(proposed_raw.get("visit_date"))
        paid_today_cents = _parse_optional_money(proposed_raw.get("amount"), "payment amount")
        if paid_today_cents is None:
            errors.append("Payment amount is required.")
        elif paid_today_cents <= 0:
            errors.append("Payment amount must be greater than zero.")

        max_amount_cents = None
        if live_context:
            max_amount_cents = int(live_context.get("max_amount_cents") or 0)
        if max_amount_cents is not None and paid_today_cents is not None and paid_today_cents > max_amount_cents:
            errors.append("Payment amount cannot be greater than the amount still due on the locked treatment.")

        treatment_context = live_context.get("treatment_context") if isinstance(live_context, dict) else None
        patient_name = _nullable_text((treatment_context or {}).get("patient_name"))
        phone = _nullable_text((treatment_context or {}).get("phone"))
        page_number = _nullable_text((treatment_context or {}).get("page_number"))
        treatment_text = _nullable_text((treatment_context or {}).get("treatment_text"))
        money_received_today = 1
        total_amount_cents = None
        discount_amount_cents = 0
        warnings = []
        if live_context:
            if not phone:
                warnings.append("Phone is missing.")
            if not page_number:
                warnings.append("Page number is missing.")
        payload_dict = {
            "current": current_snapshot or {},
            "proposed": {
                "payment_id": locked_payment_id or "",
                "treatment_id": locked_treatment_id or "",
                "amount_cents": paid_today_cents,
                "visit_date": visit_date or "",
                "method": _text(proposed_raw.get("method")) or "cash",
                "doctor_id": doctor_id,
                "doctor_label": doctor_label,
                "note": _text(proposed_raw.get("note")),
            },
        }
    elif draft_type == "edit_treatment":
        locked_treatment_id = _nullable_text(data.get("locked_treatment_id"))
        if not locked_patient_id:
            errors.append("Locked patient context is required.")
        if not locked_treatment_id:
            errors.append("Locked treatment context is required.")
        patient_intent = "existing"

        proposed_raw = payload_dict.get("proposed")
        if proposed_raw is None:
            proposed_raw = {}
        if not isinstance(proposed_raw, dict):
            errors.append("Malformed treatment correction payload.")
            proposed_raw = {}

        current_payload = payload_dict.get("current")
        current_snapshot = current_payload if isinstance(current_payload, dict) else None
        live_context = None
        if locked_patient_id and locked_treatment_id:
            live_context = get_locked_treatment_context(locked_patient_id, locked_treatment_id)
        if not current_snapshot and live_context:
            current_snapshot = _treatment_correction_payload(live_context)
        if locked_patient_id and locked_treatment_id and not current_snapshot:
            errors.append("Locked treatment was not found.")
            current_snapshot = {}

        treatment_text = _nullable_text(proposed_raw.get("treatment_text"))
        visit_date = _nullable_text(proposed_raw.get("visit_date"))
        visit_type = _nullable_text(proposed_raw.get("visit_type")) or "none"
        if visit_type not in {"none", "exam", "followup"}:
            visit_type = "none"
        doctor_id = _text(proposed_raw.get("doctor_id"))
        doctor_label = _text(proposed_raw.get("doctor_label"))
        if not doctor_id or not doctor_label:
            errors.append("Doctor is required.")

        total_raw = proposed_raw.get("total_amount")
        if total_raw in (None, ""):
            errors.append("Total amount is required.")
        total_amount_cents = _parse_optional_money(total_raw, "total amount")

        discount_raw = proposed_raw.get("discount_amount")
        discount_amount_cents = _parse_optional_money(discount_raw, "discount amount")
        if discount_amount_cents is None:
            discount_amount_cents = 0
        discount_amount_cents = max(discount_amount_cents, 0)

        if total_amount_cents is not None and discount_amount_cents > total_amount_cents:
            errors.append("Discount cannot be greater than the total amount.")

        total_paid_cents = int((live_context or {}).get("total_paid_cents") or 0)
        if total_amount_cents is not None:
            due_cents = max(total_amount_cents - discount_amount_cents, 0)
            if due_cents < total_paid_cents:
                errors.append("Total amount minus discount cannot be less than the amount already paid.")

        patient_name = _nullable_text((live_context or {}).get("patient_name"))
        phone = _nullable_text((live_context or {}).get("phone"))
        page_number = _nullable_text((live_context or {}).get("page_number"))
        money_received_today = 0
        paid_today_cents = None
        warnings = []
        if not phone:
            warnings.append("Phone is missing.")
        if not page_number:
            warnings.append("Page number is missing.")
        payload_dict = {
            "current": current_snapshot or {},
            "proposed": {
                "treatment_text": treatment_text or "",
                "visit_date": visit_date or "",
                "visit_type": visit_type,
                "doctor_id": doctor_id,
                "doctor_label": doctor_label,
                "total_amount_cents": total_amount_cents,
                "discount_amount_cents": discount_amount_cents,
                "note": _text(proposed_raw.get("note")),
            },
        }
    elif draft_type == "edit_patient":
        if not locked_patient_id:
            errors.append("Locked patient context is required.")
        patient_intent = "existing"

        proposed_raw = payload_dict.get("proposed")
        if proposed_raw is None:
            proposed_raw = {}
        if not isinstance(proposed_raw, dict):
            errors.append("Malformed patient correction payload.")
            proposed_raw = {}

        current_payload = payload_dict.get("current")
        current_snapshot = current_payload if isinstance(current_payload, dict) else None
        if not current_snapshot and locked_patient_id:
            live_snapshot = get_patient_profile_snapshot(locked_patient_id)
            if live_snapshot:
                current_snapshot = _patient_profile_payload(live_snapshot, include_short_id=True)
        if locked_patient_id and not current_snapshot:
            errors.append("Locked patient was not found.")
            current_snapshot = {}

        profile_errors, normalized_profile = normalize_patient_profile_update(
            proposed_raw,
            patient_id=locked_patient_id,
        )
        errors.extend(profile_errors)

        current_short_id = _text((current_snapshot or {}).get("short_id"))
        proposed_short_id = _text(normalized_profile.get("short_id"))
        if proposed_short_id and proposed_short_id != current_short_id:
            errors.append("Changing file number is not supported in this slice.")

        patient_name = _nullable_text(normalized_profile.get("full_name"))
        phone = _nullable_text(normalized_profile.get("primary_phone"))
        page_number = _nullable_text(normalized_profile.get("primary_page_number"))
        treatment_text = None
        visit_date = None
        visit_type = None
        money_received_today = 0
        paid_today_cents = None
        total_amount_cents = None
        discount_amount_cents = 0
        warnings = []
        if not phone:
            warnings.append("Phone is missing.")
        if not page_number:
            warnings.append("Page number is missing.")
        payload_dict = {
            "current": current_snapshot or {},
            "proposed": _patient_profile_payload(normalized_profile),
            "note": _text(payload_dict.get("note")),
        }
    elif draft_type == "new_visit_only":
        if source == "patient_file" and not locked_patient_id:
            errors.append("Locked patient context is required.")
        if not locked_patient_id and not patient_name:
            errors.append("Patient name is required when patient context is not locked.")
        if not doctor_id or not doctor_label:
            errors.append("Doctor is required.")
        if money_received_today or paid_today_cents is not None or total_amount_cents is not None or discount_amount_cents:
            errors.append("Visit-only drafts cannot include payment details.")

        patient_intent = "existing" if source == "patient_file" else "unknown"
        visit_type = "none"
        treatment_text = _consultation_visit_name()
        money_received_today = 0
        paid_today_cents = None
        total_amount_cents = None
        discount_amount_cents = 0
        warnings = []
        if not phone:
            warnings.append("Phone is missing.")
        if not page_number:
            warnings.append("Page number is missing.")
    else:
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
        "visit_date": visit_date,
        "visit_type": visit_type,
        "treatment_text": treatment_text,
        "doctor_id": doctor_id,
        "doctor_label": doctor_label,
        "money_received_today": money_received_today,
        "paid_today_cents": paid_today_cents,
        "total_amount_cents": total_amount_cents,
        "discount_amount_cents": discount_amount_cents,
        "payload_json": _json_string(payload_dict, {}),
        "warnings_json": _json_string(data.get("warnings_json"), warnings),
        "match_summary_json": _json_string(data.get("match_summary_json"), {}),
    }
    return errors, warnings, normalized


def get_locked_treatment_context(patient_id: str, treatment_id: str) -> dict[str, Any] | None:
    conn = raw_db()
    try:
        patient_select = "SELECT id, full_name, phone"
        if _column_exists(conn, "patients", "primary_page_number"):
            patient_select += ", primary_page_number"
        patient_select += " FROM patients WHERE id=?"
        patient = conn.execute(patient_select, (patient_id,)).fetchone()
        treatment = conn.execute(
            """
            SELECT id, patient_id, paid_at, amount_cents, total_amount_cents, discount_cents,
                   treatment, doctor_id, doctor_label, parent_payment_id, method, note,
                   examination_flag, followup_flag
              FROM payments
             WHERE id=?
               AND patient_id=?
               AND (parent_payment_id IS NULL OR parent_payment_id = '')
            """,
            (treatment_id, patient_id),
        ).fetchone()
        if not patient or not treatment:
            return None
        page_number = patient["primary_page_number"] if "primary_page_number" in patient.keys() else None
        if not page_number and _table_exists(conn, "patient_pages"):
            page_row = conn.execute(
                """
                SELECT page_number
                  FROM patient_pages
                 WHERE patient_id=?
                 ORDER BY rowid DESC
                 LIMIT 1
                """,
                (patient_id,),
            ).fetchone()
            if page_row:
                page_number = page_row["page_number"]
        child_sum_row = conn.execute(
            """
            SELECT COALESCE(SUM(amount_cents), 0) AS child_paid
              FROM payments
             WHERE parent_payment_id=?
               AND patient_id=?
            """,
            (treatment_id, patient_id),
        ).fetchone()
        total_cents = int(treatment["total_amount_cents"] or 0)
        discount_cents = int(treatment["discount_cents"] or 0)
        initial_cents = int(treatment["amount_cents"] or 0)
        child_paid_cents = int((child_sum_row["child_paid"] or 0) if child_sum_row else 0)
        total_paid_cents = initial_cents + child_paid_cents
        due_cents = max(total_cents - discount_cents, 0)
        remaining_cents = max(due_cents - total_paid_cents, 0)
        return {
            "patient_id": patient_id,
            "patient_name": patient["full_name"] or "",
            "phone": patient["phone"] or "",
            "page_number": page_number or "",
            "treatment_id": treatment_id,
            "treatment_text": treatment["treatment"] or "",
            "doctor_id": treatment["doctor_id"] or "",
            "doctor_label": treatment["doctor_label"] or "",
            "paid_at": treatment["paid_at"] or "",
            "method": treatment["method"] or "cash",
            "note": treatment["note"] or "",
            "visit_type": _visit_type_value(
                treatment["examination_flag"] if "examination_flag" in treatment.keys() else 0,
                treatment["followup_flag"] if "followup_flag" in treatment.keys() else 0,
                treatment["treatment"] or "",
            ),
            "initial_paid_cents": initial_cents,
            "child_paid_cents": child_paid_cents,
            "total_paid_cents": total_paid_cents,
            "total_amount_cents": total_cents,
            "discount_amount_cents": discount_cents,
            "remaining_cents": remaining_cents,
        }
    finally:
        conn.close()


def get_locked_payment_context(patient_id: str, payment_id: str) -> dict[str, Any] | None:
    conn = raw_db()
    try:
        payment = conn.execute(
            """
            SELECT id, patient_id, parent_payment_id, paid_at, amount_cents, method, note,
                   doctor_id, doctor_label
              FROM payments
             WHERE id=?
               AND patient_id=?
            """,
            (payment_id, patient_id),
        ).fetchone()
        if not payment:
            return None

        parent_payment_id = _text(payment["parent_payment_id"])
        treatment_id = payment["id"] if not parent_payment_id else parent_payment_id
        treatment_context = get_locked_treatment_context(patient_id, treatment_id)
        if not treatment_context:
            return None

        if treatment_id == payment["id"]:
            sibling_paid_cents = int(treatment_context.get("total_paid_cents") or 0) - int(payment["amount_cents"] or 0)
            is_initial_payment = True
        else:
            sibling_paid_row = conn.execute(
                """
                SELECT COALESCE(SUM(amount_cents), 0) AS sibling_paid
                  FROM payments
                 WHERE parent_payment_id=?
                   AND patient_id=?
                   AND id<>?
                """,
                (treatment_id, patient_id, payment_id),
            ).fetchone()
            sibling_paid_cents = int((sibling_paid_row["sibling_paid"] or 0) if sibling_paid_row else 0)
            sibling_paid_cents += int(treatment_context.get("initial_paid_cents") or 0)
            is_initial_payment = False

        due_cents = max(
            int(treatment_context.get("total_amount_cents") or 0) - int(treatment_context.get("discount_amount_cents") or 0),
            0,
        )
        max_amount_cents = max(due_cents - sibling_paid_cents, 0)

        return {
            "patient_id": patient_id,
            "payment_id": _text(payment["id"]),
            "treatment_id": treatment_id,
            "parent_payment_id": parent_payment_id or None,
            "is_initial_payment": is_initial_payment,
            "paid_at": _text(payment["paid_at"]),
            "amount_cents": int(payment["amount_cents"] or 0),
            "method": _text(payment["method"]) or "cash",
            "note": _text(payment["note"]),
            "doctor_id": _text(payment["doctor_id"]),
            "doctor_label": _text(payment["doctor_label"]),
            "max_amount_cents": max_amount_cents,
            "treatment_context": treatment_context,
        }
    finally:
        conn.close()


def get_locked_patient_context(patient_id: str) -> dict[str, Any] | None:
    snapshot = get_patient_profile_snapshot(patient_id)
    if not snapshot:
        return None
    return {
        "patient_id": snapshot["id"],
        "short_id": snapshot.get("short_id") or "",
        "patient_name": snapshot.get("full_name") or "",
        "full_name": snapshot.get("full_name") or "",
        "primary_phone": snapshot.get("primary_phone") or "",
        "phones": snapshot.get("phones") or [],
        "primary_page_number": snapshot.get("primary_page_number") or "",
        "pages": snapshot.get("pages") or [],
        "notes": snapshot.get("notes") or "",
    }


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
            ORDER BY updated_at DESC, submitted_at DESC, rowid DESC
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
            ORDER BY updated_at DESC, submitted_at DESC, rowid DESC
            LIMIT ?
            """,
            (*QUEUE_STATUSES, limit),
        ).fetchall()
        return [_decode_row(row) for row in rows]
    finally:
        conn.close()


def resubmit_returned_entry(entry_id: str, data: dict, *, actor_user_id: str) -> dict[str, Any]:
    return update_pending_entry(entry_id, data, actor_user_id=actor_user_id, mode="resubmit")


def update_pending_entry(entry_id: str, data: dict, *, actor_user_id: str, mode: str) -> dict[str, Any]:
    existing = get_entry(entry_id)
    if mode == "resubmit":
        entry = _require_returned_resubmittable_entry(existing, actor_user_id=actor_user_id)
        reviewed_by_user_id = None
        reviewed_at = None
        event_meta = {"resubmitted": True}
    elif mode == "manager_edit":
        entry = _require_manager_editable_entry(existing)
        reviewed_by_user_id = actor_user_id
        reviewed_at = _utc_now_iso()
        event_meta = {"manager_edit": True}
    else:
        raise ValueError("Unsupported Reception draft update mode.")

    payload = {
        "draft_type": entry["draft_type"],
        "source": entry["source"],
        "patient_intent": entry.get("patient_intent") or "unknown",
        "locked_patient_id": entry.get("locked_patient_id"),
        "locked_treatment_id": entry.get("locked_treatment_id"),
        "locked_payment_id": entry.get("locked_payment_id"),
        "target_patient_id": entry.get("target_patient_id"),
        "target_treatment_id": entry.get("target_treatment_id"),
        "target_payment_id": entry.get("target_payment_id"),
        "match_summary_json": entry.get("match_summary_json") or {},
        **data,
    }
    errors, warnings, normalized = validate_entry_payload(payload)
    if errors:
        raise ValueError("; ".join(errors))

    now = _utc_now_iso()
    conn = raw_db()
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            """
            UPDATE reception_entries
            SET patient_intent=?,
                locked_patient_id=?,
                locked_treatment_id=?,
                locked_payment_id=?,
                target_patient_id=?,
                target_treatment_id=?,
                target_payment_id=?,
                patient_name=?,
                page_number=?,
                phone=?,
                visit_date=?,
                visit_type=?,
                treatment_text=?,
                doctor_id=?,
                doctor_label=?,
                money_received_today=?,
                paid_today_cents=?,
                total_amount_cents=?,
                discount_amount_cents=?,
                payload_json=?,
                warnings_json=?,
                match_summary_json=?,
                status=?,
                updated_at=?,
                reviewed_by_user_id=?,
                reviewed_at=?,
                last_action=?,
                return_reason=NULL,
                hold_reason=NULL,
                rejection_reason=NULL
            WHERE id=?
            """,
            (
                normalized["patient_intent"],
                normalized["locked_patient_id"],
                normalized["locked_treatment_id"],
                normalized["locked_payment_id"],
                normalized["target_patient_id"],
                normalized["target_treatment_id"],
                normalized["target_payment_id"],
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
                "edited",
                now,
                reviewed_by_user_id,
                reviewed_at,
                "edited",
                entry_id,
            ),
        )
        _insert_event(
            conn,
            entry_id=entry_id,
            action="edited",
            actor_user_id=actor_user_id,
            from_status=entry["status"],
            to_status="edited",
            note=None,
            meta_json=event_meta,
            created_at=now,
        )
        conn.commit()
    finally:
        conn.close()
    return get_entry(entry_id)


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


def _create_live_patient_from_entry(conn, entry: dict[str, Any]) -> str:
    patient_id = str(uuid4())
    short_id = next_short_id(conn)
    patient_name = _text(entry.get("patient_name"))
    phone = _nullable_text(entry.get("phone"))
    note_parts: list[str] = []
    payload = entry.get("payload_json") or {}
    if isinstance(payload, dict):
        note_text = _nullable_text(payload.get("note"))
        if note_text:
            note_parts.append(note_text)
    notes = "\n".join(part for part in note_parts if part) or None
    primary_page = _nullable_text(entry.get("page_number"))

    if _column_exists(conn, "patients", "primary_page_number"):
        conn.execute(
            """
            INSERT INTO patients(id, short_id, full_name, phone, notes, primary_page_number)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (patient_id, short_id, patient_name, phone, notes, primary_page),
        )
    else:
        conn.execute(
            """
            INSERT INTO patients(id, short_id, full_name, phone, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (patient_id, short_id, patient_name, phone, notes),
        )

    if phone and _table_exists(conn, "patient_phones"):
        conn.execute(
            """
            INSERT INTO patient_phones(id, patient_id, phone, phone_normalized, label, is_primary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                patient_id,
                phone,
                _normalize_phone_digits(phone),
                None,
                1,
            ),
        )

    if primary_page and _table_exists(conn, "patient_pages"):
        conn.execute(
            """
            INSERT OR IGNORE INTO patient_pages(id, patient_id, page_number, notebook_name)
            VALUES (?, ?, ?, ?)
            """,
            (str(uuid4()), patient_id, primary_page, None),
        )

    return patient_id


def _create_live_treatment_from_entry(conn, entry: dict[str, Any], *, patient_id: str) -> str:
    treatment_id = str(uuid4())
    is_visit_only = entry.get("draft_type") == "new_visit_only"
    if is_visit_only:
        total_cents = 0
        discount_cents = 0
        paid_today_cents = 0
        due_cents = 0
        exam_flag, followup_flag = (0, 0)
        treatment_label = _consultation_visit_name()
    else:
        total_cents = entry.get("total_amount_cents")
        if total_cents is None:
            raise ValueError("Total amount is required before approval.")

        discount_cents = int(entry.get("discount_amount_cents") or 0)
        paid_today_cents = int(entry.get("paid_today_cents") or 0)
        due_cents = max(int(total_cents) - discount_cents, 0)
        if paid_today_cents > due_cents:
            raise ValueError("Paid today cannot be greater than the amount due.")
        exam_flag, followup_flag = _visit_type_flags(entry.get("visit_type"))
        treatment_label = _text(entry.get("treatment_text"))

    payload = entry.get("payload_json") or {}
    notes = ""
    if isinstance(payload, dict):
        notes = _text(payload.get("note"))

    conn.execute(
        """
        INSERT INTO payments(
            id, patient_id, parent_payment_id, paid_at, amount_cents, method, note, treatment,
            doctor_id, doctor_label,
            remaining_cents, total_amount_cents, examination_flag, followup_flag, discount_cents
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            treatment_id,
            patient_id,
            None,
            _text(entry.get("visit_date")) or datetime.now(timezone.utc).date().isoformat(),
            paid_today_cents,
            "cash",
            notes,
            treatment_label,
            _text(entry.get("doctor_id")),
            _text(entry.get("doctor_label")),
            max(due_cents - paid_today_cents, 0),
            int(total_cents),
            exam_flag,
            followup_flag,
            discount_cents,
        ),
    )
    return treatment_id


def _get_review_patient_row(conn, patient_id: str):
    page_expr = _patient_page_expr(conn)
    return conn.execute(
        f"""
        SELECT p.id, p.full_name, p.short_id, p.phone, {page_expr} AS page_number
        FROM patients p
        WHERE p.id=?
        LIMIT 1
        """,
        (patient_id,),
    ).fetchone()


def _search_review_patient_rows(conn, query: str, *, limit: int = 25) -> list[dict[str, Any]]:
    query_text = _text(query)
    if not query_text:
        return []

    norm_query = normalize_arabic(query_text) or query_text
    text_like = f"%{query_text}%"
    norm_like = f"%{norm_query}%"
    digits = _normalize_phone_digits(query_text)
    digits_like = f"%{digits}%" if digits else None
    page_expr = _patient_page_expr(conn)
    has_patient_phones = _table_exists(conn, "patient_phones")

    conditions = [
        "normalize_arabic(p.full_name) LIKE ?",
        "p.short_id LIKE ?",
        f"{page_expr} LIKE ?",
    ]
    params: list[Any] = [norm_like, text_like, text_like]
    if digits_like:
        conditions.extend(
            [
                "p.phone LIKE ?",
                "replace(replace(replace(replace(replace(p.phone,' ',''),'-',''),'+',''),'(',''),')','') LIKE ?",
            ]
        )
        params.extend([text_like, digits_like])
        if has_patient_phones:
            conditions.append(
                """
                EXISTS (
                    SELECT 1
                    FROM patient_phones ph
                    WHERE ph.patient_id = p.id
                      AND (
                          ph.phone LIKE ?
                          OR ph.phone_normalized LIKE ?
                          OR replace(replace(replace(replace(replace(ph.phone,' ',''),'-',''),'+',''),'(',''),')','') LIKE ?
                      )
                )
                """
            )
            params.extend([text_like, digits_like, digits_like])

    rows = conn.execute(
        f"""
        SELECT p.id, p.full_name, p.short_id, p.phone, {page_expr} AS page_number
        FROM patients p
        WHERE {' OR '.join(conditions)}
        ORDER BY p.rowid DESC
        LIMIT ?
        """,
        (*params, max(limit, 1)),
    ).fetchall()

    scored_rows: list[tuple[int, int, dict[str, Any]]] = []
    lowered_query = query_text.lower()
    for index, row in enumerate(rows):
        patient = {
            "id": row["id"],
            "full_name": row["full_name"] or "",
            "short_id": row["short_id"] or "",
            "phone": row["phone"] or "",
            "page_number": row["page_number"] or "",
        }
        score = 0
        normalized_name = normalize_arabic(patient["full_name"]) or patient["full_name"]
        if normalized_name == norm_query:
            score += 80
        elif norm_query in normalized_name:
            score += 30
        if patient["short_id"].lower() == lowered_query:
            score += 70
        elif lowered_query and lowered_query in patient["short_id"].lower():
            score += 20
        if patient["page_number"].lower() == lowered_query:
            score += 65
        elif lowered_query and lowered_query in patient["page_number"].lower():
            score += 20
        if digits:
            phone_digits = _normalize_phone_digits(patient["phone"])
            if phone_digits == digits:
                score += 75
            elif digits in phone_digits:
                score += 25
        scored_rows.append((score, index, patient))

    scored_rows.sort(key=lambda item: (-item[0], item[1]))
    return [patient for _, _, patient in scored_rows[:limit]]


def search_reception_review_patients(
    query: str,
    *,
    limit: int = 8,
    conn=None,
) -> list[dict[str, Any]]:
    owns_connection = conn is None
    conn = conn or raw_db()
    try:
        return _search_review_patient_rows(conn, query, limit=limit)
    finally:
        if owns_connection:
            conn.close()


def list_reception_candidate_patients(
    entry: dict[str, Any],
    *,
    limit: int = 5,
    conn=None,
) -> list[dict[str, Any]]:
    owns_connection = conn is None
    conn = conn or raw_db()
    try:
        seen_ids: set[str] = set()
        candidates: list[dict[str, Any]] = []
        for clue in (
            _text(entry.get("phone")),
            _text(entry.get("page_number")),
            _text(entry.get("patient_name")),
        ):
            if not clue:
                continue
            for patient in _search_review_patient_rows(conn, clue, limit=max(limit * 2, 6)):
                if patient["id"] in seen_ids:
                    continue
                seen_ids.add(patient["id"])
                candidates.append(patient)
                if len(candidates) >= limit:
                    return candidates
        return candidates
    finally:
        if owns_connection:
            conn.close()


def get_reception_review_patient(patient_id: str, *, conn=None) -> dict[str, Any] | None:
    patient_id = _text(patient_id)
    if not patient_id:
        return None
    owns_connection = conn is None
    conn = conn or raw_db()
    try:
        row = _get_review_patient_row(conn, patient_id)
        if not row:
            return None
        return {
            "id": row["id"],
            "full_name": row["full_name"] or "",
            "short_id": row["short_id"] or "",
            "phone": row["phone"] or "",
            "page_number": row["page_number"] or "",
        }
    finally:
        if owns_connection:
            conn.close()


def _treatment_correction_payload(context: dict[str, Any] | None) -> dict[str, Any]:
    context = context or {}
    return {
        "patient_id": _text(context.get("patient_id")),
        "treatment_id": _text(context.get("treatment_id")),
        "treatment_text": _text(context.get("treatment_text")),
        "visit_date": _text(context.get("paid_at")),
        "visit_type": _text(context.get("visit_type")) or "none",
        "doctor_id": _text(context.get("doctor_id")),
        "doctor_label": _text(context.get("doctor_label")),
        "total_amount_cents": int(context.get("total_amount_cents") or 0),
        "discount_amount_cents": int(context.get("discount_amount_cents") or 0),
        "note": _text(context.get("note")),
        "total_paid_cents": int(context.get("total_paid_cents") or 0),
        "remaining_cents": int(context.get("remaining_cents") or 0),
    }


def _payment_correction_payload(context: dict[str, Any] | None) -> dict[str, Any]:
    context = context or {}
    treatment_context = context.get("treatment_context") if isinstance(context, dict) else {}
    return {
        "payment_id": _text(context.get("payment_id")),
        "treatment_id": _text(context.get("treatment_id")),
        "is_initial_payment": 1 if context.get("is_initial_payment") else 0,
        "amount_cents": int(context.get("amount_cents") or 0),
        "visit_date": _text(context.get("paid_at")),
        "method": _text(context.get("method")) or "cash",
        "doctor_id": _text(context.get("doctor_id")),
        "doctor_label": _text(context.get("doctor_label")),
        "note": _text(context.get("note")),
        "treatment_remaining_cents": int((treatment_context or {}).get("remaining_cents") or 0),
        "treatment_total_paid_cents": int((treatment_context or {}).get("total_paid_cents") or 0),
    }


def _recompute_treatment_remaining(conn, *, treatment_id: str, patient_id: str) -> dict[str, int]:
    treatment = conn.execute(
        """
        SELECT amount_cents, total_amount_cents, discount_cents
          FROM payments
         WHERE id=?
           AND patient_id=?
           AND (parent_payment_id IS NULL OR parent_payment_id = '')
        """,
        (treatment_id, patient_id),
    ).fetchone()
    if not treatment:
        raise ValueError("Locked treatment was not found.")
    child_sum_row = conn.execute(
        """
        SELECT COALESCE(SUM(amount_cents), 0) AS child_paid
          FROM payments
         WHERE parent_payment_id=?
           AND patient_id=?
        """,
        (treatment_id, patient_id),
    ).fetchone()
    total_cents = int(treatment["total_amount_cents"] or 0)
    discount_cents = int(treatment["discount_cents"] or 0)
    initial_cents = int(treatment["amount_cents"] or 0)
    child_paid_cents = int((child_sum_row["child_paid"] or 0) if child_sum_row else 0)
    due_cents = max(total_cents - discount_cents, 0)
    total_paid_cents = initial_cents + child_paid_cents
    remaining_cents = max(due_cents - total_paid_cents, 0)
    conn.execute(
        "UPDATE payments SET remaining_cents=? WHERE id=? AND patient_id=?",
        (remaining_cents, treatment_id, patient_id),
    )
    return {
        "remaining_cents": remaining_cents,
        "total_paid_cents": total_paid_cents,
    }


def approve_edit_payment_entry(entry_id: str, *, actor_user_id: str) -> dict[str, Any]:
    now = _utc_now_iso()
    locked_patient_id: str | None = None
    locked_treatment_id: str | None = None
    locked_payment_id: str | None = None
    conn = raw_db()
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        entry = _require_active_entry(_fetch_entry(conn, entry_id), action="approve")

        if entry.get("draft_type") != "edit_payment" or entry.get("source") != "treatment_card":
            raise ValueError("Only treatment-card payment correction drafts can be approved in this slice.")
        if entry.get("status") not in {"new", "edited", "held"}:
            raise ValueError("Only pending drafts can be approved.")

        locked_patient_id = _nullable_text(entry.get("locked_patient_id"))
        locked_treatment_id = _nullable_text(entry.get("locked_treatment_id"))
        locked_payment_id = _nullable_text(entry.get("locked_payment_id"))
        if not locked_patient_id or not locked_treatment_id or not locked_payment_id:
            raise ValueError("Locked payment context is required for approval.")
        if entry.get("target_patient_id") or entry.get("target_treatment_id") or entry.get("target_payment_id"):
            raise ValueError("This payment correction draft already has live targets and cannot be approved again.")

        live_context = get_locked_payment_context(locked_patient_id, locked_payment_id)
        if not live_context or _text(live_context.get("treatment_id")) != locked_treatment_id:
            raise ValueError("Locked payment was not found.")

        payload = entry.get("payload_json") or {}
        current_snapshot = payload.get("current")
        proposed = payload.get("proposed")
        if not isinstance(current_snapshot, dict) or not isinstance(proposed, dict):
            raise ValueError("Malformed payment correction payload.")

        latest_snapshot = _payment_correction_payload(live_context)
        compare_keys = ("amount_cents", "visit_date", "method", "doctor_id", "doctor_label", "note", "is_initial_payment")
        if any(_text(current_snapshot.get(key)) != _text(latest_snapshot.get(key)) for key in compare_keys):
            raise ValueError("The live payment changed after this draft was created. Re-open the draft and review it again.")

        amount_cents = int(entry.get("paid_today_cents") or 0)
        if amount_cents <= 0:
            raise ValueError("Payment amount must be greater than zero.")
        max_amount_cents = int(live_context.get("max_amount_cents") or 0)
        if amount_cents > max_amount_cents:
            raise ValueError("Payment amount cannot be greater than the amount still due on the locked treatment.")

        conn.execute(
            """
            UPDATE payments
               SET paid_at=?,
                   amount_cents=?,
                   method=?,
                   note=?,
                   doctor_id=?,
                   doctor_label=?
             WHERE id=?
               AND patient_id=?
            """,
            (
                _text(entry.get("visit_date")) or _text(proposed.get("visit_date")) or latest_snapshot["visit_date"],
                amount_cents,
                _text(proposed.get("method")) or "cash",
                _text(proposed.get("note")),
                _text(entry.get("doctor_id")) or _text(proposed.get("doctor_id")),
                _text(entry.get("doctor_label")) or _text(proposed.get("doctor_label")),
                locked_payment_id,
                locked_patient_id,
            ),
        )
        if conn.total_changes <= 0:
            raise ValueError("Locked payment was not found.")

        _recompute_treatment_remaining(conn, treatment_id=locked_treatment_id, patient_id=locked_patient_id)

        conn.execute(
            """
            UPDATE reception_entries
            SET status=?,
                reviewed_by_user_id=?,
                updated_at=?,
                reviewed_at=?,
                last_action=?,
                hold_reason=NULL,
                return_reason=NULL,
                rejection_reason=NULL,
                target_patient_id=?,
                target_treatment_id=?,
                target_payment_id=?
            WHERE id=?
            """,
            (
                "approved",
                actor_user_id,
                now,
                now,
                "approved",
                locked_patient_id,
                locked_treatment_id,
                locked_payment_id,
                entry_id,
            ),
        )
        _insert_event(
            conn,
            entry_id=entry_id,
            action="approved",
            actor_user_id=actor_user_id,
            from_status=entry["status"],
            to_status="approved",
            note=None,
            meta_json={
                "target_patient_id": locked_patient_id,
                "target_treatment_id": locked_treatment_id,
                "target_payment_id": locked_payment_id,
                "draft_type": "edit_payment",
                "source": "treatment_card",
            },
            created_at=now,
        )
        conn.commit()
    finally:
        conn.close()

    if locked_payment_id and locked_patient_id and locked_treatment_id:
        try:
            write_event(
                actor_user_id,
                "payment_update",
                entity="payment",
                entity_id=locked_payment_id,
                meta={
                    "patient_id": locked_patient_id,
                    "treatment_id": locked_treatment_id,
                    "target_patient_id": locked_patient_id,
                    "target_treatment_id": locked_treatment_id,
                    "target_payment_id": locked_payment_id,
                    "source": "reception_approval",
                    "draft_type": "edit_payment",
                    "reception_entry_id": entry_id,
                },
            )
        except Exception:
            pass
    return get_entry(entry_id)


def approve_edit_treatment_entry(entry_id: str, *, actor_user_id: str) -> dict[str, Any]:
    now = _utc_now_iso()
    locked_patient_id: str | None = None
    locked_treatment_id: str | None = None
    conn = raw_db()
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        entry = _require_active_entry(_fetch_entry(conn, entry_id), action="approve")

        if entry.get("draft_type") != "edit_treatment" or entry.get("source") != "treatment_card":
            raise ValueError("Only treatment-card treatment correction drafts can be approved in this slice.")
        if entry.get("status") not in {"new", "edited", "held"}:
            raise ValueError("Only pending drafts can be approved.")

        locked_patient_id = _nullable_text(entry.get("locked_patient_id"))
        locked_treatment_id = _nullable_text(entry.get("locked_treatment_id"))
        if not locked_patient_id or not locked_treatment_id:
            raise ValueError("Locked treatment context is required for approval.")
        if entry.get("target_patient_id") or entry.get("target_treatment_id") or entry.get("target_payment_id"):
            raise ValueError("This treatment correction draft already has live targets and cannot be approved again.")

        live_context = get_locked_treatment_context(locked_patient_id, locked_treatment_id)
        if not live_context:
            raise ValueError("Locked treatment was not found.")

        payload = entry.get("payload_json") or {}
        proposed = payload.get("proposed")
        if not isinstance(proposed, dict):
            raise ValueError("Malformed treatment correction payload.")

        total_cents = entry.get("total_amount_cents")
        if total_cents is None:
            raise ValueError("Total amount is required.")
        total_cents = int(total_cents)
        discount_cents = int(entry.get("discount_amount_cents") or 0)
        if discount_cents > total_cents:
            raise ValueError("Discount cannot be greater than the total amount.")

        total_paid_cents = int(live_context.get("total_paid_cents") or 0)
        due_cents = max(total_cents - discount_cents, 0)
        if due_cents < total_paid_cents:
            raise ValueError("Total amount minus discount cannot be less than the amount already paid.")

        remaining_cents = due_cents - total_paid_cents
        exam_flag, followup_flag = _visit_type_flags(proposed.get("visit_type"))

        conn.execute(
            """
            UPDATE payments
               SET paid_at=?,
                   note=?,
                   treatment=?,
                   doctor_id=?,
                   doctor_label=?,
                   remaining_cents=?,
                   total_amount_cents=?,
                   examination_flag=?,
                   followup_flag=?,
                   discount_cents=?
             WHERE id=?
               AND patient_id=?
               AND (parent_payment_id IS NULL OR parent_payment_id = '')
            """,
            (
                _text(entry.get("visit_date")) or live_context.get("paid_at") or datetime.now(timezone.utc).date().isoformat(),
                _text(proposed.get("note")),
                _text(entry.get("treatment_text")),
                _text(entry.get("doctor_id")),
                _text(entry.get("doctor_label")),
                remaining_cents,
                total_cents,
                exam_flag,
                followup_flag,
                discount_cents,
                locked_treatment_id,
                locked_patient_id,
            ),
        )
        if conn.total_changes <= 0:
            raise ValueError("Locked treatment was not found.")

        conn.execute(
            """
            UPDATE reception_entries
            SET status=?,
                reviewed_by_user_id=?,
                updated_at=?,
                reviewed_at=?,
                last_action=?,
                hold_reason=NULL,
                return_reason=NULL,
                rejection_reason=NULL,
                target_patient_id=?,
                target_treatment_id=?,
                target_payment_id=NULL
            WHERE id=?
            """,
            (
                "approved",
                actor_user_id,
                now,
                now,
                "approved",
                locked_patient_id,
                locked_treatment_id,
                entry_id,
            ),
        )
        _insert_event(
            conn,
            entry_id=entry_id,
            action="approved",
            actor_user_id=actor_user_id,
            from_status=entry["status"],
            to_status="approved",
            note=None,
            meta_json={
                "target_patient_id": locked_patient_id,
                "target_treatment_id": locked_treatment_id,
                "draft_type": "edit_treatment",
                "source": "treatment_card",
            },
            created_at=now,
        )
        conn.commit()
    finally:
        conn.close()

    if locked_patient_id and locked_treatment_id:
        try:
            write_event(
                actor_user_id,
                "payment_update",
                entity="payment",
                entity_id=locked_treatment_id,
                meta={
                    "patient_id": locked_patient_id,
                    "treatment_id": locked_treatment_id,
                    "target_patient_id": locked_patient_id,
                    "target_treatment_id": locked_treatment_id,
                    "source": "reception_approval",
                    "draft_type": "edit_treatment",
                    "reception_entry_id": entry_id,
                },
            )
        except Exception:
            pass
    return get_entry(entry_id)


def approve_new_treatment_entry(
    entry_id: str,
    *,
    actor_user_id: str,
    approval_route: str = "create_new",
    target_patient_id: str | None = None,
) -> dict[str, Any]:
    now = _utc_now_iso()
    conn = raw_db()
    live_patient_id: str | None = None
    created_treatment_id: str | None = None
    route_value = _text(approval_route).lower() or "create_new"
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        entry = _require_active_entry(_fetch_entry(conn, entry_id), action="approve")

        if entry.get("draft_type") not in {"new_treatment", "new_visit_only"} or entry.get("source") not in {"reception_desk", "patient_file"}:
            raise ValueError("Only supported new treatment drafts can be approved in this slice.")
        if entry.get("locked_treatment_id") or entry.get("locked_payment_id"):
            raise ValueError("Locked-context drafts are not supported by this approval step.")
        if entry.get("target_patient_id") or entry.get("target_treatment_id") or entry.get("target_payment_id"):
            raise ValueError("This draft already has live targets and cannot be approved again.")
        if entry.get("status") not in {"new", "edited", "held"}:
            raise ValueError("Only pending drafts can be approved.")
        if route_value not in {"create_new", "attach_existing"}:
            raise ValueError("Choose how this draft should be posted before approval.")

        if entry.get("source") == "patient_file":
            live_patient_id = _nullable_text(entry.get("locked_patient_id"))
            if not live_patient_id:
                raise ValueError("Locked patient context is required for this treatment draft.")
            if not get_reception_review_patient(live_patient_id, conn=conn):
                raise ValueError("The locked live patient no longer exists. Review the draft again before approving.")
            route_value = "locked_patient"
        elif route_value == "attach_existing":
            live_patient_id = _nullable_text(target_patient_id)
            if not live_patient_id:
                raise ValueError("Choose an existing patient before approval.")
            if not get_reception_review_patient(live_patient_id, conn=conn):
                raise ValueError("The selected live patient no longer exists. Review the draft again before approving.")
        else:
            live_patient_id = _create_live_patient_from_entry(conn, entry)

        created_treatment_id = _create_live_treatment_from_entry(conn, entry, patient_id=live_patient_id)

        conn.execute(
            """
            UPDATE reception_entries
            SET status=?,
                reviewed_by_user_id=?,
                updated_at=?,
                reviewed_at=?,
                last_action=?,
                hold_reason=NULL,
                return_reason=NULL,
                rejection_reason=NULL,
                target_patient_id=?,
                target_treatment_id=?,
                target_payment_id=?
            WHERE id=?
            """,
            (
                "approved",
                actor_user_id,
                now,
                now,
                "approved",
                live_patient_id,
                created_treatment_id,
                created_treatment_id,
                entry_id,
            ),
        )
        _insert_event(
            conn,
            entry_id=entry_id,
            action="approved",
            actor_user_id=actor_user_id,
            from_status=entry["status"],
            to_status="approved",
            note=None,
            meta_json={
                "target_patient_id": live_patient_id,
                "target_treatment_id": created_treatment_id,
                "approval_route": route_value,
            },
            created_at=now,
        )
        conn.commit()
        if route_value == "create_new":
            migrate_patients_drop_unique_short_id(conn)
    finally:
        conn.close()

    if created_treatment_id and live_patient_id:
        try:
            write_event(
                actor_user_id,
                "payment_create",
                entity="payment",
                entity_id=created_treatment_id,
                meta={
                    "patient_id": live_patient_id,
                    "source": "reception_approval",
                    "reception_entry_id": entry_id,
                    "approval_route": route_value,
                },
            )
        except Exception:
            pass
    return get_entry(entry_id)


def approve_new_payment_entry(entry_id: str, *, actor_user_id: str) -> dict[str, Any]:
    now = _utc_now_iso()
    conn = raw_db()
    created_payment_id: str | None = None
    locked_patient_id: str | None = None
    locked_treatment_id: str | None = None
    amount_cents: int | None = None
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        entry = _require_active_entry(_fetch_entry(conn, entry_id), action="approve")

        if entry.get("draft_type") != "new_payment" or entry.get("source") != "treatment_card":
            raise ValueError("Only treatment-card payment drafts can be approved in this slice.")
        if entry.get("status") not in {"new", "edited", "held"}:
            raise ValueError("Only pending drafts can be approved.")

        locked_patient_id = _nullable_text(entry.get("locked_patient_id"))
        locked_treatment_id = _nullable_text(entry.get("locked_treatment_id"))
        if not locked_patient_id or not locked_treatment_id:
            raise ValueError("Locked treatment context is required for payment approval.")
        if entry.get("target_patient_id") or entry.get("target_treatment_id") or entry.get("target_payment_id"):
            raise ValueError("This payment draft already has live targets and cannot be approved again.")

        amount_cents = int(entry.get("paid_today_cents") or 0)
        if amount_cents <= 0:
            raise ValueError("Payment amount must be greater than zero.")

        payload = entry.get("payload_json") or {}
        method = _text(payload.get("method")) or "cash"
        note = _text(payload.get("note"))
        paid_at = _text(entry.get("visit_date")) or datetime.now(timezone.utc).date().isoformat()

        result = add_payment_to_treatment(
            conn,
            locked_treatment_id,
            locked_patient_id,
            amount_cents,
            paid_at,
            method,
            note,
            _text(entry.get("doctor_id")),
            _text(entry.get("doctor_label")),
        )
        created_payment_id = result["payment_id"]

        conn.execute(
            """
            UPDATE reception_entries
            SET status=?,
                reviewed_by_user_id=?,
                updated_at=?,
                reviewed_at=?,
                last_action=?,
                hold_reason=NULL,
                return_reason=NULL,
                rejection_reason=NULL,
                target_patient_id=?,
                target_treatment_id=?,
                target_payment_id=?
            WHERE id=?
            """,
            (
                "approved",
                actor_user_id,
                now,
                now,
                "approved",
                locked_patient_id,
                locked_treatment_id,
                created_payment_id,
                entry_id,
            ),
        )
        _insert_event(
            conn,
            entry_id=entry_id,
            action="approved",
            actor_user_id=actor_user_id,
            from_status=entry["status"],
            to_status="approved",
            note=None,
            meta_json={
                "target_patient_id": locked_patient_id,
                "target_treatment_id": locked_treatment_id,
                "target_payment_id": created_payment_id,
                "amount_cents": amount_cents,
            },
            created_at=now,
        )
        conn.commit()
    finally:
        conn.close()

    if created_payment_id and locked_patient_id and locked_treatment_id and amount_cents is not None:
        try:
            write_event(
                actor_user_id,
                "payment_add_to_treatment",
                entity="payment",
                entity_id=created_payment_id,
                meta={
                    "patient_id": locked_patient_id,
                    "treatment_id": locked_treatment_id,
                    "amount_cents": amount_cents,
                    "source": "reception_approval",
                    "reception_entry_id": entry_id,
                },
            )
        except Exception:
            pass
    return get_entry(entry_id)


def approve_edit_patient_entry(entry_id: str, *, actor_user_id: str) -> dict[str, Any]:
    now = _utc_now_iso()
    locked_patient_id: str | None = None
    conn = raw_db()
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        entry = _require_active_entry(_fetch_entry(conn, entry_id), action="approve")

        if entry.get("draft_type") != "edit_patient" or entry.get("source") != "patient_file":
            raise ValueError("Only patient-file correction drafts can be approved in this slice.")
        if entry.get("status") not in {"new", "edited", "held"}:
            raise ValueError("Only pending drafts can be approved.")

        locked_patient_id = _nullable_text(entry.get("locked_patient_id"))
        if not locked_patient_id:
            raise ValueError("Locked patient context is required for approval.")
        if entry.get("target_patient_id") or entry.get("target_treatment_id") or entry.get("target_payment_id"):
            raise ValueError("This patient correction draft already has live targets and cannot be approved again.")

        live_snapshot = get_patient_profile_snapshot(locked_patient_id, conn=conn)
        if not live_snapshot:
            raise ValueError("Locked patient was not found.")

        payload = entry.get("payload_json") or {}
        proposed_raw = payload.get("proposed")
        if not isinstance(proposed_raw, dict):
            raise ValueError("Malformed patient correction payload.")
        profile_errors, normalized_profile = normalize_patient_profile_update(
            proposed_raw,
            patient_id=locked_patient_id,
        )
        if profile_errors:
            raise ValueError("; ".join(profile_errors))
        proposed_short_id = _text(normalized_profile.get("short_id"))
        if proposed_short_id and proposed_short_id != _text(live_snapshot.get("short_id")):
            raise ValueError("Changing file number is not supported in this slice.")

        apply_patient_profile_update(conn, locked_patient_id, normalized_profile)

        conn.execute(
            """
            UPDATE reception_entries
            SET status=?,
                reviewed_by_user_id=?,
                updated_at=?,
                reviewed_at=?,
                last_action=?,
                hold_reason=NULL,
                return_reason=NULL,
                rejection_reason=NULL,
                target_patient_id=?,
                target_treatment_id=NULL,
                target_payment_id=NULL
            WHERE id=?
            """,
            (
                "approved",
                actor_user_id,
                now,
                now,
                "approved",
                locked_patient_id,
                entry_id,
            ),
        )
        _insert_event(
            conn,
            entry_id=entry_id,
            action="approved",
            actor_user_id=actor_user_id,
            from_status=entry["status"],
            to_status="approved",
            note=None,
            meta_json={
                "target_patient_id": locked_patient_id,
                "draft_type": "edit_patient",
                "source": "patient_file",
            },
            created_at=now,
        )
        conn.commit()
    finally:
        conn.close()

    if locked_patient_id:
        try:
            write_event(
                actor_user_id,
                "patient_update",
                entity="patient",
                entity_id=locked_patient_id,
                meta={
                    "patient_id": locked_patient_id,
                    "target_patient_id": locked_patient_id,
                    "source": "reception_approval",
                    "draft_type": "edit_patient",
                    "reception_entry_id": entry_id,
                },
            )
        except Exception:
            pass
    return get_entry(entry_id)


def list_entry_events(entry_id: str) -> list[dict[str, Any]]:
    conn = raw_db()
    try:
        rows = conn.execute(
            """
            SELECT * FROM reception_entry_events
            WHERE entry_id=?
            ORDER BY created_at DESC, rowid DESC
            """,
            (entry_id,),
        ).fetchall()
        return [_decode_row(row) for row in rows]
    finally:
        conn.close()


def list_history_events(
    *,
    submitted_by_user_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 200), 500))
    clauses: list[str] = []
    params: list[Any] = []
    if submitted_by_user_id:
        clauses.append("re.submitted_by_user_id = ?")
        params.append(submitted_by_user_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = raw_db()
    try:
        rows = conn.execute(
            f"""
            SELECT
                ev.*,
                re.draft_type,
                re.source,
                re.status,
                re.last_action,
                re.patient_name,
                re.treatment_text,
                re.submitted_by_user_id,
                u.username AS actor_username
            FROM reception_entry_events ev
            JOIN reception_entries re ON re.id = ev.entry_id
            LEFT JOIN users u ON u.id = ev.actor_user_id
            {where}
            ORDER BY ev.created_at DESC, ev.rowid DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        return [_decode_row(row) for row in rows]
    finally:
        conn.close()
