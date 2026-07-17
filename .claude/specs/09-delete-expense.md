# Spec: Delete Expense

## Overview
Step 9 implements the delete expense route, completing the full CRUD lifecycle for expenses in Spendly. The stub at `POST /expenses/<id>/delete` already exists in `app.py` and the delete buttons are already rendered in both `expenses.html` and `profile.html`. This step replaces the stub with real logic: verify the expense exists, verify it belongs to the logged-in user, delete it from the database, and redirect back to the referring page.

## Depends on
- Step 5 (backend connection) — `get_db()` must work
- Step 7 (add expense) — expenses table must exist and be populated
- Step 8 (edit expense) — `get_expense_by_id()` query helper is already in place and reused here

## Routes
- `POST /expenses/<int:expense_id>/delete` — deletes the expense with the given ID — logged-in only

## Database changes
No database changes. The `expenses` table already has all required columns.

## Templates
- **Create:** None
- **Modify:** None — both `expenses.html` and `profile.html` already render a `<form method="post">` delete button for each row pointing at this route

## Files to change
- `app.py` — replace the stub body of `delete_expense()` with the real implementation

## Files to create
None.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only — never interpolate user input into SQL strings
- Passwords hashed with werkzeug (not relevant here but kept as a standing rule)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Redirect to `url_for('expenses')` after a successful delete (the expenses list page)
- Use `get_expense_by_id(expense_id)` (already imported) to fetch the row before deleting
- Return `abort(404)` if the expense does not exist
- Return `abort(403)` if `expense["user_id"] != session["user_id"]`
- Use `WHERE id = ? AND user_id = ?` in the DELETE query as a second ownership check
- Do **not** use GET for delete — the route must only accept POST

## Definition of done
- [ ] Clicking **Delete** on any expense row in `/expenses` removes the row and redirects back to `/expenses`
- [ ] Clicking **Delete** on any row in `/profile` (Recent Transactions) removes the row and redirects to `/expenses`
- [ ] Deleting an expense owned by the logged-in user returns a 302 redirect (not an error)
- [ ] The deleted expense no longer appears in the expenses list or profile page after deletion
- [ ] Attempting to delete a non-existent expense ID returns a 404 page
- [ ] Attempting to delete another user's expense (mismatched `user_id`) returns a 403 page
- [ ] Sending a GET request to `/expenses/<id>/delete` returns 405 Method Not Allowed
- [ ] A logged-out user attempting to POST to `/expenses/<id>/delete` is redirected to `/login`
