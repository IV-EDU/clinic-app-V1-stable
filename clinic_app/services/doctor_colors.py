"""Doctor color configuration service."""

from __future__ import annotations

import sqlite3
from typing import Dict, Optional
from datetime import datetime, timezone
import secrets

from clinic_app.services.database import db

DEFAULT_COLORS: Dict[str, str] = {}
DEFAULT_COLOR = "#6B7280"
ANY_DOCTOR_ID = "any-doctor"
ANY_DOCTOR_LABEL = "Any Doctor"


def _ensure_table(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS doctor_colors (
            doctor_id TEXT PRIMARY KEY,
            color TEXT NOT NULL,
            doctor_label TEXT,
            is_active INTEGER DEFAULT 1,
            deleted_at TEXT,
            is_purged INTEGER DEFAULT 0
        )
        """
    )
    # Ensure optional columns exist
    cols = {row["name"] for row in cursor.execute("PRAGMA table_info(doctor_colors)").fetchall()}
    if "doctor_label" not in cols:
        try:
            cursor.execute("ALTER TABLE doctor_colors ADD COLUMN doctor_label TEXT")
        except sqlite3.OperationalError:
            pass
    if "is_active" not in cols:
        try:
            cursor.execute("ALTER TABLE doctor_colors ADD COLUMN is_active INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            pass
    if "deleted_at" not in cols:
        try:
            cursor.execute("ALTER TABLE doctor_colors ADD COLUMN deleted_at TEXT")
        except sqlite3.OperationalError:
            pass
    if "is_purged" not in cols:
        try:
            cursor.execute("ALTER TABLE doctor_colors ADD COLUMN is_purged INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    _ensure_any_doctor(conn)


def _ensure_any_doctor(conn: sqlite3.Connection) -> None:
    """Ensure the non-deletable Any Doctor entry exists."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT OR IGNORE INTO doctor_colors (doctor_id, color, doctor_label, is_active, deleted_at, is_purged)
            VALUES (?, ?, ?, 1, NULL, 0)
            """,
            (ANY_DOCTOR_ID, DEFAULT_COLOR, ANY_DOCTOR_LABEL),
        )
    except sqlite3.OperationalError:
        # Minimal insert if columns missing
        cursor.execute(
            "INSERT OR IGNORE INTO doctor_colors (doctor_id, color, is_active) VALUES (?, ?, 1)",
            (ANY_DOCTOR_ID, DEFAULT_COLOR),
        )
    conn.commit()


def _load_colors(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    cursor = conn.cursor()
    try:
        rows = cursor.execute(
            "SELECT doctor_id, color, doctor_label, is_active, deleted_at, is_purged FROM doctor_colors"
        ).fetchall()
    except sqlite3.OperationalError:
        try:
            rows = cursor.execute("SELECT doctor_id, color, doctor_label, is_active FROM doctor_colors").fetchall()
            return {
                row["doctor_id"]: {
                    "color": row["color"],
                    "label": row["doctor_label"],
                    "is_active": row["is_active"] if row["is_active"] is not None else 1,
                    "deleted_at": None,
                    "is_purged": 0,
                }
                for row in rows
            }
        except sqlite3.OperationalError:
            rows = cursor.execute("SELECT doctor_id, color FROM doctor_colors").fetchall()
            return {
                row["doctor_id"]: {
                    "color": row["color"],
                    "label": None,
                    "is_active": 1,
                    "deleted_at": None,
                    "is_purged": 0,
                }
                for row in rows
            }
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        result[row["doctor_id"]] = {
            "color": row["color"],
            "label": row["doctor_label"],
            "is_active": row["is_active"] if row["is_active"] is not None else 1,
            "deleted_at": row["deleted_at"],
            "is_purged": row.get("is_purged", 0) if isinstance(row, dict) else row["is_purged"],
        }
    if ANY_DOCTOR_ID not in result:
        _ensure_any_doctor(conn)
        return _load_colors(conn)
    return result


def _slugify(value: str) -> str:
    keep = []
    for ch in value:
        if ch.isalnum():
            keep.append(ch.lower())
        elif ch in {" ", "-", "_"}:
            keep.append("-")
    slug = "".join(keep).strip("-")
    return slug or "doctor"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_doctor_colors() -> dict[str, str]:
    """Get configured colors for active doctors."""
    conn = db()
    try:
        try:
            _ensure_table(conn)
            colors = _load_colors(conn)
        except Exception:
            return {}
        result: dict[str, str] = {}
        for k, v in colors.items():
            if v.get("is_active", 1) and not v.get("is_purged", 0):
                result[k] = v.get("color") or DEFAULT_COLOR
        return result
    finally:
        conn.close()


def set_doctor_color(doctor_id: str, color: str, label: str | None = None) -> None:
    """Set or update a doctor's color (and optional label), mark active."""
    if doctor_id == ANY_DOCTOR_ID:
        label = ANY_DOCTOR_LABEL
    conn = db()
    try:
        _ensure_table(conn)
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT OR REPLACE INTO doctor_colors (doctor_id, color, doctor_label, is_active, deleted_at, is_purged)
                VALUES (?, ?, ?, 1, NULL, 0)
                """,
                (doctor_id, color, label or doctor_id),
            )
        except sqlite3.OperationalError as exc:
            if "doctor_label" in str(exc).lower():
                # Fallback to storing without label if column is absent
                cursor.execute(
                    "INSERT OR REPLACE INTO doctor_colors (doctor_id, color, is_active, deleted_at) VALUES (?, ?, 1, NULL)",
                    (doctor_id, color),
                )
            else:
                raise
        conn.commit()

        # Propagate to appointments table
        try:
            appt_conn = db()
            appt_cur = appt_conn.cursor()
            appt_cur.execute(
                "UPDATE appointments SET doctor_label=?, color=? WHERE doctor_id=?",
                (label or doctor_id, color, doctor_id),
            )
            appt_conn.commit()
        except Exception:
            pass
        finally:
            try:
                appt_conn.close()
            except Exception:
                pass
    finally:
        conn.close()


def delete_doctor_color(doctor_id: str) -> None:
    """Deactivate a doctor's color entry and record deletion time."""
    if doctor_id == ANY_DOCTOR_ID:
        return
    conn = db()
    try:
        _ensure_table(conn)
        cursor = conn.cursor()
        now = _now_iso()
        updated = cursor.execute(
            "UPDATE doctor_colors SET is_active = 0, deleted_at = ?, is_purged = 0 WHERE doctor_id = ?",
            (now, doctor_id),
        ).rowcount
        if updated == 0:
            color = DEFAULT_COLOR
            try:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO doctor_colors (doctor_id, color, doctor_label, is_active, deleted_at, is_purged)
                    VALUES (?, ?, ?, 0, ?, 0)
                    """,
                    (doctor_id, color, doctor_id, now),
                )
            except sqlite3.OperationalError:
                cursor.execute(
                    "INSERT OR REPLACE INTO doctor_colors (doctor_id, color, is_active, deleted_at) VALUES (?, ?, 0, ?)",
                    (doctor_id, color, now),
                )
        conn.commit()
    finally:
        conn.close()


def restore_doctor_color(doctor_id: str) -> None:
    """Restore a previously deleted doctor entry."""
    if doctor_id == ANY_DOCTOR_ID:
        return
    conn = db()
    try:
        _ensure_table(conn)
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE doctor_colors
            SET is_active = 1, deleted_at = NULL, is_purged = 0
            WHERE doctor_id = ?
            """,
            (doctor_id,),
        )
        conn.commit()
    finally:
        conn.close()


def purge_doctor_color(doctor_id: str) -> None:
    """Permanently remove a doctor from history."""
    if doctor_id == ANY_DOCTOR_ID:
        return
    conn = db()
    try:
        _ensure_table(conn)
        cursor = conn.cursor()
        # When purging, reassign any remaining appointments/payments to Any Doctor
        try:
            appt_conn = db()
            appt_cur = appt_conn.cursor()
            any_color = DEFAULT_COLOR
            any_row = None
            try:
                any_row = appt_cur.execute(
                    "SELECT color, doctor_label FROM doctor_colors WHERE doctor_id = ?", (ANY_DOCTOR_ID,)
                ).fetchone()
                if any_row and any_row[0]:
                    any_color = any_row[0]
            except Exception:
                pass
            appt_cur.execute(
                "UPDATE appointments SET doctor_id=?, doctor_label=?, color=? WHERE doctor_id=?",
                (ANY_DOCTOR_ID, ANY_DOCTOR_LABEL, any_color, doctor_id),
            )
            appt_cur.execute(
                "UPDATE payments SET doctor_id=?, doctor_label=? WHERE doctor_id=?",
                (ANY_DOCTOR_ID, ANY_DOCTOR_LABEL, doctor_id),
            )
            appt_conn.commit()
        except Exception:
            pass
        finally:
            try:
                appt_conn.close()
            except Exception:
                pass

        cursor.execute("DELETE FROM doctor_colors WHERE doctor_id = ?", (doctor_id,))
        conn.commit()
    finally:
        conn.close()


def get_deleted_doctors() -> list[dict[str, object]]:
    """Return doctors that are deleted but not purged."""
    conn = db()
    try:
        _ensure_table(conn)
        colors = _load_colors(conn)
        deleted = []
        for doc_id, info in colors.items():
            if info.get("is_purged", 0):
                continue
            if info.get("is_active", 1):
                continue
            deleted.append(
                {
                    "doctor_id": doc_id,
                    "doctor_label": info.get("label") or doc_id,
                    "color": info.get("color") or DEFAULT_COLOR,
                    "deleted_at": info.get("deleted_at"),
                }
            )
        return deleted
    finally:
        conn.close()


def get_doctor_entry(doctor_id: str) -> Optional[dict[str, object]]:
    """Return a single doctor entry if present."""
    conn = db()
    try:
        _ensure_table(conn)
        colors = _load_colors(conn)
        return colors.get(doctor_id)
    finally:
        conn.close()


def ensure_unique_doctor_id(base_label: str) -> str:
    """Generate a unique doctor id based on a label (kept for backward compat)."""
    conn = db()
    try:
        _ensure_table(conn)
        colors = _load_colors(conn)
        existing_ids = set(colors.keys()) | set(DEFAULT_COLORS.keys())
    finally:
        conn.close()

    base = _slugify(base_label) if base_label else "doctor"
    if base not in existing_ids:
        return base
    suffix = 2
    while True:
        candidate = f"{base}-{suffix}"
        if candidate not in existing_ids:
            return candidate
        suffix += 1


def ensure_unique_numeric_id() -> str:
    """Generate a random numeric id that is unique across doctors."""
    conn = db()
    try:
        _ensure_table(conn)
        colors = _load_colors(conn)
        existing_ids = set(colors.keys()) | set(DEFAULT_COLORS.keys())
    finally:
        conn.close()
    try:
        from clinic_app.services.appointments import doctor_choices
        for doc_id, _label, _active in doctor_choices(include_inactive=True, include_status=True):
            existing_ids.add(doc_id)
    except Exception:
        pass

    for _ in range(200):
        candidate = str(secrets.randbelow(900000) + 100000)  # 6-digit
        if candidate not in existing_ids:
            return candidate
    # fallback to timestamp-based
    return str(int(datetime.now(timezone.utc).timestamp() * 1000))


def name_exists(name: str, *, exclude_id: Optional[str] = None) -> bool:
    """Return True if an active doctor name already exists (case-insensitive)."""
    target = (name or "").strip().lower()
    if not target:
        return False
    conn = db()
    try:
        _ensure_table(conn)
        colors = _load_colors(conn)
        for doc_id, info in colors.items():
            if exclude_id and doc_id == exclude_id:
                continue
            if info.get("is_purged", 0):
                continue
            if info.get("is_active", 1) == 0:
                continue
            label = (info.get("label") or doc_id or "").strip().lower()
            if label == target:
                return True
    finally:
        conn.close()

    return False


def name_exists_any(name: str, *, exclude_id: Optional[str] = None) -> bool:
    """Return True if a doctor name exists (active or deleted), excluding purged."""
    target = (name or "").strip().lower()
    if not target:
        return False
    conn = db()
    try:
        _ensure_table(conn)
        colors = _load_colors(conn)
        for doc_id, info in colors.items():
            if info.get("is_purged", 0):
                continue
            if exclude_id and doc_id == exclude_id:
                continue
            label = (info.get("label") or doc_id or "").strip().lower()
            if label == target:
                return True
    finally:
        conn.close()
    return False


def is_doctor_blocked(doctor_id: str) -> bool:
    """Return True if doctor is inactive or purged."""
    info = get_doctor_entry(doctor_id)
    if not info:
        return False
    return (info.get("is_active", 1) == 0) or bool(info.get("is_purged", 0))


def find_active_doctor_ids_by_name(name: str) -> list[str]:
    """Return doctor_ids that are currently active and match the given name."""
    target = (name or "").strip().lower()
    if not target:
        return []
    matches: list[str] = []
    conn = db()
    try:
        _ensure_table(conn)
        colors = _load_colors(conn)
        for doc_id, info in colors.items():
            if info.get("is_purged", 0):
                continue
            if info.get("is_active", 1) == 0:
                continue
            label = (info.get("label") or doc_id or "").strip().lower()
            if label == target:
                matches.append(doc_id)
    finally:
        conn.close()
    return matches


def generate_unique_color(existing: Optional[list[str]] = None) -> str:
    """Generate a unique-ish hex color not already in use."""
    existing_set = set((existing or []))
    palette = [
        "#2563EB", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6",
        "#14B8A6", "#0EA5E9", "#EC4899", "#84CC16", "#F97316",
        "#6B7280", "#3B82F6",
    ]
    for color in palette:
        if color.upper() not in existing_set and color.lower() not in existing_set:
            return color
    for _ in range(100):
        color = "#{:06X}".format(int(secrets.randbelow(0xFFFFFF)))
        if color not in existing_set and color.lower() not in existing_set:
            return color
    return DEFAULT_COLOR


def get_all_doctors_with_colors() -> list[dict[str, str]]:
    """Get all active doctors with their current colors."""
    conn = db()
    try:
        _ensure_table(conn)
        colors = _load_colors(conn)
        result: list[dict[str, str]] = []
        for doc_id, info in colors.items():
            if info.get("is_purged", 0):
                continue
            if info.get("is_active", 1) == 0:
                continue
            result.append(
                {
                    "doctor_id": doc_id,
                    "doctor_label": info.get("label") or doc_id,
                    "color": info.get("color") or DEFAULT_COLOR,
                    "is_active": info.get("is_active", 1),
                }
            )
        return result
    finally:
        conn.close()


def get_active_doctor_options(include_any: bool = True) -> list[dict[str, str]]:
    """
    Return a sorted list of active doctor entries (id, label, color).
    When include_any=True, ensure the “Any Doctor” entry exists and is first.
    """
    doctors = get_all_doctors_with_colors()
    doctors.sort(
        key=lambda doc: (
            0 if doc.get("doctor_id") == ANY_DOCTOR_ID else 1,
            (doc.get("doctor_label") or doc.get("doctor_id") or "").lower(),
        )
    )
    if include_any:
        has_any = any(doc.get("doctor_id") == ANY_DOCTOR_ID for doc in doctors)
        if not has_any:
            doctors.insert(
                0,
                {
                    "doctor_id": ANY_DOCTOR_ID,
                    "doctor_label": ANY_DOCTOR_LABEL,
                    "color": DEFAULT_COLOR,
                    "is_active": 1,
                },
            )
    else:
        doctors = [doc for doc in doctors if doc.get("doctor_id") != ANY_DOCTOR_ID]
    return doctors


def init_doctor_colors_table() -> None:
    """Initialize the doctor_colors table."""
    conn = db()
    try:
        _ensure_table(conn)
    finally:
        conn.close()
