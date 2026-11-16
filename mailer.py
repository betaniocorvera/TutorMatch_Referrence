# ============================================================
# mailer.py — email helpers
#
# Real delivery uses Gmail SMTP through Python's built-in
# smtplib: smtp.gmail.com, port 587, STARTTLS.
#
# In .env set:
#   MAIL_DEV_MODE=false
#   MAIL_USERNAME=your.address@gmail.com
#   MAIL_PASSWORD=your-16-character-google-app-password
#
# MAIL_DEV_MODE=true is the safe demo mode: nothing is sent,
# the message is printed and appended to outbox.log.
# If the credentials are missing or SMTP fails, mailer.py
# also falls back to outbox.log so auth never crashes.
# ============================================================

import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from flask import current_app
from flask_mail import Mail

mail = Mail()

OUTBOX_PATH = Path(__file__).resolve().parent / "outbox.log"


def _env_bool(name, default=False):
    value = os.getenv(name, str(default)).strip().lower()
    return value in ("1", "true", "yes", "on")


def init_mail(app):
    """Load SMTP settings from .env and attach Flask-Mail."""
    app.config.update(
        MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
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


def _smtp_settings():
    """Read the Gmail SMTP settings from .env."""
    raw_port = (os.getenv("MAIL_PORT") or "587").strip()
    try:
        port = int(raw_port)
    except ValueError:
        port = 587
    return {
        "server": (os.getenv("MAIL_SERVER") or "smtp.gmail.com").strip(),
        "port": port,
        "use_tls": _env_bool("MAIL_USE_TLS", True),
        "use_ssl": _env_bool("MAIL_USE_SSL", False),
        "username": (os.getenv("MAIL_USERNAME") or "").strip(),
        # Gmail shows App Passwords in 4 groups of 4; the spaces are
        # not part of the password, so remove them if they were pasted.
        "password": (os.getenv("MAIL_PASSWORD") or "").replace(" ", "").strip(),
        "sender_name": (os.getenv("MAIL_SENDER_NAME") or "TutorMatch").strip(),
    }


def _send_via_smtp(subject, recipient, body):
    """Send one plain-text message through Gmail SMTP."""
    settings = _smtp_settings()

    if not settings["username"]:
        raise RuntimeError(
            "MAIL_USERNAME is empty in .env. Put your Gmail address there."
        )
    if not settings["password"]:
        raise RuntimeError(
            "MAIL_PASSWORD is empty in .env. Put your Gmail App Password there."
        )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((settings["sender_name"], settings["username"]))
    message["To"] = recipient
    message.set_content(body)

    if settings["use_ssl"]:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            settings["server"],
            settings["port"],
            timeout=20,
            context=context,
        ) as smtp:
            smtp.login(settings["username"], settings["password"])
            smtp.send_message(message)
        return

    with smtplib.SMTP(settings["server"], settings["port"], timeout=20) as smtp:
        smtp.ehlo()
        if settings["use_tls"]:
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        smtp.login(settings["username"], settings["password"])
        smtp.send_message(message)


def send_email(subject, recipient, body):
    """
    Send one plain-text email.
    Returns True on success, False on failure. A mail failure must
    never crash login or registration.

    Real sending uses Gmail SMTP. If dev mode is on, the credentials
    are missing, or SMTP fails, the same message is written to
    outbox.log so the demo can continue.
    """
    if _env_bool("MAIL_DEV_MODE", True):
        try:
            _write_to_outbox(subject, recipient, body)
        except Exception as exc:
            # A read-only folder or locked file must not break auth.
            current_app.logger.error("Outbox write failed: %s", exc)
        return True

    try:
        _send_via_smtp(subject, recipient, body)
        return True
    except Exception as exc:
        # Do not leak SMTP details to the browser, but make the
        # terminal reason obvious for the developer.
        current_app.logger.error("Email send failed: %s", exc)
        settings = _smtp_settings()
        print(
            f"[mailer] Email to {recipient} failed via "
            f"{settings['server']}:{settings['port']}: {exc}",
            flush=True,
        )
        print("[mailer] Falling back to outbox.log.", flush=True)
        try:
            _write_to_outbox(subject, recipient, body)
        except Exception as outbox_exc:
            current_app.logger.error("Outbox write failed: %s", outbox_exc)
        return False


def send_otp_email(recipient, name, otp, expires_minutes):
    """Email the 6-digit verification code."""
    subject = "Your TutorMatch verification code"
    body = (
        f"Hi {name},\n\n"
        f"Your TutorMatch verification code is:\n\n"
        f"    {otp}\n\n"
        f"This code is valid for {expires_minutes} minutes and can be used once.\n"
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
