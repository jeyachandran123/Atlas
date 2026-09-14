"""Email verification for sign-up — a 6-digit code, checked before an account exists.

Nothing is created until the code is right. Until then the sign-up waits in
Redis for a limited time: the name, the address, the password already hashed
with bcrypt, and the code hashed with the server's secret. Neither the
password nor the code is ever stored as typed.

Limits, each against a real abuse: five wrong tries end the sign-up (a
6-digit code must not be guessable); a new code can be requested once a
minute and five times an hour per address (the form must not become a way to
flood someone's inbox).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import asdict, dataclass
from typing import Any

CODE_LENGTH = 6
MAX_ATTEMPTS = 5
MAX_SENDS_PER_HOUR = 5
_HOUR = 3600


class SignupError(Exception):
    """A sign-up step that cannot go ahead. The message is written for the user."""

    def __init__(self, message: str, *, status: int = 400, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.retry_after = retry_after


@dataclass
class PendingSignup:
    email: str
    full_name: str
    password_hash: str
    code_hash: str
    attempts: int = 0


def new_code() -> str:
    return f"{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}"


class SignupVerifier:
    def __init__(self, redis: Any, secret: str, *, ttl_seconds: int = 600, resend_after: int = 60) -> None:
        self._r = redis
        self._secret = secret.encode()
        self._ttl = ttl_seconds
        self._resend_after = resend_after

    # ── keys ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _pending_key(email: str) -> str:
        return f"signup:pending:{email}"

    @staticmethod
    def _cooldown_key(email: str) -> str:
        return f"signup:cooldown:{email}"

    @staticmethod
    def _sends_key(email: str) -> str:
        return f"signup:sends:{email}"

    def _code_hash(self, email: str, code: str) -> str:
        return hmac.new(self._secret, f"{email}:{code}".encode(), hashlib.sha256).hexdigest()

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    @property
    def resend_after(self) -> int:
        return self._resend_after

    # ── steps ────────────────────────────────────────────────────────────────

    async def start(self, *, email: str, full_name: str, password_hash: str) -> str:
        """Begin (or restart) a sign-up. Returns the code to send."""
        await self._allow_send(email)
        code = new_code()
        pending = PendingSignup(email, full_name, password_hash, self._code_hash(email, code))
        await self._r.setex(self._pending_key(email), self._ttl, json.dumps(asdict(pending)))
        return code

    async def resend(self, email: str) -> tuple[str, str]:
        """A fresh code for a sign-up in progress: (code, full name). The old code stops working."""
        pending = await self._load(email)
        if pending is None:
            raise SignupError("That sign-up has expired. Please start again.", status=410)
        await self._allow_send(email)
        code = new_code()
        pending.code_hash = self._code_hash(email, code)
        pending.attempts = 0
        await self._r.setex(self._pending_key(email), self._ttl, json.dumps(asdict(pending)))
        return code, pending.full_name

    async def verify(self, email: str, code: str) -> PendingSignup:
        """The pending sign-up, if ``code`` is right. Call ``complete`` once the account exists."""
        pending = await self._load(email)
        if pending is None:
            raise SignupError("That code has expired. Ask for a new one.", status=410)
        if pending.attempts >= MAX_ATTEMPTS:
            await self._r.delete(self._pending_key(email))
            raise SignupError("Too many wrong codes. Please start the sign-up again.", status=429)

        typed = "".join(ch for ch in code if ch.isdigit())
        if len(typed) == CODE_LENGTH and hmac.compare_digest(pending.code_hash, self._code_hash(email, typed)):
            return pending

        pending.attempts += 1
        left = MAX_ATTEMPTS - pending.attempts
        if left <= 0:
            await self._r.delete(self._pending_key(email))
            raise SignupError("Too many wrong codes. Please start the sign-up again.", status=429)
        remaining = await self._r.ttl(self._pending_key(email))
        await self._r.setex(self._pending_key(email), max(int(remaining), 1), json.dumps(asdict(pending)))
        raise SignupError(f"That code isn't right — {left} {'try' if left == 1 else 'tries'} left.", status=400)

    async def allow_retry(self, email: str) -> None:
        """A code that never left the server should not make the user wait a minute."""
        await self._r.delete(self._cooldown_key(email))

    async def complete(self, email: str) -> None:
        """The account exists: the pending sign-up and its code are spent."""
        await self._r.delete(self._pending_key(email), self._cooldown_key(email))

    # ── internals ────────────────────────────────────────────────────────────

    async def _load(self, email: str) -> PendingSignup | None:
        raw = await self._r.get(self._pending_key(email))
        if not raw:
            return None
        try:
            return PendingSignup(**json.loads(raw))
        except (TypeError, ValueError):
            await self._r.delete(self._pending_key(email))
            return None

    async def _allow_send(self, email: str) -> None:
        wait = int(await self._r.ttl(self._cooldown_key(email)))
        if wait > 0:
            raise SignupError(
                f"Please wait {wait} seconds before asking for another code.", status=429, retry_after=wait,
            )
        sends = int(await self._r.incr(self._sends_key(email)))
        if sends == 1:
            await self._r.expire(self._sends_key(email), _HOUR)
        if sends > MAX_SENDS_PER_HOUR:
            later = int(await self._r.ttl(self._sends_key(email)))
            raise SignupError(
                "Too many codes requested for this email. Please try again later.",
                status=429, retry_after=max(later, 60),
            )
        await self._r.setex(self._cooldown_key(email), self._resend_after, "1")
