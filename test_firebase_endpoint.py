#!/usr/bin/env python3
"""
Direct test of Firebase login endpoint without making HTTP requests.
This will show the exact error that's causing the 500.
"""

import asyncio
import sys
from pathlib import Path

backend_path = Path(__file__).parent
sys.path.insert(0, str(backend_path))


async def test_firebase_login():
    print("=" * 60)
    print("Testing Firebase Login Endpoint")
    print("=" * 60)
    print()
    
    # Your actual Firebase token from the browser
    firebase_token = "eyJhbGciOiJSUzI1NiIsImtpZCI6IjJmMjk1MGEyNGFlYWRkMjYzYzIxM2I2MDNhZjMxNWEzMjdiNmM3MjAiLCJ0eXAiOiJKV1QifQ.eyJuYW1lIjoiSmV5YWNoYW5kcmFuIFMiLCJwaWN0dXJlIjoiaHR0cHM6Ly9saDMuZ29vZ2xldXNlcmNvbnRlbnQuY29tL2EvQUNnOG9jS016TjBERXZDcW1GbU55T21QZEFlT3FUbEs2X0pZeGV3eHBXZTFzZENTQ01VRTBqTmRrdz1zOTYtYyIsImlzcyI6Imh0dHBzOi8vc2VjdXJldG9rZW4uZ29vZ2xlLmNvbS9hdGxhcy1haS1hc3Npc3RhbnQtMWFlOTEiLCJhdWQiOiJhdGxhcy1haS1hc3Npc3RhbnQtMWFlOTEiLCJhdXRoX3RpbWUiOjE3ODI4MzE3ODIsInVzZXJfaWQiOiI4cTdnS2hyalJLTUVjcmtHTDRnS1ZGSlljeXQxIiwic3ViIjoiOHE3Z0tocmpSS01FY3JrR0w0Z0tWRkpZY3l0MSIsImlhdCI6MTc4MjgzMTc4MiwiZXhwIjoxNzgyODM1MzgyLCJlbWFpbCI6ImNoYW5kcnV2aWtraTAwMDdAZ21haWwuY29tIiwiZW1haWxfdmVyaWZpZWQiOnRydWUsImZpcmViYXNlIjp7ImlkZW50aXRpZXMiOnsiZ29vZ2xlLmNvbSI6WyIxMDEzMDUzMDUxNDc0NjMyMjYxMjkiXSwiZW1haWwiOlsiY2hhbmRydXZpa2tpMDAwN0BnbWFpbC5jb20iXX0sInNpZ25faW5fcHJvdmlkZXIiOiJnb29nbGUuY29tIn19.MekC4AQk1Bnt7nqKtnnxCDOvJ7NedZNhrkaM6YgkmXnoST6FVcx3FCFCbIgyQUAueNsQZsmYtJeHa7MD8P_K3bY15RRpO7pnDUl3a3tfjR-31uJZsPFv7UVHtqKmnpaMVKeYhlFnrQ1bt13d-Nup4wmMWPLZ-QtVCd7HBNEiAwE6h3mOeZ_ac-xsq2hOUP0TqRS6844zEPxVYoZcuucLaM-1GhizXnUgd-_iwoWciaABfUAe2omRNDD95Q5HAmB8j9OK_zHTiEfv7gIaaCsYk8kX7e5JcwB9q0KBFpUNuycZA8gVfRG70G9clOrCDJipFLUcq5yDXaaTc-A9MQe2SA"
    
    try:
        from app.firebase_admin import initialize_firebase, verify_firebase_token
        
        # Step 1: Initialize Firebase
        print("[Step 1] Initializing Firebase...")
        initialize_firebase()
        print("✅ Firebase initialized\n")
        
        # Step 2: Verify the token
        print("[Step 2] Verifying Firebase token...")
        decoded_token = verify_firebase_token(firebase_token)
        print(f"✅ Token verified for: {decoded_token.get('email')}\n")
        
        # Step 3: Test database connection
        print("[Step 3] Testing database connection...")
        from app.database import get_engine
        from sqlalchemy import text
        
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            print(f"✅ Database connected\n")
        
        # Step 4: Test the actual endpoint logic
        print("[Step 4] Testing endpoint logic...")
        from app.database import get_db
        from app.api.v1.auth.router import FirebaseLoginRequest
        from sqlalchemy.ext.asyncio import AsyncSession
        
        # Get a database session
        async for db in get_db():
            try:
                # Create request object
                req = FirebaseLoginRequest(firebase_token=firebase_token)
                
                # Import the endpoint function
                from app.api.v1.auth.router import firebase_login
                
                # Call the endpoint
                print("   Calling firebase_login endpoint...")
                result = await firebase_login(req, db)
                
                print(f"✅ Login successful!")
                print(f"   User: {result.user.email}")
                print(f"   Is new user: {result.is_new_user}")
                print(f"   Access token: {result.access_token[:20]}...")
                
                return True
                
            except Exception as e:
                print(f"❌ Endpoint failed: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                return False
            finally:
                await db.close()
                break
        
    except Exception as e:
        print(f"❌ Test failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_firebase_login())
    
    print()
    print("=" * 60)
    if success:
        print("✅ Firebase login endpoint is working!")
        print("   The 500 error must be from something else.")
    else:
        print("❌ Firebase login endpoint failed")
        print("   Check the error above for details")
    print("=" * 60)
    
    sys.exit(0 if success else 1)
