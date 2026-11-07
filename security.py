# ============================================================
# security.py — small, readable security helpers
#
# This file contains the reusable pieces:
#   - input validation
#   - password hashing
#   - OTP and reset-token generation/hashing
#   - CSRF tokens
#   - session helpers
#   - role decorators
#   - security event logging
#   - per-IP rate limiting
# ============================================================

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from email_validator import EmailNotValidError, validate_email
from flask import jsonify, redirect, request, session
from werkzeug.security import check_password_hash, generate_password_hash

import db

# Password policy. Keep this in sync with the frontend hint:
# "Use 8+ characters with letters and numbers."
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128

# OTP length. 6 digits = one million possible codes.
OTP_LENGTH = 6


# ------------------------------------------------------------
# Time and request context
# ------------------------------------------------------------
def now_utc():
    """Return a naive UTC datetime for MySQL DATETIME columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_client_ip():
    """Best-effort client IP. Do not trust X-Forwarded-For here."""
    if request.remote_addr:
        return request.remote_addr[:45]
    return "0.0.0.0"


def get_user_agent():
    """Browser string, shortened to fit the database column."""
    return (request.headers.get("User-Agent") or "")[:255]


# ------------------------------------------------------------
# Input validation
# ------------------------------------------------------------
def normalize_email(value):
    """
    Return a lowercase, validated email, or None.
    check_deliverability=False keeps the demo working offline.
    """
    value = (value or "").strip()
    if not value or len(value) > 254:
        return None
    try:
        # test_environment=True allows demo addresses like ana@example.test.
        # Set it to False when you use real email domains in production.
        result = validate_email(
            value,
            check_deliverability=False,
            test_environment=True,
        )
        return result.normalized.lower()
    except EmailNotValidError:
        return None


def password_error(password):
    """
    Return an error message, or None when the password is acceptable.
    The frontend also checks this, but the server must never trust it.
    """
    password = password or ""
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Use at least {PASSWORD_MIN_LENGTH} characters."
    if len(password) > PASSWORD_MAX_LENGTH:
        return f"Use no more than {PASSWORD_MAX_LENGTH} characters."
    if not re.search(r"[A-Za-z]", password):
        return "Include at least one letter."
    if not re.search(r"\d", password):
        return "Include at least one number."
    return None


def clean_name(value):
    """Return a trimmed name between 2 and 80 characters, or None."""
    value = re.sub(r"\s+", " ", (value or "").strip())
    if len(value) < 2 or len(value) > 80:
        return None
    return value


def clean_role(value):
    """Only student and tutor can self-register. Admin is CLI-only."""
    return value if value in ("student", "tutor") else None


# ------------------------------------------------------------
# Password hashing
# ------------------------------------------------------------
def hash_password(password):
    """Werkzeug's default strong hash (scrypt). Never store the raw value."""
    return generate_password_hash(password)


def verify_password(stored_hash, password):
    """Constant-time password check through Werkzeug."""
    return check_password_hash(stored_hash, password)


# ------------------------------------------------------------
# OTP and reset tokens
# ------------------------------------------------------------
def generate_otp():
    """Generate a cryptographically secure 6-digit code."""
    return str(secrets.randbelow(10 ** OTP_LENGTH)).zfill(OTP_LENGTH)


def hash_otp(otp):
    """
    Hash an OTP with HMAC-SHA256 and a secret pepper.
    A plain SHA-256 of a 6-digit code is easy to brute-force, so the
    pepper from .env makes an offline attack much harder.
    """
    pepper = os.getenv("OTP_PEPPER", "")
    if not pepper:
        raise RuntimeError("OTP_PEPPER is missing from .env")
    return hmac.new(
        pepper.encode("utf-8"),
        otp.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def generate_reset_token():
    """High-entropy token for the password-reset link."""
    return secrets.token_urlsafe(32)


def hash_reset_token(token):
    """SHA-256 is enough for a high-entropy random token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def safe_compare(left, right):
    """Constant-time comparison for tokens and hashes."""
    if not left or not right:
        return False
    return hmac.compare_digest(str(left), str(right))


# ------------------------------------------------------------
# CSRF protection
# ------------------------------------------------------------
CSRF_SESSION_KEY = "csrf_token"


def get_csrf_token():
    """Return the session's CSRF token, creating one if needed."""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def csrf_token_is_valid():
    """
    Accept the token from the X-CSRFToken header, a form field,
    or a JSON body. The token must match the one in the session.
    """
    sent = request.headers.get("X-CSRFToken")
    if not sent:
        sent = request.form.get("csrf_token")
    if not sent:
        body = request.get_json(silent=True) or {}
        sent = body.get("csrf_token")
    expected = session.get(CSRF_SESSION_KEY)
    return safe_compare(expected, sent)


# ------------------------------------------------------------
# Session helpers
# ------------------------------------------------------------
def start_user_session(user, timeout_minutes, remember=False):
    """
    Start a fresh session after login.
    session.clear() prevents session fixation. The CSRF token is
    preserved so the open page can keep making requests.
    """
    csrf = session.get(CSRF_SESSION_KEY)
    session.clear()
    if csrf:
        session[CSRF_SESSION_KEY] = csrf

    session["user_id"] = user["id"]
    session["role"] = user["role"]
    session["name"] = user["name"]
    session["session_version"] = user["session_version"]
    session["expires_at"] = (
        now_utc() + timedelta(minutes=timeout_minutes)
    ).isoformat()
    session.permanent = bool(remember)
    session.modified = True


def clear_user_session():
    """Remove login data but keep the CSRF token for the next form."""
    csrf = session.get(CSRF_SESSION_KEY)
    session.clear()
    if csrf:
        session[CSRF_SESSION_KEY] = csrf


def session_expired():
    """True when the server-side expiry time has passed."""
    expires_at = session.get("expires_at")
    if not expires_at:
        return False
    try:
        return now_utc() > datetime.fromisoformat(expires_at)
    except ValueError:
        return True


def wants_json():
    """API routes return JSON; page routes can redirect or show HTML."""
    return request.path.startswith("/api/")


def login_required(view):
    """Protect routes that need a logged-in, current session."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            if wants_json():
                return jsonify({
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Please log in.",
                    }
                }), 401
            return redirect("/?login=1")

        # A password reset increments session_version. Reject older
        # cookies even if they still contain a user_id.
        user = db.query_one(
            "SELECT session_version, status FROM users WHERE id = %s",
            (user_id,),
        )
        if (
            not user
            or user["status"] != "active"
            or user["session_version"] != session.get("session_version")
        ):
            clear_user_session()
            if wants_json():
                return jsonify({
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Your session expired. Please log in again.",
                    }
                }), 401
            return redirect("/?login=1")

        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    """
    Protect admin pages. The role is checked in the database too,
    so an old session cannot keep admin access after a role change.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            if wants_json():
                return jsonify({
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Please log in.",
                    }
                }), 401
            return redirect("/?login=1")

        user = db.query_one(
            "SELECT role, status, session_version FROM users WHERE id = %s",
            (user_id,),
        )
        if (
            not user
            or user["status"] != "active"
            or user["role"] != "admin"
            or user["session_version"] != session.get("session_version")
        ):
            clear_user_session()
            if wants_json():
                return jsonify({
                    "error": {
                        "code": "FORBIDDEN",
                        "message": "You do not have permission.",
                    }
                }), 403
            return "Forbidden", 403

        return view(*args, **kwargs)
    return wrapped


# ------------------------------------------------------------
# Security event logging
# ------------------------------------------------------------
def log_event(event_type, user_id=None, email_tried=None, details=None):
    """
    Append one row to security_events. Logging must never crash the
    login flow, so database errors are printed and swallowed.
    """
    try:
        if email_tried:
            email_tried = email_tried.strip().lower()[:254]
        db.execute(
            """
            INSERT INTO security_events
                (event_type, user_id, email_tried, ip_address, user_agent, details)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                event_type[:40],
                user_id,
                email_tried,
                get_client_ip(),
                get_user_agent(),
                (details or "")[:255],
            ),
        )
    except Exception as exc:
        print(f"[security] could not log event {event_type}: {exc}")


# ------------------------------------------------------------
# Rate limiting
# ------------------------------------------------------------
def is_rate_limited(action, limit, window_seconds, user_id=None):
    """
    Count recent security_events rows for this action.
    By default the count is per IP. Pass user_id to count per account.
    Call this BEFORE log_event() so the current attempt is not counted.
    """
    since = now_utc() - timedelta(seconds=window_seconds)
    if user_id is not None:
        row = db.query_one(
            """
            SELECT COUNT(*) AS total
            FROM security_events
            WHERE event_type = %s AND user_id = %s AND created_at >= %s
            """,
            (action, user_id, since),
        )
    else:
        row = db.query_one(
            """
            SELECT COUNT(*) AS total
            FROM security_events
            WHERE event_type = %s AND ip_address = %s AND created_at >= %s
            """,
            (action, get_client_ip(), since),
        )
    return bool(row and row["total"] >= limit)
