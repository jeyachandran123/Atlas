"""
Authentication and authorisation.

Supports two auth methods:
  1. JWT Bearer tokens (web UI, IDE sessions)
  2. API keys (CLI, IDE extensions, CI/CD)

RBAC roles: admin | developer | viewer
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.db.models import User
from app.db.repositories import UserRepository
from app.shared.exceptions import ForbiddenError, UnauthorizedError

settings = get_settings()

# ── Password hashing ─────────────────────────────────────────────────────────
import bcrypt


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── API key hashing ───────────────────────────────────────────────────────────
def hash_api_key(key: str) -> str:
    """SHA256 hash of an API key. Only the hash is stored in the DB."""
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> tuple[str, str]:
    """Generate a new API key. Returns (raw_key, hash)."""
    raw = f"aic-{secrets.token_urlsafe(32)}"
    return raw, hash_api_key(raw)


def constant_time_compare(a: str, b: str) -> bool:
    """Timing-safe string comparison (prevents timing attacks)."""
    return secrets.compare_digest(a.encode(), b.encode())


# ── JWT ───────────────────────────────────────────────────────────────────────
def create_access_token(user_id: str, org_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_token_expire_minutes
    )
    payload = {
        "sub": user_id,
        "org": org_id,
        "role": role,
        "type": "access",
        "exp": expire,
    }
    return jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm="HS256",
    )


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.jwt_refresh_token_expire_days
    )
    payload = {"sub": user_id, "type": "refresh", "exp": expire}
    return jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm="HS256",
    )


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises UnauthorizedError on failure."""
    try:
        payload = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=["HS256"],
        )
        return payload
    except JWTError as e:
        raise UnauthorizedError(f"Invalid token: {e}") from e


# ── FastAPI security schemes ──────────────────────────────────────────────────
bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class CurrentUser:
    """
    Dependency that extracts and validates the current authenticated user.
    Supports both JWT Bearer tokens and API keys.
    """

    def __init__(self, required_role: Optional[str] = None) -> None:
        self.required_role = required_role

    async def __call__(
        self,
        bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
        x_api_key: Optional[str] = Security(api_key_header),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        user_repo = UserRepository(db)

        # Try JWT first
        if bearer and bearer.credentials:
            return await self._from_jwt(bearer.credentials, user_repo)

        # Try API key
        if x_api_key:
            return await self._from_api_key(x_api_key, user_repo)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide Bearer token or X-API-Key header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async def _from_jwt(self, token: str, user_repo: UserRepository) -> User:
        try:
            payload = decode_token(token)
        except UnauthorizedError as e:
            raise HTTPException(status_code=401, detail=str(e)) from e

        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")

        user = await user_repo.get_by_id(payload["sub"])
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User not found or inactive")

        if self.required_role:
            self._check_role(user, self.required_role)

        return user

    async def _from_api_key(self, raw_key: str, user_repo: UserRepository) -> User:
        from sqlalchemy import select

        from app.db.models import APIKey

        key_hash = hash_api_key(raw_key)

        # We need a session — get it from user_repo
        result = await user_repo.session.execute(
            select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active == True)  # noqa: E712
        )
        api_key = result.scalar_one_or_none()

        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")

        if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="API key expired")

        user = await user_repo.get_by_id(api_key.user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User not found or inactive")

        if self.required_role:
            self._check_role(user, self.required_role)

        return user

    @staticmethod
    def _check_role(user: User, required_role: str) -> None:
        role_levels = {"viewer": 0, "developer": 1, "admin": 2}
        user_level = role_levels.get(user.role, 0)
        required_level = role_levels.get(required_role, 0)
        if user_level < required_level:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{required_role}' required. You have '{user.role}'.",
            )


# Convenience dependency instances
get_current_user = CurrentUser()
require_developer = CurrentUser(required_role="developer")
require_admin = CurrentUser(required_role="admin")
