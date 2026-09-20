# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

**Bahi-Khata** is a Flask-based personal expense tracker web app targeting Indian users (currency: ₹). It is structured as a teaching project where students implement features step-by-step. The current state is a pre-auth scaffold: landing page, login/register stubs, and placeholder routes for the full CRUD flow.

## Commands

```bash
# Run the development server (port 5001)
python app.py

# Rebuild the stylesheet — required after editing any template or src CSS
npm run build:css
npm run watch:css          # rebuild on every save while developing

# Run all tests
pytest

# Run a single test file
pytest tests/test_auth.py

# Run a single test
pytest tests/test_auth.py::test_login_page

# Browser-driven UI audit (needs the dev server running)
python scripts/ui_audit.py --base http://127.0.0.1:5001
```

Install dependencies:
```bash
pip install -r requirements.txt
npm install                                  # Tailwind CLI only
pip install playwright && playwright install chromium   # for scripts/ui_audit.py
```

## Architecture

### Entry point
`app.py` — single-file Flask app. All routes live here. The app runs on port 5001 with `debug=True`.

### Dates and the app clock
`timeutil.py` is the single source of truth for what day it is. **Every user-facing calendar
date goes through `timeutil.today()` — never `date.today()`.** The server runs in UTC on
Railway while the users are in India, so reading the process clock dated every expense logged
before 05:30 IST to the previous day. `APP_TIMEZONE` (default `Asia/Kolkata`) sets the zone;
an unresolvable value logs an error and falls back rather than taking the app down.

Deliberate exception: the login lockout (`_login_lock_remaining`, `_record_login_failure`)
keeps naive `datetime.now()`. It measures a 15-minute duration, both sides of the comparison
use the same clock, and mixing aware and naive datetimes there would raise on rows written
by the old code.

`_parse_expense_form` rejects dates in the future and more than `MAX_BACKDATE_YEARS` old, and
**stores the normalised `YYYY-MM-DD`**. This matters: `date.fromisoformat` also accepts
`20260920` and `2026-W38-7`, and every query compares dates as strings — an un-normalised
date sorts outside its own month, so the expense vanishes from every filtered view while
still counting in the totals.

### Database layer
`database/db.py` — students implement three functions here:
- `get_db()` — returns a SQLite connection (`expense_tracker.db`) with `row_factory` and foreign keys enabled
- `init_db()` — creates tables with `CREATE TABLE IF NOT EXISTS`, then adds any missing columns via `_add_column_if_missing()` so existing databases migrate in place
- `seed_db()` — inserts sample rows for development

Tables: `users`, `expenses` (with a nullable `event_id`), `events` (name, optional `start_date`/`end_date`/`budget`),
`budgets` (monthly amount per category), `login_attempts` (failed-login throttling).
Read queries live in `database/queries.py`; the expense queries take keyword-only `event_id` / `exclude_events`
filters, and `get_dashboard()` serves the whole dashboard from one aggregate query.

The database path comes from `DATABASE_PATH` (defaults to the local file). SQLite runs in WAL mode with a busy
timeout; `backup_db()` takes a daily snapshot into `backups/`.

The database file (`expense_tracker.db`) is gitignored.

### Templates
Jinja2 templates in `templates/`. All pages extend `base.html`, which provides the header,
the bottom tab bar, the quick-add sheet, and loads `static/css/app.css` and `static/js/main.js`.
There are no per-page stylesheets — one compiled stylesheet covers the whole app.

Partials, all prefixed with `_`:
- `_quick_form.html` — the quick-add form, rendered into two hosts (the popover sheet
  in `base.html`, and the standalone `/quick` page)
- `_tx_rows.html` — `tx_rows()` (expenses as ruled rows) and `category_meters()`
- `_expense_form.html` — `expense_fields()` and the `form_page()` wrapper
- `_theme_toggle.html` — the light/dark control

### Styling — Tailwind CSS v4, with a build step
`static/css/src/app.css` is the **source**; `static/css/app.css` is the **compiled output
that templates load**. Editing a template without rebuilding means new utility classes
won't exist in the CSS, so run `npm run build:css` (or keep `npm run watch:css` running).

The compiled `static/css/app.css` **is committed**, because Railway deploys straight from
gunicorn with no Node step — if it were gitignored, production would have no styles.

`src/app.css` is the design system, not a dumping ground:
- `@theme` maps semantic tokens (`paper`, `ink`, `rule`, `lac`, `good`, `warn`) onto
  Tailwind's namespaces, so `bg-paper` / `text-ink` follow the theme with no `dark:` prefix.
- Only the raw `--c-*` values are restated per theme, under `:root` and `[data-theme="dark"]`.
- `@layer components` holds the reusable pieces: `.btn`, `.field`, `.chip`, `.meter`,
  `.ruled`, `.panel`, `.glass`, `.status`, `.tag`.
- New colours go in as tokens. Never hardcode a hex in a template.

Theme is resolved by an inline script in `base.html` *before first paint*, so a dark
phone never flashes white; `static/js/main.js` only wires the toggle afterwards.

### Static assets
- `static/css/src/app.css` — design-system source (Tailwind v4, `@theme` + `@layer`)
- `static/css/app.css` — compiled, committed, loaded by `base.html`
- `static/js/main.js` — progressive enhancement only: theme toggle, quick-add sheet
  behaviour, `data-confirm` on destructive forms. Every page works without it.

### Layout conventions
- **Rules, not cards.** Lists are ruled rows (`.ruled` / `.ruled-row`), not a deck of
  boxed cards. Elevation and blur (`.glass`) are reserved for surfaces that float over
  content: the quick-add sheet, the bottom tab bar, the sticky header.
- **Colour is reserved.** Category identity comes from its text label; the meters use a
  single hue. Colour only ever signals budget status, and always travels with a glyph
  and words (`.status-good` / `.status-warn` / `.status-over`).
- **44px minimum** for anything tappable. `scripts/ui_audit.py` enforces it.
- Navigation is a bottom tab bar under `lg:`, the header nav above it.
- The quick-add sheet's event picker reads `get_event_options()` (id + name), cached on `g`
  for the request — never `get_events_for_user()`, which aggregates over every expense. The
  sheet renders on every signed-in page, so `/profile`'s query budget is 5, not 4.

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
| `/budgets` | Step 12 |
| `/quick` | Step 15 — mobile quick-add, prefilled from a debit SMS link |

Phone/PWA work is Steps 13–20 in `PHONE_PLAN.md`. Step 15 (quick-add) is done;
Step 16 (manifest, service worker, installable PWA) is not.

`/quick` accepts a prefilled link — `?amount=350&category=Food&remark=...`, or raw
message text via `?text=...`, which `parse_amount_from_text()` reads an amount out of.
**A GET never writes.** The link only fills the form; nothing is saved until the user
taps Save. Keep it that way — it is what makes an automation-built link safe.
System-design decisions and what was deliberately deferred: `docs/ARCHITECTURE_REVIEW.md`.

## Key conventions

- Placeholder routes return a plain string like `"Feature — coming in Step N"` until implemented.
- SQLite is the only database; no ORM. Raw SQL via the `database/db.py` helpers.
- No authentication middleware exists yet; session handling will be added in a later step.
- The app name in UI is **Bahi-Khata**; the repo/Python module is `expense_tracker`.
