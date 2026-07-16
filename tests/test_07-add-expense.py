"""
tests/test_07-add-expense.py

Spec-driven pytest tests for Step 07: Add Expense (/expenses/add route).

All test logic is derived from the feature specification (07-add-expense.md).
No implementation details are read or referenced — tests must remain valid if
the implementation is completely rewritten.

Routes under test:
    GET  /expenses/add — render the add-expense form (authenticated only)
    POST /expenses/add — validate, insert expense, redirect to /expenses (authenticated only)
"""

import re
import sqlite3
from datetime import date

import pytest
from werkzeug.security import generate_password_hash


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _make_conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _today_str():
    return date.today().isoformat()


# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #

@pytest.fixture()
def db_path(tmp_path):
    """Create a fresh temporary SQLite DB with the Spendly schema."""
    path = str(tmp_path / "test_add_expense.db")
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
    Redirect every get_db() call to the isolated temp DB.

    app.py uses `from database.db import get_db`, which binds a direct reference
    in app's own namespace. We must import app BEFORE defining _get_db so the
    module-level seed_db() runs against the real DB (where its guard fires), and
    then explicitly patch app_module.get_db so the route's local name is redirected.
    """
    import database.db as db_module
    import database.queries as q_module
    import app as app_module  # import first — module-level init_db/seed_db uses real DB

    def _get_db():
        return _make_conn(db_path)

    monkeypatch.setattr(db_module, "get_db", _get_db)
    monkeypatch.setattr(q_module, "get_db", _get_db)
    monkeypatch.setattr(app_module, "get_db", _get_db)  # patch app's local reference

    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret-add-expense")
    return app_module.app.test_client()


@pytest.fixture()
def seeded_client(patched_app, db_path):
    """
    Insert one test user into the temp DB.
    Returns (flask_test_client, user_id).
    """
    conn = _make_conn(db_path)
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Test User", "test@example.com", generate_password_hash("Password1")),
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()
    return patched_app, user_id


@pytest.fixture()
def logged_in_client(seeded_client):
    """
    Flask test client with the test user's session already set (simulates a
    logged-in state without going through the real /login route).
    Returns (client, user_id).
    """
    client, user_id = seeded_client
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Test User"
    return client, user_id


# ------------------------------------------------------------------ #
# Auth guard                                                           #
# ------------------------------------------------------------------ #

class TestAddExpenseAuthGuard:

    def test_get_without_login_returns_redirect(self, patched_app):
        """GET /expenses/add without a session → 302 redirect (not 200)."""
        resp = patched_app.get("/expenses/add")
        assert resp.status_code == 302

    def test_get_without_login_redirects_to_login(self, patched_app):
        """GET /expenses/add without a session → Location header contains /login."""
        resp = patched_app.get("/expenses/add")
        assert "/login" in resp.headers["Location"]

    def test_get_without_login_does_not_show_add_form(self, patched_app):
        """Following the unauthenticated GET redirect must not display the add-expense form."""
        resp = patched_app.get("/expenses/add", follow_redirects=True)
        # Should land on the login page — the form submit button label should not appear
        # alongside a logged-in context
        body = resp.data.decode()
        assert "<form" not in body or "login" in body.lower() or "password" in body.lower()

    def test_post_without_login_returns_redirect(self, patched_app):
        """POST /expenses/add without a session → 302 redirect (not 200)."""
        resp = patched_app.post("/expenses/add", data={
            "amount": "100",
            "category": "Food",
            "date": _today_str(),
        })
        assert resp.status_code == 302

    def test_post_without_login_redirects_to_login(self, patched_app):
        """POST /expenses/add without a session → Location header contains /login."""
        resp = patched_app.post("/expenses/add", data={
            "amount": "100",
            "category": "Food",
            "date": _today_str(),
        })
        assert "/login" in resp.headers["Location"]

    def test_post_without_login_does_not_insert_expense(self, patched_app, db_path):
        """An unauthenticated POST must never write a row into the expenses table."""
        patched_app.post("/expenses/add", data={
            "amount": "100",
            "category": "Food",
            "date": _today_str(),
        })
        conn = _make_conn(db_path)
        count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        conn.close()
        assert count == 0


# ------------------------------------------------------------------ #
# GET — Form rendering                                                 #
# ------------------------------------------------------------------ #

class TestAddExpenseGetForm:

    def test_get_returns_200_when_logged_in(self, logged_in_client):
        """Authenticated GET /expenses/add → HTTP 200."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        assert resp.status_code == 200

    def test_get_shows_add_expense_heading(self, logged_in_client):
        """The page must contain an 'Add Expense' heading or title."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        assert b"Add Expense" in resp.data

    def test_get_shows_back_to_expenses_link_text(self, logged_in_client):
        """The page must include a 'Back to Expenses' link."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        assert b"Back to Expenses" in resp.data

    def test_get_back_to_expenses_link_points_to_expenses_route(self, logged_in_client):
        """The 'Back to Expenses' link href must point to /expenses."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        # The anchor containing "Back to Expenses" must href to /expenses
        pattern = re.compile(
            r'<a\s[^>]*href=["\'][^"\']*\/expenses[^"\']*["\'][^>]*>.*?Back to Expenses.*?</a>',
            re.DOTALL | re.IGNORECASE,
        )
        assert pattern.search(body), (
            "Expected a <a href='/expenses'> anchor containing 'Back to Expenses'."
        )

    def test_get_form_uses_post_method(self, logged_in_client):
        """The form element must use method='post'."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        body = resp.data.decode().lower()
        assert 'method="post"' in body or "method='post'" in body

    def test_get_form_action_targets_add_expense_url(self, logged_in_client):
        """The form action must target the /expenses/add URL."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        assert "/expenses/add" in body

    def test_get_form_has_amount_input(self, logged_in_client):
        """The form must contain an input element named 'amount'."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        assert 'name="amount"' in body or "name='amount'" in body

    def test_get_amount_input_is_type_number(self, logged_in_client):
        """The amount input must have type='number' (spec requirement)."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        assert 'type="number"' in body or "type='number'" in body

    def test_get_form_has_category_select(self, logged_in_client):
        """The form must contain a select element named 'category'."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        assert 'name="category"' in body or "name='category'" in body

    @pytest.mark.parametrize("category", [
        "Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other",
    ])
    def test_get_category_select_includes_all_seven_options(self, logged_in_client, category):
        """The category select must render all 7 fixed options defined in the spec."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        assert category.encode() in resp.data, (
            f"Category option '{category}' must appear in the <select> on GET."
        )

    def test_get_form_has_date_input(self, logged_in_client):
        """The form must contain an input element named 'date'."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        assert 'name="date"' in body or "name='date'" in body

    def test_get_date_input_is_type_date(self, logged_in_client):
        """The date input must have type='date'."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        assert 'type="date"' in body or "type='date'" in body

    def test_get_date_field_is_prefilled_with_today_server_side(self, logged_in_client):
        """
        The date field must be pre-filled with today's date in YYYY-MM-DD format.
        This default must come from the server — not rely on JavaScript.
        """
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        assert _today_str() in body, (
            f"Expected today's date '{_today_str()}' to be pre-filled in the date field."
        )

    def test_get_form_has_description_input(self, logged_in_client):
        """The form must contain an input element named 'description' (optional field)."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        assert 'name="description"' in body or "name='description'" in body

    def test_get_form_has_submit_button_labelled_add_expense(self, logged_in_client):
        """The form must have a submit button or input with the label 'Add Expense'."""
        client, _ = logged_in_client
        resp = client.get("/expenses/add")
        body = resp.data.decode()
        # Accept button text OR value="Add Expense" on an input[type=submit]
        assert "Add Expense" in body


# ------------------------------------------------------------------ #
# POST — Happy path                                                     #
# ------------------------------------------------------------------ #

class TestAddExpensePostSuccess:

    def test_valid_post_returns_redirect(self, logged_in_client):
        """A fully valid POST to /expenses/add → 302 redirect."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "250.50",
            "category": "Food",
            "date": _today_str(),
            "description": "Team lunch",
        })
        assert resp.status_code == 302

    def test_valid_post_redirects_to_expenses_page(self, logged_in_client):
        """A valid POST must redirect to the /expenses listing page."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "250.50",
            "category": "Food",
            "date": _today_str(),
            "description": "Team lunch",
        })
        assert "/expenses" in resp.headers["Location"]

    def test_valid_post_does_not_redirect_back_to_add_form(self, logged_in_client):
        """A successful POST must not redirect back to /expenses/add."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "250.50",
            "category": "Food",
            "date": _today_str(),
        })
        # The redirect Location must be /expenses, not /expenses/add
        assert resp.headers["Location"].rstrip("/") != "/expenses/add"

    def test_valid_post_inserts_one_row_into_expenses_table(self, logged_in_client, db_path):
        """A valid POST must insert exactly one row into the expenses table."""
        client, _ = logged_in_client
        client.post("/expenses/add", data={
            "amount": "250.50",
            "category": "Food",
            "date": _today_str(),
            "description": "Team lunch",
        })
        conn = _make_conn(db_path)
        count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        conn.close()
        assert count == 1

    def test_valid_post_stores_correct_amount(self, logged_in_client, db_path):
        """The stored expense amount must match the submitted value."""
        client, _ = logged_in_client
        client.post("/expenses/add", data={
            "amount": "349.99",
            "category": "Transport",
            "date": _today_str(),
        })
        conn = _make_conn(db_path)
        row = conn.execute("SELECT amount FROM expenses LIMIT 1").fetchone()
        conn.close()
        assert abs(row["amount"] - 349.99) < 0.001

    def test_valid_post_stores_correct_category(self, logged_in_client, db_path):
        """The stored expense category must match the submitted value."""
        client, _ = logged_in_client
        client.post("/expenses/add", data={
            "amount": "100",
            "category": "Bills",
            "date": _today_str(),
        })
        conn = _make_conn(db_path)
        row = conn.execute("SELECT category FROM expenses LIMIT 1").fetchone()
        conn.close()
        assert row["category"] == "Bills"

    def test_valid_post_stores_correct_date(self, logged_in_client, db_path):
        """The stored expense date must match the submitted YYYY-MM-DD string."""
        client, _ = logged_in_client
        target_date = "2026-06-15"
        client.post("/expenses/add", data={
            "amount": "100",
            "category": "Health",
            "date": target_date,
        })
        conn = _make_conn(db_path)
        row = conn.execute("SELECT date FROM expenses LIMIT 1").fetchone()
        conn.close()
        assert row["date"] == target_date

    def test_valid_post_stores_correct_description(self, logged_in_client, db_path):
        """The stored expense description must match the submitted text."""
        client, _ = logged_in_client
        client.post("/expenses/add", data={
            "amount": "100",
            "category": "Shopping",
            "date": _today_str(),
            "description": "Birthday gift",
        })
        conn = _make_conn(db_path)
        row = conn.execute("SELECT description FROM expenses LIMIT 1").fetchone()
        conn.close()
        assert row["description"] == "Birthday gift"

    def test_valid_post_uses_session_user_id_not_form_user_id(self, logged_in_client, db_path):
        """
        The expense's user_id must be taken from the session — not from any form
        field — and must match the currently logged-in user.
        """
        client, user_id = logged_in_client
        client.post("/expenses/add", data={
            "amount": "100",
            "category": "Food",
            "date": _today_str(),
        })
        conn = _make_conn(db_path)
        row = conn.execute("SELECT user_id FROM expenses LIMIT 1").fetchone()
        conn.close()
        assert row["user_id"] == user_id

    def test_valid_post_blank_description_does_not_error(self, logged_in_client):
        """Submitting an empty description field must succeed (description is optional)."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "category": "Other",
            "date": _today_str(),
            "description": "",
        })
        assert resp.status_code == 302

    def test_valid_post_blank_description_stored_as_null_or_empty(self, logged_in_client, db_path):
        """An empty description must be stored as NULL or empty string in the DB."""
        client, _ = logged_in_client
        client.post("/expenses/add", data={
            "amount": "100",
            "category": "Other",
            "date": _today_str(),
            "description": "",
        })
        conn = _make_conn(db_path)
        row = conn.execute("SELECT description FROM expenses LIMIT 1").fetchone()
        conn.close()
        assert row["description"] is None or row["description"] == ""

    def test_new_expense_appears_in_expenses_listing(self, logged_in_client):
        """
        After a successful POST, the new expense must be visible when fetching
        the /expenses listing for that date.
        """
        client, _ = logged_in_client
        client.post("/expenses/add", data={
            "amount": "750",
            "category": "Entertainment",
            "date": _today_str(),
            "description": "Concert tickets",
        })
        resp = client.get(f"/expenses?from={_today_str()}&to={_today_str()}")
        assert b"Concert tickets" in resp.data


# ------------------------------------------------------------------ #
# POST — user_id must come from session only (security)               #
# ------------------------------------------------------------------ #

class TestAddExpenseUserIdFromSessionOnly:

    def test_forged_user_id_form_field_is_ignored(self, db_path, patched_app):
        """
        If an attacker submits a user_id form field pointing to a different user,
        the inserted expense must still belong to the session user — not to the
        forged user_id from the form body.
        """
        conn = _make_conn(db_path)
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
        conn.commit()
        conn.close()

        # Authenticate as User A
        with patched_app.session_transaction() as sess:
            sess["user_id"] = user_a
            sess["user_name"] = "User A"

        # Submit form pretending to be User B via a forged user_id field
        patched_app.post("/expenses/add", data={
            "amount": "500",
            "category": "Food",
            "date": _today_str(),
            "user_id": str(user_b),
        })

        conn = _make_conn(db_path)
        row = conn.execute("SELECT user_id FROM expenses LIMIT 1").fetchone()
        conn.close()
        assert row["user_id"] == user_a, (
            "Expense must be owned by the session user (User A), not the forged form field (User B)."
        )


# ------------------------------------------------------------------ #
# POST — Validation: amount                                            #
# ------------------------------------------------------------------ #

class TestAddExpenseValidationAmount:

    def test_missing_amount_returns_200(self, logged_in_client):
        """POST without an amount field → 200 (form re-rendered, not a redirect)."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "category": "Food",
            "date": _today_str(),
        })
        assert resp.status_code == 200

    def test_missing_amount_shows_error_message(self, logged_in_client):
        """POST with a missing amount → an error message must appear in the response."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "category": "Food",
            "date": _today_str(),
        })
        body = resp.data.decode().lower()
        assert any(kw in body for kw in ["error", "amount", "required", "positive", "invalid", "number"])

    def test_zero_amount_returns_200(self, logged_in_client):
        """POST with amount=0 → 200 (zero is not a positive number and must be rejected)."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": _today_str(),
        })
        assert resp.status_code == 200

    def test_zero_amount_shows_error_message(self, logged_in_client):
        """POST with amount=0 → an error message indicating the amount must be positive."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": _today_str(),
        })
        body = resp.data.decode().lower()
        assert any(kw in body for kw in ["error", "amount", "positive", "invalid", "greater"])

    def test_negative_amount_returns_200(self, logged_in_client):
        """POST with a negative amount → 200 (rejected)."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "-50",
            "category": "Food",
            "date": _today_str(),
        })
        assert resp.status_code == 200

    def test_negative_amount_shows_error_message(self, logged_in_client):
        """POST with a negative amount → error message shown."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "-50",
            "category": "Food",
            "date": _today_str(),
        })
        body = resp.data.decode().lower()
        assert any(kw in body for kw in ["error", "amount", "positive", "invalid"])

    def test_non_numeric_amount_returns_200(self, logged_in_client):
        """POST with a non-numeric amount (e.g. 'abc') → 200 (rejected)."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "abc",
            "category": "Food",
            "date": _today_str(),
        })
        assert resp.status_code == 200

    def test_non_numeric_amount_shows_error_message(self, logged_in_client):
        """POST with a non-numeric amount → error message shown."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "abc",
            "category": "Food",
            "date": _today_str(),
        })
        body = resp.data.decode().lower()
        assert any(kw in body for kw in ["error", "amount", "positive", "invalid", "number"])

    def test_whitespace_only_amount_returns_200(self, logged_in_client):
        """POST with a whitespace-only amount string → 200 (rejected as blank)."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "   ",
            "category": "Food",
            "date": _today_str(),
        })
        assert resp.status_code == 200

    def test_invalid_amount_does_not_insert_expense(self, logged_in_client, db_path):
        """A validation failure on amount must not write any row to the expenses table."""
        client, _ = logged_in_client
        client.post("/expenses/add", data={
            "category": "Food",
            "date": _today_str(),
        })
        conn = _make_conn(db_path)
        count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        conn.close()
        assert count == 0

    @pytest.mark.parametrize("amount", ["0.01", "1", "100", "9999.99", "0.50", "1500.00"])
    def test_valid_positive_amounts_are_accepted(self, seeded_client, amount):
        """Each valid positive amount (including the minimum 0.01) must result in a 302 redirect."""
        client, user_id = seeded_client
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_name"] = "Test User"
        resp = client.post("/expenses/add", data={
            "amount": amount,
            "category": "Food",
            "date": _today_str(),
        })
        assert resp.status_code == 302, (
            f"Amount '{amount}' should be valid but got HTTP {resp.status_code}."
        )


# ------------------------------------------------------------------ #
# POST — Validation: category                                          #
# ------------------------------------------------------------------ #

class TestAddExpenseValidationCategory:

    def test_missing_category_returns_200(self, logged_in_client):
        """POST without a category field → 200 (form re-rendered)."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "date": _today_str(),
        })
        assert resp.status_code == 200

    def test_invalid_category_string_returns_200(self, logged_in_client):
        """POST with an unknown category value → 200 (rejected)."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "category": "NotAValidCategory",
            "date": _today_str(),
        })
        assert resp.status_code == 200

    def test_invalid_category_shows_error_message(self, logged_in_client):
        """POST with an invalid category → error message displayed in response."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "category": "NotAValidCategory",
            "date": _today_str(),
        })
        body = resp.data.decode().lower()
        assert any(kw in body for kw in ["error", "category", "valid", "select", "invalid"])

    def test_invalid_category_does_not_insert_expense(self, logged_in_client, db_path):
        """An invalid category must not insert any row into the expenses table."""
        client, _ = logged_in_client
        client.post("/expenses/add", data={
            "amount": "100",
            "category": "Hackers",
            "date": _today_str(),
        })
        conn = _make_conn(db_path)
        count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        conn.close()
        assert count == 0

    @pytest.mark.parametrize("category", [
        "Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other",
    ])
    def test_all_seven_valid_categories_are_accepted(self, seeded_client, category):
        """
        Each of the 7 valid categories defined in the spec must be accepted,
        resulting in a 302 redirect to /expenses.
        """
        client, user_id = seeded_client
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_name"] = "Test User"
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "category": category,
            "date": _today_str(),
        })
        assert resp.status_code == 302, (
            f"Category '{category}' should be valid but got HTTP {resp.status_code}."
        )

    def test_lowercase_category_is_rejected(self, logged_in_client):
        """
        Categories must match the exact casing defined in the spec ('Food', not 'food').
        A lowercase version must be treated as invalid.
        """
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "category": "food",
            "date": _today_str(),
        })
        assert resp.status_code == 200

    def test_uppercase_category_is_rejected(self, logged_in_client):
        """
        An all-uppercase variant ('FOOD') must be rejected — exact match required.
        """
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "category": "FOOD",
            "date": _today_str(),
        })
        assert resp.status_code == 200

    def test_empty_category_is_rejected(self, logged_in_client):
        """An empty category string must be rejected."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "category": "",
            "date": _today_str(),
        })
        assert resp.status_code == 200


# ------------------------------------------------------------------ #
# POST — Validation: date                                              #
# ------------------------------------------------------------------ #

class TestAddExpenseValidationDate:

    def test_missing_date_returns_200(self, logged_in_client):
        """POST without a date field → 200 (form re-rendered)."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "category": "Food",
        })
        assert resp.status_code == 200

    def test_empty_date_returns_200(self, logged_in_client):
        """POST with an empty date string → 200 (date is required)."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "category": "Food",
            "date": "",
        })
        assert resp.status_code == 200

    def test_empty_date_shows_error_message(self, logged_in_client):
        """POST with an empty date → an error message must be shown."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "category": "Food",
            "date": "",
        })
        body = resp.data.decode().lower()
        assert any(kw in body for kw in ["error", "date", "required", "invalid"])

    def test_missing_date_does_not_insert_expense(self, logged_in_client, db_path):
        """A missing or empty date must not insert any row into the expenses table."""
        client, _ = logged_in_client
        client.post("/expenses/add", data={
            "amount": "100",
            "category": "Food",
            "date": "",
        })
        conn = _make_conn(db_path)
        count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        conn.close()
        assert count == 0

    def test_valid_yyyy_mm_dd_date_is_accepted(self, logged_in_client):
        """A well-formed YYYY-MM-DD date must be accepted and result in a 302 redirect."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "category": "Food",
            "date": "2026-07-01",
        })
        assert resp.status_code == 302


# ------------------------------------------------------------------ #
# POST — Validation: form re-fill after error                          #
# ------------------------------------------------------------------ #

class TestAddExpenseFormRefillOnError:

    def test_submitted_amount_is_refilled_after_validation_error(self, logged_in_client):
        """
        After a validation failure, the previously entered amount must appear
        in the re-rendered form so the user does not lose their input.
        """
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "999",
            "category": "NotValid",   # trigger a category error
            "date": _today_str(),
            "description": "Some item",
        })
        body = resp.data.decode()
        assert "999" in body

    def test_submitted_description_is_refilled_after_validation_error(self, logged_in_client):
        """After a validation failure, the previously entered description must be re-filled."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "category": "NotValid",
            "date": _today_str(),
            "description": "Birthday dinner",
        })
        body = resp.data.decode()
        assert "Birthday dinner" in body

    def test_submitted_date_is_refilled_after_validation_error(self, logged_in_client):
        """After a validation failure, the previously entered date must be re-filled."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "category": "NotValid",
            "date": "2026-06-20",
            "description": "",
        })
        body = resp.data.decode()
        assert "2026-06-20" in body

    def test_error_message_is_displayed_on_any_validation_failure(self, logged_in_client):
        """
        Any validation failure must produce an inline error message visible to
        the user above the form (as specified in the spec template requirements).
        """
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "0",       # invalid: must be > 0
            "category": "Food",
            "date": _today_str(),
        })
        body = resp.data.decode().lower()
        assert any(kw in body for kw in ["error", "invalid", "required", "positive"])

    def test_all_seven_category_options_still_present_after_error(self, logged_in_client):
        """
        After a validation error, all 7 category options must still be rendered
        in the re-displayed form so the user can correct their selection.
        """
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "0",   # trigger amount error
            "category": "Food",
            "date": _today_str(),
        })
        body = resp.data.decode()
        for cat in ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]:
            assert cat in body, (
                f"Category option '{cat}' must be present in the re-rendered form after a validation error."
            )

    def test_form_is_re_rendered_not_redirected_on_error(self, logged_in_client):
        """A validation error must return HTTP 200 (form re-render), not a 3xx redirect."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": _today_str(),
        })
        assert resp.status_code == 200


# ------------------------------------------------------------------ #
# POST — Edge cases                                                     #
# ------------------------------------------------------------------ #

class TestAddExpenseEdgeCases:

    def test_description_at_255_chars_is_accepted(self, logged_in_client, db_path):
        """A description exactly 255 characters long must be accepted and stored correctly."""
        client, _ = logged_in_client
        long_desc = "A" * 255
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "category": "Other",
            "date": _today_str(),
            "description": long_desc,
        })
        assert resp.status_code == 302
        conn = _make_conn(db_path)
        row = conn.execute("SELECT description FROM expenses LIMIT 1").fetchone()
        conn.close()
        assert row["description"] == long_desc

    def test_minimum_valid_amount_0_01_is_accepted(self, logged_in_client):
        """Amount of 0.01 (the smallest positive value per the spec step attribute) must be accepted."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "0.01",
            "category": "Food",
            "date": _today_str(),
        })
        assert resp.status_code == 302

    def test_amount_just_below_zero_is_rejected(self, logged_in_client):
        """Amount of -0.01 must be rejected — only strictly positive values are allowed."""
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "-0.01",
            "category": "Food",
            "date": _today_str(),
        })
        assert resp.status_code == 200

    def test_two_consecutive_valid_posts_create_two_independent_rows(
        self, logged_in_client, db_path
    ):
        """Two separate valid POSTs by the same user must each create their own DB row."""
        client, user_id = logged_in_client
        client.post("/expenses/add", data={
            "amount": "100",
            "category": "Food",
            "date": _today_str(),
            "description": "First expense",
        })
        client.post("/expenses/add", data={
            "amount": "200",
            "category": "Bills",
            "date": _today_str(),
            "description": "Second expense",
        })
        conn = _make_conn(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        conn.close()
        assert count == 2

    def test_expense_from_user_a_not_visible_to_user_b(self, db_path, patched_app):
        """
        An expense created by User A must not appear in User B's /expenses listing,
        even when the date range would include it.
        """
        conn = _make_conn(db_path)
        cur_a = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Alpha", "alpha@example.com", generate_password_hash("Password1")),
        )
        user_a = cur_a.lastrowid
        cur_b = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Beta", "beta@example.com", generate_password_hash("Password1")),
        )
        user_b = cur_b.lastrowid
        conn.commit()
        conn.close()

        # User A creates an expense via the /expenses/add route
        with patched_app.session_transaction() as sess:
            sess["user_id"] = user_a
            sess["user_name"] = "Alpha"

        patched_app.post("/expenses/add", data={
            "amount": "500",
            "category": "Shopping",
            "date": _today_str(),
            "description": "Alpha personal expense",
        })

        # Switch to User B and fetch /expenses
        with patched_app.session_transaction() as sess:
            sess["user_id"] = user_b
            sess["user_name"] = "Beta"

        resp = patched_app.get("/expenses?from=2000-01-01&to=2099-12-31")
        assert b"Alpha personal expense" not in resp.data, (
            "User B must never see User A's expenses."
        )

    def test_whitespace_description_treated_as_empty(self, logged_in_client, db_path):
        """
        A whitespace-only description should be treated as absent (stored as
        None or empty string), and the POST should still succeed.
        """
        client, _ = logged_in_client
        resp = client.post("/expenses/add", data={
            "amount": "100",
            "category": "Food",
            "date": _today_str(),
            "description": "   ",
        })
        # Must succeed (redirect), not fail
        assert resp.status_code == 302
        conn = _make_conn(db_path)
        row = conn.execute("SELECT description FROM expenses LIMIT 1").fetchone()
        conn.close()
        # Whitespace-stripped description is falsy — stored as None or ""
        desc = row["description"]
        assert desc is None or desc.strip() == ""
