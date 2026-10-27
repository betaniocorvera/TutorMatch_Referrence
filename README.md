# TutorMatch — Landing Page

Public landing page for **TutorMatch A.I.**, a tutor-student matching and recommender system for Cabadbaran City, Agusan del Norte.

Static site: HTML5 + Tailwind (CDN) + Vanilla JS.

## Run
Open `index.html` in a browser, or in VS Code use the **Live Server** extension (right-click `index.html` -> Open with Live Server).
An internet connection is needed for Tailwind, fonts, icons and the video.

## Files
- `index.html` - markup (nav, hero, drawer, showreel modal, login/sign-up modal)
- `styles.css` - animations and form styling
- `script.js` - interactions and the demo auth logic
- `docs/` - Phase 1 product, API, and data documentation
- `mock/seed.json` - fictional demo data for UI development

## Project docs
- [Phase 1 — Foundations](docs/README.md)
- [Screen map and user flows](docs/01-screen-map.md)
- [Mock API contract](docs/02-api-contract.md)
- [Data model](docs/03-data-model.md)
- [Mock seed data](mock/seed.json)

## Status
Phase 1 foundations are documented. The current page is the public landing page; the authenticated app, backend, and KNN matching are the next phases.

## Auth note
Login/registration is a front-end demo that stores accounts in the browser's localStorage.
Replace `apiRegister` / `apiLogin` in `script.js` with real server calls for production.
