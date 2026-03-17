from __future__ import annotations

from pathlib import Path

from clinic_app.services.bootstrap import ensure_base_tables
from clinic_app.services.database import db as raw_db
from clinic_app.services.reception_bootstrap import ensure_reception_permissions


def _permission_codes_for_role(role_name: str) -> set[str]:
    conn = raw_db()
    try:
        rows = conn.execute(
            """
            SELECT p.code
            FROM role_permissions rp
            JOIN roles r ON r.id = rp.role_id
            JOIN permissions p ON p.id = rp.permission_id
            WHERE r.name = ?
            """,
            (role_name,),
        ).fetchall()
        return {row["code"] for row in rows}
    finally:
        conn.close()


def test_reception_tables_and_permissions_are_bootstrapped(app):
    conn = raw_db()
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "reception_entries" in tables
        assert "reception_entry_events" in tables

        perm_rows = conn.execute(
            """
            SELECT code FROM permissions
            WHERE code IN ('reception_entries:create', 'reception_entries:review', 'reception_entries:approve')
            ORDER BY code
            """
        ).fetchall()
        assert [row["code"] for row in perm_rows] == [
            "reception_entries:approve",
            "reception_entries:create",
            "reception_entries:review",
        ]
    finally:
        conn.close()


def test_default_roles_receive_reception_permissions(logged_in_client):
    resp = logged_in_client.get("/admin/settings")
    assert resp.status_code == 200

    admin_codes = _permission_codes_for_role("Admin")
    manager_codes = _permission_codes_for_role("Manager")
    reception_codes = _permission_codes_for_role("Reception")
    view_only_codes = _permission_codes_for_role("Receptionist (View Only)")

    expected_all = {
        "reception_entries:create",
        "reception_entries:review",
        "reception_entries:approve",
    }

    assert expected_all.issubset(admin_codes)
    assert expected_all.issubset(manager_codes)
    assert "reception_entries:create" in reception_codes
    assert "reception_entries:review" not in reception_codes
    assert "reception_entries:approve" not in reception_codes
    assert "reception_entries:create" not in view_only_codes
    assert "reception_entries:review" not in view_only_codes
    assert "reception_entries:approve" not in view_only_codes


def test_reception_bootstrap_is_idempotent(app):
    db_path = Path(app.config["PALMER_PLUS_DB"])
    ensure_base_tables(db_path)
    ensure_reception_permissions()
    ensure_reception_permissions()

    conn = raw_db()
    try:
        perm_count = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM permissions
            WHERE code IN ('reception_entries:create', 'reception_entries:review', 'reception_entries:approve')
            """
        ).fetchone()
        assert perm_count["c"] == 3

        role_link_count = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM role_permissions rp
            JOIN roles r ON r.id = rp.role_id
            JOIN permissions p ON p.id = rp.permission_id
            WHERE r.name = 'Reception'
              AND p.code = 'reception_entries:create'
            """
        ).fetchone()
        assert role_link_count["c"] == 1
    finally:
        conn.close()
