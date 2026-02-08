"""Flask CLI commands for migrations, bootstrap, and legacy import."""

from __future__ import annotations

import json
import os
import shutil
from datetime import date, datetime, timezone
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
from clinic_app.models_rbac import Role, User
from clinic_app.services.database import db as raw_db
from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, ANY_DOCTOR_LABEL
from clinic_app.services.import_first_stable import (
    extract_first_stable_payments,
    build_patient_group_key,
    normalize_file_number,
    normalize_name,
)
from clinic_app.services.patients import migrate_patients_drop_unique_short_id, next_short_id


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

    @app.cli.command("preview-import-first-stable")
    @click.option(
        "--source",
        type=click.Path(exists=True, dir_okay=False),
        default=str(Path("Current Clinic Excel") / "First stable.xlsm"),
        show_default=True,
        help="Path to the legacy 'First stable' Excel file.",
    )
    @with_appcontext
    def preview_import_first_stable(source: str) -> None:
        """Import legacy Excel data into a **preview** database.

        This command is designed for safe review only:
        - It requires that SQLALCHEMY_DATABASE_URI points to a *separate*
          preview DB (usually by setting CLINIC_DB_PATH).
        - It wipes existing patients and payments in that preview DB.
        - It then recreates patients + payments based on the Excel file,
          wiring all payments to the special \"Any Doctor\" entry.
        """
        source_path = Path(source)
        if not source_path.exists():
            raise click.ClickException(f"Excel file not found: {source_path}")

        # Protect the real app.db – only allow import when using an override DB.
        data_root = Path(current_app.config["DATA_ROOT"])
        main_db_path = data_root / "app.db"
        uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
        if not uri.startswith("sqlite:///"):
            raise click.ClickException("Only sqlite databases are supported for preview import.")
        current_db_path = Path(uri.replace("sqlite:///", "")).resolve()

        if current_db_path == main_db_path.resolve():
            raise click.ClickException(
                "Refusing to import into the main app.db.\n"
                "Set CLINIC_DB_PATH to a separate preview DB path "
                "(for example: data/preview_app.db) and run again."
            )

        click.echo(f"[INFO] Using preview database at: {current_db_path}")
        click.echo(f"[INFO] Reading Excel file: {source_path}")

        try:
            payments, counts = extract_first_stable_payments(source_path)
        except FileNotFoundError as exc:
            raise click.ClickException(str(exc)) from exc

        if not payments:
            click.echo("[INFO] No payment rows were found in the Excel file.")
            click.echo(f"Counts: {json.dumps(counts, ensure_ascii=False, indent=2)}")
            return

        money_payments = counts.get("payments", len(payments))
        zero_entries = counts.get("zero_entries", 0)
        skipped_rows = counts.get("skipped_rows", 0)
        click.echo(
            f"[INFO] Parsed {counts.get('total_rows', len(payments))} rows "
            f"-> {money_payments} money payments"
            + (f" + {zero_entries} zero-amount entries" if zero_entries else "")
            + (f" (skipped {skipped_rows} empty rows)" if skipped_rows else "")
            + f" for approximately {counts.get('patients', 0)} patients."
        )

        conn = raw_db()
        try:
            migrate_patients_drop_unique_short_id(conn)
            cur = conn.cursor()

            # Start with a clean slate in the preview DB.
            click.echo("[INFO] Clearing existing patients and payments in preview DB...")
            cur.execute("DELETE FROM payments")
            # Page numbers (if enabled in this database) must be cleared too.
            try:
                cur.execute("DELETE FROM patient_pages")
            except Exception:
                pass
            cur.execute("DELETE FROM patients")
            conn.commit()

            # Group by (file number + name) so we keep the Excel concept of a patient.
            patient_map: dict[str, str] = {}
            has_patient_pages = False
            try:
                has_patient_pages = (
                    cur.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='patient_pages' LIMIT 1"
                    ).fetchone()
                    is not None
                )
            except Exception:
                has_patient_pages = False
            has_primary_page_number = False
            try:
                cols = cur.execute("PRAGMA table_info(patients)").fetchall() or []
                has_primary_page_number = any((c[1] == "primary_page_number") for c in cols)
            except Exception:
                has_primary_page_number = False

            created_patients = 0
            created_payments = 0

            for p in payments:
                # In the legacy Excel, this column is the notebook/page number.
                page_raw = (p.short_id or "").strip()
                name_raw = (p.full_name or "").strip()
                phone_raw = (p.phone or "").strip()

                if not name_raw and not page_raw and not phone_raw:
                    # Too little information to safely create a patient.
                    continue
                group_key = build_patient_group_key(page_raw, name_raw, phone_raw)
                if not group_key:
                    # Fallback: treat this row as its own patient using a synthetic key.
                    group_key = f"row-{created_patients}-{created_payments}"

                if group_key not in patient_map:
                    patient_id = str(uuid4())

                    # In preview mode we keep real app "file numbers" separate from
                    # notebook page numbers, so file numbers are always auto-generated.
                    short_id_val = next_short_id(conn)

                    primary_page = page_raw.strip() if page_raw else None
                    if has_primary_page_number:
                        cur.execute(
                            """
                            INSERT INTO patients (id, short_id, full_name, phone, notes, primary_page_number)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                patient_id,
                                short_id_val,
                                name_raw or short_id_val,
                                phone_raw or None,
                                None,
                                primary_page,
                            ),
                        )
                    else:
                        cur.execute(
                            "INSERT INTO patients (id, short_id, full_name, phone, notes) VALUES (?, ?, ?, ?, ?)",
                            (patient_id, short_id_val, name_raw or short_id_val, phone_raw or None, None),
                        )
                    if has_patient_pages and page_raw:
                        try:
                            cur.execute(
                                """
                                INSERT INTO patient_pages (id, patient_id, page_number, notebook_name)
                                VALUES (?, ?, ?, ?)
                                """,
                                (str(uuid4()), patient_id, page_raw, None),
                            )
                        except Exception:
                            # Preview import should never fail the whole run because of page numbers.
                            pass
                    patient_map[group_key] = patient_id
                    created_patients += 1

                patient_id = patient_map[group_key]

                # Derive visit type flags from the Excel visit columns/labels.
                visit_label = (p.visit_label or "").strip()
                exam_flag = 1 if getattr(p, "exam_flag", 0) else 0
                follow_flag = 1 if getattr(p, "follow_flag", 0) else 0
                if not exam_flag and not follow_flag and visit_label:
                    visit_lower = visit_label.lower()
                    if "كشف" in visit_lower:
                        exam_flag = 1
                    elif "متاب" in visit_lower:
                        follow_flag = 1

                total_cents = p.total_cents or 0
                paid_cents = p.paid_cents or 0
                remaining_cents = p.remaining_cents
                if remaining_cents is None:
                    remaining_cents = 0
                if remaining_cents == 0 and total_cents and paid_cents:
                    # Trust Excel if it said "خالص"; otherwise recompute safely.
                    diff = total_cents - paid_cents
                    if diff > 0 and (p.raw_remaining or "").strip() != "خالص":
                        remaining_cents = diff
                if remaining_cents < 0:
                    remaining_cents = 0

                pay_id = str(uuid4())
                cur.execute(
                    """
                    INSERT INTO payments (
                        id,
                        patient_id,
                        paid_at,
                        amount_cents,
                        method,
                        note,
                        treatment,
                        remaining_cents,
                        total_amount_cents,
                        examination_flag,
                        followup_flag,
                        discount_cents,
                        doctor_id,
                        doctor_label
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pay_id,
                        patient_id,
                        p.paid_at or date.today().isoformat(),
                        paid_cents,
                        "cash",
                        p.notes or "",
                        p.treatment_type or "",
                        remaining_cents,
                        total_cents,
                        exam_flag,
                        follow_flag,
                        0,
                        ANY_DOCTOR_ID,
                        ANY_DOCTOR_LABEL,
                    ),
                )
                created_payments += 1

            conn.commit()
        finally:
            conn.close()

        click.echo(
            f"[DONE] Preview import complete: {created_patients} patients, "
            f"{created_payments} payments loaded into {current_db_path}."
        )
