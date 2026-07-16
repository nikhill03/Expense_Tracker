# Spec: Date Filter

## Overview
This step introduces a dedicated `/expenses` listing page where logged-in users can view all their expenses filtered by a date range. A "From" and "To" date picker form submits as a GET request, reloading the page with `?from=YYYY-MM-DD&to=YYYY-MM-DD` query parameters. The page defaults to the current calendar month when no dates are provided. A filtered total is shown above the table so the user immediately sees how much they spent in the selected window. This page also serves as the foundation for the upcoming add, edit, and delete routes (Steps 7–9), which will link back to it.

## Depends on
- Step 1 — Database setup (`expenses` table and `get_db()` must exist)
- Step 3 — Login / Logout (`session["user_id"]` is set on login)
- Step 5 — Backend connection (`database/queries.py` already exists; new helper appended here)

## Routes
- `GET /expenses` — show all user expenses filtered by date range — logged-in only (redirect to `/login` if not authenticated)

## Database changes
No database changes. The `expenses` table already has a `date TEXT NOT NULL` column in `YYYY-MM-DD` format, which SQLite can compare with `>=` / `<=` operators on plain strings.

## Templates
- **Create:** `templates/expenses.html` — extends `base.html`; contains:
  1. **Page header** — title "My Expenses" and a "+ Add Expense" button (links to `url_for('add_expense')`, which is still a placeholder)
  2. **Date filter form** — two `<input type="date">` fields ("From" and "To") plus a "Filter" submit button; form `method="get"` so dates appear in the URL
  3. **Filtered total** — a single line showing total spent in the selected range (e.g. "Total: ₹5,200.00")
  4. **Expense table** — columns: Date, Description, Category (badge), Amount; rows from the filtered query; if no expenses match, show an empty-state message ("No expenses found for this date range.")
- **Modify:** `templates/profile.html` — add a "View all" link next to the "Recent Transactions" heading that points to `url_for('expenses')`

## Files to change
- `app.py` — add `GET /expenses` route named `expenses`
- `database/queries.py` — append `get_filtered_expenses(user_id, from_date, to_date)` helper
- `templates/profile.html` — add "View all" link on the Recent Transactions section header

## Files to create
- `templates/expenses.html`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw SQL only via `get_db()`
- Parameterised queries only — never string-format values into SQL
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Authentication guard: `if not session.get("user_id"): redirect(url_for("login"))`
- Default date range: first day of the current month (`YYYY-MM-01`) to today (`YYYY-MM-DD`); compute with Python's `datetime` module — do not hardcode dates
- Read `from_date` and `to_date` from `request.args`; fall back to the defaults if either is absent or blank
- The filter form must pre-fill with the active `from_date` and `to_date` values so the user sees what range is applied
- `get_filtered_expenses` must return a list of dicts (or `sqlite3.Row` objects) with keys: `date`, `description`, `category`, `amount`; ordered by `date DESC`, then `id DESC` so newest appears first
- `get_filtered_expenses` must also compute and return the filtered total; implement this as a second query or a Python `sum()` over the returned rows — either is acceptable
- All currency amounts on the page must display the ₹ symbol
- Category badges must use the same CSS class pattern already in `profile.html`: `badge badge--{{ category | lower | replace(' ', '-') }}`
- The "View all" link added to `profile.html` must be plain text styled with the existing link colour variable — no new CSS classes

## Definition of done
- [ ] Visiting `/expenses` without being logged in redirects to `/login`
- [ ] Visiting `/expenses` while logged in returns HTTP 200
- [ ] The page defaults to showing expenses for the current month (no query params needed)
- [ ] The date filter form pre-fills with the currently active date range
- [ ] Submitting the filter form reloads the page with `?from=…&to=…` in the URL
- [ ] Only expenses whose `date` falls within `[from_date, to_date]` (inclusive) are shown
- [ ] The filtered total shown matches the sum of the displayed rows
- [ ] All amounts on the page display the ₹ symbol
- [ ] When no expenses match the filter, the empty-state message is shown and the total is ₹0.00
- [ ] Category badges render with the correct CSS class (no inline colours)
- [ ] The profile page "Recent Transactions" section has a "View all" link pointing to `/expenses`
- [ ] The app starts without errors (`python app.py`)
