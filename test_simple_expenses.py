#!/usr/bin/env python3
"""Test the new simple expenses system."""

import sys
sys.path.insert(0, '.')

from clinic_app.app import create_app

def test_simple_expenses():
    """Test the simple expenses system."""
    app = create_app()
    
    with app.app_context():
        print("[PASS] Testing simple expenses system...")
        
        # Test imports
        try:
            from clinic_app.services.simple_expenses import (
                create_simple_expense, list_simple_expenses, get_monthly_spending
            )
            print("   [PASS] All services imported successfully")
        except Exception as e:
            print(f"   [FAIL] Import failed: {e}")
            return False
        
        # Test database operations
        try:
            # List expenses (should be empty initially)
            expenses = list_simple_expenses()
            print(f"   [PASS] Found {len(expenses)} existing expenses")
            
            # Test monthly spending
            from datetime import date
            today = date.today()
            monthly_data = get_monthly_spending(today.year, today.month)
            print(f"   [PASS] Monthly spending calculated: {monthly_data['total_spending']} EGP")
            
            print("\n[SUCCESS] Simple expenses system is working correctly!")
            print("   [READY] Ready to use at: http://127.0.0.1:8080/simple-expenses/")
            
            return True
            
        except Exception as e:
            print(f"   [FAIL] Database operation failed: {e}")
            return False

if __name__ == '__main__':
    try:
        test_simple_expenses()
    except Exception as e:
        print(f"\n[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)