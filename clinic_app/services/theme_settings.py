"""Simple theme settings storage backed by SQLite (no ORM)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from clinic_app.services.database import db


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_setting(key: str) -> Optional[str]:
    """Fetch a single setting value by key."""
    conn = db()
    try:
        row = conn.execute(
            "SELECT setting_value FROM theme_settings WHERE setting_key = ?",
            (key,),
        ).fetchone()
        return row["setting_value"] if row else None
    except Exception:
        return None
    finally:
        conn.close()


def set_setting(key: str, value: str, category: Optional[str] = None) -> bool:
    """
    Upsert a setting. Uses SQLite's ON CONFLICT for simplicity.
    Returns True on success, False on error.
    """
    conn = db()
    try:
        conn.execute(
            """
            INSERT INTO theme_settings (setting_key, setting_value, category, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(setting_key)
            DO UPDATE SET
                setting_value = excluded.setting_value,
                category = COALESCE(excluded.category, theme_settings.category),
                updated_at = excluded.updated_at
            """,
            (key, value, category, _utc_now()),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


def get_theme_variables() -> Dict[str, str]:
    """Return all active theme variables as a dict of key -> value."""
    conn = db()
    try:
        rows = conn.execute(
            "SELECT setting_key, setting_value FROM theme_settings ORDER BY setting_key"
        ).fetchall()
        return {row["setting_key"]: row["setting_value"] for row in rows}
    except Exception:
        return {}
    finally:
        conn.close()


# Convenience helpers for known theme keys
def get_theme_logo_path() -> Optional[str]:
    return get_setting("logo_path")


def get_clinic_name_settings() -> Dict[str, str]:
    vars = get_theme_variables()
    return {
        "clinic_name": vars.get("clinic_name", "").strip(),
        "clinic_name_enabled": vars.get("clinic_name_enabled", "false").lower() in {"1", "true", "yes", "on"},
        "clinic_brand_color": vars.get("clinic_brand_color", "").strip(),
    }
