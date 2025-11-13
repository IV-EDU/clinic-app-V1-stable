from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from clinic_app.auth import requires
from clinic_app.extensions import db
from clinic_app.models_rbac import Role, User, user_roles
from clinic_app.services.admin_guard import ensure_admin_exists


bp = Blueprint("admin_users", __name__, url_prefix="/admin/users")


def _all_roles(session) -> list[Role]:
    """Return all roles ordered by name."""

    return (
        session.execute(select(Role).order_by(Role.name))
        .unique()
        .scalars()
        .all()
    )


def _roles_from_form(session, form_data) -> list[Role]:
    """Resolve role ids from the submitted form into ORM objects."""

    role_ids: list[int] = []
    for raw in form_data.getlist("roles"):
        if raw and raw.isdigit():
            role_ids.append(int(raw))
    if not role_ids:
        return []
    stmt = select(Role).where(Role.id.in_(role_ids))
    return session.execute(stmt).unique().scalars().all()


def _admin_role(session) -> Role | None:
    return (
        session.execute(select(Role).where(Role.name == "Admin"))
            .unique()
            .scalars()
            .one_or_none()
    )


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


@bp.route("/", methods=["GET"])
@requires("admin.user.manage")
def index():
    session = db.session()
    try:
        stmt = (
            select(User)
            .options(selectinload(User.roles))
            .order_by(User.created_at.desc())
        )
        users = session.execute(stmt).unique().scalars().all()
        return render_template("admin/users/index.html", users=users)
    finally:
        session.close()


@bp.route("/new", methods=["GET", "POST"])
@requires("admin.user.manage")
def create():
    session = db.session()
    try:
        roles = _all_roles(session)
        draft_user: SimpleNamespace | None = None
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = (request.form.get("password") or "").strip()
            full_name = (request.form.get("full_name") or "").strip() or username
            phone = (request.form.get("phone") or "").strip() or None
            is_active = bool(request.form.get("is_active"))
            selected_roles = _roles_from_form(session, request.form)
            draft_user = SimpleNamespace(
                id=str(uuid4()),
                username=username,
                full_name=full_name,
                phone=phone,
                is_active=is_active,
                roles=selected_roles,
            )

            errors: list[str] = []
            if len(username) < 3:
                errors.append("Username must be at least 3 characters.")
            if not password:
                errors.append("Password is required.")
            if session.scalar(select(User.id).where(User.username == username)):
                errors.append("Username already exists.")

            if errors:
                for err in errors:
                    flash(err, "err")
            else:
                now = datetime.now(timezone.utc).isoformat()
                new_user = User(
                    id=draft_user.id,
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
                session.commit()
                ensure_admin_exists()
                flash("User created", "ok")
                return redirect(url_for("admin_users.index"))

        return render_template("admin/users/form.html", roles=roles, user=draft_user)
    finally:
        session.close()


@bp.route("/<user_id>/edit", methods=["GET", "POST"])
@requires("admin.user.manage")
def edit(user_id: str):
    session = db.session()
    try:
        stmt = (
            select(User)
            .options(selectinload(User.roles))
            .where(User.id == user_id)
        )
        user = session.execute(stmt).unique().scalars().one_or_none()
        if not user:
            # Fallback: allow addressing by username (e.g. "admin")
            stmt2 = (
                select(User)
                .options(selectinload(User.roles))
                .where(User.username == user_id)
            )
            user = session.execute(stmt2).unique().scalars().one_or_none()
        if not user:
            flash("User not found", "err")
            return redirect(url_for("admin_users.index"))

        roles = _all_roles(session)
        protected_admin = user.username == "admin" or (user.id or "").startswith("admin-")

        if request.method == "POST":
            new_username = (request.form.get("username") or "").strip()
            full_name = (request.form.get("full_name") or "").strip()
            phone = (request.form.get("phone") or "").strip() or None
            is_active = bool(request.form.get("is_active"))
            password = (request.form.get("password") or "").strip()
            selected_roles = _roles_from_form(session, request.form)
            admin_role = _admin_role(session)
            will_be_admin = bool(
                admin_role and any(role.id == admin_role.id for role in selected_roles)
            )
            if not will_be_admin:
                # First: never allow removing the last admin
                if not _has_other_admins(session, getattr(admin_role, "id", None), user.id):
                    flash(
                        "At least one admin account must remain. Assign another Admin before changing this user.",
                        "err",
                    )
                    return render_template("admin/users/form.html", roles=roles, user=user)
                # Then: block demotion of the primary bootstrap admin even if others exist
                if protected_admin:
                    flash("The primary admin account must remain an Admin.", "err")
                    return render_template("admin/users/form.html", roles=roles, user=user)

            if len(new_username) < 3:
                flash("Username must be at least 3 characters.", "err")
                return render_template("admin/users/form.html", roles=roles, user=user)

            duplicate = session.scalar(
                select(User.id).where(User.username == new_username, User.id != user.id)
            )
            if duplicate:
                flash("Username already exists.", "err")
                return render_template("admin/users/form.html", roles=roles, user=user)

            user.username = new_username
            user.full_name = full_name or user.full_name or new_username
            user.phone = phone
            user.is_active = is_active
            user.updated_at = datetime.now(timezone.utc).isoformat()

            if password:
                user.set_password(password)

            user.roles = selected_roles
            user.sync_legacy_role()
            session.commit()
            ensure_admin_exists()
            flash("User updated successfully", "ok")
            return redirect(url_for("admin_users.index"))

        return render_template("admin/users/form.html", roles=roles, user=user)
    finally:
        session.close()


@bp.route("/<user_id>/delete", methods=["POST"])
@requires("admin.user.manage")
def delete(user_id: str):
    session = db.session()
    try:
        user = (
            session.execute(
                select(User)
                .options(selectinload(User.roles))
                .where(User.id == user_id)
            )
            .unique()
            .scalars()
            .one_or_none()
        )
        if not user:
            # Fallback by username
            user = (
                session.execute(
                    select(User)
                    .options(selectinload(User.roles))
                    .where(User.username == user_id)
                )
                .unique()
                .scalars()
                .one_or_none()
            )
        if not user:
            flash("User not found", "err")
        elif current_user.is_authenticated and current_user.id == user.id:
            flash("You cannot delete the account you are currently using.", "err")
        else:
            admin_role = _admin_role(session)
            is_admin = (user.role or "").lower() == "admin" or (
                admin_role and any(role.id == admin_role.id for role in user.roles)
            )
            protected_admin = user.username == "admin" or (user.id or "").startswith("admin-")
            if protected_admin:
                flash("The primary admin account cannot be deleted.", "err")
                return redirect(url_for("admin_users.index"))
            if is_admin and not _has_other_admins(session, getattr(admin_role, "id", None), user.id):
                flash("At least one admin account must remain. Assign another Admin before deleting this user.", "err")
                return redirect(url_for("admin_users.index"))
            session.delete(user)
            session.commit()
            ensure_admin_exists()
            flash("User removed", "ok")
        return redirect(url_for("admin_users.index"))
    finally:
        session.close()
