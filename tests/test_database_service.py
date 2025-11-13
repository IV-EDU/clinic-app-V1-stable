
import importlib

from clinic_app.services.database import db


def test_database_service_imports():
    m = importlib.import_module("clinic_app.services.database")
    assert hasattr(m, "db")


def test_sqlite_pragmas_active(app):
    conn = db()
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        foreign = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal"
    assert timeout == 5000
    assert foreign == 1
