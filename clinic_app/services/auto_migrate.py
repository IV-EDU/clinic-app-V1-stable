"""Automatically run Alembic migrations when the app starts."""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from flask import Flask


def auto_upgrade(app: Flask) -> None:
    """Run `alembic upgrade head` automatically if enabled."""

    if os.getenv("CLINIC_AUTO_MIGRATE", "1") != "1":
        return

    repo_root = Path(__file__).resolve().parents[2]
    alembic_ini = repo_root / "alembic.ini"
    migrations_dir = repo_root / "migrations"
    if not alembic_ini.exists() or not migrations_dir.exists():
        return

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(migrations_dir))
    cfg.set_main_option("sqlalchemy.url", app.config["SQLALCHEMY_DATABASE_URI"])

    try:
        command.upgrade(cfg, "head")
    except Exception as exc:  # pragma: no cover - defensive guard
        app.logger.warning("Auto migration skipped: %s", exc)
