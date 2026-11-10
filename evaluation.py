"""
TutorMatch A.I. evaluation script.

This script compares the current weighted ranker with three simple
baselines on the hand-labelled demo relevance set in
``mock/evaluation_labels.json``:

* subject-only: rank by subject/level match, then profile completeness
* random: shuffle with a fixed seed
* popularity: rank by how many requests a candidate has received

It also prints live interaction metrics from MySQL (request acceptance,
session completion, messages, and safety reports).

Usage:
    py evaluation.py
    py evaluation.py --json mock/evaluation_results.json
    py evaluation.py --labels mock/evaluation_labels.json

The script is read-only. It never changes profiles or accounts.
"""

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import app  # noqa: E402
import db  # noqa: E402

DEFAULT_LABELS = BASE_DIR / "mock" / "evaluation_labels.json"
TOP_KS = (1, 3, 5)
RANDOM_SEED = 42


def user_by_email(email):
    row = db.query_one(
        "SELECT id, role, name FROM users WHERE email = %s",
        (str(email or "").strip().lower(),),
    )
    if not row:
        raise SystemExit(f"Demo account not found: {email}")
    return row


def build_params(label, role):
    return {
        "q": str(label.get("q") or "").strip(),
        "subject_id": label.get("subjectId") or None,
        "level": label.get("level") or None,
        "format": label.get("format") or None,
        "availability_raw": label.get("availabilityRaw") or "",
        "availability_slots": [],
        "style_raw": label.get("styleRaw") or "",
        "style_filter": label.get("styleFilter") or [],
        "goal_raw": label.get("goalRaw") or "",
        "goal_filter": label.get("goalFilter") or [],
        "sort": "score",
        "hard_max_rate": (
            label.get("maxRateCentavos") if role == "student" else None
        ),
        "hard_min_budget": (
            label.get("minBudgetCentavos") if role == "tutor" else None
        ),
        "max_distance_meters": label.get("maxDistanceMeters"),
        "page": 1,
        "limit": 50,
    }


def demo_user_ids():
    """Keep evaluation reproducible and limited to fictional demo accounts."""
    rows = db.query_all(
        "SELECT id FROM users WHERE email LIKE %s",
        ("%@example.test",),
    )
    return {row["id"] for row in rows}


def request_counts():
    rows = db.query_all(
        """
        SELECT user_id, COUNT(*) AS total
        FROM (
            SELECT to_user_id AS user_id FROM match_requests
            UNION ALL
            SELECT from_user_id AS user_id FROM match_requests
        ) interactions
        GROUP BY user_id
        """
    )
    return {row["user_id"]: row["total"] for row in rows}


def completeness_map():
    rows = db.query_all("SELECT user_id, completeness FROM profiles")
    return {row["user_id"]: row["completeness"] or 0 for row in rows}


def subject_only_ranking(pool, label):
    subject_id = label.get("subjectId")
    level = label.get("level")

    def score(profile):
        matching = [
            subject
            for subject in profile.get("subjects", [])
            if not subject_id or subject.get("id") == subject_id
        ]
        exact_level = any(
            subject.get("level") == level for subject in matching
        )
        return (
            1 if matching else 0,
            1 if exact_level else 0,
            1 if profile.get("verified") else 0,
            profile.get("name") or "",
        )

    return sorted(pool, key=score, reverse=True)


def random_ranking(pool):
    shuffled = list(pool)
    random.Random(RANDOM_SEED).shuffle(shuffled)
    return shuffled


def popularity_ranking(pool, counts, completeness):
    def score(profile):
        return (
            counts.get(profile.get("userId"), 0),
            completeness.get(profile.get("userId"), 0),
            profile.get("name") or "",
        )

    return sorted(pool, key=score, reverse=True)


def precision_at(ranked_ids, relevant_ids, k):
    if k <= 0:
        return 0.0
    hits = sum(1 for user_id in ranked_ids[:k] if user_id in relevant_ids)
    return hits / k


def reciprocal_rank(ranked_ids, relevant_ids):
    for index, user_id in enumerate(ranked_ids, start=1):
        if user_id in relevant_ids:
            return 1.0 / index
    return 0.0


def live_metrics():
    requests = defaultdict(int)
    for row in db.query_all(
        "SELECT status, COUNT(*) AS total FROM match_requests GROUP BY status"
    ):
        requests[row["status"]] = row["total"]
    sessions = defaultdict(int)
    for row in db.query_all(
        "SELECT status, COUNT(*) AS total FROM session_proposals GROUP BY status"
    ):
        sessions[row["status"]] = row["total"]
    reports = defaultdict(int)
    for row in db.query_all(
        "SELECT status, COUNT(*) AS total FROM reports GROUP BY status"
    ):
        reports[row["status"]] = row["total"]
    messages = db.query_one("SELECT COUNT(*) AS total FROM messages")
    events = db.query_all(
        """
        SELECT name, COUNT(*) AS total
        FROM analytics_events
        GROUP BY name
        ORDER BY total DESC, name ASC
        """
    )

    total_requests = sum(requests.values())
    total_sessions = sum(sessions.values())
    return {
        "requests": {
            "byStatus": dict(requests),
            "total": total_requests,
            "acceptanceRate": round(
                requests.get("accepted", 0) / total_requests, 4
            )
            if total_requests
            else 0,
        },
        "sessions": {
            "byStatus": dict(sessions),
            "total": total_sessions,
            "completionRate": round(
                sessions.get("completed", 0) / total_sessions, 4
            )
            if total_sessions
            else 0,
        },
        "reports": {"byStatus": dict(reports), "total": sum(reports.values())},
        "messages": {"total": messages["total"] if messages else 0},
        "analyticsEvents": {row["name"]: row["total"] for row in events},
    }


def print_table(rows, headers):
    widths = [
        max(len(str(header)), *(len(str(row[index])) for row in rows))
        for index, header in enumerate(headers)
    ]
    line = " | ".join(
        str(header).ljust(widths[index])
        for index, header in enumerate(headers)
    )
    print(line)
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(
            " | ".join(
                str(value).ljust(widths[index])
                for index, value in enumerate(row)
            )
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--labels",
        type=Path,
        default=DEFAULT_LABELS,
        help="Path to the hand-labelled relevance JSON file.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        help="Optional path to write the full evaluation result as JSON.",
    )
    args = parser.parse_args()

    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    counts = request_counts()
    completeness = completeness_map()
    demo_ids = demo_user_ids()
    records = []
    aggregates = defaultdict(lambda: {f"p@{k}": [] for k in TOP_KS})
    aggregates["mrr"] = defaultdict(list)

    print("TutorMatch A.I. — search relevance evaluation")
    print(f"Labels: {args.labels}")
    print()

    detail_rows = []
    for label in labels.get("queries", []):
        viewer_account = user_by_email(label["viewer"])
        _user, viewer = app._viewer_profile(viewer_account["id"])
        if not viewer:
            raise SystemExit(
                f"Viewer profile is incomplete: {label['viewer']}"
            )

        params = build_params(label, viewer["role"])
        total, results, _relaxed, _suggestions = app._run_search(
            viewer, params, soft_subject=True
        )
        pool = [
            result["profile"]
            for result in results
            if result["profile"]["userId"] in demo_ids
        ]
        current_ids = [profile["userId"] for profile in pool]
        relevant_ids = {
            user_by_email(email)["id"] for email in label.get("relevant", [])
        }

        rankings = {
            "current_weighted": current_ids,
            "subject_only": [
                profile["userId"]
                for profile in subject_only_ranking(pool, label)
            ],
            "random": [
                profile["userId"] for profile in random_ranking(pool)
            ],
            "popularity": [
                profile["userId"]
                for profile in popularity_ranking(pool, counts, completeness)
            ],
        }

        record = {
            "id": label["id"],
            "viewer": label["viewer"],
            "role": viewer["role"],
            "q": label.get("q"),
            "subjectId": label.get("subjectId"),
            "level": label.get("level"),
            "poolSize": len(pool),
            "totalReturned": total,
            "relevantIds": sorted(relevant_ids),
            "rankings": rankings,
            "metrics": {},
        }
        for model, ranked_ids in rankings.items():
            metrics = {
                f"precision@{k}": round(
                    precision_at(ranked_ids, relevant_ids, k), 4
                )
                for k in TOP_KS
            }
            metrics["mrr"] = round(
                reciprocal_rank(ranked_ids, relevant_ids), 4
            )
            record["metrics"][model] = metrics
            for k in TOP_KS:
                aggregates[model][f"p@{k}"].append(metrics[f"precision@{k}"])
            aggregates["mrr"][model].append(metrics["mrr"])

        records.append(record)
        detail_rows.append(
            [
                label["id"],
                len(pool),
                len(relevant_ids),
                record["metrics"]["current_weighted"]["precision@1"],
                record["metrics"]["subject_only"]["precision@1"],
                record["metrics"]["popularity"]["precision@1"],
                record["metrics"]["random"]["precision@1"],
            ]
        )

    print("Per-query precision@1")
    print_table(
        detail_rows,
        [
            "query",
            "pool",
            "relevant",
            "current",
            "subject",
            "popular",
            "random",
        ],
    )
    print()

    aggregate_rows = []
    aggregate_json = {}
    for model in ("current_weighted", "subject_only", "popularity", "random"):
        row = [model]
        aggregate_json[model] = {}
        for k in TOP_KS:
            values = aggregates[model][f"p@{k}"]
            mean = sum(values) / len(values) if values else 0
            row.append(round(mean, 4))
            aggregate_json[model][f"precision@{k}"] = round(mean, 4)
        mrr_values = aggregates["mrr"][model]
        mean_mrr = sum(mrr_values) / len(mrr_values) if mrr_values else 0
        row.append(round(mean_mrr, 4))
        aggregate_json[model]["mrr"] = round(mean_mrr, 4)
        aggregate_rows.append(row)

    print("Aggregate ranking quality")
    print_table(
        aggregate_rows,
        ["model", "P@1", "P@3", "P@5", "MRR"],
    )
    print()

    live = live_metrics()
    print("Live interaction metrics")
    print(
        "Requests: "
        f"{live['requests']['total']} total, "
        f"{live['requests']['byStatus'].get('accepted', 0)} accepted, "
        f"acceptance rate {live['requests']['acceptanceRate']:.2%}"
    )
    print(
        "Sessions: "
        f"{live['sessions']['total']} total, "
        f"{live['sessions']['byStatus'].get('completed', 0)} completed, "
        f"completion rate {live['sessions']['completionRate']:.2%}"
    )
    print(f"Messages: {live['messages']['total']}")
    print(f"Reports: {live['reports']['total']} total")
    print(
        "Analytics events: "
        + (
            ", ".join(
                f"{name}={count}"
                for name, count in live["analyticsEvents"].items()
            )
            or "none"
        )
    )

    if args.json:
        output = {
            "labelsFile": str(args.labels),
            "queries": records,
            "aggregate": aggregate_json,
            "liveMetrics": live,
        }
        args.json.write_text(
            json.dumps(output, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print()
        print(f"Wrote {args.json}")


if __name__ == "__main__":
    main()
