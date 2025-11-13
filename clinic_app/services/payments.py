"""Payment and money handling helpers shared across blueprints."""

from __future__ import annotations

import re
from datetime import date
from typing import Optional, Tuple

MAX_MONEY_CENTS = 10_000_000 * 100


def parse_money_to_cents(txt: str) -> int:
    txt = (txt or "").strip().replace(",", "")
    if txt == "":
        return 0
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]{1,2})?)\s*$", txt)
    return int(round(float(m.group(1)) * 100)) if m else 0


def cents_guard(value_cents: int, label: str) -> int:
    if value_cents is None:
        return 0
    if value_cents > MAX_MONEY_CENTS:
        raise ValueError(f"{label} too large (max 10,000,000.00).")
    if value_cents < -MAX_MONEY_CENTS:
        raise ValueError(f"{label} too negative (min -10,000,000.00).")
    return int(value_cents)


def money(cents: int) -> str:
    return f"{(cents or 0) / 100:.2f}"


def money_input(cents: Optional[int]) -> str:
    c = cents or 0
    if c % 100 == 0:
        return str(int(c // 100))
    s = f"{c / 100:.2f}".rstrip("0").rstrip(".")
    return s


def validate_payment_fields(
    total_cents_raw: int,
    discount_cents_raw: int,
    down_cents_raw: int,
    exam: bool,
) -> Tuple[bool, int | str]:
    if discount_cents_raw < 0:
        discount_cents_raw = 0
    if discount_cents_raw > total_cents_raw:
        return False, "err_discount_gt_total"
    due_cents = total_cents_raw - discount_cents_raw
    if down_cents_raw > due_cents:
        return False, "err_overpaid"
    return True, due_cents


def overall_remaining(conn, pid: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(
            CASE
              WHEN (COALESCE(total_amount_cents,0) - COALESCE(discount_cents,0) - COALESCE(amount_cents,0)) < 0
              THEN 0
              ELSE (COALESCE(total_amount_cents,0) - COALESCE(discount_cents,0) - COALESCE(amount_cents,0))
            END
        ), 0) AS rem
        FROM payments
        WHERE patient_id=?
        """,
        (pid,),
    ).fetchone()
    return int(row["rem"] or 0)


def today_collected(conn) -> int:
    today = date.today().isoformat()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_cents),0) AS s FROM payments WHERE paid_at=?",
        (today,),
    ).fetchone()
    return int(row["s"] or 0)


def bal_class_nonneg(cents: int) -> str:
    return "bal-0" if cents == 0 else "bal-pos"
