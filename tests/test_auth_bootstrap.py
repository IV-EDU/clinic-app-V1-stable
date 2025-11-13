from clinic_app import create_app
from clinic_app.services.database import db


def test_first_login_creates_admin(app, client, get_csrf_token):
    login_page = client.get("/auth/login")
    assert b"create the first admin account" in login_page.data
    token = get_csrf_token(login_page)
    resp = client.post(
        "/auth/login",
        data={"username": "owner", "password": "supersecret", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    conn = db()
    try:
        row = conn.execute("SELECT username, role FROM users WHERE username='owner'").fetchone()
        assert row is not None
        assert row["role"] == "admin"
    finally:
        conn.close()


def test_login_page_bootstraps_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "empty.db"
    monkeypatch.setenv("CLINIC_DB_PATH", str(db_path))
    monkeypatch.setenv("CLINIC_SECRET_KEY", "test")
    app = create_app()
    with app.test_client() as client:
        resp = client.get("/auth/login")
        assert resp.status_code == 200
        assert b"create the first admin account" in resp.data
