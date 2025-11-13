"""Flask CLI commands for migrations, bootstrap, and legacy import."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from getpass import getpass
from pathlib import Path
from typing import Any
from uuid import uuid4

import click
from alembic import command
from alembic.config import Config
from flask import current_app
from flask.cli import AppGroup, with_appcontext
from sqlalchemy import select, text
from werkzeug.security import generate_password_hash

from clinic_app.extensions import db
from clinic_app.services.database import db as raw_db
from clinic_app.models_rbac import Role, User


def _alembic_config() -> Config:
    root = Path(current_app.root_path).parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", current_app.config["SQLALCHEMY_DATABASE_URI"])
    cfg.attributes["configure_logger"] = False
    return cfg


def register_cli(app) -> None:
    db_group = AppGroup("db")

    @db_group.command("upgrade")
    @with_appcontext
    def upgrade() -> None:
        cfg = _alembic_config()
        command.upgrade(cfg, "head")

    app.cli.add_command(db_group)

    @app.cli.command("seed-admin")
    @click.option("--username", default="admin", show_default=True)
    @click.option("--password", default="ChangeMe!123", show_default=True)
    @with_appcontext
    def seed_admin(username: str, password: str) -> None:
        session = db.session()
        try:
            existing = session.execute(select(User.id).where(User.username == username)).scalar_one_or_none()
            if existing:
                click.echo(f"User '{username}' already exists.")
                return
            role = (
                session.execute(select(Role).where(Role.name == "Admin"))
                .unique()
                .scalars()
                .one_or_none()
            )
            if role is None:
                raise click.ClickException("Admin role is missing. Run migrations first.")
            now = datetime.now(timezone.utc).isoformat()
            user = User(
                id=str(uuid4()),
                username=username,
                full_name=username,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            user.role = "admin"
            user.set_password(password)
            user.roles.append(role)
            user.sync_legacy_role()
            session.add(user)
            session.commit()
            click.echo(f"Admin user '{username}' created with the provided password.")
        finally:
            session.close()

    @app.cli.command("bootstrap-admin")
    @click.option("--username", required=True, help="Username for the admin account")
    @with_appcontext
    def bootstrap_admin(username: str) -> None:
        password = os.getenv("CLINIC_BOOTSTRAP_ADMIN_PASSWORD")
        if not password:
            password = getpass("Admin password: ")
        if not password:
            raise click.ClickException("Password must not be empty")

        session = db.session()
        try:
            result = session.execute(text("SELECT id FROM users WHERE username = :username"), {"username": username}).fetchone()
            if result:
                raise click.ClickException("User already exists")
            user_id = datetime.now(timezone.utc).strftime("admin-%Y%m%d%H%M%S")
            timestamps = datetime.now(timezone.utc).isoformat()
            session.execute(
                text(
                    "INSERT INTO users(id, username, password_hash, role, is_active, created_at, updated_at) "
                    "VALUES (:id, :username, :password_hash, 'admin', 1, :created_at, :updated_at)"
                ),
                {
                    "id": user_id,
                    "username": username,
                    "password_hash": generate_password_hash(password),
                    "created_at": timestamps,
                    "updated_at": timestamps,
                },
            )
            role_row = session.execute(text("SELECT id FROM roles WHERE name='Admin'")).fetchone()
            if role_row:
                session.execute(
                    text("INSERT OR IGNORE INTO user_roles(user_id, role_id) VALUES (:uid, :rid)"),
                    {"uid": user_id, "rid": role_row[0]},
                )
            session.commit()
        finally:
            session.close()
        click.echo(f"Admin user '{username}' created.")

    @app.cli.command("legacy-import")
    @click.option("--source", required=True, type=click.Path(exists=True, dir_okay=False))
    @click.option("--dry-run", is_flag=True, default=False)
    @with_appcontext
    def legacy_import(source: str, dry_run: bool) -> None:
        source_path = Path(source)
        target_db = Path(current_app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", ""))
        backup_dir = Path(current_app.config["DATA_ROOT"]) / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup_path = backup_dir / f"pre-import-{timestamp}.sqlite"

        if not dry_run:
            shutil.copy2(target_db, backup_path)

        conn = raw_db()
        try:
            conn.execute("ATTACH DATABASE ? AS legacy", (str(source_path),))
            tables = conn.execute(
                "SELECT name FROM legacy.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            report: dict[str, Any] = {"tables": {}, "dry_run": dry_run}
            try:
                conn.execute("BEGIN IMMEDIATE")
                for tbl in tables:
                    name = tbl[0]
                    rows = conn.execute(f"SELECT * FROM legacy.{name}").fetchall()
                    cols = [c[1] for c in conn.execute(f"PRAGMA legacy.table_info({name})").fetchall()]
                    placeholders = ", ".join(["?"] * len(cols))
                    col_list = ", ".join([f'"{c}"' for c in cols])
                    inserted = 0
                    for row in rows:
                        try:
                            if not dry_run:
                                conn.execute(
                                    f"INSERT OR IGNORE INTO {name} ({col_list}) VALUES ({placeholders})",
                                    row,
                                )
                                inserted += 1
                        except Exception as exc:  # pragma: no cover - import diagnostics
                            report["tables"].setdefault(name, {"errors": []})
                            report["tables"][name]["errors"].append(str(exc))
                    report["tables"].setdefault(name, {})["copied"] = len(rows)
                    if not dry_run:
                        report["tables"][name]["inserted"] = inserted
                if dry_run:
                    conn.execute("ROLLBACK")
                else:
                    conn.execute("COMMIT")
            finally:
                conn.execute("DETACH DATABASE legacy")
        finally:
            conn.close()

        report_dir = Path(current_app.config["DATA_ROOT"]) / "import_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"legacy-import-{timestamp}.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        click.echo(f"Legacy import report written to {report_path}")
