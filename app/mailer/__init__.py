"""Outgoing email. One provider (Brevo), one kind of message so far: sign-up codes."""

from app.mailer.brevo import BrevoMailer, EmailMessage, EmailSendError, get_mailer

__all__ = ["BrevoMailer", "EmailMessage", "EmailSendError", "get_mailer"]
