import logging
import os
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, abort, g
from werkzeug.security import generate_password_hash, check_password_hash
from database.db import get_db, init_db, seed_db, backup_db
from database.queries import (
    get_user_by_id,
    get_dashboard,
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

PROFILE_TRANSACTION_LIMIT = 10
EXPENSES_PER_PAGE = 50
SLOW_REQUEST_MS = 200
MAX_LOGIN_FAILURES = 5
LOGIN_LOCKOUT_MINUTES = 15

logging.basicConfig(level=logging.INFO)

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


# ------------------------------------------------------------------ #
# Cross-cutting: CSRF, timing, errors, health                         #
# ------------------------------------------------------------------ #

CSRF_EXEMPT_ENDPOINTS = set()


def _csrf_enabled():
    """On by default; off under TESTING unless a test turns it back on.

    Existing route tests post forms directly, so blanket-enforcing the token
    would fail them for the wrong reason. tests/test_11_hardening.py sets
    CSRF_ENABLED = True to cover the real behaviour.
    """
    configured = app.config.get("CSRF_ENABLED")
    if configured is None:
        return not app.config.get("TESTING", False)
    return configured


def csrf_token():
    """Per-session token, created on first use."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token


_last_backup_day = None


def _daily_backup():
    """Take one snapshot per day, on the first request that notices the date."""
    global _last_backup_day
    today = date.today().isoformat()
    if _last_backup_day == today:
        return
    _last_backup_day = today
    try:
        backup_db()
    except (OSError, sqlite3.Error):
        app.logger.exception("database backup failed")


@app.before_request
def _guard_and_time_request():
    g.started_at = time.perf_counter()
    _daily_backup()

    if (
        _csrf_enabled()
        and request.method == "POST"
        and request.endpoint not in CSRF_EXEMPT_ENDPOINTS
    ):
        sent = request.form.get("csrf_token", "")
        expected = session.get("csrf_token")
        if not expected or not secrets.compare_digest(sent, expected):
            abort(
                400,
                "Your session expired or the form was tampered with. Please try again.",
            )


@app.after_request
def _log_slow_request(response):
    started = getattr(g, "started_at", None)
    if started is not None:
        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms > SLOW_REQUEST_MS:
            app.logger.warning(
                "slow request %s %s %.0fms", request.method, request.path, elapsed_ms
            )
    return response


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
def _handle_client_error(error):
    return (
        render_template(
            "error.html",
            code=error.code,
            title={
                400: "That didn't go through",
                403: "Not your expense",
                404: "Page not found",
            }.get(error.code, "Something went wrong"),
            message=getattr(error, "description", ""),
        ),
        error.code,
    )


@app.errorhandler(500)
def _handle_server_error(error):
    app.logger.exception("unhandled error: %s", error)
    return (
        render_template(
            "error.html",
            code=500,
            title="Something broke on our side",
            message="The problem has been logged. Try again in a moment.",
        ),
        500,
    )


@app.route("/healthz")
def healthz():
    """Liveness probe: the app is up and the database answers."""
    try:
        conn = get_db()
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        app.logger.error("health check failed: %s", exc)
        return {"status": "error"}, 503
    return {"status": "ok"}, 200


# ------------------------------------------------------------------ #
# Login throttling                                                    #
# ------------------------------------------------------------------ #


def _login_lock_remaining(email):
    """Minutes left on a lockout for this email, or 0 if it can try again."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT locked_until FROM login_attempts WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()

    if row is None or not row["locked_until"]:
        return 0

    try:
        locked_until = datetime.fromisoformat(row["locked_until"])
    except (ValueError, TypeError):
        return 0

    remaining = (locked_until - datetime.now()).total_seconds()
    return max(0, int(remaining // 60) + 1) if remaining > 0 else 0


def _record_login_failure(email):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT failures FROM login_attempts WHERE email = ?", (email,)
        ).fetchone()
        failures = (row["failures"] if row else 0) + 1
        locked_until = None
        if failures >= MAX_LOGIN_FAILURES:
            locked_until = (
                datetime.now() + timedelta(minutes=LOGIN_LOCKOUT_MINUTES)
            ).isoformat(timespec="seconds")
            failures = 0  # start a fresh count after the lockout
        conn.execute(
            "INSERT INTO login_attempts (email, failures, locked_until) VALUES (?, ?, ?)"
            " ON CONFLICT(email) DO UPDATE SET failures = ?, locked_until = ?",
            (email, failures, locked_until, failures, locked_until),
        )
        conn.commit()
    finally:
        conn.close()


def _clear_login_failures(email):
    conn = get_db()
    try:
        conn.execute("DELETE FROM login_attempts WHERE email = ?", (email,))
        conn.commit()
    finally:
        conn.close()


with app.app_context():
    try:
        init_db()
        seed_db()
    except sqlite3.Error:
        # A failed migration should be loud in the logs, not a dead app.
        app.logger.exception("database initialisation failed")


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

    locked_minutes = _login_lock_remaining(email)
    if locked_minutes:
        return render_template(
            "login.html",
            error=f"Too many failed attempts. Try again in {locked_minutes} minute"
            f"{'' if locked_minutes == 1 else 's'}.",
            email=email,
        )

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if not user or not check_password_hash(user["password_hash"], password):
        _record_login_failure(email)
        return render_template(
            "login.html", error="Invalid email or password", email=email
        )

    _clear_login_failures(email)
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
    # One aggregate query covers the stat cards and the category bars.
    stats, categories = get_dashboard(
        user_id, from_date, to_date, exclude_events=exclude_events
    )
    transactions = get_recent_transactions(
        user_id,
        limit=PROFILE_TRANSACTION_LIMIT,
        from_date=from_date,
        to_date=to_date,
        exclude_events=exclude_events,
    )

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
        active_preset=active_preset,
        exclude_events=exclude_events,
        transaction_limit=PROFILE_TRANSACTION_LIMIT,
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

    page = request.args.get("page", default=1, type=int) or 1
    expense_list, total, pagination = get_filtered_expenses(
        session["user_id"],
        from_date,
        to_date,
        page=page,
        per_page=EXPENSES_PER_PAGE,
    )

    return render_template(
        "expenses.html",
        expenses=expense_list,
        total=total,
        pagination=pagination,
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
        transactions=get_recent_transactions(
            user_id, limit=EXPENSES_PER_PAGE, event_id=event_id
        ),
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
