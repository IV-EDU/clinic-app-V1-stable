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
        DataRequired(), 
        Length(max=200)
    ])
    quantity = DecimalField("Quantity", validators=[
        DataRequired(), 
        NumberRange(min=0.01)
    ], places=2)
    unit_price = DecimalField("Unit Price", validators=[
        DataRequired(), 
        NumberRange(min=0.01)
    ], places=2)
    notes = TextAreaField("Notes", validators=[
        Length(max=500)
    ])


class ExpenseReceiptForm(FlaskForm):
    """Main form for expense receipts."""
    supplier_id = SelectField("Supplier", coerce=str, validators=[DataRequired()])
    receipt_date = DateField("Receipt Date", validators=[DataRequired()])
    notes = TextAreaField("Notes", validators=[
        Length(max=1000)
    ])
    tax_rate = DecimalField("Tax Rate (%)", validators=[
        DataRequired(), 
        NumberRange(min=0, max=100)
    ], places=2, default=14.0)
    receipt_image = FileField("Receipt Image")
    
    # Dynamic line items
    items = FieldList(FormField(ExpenseItemForm), min_entries=1)
    
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
    start_date = DateField("Start Date")
    end_date = DateField("End Date")
    search_query = StringField("Search", validators=[
        Length(max=100)
    ])
    
    submit = SubmitField("Search")
    clear = SubmitField("Clear Filters")