# Spec: Quick-Add Refinements — Events, Dates and the App Clock

## Overview
Step 13 fixes three things the quick-add sheet got wrong once it met a real event page.
An expense could not be attached to an event from the sheet, backdating a forgotten expense took
three interactions, and the server's idea of "today" was the server's calendar day rather than the
user's — so every expense logged between midnight and 5:30am IST was dated to the previous day.

## Depends on
- Step 10 (events) — reuses `_resolve_event_id()` and the events table
- Step 12 (budgets) — `get_month_budget_status()` now takes its month from the app clock
- PHONE_PLAN Step 15 (quick add) — this refines the sheet that step introduced

## Routes
No new routes. `/quick`, `/expenses/add` and `/expenses/<id>/edit` change behaviour:
they now refuse a date in the future or more than `MAX_BACKDATE_YEARS` in the past, and
they store a normalised `YYYY-MM-DD` rather than whatever string was submitted.

## Database changes
None. `idx_events_user` (Step 11) already covers the new picker query.

## Templates
- **Modify:** `_quick_form.html` (event picker made reachable; date row rebuilt),
  `base.html` (passes the page's event to the sheet), `quick_add.html`,
  `_expense_form.html` (`min`/`max` on the date field)

## Files to change
`app.py`, `database/queries.py`, `database/db.py`, `requirements.txt`,
`static/css/src/app.css`, `static/js/main.js`

## Files to create
`timeutil.py`, `tests/test_14_dates_and_timezone.py`

## New dependencies
`tzdata` — `zoneinfo` reads the system tz database, which slim deploy images do not ship.
Stdlib otherwise; no new runtime service.

## Rules for implementation
- Attaching an expense to an event is **optional**. The picker is hidden entirely when the
  user has no events, and always offers "Not part of an event".
- Opening the sheet from an event page preselects that event. The preselection is a UI hint
  only — the options are already scoped to the signed-in user, and `_resolve_event_id()`
  re-checks ownership on POST regardless of what the form said.
- A redisplayed form keeps what was posted, including a deliberate "no event". Only a fresh
  form falls back to the page's event.
- The picker uses `get_event_options()` (id + name), never `get_events_for_user()`, which
  aggregates over every expense. It is cached on `g` for the request, so a page with two
  pickers still queries once.
- Every user-facing calendar date goes through `timeutil.today()`. Never `date.today()`.
- The login lockout keeps naive `datetime.now()` on purpose — it measures a duration, and
  both sides of the comparison must use the same clock.
- An expense dated outside its event's start/end saves silently. Booking flights weeks before
  a trip is normal and that spend belongs to the trip's budget.
- Store `date.fromisoformat(x).isoformat()`, never the raw string: `fromisoformat` also accepts
  `20260920` and `2026-W38-7`, and every filter compares `YYYY-MM-DD` lexically.
- The date row's `min`/`max` are a browser convenience. The server revalidates.

## Acceptance criteria
- The sheet on an event page preselects that event; saving attaches the expense to it.
- The sheet on `/profile` preselects nothing and still offers every event.
- One tap on "Dated today" opens the phone's calendar. The row reads "Dated 19 Sep" afterwards,
  rendered server-side so it is correct with JavaScript blocked.
- With the process clock in UTC at 22:00 on the 19th, the app dates an expense to the 20th.
- A future date, and one more than five years old, are refused with a message; the form comes
  back holding what the user typed.
- `/profile` stays within its query budget (now 5, the fifth being the picker).
- `scripts/ui_audit.py` stays green: 462 checks across 360/390/768/1280px.
