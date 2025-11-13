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


def _cleanup_invalid_appointments(conn: sqlite3.Connection) -> None:
    """Remove or fix appointments with invalid datetime data."""
    try:
        # Find appointments with NULL or invalid datetime strings
        invalid_rows = conn.execute("""
            SELECT id, starts_at, ends_at
            FROM appointments
            WHERE starts_at IS NULL
               OR ends_at IS NULL
               OR length(starts_at) < 19
               OR length(ends_at) < 19
               OR starts_at NOT LIKE '____-__-__T__:__:__'
               OR ends_at NOT LIKE '____-__-__T__:__:__'
        """).fetchall()

        if invalid_rows:
            current_app.logger.warning(f"Found {len(invalid_rows)} invalid appointment records, removing them")
            for row in invalid_rows:
                try:
                    conn.execute("DELETE FROM appointments WHERE id = ?", (row["id"],))
                    current_app.logger.info(f"Removed invalid appointment {row['id']}")
                except Exception as e:
                    current_app.logger.error(f"Failed to remove invalid appointment {row['id']}: {e}")

            conn.commit()
    except Exception as e:
        current_app.logger.error(f"Error during appointment cleanup: {e}")
        # Don't let cleanup errors break the main functionality


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

        # First, clean up any invalid records
        _cleanup_invalid_appointments(conn)

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
            try:
                # Validate datetime strings
                starts_at = row["starts_at"]
                ends_at = row["ends_at"]

                if not starts_at or not ends_at:
                    # Skip invalid records
                    continue

                start = datetime.strptime(starts_at, ISO_FMT)
                end = datetime.strptime(ends_at, ISO_FMT)
                duration = int((end - start).total_seconds() // 60)

                doctor_color = doctor_colors.get(row["doctor_id"])

                # Get time-based status
                time_status = get_appointment_time_status(starts_at, ends_at)
                labels = _slot_labels(starts_at, ends_at)

                result.append(
                    {
                        "id": row["id"],
                        "patient_id": row["patient_id"],
                        "patient_name": row["patient_name"] or "—",
                        "patient_phone": row["patient_phone"],
                        "patient_short_id": patient_short_ids.get(row["patient_id"]),
                        "doctor_id": row["doctor_id"],
                        "doctor_label": row["doctor_label"] or row["doctor_id"],
                        "title": row["title"] or "Untitled Appointment",
                        "notes": row["notes"],
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                        "status": row["status"] or "scheduled",
                        "room": row["room"],
                        "duration": duration,
                        "doctor_color": doctor_color,
                        "time_status": time_status,
                        "time_label": labels["range_label"],
                        "start_label": labels["start_label"],
                        "end_label": labels["end_label"],
                    }
                )
            except (ValueError, TypeError, KeyError) as e:
                # Log and skip invalid records instead of crashing
                current_app.logger.warning(f"Skipping invalid appointment record {row.get('id', 'unknown')}: {e}")
                continue
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


# Enhanced functions for multi-doctor view and advanced features

def get_multi_doctor_schedule(
    day: str,
    end_day: str | None = None,
    search: str | None = None,
    show: str = "all",
) -> dict[str, dict]:
    """Get schedule data for all doctors in a format suitable for multi-doctor view."""
    doctors = doctor_choices()
    all_appointments = {}
    mode = (show or "all").lower()
    if mode not in {"upcoming", "past", "all"}:
        mode = "upcoming"

    for doctor_id, doctor_label in doctors:
        appointments = list_for_day(
            day=day,
            end_day=end_day,
            doctor_id=doctor_id,
            search=search,
            show=mode,
        )

        # Group appointments by date for better organization
        appointments_by_date = {}
        for appt in appointments:
            appt_date = appt["starts_at"][:10]
            if appt_date not in appointments_by_date:
                appointments_by_date[appt_date] = []
            appointments_by_date[appt_date].append(appt)

        all_appointments[doctor_id] = {
            "label": doctor_label,
            "appointments": appointments,
            "appointments_by_date": appointments_by_date,
            "total_count": len(appointments),
        }

    return all_appointments


def get_date_cards_for_range(start_date: str, end_date: str | None = None, doctor_filter: str | None = None) -> list[dict]:
    """Generate compact date cards with appointment statistics for navigation."""
    if not end_date:
        # Default to 7 days from start
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = start_dt + timedelta(days=6)
        end_date = end_dt.strftime("%Y-%m-%d")

    cards = []
    current_dt = datetime.strptime(start_date, "%Y-%m-%d")

    while current_dt.strftime("%Y-%m-%d") <= end_date:
        day_str = current_dt.strftime("%Y-%m-%d")
        day_name = current_dt.strftime("%a")

        # Get appointments for this day
        appointments = list_for_day(
            day=day_str,
            doctor_id=doctor_filter if doctor_filter != "all" else None,
            show="all"
        )

        # Calculate statistics
        total = len(appointments)
        done = len([a for a in appointments if a["status"] == "done"])

        cards.append({
            "date": day_str,
            "day_of_week": day_name,
            "stats": {
                "total": total,
                "done": done,
            }
        })

        current_dt += timedelta(days=1)

    return cards


def auto_generate_time_slot(start_time: str, duration_minutes: int | None = None) -> str:
    """Auto-generate end time based on start time and default duration."""
    if not duration_minutes:
        duration_minutes = _slot_minutes()

    # Parse start time (HH:MM format)
    start_hour, start_minute = map(int, start_time.split(":"))

    # Calculate end time
    total_minutes = start_hour * 60 + start_minute + duration_minutes
    end_hour = total_minutes // 60
    end_minute = total_minutes % 60

    # Format as HH:MM
    return f"{end_hour:02d}:{end_minute:02d}"


def validate_time_slot_overlap(doctor_id: str, start_time: str, end_time: str, day: str, exclude_appointment_id: str | None = None) -> bool:
    """Check if a proposed time slot overlaps with existing appointments for the same doctor."""
    conn = db()
    try:
        start_iso = f"{day}T{start_time}:00"
        end_iso = f"{day}T{end_time}:00"

        grace_minutes = _grace_minutes()
        grace_start = (datetime.strptime(start_iso, ISO_FMT) - timedelta(minutes=grace_minutes)).strftime(ISO_FMT)
        grace_end = (datetime.strptime(end_iso, ISO_FMT) + timedelta(minutes=grace_minutes)).strftime(ISO_FMT)

        params = [doctor_id, grace_end, grace_start]
        sql = """
            SELECT id FROM appointments
            WHERE doctor_id = ?
              AND starts_at < ?
              AND ends_at > ?
        """

        if exclude_appointment_id:
            sql += " AND id != ?"
            params.append(exclude_appointment_id)

        conflict = conn.execute(sql, params).fetchone()
        return conflict is not None
    finally:
        conn.close()


def get_consecutive_slots(doctor_id: str, day: str, start_time: str, count: int = 3) -> list[dict]:
    """Get available consecutive time slots for a doctor."""
    slots = []
    current_time = start_time

    for i in range(count):
        end_time = auto_generate_time_slot(current_time)

        # Check if this slot is available
        has_conflict = validate_time_slot_overlap(doctor_id, current_time, end_time, day)

        slots.append({
            "start_time": current_time,
            "end_time": end_time,
            "available": not has_conflict,
            "slot_number": i + 1,
        })

        # Move to next slot
        current_time = end_time

    return slots
