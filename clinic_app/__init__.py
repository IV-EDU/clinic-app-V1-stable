"""Clinic app package exposing the Flask application factory."""

from __future__ import annotations

import os
import json
import sys
from pathlib import Path
from datetime import timedelta, datetime, timezone

from flask import Flask, jsonify
from flask_wtf.csrf import CSRFError

from .blueprints import register_blueprints
from .extensions import init_extensions
from .services.i18n import SUPPORTED_LOCALES, register_jinja
from .services.ui import register_ui
from .services.security import init_security
from .services.auto_migrate import auto_upgrade
from .services.bootstrap import ensure_base_tables
from .services.admin_guard import ensure_admin_exists
from .cli import register_cli
from .auth import login_manager

APP_HOST = "127.0.0.1"
APP_PORT = 8080


def _data_root(base_dir: Path, override: Path | None = None) -> Path:
    root = override if override else base_dir / "data"
    root.mkdir(parents=True, exist_ok=True)
    for sub in (
        "patient_images",
        "backups",
        "exports",
        "audit",
        "audit/archive",
        "import_reports",
        "receipts",
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _resource_root() -> Path:
    """Root folder for bundled resources (templates/static)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def _default_user_data_root() -> Path:
    """Writable per-user data root for packaged builds (offline clinics)."""
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA")
        if base:
            return Path(base) / "ClinicApp"
        return Path.home() / "AppData" / "Local" / "ClinicApp"
    base = os.getenv("XDG_DATA_HOME")
    if base:
        return Path(base) / "ClinicApp"
    return Path.home() / ".local" / "share" / "ClinicApp"


def create_app() -> Flask:
    resource_root = _resource_root()
    template_folder = resource_root / "templates"
    static_folder = resource_root / "static"
    db_override = os.getenv("CLINIC_DB_PATH")
    if db_override:
        override_root = Path(db_override).parent
    elif getattr(sys, "frozen", False):
        # Portable mode: keep `data/` next to the executable so clinics can back it up easily.
        # IMPORTANT: this requires installing/unzipping to a writable folder (default in user profile).
        override_root = Path(sys.executable).resolve().parent / "data"
    else:
        override_root = None
    data_root = _data_root(resource_root, override_root)

    app = Flask(
        __name__,
        template_folder=str(template_folder),
        static_folder=str(static_folder),
    )

    secret_key = os.getenv("CLINIC_SECRET_KEY")
    if not secret_key:
        secret_key = os.urandom(32)

    def _apply_pending_db_restore(data_root_path: Path, main_db: Path) -> None:
        """Apply a requested restore before opening the main database."""
        marker_path = data_root_path / "restore_pending.json"
        if not marker_path.exists():
            return
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except Exception:
            return

        backup_name = (marker.get("backup_name") or "").strip()
        if not backup_name or "/" in backup_name or "\\" in backup_name:
            return

        backup_path = data_root_path / "backups" / backup_name
        if not backup_path.exists():
            return

        import sqlite3

        # Safety backup of current DB before overwriting.
        try:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            safety_path = data_root_path / "backups" / f"app-before-restore-{ts}.db"
            src = sqlite3.connect(str(main_db))
            try:
                dst = sqlite3.connect(str(safety_path))
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
        except Exception:
            # If safety backup fails, do not proceed.
            return

        # Restore requested backup into app.db.
        try:
            src = sqlite3.connect(str(backup_path))
            try:
                dst = sqlite3.connect(str(main_db))
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
        except Exception:
            return

        # Clear marker on success.
        try:
            marker_path.unlink()
        except Exception:
            pass

    if db_override:
        db_path = Path(db_override)
    else:
        db_path = data_root / "app.db"
        # Apply pending restore only for the main DB (never for preview DBs).
        try:
            _apply_pending_db_restore(data_root, db_path)
        except Exception:
            pass

    default_locale = os.getenv("CLINIC_DEFAULT_LOCALE", "en").lower()
    if default_locale not in SUPPORTED_LOCALES:
        default_locale = "en"

    doctor_list = [
        doc.strip()
        for doc in os.getenv("CLINIC_DOCTORS", "Dr. Lina,Dr. Omar").split(",")
        if doc.strip()
    ]
    if not doctor_list:
        doctor_list = ["On Call"]

    app.config.update(
        SECRET_KEY=secret_key,
        SESSION_COOKIE_NAME="clinic_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        SQLALCHEMY_ENGINE_OPTIONS={"connect_args": {"check_same_thread": False}},
        RATELIMIT_STORAGE_URI=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
        DATA_ROOT=str(data_root),
        PALMER_PLUS_DB=str(db_path),
        DEFAULT_LOCALE=default_locale,
        LOCALE_COOKIE_NAME="lang",
        LOCALE_COOKIE_MAX_AGE=60 * 60 * 24 * 365,
        APPOINTMENT_SLOT_MINUTES=int(os.getenv("APPOINTMENT_SLOT_MINUTES", "30")),
        APPOINTMENT_CONFLICT_GRACE_MINUTES=int(os.getenv("APPOINTMENT_CONFLICT_GRACE_MINUTES", "5")),
        APPOINTMENT_DOCTORS=doctor_list,
        RECEIPT_SERIAL_PREFIX=os.getenv("RECEIPT_SERIAL_PREFIX", "R"),
        PDF_FONT_PATH=os.getenv(
            "PDF_FONT_PATH", str(resource_root / "static" / "fonts" / "DejaVuSans.ttf")
        ),
        # Arabic font defaults (offline): use DejaVu Sans (bundled).
        PDF_FONT_PATH_AR=os.getenv(
            "PDF_FONT_PATH_AR", str(resource_root / "static" / "fonts" / "DejaVuSans.ttf")
        ),
        PDF_FONT_PATH_AR_BOLD=os.getenv(
            "PDF_FONT_PATH_AR_BOLD",
            str(
                (resource_root / "static" / "fonts" / "DejaVuSans.ttf")
            ),
        ),
        PDF_DEFAULT_ARABIC=os.getenv("PDF_DEFAULT_ARABIC", "cairo"),  # cairo|dejavu
    )

    register_jinja(app)
    register_ui(app)
    init_extensions(app)
    login_manager.init_app(app)
    register_blueprints(app)
    auto_upgrade(app)
    ensure_base_tables(Path(app.config["PALMER_PLUS_DB"]))
    ensure_admin_exists()
    init_security(app)
    register_cli(app)

    # Disable template caching so changes show immediately even when debug is False
    app.config.setdefault("TEMPLATES_AUTO_RELOAD", True)
    app.jinja_env.auto_reload = True
    app.jinja_env.cache.clear()

    # Add CSRF error handling to catch CSRF validation failures
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        print(f"CSRF ERROR: {e}")
        return jsonify({"success": False, "errors": [f"CSRF validation failed: {str(e)}"]}), 400

    # Add general error handler to log all 400s that don't reach routes
    @app.errorhandler(400)
    def handle_bad_request(e):
        print(f"BAD REQUEST ERROR: {e}")
        return jsonify({"success": False, "errors": ["Bad request - check request format and CSRF token"]}), 400

    return app


__all__ = ["create_app", "APP_HOST", "APP_PORT"]
