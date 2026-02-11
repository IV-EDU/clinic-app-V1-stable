"""SQLAlchemy models for RBAC entities."""

from __future__ import annotations

from datetime import datetime, timezone
from flask_login import UserMixin
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

LEGACY_ROLE_CODES = {
    "admin": "admin",
    # Keep legacy `users.role` compatible with older SQLite CHECK constraints
    # that only allow: admin/doctor/assistant. RBAC roles remain the source of
    # truth for permissions.
    "manager": "assistant",
    "doctor": "doctor",
    "reception": "assistant",
    "receptionist": "assistant",
    "receptionist (view only)": "assistant",
}

_ALLOWED_LEGACY_ROLE_VALUES = {"admin", "doctor", "assistant"}

LEGACY_ROLE_DISPLAY = {
    "admin": "Admin",
    "manager": "Manager",
    "doctor": "Doctor",
    "assistant": "Reception",
}

LEGACY_PERMISSION_ALIAS = {
    "patient.view": "patients:view",
    "appointment.manage": "appointments:edit",
    "receipt.manage": "receipts:issue",
    "diagnosis.manage": "diagnostics:view",
    "admin.user.manage": "users:manage",
}

# Reverse lookup so either permission code grants access.
_REVERSE_PERMISSION_ALIAS: dict[str, set[str]] = {}
for old_code, new_code in LEGACY_PERMISSION_ALIAS.items():
    _REVERSE_PERMISSION_ALIAS.setdefault(new_code, set()).add(old_code)


def permission_candidates(code: str) -> set[str]:
    """Return permission codes that should be treated as equivalent."""
    candidates = {code}
    alias = LEGACY_PERMISSION_ALIAS.get(code)
    if alias:
        candidates.add(alias)
    for rev in _REVERSE_PERMISSION_ALIAS.get(code, set()):
        candidates.add(rev)
    return candidates

LEGACY_ROLE_PERMISSIONS = {
    "admin": {
        "patients:view",
        "patients:edit",
        "patients:merge",
        "patients:delete",
        "payments:view",
        "payments:edit",
        "payments:delete",
        "reports:view",
        "appointments:view",
        "appointments:edit",
        "receipts:view",
        "receipts:issue",
        "receipts:reprint",
        "diagnostics:view",
        "backup:create",
        "backup:restore",
        "users:manage",
        "expenses:view",
        "expenses:create",
        "expenses:edit",
        "expenses:delete",
        "expenses:print",
        "suppliers:view",
        "suppliers:manage",
        "materials:view",
        "materials:manage",
    },
    "manager": {
        "patients:view",
        "patients:edit",
        "patients:merge",
        "patients:delete",
        "payments:view",
        "payments:edit",
        "payments:delete",
        "reports:view",
        "appointments:view",
        "appointments:edit",
        "receipts:view",
        "receipts:issue",
        "receipts:reprint",
        "diagnostics:view",
        "backup:create",
        "backup:restore",
        "users:manage",
        "expenses:view",
        "expenses:create",
        "expenses:edit",
        "expenses:delete",
        "expenses:print",
        "suppliers:view",
        "suppliers:manage",
        "materials:view",
        "materials:manage",
    },
    "doctor": {
        "patients:view",
        "patients:edit",
        "payments:view",
        "payments:edit",
        "reports:view",
        "appointments:view",
        "appointments:edit",
        "receipts:view",
        "receipts:issue",
        "diagnostics:view",
        "expenses:view",
        "expenses:create",
        "expenses:edit",
        "expenses:print",
        "suppliers:view",
        "materials:view",
    },
    "assistant": {
        "patients:view",
        "patients:edit",
        "payments:view",
        "payments:edit",
        "appointments:view",
        "appointments:edit",
        "receipts:view",
        "receipts:issue",
        "expenses:view",
        "expenses:create",
        "suppliers:view",
        "materials:view",
    },
}


class Base(DeclarativeBase):
    pass


role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "permission_id",
        Integer,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    roles: Mapped[list["Role"]] = relationship(
        "Role",
        secondary=role_permissions,
        back_populates="permissions",
        lazy="joined",
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    permissions: Mapped[list[Permission]] = relationship(
        Permission,
        secondary=role_permissions,
        back_populates="roles",
        lazy="joined",
    )
    users: Mapped[list["User"]] = relationship(
        "User",
        secondary=user_roles,
        back_populates="roles",
    )

    def has_permission(self, code: str) -> bool:
        return any(permission.code == code for permission in self.permissions)


class User(Base, UserMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    roles: Mapped[list[Role]] = relationship(
        Role,
        secondary=user_roles,
        back_populates="users",
        lazy="joined",
    )

    # legacy column retained for compatibility but unused in RBAC
    role: Mapped[str | None] = mapped_column("role", Text, nullable=True)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def has_permission(self, code: str) -> bool:
        candidates = permission_candidates(code)
        # When RBAC roles are assigned, trust role permissions only.
        # Legacy users.role fallback is for older records that have no RBAC role links yet.
        if self.roles:
            return any(any(role.has_permission(c) for c in candidates) for role in self.roles)
        legacy_role = (self.role or "").lower()
        if not legacy_role:
            return False
        allowed = LEGACY_ROLE_PERMISSIONS.get(legacy_role, set())
        if not allowed:
            return False
        return any(c in allowed for c in candidates)

    @property
    def primary_role_name(self) -> str | None:
        if self.roles:
            return self.roles[0].name
        legacy = LEGACY_ROLE_DISPLAY.get((self.role or "").lower())
        return legacy

    def sync_legacy_role(self) -> None:
        # Keep `users.role` within the legacy CHECK constraint (admin/doctor/assistant).
        # RBAC roles remain the source of truth for permissions, but older DBs still
        # enforce the legacy constraint.
        role_names = {str(role.name or "").strip().lower() for role in (self.roles or [])}

        # Deterministic priority so an Admin that also has other roles stays "admin".
        for preferred in ("admin", "doctor", "manager", "reception", "receptionist", "receptionist (view only)"):
            if preferred in role_names:
                mapped = LEGACY_ROLE_CODES.get(preferred)
                if mapped:
                    self.role = mapped
                    break

        current = (self.role or "").strip().lower()
        if current not in _ALLOWED_LEGACY_ROLE_VALUES:
            self.role = "assistant"
