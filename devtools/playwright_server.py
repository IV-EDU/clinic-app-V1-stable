"""Start the Clinic app for Playwright tests with an isolated database."""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _default_db_path() -> Path:
    temp_root = Path(os.getenv("TEMP", ".")).resolve() / "clinic-app-local-playwright"
    temp_root.mkdir(parents=True, exist_ok=True)
    return temp_root / "app-e2e.db"


def _resolve_db_path() -> Path:
    raw = (os.getenv("PW_E2E_DB_PATH") or "").strip()
    if raw:
        db_path = Path(raw).expanduser().resolve()
    else:
        db_path = _default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def _should_reset_db() -> bool:
    raw = (os.getenv("PW_RESET_DB", "1") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _cleanup_database_files(db_path: Path) -> None:
    if not _should_reset_db():
        return
    candidates = [db_path, db_path.with_name(db_path.name + "-wal"), db_path.with_name(db_path.name + "-shm")]
    for candidate in candidates:
        try:
            candidate.unlink()
        except FileNotFoundError:
            continue


def _ensure_admin_user(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        existing = conn.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
        if existing:
            return

        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        now = datetime.now(timezone.utc).isoformat()
        user_id = f"pw-admin-{uuid4().hex[:12]}"
        password_hash = generate_password_hash("admin")

        if "full_name" in cols:
            conn.execute(
                """
                INSERT INTO users(id, username, password_hash, role, full_name, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (user_id, "admin", password_hash, "admin", "Administrator", now, now),
            )
        else:
            conn.execute(
                """
                INSERT INTO users(id, username, password_hash, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (user_id, "admin", password_hash, "admin", now, now),
            )

        admin_role = conn.execute("SELECT id FROM roles WHERE name='Admin' LIMIT 1").fetchone()
        if admin_role:
            conn.execute(
                "INSERT OR IGNORE INTO user_roles(user_id, role_id) VALUES (?, ?)",
                (user_id, admin_role[0]),
            )
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    db_path = _resolve_db_path()
    _cleanup_database_files(db_path)

    os.environ["CLINIC_DB_PATH"] = str(db_path)
    os.environ.setdefault("CLINIC_SECRET_KEY", "playwright-e2e-secret")

    from clinic_app import APP_HOST, create_app

    app = create_app()
    resolved_db_path = Path(app.config["PALMER_PLUS_DB"])
    _ensure_admin_user(resolved_db_path)

    host = os.getenv("PW_HOST", APP_HOST)
    port = int(os.getenv("PW_PORT", "8181"))

    print(f"[INFO] Playwright server using DB: {resolved_db_path}")
    print(f"[INFO] Playwright server listening on: http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
