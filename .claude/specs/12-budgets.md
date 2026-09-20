# Spec: Monthly Category Budgets

## Overview
Step 12 adds a recurring monthly budget per category — the counterpart to the one-off event budget from Step 10.
The dashboard shows how this month is tracking per category and gives a single "safe to spend per day" number for
the rest of the month.

## Depends on
- Step 10 (events) — reuses the `_budget_view()` helper and the budget bar styling
- Step 11 — the dashboard query shape

## Routes
- `GET /budgets` — every category with its monthly amount, plus this month's totals — logged-in only
- `POST /budgets` — saves all categories at once; a blank value clears that category's budget

## Database changes
New `budgets` table: `id`, `user_id`, `category`, `monthly_amount`, `updated_at`, `UNIQUE(user_id, category)`.

## Templates
- **Create:** `budgets.html`
- **Modify:** `profile.html` (budget block plus an empty-state prompt), `base.html` (navbar link)

## Files to change
`database/db.py`, `database/queries.py` (`get_budgets`, `get_month_budget_status`), `app.py`,
`static/css/style.css`

## Files to create
`templates/budgets.html`, `tests/test_12_budgets.py`

## New dependencies
None.

## Rules for implementation
- Budget amounts must be positive; blank means "not budgeted", not zero
- Only budgeted categories count toward the totals and the safe-to-spend figure
- Event spending counts toward budgets — it is still money spent
- Safe to spend = (total budget − spent this month) ÷ days remaining including today, never negative
- Bars: amber from 80 %, red past 100 %, and the bar itself never exceeds full width

## Acceptance criteria
- [ ] A user can set, change and clear a budget per category
- [ ] The dashboard shows spent vs budget per category with the right colour, and the safe-to-spend line
- [ ] Going over shows the overspend and the days remaining, in red
- [ ] Spending in other months, other categories and other users never leaks in
- [ ] `pytest tests/test_12_budgets.py` passes
