"""Receipt issuance and PDF generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid

from flask import current_app

from clinic_app.services.audit import write_event
from clinic_app.services.database import db
from clinic_app.services.i18n import translate_text
from clinic_app.services.pdf import ReceiptPDF
from clinic_app.services.payments import parse_money_to_cents, money


class ReceiptError(Exception):
    """Raised when a receipt operation fails."""


def _data_root() -> Path:
    return Path(current_app.config["DATA_ROOT"])


def _font_path() -> str | None:
    configured = current_app.config.get("PDF_FONT_PATH")
    if configured and Path(configured).exists():
        return str(configured)
    candidate = Path(current_app.root_path).parent / "static" / "fonts" / "DejaVuSans.ttf"
    if candidate.exists():
        return str(candidate)
    return None


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _ensure_receipt_tables(conn: sqlite3.Connection) -> None:
    for table in ("patients", "receipts", "receipt_sequences", "receipt_reprints"):
        if not _table_exists(conn, table):
            raise ReceiptError("receipts_table_missing")


def _find_patient(conn: sqlite3.Connection, lookup: str) -> sqlite3.Row | None:
    if not lookup:
        return None
    normalized = lookup.strip()
    if not normalized:
        return None
    row = conn.execute(
        """
        SELECT id, full_name, phone
        FROM patients
        WHERE lower(short_id) = lower(?)
           OR lower(full_name) = lower(?)
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (normalized, normalized),
    ).fetchone()
    return row


def _next_serial(conn: sqlite3.Connection, issued_at: str) -> tuple[str, int]:
    prefix = current_app.config.get("RECEIPT_SERIAL_PREFIX", "R")
    year = issued_at[:4]
    row = conn.execute(
        "SELECT last_number FROM receipt_sequences WHERE year_key=?",
        (year,),
    ).fetchone()
    if row:
        next_num = int(row["last_number"]) + 1
        conn.execute(
            "UPDATE receipt_sequences SET last_number=? WHERE year_key=?",
            (next_num, year),
        )
    else:
        next_num = 1
        conn.execute(
            "INSERT INTO receipt_sequences(year_key, last_number) VALUES (?, ?)",
            (year, next_num),
        )
    serial = f"{prefix}-{year}-{next_num:06d}"
    return serial, next_num


def _qr_payload(serial: str, issued_at: str, amount_cents: int) -> str:
    payload = {
        "number": serial,
        "date": issued_at[:10],
        "amount": money(amount_cents),
    }
    return json.dumps(payload, ensure_ascii=False)


def _render_pdf(
    target: Path,
    *,
    number: str,
    issued_at: str,
    patient_name: str,
    patient_phone: str | None,
    description: str,
    amount_cents: int,
    locale: str,
    qr_payload: str,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    pdf = ReceiptPDF(_font_path())
    pdf.heading(translate_text("en", "receipt_heading"), translate_text("ar", "receipt_heading"))

    issued_display = issued_at[:16].replace("T", " ")
    en_rows = [
        (translate_text("en", "receipt_number_label"), number),
        (translate_text("en", "receipt_date_label"), issued_display),
        (translate_text("en", "receipt_patient_label"), patient_name),
    ]
    if patient_phone:
        en_rows.append((translate_text("en", "receipt_phone_label"), patient_phone))
    en_rows.append((translate_text("en", "receipt_description_label"), description))
    en_rows.append((translate_text("en", "receipt_amount_label"), money(amount_cents)))
    pdf.kv_block(en_rows)

    ar_rows = [
        (translate_text("ar", "receipt_number_label"), number),
        (translate_text("ar", "receipt_date_label"), issued_display),
        (translate_text("ar", "receipt_patient_label"), patient_name),
    ]
    if patient_phone:
        ar_rows.append((translate_text("ar", "receipt_phone_label"), patient_phone))
    ar_rows.append((translate_text("ar", "receipt_description_label"), description))
    ar_rows.append((translate_text("ar", "receipt_amount_label"), money(amount_cents)))
    pdf.kv_block(ar_rows)

    pdf.note(f"{translate_text(locale, 'receipt_qr_hint')}: {qr_payload}")
    target.write_bytes(pdf.render())


def issue_receipt(form_data: dict[str, str], *, actor_id: str | None, locale: str) -> str:
    amount_cents = parse_money_to_cents(form_data.get("amount") or "")
    if amount_cents <= 0:
        raise ReceiptError("amount_required")
    patient_lookup = (form_data.get("patient_lookup") or "").strip()
    description = (form_data.get("description") or "").strip() or translate_text(locale, "receipt_default_desc")
    conn = db()
    issued_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    patient = None
    storage_path = None
    try:
        if not _table_exists(conn, "patients"):
            raise ReceiptError("patient_not_found")
        if not _table_exists(conn, "receipts"):
            raise ReceiptError("receipts_table_missing")
        conn.execute("BEGIN IMMEDIATE")
        _ensure_receipt_tables(conn)
        patient = _find_patient(conn, patient_lookup)
        if not patient:
            raise ReceiptError("patient_not_found")
        appointment_id = form_data.get("appointment_id") or None
        if appointment_id:
            exists = conn.execute("SELECT id FROM appointments WHERE id=?", (appointment_id,)).fetchone()
            if not exists:
                appointment_id = None
        serial, _ = _next_serial(conn, issued_at)
        receipt_id = str(uuid.uuid4())
        qr_payload = _qr_payload(serial, issued_at, amount_cents)
        storage_path = _data_root() / "receipts" / f"{serial}.pdf"
        meta = json.dumps(
            {
                "description": description,
                "patient_name": patient["full_name"],
                "patient_phone": patient["phone"],
            },
            ensure_ascii=False,
        )
        conn.execute(
            """
            INSERT INTO receipts(
                id, patient_id, appointment_id, issued_by_user_id, number, issued_at,
                amount_cents, locale, qr_payload, pdf_path, meta_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_id,
                patient["id"],
                appointment_id,
                actor_id,
                serial,
                issued_at,
                amount_cents,
                locale,
                qr_payload,
                str(storage_path),
                meta,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    assert patient is not None
    assert storage_path is not None
    _render_pdf(
        storage_path,
        number=serial,
        issued_at=issued_at,
        patient_name=patient["full_name"],
        patient_phone=patient["phone"],
        description=description,
        amount_cents=amount_cents,
        locale=locale,
        qr_payload=qr_payload,
    )
    write_event(actor_id, "receipts:issue", entity="receipt", entity_id=receipt_id, meta={"number": serial})
    return receipt_id


def reprint_receipt(receipt_id: str, *, actor_id: str | None) -> Path:
    conn = db()
    try:
        if not _table_exists(conn, "receipts"):
            raise ReceiptError("receipts_table_missing")
        row = conn.execute(
            """
            SELECT id, number, pdf_path, locale, patient_id, qr_payload, amount_cents, issued_at, meta_json, reprint_count
            FROM receipts
            WHERE id=?
            """,
            (receipt_id,),
        ).fetchone()
        if not row:
            raise ReceiptError("receipt_not_found")
        patient = conn.execute("SELECT full_name, phone FROM patients WHERE id=?", (row["patient_id"],)).fetchone()
        meta = json.loads(row["meta_json"] or "{}")
        conn.execute(
            """
            UPDATE receipts
            SET reprint_count = reprint_count + 1,
                last_reprinted_at = datetime('now')
            WHERE id = ?
            """,
            (receipt_id,),
        )
        conn.execute(
            """
            INSERT INTO receipt_reprints(id, receipt_id, user_id, reason, reprinted_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (str(uuid.uuid4()), receipt_id, actor_id, "manual",),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    storage = Path(row["pdf_path"])
    _render_pdf(
        storage,
        number=row["number"],
        issued_at=row["issued_at"],
        patient_name=patient["full_name"] if patient else meta.get("patient_name", "—"),
        patient_phone=patient["phone"] if patient else meta.get("patient_phone"),
        description=meta.get("description", ""),
        amount_cents=row["amount_cents"],
        locale=row["locale"],
        qr_payload=row["qr_payload"],
    )
    write_event(actor_id, "receipts:reprint", entity="receipt", entity_id=receipt_id, meta={"number": row["number"]})
    return storage


def recent_receipts(limit: int = 50) -> list[dict[str, str]]:
    conn = db()
    try:
        if not _table_exists(conn, "receipts") or not _table_exists(conn, "patients"):
            raise ReceiptError("receipts_table_missing")
        rows = conn.execute(
            f"""
            SELECT r.id, r.number, r.issued_at, r.amount_cents, r.locale, r.pdf_path, r.reprint_count,
                   p.full_name
            FROM receipts r
            JOIN patients p ON p.id = r.patient_id
            ORDER BY r.issued_at DESC
            LIMIT {int(limit)}
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_receipt_metadata(rid: str) -> dict[str, str]:
    conn = db()
    try:
        if not _table_exists(conn, "receipts"):
            raise ReceiptError("receipts_table_missing")
        row = conn.execute(
            "SELECT id, number, pdf_path FROM receipts WHERE id=?",
            (rid,),
        ).fetchone()
        if not row:
            raise ReceiptError("receipt_not_found")
        return dict(row)
    finally:
        conn.close()
