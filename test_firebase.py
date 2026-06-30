#!/usr/bin/env python3
"""
Firebase initialization diagnostic script.
Run this to check if Firebase Admin SDK is working correctly.
"""

import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent
sys.path.insert(0, str(backend_path))

def test_firebase_initialization():
    print("=" * 60)
    print("Firebase Admin SDK Diagnostic Test")
    print("=" * 60)
    print()
    
    # Test 1: Check if service account file exists
    print("[TEST 1] Checking service account file...")
    service_account_path = backend_path / "firebase-service-account.json"
    
    if service_account_path.exists():
        print(f"✅ Service account file found: {service_account_path}")
        
        import json
        with open(service_account_path) as f:
            data = json.load(f)
            print(f"   Project ID: {data.get('project_id')}")
            print(f"   Client Email: {data.get('client_email')}")
    else:
        print(f"❌ Service account file NOT found: {service_account_path}")
        return False
    
    print()
    
    # Test 2: Check if firebase-admin is installed
    print("[TEST 2] Checking firebase-admin installation...")
    try:
        import firebase_admin
        print(f"✅ firebase-admin installed (version: {firebase_admin.__version__})")
    except ImportError as e:
        print(f"❌ firebase-admin NOT installed: {e}")
        print("   Install it with: pip install firebase-admin")
        return False
    
    print()
    
    # Test 3: Initialize Firebase
    print("[TEST 3] Initializing Firebase Admin SDK...")
    try:
        from app.firebase_admin import initialize_firebase
        initialize_firebase()
        print("✅ Firebase Admin SDK initialized successfully")
    except Exception as e:
        print(f"❌ Firebase initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    
    # Test 4: Test token verification with a dummy token (expect it to fail)
    print("[TEST 4] Testing token verification...")
    try:
        from app.firebase_admin import verify_firebase_token
        # This should fail because it's a dummy token
        verify_firebase_token("dummy_token_for_testing")
        print("⚠️  Dummy token was accepted (unexpected)")
    except Exception as e:
        error_message = str(e)
        if "Invalid" in error_message or "Incorrect" in error_message:
            print("✅ Token verification is working (correctly rejected dummy token)")
        else:
            print(f"⚠️  Unexpected error: {e}")
    
    print()
    
    # Test 5: Check if Firebase app is initialized
    print("[TEST 5] Checking Firebase app status...")
    try:
        from firebase_admin import _apps
        if _apps:
            print(f"✅ Firebase app initialized: {list(_apps.keys())}")
        else:
            print("❌ No Firebase apps initialized")
            return False
    except Exception as e:
        print(f"❌ Error checking Firebase apps: {e}")
        return False
    
    print()
    print("=" * 60)
    print("✅ All tests passed! Firebase is working correctly")
    print("=" * 60)
    return True


def test_backend_startup():
    print()
    print("=" * 60)
    print("Testing Backend Startup")
    print("=" * 60)
    print()
    
    try:
        from app.main import create_app
        app = create_app()
        print("✅ Backend app created successfully")
        
        # Check if orchestrator would be available
        if hasattr(app, 'state'):
            print("✅ App state available")
        
        return True
    except Exception as e:
        print(f"❌ Backend startup failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print()
    
    # Run Firebase tests
    firebase_ok = test_firebase_initialization()
    
    # Run backend tests
    backend_ok = test_backend_startup()
    
    print()
    print("=" * 60)
    if firebase_ok and backend_ok:
        print("✅ ALL DIAGNOSTICS PASSED")
        print()
        print("Firebase authentication should work correctly.")
        print("Start your backend with: uvicorn app.main:app --reload")
        sys.exit(0)
    else:
        print("❌ SOME DIAGNOSTICS FAILED")
        print()
        print("Fix the issues above before starting the backend.")
        sys.exit(1)
