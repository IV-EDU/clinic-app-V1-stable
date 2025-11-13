"""Admin interface for managing roles and permissions."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, request, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from clinic_app.auth import requires
from clinic_app.extensions import db
from clinic_app.models_rbac import Permission, Role, user_roles
from clinic_app.services.i18n import T
from clinic_app.services.ui import render_page

bp = Blueprint("admin_roles", __name__, url_prefix="/admin/roles")


def _all_permissions(session) -> list[Permission]:
    return (
        session.execute(select(Permission).order_by(Permission.code))
        .unique()
        .scalars()
        .all()
    )


def _selected_permission_ids(form_data) -> set[int]:
    ids: set[int] = set()
    for raw in form_data.getlist("permissions"):
        if raw and raw.isdigit():
            ids.add(int(raw))
    return ids


def _selected_permissions(session, ids: set[int]) -> list[Permission]:
    if not ids:
        return []
    stmt = select(Permission).where(Permission.id.in_(ids))
    return session.execute(stmt).unique().scalars().all()


@bp.route("/", methods=["GET"])
@requires("admin.user.manage")
def index():
    session = db.session()
    try:
        roles = session.execute(select(Role).order_by(Role.name)).unique().scalars().all()
        return render_page("admin/roles/index.html", roles=roles)
    finally:
        session.close()


@bp.route("/new", methods=["GET", "POST"])
@requires("admin.user.manage")
def create():
    session = db.session()
    try:
        permissions = _all_permissions(session)
        selected_ids: set[int] = set()
        draft_role: Role | None = None
        if request.method == "POST":
            selected_ids = _selected_permission_ids(request.form)
            name = (request.form.get("name") or "").strip()
            description = (request.form.get("description") or "").strip() or None
            draft_role = Role(name=name, description=description)

            if len(name) < 2:
                flash(T("role_name_required"), "err")
            elif session.scalar(select(Role.id).where(Role.name == name)):
                flash(T("role_exists"), "err")
            else:
                role = Role(name=name, description=description)
                role.permissions = _selected_permissions(session, selected_ids)
                session.add(role)
                session.commit()
                flash(T("role_created"), "ok")
                return redirect(url_for("admin_roles.index"))

        return render_page(
            "admin/roles/form.html",
            role=draft_role,
            permissions=permissions,
            selected_permission_ids=selected_ids,
            mode="create",
            show_back=True,
        )
    finally:
        session.close()


@bp.route("/<int:role_id>/edit", methods=["GET", "POST"])
@requires("admin.user.manage")
def edit(role_id: int):
    session = db.session()
    try:
        stmt = (
            select(Role)
            .options(selectinload(Role.permissions))
            .where(Role.id == role_id)
        )
        role = session.execute(stmt).unique().scalars().one_or_none()
        if not role:
            flash(T("role_not_found"), "err")
            return redirect(url_for("admin_roles.index"))

        permissions = _all_permissions(session)
        selected_ids = {perm.id for perm in role.permissions}

        if request.method == "POST":
            selected_ids = _selected_permission_ids(request.form)
            new_name = (request.form.get("name") or "").strip()
            description = (request.form.get("description") or "").strip() or None
            if len(new_name) < 2:
                flash(T("role_name_required"), "err")
            elif session.scalar(
                select(Role.id).where(Role.name == new_name, Role.id != role.id)
            ):
                flash(T("role_exists"), "err")
            else:
                role.name = new_name
                role.description = description
                role.permissions = _selected_permissions(session, selected_ids)
                session.commit()
                flash(T("role_updated"), "ok")
                return redirect(url_for("admin_roles.index"))

        return render_page(
            "admin/roles/form.html",
            role=role,
            permissions=permissions,
            selected_permission_ids=selected_ids,
            mode="edit",
            show_back=True,
        )
    finally:
        session.close()


@bp.route("/<int:role_id>/delete", methods=["POST"])
@requires("admin.user.manage")
def delete(role_id: int):
    session = db.session()
    try:
        role = session.get(Role, role_id)
        if not role:
            flash(T("role_not_found"), "err")
            return redirect(url_for("admin_roles.index"))

        assigned = session.scalar(
            select(func.count())
            .select_from(user_roles)
            .where(user_roles.c.role_id == role_id)
        )
        if assigned:
            flash("Role is assigned to users and cannot be deleted.", "err")
            return redirect(url_for("admin_roles.index"))

        session.delete(role)
        session.commit()
        flash("Role removed", "ok")
        return redirect(url_for("admin_roles.index"))
    finally:
        session.close()
