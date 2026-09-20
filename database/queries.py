from calendar import monthrange
from datetime import datetime

import timeutil
from database.db import get_db


def get_user_by_id(user_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    name = row["name"]
    initials = "".join(w[0].upper() for w in name.split()[:2])

    try:
        member_since = datetime.strptime(
            row["created_at"], "%Y-%m-%d %H:%M:%S"
        ).strftime("%B %Y")
    except (ValueError, TypeError):
        member_since = row["created_at"]

    return {
        "name": name,
        "email": row["email"],
        "member_since": member_since,
        "initials": initials,
    }


def _date_where(from_date, to_date):
    """Return (extra_where_clauses, extra_params) for optional date filtering."""
    clauses, params = [], []
    if from_date:
        clauses.append("date >= ?")
        params.append(from_date)
    if to_date:
        clauses.append("date <= ?")
        params.append(to_date)
    return clauses, params


def _event_where(event_id, exclude_events, prefix=""):
    """Return (extra_where_clauses, extra_params) for optional event filtering.

    `event_id` limits to one event; `exclude_events` keeps only expenses that
    belong to no event. `prefix` is a table alias such as "e." when joining.
    """
    clauses, params = [], []
    if event_id is not None:
        clauses.append(f"{prefix}event_id = ?")
        params.append(event_id)
    elif exclude_events:
        clauses.append(f"{prefix}event_id IS NULL")
    return clauses, params


def get_summary_stats(
    user_id, from_date=None, to_date=None, *, event_id=None, exclude_events=False
):
    date_clauses, date_params = _date_where(from_date, to_date)
    event_clauses, event_params = _event_where(event_id, exclude_events)
    where = " AND ".join(["user_id = ?"] + date_clauses + event_clauses)
    params = [user_id] + date_params + event_params

    conn = get_db()
    try:
        agg = conn.execute(
            f"SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS cnt FROM expenses WHERE {where}",
            params,
        ).fetchone()

        top_row = conn.execute(
            f"SELECT category FROM expenses WHERE {where} GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
            params,
        ).fetchone()
    finally:
        conn.close()

    top_category = top_row["category"] if top_row else "—"

    return {
        "total_spent": f"₹{agg['total']:,.2f}",
        "transaction_count": agg["cnt"],
        "top_category": top_category,
    }


def _summary_from_rows(rows):
    """Build the three dashboard stat cards from one GROUP BY category pass."""
    total = sum(row["total"] for row in rows)
    count = sum(row["cnt"] for row in rows)
    top_category = rows[0]["category"] if rows else "—"
    return {
        "total_spent": f"₹{total:,.2f}",
        "transaction_count": count,
        "top_category": top_category,
    }


def _breakdown_from_rows(rows):
    """Build the category bars from the same pass. Percentages sum to 100."""
    if not rows:
        return []

    grand_total = sum(row["total"] for row in rows)
    items = [
        {
            "name": row["category"],
            "amount": f"₹{row['total']:,.2f}",
            "pct": int(row["total"] / grand_total * 100),
        }
        for row in rows
    ]
    items[0]["pct"] += 100 - sum(item["pct"] for item in items)
    return items


def get_dashboard(user_id, from_date=None, to_date=None, *, exclude_events=False):
    """Stats and category breakdown in a single query.

    The per-category aggregate already contains the total, the transaction
    count and the top category, so the dashboard does not need separate
    queries for them.
    """
    date_clauses, date_params = _date_where(from_date, to_date)
    event_clauses, event_params = _event_where(None, exclude_events)
    where = " AND ".join(["user_id = ?"] + date_clauses + event_clauses)
    params = [user_id] + date_params + event_params

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT category, SUM(amount) AS total, COUNT(*) AS cnt FROM expenses"
            f" WHERE {where} GROUP BY category ORDER BY total DESC",
            params,
        ).fetchall()
    finally:
        conn.close()

    return _summary_from_rows(rows), _breakdown_from_rows(rows)


def get_recent_transactions(
    user_id,
    limit=10,
    from_date=None,
    to_date=None,
    *,
    event_id=None,
    exclude_events=False,
):
    date_clauses, date_params = _date_where(from_date, to_date)
    event_clauses, event_params = _event_where(event_id, exclude_events, prefix="e.")
    where = " AND ".join(["e.user_id = ?"] + date_clauses + event_clauses)
    params = [user_id] + date_params + event_params

    sql = (
        "SELECT e.id, e.date, e.description, e.category, e.amount,"
        " e.event_id, ev.name AS event_name"
        " FROM expenses e LEFT JOIN events ev ON ev.id = e.event_id"
        f" WHERE {where} ORDER BY e.date DESC, e.id DESC"
    )
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        result.append(
            {
                "id": row["id"],
                # ISO, like get_filtered_expenses — a date that has been turned into
                # words can no longer be compared or sorted. The `dmy` filter does the
                # formatting in the template, where it belongs.
                "date": row["date"],
                "description": row["description"],
                "category": row["category"],
                "amount": f"₹{row['amount']:,.2f}",
                "event_id": row["event_id"],
                "event_name": row["event_name"],
            }
        )
    return result


def get_category_breakdown(
    user_id, from_date=None, to_date=None, *, event_id=None, exclude_events=False
):
    date_clauses, date_params = _date_where(from_date, to_date)
    event_clauses, event_params = _event_where(event_id, exclude_events)
    where = " AND ".join(["user_id = ?"] + date_clauses + event_clauses)
    params = [user_id] + date_params + event_params

    conn = get_db()
    try:
        rows = conn.execute(
            f"SELECT category, SUM(amount) AS total FROM expenses WHERE {where} GROUP BY category ORDER BY total DESC",
            params,
        ).fetchall()
    finally:
        conn.close()

    return _breakdown_from_rows(rows)


def get_expense_by_id(expense_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, user_id, event_id, amount, category, date, description"
            " FROM expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
    finally:
        conn.close()


def get_filtered_expenses(
    user_id,
    from_date,
    to_date,
    *,
    event_id=None,
    exclude_events=False,
    page=1,
    per_page=50,
):
    event_clauses, event_params = _event_where(event_id, exclude_events, prefix="e.")
    where = " AND ".join(
        ["e.user_id = ?", "e.date >= ?", "e.date <= ?"] + event_clauses
    )
    params = [user_id, from_date, to_date] + event_params

    page = max(1, page)
    per_page = max(1, per_page)

    conn = get_db()
    try:
        # Total and count cover the whole range, not just the page on screen.
        agg = conn.execute(
            "SELECT COALESCE(SUM(e.amount), 0) AS total, COUNT(*) AS cnt"
            f" FROM expenses e WHERE {where}",
            params,
        ).fetchone()

        rows = conn.execute(
            "SELECT e.id, e.date, e.description, e.category, e.amount,"
            " e.event_id, ev.name AS event_name"
            " FROM expenses e LEFT JOIN events ev ON ev.id = e.event_id"
            f" WHERE {where}"
            " ORDER BY e.date DESC, e.id DESC LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page],
        ).fetchall()
    finally:
        conn.close()

    expense_list = [
        {
            "id": r["id"],
            "date": r["date"],
            "description": r["description"],
            "category": r["category"],
            "amount": f"₹{r['amount']:,.2f}",
            "event_id": r["event_id"],
            "event_name": r["event_name"],
        }
        for r in rows
    ]

    count = agg["cnt"]
    pages = max(1, -(-count // per_page))  # ceiling division
    pagination = {
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "count": count,
        "has_prev": page > 1,
        "has_next": page < pages,
        "first_index": 0 if count == 0 else (page - 1) * per_page + 1,
        "last_index": min(page * per_page, count),
    }

    return expense_list, f"₹{agg['total']:,.2f}", pagination


# ------------------------------------------------------------------ #
# Events                                                              #
# ------------------------------------------------------------------ #


def _format_day(value):
    """Format an ISO date as '20 Sep 2026'; pass anything unparseable through."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y")
    except (ValueError, TypeError):
        return value


def _date_range_label(start_date, end_date):
    if start_date and end_date:
        return f"{_format_day(start_date)} – {_format_day(end_date)}"
    if start_date:
        return f"From {_format_day(start_date)}"
    if end_date:
        return f"Until {_format_day(end_date)}"
    return "No dates set"


def _budget_view(spent, budget):
    """Shared budget figures used by both the event list and the event page."""
    if not budget:
        return {
            "budget": None,
            "remaining": None,
            "pct_of_budget": None,
            "over_budget": False,
        }
    remaining = budget - spent
    return {
        "budget": f"₹{budget:,.2f}",
        "remaining": f"₹{abs(remaining):,.2f}",
        "pct_of_budget": min(int(spent / budget * 100), 100),
        "over_budget": remaining < 0,
    }


def get_event_options(user_id, limit=100):
    """Just id and name, for the quick-add picker.

    Kept separate from get_events_for_user, which LEFT JOINs and aggregates the
    whole expenses table — far more work than a <select> needs, and this one
    runs on every signed-in page. Same ordering, so the picker and the events
    list agree on what "most recent" means.

    Capped because these options are inlined into every signed-in page's HTML,
    and a <select> stops being usable long before 100 entries anyway.
    """
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, name FROM events WHERE user_id = ?"
            " ORDER BY COALESCE(start_date, created_at) DESC, id DESC"
            " LIMIT ?",
            (user_id, limit),
        ).fetchall()
    finally:
        conn.close()

    return [{"id": row["id"], "name": row["name"]} for row in rows]


def get_events_for_user(user_id):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT ev.id, ev.name, ev.start_date, ev.end_date, ev.budget,"
            " COALESCE(SUM(e.amount), 0) AS spent, COUNT(e.id) AS cnt"
            " FROM events ev LEFT JOIN expenses e ON e.event_id = ev.id"
            " WHERE ev.user_id = ?"
            " GROUP BY ev.id"
            " ORDER BY COALESCE(ev.start_date, ev.created_at) DESC, ev.id DESC",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()

    events = []
    for row in rows:
        event = {
            "id": row["id"],
            "name": row["name"],
            "date_range": _date_range_label(row["start_date"], row["end_date"]),
            "spent": f"₹{row['spent']:,.2f}",
            "expense_count": row["cnt"],
        }
        event.update(_budget_view(row["spent"], row["budget"]))
        events.append(event)
    return events


def get_event_by_id(event_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT id, user_id, name, start_date, end_date, budget"
            " FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
    finally:
        conn.close()


def get_event_summary(event_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT ev.name, ev.start_date, ev.end_date, ev.budget,"
            " COALESCE(SUM(e.amount), 0) AS spent, COUNT(e.id) AS cnt"
            " FROM events ev LEFT JOIN expenses e ON e.event_id = ev.id"
            " WHERE ev.id = ?"
            " GROUP BY ev.id",
            (event_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    summary = {
        "name": row["name"],
        "date_range": _date_range_label(row["start_date"], row["end_date"]),
        "spent": f"₹{row['spent']:,.2f}",
        "expense_count": row["cnt"],
    }
    summary.update(_budget_view(row["spent"], row["budget"]))
    return summary


# ------------------------------------------------------------------ #
# Monthly budgets                                                     #
# ------------------------------------------------------------------ #


def get_budgets(user_id):
    """Category -> monthly amount, for the budget form."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT category, monthly_amount FROM budgets WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()

    return {row["category"]: row["monthly_amount"] for row in rows}


def get_month_budget_status(user_id, today=None):
    """How this month's spending sits against the user's monthly budgets.

    Returns None when no budgets are set, so the dashboard can leave the
    section out entirely rather than showing an empty card.
    """
    today = today or timeutil.today()
    first_day = today.replace(day=1)
    days_in_month = monthrange(today.year, today.month)[1]
    last_day = today.replace(day=days_in_month)

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT b.category, b.monthly_amount,"
            " COALESCE(SUM(e.amount), 0) AS spent"
            " FROM budgets b"
            " LEFT JOIN expenses e"
            "   ON e.user_id = b.user_id AND e.category = b.category"
            "  AND e.date >= ? AND e.date <= ?"
            " WHERE b.user_id = ?"
            " GROUP BY b.id"
            " ORDER BY b.monthly_amount DESC",
            (first_day.isoformat(), last_day.isoformat(), user_id),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return None

    categories = []
    for row in rows:
        entry = {
            "name": row["category"],
            "spent": f"₹{row['spent']:,.2f}",
            "spent_value": row["spent"],
            "budget_value": row["monthly_amount"],
            # Amber before the limit, red past it — the warning is the point.
            "nearly_spent": 0.8 <= row["spent"] / row["monthly_amount"] < 1,
        }
        entry.update(_budget_view(row["spent"], row["monthly_amount"]))
        categories.append(entry)

    budget_total = sum(c["budget_value"] for c in categories)
    spent_total = sum(c["spent_value"] for c in categories)
    left = budget_total - spent_total
    days_left = days_in_month - today.day + 1

    return {
        "month_label": today.strftime("%B %Y"),
        "categories": categories,
        "budget_total": f"₹{budget_total:,.2f}",
        "spent_total": f"₹{spent_total:,.2f}",
        "left_total": f"₹{abs(left):,.2f}",
        "over_total": left < 0,
        "days_left": days_left,
        "safe_per_day": f"₹{max(left, 0) / days_left:,.0f}",
        "pct_used": (
            min(int(spent_total / budget_total * 100), 100) if budget_total else 0
        ),
    }
