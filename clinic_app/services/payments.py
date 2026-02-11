"""Payment and money handling helpers shared across blueprints."""

from __future__ import annotations

import re
from datetime import date
from typing import List, Optional, Tuple, Dict, Any

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
        SELECT COALESCE(
            SUM(
                CASE
                    WHEN (
                        (COALESCE(parent.total_amount_cents, 0) - COALESCE(parent.discount_cents, 0))
                        - (COALESCE(parent.amount_cents, 0) + COALESCE(children.child_paid_cents, 0))
                    ) < 0 THEN 0
                    ELSE (
                        (COALESCE(parent.total_amount_cents, 0) - COALESCE(parent.discount_cents, 0))
                        - (COALESCE(parent.amount_cents, 0) + COALESCE(children.child_paid_cents, 0))
                    )
                END
            ),
            0
        ) AS rem
          FROM payments parent
          LEFT JOIN (
              SELECT parent_payment_id, patient_id, COALESCE(SUM(amount_cents), 0) AS child_paid_cents
                FROM payments
               WHERE COALESCE(parent_payment_id, '') <> ''
               GROUP BY parent_payment_id, patient_id
          ) children
            ON children.parent_payment_id = parent.id
           AND children.patient_id = parent.patient_id
         WHERE parent.patient_id = ?
           AND COALESCE(parent.parent_payment_id, '') = ''
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


# =============================================================================
# Treatment-based payment helpers
# =============================================================================


def get_treatments_for_patient(conn, patient_id: str) -> List[Dict[str, Any]]:
    """
    Get all treatments for a patient, with their payments grouped.
    A treatment is a payment where parent_payment_id IS NULL.
    Child payments have parent_payment_id pointing to the treatment.
    """
    # Get all treatments (parent payments) for this patient
    treatments = conn.execute(
        """
        SELECT 
            p.id,
            p.paid_at,
            p.treatment,
            p.total_amount_cents,
            p.discount_cents,
            p.amount_cents,
            p.remaining_cents,
            p.method,
            p.note,
            p.doctor_id,
            p.doctor_label,
            p.examination_flag,
            p.followup_flag,
            p.created_at
        FROM payments p
        WHERE p.patient_id = ? AND (p.parent_payment_id IS NULL OR p.parent_payment_id = '')
        ORDER BY p.paid_at DESC, p.created_at DESC
        """,
        (patient_id,)
    ).fetchall()

    result = []
    for treatment in treatments:
        treatment_dict = dict(treatment)
        
        # Get child payments for this treatment
        child_payments = conn.execute(
            """
            SELECT 
                p.id,
                p.paid_at,
                p.amount_cents,
                p.method,
                p.note,
                p.doctor_id,
                p.doctor_label,
                p.created_at
            FROM payments p
            WHERE p.parent_payment_id = ?
            ORDER BY p.paid_at DESC, p.created_at DESC
            """,
            (treatment["id"],)
        ).fetchall()
        
        child_list = [dict(c) for c in child_payments]
        
        # Calculate totals
        total_paid = (treatment["amount_cents"] or 0) + sum(
            (c["amount_cents"] or 0) for c in child_list
        )
        total_cost = (treatment["total_amount_cents"] or 0)
        discount = (treatment["discount_cents"] or 0)
        due = max(total_cost - discount, 0)
        remaining = max(due - total_paid, 0)
        
        # Determine status
        if total_paid == 0 and due == 0:
            status = "visit"  # Visit only, no payment expected
        elif remaining == 0:
            status = "complete"
        else:
            status = "active"
        
        treatment_dict.update({
            "payments": child_list,
            "total_paid_cents": total_paid,
            "total_due_cents": due,
            "remaining_cents": remaining,
            "status": status,
            "is_visit_only": total_paid == 0 and due == 0,
            "payment_count": len(child_list) + (1 if treatment["amount_cents"] else 0),
        })
        
        result.append(treatment_dict)
    
    return result


def get_treatment_with_payments(conn, treatment_id: str) -> Optional[Dict[str, Any]]:
    """Get a single treatment with all its payments."""
    treatment = conn.execute(
        "SELECT * FROM payments WHERE id = ? AND (parent_payment_id IS NULL OR parent_payment_id = '')",
        (treatment_id,)
    ).fetchone()
    
    if not treatment:
        return None
    
    treatment_dict = dict(treatment)
    
    child_payments = conn.execute(
        """
        SELECT * FROM payments 
        WHERE parent_payment_id = ?
        ORDER BY paid_at DESC, created_at DESC
        """,
        (treatment_id,)
    ).fetchall()
    
    treatment_dict["payments"] = [dict(c) for c in child_payments]
    return treatment_dict


def add_payment_to_treatment(
    conn,
    treatment_id: str,
    patient_id: str,
    amount_cents: int,
    paid_at: str,
    method: str,
    note: str,
    doctor_id: str,
    doctor_label: str,
) -> str:
    """Add a child payment to an existing treatment."""
    import uuid
    
    payment_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO payments (
            id, patient_id, parent_payment_id, paid_at, amount_cents,
            method, note, doctor_id, doctor_label,
            total_amount_cents, remaining_cents, discount_cents,
            examination_flag, followup_flag
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0)
        """,
        (
            payment_id, patient_id, treatment_id, paid_at, amount_cents,
            method, note, doctor_id, doctor_label,
        )
    )
    conn.commit()
    return payment_id


def get_treatment_status_label(status: str) -> str:
    """Get display label for treatment status."""
    labels = {
        "complete": "Complete",
        "active": "Active",
        "visit": "Visit Only",
    }
    return labels.get(status, status)
