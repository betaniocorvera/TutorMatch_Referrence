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
import json
import os
import re
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request, send_from_directory, session

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

# Profile / onboarding vocabulary. Keep the frontend lists in sync.
PROFILE_LEVELS = ("elementary", "high_school", "senior_high", "college", "adult")
PROFILE_FORMATS = ("online", "in_person", "both")
PROFILE_STATUSES = ("active", "away", "accepting", "not_accepting")
STYLE_TAGS = (
    "visual",
    "step_by_step",
    "discussion",
    "practice",
    "real_world",
    "structured",
)
GOAL_TAGS = (
    "exam_prep",
    "conceptual",
    "confidence",
    "homework",
    "skill_building",
    "grades",
)
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_INDEX = {day: index + 1 for index, day in enumerate(DAYS)}
PHOTO_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
MAX_PHOTO_BYTES = 1 * 1024 * 1024

REQUIRED_FIELD_MESSAGES = {
    "bio": "Write a short bio (at least 10 characters).",
    "subjects": "Add at least one subject.",
    "availability": "Add at least one availability slot.",
    "rate": "Add your hourly rate.",
    "budget": "Add your budget range.",
    "format": "Choose a session format.",
    "area": "Add your barangay.",
}

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
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,  # 2 MB (1 MB photo + form overhead)
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


def public_user(user, profile_state=None):
    """Only return fields the browser is allowed to see."""
    payload = {
        "id": user["id"],
        "role": user["role"],
        "name": user["name"],
        "email": user["email"],
        "emailVerified": user.get("email_verified_at") is not None,
    }
    if profile_state is not None:
        payload["onboardingRequired"] = profile_state["onboardingRequired"]
        payload["profileComplete"] = profile_state["requiredComplete"]
        payload["completeness"] = profile_state["completeness"]
    return payload


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
# Profile helpers
# ============================================================
def _json_list(value):
    """Read a JSON list from MySQL, tolerating NULL and old rows."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _time_text(value):
    """Convert a MySQL TIME value to HH:MM."""
    if value is None:
        return None
    if isinstance(value, timedelta):
        total = int(value.total_seconds())
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}"
    return str(value)[:5]


def _date_text(value):
    """Convert a DATE value to YYYY-MM-DD."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _datetime_text(value):
    """Convert a DATETIME value to an ISO string."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat() + "Z"
    return str(value)


def profile_row_to_dict(row, user):
    """Normalize a profiles row into the shape used by completeness."""
    return {
        "id": row["id"] if row else None,
        "userId": user["id"],
        "role": user["role"],
        "name": user["name"],
        "email": user["email"],
        "photo_url": row["photo_url"] if row else None,
        "bio": row["bio"] if row else None,
        "birthdate": row["birthdate"] if row else None,
        "headline": row["headline"] if row else None,
        "status": row["status"] if row else "active",
        "format": row["format"] if row else None,
        "area_barangay": row["area_barangay"] if row else None,
        "area_city": row["area_city"] if row else "Cabadbaran City",
        "rate_centavos": row["rate_centavos"] if row else None,
        "budget_min_centavos": row["budget_min_centavos"] if row else None,
        "budget_max_centavos": row["budget_max_centavos"] if row else None,
        "currency": row["currency"] if row else "PHP",
        "style_tags": _json_list(row["style_tags"]) if row else [],
        "goal_tags": _json_list(row["goal_tags"]) if row else [],
        "completeness": row["completeness"] if row else 0,
        "onboarding_step": row["onboarding_step"] if row else 1,
        "onboarding_completed_at": row["onboarding_completed_at"] if row else None,
        "verified_at": row["verified_at"] if row else None,
        "created_at": row["created_at"] if row else None,
        "updated_at": row["updated_at"] if row else None,
    }


def compute_completeness(profile, subjects, availability):
    """
    Return (percent, required_complete, missing).

    Weights follow docs/03-data-model.md. A complete but unverified
    profile can reach 95%; verification is the final optional 5%.
    """
    missing = []
    percent = 0

    bio = str(profile.get("bio") or "").strip()
    if len(bio) >= 10:
        percent += 10
    else:
        missing.append({
            "field": "bio",
            "label": "Write a short bio (at least 10 characters)",
            "weight": 10,
        })

    if profile.get("photo_url"):
        percent += 5
    else:
        missing.append({
            "field": "photoUrl",
            "label": "Add a profile photo (optional)",
            "weight": 5,
        })

    if subjects:
        percent += 20
    else:
        missing.append({
            "field": "subjects",
            "label": "Add at least one subject",
            "weight": 20,
        })

    if profile.get("goal_tags"):
        percent += 10
    else:
        missing.append({
            "field": "goalTags",
            "label": "Choose a learning goal",
            "weight": 10,
        })

    if profile.get("style_tags"):
        percent += 5
    else:
        missing.append({
            "field": "styleTags",
            "label": "Choose a teaching or learning style",
            "weight": 5,
        })

    if availability:
        percent += 20
    else:
        missing.append({
            "field": "availability",
            "label": "Add at least one availability slot",
            "weight": 20,
        })

    if profile.get("role") == "tutor":
        has_price = profile.get("rate_centavos") is not None
        price_field = "rate"
        price_label = "Add your hourly rate"
    else:
        has_price = (
            profile.get("budget_min_centavos") is not None
            and profile.get("budget_max_centavos") is not None
        )
        price_field = "budget"
        price_label = "Add your budget range"

    if has_price:
        percent += 10
    else:
        missing.append({
            "field": price_field,
            "label": price_label,
            "weight": 10,
        })

    if profile.get("format"):
        percent += 5
    else:
        missing.append({
            "field": "format",
            "label": "Choose a session format",
            "weight": 5,
        })

    if str(profile.get("area_barangay") or "").strip():
        percent += 10
    else:
        missing.append({
            "field": "area",
            "label": "Add your barangay",
            "weight": 10,
        })

    if profile.get("verified_at"):
        percent += 5
    else:
        missing.append({
            "field": "verification",
            "label": "Verify your tutor profile (optional)",
            "weight": 5,
        })

    required_complete = bool(
        len(bio) >= 10
        and subjects
        and availability
        and has_price
        and profile.get("format")
        and str(profile.get("area_barangay") or "").strip()
    )
    return min(100, percent), required_complete, missing


def get_profile_payload(user_id):
    """Return the private profile shape used by onboarding and the dashboard."""
    user = fetch_user_by_id(user_id)
    if not user:
        return None

    row = db.query_one("SELECT * FROM profiles WHERE user_id = %s", (user_id,))
    subjects = []
    availability = []
    if row:
        subjects = db.query_all(
            """
            SELECT ps.subject_id, ps.level, ps.kind, s.name, s.category
            FROM profile_subjects ps
            JOIN subjects s ON s.id = ps.subject_id
            WHERE ps.profile_id = %s
            ORDER BY s.category, s.name
            """,
            (row["id"],),
        )
        availability = db.query_all(
            """
            SELECT day_of_week, start_time, end_time, timezone
            FROM availability_slots
            WHERE profile_id = %s
            ORDER BY day_of_week, start_time
            """,
            (row["id"],),
        )

    profile = profile_row_to_dict(row, user)
    percent, required_complete, missing = compute_completeness(
        profile,
        subjects,
        availability,
    )

    return {
        "id": profile["id"],
        "userId": user["id"],
        "role": user["role"],
        "name": user["name"],
        "email": user["email"],
        "photoUrl": profile["photo_url"],
        "bio": profile["bio"],
        "birthdate": _date_text(profile["birthdate"]),
        "headline": profile["headline"],
        "status": profile["status"],
        "format": profile["format"],
        "area": {
            "barangay": profile["area_barangay"],
            "city": profile["area_city"],
        },
        "subjects": [
            {
                "id": subject["subject_id"],
                "name": subject["name"],
                "level": subject["level"],
                "kind": subject["kind"],
            }
            for subject in subjects
        ],
        "styleTags": profile["style_tags"],
        "goalTags": profile["goal_tags"],
        "rateCentavos": profile["rate_centavos"],
        "budgetMinCentavos": profile["budget_min_centavos"],
        "budgetMaxCentavos": profile["budget_max_centavos"],
        "currency": profile["currency"],
        "availability": [
            {
                "day": DAYS[slot["day_of_week"] - 1],
                "start": _time_text(slot["start_time"]),
                "end": _time_text(slot["end_time"]),
            }
            for slot in availability
            if 1 <= slot["day_of_week"] <= 7
        ],
        "completeness": percent,
        "requiredComplete": required_complete,
        "missing": missing,
        "onboardingStep": profile["onboarding_step"],
        "onboardingCompleted": profile["onboarding_completed_at"] is not None,
        "verified": profile["verified_at"] is not None,
        "createdAt": _datetime_text(profile["created_at"]),
        "updatedAt": _datetime_text(profile["updated_at"]),
    }


def get_onboarding_state(user_id):
    """Small state object used by auth responses and page redirects."""
    profile = get_profile_payload(user_id)
    if not profile:
        return {
            "onboardingRequired": True,
            "requiredComplete": False,
            "onboardingCompleted": False,
            "completeness": 0,
        }
    return {
        "onboardingRequired": (
            not profile["requiredComplete"]
            or not profile["onboardingCompleted"]
        ),
        "requiredComplete": profile["requiredComplete"],
        "onboardingCompleted": profile["onboardingCompleted"],
        "completeness": profile["completeness"],
    }


def parse_money(value, field, fields):
    """Parse centavos from an integer. Empty values clear the field."""
    if value is None or value == "":
        return None
    try:
        amount = int(value)
    except (TypeError, ValueError):
        fields[field] = "Enter a whole number."
        return None
    if amount < 0 or amount > 1000000:
        fields[field] = "Enter an amount between 0 and 10,000 PHP."
        return None
    return amount


def parse_tags(value, allowed, field, fields):
    """Validate a small multi-select list."""
    if value is None:
        return []
    if not isinstance(value, list):
        fields[field] = "Choose valid options."
        return []
    result = []
    for item in value:
        tag = str(item or "").strip()
        if tag not in allowed:
            fields[field] = "Choose valid options."
            return []
        if tag not in result:
            result.append(tag)
    if len(result) > 6:
        fields[field] = "Choose up to 6 options."
        return []
    return result


def parse_subjects(value, role, fields):
    """Validate subject ids and levels, then attach teach/need."""
    if not isinstance(value, list):
        fields["subjects"] = "Choose at least one subject."
        return []
    if len(value) > 8:
        fields["subjects"] = "Choose up to 8 subjects."
        return []

    valid_ids = {
        row["id"] for row in db.query_all("SELECT id FROM subjects")
    }
    result = []
    seen = set()
    kind = "teach" if role == "tutor" else "need"

    for item in value:
        if not isinstance(item, dict):
            fields["subjects"] = "Choose valid subjects."
            return []
        subject_id = str(item.get("id") or "").strip()
        level = str(item.get("level") or "").strip()
        if subject_id not in valid_ids:
            fields["subjects"] = "Choose a valid subject."
            return []
        if level not in PROFILE_LEVELS:
            fields["subjects"] = "Choose a level for each subject."
            return []
        key = (subject_id, level)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "id": subject_id,
            "level": level,
            "kind": kind,
        })
    return result


def parse_availability(value, fields):
    """Validate weekly availability in the API's day/start/end shape."""
    if not isinstance(value, list):
        fields["availability"] = "Add at least one availability slot."
        return []
    if len(value) > 21:
        fields["availability"] = "Choose up to 21 slots."
        return []

    result = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            fields["availability"] = "Choose valid availability slots."
            return []
        day = str(item.get("day") or "").strip().lower()
        start = str(item.get("start") or "").strip()
        end = str(item.get("end") or "").strip()
        if day not in DAY_INDEX:
            fields["availability"] = "Choose a valid day."
            return []
        try:
            start_time = datetime.strptime(start, "%H:%M").time()
            end_time = datetime.strptime(end, "%H:%M").time()
        except ValueError:
            fields["availability"] = "Choose valid start and end times."
            return []
        if start_time >= end_time:
            fields["availability"] = "End time must be after start time."
            return []
        key = (day, start, end)
        if key in seen:
            continue
        seen.add(key)
        result.append({
            "day": day,
            "start": start,
            "end": end,
        })
    return result


def looks_like_image(data, mime):
    """Check magic bytes instead of trusting the browser's MIME type."""
    if mime == "image/jpeg":
        return data[:3] == b"\xff\xd8\xff"
    if mime == "image/png":
        return data[:8] == b"\x89PNG\r\n\x1a\n"
    if mime == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


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
    """The dashboard is only served after onboarding is finished."""
    state = get_onboarding_state(session["user_id"])
    if not state["onboardingCompleted"]:
        return redirect("/onboarding")
    return send_from_directory(str(BASE_DIR), "dashboard.html")


@app.get("/onboarding")
@app.get("/onboarding.html")
@login_required
def onboarding_page():
    """Serve the profile wizard. Completed users can edit with ?edit=1."""
    state = get_onboarding_state(session["user_id"])
    if state["onboardingCompleted"] and not request.args.get("edit"):
        return redirect("/dashboard.html#search")
    return send_from_directory(str(BASE_DIR), "onboarding.html")


@app.get("/dashboard.css")
def dashboard_styles():
    return send_from_directory(str(BASE_DIR), "dashboard.css")


@app.get("/onboarding.css")
def onboarding_styles():
    return send_from_directory(str(BASE_DIR), "onboarding.css")


@app.get("/js/<path:filename>")
def js_files(filename):
    """Serve the dashboard modules and the shared auth client."""
    return send_from_directory(str(BASE_DIR / "js"), filename)


@app.get("/videos/<path:filename>")
def video_files(filename):
    """Serve local videos such as the TutorMatch intro."""
    return send_from_directory(str(BASE_DIR / "videos"), filename)


@app.get("/uploads/<path:filename>")
def uploaded_files(filename):
    """Serve uploaded profile photos from the local uploads folder."""
    return send_from_directory(str(BASE_DIR / "uploads"), filename)


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

    state = get_onboarding_state(user["id"])
    return jsonify({
        "user": public_user(user, state),
        "onboardingRequired": state["onboardingRequired"],
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

    state = get_onboarding_state(user["id"])
    return jsonify({
        "user": public_user(user, state),
        "onboardingRequired": state["onboardingRequired"],
    })


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

    state = get_onboarding_state(user["id"])
    return jsonify({
        "user": public_user(user, state),
        "onboardingRequired": state["onboardingRequired"],
    })


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
# Profile and onboarding API
# ============================================================
@app.get("/api/subjects")
def subjects_list():
    """Reference subjects used by onboarding and later by search."""
    q = (request.args.get("q") or "").strip()
    if q:
        rows = db.query_all(
            """
            SELECT id, name, category
            FROM subjects
            WHERE name LIKE %s OR category LIKE %s
            ORDER BY category, name
            """,
            (f"%{q}%", f"%{q}%"),
        )
    else:
        rows = db.query_all(
            "SELECT id, name, category FROM subjects ORDER BY category, name"
        )
    return jsonify({"subjects": rows})


@app.get("/api/levels")
def levels_list():
    """Level labels shared by the onboarding UI."""
    return jsonify({
        "levels": [
            {"id": "elementary", "label": "Elementary"},
            {"id": "high_school", "label": "High school"},
            {"id": "senior_high", "label": "Senior high"},
            {"id": "college", "label": "College"},
            {"id": "adult", "label": "Adult learner"},
        ]
    })


@app.get("/api/me/profile")
@login_required
def my_profile():
    """Return the private, editable profile."""
    payload = get_profile_payload(session["user_id"])
    if not payload:
        return json_error("UNAUTHORIZED", "Please log in again.", 401)
    return jsonify({"profile": payload})


@app.get("/api/me/completeness")
@login_required
def my_completeness():
    """Return the completeness meter and the missing checklist."""
    payload = get_profile_payload(session["user_id"])
    if not payload:
        return json_error("UNAUTHORIZED", "Please log in again.", 401)
    return jsonify({
        "percent": payload["completeness"],
        "requiredComplete": payload["requiredComplete"],
        "missing": payload["missing"],
    })


@app.patch("/api/me/profile")
@login_required
def update_my_profile():
    """Save any subset of profile fields and recompute completeness."""
    user_id = session["user_id"]
    user = fetch_user_by_id(user_id)
    if not user:
        return json_error("UNAUTHORIZED", "Please log in again.", 401)

    data = json_body()
    row = db.query_one("SELECT * FROM profiles WHERE user_id = %s", (user_id,))
    current_subjects = []
    current_availability = []
    if row:
        current_subjects = db.query_all(
            """
            SELECT subject_id, level, kind
            FROM profile_subjects
            WHERE profile_id = %s
            """,
            (row["id"],),
        )
        current_availability = db.query_all(
            """
            SELECT day_of_week, start_time, end_time
            FROM availability_slots
            WHERE profile_id = %s
            """,
            (row["id"],),
        )

    profile = profile_row_to_dict(row, user)
    fields = {}
    name_update = None

    if "name" in data:
        name = clean_name(data.get("name"))
        if not name:
            fields["name"] = "Enter your full name (2-80 characters)."
        else:
            profile["name"] = name
            name_update = name

    if "headline" in data:
        headline = str(data.get("headline") or "").strip()
        if len(headline) > 120:
            fields["headline"] = "Keep the headline under 120 characters."
        else:
            profile["headline"] = headline or None

    if "bio" in data:
        bio = str(data.get("bio") or "").strip()
        if len(bio) > 600:
            fields["bio"] = "Keep the bio under 600 characters."
        else:
            profile["bio"] = bio or None

    if "birthdate" in data:
        value = str(data.get("birthdate") or "").strip()
        if not value:
            profile["birthdate"] = None
        else:
            try:
                birthdate = date.fromisoformat(value)
            except ValueError:
                fields["birthdate"] = "Use a valid date."
            else:
                if birthdate > date.today():
                    fields["birthdate"] = "Birthdate cannot be in the future."
                else:
                    profile["birthdate"] = birthdate

    if "status" in data:
        status = str(data.get("status") or "").strip()
        if status not in PROFILE_STATUSES:
            fields["status"] = "Choose a valid status."
        else:
            profile["status"] = status

    if "format" in data:
        fmt = str(data.get("format") or "").strip()
        if fmt not in PROFILE_FORMATS:
            fields["format"] = "Choose a session format."
        else:
            profile["format"] = fmt

    if "area" in data:
        area = data.get("area")
        if not isinstance(area, dict):
            fields["area"] = "Enter your barangay and city."
        else:
            barangay = str(area.get("barangay") or "").strip()
            city = str(area.get("city") or "Cabadbaran City").strip()
            if len(barangay) > 80:
                fields["area"] = "Keep the barangay under 80 characters."
            elif len(city) > 80:
                fields["area"] = "Keep the city under 80 characters."
            else:
                profile["area_barangay"] = barangay or None
                profile["area_city"] = city or "Cabadbaran City"

    if "rateCentavos" in data:
        profile["rate_centavos"] = parse_money(
            data.get("rateCentavos"),
            "rate",
            fields,
        )
    if "budgetMinCentavos" in data:
        profile["budget_min_centavos"] = parse_money(
            data.get("budgetMinCentavos"),
            "budget",
            fields,
        )
    if "budgetMaxCentavos" in data:
        profile["budget_max_centavos"] = parse_money(
            data.get("budgetMaxCentavos"),
            "budget",
            fields,
        )

    if (
        profile["budget_min_centavos"] is not None
        and profile["budget_max_centavos"] is not None
        and profile["budget_min_centavos"] > profile["budget_max_centavos"]
    ):
        fields["budget"] = "The minimum budget cannot be higher than the maximum."

    if "styleTags" in data:
        profile["style_tags"] = parse_tags(
            data.get("styleTags"),
            STYLE_TAGS,
            "styleTags",
            fields,
        )
    if "goalTags" in data:
        profile["goal_tags"] = parse_tags(
            data.get("goalTags"),
            GOAL_TAGS,
            "goalTags",
            fields,
        )

    subjects_provided = "subjects" in data
    if subjects_provided:
        parsed_subjects = parse_subjects(
            data.get("subjects"),
            user["role"],
            fields,
        )
        profile["subjects_for_write"] = parsed_subjects
    else:
        profile["subjects_for_write"] = current_subjects

    availability_provided = "availability" in data
    if availability_provided:
        parsed_availability = parse_availability(
            data.get("availability"),
            fields,
        )
        profile["availability_for_write"] = parsed_availability
    else:
        profile["availability_for_write"] = current_availability

    if "onboardingStep" in data:
        try:
            step = int(data.get("onboardingStep"))
        except (TypeError, ValueError):
            fields["onboardingStep"] = "Choose a valid step."
        else:
            if step < 1 or step > 7:
                fields["onboardingStep"] = "Choose a valid step."
            else:
                profile["onboarding_step"] = step

    finish = bool(data.get("onboardingCompleted"))
    if fields:
        return validation_error(fields)

    percent, required_complete, missing = compute_completeness(
        profile,
        profile["subjects_for_write"],
        profile["availability_for_write"],
    )

    if finish and not required_complete:
        finish_fields = {}
        for item in missing:
            if item["field"] in REQUIRED_FIELD_MESSAGES:
                finish_fields[item["field"]] = REQUIRED_FIELD_MESSAGES[item["field"]]
        return validation_error(
            finish_fields or {"profile": "Complete the required profile fields."},
            "Complete the required profile fields before finishing.",
        )

    completed_at = profile.get("onboarding_completed_at")
    if finish:
        completed_at = now_utc()
        profile["onboarding_step"] = 7
    elif not required_complete:
        completed_at = None

    style_json = json.dumps(profile["style_tags"])
    goal_json = json.dumps(profile["goal_tags"])
    # The upload route owns photo_url. Keeping it out of this write
    # prevents a save from overwriting a photo that finished uploading.
    profile_values = (
        profile["bio"],
        profile["birthdate"],
        profile["headline"],
        profile["status"],
        profile["format"],
        profile["area_barangay"],
        profile["area_city"],
        profile["rate_centavos"],
        profile["budget_min_centavos"],
        profile["budget_max_centavos"],
        profile["currency"],
        style_json,
        goal_json,
        percent,
        profile["onboarding_step"],
        completed_at,
    )

    with db.transaction() as connection:
        with connection.cursor() as cursor:
            if row:
                profile_id = row["id"]
                cursor.execute(
                    """
                    UPDATE profiles
                    SET bio=%s, birthdate=%s, headline=%s,
                        status=%s, format=%s, area_barangay=%s, area_city=%s,
                        rate_centavos=%s, budget_min_centavos=%s,
                        budget_max_centavos=%s, currency=%s, style_tags=%s,
                        goal_tags=%s, completeness=%s, onboarding_step=%s,
                        onboarding_completed_at=%s
                    WHERE id=%s
                    """,
                    profile_values + (profile_id,),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO profiles
                        (bio, birthdate, headline, status, format,
                         area_barangay, area_city, rate_centavos,
                         budget_min_centavos, budget_max_centavos, currency,
                         style_tags, goal_tags, completeness, onboarding_step,
                         onboarding_completed_at, user_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    profile_values + (user_id,),
                )
                profile_id = cursor.lastrowid

            if subjects_provided:
                cursor.execute(
                    "DELETE FROM profile_subjects WHERE profile_id = %s",
                    (profile_id,),
                )
                for subject in profile["subjects_for_write"]:
                    cursor.execute(
                        """
                        INSERT INTO profile_subjects
                            (profile_id, subject_id, level, kind)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (
                            profile_id,
                            subject["id"],
                            subject["level"],
                            subject["kind"],
                        ),
                    )

            if availability_provided:
                cursor.execute(
                    "DELETE FROM availability_slots WHERE profile_id = %s",
                    (profile_id,),
                )
                for slot in profile["availability_for_write"]:
                    cursor.execute(
                        """
                        INSERT INTO availability_slots
                            (profile_id, day_of_week, start_time, end_time, timezone)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            profile_id,
                            DAY_INDEX[slot["day"]],
                            slot["start"],
                            slot["end"],
                            "Asia/Manila",
                        ),
                    )

            if name_update:
                cursor.execute(
                    "UPDATE users SET name = %s WHERE id = %s",
                    (name_update, user_id),
                )

    log_event(
        "profile_saved",
        user_id=user_id,
        details=f"step {profile['onboarding_step']}, complete={required_complete}",
    )
    payload = get_profile_payload(user_id)
    return jsonify({"profile": payload})


@app.post("/api/me/photo")
@login_required
def upload_my_photo():
    """Store an optional profile photo in uploads/avatars."""
    photo = request.files.get("photo")
    if not photo or not photo.filename:
        return validation_error({"photo": "Choose an image file."})

    mime = (photo.mimetype or "").lower()
    if mime not in PHOTO_TYPES:
        return validation_error({"photo": "Use a JPG, PNG, or WebP image."})

    data = photo.read(MAX_PHOTO_BYTES + 1)
    if not data or len(data) > MAX_PHOTO_BYTES:
        return validation_error({"photo": "Keep the image under 1 MB."})
    if not looks_like_image(data, mime):
        return validation_error({"photo": "That file is not a valid image."})

    extension = PHOTO_TYPES[mime]
    filename = f"{session['user_id']}-{secrets.token_hex(6)}.{extension}"
    avatar_dir = BASE_DIR / "uploads" / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    (avatar_dir / filename).write_bytes(data)
    photo_url = f"/uploads/avatars/{filename}"

    old_photo = None
    with db.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, photo_url FROM profiles WHERE user_id = %s",
                (session["user_id"],),
            )
            row = cursor.fetchone()
            if row:
                old_photo = row["photo_url"]
                cursor.execute(
                    "UPDATE profiles SET photo_url = %s WHERE id = %s",
                    (photo_url, row["id"]),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO profiles (user_id, photo_url)
                    VALUES (%s, %s)
                    """,
                    (session["user_id"], photo_url),
                )

    if old_photo and old_photo.startswith("/uploads/avatars/"):
        old_path = BASE_DIR / old_photo.lstrip("/")
        try:
            old_path.unlink()
        except OSError:
            pass

    log_event("profile_photo_updated", user_id=session["user_id"])
    return jsonify({"photoUrl": photo_url}), 201


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
