"""Application extensions (SQLAlchemy engine, CSRF, limiter)."""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Callable

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf import CSRFProtect
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import scoped_session, sessionmaker


class SQLAlchemyEngine:
    """Minimal SQLAlchemy integration for the app."""

    def __init__(self) -> None:
        self._engine: Engine | None = None
        self._session_factory: Callable[[], Any] | None = None

    def init_app(self, app: Flask) -> None:
        uri = app.config["SQLALCHEMY_DATABASE_URI"]
        engine_options = app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {})
        self._engine = create_engine(uri, future=True, **engine_options)
        # Expose the engine on Flask's extensions dict so helpers like doctor_choices can access it.
        app.extensions["db"] = self

        @event.listens_for(self._engine, "connect")
        def _set_pragmas(dbapi_connection, connection_record) -> None:  # type: ignore[override]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        session_factory = sessionmaker(bind=self._engine, autoflush=False, future=True)
        self._session_factory = scoped_session(session_factory)

        @app.teardown_appcontext
        def remove_session(exception: BaseException | None) -> None:
            if self._session_factory:
                self._session_factory.remove()

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            raise RuntimeError("SQLAlchemy engine is not initialised")
        return self._engine

    def session(self):  # type: ignore[override]
        if self._session_factory is None:
            raise RuntimeError("SQLAlchemy session factory is not initialised")
        return self._session_factory()

    def raw_connection(self) -> sqlite3.Connection:
        engine = self.engine
        raw = engine.raw_connection()
        driver_conn = getattr(raw, "driver_connection", None)
        if driver_conn is None:
            driver_conn = raw.connection  # type: ignore[attr-defined]
        if hasattr(driver_conn, "row_factory"):
            driver_conn.row_factory = sqlite3.Row
        return raw


db = SQLAlchemyEngine()
csrf = CSRFProtect()
limiter = Limiter(get_remote_address, storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"))


def init_extensions(app: Flask) -> None:
    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
