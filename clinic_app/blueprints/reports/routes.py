from __future__ import annotations

import csv
import io
from datetime import datetime
from textwrap import dedent

from flask import Blueprint, request, send_file, url_for, redirect, jsonify

from clinic_app.services.database import db
from clinic_app.services.ui import render_page
from clinic_app.services.security import require_permission
from clinic_app.services.doctor_colors import (
    get_active_doctor_options,
    get_deleted_doctors,
    ANY_DOCTOR_ID,
    ANY_DOCTOR_LABEL,
)

bp = Blueprint("reports", __name__)
REPORTS_PER_PAGE = 50


@bp.route("/", methods=["GET"])
@require_permission("reports:view")
def index():
    """Redirect to collections report."""
    return redirect(url_for("reports.collections"))


def _range_args() -> tuple[str | None, str | None]:
    """Return the optional from/to query-string bounds."""

    start = request.args.get("f") or None
    end = request.args.get("t") or None
    return start, end


def _paginate_rows(rows: list[dict], per_page: int = REPORTS_PER_PAGE) -> tuple[list[dict], dict[str, int | bool]]:
    raw_page = request.args.get("page", "1")
    try:
        page = int(raw_page or "1")
    except (TypeError, ValueError):
        page = 1
    if page < 1:
        page = 1

    total_rows = len(rows)
    total_pages = (total_rows + per_page - 1) // per_page if total_rows else 1
    start = (page - 1) * per_page
    end = start + per_page
    paged = rows[start:end]
    meta = {
        "page": page,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "total_rows": total_rows,
        "per_page": per_page,
    }
    return paged, meta


def _monthly_totals_query(
    start: str | None, end: str | None, doctor_id: str | None = None
) -> tuple[str, tuple[str, ...]]:
    base = """
        SELECT substr(paid_at,1,7) as month, SUM(amount_cents) as amt
        FROM payments
        WHERE amount_cents > 0
    """
    conditions: list[str] = []
    params: list[str] = []
    if start and end:
        conditions.append("paid_at BETWEEN ? AND ?")
        params.extend([start, end])
    if doctor_id:
        conditions.append("doctor_id = ?")
        params.append(doctor_id)
    if conditions:
        base = base + " AND " + " AND ".join(conditions)
    base += "\nGROUP BY substr(paid_at,1,7)\nORDER BY month DESC"
    return (base, tuple(params))


def _monthly_totals_export_query(
    start: str | None, end: str | None, doctor_id: str | None = None
) -> tuple[str, tuple[str, ...]]:
    base = dedent(
        """
        SELECT substr(paid_at,1,7) as month, SUM(amount_cents) as amt
        FROM payments
        WHERE amount_cents > 0
        """
    )
    suffix = "\nORDER BY month DESC"
    conditions: list[str] = []
    params: list[str] = []
    if start and end:
        conditions.append("paid_at BETWEEN ? AND ?")
        params.extend([start, end])
    if doctor_id:
        conditions.append("doctor_id = ?")
        params.append(doctor_id)
    if conditions:
        base = base + " AND " + " AND ".join(conditions)
    base = base + "\nGROUP BY substr(paid_at,1,7)" + suffix
    return (base, tuple(params))


def _daily_totals_query(
    start: str | None, end: str | None, doctor_id: str | None = None
) -> tuple[str, tuple[str, ...]]:
    base = """
        SELECT paid_at, SUM(amount_cents) as amt
        FROM payments
        WHERE amount_cents > 0
    """
    conditions: list[str] = []
    params: list[str] = []
    if start and end:
        conditions.append("paid_at BETWEEN ? AND ?")
        params.extend([start, end])
    if doctor_id:
        conditions.append("doctor_id = ?")
        params.append(doctor_id)
    if conditions:
        base = base + " AND " + " AND ".join(conditions)
    base += "\nGROUP BY paid_at\nORDER BY paid_at DESC"
    return (base, tuple(params))


def _daily_totals_export_query(
    start: str | None, end: str | None, doctor_id: str | None = None
) -> tuple[str, tuple[str, ...]]:
    base = dedent(
        """
        SELECT paid_at, SUM(amount_cents) as amt
        FROM payments
        WHERE amount_cents > 0
        """
    )
    suffix = "\nORDER BY paid_at DESC"
    conditions = []
    params: list[str] = []
    if start and end:
        conditions.append("paid_at BETWEEN ? AND ?")
        params.extend([start, end])
    if doctor_id:
        conditions.append("doctor_id = ?")
        params.append(doctor_id)
    if conditions:
        base = base + " AND " + " AND ".join(conditions)
    return (base + "\nGROUP BY paid_at" + suffix, tuple(params))


def _doctor_totals_query(
    start: str | None, end: str | None
) -> tuple[str, tuple[str, ...]]:
    base = dedent(
        """
        SELECT
          COALESCE(doctor_id, '') AS doctor_id,
          COALESCE(doctor_label, '') AS doctor_label,
          SUM(amount_cents) AS amt
        FROM payments
        WHERE amount_cents > 0
        """
    )
    suffix = "\nGROUP BY COALESCE(doctor_id, ''), COALESCE(doctor_label, '')\nORDER BY amt DESC"
    if start and end:
        return (
            base + " AND paid_at BETWEEN ? AND ?" + suffix,
            (start, end),
        )
    return (base + suffix, ())


@bp.route("/receivables")
@require_permission("reports:view")
def receivables():
    """Patients who still owe the clinic money."""
    conn = db()
    cur = conn.cursor()
    patients_rows = cur.execute(
        "SELECT id, short_id, full_name, phone FROM patients ORDER BY full_name COLLATE NOCASE"
    ).fetchall()

    from clinic_app.services.payments import overall_remaining

    receivables_list: list[dict] = []
    total_owed_cents = 0
    for row in patients_rows:
        balance = overall_remaining(conn, row["id"])
        if balance <= 0:
            continue
        total_owed_cents += balance
        receivables_list.append(
            {
                "id": row["id"],
                "short_id": row["short_id"],
                "full_name": row["full_name"],
                "phone": row["phone"],
                "balance_cents": balance,
                "balance_fmt": f"{balance/100:.2f}",
            }
        )

    conn.close()

    receivables_page, pagination = _paginate_rows(receivables_list)
    total_owed = total_owed_cents / 100.0
    total_owed_fmt = f"{total_owed:.2f}"
    patients_count = len(receivables_list)

    return render_page(
        "reports/receivables.html",
        receivables=receivables_page,
        total_owed=total_owed,
        total_owed_fmt=total_owed_fmt,
        patients_count=patients_count,
        page=pagination["page"],
        has_prev=pagination["has_prev"],
        has_next=pagination["has_next"],
        total_pages=pagination["total_pages"],
        show_back=True,
    )


@bp.route("/collections")
@require_permission("reports:view")
def collections():
    tab = request.args.get("tab") or "daily"
    from_date, to_date = _range_args()
    # "all" = no doctor filter; ANY_DOCTOR_ID = Any Doctor + deleted doctors
    doctor_filter = request.args.get("doctor") or "all"
    deleted_ids = {d["doctor_id"] for d in get_deleted_doctors()}
    doctor_id_for_query = None if doctor_filter == "all" else doctor_filter
    conn = db()
    cur = conn.cursor()
    rows_data: list[dict] = []
    range_mode = False

    if tab == "monthly":
        if from_date and to_date:
            # Custom range: single aggregated row for the full period
            range_mode = True
            base = """
                SELECT COALESCE(SUM(amount_cents), 0) as amt
                FROM payments
                WHERE amount_cents > 0
            """
            conditions: list[str] = []
            params: list[str] = []
            conditions.append("paid_at BETWEEN ? AND ?")
            params.extend([from_date, to_date])
            if doctor_filter == ANY_DOCTOR_ID:
                ids = [ANY_DOCTOR_ID] + [d for d in deleted_ids]
                placeholders = ",".join("?" for _ in ids)
                conditions.append(f"doctor_id IN ({placeholders})")
                params.extend(ids)
            elif doctor_id_for_query:
                conditions.append("doctor_id = ?")
                params.append(doctor_id_for_query)
            if conditions:
                base = base + " AND " + " AND ".join(conditions)
            row = cur.execute(base, tuple(params)).fetchone()
            if row and (row["amt"] or 0):
                rows_data = [
                    {"month": f"{from_date} \u2192 {to_date}", "amt": row["amt"] or 0}
                ]
            export_url = url_for(
                "reports.export_range_csv",
                f=from_date or "",
                t=to_date or "",
                doctor=doctor_filter,
            )
        else:
            if doctor_filter == ANY_DOCTOR_ID:
                ids = [ANY_DOCTOR_ID] + [d for d in deleted_ids]
                placeholders = ",".join("?" for _ in ids)
                query = """
                    SELECT substr(paid_at,1,7) as month, SUM(amount_cents) as amt
                    FROM payments
                    WHERE amount_cents > 0
                """
                conditions: list[str] = []
                params: list[str] = []
                if from_date and to_date:
                    conditions.append("paid_at BETWEEN ? AND ?")
                    params.extend([from_date, to_date])
                conditions.append(f"doctor_id IN ({placeholders})")
                params.extend(ids)
                if conditions:
                    query = query + " AND " + " AND ".join(conditions)
                query += "\nGROUP BY substr(paid_at,1,7)\nORDER BY month DESC"
                rows = cur.execute(query, tuple(params)).fetchall()
                rows_data = [dict(r) for r in rows]
            else:
                query, params = _monthly_totals_query(from_date, to_date, doctor_id_for_query)
                rows = cur.execute(query, params).fetchall()
                rows_data = [dict(r) for r in rows]
            export_url = url_for(
                "reports.export_monthly_csv",
                f=from_date or "",
                t=to_date or "",
                doctor=doctor_filter,
            )
    else:
        if doctor_filter == ANY_DOCTOR_ID:
            ids = [ANY_DOCTOR_ID] + [d for d in deleted_ids]
            placeholders = ",".join("?" for _ in ids)
            query = """
                SELECT paid_at, SUM(amount_cents) as amt
                FROM payments
                WHERE amount_cents > 0
            """
            conditions: list[str] = []
            params: list[str] = []
            if from_date and to_date:
                conditions.append("paid_at BETWEEN ? AND ?")
                params.extend([from_date, to_date])
            conditions.append(f"doctor_id IN ({placeholders})")
            params.extend(ids)
            if conditions:
                query = query + " AND " + " AND ".join(conditions)
            query += "\nGROUP BY paid_at\nORDER BY paid_at DESC"
            rows = cur.execute(query, tuple(params)).fetchall()
            rows_data = [dict(r) for r in rows]
        else:
            query, params = _daily_totals_query(from_date, to_date, doctor_id_for_query)
            rows = cur.execute(query, params).fetchall()
            rows_data = [dict(r) for r in rows]
        export_url = url_for(
            "reports.export_daily_csv",
            f=from_date or "",
            t=to_date or "",
            doctor=doctor_filter,
        )
    summary_count = len(rows_data)
    rows_page, pagination = _paginate_rows(rows_data)

    # Per-doctor totals for the same date range (independent of doctor filter)
    doc_query, doc_params = _doctor_totals_query(from_date, to_date)
    doctor_rows = cur.execute(doc_query, doc_params).fetchall()
    doctor_totals = [dict(r) for r in doctor_rows]

    # Summary counts (payments + unique patients) for current doctor/date filter
    summary_total_cents = 0
    summary_payments_count = 0
    summary_unique_patients = 0
    conn2 = db()
    try:
        cur2 = conn2.cursor()
        base = """
            SELECT COALESCE(SUM(amount_cents), 0) as total_cents,
                   COUNT(*) as payments_count,
                   COUNT(DISTINCT patient_id) as patients_count
            FROM payments
            WHERE amount_cents > 0
        """
        conditions = []
        params2: list[str] = []
        if from_date and to_date:
            conditions.append("paid_at BETWEEN ? AND ?")
            params2.extend([from_date, to_date])
        if doctor_filter == ANY_DOCTOR_ID:
            ids = [ANY_DOCTOR_ID] + [d for d in deleted_ids]
            placeholders = ",".join("?" for _ in ids)
            conditions.append(f"doctor_id IN ({placeholders})")
            params2.extend(ids)
        elif doctor_id_for_query:
            conditions.append("doctor_id = ?")
            params2.append(doctor_id_for_query)
        if conditions:
            base = base + " AND " + " AND ".join(conditions)
        row = cur2.execute(base, tuple(params2)).fetchone()
        if row:
            summary_total_cents = row["total_cents"] or 0
            summary_payments_count = row["payments_count"] or 0
            summary_unique_patients = row["patients_count"] or 0
    finally:
        conn2.close()

    conn.close()
    summary_total = (summary_total_cents or 0) / 100.0
    summary_total_fmt = f"{summary_total:.2f}"
    doctors = get_active_doctor_options(include_any=True)
    return render_page(
        "reports/collections.html",
        tab=tab,
        rows=rows_page,
        range_mode=range_mode,
        from_date=from_date,
        to_date=to_date,
        summary_total=summary_total,
        summary_total_fmt=summary_total_fmt,
        summary_count=summary_count,
        summary_payments_count=summary_payments_count,
        summary_unique_patients=summary_unique_patients,
        doctor_totals=doctor_totals,
        doctor_filter=doctor_filter,
        doctors=doctors,
        export_url=export_url,
        page=pagination["page"],
        has_prev=pagination["has_prev"],
        has_next=pagination["has_next"],
        total_pages=pagination["total_pages"],
        show_back=True,
    )


@bp.route("/collections/doctors")
@require_permission("reports:view")
def collections_doctors():
    """Doctor-focused collections analytics."""
    tab = request.args.get("tab") or "daily"
    from_date, to_date = _range_args()

    # Doctor selection: specific doctor or Any Doctor
    doctors = get_active_doctor_options(include_any=True)
    doctor_filter = request.args.get("doctor") or (doctors[0]["doctor_id"] if doctors else None)
    doctor_id_for_query = doctor_filter

    deleted_ids = {d["doctor_id"] for d in get_deleted_doctors()}
    conn = db()
    cur = conn.cursor()
    rows_data: list[dict] = []
    export_url = ""
    range_mode = False

    if doctor_id_for_query:
        if tab == "monthly":
            if from_date and to_date:
                range_mode = True
                base = """
                    SELECT COALESCE(SUM(amount_cents), 0) as amt
                    FROM payments
                    WHERE amount_cents > 0
                """
                conditions: list[str] = []
                params: list[str] = []
                conditions.append("paid_at BETWEEN ? AND ?")
                params.extend([from_date, to_date])
                if doctor_filter == ANY_DOCTOR_ID:
                    ids = [ANY_DOCTOR_ID] + [d for d in deleted_ids]
                    placeholders = ",".join("?" for _ in ids)
                    conditions.append(f"doctor_id IN ({placeholders})")
                    params.extend(ids)
                else:
                    conditions.append("doctor_id = ?")
                    params.append(doctor_id_for_query)
                if conditions:
                    base = base + " AND " + " AND ".join(conditions)
                row = cur.execute(base, tuple(params)).fetchone()
                if row and (row["amt"] or 0):
                    rows_data = [
                        {"month": f"{from_date} \u2192 {to_date}", "amt": row["amt"] or 0}
                    ]
                export_url = url_for(
                    "reports.export_range_csv",
                    f=from_date or "",
                    t=to_date or "",
                    doctor=doctor_id_for_query,
                )
            else:
                if doctor_filter == ANY_DOCTOR_ID:
                    ids = [ANY_DOCTOR_ID] + [d for d in deleted_ids]
                    placeholders = ",".join("?" for _ in ids)
                    query = """
                        SELECT substr(paid_at,1,7) as month, SUM(amount_cents) as amt
                        FROM payments
                        WHERE amount_cents > 0
                    """
                    conditions: list[str] = []
                    params: list[str] = []
                    if from_date and to_date:
                        conditions.append("paid_at BETWEEN ? AND ?")
                        params.extend([from_date, to_date])
                    conditions.append(f"doctor_id IN ({placeholders})")
                    params.extend(ids)
                    if conditions:
                        query = query + " AND " + " AND ".join(conditions)
                    query += "\nGROUP BY substr(paid_at,1,7)\nORDER BY month DESC"
                else:
                    query, params = _monthly_totals_query(from_date, to_date, doctor_id_for_query)
                rows = cur.execute(query, params).fetchall()
                rows_data = [dict(r) for r in rows]
                export_url = url_for(
                    "reports.export_monthly_csv",
                    f=from_date or "",
                    t=to_date or "",
                    doctor=doctor_id_for_query,
                )
        else:
            if doctor_filter == ANY_DOCTOR_ID:
                ids = [ANY_DOCTOR_ID] + [d for d in deleted_ids]
                placeholders = ",".join("?" for _ in ids)
                query = """
                    SELECT paid_at, SUM(amount_cents) as amt
                    FROM payments
                    WHERE amount_cents > 0
                """
                conditions: list[str] = []
                params: list[str] = []
                if from_date and to_date:
                    conditions.append("paid_at BETWEEN ? AND ?")
                    params.extend([from_date, to_date])
                conditions.append(f"doctor_id IN ({placeholders})")
                params.extend(ids)
                if conditions:
                    query = query + " AND " + " AND ".join(conditions)
                query += "\nGROUP BY paid_at\nORDER BY paid_at DESC"
            else:
                query, params = _daily_totals_query(from_date, to_date, doctor_id_for_query)
            rows = cur.execute(query, params).fetchall()
            rows_data = [dict(r) for r in rows]
            export_url = url_for(
                "reports.export_daily_csv",
                f=from_date or "",
                t=to_date or "",
                doctor=doctor_id_for_query,
            )

    # All-time totals for this doctor
    all_time_total_cents = 0
    summary_total_cents = 0
    summary_payments_count = 0
    summary_unique_patients = 0

    if doctor_id_for_query:
        conn2 = db()
        try:
            cur2 = conn2.cursor()

            if doctor_filter == ANY_DOCTOR_ID:
                ids = [ANY_DOCTOR_ID] + [d for d in deleted_ids]
                placeholders = ",".join("?" for _ in ids)
                all_time_row = cur2.execute(
                    f"""
                    SELECT COALESCE(SUM(amount_cents), 0) AS total_cents
                    FROM payments
                    WHERE amount_cents > 0 AND doctor_id IN ({placeholders})
                    """,
                    tuple(ids),
                ).fetchone()
            else:
                all_time_row = cur2.execute(
                    """
                    SELECT COALESCE(SUM(amount_cents), 0) AS total_cents
                    FROM payments
                    WHERE amount_cents > 0 AND doctor_id = ?
                    """,
                    (doctor_id_for_query,),
                ).fetchone()
            if all_time_row:
                all_time_total_cents = all_time_row["total_cents"] or 0

            # Filtered period for this doctor
            base = """
                SELECT COALESCE(SUM(amount_cents), 0) as total_cents,
                       COUNT(*) as payments_count,
                       COUNT(DISTINCT patient_id) as patients_count
                FROM payments
                WHERE amount_cents > 0
            """
            conditions: list[str] = []
            params2: list[str] = []
            if doctor_filter == ANY_DOCTOR_ID:
                ids = [ANY_DOCTOR_ID] + [d for d in deleted_ids]
                placeholders = ",".join("?" for _ in ids)
                conditions.append(f"doctor_id IN ({placeholders})")
                params2.extend(ids)
            else:
                conditions.append("doctor_id = ?")
                params2.append(doctor_id_for_query)
            if from_date and to_date:
                conditions.append("paid_at BETWEEN ? AND ?")
                params2.extend([from_date, to_date])
            if conditions:
                base = base + " AND " + " AND ".join(conditions)
            row = cur2.execute(base, tuple(params2)).fetchone()
            if row:
                summary_total_cents = row["total_cents"] or 0
                summary_payments_count = row["payments_count"] or 0
                summary_unique_patients = row["patients_count"] or 0
        finally:
            conn2.close()

    conn.close()

    all_time_total = (all_time_total_cents or 0) / 100.0
    all_time_total_fmt = f"{all_time_total:.2f}"
    summary_total = (summary_total_cents or 0) / 100.0
    summary_total_fmt = f"{summary_total:.2f}"

    rows_page, pagination = _paginate_rows(rows_data)

    return render_page(
        "reports/collections_doctors.html",
        tab=tab,
        rows=rows_page,
        range_mode=range_mode,
        from_date=from_date,
        to_date=to_date,
        doctor_filter=doctor_id_for_query,
        doctors=doctors,
        all_time_total=all_time_total,
        all_time_total_fmt=all_time_total_fmt,
        summary_total=summary_total,
        summary_total_fmt=summary_total_fmt,
        summary_payments_count=summary_payments_count,
        summary_unique_patients=summary_unique_patients,
        export_url=export_url,
        page=pagination["page"],
        has_prev=pagination["has_prev"],
        has_next=pagination["has_next"],
        total_pages=pagination["total_pages"],
        show_back=True,
    )


@bp.route("/collections/day/<d>")
@require_permission("reports:view")
def collections_day(d):
    doctor = request.args.get("doctor") or None
    deleted_ids = {d["doctor_id"] for d in get_deleted_doctors()}
    doctor_id = doctor if doctor and doctor != "all" else None

    conn = db()
    cur = conn.cursor()
    query = """
        SELECT pay.paid_at,
               pay.patient_id,
               p.full_name,
               pay.amount_cents,
               pay.method,
               pay.doctor_id,
               pay.doctor_label
        FROM payments pay JOIN patients p ON p.id=pay.patient_id
        WHERE pay.paid_at=? AND pay.amount_cents > 0
    """
    params: list[str] = [d]
    if doctor_id:
        if doctor_id == ANY_DOCTOR_ID:
            ids = [ANY_DOCTOR_ID] + [doc for doc in deleted_ids]
            placeholders = ",".join("?" for _ in ids)
            query += f" AND pay.doctor_id IN ({placeholders})"
            params.extend(ids)
        else:
            query += " AND pay.doctor_id = ?"
            params.append(doctor_id)
    query += " ORDER BY p.full_name"

    rows = cur.execute(query, tuple(params)).fetchall()
    rows_data = [dict(r) for r in rows]
    conn.close()

    if request.args.get("format") == "json":
        total_cents = sum((r.get("amount_cents") or 0) for r in rows_data)
        total_amount = total_cents / 100.0
        payments_count = len(rows_data)
        unique_patients = len({r.get("patient_id") for r in rows_data})
        return jsonify(
            {
                "title": f"Day {d}",
                "summary_total": total_amount,
                "summary_total_fmt": f"{total_amount:.2f}",
                "payments_count": payments_count,
                "patients_count": unique_patients,
                "rows": [
                    {
                        "paid_at": r["paid_at"],
                        "patient_id": r["patient_id"],
                        "patient_url": url_for(
                            "patients.patient_detail", pid=r["patient_id"]
                        ),
                        "full_name": r["full_name"],
                        "amount": (r["amount_cents"] or 0) / 100.0,
                        "amount_fmt": f"{(r['amount_cents'] or 0) / 100:.2f}",
                        "method": r["method"] or "",
                        "doctor_label": (
                            ANY_DOCTOR_LABEL
                            if r.get("doctor_id") in deleted_ids
                            else (r.get("doctor_label") or "")
                        ),
                    }
                    for r in rows_data
                ],
                "export_url": url_for("reports.export_day_csv", d=d, doctor=doctor or ""),
            }
        )

    return render_page(
        "reports/details.html",
        rows=rows_data,
        title=f"Day {d}",
        back_href=url_for("reports.collections", tab="daily"),
        export_url=url_for("reports.export_day_csv", d=d),
        show_back=True,
    )


@bp.route("/collections/month/<m>")
@require_permission("reports:view")
def collections_month(m):
    from_date = request.args.get("f") or None
    to_date = request.args.get("t") or None
    doctor = request.args.get("doctor") or None
    deleted_ids = {d["doctor_id"] for d in get_deleted_doctors()}
    doctor_id = doctor if doctor and doctor != "all" else None

    conn = db()
    cur = conn.cursor()
    query = """
        SELECT pay.paid_at,
               pay.patient_id,
               p.full_name,
               pay.amount_cents,
               pay.method,
               pay.doctor_id,
               pay.doctor_label
        FROM payments pay JOIN patients p ON p.id=pay.patient_id
        WHERE substr(pay.paid_at,1,7)=?
          AND (? IS NULL OR ? IS NULL OR pay.paid_at BETWEEN ? AND ?)
          AND pay.amount_cents > 0
    """
    params: list[str] = [m, from_date, to_date, from_date or "", to_date or ""]
    if doctor_id:
        if doctor_id == ANY_DOCTOR_ID:
            ids = [ANY_DOCTOR_ID] + [doc for doc in deleted_ids]
            placeholders = ",".join("?" for _ in ids)
            query += f" AND pay.doctor_id IN ({placeholders})"
            params.extend(ids)
        else:
            query += " AND pay.doctor_id = ?"
            params.append(doctor_id)
    query += " ORDER BY pay.paid_at DESC, p.full_name"

    rows = cur.execute(query, tuple(params)).fetchall()
    rows_data = [dict(r) for r in rows]
    conn.close()

    title = f"{from_date} to {to_date}" if (from_date and to_date) else f"Month {m}"

    if request.args.get("format") == "json":
        total_cents = sum((r.get("amount_cents") or 0) for r in rows_data)
        total_amount = total_cents / 100.0
        payments_count = len(rows_data)
        unique_patients = len({r.get("patient_id") for r in rows_data})
        return jsonify(
            {
                "title": title,
                "summary_total": total_amount,
                "summary_total_fmt": f"{total_amount:.2f}",
                "payments_count": payments_count,
                "patients_count": unique_patients,
                "rows": [
                    {
                        "paid_at": r["paid_at"],
                        "patient_id": r["patient_id"],
                        "patient_url": url_for(
                            "patients.patient_detail", pid=r["patient_id"]
                        ),
                        "full_name": r["full_name"],
                        "amount": (r["amount_cents"] or 0) / 100.0,
                        "amount_fmt": f"{(r['amount_cents'] or 0) / 100:.2f}",
                        "method": r["method"] or "",
                        "doctor_label": (
                            ANY_DOCTOR_LABEL
                            if r.get("doctor_id") in deleted_ids
                            else (r.get("doctor_label") or "")
                        ),
                    }
                    for r in rows_data
                ],
                "export_url": url_for(
                    "reports.export_month_csv", m=m, doctor=doctor or ""
                ),
            }
        )

    return render_page(
        "reports/details.html",
        rows=rows_data,
        title=title,
        back_href=url_for(
            "reports.collections",
            tab="monthly",
            f=from_date or "",
            t=to_date or "",
        ),
        export_url=url_for("reports.export_month_csv", m=m),
        show_back=True,
    )


@bp.route("/collections/range")
@require_permission("reports:view")
def collections_range():
    """Details for a custom date range (used by monthly range view)."""
    from_date = request.args.get("f") or None
    to_date = request.args.get("t") or None
    doctor = request.args.get("doctor") or None
    deleted_ids = {d["doctor_id"] for d in get_deleted_doctors()}

    if not from_date or not to_date:
        return redirect(url_for("reports.collections", tab="monthly"))

    doctor_id = doctor if doctor and doctor not in {"all", ""} else None

    conn = db()
    cur = conn.cursor()
    query = """
        SELECT pay.paid_at,
               pay.patient_id,
               p.full_name,
               pay.amount_cents,
               pay.method,
               pay.doctor_id,
               pay.doctor_label
        FROM payments pay JOIN patients p ON p.id=pay.patient_id
        WHERE pay.paid_at BETWEEN ? AND ?
          AND pay.amount_cents > 0
    """
    params: list[str] = [from_date, to_date]
    if doctor_id:
        if doctor_id == ANY_DOCTOR_ID:
            ids = [ANY_DOCTOR_ID] + [doc for doc in deleted_ids]
            placeholders = ",".join("?" for _ in ids)
            query += f" AND pay.doctor_id IN ({placeholders})"
            params.extend(ids)
        else:
            query += " AND pay.doctor_id = ?"
            params.append(doctor_id)
    query += " ORDER BY pay.paid_at DESC, p.full_name"

    rows = cur.execute(query, tuple(params)).fetchall()
    rows_data = [dict(r) for r in rows]
    conn.close()

    title = f"{from_date} to {to_date}"

    if request.args.get("format") == "json":
        total_cents = sum((r.get("amount_cents") or 0) for r in rows_data)
        total_amount = total_cents / 100.0
        payments_count = len(rows_data)
        unique_patients = len({r.get("patient_id") for r in rows_data})
        return jsonify(
            {
                "title": title,
                "summary_total": total_amount,
                "summary_total_fmt": f"{total_amount:.2f}",
                "payments_count": payments_count,
                "patients_count": unique_patients,
                "rows": [
                    {
                        "paid_at": r["paid_at"],
                        "patient_id": r["patient_id"],
                        "patient_url": url_for(
                            "patients.patient_detail", pid=r["patient_id"]
                        ),
                        "full_name": r["full_name"],
                        "amount": (r["amount_cents"] or 0) / 100.0,
                        "amount_fmt": f"{(r['amount_cents'] or 0) / 100:.2f}",
                        "method": r["method"] or "",
                        "doctor_label": (
                            ANY_DOCTOR_LABEL
                            if r.get("doctor_id") in deleted_ids
                            else (r.get("doctor_label") or "")
                        ),
                    }
                    for r in rows_data
                ],
                "export_url": url_for(
                    "reports.export_range_csv",
                    f=from_date,
                    t=to_date,
                    doctor=doctor or "",
                ),
            }
        )

    return render_page(
        "reports/details.html",
        rows=rows_data,
        title=title,
        back_href=url_for(
            "reports.collections",
            tab="monthly",
            f=from_date or "",
            t=to_date or "",
        ),
        export_url=url_for(
            "reports.export_range_csv",
            f=from_date,
            t=to_date,
            doctor=doctor or "",
        ),
        show_back=True,
    )


@bp.route("/export/collections/daily.csv")
@require_permission("reports:view")
def export_daily_csv():
    f, t = _range_args()
    doctor = request.args.get("doctor") or "all"
    deleted_ids = {d["doctor_id"] for d in get_deleted_doctors()}
    doctor_id = None if doctor == "all" else doctor
    conn = db()
    cur = conn.cursor()
    if doctor == ANY_DOCTOR_ID:
        ids = [ANY_DOCTOR_ID] + [d for d in deleted_ids]
        placeholders = ",".join("?" for _ in ids)
        query = dedent(
            """
            SELECT paid_at, SUM(amount_cents) as amt
            FROM payments
            WHERE amount_cents > 0
            """
        )
        conditions = []
        params: list[str] = []
        if f and t:
            conditions.append("paid_at BETWEEN ? AND ?")
            params.extend([f, t])
        conditions.append(f"doctor_id IN ({placeholders})")
        params.extend(ids)
        if conditions:
            query = query + " AND " + " AND ".join(conditions)
        query = query + "\nGROUP BY paid_at\nORDER BY paid_at DESC"
    else:
        query, params = _daily_totals_export_query(f, t, doctor_id)
    rows = cur.execute(query, params).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "collected"])
    for r in rows:
        w.writerow([r["paid_at"], f"{(r['amt'] or 0)/100:.2f}"])
    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    conn.close()
    return send_file(
        io.BytesIO(buf.read().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"collections-daily-{ts}.csv",
    )


@bp.route("/export/collections/monthly.csv")
@require_permission("reports:view")
def export_monthly_csv():
    f, t = _range_args()
    doctor = request.args.get("doctor") or "all"
    deleted_ids = {d["doctor_id"] for d in get_deleted_doctors()}
    doctor_id = None if doctor == "all" else doctor
    conn = db()
    cur = conn.cursor()
    if doctor == ANY_DOCTOR_ID:
        ids = [ANY_DOCTOR_ID] + [d for d in deleted_ids]
        placeholders = ",".join("?" for _ in ids)
        query = dedent(
            """
            SELECT substr(paid_at,1,7) as month, SUM(amount_cents) as amt
            FROM payments
            WHERE amount_cents > 0
            """
        )
        conditions = []
        params: list[str] = []
        if f and t:
            conditions.append("paid_at BETWEEN ? AND ?")
            params.extend([f, t])
        conditions.append(f"doctor_id IN ({placeholders})")
        params.extend(ids)
        if conditions:
            query = query + " AND " + " AND ".join(conditions)
        query = query + "\nGROUP BY substr(paid_at,1,7)\nORDER BY month DESC"
    else:
        query, params = _monthly_totals_export_query(f, t, doctor_id)
    rows = cur.execute(query, params).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["month", "collected"])
    for r in rows:
        w.writerow([r["month"], f"{(r['amt'] or 0)/100:.2f}"])
    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    conn.close()
    return send_file(
        io.BytesIO(buf.read().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"collections-monthly-{ts}.csv",
    )


@bp.route("/export/collections/range.csv")
@require_permission("reports:view")
def export_range_csv():
    """Export detailed payments for a custom date range."""
    f = request.args.get("f") or None
    t = request.args.get("t") or None
    doctor = request.args.get("doctor") or None
    deleted_ids = {d["doctor_id"] for d in get_deleted_doctors()}
    if not f or not t:
        return redirect(url_for("reports.collections", tab="monthly"))

    doctor_id = doctor if doctor and doctor not in {"all", ""} else None

    conn = db()
    cur = conn.cursor()
    query = """
        SELECT pay.paid_at, p.full_name, pay.amount_cents, pay.method
        FROM payments pay JOIN patients p ON p.id=pay.patient_id
        WHERE pay.paid_at BETWEEN ? AND ? AND pay.amount_cents > 0
    """
    params: list[str] = [f, t]
    if doctor_id:
        if doctor_id == ANY_DOCTOR_ID:
            ids = [ANY_DOCTOR_ID] + [doc for doc in deleted_ids]
            placeholders = ",".join("?" for _ in ids)
            query += f" AND pay.doctor_id IN ({placeholders})"
            params.extend(ids)
        else:
            query += " AND pay.doctor_id = ?"
            params.append(doctor_id)
    query += " ORDER BY pay.paid_at DESC, p.full_name"

    rows = cur.execute(query, tuple(params)).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "patient", "paid_today", "method"])
    for r in rows:
        w.writerow(
            [
                r["paid_at"],
                r["full_name"],
                f"{(r['amount_cents'] or 0)/100:.2f}",
                r["method"] or "",
            ]
        )
    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    conn.close()
    return send_file(
        io.BytesIO(buf.read().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"collections-range-{f}-to-{t}-{ts}.csv",
    )


@bp.route("/export/collections/day/<d>.csv")
@require_permission("reports:view")
def export_day_csv(d):
    doctor = request.args.get("doctor") or None
    deleted_ids = {d["doctor_id"] for d in get_deleted_doctors()}
    doctor_id = doctor if doctor and doctor not in {"all", ""} else None

    conn = db()
    cur = conn.cursor()
    query = """
        SELECT pay.paid_at, p.full_name, pay.amount_cents, pay.method
        FROM payments pay JOIN patients p ON p.id=pay.patient_id
        WHERE pay.paid_at=? AND pay.amount_cents > 0
    """
    params: list[str] = [d]
    if doctor_id:
        if doctor_id == ANY_DOCTOR_ID:
            ids = [ANY_DOCTOR_ID] + [doc for doc in deleted_ids]
            placeholders = ",".join("?" for _ in ids)
            query += f" AND pay.doctor_id IN ({placeholders})"
            params.extend(ids)
        else:
            query += " AND pay.doctor_id = ?"
            params.append(doctor_id)
    query += " ORDER BY p.full_name"

    rows = cur.execute(query, tuple(params)).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "patient", "paid_today", "method"])
    for r in rows:
        w.writerow([r["paid_at"], r["full_name"], f"{(r['amount_cents'] or 0)/100:.2f}", r["method"] or ""])
    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    conn.close()
    return send_file(
        io.BytesIO(buf.read().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"collections-day-{d}-{ts}.csv",
    )


@bp.route("/export/collections/month/<m>.csv")
@require_permission("reports:view")
def export_month_csv(m):
    doctor = request.args.get("doctor") or None
    deleted_ids = {d["doctor_id"] for d in get_deleted_doctors()}
    doctor_id = doctor if doctor and doctor not in {"all", ""} else None

    conn = db()
    cur = conn.cursor()
    query = """
        SELECT pay.paid_at, p.full_name, pay.amount_cents, pay.method
        FROM payments pay JOIN patients p ON p.id=pay.patient_id
        WHERE substr(pay.paid_at,1,7)=? AND pay.amount_cents > 0
    """
    params: list[str] = [m]
    if doctor_id:
        if doctor_id == ANY_DOCTOR_ID:
            ids = [ANY_DOCTOR_ID] + [doc for doc in deleted_ids]
            placeholders = ",".join("?" for _ in ids)
            query += f" AND pay.doctor_id IN ({placeholders})"
            params.extend(ids)
        else:
            query += " AND pay.doctor_id = ?"
            params.append(doctor_id)
    query += " ORDER BY pay.paid_at DESC, p.full_name"

    rows = cur.execute(query, tuple(params)).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "patient", "paid_today", "method"])
    for r in rows:
        w.writerow([r["paid_at"], r["full_name"], f"{(r['amount_cents'] or 0)/100:.2f}", r["method"] or ""])
    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    conn.close()
    return send_file(
        io.BytesIO(buf.read().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"collections-month-{m}-{ts}.csv",
    )
