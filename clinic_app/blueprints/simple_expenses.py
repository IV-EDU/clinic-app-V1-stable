"""Simple expense routes for easy receipt entry."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
from flask import Blueprint, flash, redirect, request, url_for, jsonify
from flask_login import current_user

from clinic_app.services.ui import render_page
from clinic_app.services.security import require_permission
from clinic_app.services.simple_expenses import (
    create_simple_expense,
    list_simple_expenses,
    get_monthly_spending,
    merge_duplicate_expenses,
    delete_simple_expense,
    SimpleExpenseError,
)
from clinic_app.forms.simple_expenses import SimpleExpenseForm

bp = Blueprint("simple_expenses", __name__, url_prefix="/simple-expenses")


def _format_money(amount: float) -> str:
    """Format money value to display string."""
    return f"{amount:.2f}"


def _parse_month(month_value: str | None, today: date) -> tuple[int, int]:
    """Parse month picker value (YYYY-MM) and fall back to current month."""
    if not month_value:
        return today.year, today.month

    try:
        parsed = datetime.strptime(month_value, "%Y-%m").date()
        return parsed.year, parsed.month
    except ValueError:
        return today.year, today.month


@bp.route("/", methods=["GET"])
@require_permission("expenses:view")
def index():
    """Simple expense dashboard with monthly summary and inline add form."""
    today = date.today()
    selected_month = request.args.get("month")
    year, month = _parse_month(selected_month, today)
    last_day = monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)

    form = SimpleExpenseForm()
    if not form.receipt_date.data:
        # Default to today's day when viewing the current month, otherwise first of selected month
        default_day = min(today.day, last_day) if (today.year, today.month) == (year, month) else 1
        form.receipt_date.data = date(year, month, default_day)

    try:
        monthly_data = get_monthly_spending(year, month)
        expenses = list_simple_expenses(
            limit=100,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )

        for expense in expenses:
            expense["amount_fmt"] = _format_money(expense["amount"])

        return render_page(
            "simple_expenses/index.html",
            form=form,
            monthly_total=monthly_data["total_spending"],
            monthly_total_fmt=_format_money(monthly_data["total_spending"]),
            recent_expenses=expenses,
            month_label=start_date.strftime("%B %Y"),
            selected_month=f"{year:04d}-{month:02d}",
            show_back=False,
        )
    except Exception as e:
        flash(f"Error loading expenses: {str(e)}", "err")
        return render_page(
            "simple_expenses/index.html",
            form=form,
            monthly_total=0,
            monthly_total_fmt=_format_money(0),
            recent_expenses=[],
            month_label=today.strftime("%B %Y"),
            selected_month=f"{today.year:04d}-{today.month:02d}",
            show_back=False,
        )


@bp.route("/new", methods=["GET", "POST"])
@require_permission("expenses:edit")
def new_expense():
    """Add a simple expense and return to the dashboard."""
    form = SimpleExpenseForm()
    selected_month = request.form.get("selected_month") or request.args.get("month")

    if request.method == "GET":
        return redirect(url_for("simple_expenses.index", month=selected_month))

    if form.validate_on_submit():
        try:
            form_data = {
                "receipt_date": form.receipt_date.data.isoformat(),
                "amount": str(form.amount.data),
                "description": form.description.data.strip(),
            }

            create_simple_expense(
                form_data,
                actor_id=current_user.id,
                check_duplicates=False,
            )
            flash("Expense saved.", "ok")
        except SimpleExpenseError as e:
            flash(f"Error creating expense: {str(e)}", "err")
        except Exception as e:
            flash(f"Unexpected error: {str(e)}", "err")
    else:
        flash("Please check the details and try again.", "err")

    return redirect(url_for("simple_expenses.index", month=selected_month))


@bp.route("/merge-duplicates", methods=["POST"])
@require_permission("expenses:edit")
def merge_duplicates():
    """Merge duplicate expenses."""
    original_id = request.form.get("original_id")
    duplicate_id = request.form.get("duplicate_id")
    selected_month = request.form.get("selected_month")

    if not original_id or not duplicate_id:
        flash("Missing expense IDs for merge", "err")
        return redirect(url_for("simple_expenses.index", month=selected_month))

    try:
        merge_duplicate_expenses(original_id, duplicate_id, actor_id=current_user.id)
        flash("Duplicate expenses merged successfully", "ok")
    except SimpleExpenseError as e:
        flash(f"Error merging expenses: {str(e)}", "err")
    except Exception as e:
        flash(f"Unexpected error: {str(e)}", "err")

    return redirect(url_for("simple_expenses.index", month=selected_month))


@bp.route("/api/monthly-summary", methods=["GET"])
@require_permission("expenses:view")
def monthly_summary():
    """API endpoint for monthly spending summary."""
    try:
        year = int(request.args.get("year", date.today().year))
        month = int(request.args.get("month", date.today().month))

        data = get_monthly_spending(year, month)
        data["total_spending_fmt"] = _format_money(data["total_spending"])

        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/<expense_id>/delete", methods=["POST"])
@require_permission("expenses:edit")
def delete_expense(expense_id):
    """Delete simple expense."""
    selected_month = request.args.get("month")
    try:
        delete_simple_expense(expense_id, actor_id=current_user.id)
        flash("Expense deleted successfully", "ok")
    except SimpleExpenseError as e:
        flash(f"Error deleting expense: {str(e)}", "err")
    except Exception as e:
        flash(f"Unexpected error: {str(e)}", "err")

    return redirect(url_for("simple_expenses.index", month=selected_month))
