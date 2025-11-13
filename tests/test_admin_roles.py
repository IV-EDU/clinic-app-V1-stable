from __future__ import annotations

from clinic_app.services.database import db as raw_db


def _get_permission_id(code: str) -> int:
    conn = raw_db()
    try:
        row = conn.execute("SELECT id FROM permissions WHERE code=?", (code,)).fetchone()
        assert row is not None, f"Permission {code} missing"
        return row["id"]
    finally:
        conn.close()


def _get_role(row_name: str):
    conn = raw_db()
    try:
        row = conn.execute("SELECT id, description FROM roles WHERE name=?", (row_name,)).fetchone()
        assert row is not None, f"Role {row_name} missing"
        return row["id"], row["description"]
    finally:
        conn.close()


def test_create_role_assigns_permissions(logged_in_client, get_csrf_token):
    create_page = logged_in_client.get("/admin/roles/new")
    assert create_page.status_code == 200
    token = get_csrf_token(create_page)
    perm_id = _get_permission_id("patients:view")
    resp = logged_in_client.post(
        "/admin/roles/new",
        data={
            "csrf_token": token,
            "name": "Auditor",
            "description": "Read-only access",
            "permissions": [str(perm_id)],
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    conn = raw_db()
    try:
        role_row = conn.execute("SELECT id FROM roles WHERE name='Auditor'").fetchone()
        assert role_row is not None
        role_id = role_row["id"]
        link = conn.execute(
            "SELECT COUNT(*) AS c FROM role_permissions WHERE role_id=? AND permission_id=?",
            (role_id, perm_id),
        ).fetchone()
        assert link["c"] == 1
    finally:
        conn.close()


def test_edit_role_updates_permissions(logged_in_client, get_csrf_token):
    role_id, description = _get_role("Reception")
    description = description or ""
    edit_page = logged_in_client.get(f"/admin/roles/{role_id}/edit")
    assert edit_page.status_code == 200
    token = get_csrf_token(edit_page)
    view_id = _get_permission_id("patients:view")
    payments_edit_id = _get_permission_id("payments:edit")
    resp = logged_in_client.post(
        f"/admin/roles/{role_id}/edit",
        data={
            "csrf_token": token,
            "name": "Reception",
            "description": description,
            "permissions": [str(view_id)],
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    conn = raw_db()
    try:
        link = conn.execute(
            "SELECT COUNT(*) AS c FROM role_permissions WHERE role_id=? AND permission_id=?",
            (role_id, view_id),
        ).fetchone()
        assert link["c"] == 1
        missing = conn.execute(
            "SELECT COUNT(*) AS c FROM role_permissions WHERE role_id=? AND permission_id=?",
            (role_id, payments_edit_id),
        ).fetchone()
        assert missing["c"] == 0
    finally:
        conn.close()
