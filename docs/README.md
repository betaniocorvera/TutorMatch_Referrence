# TutorMatch A.I. — Phase 1 Foundations + Phase 2 Search

**Status:** Phase 1 complete; Phase 2 search matching implemented
**Started:** 2026-10-27
**Pilot area:** Cabadbaran City, Agusan del Norte
**Project type:** Solo capstone, real deployment

## Documents

1. [Screen map and user flows](01-screen-map.md)
2. [API contract](02-api-contract.md)
3. [Data model](03-data-model.md)
4. [Demo seed data](../mock/seed.json)

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
- Frontend stack: vanilla JS modules, HTML, and Tailwind CDN.
- Backend stack: Flask + MySQL.
- Search is API-backed and explicit; no client-side mock matching.

## Open decisions

- Launch niche: recommended senior high STEM + college math/science.
- Whether reviews and saved tutors belong in V1 or V1.5.
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

## Next phase

**Phase 3 — Persistent requests and messaging**

- Persist match requests, acceptances, conversations, and session proposals.
- Replace browser-local sent requests with backend records.
- Add notifications and request status updates.
- Log search and request analytics for evaluation.
- Run the baseline comparisons and precision@k evaluation described in the data model.

## Working agreement

- No production feature is added without a screen in the screen map.
- No screen consumes data that is not in the API contract.
- The mock layer and the future backend must use the same response shapes.
- Privacy rules in the data model are mandatory, not optional.
