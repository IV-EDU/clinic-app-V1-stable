"""Simple expense form for easy receipt entry."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import DecimalField, DateField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, NumberRange, Length


class SimpleExpenseForm(FlaskForm):
    """Simple form for expense entry."""
    receipt_date = DateField("Date", validators=[DataRequired()], format='%Y-%m-%d')
    amount = DecimalField("Amount (EGP)", validators=[
        DataRequired(),
        NumberRange(min=0.01)
    ], places=2)
    description = TextAreaField("What did you buy?", validators=[
        DataRequired(),
        Length(max=500)
    ])
    submit = SubmitField("Save Expense")