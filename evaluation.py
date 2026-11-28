"""
TutorMatch A.I. evaluation script.

This script compares the current weighted ranker with four baselines
on the hand-labelled demo relevance set in
``mock/evaluation_labels.json``:

* k-NN: cosine nearest-neighbour ranking in a shared profile feature space
* subject-only: rank by subject/level match, then profile completeness
* random: shuffle with a fixed seed
* popularity: rank by how many requests a candidate has received

The k-NN baseline is content-based: the viewer's needs and the query
filters become one query vector, every candidate profile becomes a
vector in the same space, and candidates are ordered by cosine
similarity (equivalent to Euclidean nearest-neighbour distance once
both vectors are unit length). No labels are used to fit the model, so
the precision@k and MRR numbers stay comparable.

It also prints live interaction metrics from the database (request
acceptance, session completion, messages, and safety reports).

Usage:
    py evaluation.py
    py evaluation.py --json mock/evaluation_results.json
    py evaluation.py --labels mock/evaluation_labels.json

The script is read-only. It never changes profiles or accounts.
"""

import argparse
import json
import math
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


# ============================================================
# Content-based k-NN baseline
#
# Every profile is encoded as a set of feature blocks. The query
# (viewer needs + label filters) is encoded the same way, so the
# two live in one vector space. Ranking by cosine similarity is
# identical to ranking by Euclidean nearest-neighbour distance
# for unit-length vectors.
#
# Block weights keep one sparse block from dominating the
# similarity. Nothing is fitted, so this is an unsupervised
# nearest-neighbour retrieval baseline, not a trained classifier.
# ============================================================
KNN_BLOCK_WEIGHTS = {
    "subject": 0.35,
    "level": 0.10,
    "style": 0.10,
    "goal": 0.10,
    "format": 0.06,
    "distance": 0.10,
    "availability": 0.15,
    "quality": 0.04,
}
KNN_NEUTRAL = 0.5
# Same fallback radius as app._distance_score so the two models
# measure distance on the same scale.
KNN_DEFAULT_MAX_DISTANCE = 20000
KNN_DAY_MINUTES = 8 * 60


def _knn_unit(values):
    """Scale a block to unit length, or None when it has no signal."""
    norm = math.sqrt(sum(value * value for value in values))
    if not norm:
        return None
    return [value / norm for value in values]


def _knn_binary(values, vocabulary):
    """Multi-hot encode the chosen values against a fixed vocabulary."""
    chosen = set(values or ())
    return [1.0 if item in chosen else 0.0 for item in vocabulary]


def _knn_format_vector(value):
    """Two dims: can meet online, can meet in person."""
    if not value:
        return [KNN_NEUTRAL, KNN_NEUTRAL]
    online = 1.0 if value in ("online", "both") else 0.0
    in_person = 1.0 if value in ("in_person", "both") else 0.0
    return [online, in_person]


def _knn_day_vector(slots):
    """Weekly coverage, one dim per day, each normalized to an 8h day."""
    minutes = [0.0] * 7
    for slot in slots or ():
        day = slot.get("day")
        if day not in app.DAY_INDEX:
            continue
        start = app._to_minutes(slot.get("start"))
        end = app._to_minutes(slot.get("end"))
        if start is None or end is None or end <= start:
            continue
        minutes[app.DAY_INDEX[day] - 1] += end - start
    return [min(1.0, value / KNN_DAY_MINUTES) for value in minutes]


def _knn_block_similarity(query_block, candidate_block):
    """Cosine similarity of one block; neutral when either side is empty."""
    query_unit = _knn_unit(query_block)
    candidate_unit = _knn_unit(candidate_block)
    if query_unit is None or candidate_unit is None:
        return KNN_NEUTRAL
    return sum(
        query_value * candidate_value
        for query_value, candidate_value in zip(query_unit, candidate_unit)
    )


def _knn_query_blocks(viewer, label, subject_vocab):
    """Encode what the viewer is looking for as feature blocks."""
    # When the query names a subject or level, that is the literal
    # search intent. Only fall back to the viewer's own profile when
    # the request leaves it open.
    subject_weight = {}
    if label.get("subjectId"):
        subject_weight[label["subjectId"]] = 1.0
    else:
        for subject in viewer.get("subjects") or []:
            subject_id = subject.get("id")
            if subject_id:
                subject_weight[subject_id] = 1.0

    level_weight = {}
    if label.get("level"):
        level_weight[label["level"]] = 1.0
    else:
        for subject in viewer.get("subjects") or []:
            subject_level = subject.get("level")
            if subject_level:
                level_weight[subject_level] = 1.0

    if label.get("styleFilter"):
        style_values = label["styleFilter"]
    else:
        style_values = viewer.get("styleTags") or []
    if label.get("goalFilter"):
        goal_values = label["goalFilter"]
    else:
        goal_values = viewer.get("goalTags") or []

    requested_format = label.get("format") or viewer.get("format")

    if label.get("availabilityRaw"):
        target_slots, _error = app._parse_availability_filter(
            label["availabilityRaw"]
        )
    else:
        target_slots = viewer.get("availability") or []

    return {
        "subject": [
            subject_weight.get(item, 0.0) for item in subject_vocab
        ],
        "level": [
            level_weight.get(item, 0.0) for item in app.PROFILE_LEVELS
        ],
        "style": _knn_binary(style_values, app.STYLE_TAGS),
        "goal": _knn_binary(goal_values, app.GOAL_TAGS),
        "format": _knn_format_vector(requested_format),
        "distance": [1.0],
        "availability": _knn_day_vector(target_slots),
        # A query always wants a trustworthy, responsive match.
        "quality": [1.0, 1.0],
    }


def _knn_candidate_blocks(profile, subject_vocab, max_distance):
    """Encode one search result in the same feature space."""
    distance = profile.get("distanceMeters")
    if profile.get("format") == "online":
        # Travelling never happens for an online-only tutor.
        distance_block = [1.0]
    elif distance is None:
        distance_block = [KNN_NEUTRAL]
    else:
        capped = min(1.0, max(0.0, distance / max_distance))
        distance_block = [1.0 - capped]

    response = profile.get("responseTimeMins")
    response_speed = (
        KNN_NEUTRAL
        if response is None
        else 1.0 - min(1.0, max(0.0, response / 120))
    )

    return {
        "subject": _knn_binary(
            [
                subject.get("id")
                for subject in profile.get("subjects") or []
            ],
            subject_vocab,
        ),
        "level": _knn_binary(
            [
                subject.get("level")
                for subject in profile.get("subjects") or []
            ],
            app.PROFILE_LEVELS,
        ),
        "style": _knn_binary(profile.get("styleTags"), app.STYLE_TAGS),
        "goal": _knn_binary(profile.get("goalTags"), app.GOAL_TAGS),
        "format": _knn_format_vector(profile.get("format")),
        "distance": distance_block,
        "availability": _knn_day_vector(profile.get("availability")),
        "quality": [
            1.0 if profile.get("verified") else 0.0,
            response_speed,
        ],
    }


def knn_ranking(pool, viewer, label):
    """Order the pool by cosine similarity to the query vector."""
    subject_vocab = set()
    for subject in viewer.get("subjects") or []:
        if subject.get("id"):
            subject_vocab.add(subject["id"])
    if label.get("subjectId"):
        subject_vocab.add(label["subjectId"])
    for profile in pool:
        for subject in profile.get("subjects") or []:
            if subject.get("id"):
                subject_vocab.add(subject["id"])
    subject_vocab = sorted(subject_vocab)

    query_blocks = _knn_query_blocks(viewer, label, subject_vocab)
    max_distance = (
        label.get("maxDistanceMeters") or KNN_DEFAULT_MAX_DISTANCE
    )

    def similarity(profile):
        candidate_blocks = _knn_candidate_blocks(
            profile, subject_vocab, max_distance
        )
        return sum(
            KNN_BLOCK_WEIGHTS[name]
            * _knn_block_similarity(
                query_blocks[name], candidate_blocks[name]
            )
            for name in KNN_BLOCK_WEIGHTS
        )

    scored = [(similarity(profile), profile) for profile in pool]
    scored.sort(
        key=lambda item: (
            item[0],
            1 if item[1].get("verified") else 0,
            item[1].get("name") or "",
        ),
        reverse=True,
    )
    return [profile for _score, profile in scored]


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
            "knn_similarity": [
                profile["userId"]
                for profile in knn_ranking(pool, viewer, label)
            ],
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
                record["metrics"]["knn_similarity"]["precision@1"],
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
            "knn",
            "subject",
            "popular",
            "random",
        ],
    )
    print()

    aggregate_rows = []
    aggregate_json = {}
    for model in (
        "current_weighted",
        "knn_similarity",
        "subject_only",
        "popularity",
        "random",
    ):
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
