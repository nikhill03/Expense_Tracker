# Spec: Edit Expense

## Overview
This feature allows a logged-in user to edit an existing expense. When the user clicks an "Edit" button on the expenses list, they are taken to a pre-filled form showing the current values for amount, category, date, and description. On submission the expense record is updated in the database and the user is redirected back to the expenses list. An ownership check ensures users can only edit their own expenses (not another user's).

## Depends on
- Step 5 (backend connection) — `get_db()` from `database/db.py`
- Step 7 (add expense) — the `expenses` table must exist with `id`, `user_id`, `amount`, `category`, `date`, `description` columns

## Routes
- `GET /expenses/<int:id>/edit` — render pre-filled edit form — logged-in only
- `POST /expenses/<int:id>/edit` — process form submission and update the expense — logged-in only

## Database changes
No database changes. The existing `expenses` table has all required columns.

## Templates
- **Create:** `templates/edit_expense.html` — edit form, pre-filled with existing expense data; mirrors `add_expense.html` in structure
- **Modify:** `templates/expenses.html` — add an "Actions" column to the table with Edit and Delete buttons per row

## Files to change
- `app.py` — replace the `edit_expense` placeholder with a full GET/POST implementation

## Files to create
- `templates/edit_expense.html`

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug (not applicable here, but noted for convention)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Ownership check: after fetching the expense by `id`, confirm `expense["user_id"] == session["user_id"]`; if not, return `abort(403)`
- If the expense `id` does not exist, return `abort(404)`
- On GET: fetch the expense row and pass its fields into the template so the form is pre-filled
- On POST: apply the same validation rules as `add_expense` (amount > 0, valid category, valid ISO date, description ≤ 255 chars); on failure, redisplay the form with the error message and the submitted values
- On success: run `UPDATE expenses SET amount=?, category=?, date=?, description=? WHERE id=? AND user_id=?` and redirect to `url_for("expenses")`
- Import `abort` from `flask` at the top of `app.py` if not already present
- The route decorator must accept both GET and POST: `methods=["GET", "POST"]`
- Reuse the `EXPENSE_CATEGORIES` constant from `app.py` for populating the category `<select>`

## Definition of done
- [ ] Visiting `/expenses/<id>/edit` while logged in shows a form pre-filled with the expense's current amount, category, date, and description
- [ ] Submitting the form with valid data updates the record in the database and redirects to `/expenses`
- [ ] The updated values are visible in the expenses list immediately after redirect
- [ ] Submitting with an invalid amount (e.g. `-10`, `abc`) redisplays the form with an error message and preserves the other field values
- [ ] Submitting with no category selected redisplays the form with an error message
- [ ] Submitting with an empty date redisplays the form with an error message
- [ ] Visiting `/expenses/<id>/edit` while logged out redirects to `/login`
- [ ] Attempting to edit another user's expense returns 403
- [ ] Attempting to edit a non-existent expense id returns 404
- [ ] The expenses list (`/expenses`) shows Edit and Delete action buttons for each row
- [ ] Clicking "Edit" from the expenses list navigates to the correct pre-filled form
