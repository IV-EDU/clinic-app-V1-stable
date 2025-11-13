"""Expense receipts routes for managing dental materials expenses."""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, flash, redirect, request, send_file, url_for, jsonify, current_app
from werkzeug.utils import secure_filename

from clinic_app.services.database import db
from clinic_app.services.i18n import T
from clinic_app.services.ui import render_page
from clinic_app.services.security import require_permission
from clinic_app.services.expense_receipts import (
    create_supplier, create_expense_receipt, list_expense_receipts, get_expense_receipt,
    update_expense_receipt, delete_expense_receipt, list_suppliers, list_materials,
    ExpenseReceiptError, SupplierNotFound, MaterialNotFound, ExpenseReceiptNotFound
)
from clinic_app.services.pdf import ReceiptPDF
from clinic_app.forms.expenses import (
    ExpenseReceiptForm, ExpenseReceiptEditForm, SupplierForm, MaterialForm, ExpenseSearchForm
)

bp = Blueprint("expenses", __name__)


def _format_money(cents: float) -> str:
    """Format money in cents to display string."""
    return f"{cents/100:.2f}"


def _populate_supplier_choices() -> list[tuple[str, str]]:
    """Get list of suppliers for form choices."""
    suppliers = list_suppliers()
    return [(s['id'], s['name']) for s in suppliers]


def _populate_material_choices() -> list[tuple[str, str]]:
    """Get list of materials for form choices."""
    materials = list_materials()
    return [(m['id'], m['name']) for m in materials]


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
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    search_query = request.args.get("search_query")
    
    try:
        receipts = list_expense_receipts(
            limit=per_page, 
            offset=offset,
            supplier_id=supplier_id,
            start_date=start_date,
            end_date=end_date
        )
        
        # Format monetary values
        for receipt in receipts:
            receipt['total_amount_fmt'] = _format_money(receipt['total_amount'])
            receipt['tax_amount_fmt'] = _format_money(receipt['tax_amount'])
        
        # Calculate pagination info
        total_receipts = len(receipts)
        total_pages = (total_receipts + per_page - 1) // per_page
        
        # Get suppliers for filter dropdown
        suppliers = list_suppliers()
        
        search_form = ExpenseSearchForm()
        search_form.supplier_id.choices = [('', 'All Suppliers')] + _populate_supplier_choices()
        
        if supplier_id:
            search_form.supplier_id.data = supplier_id
        if start_date:
            search_form.start_date.data = datetime.strptime(start_date, "%Y-%m-%d").date()
        if end_date:
            search_form.end_date.data = datetime.strptime(end_date, "%Y-%m-%d").date()
        if search_query:
            search_form.search_query.data = search_query
        
        return render_page(
            "expenses/index.html",
            receipts=receipts,
            suppliers=suppliers,
            search_form=search_form,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
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


@bp.route("/expenses/new", methods=["GET", "POST"])
@require_permission("expenses:edit")
def new_receipt():
    """Create new expense receipt form."""
    form = ExpenseReceiptForm()
    
    # Populate supplier choices
    form.supplier_id.choices = _populate_supplier_choices()
    
    if request.method == "POST" and form.validate():
        try:
            # Process form data
            form_data = {
                'supplier_id': form.supplier_id.data,
                'receipt_date': form.receipt_date.data.isoformat(),
                'notes': form.notes.data,
                'tax_rate': str(form.tax_rate.data)
            }
            
            # Process items
            items = []
            for item_form in form.items:
                if item_form.material_name.data:  # Only include non-empty items
                    items.append({
                        'material_name': item_form.material_name.data,
                        'quantity': str(item_form.quantity.data),
                        'unit_price': str(item_form.unit_price.data),
                        'notes': item_form.notes.data
                    })
            
            if not items:
                flash("At least one item is required", "err")
                return render_page("expenses/new.html", form=form, show_back=True)
            
            # Create receipt
            expense_id = create_expense_receipt(
                form_data, 
                items, 
                actor_id=request.user.id
            )
            
            flash("Expense receipt created successfully", "ok")
            return redirect(url_for("expenses.view_receipt", expense_id=expense_id))
            
        except ExpenseReceiptError as e:
            flash(f"Error creating receipt: {str(e)}", "err")
        except Exception as e:
            flash(f"Unexpected error: {str(e)}", "err")
    
    # GET request or validation failed
    # Add initial empty item for the form
    if not form.items.entries:
        from clinic_app.forms.expenses import ExpenseItemForm
        form.items.append_entry()
    
    return render_page("expenses/new.html", form=form, show_back=True)


@bp.route("/expenses/<expense_id>", methods=["GET"])
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
            "expenses/detail.html", 
            receipt=receipt, 
            show_back=True
        )
        
    except ExpenseReceiptNotFound:
        flash("Expense receipt not found", "err")
        return redirect(url_for("expenses.index"))
    except Exception as e:
        flash(f"Error loading receipt: {str(e)}", "err")
        return redirect(url_for("expenses.index"))


@bp.route("/expenses/<expense_id>/edit", methods=["GET", "POST"])
@require_permission("expenses:edit")
def edit_receipt(expense_id):
    """Edit expense receipt."""
    try:
        receipt = get_expense_receipt(expense_id)
        
        if request.method == "GET":
            form = ExpenseReceiptEditForm()
            form.supplier_id.choices = _populate_supplier_choices()
            form.supplier_id.data = receipt['supplier_id']
            form.receipt_date.data = datetime.strptime(receipt['receipt_date'], "%Y-%m-%d").date()
            form.notes.data = receipt['notes'] or ""
            form.tax_rate.data = Decimal("14.0")  # Default tax rate
            
            # Populate items
            from clinic_app.forms.expenses import ExpenseItemForm
            for item in receipt['items']:
                item_form = ExpenseItemForm()
                item_form.material_name.data = item['material_name']
                item_form.quantity.data = Decimal(str(item['quantity']))
                item_form.unit_price.data = Decimal(str(item['unit_price']))
                item_form.notes.data = item['notes'] or ""
                form.items.append_entry(item_form)
            
            return render_page("expenses/edit.html", form=form, receipt=receipt, show_back=True)
        
        else:  # POST request
            form = ExpenseReceiptEditForm()
            form.supplier_id.choices = _populate_supplier_choices()
            
            if form.validate():
                try:
                    # Process form data
                    form_data = {
                        'supplier_id': form.supplier_id.data,
                        'receipt_date': form.receipt_date.data.isoformat(),
                        'notes': form.notes.data,
                        'tax_rate': str(form.tax_rate.data)
                    }
                    
                    # Process items
                    items = []
                    for item_form in form.items:
                        if item_form.material_name.data:  # Only include non-empty items
                            items.append({
                                'material_name': item_form.material_name.data,
                                'quantity': str(item_form.quantity.data),
                                'unit_price': str(item_form.unit_price.data),
                                'notes': item_form.notes.data
                            })
                    
                    if not items:
                        flash("At least one item is required", "err")
                        return render_page("expenses/edit.html", form=form, receipt=receipt, show_back=True)
                    
                    # Update receipt
                    update_expense_receipt(
                        expense_id,
                        form_data, 
                        items, 
                        actor_id=request.user.id
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


@bp.route("/expenses/<expense_id>/delete", methods=["GET"])
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


@bp.route("/expenses/<expense_id>/delete", methods=["POST"])
@require_permission("expenses:edit")
def delete_receipt(expense_id):
    """Delete expense receipt."""
    try:
        delete_expense_receipt(expense_id, actor_id=request.user.id)
        flash("Expense receipt deleted successfully", "ok")
    except ExpenseReceiptNotFound:
        flash("Expense receipt not found", "err")
    except Exception as e:
        flash(f"Error deleting receipt: {str(e)}", "err")
    
    return redirect(url_for("expenses.index"))


@bp.route("/expenses/<expense_id>/print", methods=["GET"])
@require_permission("expenses:view")
def print_receipt(expense_id):
    """Generate and serve expense receipt PDF."""
    try:
        receipt = get_expense_receipt(expense_id)
        
        # Generate PDF
        pdf = ReceiptPDF(font_path="static/fonts/DejaVuSans.ttf")
        pdf.heading("Expense Receipt", "فاتورة مصروفات")
        
        # Receipt header info
        pdf.kv_block([
            ("Receipt Number", receipt['serial_number']),
            ("Date", receipt['receipt_date']),
            ("Supplier", receipt['supplier_name']),
        ])
        
        # Items table
        pdf.set_font(pdf._family, "B", 12)
        pdf.cell(0, 8, "Items:", pdf.ln())
        
        pdf.set_font(pdf._family, "", 10)
        for item in receipt['items']:
            pdf.multi_cell(0, 6, f"{item['material_name']} - {item['quantity']} x {_format_money(item['unit_price'])} = {_format_money(item['total_price'])}")
        
        # Totals
        pdf.ln(4)
        pdf.set_font(pdf._family, "B", 12)
        pdf.kv_block([
            ("Subtotal", _format_money(receipt['total_amount'] - receipt['tax_amount'])),
            ("Tax Amount", _format_money(receipt['tax_amount'])),
            ("Total Amount", _format_money(receipt['total_amount'])),
        ])
        
        if receipt['notes']:
            pdf.note(f"Notes: {receipt['notes']}")
        
        pdf_output = pdf.render()
        
        # Serve PDF
        filename = f"expense_{receipt['serial_number']}.pdf"
        return send_file(
            io.BytesIO(pdf_output),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )
        
    except ExpenseReceiptNotFound:
        flash("Expense receipt not found", "err")
        return redirect(url_for("expenses.index"))
    except Exception as e:
        flash(f"Error generating PDF: {str(e)}", "err")
        return redirect(url_for("expenses.view_receipt", expense_id=expense_id))


# Supplier Management Routes
@bp.route("/expenses/suppliers", methods=["GET"])
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


@bp.route("/expenses/suppliers/new", methods=["GET", "POST"])
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
                actor_id=request.user.id
            )
            
            flash("Supplier created successfully", "ok")
            return redirect(url_for("expenses.suppliers"))
            
        except ExpenseReceiptError as e:
            flash(f"Error creating supplier: {str(e)}", "err")
        except Exception as e:
            flash(f"Unexpected error: {str(e)}", "err")
    
    return render_page("expenses/supplier_form.html", form=form, show_back=True)


@bp.route("/expenses/suppliers/<supplier_id>/edit", methods=["GET", "POST"])
@require_permission("expenses:edit")
def edit_supplier(supplier_id):
    """Edit supplier."""
    # Implementation would go here - similar pattern to expense editing
    flash("Edit supplier functionality not yet implemented", "info")
    return redirect(url_for("expenses.suppliers"))


# Material Management Routes
@bp.route("/expenses/materials", methods=["GET"])
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


@bp.route("/expenses/materials/new", methods=["GET", "POST"])
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


@bp.route("/expenses/materials/<material_id>/edit", methods=["GET", "POST"])
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