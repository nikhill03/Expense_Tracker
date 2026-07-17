"""
tests/test_edit_expense.py

Spec-driven pytest tests for Step 08: Edit Expense (/expenses/<id>/edit route).

All test logic is derived from the feature specification (08-edit-expense.md).
No implementation details are read or referenced — tests must remain valid if
the implementation is completely rewritten.

Routes under test:
    GET  /expenses/<int:id>/edit — render pre-filled edit form (authenticated only)
    POST /expenses/<int:id>/edit — validate, update expense, redirect to /expenses
                                   (authenticated only)
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
    path = str(tmp_path / "test_edit_expense.db")
    conn = _make_conn(path)
    conn.executescript(
        """
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
    """
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def patched_app(db_path, monkeypatch):
    """
    Redirect every get_db() call to the isolated temp DB.

    app.py uses `from database.db import get_db`, which binds a direct reference
    in app's own namespace.  We import app BEFORE defining _get_db so the
    module-level seed_db() runs against the real DB (where its row-count guard
    fires), and then explicitly patch app_module.get_db so the route's local
    name is redirected.
    """
    import database.db as db_module
    import database.queries as q_module
    import app as app_module  # import first — module-level init_db/seed_db runs against real DB

    def _get_db():
        return _make_conn(db_path)

    monkeypatch.setattr(db_module, "get_db", _get_db)
    monkeypatch.setattr(q_module, "get_db", _get_db)
    monkeypatch.setattr(app_module, "get_db", _get_db)  # patch app's local reference

    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret-edit-expense")
    return app_module.app.test_client()


@pytest.fixture()
def seeded_client(patched_app, db_path):
    """
    Insert one test user and one test expense into the temp DB.
    Returns (flask_test_client, user_id, expense_id).
    The client has NO active session — the user is not logged in.
    """
    conn = _make_conn(db_path)
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Test User", "test@example.com", generate_password_hash("Password1")),
    )
    user_id = cur.lastrowid
    cur2 = conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description)"
        " VALUES (?, ?, ?, ?, ?)",
        (user_id, 500.00, "Food", "2026-07-10", "Original description"),
    )
    expense_id = cur2.lastrowid
    conn.commit()
    conn.close()
    return patched_app, user_id, expense_id


@pytest.fixture()
def logged_in_client(seeded_client):
    """
    Flask test client with the test user's session already set (simulates a
    logged-in state without going through the real /login route).
    Returns (client, user_id, expense_id).
    """
    client, user_id, expense_id = seeded_client
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Test User"
    return client, user_id, expense_id


# ------------------------------------------------------------------ #
# Auth guard — unauthenticated access                                  #
# ------------------------------------------------------------------ #


class TestEditExpenseAuthGuard:

    def test_get_without_login_returns_redirect(self, seeded_client):
        """GET /expenses/<id>/edit without a session → 302 redirect (not 200)."""
        client, _, expense_id = seeded_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        assert resp.status_code == 302

    def test_get_without_login_redirects_to_login(self, seeded_client):
        """GET /expenses/<id>/edit without a session → Location header contains /login."""
        client, _, expense_id = seeded_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        assert "/login" in resp.headers["Location"]

    def test_get_without_login_does_not_show_edit_form(self, seeded_client):
        """Following the unauthenticated GET redirect must land on login page, not edit form."""
        client, _, expense_id = seeded_client
        resp = client.get(f"/expenses/{expense_id}/edit", follow_redirects=True)
        body = resp.data.decode().lower()
        assert "password" in body or "login" in body

    def test_post_without_login_returns_redirect(self, seeded_client):
        """POST /expenses/<id>/edit without a session → 302 redirect (not 200)."""
        client, _, expense_id = seeded_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "Food",
                "date": _today_str(),
            },
        )
        assert resp.status_code == 302

    def test_post_without_login_redirects_to_login(self, seeded_client):
        """POST /expenses/<id>/edit without a session → Location header contains /login."""
        client, _, expense_id = seeded_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "Food",
                "date": _today_str(),
            },
        )
        assert "/login" in resp.headers["Location"]

    def test_post_without_login_does_not_update_expense(self, seeded_client, db_path):
        """An unauthenticated POST must never modify the expense row in the database."""
        client, _, expense_id = seeded_client
        client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "9999",
                "category": "Bills",
                "date": _today_str(),
                "description": "Tampered description",
            },
        )
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT amount, description FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert abs(row["amount"] - 500.00) < 0.001
        assert row["description"] == "Original description"


# ------------------------------------------------------------------ #
# Authorization — ownership check                                      #
# ------------------------------------------------------------------ #


class TestEditExpenseOwnershipCheck:

    def _setup_two_users_and_expense(self, db_path):
        """Insert two users and one expense owned by user A. Returns (user_a, user_b, expense_id)."""
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
        cur_exp = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_a, 300.00, "Food", "2026-07-01", "User A expense"),
        )
        expense_id = cur_exp.lastrowid
        conn.commit()
        conn.close()
        return user_a, user_b, expense_id

    def test_get_another_users_expense_returns_403(self, db_path, patched_app):
        """GET /expenses/<id>/edit for an expense owned by a different user → 403."""
        _, user_b, expense_id = self._setup_two_users_and_expense(db_path)

        with patched_app.session_transaction() as sess:
            sess["user_id"] = user_b
            sess["user_name"] = "User B"

        resp = patched_app.get(f"/expenses/{expense_id}/edit")
        assert resp.status_code == 403

    def test_post_another_users_expense_returns_403(self, db_path, patched_app):
        """POST /expenses/<id>/edit for an expense owned by a different user → 403."""
        _, user_b, expense_id = self._setup_two_users_and_expense(db_path)

        with patched_app.session_transaction() as sess:
            sess["user_id"] = user_b
            sess["user_name"] = "User B"

        resp = patched_app.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "1.00",
                "category": "Bills",
                "date": _today_str(),
                "description": "Hijacked",
            },
        )
        assert resp.status_code == 403

    def test_post_another_users_expense_does_not_update_db(self, db_path, patched_app):
        """
        Attempting to POST to another user's expense must not modify the expense
        row in the database — the original values must remain intact.
        """
        _, user_b, expense_id = self._setup_two_users_and_expense(db_path)

        with patched_app.session_transaction() as sess:
            sess["user_id"] = user_b
            sess["user_name"] = "User B"

        patched_app.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "1.00",
                "category": "Bills",
                "date": _today_str(),
                "description": "Hijacked",
            },
        )

        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT amount, description FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert abs(row["amount"] - 300.00) < 0.001
        assert row["description"] == "User A expense"


# ------------------------------------------------------------------ #
# 404 — Non-existent expense ID                                        #
# ------------------------------------------------------------------ #


class TestEditExpenseNotFound:

    def test_get_nonexistent_id_returns_404(self, logged_in_client):
        """GET /expenses/99999/edit for an ID that does not exist → 404."""
        client, _, _ = logged_in_client
        resp = client.get("/expenses/99999/edit")
        assert resp.status_code == 404

    def test_post_nonexistent_id_returns_404(self, logged_in_client):
        """POST /expenses/99999/edit for an ID that does not exist → 404."""
        client, _, _ = logged_in_client
        resp = client.post(
            "/expenses/99999/edit",
            data={
                "amount": "100",
                "category": "Food",
                "date": _today_str(),
            },
        )
        assert resp.status_code == 404


# ------------------------------------------------------------------ #
# GET — Pre-filled form rendering                                      #
# ------------------------------------------------------------------ #


class TestEditExpenseGetForm:

    def test_get_returns_200_when_logged_in(self, logged_in_client):
        """Authenticated GET /expenses/<id>/edit → HTTP 200."""
        client, _, expense_id = logged_in_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        assert resp.status_code == 200

    def test_get_shows_edit_expense_heading(self, logged_in_client):
        """The page must contain an 'Edit Expense' heading or title."""
        client, _, expense_id = logged_in_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        assert b"Edit Expense" in resp.data

    def test_get_form_uses_post_method(self, logged_in_client):
        """The form element must use method='post'."""
        client, _, expense_id = logged_in_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode().lower()
        assert 'method="post"' in body or "method='post'" in body

    def test_get_form_action_targets_edit_url(self, logged_in_client):
        """The form action must target the correct /expenses/<id>/edit URL."""
        client, _, expense_id = logged_in_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert f"/expenses/{expense_id}/edit" in body

    def test_get_form_has_amount_input(self, logged_in_client):
        """The form must contain an input element named 'amount'."""
        client, _, expense_id = logged_in_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert 'name="amount"' in body or "name='amount'" in body

    def test_get_form_has_category_select(self, logged_in_client):
        """The form must contain a select element named 'category'."""
        client, _, expense_id = logged_in_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert 'name="category"' in body or "name='category'" in body

    def test_get_form_has_date_input(self, logged_in_client):
        """The form must contain an input element named 'date'."""
        client, _, expense_id = logged_in_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert 'name="date"' in body or "name='date'" in body

    def test_get_form_has_description_input(self, logged_in_client):
        """The form must contain an input or textarea element named 'description'."""
        client, _, expense_id = logged_in_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert 'name="description"' in body or "name='description'" in body

    def test_get_form_prefills_existing_amount(self, logged_in_client):
        """The amount field must be pre-filled with the expense's current amount (500)."""
        client, _, expense_id = logged_in_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert "500" in body

    def test_get_form_prefills_existing_category(self, logged_in_client):
        """The category field must show the expense's current category pre-selected ('Food')."""
        client, _, expense_id = logged_in_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert "Food" in body

    def test_get_form_prefills_existing_date(self, logged_in_client):
        """The date field must be pre-filled with the expense's current date (2026-07-10)."""
        client, _, expense_id = logged_in_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert "2026-07-10" in body

    def test_get_form_prefills_existing_description(self, logged_in_client):
        """The description field must be pre-filled with the expense's current description."""
        client, _, expense_id = logged_in_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert "Original description" in body

    @pytest.mark.parametrize(
        "category",
        [
            "Food",
            "Transport",
            "Bills",
            "Health",
            "Entertainment",
            "Shopping",
            "Other",
        ],
    )
    def test_get_category_select_includes_all_seven_options(
        self, logged_in_client, category
    ):
        """The category <select> must render all 7 fixed options defined in the spec."""
        client, _, expense_id = logged_in_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        assert (
            category.encode() in resp.data
        ), f"Category option '{category}' must appear in the <select> on GET."

    def test_get_shows_link_back_to_expenses(self, logged_in_client):
        """The page must include a navigable link back to the expenses list."""
        client, _, expense_id = logged_in_client
        resp = client.get(f"/expenses/{expense_id}/edit")
        body = resp.data.decode()
        assert "/expenses" in body


# ------------------------------------------------------------------ #
# POST — Happy path                                                     #
# ------------------------------------------------------------------ #


class TestEditExpensePostSuccess:

    def test_valid_post_returns_redirect(self, logged_in_client):
        """A fully valid POST to /expenses/<id>/edit → 302 redirect."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "750.00",
                "category": "Transport",
                "date": "2026-07-15",
                "description": "Updated description",
            },
        )
        assert resp.status_code == 302

    def test_valid_post_redirects_to_expenses_page(self, logged_in_client):
        """A valid POST must redirect to the /expenses listing page."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "750.00",
                "category": "Transport",
                "date": "2026-07-15",
                "description": "Updated description",
            },
        )
        assert "/expenses" in resp.headers["Location"]

    def test_valid_post_does_not_redirect_back_to_edit_form(self, logged_in_client):
        """A successful POST must not redirect back to the /expenses/<id>/edit URL."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "750.00",
                "category": "Transport",
                "date": "2026-07-15",
            },
        )
        location = resp.headers.get("Location", "")
        assert f"/expenses/{expense_id}/edit" not in location

    def test_valid_post_updates_amount_in_db(self, logged_in_client, db_path):
        """The expense's amount must be updated to the submitted value in the database."""
        client, _, expense_id = logged_in_client
        client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "999.99",
                "category": "Bills",
                "date": "2026-07-15",
                "description": "Updated",
            },
        )
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT amount FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert abs(row["amount"] - 999.99) < 0.001

    def test_valid_post_updates_category_in_db(self, logged_in_client, db_path):
        """The expense's category must be updated to the submitted value in the database."""
        client, _, expense_id = logged_in_client
        client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "500.00",
                "category": "Health",
                "date": "2026-07-15",
                "description": "Updated",
            },
        )
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT category FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert row["category"] == "Health"

    def test_valid_post_updates_date_in_db(self, logged_in_client, db_path):
        """The expense's date must be updated to the submitted YYYY-MM-DD value in the database."""
        client, _, expense_id = logged_in_client
        new_date = "2026-06-25"
        client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "500.00",
                "category": "Food",
                "date": new_date,
                "description": "Updated",
            },
        )
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT date FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert row["date"] == new_date

    def test_valid_post_updates_description_in_db(self, logged_in_client, db_path):
        """The expense's description must be updated to the submitted value in the database."""
        client, _, expense_id = logged_in_client
        client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "500.00",
                "category": "Food",
                "date": "2026-07-10",
                "description": "Updated description text",
            },
        )
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT description FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert row["description"] == "Updated description text"

    def test_valid_post_does_not_change_expense_user_id(
        self, logged_in_client, db_path
    ):
        """A successful edit must not change the expense's user_id."""
        client, user_id, expense_id = logged_in_client
        client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "250.00",
                "category": "Shopping",
                "date": "2026-07-10",
                "description": "New desc",
            },
        )
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT user_id FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert row["user_id"] == user_id

    def test_valid_post_does_not_create_new_expense_row(
        self, logged_in_client, db_path
    ):
        """An edit must UPDATE the existing row — not INSERT a new one. Row count stays at 1."""
        client, _, expense_id = logged_in_client
        client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "250.00",
                "category": "Shopping",
                "date": "2026-07-10",
            },
        )
        conn = _make_conn(db_path)
        count = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        conn.close()
        assert count == 1

    def test_valid_post_blank_description_accepted(self, logged_in_client):
        """Submitting an empty description must succeed — description is optional."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "Other",
                "date": _today_str(),
                "description": "",
            },
        )
        assert resp.status_code == 302

    def test_valid_post_blank_description_stored_as_null_or_empty(
        self, logged_in_client, db_path
    ):
        """An empty description submitted on edit must be stored as NULL or empty string."""
        client, _, expense_id = logged_in_client
        client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "Other",
                "date": _today_str(),
                "description": "",
            },
        )
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT description FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert row["description"] is None or row["description"] == ""

    def test_updated_expense_visible_in_expenses_listing(self, logged_in_client):
        """
        After a valid edit, the updated description must appear in the /expenses
        listing when the date range includes the updated date.
        """
        client, _, expense_id = logged_in_client
        client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "750",
                "category": "Entertainment",
                "date": _today_str(),
                "description": "Updated concert tickets",
            },
        )
        resp = client.get(f"/expenses?from={_today_str()}&to={_today_str()}")
        assert b"Updated concert tickets" in resp.data


# ------------------------------------------------------------------ #
# POST — Validation: amount                                            #
# ------------------------------------------------------------------ #


class TestEditExpenseValidationAmount:

    def test_missing_amount_returns_200(self, logged_in_client):
        """POST without an amount field → 200 (form re-rendered, not a redirect)."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "category": "Food",
                "date": _today_str(),
            },
        )
        assert resp.status_code == 200

    def test_missing_amount_shows_error_message(self, logged_in_client):
        """POST with a missing amount → an error message must appear in the response."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "category": "Food",
                "date": _today_str(),
            },
        )
        body = resp.data.decode().lower()
        assert any(
            kw in body
            for kw in ["error", "amount", "required", "positive", "invalid", "number"]
        )

    def test_zero_amount_returns_200(self, logged_in_client):
        """POST with amount=0 → 200 (zero is not a positive number and must be rejected)."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "0",
                "category": "Food",
                "date": _today_str(),
            },
        )
        assert resp.status_code == 200

    def test_zero_amount_shows_error_message(self, logged_in_client):
        """POST with amount=0 → error message indicating the amount must be positive."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "0",
                "category": "Food",
                "date": _today_str(),
            },
        )
        body = resp.data.decode().lower()
        assert any(
            kw in body for kw in ["error", "amount", "positive", "invalid", "greater"]
        )

    def test_negative_amount_returns_200(self, logged_in_client):
        """POST with a negative amount (-10) → 200 (rejected)."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "-10",
                "category": "Food",
                "date": _today_str(),
            },
        )
        assert resp.status_code == 200

    def test_negative_amount_shows_error_message(self, logged_in_client):
        """POST with a negative amount → error message shown."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "-10",
                "category": "Food",
                "date": _today_str(),
            },
        )
        body = resp.data.decode().lower()
        assert any(kw in body for kw in ["error", "amount", "positive", "invalid"])

    def test_non_numeric_amount_returns_200(self, logged_in_client):
        """POST with a non-numeric amount ('abc') → 200 (rejected)."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "abc",
                "category": "Food",
                "date": _today_str(),
            },
        )
        assert resp.status_code == 200

    def test_non_numeric_amount_shows_error_message(self, logged_in_client):
        """POST with a non-numeric amount → error message shown."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "abc",
                "category": "Food",
                "date": _today_str(),
            },
        )
        body = resp.data.decode().lower()
        assert any(
            kw in body for kw in ["error", "amount", "positive", "invalid", "number"]
        )

    def test_whitespace_only_amount_returns_200(self, logged_in_client):
        """POST with a whitespace-only amount string → 200 (rejected as blank)."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "   ",
                "category": "Food",
                "date": _today_str(),
            },
        )
        assert resp.status_code == 200

    def test_invalid_amount_does_not_update_expense(self, logged_in_client, db_path):
        """A validation failure on amount must not modify the expense row."""
        client, _, expense_id = logged_in_client
        client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "abc",
                "category": "Food",
                "date": _today_str(),
            },
        )
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT amount FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert abs(row["amount"] - 500.00) < 0.001  # original amount unchanged

    @pytest.mark.parametrize(
        "amount", ["0.01", "1", "100", "9999.99", "0.50", "1500.00"]
    )
    def test_valid_positive_amounts_are_accepted(self, seeded_client, amount):
        """Each valid positive amount must result in a 302 redirect on edit."""
        client, user_id, expense_id = seeded_client
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_name"] = "Test User"
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": amount,
                "category": "Food",
                "date": _today_str(),
            },
        )
        assert (
            resp.status_code == 302
        ), f"Amount '{amount}' should be valid but got HTTP {resp.status_code}."


# ------------------------------------------------------------------ #
# POST — Validation: category                                          #
# ------------------------------------------------------------------ #


class TestEditExpenseValidationCategory:

    def test_missing_category_returns_200(self, logged_in_client):
        """POST without a category field → 200 (form re-rendered)."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "date": _today_str(),
            },
        )
        assert resp.status_code == 200

    def test_invalid_category_string_returns_200(self, logged_in_client):
        """POST with an unknown category value → 200 (rejected)."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "NotAValidCategory",
                "date": _today_str(),
            },
        )
        assert resp.status_code == 200

    def test_invalid_category_shows_error_message(self, logged_in_client):
        """POST with an invalid category → error message displayed in response."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "NotAValidCategory",
                "date": _today_str(),
            },
        )
        body = resp.data.decode().lower()
        assert any(
            kw in body for kw in ["error", "category", "valid", "select", "invalid"]
        )

    def test_invalid_category_does_not_update_expense(self, logged_in_client, db_path):
        """An invalid category must not update the expense row — original category is preserved."""
        client, _, expense_id = logged_in_client
        client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "InvalidCategory",
                "date": _today_str(),
            },
        )
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT category FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert row["category"] == "Food"  # original unchanged

    def test_empty_category_is_rejected(self, logged_in_client):
        """An empty category string must be rejected → 200."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "",
                "date": _today_str(),
            },
        )
        assert resp.status_code == 200

    def test_lowercase_category_is_rejected(self, logged_in_client):
        """Category 'food' (wrong case) must be rejected — exact casing required."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "food",
                "date": _today_str(),
            },
        )
        assert resp.status_code == 200

    def test_uppercase_category_is_rejected(self, logged_in_client):
        """Category 'FOOD' (all-caps) must be rejected — exact casing required."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "FOOD",
                "date": _today_str(),
            },
        )
        assert resp.status_code == 200

    @pytest.mark.parametrize(
        "category",
        [
            "Food",
            "Transport",
            "Bills",
            "Health",
            "Entertainment",
            "Shopping",
            "Other",
        ],
    )
    def test_all_seven_valid_categories_are_accepted(self, seeded_client, category):
        """Each of the 7 valid categories must be accepted and result in a 302 redirect."""
        client, user_id, expense_id = seeded_client
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_name"] = "Test User"
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": category,
                "date": _today_str(),
            },
        )
        assert (
            resp.status_code == 302
        ), f"Category '{category}' should be valid but got HTTP {resp.status_code}."


# ------------------------------------------------------------------ #
# POST — Validation: date                                              #
# ------------------------------------------------------------------ #


class TestEditExpenseValidationDate:

    def test_missing_date_returns_200(self, logged_in_client):
        """POST without a date field → 200 (form re-rendered)."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "Food",
            },
        )
        assert resp.status_code == 200

    def test_empty_date_returns_200(self, logged_in_client):
        """POST with an empty date string → 200 (date is required)."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "Food",
                "date": "",
            },
        )
        assert resp.status_code == 200

    def test_empty_date_shows_error_message(self, logged_in_client):
        """POST with an empty date → an error message must be shown."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "Food",
                "date": "",
            },
        )
        body = resp.data.decode().lower()
        assert any(kw in body for kw in ["error", "date", "required", "invalid"])

    def test_empty_date_does_not_update_expense(self, logged_in_client, db_path):
        """A missing or empty date must not update the expense row — original date preserved."""
        client, _, expense_id = logged_in_client
        client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "Food",
                "date": "",
            },
        )
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT date FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert row["date"] == "2026-07-10"  # original unchanged

    def test_valid_yyyy_mm_dd_date_is_accepted(self, logged_in_client):
        """A well-formed YYYY-MM-DD date must be accepted and result in a 302 redirect."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "Food",
                "date": "2026-07-01",
            },
        )
        assert resp.status_code == 302


# ------------------------------------------------------------------ #
# POST — Validation: description                                       #
# ------------------------------------------------------------------ #


class TestEditExpenseValidationDescription:

    def test_description_at_255_chars_is_accepted(self, logged_in_client, db_path):
        """A description exactly 255 characters long must be accepted and stored."""
        client, _, expense_id = logged_in_client
        long_desc = "B" * 255
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "Other",
                "date": _today_str(),
                "description": long_desc,
            },
        )
        assert resp.status_code == 302
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT description FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert row["description"] == long_desc

    def test_description_over_255_chars_returns_200(self, logged_in_client):
        """A description longer than 255 characters must be rejected → 200."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "Food",
                "date": _today_str(),
                "description": "X" * 256,
            },
        )
        assert resp.status_code == 200

    def test_description_over_255_chars_shows_error_message(self, logged_in_client):
        """A description > 255 characters must produce an error message in the response."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "Food",
                "date": _today_str(),
                "description": "X" * 256,
            },
        )
        body = resp.data.decode().lower()
        assert any(
            kw in body for kw in ["error", "description", "255", "character", "long"]
        )

    def test_description_over_255_chars_does_not_update_expense(
        self, logged_in_client, db_path
    ):
        """A description > 255 characters must not update the expense row."""
        client, _, expense_id = logged_in_client
        client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "Food",
                "date": _today_str(),
                "description": "X" * 256,
            },
        )
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT description FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert row["description"] == "Original description"  # unchanged

    def test_whitespace_description_treated_as_empty(self, logged_in_client, db_path):
        """
        A whitespace-only description should be treated as absent (stored as
        None or empty string), and the POST should still succeed.
        """
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "Food",
                "date": _today_str(),
                "description": "   ",
            },
        )
        assert resp.status_code == 302
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT description FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        desc = row["description"]
        assert desc is None or desc.strip() == ""


# ------------------------------------------------------------------ #
# POST — Form refill after validation error                            #
# ------------------------------------------------------------------ #


class TestEditExpenseFormRefillOnError:

    def test_submitted_amount_is_refilled_after_validation_error(
        self, logged_in_client
    ):
        """
        After a validation failure, the previously entered amount must appear
        in the re-rendered form so the user does not lose their input.
        """
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "1234",
                "category": "InvalidCat",  # trigger a category error
                "date": _today_str(),
                "description": "Some item",
            },
        )
        body = resp.data.decode()
        assert "1234" in body

    def test_submitted_description_is_refilled_after_validation_error(
        self, logged_in_client
    ):
        """After a validation failure, the previously entered description must be re-filled."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "InvalidCat",
                "date": _today_str(),
                "description": "Birthday dinner edit",
            },
        )
        body = resp.data.decode()
        assert "Birthday dinner edit" in body

    def test_submitted_date_is_refilled_after_validation_error(self, logged_in_client):
        """After a validation failure, the previously entered date must be re-filled."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "100",
                "category": "InvalidCat",
                "date": "2026-05-20",
                "description": "",
            },
        )
        body = resp.data.decode()
        assert "2026-05-20" in body

    def test_error_message_is_displayed_on_any_validation_failure(
        self, logged_in_client
    ):
        """Any validation failure must produce an inline error message visible to the user."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "0",  # invalid: must be > 0
                "category": "Food",
                "date": _today_str(),
            },
        )
        body = resp.data.decode().lower()
        assert any(kw in body for kw in ["error", "invalid", "required", "positive"])

    def test_all_seven_category_options_still_present_after_error(
        self, logged_in_client
    ):
        """
        After a validation error, all 7 category options must still be rendered
        in the re-displayed form so the user can correct their selection.
        """
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "0",  # trigger amount error
                "category": "Food",
                "date": _today_str(),
            },
        )
        body = resp.data.decode()
        for cat in [
            "Food",
            "Transport",
            "Bills",
            "Health",
            "Entertainment",
            "Shopping",
            "Other",
        ]:
            assert (
                cat in body
            ), f"Category option '{cat}' must be present in the re-rendered form after a validation error."

    def test_form_is_re_rendered_not_redirected_on_error(self, logged_in_client):
        """A validation error must return HTTP 200 (form re-render), not a 3xx redirect."""
        client, _, expense_id = logged_in_client
        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={
                "amount": "0",
                "category": "Food",
                "date": _today_str(),
            },
        )
        assert resp.status_code == 200


# ------------------------------------------------------------------ #
# Expenses list — Edit action buttons                                  #
# ------------------------------------------------------------------ #


class TestExpensesListEditButton:

    def test_expenses_list_shows_edit_link_for_each_expense(self, logged_in_client):
        """
        The /expenses listing page must contain a link to /expenses/<id>/edit
        for the seeded expense, confirming the 'Edit' action button is rendered.
        """
        client, _, expense_id = logged_in_client
        resp = client.get("/expenses?from=2026-07-01&to=2026-07-31")
        body = resp.data.decode()
        assert f"/expenses/{expense_id}/edit" in body

    def test_expenses_list_edit_link_is_identifiable_as_edit_action(
        self, logged_in_client
    ):
        """
        The expenses list must include text or an attribute that makes the edit
        action visually identifiable (e.g. the word 'Edit').
        """
        client, _, expense_id = logged_in_client
        resp = client.get("/expenses?from=2026-07-01&to=2026-07-31")
        body = resp.data.decode().lower()
        assert "edit" in body
