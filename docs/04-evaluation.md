# TutorMatch A.I. — Evaluation

**Phase:** 4 — Trust, safety, and evaluation  
**Last updated:** 2026-11-10

## 1. Purpose

This document explains how TutorMatch A.I. evaluates its search ranking for the capstone defense. The goal is not to claim a production-scale benchmark. The goal is a reproducible, honest comparison between the current weighted ranker and simple baselines on a small hand-labelled demo set, plus live product-interaction metrics.

## 2. Research question

> Does the current weighted TutorMatch ranker place relevant tutors or students above simple subject-only, popularity, and random baselines?

The current ranker combines subject/level fit, availability overlap, budget/rate fit, distance, style/goal overlap, and profile completeness. The baselines isolate one signal at a time.

## 3. Relevance labels

Labels live in [`mock/evaluation_labels.json`](../mock/evaluation_labels.json).

Each query defines:

- `id`: stable query name.
- `viewer`: the demo account performing the search.
- `role`: `student` or `tutor`.
- `subjectId`: the subject intent used by the ranker and the subject-only baseline.
- `level`: the requested level.
- `format`: optional format filter.
- `maxRateCentavos` for student viewers or `minBudgetCentavos` for tutor viewers.
- `maxDistanceMeters`: optional distance filter.
- `relevant`: demo accounts that a human labelled relevant.
- `note`: the reasoning behind the label.

Relevance is binary at the candidate level. A candidate is relevant when the demo profile can genuinely help with the requested subject at the requested level. The labels were written from the seeded demo profiles, not from the ranker’s output, to avoid circular labelling.

### Candidate pool

The evaluation calls the real ranker with `soft_subject=True`. This keeps the requested subject in the score but does **not** use it as a hard pre-filter. All models therefore rank the same compatible demo candidate pool, which makes the comparison fair. The API and web UI always use the normal hard subject filter; `soft_subject` is an offline evaluation aid only.

Only accounts with `@example.test` emails are included in the evaluation pool. Real accounts are never used as evaluation candidates or printed in the report.

## 4. Models compared

| Model | Ranking signal |
|---|---|
| `current_weighted` | The production weighted ranker: subject/level, availability, budget/rate, distance, style/goal, and completeness |
| `subject_only` | Matching subject and level, then verification and name |
| `popularity` | Number of requests involving the candidate, then profile completeness |
| `random` | Uniform shuffle with a fixed seed (`42`) for reproducibility |

All models use the same candidate pool and the same relevance labels.

## 5. Metrics

- **Precision@1** — fraction of queries where the first result is relevant.
- **Precision@3** — relevant results in the top three divided by three.
- **Precision@5** — relevant results in the top five divided by five.
- **MRR** — mean reciprocal rank of the first relevant result.

Because the demo pool is small, precision@3 and precision@5 use a fixed denominator. A query with one candidate can therefore score only `1/3` at P@3 and `1/5` at P@5 even when the single result is relevant. P@1 and MRR are the most informative metrics for this pilot dataset.

## 6. Current results

Run:

```powershell
py evaluation.py
```

Latest run on 2026-11-10:

```text
Per-query precision@1
query                     | pool | relevant | current | subject | popular | random
--------------------------+------+----------+---------+---------+---------+-------
student_calculus          | 1    | 1        | 1.0     | 1.0     | 1.0     | 1.0
student_physics           | 2    | 1        | 1.0     | 1.0     | 0.0     | 0.0
student_programming       | 2    | 1        | 1.0     | 1.0     | 0.0     | 0.0
student_math_senior_high  | 3    | 2        | 1.0     | 1.0     | 1.0     | 1.0
student_english           | 1    | 1        | 1.0     | 1.0     | 1.0     | 1.0
tutor_calculus            | 1    | 1        | 1.0     | 1.0     | 1.0     | 1.0
tutor_programming         | 2    | 1        | 1.0     | 1.0     | 1.0     | 0.0
tutor_chemistry           | 2    | 1        | 1.0     | 1.0     | 1.0     | 0.0
tutor_english_high_school | 2    | 1        | 1.0     | 1.0     | 0.0     | 0.0

Aggregate ranking quality
model            | P@1    | P@3    | P@5    | MRR
-----------------+--------+--------+--------+-------
current_weighted | 1.0    | 0.3703 | 0.2222 | 1.0
subject_only     | 1.0    | 0.3703 | 0.2222 | 1.0
popularity       | 0.6667 | 0.3703 | 0.2222 | 0.8333
random           | 0.4444 | 0.3703 | 0.2222 | 0.7222
```

### Interpretation

- The current weighted ranker places a relevant result first on every label.
- The subject-only baseline also places a relevant result first on every label, which is expected: the labels are subject-driven and the candidate pools are small.
- Popularity and random baselines fail on several two-candidate queries, so their P@1 and MRR are lower.
- P@3 and P@5 are identical across models because every relevant candidate already appears in the top three. With four demo profiles per role, most pools contain only one to three compatible candidates.
- These results are a sanity check, not evidence of superiority over a large-scale search system. The strongest defensible claim is that the current ranker preserves subject relevance while adding the other product signals.

## 7. Live interaction metrics

The same script prints live MySQL metrics:

- Request counts by status and acceptance rate.
- Session counts by status and completion rate.
- Message count.
- Report count by status.
- Analytics events in the database.

The evaluator intentionally does not seed fake interactions. Run the demo flow first (send requests, accept some, chat, propose sessions, complete sessions) and then rerun `py evaluation.py` to populate these numbers. After the Phase 4 regression cleanup, the transactional demo data is removed again, so a fresh run may show zeros. This is expected and keeps the demo database free of stale test conversations.

## 8. Reproducing the evaluation

1. Start MySQL and Flask.
2. Ensure the demo accounts exist:
   - `ana@example.test`
   - `maria@example.test`
   - `johnpaul@example.test`
   - `angelica@example.test`
   - `kevin@example.test`
   - `mark@example.test`
   - `shaira@example.test`
   - `reymart@example.test`
3. Run `py evaluation.py`.
4. Optionally write a machine-readable report:

```powershell
py evaluation.py --json mock/evaluation_results.json
```

Do not commit generated result files unless the defense requires a frozen snapshot. The script is read-only by default.

## 9. Threats to validity

- **Small label set.** Nine queries and eight demo profiles are enough for a capstone sanity check, not for statistical significance.
- **Small candidate pools.** Most pools contain one or two compatible candidates, so P@3 and P@5 saturate or use fixed denominators.
- **Single labeller.** Labels reflect one student’s judgment. A second labeller and Cohen’s kappa would strengthen the study.
- **Demo profiles only.** The pilot uses fictional `@example.test` profiles, not real Cabadbaran users.
- **No click logs yet.** Live metrics are useful only after real or realistic demo sessions. The system logs events from day one, but the dataset is still tiny.
- **Popularity is sparse.** With no request history, the popularity baseline falls back to profile completeness, which is a weak proxy.

## 10. Privacy and ethics

- Evaluation only uses demo accounts with `@example.test` emails.
- Real accounts are excluded from the candidate pool.
- The script prints aggregate metrics and query IDs, not emails.
- Analytics payloads are sanitized server-side and never store emails, passwords, message bodies, or exact locations.
- Reports and blocks are private to their owner and server-side moderation code.
- No human subjects were recruited for this pilot; all profiles are fictional.

## 11. Future work

- Expand to 20–30 labelled queries and a larger tutor pool.
- Add a second independent labeller and report inter-rater agreement.
- Add nDCG with graded relevance (for example, `2 = strong fit`, `1 = acceptable`, `0 = not relevant`).
- Compare against a collaborative-filtering or learning-to-rank baseline once enough interaction data exists.
- Track search-to-request and request-to-session completion funnels over time.
