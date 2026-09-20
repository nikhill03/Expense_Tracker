from datetime import datetime
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
        try:
            fmt_date = datetime.strptime(row["date"], "%Y-%m-%d").strftime("%d %b %Y")
        except (ValueError, TypeError):
            fmt_date = row["date"]
        result.append(
            {
                "id": row["id"],
                "date": fmt_date,
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

    diff = 100 - sum(item["pct"] for item in items)
    items[0]["pct"] += diff

    return items


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
    user_id, from_date, to_date, *, event_id=None, exclude_events=False
):
    event_clauses, event_params = _event_where(event_id, exclude_events, prefix="e.")
    where = " AND ".join(
        ["e.user_id = ?", "e.date >= ?", "e.date <= ?"] + event_clauses
    )

    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT e.id, e.date, e.description, e.category, e.amount,"
            " e.event_id, ev.name AS event_name"
            " FROM expenses e LEFT JOIN events ev ON ev.id = e.event_id"
            f" WHERE {where}"
            " ORDER BY e.date DESC, e.id DESC",
            [user_id, from_date, to_date] + event_params,
        ).fetchall()
    finally:
        conn.close()

    total = sum(r["amount"] for r in rows)
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
    return expense_list, f"₹{total:,.2f}"


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
