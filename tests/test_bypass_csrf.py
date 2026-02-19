#!/usr/bin/env python3
"""
CSRF bypass integration tests — require a running server on port 8080.

These are manual debugging scripts, not real unit tests (no assertions).
They are skipped during normal pytest runs to avoid 4s of network timeout.
Run manually with: python tests/test_bypass_csrf.py
"""

import requests
import json
import pytest

BASE_URL = "http://127.0.0.1:8080"

@pytest.mark.skip(reason="Integration test — requires running server on :8080")
def test_endpoint_direct():
    """Test admin endpoints by bypassing Flask-WTF CSRF entirely"""
    print("Testing admin endpoints with CSRF bypass...")
    
    # Test the colors/reset endpoint (simplest one)
    try:
        # Use a completely empty JSON to see if CSRF validation is bypassed
        test_data = {}
        
        response = requests.post(
            f"{BASE_URL}/admin/settings/colors/reset",
            json=test_data,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"POST /admin/settings/colors/reset - Status: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 400:
            print("ERROR: Still getting CSRF error - Flask-WTF is blocking at a higher level")
        elif response.status_code == 500:
            print("SUCCESS: Request reached the route handler (likely getting DB error)")
        elif response.status_code == 200:
            print("SUCCESS: Endpoint working perfectly")
            
    except Exception as e:
        print(f"Error: {e}")

@pytest.mark.skip(reason="Integration test — requires running server on :8080")
def test_auth_login():
    """Test login endpoint specifically"""
    print("\nTesting login endpoint...")
    
    try:
        # Test with no CSRF token to see the exact error
        response = requests.post(
            f"{BASE_URL}/auth/login",
            data={"username": "admin", "password": "admin123"}
        )
        
        print(f"POST /auth/login - Status: {response.status_code}")
        print(f"Response: {response.text}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_auth_login()
    test_endpoint_direct()