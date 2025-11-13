"""Alembic migration helpers."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from flask import Flask


def _alembic_config(app: Flask) -> Config:
    root = Path(app.root_path).parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", app.config["SQLALCHEMY_DATABASE_URI"])
    cfg.attributes["configure_logger"] = False
    return cfg


def run_migrations(app: Flask) -> None:
    """Upgrade the database to the latest revision."""

    cfg = _alembic_config(app)
    command.upgrade(cfg, "head")


def alembic_config(app: Flask) -> Config:
    """Expose a configured Alembic Config for CLI commands."""

    return _alembic_config(app)
