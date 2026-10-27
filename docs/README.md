# TutorMatch A.I. — Phase 1 Foundations

**Status:** In progress  
**Started:** 2026-10-27  
**Pilot area:** Cabadbaran City, Agusan del Norte  
**Project type:** Solo capstone, real deployment

## Documents

1. [Screen map and user flows](01-screen-map.md)
2. [Mock API contract](02-api-contract.md)
3. [Data model](03-data-model.md)
4. [Mock seed data](../mock/seed.json)

## Decisions locked

- Brand in the UI: **TutorMatch**. Academic title: **TutorMatch A.I.**
- Two roles, **Student** and **Tutor**, fixed at registration.
- Search-first matching: no automatic recommendations before a search.
- Mutual acceptance before chat unlocks.
- Location is barangay-level only.
- Mobile-first, low-data UI.
- English UI for V1, with localization-friendly copy for Cebuano later.
- V1 messaging: text chat and session proposals. Voice notes and simulated calls are deferred or clearly labelled as demo features.
- The current landing page remains the public entry point. The app itself will be a separate authenticated area.

## Open decisions

- Frontend stack: React/Vite or vanilla JS modules.
- Backend stack: Node/Express + PostgreSQL or Supabase.
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

## Next phase

**Phase 2 — Design foundation**

- Lock the frontend stack.
- Create design tokens from the existing cream/orange/ink identity.
- Build the core component inventory.
- Build the mobile app shell and desktop sidebar.
- Add loading, empty, error, and offline states.
- Create a clickable search-results screen with mock data.

## Working agreement

- No production feature is added without a screen in the screen map.
- No screen consumes data that is not in the API contract.
- The mock layer and the future backend must use the same response shapes.
- Privacy rules in the data model are mandatory, not optional.
