"""
Authentication API.

Endpoints:
  POST /api/v1/auth/firebase-login → Login with Firebase (Google/Apple/etc.)
  POST /api/v1/auth/login         → JWT access + refresh tokens (email/password)
  POST /api/v1/auth/refresh       → new access token from refresh token
  POST /api/v1/auth/logout        → invalidate refresh token
  POST /api/v1/auth/register      → self-service sign-up into the default organisation
  POST /api/v1/auth/password      → add a password to this account, or change it
  POST /api/v1/auth/keys          → create API key
  GET  /api/v1/auth/keys          → list API keys
  DELETE /api/v1/auth/keys/{id}   → revoke API key
  GET  /api/v1/auth/me            → current user info
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select, update
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
from app.signup.verification import SignupError

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
    """Self-service sign-up.

    Role and organisation are not fields: the server decides both. Taking
    them from the request let anyone register as an admin, or into any
    organisation.
    """
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=255)


class SetPasswordRequest(BaseModel):
    current_password: Optional[str] = None
    new_password: str = Field(..., min_length=8, max_length=128)


class VerifySignupRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=12)


class ResendSignupRequest(BaseModel):
    email: EmailStr


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


# ── Firebase login helpers (reduce coupling in firebase_login) ────────────────


def _verify_firebase_token_safe(firebase_token: str) -> dict:
    """Verify Firebase token and raise appropriate HTTPExceptions."""
    from firebase_admin import auth as firebase_auth_errors
    from app.firebase_admin import verify_firebase_token
    try:
        return verify_firebase_token(firebase_token)
    except firebase_auth_errors.ExpiredIdTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Firebase token expired. Please sign in again.")
    except firebase_auth_errors.InvalidIdTokenError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid Firebase token: {e}")
    except RuntimeError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Firebase authentication is not available. Contact administrator.")
    except Exception as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Failed to verify Firebase token: {e}")


def _extract_firebase_claims(decoded_token: dict) -> tuple[str, str, str | None, str | None, bool, str]:
    """Extract and validate claims from a decoded Firebase token."""
    email = decoded_token.get("email")
    if not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email not found in Firebase token")
    firebase_uid = decoded_token.get("uid")
    name = decoded_token.get("name")
    picture = decoded_token.get("picture")
    email_verified = decoded_token.get("email_verified", False)
    sign_in_provider = decoded_token.get("firebase", {}).get("sign_in_provider", "google")
    provider_map = {"google.com": "google", "apple.com": "apple", "microsoft.com": "microsoft", "github.com": "github"}
    auth_provider = provider_map.get(sign_in_provider, "google")
    return email, firebase_uid, name, picture, email_verified, auth_provider


async def _ensure_default_org(db: AsyncSession) -> str:
    """Ensure the default org exists; return its id."""
    from loguru import logger
    from sqlalchemy import select
    from app.db.models import Organization
    from app.config import get_settings
    cfg = get_settings()
    org_id = cfg.default_org_id
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    if result.scalar_one_or_none() is None:
        logger.info("Creating default organization")
        db.add(Organization(
            id=org_id,
            name=cfg.default_org_name,
            slug=cfg.default_org_slug,
            plan=cfg.default_org_plan,
            max_repos=cfg.default_org_max_repos,
            max_users=cfg.default_org_max_users,
        ))
        await db.flush()
    return org_id


async def _find_or_create_user(
    db: AsyncSession,
    org_id: str,
    email: str,
    firebase_uid: str,
    name: str | None,
    picture: str | None,
    email_verified: bool,
    auth_provider: str,
) -> tuple[User, bool]:
    """Return (user, is_new_user). Creates user on first login."""
    from loguru import logger
    user_repo = UserRepository(db)
    user = await _find_by_email(db, email)
    if user is None:
        user = User(
            org_id=org_id, email=email, full_name=name, role="developer",
            hashed_password="", auth_provider=auth_provider,
            firebase_uid=firebase_uid, profile_picture_url=picture,
            email_verified=email_verified, is_active=True,
        )
        db.add(user)
        await db.flush()
        logger.info(f"New user registered via {auth_provider}: {email}")
        return user, True
    # Sign-up does not verify email addresses, so a password account made for
    # this address before its owner ever used Google may have been made by
    # someone else. Google has now proven who owns it: that password stops
    # working, and the owner can add their own from Settings.
    if user.firebase_uid is None and not user.email_verified and email_verified and user.hashed_password:
        user.hashed_password = ""
        logger.warning(f"Cleared an unverified password on {email}: Google verified the address")
    if user.firebase_uid is None:
        user.firebase_uid = firebase_uid
    # Google is the source of truth for the photo: follow it when it changes.
    if picture and user.profile_picture_url != picture:
        user.profile_picture_url = picture
    if not user.email_verified and email_verified:
        user.email_verified = email_verified
    await user_repo.update_last_login(user.id)
    logger.info(f"Existing user logged in: {email}")
    return user, False


async def _store_refresh_token(user_id: str, refresh_token: str) -> None:
    """Persist refresh token in Redis."""
    from app.redis_client import get_redis
    from app.config import get_settings
    r = get_redis()
    cfg = get_settings()
    await r.setex(f"refresh:{refresh_token}", cfg.jwt_refresh_token_expire_days * 86400, user_id)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


async def _find_by_email(db: AsyncSession, email: str) -> User | None:
    """The account for an address, whatever its case: Google reports
    lower-case addresses, people type whatever they like."""
    result = await db.execute(
        select(User)
        .where(func.lower(User.email) == _normalize_email(email))
        .order_by(User.created_at)
    )
    return result.scalars().first()


def _password_matches(plain: str, hashed: str) -> bool:
    """A Google-only account has no hash; bcrypt raises on that rather than failing."""
    if not hashed:
        return False
    try:
        return verify_password(plain, hashed)
    except ValueError:
        return False


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        created_at=user.created_at,
        has_password=bool(user.hashed_password),
        auth_provider=getattr(user, "auth_provider", None),
        avatar_url=getattr(user, "profile_picture_url", None) or None,
    )


# ── Sign-up helpers ───────────────────────────────────────────────────────────


async def _rate_limit(request: Request, bucket: str, per_minute: int) -> None:
    """At most ``per_minute`` calls a minute from one address.

    Done here rather than with slowapi's decorator: its wrapper makes FastAPI
    resolve this module's postponed annotations in slowapi's namespace, which
    turns the JSON body into a missing query parameter.
    """
    from app.redis_client import get_redis

    ip = request.client.host if request.client else "unknown"
    key = f"ratelimit:auth:{bucket}:{ip}"
    r = get_redis()
    count = int(await r.incr(key))
    if count == 1:
        await r.expire(key, 60)
    if count > per_minute:
        wait = max(int(await r.ttl(key)), 1)
        raise HTTPException(
            429, "Too many attempts. Please wait a minute and try again.",
            headers={"Retry-After": str(wait)},
        )


def _require_open_registration() -> None:
    from app.config import get_settings

    if not get_settings().allow_open_registration:
        raise HTTPException(403, "Sign-ups are closed. Ask your administrator for an account.")


def _existing_account_error(existing: User) -> HTTPException:
    if not existing.hashed_password:
        return HTTPException(
            409,
            "This email already signs in with Google. Use “Continue with Google”, "
            "then add a password in Settings.",
        )
    return HTTPException(409, "An account with this email already exists. Sign in instead.")


async def _create_member(
    db: AsyncSession, *, email: str, full_name: str, password_hash: str, email_verified: bool,
) -> User:
    """A new developer in the default organisation — the only kind of account sign-up makes."""
    org_id = await _ensure_default_org(db)
    user = await UserRepository(db).create(
        org_id=org_id,
        email=email,
        hashed_password=password_hash,
        full_name=full_name.strip(),
        role="developer",
        auth_provider="email",
        email_verified=email_verified,
        is_active=True,
    )
    await db.commit()
    return user


def _signup_verifier():
    from app.config import get_settings
    from app.redis_client import get_redis
    from app.signup.verification import SignupVerifier

    cfg = get_settings()
    return SignupVerifier(
        get_redis(), cfg.secret_key.get_secret_value(),
        ttl_seconds=cfg.signup_code_ttl_seconds,
        resend_after=cfg.signup_resend_cooldown_seconds,
    )


def _signup_http(e: SignupError) -> HTTPException:
    headers = {"Retry-After": str(e.retry_after)} if e.retry_after else None
    return HTTPException(e.status, e.message, headers=headers)


async def _send_signup_code(mailer, verifier, email: str, full_name: str, code: str) -> None:
    """Email the code. If it cannot be sent, say so — and let the user try again at once."""
    from loguru import logger

    from app.mailer import EmailSendError
    from app.mailer.templates import signup_code

    try:
        await mailer.send(signup_code(email, full_name, code, max(1, verifier.ttl_seconds // 60)))
    except EmailSendError as e:
        logger.error(f"Sign-up code not sent: {e}")
        await verifier.allow_retry(email)
        raise HTTPException(502, "We couldn't send the verification email just now. Please try again.")


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
    """
    from loguru import logger
    try:
        decoded_token = _verify_firebase_token_safe(req.firebase_token)
        email, firebase_uid, name, picture, email_verified, auth_provider = _extract_firebase_claims(decoded_token)
        logger.info(f"Firebase authentication for: {email}")
        org_id = await _ensure_default_org(db)
        user, is_new_user = await _find_or_create_user(
            db, org_id, email, firebase_uid, name, picture, email_verified, auth_provider
        )
        await db.commit()
        access_token = create_access_token(user.id, user.org_id, user.role)
        refresh_token = create_refresh_token(user.id)
        await _store_refresh_token(user.id, refresh_token)
        logger.info(f"Firebase login successful for: {email}")
        return FirebaseLoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            user=_user_out(user),
            is_new_user=is_new_user,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error in firebase_login: {e}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"An unexpected error occurred during login: {e}")


@router.post("/login", response_model=LoginResponse)
async def login(
    req: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    """Authenticate with email + password. Returns JWT tokens."""
    user_repo = UserRepository(db)

    # Single-organisation setup: the address alone identifies the account.
    user = await _find_by_email(db, req.email)
    if user is not None and not user.is_active:
        user = None

    if user is not None and not user.hashed_password:
        # A Google account with no password yet. Saying so beats "incorrect
        # password" for a password that was never set.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account signs in with Google. Use “Continue with Google”, "
                   "then add a password in Settings to sign in with email too.",
        )
    if not user or not _password_matches(req.password, user.hashed_password):
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
        user=_user_out(user),
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
    request: Request,
    req: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Self-service sign-up into the default organisation, always as a developer.

    With email set up (BREVO_API_KEY + EMAIL_SENDER_ADDRESS) nothing is
    created yet: a 6-digit code is emailed and the answer is 202 — the account
    exists only once /register/verify gets the right code. Without email the
    account is created as given, its address unverified.

    An address that already has an account is refused; one belonging to a
    Google account is pointed at Google sign-in and Settings, where its owner
    can add a password from inside a signed-in session.
    ALLOW_OPEN_REGISTRATION=false closes sign-up entirely.
    """
    from app.mailer import get_mailer

    _require_open_registration()
    await _rate_limit(request, "register", 10)
    email = _normalize_email(req.email)
    existing = await _find_by_email(db, email)
    if existing:
        raise _existing_account_error(existing)

    mailer = get_mailer()
    if mailer is None:
        user = await _create_member(
            db, email=email, full_name=req.full_name,
            password_hash=hash_password(req.password), email_verified=False,
        )
        return _user_out(user)

    verifier = _signup_verifier()
    try:
        code = await verifier.start(
            email=email, full_name=req.full_name.strip(), password_hash=hash_password(req.password),
        )
    except SignupError as e:
        raise _signup_http(e)
    await _send_signup_code(mailer, verifier, email, req.full_name.strip(), code)
    return JSONResponse(status_code=202, content={
        "verification": "email_otp",
        "email": email,
        "expires_in": verifier.ttl_seconds,
        "resend_after": verifier.resend_after,
    })


@router.post("/register/verify", response_model=UserOut, status_code=201)
async def verify_signup(
    request: Request,
    req: VerifySignupRequest,
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    """Finish a sign-up with the emailed code: the account is created, its address verified."""
    _require_open_registration()
    await _rate_limit(request, "verify", 20)
    email = _normalize_email(req.email)
    verifier = _signup_verifier()
    try:
        pending = await verifier.verify(email, req.code)
    except SignupError as e:
        raise _signup_http(e)

    existing = await _find_by_email(db, email)
    if existing:  # made some other way while the code was in the inbox
        await verifier.complete(email)
        raise _existing_account_error(existing)

    user = await _create_member(
        db, email=email, full_name=pending.full_name,
        password_hash=pending.password_hash, email_verified=True,
    )
    await verifier.complete(email)
    return _user_out(user)


@router.post("/register/resend", status_code=202)
async def resend_signup_code(request: Request, req: ResendSignupRequest) -> dict:
    """A fresh code for a sign-up in progress; the previous one stops working."""
    from app.mailer import get_mailer

    _require_open_registration()
    await _rate_limit(request, "resend", 5)
    mailer = get_mailer()
    if mailer is None:
        raise HTTPException(400, "Email verification is not set up on this server.")
    email = _normalize_email(req.email)
    verifier = _signup_verifier()
    try:
        code, full_name = await verifier.resend(email)
    except SignupError as e:
        raise _signup_http(e)
    await _send_signup_code(mailer, verifier, email, full_name, code)
    return {"email": email, "expires_in": verifier.ttl_seconds, "resend_after": verifier.resend_after}


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)) -> UserOut:
    """Return the currently authenticated user."""
    return _user_out(current_user)


@router.post("/password")
async def set_password(
    req: SetPasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add a password to this account, or change it.

    A Google account has no password until its owner adds one here. Being
    signed in is the proof of ownership that an unverified sign-up form
    cannot give, which is why this is the only way to put a password on an
    existing account. Changing a password needs the current one.
    """
    if current_user.hashed_password and not _password_matches(
        req.current_password or "", current_user.hashed_password
    ):
        raise HTTPException(400, "Your current password is incorrect.")

    await db.execute(
        update(User)
        .where(User.id == current_user.id)
        .values(hashed_password=hash_password(req.new_password))
    )
    await db.commit()
    return {"has_password": True}


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
        select(APIKey).where(APIKey.user_id == current_user.id, APIKey.is_active.is_(True))
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
