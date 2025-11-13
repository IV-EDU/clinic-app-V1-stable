"""Authentication blueprint."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, url_for
import logging
from flask_login import login_user, logout_user
from sqlalchemy import select

from clinic_app.services.migrations import run_migrations
from clinic_app.extensions import limiter, db
from clinic_app.forms.auth import LoginForm
from clinic_app.models_rbac import Role, User
from clinic_app.services.security import record_login, record_logout


bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/", methods=["GET"])
def index():
    """Redirect to login page."""
    return redirect(url_for("auth.login"))


def _login_rate_key() -> str:
    username = request.form.get("username", "")
    return f"{request.remote_addr}:{username}"


def _ensure_schema() -> None:
    app = current_app._get_current_object()
    run_migrations(app)


def _users_exist() -> bool:
    try:
        session = db.session()
        try:
            users_exist = session.execute(select(User.id).limit(1)).first() is not None
            current_app.logger.debug(f"[_users_exist] Users exist: {users_exist}")
            return users_exist
        finally:
            session.close()
    except Exception as e:
        current_app.logger.error(f"[_users_exist] Error checking for users: {e}")
        _ensure_schema()
        session = db.session()
        try:
            users_exist = session.execute(select(User.id).limit(1)).first() is not None
            current_app.logger.debug(f"[_users_exist] Users exist after schema ensure: {users_exist}")
            return users_exist
        finally:
            session.close()


def _create_initial_admin(username: str, password: str) -> User:
    session = db.session()
    try:
        user_id = datetime.now(timezone.utc).strftime("admin-%Y%m%d%H%M%S")
        now = datetime.now(timezone.utc).isoformat()
        user = User(
            id=user_id,
            username=username,
            full_name=username,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        user.set_password(password)
        admin_role = (
            session.execute(select(Role).where(Role.name == "Admin"))
            .unique()
            .scalars()
            .one_or_none()
        )
        if admin_role:
            user.roles.append(admin_role)
            user.sync_legacy_role()
        else:
            user.role = "admin"
        session.add(user)
        session.commit()
        # Load all attributes before detaching from session
        session.refresh(user)
        session.expunge(user)
        return user
    finally:
        session.close()


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per 15 minutes", key_func=_login_rate_key, methods=["POST"])
def login():
    form = LoginForm()
    g.nostore = True
    next_url = request.args.get("next") or url_for("index")
    bootstrap_mode = not _users_exist()
    current_app.logger.debug(f"[login] Bootstrap mode: {bootstrap_mode}")

    if form.validate_on_submit():
        if bootstrap_mode:
            current_app.logger.debug("[login] In bootstrap mode, attempting to create initial admin.")
            username = form.username.data.strip()
            password = form.password.data
            if len(username) < 3:
                flash("Username must be at least 3 characters.", "err")
            else:
                user = _create_initial_admin(username, password)
                bootstrap_mode = False
                login_user(user)
                record_login(user, success=True)
                flash("Admin account created and logged in.", "ok")
                return redirect(next_url)
        else:
            session = db.session()
            try:
                # Use SQLAlchemy ORM to load user with relationships
                user = session.execute(
                    select(User).where(User.username == form.username.data.strip())
                ).unique().scalars().one_or_none()
                
                if user and user.is_active and user.check_password(form.password.data):
                    # Load relationships to ensure RBAC works properly
                    session.refresh(user)
                    login_user(user)
                    record_login(user, success=True)
                    flash("Logged in", "ok")
                    return redirect(next_url)
                record_login(None, success=False)
                flash("Invalid credentials", "err")
            finally:
                session.close()
    current_app.logger.debug(f"[login] Form validation result: {form.validate_on_submit()}")

    if request.method == "POST" and not form.validate_on_submit():
        current_app.logger.debug(f"[login] Form validation failed. Errors: {form.errors}")

    return render_template("auth/login.html", form=form, next_url=next_url, bootstrap_mode=bootstrap_mode)


@bp.route("/logout", methods=["POST"])
def logout():
    user = g.get("current_user")
    record_logout(user)
    logout_user()
    flash("Logged out", "ok")
    return redirect(url_for("auth.login"))
