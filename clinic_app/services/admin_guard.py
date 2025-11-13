"""Ensure at least one active Admin user exists."""

from __future__ import annotations

from sqlalchemy import select

from clinic_app.extensions import db
from clinic_app.models_rbac import Role, User, user_roles


def ensure_admin_exists() -> None:
    """Assign the Admin role to the first available user if none remain."""

    session = db.session()
    try:
        admin_role = (
            session.execute(select(Role).where(Role.name == "Admin"))
            .unique()
            .scalars()
            .one_or_none()
        )
        if admin_role is None:
            return
        has_admin = session.execute(
            select(user_roles.c.user_id).where(user_roles.c.role_id == admin_role.id).limit(1)
        ).first()
        if has_admin:
            return
        fallback_user = (
            session.execute(select(User).order_by(User.created_at.asc()))
            .scalars()
            .first()
        )
        if not fallback_user:
            return
        fallback_user.roles.append(admin_role)
        fallback_user.sync_legacy_role()
        session.commit()
    finally:
        session.close()
