# TutorMatch — Landing Page + Authenticated Dashboard

Public landing page and authenticated search dashboard for **TutorMatch A.I.**, a tutor-student matching and recommender system for Cabadbaran City, Agusan del Norte.

HTML5 + Tailwind (CDN) + Vanilla JS, with a Flask/MySQL authentication backend.

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

The schema creates the `tutormatch` database and the `users`, `email_otps`, `password_resets`, and `security_events` tables.

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

## Files
- `index.html` - landing page, auth modal (login, register, verify, reset)
- `styles.css` - animations and form styling
- `script.js` - landing interactions and API-backed auth flows
- `dashboard.html` - authenticated search dashboard shell
- `dashboard.css` - dashboard and responsive styles
- `js/auth.js` - shared API client, CSRF handling, session validation
- `js/dashboard.js` - async session guard, sidebar, hash routing, logout
- `js/data.js` - mock users, hard filters, and placeholder match scoring
- `js/search.js`, `js/profile.js`, `js/messages.js` - dashboard sections
- `app.py` - Flask app, auth routes, static routes, security headers
- `security.py` - validation, hashing, OTP/reset helpers, CSRF, sessions, rate limits
- `db.py` - MySQL helpers
- `mailer.py` - dev outbox / SMTP email helpers
- `schema.sql` - MySQL schema
- `docs/` - Phase 1 product, API, and data documentation
- `mock/seed.json` - fictional demo data for UI development

## Project docs
- [Phase 1 — Foundations](docs/README.md)
- [Screen map and user flows](docs/01-screen-map.md)
- [Mock API contract](docs/02-api-contract.md)
- [Data model](docs/03-data-model.md)
- [Mock seed data](mock/seed.json)

## Status
The landing page, registration/login/verification/reset flow, secure sessions, and authenticated dashboard shell are wired. Search results and sent requests are still demo data stored in the browser; KNN matching and a persistent requests/messages backend are next.
