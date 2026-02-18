"""Admin settings page with tabs for users, roles, and doctor colors."""

import csv
import os
import re
import hashlib
from collections.abc import Iterable, Mapping
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import io

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import selectinload
from flask_wtf.csrf import validate_csrf

from clinic_app.services.security import require_permission
from clinic_app.services.csrf import ensure_csrf_token
from clinic_app.services.doctor_colors import (
    DEFAULT_COLORS,
    ANY_DOCTOR_LABEL,
    delete_doctor_color,
    get_all_doctors_with_colors,
    init_doctor_colors_table,
    set_doctor_color,
    ensure_unique_doctor_id,
    ensure_unique_numeric_id,
    get_deleted_doctors,
    restore_doctor_color,
    purge_doctor_color,
    get_doctor_entry,
    is_doctor_blocked,
    name_exists,
    generate_unique_color,
    name_exists_any,
)
import sqlite3

from clinic_app.services.theme_settings import get_setting, get_theme_variables, set_setting
from clinic_app.services.appointments import _slugify as slugify_doctor
from clinic_app.extensions import db, csrf
from clinic_app.services.database import db as db_sqlite
from clinic_app.models_rbac import Permission, Role, User, role_permissions, user_roles, LEGACY_ROLE_PERMISSIONS
try:
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]
from clinic_app.services.ui import render_page
from clinic_app.services.import_first_stable import (
    analyze_first_stable_excel,
    analyze_import_csv_template,
    extract_first_stable_payments,
    extract_import_csv_payments,
)
from clinic_app.services.i18n import T
from clinic_app.services.payments import money
from clinic_app.services.patients import MergeConflict, merge_patient_records, migrate_patients_drop_unique_short_id, next_short_id

bp = Blueprint("admin_settings", __name__, url_prefix="/admin")
csrf.exempt(bp)


def _all_roles(session) -> list[Role]:
    """Return all roles ordered by name."""
    return session.execute(select(Role).order_by(Role.name)).unique().scalars().all()


def _roles_from_form(session, form_data) -> list[Role]:
    """Resolve role ids from the submitted form into ORM objects."""
    role_values: Iterable[object]
    if hasattr(form_data, "getlist"):
        role_values = form_data.getlist("roles")  # type: ignore[call-arg]
    elif isinstance(form_data, Mapping):
        role_values = form_data.get("roles", [])  # type: ignore[assignment]
    elif isinstance(form_data, Iterable):
        role_values = form_data
    else:
        role_values = []

    role_ids: list[int] = []
    for raw in role_values:
        if raw in (None, ""):
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        role_ids.append(value)

    if not role_ids:
        return []
    stmt = select(Role).where(Role.id.in_(role_ids))
    return session.execute(stmt).unique().scalars().all()


def _is_ck_users_role_error(err: BaseException) -> bool:
    message = str(err).lower()
    return "ck_users_role" in message and "check constraint failed" in message


def _commit_with_legacy_role_fallback(session, user: User) -> None:
    """Commit user changes, falling back to a legacy-safe role value when needed.

    Some older clinic databases enforce a SQLite CHECK constraint on users.role that
    only allows: admin/doctor/assistant. RBAC roles remain the source of truth.
    """
    try:
        session.commit()
    except IntegrityError as err:
        if not _is_ck_users_role_error(err):
            raise
        session.rollback()
        user.role = "assistant"
        session.add(user)
        session.commit()


def _fallback_user_id(session, exclude_user_id: str) -> str | None:
    """Pick another user id for reassignment (prefer current user)."""
    if current_user.is_authenticated and current_user.id != exclude_user_id:
        return current_user.id

    fallback = session.execute(
        select(User.id)
        .where(User.id != exclude_user_id)
        .order_by(User.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    return fallback


def _reassign_linked_records(session, source_user_id: str, target_user_id: str | None) -> bool:
    """Reassign FK references that block deletion."""
    if not target_user_id:
        return False
    try:
        # Reassign expense_receipts.created_by
        session.execute(
            text("UPDATE expense_receipts SET created_by=:target WHERE created_by=:source"),
            {"target": target_user_id, "source": source_user_id},
        )
    except OperationalError:
        # Expense receipts table not present; skip
        pass
    
    try:
        # Reassign receipts.issued_by_user_id
        session.execute(
            text("UPDATE receipts SET issued_by_user_id=:target WHERE issued_by_user_id=:source"),
            {"target": target_user_id, "source": source_user_id},
        )
    except OperationalError:
        # Receipts table not present or column doesn't exist; skip
        pass
    
    try:
        # Reassign receipt_reprints.user_id
        session.execute(
            text("UPDATE receipt_reprints SET user_id=:target WHERE user_id=:source"),
            {"target": target_user_id, "source": source_user_id},
        )
    except OperationalError:
        # Receipt reprints table not present; skip
        pass
    
    return True


def _admin_role(session) -> Role | None:
    return session.execute(select(Role).where(Role.name == "Admin")).unique().scalars().one_or_none()


def _has_other_admins(session, admin_role_id: int | None, exclude_user_id: str) -> bool:
    legacy_count = session.scalar(
        select(func.count())
        .select_from(User)
        .where(func.lower(User.role) == "admin", User.id != exclude_user_id)
    )
    if legacy_count:
        return True
    if admin_role_id is None:
        return False
    assigned = session.scalar(
        select(func.count())
        .select_from(user_roles)
        .where(user_roles.c.role_id == admin_role_id, user_roles.c.user_id != exclude_user_id)
    )
    return bool(assigned)


def _grouped_permissions(session) -> dict[str, list[Permission]]:
    """Group permissions into logical categories."""
    permissions = session.execute(select(Permission).order_by(Permission.code)).unique().scalars().all()

    groups = {
        f"👥 {T('perm_group_user_mgmt')}": [],
        f"📅 {T('perm_group_appointments')}": [],
        f"🏥 {T('perm_group_patients')}": [],
        f"💰 {T('perm_group_payments_receipts')}": [],
        f"📊 {T('perm_group_reports_exports')}": [],
        f"⚙️ {T('perm_group_system_admin')}": [],
        f"🖼️ {T('perm_group_images_media')}": [],
        f"💼 {T('perm_group_expenses')}": [],
    }

    for perm in permissions:
        code = perm.code.lower()
        if any(keyword in code for keyword in ['user', 'role', 'admin']):
            groups[f"👥 {T('perm_group_user_mgmt')}"].append(perm)
        elif any(keyword in code for keyword in ['appointment', 'schedule']):
            groups[f"📅 {T('perm_group_appointments')}"].append(perm)
        elif any(keyword in code for keyword in ['patient']):
            groups[f"🏥 {T('perm_group_patients')}"].append(perm)
        elif any(keyword in code for keyword in ['payment', 'receipt']):
            groups[f"💰 {T('perm_group_payments_receipts')}"].append(perm)
        elif any(keyword in code for keyword in ['report', 'export', 'collection']):
            groups[f"📊 {T('perm_group_reports_exports')}"].append(perm)
        elif any(keyword in code for keyword in ['doctor', 'color', 'system']):
            groups[f"⚙️ {T('perm_group_system_admin')}"].append(perm)
        elif any(keyword in code for keyword in ['image', 'media']):
            groups[f"🖼️ {T('perm_group_images_media')}"].append(perm)
        elif any(keyword in code for keyword in ['expense']):
            groups[f"💼 {T('perm_group_expenses')}"].append(perm)
        else:
            groups[f"⚙️ {T('perm_group_system_admin')}"].append(perm)  # Default group

    # Remove empty groups
    return {k: v for k, v in groups.items() if v}


def _bool_from_value(value: object) -> bool:
    """Convert form/JSON values to a boolean flag."""
    if isinstance(value, str):
        return value.lower() not in {"0", "false", "off", "no", ""}
    return bool(value)


def _get_user_by_any_id(session, user_id: str) -> User | None:
    """Fetch a user by id, falling back to username lookups."""
    user = session.get(User, user_id)
    if user:
        return user
    return (
        session.execute(select(User).where(User.username == user_id))
        .unique()
        .scalar_one_or_none()
    )


def _ensure_default_roles(session) -> None:
    """Create missing default roles with safe permissions (do not overwrite existing roles)."""
    try:
        all_perms = session.execute(select(Permission).order_by(Permission.code)).unique().scalars().all()
    except Exception:
        all_perms = []
    if not all_perms:
        return

    perm_by_code = {p.code: p for p in all_perms}

    defaults = [
        {
            "name": "Admin",
            "description": "Full access to all clinic features.",
            "all": True,
        },
        {
            "name": "Manager",
            "description": "Full access to all clinic features.",
            "all": True,
        },
        {
            "name": "Doctor",
            "description": "Clinical access with no user management.",
            "codes": sorted(LEGACY_ROLE_PERMISSIONS.get("doctor", set())),
        },
        {
            "name": "Reception",
            "description": "Front-desk access with data entry.",
            "codes": sorted(LEGACY_ROLE_PERMISSIONS.get("assistant", set())),
        },
        {
            "name": "Receptionist (View Only)",
            "description": "Can view patient files, payments, and reports; can fully manage appointments only.",
            "codes": [
                "appointments:edit",
                "appointments:view",
                "patients:view",
                "payments:view",
                "reports:view",
            ],
        },
    ]

    created = False
    for spec in defaults:
        role = session.execute(select(Role).where(Role.name == spec["name"])).unique().scalars().one_or_none()
        if role:
            continue
        role = Role(name=spec["name"], description=spec.get("description") or "")
        if spec.get("all"):
            role.permissions = list(all_perms)
        else:
            codes = spec.get("codes") or []
            role.permissions = [perm_by_code[c] for c in codes if c in perm_by_code]
        session.add(role)
        created = True

    if created:
        session.commit()


@bp.route("/", methods=["GET"])
@bp.route("/settings", methods=["GET"])
@require_permission("admin.user.manage")
def index():
    """Main admin settings page with tabs."""
    session = db.session()

    try:
        # Ensure default roles exist (do not overwrite existing roles).
        _ensure_default_roles(session)

        # Get all users with their roles
        stmt = select(User).options(selectinload(User.roles)).order_by(User.created_at.desc())
        users = session.execute(stmt).unique().scalars().all()

        # Get all roles with their permissions
        roles_stmt = select(Role).options(selectinload(Role.permissions)).order_by(Role.name)
        roles = session.execute(roles_stmt).unique().scalars().all()

        # Get grouped permissions
        permissions = _grouped_permissions(session)

        # Get doctor colors
        doctors = get_all_doctors_with_colors()

        theme_settings = get_theme_variables()

        # Patient/page-number settings (new feature). Guard with a safe fallback
        # so older installs or missing tables do not break the settings page.
        try:
            from clinic_app.services.patient_pages import AdminSettingsService

            patient_settings = AdminSettingsService().get_all_settings() or {}
        except Exception:
            patient_settings = {}

        return render_page(
            "admin/settings/index.html",
            users=users,
            roles=roles,
            permissions=permissions,
            doctors=doctors,
            theme_settings=theme_settings,
            patient_settings=patient_settings,
        )
    finally:
        session.close()


@bp.route("/users/new", methods=["GET"])
@bp.route("/settings/users/new", methods=["GET"])
@require_permission("admin.user.manage")
def new_user_form():
    """Render a simple form for creating a user (HTML)."""
    session = db.session()
    try:
        roles = _all_roles(session)
        return render_template("admin/user_form.html", user=None, roles=roles, errors=[])
    finally:
        session.close()


@bp.route("/users/<user_id>/edit", methods=["GET"])
@bp.route("/settings/users/<user_id>/edit", methods=["GET"])
@require_permission("admin.user.manage")
def edit_user_form(user_id: str):
    """Render the edit user form (HTML)."""
    session = db.session()
    try:
        user = _get_user_by_any_id(session, user_id)
        if not user:
            abort(404)
        roles = _all_roles(session)
        return render_template("admin/user_form.html", user=user, roles=roles, errors=[])
    finally:
        session.close()


@bp.route("/roles/new", methods=["GET"])
@bp.route("/settings/roles/new", methods=["GET"])
@require_permission("admin.user.manage")
def new_role_form():
    """Render a simple form for creating a role (HTML)."""
    session = db.session()
    try:
        permissions = session.execute(select(Permission).order_by(Permission.code)).unique().scalars().all()
        return render_template("admin/role_form.html", role=None, permissions=permissions, errors=[])
    finally:
        session.close()


@bp.route("/roles/<int:role_id>/edit", methods=["GET"])
@bp.route("/settings/roles/<int:role_id>/edit", methods=["GET"])
@require_permission("admin.user.manage")
def edit_role_form(role_id: int):
    """Render the edit role form (HTML)."""
    session = db.session()
    try:
        role = session.get(Role, role_id)
        if not role:
            abort(404)
        permissions = session.execute(select(Permission).order_by(Permission.code)).unique().scalars().all()
        return render_template("admin/role_form.html", role=role, permissions=permissions, errors=[])
    finally:
        session.close()


@bp.route("/users/create", methods=["POST"])
@bp.route("/settings/users/create", methods=["POST"])
@bp.route("/users/new", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def create_user():
    """Create a new user (JSON or HTML form)."""
    session = db.session()
    wants_json = request.is_json
    try:
        data = request.get_json(silent=True) if wants_json else request.form
        if wants_json:
            ensure_csrf_token(data or {})
        else:
            validate_csrf((data or {}).get("csrf_token"), secret_key=current_app.secret_key)

        username = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()
        full_name = (data.get("full_name") or "").strip() or username
        phone = (data.get("phone") or "").strip() or None
        is_active = _bool_from_value(data.get("is_active", True))
        if wants_json:
            selected_roles = _roles_from_form(session, SimpleNamespace(getlist=lambda k: data.get("roles", [])))
        else:
            selected_roles = _roles_from_form(session, data)

        errors = []
        if len(username) < 3:
            errors.append("Username must be at least 3 characters.")
        if not password:
            errors.append("Password is required.")
        if session.scalar(select(User.id).where(User.username == username)):
            errors.append("Username already exists.")

        if errors:
            if wants_json:
                return jsonify({"success": False, "errors": errors}), 400
            roles = _all_roles(session)
            return render_template("admin/user_form.html", user=None, roles=roles, errors=errors), 200

        now = datetime.now(timezone.utc).isoformat()
        new_user = User(
            id=str(uuid4()),
            username=username,
            full_name=full_name,
            phone=phone,
            is_active=is_active,
            created_at=now,
            updated_at=now,
        )
        new_user.set_password(password)
        new_user.roles = selected_roles
        new_user.sync_legacy_role()
        session.add(new_user)
        _commit_with_legacy_role_fallback(session, new_user)

        if wants_json:
            return jsonify({
                "success": True,
                "user": {
                    "id": new_user.id,
                    "username": new_user.username,
                    "full_name": new_user.full_name,
                    "phone": new_user.phone,
                    "is_active": new_user.is_active,
                    "roles": [role.name for role in new_user.roles]
                }
            })
        flash("User created successfully.", "ok")
        return redirect(url_for("admin_settings.index"))
    except Exception as e:
        session.rollback()
        if wants_json:
            return jsonify({"success": False, "errors": [str(e)]}), 500
        errors = ["Could not create user: " + str(e)]
        roles = _all_roles(session)
        return render_template("admin/user_form.html", user=None, roles=roles, errors=errors), 500
    finally:
        session.close()


@bp.route("/users/<user_id>/update", methods=["POST"])
@bp.route("/settings/users/<user_id>/update", methods=["POST"])
@bp.route("/users/<user_id>/edit", methods=["POST"])
@bp.route("/settings/users/<user_id>/edit", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def update_user(user_id: str):
    """Update a user via JSON or HTML form."""
    session = db.session()
    wants_json = request.is_json
    try:
        data = request.get_json(silent=True) if wants_json else request.form
        if wants_json:
            ensure_csrf_token(data or {})
        else:
            validate_csrf((data or {}).get("csrf_token"), secret_key=current_app.secret_key)

        user = _get_user_by_any_id(session, user_id)
        if not user:
            if wants_json:
                return jsonify({"success": False, "errors": ["User not found"]}), 404
            abort(404)

        new_username = (data.get("username") or "").strip()
        full_name = (data.get("full_name") or "").strip()
        phone = (data.get("phone") or "").strip() or None
        is_active = _bool_from_value(data.get("is_active", True))
        password = (data.get("password") or "").strip()
        if wants_json:
            selected_roles = _roles_from_form(session, SimpleNamespace(getlist=lambda k: data.get("roles", [])))
        else:
            selected_roles = _roles_from_form(session, data)

        admin_role = _admin_role(session)
        will_be_admin = bool(
            admin_role and any(role.id == admin_role.id for role in selected_roles)
        )
        protected_admin = user.username == "admin" or (user.id or "").startswith("admin-")

        errors = []

        # Last admin protection
        if not will_be_admin:
            if not _has_other_admins(session, getattr(admin_role, "id", None), user.id):
                errors.append("At least one admin account must remain. Assign another Admin before changing this user.")
            if protected_admin:
                errors.append("The primary admin account must remain an Admin.")

        if len(new_username) < 3:
            errors.append("Username must be at least 3 characters.")

        duplicate = session.scalar(
            select(User.id).where(User.username == new_username, User.id != user.id)
        )
        if duplicate:
            errors.append("Username already exists.")

        if errors:
            if wants_json:
                return jsonify({"success": False, "errors": errors}), 400
            roles = _all_roles(session)
            return render_template("admin/user_form.html", user=user, roles=roles, errors=errors), 200

        user.username = new_username
        user.full_name = full_name or user.full_name or new_username
        user.phone = phone
        user.is_active = is_active
        user.updated_at = datetime.now(timezone.utc).isoformat()

        if password:
            user.set_password(password)

        user.roles = selected_roles
        user.sync_legacy_role()
        _commit_with_legacy_role_fallback(session, user)
        if wants_json:
            return jsonify({
                "success": True,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "full_name": user.full_name,
                    "phone": user.phone,
                    "is_active": user.is_active,
                    "roles": [role.name for role in user.roles]
                }
            })
        flash("User updated successfully.", "ok")
        return redirect(url_for("admin_settings.index"))
    except Exception as e:
        session.rollback()
        if wants_json:
            return jsonify({"success": False, "errors": [str(e)]}), 500
        roles = _all_roles(session)
        errors = ["Could not update user: " + str(e)]
        return render_template("admin/user_form.html", user=user if 'user' in locals() else None, roles=roles, errors=errors), 500
    finally:
        session.close()


@bp.route("/users/<user_id>/delete", methods=["POST"])
@bp.route("/settings/users/<user_id>/delete", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def delete_user(user_id: str):
    """Delete a user via AJAX or HTML form."""
    session = db.session()
    wants_json = request.is_json
    try:
        data = request.get_json(silent=True) or {}
        if not wants_json and not data:
            data = request.form
        if wants_json:
            ensure_csrf_token(data)
        else:
            validate_csrf((data or {}).get("csrf_token"), secret_key=current_app.secret_key)

        user = _get_user_by_any_id(session, user_id)
        if not user:
            if wants_json:
                return jsonify({"success": False, "errors": ["User not found"]}), 404
            abort(404)

        if current_user.is_authenticated and current_user.id == user.id:
            message = "You cannot delete the account you are currently using."
            if wants_json:
                return jsonify({"success": False, "errors": [message]}), 400
            flash(message, "err")
            return redirect(url_for("admin_settings.index"))

        admin_role = _admin_role(session)
        is_admin = (user.role or "").lower() == "admin" or (
            admin_role and any(role.id == admin_role.id for role in user.roles)
        )
        protected_admin = user.username == "admin" or (user.id or "").startswith("admin-")

        if protected_admin:
            message = "The primary admin account cannot be deleted."
            if wants_json:
                return jsonify({"success": False, "errors": [message]}), 400
            flash(message, "err")
            return redirect(url_for("admin_settings.index"))

        if is_admin and not _has_other_admins(session, getattr(admin_role, "id", None), user.id):
            message = "At least one admin account must remain. Assign another Admin before deleting this user."
            if wants_json:
                return jsonify({"success": False, "errors": [message]}), 400
            flash(message, "err")
            return redirect(url_for("admin_settings.index"))

        # Reassign linked records that enforce FK constraints
        fallback_id = _fallback_user_id(session, user.id)
        if not fallback_id:
            message = "Cannot delete user: no other user available to reassign linked records. Create another user first."
            if wants_json:
                return jsonify({"success": False, "errors": [message]}), 400
            flash(message, "err")
            return redirect(url_for("admin_settings.index"))
        
        reassigned = _reassign_linked_records(session, user.id, fallback_id)

        # Clean up user relationships before deletion
        session.execute(user_roles.delete().where(user_roles.c.user_id == user.id))
        
        # Flush to apply reassignments before deletion
        session.flush()

        try:
            session.delete(user)
            session.commit()
        except IntegrityError as e:
            session.rollback()
            message = (
                "This account is linked to existing records and could not be deleted. "
                "The system attempted to reassign records but a foreign key constraint is preventing deletion. "
                "Please contact support if this issue persists."
            )
            if wants_json:
                return jsonify({"success": False, "errors": [message]}), 400
            flash(message, "err")
            return redirect(url_for("admin_settings.index"))

        if wants_json:
            return jsonify({"success": True})
        flash("User deleted.", "ok")
        return redirect(url_for("admin_settings.index"))
    except Exception as e:
        session.rollback()
        if wants_json:
            return jsonify({"success": False, "errors": [str(e)]}), 500
        flash(f"Could not delete user: {e}", "err")
        return redirect(url_for("admin_settings.index"))
    finally:
        session.close()


@bp.route("/roles/create", methods=["POST"])
@bp.route("/settings/roles/create", methods=["POST"])
@bp.route("/roles/new", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def create_role():
    """Create a new role via JSON or HTML form."""
    session = db.session()
    wants_json = request.is_json
    try:
        data = request.get_json(silent=True) if wants_json else request.form
        if wants_json:
            ensure_csrf_token(data or {})
        else:
            validate_csrf((data or {}).get("csrf_token"), secret_key=current_app.secret_key)

        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip() or None
        raw_permissions = data.get("permissions", [])
        if not wants_json and hasattr(data, "getlist"):
            raw_permissions = data.getlist("permissions")
        try:
            permission_ids = [int(pid) for pid in raw_permissions]
        except Exception:
            permission_ids = []

        if len(name) < 2:
            errors = ["Role name must be at least 2 characters."]
            if wants_json:
                return jsonify({"success": False, "errors": errors}), 400
            permissions = session.execute(select(Permission).order_by(Permission.code)).unique().scalars().all()
            return render_template("admin/role_form.html", role=None, permissions=permissions, errors=errors), 200

        if session.scalar(select(Role.id).where(Role.name == name)):
            errors = ["Role name already exists."]
            if wants_json:
                return jsonify({"success": False, "errors": errors}), 400
            permissions = session.execute(select(Permission).order_by(Permission.code)).unique().scalars().all()
            return render_template("admin/role_form.html", role=None, permissions=permissions, errors=errors), 200

        role = Role(name=name, description=description)

        if permission_ids:
            permissions = session.execute(
                select(Permission).where(Permission.id.in_(permission_ids))
            ).unique().scalars().all()
            role.permissions = permissions

        session.add(role)
        session.commit()

        if wants_json:
            return jsonify({
                "success": True,
                "role": {
                    "id": role.id,
                    "name": role.name,
                    "description": role.description,
                    "permissions": [{"id": p.id, "code": p.code, "name": p.code} for p in role.permissions]
                }
            })
        flash("Role created successfully.", "ok")
        return redirect(url_for("admin_settings.index"))
    except Exception as e:
        session.rollback()
        if wants_json:
            return jsonify({"success": False, "errors": [str(e)]}), 500
        permissions = session.execute(select(Permission).order_by(Permission.code)).unique().scalars().all()
        errors = ["Could not create role: " + str(e)]
        return render_template("admin/role_form.html", role=None, permissions=permissions, errors=errors), 500
    finally:
        session.close()


@bp.route("/roles/<int:role_id>/update", methods=["POST"])
@bp.route("/settings/roles/<int:role_id>/update", methods=["POST"])
@bp.route("/roles/<int:role_id>/edit", methods=["POST"])
@bp.route("/settings/roles/<int:role_id>/edit", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def update_role(role_id: int):
    """Update a role via JSON or HTML form."""
    session = db.session()
    wants_json = request.is_json
    try:
        data = request.get_json(silent=True) if wants_json else request.form
        if wants_json:
            ensure_csrf_token(data or {})
        else:
            validate_csrf((data or {}).get("csrf_token"), secret_key=current_app.secret_key)

        role = session.get(Role, role_id)
        if not role:
            if wants_json:
                return jsonify({"success": False, "errors": ["Role not found"]}), 404
            abort(404)

        new_name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip() or None
        raw_permissions = data.get("permissions", [])
        if not wants_json and hasattr(data, "getlist"):
            raw_permissions = data.getlist("permissions")
        try:
            permission_ids = [int(pid) for pid in raw_permissions]
        except Exception:
            permission_ids = []

        errors = []
        if len(new_name) < 2:
            errors.append("Role name must be at least 2 characters.")

        duplicate = session.scalar(
            select(Role.id).where(Role.name == new_name, Role.id != role.id)
        )
        if duplicate:
            errors.append("Role name already exists.")

        manage_codes = {"users:manage", "admin.user.manage"}
        perm_codes: set[str] = set()
        if permission_ids:
            perm_codes = set(
                session.execute(select(Permission.code).where(Permission.id.in_(permission_ids))).scalars().all()
            )

        # Safety: never allow a change that removes all admin-management permissions.
        # This prevents lockout from Admin Settings.
        if role.name == "Admin" and not (perm_codes & manage_codes):
            errors.append("Admin role must keep user management permission.")

        other_roles_manage_count = session.scalar(
            select(func.count(func.distinct(Role.id)))
            .select_from(Role)
            .join(role_permissions, role_permissions.c.role_id == Role.id)
            .join(Permission, Permission.id == role_permissions.c.permission_id)
            .where(Role.id != role.id, Permission.code.in_(manage_codes))
        ) or 0
        if other_roles_manage_count == 0 and not (perm_codes & manage_codes):
            errors.append("At least one role must keep user management permission.")

        # Safety: do not let the current user remove their own ability to manage users/roles.
        try:
            current_db_user = session.get(User, str(getattr(current_user, "id", "")))
        except Exception:
            current_db_user = None
        if current_db_user and current_db_user.is_active:
            current_is_legacy_admin = (current_db_user.role or "").lower() == "admin"
            if not current_is_legacy_admin:
                current_role_ids = {r.id for r in current_db_user.roles}
                will_have_manage = False
                if role.id in current_role_ids:
                    if perm_codes & manage_codes:
                        will_have_manage = True
                for r in current_db_user.roles:
                    if r.id == role.id:
                        continue
                    if any(p.code in manage_codes for p in (r.permissions or [])):
                        will_have_manage = True
                        break
                if not will_have_manage:
                    errors.append("You cannot remove your own user-management access.")

        if errors:
            if wants_json:
                return jsonify({"success": False, "errors": errors}), 400
            permissions = session.execute(select(Permission).order_by(Permission.code)).unique().scalars().all()
            return render_template("admin/role_form.html", role=role, permissions=permissions, errors=errors), 200

        role.name = new_name
        role.description = description

        # Update role permissions using the association table directly.
        # This avoids ORM edge-cases and keeps the operation deterministic.
        session.execute(role_permissions.delete().where(role_permissions.c.role_id == role.id))
        effective_permission_ids: list[int] = []
        if permission_ids:
            effective_permission_ids = (
                session.execute(select(Permission.id).where(Permission.id.in_(permission_ids))).scalars().all()
            )
            if effective_permission_ids:
                session.execute(
                    role_permissions.insert(),
                    [{"role_id": role.id, "permission_id": pid} for pid in effective_permission_ids],
                )

        session.commit()

        if wants_json:
            effective_permissions: list[Permission] = []
            if effective_permission_ids:
                effective_permissions = (
                    session.execute(
                        select(Permission)
                        .where(Permission.id.in_(effective_permission_ids))
                        .order_by(Permission.code)
                    )
                    .unique()
                    .scalars()
                    .all()
                )
            return jsonify({
                "success": True,
                "role": {
                    "id": role.id,
                    "name": role.name,
                    "description": role.description,
                    "permissions": [{"id": p.id, "code": p.code, "name": p.code} for p in effective_permissions]
                }
            })
        flash("Role updated successfully.", "ok")
        return redirect(url_for("admin_settings.index"))
    except Exception as e:
        session.rollback()
        if wants_json:
            return jsonify({"success": False, "errors": [str(e)]}), 500
        permissions = session.execute(select(Permission).order_by(Permission.code)).unique().scalars().all()
        errors = ["Could not update role: " + str(e)]
        return render_template("admin/role_form.html", role=role if 'role' in locals() else None, permissions=permissions, errors=errors), 500
    finally:
        session.close()


@bp.route("/roles/<int:role_id>/delete", methods=["POST"])
@bp.route("/settings/roles/<int:role_id>/delete", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def delete_role(role_id: int):
    """Delete a role via AJAX."""
    session = db.session()
    try:
        # Validate CSRF token
        data = request.get_json() or {}
        ensure_csrf_token(data)

        role = session.get(Role, role_id)
        if not role:
            return jsonify({"success": False, "errors": ["Role not found"]}), 404

        assigned = session.scalar(
            select(func.count())
            .select_from(user_roles)
            .where(user_roles.c.role_id == role_id)
        )
        if assigned:
            return jsonify({"success": False, "errors": ["Role is assigned to users and cannot be deleted."]}), 400

        session.delete(role)
        session.commit()

        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        return jsonify({"success": False, "errors": [str(e)]}), 500
    finally:
        session.close()


@bp.route("/colors/update", methods=["POST"])
@bp.route("/settings/colors/update", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def update_color():
    """Create or update doctor color (and optional label) via AJAX."""
    try:
        # Validate CSRF token
        data = request.get_json()
        ensure_csrf_token(data)

        raw_id = data.get("doctor_id")
        original_id = data.get("original_id")
        color = data.get("color")
        doctor_label = (data.get("doctor_label") or "").strip()

        if not doctor_label:
            return jsonify({"success": False, "errors": ["Doctor name is required"]}), 400
        if not color:
            return jsonify({"success": False, "errors": ["Doctor color is required"]}), 400

        init_doctor_colors_table()

        # Normalize name for uniqueness
        normalized_name = doctor_label.lower()

        # Determine if edit or create
        doctor_id: str
        if original_id:
            doctor_id = slugify_doctor(str(original_id))
        elif raw_id:
            doctor_id = slugify_doctor(str(raw_id))
        else:
            doctor_id = ensure_unique_numeric_id()

        # Editing: block duplicate active name on a different doctor
        if original_id:
            if name_exists(normalized_name, exclude_id=doctor_id) or name_exists_any(normalized_name, exclude_id=doctor_id):
                return jsonify({"success": False, "errors": ["Doctor name already exists. Please choose another."]}), 400
        else:
            # Creating: block duplicates (active or deleted)
            if name_exists_any(normalized_name):
                return jsonify({"success": False, "errors": ["Doctor name already exists. Please choose another."]}), 400

        # Prevent overwriting another active record with same id
        existing = get_doctor_entry(doctor_id)
        is_edit = bool(original_id and existing)
        if existing and not is_edit and existing.get("is_active", 1):
            return jsonify({"success": False, "errors": ["Doctor ID already exists."]}), 400

        # Auto-generate a unique color for new doctors
        if not original_id and not raw_id:
            existing_colors = [doc["color"] for doc in get_all_doctors_with_colors()]
            color = generate_unique_color(existing_colors)

        set_doctor_color(doctor_id, color, doctor_label or doctor_id)

        return jsonify({"success": True, "doctor_id": doctor_id})
    except sqlite3.OperationalError as e:
        return jsonify({"success": False, "errors": [f"Doctor colors storage unavailable: {e}"]}), 500
    except Exception as e:
        return jsonify({"success": False, "errors": [str(e)]}), 500


@bp.route("/colors/reset", methods=["POST"])
@bp.route("/settings/colors/reset", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def reset_colors():
    """Reset all doctor colors to a neutral default; does not create doctors."""
    try:
        # Validate CSRF token
        data = request.get_json() or {}
        ensure_csrf_token(data)

        init_doctor_colors_table()
        doctors = get_all_doctors_with_colors()
        for doc in doctors:
            set_doctor_color(doc["doctor_id"], "#6B7280", doc["doctor_label"])

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "errors": [str(e)]}), 500


@bp.route("/colors/delete", methods=["POST"])
@bp.route("/settings/colors/delete", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def delete_color_entry():
    """Delete a doctor color entry (removes from new appointments; history unchanged)."""
    try:
        data = request.get_json() or {}
        ensure_csrf_token(data)
        raw_id = data.get("doctor_id")
        doctor_id = slugify_doctor(str(raw_id)) if raw_id else None
        if not doctor_id:
            return jsonify({"success": False, "errors": ["Doctor ID is required"]}), 400
        from clinic_app.services.doctor_colors import ANY_DOCTOR_ID
        if doctor_id == ANY_DOCTOR_ID:
            return jsonify({"success": False, "errors": ["Any Doctor cannot be deleted"]}), 400
        delete_doctor_color(doctor_id)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "errors": [str(e)]}), 500


@bp.route("/colors/deleted", methods=["GET"])
@bp.route("/settings/colors/deleted", methods=["GET"])
@require_permission("admin.user.manage")
def list_deleted_doctors():
    """List soft-deleted doctors."""
    try:
        deleted = get_deleted_doctors()
        return jsonify({"success": True, "deleted": deleted})
    except Exception as e:
        return jsonify({"success": False, "errors": [str(e)]}), 500


@bp.route("/colors/restore", methods=["POST"])
@bp.route("/settings/colors/restore", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def restore_doctor():
    """Restore a deleted doctor."""
    try:
        data = request.get_json() or {}
        ensure_csrf_token(data)
        doctor_id = slugify_doctor(str(data.get("doctor_id") or ""))
        if not doctor_id:
            return jsonify({"success": False, "errors": ["Doctor ID is required"]}), 400
        restore_doctor_color(doctor_id)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "errors": [str(e)]}), 500


@bp.route("/colors/purge", methods=["POST"])
@bp.route("/settings/colors/purge", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def purge_doctor():
    """Permanently remove a doctor from history (keeps id reserved)."""
    try:
        data = request.get_json() or {}
        ensure_csrf_token(data)
        doctor_id = slugify_doctor(str(data.get("doctor_id") or ""))
        if not doctor_id:
            return jsonify({"success": False, "errors": ["Doctor ID is required"]}), 400
        purge_doctor_color(doctor_id)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "errors": [str(e)]}), 500


# --- Theme Settings ---


def _valid_hex_color(value: str) -> bool:
    if not isinstance(value, str):
        return False
    value = value.strip()
    if len(value) not in (4, 7):
        return False
    if not value.startswith("#"):
        return False
    hex_part = value[1:]
    return all(c in "0123456789abcdefABCDEF" for c in hex_part)


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _data_root() -> Path:
    """Resolve the configured DATA_ROOT safely."""
    try:
        return Path(current_app.config.get("DATA_ROOT", "data"))
    except Exception:
        return Path("data")


def _current_logo_file() -> Path | None:
    """Return the current clinic logo file if it exists, else None."""
    root = _data_root()
    rel = get_setting("logo_path")
    if rel:
        candidate = root / rel
        if candidate.exists():
            return candidate
    auto = _auto_find_logo("logo")
    if auto:
        candidate = root / auto
        if candidate.exists():
            return candidate
    return None


def _logo_dir() -> Path:
    return _data_root() / "theme" / "logos"


def _ensure_logo_dir() -> Path:
    path = _logo_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _suggest_theme_colors_from_logo(logo_path: Path) -> tuple[str, str, str]:
    """Derive (primary, accent, brand) colors from a logo image.

    Kept intentionally simple and conservative: we pick the most frequent
    non-grey color and derive a lighter accent variant from it.
    """
    if Image is None:
        raise RuntimeError("Pillow is not installed. Install it to auto-pick colors from a logo.")
    try:
        img = Image.open(logo_path).convert("RGBA")
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError(f"Cannot open logo: {exc}")

    # Downscale to keep processing fast and robust
    img = img.resize((64, 64))
    colors = img.getcolors(64 * 64) or []

    def is_valid_color(r: int, g: int, b: int, a: int) -> bool:
        # Skip transparent and near-black / near-white
        if a < 40:
            return False
        brightness = (r + g + b) / 3.0
        if brightness < 20 or brightness > 245:
            return False
        # Skip very dull greys
        if max(abs(r - g), abs(r - b), abs(g - b)) < 12:
            return False
        return True

    candidates: list[tuple[int, tuple[int, int, int]]] = []
    for count, rgba in colors:
        r, g, b, a = rgba
        if is_valid_color(r, g, b, a):
            candidates.append((count, (r, g, b)))

    if not candidates:
        # Fallback to safe defaults
        return "#3b82f6", "#0ea5e9", "#d4a74a"

    # Most frequent candidate is our base brand color
    candidates.sort(key=lambda x: x[0], reverse=True)
    base_r, base_g, base_b = candidates[0][1]

    def to_hex(r: int, g: int, b: int) -> str:
        return f"#{r:02x}{g:02x}{b:02x}"

    # Brand color is the base color as-is
    brand_hex = to_hex(base_r, base_g, base_b)

    # Primary: slightly deepened version of the base color
    def adjust_contrast(r: int, g: int, b: int, factor: float) -> tuple[int, int, int]:
        # Move a bit away from mid-grey for better button contrast
        def _one(c: int) -> int:
            return int(_clamp(128 + (c - 128) * factor, 0, 255))

        return _one(r), _one(g), _one(b)

    primary_r, primary_g, primary_b = adjust_contrast(base_r, base_g, base_b, 1.2)
    primary_hex = to_hex(primary_r, primary_g, primary_b)

    # Accent: mix brand color with white for a lighter variant
    def mix_with_white(r: int, g: int, b: int, ratio: float) -> tuple[int, int, int]:
        return (
            int(_clamp(r + (255 - r) * ratio, 0, 255)),
            int(_clamp(g + (255 - g) * ratio, 0, 255)),
            int(_clamp(b + (255 - b) * ratio, 0, 255)),
        )

    accent_r, accent_g, accent_b = mix_with_white(base_r, base_g, base_b, 0.35)
    accent_hex = to_hex(accent_r, accent_g, accent_b)

    return primary_hex, accent_hex, brand_hex


def _save_logo_file(file) -> tuple[bool, str | list[str]]:
    """Save uploaded logo to history and set current logo path. Returns (ok, errors or rel_path)."""
    ext = Path(file.filename).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg"}:
        return False, ["Logo must be a PNG or JPG image."]

    # Enforce a simple size guard (max ~2MB)
    file.stream.seek(0, 2)
    size = file.stream.tell()
    file.stream.seek(0)
    if size and size > 2 * 1024 * 1024:
        return False, ["Logo is too large (max 2MB)."]

    dest_dir = _ensure_logo_dir()
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    history_name = f"logo-{ts}{ext}"
    history_path = dest_dir / history_name
    current_path = _data_root() / "theme" / f"logo-current{ext}"

    try:
        file.save(history_path)
        # Copy to current logo
        current_path.parent.mkdir(parents=True, exist_ok=True)
        current_path.write_bytes(history_path.read_bytes())
        # Store relative path for serving (use relative to DATA_ROOT)
        rel_path = os.path.relpath(current_path, _data_root())
        set_setting("logo_path", rel_path, category="logo")
        return True, rel_path
    except Exception as exc:
        return False, [str(exc)]


# PDF logo helpers
def _pdf_logo_dir() -> Path:
    return _data_root() / "theme" / "pdf_logos"


def _ensure_pdf_logo_dir() -> Path:
    path = _pdf_logo_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _auto_find_logo(kind: str = "logo") -> str | None:
    """
    Try to auto-detect an existing logo file if the setting is empty.
    kind: "logo" or "pdf-logo"
    """
    root = _data_root()
    candidates = []
    if kind == "logo":
        candidates = list(root.glob("theme/logo-current.*")) + list(root.glob("theme/logo.*"))
    else:
        candidates = list(root.glob("theme/pdf-logo-current.*")) + list(root.glob("theme/pdf-logo.*"))
    for path in candidates:
        if path.exists():
            try:
                return os.path.relpath(path, root)
            except Exception:
                return str(path)
    return None


def _save_pdf_logo_file(file) -> tuple[bool, str | list[str]]:
    """Save uploaded PDF logo to history and set current PDF logo path."""
    ext = Path(file.filename).suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg"}:
        return False, ["Logo must be a PNG or JPG image."]
    file.stream.seek(0, 2)
    size = file.stream.tell()
    file.stream.seek(0)
    if size and size > 2 * 1024 * 1024:
        return False, ["Logo is too large (max 2MB)."]

    dest_dir = _ensure_pdf_logo_dir()
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    history_name = f"pdf-logo-{ts}{ext}"
    history_path = dest_dir / history_name
    current_path = _data_root() / "theme" / f"pdf-logo-current{ext}"

    try:
        file.save(history_path)
        current_path.parent.mkdir(parents=True, exist_ok=True)
        current_path.write_bytes(history_path.read_bytes())
        rel_path = os.path.relpath(current_path, _data_root())
        set_setting("pdf_logo_path", rel_path, category="logo")
        return True, rel_path
    except Exception as exc:
        return False, [str(exc)]


def _list_logo_history(base: Path, prefix: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not base.exists():
        return items
    for path in sorted(base.glob(f"{prefix}-*.*")):
        label = path.stem.replace(f"{prefix}-", "")
        try:
            rel_str = os.path.relpath(path, _data_root())
        except Exception:
            rel_str = str(path.name)
        items.append({"label": label, "path": rel_str})
    return list(reversed(items))  # newest first


def _list_pdf_logo_history() -> list[dict[str, str]]:
    return _list_logo_history(_pdf_logo_dir(), "pdf-logo")


def _list_logo_history() -> list[dict[str, str]]:
    """List saved logos in history with label and path."""
    items: list[dict[str, str]] = []
    base = _logo_dir()
    if not base.exists():
        return items
    for path in sorted(base.glob("logo-*.*")):
        label = path.stem.replace("logo-", "")
        items.append({"label": label, "path": str(path.relative_to(_data_root()))})
    return list(reversed(items))  # newest first


@bp.route("/theme/update", methods=["POST"])
@bp.route("/settings/theme/update", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def update_theme_settings():
    """Save simple theme settings (primary, accent, text color, base font size)."""
    data = request.get_json() or {}
    ensure_csrf_token(data)

    scope = (data.get("scope") or "").lower()
    apply_colors = scope in {"", "all", "colors"}
    apply_branding = scope in {"", "all", "branding"}

    primary = (data.get("primary_color") or "").strip()
    accent = (data.get("accent_color") or "").strip()
    text_color = (data.get("text_color") or "").strip()
    btn_text_color = (data.get("btn_text_color") or "").strip()
    metric_text_color = (data.get("metric_text_color") or "").strip()
    page_bg_tint = (data.get("page_bg_tint") or "").strip()
    card_bg_tint = (data.get("card_bg_tint") or "").strip()
    base_size = (data.get("base_font_size") or "").strip()
    clinic_name = (data.get("clinic_name") or "").strip()
    clinic_name_enabled_raw = str(data.get("clinic_name_enabled") or "").lower()
    clinic_name_enabled = clinic_name_enabled_raw in {"1", "true", "yes", "on"}
    clinic_brand_color = (data.get("clinic_brand_color") or "").strip()
    clinic_tagline = (data.get("clinic_tagline") or "").strip()
    clinic_tagline_enabled_raw = str(data.get("clinic_tagline_enabled") or "").lower()
    clinic_tagline_enabled = clinic_tagline_enabled_raw in {"1", "true", "yes", "on"}
    logo_scale_raw = (data.get("logo_scale") or "").strip()

    def _normalize_white_hex(value: str, fallback: str) -> str:
        """Prevent users from picking a 100% white primary/accent which makes UI invisible."""
        s = (value or "").strip().lower()
        if s in {"#fff", "#ffffff"}:
            return fallback
        return value

    if apply_colors:
        # Gently nudge pure-white primaries/accents to a very light grey so buttons stay visible.
        primary = _normalize_white_hex(primary, "#f3f4f6")
        accent = _normalize_white_hex(accent, "#f3f4f6")

    errors = []
    if apply_colors:
        if primary and not _valid_hex_color(primary):
            errors.append("Primary color must be hex (e.g., #3b82f6).")
        if accent and not _valid_hex_color(accent):
            errors.append("Accent color must be hex (e.g., #0ea5e9).")
        if text_color and not _valid_hex_color(text_color):
            errors.append("Text color must be hex (e.g., #111827).")
        if btn_text_color and not _valid_hex_color(btn_text_color):
            errors.append("Button text color must be hex (e.g., #ffffff).")
        if metric_text_color and not _valid_hex_color(metric_text_color):
            errors.append("Highlight numbers color must be hex (e.g., #2563eb).")
        if page_bg_tint and not _valid_hex_color(page_bg_tint):
            errors.append("Page background tint must be hex (e.g., #f7f7f8).")
        if card_bg_tint and not _valid_hex_color(card_bg_tint):
            errors.append("Card background tint must be hex (e.g., #ffffff).")
        if base_size:
            try:
                size_val = int(base_size)
                if size_val < 14 or size_val > 18:
                    errors.append("Base font size must be between 14 and 18.")
            except ValueError:
                errors.append("Base font size must be a number.")
    if apply_branding:
        if clinic_brand_color and not _valid_hex_color(clinic_brand_color):
            errors.append("Brand color must be hex (e.g., #d4a74a).")
        if logo_scale_raw:
            try:
                scale_val = int(float(logo_scale_raw))
                if scale_val < 60 or scale_val > 140:
                    errors.append("Logo size must be between 60 and 140.")
            except ValueError:
                errors.append("Logo size must be a number.")

    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    if apply_colors:
        if primary:
            set_setting("primary_color", primary, category="colors")
        if accent:
            set_setting("accent_color", accent, category="colors")
        if text_color:
            set_setting("text_color", text_color, category="colors")
        if btn_text_color:
            set_setting("btn_text_color", btn_text_color, category="colors")
        if metric_text_color:
            set_setting("metric_text_color", metric_text_color, category="colors")
        if page_bg_tint:
            set_setting("page_bg_tint", page_bg_tint, category="colors")
        if card_bg_tint:
            set_setting("card_bg_tint", card_bg_tint, category="colors")
        if base_size:
            set_setting("base_font_size", str(base_size), category="typography")

    if apply_branding:
        set_setting("clinic_name", clinic_name, category="branding")
        set_setting("clinic_name_enabled", "1" if clinic_name_enabled else "0", category="branding")
        if clinic_brand_color:
            set_setting("clinic_brand_color", clinic_brand_color, category="branding")
        else:
            set_setting("clinic_brand_color", "", category="branding")
        set_setting("clinic_tagline", clinic_tagline, category="branding")
        set_setting("clinic_tagline_enabled", "1" if clinic_tagline_enabled else "0", category="branding")
        if logo_scale_raw:
            # Clamp to guardrails 60–140
            try:
                scale_val = int(float(logo_scale_raw))
                scale_val = max(60, min(scale_val, 140))
                set_setting("logo_scale", str(scale_val), category="branding")
            except Exception:
                set_setting("logo_scale", "100", category="branding")

    return jsonify({"success": True})


@bp.route("/theme/colors/from_logo", methods=["POST"])
@require_permission("admin.user.manage")
def theme_colors_from_logo():
    """Suggest theme colors based on the current clinic logo.

    This does **not** save any settings; it only returns a suggestion
    so the admin can review and then click the existing save buttons.
    """
    data = request.get_json() or {}
    ensure_csrf_token(data)

    logo_file = _current_logo_file()
    if not logo_file:
        return jsonify({"success": False, "errors": ["No clinic logo found. Please upload a logo first."]}), 400

    try:
        primary_hex, accent_hex, brand_hex = _suggest_theme_colors_from_logo(logo_file)
    except Exception as exc:  # pragma: no cover - defensive
        return jsonify({"success": False, "errors": [f"Could not analyse logo: {exc}"]}), 500

    return jsonify(
        {
            "success": True,
            "primary_color": primary_hex,
            "accent_color": accent_hex,
            "clinic_brand_color": brand_hex,
        }
    )


@bp.route("/theme/logo", methods=["GET"])
def theme_logo():
    """Serve the uploaded clinic logo if present."""
    logo_rel = get_setting("logo_path")
    if not logo_rel:
        abort(404)
    logo_path = _data_root() / logo_rel
    if not logo_path.exists():
        # Clear stale setting so UI shows "no logo" again
        set_setting("logo_path", "", category="logo")
        abort(404)
    return send_file(logo_path)


@bp.route("/theme/pdf_logo", methods=["GET"])
def theme_pdf_logo():
    """Serve the uploaded PDF logo if present."""
    logo_rel = get_setting("pdf_logo_path")
    root = _data_root()

    def _resolve_logo(rel: str | None) -> Path | None:
        if not rel:
            return None
        cand = Path(rel)
        if cand.is_absolute():
            return cand if cand.exists() else None
        norm = Path(rel.replace("\\", "/"))
        full = root / norm
        return full if full.exists() else None

    logo_path = _resolve_logo(logo_rel)

    if not logo_path:
        # Try to auto-detect a recently uploaded PDF logo
        auto = _auto_find_logo("pdf-logo")
        logo_path = _resolve_logo(auto)
        if auto and logo_path:
            set_setting("pdf_logo_path", auto, category="logo")

    if not logo_path:
        # Clear stale setting so UI shows "no logo" again
        set_setting("pdf_logo_path", "", category="logo")
        abort(404)

    return send_file(logo_path)


@bp.route("/theme/logo/upload", methods=["POST"])
@require_permission("admin.user.manage")
def upload_logo():
    """Upload a clinic logo and store its relative path in theme settings."""
    try:
        file = request.files.get("logo")
        if not file or not file.filename:
            return jsonify({"success": False, "errors": ["No file uploaded."]}), 400

        ok, res = _save_logo_file(file)
        if not ok:
            return jsonify({"success": False, "errors": res}), 400

        return jsonify(
            {
                "success": True,
                "logo_url": url_for("admin_settings.theme_logo", _ts=int(datetime.utcnow().timestamp())),
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "errors": [str(exc)]}), 500


@bp.route("/theme/logo/reset", methods=["POST"])
@require_permission("admin.user.manage")
def reset_logo():
    """Clear current logo setting (keeps files)."""
    set_setting("logo_path", "", category="logo")
    return jsonify({"success": True})


@bp.route("/theme/logo/select", methods=["POST"])
@require_permission("admin.user.manage")
def select_logo():
    """Switch to a previously uploaded logo from history."""
    data = request.get_json() or {}
    ensure_csrf_token(data)
    rel_path = (data.get("logo_path") or "").strip()
    if not rel_path:
        return jsonify({"success": False, "errors": ["No logo selected."]}), 400

    source = _data_root() / rel_path
    if not source.exists():
        return jsonify({"success": False, "errors": ["Selected logo not found."]}), 404

    ext = source.suffix.lower()
    current_path = _data_root() / "theme" / f"logo-current{ext}"
    try:
        current_path.parent.mkdir(parents=True, exist_ok=True)
        current_path.write_bytes(source.read_bytes())
        rel = os.path.relpath(current_path, _data_root())
        set_setting("logo_path", rel, category="logo")
        return jsonify(
            {
                "success": True,
                "logo_url": url_for("admin_settings.theme_logo", _ts=int(datetime.utcnow().timestamp())),
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "errors": [str(exc)]}), 500


@bp.route("/theme/reset", methods=["POST"])
@require_permission("admin.user.manage")
def reset_theme_defaults():
    """
    Reset **color** theme settings to defaults only:
    - Reset primary/accent colors
    - Reset text color
    - Reset button text color (auto-contrast)
    - Reset base font size

    Branding (clinic name, tagline, logo, scale) is not changed here.
    """
    try:
        set_setting("primary_color", "#3b82f6", category="colors")
        set_setting("accent_color", "#0ea5e9", category="colors")
        set_setting("text_color", "#111827", category="colors")
        set_setting("btn_text_color", "", category="colors")
        set_setting("base_font_size", "16", category="typography")
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"success": False, "errors": [str(exc)]}), 500


@bp.route("/theme/logo/history", methods=["GET"])
@require_permission("admin.user.manage")
def logo_history():
    """Return list of past logos (newest first)."""
    try:
        history = _list_logo_history(_ensure_logo_dir(), "logo")
    except Exception:
        history = []
    return jsonify({"success": True, "logo_history": history})


# PDF logo endpoints
@bp.route("/theme/pdf_logo/upload", methods=["POST"])
@require_permission("admin.user.manage")
def upload_pdf_logo():
    """Upload a PDF-specific clinic logo."""
    try:
        file = request.files.get("logo")
        if not file or not file.filename:
            return jsonify({"success": False, "errors": ["No file uploaded."]}), 400

        ok, res = _save_pdf_logo_file(file)
        if not ok:
            return jsonify({"success": False, "errors": res}), 400

        return jsonify(
            {
                "success": True,
                "logo_url": url_for("admin_settings.theme_pdf_logo", _ts=int(datetime.utcnow().timestamp())),
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "errors": [str(exc)]}), 500


@bp.route("/theme/pdf_logo/reset", methods=["POST"])
@require_permission("admin.user.manage")
def reset_pdf_logo():
    """Clear PDF logo setting (keeps files)."""
    set_setting("pdf_logo_path", "", category="logo")
    return jsonify({"success": True})


@bp.route("/theme/pdf_logo/select", methods=["POST"])
@require_permission("admin.user.manage")
def select_pdf_logo():
    data = request.get_json() or {}
    ensure_csrf_token(data)
    rel_path = (data.get("logo_path") or "").strip()
    if not rel_path:
        return jsonify({"success": False, "errors": ["No logo selected."]}), 400

    source = _data_root() / rel_path
    if not source.exists():
        return jsonify({"success": False, "errors": ["Selected logo not found."]}), 404

    ext = source.suffix.lower()
    current_path = _data_root() / "theme" / f"pdf-logo-current{ext}"
    try:
        current_path.parent.mkdir(parents=True, exist_ok=True)
        current_path.write_bytes(source.read_bytes())
        rel = os.path.relpath(current_path, _data_root())
        set_setting("pdf_logo_path", rel, category="logo")
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"success": False, "errors": [str(exc)]}), 500


@bp.route("/theme/pdf_logo/history", methods=["GET"])
@require_permission("admin.user.manage")
def pdf_logo_history():
    try:
        history = _list_pdf_logo_history()
    except Exception:
        history = []
    return jsonify({"success": True, "logo_history": history})


@bp.route("/settings/data-import/first-stable/preview", methods=["POST"])
@require_permission("admin.user.manage")
def preview_first_stable_import():
    """
    Preview an uploaded Excel/CSV file without writing to the DB.

    The frontend uses multipart/form-data when a user uploads a file.
    """
    # CSRF validation for both JSON and multipart form requests.
    if request.content_type and request.content_type.startswith("multipart/"):
        data = {"csrf_token": request.form.get("csrf_token") or request.headers.get("X-CSRFToken")}
    else:
        data = request.get_json() or {}
    ensure_csrf_token(data)

    upload = request.files.get("excel_file")
    analyze_mode = (request.form.get("analyze_mode") or "").strip().lower()
    if analyze_mode not in {"safe", "normal", "aggressive"}:
        analyze_mode = "safe"

    if not upload or not upload.filename:
        return (
            jsonify({"success": False, "errors": [T("data_import_file_required")]}),
            400,
        )

    # Use an uploaded Excel/CSV file – save to a temporary location outside
    # the app's data folder, analyse it, then remove the temp file.
    import tempfile
    import os

    suffix = Path(upload.filename).suffix or ".xlsx"
    suffix_lower = suffix.lower()
    if suffix_lower not in {".xlsx", ".xlsm", ".csv"}:
        return (
            jsonify(
                {
                    "success": False,
                    "errors": [T("data_import_unsupported_file")],
                }
            ),
            400,
        )
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = Path(tmp.name)
    try:
        upload.save(tmp_path)
        if suffix_lower == ".csv":
            preview = analyze_import_csv_template(tmp_path, max_preview_rows=10000, mode=analyze_mode)
        else:
            preview = analyze_first_stable_excel(tmp_path, max_preview_rows=10000, mode=analyze_mode)
    except FileNotFoundError:
        return (
            jsonify(
                {
                    "success": False,
                    "errors": [T("data_import_file_not_found")],
                }
            ),
            404,
        )
    except Exception as exc:
        # Common case: old binary .xls or invalid files (not a zip workbook).
        msg = str(exc) or ""
        if "File is not a zip file" in msg or "BadZipFile" in msg:
            return (
                jsonify(
                    {
                        "success": False,
                        "errors": [T("data_import_unsupported_file")],
                    }
                ),
                400,
            )
        return jsonify({"success": False, "errors": [str(exc)]}), 500
    finally:
        try:
            tmp.close()
        except Exception:
            pass
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    counts = preview.get("counts") or {}
    rows = preview.get("rows") or []
    duplicates = preview.get("duplicates") or []
    duplicates_aggressive = preview.get("duplicates_aggressive") or []

    # IMPORTANT: in the UI, "Patients" should mean unique patient files in this preview.
    # The analyzers may count differently depending on the source file, so we normalize here.
    total_rows = int(counts.get("total_rows") or 0)
    payment_rows = int(counts.get("payments") or 0)
    unique_patients = len(rows)
    counts["patients"] = unique_patients
    counts["payment_rows"] = payment_rows

    parts = []
    if total_rows:
        parts.append(f"{T('data_import_total_rows')}: {total_rows}")
    if unique_patients:
        parts.append(f"{T('patients')}: {unique_patients}")
    if payment_rows:
        parts.append(f"{T('data_import_payment_rows')}: {payment_rows}")

    message = " • ".join(parts) if parts else T("data_import_preview_ok")

    return jsonify(
        {
            "success": True,
            "message": message,
            "counts": counts,
            "rows": rows,
            "duplicates": duplicates,
            "duplicates_aggressive": duplicates_aggressive,
        }
    )


@bp.route("/settings/data-import/template.csv", methods=["GET"])
@require_permission("admin.user.manage")
def download_import_template():
    """
    Download a simple CSV template other clinics can fill with their data.

    This does not depend on the legacy Excel structure and is intended as the
    long-term, clinic-friendly import format.
    """
    import csv

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "file_number",
            "page_number",
            "full_name",
            "phone",
            "date",
            "total_amount",
            "paid_today",
            "remaining",
            "visit_type",
            "treatment_type",
            "notes",
            # Optional columns
            "method",
            "discount",
            "doctor_label",
        ]
    )
    # Provide a single example row as a hint (comment-style).
    writer.writerow(
        [
            "P000123",
            "12",
            "Omar Ahmed",
            "01234567890",
            "2025-01-15",
            "1000.00",
            "300.00",
            "700.00",
            "exam",
            "Root canal",
            "Root canal treatment",
            "cash",
            "0.00",
            "Any Doctor",
        ]
    )
    buf.seek(0)

    return send_file(
        io.BytesIO(buf.read().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name="clinic-import-template.csv",
    )


@bp.route("/settings/data-export/payments.csv", methods=["GET"])
@require_permission("admin.user.manage")
def export_payments_csv():
    """Export all payments (oldest first) for clinic-wide Excel review."""
    import csv

    conn = db_sqlite()
    # We prefer all page numbers from patient_pages; if that table is empty/missing,
    # fall back to patients.primary_page_number when available.
    has_patient_pages = False
    try:
        has_patient_pages = (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='patient_pages' LIMIT 1"
            ).fetchone()
            is not None
        )
    except Exception:
        has_patient_pages = False

    has_primary_page_number = False
    try:
        has_primary_page_number = (
            conn.execute("SELECT 1 FROM pragma_table_info('patients') WHERE name='primary_page_number' LIMIT 1")
            .fetchone()
            is not None
        )
    except Exception:
        has_primary_page_number = False

    if has_patient_pages:
        pages_expr = """
        (
          SELECT GROUP_CONCAT(page_number, ', ')
            FROM (SELECT page_number
                    FROM patient_pages
                   WHERE patient_id = p.id
                   ORDER BY page_number)
        )
        """
    else:
        pages_expr = "NULL"

    if has_primary_page_number:
        page_numbers_expr = f"COALESCE({pages_expr}, p.primary_page_number, '')"
    else:
        page_numbers_expr = f"COALESCE({pages_expr}, '')"

    rows = conn.execute(
        f"""
      SELECT pay.id, p.short_id, p.full_name, p.phone,
             {page_numbers_expr} AS page_numbers,
             pay.paid_at, pay.amount_cents, pay.method, pay.note,
             pay.treatment, pay.remaining_cents, pay.total_amount_cents,
             pay.examination_flag, pay.followup_flag, pay.discount_cents,
             pay.doctor_id, pay.doctor_label
      FROM payments pay JOIN patients p ON p.id = pay.patient_id
      ORDER BY pay.paid_at IS NULL, pay.paid_at ASC
    """,
    ).fetchall()
    conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "file_number",
            "page_number",
            "full_name",
            "phone",
            "date",
            "total_amount",
            "paid_today",
            "remaining",
            "visit_type",
            "treatment_type",
            "notes",
            # Optional columns (safe to ignore on import)
            "method",
            "discount",
            "doctor_label",
            "payment_id",
        ]
    )
    for row in rows:
        total_cents = row["total_amount_cents"] or 0
        discount_cents = row["discount_cents"] or 0
        paid_cents = row["amount_cents"] or 0
        remaining_cents = row["remaining_cents"]
        if remaining_cents is None:
            remaining_cents = max(total_cents - discount_cents - paid_cents, 0)
        visit_type = "exam" if (row["examination_flag"] or 0) == 1 else ("followup" if (row["followup_flag"] or 0) == 1 else "")
        writer.writerow(
            [
                row["short_id"] or "",
                row["page_numbers"] or "",
                row["full_name"],
                row["phone"] or "",
                row["paid_at"] or "",
                money(total_cents),
                money(paid_cents),
                money(int(remaining_cents or 0)),
                visit_type,
                row["treatment"] or "",
                row["note"] or "",
                row["method"] or "",
                money(discount_cents),
                row["doctor_label"] or ANY_DOCTOR_LABEL,
                row["id"],
            ]
        )
    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    return send_file(
        io.BytesIO(buf.read().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"clinic-payments-{ts}.csv",
    )


def _db_file_path() -> Path:
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if isinstance(uri, str) and uri.startswith("sqlite:///"):
        return Path(uri.replace("sqlite:///", ""))
    raise RuntimeError("Only sqlite databases are supported for import/export.")


def _main_db_path() -> Path:
    data_root = Path(current_app.config["DATA_ROOT"])
    return data_root / "app.db"


def _create_db_backup() -> Path:
    db_path = _db_file_path()
    backup_dir = Path(current_app.config["DATA_ROOT"]) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"app-{ts}.db"

    # Use SQLite's backup API instead of copying the file, because Windows can
    # lock open database files during runtime.
    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(backup_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return backup_path


def _patient_pages_table_exists(conn: sqlite3.Connection) -> bool:
    try:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='patient_pages' LIMIT 1"
            ).fetchone()
            is not None
        )
    except Exception:
        return False


def _patients_primary_page_column_exists(conn: sqlite3.Connection) -> bool:
    try:
        return (
            conn.execute(
                "SELECT 1 FROM pragma_table_info('patients') WHERE name='primary_page_number' LIMIT 1"
            ).fetchone()
            is not None
        )
    except Exception:
        return False


def _split_page_numbers(raw: str) -> list[str]:
    txt = (raw or "").strip()
    if not txt:
        return []
    # Keep as simple tokens; do not expand ranges automatically.
    parts = [p.strip() for p in txt.replace("،", ",").split(",")]
    return [p for p in parts if p]

def _first_page_number_token(raw: str) -> str:
    """Best-effort: return the first numeric page token (normalised), for identity matching.

    This keeps "45-46" and "45" aligned, and normalises Arabic-Indic digits.
    """
    txt = (raw or "").strip()
    if not txt:
        return ""
    txt = txt.translate(
        str.maketrans(
            {
                "٠": "0",
                "١": "1",
                "٢": "2",
                "٣": "3",
                "٤": "4",
                "٥": "5",
                "٦": "6",
                "٧": "7",
                "٨": "8",
                "٩": "9",
            }
        )
    )
    m = re.search(r"(\d+)", txt)
    if not m:
        return ""
    digits = (m.group(1) or "").lstrip("0")
    return digits or "0"

def _normalize_file_number_token(raw: str) -> str:
    txt = (raw or "").strip()
    if not txt:
        return ""
    digits = "".join(ch for ch in txt if ch.isdigit())
    if not digits:
        return ""
    digits = digits.lstrip("0")
    return digits or "0"


def _admin_setting_bool(conn: sqlite3.Connection, key: str, default: bool) -> bool:
    try:
        row = conn.execute(
            "SELECT setting_value FROM admin_settings WHERE setting_key=? LIMIT 1",
            (key,),
        ).fetchone()
        if not row:
            return default
        try:
            raw = row["setting_value"]
        except Exception:
            raw = row[0]
        val = (str(raw or "").strip().lower())
        if val in {"1", "true", "yes", "on"}:
            return True
        if val in {"0", "false", "no", "off"}:
            return False
        return default
    except Exception:
        return default

def _normalize_db_name(raw: str) -> str:
    return " ".join((raw or "").split()).strip().lower()


def _first_two_tokens(raw: str) -> str:
    parts = [p for p in (raw or "").split(" ") if p]
    return " ".join(parts[:2])


def _normalize_db_phone(raw: str) -> str:
    return "".join(ch for ch in (raw or "") if ch.isdigit())


def _db_duplicate_groups(
    mode: str = "safe",
    *,
    restrict_to_patient_ids: set[str] | None = None,
) -> list[dict[str, object]]:
    """Find possible duplicate patients inside the clinic database.

    Safe mode:
      - same first + second name, AND
      - phone matches OR at least one phone is missing.

    Normal mode:
      - same first + second name, AND
      - phone matches OR page number matches OR at least one phone is missing.

    Aggressive mode:
      - same first + second name only.

    This does not merge anything; it only returns suggestions for review.
    """
    mode = (mode or "safe").strip().lower()
    if mode not in {"safe", "normal", "aggressive"}:
        mode = "safe"
    aggressive = mode == "aggressive"
    conn = db_sqlite()
    try:
        has_primary = _patients_primary_page_column_exists(conn)
        cols = "id, short_id, full_name, phone"
        if has_primary:
            cols += ", primary_page_number"
        rows = conn.execute(f"SELECT {cols} FROM patients ORDER BY full_name").fetchall()
    finally:
        conn.close()

    groups: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        name_norm = _normalize_db_name(r["full_name"] or "")
        first_two = _first_two_tokens(name_norm)
        if not first_two:
            continue
        cand = {
            "id": r["id"],
            "short_id": r["short_id"] or "",
            "full_name": r["full_name"] or "",
            "phone": r["phone"] or "",
            "primary_page_number": (r["primary_page_number"] or "") if has_primary else "",
            "phone_norm": _normalize_db_phone(r["phone"] or ""),
        }
        groups.setdefault(first_two, []).append(cand)

    results: list[dict[str, object]] = []
    for first_two, cands in groups.items():
        if len(cands) < 2:
            continue

        if aggressive:
            ok = True
        else:
            phone_counts: dict[str, int] = {}
            missing_phone = False
            page_counts: dict[str, int] = {}
            for c in cands:
                ph = c.get("phone_norm") or ""
                if not ph:
                    missing_phone = True
                else:
                    phone_counts[ph] = phone_counts.get(ph, 0) + 1
                if mode == "normal":
                    pg = (c.get("primary_page_number") or "").strip()
                    if pg:
                        page_counts[pg] = page_counts.get(pg, 0) + 1
            duplicates_same_phone = any(n >= 2 for n in phone_counts.values())
            duplicates_same_page = any(n >= 2 for n in page_counts.values()) if mode == "normal" else False
            ok = duplicates_same_phone or duplicates_same_page or missing_phone

        if not ok:
            continue

        if restrict_to_patient_ids is not None:
            any_in_scope = any((c.get("id") or "") in restrict_to_patient_ids for c in cands)
            if not any_in_scope:
                continue

        results.append(
            {
                "first_two_name": first_two,
                "display_name": cands[0].get("full_name") or first_two,
                "candidates": [
                    {
                        "id": c["id"],
                        "short_id": c["short_id"],
                        "full_name": c["full_name"],
                        "phone": c["phone"],
                        "primary_page_number": c.get("primary_page_number", ""),
                    }
                    for c in cands
                ],
            }
        )

    return results


@bp.route("/settings/data-import/report/<name>/duplicates-db", methods=["GET"])
@require_permission("admin.user.manage")
def data_import_report_duplicates_db(name: str):
    """Return possible duplicates that involve patients from a given import report."""
    mode = (request.args.get("mode") or "").strip().lower()
    aggressive_flag = (request.args.get("aggressive") or "").strip().lower() in {"1", "true", "yes", "on"}
    if aggressive_flag:
        mode = "aggressive"
    if mode not in {"safe", "normal", "aggressive"}:
        mode = "safe"
    report = _load_import_report(name)
    if not report:
        return jsonify({"success": False, "errors": [T("data_import_report_not_found")]}), 404

    ids_raw = report.get("patient_ids_in_file") if isinstance(report, dict) else None
    if not isinstance(ids_raw, list) or not ids_raw:
        return jsonify({"success": True, "duplicates": []})

    restrict_ids = {str(x) for x in ids_raw if str(x).strip()}
    try:
        duplicates = _db_duplicate_groups(mode=mode, restrict_to_patient_ids=restrict_ids)
        return jsonify({"success": True, "duplicates": duplicates})
    except Exception as exc:
        return jsonify({"success": False, "errors": [str(exc)]}), 500


def _load_import_report(name: str) -> dict[str, object] | None:
    safe = (name or "").strip()
    if not safe or "/" in safe or "\\" in safe:
        return None
    report_path = Path(current_app.config["DATA_ROOT"]) / "import_reports" / safe
    if not report_path.exists():
        return None
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _merge_patient_pages_for_merge(conn: sqlite3.Connection, *, source_id: str, target_id: str) -> None:
    """Move page numbers from source to target (best-effort), then delete source page rows."""
    if not _patient_pages_table_exists(conn):
        return
    try:
        rows = conn.execute(
            "SELECT page_number, notebook_name FROM patient_pages WHERE patient_id=?",
            (source_id,),
        ).fetchall()
    except Exception:
        rows = []

    for r in rows:
        page_number = (r["page_number"] or "").strip()
        if not page_number:
            continue
        exists = conn.execute(
            "SELECT 1 FROM patient_pages WHERE patient_id=? AND page_number=? LIMIT 1",
            (target_id, page_number),
        ).fetchone()
        if exists:
            continue
        try:
            conn.execute(
                "INSERT INTO patient_pages (id, patient_id, page_number, notebook_name) VALUES (?, ?, ?, ?)",
                (str(uuid4()), target_id, page_number, r["notebook_name"]),
            )
        except Exception:
            continue

    try:
        conn.execute("DELETE FROM patient_pages WHERE patient_id=?", (source_id,))
    except Exception:
        pass


@bp.route("/settings/data-import/duplicates-db/merge", methods=["POST"])
@require_permission("admin.user.manage")
def merge_db_duplicate_patients():
    """Merge two patient files from the Admin 'database duplicates' panel."""
    data = request.get_json() or {}
    ensure_csrf_token(data)

    source_id = (data.get("source_id") or "").strip()
    target_id = (data.get("target_id") or "").strip()
    merge_diag_flag = _bool_from_value(data.get("merge_diag", False))

    if not source_id or not target_id:
        return jsonify({"success": False, "errors": [T("merge_conflict")]}), 400
    if source_id == target_id:
        return jsonify({"success": False, "errors": [T("merge_same_patient")]}), 400

    conn = db_sqlite()
    cur = conn.cursor()
    try:
        src = cur.execute(
            "SELECT id, short_id, full_name, phone FROM patients WHERE id=?",
            (source_id,),
        ).fetchone()
        tgt = cur.execute(
            "SELECT id, short_id, full_name, phone FROM patients WHERE id=?",
            (target_id,),
        ).fetchone()
        if not src or not tgt:
            return jsonify({"success": False, "errors": [T("merge_conflict")]}), 404

        try:
            merge_patient_records(conn, dict(src), dict(tgt), merge_diag=merge_diag_flag)

            # Move page numbers (always) so notebook links don't get lost.
            _merge_patient_pages_for_merge(conn, source_id=source_id, target_id=target_id)

            # If target has no primary page number but source does, keep it.
            try:
                if _patients_primary_page_column_exists(conn):
                    tgt_page = conn.execute(
                        "SELECT primary_page_number FROM patients WHERE id=?",
                        (target_id,),
                    ).fetchone()
                    src_page = conn.execute(
                        "SELECT primary_page_number FROM patients WHERE id=?",
                        (source_id,),
                    ).fetchone()
                    if tgt_page and src_page:
                        if not (tgt_page["primary_page_number"] or "").strip() and (src_page["primary_page_number"] or "").strip():
                            conn.execute(
                                "UPDATE patients SET primary_page_number=? WHERE id=?",
                                (src_page["primary_page_number"], target_id),
                            )
            except Exception:
                pass

            # After a successful merge, remove any remaining diagnosis/medical rows
            # for the source (if they were not moved) and delete the source patient.
            for tbl in ("diagnosis", "diagnosis_event", "medical", "medical_event"):
                try:
                    cur.execute(f"DELETE FROM {tbl} WHERE patient_id=?", (source_id,))
                except Exception:
                    continue
            cur.execute("DELETE FROM patients WHERE id=?", (source_id,))
            conn.commit()
        except MergeConflict as mc:
            conn.rollback()
            if mc.code == "target_has_diagnosis":
                return jsonify({"success": False, "errors": [T("merge_target_has_diag")]}), 400
            return jsonify({"success": False, "errors": [T("merge_conflict")]}), 400
        except Exception:
            conn.rollback()
            return jsonify({"success": False, "errors": [T("merge_unexpected_error")]}), 500

        return jsonify({"success": True, "message": T("db_dup_merge_ok")})
    finally:
        conn.close()


def _resolve_patient_for_import(
    conn: sqlite3.Connection,
    *,
    source_kind: str,
    file_number: str,
    page_number: str,
    full_name: str,
    phone: str,
    never_auto_merge: bool = False,
    merge_mode: str = "safe",
) -> tuple[str, bool, bool]:
    """Return (patient_id, created, file_number_collision)."""
    file_number = (file_number or "").strip()
    page_number = (page_number or "").strip()
    full_name = (full_name or "").strip()
    phone = (phone or "").strip()
    mode = (merge_mode or "safe").strip().lower()
    if mode not in {"safe", "normal"}:
        mode = "safe"

    # 1) Prefer exact file number match when present (CSV export/template).
    if file_number:
        row = conn.execute("SELECT id FROM patients WHERE short_id=? LIMIT 1", (file_number,)).fetchone()
        if row:
            return row["id"], False, False

    # 2) Otherwise, only match by page number when we can strongly confirm
    # it's the same patient. In notebook-based clinics, page numbers are NOT
    # guaranteed unique, so matching by page alone can incorrectly merge patients.
    pages = _split_page_numbers(page_number)
    phone_norm = "".join(ch for ch in phone if ch.isdigit())
    name_norm = " ".join(full_name.split()).strip().lower()
    strong_match_possible = bool(name_norm and (phone_norm or mode == "normal"))

    if (not never_auto_merge) and pages and strong_match_possible:
        # Try primary_page_number (single) match.
        if _patients_primary_page_column_exists(conn):
            row = conn.execute(
                """
                SELECT id, full_name, phone
                  FROM patients
                 WHERE primary_page_number=?
                 LIMIT 1
                """,
                (pages[0],),
            ).fetchone()
            if row:
                db_name = " ".join((row["full_name"] or "").split()).strip().lower()
                db_phone = "".join(ch for ch in (row["phone"] or "") if ch.isdigit())
                if db_name == name_norm:
                    if mode == "normal":
                        return row["id"], False, False
                    phone_ok = (phone_norm and db_phone and phone_norm == db_phone) or (not phone_norm) or (not db_phone)
                    if phone_ok:
                        return row["id"], False, False

        # Try patient_pages match.
        if _patient_pages_table_exists(conn):
            row = conn.execute(
                """
                SELECT p.id, p.full_name, p.phone
                  FROM patient_pages pg
                  JOIN patients p ON p.id = pg.patient_id
                 WHERE pg.page_number=?
                 LIMIT 1
                """,
                (pages[0],),
            ).fetchone()
            if row:
                db_name = " ".join((row["full_name"] or "").split()).strip().lower()
                db_phone = "".join(ch for ch in (row["phone"] or "") if ch.isdigit())
                if db_name == name_norm:
                    if mode == "normal":
                        return row["id"], False, False
                    phone_ok = (phone_norm and db_phone and phone_norm == db_phone) or (not phone_norm) or (not db_phone)
                    if phone_ok:
                        return row["id"], False, False

    # 3) Create new patient
    patient_id = str(uuid4())

    file_number_collision = False
    if file_number:
        # Use provided file number if free; otherwise auto-generate and report collision.
        exists = conn.execute("SELECT 1 FROM patients WHERE short_id=? LIMIT 1", (file_number,)).fetchone()
        if exists:
            file_number_collision = True
            file_number = next_short_id(conn)
    else:
        file_number = next_short_id(conn)

    if _patients_primary_page_column_exists(conn):
        primary_page = pages[0] if pages else None
        conn.execute(
            """
            INSERT INTO patients (id, short_id, full_name, phone, notes, primary_page_number)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (patient_id, file_number, full_name or file_number, phone or None, "", primary_page),
        )
    else:
        conn.execute(
            "INSERT INTO patients (id, short_id, full_name, phone, notes) VALUES (?, ?, ?, ?, ?)",
            (patient_id, file_number, full_name or file_number, phone or None, ""),
        )

    # Add additional page numbers if table exists.
    if pages and _patient_pages_table_exists(conn):
        for pg in pages:
            try:
                existing = conn.execute(
                    "SELECT 1 FROM patient_pages WHERE patient_id=? AND page_number=? LIMIT 1",
                    (patient_id, pg),
                ).fetchone()
                if existing:
                    continue
                conn.execute(
                    """
                    INSERT OR IGNORE INTO patient_pages (id, patient_id, page_number, notebook_name)
                    VALUES (?, ?, ?, ?)
                    """,
                    (str(uuid4()), patient_id, pg, None),
                )
            except Exception:
                # Ignore page insertion errors; they should not block payments import.
                continue

    return patient_id, True, file_number_collision


def _record_page_conflict(
    conflicts: list[dict[str, str]],
    *,
    page_number: str,
    incoming_name: str,
    incoming_phone: str,
    existing_name: str,
    existing_phone: str,
    existing_file: str,
) -> None:
    if not page_number:
        return
    conflicts.append(
        {
            "page_number": page_number,
            "incoming_name": incoming_name or "",
            "incoming_phone": incoming_phone or "",
            "existing_name": existing_name or "",
            "existing_phone": existing_phone or "",
            "existing_file_number": existing_file or "",
        }
    )


def _attach_page_numbers_to_patient(
    conn: sqlite3.Connection,
    *,
    patient_id: str,
    page_numbers_raw: str,
) -> tuple[int, bool]:
    """Attach page numbers to a patient (best-effort).

    Returns (saved_pages_count, primary_set).
    """
    pages = _split_page_numbers(page_numbers_raw)
    if not pages:
        return (0, False)

    saved = 0
    primary_set = False

    # Set primary_page_number if the column exists and the patient has none yet.
    if _patients_primary_page_column_exists(conn):
        row = conn.execute(
            "SELECT primary_page_number FROM patients WHERE id=? LIMIT 1",
            (patient_id,),
        ).fetchone()
        current_primary = ""
        if row:
            current_primary = (row["primary_page_number"] or "").strip()
        if not current_primary and pages[0]:
            conn.execute(
                "UPDATE patients SET primary_page_number=? WHERE id=?",
                (pages[0], patient_id),
            )
            primary_set = True

    # Always store all pages in patient_pages when possible (even if there are conflicts),
    # because notebooks can reuse the same page number across different patients.
    if _patient_pages_table_exists(conn):
        seen: set[str] = set()
        for pg in pages:
            if not pg or pg in seen:
                continue
            seen.add(pg)
            try:
                existing = conn.execute(
                    "SELECT 1 FROM patient_pages WHERE patient_id=? AND page_number=? LIMIT 1",
                    (patient_id, pg),
                ).fetchone()
                if existing:
                    continue
                conn.execute(
                    """
                    INSERT INTO patient_pages (id, patient_id, page_number, notebook_name)
                    VALUES (?, ?, ?, ?)
                    """,
                    (str(uuid4()), patient_id, pg, None),
                )
                saved += 1
            except Exception:
                # Never fail the import because of page-number storage.
                continue

    return (saved, primary_set)


def _ensure_import_row_tracking_table(conn: sqlite3.Connection) -> None:
    """Create lightweight tracking table used by safe re-import checks."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS import_row_fingerprints (
            source_kind TEXT NOT NULL,
            row_key TEXT NOT NULL,
            row_fingerprint TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (source_kind, row_key)
        )
        """
    )


def _import_row_tracking_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT 1
          FROM sqlite_master
         WHERE type='table' AND name='import_row_fingerprints'
         LIMIT 1
        """
    ).fetchone()
    return row is not None


def _normalize_import_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def _first_stable_row_key(payment: object) -> str:
    """Best-effort stable key for a First Stable row across re-imports."""
    row_id = (getattr(payment, "source_row_id", "") or "").strip()
    if not row_id:
        return ""
    page0 = _first_page_number_token(getattr(payment, "short_id", "") or "")
    name_norm = _normalize_import_text(getattr(payment, "full_name", "") or "")
    phone_norm = "".join(ch for ch in str(getattr(payment, "phone", "") or "") if ch.isdigit())
    return f"{row_id}|pg:{page0}|nm:{name_norm}|ph:{phone_norm}"


def _first_stable_row_fingerprint(payment: object) -> str:
    """Content fingerprint used to detect edited old rows."""
    parts = [
        str(getattr(payment, "paid_at", "") or "").strip(),
        str(int(getattr(payment, "total_cents", 0) or 0)),
        str(int(getattr(payment, "paid_cents", 0) or 0)),
        str(int(getattr(payment, "remaining_cents", 0) or 0)),
        str(int(getattr(payment, "discount_cents", 0) or 0)),
        str(int(getattr(payment, "exam_flag", 0) or 0)),
        str(int(getattr(payment, "follow_flag", 0) or 0)),
        str(getattr(payment, "treatment_type", "") or "").strip(),
        str(getattr(payment, "notes", "") or "").strip(),
    ]
    payload = "|".join(parts).encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()


def _tracked_row_fingerprint(conn: sqlite3.Connection, source_kind: str, row_key: str) -> str:
    if not source_kind or not row_key:
        return ""
    row = conn.execute(
        """
        SELECT row_fingerprint
          FROM import_row_fingerprints
         WHERE source_kind=? AND row_key=?
         LIMIT 1
        """,
        (source_kind, row_key),
    ).fetchone()
    if not row:
        return ""
    try:
        return str(row["row_fingerprint"] or "")
    except Exception:
        return str(row[0] or "")


def _upsert_tracked_row_fingerprint(
    conn: sqlite3.Connection,
    *,
    source_kind: str,
    row_key: str,
    row_fingerprint: str,
) -> None:
    if not source_kind or not row_key or not row_fingerprint:
        return
    conn.execute(
        """
        INSERT INTO import_row_fingerprints(source_kind, row_key, row_fingerprint)
        VALUES (?, ?, ?)
        ON CONFLICT(source_kind, row_key)
        DO UPDATE SET
            row_fingerprint=excluded.row_fingerprint,
            updated_at=CURRENT_TIMESTAMP
        """,
        (source_kind, row_key, row_fingerprint),
    )


def _resolve_import_doctor(raw_label: str, doctor_options: list[dict[str, str]]) -> tuple[str, str]:
    from clinic_app.services.doctor_colors import ANY_DOCTOR_ID, ANY_DOCTOR_LABEL

    label = (raw_label or "").strip()
    if not label:
        return (ANY_DOCTOR_ID, ANY_DOCTOR_LABEL)

    label_norm = _normalize_import_text(label)
    id_norm = label_norm

    for option in doctor_options:
        doc_id = (option.get("doctor_id") or "").strip()
        doc_label = (option.get("doctor_label") or "").strip()
        if not doc_id:
            continue
        if id_norm == _normalize_import_text(doc_id):
            return (doc_id, doc_label or ANY_DOCTOR_LABEL)
        if label_norm and label_norm == _normalize_import_text(doc_label):
            return (doc_id, doc_label or ANY_DOCTOR_LABEL)

    if label_norm in {"any doctor", "any"}:
        return (ANY_DOCTOR_ID, ANY_DOCTOR_LABEL)
    return (ANY_DOCTOR_ID, ANY_DOCTOR_LABEL)


def _payment_exists(
    conn: sqlite3.Connection,
    *,
    payment_id: str,
    patient_id: str,
    paid_at: str,
    amount_cents: int,
    total_cents: int,
    remaining_cents: int,
    discount_cents: int,
    note: str,
    treatment: str,
    exam_flag: int,
    follow_flag: int,
) -> bool:
    if payment_id:
        row = conn.execute("SELECT 1 FROM payments WHERE id=? LIMIT 1", (payment_id,)).fetchone()
        return row is not None

    row = conn.execute(
        """
        SELECT 1
          FROM payments
         WHERE patient_id=?
           AND paid_at=?
           AND amount_cents=?
           AND total_amount_cents=?
           AND remaining_cents=?
           AND discount_cents=?
           AND COALESCE(note,'')=?
           AND COALESCE(treatment,'')=?
           AND COALESCE(examination_flag,0)=?
           AND COALESCE(followup_flag,0)=?
         LIMIT 1
        """,
        (
            patient_id,
            paid_at,
            amount_cents,
            total_cents,
            remaining_cents,
            discount_cents,
            (note or "").strip(),
            (treatment or "").strip(),
            exam_flag,
            follow_flag,
        ),
    ).fetchone()
    return row is not None


@bp.route("/settings/data-import/duplicates-db", methods=["GET"])
@require_permission("admin.user.manage")
def data_import_duplicates_db():
    """Return possible duplicate patients inside the database (no merges)."""
    mode = (request.args.get("mode") or "").strip().lower()
    aggressive_flag = (request.args.get("aggressive") or "").strip().lower() in {"1", "true", "yes", "on"}
    if aggressive_flag:
        mode = "aggressive"
    if mode not in {"safe", "normal", "aggressive"}:
        mode = "safe"
    try:
        duplicates = _db_duplicate_groups(mode=mode)
        return jsonify({"success": True, "duplicates": duplicates})
    except Exception as exc:
        return jsonify({"success": False, "errors": [str(exc)]}), 500


def _payments_columns(conn: sqlite3.Connection) -> set[str]:
    try:
        cols = conn.execute("PRAGMA table_info(payments)").fetchall() or []
    except Exception:
        return set()
    names: set[str] = set()
    for c in cols:
        try:
            names.add(c["name"])
        except Exception:
            names.add(c[1])
    return names


def _payments_schema_check(conn: sqlite3.Connection) -> tuple[bool, list[str]]:
    """Return (ok, missing_columns)."""
    cols = _payments_columns(conn)
    required = {
        "id",
        "patient_id",
        "paid_at",
        "amount_cents",
        "remaining_cents",
        "total_amount_cents",
        "examination_flag",
        "followup_flag",
        "discount_cents",
    }
    missing = sorted(required - cols)
    return (len(missing) == 0), missing


def _insert_payment_row(
    conn: sqlite3.Connection,
    *,
    payment_id: str,
    patient_id: str,
    paid_at: str,
    amount_cents: int,
    method: str,
    note: str,
    treatment: str,
    remaining_cents: int,
    total_cents: int,
    exam_flag: int,
    follow_flag: int,
    discount_cents: int,
    doctor_id: str,
    doctor_label: str,
) -> None:
    cols = _payments_columns(conn)

    # Minimal schema guard: do not attempt partial imports that would break the app.
    ok, missing = _payments_schema_check(conn)
    if not ok:
        raise RuntimeError("missing_payments_columns:" + ",".join(missing))

    insert_cols: list[str] = []
    values: list[object] = []

    def add(col: str, value: object) -> None:
        if col in cols:
            insert_cols.append(col)
            values.append(value)

    add("id", payment_id)
    add("patient_id", patient_id)
    add("paid_at", paid_at)
    add("amount_cents", amount_cents)
    add("method", method)
    add("note", note)
    add("treatment", treatment)
    add("remaining_cents", remaining_cents)
    add("total_amount_cents", total_cents)
    add("examination_flag", exam_flag)
    add("followup_flag", follow_flag)
    add("discount_cents", discount_cents)
    add("doctor_id", doctor_id)
    add("doctor_label", doctor_label)

    placeholders = ", ".join(["?"] * len(insert_cols))
    col_list = ", ".join(insert_cols)
    conn.execute(f"INSERT INTO payments({col_list}) VALUES ({placeholders})", values)


@bp.route("/settings/data-import/commit", methods=["POST"])
@require_permission("admin.user.manage")
def commit_data_import():
    """Import an uploaded file into the **main** clinic database (with backup)."""
    # CSRF validation for both JSON and multipart form requests.
    if request.content_type and request.content_type.startswith("multipart/"):
        data = {"csrf_token": request.form.get("csrf_token") or request.headers.get("X-CSRFToken")}
    else:
        data = request.get_json() or {}
    ensure_csrf_token(data)

    # Only allow importing into the main DB (not preview servers).
    if _db_file_path().resolve() != _main_db_path().resolve():
        return (
            jsonify(
                {
                    "success": False,
                    "errors": [T("data_import_commit_only_main_db")],
                }
            ),
            400,
        )

    upload = request.files.get("excel_file")
    if not upload or not upload.filename:
        return (
            jsonify({"success": False, "errors": [T("data_import_file_required")]}),
            400,
        )

    raw_skip_duplicates = request.form.get("skip_duplicates")
    raw_import_zero_entries = request.form.get("import_zero_entries")
    raw_never_auto_merge = request.form.get("never_auto_merge")

    # Defaults: keep current behavior (skip duplicates ON, import zero-amount rows ON),
    # and use the saved clinic preference for safe merge when the field is missing.
    skip_duplicates: bool | None = _bool_from_value(raw_skip_duplicates) if raw_skip_duplicates is not None else None
    import_zero_entries: bool | None = (
        _bool_from_value(raw_import_zero_entries) if raw_import_zero_entries is not None else None
    )
    never_auto_merge: bool | None = _bool_from_value(raw_never_auto_merge) if raw_never_auto_merge is not None else None

    if skip_duplicates is None or import_zero_entries is None or never_auto_merge is None:
        try:
            conn_settings = db_sqlite()
        except Exception:
            # If we cannot read clinic settings, fall back to safe defaults.
            if skip_duplicates is None:
                skip_duplicates = True
            if import_zero_entries is None:
                import_zero_entries = True
            if never_auto_merge is None:
                never_auto_merge = True
        else:
            try:
                if skip_duplicates is None:
                    skip_duplicates = _admin_setting_bool(conn_settings, "import_skip_duplicates", True)
                if import_zero_entries is None:
                    import_zero_entries = _admin_setting_bool(conn_settings, "import_import_zero_entries", True)
                if never_auto_merge is None:
                    never_auto_merge = _admin_setting_bool(conn_settings, "import_never_auto_merge", True)
            finally:
                conn_settings.close()

    merge_mode = (request.form.get("merge_mode") or "").strip().lower()
    if merge_mode not in {"safe", "normal"}:
        merge_mode = "safe" if never_auto_merge else "normal"

    import tempfile
    import os

    suffix = Path(upload.filename).suffix or ".xlsx"
    suffix_lower = suffix.lower()
    if suffix_lower not in {".xlsx", ".xlsm", ".csv"}:
        return (
            jsonify({"success": False, "errors": [T("data_import_unsupported_file")]}),
            400,
        )

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = Path(tmp.name)
    source_kind = "csv" if suffix_lower == ".csv" else "first_stable"

    try:
        upload.save(tmp_path)
        if suffix_lower == ".csv":
            payments, counts = extract_import_csv_payments(tmp_path)
        else:
            payments, counts = extract_first_stable_payments(tmp_path)
    except FileNotFoundError:
        return (
            jsonify({"success": False, "errors": [T("data_import_file_not_found")]}),
            404,
        )
    except Exception as exc:
        msg = str(exc) or ""
        if "File is not a zip file" in msg or "BadZipFile" in msg:
            return (
                jsonify({"success": False, "errors": [T("data_import_unsupported_file")]}),
                400,
            )
        return jsonify({"success": False, "errors": [str(exc)]}), 500
    finally:
        try:
            tmp.close()
        except Exception:
            pass

    if not payments:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return jsonify({"success": True, "message": T("data_import_no_rows"), "result": {"counts": counts}})

    # Backup before any DB writes.
    try:
        backup_path = _create_db_backup()
    except Exception as exc:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return jsonify({"success": False, "errors": [f"{T('data_import_backup_failed')}: {exc}"]}), 500

    conn = db_sqlite()
    try:
        if request.form.get("never_auto_merge") is None:
            never_auto_merge = _admin_setting_bool(conn, "import_never_auto_merge", True)
        if request.form.get("merge_mode") in (None, "", False):
            merge_mode = "safe" if never_auto_merge else "normal"
        if request.form.get("merge_mode") in (None, "", False):
            merge_mode = "safe" if never_auto_merge else "normal"
        if request.form.get("merge_mode") in (None, "", False):
            merge_mode = "safe" if never_auto_merge else "normal"
        if request.form.get("merge_mode") in (None, "", False):
            merge_mode = "safe" if never_auto_merge else "normal"

        migrate_patients_drop_unique_short_id(conn)
        conn.execute("BEGIN")

        from clinic_app.services.doctor_colors import ANY_DOCTOR_ID

        schema_ok, missing_cols = _payments_schema_check(conn)
        if not schema_ok:
            return (
                jsonify(
                    {
                        "success": False,
                        "errors": [T("data_import_schema_missing").format(cols=", ".join(missing_cols))],
                    }
                ),
                400,
            )
        if source_kind == "first_stable":
            _ensure_import_row_tracking_table(conn)
        track_first_stable_rows = bool(source_kind == "first_stable" and skip_duplicates)

        created_patients = 0
        matched_patients = 0
        file_number_collisions = 0
        inserted_money = 0
        inserted_zero = 0
        skipped_duplicates = 0
        skipped_edited_existing_rows = 0
        skipped_zero = 0
        unknown_dates = 0
        page_conflicts: list[dict[str, str]] = []
        saved_page_numbers = 0
        primary_pages_set = 0
        patient_ids_in_file: set[str] = set()
        created_patient_ids: set[str] = set()
        patients_with_imported_payment: set[str] = set()

        # Cache per-patient creation to reduce lookups.
        patient_cache: dict[tuple[str, str, str, str], str] = {}

        for p in payments:
            first_stable_row_key = ""
            first_stable_row_fingerprint = ""
            if track_first_stable_rows:
                first_stable_row_key = _first_stable_row_key(p)
                first_stable_row_fingerprint = _first_stable_row_fingerprint(p)
                tracked_fingerprint = _tracked_row_fingerprint(conn, source_kind, first_stable_row_key)
                if tracked_fingerprint:
                    if tracked_fingerprint == first_stable_row_fingerprint:
                        skipped_duplicates += 1
                    else:
                        skipped_edited_existing_rows += 1
                    continue

            # First stable stores notebook pages in short_id; CSV uses file_number in short_id.
            file_number = (p.short_id or "").strip() if source_kind == "csv" else ""
            page_number_raw = (p.page_number or "").strip() if source_kind == "csv" else (p.short_id or "").strip()
            full_name = (p.full_name or "").strip()
            phone = (p.phone or "").strip()
            name_key = " ".join(full_name.split()).strip().lower()
            phone_key = "".join(ch for ch in phone if ch.isdigit())

            # Cache key should be stable even if the Excel has page formats like
            # "45-46" vs "45". We normalize to the first page number token for
            # identity lookups.
            page_key = _first_page_number_token(page_number_raw) or page_number_raw

            cache_key = (file_number, page_key, name_key, phone_key)
            patient_id = patient_cache.get(cache_key)
            created = False
            collided = False
            if not patient_id:
                # If this is First Stable import, never auto-merge by page number alone.
                # Record conflicts when the same page number already exists for a different patient.
                if source_kind == "first_stable":
                    page0 = _first_page_number_token(page_number_raw)
                    if page0:
                        # Look up any existing patient using this page number.
                        existing = None
                        if _patients_primary_page_column_exists(conn):
                            existing = conn.execute(
                                "SELECT id, short_id, full_name, phone FROM patients WHERE primary_page_number=? LIMIT 1",
                                (page0,),
                            ).fetchone()
                        if (not existing) and _patient_pages_table_exists(conn):
                            existing = conn.execute(
                                """
                                SELECT p.id, p.short_id, p.full_name, p.phone
                                  FROM patient_pages pg
                                  JOIN patients p ON p.id = pg.patient_id
                                 WHERE pg.page_number=?
                                 LIMIT 1
                                """,
                                (page0,),
                            ).fetchone()

                        if existing:
                            in_name = " ".join(full_name.split()).strip().lower()
                            in_phone = "".join(ch for ch in phone if ch.isdigit())
                            ex_name = " ".join((existing["full_name"] or "").split()).strip().lower()
                            ex_phone = "".join(ch for ch in (existing["phone"] or "") if ch.isdigit())
                            # For First Stable re-imports, allow two modes:
                            # - safe: require exact name, phone when present
                            # - normal: exact name only
                            phone_ok = True if merge_mode == "normal" else (
                                (in_phone and ex_phone and in_phone == ex_phone) or (not in_phone) or (not ex_phone)
                            )
                            if in_name and in_name == ex_name and phone_ok:
                                patient_id = existing["id"]
                                created = False
                                collided = False
                            else:
                                _record_page_conflict(
                                    page_conflicts,
                                    page_number=page0,
                                    incoming_name=full_name,
                                    incoming_phone=phone,
                                    existing_name=existing["full_name"] or "",
                                    existing_phone=existing["phone"] or "",
                                    existing_file=existing["short_id"] or "",
                                )
                                # Force creation of a new patient (do not merge).
                                patient_id, created, collided = _resolve_patient_for_import(
                                    conn,
                                    source_kind=source_kind,
                                    file_number=file_number,
                                    page_number="",
                                    full_name=full_name,
                                    phone=phone,
                                    never_auto_merge=never_auto_merge,
                                    merge_mode=merge_mode,
                                )
                        else:
                            patient_id, created, collided = _resolve_patient_for_import(
                                conn,
                                source_kind=source_kind,
                                file_number=file_number,
                                page_number="",
                                full_name=full_name,
                                phone=phone,
                                never_auto_merge=never_auto_merge,
                                merge_mode=merge_mode,
                            )
                    else:
                        patient_id, created, collided = _resolve_patient_for_import(
                            conn,
                            source_kind=source_kind,
                            file_number=file_number,
                            page_number="",
                            full_name=full_name,
                            phone=phone,
                            never_auto_merge=never_auto_merge,
                            merge_mode=merge_mode,
                        )
                else:
                    patient_id, created, collided = _resolve_patient_for_import(
                        conn,
                        source_kind=source_kind,
                        file_number=file_number,
                        page_number=page_number_raw,
                        full_name=full_name,
                        phone=phone,
                        never_auto_merge=never_auto_merge,
                        merge_mode=merge_mode,
                    )
                patient_cache[cache_key] = patient_id

                # Count unique patient files (not per-row).
                if created:
                    created_patients += 1
                    created_patient_ids.add(patient_id)
                else:
                    matched_patients += 1
                if collided:
                    file_number_collisions += 1
            patient_ids_in_file.add(patient_id)

            # For First Stable, the notebook page number is a *property* of the patient.
            # We always save it (even if it conflicts), but we never auto-merge by page alone.
            if source_kind == "first_stable":
                saved, primary_set = _attach_page_numbers_to_patient(
                    conn, patient_id=patient_id, page_numbers_raw=page_number_raw
                )
                saved_page_numbers += saved
                if primary_set:
                    primary_pages_set += 1

            # Decide whether to import this row as a payment entry.
            has_amounts = bool((p.total_cents or 0) or (p.paid_cents or 0) or (p.remaining_cents or 0))
            if (not has_amounts) and (not import_zero_entries):
                skipped_zero += 1
                continue

            # Safety: never guess unknown dates. Keep blank if unreadable/missing.
            paid_at = (p.paid_at or "").strip()
            if not paid_at:
                unknown_dates += 1

            amount_cents = int(p.paid_cents or 0)
            total_cents = int(p.total_cents or 0)
            discount_cents = int(getattr(p, "discount_cents", 0) or 0)
            remaining_cents = int(p.remaining_cents or 0)
            note = (p.notes or "").strip()
            treatment = (p.treatment_type or "").strip()
            exam_flag = 1 if getattr(p, "exam_flag", 0) else 0
            follow_flag = 1 if getattr(p, "follow_flag", 0) else 0

            payment_id = (getattr(p, "payment_id", "") or "").strip()
            if skip_duplicates and _payment_exists(
                conn,
                payment_id=payment_id,
                patient_id=patient_id,
                paid_at=paid_at,
                amount_cents=amount_cents,
                total_cents=total_cents,
                remaining_cents=remaining_cents,
                discount_cents=discount_cents,
                note=note,
                treatment=treatment,
                exam_flag=exam_flag,
                follow_flag=follow_flag,
            ):
                if source_kind == "first_stable":
                    _upsert_tracked_row_fingerprint(
                        conn,
                        source_kind=source_kind,
                        row_key=first_stable_row_key,
                        row_fingerprint=first_stable_row_fingerprint,
                    )
                skipped_duplicates += 1
                continue

            pay_id = payment_id or str(uuid4())
            method = (getattr(p, "method", "") or "").strip() or "cash"
            # Always import as Any Doctor, regardless of what's inside the file.
            doctor_label = ANY_DOCTOR_LABEL
            _insert_payment_row(
                conn,
                payment_id=pay_id,
                patient_id=patient_id,
                paid_at=paid_at,
                amount_cents=amount_cents,
                method=method,
                note=note,
                treatment=treatment,
                remaining_cents=remaining_cents,
                total_cents=total_cents,
                exam_flag=exam_flag,
                follow_flag=follow_flag,
                discount_cents=discount_cents,
                doctor_id=ANY_DOCTOR_ID,
                doctor_label=doctor_label,
            )
            if source_kind == "first_stable":
                _upsert_tracked_row_fingerprint(
                    conn,
                    source_kind=source_kind,
                    row_key=first_stable_row_key,
                    row_fingerprint=first_stable_row_fingerprint,
                )
            patients_with_imported_payment.add(patient_id)

            if has_amounts:
                inserted_money += 1
            else:
                inserted_zero += 1

        conn.commit()

    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return jsonify({"success": False, "errors": [str(exc)]}), 500
    finally:
        conn.close()
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    report_dir = Path(current_app.config["DATA_ROOT"]) / "import_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_name = f"import-{ts}.json"
    report_path = report_dir / report_name
    report = {
        "timestamp": ts,
        "filename": upload.filename,
        "source_kind": source_kind,
        "options": {
            "skip_duplicates": bool(skip_duplicates),
            "import_zero_entries": bool(import_zero_entries),
            "never_auto_merge": bool(never_auto_merge),
        },
        "patient_ids_in_file": sorted(patient_ids_in_file),
        "created_patient_ids": sorted(created_patient_ids),
        "counts": counts,
        "results": {
            "unique_patients_in_file": len(patient_cache),
            "created_patients": created_patients,
            "matched_patients": matched_patients,
            "created_patients_no_payments_imported": len(created_patient_ids - patients_with_imported_payment),
            "file_number_collisions": file_number_collisions,
            "inserted_money_payments": inserted_money,
            "inserted_zero_entries": inserted_zero,
            "skipped_duplicates": skipped_duplicates,
            "skipped_edited_existing_rows": skipped_edited_existing_rows,
            "skipped_zero_entries": skipped_zero,
            # Backwards compatible key name (older UI used "fallback to today").
            # We intentionally keep unknown dates blank now.
            "unknown_dates_fallback_to_today": unknown_dates,
            "unknown_dates_left_blank": unknown_dates,
            "page_number_conflicts": len(page_conflicts),
            "page_numbers_saved": saved_page_numbers,
            "primary_pages_set": primary_pages_set,
        },
        "page_conflicts_preview": page_conflicts[:50],
        "backup_path": str(backup_path),
    }
    try:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # Report writing should not block the import.
        report_name = ""

    msg = T("data_import_commit_ok")
    return jsonify(
        {
            "success": True,
            "message": msg,
            "result": report["results"],
            "options": {
                "merge_mode": merge_mode,
                "skip_duplicates": bool(skip_duplicates),
                "import_zero_entries": bool(import_zero_entries),
                "never_auto_merge": bool(never_auto_merge),
                "source_kind": source_kind,
                # Debug-friendly raw values (helps confirm checkboxes are actually sent)
                "raw_skip_duplicates": raw_skip_duplicates,
                "raw_import_zero_entries": raw_import_zero_entries,
                "raw_never_auto_merge": raw_never_auto_merge,
            },
            "backup_path": str(backup_path),
            "report_name": report_name,
        }
    )


@bp.route("/settings/data-import/report/<name>", methods=["GET"])
@require_permission("admin.user.manage")
def download_import_report(name: str):
    safe = (name or "").strip()
    if not safe or "/" in safe or "\\" in safe:
        abort(404)
    report_path = Path(current_app.config["DATA_ROOT"]) / "import_reports" / safe
    if not report_path.exists():
        abort(404)
    return send_file(
        io.BytesIO(report_path.read_bytes()),
        mimetype="application/json",
        as_attachment=True,
        download_name=safe,
    )


@bp.route("/settings/data-import/reports", methods=["GET"])
@require_permission("admin.user.manage")
def list_import_reports():
    """List available import reports under data/import_reports."""
    report_dir = Path(current_app.config["DATA_ROOT"]) / "import_reports"
    if not report_dir.exists():
        return jsonify({"success": True, "reports": []})

    items: list[dict[str, object]] = []
    for p in sorted(report_dir.glob("import-*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            st = p.stat()
        except OSError:
            continue
        # Read minimal fields (best-effort).
        meta: dict[str, object] = {}
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        items.append(
            {
                "name": p.name,
                "bytes": int(st.st_size),
                "modified_at": int(st.st_mtime),
                "filename": meta.get("filename") if isinstance(meta, dict) else None,
                "source_kind": meta.get("source_kind") if isinstance(meta, dict) else None,
                "results": meta.get("results") if isinstance(meta, dict) else None,
            }
        )

    return jsonify({"success": True, "reports": items[:50]})


@bp.route("/settings/data-import/report/<name>/meta", methods=["GET"])
@require_permission("admin.user.manage")
def import_report_meta(name: str):
    """Return a single import report's metadata (safe subset for UI)."""
    report = _load_import_report(name)
    if not report or not isinstance(report, dict):
        return jsonify({"success": False, "errors": [T("data_import_report_not_found")]}), 404

    meta = {
        "name": name,
        "timestamp": report.get("timestamp"),
        "filename": report.get("filename"),
        "source_kind": report.get("source_kind"),
        "options": report.get("options") or {},
        "counts": report.get("counts") or {},
        "results": report.get("results") or {},
        "page_conflicts_preview": report.get("page_conflicts_preview") or [],
    }
    return jsonify({"success": True, "report": meta})


@bp.route("/settings/data-import/preflight", methods=["POST"])
@require_permission("admin.user.manage")
def preflight_data_import():
    """Dry-run import against the real DB (no writes)."""
    if request.content_type and request.content_type.startswith("multipart/"):
        data = {"csrf_token": request.form.get("csrf_token") or request.headers.get("X-CSRFToken")}
    else:
        data = request.get_json() or {}
    ensure_csrf_token(data)

    # Only allow preflight against the main DB (same rules as commit).
    if _db_file_path().resolve() != _main_db_path().resolve():
        return (
            jsonify({"success": False, "errors": [T("data_import_commit_only_main_db")]}),
            400,
        )

    upload = request.files.get("excel_file")
    if not upload or not upload.filename:
        return jsonify({"success": False, "errors": [T("data_import_file_required")]}), 400

    raw_skip_duplicates = request.form.get("skip_duplicates")
    raw_import_zero_entries = request.form.get("import_zero_entries")
    raw_never_auto_merge = request.form.get("never_auto_merge")

    skip_duplicates = _bool_from_value(raw_skip_duplicates) if raw_skip_duplicates is not None else True
    import_zero_entries = _bool_from_value(raw_import_zero_entries) if raw_import_zero_entries is not None else True
    never_auto_merge = _bool_from_value(raw_never_auto_merge) if raw_never_auto_merge is not None else False

    import tempfile
    import os

    suffix = Path(upload.filename).suffix or ".xlsx"
    suffix_lower = suffix.lower()
    if suffix_lower not in {".xlsx", ".xlsm", ".csv"}:
        return jsonify({"success": False, "errors": [T("data_import_unsupported_file")]}), 400

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp_path = Path(tmp.name)
    source_kind = "csv" if suffix_lower == ".csv" else "first_stable"

    try:
        upload.save(tmp_path)
        if suffix_lower == ".csv":
            payments, counts = extract_import_csv_payments(tmp_path)
        else:
            payments, counts = extract_first_stable_payments(tmp_path)
    except Exception as exc:
        msg = str(exc) or ""
        if "File is not a zip file" in msg or "BadZipFile" in msg:
            return jsonify({"success": False, "errors": [T("data_import_unsupported_file")]}), 400
        return jsonify({"success": False, "errors": [str(exc)]}), 500
    finally:
        try:
            tmp.close()
        except Exception:
            pass
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    if not payments:
        return jsonify({"success": True, "message": T("data_import_no_rows"), "counts": counts, "result": {}})

    conn = db_sqlite()
    try:
        if raw_skip_duplicates is None:
            skip_duplicates = _admin_setting_bool(conn, "import_skip_duplicates", True)
        if raw_import_zero_entries is None:
            import_zero_entries = _admin_setting_bool(conn, "import_import_zero_entries", True)
        if raw_never_auto_merge is None:
            never_auto_merge = _admin_setting_bool(conn, "import_never_auto_merge", True)

        merge_mode = (request.form.get("merge_mode") or "").strip().lower()
        if merge_mode not in {"safe", "normal"}:
            # Match commit defaults: safe when never_auto_merge, else normal.
            merge_mode = "safe" if never_auto_merge else "normal"

        schema_ok, missing_cols = _payments_schema_check(conn)
        if not schema_ok:
            return (
                jsonify(
                    {
                        "success": False,
                        "errors": [T("data_import_schema_missing").format(cols=", ".join(missing_cols))],
                    }
                ),
                400,
            )
        track_first_stable_rows = bool(
            source_kind == "first_stable"
            and skip_duplicates
            and _import_row_tracking_table_exists(conn)
        )

        from clinic_app.services.doctor_colors import ANY_DOCTOR_ID

        would_create_patients = 0
        would_match_patients = 0
        would_page_conflicts = 0
        would_insert_money = 0
        would_insert_zero = 0
        would_skip_duplicates = 0
        would_skip_edited_existing_rows = 0
        would_skip_zero = 0
        unknown_dates = 0

        # Keyed by "patient identity in file" so counts match Analyze (Safe/Normal).
        patient_cache: dict[str, str] = {}
        created_patient_keys: set[str] = set()
        patient_keys_with_importable_payment: set[str] = set()

        for p in payments:
            if track_first_stable_rows:
                row_key = _first_stable_row_key(p)
                row_fingerprint = _first_stable_row_fingerprint(p)
                tracked_fingerprint = _tracked_row_fingerprint(conn, source_kind, row_key)
                if tracked_fingerprint:
                    if tracked_fingerprint == row_fingerprint:
                        would_skip_duplicates += 1
                    else:
                        would_skip_edited_existing_rows += 1
                    continue

            file_number = (p.short_id or "").strip() if source_kind == "csv" else ""
            page_number_raw = (p.page_number or "").strip() if source_kind == "csv" else (p.short_id or "").strip()
            full_name = (p.full_name or "").strip()
            phone = (p.phone or "").strip()
            name_key = " ".join(full_name.split()).strip().lower()
            phone_key = "".join(ch for ch in phone if ch.isdigit())

            page0 = _first_page_number_token(page_number_raw)
            file_norm = _normalize_file_number_token(file_number) if source_kind == "csv" else ""

            # Grouping key must mirror Analyze:
            # - First stable safe/normal: page + exact name (phone only if present), else phone, else name.
            # - CSV safe: file + exact name (phone only if present), else phone, else name.
            # - CSV normal: file + exact name, else phone, else name.
            if source_kind == "first_stable":
                if page0 and name_key and phone_key:
                    cache_key = f"pg|{page0}|{name_key}|{phone_key}"
                elif page0 and name_key:
                    cache_key = f"pg|{page0}|{name_key}"
                elif phone_key:
                    cache_key = f"phone|{phone_key}"
                elif name_key:
                    cache_key = f"name|{name_key}"
                else:
                    cache_key = ""
            else:
                if merge_mode == "safe":
                    if file_norm and name_key and phone_key:
                        cache_key = f"file|{file_norm}|{name_key}|{phone_key}"
                    elif file_norm and name_key:
                        cache_key = f"file|{file_norm}|{name_key}"
                    elif phone_key:
                        cache_key = f"phone|{phone_key}"
                    elif name_key:
                        cache_key = f"name|{name_key}"
                    else:
                        cache_key = ""
                else:
                    if file_norm and name_key:
                        cache_key = f"file|{file_norm}|{name_key}"
                    elif phone_key:
                        cache_key = f"phone|{phone_key}"
                    elif name_key:
                        cache_key = f"name|{name_key}"
                    else:
                        cache_key = ""

            if not cache_key:
                # Can't match/create without identity; ignore for patient counting.
                continue

            patient_id = patient_cache.get(cache_key)
            created = False
            if not patient_id:
                # Try to resolve without creating: mimic the real import logic
                if file_number:
                    row = conn.execute("SELECT id FROM patients WHERE short_id=? LIMIT 1", (file_number,)).fetchone()
                    if row:
                        patient_id = row["id"]
                if not patient_id:
                    pages = _split_page_numbers(page_number_raw)
                    # Never-auto-merge only disables using page number to match
                    # existing patients for CSV/template imports. For First Stable,
                    # we still compute page conflicts for reporting.
                    if never_auto_merge and source_kind != "first_stable":
                        pages = []
                    if source_kind == "first_stable":
                        page0 = _first_page_number_token(page_number_raw)
                        pages = [page0] if page0 else []
                    if pages:
                        page0 = pages[0]
                        # For First Stable, page number alone is NOT a safe match.
                        if source_kind == "first_stable":
                            existing = None
                            if _patients_primary_page_column_exists(conn):
                                existing = conn.execute(
                                    "SELECT id, full_name, phone FROM patients WHERE primary_page_number=? LIMIT 1",
                                    (page0,),
                                ).fetchone()
                            if (not existing) and _patient_pages_table_exists(conn):
                                existing = conn.execute(
                                    """
                                    SELECT p.id, p.full_name, p.phone
                                      FROM patient_pages pg
                                      JOIN patients p ON p.id = pg.patient_id
                                     WHERE pg.page_number=?
                                     LIMIT 1
                                    """,
                                    (page0,),
                                ).fetchone()
                            if existing:
                                in_name = " ".join(full_name.split()).strip().lower()
                                in_phone = "".join(ch for ch in phone if ch.isdigit())
                                ex_name = " ".join((existing["full_name"] or "").split()).strip().lower()
                                ex_phone = "".join(ch for ch in (existing["phone"] or "") if ch.isdigit())
                                phone_ok = True if merge_mode == "normal" else (
                                    (in_phone and ex_phone and in_phone == ex_phone) or (not in_phone) or (not ex_phone)
                                )
                                if in_name and in_name == ex_name and phone_ok:
                                    patient_id = existing["id"]
                                else:
                                    would_page_conflicts += 1
                                    patient_id = "NEW"
                            else:
                                patient_id = "NEW"
                        else:
                            if _patients_primary_page_column_exists(conn):
                                row = conn.execute(
                                    "SELECT id FROM patients WHERE primary_page_number=? LIMIT 1",
                                    (page0,),
                                ).fetchone()
                                if row:
                                    patient_id = row["id"]
                            if not patient_id and _patient_pages_table_exists(conn):
                                row = conn.execute(
                                    "SELECT patient_id as id FROM patient_pages WHERE page_number=? LIMIT 1",
                                    (page0,),
                                ).fetchone()
                                if row:
                                    patient_id = row["id"]
                if not patient_id:
                    created = True
                    patient_id = "NEW"
                patient_cache[cache_key] = patient_id

                # Count unique patient files (not per row).
                if created:
                    would_create_patients += 1
                    created_patient_keys.add(cache_key)
                else:
                    would_match_patients += 1

            has_amounts = bool((p.total_cents or 0) or (p.paid_cents or 0) or (p.remaining_cents or 0))
            if (not has_amounts) and (not import_zero_entries):
                would_skip_zero += 1
                continue

            # Safety: never guess unknown dates. Keep blank if unreadable/missing.
            paid_at = (p.paid_at or "").strip()
            if not paid_at:
                unknown_dates += 1

            if patient_id == "NEW":
                # Can't be a duplicate in DB if the patient doesn't exist yet.
                if has_amounts:
                    would_insert_money += 1
                else:
                    would_insert_zero += 1
                patient_keys_with_importable_payment.add(cache_key)
                continue

            amount_cents = int(p.paid_cents or 0)
            total_cents = int(p.total_cents or 0)
            discount_cents = int(getattr(p, "discount_cents", 0) or 0)
            remaining_cents = int(p.remaining_cents or 0)
            note = (p.notes or "").strip()
            treatment = (p.treatment_type or "").strip()
            exam_flag = 1 if getattr(p, "exam_flag", 0) else 0
            follow_flag = 1 if getattr(p, "follow_flag", 0) else 0

            payment_id = (getattr(p, "payment_id", "") or "").strip()
            if skip_duplicates and _payment_exists(
                conn,
                payment_id=payment_id,
                patient_id=patient_id,
                paid_at=paid_at,
                amount_cents=amount_cents,
                total_cents=total_cents,
                remaining_cents=remaining_cents,
                discount_cents=discount_cents,
                note=note,
                treatment=treatment,
                exam_flag=exam_flag,
                follow_flag=follow_flag,
            ):
                would_skip_duplicates += 1
                continue

            # Would insert
            _ = ANY_DOCTOR_ID  # keep lint quiet
            if has_amounts:
                would_insert_money += 1
            else:
                would_insert_zero += 1
            patient_keys_with_importable_payment.add(cache_key)

        return jsonify(
            {
                "success": True,
                "message": T("data_import_preflight_ok"),
                "counts": counts,
                "options": {
                    "merge_mode": merge_mode,
                    "skip_duplicates": bool(skip_duplicates),
                    "import_zero_entries": bool(import_zero_entries),
                    "never_auto_merge": bool(never_auto_merge),
                    "source_kind": source_kind,
                    # Debug-friendly raw values (helps confirm checkboxes are actually sent)
                    "raw_skip_duplicates": raw_skip_duplicates,
                    "raw_import_zero_entries": raw_import_zero_entries,
                    "raw_never_auto_merge": raw_never_auto_merge,
                },
                "result": {
                    "unique_patients_in_file": len(patient_cache),
                    # Only count patients that would actually be created AND have at least
                    # one importable row (otherwise the UI can look scary after a re-import).
                    "would_create_patients": len(created_patient_keys & patient_keys_with_importable_payment),
                    "would_match_patients": would_match_patients,
                    "would_create_patients_no_payments_imported": len(
                        created_patient_keys - patient_keys_with_importable_payment
                    ),
                    "would_insert_money_payments": would_insert_money,
                    "would_insert_zero_entries": would_insert_zero,
                    "would_skip_duplicates": would_skip_duplicates,
                    "would_skip_edited_existing_rows": would_skip_edited_existing_rows,
                    "would_skip_zero_entries": would_skip_zero,
                    # Backwards compatible key name (older UI used "fallback to today").
                    # We intentionally keep unknown dates blank now.
                    "unknown_dates_fallback_to_today": unknown_dates,
                    "unknown_dates_left_blank": unknown_dates,
                    "page_number_conflicts": would_page_conflicts,
                },
            }
        )
    finally:
        conn.close()


def _list_db_backups() -> list[dict[str, object]]:
    backup_dir = Path(current_app.config["DATA_ROOT"]) / "backups"
    if not backup_dir.exists():
        return []
    items: list[dict[str, object]] = []
    for p in sorted(backup_dir.glob("*.db"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            st = p.stat()
        except OSError:
            continue
        items.append(
            {
                "name": p.name,
                "bytes": int(st.st_size),
                "modified_at": int(st.st_mtime),
            }
        )
    return items


@bp.route("/settings/db-backups/list", methods=["GET"])
@require_permission("admin.user.manage")
def list_db_backups():
    """List available DB backups under data/backups."""
    try:
        return jsonify({"success": True, "backups": _list_db_backups()})
    except Exception as exc:
        return jsonify({"success": False, "errors": [str(exc)]}), 500


@bp.route("/settings/db-backups/create", methods=["POST"])
@require_permission("admin.user.manage")
def create_db_backup():
    """Create a DB backup immediately."""
    data = request.get_json(silent=True) or {}
    ensure_csrf_token(data)

    # Only allow backing up the main DB.
    if _db_file_path().resolve() != _main_db_path().resolve():
        return jsonify({"success": False, "errors": [T("data_import_commit_only_main_db")]}), 400

    try:
        backup_path = _create_db_backup()
        return jsonify(
            {
                "success": True,
                "message": T("db_backup_created"),
                "backup_name": backup_path.name,
                "backups": _list_db_backups(),
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "errors": [str(exc)]}), 500


@bp.route("/settings/db-backups/download/<name>", methods=["GET"])
@require_permission("admin.user.manage")
def download_db_backup(name: str):
    safe = (name or "").strip()
    if not safe or "/" in safe or "\\" in safe or not safe.endswith(".db"):
        abort(404)
    backup_path = Path(current_app.config["DATA_ROOT"]) / "backups" / safe
    if not backup_path.exists():
        abort(404)
    return send_file(
        io.BytesIO(backup_path.read_bytes()),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=safe,
    )


def _restore_marker_path() -> Path:
    return Path(current_app.config["DATA_ROOT"]) / "restore_pending.json"


@bp.route("/settings/db-backups/restore", methods=["POST"])
@require_permission("admin.user.manage")
def restore_db_backup():
    """Request restoring a backup on next startup, then attempt to close the app.

    Restoring while the app is running is risky (open DB connections). The safe
    workflow is:
      1) Create a backup of the current DB.
      2) Write a small marker file that tells the app which backup to restore.
      3) Shut down the server so the next start can safely swap the DB.
    """
    data = request.get_json(silent=True) or {}
    ensure_csrf_token(data)

    if _db_file_path().resolve() != _main_db_path().resolve():
        return jsonify({"success": False, "errors": [T("data_import_commit_only_main_db")]}), 400

    name = (data.get("name") or "").strip()
    if not name or "/" in name or "\\" in name or not name.endswith(".db"):
        return jsonify({"success": False, "errors": [T("db_backup_invalid")]}), 400

    backup_path = Path(current_app.config["DATA_ROOT"]) / "backups" / name
    if not backup_path.exists():
        return jsonify({"success": False, "errors": [T("db_backup_not_found")]}), 404

    # Safety backup of current state before restoring.
    try:
        safety_backup = _create_db_backup()
    except Exception as exc:
        return jsonify({"success": False, "errors": [f"{T('data_import_backup_failed')}: {exc}"]}), 500

    marker = {
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "backup_name": name,
        "safety_backup_name": safety_backup.name,
    }
    try:
        _restore_marker_path().write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        return jsonify({"success": False, "errors": [str(exc)]}), 500

    # Best-effort shutdown. If it fails, the UI will instruct the user to close manually.
    try:
        shutdown = request.environ.get("werkzeug.server.shutdown")
        if callable(shutdown):
            shutdown()
        else:
            import threading
            import os

            def _exit():
                os._exit(0)

            threading.Timer(0.75, _exit).start()
    except Exception:
        pass

    return jsonify(
        {
            "success": True,
            "message": T("db_backup_restore_scheduled"),
            "backup_name": name,
            "safety_backup_name": safety_backup.name,
        }
    )


@bp.route("/users/<user_id>", methods=["GET"])
@bp.route("/settings/users/<user_id>", methods=["GET"])
@require_permission("admin.user.manage")
def get_user(user_id: str):
    """Get user data for editing via AJAX."""
    session = db.session()
    try:
        # Load user with roles relationship
        user = session.execute(
            select(User).options(selectinload(User.roles)).where(User.id == user_id)
        ).unique().scalars().one_or_none()
        
        if not user:
            return jsonify({"success": False, "errors": ["User not found"]}), 404

        return jsonify({
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "phone": user.phone,
                "is_active": user.is_active,
                "roles": [role.id for role in user.roles]
            }
        })
    finally:
        session.close()


@bp.route("/roles/<int:role_id>", methods=["GET"])
@bp.route("/settings/roles/<int:role_id>", methods=["GET"])
@require_permission("admin.user.manage")
def get_role(role_id: int):
    """Get role data for editing via AJAX."""
    session = db.session()
    try:
        # Load role with permissions relationship
        role = session.execute(
            select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id)
        ).unique().scalars().one_or_none()
        
        if not role:
            return jsonify({"success": False, "errors": ["Role not found"]}), 404

        return jsonify({
            "success": True,
            "role": {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "permissions": [perm.id for perm in role.permissions]
            }
        })
    finally:
        session.close()


# --- Patient Settings API ---

@bp.route("/api/admin/settings", methods=["GET"])
@require_permission("admin.user.manage")
def get_patient_settings():
    """Get current patient settings."""
    try:
        from clinic_app.services.patient_pages import AdminSettingsService
        
        service = AdminSettingsService()
        settings = service.get_all_settings()
        
        return jsonify({
            "success": True,
            "settings": settings
        })
    except Exception as e:
        return jsonify({"success": False, "errors": [str(e)]}), 500


@bp.route("/api/admin/settings", methods=["POST"])
@require_permission("admin.user.manage")
@csrf.exempt
def update_patient_settings():
    """Update patient settings."""
    try:
        data = request.get_json() or {}
        ensure_csrf_token(data)
        
        from clinic_app.services.patient_pages import AdminSettingsService
        
        service = AdminSettingsService()
        
        # Extract settings from request data
        settings_to_update = {
            'enable_file_numbers': data.get('enable_file_numbers', False),
            'require_page_numbers': data.get('require_page_numbers', False),
            'default_page_format': data.get('default_page_format', 'numeric'),
            'custom_page_format': data.get('custom_page_format', ''),
            'page_ranges': data.get('page_ranges', [])
        }
        
        service.update_settings(settings_to_update)
        
        return jsonify({
            "success": True,
            "message": "Patient settings updated successfully"
        })
    except Exception as e:
        return jsonify({"success": False, "errors": [str(e)]}), 500


@bp.route("/api/admin/settings/page-numbers", methods=["GET"])
@require_permission("admin.user.manage")
def get_page_number_settings():
    """Get page number specific settings."""
    try:
        from clinic_app.services.patient_pages import AdminSettingsService
        
        service = AdminSettingsService()
        settings = service.get_all_settings()
        
        page_settings = {
            'enable_file_numbers': settings.get('enable_file_numbers', False),
            'require_page_numbers': settings.get('require_page_numbers', False),
            'default_page_format': settings.get('default_page_format', 'numeric'),
            'custom_page_format': settings.get('custom_page_format', ''),
            'page_ranges': settings.get('page_ranges', [])
        }
        
        return jsonify({
            "success": True,
            "page_settings": page_settings
        })
    except Exception as e:
        return jsonify({"success": False, "errors": [str(e)]}), 500


def _audit_payments_filters() -> tuple[dict[str, object], str]:
    """Build SQL WHERE filters for payments audit log."""
    params: dict[str, object] = {}
    where = ["a.entity='payment'", "a.action IN ('payment_create','payment_update','payment_delete')"]

    action = (request.args.get("action") or "").strip()
    if action in {"payment_create", "payment_update", "payment_delete"}:
        where.append("a.action = :action")
        params["action"] = action

    user_q = (request.args.get("user") or "").strip()
    if user_q:
        where.append("(u.username LIKE :user_like)")
        params["user_like"] = f"%{user_q}%"

    def _date_bound(name: str, *, end_of_day: bool) -> str | None:
        raw = (request.args.get(name) or "").strip()
        if not raw:
            return None
        try:
            d = datetime.fromisoformat(raw).date()
        except Exception:
            try:
                d = datetime.strptime(raw, "%Y-%m-%d").date()
            except Exception:
                return None
        if end_of_day:
            return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc).isoformat()
        return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc).isoformat()

    from_ts = _date_bound("from", end_of_day=False)
    if from_ts:
        where.append("a.ts >= :from_ts")
        params["from_ts"] = from_ts

    to_ts = _date_bound("to", end_of_day=True)
    if to_ts:
        where.append("a.ts <= :to_ts")
        params["to_ts"] = to_ts

    return params, " AND ".join(where)

def _audit_log_meta_expr(session) -> tuple[bool, str]:
    """Return (table_exists, sql_expr) for a.meta_json field.

    Older clinic DBs may have either:
      - audit_log.meta_json_redacted (newer)
      - audit_log.meta_json (older)
    If neither exists, we fall back to '{}' so audit still loads.
    """
    try:
        cols = session.execute(text("PRAGMA table_info(audit_log)")).mappings().all()
    except Exception:
        # If introspection fails, assume the modern column exists and let the core query fallback handle errors.
        return True, "COALESCE(a.meta_json_redacted, '{}')"

    if not cols:
        return False, "'{}'"

    names = {str(r.get("name") or "") for r in cols}
    if "meta_json_redacted" in names:
        return True, "COALESCE(a.meta_json_redacted, '{}')"
    if "meta_json" in names:
        return True, "COALESCE(a.meta_json, '{}')"
    return True, "'{}'"

def _load_patients_for_ids(session, patient_ids: set[str]) -> dict[str, dict[str, str]]:
    if not patient_ids:
        return {}
    stmt = (
        text(
            """
            SELECT id, full_name, short_id, phone, primary_page_number
              FROM patients
             WHERE id IN :ids
            """
        )
        .bindparams(bindparam("ids", expanding=True))
    )
    try:
        rows = session.execute(stmt, {"ids": sorted(patient_ids)}).mappings().all()
    except OperationalError:
        # Backwards compatibility for DBs without page-number columns.
        stmt_fallback = (
            text(
                """
                SELECT id, full_name, short_id, phone
                  FROM patients
                 WHERE id IN :ids
                """
            )
            .bindparams(bindparam("ids", expanding=True))
        )
        rows = session.execute(stmt_fallback, {"ids": sorted(patient_ids)}).mappings().all()
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        out[str(r.get("id") or "")] = {
            "id": str(r.get("id") or ""),
            "full_name": str(r.get("full_name") or ""),
            "short_id": str(r.get("short_id") or ""),
            "phone": str(r.get("phone") or ""),
            "primary_page_number": str(r.get("primary_page_number") or ""),
        }
    return out

def _patient_display(patient_row: dict[str, str] | None) -> str:
    if not patient_row:
        return ""
    name = (patient_row.get("full_name") or "").strip()
    file_no = (patient_row.get("short_id") or "").strip()
    page_no = (patient_row.get("primary_page_number") or "").strip()
    phone = (patient_row.get("phone") or "").strip()
    parts: list[str] = []
    if file_no:
        parts.append(file_no)
    if page_no:
        parts.append(f"Pg {page_no}")
    if name:
        parts.append(name)
    if phone:
        parts.append(phone)
    return " · ".join(parts) if parts else ""

def _load_payments_patient_ids(session, payment_ids: set[str]) -> dict[str, str]:
    if not payment_ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT id, patient_id
              FROM payments
             WHERE id IN :ids
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": sorted(payment_ids)},
    ).mappings().all()
    out: dict[str, str] = {}
    for r in rows:
        pid = str(r.get("patient_id") or "").strip()
        if pid:
            out[str(r.get("id") or "")] = pid
    return out

def _audit_ts_display(ts_value: str) -> str:
    s = (ts_value or "").strip()
    if not s:
        return ""
    normalized = s
    if "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(normalized)
    except Exception:
        return s
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def _admin_setting_get(session, key: str) -> str | None:
    try:
        row = session.execute(
            text("SELECT setting_value FROM admin_settings WHERE setting_key = :k LIMIT 1"),
            {"k": key},
        ).first()
        if not row:
            return None
        return str(row[0]) if row[0] is not None else None
    except Exception:
        return None

def _admin_setting_set(session, key: str, value: str, setting_type: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    existing = None
    try:
        existing = session.execute(
            text("SELECT id FROM admin_settings WHERE setting_key = :k LIMIT 1"),
            {"k": key},
        ).scalar()
    except Exception:
        existing = None

    if existing:
        session.execute(
            text(
                """
                UPDATE admin_settings
                   SET setting_value = :v,
                       setting_type = :t,
                       updated_at = :u
                 WHERE setting_key = :k
                """
            ),
            {"k": key, "v": value, "t": setting_type, "u": now},
        )
    else:
        session.execute(
            text(
                """
                INSERT INTO admin_settings (id, setting_key, setting_value, setting_type, updated_at)
                VALUES (:id, :k, :v, :t, :u)
                """
            ),
            {"id": str(uuid4()), "k": key, "v": value, "t": setting_type, "u": now},
        )

def _audit_snapshot_enabled(session) -> bool:
    raw = _admin_setting_get(session, "audit_payments_snapshots_enabled")
    if raw is None:
        return True
    return raw.strip().lower() == "true"

def _audit_snapshot_retention_days(session) -> int:
    raw = _admin_setting_get(session, "audit_payments_snapshots_retention_days")
    if raw is None:
        return 180
    try:
        return int(str(raw).strip())
    except Exception:
        return 180

def _audit_snapshot_last_purge_epoch(session) -> int:
    raw = _admin_setting_get(session, "audit_payments_snapshots_last_purge_epoch")
    if raw is None:
        return 0
    try:
        return int(str(raw).strip())
    except Exception:
        return 0

def _load_audit_snapshots_for_ids(session, audit_log_ids: set[int]) -> dict[int, dict[str, str]]:
    if not audit_log_ids:
        return {}
    stmt = (
        text(
            """
            SELECT audit_log_id, patient_id, patient_full_name, patient_short_id, patient_primary_page_number
              FROM audit_patient_snapshots
             WHERE audit_log_id IN :ids
            """
        )
        .bindparams(bindparam("ids", expanding=True))
    )
    try:
        rows = session.execute(stmt, {"ids": sorted(audit_log_ids)}).mappings().all()
    except Exception:
        return {}
    out: dict[int, dict[str, str]] = {}
    for r in rows:
        try:
            aid = int(r.get("audit_log_id") or 0)
        except Exception:
            continue
        out[aid] = {
            "patient_id": str(r.get("patient_id") or ""),
            "patient_full_name": str(r.get("patient_full_name") or ""),
            "patient_short_id": str(r.get("patient_short_id") or ""),
            "patient_primary_page_number": str(r.get("patient_primary_page_number") or ""),
        }
    return out

def _snapshot_display(snap: dict[str, str] | None) -> str:
    if not snap:
        return ""
    name = (snap.get("patient_full_name") or "").strip()
    file_no = (snap.get("patient_short_id") or "").strip()
    page_no = (snap.get("patient_primary_page_number") or "").strip()
    parts: list[str] = []
    if file_no:
        parts.append(file_no)
    if page_no:
        parts.append(f"Pg {page_no}")
    if name:
        parts.append(name)
    return " · ".join(parts) if parts else ""

def _parse_ts_epoch(ts_value: str) -> int:
    s = (ts_value or "").strip()
    if not s:
        return int(datetime.now(timezone.utc).timestamp())
    normalized = s
    if "T" not in normalized and " " in normalized:
        normalized = normalized.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(normalized)
    except Exception:
        return int(datetime.now(timezone.utc).timestamp())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())

def _maybe_auto_purge_audit_snapshots(session) -> int:
    if not _audit_snapshot_enabled(session):
        return 0
    retention_days = _audit_snapshot_retention_days(session)
    if retention_days <= 0:
        return 0
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    last_purge = _audit_snapshot_last_purge_epoch(session)
    if (now_epoch - last_purge) < 86400:
        return 0
    cutoff = now_epoch - (retention_days * 86400)
    try:
        res = session.execute(
            text("DELETE FROM audit_patient_snapshots WHERE audit_ts_epoch < :cutoff"),
            {"cutoff": cutoff},
        )
        _admin_setting_set(session, "audit_payments_snapshots_last_purge_epoch", str(now_epoch), "int")
        session.commit()
        return int(getattr(res, "rowcount", 0) or 0)
    except Exception:
        session.rollback()
        return 0

@bp.route("/settings/audit/payments.json", methods=["GET"])
@require_permission("admin.user.manage")
def audit_payments_json():
    """Return payments audit log entries for Admin Settings tab."""
    session = db.session()
    warnings: list[str] = []
    try:
        _maybe_auto_purge_audit_snapshots(session)
        params, where_sql = _audit_payments_filters()
        table_ok, meta_expr = _audit_log_meta_expr(session)
        if not table_ok:
            return jsonify({"success": False, "errors": ["audit table missing"]}), 200
        try:
            limit = int(request.args.get("limit") or "300")
        except Exception:
            limit = 300
        limit = max(1, min(limit, 1000))
        params["limit"] = limit

        try:
            rows = session.execute(
                text(
                    f"""
                    SELECT a.id AS audit_log_id, a.ts, a.action, a.entity_id, a.actor_user_id,
                           COALESCE(u.username, '') AS actor_username,
                           {meta_expr} AS meta_json
                      FROM audit_log a
                      LEFT JOIN users u ON u.id = a.actor_user_id
                     WHERE {where_sql}
                     ORDER BY a.ts DESC
                     LIMIT :limit
                    """
                ),
                params,
            ).mappings().all()
        except Exception as e:
            msg = str(e) or ""
            if "no such table: audit_log" in msg:
                return jsonify({"success": False, "errors": ["audit table missing"]}), 200
            # Some DBs use meta_json instead of meta_json_redacted; attempt a single fallback.
            if "no such column" in msg and "meta_json_redacted" in msg:
                try:
                    rows = session.execute(
                        text(
                            f"""
                            SELECT a.id AS audit_log_id, a.ts, a.action, a.entity_id, a.actor_user_id,
                                   COALESCE(u.username, '') AS actor_username,
                                   COALESCE(a.meta_json, '{{}}') AS meta_json
                              FROM audit_log a
                              LEFT JOIN users u ON u.id = a.actor_user_id
                             WHERE {where_sql}
                             ORDER BY a.ts DESC
                             LIMIT :limit
                            """
                        ),
                        params,
                    ).mappings().all()
                except Exception as e2:
                    return jsonify({"success": False, "errors": [f"audit query failed: {e2}"]}), 200
            else:
                # Core query failed: return a readable error (do not 500 the page).
                return jsonify({"success": False, "errors": [f"audit query failed: {e}"]}), 200

        items: list[dict[str, object]] = []
        patient_ids: set[str] = set()
        payment_ids: set[str] = set()
        audit_ids: set[int] = set()
        for r in rows:
            meta: dict[str, object] = {}
            try:
                loaded = json.loads(r.get("meta_json") or "{}")
                if isinstance(loaded, dict):
                    meta = loaded
            except Exception:
                meta = {}

            pid = (str(meta.get("patient_id") or "")).strip()
            if pid:
                patient_ids.add(pid)

            entity_id = (str(r.get("entity_id") or "")).strip()
            if entity_id:
                payment_ids.add(entity_id)

            audit_log_id = 0
            try:
                audit_log_id = int(r.get("audit_log_id") or 0)
            except Exception:
                audit_log_id = 0
            if audit_log_id:
                audit_ids.add(audit_log_id)

            items.append(
                {
                    "ts": r.get("ts") or "",
                    "ts_display": _audit_ts_display(r.get("ts") or ""),
                    "action": (str(r.get("action") or "").strip()),
                    "entity_id": entity_id,
                    "actor_user_id": r.get("actor_user_id") or "",
                    "actor_username": r.get("actor_username") or "",
                    "meta": meta,
                    "audit_log_id": audit_log_id,
                }
            )

        try:
            payment_patient = _load_payments_patient_ids(session, payment_ids)
        except Exception as e:
            payment_patient = {}
            warnings.append(f"payments lookup failed: {e}")
        for it in items:
            if not isinstance(it.get("meta"), dict):
                it["meta"] = {}
            meta = it.get("meta") if isinstance(it.get("meta"), dict) else {}
            if isinstance(meta, dict):
                pid = (meta.get("patient_id") or "").strip()
                if not pid:
                    pid = (payment_patient.get(str(it.get("entity_id") or "")) or "").strip()
                    if pid:
                        meta["patient_id"] = pid
                if pid:
                    patient_ids.add(pid)

        try:
            patients = _load_patients_for_ids(session, patient_ids)
        except Exception as e:
            patients = {}
            warnings.append(f"patients lookup failed: {e}")
        try:
            snapshots = _load_audit_snapshots_for_ids(session, audit_ids)
        except Exception as e:
            snapshots = {}
            warnings.append(f"snapshots lookup failed: {e}")
        for it in items:
            meta = it.get("meta") if isinstance(it.get("meta"), dict) else {}
            pid = (meta.get("patient_id") or "").strip() if isinstance(meta, dict) else ""
            prow = patients.get(pid) if pid else None
            it["patient"] = prow or {"id": pid, "full_name": "", "short_id": "", "phone": "", "primary_page_number": ""}

            display = _patient_display(prow)
            if not display:
                try:
                    aid = int(it.get("audit_log_id") or 0)
                except Exception:
                    aid = 0
                display = _snapshot_display(snapshots.get(aid))
            it["patient_display"] = display or T("unknown_patient")

        payload: dict[str, object] = {"success": True, "items": items}
        if warnings:
            payload["warnings"] = warnings[:10]
        return jsonify(payload)
    except Exception as e:
        # Safety: never crash the whole tab due to an enrichment failure.
        return jsonify({"success": True, "items": [], "warnings": [f"audit unexpected error: {e}"]})
    finally:
        session.close()


@bp.route("/settings/audit/payments.csv", methods=["GET"])
@require_permission("admin.user.manage")
def audit_payments_csv():
    """Export payments audit log as CSV."""
    session = db.session()
    try:
        params, where_sql = _audit_payments_filters()
        table_ok, meta_expr = _audit_log_meta_expr(session)
        if not table_ok:
            return jsonify({"success": False, "errors": ["audit table missing"]}), 200
        rows = session.execute(
            text(
                f"""
                SELECT a.id AS audit_log_id, a.ts, a.action, a.entity_id,
                       COALESCE(u.username, '') AS actor_username,
                       {meta_expr} AS meta_json
                  FROM audit_log a
                  LEFT JOIN users u ON u.id = a.actor_user_id
                 WHERE {where_sql}
                 ORDER BY a.ts DESC
                 LIMIT 5000
                """
            ),
            params,
        ).mappings().all()

        patient_ids: set[str] = set()
        payment_ids: set[str] = set()
        audit_ids: set[int] = set()
        metas: list[dict[str, object]] = []
        for r in rows:
            meta = {}
            try:
                meta = json.loads(r.get("meta_json") or "{}")
            except Exception:
                meta = {}
            metas.append(meta if isinstance(meta, dict) else {})
            pid = (meta.get("patient_id") or "").strip() if isinstance(meta, dict) else ""
            if pid:
                patient_ids.add(pid)
            entity_id = (r.get("entity_id") or "").strip()
            if entity_id:
                payment_ids.add(entity_id)
            try:
                audit_ids.add(int(r.get("audit_log_id") or 0))
            except Exception:
                pass
        payment_patient = _load_payments_patient_ids(session, payment_ids)
        for meta_idx, r in enumerate(rows):
            meta = metas[meta_idx] if meta_idx < len(metas) else {}
            if not isinstance(meta, dict):
                continue
            pid = (meta.get("patient_id") or "").strip()
            if not pid:
                pid = (payment_patient.get(str(r.get("entity_id") or "")) or "").strip()
                if pid:
                    meta["patient_id"] = pid
                    patient_ids.add(pid)
        patients = _load_patients_for_ids(session, patient_ids)
        snapshots = _load_audit_snapshots_for_ids(session, audit_ids)

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ts", "user", "action", "payment_id", "patient", "file_no", "page_no", "paid_at", "amount", "method", "doctor"])
        for idx, r in enumerate(rows):
            meta = metas[idx] if idx < len(metas) else {}
            pid = (meta.get("patient_id") or "").strip() if isinstance(meta, dict) else ""
            prow = patients.get(pid) if pid else None
            try:
                aid = int(r.get("audit_log_id") or 0)
            except Exception:
                aid = 0
            snap = snapshots.get(aid)
            w.writerow(
                [
                    _audit_ts_display(r.get("ts") or "") or (r.get("ts") or ""),
                    r.get("actor_username") or "",
                    r.get("action") or "",
                    r.get("entity_id") or "",
                    (prow.get("full_name") if prow else (snap.get("patient_full_name") if snap else "")) or "",
                    (prow.get("short_id") if prow else (snap.get("patient_short_id") if snap else "")) or "",
                    (prow.get("primary_page_number") if prow else (snap.get("patient_primary_page_number") if snap else "")) or "",
                    meta.get("paid_at") or "",
                    (meta.get("amount_cents") or 0) / 100 if isinstance(meta.get("amount_cents"), (int, float)) else "",
                    meta.get("method") or "",
                    meta.get("doctor_label") or "",
                ]
            )
        buf.seek(0)
        ts = datetime.now().strftime("%Y%m%d-%H%M")
        return send_file(
            io.BytesIO(buf.read().encode("utf-8-sig")),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"payments-audit-{ts}.csv",
        )
    finally:
        session.close()


@bp.route("/settings/audit/payments/privacy.json", methods=["GET"])
@require_permission("admin.user.manage")
def audit_payments_privacy_json():
    session = db.session()
    try:
        enabled = _audit_snapshot_enabled(session)
        retention_days = _audit_snapshot_retention_days(session)
        last_purge = _audit_snapshot_last_purge_epoch(session)
        count = 0
        table_ok = True
        try:
            count = int(session.execute(text("SELECT COUNT(*) FROM audit_patient_snapshots")).scalar() or 0)
        except Exception:
            table_ok = False
            count = 0
        return jsonify(
            {
                "success": True,
                "enabled": enabled,
                "retention_days": retention_days,
                "last_purge_epoch": last_purge,
                "snapshot_count": count,
                "snapshots_available": table_ok,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "errors": [str(e)]}), 500
    finally:
        session.close()


@bp.route("/settings/audit/payments/privacy", methods=["POST"])
@require_permission("admin.user.manage")
def audit_payments_privacy_save():
    session = db.session()
    try:
        data = request.get_json() or {}
        ensure_csrf_token(data)
        enabled = bool(data.get("enabled", True))
        try:
            retention_days = int(data.get("retention_days", 180))
        except Exception:
            retention_days = 180
        retention_days = max(0, min(retention_days, 3650))

        _admin_setting_set(session, "audit_payments_snapshots_enabled", "true" if enabled else "false", "boolean")
        _admin_setting_set(session, "audit_payments_snapshots_retention_days", str(retention_days), "int")
        session.commit()
        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        return jsonify({"success": False, "errors": [str(e)]}), 500
    finally:
        session.close()


@bp.route("/settings/audit/payments/privacy/purge-expired", methods=["POST"])
@require_permission("admin.user.manage")
def audit_payments_privacy_purge_expired():
    session = db.session()
    try:
        data = request.get_json() or {}
        ensure_csrf_token(data)
        if not _audit_snapshot_enabled(session):
            return jsonify({"success": True, "deleted": 0})
        retention_days = _audit_snapshot_retention_days(session)
        if retention_days <= 0:
            return jsonify({"success": True, "deleted": 0})
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        cutoff = now_epoch - (retention_days * 86400)
        res = session.execute(
            text("DELETE FROM audit_patient_snapshots WHERE audit_ts_epoch < :cutoff"),
            {"cutoff": cutoff},
        )
        _admin_setting_set(session, "audit_payments_snapshots_last_purge_epoch", str(now_epoch), "int")
        session.commit()
        return jsonify({"success": True, "deleted": int(getattr(res, "rowcount", 0) or 0)})
    except Exception as e:
        session.rollback()
        return jsonify({"success": False, "errors": [str(e)]}), 500
    finally:
        session.close()


@bp.route("/settings/audit/payments/privacy/purge-all", methods=["POST"])
@require_permission("admin.user.manage")
def audit_payments_privacy_purge_all():
    session = db.session()
    try:
        data = request.get_json() or {}
        ensure_csrf_token(data)
        res = session.execute(text("DELETE FROM audit_patient_snapshots"))
        now_epoch = int(datetime.now(timezone.utc).timestamp())
        _admin_setting_set(session, "audit_payments_snapshots_last_purge_epoch", str(now_epoch), "int")
        session.commit()
        return jsonify({"success": True, "deleted": int(getattr(res, "rowcount", 0) or 0)})
    except Exception as e:
        session.rollback()
        return jsonify({"success": False, "errors": [str(e)]}), 500
    finally:
        session.close()


@bp.route("/settings/audit/payments/privacy/backfill", methods=["POST"])
@require_permission("admin.user.manage")
def audit_payments_privacy_backfill():
    session = db.session()
    try:
        data = request.get_json() or {}
        ensure_csrf_token(data)
        # Find audit rows missing a snapshot. Backfill only where patient still exists.
        rows = session.execute(
            text(
                """
                SELECT a.id AS audit_log_id, a.ts, COALESCE(a.meta_json_redacted, '{}') AS meta_json
                  FROM audit_log a
                  LEFT JOIN audit_patient_snapshots s ON s.audit_log_id = a.id
                 WHERE a.entity = 'payment'
                   AND a.action IN ('payment_create','payment_update','payment_delete')
                   AND s.audit_log_id IS NULL
                 ORDER BY a.id DESC
                 LIMIT 5000
                """
            )
        ).mappings().all()

        metas: list[dict[str, object]] = []
        audit_patient: dict[int, str] = {}
        patient_ids: set[str] = set()
        for r in rows:
            meta = {}
            try:
                meta = json.loads(r.get("meta_json") or "{}")
            except Exception:
                meta = {}
            metas.append(meta if isinstance(meta, dict) else {})
            pid = (meta.get("patient_id") or "").strip() if isinstance(meta, dict) else ""
            try:
                aid = int(r.get("audit_log_id") or 0)
            except Exception:
                aid = 0
            if aid and pid:
                audit_patient[aid] = pid
                patient_ids.add(pid)

        patients = _load_patients_for_ids(session, patient_ids)
        inserted = 0
        for r in rows:
            try:
                aid = int(r.get("audit_log_id") or 0)
            except Exception:
                continue
            pid = audit_patient.get(aid, "")
            prow = patients.get(pid) if pid else None
            if not prow:
                continue
            epoch = _parse_ts_epoch(r.get("ts") or "")
            try:
                session.execute(
                    text(
                        """
                        INSERT OR IGNORE INTO audit_patient_snapshots
                            (audit_log_id, audit_ts_epoch, patient_id, patient_full_name, patient_short_id, patient_primary_page_number)
                        VALUES
                            (:aid, :epoch, :pid, :name, :short_id, :page_no)
                        """
                    ),
                    {
                        "aid": aid,
                        "epoch": epoch,
                        "pid": pid,
                        "name": prow.get("full_name") or "",
                        "short_id": prow.get("short_id") or "",
                        "page_no": prow.get("primary_page_number") or "",
                    },
                )
                inserted += 1
            except Exception:
                continue

        session.commit()
        return jsonify({"success": True, "checked": len(rows), "inserted": inserted})
    except Exception as e:
        session.rollback()
        return jsonify({"success": False, "errors": [str(e)]}), 500
    finally:
        session.close()


@bp.route("/settings/audit/payments/snapshots.json", methods=["GET"])
@require_permission("admin.user.manage")
def audit_payments_snapshots_json():
    session = db.session()
    try:
        params, where_sql = _audit_payments_filters()

        q = (request.args.get("q") or "").strip()
        if q:
            params["q"] = f"%{q}%"
            where_sql = (
                where_sql
                + " AND (s.patient_full_name LIKE :q OR s.patient_short_id LIKE :q OR s.patient_primary_page_number LIKE :q)"
            )

        try:
            limit = int(request.args.get("limit") or "200")
        except Exception:
            limit = 200
        limit = max(1, min(limit, 1000))

        try:
            offset = int(request.args.get("offset") or "0")
        except Exception:
            offset = 0
        offset = max(0, min(offset, 200000))

        params["limit"] = limit + 1
        params["offset"] = offset

        try:
            rows = session.execute(
                text(
                    f"""
                    SELECT a.id AS audit_log_id,
                           a.ts,
                           a.action,
                           a.entity_id AS payment_id,
                           s.patient_full_name,
                           s.patient_short_id,
                           s.patient_primary_page_number
                      FROM audit_patient_snapshots s
                      JOIN audit_log a ON a.id = s.audit_log_id
                      LEFT JOIN users u ON u.id = a.actor_user_id
                     WHERE {where_sql}
                     ORDER BY a.ts DESC
                     LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            ).mappings().all()
        except OperationalError:
            return jsonify({"success": True, "items": [], "has_more": False, "snapshots_available": False})

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        items: list[dict[str, object]] = []
        for r in rows:
            snap = {
                "patient_full_name": str(r.get("patient_full_name") or ""),
                "patient_short_id": str(r.get("patient_short_id") or ""),
                "patient_primary_page_number": str(r.get("patient_primary_page_number") or ""),
            }
            items.append(
                {
                    "audit_log_id": r.get("audit_log_id") or 0,
                    "ts": r.get("ts") or "",
                    "ts_display": _audit_ts_display(r.get("ts") or ""),
                    "action": r.get("action") or "",
                    "payment_id": r.get("payment_id") or "",
                    "patient_display": _snapshot_display(snap) or T("unknown_patient"),
                }
            )

        return jsonify({"success": True, "items": items, "has_more": has_more, "snapshots_available": True})
    except Exception as e:
        return jsonify({"success": False, "errors": [str(e)]}), 500
    finally:
        session.close()
