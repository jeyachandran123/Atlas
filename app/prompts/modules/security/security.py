"""
Security prompt modules.
"""

from __future__ import annotations

OWASP = """\
OWASP Top 10 awareness: injection (SQL, NoSQL, command), broken auth, \
sensitive data exposure, XXE, broken access control, \
security misconfiguration, XSS, insecure deserialization, \
vulnerable components, and insufficient logging."""

AUTH_SECURITY = """\
Authentication security: bcrypt/Argon2 for passwords, \
JWT best practices (short expiry, rotation, revocation), \
MFA implementation, session fixation prevention, \
and brute-force protection (rate limiting + lockout)."""

API_SECURITY = """\
API security: input validation at every boundary, \
parameterized queries (never string concatenation), \
CORS configuration, rate limiting, \
API key rotation, and request signing."""

SECURE_CODING = """\
Secure coding: principle of least privilege, \
defense in depth, fail securely (deny by default), \
never trust user input, sanitize before output, \
and audit logging for all sensitive operations."""
