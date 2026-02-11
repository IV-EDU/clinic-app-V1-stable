"""Expenses blueprint for managing dental material expenses."""

from __future__ import annotations

# Import routes to register decorators and routes
from clinic_app.blueprints.expenses import routes

# Export the blueprint for registration
bp = routes.bp

__all__ = ["bp"]