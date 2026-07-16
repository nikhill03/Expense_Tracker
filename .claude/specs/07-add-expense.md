# Spec: Add Expense

## Overview
This step implements the `/expenses/add` route so logged-in users can record a new expense. A GET request renders a form with fields for amount, category, date, and an optional description. A POST request validates the input, inserts a new row into the `expenses` table, and redirects to `/expenses` on success. The route replaces the existing placeholder string that was left in Step 6. This is the first write operation students implement on the `expenses` table.

## Depends on
- Step 1 — Database setup (`expenses` table and `get_db()` must exist)
- Step 3 — Login / Logout (`session["user_id"]` is set on login)
- Step 6 — Date filter (`/expenses` listing page exists to redirect back to)

## Routes
- `GET /expenses/add` — render the add-expense form — logged-in only
- `POST /expenses/add` — validate and insert the new expense, then redirect to `/expenses` — logged-in only

## Database changes
No database changes. The `expenses` table already has all required columns: `user_id`, `amount`, `category`, `date`, `description`.

## Templates
- **Create:** `templates/add_expense.html` — extends `base.html`; contains:
  1. **Page header** — title "Add Expense" and a "Back to Expenses" link pointing to `url_for('expenses')`
  2. **Form** — `method="post"` targeting `/expenses/add`; fields:
     - `amount` — `<input type="number" step="0.01" min="0.01">` (required)
     - `category` — `<select>` with fixed options: Food, Transport, Bills, Health, Entertainment, Shopping, Other (required)
     - `date` — `<input type="date">` pre-filled with today's date (required)
     - `description` — `<input type="text">` (optional, max 255 chars)
     - Submit button labelled "Add Expense"
  3. **Inline error message** — displayed above the form when validation fails; re-fills all fields with the submitted values so the user does not lose their input

## Files to change
- `app.py` — replace the existing `GET /expenses/add` stub with a full `GET`+`POST` route named `add_expense`

## Files to create
- `templates/add_expense.html`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs — raw SQL only via `get_db()`
- Parameterised queries only — never string-format values into SQL
- Passwords hashed with werkzeug (not relevant here, included for consistency)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Authentication guard on both GET and POST: `if not session.get("user_id"): redirect(url_for("login"))`
- `user_id` for the INSERT must come from `session["user_id"]` — never from the form
- Validation rules (return form with error on failure, re-filling submitted values):
  - `amount` must be present and convertible to a positive float (> 0)
  - `category` must be one of the seven fixed options
  - `date` must be present and in `YYYY-MM-DD` format
  - `description` is optional; store `None` / empty string if blank
- On success, redirect to `url_for('expenses')` — do not render a template
- The date field default (`today.isoformat()`) must be computed server-side and passed to the GET template — do not rely on JavaScript for the default

## Definition of done
- [ ] Visiting `/expenses/add` without being logged in redirects to `/login`
- [ ] Visiting `/expenses/add` while logged in returns HTTP 200 and shows the form
- [ ] The date field is pre-filled with today's date on GET
- [ ] Submitting the form with all valid fields inserts a row and redirects to `/expenses`
- [ ] The new expense appears in the `/expenses` list immediately after redirect
- [ ] Submitting with a missing or zero amount re-renders the form with an error message
- [ ] Submitting with an invalid category re-renders the form with an error message
- [ ] Submitting with a missing date re-renders the form with an error message
- [ ] After a validation error, all previously entered field values are re-filled in the form
- [ ] `user_id` is always taken from the session, not from any form field
- [ ] The app starts without errors (`python app.py`)
