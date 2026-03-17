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
                """
                CREATE TABLE IF NOT EXISTS reception_entries (
                    id TEXT PRIMARY KEY,
                    draft_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    patient_intent TEXT NOT NULL DEFAULT 'unknown',
                    locked_patient_id TEXT,
                    locked_treatment_id TEXT,
                    locked_payment_id TEXT,
                    target_patient_id TEXT,
                    target_treatment_id TEXT,
                    target_payment_id TEXT,
                    submitted_by_user_id TEXT NOT NULL,
                    reviewed_by_user_id TEXT,
                    submitted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    last_action TEXT NOT NULL DEFAULT 'submitted',
                    return_reason TEXT,
                    hold_reason TEXT,
                    rejection_reason TEXT,
                    patient_name TEXT,
                    page_number TEXT,
                    phone TEXT,
                    visit_date TEXT,
                    visit_type TEXT,
                    treatment_text TEXT,
                    doctor_id TEXT NOT NULL,
                    doctor_label TEXT NOT NULL,
                    money_received_today INTEGER NOT NULL DEFAULT 0,
                    paid_today_cents INTEGER,
                    total_amount_cents INTEGER,
                    discount_amount_cents INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    match_summary_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(submitted_by_user_id) REFERENCES users(id) ON DELETE RESTRICT,
                    FOREIGN KEY(reviewed_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
                    FOREIGN KEY(locked_patient_id) REFERENCES patients(id) ON DELETE SET NULL,
                    FOREIGN KEY(target_patient_id) REFERENCES patients(id) ON DELETE SET NULL,
                    FOREIGN KEY(locked_treatment_id) REFERENCES payments(id) ON DELETE SET NULL,
                    FOREIGN KEY(target_treatment_id) REFERENCES payments(id) ON DELETE SET NULL,
                    FOREIGN KEY(locked_payment_id) REFERENCES payments(id) ON DELETE SET NULL,
                    FOREIGN KEY(target_payment_id) REFERENCES payments(id) ON DELETE SET NULL,
                    CHECK(draft_type IN ('new_visit_only','new_treatment','new_payment','edit_patient','edit_payment','edit_treatment')),
                    CHECK(source IN ('reception_desk','patient_file','treatment_card')),
                    CHECK(status IN ('new','edited','held','approved','rejected')),
                    CHECK(patient_intent IN ('unknown','existing','new_patient')),
                    CHECK(money_received_today IN (0, 1))
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_reception_entries_status_submitted_at
                ON reception_entries(status, submitted_at DESC)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_reception_entries_submitted_by_user_id
                ON reception_entries(submitted_by_user_id, submitted_at DESC)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_reception_entries_locked_patient_id
                ON reception_entries(locked_patient_id)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_reception_entries_target_patient_id
                ON reception_entries(target_patient_id)
                """,
                """
                CREATE TABLE IF NOT EXISTS reception_entry_events (
                    id TEXT PRIMARY KEY,
                    entry_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor_user_id TEXT NOT NULL,
                    from_status TEXT,
                    to_status TEXT,
                    note TEXT,
                    meta_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(entry_id) REFERENCES reception_entries(id) ON DELETE CASCADE,
                    FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE RESTRICT,
                    CHECK(action IN ('submitted','edited','held','returned','rejected','approved'))
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_reception_entry_events_entry_id_created_at
                ON reception_entry_events(entry_id, created_at DESC)
                """,
            ],
        )
        conn.commit()
    finally:
        conn.close()
