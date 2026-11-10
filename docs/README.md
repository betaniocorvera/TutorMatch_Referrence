# TutorMatch A.I. — Phase 1 Foundations + Phase 2 Search + Phase 3 Messaging + Phase 4 Trust & Evaluation

**Status:** Phases 1–4 complete for the capstone build
**Started:** 2026-10-27
**Pilot area:** Cabadbaran City, Agusan del Norte
**Project type:** Solo capstone, real deployment

## Documents

1. [Screen map and user flows](01-screen-map.md)
2. [API contract](02-api-contract.md)
3. [Data model](03-data-model.md)
4. [Evaluation methodology and results](04-evaluation.md)
5. [Demo seed data](../mock/seed.json)

## Decisions locked

- Brand in the UI: **TutorMatch**. Academic title: **TutorMatch A.I.**
- Two roles, **Student** and **Tutor**, fixed at registration.
- Search-first matching: no automatic recommendations before a search.
- Mutual acceptance before chat unlocks.
- Location is barangay-level only.
- Mobile-first, low-data UI.
- English UI for V1, with localization-friendly copy for Cebuano later.
- V1 messaging: text chat and session proposals. Voice notes and simulated calls are deferred or clearly labelled as demo features.
- The current landing page remains the public entry point. The app itself is a separate authenticated area.
- Frontend stack: vanilla JS modules, HTML, and CSS with the cream/orange design system.
- Backend stack: Flask + MySQL.
- Search is API-backed and explicit; no client-side mock matching.
- Session proposals, reports, blocks, notifications, analytics, and the evaluation harness are API-backed and persistent.

## Open decisions

- Launch niche: recommended senior high STEM + college math/science.
- Whether reviews and saved tutors belong in V1 or V1.5. They remain V1.5.
- Payment handling: recommended off-platform in V1.
- Defense date and weekly build cadence.

## Phase 1 deliverables

- [x] Screen inventory and role-based navigation
- [x] Student, tutor, request, chat, and session flows
- [x] Screen-level states and edge cases
- [x] Component inventory
- [x] Mock API contract
- [x] Data model and privacy matrix
- [x] Initial matching feature weights and cold-start rules
- [x] Seed data plan
- [x] Initial mock seed dataset

## Phase 2 deliverables

- [x] Cream/orange design tokens and responsive dashboard shell
- [x] Onboarding wizard and MySQL profile persistence
- [x] API-backed student/tutor search with explicit submit
- [x] Hard filters plus weighted subject, availability, budget, distance, and style/goal scoring
- [x] Match score, band, reasons, overlap, warnings, breakdown, and pagination
- [x] Privacy-safe public profile preview
- [x] Loading, empty, no-results, error, and relaxed-filter states
- [x] Fictional demo seeder that leaves real accounts untouched

## Phase 3 deliverables

- [x] MySQL-backed match requests with pending, accepted, declined, cancelled, and expired states
- [x] Incoming and outgoing request lists with accept, decline, and cancel actions
- [x] One pending request per user pair, checked in both directions
- [x] Seven-day request expiry and five-requests-per-day limit
- [x] Conversation created only when a request is accepted; chat stays locked before acceptance
- [x] Persistent text and system messages with a thirty-messages-per-minute limit
- [x] Unread message counts, conversation read markers, and notification badge
- [x] Search sends requests through the API instead of browser-local storage
- [x] Responsive Messages section with Incoming, Outgoing, and Chats tabs
- [x] Demo seeder remains limited to `@example.test` accounts

## Phase 4 deliverables

- [x] Session proposal API with propose, accept, decline, reschedule, cancel, and complete actions
- [x] Session cards, proposal modal, reschedule flow, and role rules in chat
- [x] Report API and chat report modal, including an optional report-and-block action
- [x] Block and unblock APIs that hide the pair from search, lock shared chats, cancel pending requests, and pause session actions
- [x] Dedicated Notifications page with all/unread filters, unread badge, mark-one-read, mark-all-read, and blocked-accounts management
- [x] Notification records for requests, sessions, and messages
- [x] Non-sensitive analytics events with server-side payload sanitization and a best-effort write path
- [x] Admin-only analytics summary endpoint
- [x] Hand-labelled evaluation set and current-vs-baseline precision@k/MRR harness
- [x] Live interaction metrics for requests, sessions, messages, reports, and analytics
- [x] Local API and browser regression checks for Phase 4 flows (development-only scripts)

## Evaluation

Run the offline ranking evaluation from the project root:

```powershell
py evaluation.py
```

The script compares the current weighted ranker with subject-only, random, and popularity baselines on `mock/evaluation_labels.json`, then prints live request, session, message, report, and analytics metrics. It is read-only unless `--json PATH` is supplied. See [04-evaluation.md](04-evaluation.md) for methodology, results, and limitations.

## Verification commands

```powershell
py -m py_compile app.py db.py seed_demo.py evaluation.py
node --check js/auth.js
node --check js/search.js
node --check js/profile.js
node --check js/messages.js
node --check js/notifications.js
node --check js/dashboard.js
git diff --check
```

## Working agreement

- No production feature is added without a screen in the screen map.
- No screen consumes data that is not in the API contract.
- The mock layer and the backend use the same response shapes.
- Privacy rules in the data model are mandatory, not optional.
- Analytics must never store emails, passwords, message bodies, or exact locations.
- Real accounts are never deleted by demo seed or cleanup scripts.
