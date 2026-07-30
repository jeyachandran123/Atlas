"""
Firebase Admin SDK initialization.

Initializes Firebase Admin SDK on application startup.
Used to verify Firebase ID tokens sent from the frontend.
"""

from __future__ import annotations

import os
from pathlib import Path

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from loguru import logger

_firebase_initialized = False


def initialize_firebase() -> None:
    """
    Initialize Firebase Admin SDK.
    
    Call this once during application startup (in main.py).
    Uses service account JSON file for authentication.
    """
    global _firebase_initialized
    
    if _firebase_initialized:
        logger.debug("Firebase Admin SDK already initialized")
        return
    
    # Path to service account JSON file
    service_account_path = Path(__file__).parent.parent / "firebase-service-account.json"
    
    if not service_account_path.exists():
        raise FileNotFoundError(
            f"Firebase service account file not found: {service_account_path}\n"
            "Download it from Firebase Console → Project Settings → Service Accounts"
        )
    
    try:
        cred = credentials.Certificate(str(service_account_path))
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        logger.info("✅ Firebase Admin SDK initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Firebase Admin SDK: {e}")
        raise


def verify_firebase_token(id_token: str) -> dict:
    """
    Verify a Firebase ID token received from the frontend.
    
    Args:
        id_token: Firebase ID token (JWT) from client
    
    Returns:
        dict: Decoded token payload containing:
            - uid: Firebase user ID
            - email: User email
            - name: User display name (if available)
            - picture: Profile picture URL (if available)
            - email_verified: bool
            - firebase.sign_in_provider: "google.com", "apple.com", etc.
    
    Raises:
        firebase_admin.auth.InvalidIdTokenError: If token is invalid
        firebase_admin.auth.ExpiredIdTokenError: If token is expired
        firebase_admin.auth.RevokedIdTokenError: If token is revoked
    """
    if not _firebase_initialized:
        raise RuntimeError("Firebase Admin SDK not initialized. Call initialize_firebase() first.")
    
    # Verify token and return decoded payload
    # Firebase Admin SDK handles:
    # - Signature verification (using Google's public keys)
    # - Expiration check
    # - Issuer validation
    # - Audience validation
    #
    # clock_skew_seconds tolerates small clock drift between this machine and Google
    # (avoids the "Token used too early / expired" failure when the local clock is a few
    # seconds off). Google supports up to 60s; 10s is a safe, conservative tolerance.
    try:
        decoded_token = firebase_auth.verify_id_token(
            id_token, check_revoked=False, clock_skew_seconds=10
        )
    except TypeError:
        # Older firebase-admin without clock_skew_seconds — fall back gracefully.
        decoded_token = firebase_auth.verify_id_token(id_token, check_revoked=False)
    
    logger.debug(f"✅ Verified Firebase token for user: {decoded_token.get('email')}")
    
    return decoded_token


def get_firebase_user(uid: str) -> dict:
    """
    Get user information from Firebase by UID.
    
    Args:
        uid: Firebase user ID
    
    Returns:
        dict: User information
    """
    if not _firebase_initialized:
        raise RuntimeError("Firebase Admin SDK not initialized")
    
    user = firebase_auth.get_user(uid)
    
    return {
        "uid": user.uid,
        "email": user.email,
        "display_name": user.display_name,
        "photo_url": user.photo_url,
        "email_verified": user.email_verified,
        "disabled": user.disabled,
        "provider_data": [
            {
                "provider_id": provider.provider_id,
                "uid": provider.uid,
                "email": provider.email,
            }
            for provider in user.provider_data
        ],
    }
