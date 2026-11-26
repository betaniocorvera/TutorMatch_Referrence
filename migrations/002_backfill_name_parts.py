"""Backfill first/middle/last name parts for existing accounts.

Run from the project root after applying migrations/001_signup_fields.sql:

    py migrations/002_backfill_name_parts.py
    py migrations/002_backfill_name_parts.py --dry-run

The script only touches accounts that still have no name parts. It splits
users.name into at least two tokens, validates every part with the same
rules as sign-up, and never overwrites an existing value. Accounts whose
name cannot be split safely are left unchanged so the owner can fill the
fields from Edit profile.
"""

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import db  # noqa: E402
from security import clean_name_part, compose_name  # noqa: E402


def split_name(display_name):
    """Return (first, middle, last) or None when the name is unsafe."""
    tokens = re.split(r"\s+", str(display_name or "").strip())
    tokens = [token for token in tokens if token]
    if len(tokens) < 2:
        return None

    first = clean_name_part(tokens[0])
    last = clean_name_part(tokens[-1])
    middle = None
    if len(tokens) > 2:
        middle = clean_name_part(" ".join(tokens[1:-1]))

    if not first or not last:
        return None
    if len(tokens) > 2 and not middle:
        return None
    if len(compose_name(first, middle, last)) > 80:
        return None
    return first, middle, last


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing to the database.",
    )
    args = parser.parse_args()

    rows = db.query_all(
        """
        SELECT id, name, first_name, middle_name, last_name
        FROM users
        ORDER BY id
        """
    )

    updated = 0
    skipped = []

    for row in rows:
        if row["first_name"] or row["last_name"]:
            continue

        parts = split_name(row["name"])
        if not parts:
            skipped.append((row["id"], row["name"]))
            continue

        first, middle, last = parts
        print(f"user {row['id']}: {row['name']!r} -> {first!r}, {middle!r}, {last!r}")
        if args.dry_run:
            updated += 1
            continue

        db.execute(
            """
            UPDATE users
            SET first_name = %s,
                middle_name = %s,
                last_name = %s
            WHERE id = %s
              AND first_name IS NULL
              AND last_name IS NULL
            """,
            (first, middle, last, row["id"]),
        )
        updated += 1

    print()
    print(f"{'Would update' if args.dry_run else 'Updated'} {updated} account(s).")
    if skipped:
        print(f"Left {len(skipped)} account(s) for manual completion:")
        for user_id, name in skipped:
            print(f"  user {user_id}: {name!r}")


if __name__ == "__main__":
    main()
