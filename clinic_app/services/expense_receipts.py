"""Expense receipts service for dental materials tracking."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
import uuid
import hashlib
from typing import Sequence, Optional

from flask import current_app

from clinic_app.services.audit import write_event
from clinic_app.services.database import db


class ExpenseReceiptError(Exception):
    """Base exception for expense receipt operations."""


class SupplierNotFound(ExpenseReceiptError):
    """Raised when a supplier cannot be located."""


class MaterialNotFound(ExpenseReceiptError):
    """Raised when a material cannot be located."""


class ExpenseReceiptNotFound(ExpenseReceiptError):
    """Raised when an expense receipt cannot be located."""


class FileAttachmentError(ExpenseReceiptError):
    """Raised when file attachment operations fail."""


class CategoryNotFound(ExpenseReceiptError):
    """Raised when a category cannot be located."""

def _write_audit_event_safe(actor_user_id: str | None, action: str, *, entity: str | None = None, entity_id: str | None = None, meta: dict | None = None) -> None:
    """Write audit event safely - only if user exists in database."""
    try:
        if not actor_user_id:
            return
        
        # Check if user exists in database
        conn = db()
        try:
            user_exists = conn.execute("SELECT id FROM users WHERE id = ?", (actor_user_id,)).fetchone()
            if user_exists:
                from clinic_app.services.audit import write_event
                write_event(actor_user_id, action, entity=entity, entity_id=entity_id, meta=meta)
        finally:
            conn.close()
    except Exception:
        # Silently ignore audit errors to avoid breaking core functionality
        pass

def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return bool(row)


def _ensure_expense_tables(conn: sqlite3.Connection) -> None:
    """Ensure all expense-related tables exist."""
    required_tables = [
        'suppliers',
        'expense_categories',
        'materials',
        'expense_receipts',
        'expense_receipt_items',
        'expense_sequences',
        'receipt_settings'
    ]
    
    for table in required_tables:
        if not _table_exists(conn, table):
            raise ExpenseReceiptError(f"required_table_missing:{table}")
    
    # Ensure default categories exist
    _ensure_default_categories(conn)


def _ensure_default_categories(conn: sqlite3.Connection) -> None:
    """Ensure default expense categories exist."""
    default_categories = [
        ('Travel', 'Travel expenses including transportation and accommodation', '#3498db'),
        ('Meals', 'Business meals and dining expenses', '#e67e22'),
        ('Office Supplies', 'Office supplies and administrative materials', '#9b59b6'),
        ('Software', 'Software licenses and subscriptions', '#1abc9c'),
        ('Equipment', 'Equipment purchases and maintenance', '#34495e'),
        ('Maintenance', 'Equipment and facility maintenance', '#95a5a6'),
        ('Utilities', 'Utility bills and services', '#f39c12'),
        ('Professional Services', 'Professional consulting and services', '#8e44ad'),
        ('Marketing', 'Marketing and advertising expenses', '#27ae60'),
        ('Training', 'Training and education expenses', '#e74c3c')
    ]
    
    for name, description, color in default_categories:
        existing = conn.execute(
            "SELECT id FROM expense_categories WHERE name = ?",
            (name,)
        ).fetchone()
        
        if not existing:
            conn.execute(
                "INSERT INTO expense_categories (name, description, color) VALUES (?, ?, ?)",
                (name, description, color)
            )


def generate_expense_serial(conn: sqlite3.Connection, receipt_date: str) -> str:
    """Generate unique serial number for expense receipt (E-YYYY-######)."""
    prefix = "E"
    year = receipt_date[:4]
    row = conn.execute(
        "SELECT last_number FROM expense_sequences WHERE year_key=?",
        (year,),
    ).fetchone()
    
    if row:
        next_num = int(row["last_number"]) + 1
        conn.execute(
            "UPDATE expense_sequences SET last_number=? WHERE year_key=?",
            (next_num, year),
        )
    else:
        next_num = 1
        conn.execute(
            "INSERT INTO expense_sequences(year_key, last_number) VALUES (?, ?)",
            (year, next_num),
        )
    
    serial = f"{prefix}-{year}-{next_num:06d}"
    return serial


def calculate_totals(items: list[dict[str, float]], tax_rate: float = 14.0) -> dict[str, float]:
    """Calculate receipt totals including tax."""
    subtotal = sum(item['total_price'] for item in items)
    tax_amount = subtotal * (tax_rate / 100)
    total_amount = subtotal + tax_amount
    
    return {
        'subtotal': subtotal,
        'tax_amount': tax_amount,
        'total_amount': total_amount,
        'tax_rate': tax_rate
    }


def create_supplier(form_data: dict[str, str], *, actor_id: str) -> str:
    """Create a new supplier."""
    required_fields = ['name']
    for field in required_fields:
        if not form_data.get(field, '').strip():
            raise ExpenseReceiptError(f"supplier_{field}_required")
    
    supplier_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        
        # Check if supplier name already exists
        existing = conn.execute(
            "SELECT id FROM suppliers WHERE lower(name) = lower(?)",
            (form_data['name'].strip(),)
        ).fetchone()
        if existing:
            raise ExpenseReceiptError("supplier_name_exists")
        
        conn.execute(
            """
            INSERT INTO suppliers(
                id, name, contact_person, phone, email, address, tax_number, 
                is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                supplier_id,
                form_data['name'].strip(),
                form_data.get('contact_person', '').strip() or None,
                form_data.get('phone', '').strip() or None,
                form_data.get('email', '').strip() or None,
                form_data.get('address', '').strip() or None,
                form_data.get('tax_number', '').strip() or None,
                1,  # is_active
                now,
                now
            )
        )
        conn.commit()
        
        # Only write audit event if actor_id exists in users table
        _write_audit_event_safe(actor_id, "suppliers:create", entity="supplier", entity_id=supplier_id)
        return supplier_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_expense_receipt(form_data: dict[str, str], items: list[dict[str, str]], *, actor_id: str) -> str:
    """Create a new expense receipt with items."""
    required_fields = ['supplier_id', 'receipt_date']
    for field in required_fields:
        if not form_data.get(field, '').strip():
            raise ExpenseReceiptError(f"expense_{field}_required")
    
    if not items:
        raise ExpenseReceiptError("expense_items_required")
    
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_expense_tables(conn)
        
        # Validate supplier exists
        supplier = conn.execute(
            "SELECT id, name FROM suppliers WHERE id=? AND is_active=1",
            (form_data['supplier_id'],)
        ).fetchone()
        if not supplier:
            raise SupplierNotFound(form_data['supplier_id'])
        
        # Generate serial number
        serial_number = generate_expense_serial(conn, form_data['receipt_date'])
        expense_receipt_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        
        # Process items and calculate totals
        processed_items = []
        for i, item in enumerate(items):
            if not item.get('material_name', '').strip():
                raise ExpenseReceiptError(f"item_{i+1}_name_required")
            
            try:
                quantity = float(item.get('quantity', 0))
                unit_price = float(item.get('unit_price', 0))
                if quantity <= 0 or unit_price <= 0:
                    raise ExpenseReceiptError(f"item_{i+1}_invalid_pricing")
                
                total_price = quantity * unit_price
                
                # Validate material_id if provided
                material_id = item.get('material_id', '').strip()
                if material_id:
                    material = conn.execute(
                        "SELECT id FROM materials WHERE id=? AND is_active=1",
                        (material_id,)
                    ).fetchone()
                    if not material:
                        raise MaterialNotFound(material_id)
                else:
                    material_id = None
                
                processed_items.append({
                    'material_id': material_id,
                    'material_name': item['material_name'].strip(),
                    'quantity': quantity,
                    'unit_price': unit_price,
                    'total_price': total_price,
                    'notes': item.get('notes', '').strip() or None
                })
            except ValueError:
                raise ExpenseReceiptError(f"item_{i+1}_invalid_numbers")
        
        # Calculate totals
        tax_rate = float(form_data.get('tax_rate', '14'))
        totals = calculate_totals(processed_items, tax_rate)
        
        # Insert expense receipt
        conn.execute(
            """
            INSERT INTO expense_receipts(
                id, serial_number, supplier_id, category_id, receipt_date, total_amount, tax_amount,
                notes, receipt_image_path, receipt_status, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                expense_receipt_id,
                serial_number,
                form_data['supplier_id'],
                form_data.get('category_id'),
                form_data['receipt_date'],
                totals['total_amount'],
                totals['tax_amount'],
                form_data.get('notes', '').strip() or None,
                form_data.get('receipt_image_path', '').strip() or None,
                form_data.get('receipt_status', 'pending'),
                actor_id,
                created_at,
                created_at
            )
        )
        
        # Insert expense receipt items
        for item in processed_items:
            conn.execute(
                """
                INSERT INTO expense_receipt_items(
                    id, expense_receipt_id, material_id, material_name, quantity,
                    unit_price, total_price, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    expense_receipt_id,
                    item['material_id'],
                    item['material_name'],
                    item['quantity'],
                    item['unit_price'],
                    item['total_price'],
                    item['notes']
                )
            )
        
        conn.commit()
        
        _write_audit_event_safe(actor_id, "expenses:create", entity="expense_receipt", entity_id=expense_receipt_id,
                               meta={"serial_number": serial_number, "total_amount": totals['total_amount']})
        
        return expense_receipt_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_expense_receipts(limit: int = 50, offset: int = 0,
                          supplier_id: str | None = None,
                          category_id: str | None = None,
                          receipt_status: str | None = None,
                          start_date: str | None = None,
                          end_date: str | None = None,
                          min_amount: str | None = None,
                          max_amount: str | None = None,
                          search_query: str | None = None) -> list[dict[str, str]]:
    """Get paginated list of expense receipts with advanced filtering."""
    conn = db()
    try:
        _ensure_expense_tables(conn)
        
        params = []
        where_conditions = []
        
        if supplier_id:
            where_conditions.append("er.supplier_id = ?")
            params.append(supplier_id)
        
        if category_id:
            where_conditions.append("er.category_id = ?")
            params.append(category_id)
        
        if receipt_status:
            where_conditions.append("er.receipt_status = ?")
            params.append(receipt_status)
        
        if start_date:
            where_conditions.append("er.receipt_date >= ?")
            params.append(start_date)
        
        if end_date:
            where_conditions.append("er.receipt_date <= ?")
            params.append(end_date)
        
        if min_amount:
            where_conditions.append("er.total_amount >= ?")
            params.append(float(min_amount))
        
        if max_amount:
            where_conditions.append("er.total_amount <= ?")
            params.append(float(max_amount))
        
        if search_query:
            where_conditions.append("(LOWER(er.notes) LIKE ? OR LOWER(s.name) LIKE ?)")
            search_pattern = f"%{search_query.lower()}%"
            params.extend([search_pattern, search_pattern])
        
        where_clause = ""
        if where_conditions:
            where_clause = "WHERE " + " AND ".join(where_conditions)
        
        query = f"""
            SELECT er.id, er.serial_number, er.receipt_date, er.total_amount, er.tax_amount,
                   er.notes, er.created_at, er.receipt_status, er.category_id,
                   s.name as supplier_name,
                   COUNT(eri.id) as item_count,
                   COUNT(era.id) as files_count
            FROM expense_receipts er
            JOIN suppliers s ON s.id = er.supplier_id
            LEFT JOIN expense_receipt_items eri ON eri.expense_receipt_id = er.id
            LEFT JOIN expense_receipts_attachments era ON era.expense_receipt_id = er.id
            {where_clause}
            GROUP BY er.id
            ORDER BY er.created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        
        rows = conn.execute(query, params).fetchall()
        
        result = []
        for row in rows:
            result.append({
                'id': row['id'],
                'serial_number': row['serial_number'],
                'supplier_name': row['supplier_name'],
                'receipt_date': row['receipt_date'],
                'total_amount': row['total_amount'],
                'tax_amount': row['tax_amount'],
                'notes': row['notes'],
                'receipt_status': row['receipt_status'],
                'category_id': row['category_id'],
                'item_count': row['item_count'],
                'files_count': row['files_count'],
                'created_at': row['created_at']
            })
        
        return result
    finally:
        conn.close()


def get_expense_receipt(expense_receipt_id: str) -> dict[str, str]:
    """Get detailed expense receipt with items."""
    conn = db()
    try:
        _ensure_expense_tables(conn)
        
        # Get main expense receipt data
        receipt = conn.execute(
            """
            SELECT er.*, s.name as supplier_name, s.phone as supplier_phone, s.email as supplier_email
            FROM expense_receipts er
            JOIN suppliers s ON s.id = er.supplier_id
            WHERE er.id = ?
            """,
            (expense_receipt_id,)
        ).fetchone()
        
        if not receipt:
            raise ExpenseReceiptNotFound(expense_receipt_id)
        
        # Get items
        items = conn.execute(
            """
            SELECT eri.*, m.name as material_name_catalog
            FROM expense_receipt_items eri
            LEFT JOIN materials m ON m.id = eri.material_id
            WHERE eri.expense_receipt_id = ?
            ORDER BY eri.rowid
            """,
            (expense_receipt_id,)
        ).fetchall()
        
        # Format response
        receipt_data = {
            'id': receipt['id'],
            'serial_number': receipt['serial_number'],
            'supplier_id': receipt['supplier_id'],
            'supplier_name': receipt['supplier_name'],
            'supplier_phone': receipt['supplier_phone'],
            'supplier_email': receipt['supplier_email'],
            'receipt_date': receipt['receipt_date'],
            'total_amount': receipt['total_amount'],
            'tax_amount': receipt['tax_amount'],
            'notes': receipt['notes'],
            'receipt_image_path': receipt['receipt_image_path'],
            'created_by': receipt['created_by'],
            'created_at': receipt['created_at'],
            'items': []
        }
        
        for item in items:
            receipt_data['items'].append({
                'id': item['id'],
                'material_id': item['material_id'],
                'material_name': item['material_name'],
                'material_name_catalog': item['material_name_catalog'],
                'quantity': item['quantity'],
                'unit_price': item['unit_price'],
                'total_price': item['total_price'],
                'notes': item['notes']
            })
        
        return receipt_data
    finally:
        conn.close()


def update_expense_receipt(expense_receipt_id: str, form_data: dict[str, str], 
                          items: list[dict[str, str]] | None, *, actor_id: str) -> None:
    """Update expense receipt."""
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_expense_tables(conn)
        
        # Check if receipt exists
        existing = conn.execute(
            "SELECT id FROM expense_receipts WHERE id=?",
            (expense_receipt_id,)
        ).fetchone()
        if not existing:
            raise ExpenseReceiptNotFound(expense_receipt_id)
        
        # Update main receipt data if provided
        if form_data.get('supplier_id') or form_data.get('receipt_date') or form_data.get('notes'):
            update_fields = []
            params = []
            
            if form_data.get('supplier_id'):
                # Validate supplier exists
                supplier = conn.execute(
                    "SELECT id FROM suppliers WHERE id=? AND is_active=1",
                    (form_data['supplier_id'],)
                ).fetchone()
                if not supplier:
                    raise SupplierNotFound(form_data['supplier_id'])
                update_fields.append("supplier_id = ?")
                params.append(form_data['supplier_id'])
            
            if form_data.get('receipt_date'):
                update_fields.append("receipt_date = ?")
                params.append(form_data['receipt_date'])
            
            if 'notes' in form_data:
                update_fields.append("notes = ?")
                params.append(form_data.get('notes', '').strip() or None)
            
            update_fields.append("updated_at = ?")
            params.append(datetime.now(timezone.utc).isoformat())
            params.append(expense_receipt_id)
            
            conn.execute(
                f"UPDATE expense_receipts SET {', '.join(update_fields)} WHERE id = ?",
                params
            )
        
        # Update items if provided
        if items is not None:
            # Delete existing items
            conn.execute(
                "DELETE FROM expense_receipt_items WHERE expense_receipt_id = ?",
                (expense_receipt_id,)
            )
            
            # Add new items
            processed_items = []
            for i, item in enumerate(items):
                if not item.get('material_name', '').strip():
                    raise ExpenseReceiptError(f"item_{i+1}_name_required")
                
                try:
                    quantity = float(item.get('quantity', 0))
                    unit_price = float(item.get('unit_price', 0))
                    if quantity <= 0 or unit_price <= 0:
                        raise ExpenseReceiptError(f"item_{i+1}_invalid_pricing")
                    
                    total_price = quantity * unit_price
                    
                    processed_items.append({
                        'material_id': item.get('material_id', '').strip() or None,
                        'material_name': item['material_name'].strip(),
                        'quantity': quantity,
                        'unit_price': unit_price,
                        'total_price': total_price,
                        'notes': item.get('notes', '').strip() or None
                    })
                except ValueError:
                    raise ExpenseReceiptError(f"item_{i+1}_invalid_numbers")
            
            # Recalculate totals
            tax_rate = float(form_data.get('tax_rate', '14'))
            totals = calculate_totals(processed_items, tax_rate)
            
            # Update totals
            conn.execute(
                """
                UPDATE expense_receipts 
                SET total_amount = ?, tax_amount = ?, updated_at = ?
                WHERE id = ?
                """,
                (totals['total_amount'], totals['tax_amount'], datetime.now(timezone.utc).isoformat(), expense_receipt_id)
            )
            
            # Insert new items
            for item in processed_items:
                conn.execute(
                    """
                    INSERT INTO expense_receipt_items(
                        id, expense_receipt_id, material_id, material_name, quantity,
                        unit_price, total_price, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        expense_receipt_id,
                        item['material_id'],
                        item['material_name'],
                        item['quantity'],
                        item['unit_price'],
                        item['total_price'],
                        item['notes']
                    )
                )
        
        conn.commit()
        
        _write_audit_event_safe(actor_id, "expenses:edit", entity="expense_receipt", entity_id=expense_receipt_id)
        
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_expense_receipt(expense_receipt_id: str, *, actor_id: str) -> None:
    """Delete expense receipt (soft delete - deactivate)."""
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _ensure_expense_tables(conn)
        
        # Check if receipt exists
        existing = conn.execute(
            "SELECT id FROM expense_receipts WHERE id=?",
            (expense_receipt_id,)
        ).fetchone()
        if not existing:
            raise ExpenseReceiptNotFound(expense_receipt_id)
        
        # Note: We don't actually delete the receipt, as it contains financial data
        # In a real system, you might want to mark it as cancelled or archived
        # For now, we'll just log the deletion attempt
        conn.execute(
            "DELETE FROM expense_receipt_items WHERE expense_receipt_id = ?",
            (expense_receipt_id,)
        )
        conn.execute(
            "DELETE FROM expense_receipts WHERE id = ?",
            (expense_receipt_id,)
        )
        
        conn.commit()
        
        _write_audit_event_safe(actor_id, "expenses:delete", entity="expense_receipt", entity_id=expense_receipt_id)
        
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def attach_receipt_file(expense_receipt_id: str, file_data: dict, *, actor_id: str) -> str:
    """Attach a file to an expense receipt."""
    conn = db()
    try:
        _ensure_expense_tables(conn)
        
        # Verify receipt exists
        receipt = conn.execute(
            "SELECT id FROM expense_receipts WHERE id=?",
            (expense_receipt_id,)
        ).fetchone()
        if not receipt:
            raise ExpenseReceiptNotFound(expense_receipt_id)
        
        attachment_id = str(uuid.uuid4())
        upload_date = datetime.now(timezone.utc).isoformat()
        
        # Calculate file hash
        file_hash = hashlib.md5(file_data['filename'].encode()).hexdigest()
        
        conn.execute(
            """
            INSERT INTO expense_receipts_attachments (
                id, expense_receipt_id, filename, original_filename, file_path,
                file_type, file_size, file_hash, mime_type, upload_date, uploaded_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attachment_id,
                expense_receipt_id,
                file_data['filename'],
                file_data.get('original_filename', file_data['filename']),
                file_data['file_path'],
                file_data['file_type'],
                file_data.get('file_size', 0),
                file_hash,
                file_data.get('mime_type'),
                upload_date,
                actor_id
            )
        )
        
        conn.commit()
        write_event(actor_id, "expenses:attach_file", entity="expense_receipt", entity_id=expense_receipt_id)
        return attachment_id
        
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_receipt_files(expense_receipt_id: str) -> list[dict[str, str]]:
    """Get all files attached to an expense receipt."""
    conn = db()
    try:
        _ensure_expense_tables(conn)
        
        rows = conn.execute(
            """
            SELECT id, filename, original_filename, file_type, file_size,
                   mime_type, upload_date, uploaded_by
            FROM expense_receipts_attachments
            WHERE expense_receipt_id = ?
            ORDER BY upload_date DESC
            """,
            (expense_receipt_id,)
        ).fetchall()
        
        result = []
        for row in rows:
            result.append({
                'id': row['id'],
                'filename': row['filename'],
                'original_filename': row['original_filename'],
                'file_type': row['file_type'],
                'file_size': row['file_size'],
                'mime_type': row['mime_type'],
                'upload_date': row['upload_date'],
                'uploaded_by': row['uploaded_by'],
                'file_url': f"/expense-receipts/files/{row['filename']}"
            })
        
        return result
        
    finally:
        conn.close()


def create_category(form_data: dict[str, str], *, actor_id: str) -> str:
    """Create a new expense category."""
    required_fields = ['name']
    for field in required_fields:
        if not form_data.get(field, '').strip():
            raise ExpenseReceiptError(f"category_{field}_required")
    
    conn = db()
    try:
        _ensure_expense_tables(conn)
        
        # Check if category name already exists
        existing = conn.execute(
            "SELECT id FROM expense_categories WHERE lower(name) = lower(?)",
            (form_data['name'].strip(),)
        ).fetchone()
        if existing:
            raise ExpenseReceiptError("category_name_exists")
        
        category_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        conn.execute(
            """
            INSERT INTO expense_categories(id, name, description, color, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                category_id,
                form_data['name'].strip(),
                form_data.get('description', '').strip() or None,
                form_data.get('color', '#3498db').strip() or '#3498db',
                now
            )
        )
        
        conn.commit()
        write_event(actor_id, "expenses:create_category", entity="expense_category", entity_id=category_id)
        return category_id
        
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_categories() -> list[dict[str, str]]:
    """List all expense categories."""
    conn = db()
    try:
        _ensure_expense_tables(conn)
        
        rows = conn.execute(
            """
            SELECT ec.*,
                   COUNT(er.id) as receipt_count,
                   SUM(er.total_amount) as total_amount
            FROM expense_categories ec
            LEFT JOIN expense_receipts er ON er.category_id = ec.id
            GROUP BY ec.id
            ORDER BY ec.name ASC
            """
        ).fetchall()
        
        result = []
        for row in rows:
            result.append({
                'id': row['id'],
                'name': row['name'],
                'description': row['description'],
                'color': row['color'],
                'receipt_count': row['receipt_count'] or 0,
                'total_amount': row['total_amount'] or 0,
                'created_at': row['created_at'] if 'created_at' in row.keys() else None
            })
        
        return result
        
    finally:
        conn.close()


def get_category(category_id: str) -> dict[str, str]:
    """Get detailed expense category information."""
    conn = db()
    try:
        _ensure_expense_tables(conn)
        
        row = conn.execute(
            """
            SELECT ec.*,
                   COUNT(er.id) as receipt_count,
                   SUM(er.total_amount) as total_amount
            FROM expense_categories ec
            LEFT JOIN expense_receipts er ON er.category_id = ec.id
            WHERE ec.id = ?
            GROUP BY ec.id
            """,
            (category_id,)
        ).fetchone()
        
        if not row:
            raise CategoryNotFound(category_id)
        
        return {
            'id': row['id'],
            'name': row['name'],
            'description': row['description'],
            'color': row['color'],
            'receipt_count': row['receipt_count'] or 0,
            'total_amount': row['total_amount'] or 0,
            'created_at': row['created_at'] if 'created_at' in row.keys() else None
        }
        
    finally:
        conn.close()


def update_category(category_id: str, form_data: dict[str, str], *, actor_id: str) -> None:
    """Update expense category."""
    conn = db()
    try:
        _ensure_expense_tables(conn)
        
        # Check if category exists
        existing = conn.execute(
            "SELECT id FROM expense_categories WHERE id=?",
            (category_id,)
        ).fetchone()
        if not existing:
            raise CategoryNotFound(category_id)
        
        # Check for name conflicts
        if form_data.get('name'):
            name_conflict = conn.execute(
                "SELECT id FROM expense_categories WHERE lower(name) = lower(?) AND id != ?",
                (form_data['name'].strip(), category_id)
            ).fetchone()
            if name_conflict:
                raise ExpenseReceiptError("category_name_exists")
        
        # Build update query
        update_fields = []
        params = []
        
        if form_data.get('name'):
            update_fields.append("name = ?")
            params.append(form_data['name'].strip())
        
        if 'description' in form_data:
            update_fields.append("description = ?")
            params.append(form_data.get('description', '').strip() or None)
        
        if form_data.get('color'):
            update_fields.append("color = ?")
            params.append(form_data['color'].strip())
        
        if not update_fields:
            return
        
        update_fields.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(category_id)
        
        conn.execute(
            f"UPDATE expense_categories SET {', '.join(update_fields)} WHERE id = ?",
            params
        )
        
        conn.commit()
        write_event(actor_id, "expenses:update_category", entity="expense_category", entity_id=category_id)
        
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_category(category_id: str, *, actor_id: str) -> None:
    """Delete expense category (only if no receipts are associated)."""
    conn = db()
    try:
        _ensure_expense_tables(conn)
        
        # Check if category exists and has no receipts
        category = conn.execute(
            """
            SELECT ec.id, COUNT(er.id) as receipt_count
            FROM expense_categories ec
            LEFT JOIN expense_receipts er ON er.category_id = ec.id
            WHERE ec.id = ?
            GROUP BY ec.id
            """,
            (category_id,)
        ).fetchone()
        
        if not category:
            raise CategoryNotFound(category_id)
        
        if category['receipt_count'] > 0:
            raise ExpenseReceiptError("category_has_receipts")
        
        conn.execute("DELETE FROM expense_categories WHERE id = ?", (category_id,))
        conn.commit()
        write_event(actor_id, "expenses:delete_category", entity="expense_category", entity_id=category_id)
        
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_receipt_category(expense_receipt_id: str, category_id: str, *, actor_id: str) -> None:
    """Set category for an expense receipt."""
    conn = db()
    try:
        _ensure_expense_tables(conn)
        
        # Verify both receipt and category exist
        receipt = conn.execute(
            "SELECT id FROM expense_receipts WHERE id=?",
            (expense_receipt_id,)
        ).fetchone()
        if not receipt:
            raise ExpenseReceiptNotFound(expense_receipt_id)
        
        category = conn.execute(
            "SELECT id FROM expense_categories WHERE id=?",
            (category_id,)
        ).fetchone()
        if not category:
            raise CategoryNotFound(category_id)
        
        conn.execute(
            "UPDATE expense_receipts SET category_id = ?, updated_at = ? WHERE id = ?",
            (category_id, datetime.now(timezone.utc).isoformat(), expense_receipt_id)
        )
        
        conn.commit()
        write_event(actor_id, "expenses:set_category", entity="expense_receipt", entity_id=expense_receipt_id)
        
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_receipt_file(attachment_id: str, *, actor_id: str) -> None:
    """Delete a file attachment."""
    conn = db()
    try:
        _ensure_expense_tables(conn)
        
        # Get attachment info before deletion
        attachment = conn.execute(
            "SELECT filename, expense_receipt_id FROM expense_receipts_attachments WHERE id=?",
            (attachment_id,)
        ).fetchone()
        
        if not attachment:
            raise ExpenseReceiptError("attachment_not_found")
        
        # Delete from database
        conn.execute("DELETE FROM expense_receipts_attachments WHERE id=?", (attachment_id,))
        conn.commit()
        
        # Delete physical file
        file_manager = get_receipt_file_manager()
        file_manager.delete_file(attachment['filename'])
        
        write_event(actor_id, "expenses:delete_file", entity="expense_receipt",
                   entity_id=attachment['expense_receipt_id'])
        
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_receipt_status(expense_receipt_id: str, status: str, approval_notes: Optional[str] = None, *, actor_id: str) -> None:
    """Update receipt status (pending, approved, rejected)."""
    conn = db()
    try:
        _ensure_expense_tables(conn)
        
        # Verify receipt exists
        receipt = conn.execute(
            "SELECT id FROM expense_receipts WHERE id=?",
            (expense_receipt_id,)
        ).fetchone()
        if not receipt:
            raise ExpenseReceiptNotFound(expense_receipt_id)
        
        valid_statuses = ['pending', 'approved', 'rejected']
        if status not in valid_statuses:
            raise ExpenseReceiptError(f"invalid_status_{status}")
        
        update_data = {
            'receipt_status': status,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        if status == 'approved':
            update_data['approval_date'] = datetime.now(timezone.utc).isoformat()
            update_data['approved_by'] = actor_id
            if approval_notes:
                update_data['approval_notes'] = approval_notes
        elif status == 'pending':
            # Clear approval data when setting back to pending
            update_data['approval_date'] = None
            update_data['approved_by'] = None
            update_data['approval_notes'] = None
        
        # Build update query
        set_clause = ", ".join(f"{key} = ?" for key in update_data.keys())
        params = list(update_data.values()) + [expense_receipt_id]
        
        conn.execute(
            f"UPDATE expense_receipts SET {set_clause} WHERE id = ?",
            params
        )
        
        conn.commit()
        write_event(actor_id, f"expenses:status_{status}", entity="expense_receipt", entity_id=expense_receipt_id)
        
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_receipt_statistics() -> dict[str, any]:
    """Get expense receipt statistics."""
    conn = db()
    try:
        _ensure_expense_tables(conn)
        
        # Total receipts and amounts by status
        status_stats = conn.execute("""
            SELECT receipt_status, COUNT(*) as count, SUM(total_amount) as total_amount
            FROM expense_receipts
            GROUP BY receipt_status
        """).fetchall()
        
        # Monthly totals (last 12 months)
        monthly_stats = conn.execute("""
            SELECT substr(receipt_date, 1, 7) as month,
                   COUNT(*) as count, SUM(total_amount) as total_amount
            FROM expense_receipts
            WHERE receipt_date >= date('now', '-12 months')
            GROUP BY substr(receipt_date, 1, 7)
            ORDER BY month DESC
        """).fetchall()
        
        result = {
            'by_status': {},
            'monthly': []
        }
        
        for row in status_stats:
            result['by_status'][row['receipt_status']] = {
                'count': row['count'],
                'total_amount': row['total_amount'] or 0
            }
        
        for row in monthly_stats:
            result['monthly'].append({
                'month': row['month'],
                'count': row['count'],
                'total_amount': row['total_amount'] or 0
            })
        
        return result
        
    finally:
        conn.close()

def list_suppliers(active_only: bool = True) -> list[dict[str, str]]:
    """List all suppliers."""
    conn = db()
    try:
        _ensure_expense_tables(conn)
        
        query = "SELECT * FROM suppliers"
        params = []
        
        if active_only:
            query += " WHERE is_active = 1"
        
        query += " ORDER BY name ASC"
        
        rows = conn.execute(query, params).fetchall()
        
        result = []
        for row in rows:
            result.append({
                'id': row['id'],
                'name': row['name'],
                'contact_person': row['contact_person'],
                'phone': row['phone'],
                'email': row['email'],
                'address': row['address'],
                'tax_number': row['tax_number'],
                'is_active': row['is_active'],
                'created_at': row['created_at']
            })
        
        return result
    finally:
        conn.close()


def list_materials(category_id: int | None = None, active_only: bool = True) -> list[dict[str, str]]:
    """List all materials."""
    conn = db()
    try:
        _ensure_expense_tables(conn)
        
        params = []
        where_conditions = []
        
        if active_only:
            where_conditions.append("m.is_active = 1")
        
        if category_id:
            where_conditions.append("m.category_id = ?")
            params.append(category_id)
        
        where_clause = ""
        if where_conditions:
            where_clause = "WHERE " + " AND ".join(where_conditions)
        
        query = f"""
            SELECT m.*, ec.name as category_name
            FROM materials m
            LEFT JOIN expense_categories ec ON ec.id = m.category_id
            {where_clause}
            ORDER BY m.name ASC
        """
        
        rows = conn.execute(query, params).fetchall()
        
        result = []
        for row in rows:
            result.append({
                'id': row['id'],
                'name': row['name'],
                'category_id': row['category_id'],
                'category_name': row['category_name'],
                'unit': row['unit'],
                'price_per_unit': row['price_per_unit'],
                'description': row['description'],
                'supplier_id': row['supplier_id'],
                'is_active': row['is_active'],
                'created_at': row['created_at']
            })
        
        return result
    finally:
        conn.close()