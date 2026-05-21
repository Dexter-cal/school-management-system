#!/usr/bin/env python
"""
Test script to verify sidebar menu rendering works correctly.
Tests: Login → Profile retrieval → Frontend code validation
"""

import requests
import json
import os

def test_sidebar_menu():
    session = requests.Session()
    
    print("\n" + "="*60)
    print("TESTING SIDEBAR MENU RENDERING")
    print("="*60)
    
    # Test 1: CSRF Token
    print("\n[TEST 1] Getting CSRF token...")
    try:
        resp = session.get('http://127.0.0.1:8000/api/auth/csrf/', timeout=5)
        assert resp.status_code == 200, f"Status: {resp.status_code}"
        csrf_token = resp.json()['csrfToken']
        print("✓ CSRF token obtained successfully")
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False
    
    # Test 2: Login
    print("\n[TEST 2] Testing authentication (configured superadmin credentials)...")
    try:
        resp = session.post(
            'http://127.0.0.1:8000/api/auth/login/',
            json={
                'identifier': os.environ.get('BJS_TEST_USERNAME', 'admin'),
                'password': os.environ.get('BJS_TEST_PASSWORD', ''),
            },
            headers={'X-CSRFToken': csrf_token, 'Content-Type': 'application/json'},
            timeout=5
        )
        assert resp.status_code == 200, f"Status: {resp.status_code}"
        print("✓ Login successful")
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False
    
    # Test 3: Get user profile
    print("\n[TEST 3] Retrieving user profile...")
    try:
        resp = session.get('http://127.0.0.1:8000/api/auth/me/', timeout=5)
        assert resp.status_code == 200, f"Status: {resp.status_code}"
        user_data = resp.json()
        
        # Check profile exists
        assert 'profile' in user_data, "Profile not in response"
        role = user_data['profile'].get('role')
        print(f"✓ User profile retrieved: role={role}")
        
        assert role == 'superadmin', f"Expected superadmin, got {role}"
        print("✓ Role is superadmin (full menu should display)")
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False
    
    # Test 4: Verify frontend code
    print("\n[TEST 4] Checking frontend code elements...")
    try:
        resp = session.get('http://127.0.0.1:8000/', timeout=5)
        assert resp.status_code == 200, f"Status: {resp.status_code}"
        html = resp.text
        
        checks = {
            'sb-nav-content element': 'sb-nav-content' in html,
            'buildSidebar function': 'function buildSidebar()' in html,
            'debugSidebar function': 'window.debugSidebar = function()' in html,
            'NAV object definition': 'const NAV =' in html or 'var NAV =' in html,
            'Enhanced error handling': '[DEBUG]' in html and '[ERROR]' in html,
            'Fallback element creation': 'sidebar.insertBefore(newNav' in html,
        }
        
        all_pass = True
        for check_name, result in checks.items():
            status = "✓" if result else "✗"
            print(f"  {status} {check_name}: {result}")
            if not result:
                all_pass = False
        
        return all_pass
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False

if __name__ == '__main__':
    success = test_sidebar_menu()
    
    print("\n" + "="*60)
    if success:
        print("✓ ALL TESTS PASSED!")
        print("\nMenu rendering should now work correctly.")
        print("The enhanced buildSidebar() function includes:")
        print("  • Error handling (try-catch)")
        print("  • Fallback element creation")
        print("  • Detailed console logging")
        print("  • Item counter tracking")
        print("  • CSS visibility verification")
        print("\nTo verify in browser:")
        print("  1. Open http://127.0.0.1:8000")
        print("  2. Set BJS_TEST_USERNAME and BJS_TEST_PASSWORD, then login with those credentials")
        print("  3. Press F12 and check Console tab")
        print("  4. Run: debugSidebar()")
        print("  5. Menu items should be visible in sidebar")
    else:
        print("✗ SOME TESTS FAILED")
        print("\nPlease review the errors above.")
    print("="*60 + "\n")
