"""Seed fictional TutorMatch demo accounts and profiles.

Usage:
    py seed_demo.py
    py seed_demo.py --reset

Only addresses ending in @example.test are touched. The real account
and any other non-demo users are left alone.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import db
from security import hash_password, now_utc

BASE_DIR = Path(__file__).resolve().parent
SEED_PATH = BASE_DIR / "mock" / "seed.json"
DEMO_PASSWORD = "demo1234"

SUBJECT_ALIASES = {
    "sub_math": "sub_mathematics",
}
STYLE_ALIASES = {
    "hands_on": "practice",
    "project_based": "real_world",
}
GOAL_ALIASES = {
    "portfolio": "skill_building",
}
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _datetime(value):
    """Parse an ISO timestamp from mock/seed.json into a naive UTC value."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def _load_seed():
    with SEED_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _reset_demo_users(emails):
    """Delete only the fictional demo accounts and their cascaded profiles."""
    if not emails:
        return
    placeholders = ", ".join(["%s"] * len(emails))
    db.execute(
        f"DELETE FROM users WHERE email IN ({placeholders})",
        tuple(emails),
    )


def _ensure_subjects(seed):
    """Insert any reference subjects used by the demo profiles."""
    for subject in seed.get("subjects", []):
        subject_id = SUBJECT_ALIASES.get(subject["id"], subject["id"])
        db.execute(
            """
            INSERT IGNORE INTO subjects (id, name, category)
            VALUES (%s, %s, %s)
            """,
            (subject_id, subject["name"], subject["category"]),
        )


def _upsert_user(user):
    """Create or refresh one demo account. Returns the database user id."""
    email = str(user["email"]).strip().lower()
    if not email.endswith("@example.test"):
        raise ValueError(f"Refusing to seed non-demo email: {email}")

    existing = db.query_one(
        "SELECT id FROM users WHERE email = %s",
        (email,),
    )
    if existing:
        user_id = existing["id"]
        db.execute(
            """
            UPDATE users
            SET role = %s, name = %s, password_hash = %s,
                email_verified_at = COALESCE(email_verified_at, UTC_TIMESTAMP()),
                status = 'active', failed_attempts = 0, locked_until = NULL
            WHERE id = %s
            """,
            (
                user["role"],
                user["name"],
                hash_password(DEMO_PASSWORD),
                user_id,
            ),
        )
        return user_id

    return db.execute(
        """
        INSERT INTO users
            (role, name, email, password_hash, email_verified_at, status)
        VALUES (%s, %s, %s, %s, UTC_TIMESTAMP(), 'active')
        """,
        (
            user["role"],
            user["name"],
            email,
            hash_password(DEMO_PASSWORD),
        ),
    )


def _upsert_profile(profile, user_id):
    """Create or replace the profile row for a demo account."""
    existing = db.query_one(
        "SELECT id FROM profiles WHERE user_id = %s",
        (user_id,),
    )
    area = profile.get("area") or {}
    style_tags = [
        STYLE_ALIASES.get(tag, tag)
        for tag in profile.get("styleTags") or []
    ]
    goal_tags = [
        GOAL_ALIASES.get(tag, tag)
        for tag in profile.get("goalTags") or []
    ]
    values = (
        profile.get("photoUrl"),
        profile.get("bio"),
        profile.get("birthdate"),
        profile.get("headline"),
        profile.get("status") or "active",
        profile.get("format"),
        area.get("barangay"),
        area.get("city") or "Cabadbaran City",
        profile.get("rateCentavos") if profile.get("role") == "tutor" else None,
        profile.get("budgetMinCentavos") if profile.get("role") == "student" else None,
        profile.get("budgetMaxCentavos") if profile.get("role") == "student" else None,
        profile.get("currency") or "PHP",
        json.dumps(style_tags),
        json.dumps(goal_tags),
        profile.get("completeness") or 0,
        7,
        now_utc(),
        now_utc() if profile.get("verified") else None,
        profile.get("responseTimeMins"),
        _datetime(profile.get("lastActiveAt")),
    )

    with db.transaction() as connection:
        with connection.cursor() as cursor:
            if existing:
                profile_id = existing["id"]
                cursor.execute(
                    """
                    UPDATE profiles
                    SET photo_url=%s, bio=%s, birthdate=%s, headline=%s,
                        status=%s, format=%s, area_barangay=%s, area_city=%s,
                        rate_centavos=%s, budget_min_centavos=%s,
                        budget_max_centavos=%s, currency=%s, style_tags=%s,
                        goal_tags=%s, completeness=%s, onboarding_step=%s,
                        onboarding_completed_at=%s, verified_at=%s,
                        response_time_mins=%s, last_active_at=%s
                    WHERE id=%s
                    """,
                    values + (profile_id,),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO profiles
                        (photo_url, bio, birthdate, headline, status, format,
                         area_barangay, area_city, rate_centavos,
                         budget_min_centavos, budget_max_centavos, currency,
                         style_tags, goal_tags, completeness, onboarding_step,
                         onboarding_completed_at, verified_at,
                         response_time_mins, last_active_at, user_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            %s,%s,%s,%s,%s)
                    """,
                    values + (user_id,),
                )
                profile_id = cursor.lastrowid

            cursor.execute(
                "DELETE FROM profile_subjects WHERE profile_id = %s",
                (profile_id,),
            )
            cursor.execute(
                "DELETE FROM availability_slots WHERE profile_id = %s",
                (profile_id,),
            )

            kind = "teach" if profile.get("role") == "tutor" else "need"
            for subject in profile.get("subjects") or []:
                subject_id = SUBJECT_ALIASES.get(subject["id"], subject["id"])
                cursor.execute(
                    """
                    INSERT IGNORE INTO profile_subjects
                        (profile_id, subject_id, level, kind)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (profile_id, subject_id, subject["level"], kind),
                )

            for slot in profile.get("_availability") or []:
                day = str(slot.get("day") or "").lower()
                if day not in DAYS:
                    continue
                cursor.execute(
                    """
                    INSERT IGNORE INTO availability_slots
                        (profile_id, day_of_week, start_time, end_time, timezone)
                    VALUES (%s, %s, %s, %s, 'Asia/Manila')
                    """,
                    (
                        profile_id,
                        DAYS.index(day) + 1,
                        slot["start"],
                        slot["end"],
                    ),
                )

    return profile_id


def seed(reset=False):
    """Seed or refresh the fictional demo dataset."""
    seed_data = _load_seed()
    users = seed_data.get("users") or []
    profiles = seed_data.get("profiles") or []
    availability = seed_data.get("availability") or []
    demo_emails = [
        str(user["email"]).strip().lower()
        for user in users
        if str(user.get("email") or "").strip().lower().endswith("@example.test")
    ]

    if reset:
        _reset_demo_users(demo_emails)

    _ensure_subjects(seed_data)

    user_id_by_seed_id = {}
    for user in users:
        user_id_by_seed_id[user["id"]] = _upsert_user(user)

    availability_by_profile = {}
    for slot in availability:
        availability_by_profile.setdefault(slot["profileId"], []).append(slot)

    created = 0
    for profile in profiles:
        user_id = user_id_by_seed_id.get(profile.get("userId"))
        if not user_id:
            continue
        profile["_availability"] = availability_by_profile.get(profile["id"], [])
        _upsert_profile(profile, user_id)
        created += 1

    print(f"Seeded {created} demo profiles and {len(user_id_by_seed_id)} demo accounts.")
    print(f"Demo password: {DEMO_PASSWORD}")
    print("Student: ana@example.test")
    print("Tutor:   maria@example.test")
    print("Other demo accounts: johnpaul, angelica, kevin, mark, shaira, reymart @example.test")


def main():
    parser = argparse.ArgumentParser(description="Seed TutorMatch demo profiles.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the fictional demo accounts before seeding them again.",
    )
    args = parser.parse_args()
    seed(reset=args.reset)


if __name__ == "__main__":
    main()
