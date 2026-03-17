"""Bootstrap helpers for Reception workflow permissions."""

from __future__ import annotations

from clinic_app.services.database import db as raw_db


RECEPTION_PERMISSION_SPECS = [
    ("reception_entries:create", "Create reception draft entries"),
    ("reception_entries:review", "Review reception draft entries"),
    ("reception_entries:approve", "Approve reception draft entries"),
]

DEFAULT_ROLE_RECEPTION_PERMISSIONS = {
    "Admin": {
        "reception_entries:create",
        "reception_entries:review",
        "reception_entries:approve",
    },
    "Manager": {
        "reception_entries:create",
        "reception_entries:review",
        "reception_entries:approve",
    },
    "Reception": {"reception_entries:create"},
    "Receptionist (View Only)": set(),
}


def ensure_reception_permissions() -> None:
    """Seed Reception permission rows and default-role links when RBAC tables exist."""

    conn = raw_db()
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required = {"roles", "permissions", "role_permissions"}
        if not required.issubset(tables):
            return

        for code, description in RECEPTION_PERMISSION_SPECS:
            conn.execute(
                "INSERT OR IGNORE INTO permissions(code, description) VALUES (?, ?)",
                (code, description),
            )

        role_ids = {
            row["name"]: row["id"]
            for row in conn.execute(
                "SELECT id, name FROM roles WHERE name IN (?, ?, ?, ?)",
                tuple(DEFAULT_ROLE_RECEPTION_PERMISSIONS.keys()),
            ).fetchall()
        }
        perm_ids = {
            row["code"]: row["id"]
            for row in conn.execute(
                "SELECT id, code FROM permissions WHERE code IN (?, ?, ?)",
                tuple(code for code, _ in RECEPTION_PERMISSION_SPECS),
            ).fetchall()
        }

        for role_name, permission_codes in DEFAULT_ROLE_RECEPTION_PERMISSIONS.items():
            role_id = role_ids.get(role_name)
            if not role_id:
                continue
            for code in permission_codes:
                perm_id = perm_ids.get(code)
                if not perm_id:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO role_permissions(role_id, permission_id) VALUES (?, ?)",
                    (role_id, perm_id),
                )

        conn.commit()
    finally:
        conn.close()
