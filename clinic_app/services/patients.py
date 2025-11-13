"""Patient helpers shared across routes."""

from __future__ import annotations

import re
from typing import Optional


def migrate_patients_drop_unique_short_id(conn) -> None:
    cur = conn.cursor()
    row = cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='patients'",
    ).fetchone()
    if not row:
        return
    table_sql = row[0] or ""
    if "short_id TEXT UNIQUE" in table_sql:
        cur.execute("PRAGMA foreign_keys=OFF")
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS patients_new (
              id TEXT PRIMARY KEY,
              short_id TEXT,
              full_name TEXT NOT NULL,
              phone TEXT,
              notes TEXT,
              created_at TEXT DEFAULT (datetime('now'))
            );
            INSERT INTO patients_new(id, short_id, full_name, phone, notes, created_at)
              SELECT id, short_id, full_name, phone, notes, created_at FROM patients;
            DROP TABLE patients;
            ALTER TABLE patients_new RENAME TO patients;
            """
        )
        cur.execute("PRAGMA foreign_keys=ON")
        conn.commit()


def next_short_id(conn) -> str:
    n = conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0] or 0
    return f"P{n+1:06d}"


def normalize_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def dup_by_name(conn, name: str, exclude_patient_id: Optional[str] = None) -> bool:
    n = normalize_name(name)
    if exclude_patient_id:
        row = conn.execute(
            "SELECT 1 FROM patients WHERE lower(trim(full_name))=? AND id<>?",
            (n, exclude_patient_id),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM patients WHERE lower(trim(full_name))=?",
            (n,),
        ).fetchone()
    return row is not None
