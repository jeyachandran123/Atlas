"""The emails themselves — plain text and HTML, written together so they say the same thing."""

from __future__ import annotations

from html import escape

from app.mailer.brevo import EmailMessage


def signup_code(to_email: str, name: str | None, code: str, minutes: int) -> EmailMessage:
    """The 6-digit code that confirms an address before its account is created."""
    first = (name or "").strip().split(" ")[0]
    greeting = f"Hi {first}," if first else "Hi,"
    subject = f"{code} is your UnityWorks verification code"

    text = (
        f"{greeting}\n\n"
        f"Your UnityWorks verification code is {code}\n\n"
        f"Enter it on the sign-up page to finish creating your account. "
        f"It expires in {minutes} minutes.\n\n"
        "If you didn't try to create a UnityWorks account, you can ignore this email — "
        "no account is made without this code.\n"
    )

    spaced = " ".join(code)
    html = f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f4f4f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;padding:32px 12px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background:#ffffff;border-radius:16px;border:1px solid #e6e6ef;">
        <tr><td style="padding:28px 32px 8px;">
          <div style="display:inline-block;width:36px;height:36px;border-radius:10px;background:linear-gradient(145deg,#6366f1,#6d28d9);"></div>
          <p style="margin:14px 0 0;font-size:15px;font-weight:600;color:#111827;">UnityWorks</p>
        </td></tr>
        <tr><td style="padding:12px 32px 0;">
          <p style="margin:0 0 12px;font-size:14px;color:#374151;">{escape(greeting)}</p>
          <p style="margin:0 0 20px;font-size:14px;line-height:1.6;color:#374151;">
            Enter this code on the sign-up page to finish creating your account.
          </p>
          <div style="text-align:center;margin:0 0 20px;padding:18px 12px;border-radius:12px;background:#f5f5ff;border:1px solid #e0e0fb;">
            <span style="font-size:30px;font-weight:700;letter-spacing:6px;color:#4f46e5;font-family:'SFMono-Regular',Consolas,monospace;">{escape(spaced)}</span>
          </div>
          <p style="margin:0 0 24px;font-size:13px;color:#6b7280;">This code expires in {minutes} minutes.</p>
        </td></tr>
        <tr><td style="padding:16px 32px 28px;border-top:1px solid #eeeef4;">
          <p style="margin:0;font-size:12px;line-height:1.6;color:#9ca3af;">
            If you didn't try to create a UnityWorks account, you can ignore this email —
            no account is made without this code.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    return EmailMessage(to_email=to_email, to_name=first or None, subject=subject, html=html, text=text)
