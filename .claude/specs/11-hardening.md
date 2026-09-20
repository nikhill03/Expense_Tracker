# Spec: Performance & Hardening

## Overview
Step 11 prepares Bahi-Khata for a public URL: index the queries that actually run, stop any page loading an
unbounded list, make SQLite behave under a server, and add the security and operations basics that were missing.
No user-visible feature changes, apart from pagination and friendlier error pages.

## Depends on
- Steps 5–10 — the routes and queries being optimised

## Routes
- `GET /healthz` — liveness probe: 200 plus a `SELECT 1`, public
- Changed: `/expenses` accepts `?page=`; `/profile` shows the latest 10 transactions with a "View all" link

## Database changes
- `idx_expenses_user_date (user_id, date)` and `idx_expenses_user_event (user_id, event_id)`; the older
  single-column `idx_expenses_event` is dropped
- `journal_mode = WAL`, `busy_timeout = 5000`, `synchronous = NORMAL`
- New `login_attempts` table (email, failures, locked_until)
- `DATABASE_PATH` environment variable, defaulting to the local database file
- `backup_db()` — daily `VACUUM INTO` snapshot, keeping 7

## Templates
- **Create:** `error.html`
- **Modify:** every POST gains a hidden `csrf_token` field; `expenses.html` gains pagination; `profile.html` gains
  the "View all" link

## Files to change
`database/db.py`, `database/queries.py` (`get_dashboard`, pagination), `app.py` (CSRF, throttling, error handlers,
`/healthz`, timing log, pagination), `Procfile`, `.gitignore`, `static/css/style.css`

## Files to create
`templates/error.html`, `tests/test_11_hardening.py`, `docs/ARCHITECTURE_REVIEW.md`

## New dependencies
None. CSRF and throttling are implemented with the standard library.

## Rules for implementation
- CSRF on by default, disabled under `TESTING` so existing route tests stay readable; `CSRF_ENABLED = True` turns it
  back on for the tests that cover it
- The dashboard must not grow its query count as data grows
- Totals are computed in SQL over the whole range, never summed from the rows on the current page
- Query-layer changes stay backwards compatible (new arguments keyword-only with defaults)

## Acceptance criteria
- [ ] `EXPLAIN QUERY PLAN` shows index use, not `SCAN`, for the four expense queries
- [ ] `/profile` runs at most 4 queries regardless of data size
- [ ] `/profile` renders at most 10 transactions; `/expenses` paginates at 50 with correct whole-range totals
- [ ] A POST without a valid CSRF token is rejected
- [ ] 5 failed logins lock that email for 15 minutes; a correct login clears the counter
- [ ] `/healthz` returns 200; 404/403/500 render a friendly page with no traceback
- [ ] A daily backup file appears beside the database
