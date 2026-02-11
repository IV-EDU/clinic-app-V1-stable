"""Simple expense service for easy receipt tracking."""

from __future__ import annotations

from datetime import datetime, timezone, date
import sqlite3
import uuid
from typing import Sequence

from flask import current_app

from clinic_app.services.database import db


class SimpleExpenseError(Exception):
    """Base exception for simple expense operations."""


def check_for_duplicates(receipt_date: str, amount: float, description: str, created_by: str) -> list[dict]:
    """Check for potential duplicate expenses."""
    conn = db()
    try:
        # Normalize description for comparison (case insensitive, trim whitespace)
        normalized_desc = description.strip().lower()
        
        # Find expenses with same date, amount, and similar description
        duplicates = conn.execute(
            """
            SELECT id, receipt_date, amount, description, created_at
            FROM simple_expenses
            WHERE receipt_date = ?
              AND amount = ?
              AND LOWER(TRIM(description)) LIKE ?
              AND created_by = ?
            ORDER BY created_at DESC
            """,
            (receipt_date, amount, f"%{normalized_desc}%", created_by)
        ).fetchall()
        
        return [dict(row) for row in duplicates]
    finally:
        conn.close()


def create_simple_expense(form_data: dict, *, actor_id: str, check_duplicates: bool = True) -> tuple[str, list[dict]]:
    """Create a simple expense entry with optional duplicate checking."""
    required_fields = ['receipt_date', 'amount', 'description']
    for field in required_fields:
        if not form_data.get(field, '').strip():
            raise SimpleExpenseError(f"{field}_required")
    
    # Clean and validate data
    receipt_date = form_data['receipt_date']
    amount = float(form_data['amount'])
    description = form_data['description'].strip()
    
    # Check for duplicates if requested
    duplicates = []
    if check_duplicates:
        duplicates = check_for_duplicates(receipt_date, amount, description, actor_id)
    
    expense_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        
        conn.execute(
            """
            INSERT INTO simple_expenses(
                id, receipt_date, amount, description, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                expense_id,
                receipt_date,
                amount,
                description,
                actor_id,
                created_at
            )
        )
        
        conn.commit()
        return expense_id, duplicates
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def merge_duplicate_expenses(original_id: str, duplicate_id: str, *, actor_id: str) -> None:
    """Merge two duplicate expenses into one."""
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        
        # Get the original expense
        original = conn.execute(
            "SELECT amount FROM simple_expenses WHERE id = ?",
            (original_id,)
        ).fetchone()
        
        if not original:
            raise SimpleExpenseError("original_expense_not_found")
        
        # Delete the duplicate
        conn.execute("DELETE FROM simple_expenses WHERE id = ?", (duplicate_id,))
        
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_simple_expenses(limit: int = 50, offset: int = 0,
                        start_date: str | None = None,
                        end_date: str | None = None) -> list[dict]:
    """Get list of simple expenses."""
    conn = db()
    try:
        params = []
        where_conditions = []
        
        if start_date:
            where_conditions.append("receipt_date >= ?")
            params.append(start_date)
        
        if end_date:
            where_conditions.append("receipt_date <= ?")
            params.append(end_date)
        
        where_clause = ""
        if where_conditions:
            where_clause = "WHERE " + " AND ".join(where_conditions)
        
        query = f"""
            SELECT id, receipt_date, amount, description, created_at
            FROM simple_expenses
            {where_clause}
            ORDER BY receipt_date DESC, created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        
        rows = conn.execute(query, params).fetchall()
        
        result = []
        for row in rows:
            result.append({
                'id': row['id'],
                'receipt_date': row['receipt_date'],
                'amount': row['amount'],
                'description': row['description'],
                'created_at': row['created_at']
            })
        
        return result
    finally:
        conn.close()


def get_monthly_spending(year: int, month: int) -> dict:
    """Get monthly spending summary."""
    conn = db()
    try:
        # Get total spending for the month
        month_str = f"{year:04d}-{month:02d}"
        
        total = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) as total_spending
            FROM simple_expenses
            WHERE substr(receipt_date, 1, 7) = ?
            """,
            (month_str,)
        ).fetchone()
        
        # Get daily breakdown
        daily = conn.execute(
            """
            SELECT receipt_date, SUM(amount) as daily_total
            FROM simple_expenses
            WHERE substr(receipt_date, 1, 7) = ?
            GROUP BY receipt_date
            ORDER BY receipt_date
            """,
            (month_str,)
        ).fetchall()
        
        # Get recent transactions
        recent = conn.execute(
            """
            SELECT receipt_date, amount, description
            FROM simple_expenses
            WHERE substr(receipt_date, 1, 7) = ?
            ORDER BY receipt_date DESC, created_at DESC
            LIMIT 10
            """,
            (month_str,)
        ).fetchall()
        
        return {
            'total_spending': total['total_spending'] if total else 0,
            'daily_breakdown': [{'date': row['receipt_date'], 'amount': row['daily_total']} for row in daily],
            'recent_transactions': [{'date': row['receipt_date'], 'amount': row['amount'], 'description': row['description']} for row in recent]
        }
    finally:
        conn.close()


def delete_simple_expense(expense_id: str, *, actor_id: str) -> None:
    """Delete a simple expense."""
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        
        # Check if expense exists
        existing = conn.execute(
            "SELECT id FROM simple_expenses WHERE id=?",
            (expense_id,)
        ).fetchone()
        
        if not existing:
            raise SimpleExpenseError("expense_not_found")
        
        conn.execute("DELETE FROM simple_expenses WHERE id=?", (expense_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()