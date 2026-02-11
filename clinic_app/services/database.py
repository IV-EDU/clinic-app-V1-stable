"""Database helpers backed by SQLAlchemy."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from clinic_app.extensions import db as sa_db


def db() -> sqlite3.Connection:
    """Return a raw sqlite3 connection with PRAGMAs applied."""

    return sa_db.raw_connection()


@contextmanager
def session_scope():
    """Provide a transactional scope for ORM usage."""

    session = sa_db.session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
