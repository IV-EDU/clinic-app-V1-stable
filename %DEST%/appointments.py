"""Appointment scheduling helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3
import uuid
from typing import Sequence

from flask import current_app

from clinic_app.services.database import db
from clinic_app.services.doctor_colors import get_doctor_colors


ISO_FMT = "%Y-%m-%dT%H:%M:%S"
UPCOMING_THRESHOLD_SECONDS = 3600  # 1 hour threshold for "upcoming" status


class AppointmentError(Exception):
    """Base exception for appointment operations."""


class AppointmentOverlap(AppointmentError):
    """Raised when a requested slot overlaps an existing booking."""


class AppointmentNotFound(AppointmentError):
    """Raised when an appointment cannot be located."""


def _format_clock_label(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    minute = dt.strftime("%M")
    ampm = "PM" if dt.hour >= 12 else "AM"
    return f"{hour}:{minute} {ampm}"


def _slot_labels(starts_at: str, ends_at: str) -> dict[str, str]:
    start_dt = datetime.strptime(starts_at, ISO_FMT)
    end_dt = datetime.strptime(ends_at, ISO_FMT)
    start_label = _format_clock_label(start_dt)
    end_label = _format_clock_label(end_dt)
    return {
        "start_label": start_label,
        "end_label": end_label,
        "range_label": f"{start_label} → {end_label}",
    }


def format_time_range(starts_at: str, ends_at: str) -> str:
    """Return a human-friendly time span label (e.g. `9:00 AM → 9:30 AM`)."""

    return _slot_labels(starts_at, ends_at)["range_label"]


def _slugify(label: str) -> str:
    keep = []
    for ch in label.lower():
        if ch.isalnum():
            keep.append(ch)
        elif ch in {" ", "-", "_"}:
            keep.append("-")
    slug = "".join(keep).strip("-")
    return slug or "doctor"


def doctor_choices() -> list[tuple[str, str]]:
    doctors = current_app.config.get("APPOINTMENT_DOCTORS", [])  # type: ignore[attr-defined]
    if not doctors:
        doctors = ["On Call"]
    return [(_slugify(name), name) for name in doctors]


def get_appointment_time_status(starts_at: str, ends_at: str) -> str:
    """Determine time-based status of appointment."""
    now = datetime.now(timezone.utc)
    start_dt = datetime.strptime(starts_at, ISO_FMT).replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(ends_at, ISO_FMT).replace(tzinfo=timezone.utc)
    
    if now < start_dt:
        # Future appointment
        if (start_dt - now).total_seconds() < UPCOMING_THRESHOLD_SECONDS:
            return "upcoming"  # Yellow
        else:
            return "scheduled"  # Green
    elif now >= start_dt and now <= end_dt:
        return "in-progress"  # Blue
    else:
        return "overdue"  # Red


def _combine_datetime(day: str, time24: str) -> datetime:
    try:
        return datetime.strptime(f"{day} {time24}", "%Y-%m-%d %H:%M")
    except ValueError as exc:  # pragma: no cover - validated upstream
        raise AppointmentError("invalid_datetime") from exc


def _grace_minutes() -> int:
    return int(current_app.config.get("APPOINTMENT_CONFLICT_GRACE_MINUTES", 5))


def _slot_minutes() -> int:
    return int(current_app.config.get("APPOINTMENT_SLOT_MINUTES", 30))


def _serialize(dt: datetime) -> str:
    return dt.replace(second=0, microsecond=0).strftime(ISO_FMT)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _resolve_patient(conn: sqlite3.Connection, lookup: str) -> tuple[str | None, str | None, str | None]:
    if not lookup:
        return None, None, None
    normalized = lookup.strip()
    if not normalized:
        return None, None, None
    row = conn.execute(
        """
        SELECT id, full_name, phone
        FROM patients
        WHERE lower(short_id) = lower(?) OR lower(full_name) = lower(?)
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (normalized, normalized),
    ).fetchone()
    if not row:
        return None, None, None
    return row["id"], row["full_name"], row["phone"]


def _check_overlap(
    conn: sqlite3.Connection,
    doctor_id: str,
    start_iso: str,
    end_iso: str,
    *,
    exclude_id: str | None = None,
) -> None:
    params: list[str] = [doctor_id, end_iso, start_iso]
    sql = """
        SELECT id, title
        FROM appointments
        WHERE doctor_id = ?
          AND starts_at < ?
          AND ends_at > ?
    """
    if exclude_id:
        sql += " AND id != ?"
        params.append(exclude_id)
    conflict = conn.execute(sql, params).fetchone()
    if conflict:
        raise AppointmentOverlap(f"conflict_with:{conflict['id']}")


def _extract_patient_details(conn, form_data: dict[str, str]) -> tuple[str | None, str, str | None]:
    patient_id = (form_data.get("patient_id") or "").strip()
    patient_name = (form_data.get("patient_name") or "").strip()
    patient_phone = (form_data.get("patient_phone") or "").strip()
    patient_lookup = (form_data.get("patient_lookup") or "").strip()

    if patient_id:
        row = conn.execute(
            "SELECT id, full_name, phone FROM patients WHERE id = ?",
            (patient_id,),
        ).fetchone()
        if row:
            return row["id"], row["full_name"], row["phone"]

    if patient_lookup:
        pid, full_name, phone = _resolve_patient(conn, patient_lookup)
    else:
        pid, full_name, phone = None, None, None

    patient_display = full_name or patient_name or "—"
    patient_phone = phone or patient_phone or None
    return pid, patient_display, patient_phone


def create_appointment(form_data: dict[str, str], *, actor_id: str | None) -> str:
    # FIX: Use timezone-aware datetime consistently
    from datetime import timezone

    day = form_data.get("day") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_time = form_data.get("start_time") or "09:00"
    duration = _slot_minutes()
    doctor_id = form_data.get("doctor_id") or doctor_choices()[0][0]
    doctor_label = next((label for slug, label in doctor_choices() if slug == doctor_id), doctor_id)
    title = (form_data.get("title") or "").strip()
    if not title:
        raise AppointmentError("title_required")
    notes = (form_data.get("notes") or "").strip()

    start_dt = _combine_datetime(day, start_time)
    end_dt = start_dt + timedelta(minutes=duration)
    grace = timedelta(minutes=_grace_minutes())
    overlap_start = _serialize(start_dt - grace)
    overlap_end = _serialize(end_dt + grace)

    conn = db()
    try:
        if not _table_exists(conn, "appointments"):
            raise AppointmentError("appointments_table_missing")
        conn.execute("BEGIN IMMEDIATE")

        pid, patient_display, patient_phone = _extract_patient_details(conn, form_data)

        _check_overlap(conn, doctor_id, overlap_start, overlap_end)
        appt_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO appointments(
                id, patient_id, patient_name, patient_phone,
                doctor_id, doctor_label, title, notes,
                starts_at, ends_at, status, room, reminder_minutes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?, 0, datetime('now'), datetime('now'))
            """,
            (
                appt_id,
                pid,
                patient_display,
                patient_phone,
                doctor_id,
                doctor_label,
                title,
                notes,
                _serialize(start_dt),
                _serialize(end_dt),
                form_data.get("room") or None,
            ),
        )
        conn.commit()
        return appt_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_appointment(appt_id: str, form_data: dict[str, str], *, actor_id: str | None) -> str:
    conn = db()
    try:
        if not _table_exists(conn, "appointments"):
            raise AppointmentError("appointments_table_missing")
        existing = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
        if not existing:
            raise AppointmentNotFound(appt_id)

        doctor_id = form_data.get("doctor_id") or existing["doctor_id"]
        doctor_label = next((label for slug, label in doctor_choices() if slug == doctor_id), doctor_id)
        title = (form_data.get("title") or "").strip() or existing["title"]
        notes = (form_data.get("notes") or "").strip()
        start_time = form_data.get("start_time") or existing["starts_at"][11:16]
        day = form_data.get("day") or existing["starts_at"][:10]

        start_dt = _combine_datetime(day, start_time)
        existing_duration = datetime.strptime(existing["ends_at"], ISO_FMT) - datetime.strptime(
            existing["starts_at"], ISO_FMT
        )
        duration_minutes = max(int(existing_duration.total_seconds() // 60), 1)
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        grace = timedelta(minutes=_grace_minutes())
        overlap_start = _serialize(start_dt - grace)
        overlap_end = _serialize(end_dt + grace)

        conn.execute("BEGIN IMMEDIATE")
        pid, patient_display, patient_phone = _extract_patient_details(conn, form_data)

        _check_overlap(conn, doctor_id, overlap_start, overlap_end, exclude_id=appt_id)
        conn.execute(
            """
            UPDATE appointments
            SET patient_id=?,
                patient_name=?,
                patient_phone=?,
                doctor_id=?,
                doctor_label=?,
                title=?,
                notes=?,
                starts_at=?,
                ends_at=?,
                updated_at=datetime('now')
            WHERE id=?
            """,
            (
                pid,
                patient_display,
                patient_phone,
                doctor_id,
                doctor_label,
                title,
                notes,
                _serialize(start_dt),
                _serialize(end_dt),
                appt_id,
            ),
        )
        conn.commit()
        return appt_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _build_search_filter(rows: list[sqlite3.Row], patient_short_ids: dict[str, str | None], search: str | None) -> list[sqlite3.Row]:
    if not search:
        return rows
    needle = search.strip().lower()
    if not needle:
        return rows
    filtered: list[sqlite3.Row] = []
    for row in rows:
        patient_name = (row["patient_name"] or "").lower()
        patient_phone = (row["patient_phone"] or "").lower()
        title = (row["title"] or "").lower()
        short_id = (patient_short_ids.get(row["patient_id"]) or "").lower()
        if any(
            needle in value
            for value in (patient_name, patient_phone, title, short_id)
        ):
            filtered.append(row)
    return filtered


def _filter_show(rows: list[sqlite3.Row], mode: str) -> list[sqlite3.Row]:
    mode = (mode or "upcoming").lower()
    if mode not in {"upcoming", "past", "all"}:
        mode = "upcoming"
    if mode == "all":
        return rows
    now_iso = datetime.now().strftime(ISO_FMT)
    if mode == "past":
        return [row for row in rows if (row["starts_at"] or "") < now_iso]
    # default upcoming
    return [row for row in rows if (row["starts_at"] or "") >= now_iso]


def list_for_day(
    day: str,
    *,
    doctor_id: str | None = None,
    end_day: str | None = None,
    search: str | None = None,
    show: str = "upcoming",
) -> list[dict[str, str]]:
    start_iso = f"{day}T00:00:00"
    end_iso = f"{end_day or day}T23:59:59" if end_day else None
    conn = db()
    try:
        if not _table_exists(conn, "appointments"):
            raise AppointmentError("appointments_table_missing")
        params: list[str] = [start_iso]
        sql = """
            SELECT *
            FROM appointments
            WHERE starts_at >= ?
        """
        if end_iso:
            sql += " AND starts_at <= ?"
            params.append(end_iso)
        if doctor_id:
            sql += " AND doctor_id = ?"
            params.append(doctor_id)
        sql += " ORDER BY starts_at ASC"
        rows = conn.execute(sql, params).fetchall()
        patient_short_ids: dict[str, str | None] = {}
        patient_ids = [row["patient_id"] for row in rows if row["patient_id"]]
        if patient_ids:
            unique_ids = list({pid for pid in patient_ids if pid})
            placeholders = ",".join(["?"] * len(unique_ids))
            short_rows = conn.execute(
                f"SELECT id, short_id FROM patients WHERE id IN ({placeholders})",
                unique_ids,
            ).fetchall()
            patient_short_ids = {r["id"]: r["short_id"] for r in short_rows}

        rows = _build_search_filter(rows, patient_short_ids, search)
        rows = _filter_show(rows, show)

        doctor_colors = get_doctor_colors()
        result = []
        for row in rows:
            start = datetime.strptime(row["starts_at"], ISO_FMT)
            end = datetime.strptime(row["ends_at"], ISO_FMT)
            duration = int((end - start).total_seconds() // 60)

            doctor_color = doctor_colors.get(row["doctor_id"])

            # Get time-based status
            time_status = get_appointment_time_status(row["starts_at"], row["ends_at"])
            labels = _slot_labels(row["starts_at"], row["ends_at"])
            
            result.append(
                {
                    "id": row["id"],
                    "patient_id": row["patient_id"],
                    "patient_name": row["patient_name"],
                    "patient_phone": row["patient_phone"],
                    "patient_short_id": patient_short_ids.get(row["patient_id"]),
                    "doctor_id": row["doctor_id"],
                    "doctor_label": row["doctor_label"],
                    "title": row["title"],
                    "notes": row["notes"],
                    "starts_at": row["starts_at"],
                    "ends_at": row["ends_at"],
                    "status": row["status"],
                    "room": row["room"],
                    "duration": duration,
                    "doctor_color": doctor_color,
                    "time_status": time_status,
                    "time_label": labels["range_label"],
                    "start_label": labels["start_label"],
                    "end_label": labels["end_label"],
                }
            )
        return result
    finally:
        conn.close()


def update_status(appt_id: str, status: str) -> None:
    allowed = {"scheduled", "checked_in", "in_progress", "done", "no_show", "cancelled"}
    if status not in allowed:
        raise AppointmentError("invalid_status")
    conn = db()
    try:
        if not _table_exists(conn, "appointments"):
            raise AppointmentError("appointments_table_missing")
        cur = conn.execute("SELECT id FROM appointments WHERE id=?", (appt_id,)).fetchone()
        if not cur:
            raise AppointmentNotFound(appt_id)
        conn.execute(
            "UPDATE appointments SET status=?, updated_at=datetime('now') WHERE id=?",
            (status, appt_id),
        )
        conn.commit()
    finally:
        conn.close()


def timeline_blocks(appointments: Sequence[dict[str, str]]) -> list[dict[str, object]]:
    """Return appointments grouped by hour for easier rendering."""

    blocks: dict[str, list[dict[str, str]]] = {}
    for appt in appointments:
        hour = appt["starts_at"][11:13]
        blocks.setdefault(hour, []).append(appt)
    for hour in blocks:
        blocks[hour].sort(key=lambda item: item["starts_at"])
    ordered = []
    for hr in range(24):
        key = f"{hr:02d}"
        ordered.append(
            {
                "hour": key,
                "entries": blocks.get(key, []),
            }
        )
    return ordered


def move_appointment_slot(appt_id: str, *, target_doctor: str, target_time: str) -> dict[str, str]:
    """Move an appointment to a new doctor/time slot."""

    conn = db()
    try:
        if not _table_exists(conn, "appointments"):
            raise AppointmentError("appointments_table_missing")
        conn.execute("BEGIN IMMEDIATE")
        appt = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
        if not appt:
            raise AppointmentNotFound(appt_id)

        doctor_labels = dict(doctor_choices())
        if target_doctor not in doctor_labels:
            raise AppointmentError("invalid_doctor")

        day = appt["starts_at"][:10]
        target_time = target_time.strip()
        new_start = _combine_datetime(day, target_time)
        new_end = new_start + timedelta(minutes=_slot_minutes())
        grace = timedelta(minutes=_grace_minutes())
        overlap_start = _serialize(new_start - grace)
        overlap_end = _serialize(new_end + grace)
        _check_overlap(conn, target_doctor, overlap_start, overlap_end, exclude_id=appt_id)

        serialized_start = _serialize(new_start)
        serialized_end = _serialize(new_end)
        conn.execute(
            """
            UPDATE appointments
            SET doctor_id=?, doctor_label=?, starts_at=?, ends_at=?, updated_at=datetime('now')
            WHERE id=?
            """,
            (
                target_doctor,
                doctor_labels[target_doctor],
                serialized_start,
                serialized_end,
                appt_id,
            ),
        )
        conn.commit()
        return {
            "doctor_id": target_doctor,
            "doctor_label": doctor_labels[target_doctor],
            "starts_at": serialized_start,
            "ends_at": serialized_end,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_appointment_by_id(appt_id: str) -> dict[str, str] | None:
    """Get a single appointment by ID."""
    conn = db()
    try:
        if not _table_exists(conn, "appointments"):
            return None
        row = conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()
        if not row:
            return None
        patient_short_id = None
        if row["patient_id"]:
            short_row = conn.execute(
                "SELECT short_id FROM patients WHERE id=?", (row["patient_id"],)
            ).fetchone()
            if short_row:
                patient_short_id = short_row["short_id"]

        doctor_colors = get_doctor_colors()
        # Get time-based status
        time_status = get_appointment_time_status(row["starts_at"], row["ends_at"])
        doctor_color = doctor_colors.get(row["doctor_id"])
        
        start = datetime.strptime(row["starts_at"], ISO_FMT)
        end = datetime.strptime(row["ends_at"], ISO_FMT)
        duration = int((end - start).total_seconds() // 60)
        
        return {
            "id": row["id"],
            "patient_name": row["patient_name"],
            "patient_phone": row["patient_phone"],
            "patient_id": row["patient_id"],
            "patient_short_id": patient_short_id,
            "doctor_id": row["doctor_id"],
            "doctor_label": row["doctor_label"],
            "title": row["title"],
            "notes": row["notes"],
            "starts_at": row["starts_at"],
            "ends_at": row["ends_at"],
            "status": row["status"],
            "room": row["room"],
            "duration": duration,
            "doctor_color": doctor_color,
            "time_status": time_status,
        }
    finally:
        conn.close()


def delete_appointment(appt_id: str) -> None:
    """Delete an appointment by ID."""
    conn = db()
    try:
        if not _table_exists(conn, "appointments"):
            raise AppointmentError("appointments_table_missing")
        
        # Check if appointment exists
        cur = conn.execute("SELECT id FROM appointments WHERE id=?", (appt_id,)).fetchone()
        if not cur:
            raise AppointmentNotFound(appt_id)
        
        # Delete the appointment
        conn.execute("DELETE FROM appointments WHERE id=?", (appt_id,))
        conn.commit()
    finally:
        conn.close()
