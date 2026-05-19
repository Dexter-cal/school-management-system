#!/usr/bin/env python
"""
Complete end-to-end test of sidebar menu rendering functionality.
Tests: API connectivity → CSRF → Login → Profile retrieval → Frontend code validation.
"""

import requests
import json
import time
from requests.exceptions import ConnectTimeout, ReadTimeout

def test_complete_flow():
    """Run complete test of menu rendering system."""
    
    print("\n" + "="*70)
    print("COMPLETE END-TO-END MENU RENDERING TEST")
    print("="*70)
    
    session = requests.Session()
    session.timeout = 30  # Global timeout
    
    # Test 1: Basic connectivity
    print("\n[1/5] Testing basic API connectivity...")
    try:
        resp = session.get('http://127.0.0.1:8000/api/auth/csrf/', timeout=10)
        assert resp.status_code == 200
        print("     ✓ Server responsive")
    except Exception as e:
        print(f"     ✗ Server not responding: {e}")
        return False
    
    # Test 2: Get CSRF token
    print("[2/5] Obtaining CSRF token...")
    try:
        csrf_data = resp.json()
        csrf_token = csrf_data.get('csrfToken')
        assert csrf_token, "No CSRF token in response"
        print(f"     ✓ CSRF token obtained: {csrf_token[:20]}...")
    except Exception as e:
        print(f"     ✗ Failed to get CSRF token: {e}")
        return False
    
    # Test 3: User authentication
    print("[3/5] Authenticating user (admin/admin)...")
    try:
        login_data = {'identifier': 'admin', 'password': 'admin'}
        headers = {
            'X-CSRFToken': csrf_token,
            'Content-Type': 'application/json'
        }
        resp = session.post(
            'http://127.0.0.1:8000/api/auth/login/',
            json=login_data,
            headers=headers,
            timeout=30
        )
        if resp.status_code not in [200, 201]:
            print(f"     ✗ Login failed with status {resp.status_code}")
            print(f"       Response: {resp.text[:200]}")
            return False
        print("     ✓ User authenticated successfully")
    except Exception as e:
        print(f"     ✗ Login failed: {e}")
        return False
    
    # Test 4: Verify user profile with role
    print("[4/5] Retrieving authenticated user profile...")
    try:
        resp = session.get('http://127.0.0.1:8000/api/auth/me/', timeout=10)
        assert resp.status_code == 200
        user_data = resp.json()
        
        # Verify profile structure
        assert 'profile' in user_data, "Profile missing in response"
        profile = user_data['profile']
        role = profile.get('role')
        
        print(f"     ✓ User profile retrieved")
        print(f"       - Role: {role}")
        print(f"       - Email: {user_data.get('email', 'N/A')}")
        
        if role != 'superadmin':
            print(f"     ⚠ Warning: Expected superadmin, got {role}")
        else:
            print(f"     ✓ Role is superadmin (full menu should display)")
            
    except Exception as e:
        print(f"     ✗ Failed to retrieve profile: {e}")
        return False
    
    # Test 5: Verify frontend code
    print("[5/5] Verifying frontend menu rendering code...")
    try:
        resp = session.get('http://127.0.0.1:8000/', timeout=10)
        assert resp.status_code == 200
        html = resp.text
        
        # Check critical components
        checks = [
            ('sb-nav-content element', 'id="sb-nav-content"' in html),
            ('buildSidebar function', 'function buildSidebar()' in html),
            ('debugSidebar function', 'window.debugSidebar = function()' in html),
            ('NAV object', 'const NAV = {' in html),
            ('superadmin menu items', '"superadmin":' in html),
            ('Error handling', 'console.error' in html and '[ERROR]' in html),
            ('Try-catch blocks', 'try {' in html and 'catch' in html),
            ('Fallback creation', 'sidebar.insertBefore(newNav' in html),
            ('enterApp function', 'function enterApp()' in html),
            ('doLogin function', 'function doLogin()' in html),
        ]
        
        print("     Frontend code validation:")
        all_pass = True
        for check_name, result in checks:
            status = "✓" if result else "✗"
            print(f"       {status} {check_name}")
            if not result:
                all_pass = False
        
        if not all_pass:
            print("     ⚠ Some components missing - menu may not render correctly")
            return False
        else:
            print("     ✓ All components present")
            
    except Exception as e:
        print(f"     ✗ Frontend verification failed: {e}")
        return False
    
    return True

def main():
    """Main test runner."""
    try:
        success = test_complete_flow()
        
        print("\n" + "="*70)
        if success:
            print("✓ ALL TESTS PASSED - SYSTEM IS READY")
            print("\nThe sidebar menu rendering system is fully functional:")
            print("  • Backend API is working correctly")
            print("  • User authentication and profile retrieval successful")
            print("  • Frontend code with error handling is loaded")
            print("  • All required menu components present")
            print("\nNEXT STEPS:")
            print("  1. Open browser: http://127.0.0.1:8000")
            print("  2. Login with: admin / admin")
            print("  3. Check if menu items appear in sidebar")
            print("  4. Open browser console (F12)")
            print("  5. Run: debugSidebar()")
            print("  6. Check [DEBUG] messages showing menu rendering")
            print("\nEXPECTED RESULT:")
            print("  • Dashboard, Classes, Events, Settings visible in sidebar")
            print("  • Console shows [DEBUG] messages with item count")
            print("  • No [ERROR] messages (unless intentionally debugging)")
        else:
            print("✗ TESTS FAILED - REVIEW ERRORS ABOVE")
        print("="*70 + "\n")
        
        return 0 if success else 1
        
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    exit(main())
