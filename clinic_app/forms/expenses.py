"""Expense-related forms for validation and handling."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    DecimalField, DateField, FileField, StringField, TextAreaField, 
    HiddenField, SubmitField, BooleanField, SelectField, IntegerField
)
from wtforms.validators import DataRequired, NumberRange, Length, Email, Optional
from wtforms.fields import FieldList, FormField


class ExpenseItemForm(FlaskForm):
    """Form for individual expense receipt items."""
    material_name = StringField("Material Name", validators=[
        Optional(),
        Length(max=200)
    ])
    quantity = DecimalField("Quantity", validators=[
        Optional(),
        NumberRange(min=0.01)
    ], places=2)
    unit_price = DecimalField("Unit Price", validators=[
        Optional(),
        NumberRange(min=0.01)
    ], places=2)
    notes = TextAreaField("Notes", validators=[
        Length(max=500)
    ])


class ExpenseReceiptForm(FlaskForm):
    """Main form for expense receipts."""
    supplier_id = HiddenField("Supplier", validators=[Optional()])
    receipt_date = DateField("Receipt Date", validators=[DataRequired()])
    total_amount = DecimalField("Total Paid (EGP)", validators=[
        DataRequired(),
        NumberRange(min=0)
    ], places=2)
    notes = TextAreaField("What did you buy?", validators=[
        Length(max=1000)
    ])
    tax_rate = DecimalField("Tax Rate (%)", validators=[
        DataRequired(), 
        NumberRange(min=0, max=100)
    ], places=2, default=14.0)
    receipt_image = FileField("Receipt Image")
    category_id = SelectField("Category", coerce=str, validators=[Optional()])
    receipt_status = SelectField("Status", choices=[
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], default='pending', validators=[DataRequired()])
    
    # Dynamic line items
    items = FieldList(FormField(ExpenseItemForm), min_entries=0)
    
    add_item = SubmitField("Add Another Item")
    submit = SubmitField("Create Receipt")


class ExpenseReceiptEditForm(ExpenseReceiptForm):
    """Form for editing expense receipts."""
    submit = SubmitField("Update Receipt")


class SupplierForm(FlaskForm):
    """Form for managing suppliers."""
    name = StringField("Supplier Name", validators=[
        DataRequired(), 
        Length(max=200)
    ])
    contact_person = StringField("Contact Person", validators=[
        Length(max=100)
    ])
    phone = StringField("Phone", validators=[
        Length(max=50)
    ])
    email = StringField("Email", validators=[
        Optional(), 
        Email(), 
        Length(max=100)
    ])
    address = TextAreaField("Address", validators=[
        Length(max=500)
    ])
    tax_number = StringField("Tax Number", validators=[
        Length(max=50)
    ])
    is_active = BooleanField("Active", default=True)
    
    submit = SubmitField("Save Supplier")


class MaterialForm(FlaskForm):
    """Form for managing materials."""
    name = StringField("Material Name", validators=[
        DataRequired(), 
        Length(max=200)
    ])
    category_name = StringField("Category", validators=[
        Length(max=100)
    ])
    unit = StringField("Unit of Measure", validators=[
        DataRequired(), 
        Length(max=50)
    ])
    price_per_unit = DecimalField("Price per Unit", validators=[
        Optional(), 
        NumberRange(min=0)
    ], places=2)
    description = TextAreaField("Description", validators=[
        Length(max=500)
    ])
    is_active = BooleanField("Active", default=True)
    
    submit = SubmitField("Save Material")


class ExpenseSearchForm(FlaskForm):
    """Form for searching expense receipts."""
    supplier_id = SelectField("Supplier", coerce=str)
    category_id = SelectField("Category", coerce=str)
    receipt_status = SelectField("Status", choices=[
        ('', 'All Statuses'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ])
    start_date = DateField("Start Date")
    end_date = DateField("End Date")
    min_amount = DecimalField("Min Amount", validators=[
        Optional(),
        NumberRange(min=0)
    ], places=2)
    max_amount = DecimalField("Max Amount", validators=[
        Optional(),
        NumberRange(min=0)
    ], places=2)
    search_query = StringField("Search", validators=[
        Length(max=100)
    ])
    
    submit = SubmitField("Search")
    clear = SubmitField("Clear Filters")
    export = SubmitField("Export Results")


class ExpenseStatusForm(FlaskForm):
    """Form for managing receipt status and approval."""
    receipt_status = SelectField("Status", choices=[
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], validators=[DataRequired()])
    approval_notes = TextAreaField("Approval Notes", validators=[
        Length(max=500)
    ])
    submit = SubmitField("Update Status")


class ExpenseCategoryForm(FlaskForm):
    """Form for managing expense categories."""
    name = StringField("Category Name", validators=[
        DataRequired(),
        Length(max=100)
    ])
    description = TextAreaField("Description", validators=[
        Length(max=500)
    ])
    color = StringField("Color", validators=[
        Length(max=7)
    ], default="#3498db")
    submit = SubmitField("Save Category")
