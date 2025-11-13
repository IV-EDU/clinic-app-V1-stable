"""Doctor color configuration service."""

from __future__ import annotations

import sqlite3
from typing import Dict

from clinic_app.services.database import db

DEFAULT_COLORS: Dict[str, str] = {
    "dr-omar": "#3B82F6",  # Blue
    "dr-lina": "#10B981",  # Green
    "on-call": "#F59E0B",  # Amber
    "default": "#6B7280",  # Gray
}


def _ensure_table(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS doctor_colors (
            doctor_id TEXT PRIMARY KEY,
            color TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _load_colors(conn: sqlite3.Connection) -> dict[str, str]:
    cursor = conn.cursor()
    rows = cursor.execute("SELECT doctor_id, color FROM doctor_colors").fetchall()
    return {row["doctor_id"]: row["color"] for row in rows}


def get_doctor_colors() -> dict[str, str]:
    """Get configured colors merged with defaults."""
    conn = db()
    try:
        try:
            _ensure_table(conn)
            colors = _load_colors(conn)
        except Exception:
            # Fall back entirely to defaults if the table is unavailable.
            return dict(DEFAULT_COLORS)
        merged = dict(DEFAULT_COLORS)
        merged.update(colors)
        return merged
    finally:
        conn.close()


def set_doctor_color(doctor_id: str, color: str) -> None:
    """Set or update a doctor's color."""
    conn = db()
    try:
        _ensure_table(conn)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO doctor_colors (doctor_id, color) VALUES (?, ?)",
            (doctor_id, color),
        )
        conn.commit()
    finally:
        conn.close()


def delete_doctor_color(doctor_id: str) -> None:
    """Delete a doctor's color (will fall back to default)."""
    conn = db()
    try:
        _ensure_table(conn)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM doctor_colors WHERE doctor_id = ?", (doctor_id,))
        conn.commit()
    finally:
        conn.close()


def get_all_doctors_with_colors() -> list[dict[str, str]]:
    """Get all doctors with their current colors."""
    conn = db()
    try:
        _ensure_table(conn)
        from clinic_app.services.appointments import doctor_choices

        doctors = doctor_choices()
        colors = _load_colors(conn)
        merged = dict(DEFAULT_COLORS)
        merged.update(colors)

        result: list[dict[str, str]] = []
        for doctor_id, doctor_label in doctors:
            color = merged.get(doctor_id, merged["default"])
            result.append({"doctor_id": doctor_id, "doctor_label": doctor_label, "color": color})
        return result
    finally:
        conn.close()


def init_doctor_colors_table() -> None:
    """Initialize the doctor_colors table."""
    conn = db()
    try:
        _ensure_table(conn)
    finally:
        conn.close()
