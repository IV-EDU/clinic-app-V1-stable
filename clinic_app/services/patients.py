"""Patient helpers shared across routes."""

from __future__ import annotations

import re
import sqlite3
import uuid
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


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row["name"] or "") == column_name for row in rows)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_phone_digits(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _sanitize_notebook_color(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if re.fullmatch(r"#[0-9a-fA-F]{6}", raw):
        return raw.lower()
    return ""


def page_color_notebook_key(patient_id: str, page_number: str) -> str:
    pid_compact = (patient_id or "").replace("-", "")
    page = (page_number or "").strip()
    key = f"pc:{pid_compact}:{page}"
    if len(key) > 100:
        keep = max(0, 100 - len(f"pc:{pid_compact}:"))
        key = f"pc:{pid_compact}:{page[:keep]}"
    return key


def _value(form_like: Any, key: str, default: Any = "") -> Any:
    if hasattr(form_like, "get"):
        try:
            return form_like.get(key, default)
        except TypeError:
            return form_like.get(key) or default
    if isinstance(form_like, dict):
        return form_like.get(key, default)
    return default


def _list_value(form_like: Any, key: str) -> list[Any]:
    if hasattr(form_like, "getlist"):
        return list(form_like.getlist(key))
    value = _value(form_like, key, [])
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    return [value]


def load_patient_phones(conn, patient_id: str, primary_phone: str | None) -> list[dict[str, Any]]:
    if not _table_exists(conn, "patient_phones"):
        return [{"phone": primary_phone or "", "label": None, "is_primary": True}] if primary_phone else []
    rows = conn.execute(
        """
        SELECT phone, label, is_primary
          FROM patient_phones
         WHERE patient_id=?
         ORDER BY is_primary DESC, rowid ASC
        """,
        (patient_id,),
    ).fetchall()
    if rows:
        return [dict(row) for row in rows]
    return [{"phone": primary_phone or "", "label": None, "is_primary": True}] if primary_phone else []


def load_patient_pages(conn, patient_id: str, primary_page_number: str | None) -> list[dict[str, Any]]:
    if not _table_exists(conn, "patient_pages"):
        return (
            [{"page_number": primary_page_number or "", "notebook_name": None, "notebook_color": ""}]
            if primary_page_number
            else []
        )
    if _table_exists(conn, "notebooks"):
        rows = conn.execute(
            """
            SELECT pg.page_number, pg.notebook_name, COALESCE(nb.color, '') AS notebook_color
              FROM patient_pages pg
              LEFT JOIN notebooks nb
                ON lower(trim(nb.name)) = lower(trim(pg.notebook_name))
             WHERE pg.patient_id=?
             ORDER BY pg.rowid ASC
            """,
            (patient_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT page_number, notebook_name, '' AS notebook_color
              FROM patient_pages
             WHERE patient_id=?
             ORDER BY rowid ASC
            """,
            (patient_id,),
        ).fetchall()
    if rows:
        return [dict(row) for row in rows]
    return (
        [{"page_number": primary_page_number or "", "notebook_name": None, "notebook_color": ""}]
        if primary_page_number
        else []
    )


def get_patient_profile_snapshot(patient_id: str, *, conn=None) -> dict[str, Any] | None:
    owns_conn = conn is None
    conn = conn or main_db()
    try:
        select_sql = "SELECT id, short_id, full_name, phone, notes"
        if _column_exists(conn, "patients", "primary_page_number"):
            select_sql += ", primary_page_number"
        select_sql += " FROM patients WHERE id=?"
        patient = conn.execute(select_sql, (patient_id,)).fetchone()
        if not patient:
            return None
        primary_page_number = patient["primary_page_number"] if "primary_page_number" in patient.keys() else None
        phones = load_patient_phones(conn, patient_id, patient["phone"])
        pages = load_patient_pages(conn, patient_id, primary_page_number)
        primary_phone = phones[0]["phone"] if phones else (patient["phone"] or "")
        primary_page = pages[0]["page_number"] if pages else (primary_page_number or "")
        return {
            "id": patient["id"],
            "short_id": patient["short_id"] or "",
            "full_name": patient["full_name"] or "",
            "primary_phone": primary_phone or "",
            "phones": phones,
            "primary_page_number": primary_page or "",
            "pages": pages,
            "notes": patient["notes"] or "",
        }
    finally:
        if owns_conn:
            conn.close()


def normalize_patient_profile_update(
    form_like: Any,
    *,
    patient_id: str | None = None,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []

    short_id = _text(_value(form_like, "short_id"))
    full_name = _text(_value(form_like, "full_name"))
    notes = _text(_value(form_like, "notes"))

    phones: list[dict[str, Any]] = []
    seen_phones: set[str] = set()

    if isinstance(_value(form_like, "phones"), list):
        incoming_phones = _value(form_like, "phones") or []
        for index, row in enumerate(incoming_phones):
            phone = _text((row or {}).get("phone"))
            if not phone:
                continue
            normalized_phone = _normalize_phone_digits(phone)
            if not normalized_phone:
                continue
            if normalized_phone in seen_phones:
                errors.append("Duplicate phone numbers are not allowed.")
                continue
            seen_phones.add(normalized_phone)
            phones.append(
                {
                    "phone": phone,
                    "phone_normalized": normalized_phone,
                    "label": _text((row or {}).get("label")) or None,
                    "is_primary": 1 if index == 0 else 0,
                }
            )
    else:
        primary_phone = _text(_value(form_like, "phone"))
        primary_label = _text(_value(form_like, "phone_label")) or None
        extra_numbers = _list_value(form_like, "extra_phone_number")
        extra_labels = _list_value(form_like, "extra_phone_label")
        phone_rows: list[tuple[str, str | None]] = []
        if primary_phone:
            phone_rows.append((primary_phone, primary_label))
        for index, phone_raw in enumerate(extra_numbers):
            label_raw = extra_labels[index] if index < len(extra_labels) else ""
            phone_rows.append((_text(phone_raw), _text(label_raw) or None))
        for index, (phone, label) in enumerate(phone_rows):
            if not phone:
                continue
            normalized_phone = _normalize_phone_digits(phone)
            if not normalized_phone:
                continue
            if normalized_phone in seen_phones:
                errors.append("Duplicate phone numbers are not allowed.")
                continue
            seen_phones.add(normalized_phone)
            phones.append(
                {
                    "phone": phone,
                    "phone_normalized": normalized_phone,
                    "label": label,
                    "is_primary": 1 if index == 0 else 0,
                }
            )

    pages: list[dict[str, Any]] = []
    seen_pages: set[str] = set()

    if isinstance(_value(form_like, "pages"), list):
        incoming_pages = _value(form_like, "pages") or []
        for row in incoming_pages:
            page_number = _text((row or {}).get("page_number"))
            if not page_number:
                continue
            page_key = page_number.lower()
            if page_key in seen_pages:
                errors.append("Duplicate page numbers are not allowed.")
                continue
            seen_pages.add(page_key)
            notebook_name = _text((row or {}).get("notebook_name")) or None
            notebook_color = _sanitize_notebook_color((row or {}).get("notebook_color"))
            if notebook_color and not notebook_name and patient_id:
                notebook_name = page_color_notebook_key(patient_id, page_number)
            pages.append(
                {
                    "page_number": page_number,
                    "notebook_name": notebook_name,
                    "notebook_color": notebook_color,
                }
            )
    else:
        page_rows: list[tuple[str, str | None, str]] = []
        primary_page = _text(_value(form_like, "primary_page_number"))
        primary_notebook_name = _text(_value(form_like, "primary_notebook_name")) or None
        primary_notebook_color = _sanitize_notebook_color(_value(form_like, "primary_notebook_color"))
        if primary_page:
            page_rows.append((primary_page, primary_notebook_name, primary_notebook_color))
        extra_pages = _list_value(form_like, "extra_page_number")
        extra_notebook_names = _list_value(form_like, "extra_notebook_name")
        extra_notebook_colors = _list_value(form_like, "extra_notebook_color")
        row_count = max(len(extra_pages), len(extra_notebook_names), len(extra_notebook_colors))
        for index in range(row_count):
            page_number = _text(extra_pages[index] if index < len(extra_pages) else "")
            notebook_name = _text(extra_notebook_names[index] if index < len(extra_notebook_names) else "") or None
            notebook_color = _sanitize_notebook_color(
                extra_notebook_colors[index] if index < len(extra_notebook_colors) else ""
            )
            if page_number:
                page_rows.append((page_number, notebook_name, notebook_color))
        for page_number, notebook_name, notebook_color in page_rows:
            page_key = page_number.lower()
            if page_key in seen_pages:
                errors.append("Duplicate page numbers are not allowed.")
                continue
            seen_pages.add(page_key)
            if notebook_color and not notebook_name and patient_id:
                notebook_name = page_color_notebook_key(patient_id, page_number)
            pages.append(
                {
                    "page_number": page_number,
                    "notebook_name": notebook_name,
                    "notebook_color": notebook_color,
                }
            )

    if not full_name:
        errors.append("Name is required.")

    normalized = {
        "short_id": short_id or None,
        "full_name": full_name,
        "primary_phone": phones[0]["phone"] if phones else "",
        "phones": phones,
        "primary_page_number": pages[0]["page_number"] if pages else "",
        "pages": pages,
        "notes": notes,
    }
    return errors, normalized


def apply_patient_profile_update(conn, patient_id: str, normalized: dict[str, Any]) -> None:
    existing = conn.execute(
        "SELECT id, short_id FROM patients WHERE id=?",
        (patient_id,),
    ).fetchone()
    if not existing:
        raise ValueError("Locked patient was not found.")

    short_id = normalized.get("short_id")
    if short_id in (None, ""):
        short_id = existing["short_id"]

    primary_page_number = normalized.get("primary_page_number") or None
    conn.execute(
        """
        UPDATE patients
           SET short_id=?,
               full_name=?,
               phone=?,
               notes=?,
               primary_page_number=?
         WHERE id=?
        """,
        (
            short_id,
            normalized.get("full_name") or "",
            normalized.get("primary_phone") or None,
            normalized.get("notes") or "",
            primary_page_number,
            patient_id,
        ),
    )

    if _table_exists(conn, "patient_phones"):
        conn.execute("DELETE FROM patient_phones WHERE patient_id=?", (patient_id,))
        for index, phone_entry in enumerate(normalized.get("phones") or []):
            conn.execute(
                """
                INSERT INTO patient_phones(id, patient_id, phone, phone_normalized, label, is_primary)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    patient_id,
                    phone_entry.get("phone") or "",
                    phone_entry.get("phone_normalized") or _normalize_phone_digits(phone_entry.get("phone")),
                    phone_entry.get("label"),
                    1 if index == 0 else 0,
                ),
            )

    if _table_exists(conn, "patient_pages"):
        conn.execute("DELETE FROM patient_pages WHERE patient_id=?", (patient_id,))
        for page_entry in normalized.get("pages") or []:
            conn.execute(
                """
                INSERT OR IGNORE INTO patient_pages(id, patient_id, page_number, notebook_name)
                VALUES (?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    patient_id,
                    page_entry.get("page_number") or "",
                    page_entry.get("notebook_name"),
                ),
            )

    if _table_exists(conn, "notebooks"):
        for page_entry in normalized.get("pages") or []:
            notebook_name = _text(page_entry.get("notebook_name"))
            notebook_color = _sanitize_notebook_color(page_entry.get("notebook_color"))
            if not notebook_name:
                continue
            if notebook_color:
                conn.execute(
                    """
                    INSERT INTO notebooks(id, name, color, active)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(name) DO UPDATE SET
                        color=excluded.color,
                        active=1,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (str(uuid.uuid4()), notebook_name, notebook_color),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO notebooks(id, name, active)
                    VALUES (?, ?, 1)
                    ON CONFLICT(name) DO UPDATE SET
                        active=1,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (str(uuid.uuid4()), notebook_name),
                )
