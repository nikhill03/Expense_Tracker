# Spec: Events

## Overview
Step 10 lets a user group expenses under an **event** — a trip, a festival, a wedding — so they can see what that
occasion cost and compare it against a budget. An event holds a name, optional start/end dates and an optional budget.
Expenses keep an optional `event_id`; an expense with no event behaves exactly as before.

Event expenses **stay part of the main list and the dashboard totals** (they are real spending) and show a small event
chip in the transaction rows. The dashboard gains an "Exclude event spending" toggle for an everyday-only view.

## Depends on
- Step 5 (backend connection) — `get_db()` and the query helpers in `database/queries.py`
- Step 7/8/9 (add, edit, delete expense) — the expense routes that now carry an optional event

## Routes
- `GET  /events` — list the user's events with spend vs budget — logged-in only
- `GET|POST /events/new` — create an event — logged-in only
- `GET  /events/<int:event_id>` — event detail: stats, category breakdown, its expenses — owner only
- `GET|POST /events/<int:event_id>/edit` — update an event — owner only
- `POST /events/<int:event_id>/delete` — delete the event, keep its expenses — owner only

Changed: `/expenses/add` accepts an optional `event_id` field and an `?event=<id>` query parameter to preselect one;
`/expenses/<id>/edit` can change or clear an expense's event; `/profile` accepts `?events=exclude`.

## Database changes
New `events` table: `id`, `user_id` (FK users), `name`, `start_date`, `end_date`, `budget`, `created_at`.
New nullable column `expenses.event_id` (FK events), added to existing databases by `_add_column_if_missing()` in
`database/db.py`. Indexes: `idx_expenses_event`, `idx_events_user`.

## Templates
- **Create:** `events.html` (list), `event_detail.html`, `event_form.html` (shared by create and edit)
- **Modify:** `base.html` (navbar "Events" link), `add_expense.html` + `edit_expense.html` (optional event select),
  `profile.html` + `expenses.html` (event chip, exclude toggle)

## Files to change
- `database/db.py` — `events` table, `event_id` column, migration helper, indexes
- `database/queries.py` — `_event_where()`; `event_id` / `exclude_events` keyword arguments on the four expense
  queries; new `get_events_for_user()`, `get_event_by_id()`, `get_event_summary()`
- `app.py` — `_parse_event_form()`, `_resolve_event_id()`, `_owned_event_or_abort()`, the five event routes, and the
  event handling in `add_expense` / `edit_expense` / `profile`
- `static/css/style.css` — event card, budget bar, event badge styles

## Files to create
- `tests/test_10_events.py`

## New dependencies
None.

## Rules for implementation
- No SQLAlchemy or ORMs; parameterised queries only
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- `abort(404)` when an event does not exist, `abort(403)` when it belongs to another user
- An `event_id` posted by a user who does not own that event is ignored (treated as "no event")
- Deleting an event **never** deletes expenses — it clears their `event_id` first
- Budget is optional; when absent the event page shows spend only
- Existing query signatures stay backwards compatible (new arguments are keyword-only with defaults)

## Acceptance criteria
- [ ] A logged-in user can create, view, edit and delete their own events
- [ ] Event detail shows total spent, expense count, budget remaining (or over-budget) and a category breakdown
- [ ] An expense can be tagged to an event when added or edited, and untagged again
- [ ] Event expenses appear in `/profile` and `/expenses` with a clickable event chip
- [ ] `/profile?events=exclude` hides event spending from the totals, list and category breakdown
- [ ] Another user's event returns 403; a missing event returns 404; logged-out requests redirect to `/login`
- [ ] Deleting an event keeps its expenses, with `event_id` cleared
- [ ] `pytest tests/test_10_events.py` passes
