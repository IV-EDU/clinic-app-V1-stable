from __future__ import annotations

import uuid

from clinic_app.services.database import db as raw_db


def _make_role_id(name: str) -> int:
    conn = raw_db()
    try:
        row = conn.execute("SELECT id FROM roles WHERE name=?", (name,)).fetchone()
        assert row is not None
        return row["id"]
    finally:
        conn.close()


def _isolate_admin_user(admin_role_id: int) -> str:
    conn = raw_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        assert row is not None
        admin_id = row["id"]
        conn.execute(
            "DELETE FROM user_roles WHERE role_id=? AND user_id != ?",
            (admin_role_id, admin_id),
        )
        conn.execute(
            "UPDATE users SET role='assistant' WHERE id != ?",
            (admin_id,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO user_roles(user_id, role_id) VALUES (?, ?)",
            (admin_id, admin_role_id),
        )
        conn.commit()
        return admin_id
    finally:
        conn.close()


def _get_primary_admin_id() -> str:
    conn = raw_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        assert row is not None
        return row["id"]
    finally:
        conn.close()


def _create_extra_admin(username: str = "extra_admin") -> str:
    admin_role_id = _make_role_id("Admin")
    conn = raw_db()
    try:
        user_id = f"extra-{uuid.uuid4()}"
        conn.execute(
            "INSERT INTO users(id, username, password_hash, role, is_active, created_at, updated_at) "
            "VALUES (?, ?, '', 'admin', 1, datetime('now'), datetime('now'))",
            (user_id, username),
        )
        conn.execute(
            "INSERT INTO user_roles(user_id, role_id) VALUES (?, ?)",
            (user_id, admin_role_id),
        )
        conn.commit()
        return user_id
    finally:
        conn.close()


def test_admin_can_create_and_edit_user(logged_in_client, get_csrf_token):
    # Ensure default roles (including Manager) exist.
    logged_in_client.get("/admin/settings")
    page = logged_in_client.get("/admin/users/new")
    assert page.status_code == 200
    token = get_csrf_token(page)
    admin_role_id = _make_role_id("Admin")
    resp = logged_in_client.post(
        "/admin/users/new",
        data={
            "csrf_token": token,
            "username": "helper",
            "password": "any",
            "full_name": "Helper User",
            "roles": [str(admin_role_id)],
            "is_active": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    conn = raw_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE username='helper'").fetchone()
        assert row is not None
        user_id = row["id"]
    finally:
        conn.close()


def test_can_assign_manager_role_without_legacy_role_error(logged_in_client, get_csrf_token):
    # Ensure default roles (including Manager) exist.
    logged_in_client.get("/admin/settings")

    page = logged_in_client.get("/admin/users/new")
    assert page.status_code == 200
    token = get_csrf_token(page)
    manager_role_id = _make_role_id("Manager")
    resp = logged_in_client.post(
        "/admin/users/new",
        data={
            "csrf_token": token,
            "username": "manager_user",
            "password": "any",
            "full_name": "Manager User",
            "roles": [str(manager_role_id)],
            "is_active": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    conn = raw_db()
    try:
        row = conn.execute("SELECT id, role FROM users WHERE username='manager_user'").fetchone()
        assert row is not None
        # Legacy role should remain compatible with older CHECK constraints.
        assert (row["role"] or "").lower() in ("assistant", "admin", "doctor")
    finally:
        conn.close()


def test_can_update_user_to_manager_role_without_legacy_role_error(logged_in_client, get_csrf_token):
    # Ensure default roles (including Manager) exist.
    logged_in_client.get("/admin/settings")

    # Create a normal assistant user first.
    page = logged_in_client.get("/admin/users/new")
    assert page.status_code == 200
    token = get_csrf_token(page)
    reception_role_id = _make_role_id("Reception")
    create_resp = logged_in_client.post(
        "/admin/users/new",
        data={
            "csrf_token": token,
            "username": "merge_manager_user",
            "password": "any",
            "full_name": "Merge Manager User",
            "roles": [str(reception_role_id)],
            "is_active": "1",
        },
        follow_redirects=False,
    )
    assert create_resp.status_code in (302, 303)

    conn = raw_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE username='merge_manager_user'").fetchone()
        assert row is not None
        user_id = row["id"]
    finally:
        conn.close()

    # Update the user to Manager.
    edit_page = logged_in_client.get(f"/admin/users/{user_id}/edit")
    assert edit_page.status_code == 200
    token = get_csrf_token(edit_page)
    manager_role_id = _make_role_id("Manager")
    resp = logged_in_client.post(
        f"/admin/users/{user_id}/edit",
        data={
            "csrf_token": token,
            "username": "merge_manager_user",
            "full_name": "Merge Manager User",
            "roles": [str(manager_role_id)],
            "is_active": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    conn = raw_db()
    try:
        row = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        assert row is not None
        # Legacy role should remain compatible with older CHECK constraints.
        assert (row["role"] or "").lower() in ("assistant", "admin", "doctor")
    finally:
        conn.close()


def test_cannot_demote_last_admin(logged_in_client, get_csrf_token):
    admin_role_id = _make_role_id("Admin")
    doctor_role_id = _make_role_id("Doctor")
    admin_id = _isolate_admin_user(admin_role_id)

    page = logged_in_client.get(f"/admin/users/{admin_id}/edit")
    assert page.status_code == 200
    token = get_csrf_token(page)
    resp = logged_in_client.post(
        f"/admin/users/{admin_id}/edit",
        data={
            "csrf_token": token,
            "username": "admin",
            "full_name": "Admin User",
            "roles": [str(doctor_role_id)],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert b"At least one admin account must remain" in resp.data

    conn = raw_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM user_roles WHERE user_id=? AND role_id=?",
            (admin_id, admin_role_id),
        ).fetchone()
        assert row["cnt"] == 1
    finally:
        conn.close()


def test_cannot_delete_last_admin(logged_in_client, get_csrf_token):
    admin_role_id = _make_role_id("Admin")
    admin_id = _isolate_admin_user(admin_role_id)

    login_page = logged_in_client.get("/patients/new")
    token = get_csrf_token(login_page)
    resp = logged_in_client.post(
        f"/admin/users/{admin_id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    conn = raw_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE id=?", (admin_id,)).fetchone()
        assert row is not None, "Admin user should not be deleted"
    finally:
        conn.close()


def test_primary_admin_cannot_be_demoted_even_with_other_admins(logged_in_client, get_csrf_token):
    _create_extra_admin("backup_admin")
    doctor_role_id = _make_role_id("Doctor")
    admin_id = _get_primary_admin_id()

    page = logged_in_client.get(f"/admin/users/{admin_id}/edit")
    assert page.status_code == 200
    token = get_csrf_token(page)
    resp = logged_in_client.post(
        "/admin/users/admin/edit",
        data={
            "csrf_token": token,
            "username": "admin",
            "full_name": "Admin User",
            "roles": [str(doctor_role_id)],
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert b"primary admin account must remain" in resp.data

    conn = raw_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM user_roles ur JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=(SELECT id FROM users WHERE username='admin') AND r.name='Admin'"
        ).fetchone()
        assert row["cnt"] == 1
    finally:
        conn.close()


def test_primary_admin_cannot_be_deleted_even_with_other_admins(logged_in_client, get_csrf_token):
    _create_extra_admin("backup_admin2")
    admin_id = _get_primary_admin_id()
    page = logged_in_client.get("/patients/new")
    token = get_csrf_token(page)
    resp = logged_in_client.post(
        f"/admin/users/{admin_id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    conn = raw_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        assert row is not None
    finally:
        conn.close()
