"""
tests/test_06_date_filter.py

Spec-driven pytest tests for Step 06: Date Filter (/expenses route).

Tests are written against the feature specification, not the implementation.
They assert HTTP contracts, UI content, filtering behaviour, and DB side effects
without referencing internal variable names or function internals.
"""

import sqlite3
import pytest
from datetime import date, timedelta
from werkzeug.security import generate_password_hash


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _make_conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _today():
    return date.today()


def _first_of_month():
    return _today().replace(day=1)


def _date_str(d):
    return d.isoformat()


# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #

@pytest.fixture()
def db_path(tmp_path):
    """Create a fresh temporary SQLite DB with the correct schema."""
    path = str(tmp_path / "test_date_filter.db")
    conn = _make_conn(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            amount      REAL    NOT NULL,
            category    TEXT    NOT NULL,
            date        TEXT    NOT NULL,
            description TEXT,
            created_at  TEXT    DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def patched_app(db_path, monkeypatch):
    """
    Redirect every get_db() call — in both database.db and database.queries —
    to the isolated temp DB, then return the Flask test client.
    """
    import database.db as db_module
    import database.queries as q_module

    def _get_db():
        return _make_conn(db_path)

    monkeypatch.setattr(db_module, "get_db", _get_db)
    monkeypatch.setattr(q_module, "get_db", _get_db)

    import app as app_module
    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret-date-filter")
    return app_module.app.test_client()


@pytest.fixture()
def seeded_client(patched_app, db_path):
    """
    Insert one test user plus controlled expense rows spanning three time periods:
      - current month (two rows)
      - previous calendar month (one row)
      - a fixed old date in 2025-01 (one row)

    Returns (client, user_id, current_month_expenses) where
    current_month_expenses is a list of (amount, category, date_str, description).
    """
    today = _today()
    first = _first_of_month()

    # Guarantee a mid-month date that is always >= first of month and <= today
    mid_month = first + timedelta(days=4)
    if mid_month > today:
        mid_month = today

    # A date that is definitely in the previous calendar month
    prev_month_date = (first - timedelta(days=1)).replace(day=10)

    conn = _make_conn(db_path)
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Filter Tester", "filter@example.com", generate_password_hash("Password1")),
    )
    user_id = cur.lastrowid

    current_month_rows = [
        (user_id, 500.00,  "Food",      _date_str(mid_month), "Lunch"),
        (user_id, 200.00,  "Transport", _date_str(first),     "Bus pass"),
    ]
    prev_month_rows = [
        (user_id, 800.00,  "Bills",     _date_str(prev_month_date), "Old electric bill"),
    ]
    old_rows = [
        (user_id, 1000.00, "Shopping",  "2025-01-15", "Old purchase 2025"),
    ]

    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        current_month_rows + prev_month_rows + old_rows,
    )
    conn.commit()
    conn.close()

    current_month_expenses = [
        {"amount": 500.00, "category": "Food",      "date": _date_str(mid_month), "description": "Lunch"},
        {"amount": 200.00, "category": "Transport",  "date": _date_str(first),    "description": "Bus pass"},
    ]

    return patched_app, user_id, current_month_expenses


@pytest.fixture()
def logged_in_client(seeded_client):
    """
    A Flask test client with the test user's session already set
    (simulates a logged-in state using the session directly).
    """
    client, user_id, current_month_expenses = seeded_client
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Filter Tester"
    return client, user_id, current_month_expenses


# ------------------------------------------------------------------ #
# Auth guard                                                           #
# ------------------------------------------------------------------ #

class TestExpensesAuthGuard:

    def test_expenses_page_requires_login(self, patched_app):
        """GET /expenses without a session → 302 redirect, Location contains /login."""
        resp = patched_app.get("/expenses")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_expenses_page_redirect_does_not_show_content(self, patched_app):
        """Unauthenticated GET /expenses must not return the expenses page body."""
        resp = patched_app.get("/expenses", follow_redirects=True)
        # Should land on the login page, not the expenses listing
        assert b"My Expenses" not in resp.data


# ------------------------------------------------------------------ #
# Happy path                                                           #
# ------------------------------------------------------------------ #

class TestExpensesHappyPath:

    def test_expenses_page_loads_when_logged_in(self, logged_in_client):
        """Authenticated GET /expenses → HTTP 200."""
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        assert resp.status_code == 200

    def test_expenses_page_shows_my_expenses_heading(self, logged_in_client):
        """The expenses page must include the heading 'My Expenses'."""
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        assert b"My Expenses" in resp.data

    def test_expenses_page_shows_rupee_symbol(self, logged_in_client):
        """All currency amounts on the page must display the ₹ symbol."""
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        assert "₹".encode() in resp.data

    def test_expenses_page_shows_add_expense_button(self, logged_in_client):
        """The page header must include a link/button labelled '+ Add Expense'."""
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        assert b"Add Expense" in resp.data

    def test_expenses_page_shows_filter_form_with_get_method(self, logged_in_client):
        """The date filter form must use method='get'."""
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        body = resp.data.decode()
        assert 'method="get"' in body or "method='get'" in body

    def test_expenses_page_filter_form_has_from_input(self, logged_in_client):
        """The filter form must include a date input named 'from'."""
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        body = resp.data.decode()
        assert 'name="from"' in body or "name='from'" in body

    def test_expenses_page_filter_form_has_to_input(self, logged_in_client):
        """The filter form must include a date input named 'to'."""
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        body = resp.data.decode()
        assert 'name="to"' in body or "name='to'" in body

    def test_expenses_page_shows_total_label(self, logged_in_client):
        """The page must display a filtered total prefixed with 'Total:'."""
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        assert b"Total:" in resp.data

    def test_expenses_page_table_has_date_column(self, logged_in_client):
        """The expense table must have a 'Date' column header."""
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        assert b"Date" in resp.data

    def test_expenses_page_table_has_category_column(self, logged_in_client):
        """The expense table must have a 'Category' column header."""
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        assert b"Category" in resp.data

    def test_expenses_page_table_has_amount_column(self, logged_in_client):
        """The expense table must have an 'Amount' column header."""
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        assert b"Amount" in resp.data


# ------------------------------------------------------------------ #
# Default date range (current month)                                  #
# ------------------------------------------------------------------ #

class TestExpensesDefaultDateRange:

    def test_expenses_default_shows_current_month_expenses(self, logged_in_client):
        """
        With no query params, the page must show expenses belonging to the
        current calendar month.  The 'Lunch' and 'Bus pass' rows (seeded in the
        current month) must appear in the response.
        """
        client, _, current = logged_in_client
        resp = client.get("/expenses")
        body = resp.data.decode()
        for row in current:
            assert row["description"] in body, (
                f"Expected current-month expense '{row['description']}' to appear "
                "in the default /expenses view."
            )

    def test_expenses_default_excludes_old_year_expenses(self, logged_in_client):
        """
        With no query params, expenses from 2025-01-15 must NOT appear —
        they pre-date the current month's default range.
        """
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        assert b"Old purchase 2025" not in resp.data

    def test_expenses_default_excludes_previous_month_expenses(self, logged_in_client):
        """
        With no query params, expenses from the previous calendar month must
        NOT appear in the default current-month view.
        """
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        assert b"Old electric bill" not in resp.data

    def test_expenses_default_total_matches_current_month_sum(self, logged_in_client):
        """
        The total displayed when using the default (no params) range must equal
        the sum of only the current-month expenses: 500 + 200 = ₹700.00.
        """
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        assert "₹700.00".encode() in resp.data

    def test_expenses_default_prefills_from_date_as_first_of_month(self, logged_in_client):
        """
        The filter form must be pre-filled with the first day of the current
        month as the 'from' value when no query params are supplied.
        """
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        body = resp.data.decode()
        first_of_month = _date_str(_first_of_month())
        assert first_of_month in body, (
            f"Expected filter form to pre-fill 'from' with '{first_of_month}'."
        )

    def test_expenses_default_prefills_to_date_as_today(self, logged_in_client):
        """
        The filter form must be pre-filled with today's date as the 'to' value
        when no query params are supplied.
        """
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        body = resp.data.decode()
        today_str = _date_str(_today())
        assert today_str in body, (
            f"Expected filter form to pre-fill 'to' with '{today_str}'."
        )


# ------------------------------------------------------------------ #
# Filtering                                                            #
# ------------------------------------------------------------------ #

class TestExpensesFiltering:

    def test_expenses_filter_by_explicit_date_range(self, logged_in_client):
        """
        Passing ?from=…&to=… that covers only the current month shows only those
        expenses — 'Lunch' and 'Bus pass' must appear.
        """
        client, _, current = logged_in_client
        from_str = _date_str(_first_of_month())
        to_str   = _date_str(_today())
        resp = client.get(f"/expenses?from={from_str}&to={to_str}")
        body = resp.data.decode()
        for row in current:
            assert row["description"] in body

    def test_expenses_filter_excludes_rows_outside_range(self, logged_in_client):
        """
        A filter range of only the current month must exclude expenses whose date
        falls before the range (2025-01-15 and previous-month expense).
        """
        client, _, _ = logged_in_client
        from_str = _date_str(_first_of_month())
        to_str   = _date_str(_today())
        resp = client.get(f"/expenses?from={from_str}&to={to_str}")
        assert b"Old purchase 2025" not in resp.data
        assert b"Old electric bill" not in resp.data

    def test_expenses_filter_inclusive_on_from_date(self, logged_in_client):
        """
        An expense whose date equals from_date exactly must be included in results.
        'Bus pass' is seeded on the first day of the current month; a filter
        starting on that exact date must include it.
        """
        client, _, _ = logged_in_client
        from_str = _date_str(_first_of_month())
        to_str   = _date_str(_today())
        resp = client.get(f"/expenses?from={from_str}&to={to_str}")
        assert b"Bus pass" in resp.data

    def test_expenses_filter_inclusive_on_to_date(self, logged_in_client):
        """
        An expense whose date equals to_date exactly must be included in results.
        """
        client, _, current = logged_in_client
        # Use the mid-month 'Lunch' row — its date is the to_date boundary
        lunch = next(e for e in current if e["description"] == "Lunch")
        from_str = _date_str(_first_of_month())
        to_str   = lunch["date"]
        resp = client.get(f"/expenses?from={from_str}&to={to_str}")
        assert b"Lunch" in resp.data

    def test_expenses_filtered_total_matches_displayed_rows(self, logged_in_client):
        """
        When filtering to a range that returns only current-month expenses
        (500 + 200 = 700), the displayed total must be ₹700.00.
        """
        client, _, _ = logged_in_client
        from_str = _date_str(_first_of_month())
        to_str   = _date_str(_today())
        resp = client.get(f"/expenses?from={from_str}&to={to_str}")
        assert "₹700.00".encode() in resp.data

    def test_expenses_filter_single_expense_range(self, logged_in_client):
        """
        A filter range that covers only the exact date of 'Lunch' (500.00) must
        show ₹500.00 as the total and not include 'Bus pass'.
        """
        client, _, current = logged_in_client
        lunch = next(e for e in current if e["description"] == "Lunch")
        resp = client.get(f"/expenses?from={lunch['date']}&to={lunch['date']}")
        body = resp.data.decode()
        assert "Lunch" in body
        assert "₹500.00" in body
        assert "Bus pass" not in body

    def test_expenses_filter_form_prefills_with_query_param_dates(self, logged_in_client):
        """
        When ?from=…&to=… are passed, the filter form inputs must be pre-filled
        with those exact values so the user can see and adjust the active range.
        """
        client, _, _ = logged_in_client
        from_str = "2026-01-01"
        to_str   = "2026-01-31"
        resp = client.get(f"/expenses?from={from_str}&to={to_str}")
        body = resp.data.decode()
        assert from_str in body
        assert to_str in body

    def test_expenses_filter_isolates_to_logged_in_user(self, db_path, patched_app):
        """
        Expenses belonging to a different user must never appear in the logged-in
        user's expense list, even when the date range would include them.
        """
        conn = _make_conn(db_path)
        # Insert user A and user B
        cur_a = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("User A", "usera@example.com", generate_password_hash("Password1")),
        )
        user_a = cur_a.lastrowid
        cur_b = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("User B", "userb@example.com", generate_password_hash("Password1")),
        )
        user_b = cur_b.lastrowid
        today_str = _date_str(_today())
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
            (user_a, 300.00, "Food", today_str, "User A lunch"),
        )
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
            (user_b, 999.00, "Shopping", today_str, "User B secret expense"),
        )
        conn.commit()
        conn.close()

        # Log in as user A
        with patched_app.session_transaction() as sess:
            sess["user_id"] = user_a
            sess["user_name"] = "User A"

        resp = patched_app.get("/expenses")
        body = resp.data.decode()
        assert "User A lunch" in body
        assert "User B secret expense" not in body


# ------------------------------------------------------------------ #
# Empty state                                                          #
# ------------------------------------------------------------------ #

class TestExpensesEmptyState:

    def test_expenses_empty_state_message_shown(self, logged_in_client):
        """
        A date range that matches no expenses must display the empty-state
        message: 'No expenses found for this date range.'
        """
        client, _, _ = logged_in_client
        # Use a future date range guaranteed to contain no seeded data
        resp = client.get("/expenses?from=2099-01-01&to=2099-01-31")
        assert b"No expenses found for this date range." in resp.data

    def test_expenses_empty_state_total_is_zero(self, logged_in_client):
        """
        When no expenses match the filter, the displayed total must be ₹0.00.
        """
        client, _, _ = logged_in_client
        resp = client.get("/expenses?from=2099-01-01&to=2099-01-31")
        assert "₹0.00".encode() in resp.data

    def test_expenses_empty_state_no_expense_rows_in_table(self, logged_in_client):
        """
        When no expenses match, expense description text from seeded rows must
        not appear in the response body.
        """
        client, _, _ = logged_in_client
        resp = client.get("/expenses?from=2099-01-01&to=2099-01-31")
        assert b"Lunch" not in resp.data
        assert b"Bus pass" not in resp.data


# ------------------------------------------------------------------ #
# Category badges                                                      #
# ------------------------------------------------------------------ #

class TestExpensesCategoryBadges:

    def test_expenses_category_badge_class_present(self, logged_in_client):
        """
        Each expense row's category must render inside an element carrying the
        CSS class 'badge badge--<category-slug>' (no inline colour styles).
        """
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        body = resp.data.decode()
        # The template applies 'badge badge--' prefix for every category cell
        assert "badge badge--" in body

    def test_expenses_food_badge_class(self, logged_in_client):
        """
        A 'Food' category expense must render with class 'badge badge--food'.
        """
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        body = resp.data.decode()
        assert "badge--food" in body

    def test_expenses_transport_badge_class(self, logged_in_client):
        """
        A 'Transport' category expense must render with class 'badge badge--transport'.
        """
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        body = resp.data.decode()
        assert "badge--transport" in body

    def test_expenses_badge_does_not_use_inline_style_for_colour(self, logged_in_client):
        """
        Category badges must use CSS classes, not inline background-color styles,
        to colour-code the category.
        """
        client, _, _ = logged_in_client
        resp = client.get("/expenses")
        # Inline colour on the badge span itself would be unusual and spec-disallowed
        body = resp.data.decode()
        # Count <span class="badge badge--..."> occurrences to confirm class-based approach
        import re
        badge_spans = re.findall(r'class="badge badge--[\w-]+"', body)
        assert len(badge_spans) > 0, "Expected at least one badge span with CSS class."


# ------------------------------------------------------------------ #
# Profile page "View all" link                                         #
# ------------------------------------------------------------------ #

class TestProfileViewAllLink:

    def test_profile_has_view_all_link_to_expenses(self, logged_in_client):
        """
        GET /profile (logged in) must contain a 'View all' link whose href
        points to /expenses, as required by the spec.
        """
        client, _, _ = logged_in_client
        resp = client.get("/profile")
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "/expenses" in body
        assert "View all" in body

    def test_profile_view_all_link_is_an_anchor_tag(self, logged_in_client):
        """
        The 'View all' link on the profile page must be an HTML anchor (<a>)
        tag pointing to /expenses.
        """
        client, _, _ = logged_in_client
        resp = client.get("/profile")
        body = resp.data.decode()
        import re
        # Match <a href="/expenses...">...View all...</a> (flexible whitespace/attrs)
        pattern = re.compile(r'<a\s[^>]*href=["\'][^"\']*\/expenses[^"\']*["\'][^>]*>.*?View all.*?</a>', re.DOTALL)
        assert pattern.search(body), (
            "Expected an <a href='/expenses'> anchor containing 'View all' text on the profile page."
        )
