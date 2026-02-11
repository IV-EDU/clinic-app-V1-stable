import json
import pathlib
import sqlite3

import pytest
from werkzeug.security import generate_password_hash

from clinic_app import create_app
from clinic_app.extensions import db as db_engine
from clinic_app.services.database import db


def test_csrf_rejects_missing_token(logged_in_client):
    resp = logged_in_client.post(
        "/patients/new",
        data={"full_name": "Missing Token"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_login_rate_limit(client, admin_user, get_csrf_token):
    for _ in range(5):
        login_page = client.get("/auth/login")
        token = get_csrf_token(login_page)
        resp = client.post(
            "/auth/login",
            data={"username": admin_user["username"], "password": "wrong", "csrf_token": token},
        )
        assert resp.status_code == 200
    login_page = client.get("/auth/login")
    token = get_csrf_token(login_page)
    resp = client.post(
        "/auth/login",
        data={"username": admin_user["username"], "password": "wrong", "csrf_token": token},
    )
    assert resp.status_code == 429


def test_mutation_rate_limit(logged_in_client, get_csrf_token):
    for i in range(60):
        page = logged_in_client.get("/patients/new")
        token = get_csrf_token(page)
        resp = logged_in_client.post(
            "/patients/new",
            data={"full_name": f"Rate Limit {i}", "csrf_token": token},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303)
    page = logged_in_client.get("/patients/new")
    token = get_csrf_token(page)
    resp = logged_in_client.post(
        "/patients/new",
        data={"full_name": "Rate Limit Final", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 429


def test_security_headers_present(logged_in_client):
    resp = logged_in_client.get("/")
    headers = resp.headers
    assert "default-src" in headers.get("Content-Security-Policy", "")
    assert headers.get("Referrer-Policy") == "no-referrer"
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("Permissions-Policy") == "geolocation=(), camera=(), microphone=()"
    assert headers.get("Cache-Control") == "no-store"


def test_static_not_marked_no_store(client):
    resp = client.get("/static/css/app.css")
    assert resp.status_code == 200
    assert "Cache-Control" not in resp.headers or resp.headers["Cache-Control"].lower() != "no-store"


def test_alembic_upgrade_creates_schema(tmp_path, monkeypatch):
    db_path = tmp_path / "schema.db"
    monkeypatch.setenv("CLINIC_DB_PATH", str(db_path))
    monkeypatch.setenv("CLINIC_SECRET_KEY", "test")
    app = create_app()
    db_engine.engine.dispose()
    if db_path.exists():
        db_path.unlink()
    runner = app.test_cli_runner()
    result = runner.invoke(args=["db", "upgrade"])
    assert result.exit_code == 0, result.output
    conn = sqlite3.connect(db_path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert {"patients", "payments", "users", "audit_log"}.issubset(tables)


def test_legacy_import_dry_run(app, tmp_path):
    source_db = tmp_path / "legacy.db"
    conn = sqlite3.connect(source_db)
    conn.execute("CREATE TABLE patients (id TEXT PRIMARY KEY, full_name TEXT)")
    conn.execute("INSERT INTO patients VALUES (?, ?)", ("p1", "Legacy Patient"))
    conn.commit()
    conn.close()

    runner = app.test_cli_runner()
    result = runner.invoke(args=["legacy-import", "--source", str(source_db), "--dry-run"])
    assert result.exit_code == 0, result.output
    report_dir = pathlib.Path(app.config["DATA_ROOT"]) / "import_reports"
    reports = list(report_dir.glob("legacy-import-*.json"))
    assert reports, "expected import report file"
    payload = json.loads(reports[-1].read_text())
    assert payload.get("dry_run") is True


def test_role_matrix_enforced(app, get_csrf_token):
    conn = db()
    conn.execute(
        "INSERT INTO users(id, username, password_hash, role, is_active, created_at) VALUES (?, ?, ?, ?, 1, datetime('now'))",
        ("assistant-test", "assistant", generate_password_hash("assistant123"), "assistant"),
    )
    conn.commit()
    conn.close()

    client = app.test_client()
    login_page = client.get("/auth/login")
    token = get_csrf_token(login_page)
    resp = client.post(
        "/auth/login",
        data={"username": "assistant", "password": "assistant123", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    page = client.get("/patients/new")
    token = get_csrf_token(page)
    resp = client.post(
        "/patients/new",
        data={"full_name": "Assistant Patient", "csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)

    patient_conn = db()
    patient_row = patient_conn.execute("SELECT id FROM patients WHERE full_name=?", ("Assistant Patient",)).fetchone()
    patient_conn.close()
    assert patient_row

    resp = client.get(f"/patients/{patient_row['id']}/delete")
    assert resp.status_code == 403

    resp = client.get("/diagnostics")
    assert resp.status_code == 403
    audit_conn = db()
    entry = audit_conn.execute(
        "SELECT action, result FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    audit_conn.close()
    assert entry is not None
    assert entry["action"] == "diagnostics:view"
    assert entry["result"] == "denied"

    page = client.get("/patients/new")
    token = get_csrf_token(page)
    resp = client.post(
        "/backup/restore",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 403
    audit_conn = db()
    entry = audit_conn.execute(
        "SELECT action, result FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    audit_conn.close()
    assert entry is not None
    assert entry["action"] == "backup:restore"
    assert entry["result"] == "denied"


def test_audit_append_only_trigger(app):
    conn = db()
    try:
        conn.execute(
            "INSERT INTO audit_log(actor_user_id, action, result, meta_json_redacted) VALUES (NULL, 'test', 'ok', '{}')"
        )
        conn.commit()
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE audit_log SET action='changed'")
    finally:
        conn.close()
