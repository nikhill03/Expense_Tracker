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


def get_summary_stats(user_id, from_date=None, to_date=None):
    date_clauses, date_params = _date_where(from_date, to_date)
    where = " AND ".join(["user_id = ?"] + date_clauses)
    params = [user_id] + date_params

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


def get_recent_transactions(user_id, limit=10, from_date=None, to_date=None):
    date_clauses, date_params = _date_where(from_date, to_date)
    where = " AND ".join(["user_id = ?"] + date_clauses)
    params = [user_id] + date_params

    sql = f"SELECT id, date, description, category, amount FROM expenses WHERE {where} ORDER BY date DESC, id DESC"
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
            }
        )
    return result


def get_category_breakdown(user_id, from_date=None, to_date=None):
    date_clauses, date_params = _date_where(from_date, to_date)
    where = " AND ".join(["user_id = ?"] + date_clauses)
    params = [user_id] + date_params

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
            "SELECT id, user_id, amount, category, date, description"
            " FROM expenses WHERE id = ?",
            (expense_id,),
        ).fetchone()
    finally:
        conn.close()


def get_filtered_expenses(user_id, from_date, to_date):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, date, description, category, amount FROM expenses"
            " WHERE user_id = ? AND date >= ? AND date <= ?"
            " ORDER BY date DESC, id DESC",
            (user_id, from_date, to_date),
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
        }
        for r in rows
    ]
    return expense_list, f"₹{total:,.2f}"
