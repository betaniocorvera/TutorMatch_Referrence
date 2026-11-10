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
import math
import os
import re
import secrets
from datetime import date, datetime, timedelta, timezone
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

# Search weights follow docs/03-data-model.md. They are intentionally
# visible in one place so they can be tuned with evidence later.
MATCH_WEIGHTS = {
    "subject": 0.35,
    "availability": 0.20,
    "budget": 0.15,
    "distance": 0.15,
    "styleGoal": 0.15,
}
LEVEL_RANK = {level: index for index, level in enumerate(PROFILE_LEVELS)}
DAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Approximate barangay centroids for Cabadbaran City. These are only
# used to compute a coarse distance rounded to the nearest 100 m. The
# exact coordinates are never returned by the API.
CABADBARAN_CENTER = (9.1236, 125.5345)
BARANGAY_CENTROIDS = {
    "del pilar": (9.1202, 125.5361),
    "calibunan": (9.1020, 125.5210),
    "comagascas": (9.1390, 125.5480),
    "katugasan": (9.1080, 125.5010),
    "concepcion": (9.1320, 125.5400),
    "san agustin": (9.1450, 125.5300),
    "san jose": (9.1180, 125.5280),
    "mabini": (9.1100, 125.5450),
    "la union": (9.1350, 125.5150),
    "sanghan": (9.1000, 125.5400),
    "marang": (9.1500, 125.5600),
    "tagmamarkay": (9.0900, 125.5100),
    "tagongtong": (9.1600, 125.5200),
    "tubo-tubo": (9.0800, 125.5500),
}

# The UI uses coarse three-hour windows for the mini availability grid.
# Search itself compares the exact HH:MM slots stored in MySQL.
AVAILABILITY_FILTERS = {
    "weekday-am": [
        {"day": day, "start": "06:00", "end": "12:00"}
        for day in DAYS[:5]
    ],
    "weekday-pm": [
        {"day": day, "start": "12:00", "end": "18:00"}
        for day in DAYS[:5]
    ],
    "weekday-eve": [
        {"day": day, "start": "18:00", "end": "24:00"}
        for day in DAYS[:5]
    ],
    "weekend": [
        {"day": "sat", "start": "00:00", "end": "24:00"},
        {"day": "sun", "start": "00:00", "end": "24:00"},
    ],
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
# Search and matching helpers
# ============================================================
def _to_minutes(value):
    """Convert HH:MM (or 24:00) to minutes from midnight."""
    if value is None:
        return None
    text = str(value).strip()
    if text == "24:00":
        return 24 * 60
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    if hours > 24 or minutes > 59 or (hours == 24 and minutes != 0):
        return None
    return hours * 60 + minutes


def _minutes_text(value):
    """Convert minutes from midnight back to HH:MM."""
    value = max(0, min(24 * 60, int(value)))
    if value == 24 * 60:
        return "24:00"
    return f"{value // 60:02d}:{value % 60:02d}"


def _time_label(value):
    """Format a time for a short plain-language reason."""
    minutes = _to_minutes(value)
    if minutes is None:
        return str(value or "")
    hours = (minutes // 60) % 24
    mins = minutes % 60
    suffix = "AM" if hours < 12 else "PM"
    display = hours % 12 or 12
    if mins:
        return f"{display}:{mins:02d} {suffix}"
    return f"{display} {suffix}"


def _range_label(start, end):
    """Format a compact time range such as 6–8 PM."""
    start_minutes = _to_minutes(start)
    end_minutes = _to_minutes(end)
    if start_minutes is None or end_minutes is None:
        return f"{start}–{end}"
    start_hour = (start_minutes // 60) % 24
    end_hour = (end_minutes // 60) % 24
    start_suffix = "AM" if start_hour < 12 else "PM"
    end_suffix = "AM" if end_hour < 12 else "PM"
    start_display = start_hour % 12 or 12
    end_display = end_hour % 12 or 12
    if start_minutes % 60 == 0 and end_minutes % 60 == 0:
        if start_suffix == end_suffix:
            return f"{start_display}–{end_display} {end_suffix}"
        return f"{start_display} {start_suffix}–{end_display} {end_suffix}"
    return f"{_time_label(start)}–{_time_label(end)}"


def _money_text(centavos):
    """Format integer centavos for a reason or warning."""
    if centavos is None:
        return None
    pesos = int(centavos) / 100
    if pesos.is_integer():
        return f"₱{int(pesos):,}"
    return f"₱{pesos:,.2f}"


def _barangay_coords(barangay, city=None):
    """Return a coarse centroid for a Cabadbaran barangay, or None."""
    if not barangay:
        return None
    if city and "cabadbaran" not in str(city).lower():
        return None
    text = str(barangay).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\b(brgy|barangay|poblacion|pob)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    if text in BARANGAY_CENTROIDS:
        return BARANGAY_CENTROIDS[text]
    digits = re.search(r"\d+", text)
    if digits:
        number = int(digits.group())
        angle = (number % 12) * (2 * math.pi / 12)
        radius = 0.012
        return (
            CABADBARAN_CENTER[0] + radius * math.cos(angle),
            CABADBARAN_CENTER[1] + radius * math.sin(angle),
        )
    return None


def _haversine_meters(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres."""
    radius = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def _distance_meters(viewer_profile, candidate_row):
    """Coarse distance rounded to the nearest 100 m, or None."""
    viewer_area = (viewer_profile or {}).get("area") or {}
    start = _barangay_coords(
        viewer_area.get("barangay"),
        viewer_area.get("city"),
    )
    end = _barangay_coords(
        candidate_row.get("area_barangay"),
        candidate_row.get("area_city"),
    )
    if not start or not end:
        return None
    meters = _haversine_meters(start[0], start[1], end[0], end[1])
    return int(round(meters / 100.0) * 100)


def _overlap_intervals(left_slots, right_slots):
    """Return merged day/time intervals where two availability lists meet."""
    grouped = {}
    for left in left_slots or []:
        left_start = _to_minutes(left.get("start"))
        left_end = _to_minutes(left.get("end"))
        if left_start is None or left_end is None or left_start >= left_end:
            continue
        for right in right_slots or []:
            if left.get("day") != right.get("day"):
                continue
            right_start = _to_minutes(right.get("start"))
            right_end = _to_minutes(right.get("end"))
            if right_start is None or right_end is None:
                continue
            start = max(left_start, right_start)
            end = min(left_end, right_end)
            if start < end:
                grouped.setdefault(left["day"], []).append((start, end))

    merged = []
    for day in DAYS:
        intervals = sorted(grouped.get(day, []))
        for start, end in intervals:
            if (
                merged
                and merged[-1]["day"] == day
                and start <= _to_minutes(merged[-1]["end"])
            ):
                merged[-1]["end"] = _minutes_text(
                    max(_to_minutes(merged[-1]["end"]), end)
                )
            else:
                merged.append({
                    "day": day,
                    "start": _minutes_text(start),
                    "end": _minutes_text(end),
                })
    return merged


def _overlap_minutes(intervals):
    """Total minutes covered by merged intervals."""
    total = 0
    for interval in intervals or []:
        start = _to_minutes(interval.get("start"))
        end = _to_minutes(interval.get("end"))
        if start is not None and end is not None and end > start:
            total += end - start
    return total


def _availability_score(target_slots, candidate_slots):
    """Jaccard-style availability overlap against a target schedule."""
    merged_target = _overlap_intervals(target_slots, target_slots)
    target_minutes = _overlap_minutes(merged_target)
    if not target_minutes:
        return 0.5, []
    overlap = _overlap_intervals(target_slots, candidate_slots)
    score = min(1.0, _overlap_minutes(overlap) / target_minutes)
    return score, overlap


def _format_compatible(left, right):
    """True when two people can meet in at least one common format."""
    if not left or not right:
        return True
    if left == "both" or right == "both":
        return True
    return left == right


def _format_matches_filter(requested, candidate):
    """Apply the explicit format filter from the query string."""
    if not requested or requested == "any":
        return True
    if requested == "online":
        return candidate in ("online", "both")
    if requested == "in_person":
        return candidate in ("in_person", "both")
    if requested == "both":
        return candidate == "both"
    return True


def _level_closeness(left, right):
    """1.0 for the same level, smaller values for a larger gap."""
    if left not in LEVEL_RANK or right not in LEVEL_RANK:
        return 0.5
    difference = abs(LEVEL_RANK[left] - LEVEL_RANK[right])
    if difference == 0:
        return 1.0
    if difference == 1:
        return 0.75
    if difference == 2:
        return 0.5
    return 0.25


def _jaccard(left, right):
    """Jaccard similarity, or None when one side has no data."""
    left_set = set(left or [])
    right_set = set(right or [])
    if not left_set or not right_set:
        return None
    return len(left_set & right_set) / len(left_set | right_set)


def _parse_int_arg(name, default=None, minimum=0, maximum=None):
    """Read an integer query parameter and return (value, error)."""
    raw = request.args.get(name)
    if raw is None or str(raw).strip() == "":
        return default, None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default, "Enter a whole number."
    if value < minimum:
        return default, f"Enter a value of at least {minimum}."
    if maximum is not None and value > maximum:
        return default, f"Enter a value no higher than {maximum}."
    return value, None


def _parse_tag_filter(raw, allowed, field, fields):
    """Read a comma-separated soft tag filter."""
    if not raw:
        return []
    result = []
    for token in str(raw).split(","):
        tag = token.strip()
        if not tag:
            continue
        if tag not in allowed:
            fields[field] = "Choose valid tags."
            return []
        if tag not in result:
            result.append(tag)
    return result


def _parse_availability_filter(raw):
    """Read category tokens or exact day:HH:MM-HH:MM slots."""
    if not raw:
        return [], None
    result = []
    for token in str(raw).split(","):
        token = token.strip().lower()
        if not token:
            continue
        if token in AVAILABILITY_FILTERS:
            result.extend(AVAILABILITY_FILTERS[token])
            continue
        match = re.fullmatch(
            r"([a-z]{3}):(\d{1,2}:\d{2})-(\d{1,2}:\d{2})",
            token,
        )
        if not match:
            return [], "Choose valid availability."
        day, start, end = match.groups()
        start_minutes = _to_minutes(start)
        end_minutes = _to_minutes(end)
        if (
            day not in DAY_INDEX
            or start_minutes is None
            or end_minutes is None
            or start_minutes >= end_minutes
        ):
            return [], "Choose valid availability."
        result.append({"day": day, "start": start, "end": end})
    return result, None


def _viewer_profile(user_id):
    """Return the account row and a search-friendly private profile."""
    user = fetch_user_by_id(user_id)
    if not user:
        return None, None
    profile = get_profile_payload(user_id)
    if not profile:
        profile = {
            "id": None,
            "userId": user["id"],
            "role": user["role"],
            "name": user["name"],
            "area": {"barangay": None, "city": "Cabadbaran City"},
            "subjects": [],
            "availability": [],
            "styleTags": [],
            "goalTags": [],
            "rateCentavos": None,
            "budgetMinCentavos": None,
            "budgetMaxCentavos": None,
            "format": None,
            "verified": False,
        }
    return user, profile


def _load_search_candidates(role):
    """Load opposite-role profiles with their subjects and availability."""
    rows = db.query_all(
        """
        SELECT p.id, p.user_id, p.photo_url, p.bio, p.headline, p.status,
               p.format, p.area_barangay, p.area_city, p.coarse_geohash,
               p.rate_centavos, p.budget_min_centavos, p.budget_max_centavos,
               p.currency, p.style_tags, p.goal_tags, p.completeness,
               p.onboarding_completed_at, p.verified_at, p.response_time_mins,
               p.last_active_at,
               u.id AS account_id, u.role AS account_role,
               u.name AS account_name, u.last_login_at
        FROM profiles p
        JOIN users u ON u.id = p.user_id
        WHERE u.role = %s
          AND u.status = 'active'
          AND p.onboarding_completed_at IS NOT NULL
        ORDER BY p.id
        """,
        (role,),
    )
    if not rows:
        return []

    profile_ids = [row["id"] for row in rows]
    placeholders = ", ".join(["%s"] * len(profile_ids))
    subject_rows = db.query_all(
        f"""
        SELECT ps.profile_id, ps.subject_id, ps.level, ps.kind,
               s.name, s.category
        FROM profile_subjects ps
        JOIN subjects s ON s.id = ps.subject_id
        WHERE ps.profile_id IN ({placeholders})
        ORDER BY s.category, s.name
        """,
        tuple(profile_ids),
    )
    availability_rows = db.query_all(
        f"""
        SELECT profile_id, day_of_week, start_time, end_time
        FROM availability_slots
        WHERE profile_id IN ({placeholders})
        ORDER BY day_of_week, start_time
        """,
        tuple(profile_ids),
    )

    subjects_by_profile = {}
    for row in subject_rows:
        subjects_by_profile.setdefault(row["profile_id"], []).append({
            "id": row["subject_id"],
            "name": row["name"],
            "category": row["category"],
            "level": row["level"],
            "kind": row["kind"],
        })

    availability_by_profile = {}
    for row in availability_rows:
        if 1 <= row["day_of_week"] <= 7:
            availability_by_profile.setdefault(row["profile_id"], []).append({
                "day": DAYS[row["day_of_week"] - 1],
                "start": _time_text(row["start_time"]),
                "end": _time_text(row["end_time"]),
            })

    candidates = []
    for row in rows:
        candidates.append({
            "row": row,
            "user": {
                "id": row["account_id"],
                "role": row["account_role"],
                "name": row["account_name"],
                "last_login_at": row["last_login_at"],
            },
            "subjects": subjects_by_profile.get(row["id"], []),
            "availability": availability_by_profile.get(row["id"], []),
        })
    return candidates


def _profile_is_searchable(candidate):
    """Apply the minimum profile rules from docs/03-data-model.md."""
    row = candidate["row"]
    if not row.get("onboarding_completed_at"):
        return False
    if len(str(row.get("bio") or "").strip()) < 10:
        return False
    if not str(row.get("area_barangay") or "").strip():
        return False
    if not row.get("format"):
        return False
    if not candidate["subjects"] or not candidate["availability"]:
        return False
    if candidate["user"]["role"] == "tutor" and row.get("rate_centavos") is None:
        return False
    if candidate["user"]["role"] == "student":
        if (
            row.get("budget_min_centavos") is None
            or row.get("budget_max_centavos") is None
        ):
            return False
    return True


def _subject_score(viewer_subjects, candidate_subjects, subject_id=None, level=None):
    """Score subject overlap and return the best subject for the reason."""
    candidate_by_id = {}
    for subject in candidate_subjects:
        candidate_by_id.setdefault(subject["id"], []).append(subject)

    if subject_id:
        matches = candidate_by_id.get(subject_id, [])
        if not matches:
            return 0.0, None, []
        if level:
            best = max(
                matches,
                key=lambda subject: _level_closeness(subject["level"], level),
            )
            return _level_closeness(best["level"], level), best, matches
        return 1.0, matches[0], matches

    viewer_ids = {subject["id"] for subject in viewer_subjects}
    if not viewer_ids:
        return 0.5, None, []
    candidate_ids = set(candidate_by_id)
    common = viewer_ids & candidate_ids
    if not common:
        return 0.0, None, []

    jaccard = len(common) / len(viewer_ids | candidate_ids)
    level_scores = []
    for subject_id_value in common:
        viewer_levels = [
            subject["level"]
            for subject in viewer_subjects
            if subject["id"] == subject_id_value
        ]
        candidate_levels = [
            subject["level"]
            for subject in candidate_by_id[subject_id_value]
        ]
        level_scores.append(max(
            _level_closeness(candidate_level, viewer_level)
            for candidate_level in candidate_levels
            for viewer_level in viewer_levels
        ))
    level_average = sum(level_scores) / len(level_scores)
    score = 0.6 * jaccard + 0.4 * level_average

    best_subject = None
    best_level_score = -1
    for subject in candidate_subjects:
        if subject["id"] not in common:
            continue
        viewer_levels = [
            viewer_subject["level"]
            for viewer_subject in viewer_subjects
            if viewer_subject["id"] == subject["id"]
        ]
        closeness = max(
            _level_closeness(subject["level"], viewer_level)
            for viewer_level in viewer_levels
        )
        if closeness > best_level_score:
            best_level_score = closeness
            best_subject = subject
    return score, best_subject, [
        subject for subject in candidate_subjects if subject["id"] in common
    ]


def _style_goal_score(viewer, candidate, style_filter, goal_filter):
    """Score style and goal tags together, ignoring missing sections."""
    style_target = style_filter or viewer.get("styleTags") or []
    goal_target = goal_filter or viewer.get("goalTags") or []
    style = _jaccard(style_target, candidate["row"].get("style_tags"))
    goal = _jaccard(goal_target, candidate["row"].get("goal_tags"))
    parts = [value for value in (style, goal) if value is not None]
    if not parts:
        return 0.5, [], []
    style_common = list(
        set(style_target)
        & set(_json_list(candidate["row"].get("style_tags")))
    )
    goal_common = list(
        set(goal_target)
        & set(_json_list(candidate["row"].get("goal_tags")))
    )
    return sum(parts) / len(parts), style_common, goal_common


def _budget_score(viewer, candidate, hard_max_rate, hard_min_budget):
    """Score budget fit and return a soft warning when it is close."""
    row = candidate["row"]
    if viewer["role"] == "student":
        rate = row.get("rate_centavos")
        budget = (
            hard_max_rate
            if hard_max_rate is not None
            else viewer.get("budgetMaxCentavos")
        )
        if rate is None or budget is None or budget <= 0:
            return 0.5, None
        if rate <= budget:
            return 1.0, None
        over = rate - budget
        score = max(0.0, 1.0 - (over / max(budget, 1)))
        return score, f"{_money_text(over)} above your {_money_text(budget)} budget"

    student_budget = row.get("budget_max_centavos")
    rate = (
        hard_min_budget
        if hard_min_budget is not None
        else viewer.get("rateCentavos")
    )
    if student_budget is None or rate is None or rate <= 0:
        return 0.5, None
    if student_budget >= rate:
        return 1.0, None
    short = rate - student_budget
    score = max(0.0, 1.0 - (short / max(rate, 1)))
    return score, f"Budget is {_money_text(short)} below your {_money_text(rate)} rate"


def _distance_score(candidate_row, distance_meters, max_distance_meters):
    """Score distance, or neutral for online-only candidates."""
    if candidate_row.get("format") == "online":
        return 1.0
    if distance_meters is None:
        return 0.5
    radius = (
        max_distance_meters
        if max_distance_meters and max_distance_meters > 0
        else 20000
    )
    return max(0.0, min(1.0, 1.0 - (distance_meters / radius)))


def _band_for_score(score):
    """Map a 0–100 similarity score to the UI band."""
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "fair"
    return "low"


def _availability_summary(overlap):
    """Build a compact reason such as 'Tue & Thu, 6–8 PM'."""
    if not overlap:
        return ""
    day_names = []
    for interval in overlap:
        label = DAY_LABELS[DAYS.index(interval["day"])]
        if label not in day_names:
            day_names.append(label)
    ranges = []
    for interval in overlap:
        label = _range_label(interval["start"], interval["end"])
        if label not in ranges:
            ranges.append(label)
    days = " & ".join(day_names[:2])
    if len(day_names) > 2:
        days += f" + {len(day_names) - 2} more"
    if not ranges:
        return days
    return f"{days}, {ranges[0]}"


def _build_reasons(
    viewer,
    candidate,
    features,
    subject_info,
    overlap,
    distance_meters,
    hard_max_rate,
    hard_min_budget,
    style_common,
    goal_common,
):
    """Turn the strongest positive contributions into at most three reasons."""
    reasons = []
    row = candidate["row"]

    if features["subject"] >= 0.55 and subject_info:
        name = subject_info.get("name") or "a shared subject"
        if viewer["role"] == "student":
            label = f"Teaches {name}"
        else:
            label = f"Needs help with {name}"
        reasons.append(("subject", label, MATCH_WEIGHTS["subject"] * features["subject"]))

    if features["availability"] >= 0.25 and overlap:
        label = f"Free {_availability_summary(overlap)}"
        reasons.append(("availability", label, MATCH_WEIGHTS["availability"] * features["availability"]))

    if features["budget"] >= 0.85:
        if viewer["role"] == "student":
            budget = (
                hard_max_rate
                if hard_max_rate is not None
                else viewer.get("budgetMaxCentavos")
            )
            if budget is not None:
                reasons.append((
                    "budget",
                    f"Within your {_money_text(budget)} budget",
                    MATCH_WEIGHTS["budget"] * features["budget"],
                ))
        else:
            rate = (
                hard_min_budget
                if hard_min_budget is not None
                else viewer.get("rateCentavos")
            )
            if rate is not None:
                reasons.append((
                    "budget",
                    f"Budget covers your {_money_text(rate)} rate",
                    MATCH_WEIGHTS["budget"] * features["budget"],
                ))

    if (
        features["distance"] >= 0.55
        and distance_meters is not None
        and row.get("format") != "online"
    ):
        if distance_meters == 0:
            distance_label = "Same barangay"
        elif distance_meters < 1000:
            distance_label = f"Only {distance_meters} m away"
        else:
            distance_label = f"Only {distance_meters / 1000:.1f} km away"
        reasons.append((
            "distance",
            distance_label,
            MATCH_WEIGHTS["distance"] * features["distance"],
        ))

    if style_common:
        tags = ", ".join(tag.replace("_", " ") for tag in style_common[:2])
        if viewer["role"] == "student":
            label = f"Uses a {tags} style"
        else:
            label = f"Prefers {tags} learning"
        reasons.append(("style", label, MATCH_WEIGHTS["styleGoal"] * features["styleGoal"]))

    if goal_common:
        tags = ", ".join(tag.replace("_", " ") for tag in goal_common[:2])
        reasons.append((
            "goal",
            f"Shares your {tags} goal",
            MATCH_WEIGHTS["styleGoal"] * features["styleGoal"],
        ))

    if row.get("verified_at"):
        reasons.append(("verification", "Verified profile", 0.02))
    if row.get("response_time_mins"):
        reasons.append((
            "response",
            f"Usually replies in {row['response_time_mins']} min",
            0.01,
        ))

    reasons.sort(key=lambda item: item[2], reverse=True)
    return [
        {"type": reason_type, "label": label}
        for reason_type, label, _score in reasons[:3]
    ]


def _build_match(
    viewer,
    candidate,
    distance_meters,
    max_distance_meters,
    hard_max_rate,
    hard_min_budget,
    target_slots,
    style_filter,
    goal_filter,
):
    """Compute the score, band, reasons, overlap, warnings, and breakdown."""
    subject_score, subject_info, _common_subjects = _subject_score(
        viewer.get("subjects") or [],
        candidate["subjects"],
        subject_id=viewer.get("_subject_id"),
        level=viewer.get("_level"),
    )
    availability_score, overlap = _availability_score(
        target_slots,
        candidate["availability"],
    )
    budget_score, budget_warning = _budget_score(
        viewer,
        candidate,
        hard_max_rate,
        hard_min_budget,
    )
    distance_score = _distance_score(
        candidate["row"],
        distance_meters,
        max_distance_meters,
    )
    style_goal_score, style_common, goal_common = _style_goal_score(
        viewer,
        candidate,
        style_filter,
        goal_filter,
    )

    features = {
        "subject": subject_score,
        "availability": availability_score,
        "budget": budget_score,
        "distance": distance_score,
        "styleGoal": style_goal_score,
    }
    score = round(100 * sum(
        MATCH_WEIGHTS[key] * features[key]
        for key in MATCH_WEIGHTS
    ))
    score = max(0, min(100, score))
    band = _band_for_score(score)

    warnings = []
    if budget_warning:
        warnings.append(budget_warning)
    if distance_meters is None and candidate["row"].get("format") in ("in_person", "both"):
        warnings.append("Distance is unavailable for this barangay.")

    reasons = _build_reasons(
        viewer,
        candidate,
        features,
        subject_info,
        overlap,
        distance_meters,
        hard_max_rate,
        hard_min_budget,
        style_common,
        goal_common,
    )
    breakdown = {
        key: round(MATCH_WEIGHTS[key] * features[key], 4)
        for key in MATCH_WEIGHTS
    }
    return {
        "score": score,
        "scoreMode": "one-sided",
        "band": band,
        "reasons": reasons,
        "availabilityOverlap": overlap,
        "warnings": warnings,
        "breakdown": breakdown,
    }


def _public_profile(candidate, viewer, distance_meters):
    """Serialize only fields allowed by the privacy matrix."""
    row = candidate["row"]
    user = candidate["user"]
    profile = {
        "id": row["id"],
        "userId": user["id"],
        "role": user["role"],
        "name": user["name"],
        "photoUrl": row.get("photo_url"),
        "headline": row.get("headline"),
        "bio": row.get("bio"),
        "status": row.get("status"),
        "format": row.get("format"),
        "area": {
            "barangay": row.get("area_barangay"),
            "city": row.get("area_city") or "Cabadbaran City",
        },
        "distanceMeters": distance_meters,
        "subjects": [
            {
                "id": subject["id"],
                "name": subject["name"],
                "level": subject["level"],
            }
            for subject in candidate["subjects"]
        ],
        "styleTags": _json_list(row.get("style_tags")),
        "goalTags": _json_list(row.get("goal_tags")),
        "availability": candidate["availability"],
        "verified": row.get("verified_at") is not None,
        "responseTimeMins": row.get("response_time_mins"),
        "lastActiveAt": _datetime_text(
            row.get("last_active_at") or user.get("last_login_at")
        ),
        "reviews": {"count": 0, "average": None},
    }
    if user["role"] == "tutor":
        profile["rateCentavos"] = row.get("rate_centavos")
    else:
        profile["budgetMinCentavos"] = row.get("budget_min_centavos")
        profile["budgetMaxCentavos"] = row.get("budget_max_centavos")
    return profile


def _candidate_matches(
    viewer,
    candidate,
    subject_id,
    requested_format,
    hard_max_rate,
    hard_min_budget,
    max_distance_meters,
    requested_slots,
    query_text,
):
    """Apply all hard filters before ranking."""
    if not _profile_is_searchable(candidate):
        return False
    if candidate["user"]["role"] == viewer["role"]:
        return False
    if not _format_compatible(viewer.get("format"), candidate["row"].get("format")):
        return False
    if not _format_matches_filter(requested_format, candidate["row"].get("format")):
        return False

    row = candidate["row"]
    if viewer["role"] == "student":
        if (
            hard_max_rate is not None
            and row.get("rate_centavos") is not None
            and row["rate_centavos"] > hard_max_rate
        ):
            return False
    else:
        if (
            hard_min_budget is not None
            and row.get("budget_max_centavos") is not None
            and row["budget_max_centavos"] < hard_min_budget
        ):
            return False

    if subject_id and not any(
        subject["id"] == subject_id for subject in candidate["subjects"]
    ):
        return False

    if requested_slots:
        overlap = _overlap_intervals(requested_slots, candidate["availability"])
        if not overlap:
            return False

    if max_distance_meters is not None and row.get("format") in ("in_person", "both"):
        distance = _distance_meters(viewer, row)
        if distance is not None and distance > max_distance_meters:
            return False

    if query_text:
        terms = query_text.lower().split()
        haystack = " ".join([
            str(row.get("headline") or ""),
            str(row.get("bio") or ""),
            str(row.get("area_barangay") or ""),
            str(row.get("area_city") or ""),
            candidate["user"]["name"],
            *[subject["name"] for subject in candidate["subjects"]],
            *[subject["category"] for subject in candidate["subjects"]],
        ]).lower()
        if not all(term in haystack for term in terms):
            return False
    return True


def _sort_results(results, sort):
    """Sort scored results in place and return them."""
    if sort == "distance":
        results.sort(key=lambda item: (
            item["profile"].get("distanceMeters") is None,
            item["profile"].get("distanceMeters") or 0,
            -item["match"]["score"],
        ))
    elif sort == "rate":
        results.sort(key=lambda item: (
            item["profile"].get("rateCentavos") is None,
            item["profile"].get("rateCentavos") or 0,
            -item["match"]["score"],
        ))
    elif sort == "budget":
        results.sort(key=lambda item: (
            item["profile"].get("budgetMaxCentavos") is None,
            -(item["profile"].get("budgetMaxCentavos") or 0),
            -item["match"]["score"],
        ))
    else:
        results.sort(key=lambda item: (
            -item["match"]["score"],
            item["profile"].get("distanceMeters") is None,
            item["profile"].get("distanceMeters") or 0,
            item["profile"].get("name") or "",
        ))
    return results


def _search_suggestions(viewer, params, total, relaxed):
    """Return short, actionable suggestions for the no-results state."""
    tips = []
    role_word = "tutors" if viewer["role"] == "student" else "students"
    if total == 0:
        if params["format"]:
            tips.append(f"Try any format to see more {role_word}")
        if params["max_distance_meters"] is not None:
            tips.append("Widen your distance or choose Any distance")
        if params["availability_slots"]:
            tips.append("Clear the availability filter")
        if params["subject_id"]:
            tips.append("Try a broader subject")
        if params["q"]:
            tips.append("Try a shorter keyword")
        if params["hard_max_rate"] is not None or params["hard_min_budget"] is not None:
            tips.append(
                "Raise your budget"
                if viewer["role"] == "student"
                else "Lower your rate"
            )
        tips.append("Clear a filter and search again")
    elif total < 3:
        tips.append("Add more subjects or availability to improve matches")
    if relaxed:
        tips.append("Distance was widened to show more matches")

    result = []
    for tip in tips:
        if tip not in result:
            result.append(tip)
    return result[:4]


def _query_echo(params, role):
    """Echo the effective search criteria back to the client."""
    return {
        "q": params["q"] or None,
        "subjectId": params["subject_id"],
        "level": params["level"],
        "format": params["format"],
        "maxRateCentavos": (
            params["hard_max_rate"] if role == "student" else None
        ),
        "minBudgetCentavos": (
            params["hard_min_budget"] if role == "tutor" else None
        ),
        "availability": params["availability_raw"] or None,
        "maxDistanceMeters": params["max_distance_meters"],
        "style": params["style_raw"] or None,
        "goal": params["goal_raw"] or None,
        "sort": params["sort"],
        "page": params["page"],
        "limit": params["limit"],
    }


def _parse_search_params(role):
    """Validate every search query parameter in one place."""
    fields = {}
    q = (request.args.get("q") or "").strip()[:120]
    subject_id = (request.args.get("subjectId") or "").strip() or None
    level = (request.args.get("level") or "").strip() or None
    requested_format = (request.args.get("format") or "").strip() or None
    availability_raw = (request.args.get("availability") or "").strip()
    style_raw = (request.args.get("style") or "").strip()
    goal_raw = (request.args.get("goal") or "").strip()
    sort = (request.args.get("sort") or "score").strip().lower()

    if subject_id:
        exists = db.query_one(
            "SELECT id FROM subjects WHERE id = %s",
            (subject_id,),
        )
        if not exists:
            fields["subjectId"] = "Choose a valid subject."
    if level and level not in PROFILE_LEVELS:
        fields["level"] = "Choose a valid level."
    if requested_format and requested_format not in PROFILE_FORMATS:
        fields["format"] = "Choose a valid format."

    allowed_sorts = (
        ("score", "distance", "rate")
        if role == "student"
        else ("score", "distance", "budget")
    )
    if sort not in allowed_sorts:
        fields["sort"] = "Choose a valid sort order."

    availability_slots, availability_error = _parse_availability_filter(
        availability_raw
    )
    if availability_error:
        fields["availability"] = availability_error
    style_filter = _parse_tag_filter(style_raw, STYLE_TAGS, "style", fields)
    goal_filter = _parse_tag_filter(goal_raw, GOAL_TAGS, "goal", fields)

    hard_max_rate = None
    hard_min_budget = None
    if role == "student":
        hard_max_rate, error = _parse_int_arg(
            "maxRateCentavos",
            None,
            0,
            10000000,
        )
        if error:
            fields["maxRateCentavos"] = error
    else:
        hard_min_budget, error = _parse_int_arg(
            "minBudgetCentavos",
            None,
            0,
            10000000,
        )
        if error:
            fields["minBudgetCentavos"] = error

    max_distance_meters, error = _parse_int_arg(
        "maxDistanceMeters",
        None,
        0,
        1000000,
    )
    if error:
        fields["maxDistanceMeters"] = error
    page, error = _parse_int_arg("page", 1, 1, 1000)
    if error:
        fields["page"] = error
    limit, error = _parse_int_arg("limit", 10, 1, 50)
    if error:
        fields["limit"] = error

    return {
        "q": q,
        "subject_id": subject_id,
        "level": level,
        "format": requested_format,
        "availability_raw": availability_raw,
        "availability_slots": availability_slots,
        "style_raw": style_raw,
        "style_filter": style_filter,
        "goal_raw": goal_raw,
        "goal_filter": goal_filter,
        "sort": sort,
        "hard_max_rate": hard_max_rate,
        "hard_min_budget": hard_min_budget,
        "max_distance_meters": max_distance_meters,
        "page": page,
        "limit": limit,
    }, fields


def _run_search(viewer, params, soft_subject=False):
    """Filter, score, sort, and paginate candidates.

    ``soft_subject`` is used only by the offline evaluation script. It keeps
    the requested subject in the score but does not hard-filter the candidate
    pool, so rankers can be compared on the same candidates.
    """
    candidate_role = "tutor" if viewer["role"] == "student" else "student"
    candidates = _load_search_candidates(candidate_role)
    blocked_ids = _blocked_user_ids(viewer.get("userId"))
    if blocked_ids:
        candidates = [
            candidate
            for candidate in candidates
            if candidate["user"]["id"] not in blocked_ids
        ]
    target_slots = params["availability_slots"] or viewer.get("availability") or []
    viewer["_subject_id"] = params["subject_id"]
    viewer["_level"] = params["level"]

    def matches(candidate, max_distance_meters):
        return _candidate_matches(
            viewer,
            candidate,
            None if soft_subject else params["subject_id"],
            params["format"],
            params["hard_max_rate"],
            params["hard_min_budget"],
            max_distance_meters,
            params["availability_slots"],
            params["q"],
        )

    filtered = [
        candidate
        for candidate in candidates
        if matches(candidate, params["max_distance_meters"])
    ]
    relaxed = []
    if params["max_distance_meters"] is not None and len(filtered) < 3:
        wider = [
            candidate
            for candidate in candidates
            if matches(candidate, None)
        ]
        if len(wider) > len(filtered):
            filtered = wider
            relaxed.append("distance")

    scored = []
    for candidate in filtered:
        distance = _distance_meters(viewer, candidate["row"])
        match = _build_match(
            viewer,
            candidate,
            distance,
            params["max_distance_meters"],
            params["hard_max_rate"],
            params["hard_min_budget"],
            target_slots,
            params["style_filter"],
            params["goal_filter"],
        )
        scored.append({
            "profile": _public_profile(candidate, viewer, distance),
            "match": match,
        })

    visible = [
        item for item in scored
        if item["match"]["score"] >= 50
    ]
    if not visible and scored:
        visible = scored
        for item in visible:
            warning = "Low match score. Try widening your search."
            if warning not in item["match"]["warnings"]:
                item["match"]["warnings"].append(warning)

    _sort_results(visible, params["sort"])
    total = len(visible)
    start = (params["page"] - 1) * params["limit"]
    page_results = visible[start:start + params["limit"]]
    return (
        total,
        page_results,
        relaxed,
        _search_suggestions(viewer, params, total, relaxed),
    )


def _search_response(expected_role):
    """Shared implementation for both role-specific search endpoints."""
    user, viewer = _viewer_profile(session["user_id"])
    if not user:
        return json_error("UNAUTHORIZED", "Please log in again.", 401)
    if user["role"] != expected_role:
        message = (
            "Tutors search for students."
            if expected_role == "student"
            else "Students search for tutors."
        )
        return json_error("FORBIDDEN", message, 403)

    params, fields = _parse_search_params(user["role"])
    if fields:
        return validation_error(fields)

    total, results, relaxed, suggestions = _run_search(viewer, params)
    _record_analytics(
        "search_submitted",
        {
            "role": user["role"],
            "subjectId": params["subject_id"],
            "level": params["level"],
            "format": params["format"],
            "filters": {
                "maxRateCentavos": params["hard_max_rate"],
                "minBudgetCentavos": params["hard_min_budget"],
                "availability": params["availability_raw"] or None,
                "maxDistanceMeters": params["max_distance_meters"],
            },
            "resultCount": total,
        },
        user_id=user["id"],
    )
    return jsonify({
        "query": _query_echo(params, user["role"]),
        "total": total,
        "page": params["page"],
        "limit": params["limit"],
        "results": results,
        "relaxedFilters": relaxed,
        "suggestions": suggestions,
    })


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
# Search and public profile API
# ============================================================
@app.get("/api/search/tutors")
@login_required
def search_tutors():
    """Students search for tutors. Never called automatically by the UI."""
    return _search_response("student")


@app.get("/api/search/students")
@login_required
def search_students():
    """Tutors search for students. Never called automatically by the UI."""
    return _search_response("tutor")


@app.get("/api/profiles/<profile_id>")
@login_required
def public_profile(profile_id):
    """Return the privacy-safe public view of one profile."""
    raw = str(profile_id or "").strip()
    if raw.startswith("prof_"):
        raw = raw[5:]
    try:
        profile_id_value = int(raw)
    except (TypeError, ValueError):
        return json_error("NOT_FOUND", "Profile not found.", 404)

    row = db.query_one(
        """
        SELECT p.id, p.user_id, p.photo_url, p.bio, p.headline, p.status,
               p.format, p.area_barangay, p.area_city, p.coarse_geohash,
               p.rate_centavos, p.budget_min_centavos, p.budget_max_centavos,
               p.currency, p.style_tags, p.goal_tags, p.completeness,
               p.onboarding_completed_at, p.verified_at, p.response_time_mins,
               p.last_active_at,
               u.id AS account_id, u.role AS account_role,
               u.name AS account_name, u.last_login_at
        FROM profiles p
        JOIN users u ON u.id = p.user_id
        WHERE p.id = %s AND u.status = 'active'
        """,
        (profile_id_value,),
    )
    if not row:
        return json_error("NOT_FOUND", "Profile not found.", 404)
    if row["account_id"] != session["user_id"] and _block_exists(
        session["user_id"], row["account_id"]
    ):
        return json_error("NOT_FOUND", "Profile not found.", 404)

    subject_rows = db.query_all(
        """
        SELECT ps.subject_id, ps.level, ps.kind, s.name, s.category
        FROM profile_subjects ps
        JOIN subjects s ON s.id = ps.subject_id
        WHERE ps.profile_id = %s
        ORDER BY s.category, s.name
        """,
        (profile_id_value,),
    )
    availability_rows = db.query_all(
        """
        SELECT day_of_week, start_time, end_time
        FROM availability_slots
        WHERE profile_id = %s
        ORDER BY day_of_week, start_time
        """,
        (profile_id_value,),
    )

    candidate = {
        "row": row,
        "user": {
            "id": row["account_id"],
            "role": row["account_role"],
            "name": row["account_name"],
            "last_login_at": row["last_login_at"],
        },
        "subjects": [
            {
                "id": subject["subject_id"],
                "name": subject["name"],
                "level": subject["level"],
                "kind": subject["kind"],
            }
            for subject in subject_rows
        ],
        "availability": [
            {
                "day": DAYS[slot["day_of_week"] - 1],
                "start": _time_text(slot["start_time"]),
                "end": _time_text(slot["end_time"]),
            }
            for slot in availability_rows
            if 1 <= slot["day_of_week"] <= 7
        ],
    }
    _user, viewer = _viewer_profile(session["user_id"])
    distance = _distance_meters(viewer, row)
    _record_analytics(
        "profile_viewed",
        {"role": row["account_role"], "profileId": row["id"]},
        user_id=session["user_id"],
    )
    return jsonify({
        "profile": _public_profile(candidate, viewer, distance),
    })


# ============================================================
# Requests, conversations, and messaging API
# ============================================================
REQUEST_STATUSES = ("pending", "accepted", "declined", "cancelled", "expired")
REQUEST_ACTIONS = ("accept", "decline", "cancel")
REQUEST_MESSAGE_MAX_LENGTH = 500
REQUEST_DAILY_LIMIT = 5
REQUEST_EXPIRY_DAYS = 7
MESSAGE_MAX_LENGTH = 2000
MESSAGE_RATE_LIMIT = 30
MESSAGE_RATE_WINDOW_SECONDS = 60

SESSION_DURATIONS = (30, 60, 90, 120)
SESSION_STATUSES = (
    "proposed",
    "accepted",
    "declined",
    "rescheduled",
    "completed",
    "cancelled",
)
SESSION_ACTIONS = ("accept", "decline", "reschedule", "cancel", "complete")
SESSION_LOCATION_MAX_LENGTH = 200
SESSION_NOTE_MAX_LENGTH = 500

REPORT_REASONS = (
    "harassment",
    "spam",
    "impersonation",
    "inappropriate",
    "no_show",
    "other",
)
REPORT_DETAILS_MAX_LENGTH = 1000

ANALYTICS_EVENTS = frozenset({
    "search_submitted",
    "result_clicked",
    "profile_viewed",
    "request_sent",
    "request_accepted",
    "request_declined",
    "request_cancelled",
    "message_sent",
    "session_proposed",
    "session_accepted",
    "session_declined",
    "session_rescheduled",
    "session_completed",
    "session_cancelled",
    "report_submitted",
    "block_created",
    "block_removed",
})
ANALYTICS_FORBIDDEN_KEYS = frozenset({
    "email",
    "password",
    "password_hash",
    "passwordhash",
    "birthdate",
    "body",
    "message",
    "token",
    "address",
    "exact_location",
    "exactlocation",
    "latitude",
    "longitude",
    "coarse_geohash",
    "coarsegeohash",
    "verification_document",
    "verificationdocument",
})
ANALYTICS_PAYLOAD_MAX_BYTES = 4000

REQUEST_SELECT = """
    SELECT r.*, s.name AS subject_name,
           fu.name AS from_name, fu.role AS from_role,
           fp.photo_url AS from_photo_url,
           tu.name AS to_name, tu.role AS to_role,
           tp.photo_url AS to_photo_url,
           c.id AS conversation_id
    FROM match_requests r
    JOIN users fu ON fu.id = r.from_user_id
    LEFT JOIN profiles fp ON fp.user_id = fu.id
    JOIN users tu ON tu.id = r.to_user_id
    LEFT JOIN profiles tp ON tp.user_id = tu.id
    LEFT JOIN subjects s ON s.id = r.subject_id
    LEFT JOIN conversations c ON c.request_id = r.id
"""


def _expire_pending_requests():
    """Mark stale pending requests as expired before reading or acting."""
    db.execute(
        """
        UPDATE match_requests
        SET status = 'expired', responded_at = UTC_TIMESTAMP(), pending_key = NULL
        WHERE status = 'pending' AND expires_at < UTC_TIMESTAMP()
        """
    )


def _json_object(value):
    """Read a JSON object from MySQL, tolerating NULL and old rows."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def _account_summary(user_id):
    """Small public user card used by requests and conversations."""
    row = db.query_one(
        """
        SELECT u.id, u.role, u.name, p.photo_url, p.verified_at
        FROM users u
        LEFT JOIN profiles p ON p.user_id = u.id
        WHERE u.id = %s AND u.status = 'active'
        """,
        (user_id,),
    )
    if not row:
        return None
    return {
        "id": row["id"],
        "role": row["role"],
        "name": row["name"],
        "photoUrl": row["photo_url"],
        "verified": row["verified_at"] is not None,
    }


def _block_direction(user_id, other_id):
    """Return (blocked_by_me, blocked_by_other) for one pair."""
    if not user_id or not other_id or user_id == other_id:
        return False, False
    rows = db.query_all(
        """
        SELECT blocker_id, blocked_id
        FROM blocks
        WHERE (blocker_id = %s AND blocked_id = %s)
           OR (blocker_id = %s AND blocked_id = %s)
        """,
        (user_id, other_id, other_id, user_id),
    )
    blocked_by_me = any(row["blocker_id"] == user_id for row in rows)
    blocked_by_other = any(row["blocker_id"] == other_id for row in rows)
    return blocked_by_me, blocked_by_other


def _block_exists(user_id, other_id):
    """True when either user has blocked the other one."""
    blocked_by_me, blocked_by_other = _block_direction(user_id, other_id)
    return blocked_by_me or blocked_by_other


def _blocked_user_ids(user_id):
    """All user IDs hidden from this viewer in either block direction."""
    rows = db.query_all(
        """
        SELECT blocked_id AS user_id FROM blocks WHERE blocker_id = %s
        UNION
        SELECT blocker_id AS user_id FROM blocks WHERE blocked_id = %s
        """,
        (user_id, user_id),
    )
    return {row["user_id"] for row in rows}


def _clean_analytics_payload(value, depth=0):
    """Drop sensitive keys and cap the size of an analytics payload."""
    if depth > 3:
        return None
    if isinstance(value, dict):
        cleaned = {}
        for key, item in list(value.items())[:30]:
            key_text = str(key).strip()[:60]
            if not key_text or key_text.lower() in ANALYTICS_FORBIDDEN_KEYS:
                continue
            item = _clean_analytics_payload(item, depth + 1)
            if item is not None:
                cleaned[key_text] = item
        return cleaned
    if isinstance(value, list):
        return [
            item
            for item in (
                _clean_analytics_payload(entry, depth + 1)
                for entry in value[:20]
            )
            if item is not None
        ]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:200]
    return None


def _record_analytics(name, payload=None, user_id=None):
    """Best-effort analytics insert; never break the user's action."""
    if name not in ANALYTICS_EVENTS:
        return
    cleaned = _clean_analytics_payload(payload or {})
    try:
        encoded = json.dumps(cleaned, ensure_ascii=False)
    except (TypeError, ValueError):
        return
    if len(encoded.encode("utf-8")) > ANALYTICS_PAYLOAD_MAX_BYTES:
        return
    try:
        db.execute(
            """
            INSERT INTO analytics_events (user_id, name, payload)
            VALUES (%s, %s, %s)
            """,
            (user_id, name, encoded),
        )
    except Exception:
        # Analytics must never block requests, messages, or safety actions.
        pass


def _parse_datetime_value(value):
    """Parse an ISO datetime and normalize it to naive UTC."""
    text = str(value or "").strip()
    if not text:
        return None, "Choose a date and time."
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, "Choose a valid date and time."
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed, None


def _session_time_text(value):
    """Short UTC timestamp used inside system messages."""
    if not isinstance(value, datetime):
        return ""
    return value.strftime("%b %d, %Y %I:%M %p UTC")


def _insert_system_message(cursor, conversation_id, body, now):
    """Append a system message and move the conversation preview forward."""
    cursor.execute(
        """
        INSERT INTO messages (conversation_id, sender_id, type, body)
        VALUES (%s, NULL, 'system', %s)
        """,
        (conversation_id, body),
    )
    cursor.execute(
        "UPDATE conversations SET last_message_at = %s WHERE id = %s",
        (now, conversation_id),
    )


def _notify_user(cursor, user_id, notification_type, payload):
    """Insert one lightweight notification inside an existing transaction."""
    cursor.execute(
        """
        INSERT INTO notifications (user_id, type, payload)
        VALUES (%s, %s, %s)
        """,
        (user_id, notification_type, json.dumps(payload)),
    )


def _session_row(session_id):
    return db.query_one(
        """
        SELECT sp.*, u.name AS proposed_by_name
        FROM session_proposals sp
        JOIN users u ON u.id = sp.proposed_by
        WHERE sp.id = %s
        """,
        (session_id,),
    )


def _session_payload(row):
    """Serialize a session proposal without exposing private profile data."""
    if not row:
        return None
    return {
        "id": row["id"],
        "conversationId": row.get("conversation_id"),
        "proposedBy": row.get("proposed_by"),
        "proposedByName": row.get("proposed_by_name"),
        "startsAt": _datetime_text(row.get("starts_at")),
        "durationMins": row.get("duration_mins"),
        "format": row.get("format"),
        "location": row.get("location_text"),
        "note": row.get("note"),
        "status": row.get("status"),
        "createdAt": _datetime_text(row.get("created_at")),
        "respondedAt": _datetime_text(row.get("responded_at")),
    }


def _parse_request_slots(value):
    """Validate preferredSlots from a request body."""
    if value is None or value == "":
        return [], None
    if not isinstance(value, list):
        return [], "Choose valid availability."
    result = []
    for item in value[:8]:
        if not isinstance(item, dict):
            return [], "Choose valid availability."
        day = str(item.get("day") or "").strip().lower()
        start = str(item.get("start") or "").strip()
        end = str(item.get("end") or "").strip()
        start_minutes = _to_minutes(start)
        end_minutes = _to_minutes(end)
        if (
            day not in DAY_INDEX
            or start_minutes is None
            or end_minutes is None
            or start_minutes >= end_minutes
        ):
            return [], "Choose valid availability."
        result.append({"day": day, "start": start, "end": end})
    return result, None


def _fetch_request_row(request_id):
    return db.query_one(REQUEST_SELECT + " WHERE r.id = %s", (request_id,))


def _request_payload(row, viewer_id):
    """Serialize a request row with privacy-safe participant cards."""
    direction = "incoming" if row["to_user_id"] == viewer_id else "outgoing"
    subject = None
    if row.get("subject_id"):
        subject = {
            "id": row["subject_id"],
            "name": row.get("subject_name") or row["subject_id"],
        }
    return {
        "id": row["id"],
        "direction": direction,
        "from": {
            "id": row["from_user_id"],
            "name": row["from_name"],
            "photoUrl": row.get("from_photo_url"),
            "role": row["from_role"],
        },
        "to": {
            "id": row["to_user_id"],
            "name": row["to_name"],
            "photoUrl": row.get("to_photo_url"),
            "role": row["to_role"],
        },
        "subject": subject,
        "message": row.get("message"),
        "preferredSlots": _json_list(row.get("preferred_slots")),
        "format": row.get("format"),
        "status": row["status"],
        "createdAt": _datetime_text(row.get("created_at")),
        "respondedAt": _datetime_text(row.get("responded_at")),
        "expiresAt": _datetime_text(row.get("expires_at")),
        "conversationId": row.get("conversation_id"),
    }


def _conversation_row(conversation_id):
    return db.query_one(
        """
        SELECT c.*, r.status AS request_status, r.subject_id,
               s.name AS subject_name
        FROM conversations c
        JOIN match_requests r ON r.id = c.request_id
        LEFT JOIN subjects s ON s.id = r.subject_id
        WHERE c.id = %s
        """,
        (conversation_id,),
    )


def _conversation_for_user(conversation_id, user_id):
    row = _conversation_row(conversation_id)
    if not row:
        return None
    if row["user_a_id"] != user_id and row["user_b_id"] != user_id:
        return None
    return row


def _other_user_id(conversation, user_id):
    if conversation["user_a_id"] == user_id:
        return conversation["user_b_id"]
    return conversation["user_a_id"]


def _message_payload(row):
    return {
        "id": row["id"],
        "conversationId": row["conversation_id"],
        "senderId": row.get("sender_id"),
        "type": row["type"],
        "body": row.get("body"),
        "createdAt": _datetime_text(row.get("created_at")),
        "readAt": _datetime_text(row.get("read_at")),
    }


def _notification_payload(row):
    return {
        "id": row["id"],
        "type": row["type"],
        "payload": _json_object(row.get("payload")),
        "readAt": _datetime_text(row.get("read_at")),
        "createdAt": _datetime_text(row.get("created_at")),
    }


def _latest_session_payload(conversation_id):
    row = db.query_one(
        """
        SELECT sp.*, u.name AS proposed_by_name
        FROM session_proposals sp
        JOIN users u ON u.id = sp.proposed_by
        WHERE sp.conversation_id = %s
        ORDER BY sp.created_at DESC, sp.id DESC
        LIMIT 1
        """,
        (conversation_id,),
    )
    return _session_payload(row)


def _conversation_payload(row, viewer_id):
    other_id = _other_user_id(row, viewer_id)
    blocked_by_me, blocked_by_other = _block_direction(viewer_id, other_id)
    other = _account_summary(other_id)
    last_message = db.query_one(
        """
        SELECT id, type, body, sender_id, created_at
        FROM messages
        WHERE conversation_id = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (row["id"],),
    )
    unread = db.query_one(
        """
        SELECT COUNT(*) AS total
        FROM messages
        WHERE conversation_id = %s
          AND sender_id IS NOT NULL
          AND sender_id <> %s
          AND read_at IS NULL
        """,
        (row["id"], viewer_id),
    )
    preview = None
    if last_message:
        preview = (last_message.get("body") or "").strip()
        if len(preview) > 90:
            preview = preview[:87] + "..."
    return {
        "id": row["id"],
        "status": row["status"],
        "otherUser": other,
        "subject": (
            {"id": row["subject_id"], "name": row.get("subject_name") or row["subject_id"]}
            if row.get("subject_id")
            else None
        ),
        "lastMessage": (
            {
                "id": last_message["id"],
                "type": last_message["type"],
                "preview": preview,
                "senderId": last_message.get("sender_id"),
                "createdAt": _datetime_text(last_message.get("created_at")),
            }
            if last_message
            else None
        ),
        "unreadCount": unread["total"] if unread else 0,
        "blockedByMe": blocked_by_me,
        "blockedByOther": blocked_by_other,
        "readOnly": row["status"] != "active" or blocked_by_me or blocked_by_other,
        "lastMessageAt": _datetime_text(
            row.get("last_message_at")
            or (last_message and last_message.get("created_at"))
            or row.get("created_at")
        ),
    }


def _pagination(default_limit, max_limit):
    page, page_error = _parse_int_arg("page", 1, 1)
    if page_error:
        return None, None, validation_error({"page": page_error})
    limit, limit_error = _parse_int_arg("limit", default_limit, 1, max_limit)
    if limit_error:
        return None, None, validation_error({"limit": limit_error})
    return page, limit, None


@app.post("/api/requests")
@login_required
def create_request():
    """Create one pending introduction request."""
    _expire_pending_requests()
    user_id = session["user_id"]
    user = fetch_user_by_id(user_id)
    if not user:
        return json_error("UNAUTHORIZED", "Please log in again.", 401)

    data = json_body()
    fields = {}
    raw_to = data.get("toUserId", data.get("to_user_id"))
    try:
        to_user_id = int(raw_to)
    except (TypeError, ValueError):
        fields["toUserId"] = "Choose a valid person."
        return validation_error(fields)

    if to_user_id == user_id:
        return validation_error({"toUserId": "You cannot request yourself."})

    to_user = fetch_user_by_id(to_user_id)
    if not to_user or to_user["status"] != "active":
        return json_error("NOT_FOUND", "That account was not found.", 404)
    if to_user["role"] == user["role"]:
        return validation_error(
            {"toUserId": "Students request tutors, and tutors request students."}
        )
    if _block_exists(user_id, to_user_id):
        return json_error(
            "BLOCKED",
            "You cannot send a request while a block is active.",
            403,
        )

    my_profile = get_profile_payload(user_id)
    to_profile = get_profile_payload(to_user_id)
    if not my_profile or not my_profile["requiredComplete"]:
        return json_error(
            "PROFILE_INCOMPLETE",
            "Complete your profile before sending requests.",
            400,
        )
    if not to_profile or not to_profile["requiredComplete"]:
        return json_error(
            "PROFILE_INCOMPLETE",
            "This profile is not ready for requests yet.",
            400,
        )

    subject_id = str(data.get("subjectId") or "").strip() or None
    subject = None
    if subject_id:
        subject = db.query_one(
            "SELECT id, name FROM subjects WHERE id = %s",
            (subject_id,),
        )
        if not subject:
            fields["subjectId"] = "Choose a valid subject."
    elif to_profile.get("subjects"):
        subject = to_profile["subjects"][0]
        subject_id = subject["id"]
    if fields:
        return validation_error(fields)

    message = str(data.get("message") or "").strip()
    if len(message) > REQUEST_MESSAGE_MAX_LENGTH:
        fields["message"] = (
            f"Keep the introduction under {REQUEST_MESSAGE_MAX_LENGTH} characters."
        )

    requested_format = str(data.get("format") or "").strip() or None
    if requested_format and requested_format not in PROFILE_FORMATS:
        fields["format"] = "Choose a valid format."
    if not requested_format:
        requested_format = to_profile.get("format")

    preferred_slots, slot_error = _parse_request_slots(
        data.get("preferredSlots", data.get("preferred_slots"))
    )
    if slot_error:
        fields["preferredSlots"] = slot_error
    if fields:
        return validation_error(fields)

    pending = db.query_one(
        """
        SELECT id
        FROM match_requests
        WHERE status = 'pending'
          AND (
            (from_user_id = %s AND to_user_id = %s)
            OR (from_user_id = %s AND to_user_id = %s)
          )
        LIMIT 1
        """,
        (user_id, to_user_id, to_user_id, user_id),
    )
    if pending:
        return json_error(
            "CONFLICT",
            "You already have a pending request with this person.",
            409,
        )

    if is_rate_limited(
        "request_sent",
        REQUEST_DAILY_LIMIT,
        24 * 60 * 60,
        user_id=user_id,
    ):
        return json_error(
            "RATE_LIMITED",
            "You have sent too many requests today. Try again tomorrow.",
            429,
        )

    now = now_utc()
    expires_at = now + timedelta(days=REQUEST_EXPIRY_DAYS)
    request_id = None
    with db.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO match_requests
                    (from_user_id, to_user_id, subject_id, message,
                     preferred_slots, format, status, pending_key, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, %s)
                """,
                (
                    user_id,
                    to_user_id,
                    subject_id,
                    message or None,
                    json.dumps(preferred_slots) if preferred_slots else None,
                    requested_format,
                    f"{user_id}-{to_user_id}",
                    expires_at,
                ),
            )
            request_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO notifications (user_id, type, payload)
                VALUES (%s, 'request_received', %s)
                """,
                (
                    to_user_id,
                    json.dumps({
                        "requestId": request_id,
                        "fromUserId": user_id,
                        "fromName": user["name"],
                        "subjectId": subject_id,
                        "subjectName": subject["name"] if subject else None,
                    }),
                ),
            )

    log_event("request_sent", user_id=user_id, details=f"request {request_id}")
    _record_analytics(
        "request_sent",
        {
            "requestId": request_id,
            "toUserId": to_user_id,
            "subjectId": subject_id,
            "format": requested_format,
        },
        user_id=user_id,
    )
    return jsonify({"request": _request_payload(_fetch_request_row(request_id), user_id)}), 201


@app.get("/api/requests")
@login_required
def list_requests():
    """List incoming or outgoing requests with pagination."""
    _expire_pending_requests()
    user_id = session["user_id"]
    box = str(request.args.get("box") or "incoming").strip().lower()
    if box not in ("incoming", "outgoing"):
        return validation_error({"box": "Choose incoming or outgoing."})

    status = str(request.args.get("status") or "").strip().lower() or None
    if status and status not in REQUEST_STATUSES:
        return validation_error({"status": "Choose a valid request status."})

    page, limit, error = _pagination(10, 50)
    if error:
        return error

    where = ["r.to_user_id = %s" if box == "incoming" else "r.from_user_id = %s"]
    params = [user_id]
    if status:
        where.append("r.status = %s")
        params.append(status)
    where_sql = " AND ".join(where)

    total_row = db.query_one(
        f"SELECT COUNT(*) AS total FROM match_requests r WHERE {where_sql}",
        tuple(params),
    )
    rows = db.query_all(
        REQUEST_SELECT + f" WHERE {where_sql} ORDER BY r.created_at DESC, r.id DESC LIMIT %s OFFSET %s",
        tuple(params + [limit, (page - 1) * limit]),
    )
    return jsonify({
        "total": total_row["total"] if total_row else 0,
        "page": page,
        "limit": limit,
        "requests": [_request_payload(row, user_id) for row in rows],
    })


@app.patch("/api/requests/<int:request_id>")
@login_required
def update_request(request_id):
    """Accept, decline, or cancel a pending request."""
    _expire_pending_requests()
    user_id = session["user_id"]
    row = _fetch_request_row(request_id)
    if not row:
        return json_error("NOT_FOUND", "Request not found.", 404)

    is_from = row["from_user_id"] == user_id
    is_to = row["to_user_id"] == user_id
    if not is_from and not is_to:
        return json_error("FORBIDDEN", "You cannot change this request.", 403)

    data = json_body()
    action = str(data.get("action") or "").strip().lower()
    if action not in REQUEST_ACTIONS:
        return validation_error({"action": "Choose accept, decline, or cancel."})
    if action in ("accept", "decline") and not is_to:
        return json_error("FORBIDDEN", "Only the recipient can respond.", 403)
    if action == "cancel" and not is_from:
        return json_error("FORBIDDEN", "Only the sender can cancel.", 403)
    if action == "accept" and _block_exists(row["from_user_id"], row["to_user_id"]):
        return json_error(
            "BLOCKED",
            "This request cannot be accepted while a block is active.",
            403,
        )
    if row["status"] != "pending":
        return json_error("CONFLICT", "This request is no longer pending.", 409)

    now = now_utc()
    conversation_id = None
    conflict = False

    if action == "accept":
        with db.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE match_requests
                    SET status = 'accepted', responded_at = %s, pending_key = NULL
                    WHERE id = %s AND status = 'pending'
                    """,
                    (now, request_id),
                )
                if cursor.rowcount != 1:
                    conflict = True
                else:
                    cursor.execute(
                        "SELECT id FROM conversations WHERE request_id = %s",
                        (request_id,),
                    )
                    existing = cursor.fetchone()
                    if existing:
                        conversation_id = existing["id"]
                    else:
                        cursor.execute(
                            """
                            INSERT INTO conversations
                                (request_id, user_a_id, user_b_id, status, last_message_at)
                            VALUES (%s, %s, %s, 'active', %s)
                            """,
                            (request_id, row["from_user_id"], row["to_user_id"], now),
                        )
                        conversation_id = cursor.lastrowid
                        cursor.execute(
                            """
                            INSERT INTO messages
                                (conversation_id, sender_id, type, body)
                            VALUES (%s, NULL, 'system', %s)
                            """,
                            (
                                conversation_id,
                                "Request accepted. You can now chat.",
                            ),
                        )
                    cursor.execute(
                        """
                        INSERT INTO notifications (user_id, type, payload)
                        VALUES (%s, 'request_accepted', %s)
                        """,
                        (
                            row["from_user_id"],
                            json.dumps({
                                "requestId": request_id,
                                "conversationId": conversation_id,
                                "acceptedBy": row["to_name"],
                                "actorName": row["to_name"],
                            }),
                        ),
                    )
        if conflict:
            return json_error("CONFLICT", "This request is no longer pending.", 409)
        log_event("request_accepted", user_id=user_id, details=f"request {request_id}")
        _record_analytics(
            "request_accepted",
            {
                "requestId": request_id,
                "conversationId": conversation_id,
                "subjectId": row.get("subject_id"),
            },
            user_id=user_id,
        )
    else:
        new_status = "declined" if action == "decline" else "cancelled"
        notify_user_id = (
            row["from_user_id"] if action == "decline" else row["to_user_id"]
        )
        notification_type = (
            "request_declined" if action == "decline" else "request_cancelled"
        )
        with db.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE match_requests
                    SET status = %s, responded_at = %s, pending_key = NULL
                    WHERE id = %s AND status = 'pending'
                    """,
                    (new_status, now, request_id),
                )
                if cursor.rowcount != 1:
                    conflict = True
                else:
                    cursor.execute(
                        """
                        INSERT INTO notifications (user_id, type, payload)
                        VALUES (%s, %s, %s)
                        """,
                        (
                            notify_user_id,
                            notification_type,
                            json.dumps({
                                "requestId": request_id,
                                "status": new_status,
                                "actorName": (
                                    row["to_name"]
                                    if action == "decline"
                                    else row["from_name"]
                                ),
                            }),
                        ),
                    )
        if conflict:
            return json_error("CONFLICT", "This request is no longer pending.", 409)
        log_event(
            f"request_{new_status}",
            user_id=user_id,
            details=f"request {request_id}",
        )
        _record_analytics(
            f"request_{new_status}",
            {"requestId": request_id, "subjectId": row.get("subject_id")},
            user_id=user_id,
        )

    # Opening/responding to a request clears its request notification.
    db.execute(
        """
        UPDATE notifications
        SET read_at = UTC_TIMESTAMP()
        WHERE user_id = %s
          AND read_at IS NULL
          AND type = 'request_received'
          AND JSON_UNQUOTE(JSON_EXTRACT(payload, '$.requestId')) = %s
        """,
        (user_id, str(request_id)),
    )

    fresh = _fetch_request_row(request_id)
    return jsonify({
        "request": _request_payload(fresh, user_id),
        "conversationId": conversation_id or fresh.get("conversation_id"),
    })


@app.get("/api/conversations")
@login_required
def list_conversations():
    """List conversations for the current participant."""
    user_id = session["user_id"]
    page, limit, error = _pagination(20, 50)
    if error:
        return error

    total_row = db.query_one(
        """
        SELECT COUNT(*) AS total
        FROM conversations
        WHERE user_a_id = %s OR user_b_id = %s
        """,
        (user_id, user_id),
    )
    rows = db.query_all(
        """
        SELECT c.*, r.status AS request_status, r.subject_id,
               s.name AS subject_name
        FROM conversations c
        JOIN match_requests r ON r.id = c.request_id
        LEFT JOIN subjects s ON s.id = r.subject_id
        WHERE c.user_a_id = %s OR c.user_b_id = %s
        ORDER BY COALESCE(c.last_message_at, c.created_at) DESC, c.id DESC
        LIMIT %s OFFSET %s
        """,
        (user_id, user_id, limit, (page - 1) * limit),
    )
    return jsonify({
        "total": total_row["total"] if total_row else 0,
        "page": page,
        "limit": limit,
        "conversations": [
            _conversation_payload(row, user_id)
            for row in rows
        ],
    })


@app.get("/api/conversations/<int:conversation_id>")
@login_required
def get_conversation(conversation_id):
    """Return one conversation with participants and latest session."""
    user_id = session["user_id"]
    row = _conversation_for_user(conversation_id, user_id)
    if not row:
        return json_error("NOT_FOUND", "Conversation not found.", 404)

    participant_ids = [row["user_a_id"], row["user_b_id"]]
    participants = [
        account
        for account in (_account_summary(pid) for pid in participant_ids)
        if account
    ]
    other_id = _other_user_id(row, user_id)
    blocked_by_me, blocked_by_other = _block_direction(user_id, other_id)
    return jsonify({
        "conversation": {
            "id": row["id"],
            "status": row["status"],
            "blockedByMe": blocked_by_me,
            "blockedByOther": blocked_by_other,
            "readOnly": (
                row["status"] != "active" or blocked_by_me or blocked_by_other
            ),
            "request": {
                "id": row["request_id"],
                "status": row["request_status"],
                "subject": (
                    {
                        "id": row["subject_id"],
                        "name": row.get("subject_name") or row["subject_id"],
                    }
                    if row.get("subject_id")
                    else None
                ),
            },
            "participants": participants,
            "latestSession": _latest_session_payload(row["id"]),
            "lastMessageAt": _datetime_text(row.get("last_message_at")),
            "createdAt": _datetime_text(row.get("created_at")),
        }
    })


@app.get("/api/conversations/<int:conversation_id>/messages")
@login_required
def list_messages(conversation_id):
    """Return a page of messages, newest page first internally."""
    user_id = session["user_id"]
    conversation = _conversation_for_user(conversation_id, user_id)
    if not conversation:
        return json_error("NOT_FOUND", "Conversation not found.", 404)

    before = request.args.get("before")
    before_id = None
    if before not in (None, ""):
        try:
            before_id = int(str(before).strip())
        except (TypeError, ValueError):
            return validation_error({"before": "Choose a valid message."})

    limit, limit_error = _parse_int_arg("limit", 30, 1, 100)
    if limit_error:
        return validation_error({"limit": limit_error})

    params = [conversation_id]
    before_sql = ""
    if before_id is not None:
        before_sql = " AND id < %s"
        params.append(before_id)
    rows = db.query_all(
        f"""
        SELECT id, conversation_id, sender_id, type, body, created_at, read_at
        FROM messages
        WHERE conversation_id = %s{before_sql}
        ORDER BY id DESC
        LIMIT %s
        """,
        tuple(params + [limit + 1]),
    )
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    rows.reverse()
    return jsonify({
        "messages": [_message_payload(row) for row in rows],
        "hasMore": has_more,
    })


@app.post("/api/conversations/<int:conversation_id>/messages")
@login_required
def send_message(conversation_id):
    """Send a text message. Chat must be active."""
    user_id = session["user_id"]
    conversation = _conversation_for_user(conversation_id, user_id)
    if not conversation:
        return json_error("NOT_FOUND", "Conversation not found.", 404)
    if conversation["status"] != "active":
        return json_error("CHAT_LOCKED", "This conversation is not open.", 403)
    other_id = _other_user_id(conversation, user_id)
    if _block_exists(user_id, other_id):
        return json_error(
            "BLOCKED",
            "This conversation is read-only while a block is active.",
            403,
        )

    data = json_body()
    message_type = str(data.get("type") or "text").strip().lower()
    if message_type != "text":
        return validation_error(
            {"type": "Only text messages are supported in V1."}
        )
    body = str(data.get("body") or "").strip()
    if not body:
        return validation_error({"body": "Write a message first."})
    if len(body) > MESSAGE_MAX_LENGTH:
        return validation_error(
            {"body": f"Keep messages under {MESSAGE_MAX_LENGTH} characters."}
        )

    if is_rate_limited(
        "message_sent",
        MESSAGE_RATE_LIMIT,
        MESSAGE_RATE_WINDOW_SECONDS,
        user_id=user_id,
    ):
        return json_error(
            "RATE_LIMITED",
            "You are sending messages too quickly. Try again shortly.",
            429,
        )

    sender = fetch_user_by_id(user_id)
    now = now_utc()
    message_id = None
    with db.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO messages (conversation_id, sender_id, type, body)
                VALUES (%s, %s, 'text', %s)
                """,
                (conversation_id, user_id, body),
            )
            message_id = cursor.lastrowid
            cursor.execute(
                "UPDATE conversations SET last_message_at = %s WHERE id = %s",
                (now, conversation_id),
            )
            cursor.execute(
                """
                INSERT INTO notifications (user_id, type, payload)
                VALUES (%s, 'message_received', %s)
                """,
                (
                    other_id,
                    json.dumps({
                        "conversationId": conversation_id,
                        "messageId": message_id,
                        "senderId": user_id,
                        "senderName": sender["name"] if sender else None,
                        "actorName": sender["name"] if sender else None,
                        "preview": body[:120],
                    }),
                ),
            )

    log_event("message_sent", user_id=user_id, details=f"conversation {conversation_id}")
    _record_analytics(
        "message_sent",
        {"conversationId": conversation_id, "length": len(body)},
        user_id=user_id,
    )
    message = db.query_one(
        """
        SELECT id, conversation_id, sender_id, type, body, created_at, read_at
        FROM messages
        WHERE id = %s
        """,
        (message_id,),
    )
    return jsonify({"message": _message_payload(message)}), 201


@app.patch("/api/conversations/<int:conversation_id>/read")
@login_required
def mark_conversation_read(conversation_id):
    """Mark messages from the other participant as read."""
    user_id = session["user_id"]
    conversation = _conversation_for_user(conversation_id, user_id)
    if not conversation:
        return json_error("NOT_FOUND", "Conversation not found.", 404)

    data = json_body()
    last_message_id = data.get("lastMessageId")
    now = now_utc()
    params = [now, conversation_id, user_id]
    last_sql = ""
    if last_message_id not in (None, ""):
        try:
            last_id = int(last_message_id)
        except (TypeError, ValueError):
            return validation_error({"lastMessageId": "Choose a valid message."})
        last_sql = " AND id <= %s"
        params.append(last_id)
    db.execute(
        f"""
        UPDATE messages
        SET read_at = %s
        WHERE conversation_id = %s
          AND sender_id IS NOT NULL
          AND sender_id <> %s
          AND read_at IS NULL{last_sql}
        """,
        tuple(params),
    )
    db.execute(
        """
        UPDATE notifications
        SET read_at = %s
        WHERE user_id = %s
          AND read_at IS NULL
          AND type IN ('message_received', 'request_accepted')
          AND JSON_UNQUOTE(JSON_EXTRACT(payload, '$.conversationId')) = %s
        """,
        (now, user_id, str(conversation_id)),
    )
    return "", 204


@app.get("/api/notifications")
@login_required
def list_notifications():
    """Return in-app notifications and the unread count."""
    user_id = session["user_id"]
    unread_only = str(request.args.get("unread") or "").lower() in (
        "1", "true", "yes", "on"
    )
    page, limit, error = _pagination(20, 50)
    if error:
        return error

    where = ["user_id = %s"]
    params = [user_id]
    if unread_only:
        where.append("read_at IS NULL")
    where_sql = " AND ".join(where)

    total_row = db.query_one(
        f"SELECT COUNT(*) AS total FROM notifications WHERE {where_sql}",
        tuple(params),
    )
    unread_row = db.query_one(
        """
        SELECT COUNT(*) AS total
        FROM notifications
        WHERE user_id = %s AND read_at IS NULL
        """,
        (user_id,),
    )
    rows = db.query_all(
        f"""
        SELECT id, type, payload, read_at, created_at
        FROM notifications
        WHERE {where_sql}
        ORDER BY created_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        tuple(params + [limit, (page - 1) * limit]),
    )
    unread_count = unread_row["total"] if unread_row else 0
    return jsonify({
        "total": total_row["total"] if total_row else 0,
        "unread": unread_count,
        "unreadCount": unread_count,
        "page": page,
        "limit": limit,
        "notifications": [_notification_payload(row) for row in rows],
    })


@app.patch("/api/notifications/<int:notification_id>/read")
@login_required
def mark_notification_read(notification_id):
    """Mark one notification as read."""
    db.execute(
        """
        UPDATE notifications
        SET read_at = UTC_TIMESTAMP()
        WHERE id = %s AND user_id = %s AND read_at IS NULL
        """,
        (notification_id, session["user_id"]),
    )
    return "", 204


@app.patch("/api/notifications/read-all")
@login_required
def mark_all_notifications_read():
    """Mark every notification for the current user as read."""
    db.execute(
        """
        UPDATE notifications
        SET read_at = UTC_TIMESTAMP()
        WHERE user_id = %s AND read_at IS NULL
        """,
        (session["user_id"],),
    )
    return "", 204


# ============================================================
# Session proposals
# ============================================================
@app.post("/api/sessions")
@login_required
def create_session():
    """Propose a tutoring session inside an open conversation."""
    user_id = session["user_id"]
    user = fetch_user_by_id(user_id)
    if not user:
        return json_error("UNAUTHORIZED", "Please log in again.", 401)

    data = json_body()
    fields = {}
    raw_conversation = data.get("conversationId", data.get("conversation_id"))
    try:
        conversation_id = int(raw_conversation)
    except (TypeError, ValueError):
        return validation_error({"conversationId": "Choose a valid conversation."})

    conversation = _conversation_for_user(conversation_id, user_id)
    if not conversation:
        return json_error("NOT_FOUND", "Conversation not found.", 404)
    if conversation["status"] != "active":
        return json_error(
            "CHAT_LOCKED",
            "Session proposals require an open conversation.",
            403,
        )
    other_id = _other_user_id(conversation, user_id)
    if _block_exists(user_id, other_id):
        return json_error(
            "BLOCKED",
            "This conversation is read-only while a block is active.",
            403,
        )

    starts_at, start_error = _parse_datetime_value(
        data.get("startsAt", data.get("starts_at"))
    )
    now = now_utc()
    if start_error:
        fields["startsAt"] = start_error
    elif starts_at <= now:
        fields["startsAt"] = "Choose a future date and time."

    try:
        duration_mins = int(data.get("durationMins", data.get("duration_mins")))
    except (TypeError, ValueError):
        duration_mins = None
    if duration_mins not in SESSION_DURATIONS:
        fields["durationMins"] = "Choose 30, 60, 90, or 120 minutes."

    session_format = str(data.get("format") or "").strip().lower()
    if session_format not in PROFILE_FORMATS:
        fields["format"] = "Choose a valid session format."

    location = str(data.get("location") or "").strip()
    if len(location) > SESSION_LOCATION_MAX_LENGTH:
        fields["location"] = (
            f"Keep the location under {SESSION_LOCATION_MAX_LENGTH} characters."
        )
    note = str(data.get("note") or "").strip()
    if len(note) > SESSION_NOTE_MAX_LENGTH:
        fields["note"] = f"Keep the note under {SESSION_NOTE_MAX_LENGTH} characters."
    if fields:
        return validation_error(fields)

    pending = db.query_one(
        """
        SELECT id
        FROM session_proposals
        WHERE conversation_id = %s
          AND status IN ('proposed', 'rescheduled')
        LIMIT 1
        """,
        (conversation_id,),
    )
    if pending:
        return json_error(
            "CONFLICT",
            "There is already a session waiting for a response.",
            409,
        )

    session_id = None
    with db.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO session_proposals
                    (conversation_id, proposed_by, starts_at, duration_mins,
                     format, location_text, note, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'proposed')
                """,
                (
                    conversation_id,
                    user_id,
                    starts_at,
                    duration_mins,
                    session_format,
                    location or None,
                    note or None,
                ),
            )
            session_id = cursor.lastrowid
            _notify_user(
                cursor,
                other_id,
                "session_proposed",
                {
                    "sessionId": session_id,
                    "conversationId": conversation_id,
                    "startsAt": _datetime_text(starts_at),
                    "actorName": user["name"],
                    "subjectName": conversation.get("subject_name"),
                },
            )
            _insert_system_message(
                cursor,
                conversation_id,
                f"{user['name']} proposed a session for "
                f"{_session_time_text(starts_at)}.",
                now,
            )

    _record_analytics(
        "session_proposed",
        {
            "sessionId": session_id,
            "conversationId": conversation_id,
            "durationMins": duration_mins,
            "format": session_format,
        },
        user_id=user_id,
    )
    return jsonify({"session": _session_payload(_session_row(session_id))}), 201


@app.get("/api/sessions")
@login_required
def list_sessions():
    """List sessions for the current user, optionally filtered by date."""
    user_id = session["user_id"]
    from_text = (request.args.get("from") or "").strip()
    to_text = (request.args.get("to") or "").strip()
    from_date = None
    to_date = None
    fields = {}
    if from_text:
        try:
            from_date = datetime.strptime(from_text, "%Y-%m-%d").date()
        except ValueError:
            fields["from"] = "Use YYYY-MM-DD."
    if to_text:
        try:
            to_date = datetime.strptime(to_text, "%Y-%m-%d").date()
        except ValueError:
            fields["to"] = "Use YYYY-MM-DD."
    if from_date and to_date and from_date > to_date:
        fields["to"] = "The end date must be after the start date."
    if fields:
        return validation_error(fields)

    where = ["(c.user_a_id = %s OR c.user_b_id = %s)"]
    params = [user_id, user_id]
    if from_date:
        where.append("sp.starts_at >= %s")
        params.append(datetime.combine(from_date, datetime.min.time()))
    if to_date:
        where.append("sp.starts_at <= %s")
        params.append(datetime.combine(to_date, datetime.max.time()))

    rows = db.query_all(
        f"""
        SELECT sp.*, u.name AS proposed_by_name,
               c.user_a_id, c.user_b_id
        FROM session_proposals sp
        JOIN conversations c ON c.id = sp.conversation_id
        JOIN users u ON u.id = sp.proposed_by
        WHERE {' AND '.join(where)}
        ORDER BY sp.starts_at ASC, sp.id DESC
        LIMIT 100
        """,
        tuple(params),
    )
    sessions = []
    for row in rows:
        payload = _session_payload(row)
        other_id = (
            row["user_b_id"] if row["user_a_id"] == user_id else row["user_a_id"]
        )
        payload["otherUser"] = _account_summary(other_id)
        sessions.append(payload)
    return jsonify({"sessions": sessions})


@app.patch("/api/sessions/<int:session_id>")
@login_required
def update_session(session_id):
    """Accept, decline, reschedule, cancel, or complete a session."""
    user_id = session["user_id"]
    user = fetch_user_by_id(user_id)
    if not user:
        return json_error("UNAUTHORIZED", "Please log in again.", 401)

    row = db.query_one(
        """
        SELECT sp.*, u.name AS proposed_by_name,
               c.user_a_id, c.user_b_id
        FROM session_proposals sp
        JOIN conversations c ON c.id = sp.conversation_id
        JOIN users u ON u.id = sp.proposed_by
        WHERE sp.id = %s
        """,
        (session_id,),
    )
    if not row:
        return json_error("NOT_FOUND", "Session not found.", 404)
    if user_id not in (row["user_a_id"], row["user_b_id"]):
        return json_error("NOT_FOUND", "Session not found.", 404)

    data = json_body()
    action = str(data.get("action") or "").strip().lower()
    if action not in SESSION_ACTIONS:
        return validation_error({"action": "Choose a valid session action."})

    other_id = row["user_b_id"] if row["user_a_id"] == user_id else row["user_a_id"]
    if _block_exists(user_id, other_id) and action not in ("decline", "cancel"):
        return json_error(
            "BLOCKED",
            "This conversation is read-only while a block is active.",
            403,
        )

    status = row["status"]
    if action in ("accept", "decline"):
        if row["proposed_by"] == user_id:
            return json_error(
                "FORBIDDEN",
                "Only the other participant can accept or decline.",
                403,
            )
        if status not in ("proposed", "rescheduled"):
            return json_error(
                "CONFLICT",
                "This session is no longer waiting for a response.",
                409,
            )
    elif action == "reschedule":
        if status not in ("proposed", "rescheduled", "accepted"):
            return json_error("CONFLICT", "This session cannot be rescheduled.", 409)
    elif action == "cancel":
        if status in ("cancelled", "completed", "declined"):
            return json_error("CONFLICT", "This session cannot be cancelled.", 409)
    elif action == "complete":
        if status != "accepted":
            return json_error(
                "CONFLICT",
                "Only an accepted session can be completed.",
                409,
            )

    now = now_utc()
    fields = {}
    new_starts_at = row["starts_at"]
    new_duration = row["duration_mins"]
    if action == "reschedule":
        new_starts_at, start_error = _parse_datetime_value(
            data.get("startsAt", data.get("starts_at"))
        )
        if start_error:
            fields["startsAt"] = start_error
        elif new_starts_at <= now:
            fields["startsAt"] = "Choose a future date and time."
        raw_duration = data.get("durationMins", data.get("duration_mins"))
        if raw_duration not in (None, ""):
            try:
                new_duration = int(raw_duration)
            except (TypeError, ValueError):
                new_duration = None
        if new_duration not in SESSION_DURATIONS:
            fields["durationMins"] = "Choose 30, 60, 90, or 120 minutes."
        if fields:
            return validation_error(fields)

    status_map = {
        "accept": "accepted",
        "decline": "declined",
        "reschedule": "rescheduled",
        "cancel": "cancelled",
        "complete": "completed",
    }
    notification_map = {
        "accept": "session_accepted",
        "decline": "session_declined",
        "reschedule": "session_rescheduled",
        "cancel": "session_cancelled",
        "complete": "session_completed",
    }
    new_status = status_map[action]
    message_text = {
        "accept": f"{user['name']} accepted the session.",
        "decline": f"{user['name']} declined the session.",
        "reschedule": (
            f"{user['name']} rescheduled the session to "
            f"{_session_time_text(new_starts_at)}."
        ),
        "cancel": f"{user['name']} cancelled the session.",
        "complete": f"{user['name']} marked the session complete.",
    }[action]

    conflict = False
    with db.transaction() as connection:
        with connection.cursor() as cursor:
            if action == "reschedule":
                cursor.execute(
                    """
                    UPDATE session_proposals
                    SET starts_at = %s, duration_mins = %s,
                        status = %s, responded_at = %s
                    WHERE id = %s AND status = %s
                    """,
                    (
                        new_starts_at,
                        new_duration,
                        new_status,
                        now,
                        session_id,
                        status,
                    ),
                )
            else:
                cursor.execute(
                    """
                    UPDATE session_proposals
                    SET status = %s, responded_at = %s
                    WHERE id = %s AND status = %s
                    """,
                    (new_status, now, session_id, status),
                )
            if cursor.rowcount != 1:
                conflict = True
            else:
                _notify_user(
                    cursor,
                    other_id,
                    notification_map[action],
                    {
                        "sessionId": session_id,
                        "conversationId": row["conversation_id"],
                        "startsAt": _datetime_text(new_starts_at),
                        "actorName": user["name"],
                        "status": new_status,
                    },
                )
                _insert_system_message(
                    cursor,
                    row["conversation_id"],
                    message_text,
                    now,
                )
                cursor.execute(
                    """
                    UPDATE notifications
                    SET read_at = UTC_TIMESTAMP()
                    WHERE user_id = %s
                      AND read_at IS NULL
                      AND JSON_UNQUOTE(
                            JSON_EXTRACT(payload, '$.sessionId')
                          ) = %s
                    """,
                    (user_id, str(session_id)),
                )

    if conflict:
        return json_error("CONFLICT", "This session changed. Refresh and try again.", 409)

    _record_analytics(
        notification_map[action],
        {
            "sessionId": session_id,
            "conversationId": row["conversation_id"],
            "status": new_status,
        },
        user_id=user_id,
    )
    return jsonify({"session": _session_payload(_session_row(session_id))})


# ============================================================
# Reports and blocks
# ============================================================
def _report_response(user_id, data, conversation_id=None, reported_user_id=None):
    """Shared implementation for general and conversation-specific reports."""
    fields = {}
    if reported_user_id is None:
        raw_reported = data.get("reportedUserId", data.get("reported_user_id"))
        try:
            reported_user_id = int(raw_reported)
        except (TypeError, ValueError):
            return validation_error({"reportedUserId": "Choose a valid person."})

    if reported_user_id == user_id:
        return validation_error({"reportedUserId": "You cannot report yourself."})
    target = fetch_user_by_id(reported_user_id)
    if not target or target["status"] != "active":
        return json_error("NOT_FOUND", "That account was not found.", 404)
    if _block_exists(user_id, reported_user_id):
        return json_error(
            "BLOCKED",
            "You cannot report this person while a block is active.",
            403,
        )

    reason = str(data.get("reason") or "").strip().lower()
    if reason not in REPORT_REASONS:
        fields["reason"] = "Choose a valid report reason."
    details = str(data.get("details") or "").strip()
    if len(details) > REPORT_DETAILS_MAX_LENGTH:
        fields["details"] = (
            f"Keep the details under {REPORT_DETAILS_MAX_LENGTH} characters."
        )

    if conversation_id is None:
        raw_conversation = data.get("conversationId", data.get("conversation_id"))
        if raw_conversation not in (None, ""):
            try:
                requested_conversation_id = int(raw_conversation)
            except (TypeError, ValueError):
                fields["conversationId"] = "Choose a valid conversation."
            else:
                conversation = _conversation_for_user(
                    requested_conversation_id, user_id
                )
                if not conversation:
                    return json_error("NOT_FOUND", "Conversation not found.", 404)
                other_id = _other_user_id(conversation, user_id)
                if other_id != reported_user_id:
                    fields["reportedUserId"] = (
                        "Choose the other participant in this conversation."
                    )
                conversation_id = requested_conversation_id
    else:
        conversation = _conversation_for_user(conversation_id, user_id)
        if not conversation:
            return json_error("NOT_FOUND", "Conversation not found.", 404)
        if _other_user_id(conversation, user_id) != reported_user_id:
            fields["reportedUserId"] = (
                "Choose the other participant in this conversation."
            )

    if fields:
        return validation_error(fields)

    report_id = db.execute(
        """
        INSERT INTO reports
            (reporter_id, reported_user_id, reason, details,
             conversation_id, status)
        VALUES (%s, %s, %s, %s, %s, 'open')
        """,
        (
            user_id,
            reported_user_id,
            reason,
            details or None,
            conversation_id,
        ),
    )
    _record_analytics(
        "report_submitted",
        {
            "reportId": report_id,
            "reason": reason,
            "conversationId": conversation_id,
        },
        user_id=user_id,
    )
    return jsonify({"reportId": report_id, "status": "open"}), 201


@app.post("/api/reports")
@login_required
def create_report():
    """File a private safety report."""
    return _report_response(session["user_id"], json_body())


@app.post("/api/conversations/<int:conversation_id>/report")
@login_required
def report_conversation(conversation_id):
    """File a report about the other participant in a conversation."""
    user_id = session["user_id"]
    conversation = _conversation_for_user(conversation_id, user_id)
    if not conversation:
        return json_error("NOT_FOUND", "Conversation not found.", 404)
    other_id = _other_user_id(conversation, user_id)
    return _report_response(
        user_id,
        json_body(),
        conversation_id=conversation_id,
        reported_user_id=other_id,
    )


def _block_response(user_id, other_id):
    """Block one user and make all shared conversations read-only."""
    if other_id == user_id:
        return validation_error({"userId": "You cannot block yourself."})
    target = fetch_user_by_id(other_id)
    if not target or target["status"] != "active":
        return json_error("NOT_FOUND", "That account was not found.", 404)

    now = now_utc()
    db.execute(
        "INSERT IGNORE INTO blocks (blocker_id, blocked_id) VALUES (%s, %s)",
        (user_id, other_id),
    )
    with db.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE conversations
                SET status = 'blocked'
                WHERE status = 'active'
                  AND (
                    (user_a_id = %s AND user_b_id = %s)
                    OR (user_a_id = %s AND user_b_id = %s)
                  )
                """,
                (user_id, other_id, other_id, user_id),
            )
            cursor.execute(
                """
                UPDATE match_requests
                SET status = 'cancelled', responded_at = %s, pending_key = NULL
                WHERE status = 'pending'
                  AND (
                    (from_user_id = %s AND to_user_id = %s)
                    OR (from_user_id = %s AND to_user_id = %s)
                  )
                """,
                (now, user_id, other_id, other_id, user_id),
            )
    _record_analytics(
        "block_created",
        {"blockedUserId": other_id},
        user_id=user_id,
    )
    return "", 204


@app.post("/api/blocks/<int:user_id>")
@login_required
def block_user(user_id):
    """Block a user by account ID."""
    return _block_response(session["user_id"], user_id)


@app.post("/api/conversations/<int:conversation_id>/block")
@login_required
def block_conversation(conversation_id):
    """Block the other participant in a conversation."""
    user_id = session["user_id"]
    conversation = _conversation_for_user(conversation_id, user_id)
    if not conversation:
        return json_error("NOT_FOUND", "Conversation not found.", 404)
    return _block_response(user_id, _other_user_id(conversation, user_id))


@app.delete("/api/blocks/<int:user_id>")
@login_required
def unblock_user(user_id):
    """Remove a block and reopen shared conversations when safe."""
    user_id_current = session["user_id"]
    if user_id == user_id_current:
        return validation_error({"userId": "You cannot unblock yourself."})
    deleted = db.execute(
        "DELETE FROM blocks WHERE blocker_id = %s AND blocked_id = %s",
        (user_id_current, user_id),
    )
    del deleted
    other_block = db.query_one(
        """
        SELECT 1 AS blocked
        FROM blocks
        WHERE blocker_id = %s AND blocked_id = %s
        """,
        (user_id, user_id_current),
    )
    if not other_block:
        db.execute(
            """
            UPDATE conversations
            SET status = 'active'
            WHERE status = 'blocked'
              AND (
                (user_a_id = %s AND user_b_id = %s)
                OR (user_a_id = %s AND user_b_id = %s)
              )
            """,
            (user_id_current, user_id, user_id, user_id_current),
        )
    _record_analytics(
        "block_removed",
        {"blockedUserId": user_id},
        user_id=user_id_current,
    )
    return "", 204


@app.get("/api/blocks")
@login_required
def list_blocks():
    """Return only the current user's private blocked list."""
    rows = db.query_all(
        """
        SELECT b.blocked_id, b.created_at, u.role, u.name, p.photo_url
        FROM blocks b
        JOIN users u ON u.id = b.blocked_id
        LEFT JOIN profiles p ON p.user_id = u.id
        WHERE b.blocker_id = %s AND u.status = 'active'
        ORDER BY b.created_at DESC, b.blocked_id DESC
        """,
        (session["user_id"],),
    )
    return jsonify({
        "blocks": [
            {
                "userId": row["blocked_id"],
                "name": row["name"],
                "role": row["role"],
                "photoUrl": row["photo_url"],
                "blockedAt": _datetime_text(row["created_at"]),
            }
            for row in rows
        ]
    })


# ============================================================
# Analytics events
# ============================================================
@app.post("/api/events")
@login_required
def create_event():
    """Record one non-sensitive product/evaluation event."""
    data = json_body()
    name = str(data.get("name") or "").strip().lower()
    if name not in ANALYTICS_EVENTS:
        return validation_error({"name": "Choose a valid event name."})
    payload = data.get("payload") or {}
    if not isinstance(payload, dict):
        return validation_error({"payload": "Payload must be an object."})
    cleaned = _clean_analytics_payload(payload)
    try:
        encoded = json.dumps(cleaned, ensure_ascii=False)
    except (TypeError, ValueError):
        return validation_error({"payload": "Payload is not valid JSON."})
    if len(encoded.encode("utf-8")) > ANALYTICS_PAYLOAD_MAX_BYTES:
        return validation_error({"payload": "Payload is too large."})
    db.execute(
        """
        INSERT INTO analytics_events (user_id, name, payload)
        VALUES (%s, %s, %s)
        """,
        (session["user_id"], name, encoded),
    )
    return "", 204


@app.get("/api/analytics/summary")
@login_required
def analytics_summary():
    """Admin-only aggregate metrics for the capstone evaluation."""
    user = fetch_user_by_id(session["user_id"])
    if not user or user["role"] != "admin":
        return json_error("FORBIDDEN", "Admin access is required.", 403)

    request_rows = db.query_all(
        "SELECT status, COUNT(*) AS total FROM match_requests GROUP BY status"
    )
    request_counts = {row["status"]: row["total"] for row in request_rows}
    total_requests = sum(request_counts.values())

    session_rows = db.query_all(
        "SELECT status, COUNT(*) AS total FROM session_proposals GROUP BY status"
    )
    session_counts = {row["status"]: row["total"] for row in session_rows}
    total_sessions = sum(session_counts.values())

    report_rows = db.query_all(
        "SELECT status, COUNT(*) AS total FROM reports GROUP BY status"
    )
    report_counts = {row["status"]: row["total"] for row in report_rows}

    user_rows = db.query_all(
        """
        SELECT role, COUNT(*) AS total
        FROM users
        WHERE status = 'active'
        GROUP BY role
        """
    )
    user_counts = {row["role"]: row["total"] for row in user_rows}

    event_rows = db.query_all(
        """
        SELECT name, COUNT(*) AS total
        FROM analytics_events
        WHERE created_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY
        GROUP BY name
        ORDER BY total DESC, name ASC
        """
    )
    message_row = db.query_one("SELECT COUNT(*) AS total FROM messages")

    accepted = request_counts.get("accepted", 0)
    completed = session_counts.get("completed", 0)
    return jsonify({
        "generatedAt": _datetime_text(now_utc()),
        "users": user_counts,
        "requests": {
            "byStatus": request_counts,
            "total": total_requests,
            "acceptanceRate": round(accepted / total_requests, 4)
            if total_requests
            else 0,
        },
        "sessions": {
            "byStatus": session_counts,
            "total": total_sessions,
            "completionRate": round(completed / total_sessions, 4)
            if total_sessions
            else 0,
        },
        "reports": {
            "byStatus": report_counts,
            "total": sum(report_counts.values()),
        },
        "messages": {"total": message_row["total"] if message_row else 0},
        "analyticsEventsLast30Days": {
            row["name"]: row["total"] for row in event_rows
        },
    })


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
