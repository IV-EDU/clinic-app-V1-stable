"""Bootstrap helper to ensure critical tables exist for first-time runs."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


def _execute_statements(conn: sqlite3.Connection, statements: Iterable[str]) -> None:
    for stmt in statements:
        conn.execute(stmt)


def ensure_base_tables(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        _execute_statements(
            conn,
            [
                """
                CREATE TABLE IF NOT EXISTS appointments (
                    id TEXT PRIMARY KEY,
                    patient_id TEXT,
                    patient_name TEXT,
                    patient_phone TEXT,
                    doctor_id TEXT NOT NULL,
                    doctor_label TEXT NOT NULL,
                    title TEXT NOT NULL,
                    notes TEXT,
                    starts_at TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    color TEXT,
                    room TEXT,
                    reminder_minutes INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY(patient_id) REFERENCES patients(id) ON DELETE SET NULL,
                    CHECK(status IN ('scheduled','checked_in','in_progress','done','no_show','cancelled'))
                )
                """,
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_doctor_start
                ON appointments(doctor_id, starts_at)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_appointments_day
                ON appointments(substr(starts_at, 1, 10))
                """,
                """
                CREATE TABLE IF NOT EXISTS receipt_sequences (
                    year_key TEXT PRIMARY KEY,
                    last_number INTEGER NOT NULL
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS receipts (
                    id TEXT PRIMARY KEY,
                    patient_id TEXT NOT NULL,
                    appointment_id TEXT,
                    issued_by_user_id TEXT,
                    number TEXT NOT NULL UNIQUE,
                    issued_at TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL DEFAULT 0,
                    locale TEXT NOT NULL DEFAULT 'en',
                    qr_payload TEXT,
                    pdf_path TEXT NOT NULL,
                    reprint_count INTEGER NOT NULL DEFAULT 0,
                    last_reprinted_at TEXT,
                    meta_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(patient_id) REFERENCES patients(id) ON DELETE CASCADE,
                    FOREIGN KEY(appointment_id) REFERENCES appointments(id) ON DELETE SET NULL,
                    FOREIGN KEY(issued_by_user_id) REFERENCES users(id) ON DELETE SET NULL
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_receipts_patient ON receipts(patient_id)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_receipts_issued_at ON receipts(issued_at)
                """,
                """
                CREATE TABLE IF NOT EXISTS receipt_reprints (
                    id TEXT PRIMARY KEY,
                    receipt_id TEXT NOT NULL,
                    user_id TEXT,
                    reason TEXT,
                    reprinted_at TEXT NOT NULL,
                    FOREIGN KEY(receipt_id) REFERENCES receipts(id) ON DELETE CASCADE,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
                )
                """,
            ],
        )
        _execute_statements(
            conn,
            [
                """
                CREATE TABLE IF NOT EXISTS doctor_colors (
                    doctor_id TEXT PRIMARY KEY,
                    color TEXT NOT NULL
                )
                """,
            ],
        )
        conn.commit()
    finally:
        conn.close()
