import re
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


@pytest.fixture
def app(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    monkeypatch.setenv("CLINIC_DB_PATH", str(db_path))
    monkeypatch.setenv("CLINIC_SECRET_KEY", "test-secret")
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
    runner = app.test_cli_runner()
    result = runner.invoke(args=["db", "upgrade"])
    assert result.exit_code == 0, result.output
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
