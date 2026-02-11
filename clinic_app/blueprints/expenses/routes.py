"""Expense receipts routes for managing dental materials expenses."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, flash, redirect, request, url_for, jsonify, make_response
from flask_login import current_user

from clinic_app.services.ui import render_page
from clinic_app.services.security import require_permission
from clinic_app.services.expense_receipts import (
    create_supplier, create_expense_receipt, list_expense_receipts, get_expense_receipt,
    update_expense_receipt, delete_expense_receipt, list_suppliers, list_materials,
    update_receipt_status, get_receipt_files, attach_receipt_file, delete_receipt_file,
    create_category, list_categories, get_category, set_receipt_category, get_receipt_statistics,
    ExpenseReceiptError, SupplierNotFound, MaterialNotFound, ExpenseReceiptNotFound
)
from clinic_app.forms.expenses import (
    ExpenseReceiptForm, ExpenseReceiptEditForm, SupplierForm, MaterialForm, ExpenseSearchForm,
    ExpenseStatusForm, ExpenseCategoryForm
)

bp = Blueprint("expenses", __name__)


def _format_money(cents: float) -> str:
    """Format money value to display string."""
    return f"{cents:.2f}"


def _populate_supplier_choices() -> list[tuple[str, str]]:
    """Get list of suppliers for form choices."""
    suppliers = list_suppliers()
    return [(s['id'], s['name']) for s in suppliers]


def _populate_material_choices() -> list[tuple[str, str]]:
    """Get list of materials for form choices."""
    materials = list_materials()
    return [(m['id'], m['name']) for m in materials]


def _populate_category_choices() -> list[tuple[str, str]]:
    """Get list of expense categories for form choices."""
    categories = list_categories()
    return [('', 'No Category')] + [(c['id'], c['name']) for c in categories]


def _get_default_supplier_id(actor_id: str) -> str:
    """Ensure a default supplier exists and return its id."""
    suppliers = list_suppliers()
    for supplier in suppliers:
        if supplier['name'].lower() == "general clinic expenses":
            return supplier['id']

    # Create the default supplier if missing
    return create_supplier({'name': 'General Clinic Expenses'}, actor_id=actor_id)


# Expense Receipt Routes
@bp.route("/", methods=["GET"])
@require_permission("expenses:view")
def index():
    """List all expense receipts with search/filter options."""
    page = max(int(request.args.get("page", 1)), 1)
    per_page = 20
    offset = (page - 1) * per_page
    
    # Get filter parameters
    supplier_id = request.args.get("supplier_id")
    category_id = request.args.get("category_id")
    receipt_status = request.args.get("receipt_status")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    min_amount = request.args.get("min_amount")
    max_amount = request.args.get("max_amount")
    search_query = request.args.get("search_query")
    
    try:
        receipts = list_expense_receipts(
            limit=per_page,
            offset=offset,
            supplier_id=supplier_id,
            category_id=category_id,
            receipt_status=receipt_status,
            start_date=start_date,
            end_date=end_date,
            min_amount=min_amount,
            max_amount=max_amount,
            search_query=search_query
        )
        
        # Format monetary values and add category info
        categories = list_categories()
        categories_dict = {c['id']: c for c in categories}
        
        for receipt in receipts:
            receipt['total_amount_fmt'] = _format_money(receipt['total_amount'])
            receipt['tax_amount_fmt'] = _format_money(receipt['tax_amount'])
            
            # Add category information
            if receipt.get('category_id'):
                receipt['category_name'] = categories_dict.get(receipt['category_id'], {}).get('name', 'Unknown')
                receipt['category_color'] = categories_dict.get(receipt['category_id'], {}).get('color', '#3498db')
            else:
                receipt['category_name'] = 'Uncategorized'
                receipt['category_color'] = '#95a5a6'
        
        # Calculate pagination info
        total_receipts = len(receipts)
        total_pages = (total_receipts + per_page - 1) // per_page

        # Monthly total (simple recent summary)
        today = date.today()
        month_start = today.replace(day=1).isoformat()
        month_receipts = list_expense_receipts(
            limit=500,
            offset=0,
            start_date=month_start,
            end_date=today.isoformat()
        )
        month_total = sum(r.get("total_amount", 0) or 0 for r in month_receipts)
        
        search_form = ExpenseSearchForm()
        search_form.supplier_id.choices = [('', 'All Suppliers')] + _populate_supplier_choices()
        search_form.category_id.choices = [('', 'All Categories')] + _populate_category_choices()
        
        if start_date:
            search_form.start_date.data = datetime.strptime(start_date, "%Y-%m-%d").date()
        if end_date:
            search_form.end_date.data = datetime.strptime(end_date, "%Y-%m-%d").date()
        if search_query:
            search_form.search_query.data = search_query
        if category_id:
            search_form.category_id.data = category_id
        if receipt_status:
            search_form.receipt_status.data = receipt_status
        if min_amount:
            search_form.min_amount.data = Decimal(min_amount)
        if max_amount:
            search_form.max_amount.data = Decimal(max_amount)
        
        return render_page(
            "expenses/index.html",
            receipts=receipts,
            search_form=search_form,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            month_total=_format_money(month_total),
            current_filters={
                'supplier_id': supplier_id,
                'start_date': start_date,
                'end_date': end_date,
                'search_query': search_query
            },
            show_back=True
        )
        
    except Exception as e:
        flash(f"Error loading expense receipts: {str(e)}", "err")
        return render_page("expenses/index.html", receipts=[], suppliers=[], show_back=True)


@bp.route("/new", methods=["GET", "POST"])
@require_permission("expenses:edit")
def new_receipt():
    """Create new expense receipt form."""
    form = ExpenseReceiptForm()

    default_supplier_id = _get_default_supplier_id(current_user.id)
    
    # Populate category choices
    form.category_id.choices = _populate_category_choices()
    
    if request.method == "GET":
        form.process(
            supplier_id=default_supplier_id,
            tax_rate=Decimal("0.0"),
        )
        if not form.receipt_date.data:
            form.receipt_date.data = date.today()

    if request.method == "POST":
        # Force hidden defaults into raw_data so validators pass
        form.supplier_id.data = default_supplier_id
        form.supplier_id.raw_data = [default_supplier_id]
        form.tax_rate.data = Decimal("0.0")
        form.tax_rate.raw_data = ["0"]

    if request.method == "POST" and form.validate_on_submit():
        try:
            if not form.total_amount.data or form.total_amount.data <= 0:
                flash("Please enter how much you paid.", "err")
                return render_page("expenses/new.html", form=form, show_back=True)

            form_data = {
                'supplier_id': default_supplier_id,
                'receipt_date': form.receipt_date.data.isoformat(),
                'notes': form.notes.data,
                'tax_rate': "0",
                'category_id': form.category_id.data if form.category_id.data else None,
            }

            # Always create a single simple item using the total amount
            items = [{
                'material_name': "Materials purchase",
                'quantity': "1",
                'unit_price': str(form.total_amount.data),
                'notes': form.notes.data
            }]

            expense_id = create_expense_receipt(
                form_data,
                items,
                actor_id=current_user.id
            )

            flash("Expense receipt created successfully", "ok")
            return redirect(url_for("expenses.view_receipt", expense_id=expense_id))
            
        except ExpenseReceiptError as e:
            flash(f"Error creating receipt: {str(e)}", "err")
        except Exception as e:
            flash(f"Unexpected error: {str(e)}", "err")
    elif request.method == "POST":
        flash("Please fix the highlighted errors and try again.", "err")
    
    # GET request or validation failed
    # Add initial empty item for the form
    if not form.items.entries:
        from clinic_app.forms.expenses import ExpenseItemForm
        form.items.append_entry()
    
    return render_page("expenses/new.html", form=form, show_back=True)


@bp.route("/<expense_id>", methods=["GET"])
@require_permission("expenses:view")
def view_receipt(expense_id):
    """View expense receipt details."""
    try:
        receipt = get_expense_receipt(expense_id)

        # Format monetary values
        receipt['total_amount_fmt'] = _format_money(receipt['total_amount'])
        receipt['tax_amount_fmt'] = _format_money(receipt['tax_amount'])

        for item in receipt['items']:
            item['unit_price_fmt'] = _format_money(item['unit_price'])
            item['total_price_fmt'] = _format_money(item['total_price'])
        
        return render_page(
            "expenses/detail_enhanced.html",
            receipt=receipt,
            show_back=True
        )
        
    except ExpenseReceiptNotFound:
        flash("Expense receipt not found", "err")
        return redirect(url_for("expenses.index"))
    except Exception as e:
        flash(f"Error loading receipt: {str(e)}", "err")
        return redirect(url_for("expenses.index"))


@bp.route("/<expense_id>/edit", methods=["GET", "POST"])
@require_permission("expenses:edit")
def edit_receipt(expense_id):
    """Edit expense receipt."""
    try:
        receipt = get_expense_receipt(expense_id)

        if request.method == "GET":
            form = ExpenseReceiptEditForm()
            default_supplier_id = _get_default_supplier_id(current_user.id)
            form.process(
                supplier_id=default_supplier_id,
                receipt_date=datetime.strptime(receipt['receipt_date'], "%Y-%m-%d").date(),
                notes=receipt['notes'] or "",
                tax_rate=Decimal("0.0"),
                total_amount=Decimal(str(receipt['total_amount']))
            )
            
            return render_page("expenses/edit.html", form=form, receipt=receipt, show_back=True)
        
        else:  # POST request
            form = ExpenseReceiptEditForm()
            default_supplier_id = _get_default_supplier_id(current_user.id)
            form.supplier_id.data = default_supplier_id
            form.supplier_id.raw_data = [default_supplier_id]
            form.tax_rate.data = Decimal("0.0")
            form.tax_rate.raw_data = ["0"]
            
            if form.validate_on_submit():
                try:
                    if not form.total_amount.data or form.total_amount.data <= 0:
                        flash("Please enter how much you paid.", "err")
                        return render_page("expenses/edit.html", form=form, receipt=receipt, show_back=True)

                    form_data = {
                        'supplier_id': default_supplier_id,
                        'receipt_date': form.receipt_date.data.isoformat(),
                        'notes': form.notes.data,
                        'tax_rate': "0",
                    }

                    items = [{
                        'material_name': "Materials purchase",
                        'quantity': "1",
                        'unit_price': str(form.total_amount.data),
                        'notes': form.notes.data
                    }]

                    # Update receipt
                    update_expense_receipt(
                        expense_id,
                        form_data, 
                        items, 
                        actor_id=current_user.id
                    )
                    
                    flash("Expense receipt updated successfully", "ok")
                    return redirect(url_for("expenses.view_receipt", expense_id=expense_id))
                    
                except ExpenseReceiptError as e:
                    flash(f"Error updating receipt: {str(e)}", "err")
                except Exception as e:
                    flash(f"Unexpected error: {str(e)}", "err")
            
            # Validation failed, show form again
            return render_page("expenses/edit.html", form=form, receipt=receipt, show_back=True)
            
    except ExpenseReceiptNotFound:
        flash("Expense receipt not found", "err")
        return redirect(url_for("expenses.index"))
    except Exception as e:
        flash(f"Error loading receipt: {str(e)}", "err")
        return redirect(url_for("expenses.index"))


@bp.route("/<expense_id>/delete", methods=["GET"])
@require_permission("expenses:edit")
def delete_receipt_confirm(expense_id):
    """Delete expense receipt confirmation."""
    try:
        receipt = get_expense_receipt(expense_id)
        return render_page(
            "expenses/delete_confirm.html", 
            receipt=receipt, 
            show_back=True
        )
    except ExpenseReceiptNotFound:
        flash("Expense receipt not found", "err")
        return redirect(url_for("expenses.index"))


@bp.route("/<expense_id>/delete", methods=["POST"])
@require_permission("expenses:edit")
def delete_receipt(expense_id):
    """Delete expense receipt."""
    try:
        delete_expense_receipt(expense_id, actor_id=current_user.id)
        flash("Expense receipt deleted successfully", "ok")
    except ExpenseReceiptNotFound:
        flash("Expense receipt not found", "err")
    except Exception as e:
        flash(f"Error deleting receipt: {str(e)}", "err")
    
    return redirect(url_for("expenses.index"))


# Supplier Management Routes
@bp.route("/suppliers", methods=["GET"])
@require_permission("expenses:view")
def suppliers():
    """List all suppliers."""
    try:
        suppliers_list = list_suppliers(active_only=False)
        return render_page(
            "expenses/suppliers.html", 
            suppliers=suppliers_list, 
            show_back=True
        )
    except Exception as e:
        flash(f"Error loading suppliers: {str(e)}", "err")
        return render_page("expenses/suppliers.html", suppliers=[], show_back=True)


@bp.route("/suppliers/new", methods=["GET", "POST"])
@require_permission("expenses:edit")
def new_supplier():
    """Create new supplier."""
    form = SupplierForm()
    
    if request.method == "POST" and form.validate():
        try:
            supplier_id = create_supplier(
                {
                    'name': form.name.data,
                    'contact_person': form.contact_person.data,
                    'phone': form.phone.data,
                    'email': form.email.data,
                    'address': form.address.data,
                    'tax_number': form.tax_number.data,
                    'is_active': '1' if form.is_active.data else '0'
                },
                actor_id=current_user.id
            )
            
            flash("Supplier created successfully", "ok")
            return redirect(url_for("expenses.suppliers"))
            
        except ExpenseReceiptError as e:
            flash(f"Error creating supplier: {str(e)}", "err")
        except Exception as e:
            flash(f"Unexpected error: {str(e)}", "err")
    
    return render_page("expenses/supplier_form.html", form=form, show_back=True)


@bp.route("/suppliers/<supplier_id>/edit", methods=["GET", "POST"])
@require_permission("expenses:edit")
def edit_supplier(supplier_id):
    """Edit supplier."""
    # Implementation would go here - similar pattern to expense editing
    flash("Edit supplier functionality not yet implemented", "info")
    return redirect(url_for("expenses.suppliers"))


# Material Management Routes
@bp.route("/materials", methods=["GET"])
@require_permission("expenses:view")
def materials():
    """List all materials."""
    try:
        materials_list = list_materials(active_only=False)
        return render_page(
            "expenses/materials.html", 
            materials=materials_list, 
            show_back=True
        )
    except Exception as e:
        flash(f"Error loading materials: {str(e)}", "err")
        return render_page("expenses/materials.html", materials=[], show_back=True)


@bp.route("/materials/new", methods=["GET", "POST"])
@require_permission("expenses:edit")
def new_material():
    """Create new material."""
    form = MaterialForm()
    
    if request.method == "POST" and form.validate():
        try:
            # Material creation would be implemented here
            flash("Material creation functionality not yet implemented", "info")
            return redirect(url_for("expenses.materials"))
            
        except Exception as e:
            flash(f"Error: {str(e)}", "err")
    
    return render_page("expenses/material_form.html", form=form, show_back=True)


@bp.route("/materials/<material_id>/edit", methods=["GET", "POST"])
@require_permission("expenses:edit")
def edit_material(material_id):
    """Edit material."""
    flash("Edit material functionality not yet implemented", "info")
    return redirect(url_for("expenses.materials"))


# API Routes
@bp.route("/api/expenses/search", methods=["GET"])
@require_permission("expenses:view")
def search_expenses():
    """API endpoint for searching expenses."""
    query = (request.args.get("q") or "").strip()
    
    if not query:
        return jsonify([])
    
    try:
        # Search in supplier names and material names
        suppliers = list_suppliers()
        materials = list_materials()
        
        results = []
        
        # Search suppliers
        for supplier in suppliers:
            if query.lower() in supplier['name'].lower():
                results.append({
                    'id': supplier['id'],
                    'name': supplier['name'],
                    'type': 'supplier'
                })
        
        # Search materials
        for material in materials:
            if query.lower() in material['name'].lower():
                results.append({
                    'id': material['id'],
                    'name': material['name'],
                    'type': 'material'
                })
        
        return jsonify(results[:10])  # Limit to 10 results
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/expenses/autocomplete/materials", methods=["GET"])
@require_permission("expenses:view")
def autocomplete_materials():
    """API endpoint for material autocomplete in expense forms."""
    query = (request.args.get("q") or "").strip()
    
    if not query or len(query) < 2:
        return jsonify([])
    
    try:
        materials = list_materials()
        
        # Filter materials by name
        filtered_materials = [
            {
                'id': m['id'],
                'name': m['name'],
                'unit': m.get('unit', ''),
                'price_per_unit': str(m.get('price_per_unit', ''))
            }
            for m in materials
            if query.lower() in m['name'].lower()
        ]
        
        return jsonify(filtered_materials[:10])
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Export Routes
@bp.route("/export/csv", methods=["GET"])
@require_permission("expenses:view")
def export_csv():
    """Export expense receipts to CSV format."""
    try:
        # Get current filters from URL parameters
        supplier_id = request.args.get("supplier_id")
        category_id = request.args.get("category_id")
        receipt_status = request.args.get("receipt_status")
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        min_amount = request.args.get("min_amount")
        max_amount = request.args.get("max_amount")
        search_query = request.args.get("search_query")
        
        # Get all matching receipts (without pagination)
        receipts = list_expense_receipts(
            limit=10000,  # High limit for export
            offset=0,
            supplier_id=supplier_id,
            category_id=category_id,
            receipt_status=receipt_status,
            start_date=start_date,
            end_date=end_date,
            min_amount=min_amount,
            max_amount=max_amount,
            search_query=search_query
        )
        
        # Import CSV module
        import csv
        from io import StringIO
        
        # Create CSV content
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'Serial Number', 'Date', 'Supplier', 'Category', 'Status',
            'Total Amount (EGP)', 'Tax Amount (EGP)', 'Notes', 'Created At'
        ])
        
        # Get category info
        categories = list_categories()
        categories_dict = {c['id']: c for c in categories}
        
        # Write data rows
        for receipt in receipts:
            category_name = categories_dict.get(receipt.get('category_id'), {}).get('name', 'Uncategorized')
            status = receipt.get('receipt_status', 'pending').title()
            
            writer.writerow([
                receipt['serial_number'],
                receipt['receipt_date'],
                receipt['supplier_name'],
                category_name,
                status,
                f"{receipt['total_amount']:.2f}",
                f"{receipt['tax_amount']:.2f}",
                receipt.get('notes', ''),
                receipt['created_at'][:19]  # Remove microseconds
            ])
        
        # Prepare response
        output.seek(0)
        filename = f"expense_receipts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        
        return response
        
    except Exception as e:
        flash(f"Error exporting CSV: {str(e)}", "err")
        return redirect(url_for("expenses.index"))


@bp.route("/export/pdf", methods=["GET"])
@require_permission("expenses:view")
def export_pdf():
    """Export expense receipts summary to PDF format."""
    try:
        # Get current filters
        supplier_id = request.args.get("supplier_id")
        category_id = request.args.get("category_id")
        receipt_status = request.args.get("receipt_status")
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        min_amount = request.args.get("min_amount")
        max_amount = request.args.get("max_amount")
        search_query = request.args.get("search_query")
        
        # Get matching receipts
        receipts = list_expense_receipts(
            limit=1000,
            offset=0,
            supplier_id=supplier_id,
            category_id=category_id,
            receipt_status=receipt_status,
            start_date=start_date,
            end_date=end_date,
            min_amount=min_amount,
            max_amount=max_amount,
            search_query=search_query
        )
        
        # Get statistics
        stats = get_receipt_statistics()
        categories = list_categories()
        suppliers = list_suppliers()
        
        # Calculate totals
        total_amount = sum(r['total_amount'] for r in receipts)
        total_count = len(receipts)
        
        # Group by status for summary
        status_summary = {}
        for receipt in receipts:
            status = receipt.get('receipt_status', 'pending')
            if status not in status_summary:
                status_summary[status] = {'count': 0, 'amount': 0}
            status_summary[status]['count'] += 1
            status_summary[status]['amount'] += receipt['total_amount']
        
        # Generate PDF using the existing PDF service
        from clinic_app.services.pdf_enhanced import ExpenseReceiptPDF
        from flask import current_app
        
        pdf_service = ExpenseReceiptPDF()
        pdf_service.add_title("Expense Receipts Report")
        
        # Add summary section
        pdf_service.add_summary_section({
            'total_receipts': total_count,
            'total_amount': total_amount,
            'date_range': f"{start_date or 'All'} to {end_date or 'All'}",
            'status_breakdown': status_summary
        })
        
        # Add receipts table
        pdf_data = []
        categories_dict = {c['id']: c['name'] for c in categories}
        suppliers_dict = {s['id']: s['name'] for s in suppliers}
        
        for receipt in receipts:
            pdf_data.append({
                'serial': receipt['serial_number'],
                'date': receipt['receipt_date'],
                'supplier': suppliers_dict.get(receipt.get('supplier_id'), receipt.get('supplier_name', 'Unknown')),
                'category': categories_dict.get(receipt.get('category_id'), 'Uncategorized'),
                'status': receipt.get('receipt_status', 'pending').title(),
                'amount': receipt['total_amount']
            })
        
        pdf_service.add_receipts_table(pdf_data)
        
        # Generate PDF
        pdf_content = pdf_service.generate()
        
        # Prepare response
        filename = f"expense_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        response = make_response(pdf_content)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        
        return response
        
    except Exception as e:
        flash(f"Error generating PDF: {str(e)}", "err")
        return redirect(url_for("expenses.index"))


# Status Management Routes
@bp.route("/<expense_id>/status", methods=["GET", "POST"])
@require_permission("expenses:edit")
def update_receipt_status_route(expense_id):
    """Update receipt status and approval workflow."""
    form = ExpenseStatusForm()
    
    if request.method == "GET":
        try:
            receipt = get_expense_receipt(expense_id)
            form.process(
                receipt_status=receipt.get('receipt_status', 'pending'),
                approval_notes=receipt.get('approval_notes', '')
            )
            return render_page(
                "expenses/status.html",
                form=form,
                receipt=receipt,
                show_back=True
            )
        except ExpenseReceiptNotFound:
            flash("Expense receipt not found", "err")
            return redirect(url_for("expenses.index"))
    
    elif request.method == "POST" and form.validate():
        try:
            update_receipt_status(
                expense_id,
                form.receipt_status.data,
                form.approval_notes.data,
                actor_id=current_user.id
            )
            flash("Receipt status updated successfully", "ok")
            return redirect(url_for("expenses.view_receipt", expense_id=expense_id))
        except ExpenseReceiptError as e:
            flash(f"Error updating status: {str(e)}", "err")
    
    # Validation failed
    try:
        receipt = get_expense_receipt(expense_id)
        return render_page(
            "expenses/status.html",
            form=form,
            receipt=receipt,
            show_back=True
        )
    except ExpenseReceiptNotFound:
        flash("Expense receipt not found", "err")
        return redirect(url_for("expenses.index"))


# Category Management Routes
@bp.route("/categories", methods=["GET"])
@require_permission("expenses:view")
def categories():
    """List all expense categories."""
    try:
        categories_list = list_categories()
        return render_page(
            "expenses/categories.html",
            categories=categories_list,
            show_back=True
        )
    except Exception as e:
        flash(f"Error loading categories: {str(e)}", "err")
        return render_page("expenses/categories.html", categories=[], show_back=True)


@bp.route("/categories/new", methods=["GET", "POST"])
@require_permission("expenses:edit")
def new_category():
    """Create new expense category."""
    form = ExpenseCategoryForm()
    
    if request.method == "POST" and form.validate():
        try:
            category_id = create_category(
                {
                    'name': form.name.data,
                    'description': form.description.data,
                    'color': form.color.data
                },
                actor_id=current_user.id
            )
            
            flash("Expense category created successfully", "ok")
            return redirect(url_for("expenses.categories"))
            
        except ExpenseReceiptError as e:
            flash(f"Error creating category: {str(e)}", "err")
        except Exception as e:
            flash(f"Unexpected error: {str(e)}", "err")
    
    return render_page("expenses/category_form.html", form=form, show_back=True)


@bp.route("/categories/<category_id>", methods=["GET"])
@require_permission("expenses:view")
def view_category(category_id):
    """View expense category details with associated receipts."""
    try:
        category = get_category(category_id)
        
        # Get receipts in this category
        receipts = list_expense_receipts(limit=50, offset=0)
        category_receipts = [r for r in receipts if r.get('category_id') == category_id]
        
        # Format monetary values
        for receipt in category_receipts:
            receipt['total_amount_fmt'] = _format_money(receipt['total_amount'])
            receipt['tax_amount_fmt'] = _format_money(receipt['tax_amount'])
        
        return render_page(
            "expenses/category_detail.html",
            category=category,
            receipts=category_receipts,
            show_back=True
        )
    except ExpenseReceiptError as e:
        flash(f"Error loading category: {str(e)}", "err")
        return redirect(url_for("expenses.categories"))


# Enhanced Receipt Detail with Files
@bp.route("/<expense_id>/files", methods=["GET"])
@require_permission("expenses:view")
def view_receipt_files(expense_id):
    """View files attached to a receipt."""
    try:
        receipt = get_expense_receipt(expense_id)
        files = get_receipt_files(expense_id)
        
        return render_page(
            "expenses/receipt_files.html",
            receipt=receipt,
            files=files,
            show_back=True
        )
        
    except ExpenseReceiptNotFound:
        flash("Expense receipt not found", "err")
        return redirect(url_for("expenses.index"))
    except Exception as e:
        flash(f"Error loading files: {str(e)}", "err")
        return redirect(url_for("expenses.view_receipt", expense_id=expense_id))


# API Routes for Enhanced Functionality
@bp.route("/api/expenses/categories", methods=["GET"])
@require_permission("expenses:view")
def api_categories():
    """API endpoint for getting expense categories."""
    try:
        categories = list_categories()
        return jsonify([{
            'id': cat['id'],
            'name': cat['name'],
            'color': cat['color'],
            'receipt_count': cat['receipt_count']
        } for cat in categories])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/expenses/receipts/<receipt_id>/files", methods=["GET"])
@require_permission("expenses:view")
def api_receipt_files(receipt_id):
    """API endpoint for getting receipt files."""
    try:
        files = get_receipt_files(receipt_id)
        return jsonify({"files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/expenses/receipts/<receipt_id>/status", methods=["POST"])
@require_permission("expenses:edit")
def api_update_receipt_status(receipt_id):
    """API endpoint for updating receipt status."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        status = data.get("status")
        notes = data.get("approval_notes", "")
        
        if not status or status not in ["pending", "approved", "rejected"]:
            return jsonify({"error": "Invalid status"}), 400
        
        update_receipt_status(receipt_id, status, notes, actor_id=current_user.id)
        return jsonify({"success": True})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/expenses/receipts/<receipt_id>/category", methods=["POST"])
@require_permission("expenses:edit")
def api_set_receipt_category(receipt_id):
    """API endpoint for setting receipt category."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        category_id = data.get("category_id")
        if not category_id:
            return jsonify({"error": "Category ID required"}), 400
        
        set_receipt_category(receipt_id, category_id, actor_id=current_user.id)
        return jsonify({"success": True})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/api/expenses/statistics", methods=["GET"])
@require_permission("expenses:view")
def api_expense_statistics():
    """API endpoint for expense statistics."""
    try:
        from clinic_app.services.expense_receipts import get_receipt_statistics
        stats = get_receipt_statistics()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
