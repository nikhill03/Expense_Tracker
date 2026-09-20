# Bahi-Khata

A personal expense tracker for Indian users (₹), built with Flask and SQLite.
Designed to be used on a phone: log an expense in a few seconds against a bank
debit notification, then see where the money actually went.

## Features

- Log expenses by amount, category, date and remark
- **Quick add** (`/quick`) — a thumb-sized screen a back-tap or a shared debit SMS
  can open, with the amount read out of the message
- **Events** — group spending for a trip, festival or occasion, with its own budget
- **Monthly budgets** per category, with a "safe to spend per day" figure
- Date filtering, category breakdown, light and dark themes

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm install                 # Tailwind CLI only; no runtime JS dependencies
```

## Running

```bash
npm run build:css           # required — see "Stylesheet" below
python app.py               # http://localhost:5001
```

## Stylesheet

The UI is built with Tailwind CSS v4. **`static/css/src/app.css` is the source;
`static/css/app.css` is the compiled output that the templates load.**

Run `npm run build:css` after changing any template or the source CSS, or keep
`npm run watch:css` running while developing. Editing a template without
rebuilding means the new utility classes do not exist in the compiled file and
the page renders unstyled.

The compiled `static/css/app.css` is committed on purpose: deployment runs
gunicorn directly with no Node step, so a gitignored build output would ship a
site with no styles.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `production` requires a real `SECRET_KEY`, sends `Secure` cookies, trusts the proxy headers, and never seeds the sample data or demo login. |
| `SECRET_KEY` | a placeholder, development only | Signs the session cookie. **Required in production** — the app refuses to start without it, rather than falling back to a value that is in this repo. |
| `DATABASE_PATH` | `expense_tracker.db` | SQLite file location. Point at a mounted volume in production so data survives a redeploy. Daily backups are written to a `backups/` directory beside it. |
| `APP_TIMEZONE` | `Asia/Kolkata` | The calendar day the app uses. Set this to the users' zone, not the server's — see below. |
| `ALLOW_REGISTRATION` | `true` | Set to `false` to close `/register` on a public instance; the sign-up links disappear with it. |
| `PORT` | `5001` | Port to bind. |

`.env.example` lists the same set with safe placeholder values. `.env` is gitignored.

**On `APP_TIMEZONE`:** expense dates are what a person would write in a ledger, so
they follow the user's calendar day rather than the server's. A UTC host would
otherwise date every expense logged before 05:30 IST to the previous day. All
user-facing dates go through `timeutil.today()`; never `date.today()`.

## Deploying

The app runs on Railway: gunicorn from the `Procfile`, SQLite on a volume mounted at
`/data`, `/healthz` as the healthcheck. Set `APP_ENV=production`, a real `SECRET_KEY`
and `DATABASE_PATH=/data/expense_tracker.db`, or the deploy will either refuse to
start or throw the data away on the next redeploy.

Full runbook — variables, volume, rollback, restoring a backup, rotating the secret:
**`docs/DEPLOYMENT.md`**.

## Testing

```bash
pytest                                              # unit and route tests
pytest tests/test_13_quick_add.py                   # a single file

# Browser-driven UI audit — needs the dev server running
pip install playwright && playwright install chromium
python scripts/ui_audit.py --base http://127.0.0.1:5001
```

`scripts/ui_audit.py` drives Chromium over the whole app at 360/390/768/1280px
and checks tap-target sizes, accessible names, landmarks, heading order, console
errors, the theme toggle and the quick-add sheet. It exits non-zero on failure,
so it can gate a commit or a CI job.

## Layout

```
app.py                 all routes
timeutil.py            the app's calendar day (see APP_TIMEZONE)
database/db.py         connection, schema, migrations, backups
database/queries.py    read queries
templates/             Jinja2; partials are prefixed with _
static/css/src/        Tailwind source (the design system)
static/css/app.css     compiled output — committed, do not edit by hand
scripts/ui_audit.py    browser-driven accessibility and layout checks
docs/                  architecture notes and the deployment runbook
```

## Conventions

- SQLite only, no ORM. Raw SQL through the `database/db.py` helpers.
- Colour is reserved for budget status and always ships with a glyph and words;
  category identity comes from its text label.
- Anything tappable is at least 44px. `scripts/ui_audit.py` enforces it.
- New colours go in as tokens in `static/css/src/app.css`. Never hardcode a hex
  in a template.
