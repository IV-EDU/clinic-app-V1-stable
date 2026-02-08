"""Patient helpers shared across routes."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

from flask import current_app

from clinic_app.services.database import db as main_db


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
    """Generate the next free file number (short_id).

    Old behaviour was based purely on patient count, which could collide with
    manually assigned file numbers. This version always picks the first
    unused `P000001`‑style id.
    """
    cur = conn.cursor()
    row = cur.execute("SELECT COUNT(*) FROM patients").fetchone()
    n = (row[0] if row and row[0] is not None else 0)

    while True:
        n += 1
        candidate = f"P{n:06d}"
        exists = cur.execute(
            "SELECT 1 FROM patients WHERE short_id=?",
            (candidate,),
        ).fetchone()
        if not exists:
            return candidate


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


class MergeConflict(Exception):
    """Raised when a merge cannot be safely completed."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


def _patient_images_root() -> Path:
    app = current_app
    data_root = Path(app.config.get("DATA_ROOT", Path(app.root_path) / "data"))
    return data_root / "patient_images"


def merge_patient_images(source_id: str, target_id: str) -> None:
    """Move patient image files from source to target folder.

    This is used when 'also merge diagnosis / medical / images' is selected.
    """
    try:
        root = _patient_images_root()
    except RuntimeError:
        # No application context; nothing we can safely do.
        return
    src = root / str(source_id)
    dst = root / str(target_id)
    if not src.exists() or not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for p in src.glob("*"):
        if not p.is_file():
            continue
        dest = dst / p.name
        if dest.exists():
            ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            dest = dst / f"{dest.stem}_{ts}{dest.suffix}"
        try:
            # Move the file so we do not keep duplicate copies.
            p.rename(dest)
        except OSError:
            # If we cannot move a particular file, skip it instead of failing
            # the whole merge.
            continue

    # After moving all files, try to remove the now-empty source folder so we
    # do not leave unused per-patient image directories behind. If the folder
    # is not empty or cannot be removed, we quietly ignore the error.
    try:
        src.rmdir()
    except OSError:
        pass


def merge_patient_records(
    conn: sqlite3.Connection,
    source: Dict[str, Any],
    target: Dict[str, Any],
    merge_diag: bool = False,
) -> None:
    """Merge one patient's records into another.

    Always moves:
      - Payments
      - Appointments (including patient_name/phone fields)

    Optionally moves diagnosis / medical / events / images when merge_diag=True.
    When merging diagnosis/medical:
      - Diagnosis rows from the source are moved to the target. If both source
        and target have the same tooth (patient_id, chart_type, tooth_code),
        the target row is kept and the source row is skipped.
      - Medical rows are merged when both patients have entries: the target's
        problems/allergies are kept and the source values are appended with a
        short '[MERGED FROM ...]' prefix. Vitals from the target are kept.
    """
    src_id = source["id"]
    tgt_id = target["id"]
    if src_id == tgt_id:
        raise MergeConflict("same_patient", "Cannot merge a patient into itself.")

    cur = conn.cursor()

    # Payments: collections and analytics derive from payments, so they will
    # automatically follow the new patient.
    cur.execute("UPDATE payments SET patient_id=? WHERE patient_id=?", (tgt_id, src_id))

    # Appointments: update the patient reference and denormalised name/phone.
    tgt_name = target.get("full_name")
    tgt_phone = target.get("phone")
    try:
        cur.execute(
            """
            UPDATE appointments
               SET patient_id = ?,
                   patient_name = COALESCE(?, patient_name),
                   patient_phone = COALESCE(?, patient_phone)
             WHERE patient_id = ?
            """,
            (tgt_id, tgt_name, tgt_phone, src_id),
        )
    except sqlite3.OperationalError:
        # Appointments table may not exist in some databases.
        pass

    # Optional diagnosis / medical / events / images.
    if merge_diag:
        # --- Diagnosis rows --------------------------------------------------
        try:
            diag_rows = cur.execute(
                "SELECT id, chart_type, tooth_code FROM diagnosis WHERE patient_id=?",
                (src_id,),
            ).fetchall()
            for r in diag_rows:
                chart = r["chart_type"]
                tooth = r["tooth_code"]
                exists = cur.execute(
                    """
                    SELECT id FROM diagnosis
                     WHERE patient_id=? AND chart_type=? AND tooth_code=?
                    """,
                    (tgt_id, chart, tooth),
                ).fetchone()
                if exists:
                    # Keep the target's diagnosis for this tooth; skip the source row.
                    continue
                cur.execute(
                    "UPDATE diagnosis SET patient_id=? WHERE id=?",
                    (tgt_id, r["id"]),
                )
        except sqlite3.OperationalError:
            # Diagnosis table may not exist; skip.
            pass

        # Diagnosis events: safe to re-point all to the target.
        try:
            cur.execute(
                "UPDATE diagnosis_event SET patient_id=? WHERE patient_id=?",
                (tgt_id, src_id),
            )
        except sqlite3.OperationalError:
            pass

        # --- Medical rows ----------------------------------------------------
        try:
            src_med = cur.execute(
                "SELECT id, problems, allergies_flag, allergies, vitals FROM medical WHERE patient_id=?",
                (src_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            src_med = None
        try:
            tgt_med = cur.execute(
                "SELECT id, problems, allergies_flag, allergies, vitals FROM medical WHERE patient_id=?",
                (tgt_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            tgt_med = None

        now_iso = datetime.now(timezone.utc).isoformat()

        if src_med:
            if tgt_med:
                # Merge source medical data into target without losing existing info.
                src_label = source.get("short_id") or source.get("full_name") or src_id
                prefix = f"[MERGED FROM {src_label}] "
                merged_problems = (tgt_med["problems"] or "") or ""
                if src_med["problems"]:
                    extra = prefix + (src_med["problems"] or "")
                    merged_problems = (merged_problems + "\n" + extra).strip() if merged_problems else extra
                merged_allergies_flag = int(bool(tgt_med["allergies_flag"] or src_med["allergies_flag"]))
                merged_allergies = (tgt_med["allergies"] or "") or ""
                if src_med["allergies"]:
                    extra_all = prefix + (src_med["allergies"] or "")
                    merged_allergies = (merged_allergies + "\n" + extra_all).strip() if merged_allergies else extra_all
                merged_vitals = tgt_med["vitals"]  # Keep target vitals as-is.
                try:
                    cur.execute(
                        """
                        UPDATE medical
                           SET problems=?, allergies_flag=?, allergies=?, vitals=?, updated_at=?
                         WHERE id=?
                        """,
                        (
                            merged_problems,
                            merged_allergies_flag,
                            merged_allergies,
                            merged_vitals,
                            now_iso,
                            tgt_med["id"],
                        ),
                    )
                    cur.execute("DELETE FROM medical WHERE id=?", (src_med["id"],))
                except sqlite3.OperationalError:
                    pass
            else:
                # Target has no medical row; simply re-point the source row.
                try:
                    cur.execute(
                        "UPDATE medical SET patient_id=?, updated_at=? WHERE patient_id=?",
                        (tgt_id, now_iso, src_id),
                    )
                except sqlite3.OperationalError:
                    pass

        # Medical events: safe to re-point all to the target.
        try:
            cur.execute(
                "UPDATE medical_event SET patient_id=? WHERE patient_id=?",
                (tgt_id, src_id),
            )
        except sqlite3.OperationalError:
            pass

        # Move images on disk
        merge_patient_images(src_id, tgt_id)

    # Append a note on the source patient so it is clear it was merged.
    try:
        row = cur.execute(
            "SELECT notes FROM patients WHERE id=?", (src_id,)
        ).fetchone()
        old_notes = row["notes"] if row and "notes" in row.keys() else (row[0] if row else "")
    except Exception:
        old_notes = ""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    target_label = target.get("short_id") or target.get("full_name") or tgt_id
    merge_note = f"[MERGED {ts}] Payments and appointments moved into {target_label}."
    if merge_diag:
        merge_note = f"[MERGED {ts}] Payments, appointments, diagnosis, medical, and images moved into {target_label}."
    new_notes = (old_notes or "").strip()
    if new_notes:
        new_notes = new_notes + "\n" + merge_note
    else:
        new_notes = merge_note
    try:
        cur.execute("UPDATE patients SET notes=? WHERE id=?", (new_notes, src_id))
    except Exception:
        pass
