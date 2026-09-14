"""Transactional email through Brevo's HTTP API.

One call — ``POST /v3/smtp/email`` — is all the app needs: a message to one
person. Brevo delivers worldwide. Whether a message reaches the inbox rather
than spam depends on the sender, which must be verified in Brevo: a domain
authenticated with SPF and DKIM is best; a single verified address works for
testing.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from loguru import logger

BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"


class EmailSendError(Exception):
    """The message was not accepted for delivery. The text is safe to log."""


@dataclass(frozen=True)
class EmailMessage:
    to_email: str
    to_name: str | None
    subject: str
    html: str
    text: str


def mask_email(email: str) -> str:
    """``c***@gmail.com`` — enough to trace a delivery in the logs, no more."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


class BrevoMailer:
    def __init__(
        self,
        api_key: str,
        sender_email: str,
        sender_name: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._api_key = api_key
        self._sender = {"email": sender_email, "name": sender_name}
        self._client = client
        self._timeout = timeout

    async def send(self, message: EmailMessage) -> str:
        """Hand one message to Brevo. Returns its message id; raises EmailSendError."""
        recipient = {"email": message.to_email}
        if message.to_name:
            recipient["name"] = message.to_name
        payload = {
            "sender": self._sender,
            "to": [recipient],
            "subject": message.subject,
            "htmlContent": message.html,
            "textContent": message.text,
        }
        headers = {"api-key": self._api_key, "accept": "application/json"}
        try:
            if self._client is not None:
                resp = await self._client.post(BREVO_SEND_URL, json=payload, headers=headers, timeout=self._timeout)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(BREVO_SEND_URL, json=payload, headers=headers)
        except httpx.HTTPError as e:
            raise EmailSendError(f"Could not reach Brevo ({type(e).__name__})") from e

        body: dict = {}
        try:
            parsed = resp.json()
            body = parsed if isinstance(parsed, dict) else {}
        except ValueError:
            pass
        if resp.status_code >= 300:
            detail = str(body.get("message") or "").strip()
            raise EmailSendError(
                f"Brevo refused the message (HTTP {resp.status_code})" + (f": {detail}" if detail else "")
            )
        message_id = str(body.get("messageId") or "")
        logger.info(f"Email sent via Brevo to {mask_email(message.to_email)} ({message_id or 'no id'})")
        return message_id


def get_mailer() -> BrevoMailer | None:
    """The configured mailer, or None when email is not set up (no key or no sender)."""
    from app.config import get_settings

    cfg = get_settings()
    key = cfg.brevo_api_key.get_secret_value().strip()
    sender = cfg.email_sender_address.strip()
    if not key or not sender:
        return None
    return BrevoMailer(key, sender, cfg.email_sender_name)
