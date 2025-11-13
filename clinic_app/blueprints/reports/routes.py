from __future__ import annotations

import csv
import io
from datetime import datetime
from textwrap import dedent

from flask import Blueprint, request, send_file, url_for, redirect

from clinic_app.services.database import db
from clinic_app.services.ui import render_page
from clinic_app.services.security import require_permission

bp = Blueprint("reports", __name__)


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


def _monthly_totals_query(
    start: str | None, end: str | None
) -> tuple[str, tuple[str, ...]]:
    if start and end:
        return (
            """
            SELECT substr(paid_at,1,7) as month, SUM(amount_cents) as amt
            FROM payments
            WHERE paid_at BETWEEN ? AND ?
            GROUP BY substr(paid_at,1,7)
            ORDER BY month DESC
            """,
            (start, end),
        )
    return (
        """
        SELECT substr(paid_at,1,7) as month, SUM(amount_cents) as amt
        FROM payments
        GROUP BY substr(paid_at,1,7)
        ORDER BY month DESC
        """,
        (),
    )


def _monthly_totals_export_query(
    start: str | None, end: str | None
) -> tuple[str, tuple[str, ...]]:
    base = dedent(
        """
        SELECT substr(paid_at,1,7) as month, SUM(amount_cents) as amt
        FROM payments
        WHERE amount_cents > 0
        """
    )
    suffix = "\nORDER BY month DESC"
    if start and end:
        return (
            base
            + " AND paid_at BETWEEN ? AND ?\nGROUP BY substr(paid_at,1,7)"
            + suffix,
            (start, end),
        )
    return (
        base + "\nGROUP BY substr(paid_at,1,7)" + suffix,
        (),
    )


def _daily_totals_query(
    start: str | None, end: str | None
) -> tuple[str, tuple[str, ...]]:
    if start and end:
        return (
            """
            SELECT paid_at, SUM(amount_cents) as amt
            FROM payments
            WHERE paid_at BETWEEN ? AND ?
            GROUP BY paid_at
            ORDER BY paid_at DESC
            """,
            (start, end),
        )
    return (
        """
        SELECT paid_at, SUM(amount_cents) as amt
        FROM payments
        GROUP BY paid_at
        ORDER BY paid_at DESC
        """,
        (),
    )


def _daily_totals_export_query(
    start: str | None, end: str | None
) -> tuple[str, tuple[str, ...]]:
    base = dedent(
        """
        SELECT paid_at, SUM(amount_cents) as amt
        FROM payments
        WHERE amount_cents > 0
        """
    )
    suffix = "\nORDER BY paid_at DESC"
    if start and end:
        return (
            base + " AND paid_at BETWEEN ? AND ?\nGROUP BY paid_at" + suffix,
            (start, end),
        )
    return (
        base + "\nGROUP BY paid_at" + suffix,
        (),
    )


@bp.route("/collections")
@require_permission("reports:view")
def collections():
    tab = request.args.get("tab") or "daily"
    from_date, to_date = _range_args()
    conn = db()
    cur = conn.cursor()
    rows = []
    if tab == "monthly":
        query, params = _monthly_totals_query(from_date, to_date)
        rows = cur.execute(query, params).fetchall()
        export_url = url_for(
            "reports.export_monthly_csv", f=from_date or "", t=to_date or ""
        )
    else:
        query, params = _daily_totals_query(from_date, to_date)
        rows = cur.execute(query, params).fetchall()
        export_url = url_for(
            "reports.export_daily_csv", f=from_date or "", t=to_date or ""
        )
    rows_data = [dict(r) for r in rows]
    conn.close()
    return render_page(
        "reports/collections.html",
        tab=tab,
        rows=rows_data,
        from_date=from_date,
        to_date=to_date,
        export_url=export_url,
        show_back=True,
    )


@bp.route("/collections/day/<d>")
@require_permission("reports:view")
def collections_day(d):
    conn = db()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT pay.paid_at, p.full_name, pay.amount_cents, pay.method
        FROM payments pay JOIN patients p ON p.id=pay.patient_id
        WHERE pay.paid_at=? AND pay.amount_cents > 0
        ORDER BY p.full_name
    """,
        (d,),
    ).fetchall()
    rows_data = [dict(r) for r in rows]
    conn.close()
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
    conn = db()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT pay.paid_at, p.full_name, pay.amount_cents, pay.method
        FROM payments pay JOIN patients p ON p.id=pay.patient_id
        WHERE substr(pay.paid_at,1,7)=? AND (? IS NULL OR ? IS NULL OR pay.paid_at BETWEEN ? AND ?) AND pay.amount_cents > 0
        ORDER BY pay.paid_at DESC, p.full_name
    """,
        (m, from_date, to_date, from_date or "", to_date or ""),
    ).fetchall()
    rows_data = [dict(r) for r in rows]
    conn.close()
    return render_page(
        "reports/details.html",
        rows=rows_data,
        title=(
            f"{from_date} to {to_date}" if (from_date and to_date) else f"Month {m}"
        ),
        back_href=url_for(
            "reports.collections",
            tab="monthly",
            f=from_date or "",
            t=to_date or "",
        ),
        export_url=url_for("reports.export_month_csv", m=m),
        show_back=True,
    )


@bp.route("/export/collections/daily.csv")
@require_permission("reports:view")
def export_daily_csv():
    f, t = _range_args()
    conn = db()
    cur = conn.cursor()
    query, params = _daily_totals_export_query(f, t)
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
    conn = db()
    cur = conn.cursor()
    query, params = _monthly_totals_export_query(f, t)
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


@bp.route("/export/collections/day/<d>.csv")
@require_permission("reports:view")
def export_day_csv(d):
    conn = db()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT pay.paid_at, p.full_name, pay.amount_cents, pay.method
        FROM payments pay JOIN patients p ON p.id=pay.patient_id
        WHERE pay.paid_at=? AND pay.amount_cents > 0
        ORDER BY p.full_name
    """,
        (d,),
    ).fetchall()
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
    conn = db()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT pay.paid_at, p.full_name, pay.amount_cents, pay.method
        FROM payments pay JOIN patients p ON p.id=pay.patient_id
        WHERE substr(pay.paid_at,1,7)=?
        ORDER BY pay.paid_at DESC, p.full_name
    """,
        (m,),
    ).fetchall()
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
