"""
Authentication API.

Endpoints:
  POST /api/v1/auth/firebase-login → Login with Firebase (Google/Apple/etc.)
  POST /api/v1/auth/login         → JWT access + refresh tokens (email/password)
  POST /api/v1/auth/refresh       → new access token from refresh token
  POST /api/v1/auth/logout        → invalidate refresh token
  POST /api/v1/auth/register      → create user (admin only in production)
  POST /api/v1/auth/keys          → create API key
  GET  /api/v1/auth/keys          → list API keys
  DELETE /api/v1/auth/keys/{id}   → revoke API key
  GET  /api/v1/auth/me            → current user info
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,
)
from app.database import get_db
from app.db.models import APIKey, User
from app.db.repositories import UserRepository
from app.shared.schemas import UserOut

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ── Request / Response schemas ────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class RefreshRequest(BaseModel):
    refresh_token: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: Optional[str] = None
    role: str = Field(default="developer")
    org_id: str


class CreateAPIKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: ["read", "write"])
    expires_days: Optional[int] = None


class APIKeyOut(BaseModel):
    id: str
    name: str
    scopes: list[str]
    created_at: datetime
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]


class CreateAPIKeyResponse(BaseModel):
    key: str  # Raw key — shown ONCE, then only the hash is stored
    details: APIKeyOut


class FirebaseLoginRequest(BaseModel):
    """Request to login with Firebase ID token."""
    firebase_token: str = Field(..., min_length=1)


class FirebaseLoginResponse(BaseModel):
    """Response after successful Firebase login."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut
    is_new_user: bool  # True if user was just created (first login)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/firebase-login", response_model=FirebaseLoginResponse)
async def firebase_login(
    req: FirebaseLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> FirebaseLoginResponse:
    """
    Authenticate with Firebase ID token (Google Sign-In).
    
    Flow:
    1. Frontend gets Firebase ID token from Google Sign-In
    2. Backend verifies token with Firebase Admin SDK
    3. Find or create user in database
    4. Issue JWT access + refresh tokens
    5. Return tokens + user info
    
    This is the primary authentication method for the web app.
    """
    from loguru import logger
    
    try:
        from firebase_admin import auth as firebase_auth_errors
        from app.firebase_admin import verify_firebase_token
        from sqlalchemy import select
        from app.db.models import Organization
        
        # Step 1: Verify Firebase token
        try:
            decoded_token = verify_firebase_token(req.firebase_token)
        except firebase_auth_errors.ExpiredIdTokenError:
            logger.warning("Firebase token expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Firebase token expired. Please sign in again.",
            )
        except firebase_auth_errors.InvalidIdTokenError as e:
            logger.error(f"Invalid Firebase token: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid Firebase token: {str(e)}",
            )
        except RuntimeError as e:
            logger.error(f"Firebase not initialized: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Firebase authentication is not available. Contact administrator.",
            )
        except Exception as e:
            logger.exception(f"Unexpected error verifying Firebase token: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Failed to verify Firebase token: {str(e)}",
            )
        
        # Step 2: Extract user info from token
        email = decoded_token.get("email")
        firebase_uid = decoded_token.get("uid")
        name = decoded_token.get("name")
        picture = decoded_token.get("picture")
        email_verified = decoded_token.get("email_verified", False)
        
        # Get sign-in provider (google.com, apple.com, etc.)
        firebase_info = decoded_token.get("firebase", {})
        sign_in_provider = firebase_info.get("sign_in_provider", "google")
        
        # Map Firebase provider to our auth_provider field
        provider_map = {
            "google.com": "google",
            "apple.com": "apple",
            "microsoft.com": "microsoft",
            "github.com": "github",
        }
        auth_provider = provider_map.get(sign_in_provider, "google")
        
        if not email:
            logger.error("Email not found in Firebase token")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email not found in Firebase token",
            )
        
        logger.info(f"Firebase authentication for: {email}")
        
        # For V1: Single organization - all users go to "default" org
        org_id = "default"
        
        # Step 3: Ensure default organization exists
        result = await db.execute(select(Organization).where(Organization.id == org_id))
        org = result.scalar_one_or_none()
        
        if not org:
            # Create default organization if it doesn't exist
            logger.info("Creating default organization")
            org = Organization(
                id=org_id,
                name="Atlas",
                slug="atlas",
                plan="free",
                max_repos=10,
                max_users=100,
            )
            db.add(org)
            await db.flush()
        
        # Step 4: Find or create user
        user_repo = UserRepository(db)
        user = await user_repo.get_by_email(org_id, email)
        
        is_new_user = False
        
        if not user:
            # First time user - auto-register
            is_new_user = True
            logger.info(f"Auto-registering new user: {email}")
            user = User(
                org_id=org_id,
                email=email,
                full_name=name,
                role="developer",  # Default role for new users
                hashed_password="",  # No password for OAuth users
                auth_provider=auth_provider,
                firebase_uid=firebase_uid,
                profile_picture_url=picture,
                email_verified=email_verified,
                is_active=True,
            )
            db.add(user)
            await db.flush()
            
            logger.info(f"✅ New user registered via {auth_provider}: {email}")
        else:
            # Existing user - update Firebase info if needed
            if not user.firebase_uid:
                user.firebase_uid = firebase_uid
            if not user.profile_picture_url and picture:
                user.profile_picture_url = picture
            if not user.email_verified and email_verified:
                user.email_verified = email_verified
            
            await user_repo.update_last_login(user.id)
            logger.info(f"✅ Existing user logged in: {email}")
        
        await db.commit()
        
        # Step 5: Issue JWT tokens
        access_token = create_access_token(user.id, user.org_id, user.role)
        refresh_token = create_refresh_token(user.id)
        
        # Store refresh token in Redis for validation and revocation
        from app.redis_client import get_redis
        from app.config import get_settings
        
        r = get_redis()
        cfg = get_settings()
        await r.setex(
            f"refresh:{refresh_token}",
            cfg.jwt_refresh_token_expire_days * 86400,
            user.id,
        )
        
        logger.info(f"✅ Firebase login successful for: {email}")
        
        return FirebaseLoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=UserOut(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=user.role,
                created_at=user.created_at,
            ),
            is_new_user=is_new_user,
        )
    
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Catch any unexpected errors
        logger.exception(f"Unexpected error in firebase_login: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during login: {str(e)}",
        )


@router.post("/login", response_model=LoginResponse)
async def login(
    req: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Authenticate with email + password. Returns JWT tokens."""
    user_repo = UserRepository(db)

    # We need the org_id to look up by email.
    # For V1 single-org setups, look up by email directly.
    from sqlalchemy import select
    result = await db.execute(
        select(User).where(User.email == req.email, User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    await user_repo.update_last_login(user.id)

    access_token = create_access_token(user.id, user.org_id, user.role)
    refresh_token = create_refresh_token(user.id)

    # Store refresh token in Redis for validation and revocation
    from app.redis_client import get_redis
    r = get_redis()
    from app.config import get_settings
    cfg = get_settings()
    await r.setex(
        f"refresh:{refresh_token}",
        cfg.jwt_refresh_token_expire_days * 86400,
        user.id,
    )

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserOut(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            created_at=user.created_at,
        ),
    )


@router.post("/refresh", response_model=dict)
async def refresh_token(
    req: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Exchange a refresh token for a new access token."""
    from app.redis_client import get_redis
    r = get_redis()

    # Check Redis — refresh tokens are stored there for instant revocation
    user_id = await r.get(f"refresh:{req.refresh_token}")
    if not user_id:
        raise HTTPException(401, "Invalid or expired refresh token")

    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(401, "User not found or inactive")

    # Rotate: invalidate old refresh token, issue new one
    await r.delete(f"refresh:{req.refresh_token}")
    new_refresh_token = create_refresh_token(user.id)

    from app.config import get_settings
    cfg = get_settings()
    await r.setex(
        f"refresh:{new_refresh_token}",
        cfg.jwt_refresh_token_expire_days * 86400,
        user.id,
    )

    return {
        "access_token": create_access_token(user.id, user.org_id, user.role),
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }


@router.post("/logout")
async def logout(req: RefreshRequest) -> dict:
    """Invalidate a refresh token."""
    from app.redis_client import get_redis
    r = get_redis()
    await r.delete(f"refresh:{req.refresh_token}")
    return {"message": "Logged out successfully"}


@router.post("/register", response_model=UserOut, status_code=201)
async def register(
    req: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    """
    Create a new user account.
    In production: restrict to admin role or invite-only flow.
    """
    user_repo = UserRepository(db)

    existing = await user_repo.get_by_email(req.org_id, req.email)
    if existing:
        raise HTTPException(409, "Email already registered in this organisation")

    user = await user_repo.create(
        org_id=req.org_id,
        email=req.email,
        hashed_password=hash_password(req.password),
        full_name=req.full_name,
        role=req.role,
    )

    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        created_at=user.created_at,
    )


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)) -> UserOut:
    """Return the currently authenticated user."""
    return UserOut(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        created_at=current_user.created_at,
    )


@router.post("/keys", response_model=CreateAPIKeyResponse, status_code=201)
async def create_api_key(
    req: CreateAPIKeyRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CreateAPIKeyResponse:
    """Create a new API key. The raw key is returned ONCE — store it securely."""
    import json
    from datetime import timedelta

    raw_key, key_hash = generate_api_key()
    expires_at = None
    if req.expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=req.expires_days)

    api_key = APIKey(
        user_id=current_user.id,
        key_hash=key_hash,
        name=req.name,
        scopes_json=json.dumps(req.scopes),
        expires_at=expires_at,
    )
    db.add(api_key)
    await db.flush()

    return CreateAPIKeyResponse(
        key=raw_key,
        details=APIKeyOut(
            id=api_key.id,
            name=api_key.name,
            scopes=req.scopes,
            created_at=api_key.created_at,
            last_used_at=None,
            expires_at=expires_at,
        ),
    )


@router.get("/keys", response_model=list[APIKeyOut])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[APIKeyOut]:
    """List API keys for the current user."""
    import json
    from sqlalchemy import select

    result = await db.execute(
        select(APIKey).where(APIKey.user_id == current_user.id, APIKey.is_active == True)  # noqa: E712
    )
    keys = list(result.scalars().all())
    return [
        APIKeyOut(
            id=k.id,
            name=k.name,
            scopes=json.loads(k.scopes_json),
            created_at=k.created_at,
            last_used_at=k.last_used_at,
            expires_at=k.expires_at,
        )
        for k in keys
    ]


@router.delete("/keys/{key_id}", status_code=200)
async def revoke_api_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke an API key."""
    from sqlalchemy import select, update

    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.user_id == current_user.id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(404, "API key not found")

    await db.execute(
        update(APIKey).where(APIKey.id == key_id).values(is_active=False)
    )
