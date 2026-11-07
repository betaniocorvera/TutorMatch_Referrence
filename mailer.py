# ============================================================
# mailer.py — email helpers
#
# MAIL_DEV_MODE=true is the safe demo mode:
#   - nothing is sent over the network
#   - the message is printed in the terminal
#   - the message is appended to outbox.log
#
# Set MAIL_DEV_MODE=false and fill in the SMTP values in .env
# to send real email with Flask-Mail.
# ============================================================

import os
from datetime import datetime
from pathlib import Path

from flask import current_app
from flask_mail import Mail, Message

mail = Mail()

OUTBOX_PATH = Path(__file__).resolve().parent / "outbox.log"


def _env_bool(name, default=False):
    value = os.getenv(name, str(default)).strip().lower()
    return value in ("1", "true", "yes", "on")


def init_mail(app):
    """Load SMTP settings from .env and attach Flask-Mail."""
    app.config.update(
        MAIL_SERVER=os.getenv("MAIL_SERVER", ""),
        MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
        MAIL_USE_TLS=_env_bool("MAIL_USE_TLS", True),
        MAIL_USE_SSL=_env_bool("MAIL_USE_SSL", False),
        MAIL_USERNAME=os.getenv("MAIL_USERNAME") or None,
        MAIL_PASSWORD=os.getenv("MAIL_PASSWORD") or None,
        MAIL_DEFAULT_SENDER=os.getenv(
            "MAIL_DEFAULT_SENDER",
            "TutorMatch <no-reply@example.test>",
        ),
    )
    mail.init_app(app)


def _write_to_outbox(subject, recipient, body):
    """Print and save a readable copy for the live demo."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    block = (
        "\n" + "=" * 70 + "\n"
        f"[{stamp}] TO: {recipient}\n"
        f"SUBJECT: {subject}\n"
        + "-" * 70 + "\n"
        f"{body}\n"
        + "=" * 70 + "\n"
    )
    print(block)
    with OUTBOX_PATH.open("a", encoding="utf-8") as file:
        file.write(block)


def send_email(subject, recipient, body):
    """
    Send one plain-text email.
    Returns True on success, False on failure. A mail failure must
    never crash login or registration.
    """
    if _env_bool("MAIL_DEV_MODE", True):
        try:
            _write_to_outbox(subject, recipient, body)
        except Exception as exc:
            # A read-only folder or locked file must not break auth.
            current_app.logger.error("Outbox write failed: %s", exc)
        return True

    try:
        message = Message(
            subject=subject,
            recipients=[recipient],
            body=body,
        )
        mail.send(message)
        return True
    except Exception as exc:
        # Do not leak SMTP details to the browser.
        current_app.logger.error("Email send failed: %s", exc)
        return False


def send_otp_email(recipient, name, otp, expires_minutes):
    """Email the 6-digit verification code."""
    subject = "TutorMatch: your verification code"
    body = (
        f"Hi {name},\n\n"
        f"Your TutorMatch verification code is:\n\n"
        f"    {otp}\n\n"
        f"This code expires in {expires_minutes} minutes and can be used once.\n"
        f"If you did not create a TutorMatch account, you can ignore this email.\n"
    )
    return send_email(subject, recipient, body)


def send_reset_email(recipient, name, reset_url, expires_minutes):
    """Email the single-use password-reset link."""
    subject = "TutorMatch: reset your password"
    body = (
        f"Hi {name},\n\n"
        f"Use this link to choose a new password:\n\n"
        f"{reset_url}\n\n"
        f"The link expires in {expires_minutes} minutes and can be used once.\n"
        f"If you did not request this, ignore this email. Your password is unchanged.\n"
    )
    return send_email(subject, recipient, body)


def send_security_alert(recipient, name, event_label, ip_address, user_agent, when):
    """Send one of the security alerts: lockout, new login, password change."""
    subject = f"TutorMatch security alert: {event_label}"
    body = (
        f"Hi {name},\n\n"
        f"Security event: {event_label}\n"
        f"Time (UTC): {when}\n"
        f"IP address: {ip_address}\n"
        f"Browser: {user_agent or 'Unknown'}\n\n"
        f"If this was you, no action is needed.\n"
        f"If this was not you, reset your password immediately and contact support.\n"
    )
    return send_email(subject, recipient, body)
