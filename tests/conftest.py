import os
import re
import shutil
import sys
import pathlib
import re
import sys

import pytest
from werkzeug.security import generate_password_hash

root = pathlib.Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from clinic_app import create_app
from clinic_app.services.database import db as raw_db


@pytest.fixture(scope="session")
def _template_db(tmp_path_factory):
    """Build a fully-migrated DB once per test session.

    Every function-scoped ``app`` fixture copies this file instead of
    running 18 Alembic migrations from scratch — makes the suite ~10×
    faster.
    """
    db_path = tmp_path_factory.mktemp("template") / "app.db"
    old_db = os.environ.get("CLINIC_DB_PATH")
    old_key = os.environ.get("CLINIC_SECRET_KEY")
    os.environ["CLINIC_DB_PATH"] = str(db_path)
    os.environ["CLINIC_SECRET_KEY"] = "test-secret"
    try:
        _app = create_app()
        # Push an app context so extensions close cleanly.
        with _app.app_context():
            pass
    finally:
        # Restore environment so monkeypatch in tests can work normally.
        if old_db is None:
            os.environ.pop("CLINIC_DB_PATH", None)
        else:
            os.environ["CLINIC_DB_PATH"] = old_db
        if old_key is None:
            os.environ.pop("CLINIC_SECRET_KEY", None)
        else:
            os.environ["CLINIC_SECRET_KEY"] = old_key
    return db_path


@pytest.fixture
def app(tmp_path, monkeypatch, _template_db):
    # Copy pre-migrated template DB — avoids running Alembic per test.
    db_path = tmp_path / "app.db"
    shutil.copy2(_template_db, db_path)
    monkeypatch.setenv("CLINIC_DB_PATH", str(db_path))
    monkeypatch.setenv("CLINIC_SECRET_KEY", "test-secret")
    monkeypatch.setenv("CLINIC_AUTO_MIGRATE", "0")  # Already migrated
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_user(app):
    """Create an admin user with proper RBAC permissions for tests."""
    conn = raw_db()
    try:
        conn.execute(
            "INSERT INTO users(id, username, password_hash, role, full_name, is_active, created_at, updated_at) "
            "VALUES (?, ?, ?, 'admin', ?, 1, datetime('now'), datetime('now'))",
            ("admin-test", "admin", generate_password_hash("password123"), "Administrator"),
        )
        role = conn.execute("SELECT id FROM roles WHERE name='Admin'").fetchone()
        if role:
            conn.execute(
                "INSERT OR IGNORE INTO user_roles(user_id, role_id) VALUES (?, ?)",
                ("admin-test", role[0]),
            )
        conn.commit()
        return {"username": "admin", "password": "password123"}
    finally:
        conn.close()


def _extract_csrf(response) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.data.decode("utf-8"))
    assert match, "CSRF token not found"
    return match.group(1)


@pytest.fixture
def logged_in_client(client, admin_user):
    login_page = client.get("/auth/login")
    token = _extract_csrf(login_page)
    resp = client.post(
        "/auth/login",
        data={"username": admin_user["username"], "password": admin_user["password"], "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    return client


@pytest.fixture
def get_csrf_token():
    return _extract_csrf
