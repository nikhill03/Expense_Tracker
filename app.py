import os
import sqlite3
from datetime import date, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, abort
from werkzeug.security import generate_password_hash, check_password_hash
from database.db import get_db, init_db, seed_db
from database.queries import (
    get_user_by_id,
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
    get_filtered_expenses,
    get_expense_by_id,
    get_events_for_user,
    get_event_by_id,
    get_event_summary,
)

app = Flask(__name__)
app.secret_key = "dev-secret-change-me"

EXPENSE_CATEGORIES = [
    "Food",
    "Transport",
    "Bills",
    "Health",
    "Entertainment",
    "Shopping",
    "Other",
]


def _parse_expense_form(form):
    """Parse and validate expense form fields. Returns (fields, amount, error)."""
    amount_raw = form.get("amount", "").strip()
    category = form.get("category", "").strip()
    expense_date = form.get("date", "").strip()
    description = form.get("description", "").strip() or None

    fields = {
        "amount_raw": amount_raw,
        "category": category,
        "expense_date": expense_date,
        "description": description,
    }

    try:
        amount = float(amount_raw)
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return fields, None, "Amount must be a positive number."

    if category not in EXPENSE_CATEGORIES:
        return fields, None, "Please select a valid category."

    if not expense_date:
        return fields, None, "Date is required."

    try:
        date.fromisoformat(expense_date)
    except ValueError:
        return fields, None, "Date must be a valid date."

    if description and len(description) > 255:
        return fields, None, "Description must be 255 characters or fewer."

    return fields, amount, None


def _parse_event_form(form):
    """Parse and validate event form fields. Returns (fields, values, error)."""
    name = form.get("name", "").strip()
    start_date = form.get("start_date", "").strip() or None
    end_date = form.get("end_date", "").strip() or None
    budget_raw = form.get("budget", "").strip()

    fields = {
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "budget_raw": budget_raw,
    }

    if not name:
        return fields, None, "Event name is required."

    if len(name) > 100:
        return fields, None, "Event name must be 100 characters or fewer."

    for value in (start_date, end_date):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                return fields, None, "Dates must be valid dates."

    if start_date and end_date and end_date < start_date:
        return fields, None, "End date cannot be before the start date."

    budget = None
    if budget_raw:
        try:
            budget = float(budget_raw)
            if budget <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return fields, None, "Budget must be a positive number."

    values = {
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "budget": budget,
    }
    return fields, values, None


def _resolve_event_id(form, user_id):
    """Return the posted event id, but only if that event belongs to this user."""
    raw = form.get("event_id", "").strip()
    if not raw:
        return None
    try:
        event_id = int(raw)
    except ValueError:
        return None

    event = get_event_by_id(event_id)
    if event is None or event["user_id"] != user_id:
        return None
    return event_id


def _owned_event_or_abort(event_id):
    """Fetch an event, 404 if it doesn't exist, 403 if it isn't this user's."""
    event = get_event_by_id(event_id)
    if event is None:
        abort(404)
    if event["user_id"] != session["user_id"]:
        abort(403)
    return event


with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #


@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("landing"))
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not name or not email or not password:
        return render_template(
            "register.html", error="All fields are required", name=name, email=email
        )

    if len(password) < 8:
        return render_template(
            "register.html",
            error="Password must be at least 8 characters",
            name=name,
            email=email,
        )

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(password)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return render_template(
            "register.html",
            error="An account with that email already exists",
            name=name,
            email=email,
        )
    finally:
        conn.close()

    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("landing"))
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not email or not password:
        return render_template(
            "login.html", error="All fields are required", email=email
        )

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if not user or not check_password_hash(user["password_hash"], password):
        return render_template(
            "login.html", error="Invalid email or password", email=email
        )

    session.clear()
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("landing"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    user_id = session["user_id"]
    today = date.today()

    preset = request.args.get("preset", "")
    custom_from = request.args.get("from", "").strip()
    custom_to = request.args.get("to", "").strip()

    if preset == "this_month":
        active_preset = "this_month"
        from_date = today.replace(day=1).isoformat()
        to_date = today.isoformat()
    elif preset == "last_3_months":
        active_preset = "last_3_months"
        from_date = (today - timedelta(days=90)).isoformat()
        to_date = today.isoformat()
    elif preset == "last_6_months":
        active_preset = "last_6_months"
        from_date = (today - timedelta(days=180)).isoformat()
        to_date = today.isoformat()
    elif custom_from and custom_to:
        active_preset = "custom"
        from_date = custom_from
        to_date = custom_to
    else:
        active_preset = "all"
        from_date = None
        to_date = None

    exclude_events = request.args.get("events") == "exclude"

    user = get_user_by_id(user_id)
    stats = get_summary_stats(
        user_id, from_date, to_date, exclude_events=exclude_events
    )
    transactions = get_recent_transactions(
        user_id,
        limit=None,
        from_date=from_date,
        to_date=to_date,
        exclude_events=exclude_events,
    )
    categories = get_category_breakdown(
        user_id, from_date, to_date, exclude_events=exclude_events
    )

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
        active_preset=active_preset,
        exclude_events=exclude_events,
        form_from=from_date if active_preset == "custom" else "",
        form_to=to_date if active_preset == "custom" else "",
    )


@app.route("/expenses")
def expenses():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    today = date.today()
    default_from = today.replace(day=1).isoformat()
    default_to = today.isoformat()

    from_date = request.args.get("from", "").strip() or default_from
    to_date = request.args.get("to", "").strip() or default_to

    expense_list, total = get_filtered_expenses(session["user_id"], from_date, to_date)

    return render_template(
        "expenses.html",
        expenses=expense_list,
        total=total,
        from_date=from_date,
        to_date=to_date,
    )


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    today = date.today().isoformat()
    events = get_events_for_user(session["user_id"])

    if request.method == "GET":
        return render_template(
            "add_expense.html",
            categories=EXPENSE_CATEGORIES,
            today=today,
            events=events,
            event_id=request.args.get("event", type=int),
        )

    fields, amount, error = _parse_expense_form(request.form)
    event_id = _resolve_event_id(request.form, session["user_id"])

    def redisplay(msg):
        return render_template(
            "add_expense.html",
            categories=EXPENSE_CATEGORIES,
            today=today,
            events=events,
            event_id=event_id,
            error=msg,
            amount=fields["amount_raw"],
            category=fields["category"],
            date=fields["expense_date"],
            description=fields["description"] or "",
        )

    if error:
        return redisplay(error)

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO expenses (user_id, event_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                session["user_id"],
                event_id,
                amount,
                fields["category"],
                fields["expense_date"],
                fields["description"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    if event_id:
        return redirect(url_for("event_detail", event_id=event_id))
    return redirect(url_for("profile"))


@app.route("/expenses/<int:expense_id>/edit", methods=["GET", "POST"])
def edit_expense(expense_id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    expense = get_expense_by_id(expense_id)

    if expense is None:
        abort(404)
    if expense["user_id"] != session["user_id"]:
        abort(403)

    events = get_events_for_user(session["user_id"])

    if request.method == "GET":
        return render_template(
            "edit_expense.html",
            expense=expense,
            categories=EXPENSE_CATEGORIES,
            events=events,
            event_id=expense["event_id"],
        )

    fields, amount, error = _parse_expense_form(request.form)
    event_id = _resolve_event_id(request.form, session["user_id"])

    def redisplay(msg):
        return render_template(
            "edit_expense.html",
            expense=expense,
            categories=EXPENSE_CATEGORIES,
            events=events,
            event_id=event_id,
            error=msg,
            amount=fields["amount_raw"],
            category=fields["category"],
            date=fields["expense_date"],
            description=fields["description"] or "",
        )

    if error:
        return redisplay(error)

    conn = get_db()
    try:
        conn.execute(
            "UPDATE expenses SET amount=?, category=?, date=?, description=?, event_id=?"
            " WHERE id=? AND user_id=?",
            (
                amount,
                fields["category"],
                fields["expense_date"],
                fields["description"],
                event_id,
                expense_id,
                session["user_id"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for("profile"))


@app.route("/expenses/<int:expense_id>/delete", methods=["POST"])
def delete_expense(expense_id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    expense = get_expense_by_id(expense_id)

    if expense is None:
        abort(404)
    if expense["user_id"] != session["user_id"]:
        abort(403)

    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, session["user_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for("profile"))


# ------------------------------------------------------------------ #
# Events                                                              #
# ------------------------------------------------------------------ #


@app.route("/events")
def events():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    return render_template(
        "events.html", events=get_events_for_user(session["user_id"])
    )


@app.route("/events/new", methods=["GET", "POST"])
def new_event():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    if request.method == "GET":
        return render_template("event_form.html", mode="new")

    fields, values, error = _parse_event_form(request.form)

    if error:
        return render_template("event_form.html", mode="new", error=error, **fields)

    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO events (user_id, name, start_date, end_date, budget)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                session["user_id"],
                values["name"],
                values["start_date"],
                values["end_date"],
                values["budget"],
            ),
        )
        conn.commit()
        event_id = cursor.lastrowid
    finally:
        conn.close()

    return redirect(url_for("event_detail", event_id=event_id))


@app.route("/events/<int:event_id>")
def event_detail(event_id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    _owned_event_or_abort(event_id)
    user_id = session["user_id"]

    return render_template(
        "event_detail.html",
        event_id=event_id,
        summary=get_event_summary(event_id),
        transactions=get_recent_transactions(user_id, limit=None, event_id=event_id),
        categories=get_category_breakdown(user_id, event_id=event_id),
    )


@app.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
def edit_event(event_id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    event = _owned_event_or_abort(event_id)

    if request.method == "GET":
        return render_template(
            "event_form.html",
            mode="edit",
            event_id=event_id,
            name=event["name"],
            start_date=event["start_date"],
            end_date=event["end_date"],
            budget_raw="" if event["budget"] is None else event["budget"],
        )

    fields, values, error = _parse_event_form(request.form)

    if error:
        return render_template(
            "event_form.html", mode="edit", event_id=event_id, error=error, **fields
        )

    conn = get_db()
    try:
        conn.execute(
            "UPDATE events SET name=?, start_date=?, end_date=?, budget=?"
            " WHERE id=? AND user_id=?",
            (
                values["name"],
                values["start_date"],
                values["end_date"],
                values["budget"],
                event_id,
                session["user_id"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for("event_detail", event_id=event_id))


@app.route("/events/<int:event_id>/delete", methods=["POST"])
def delete_event(event_id):
    if not session.get("user_id"):
        return redirect(url_for("login"))

    _owned_event_or_abort(event_id)

    conn = get_db()
    try:
        # Expenses outlive their event — they are only unlinked from it.
        conn.execute(
            "UPDATE expenses SET event_id = NULL WHERE event_id = ? AND user_id = ?",
            (event_id, session["user_id"]),
        )
        conn.execute(
            "DELETE FROM events WHERE id = ? AND user_id = ?",
            (event_id, session["user_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for("events"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=False, host="0.0.0.0", port=port)
