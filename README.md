# TutorMatch — Landing Page, Dashboard, and Search Matching

Public landing page and authenticated search dashboard for **TutorMatch A.I.**, a tutor-student matching and recommender system for Cabadbaran City, Agusan del Norte.

HTML5 + Tailwind (CDN) + Vanilla JS, with a Flask/MySQL backend for authentication, onboarding, profile persistence, and privacy-safe search matching.

## Run the full app

The app must be served by Flask. Opening `index.html` directly or using a static Live Server will not work for auth because the API and session cookie are required.

### 1. Install dependencies

```powershell
py -m pip install -r requirements.txt
```

### 2. Create the MySQL database

```powershell
mysql -u root -p -e "source schema.sql"
```

The schema creates the `tutormatch` database and the `users`, `email_otps`, `password_resets`, `security_events`, `profiles`, `subjects`, `profile_subjects`, and `availability_slots` tables. It also seeds the reference subject list.

### 3. Configure `.env`

```powershell
Copy-Item .env.example .env
```

Then fill in:

- `SECRET_KEY` and `OTP_PEPPER` — generate each with:
  ```powershell
  py -c "import secrets; print(secrets.token_hex(32))"
  ```
- MySQL `DB_USER` / `DB_PASSWORD`
- `APP_BASE_URL` — the URL used in password-reset emails, normally `http://127.0.0.1:5000`
- Keep `MAIL_DEV_MODE=true` for the demo. OTPs and reset links are printed in the Flask terminal and appended to `outbox.log` instead of being sent over SMTP.

### 4. Start Flask

```powershell
py -m flask --app app run
```

Open <http://127.0.0.1:5000>. An internet connection is needed for Tailwind, fonts, icons and the video.

### Optional: create an admin account

```powershell
py -m flask --app app create-admin
```

### Optional: seed fictional demo accounts

```powershell
py seed_demo.py
```

Use `--reset` to replace only the fictional `@example.test` demo accounts:

```powershell
py seed_demo.py --reset
```

The seeder creates 4 tutor and 4 student profiles from `mock/seed.json`. Demo accounts use the password `demo1234`:

- Student: `ana@example.test`
- Tutor: `maria@example.test`
- Other demo accounts: `johnpaul@example.test`, `angelica@example.test`, `kevin@example.test`, `mark@example.test`, `shaira@example.test`, `reymart@example.test`

`--reset` never deletes real accounts; it only deletes users whose email ends in `@example.test`.

## Auth flow

- **Register** — creates an unverified account, emails a 6-digit code, and opens the verification form.
- **Verify email** — the code expires in 5 minutes, allows 5 attempts, and is stored as an HMAC-SHA256 hash.
- **Login** — requires a verified email. Wrong passwords lock the account after 5 attempts for 15 minutes.
- **Resend code** — rate-limited and returns the same generic response whether the account exists or not.
- **Forgot password** — emails a single-use reset link. The link opens `/?reset_token=...` and the reset form in the auth modal.
- **Reset password** — updates the password hash, invalidates old sessions, and clears lockout state.
- **Logout** — clears the server session.
- **Sessions** — Flask session cookie is the source of truth. The dashboard calls `/api/auth/me` before initializing.
- **CSRF** — every write sends `X-CSRFToken`; the client fetches it from `/api/csrf` and retries once if the session token expired.
- **Security log** — registrations, logins, lockouts, OTP events, resets, and rate-limit hits are appended to `security_events`.

In development, read the latest OTP or reset link from the Flask terminal or `outbox.log`. The API never returns OTPs or reset tokens.

## Onboarding and profile persistence

After login or email verification, the API returns `onboardingRequired`. The landing page sends new or incomplete profiles to `/onboarding`; completed profiles go to the dashboard.

The wizard has seven steps:

1. Basics — photo (optional), display name, headline, bio, birthdate (private), status.
2. Subjects and levels — at least one subject, each with a level.
3. Goals and style — recommended, not required.
4. Availability — at least one weekly slot from the morning, afternoon, or evening grid.
5. Rate or budget and format — required.
6. Area — barangay and city only; no exact address.
7. Preview — review the public card, then finish.

Profiles save to MySQL after each step and on text changes (debounced). `Save & exit` stores your progress; the next visit resumes at the furthest saved step. Required fields cannot be skipped, and the completeness meter updates live.

Minimum profile for search: a bio of at least 10 characters, one subject, one availability slot, a rate (tutor) or budget range (student), a format, and a barangay. The server redirects incomplete profiles from `/dashboard.html` back to `/onboarding`. Completed profiles can edit from the dashboard with `/onboarding?edit=1`.

Photos are optional, limited to 1 MB, validated by magic bytes (JPG, PNG, WebP), and stored in `uploads/avatars/`. They are served from `/uploads/...`.

### Profile API

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/subjects` | Reference subjects, optionally filtered with `?q=`. |
| `GET` | `/api/levels` | Level labels. |
| `GET` | `/api/me/profile` | Private profile, subjects, availability, completeness. |
| `PATCH` | `/api/me/profile` | Save any subset of profile fields; recompute completeness. |
| `GET` | `/api/me/completeness` | Percentage, required-complete flag, missing checklist. |
| `POST` | `/api/me/photo` | Upload a profile photo as multipart form data. |

Profile writes use `db.transaction()` so the profile row, subjects, availability, and display name stay in sync.

## Search and matching

Search is explicit. The dashboard shows an empty state until the user submits the form; it does not call the search API on page load.

Students search for tutors and tutors search for students. The role is enforced by the server: calling the wrong endpoint returns `403`.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/search/tutors` | Student searching for tutors. |
| `GET` | `/api/search/students` | Tutor searching for students. |
| `GET` | `/api/profiles/<profile_id>` | Privacy-safe public profile preview. |

Search reads live MySQL profile data. `js/data.js` contains only shared UI constants; there are no mock users or client-side matching rules anymore.

Supported query parameters:

- `q` — free-text keyword across name, headline, bio, area, and subjects.
- `subjectId` — exact subject filter.
- `level` — student level; used to score subject-level closeness.
- `format` — `online`, `in_person`, or `both`.
- `maxRateCentavos` (student search) or `minBudgetCentavos` (tutor search).
- `availability` — comma-separated category tokens (`weekday-am`, `weekday-pm`, `weekday-eve`, `weekend`) or exact slots such as `tue:18:00-20:00`.
- `maxDistanceMeters` — applied only to in-person or `both` profiles.
- `style`, `goal` — comma-separated tag filters.
- `sort` — `score` (default), `distance`, and `rate` for students or `budget` for tutors.
- `page`, `limit` — pagination; `limit` defaults to 10 and is capped at 50.

Ranking uses the documented starting weights: subject/level 35%, availability 20%, budget/rate 15%, distance 15%, and style/goal 15%. Each result returns `match.score`, `match.scoreMode`, `match.band`, `match.reasons`, `match.availabilityOverlap`, `match.warnings`, and `match.breakdown`. The current score is explicitly labelled `one-sided`; pair scoring is deferred. Results below the fair band are shown only when the search would otherwise be empty, and are labelled with a low-match warning.

If an explicit distance filter is too narrow, the server retries without it and reports `relaxedFilters: ["distance"]`; the dashboard shows a visible notice. Budget, format, and availability filters are not silently relaxed.

Distance comes from barangay centroids and Haversine, rounded to the nearest 100 m. Unknown barangays return `distanceMeters: null` with a warning; missing distance is never treated as zero. Location is always barangay-level only.

Search results and public profiles never expose email, birthdate, exact coordinates, password hashes, verification documents, reports, or blocks.

## Files
- `index.html` - landing page, auth modal (login, register, verify, reset)
- `styles.css` - animations and form styling
- `script.js` - landing interactions and API-backed auth flows
- `dashboard.html` - authenticated search dashboard shell
- `dashboard.css` - dashboard and responsive styles
- `onboarding.html` - seven-step profile wizard
- `onboarding.css` - onboarding-specific styles
- `js/onboarding.js` - wizard state, autosave, validation, preview
- `js/auth.js` - shared API client, CSRF handling, session validation, profile methods
- `js/dashboard.js` - async session guard, sidebar, hash routing, logout
- `js/data.js` - shared UI constants for availability and labels only
- `js/search.js` - API-backed search, filters, sorting, pagination, profile panel, requests
- `js/profile.js`, `js/messages.js` - dashboard sections
- `app.py` - Flask app, auth/onboarding/profile/search routes, static routes, security headers
- `security.py` - validation, hashing, OTP/reset helpers, CSRF, sessions, rate limits
- `db.py` - MySQL helpers
- `mailer.py` - dev outbox / SMTP email helpers
- `schema.sql` - MySQL schema and reference subjects
- `seed_demo.py` - fictional demo account/profile seeder
- `uploads/avatars/` - optional profile photos (local, git-ignored)
- `docs/` - product, API, and data documentation for Phases 1–2
- `mock/seed.json` - fictional demo data used by `seed_demo.py`

## Project docs
- [Phase 1 — Foundations](docs/README.md)
- [Screen map and user flows](docs/01-screen-map.md)
- [API contract](docs/02-api-contract.md)
- [Data model](docs/03-data-model.md)
- [Demo seed data](mock/seed.json)

## Status
The landing page, registration/login/verification/reset flow, secure sessions, onboarding/profile persistence, authenticated dashboard, and API-backed search matching are wired. Students and tutors can search each other, filter, sort, paginate, preview privacy-safe public profiles, and send local requests.

Sent requests and messages are still stored in the browser. A persistent requests/messages backend and the evaluation baseline comparisons remain next.
