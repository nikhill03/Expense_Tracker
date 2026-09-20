# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

**Bahi-Khata** is a Flask-based personal expense tracker web app targeting Indian users (currency: ₹). It is structured as a teaching project where students implement features step-by-step. The current state is a pre-auth scaffold: landing page, login/register stubs, and placeholder routes for the full CRUD flow.

## Commands

```bash
# Run the development server (port 5001)
python app.py

# Run all tests
pytest

# Run a single test file
pytest tests/test_auth.py

# Run a single test
pytest tests/test_auth.py::test_login_page
```

Install dependencies:
```bash
pip install -r requirements.txt
```

## Architecture

### Entry point
`app.py` — single-file Flask app. All routes live here. The app runs on port 5001 with `debug=True`.

### Database layer
`database/db.py` — students implement three functions here:
- `get_db()` — returns a SQLite connection (`expense_tracker.db`) with `row_factory` and foreign keys enabled
- `init_db()` — creates tables with `CREATE TABLE IF NOT EXISTS`, then adds any missing columns via `_add_column_if_missing()` so existing databases migrate in place
- `seed_db()` — inserts sample rows for development

Tables: `users`, `expenses` (with a nullable `event_id`), `events` (name, optional `start_date`/`end_date`/`budget`),
`login_attempts` (failed-login throttling).
Read queries live in `database/queries.py`; the expense queries take keyword-only `event_id` / `exclude_events`
filters, and `get_dashboard()` serves the whole dashboard from one aggregate query.

The database path comes from `DATABASE_PATH` (defaults to the local file). SQLite runs in WAL mode with a busy
timeout; `backup_db()` takes a daily snapshot into `backups/`.

The database file (`expense_tracker.db`) is gitignored.

### Templates
Jinja2 templates in `templates/`. All pages extend `base.html`, which provides the navbar, footer, and loads `static/css/style.css` and `static/js/main.js`. Pages that need extra CSS (e.g., `landing.html`) use `{% block head %}` to add a page-specific stylesheet.

### Static assets
- `static/css/style.css` — global styles (navbar, footer, shared components)
- `static/css/landing.css` — landing-page-only styles
- `static/js/main.js` — global JS; landing page's YouTube modal JS is inlined in the template via `{% block scripts %}`

## Planned route structure (student implementation steps)

| Route | Status |
|---|---|
| `/`, `/login`, `/register`, `/terms`, `/privacy` | Implemented |
| `/logout` | Step 3 |
| `/profile` | Step 4 |
| `/expenses/add` | Step 7 |
| `/expenses/<id>/edit` | Step 8 |
| `/expenses/<id>/delete` | Step 9 |
| `/events`, `/events/new`, `/events/<id>`, `/events/<id>/edit`, `/events/<id>/delete` | Step 10 |
| `/healthz` | Step 11 |

Phone/PWA work (production hosting, quick-add page, installable app, back-tap) is Steps 13–20 in `PHONE_PLAN.md`.
System-design decisions and what was deliberately deferred: `docs/ARCHITECTURE_REVIEW.md`.

## Key conventions

- Placeholder routes return a plain string like `"Feature — coming in Step N"` until implemented.
- SQLite is the only database; no ORM. Raw SQL via the `database/db.py` helpers.
- No authentication middleware exists yet; session handling will be added in a later step.
- The app name in UI is **Bahi-Khata**; the repo/Python module is `expense_tracker`.
