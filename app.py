# ============================================================
# app.py — TutorMatch secure backend
#
# Feature 1: server foundation
#   - loads secrets from .env
#   - serves the existing index.html / styles.css / script.js
#   - adds CSRF protection, secure session settings, security headers
#   - exposes /api/csrf, /api/health, /api/auth/me
#   - provides the "flask create-admin" command
#
# Run:
#   py -m flask --app app run
#   or: py app.py
# ============================================================

import getpass
import os
import re
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, session

import db
import mailer
from security import (
    clean_name,
    clean_role,
    clear_user_session,
    csrf_token_is_valid,
    generate_otp,
    generate_reset_token,
    get_client_ip,
    get_csrf_token,
    get_user_agent,
    hash_otp,
    hash_password,
    hash_reset_token,
    is_rate_limited,
    log_event,
    login_required,
    normalize_email,
    now_utc,
    password_error,
    safe_compare,
    session_expired,
    start_user_session,
    verify_password,
)

# Load .env BEFORE reading any environment variable.
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ============================================================
# SETTINGS — change these values for your demo
# ============================================================
MAX_LOGIN_ATTEMPTS = 5          # wrong passwords before lockout
LOCKOUT_MINUTES = 15            # how long the account stays locked
OTP_EXPIRY_MINUTES = 5          # verification code lifetime
OTP_MAX_ATTEMPTS = 5            # wrong code tries before it is burned
OTP_RESEND_SECONDS = 60         # minimum wait between code requests
RESET_TOKEN_EXPIRY_MINUTES = 30 # password-reset link lifetime
SESSION_TIMEOUT_MINUTES = 30    # normal login lifetime
REMEMBER_TIMEOUT_DAYS = 7       # "Keep me signed in" lifetime

# Rate limits: (number of attempts, window in seconds)
LOGIN_RATE_LIMIT = 10
LOGIN_RATE_WINDOW_SECONDS = 60
OTP_RATE_LIMIT = 5
OTP_RATE_WINDOW_SECONDS = 600
FORGOT_RATE_LIMIT = 5
FORGOT_RATE_WINDOW_SECONDS = 900
REGISTER_RATE_LIMIT = 5
REGISTER_RATE_WINDOW_SECONDS = 3600

# ============================================================
# App configuration
# ============================================================
app = Flask(__name__)

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY is missing. Copy .env.example to .env and set a random value."
    )
if not os.getenv("OTP_PEPPER"):
    raise RuntimeError(
        "OTP_PEPPER is missing. Copy .env.example to .env and set a random value."
    )


def _env_bool(name, default=False):
    """Read a true/false value from .env."""
    value = os.getenv(name, str(default)).strip().lower()
    return value in ("1", "true", "yes", "on")


app.config.update(
    SECRET_KEY=SECRET_KEY,
    SESSION_COOKIE_NAME="tutormatch_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=_env_bool("COOKIE_SECURE", False),
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=REMEMBER_TIMEOUT_DAYS),
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,  # 1 MB request body limit
    JSON_SORT_KEYS=False,
)

mailer.init_mail(app)

# ============================================================
# Security headers
# ============================================================
# The page uses Tailwind and Lucide from CDNs and a remote video,
# so those hosts must be allowed. 'unsafe-inline' and 'unsafe-eval'
# are needed by the Tailwind Play CDN. A production build would
# compile Tailwind ahead of time and remove both.
CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
    "https://cdn.tailwindcss.com https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "media-src 'self' https://strvid.nyc3.cdn.digitaloceanspaces.com; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none';"
)


@app.after_request
def add_security_headers(response):
    """Add browser security headers to every response."""
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"

    # HSTS only makes sense over HTTPS.
    if app.config["SESSION_COOKIE_SECURE"]:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

    # Never cache API responses that may contain user data.
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"

    return response


# ============================================================
# Request checks: session expiry and CSRF
# ============================================================
@app.before_request
def check_session_and_csrf():
    """Expire old sessions, then require a CSRF token on writes."""
    if session.get("user_id") and session_expired():
        clear_user_session()

    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if not csrf_token_is_valid():
            return json_error(
                "CSRF_ERROR",
                "Your session expired. Refresh the page and try again.",
                400,
            )


# ============================================================
# Small response helpers
# ============================================================
def json_error(code, message, status, fields=None):
    """One error shape for every API response."""
    payload = {
        "code": code,
        "message": message,
    }
    if fields:
        payload["fields"] = fields
    return jsonify({"error": payload}), status


def error_response(code, message, status):
    """Return JSON for /api/ and plain text for normal pages."""
    if request.path.startswith("/api/"):
        return json_error(code, message, status)
    return message, status


def json_body():
    """Return a JSON object even when the client sends nothing."""
    return request.get_json(silent=True) or {}


def validation_error(fields, message="Please check the highlighted fields."):
    """Validation errors include the field name so the form can mark it."""
    return json_error("VALIDATION_ERROR", message, 400, fields=fields)


def public_user(user):
    """Only return fields the browser is allowed to see."""
    return {
        "id": user["id"],
        "role": user["role"],
        "name": user["name"],
        "email": user["email"],
        "emailVerified": user.get("email_verified_at") is not None,
    }


def fetch_user_by_email(email):
    return db.query_one(
        """
        SELECT id, role, name, email, password_hash, email_verified_at,
               failed_attempts, locked_until, session_version, status,
               last_login_at, last_login_ip
        FROM users
        WHERE email = %s
        """,
        (email,),
    )


def fetch_user_by_id(user_id):
    return db.query_one(
        """
        SELECT id, role, name, email, password_hash, email_verified_at,
               failed_attempts, locked_until, session_version, status,
               last_login_at, last_login_ip
        FROM users
        WHERE id = %s
        """,
        (user_id,),
    )


def normalize_otp(value):
    """Return a 6-digit code, or None."""
    value = str(value or "").strip()
    return value if re.fullmatch(r"\d{6}", value) else None


def send_verification_code(user):
    """
    Create a fresh OTP, invalidate older unused codes, and email it.
    The raw code is never stored or returned by the API.
    """
    otp = generate_otp()
    expires_at = now_utc() + timedelta(minutes=OTP_EXPIRY_MINUTES)

    db.execute(
        """
        UPDATE email_otps
        SET used_at = UTC_TIMESTAMP()
        WHERE user_id = %s AND used_at IS NULL
        """,
        (user["id"],),
    )
    db.execute(
        """
        INSERT INTO email_otps (user_id, otp_hash, expires_at, ip_address)
        VALUES (%s, %s, %s, %s)
        """,
        (user["id"], hash_otp(otp), expires_at, get_client_ip()),
    )

    sent = mailer.send_otp_email(
        user["email"],
        user["name"],
        otp,
        OTP_EXPIRY_MINUTES,
    )
    log_event(
        "otp_sent",
        user_id=user["id"],
        email_tried=user["email"],
        details="email verification code",
    )
    return bool(sent)


def send_password_reset(user):
    """
    Create a fresh single-use reset link and email it.
    The raw token is never stored or returned by the API.
    """
    token = generate_reset_token()
    expires_at = now_utc() + timedelta(minutes=RESET_TOKEN_EXPIRY_MINUTES)

    db.execute(
        """
        UPDATE password_resets
        SET used_at = UTC_TIMESTAMP()
        WHERE user_id = %s AND used_at IS NULL
        """,
        (user["id"],),
    )
    db.execute(
        """
        INSERT INTO password_resets (user_id, token_hash, expires_at, ip_address)
        VALUES (%s, %s, %s, %s)
        """,
        (user["id"], hash_reset_token(token), expires_at, get_client_ip()),
    )

    base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
    reset_url = f"{base_url}/?reset_token={token}"
    sent = mailer.send_reset_email(
        user["email"],
        user["name"],
        reset_url,
        RESET_TOKEN_EXPIRY_MINUTES,
    )
    log_event(
        "password_reset_requested",
        user_id=user["id"],
        email_tried=user["email"],
        details="password reset link",
    )
    return bool(sent)


def record_failed_login(user, email):
    """Increment the counter and lock the account after too many tries."""
    attempts = int(user.get("failed_attempts") or 0) + 1
    locked_until = None
    if attempts >= MAX_LOGIN_ATTEMPTS:
        locked_until = now_utc() + timedelta(minutes=LOCKOUT_MINUTES)

    db.execute(
        """
        UPDATE users
        SET failed_attempts = %s, locked_until = %s
        WHERE id = %s
        """,
        (attempts, locked_until, user["id"]),
    )
    log_event(
        "login_failed",
        user_id=user["id"],
        email_tried=email,
        details=f"wrong password, attempt {attempts}",
    )

    if locked_until:
        log_event(
            "account_locked",
            user_id=user["id"],
            email_tried=email,
            details=f"locked for {LOCKOUT_MINUTES} minutes",
        )
        mailer.send_security_alert(
            user["email"],
            user["name"],
            "account locked after repeated failed logins",
            get_client_ip(),
            get_user_agent(),
            now_utc().isoformat(),
        )


def clear_login_failures(user_id):
    db.execute(
        """
        UPDATE users
        SET failed_attempts = 0, locked_until = NULL
        WHERE id = %s
        """,
        (user_id,),
    )


def send_new_login_alert(user):
    """Only alert when the IP changes, so normal logins are not noisy."""
    previous_ip = user.get("last_login_ip")
    if user.get("last_login_at") and previous_ip and previous_ip != get_client_ip():
        mailer.send_security_alert(
            user["email"],
            user["name"],
            "new login from a different IP address",
            get_client_ip(),
            get_user_agent(),
            now_utc().isoformat(),
        )


def update_last_login(user):
    db.execute(
        """
        UPDATE users
        SET last_login_at = UTC_TIMESTAMP(), last_login_ip = %s
        WHERE id = %s
        """,
        (get_client_ip(), user["id"]),
    )


def start_session_for(user, remember=False):
    timeout = (
        REMEMBER_TIMEOUT_DAYS * 24 * 60
        if remember
        else SESSION_TIMEOUT_MINUTES
    )
    start_user_session(user, timeout, remember=remember)


# ============================================================
# Frontend files
# ============================================================
@app.get("/")
@app.get("/index.html")
def index():
    """Serve the existing landing page without changing its layout."""
    return send_from_directory(str(BASE_DIR), "index.html")


@app.get("/styles.css")
def styles():
    return send_from_directory(str(BASE_DIR), "styles.css")


@app.get("/script.js")
def script():
    return send_from_directory(str(BASE_DIR), "script.js")


@app.get("/dashboard.html")
@login_required
def dashboard_page():
    """The dashboard shell is only served to a logged-in session."""
    return send_from_directory(str(BASE_DIR), "dashboard.html")


@app.get("/dashboard.css")
def dashboard_styles():
    return send_from_directory(str(BASE_DIR), "dashboard.css")


@app.get("/js/<path:filename>")
def js_files(filename):
    """Serve the dashboard modules and the shared auth client."""
    return send_from_directory(str(BASE_DIR / "js"), filename)


# ============================================================
# API foundation
# ============================================================
@app.get("/api/csrf")
def csrf_token():
    """Give the page a token for its next POST request."""
    return jsonify({"csrf_token": get_csrf_token()})


@app.get("/api/health")
def health():
    """Small check that the app and MySQL are reachable."""
    if db.test_connection():
        return jsonify({"ok": True})
    return jsonify({"ok": False}), 503


@app.get("/api/auth/me")
def auth_me():
    """
    Return the logged-in user, or 401.
    The browser never stores the user object; this endpoint is the
    source of truth for the nav bar.
    """
    user_id = session.get("user_id")
    if not user_id:
        return json_error("UNAUTHORIZED", "Please log in.", 401)

    user = db.query_one(
        """
        SELECT id, role, name, email, email_verified_at, session_version
        FROM users
        WHERE id = %s AND status = 'active'
        """,
        (user_id,),
    )

    # A password change increments session_version, which logs out
    # every browser that still holds the old version.
    if not user or user["session_version"] != session.get("session_version"):
        clear_user_session()
        return json_error("UNAUTHORIZED", "Please log in again.", 401)

    return jsonify({
        "user": {
            "id": user["id"],
            "role": user["role"],
            "name": user["name"],
            "email": user["email"],
            "emailVerified": user["email_verified_at"] is not None,
        }
    })


# ============================================================
# Authentication API
# ============================================================
@app.post("/api/auth/register")
def auth_register():
    """
    Create an unverified account, then email a 6-digit code.
    No session is started until the email is verified.
    """
    data = json_body()
    email = normalize_email(data.get("email"))
    name = clean_name(data.get("name"))
    role = clean_role(data.get("role"))
    password = str(data.get("password") or "")

    if is_rate_limited(
        "registration_attempt",
        REGISTER_RATE_LIMIT,
        REGISTER_RATE_WINDOW_SECONDS,
    ):
        log_event("rate_limited", email_tried=email, details="registration")
        return json_error(
            "RATE_LIMITED",
            "Too many registration attempts. Try again later.",
            429,
        )
    log_event("registration_attempt", email_tried=email)

    fields = {}
    if not role:
        fields["role"] = "Choose Student or Tutor."
    if not name:
        fields["name"] = "Enter your full name (2-80 characters)."
    if not email:
        fields["email"] = "Enter a valid email address."
    problem = password_error(password)
    if problem:
        fields["password"] = problem
    if fields:
        return validation_error(fields)

    existing = db.query_one(
        "SELECT id FROM users WHERE email = %s",
        (email,),
    )
    if existing:
        log_event("registration_duplicate", email_tried=email)
        return json_error(
            "CONFLICT",
            "An account with this email already exists.",
            409,
        )

    try:
        user_id = db.execute(
            """
            INSERT INTO users
                (role, name, email, password_hash, email_verified_at)
            VALUES (%s, %s, %s, %s, NULL)
            """,
            (role, name, email, hash_password(password)),
        )
    except Exception as exc:
        # The unique index is the final guard against a duplicate race.
        if "Duplicate entry" in str(exc):
            return json_error(
                "CONFLICT",
                "An account with this email already exists.",
                409,
            )
        raise

    user = fetch_user_by_id(user_id)
    email_sent = send_verification_code(user)
    log_event("registration", user_id=user_id, email_tried=email, details=role)

    message = (
        "Account created. Check your email for the 6-digit verification code."
        if email_sent
        else "Account created, but the verification email could not be sent. Use Resend code."
    )
    return jsonify({
        "user": public_user(user),
        "verificationRequired": True,
        "emailSent": email_sent,
        "message": message,
    }), 201


@app.post("/api/auth/login")
def auth_login():
    """Check credentials, lockout, rate limit, and verification state."""
    data = json_body()
    email = normalize_email(data.get("email"))
    password = str(data.get("password") or "")
    remember = bool(data.get("remember"))

    if is_rate_limited(
        "login_failed",
        LOGIN_RATE_LIMIT,
        LOGIN_RATE_WINDOW_SECONDS,
    ):
        log_event("rate_limited", email_tried=email, details="login")
        return json_error(
            "RATE_LIMITED",
            "Too many login attempts. Try again in a minute.",
            429,
        )

    fields = {}
    if not email:
        fields["email"] = "Enter a valid email address."
    if not password:
        fields["password"] = "Enter your password."
    if fields:
        return validation_error(fields)

    user = fetch_user_by_email(email)
    if not user:
        log_event("login_failed", email_tried=email, details="unknown email")
        return json_error("UNAUTHORIZED", "Incorrect email or password.", 401)

    if user["status"] != "active":
        log_event(
            "login_failed",
            user_id=user["id"],
            email_tried=email,
            details="suspended account",
        )
        return json_error("FORBIDDEN", "This account is suspended.", 403)

    locked_until = user.get("locked_until")
    if locked_until and locked_until > now_utc():
        log_event(
            "login_failed",
            user_id=user["id"],
            email_tried=email,
            details="account locked",
        )
        return json_error(
            "LOCKED",
            f"Too many wrong passwords. Try again in {LOCKOUT_MINUTES} minutes.",
            423,
        )

    if not verify_password(user["password_hash"], password):
        record_failed_login(user, email)
        return json_error("UNAUTHORIZED", "Incorrect email or password.", 401)

    if not user.get("email_verified_at"):
        log_event(
            "login_unverified",
            user_id=user["id"],
            email_tried=email,
        )
        return json_error(
            "EMAIL_NOT_VERIFIED",
            "Verify your email before logging in.",
            403,
        )

    clear_login_failures(user["id"])
    send_new_login_alert(user)
    update_last_login(user)
    user = fetch_user_by_id(user["id"])
    start_session_for(user, remember)
    log_event("login_success", user_id=user["id"], email_tried=email)

    return jsonify({"user": public_user(user)})


@app.post("/api/auth/verify-email")
def auth_verify_email():
    """Validate the latest OTP, mark the email verified, and log in."""
    data = json_body()
    email = normalize_email(data.get("email"))
    otp = normalize_otp(data.get("otp"))

    fields = {}
    if not email:
        fields["email"] = "Enter a valid email address."
    if not otp:
        fields["otp"] = "Enter the 6-digit code."
    if fields:
        return validation_error(fields)

    user = fetch_user_by_email(email)
    if not user or user["status"] != "active":
        log_event(
            "otp_verify_failed",
            email_tried=email,
            details="unknown or inactive account",
        )
        return json_error("INVALID_OTP", "That code is invalid or expired.", 400)

    if user.get("email_verified_at"):
        return json_error(
            "ALREADY_VERIFIED",
            "Email already verified. Please log in.",
            409,
        )

    row = db.query_one(
        """
        SELECT id, otp_hash, expires_at, attempts
        FROM email_otps
        WHERE user_id = %s AND used_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (user["id"],),
    )
    if not row:
        log_event(
            "otp_verify_failed",
            user_id=user["id"],
            email_tried=email,
            details="no active code",
        )
        return json_error(
            "OTP_EXPIRED",
            "That code has expired. Request a new one.",
            400,
        )

    if row["expires_at"] < now_utc():
        db.execute(
            "UPDATE email_otps SET used_at = UTC_TIMESTAMP() WHERE id = %s",
            (row["id"],),
        )
        log_event(
            "otp_verify_failed",
            user_id=user["id"],
            email_tried=email,
            details="expired code",
        )
        return json_error(
            "OTP_EXPIRED",
            "That code has expired. Request a new one.",
            400,
        )

    attempts = int(row["attempts"] or 0)
    if attempts >= OTP_MAX_ATTEMPTS:
        db.execute(
            "UPDATE email_otps SET used_at = UTC_TIMESTAMP() WHERE id = %s",
            (row["id"],),
        )
        log_event(
            "otp_verify_failed",
            user_id=user["id"],
            email_tried=email,
            details="too many code attempts",
        )
        return json_error(
            "OTP_LOCKED",
            "Too many wrong codes. Request a new one.",
            400,
        )

    if not safe_compare(row["otp_hash"], hash_otp(otp)):
        attempts += 1
        used_at = now_utc() if attempts >= OTP_MAX_ATTEMPTS else None
        db.execute(
            """
            UPDATE email_otps
            SET attempts = %s, used_at = %s
            WHERE id = %s
            """,
            (attempts, used_at, row["id"]),
        )
        log_event(
            "otp_verify_failed",
            user_id=user["id"],
            email_tried=email,
            details=f"wrong code, attempt {attempts}",
        )
        return json_error("INVALID_OTP", "That code is invalid or expired.", 400)

    db.execute(
        "UPDATE email_otps SET used_at = UTC_TIMESTAMP() WHERE id = %s",
        (row["id"],),
    )
    db.execute(
        """
        UPDATE users
        SET email_verified_at = UTC_TIMESTAMP(),
            failed_attempts = 0,
            locked_until = NULL
        WHERE id = %s
        """,
        (user["id"],),
    )
    user = fetch_user_by_id(user["id"])
    start_session_for(user, False)
    log_event("email_verified", user_id=user["id"], email_tried=email)

    return jsonify({"user": public_user(user)})


@app.post("/api/auth/resend-otp")
def auth_resend_otp():
    """Send a fresh code without revealing whether the account exists."""
    data = json_body()
    email = normalize_email(data.get("email"))
    generic = jsonify({
        "message": "If that account needs verification, a new code has been sent."
    }), 202

    if is_rate_limited(
        "otp_resend_attempt",
        OTP_RATE_LIMIT,
        OTP_RATE_WINDOW_SECONDS,
    ):
        log_event("rate_limited", email_tried=email, details="otp resend")
        return json_error(
            "RATE_LIMITED",
            "Please wait before requesting another code.",
            429,
        )
    log_event("otp_resend_attempt", email_tried=email)

    if not email:
        return generic

    user = fetch_user_by_email(email)
    if (
        not user
        or user["status"] != "active"
        or user.get("email_verified_at")
    ):
        log_event("otp_resend_ignored", email_tried=email)
        return generic

    # Keep the first code valid if someone clicks Resend too quickly.
    if is_rate_limited(
        "otp_sent",
        1,
        OTP_RESEND_SECONDS,
        user_id=user["id"],
    ):
        log_event(
            "otp_resend_throttled",
            user_id=user["id"],
            email_tried=email,
        )
        return generic

    send_verification_code(user)
    return generic


@app.post("/api/auth/forgot-password")
def auth_forgot_password():
    """Always return the same response, whether the account exists or not."""
    data = json_body()
    email = normalize_email(data.get("email"))
    generic = jsonify({
        "message": "If an account exists for that email, a reset link has been sent."
    }), 202

    if is_rate_limited(
        "password_reset_attempt",
        FORGOT_RATE_LIMIT,
        FORGOT_RATE_WINDOW_SECONDS,
    ):
        log_event("rate_limited", email_tried=email, details="forgot password")
        return json_error(
            "RATE_LIMITED",
            "Please wait before requesting another reset link.",
            429,
        )
    log_event("password_reset_attempt", email_tried=email)

    if not email:
        return generic

    user = fetch_user_by_email(email)
    if not user or user["status"] != "active":
        log_event("password_reset_ignored", email_tried=email)
        return generic

    send_password_reset(user)
    return generic


@app.post("/api/auth/reset-password")
def auth_reset_password():
    """Consume a single-use reset token and replace the password hash."""
    data = json_body()
    token = str(data.get("token") or "").strip()
    password = str(data.get("password") or "")

    fields = {}
    if not token:
        fields["token"] = "This reset link is invalid."
    problem = password_error(password)
    if problem:
        fields["password"] = problem
    if fields:
        return validation_error(fields)

    row = db.query_one(
        """
        SELECT pr.id, pr.user_id, pr.expires_at, u.email, u.name, u.status
        FROM password_resets pr
        JOIN users u ON u.id = pr.user_id
        WHERE pr.token_hash = %s AND pr.used_at IS NULL
        ORDER BY pr.id DESC
        LIMIT 1
        """,
        (hash_reset_token(token),),
    )

    if not row:
        log_event("password_reset_failed", details="unknown or used token")
        return json_error(
            "INVALID_RESET_TOKEN",
            "This reset link is invalid or expired.",
            400,
        )

    if row["expires_at"] < now_utc():
        db.execute(
            "UPDATE password_resets SET used_at = UTC_TIMESTAMP() WHERE id = %s",
            (row["id"],),
        )
        log_event(
            "password_reset_failed",
            user_id=row["user_id"],
            email_tried=row["email"],
            details="expired token",
        )
        return json_error(
            "INVALID_RESET_TOKEN",
            "This reset link is invalid or expired.",
            400,
        )

    if row["status"] != "active":
        log_event(
            "password_reset_failed",
            user_id=row["user_id"],
            email_tried=row["email"],
            details="inactive account",
        )
        return json_error(
            "INVALID_RESET_TOKEN",
            "This reset link is invalid or expired.",
            400,
        )

    db.execute(
        """
        UPDATE users
        SET password_hash = %s,
            session_version = session_version + 1,
            password_changed_at = UTC_TIMESTAMP(),
            failed_attempts = 0,
            locked_until = NULL,
            email_verified_at = COALESCE(email_verified_at, UTC_TIMESTAMP())
        WHERE id = %s
        """,
        (hash_password(password), row["user_id"]),
    )
    db.execute(
        "UPDATE password_resets SET used_at = UTC_TIMESTAMP() WHERE id = %s",
        (row["id"],),
    )
    clear_user_session()
    log_event(
        "password_reset_completed",
        user_id=row["user_id"],
        email_tried=row["email"],
    )
    mailer.send_security_alert(
        row["email"],
        row["name"],
        "password changed through a reset link",
        get_client_ip(),
        get_user_agent(),
        now_utc().isoformat(),
    )

    return jsonify({
        "message": "Password updated. Please log in with your new password.",
        "email": row["email"],
    })


@app.post("/api/auth/logout")
def auth_logout():
    """Clear the server session. The CSRF token is preserved."""
    user_id = session.get("user_id")
    clear_user_session()
    if user_id:
        log_event("logout", user_id=user_id)
    return "", 204


# ============================================================
# Error handlers
# ============================================================
@app.errorhandler(400)
def handle_400(error):
    return error_response("VALIDATION_ERROR", "Please check your input.", 400)


@app.errorhandler(403)
def handle_403(error):
    return error_response("FORBIDDEN", "You do not have permission.", 403)


@app.errorhandler(404)
def handle_404(error):
    return error_response("NOT_FOUND", "Not found.", 404)


@app.errorhandler(405)
def handle_405(error):
    return error_response("METHOD_NOT_ALLOWED", "Method not allowed.", 405)


@app.errorhandler(413)
def handle_413(error):
    return error_response("TOO_LARGE", "The request is too large.", 413)


@app.errorhandler(429)
def handle_429(error):
    return error_response(
        "RATE_LIMITED",
        "Too many attempts. Please try again later.",
        429,
    )


@app.errorhandler(500)
def handle_500(error):
    app.logger.exception("Unhandled server error")
    return error_response(
        "INTERNAL",
        "Something went wrong. Please try again.",
        500,
    )


# ============================================================
# Admin creation command
# ============================================================
@app.cli.command("create-admin")
def create_admin():
    """
    Create the first admin account with a hashed password.
    Usage: py -m flask --app app create-admin
    """
    email = input("Admin email: ").strip()
    name = input("Admin name: ").strip()
    password = getpass.getpass("Admin password: ")

    normalized = normalize_email(email)
    if not normalized:
        print("Invalid email address.")
        return

    clean = clean_name(name)
    if not clean:
        print("Name must be between 2 and 80 characters.")
        return

    problem = password_error(password)
    if problem:
        print(problem)
        return

    existing = db.query_one(
        "SELECT id FROM users WHERE email = %s",
        (normalized,),
    )
    if existing:
        print("An account with that email already exists.")
        return

    user_id = db.execute(
        """
        INSERT INTO users (role, name, email, password_hash, email_verified_at)
        VALUES ('admin', %s, %s, %s, UTC_TIMESTAMP())
        """,
        (clean, normalized, hash_password(password)),
    )
    print(f"Admin created: {normalized} (id={user_id})")


# ============================================================
# Start the development server
# ============================================================
if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", "5000")),
        debug=_env_bool("FLASK_DEBUG", False),
    )
