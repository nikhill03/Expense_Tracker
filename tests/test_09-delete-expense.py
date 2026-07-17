"""
tests/test_09-delete-expense.py

Spec-driven pytest tests for Step 09: Delete Expense
(POST /expenses/<id>/delete route).

All test logic is derived from the feature specification (09-delete-expense.md).
No implementation details are read or referenced — tests must remain valid if
the implementation is completely rewritten.

Route under test:
    POST /expenses/<int:expense_id>/delete — delete the expense (authenticated only)
"""

import sqlite3

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


# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #


@pytest.fixture()
def db_path(tmp_path):
    """Create a fresh temporary SQLite DB with the Spendly schema."""
    path = str(tmp_path / "test_delete_expense.db")
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

    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret-delete-expense")
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
        (user_id, 500.00, "Food", "2026-07-10", "Lunch at restaurant"),
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


class TestDeleteExpenseAuthGuard:

    def test_post_without_login_returns_redirect(self, seeded_client):
        """POST /expenses/<id>/delete without a session → 302 redirect (not 200)."""
        client, _, expense_id = seeded_client
        resp = client.post(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 302

    def test_post_without_login_redirects_to_login(self, seeded_client):
        """POST /expenses/<id>/delete without a session → Location header contains /login."""
        client, _, expense_id = seeded_client
        resp = client.post(f"/expenses/{expense_id}/delete")
        assert "/login" in resp.headers["Location"]

    def test_post_without_login_lands_on_login_page(self, seeded_client):
        """Following the unauthenticated POST redirect must land on the login page."""
        client, _, expense_id = seeded_client
        resp = client.post(f"/expenses/{expense_id}/delete", follow_redirects=True)
        body = resp.data.decode().lower()
        assert "password" in body or "login" in body

    def test_post_without_login_does_not_delete_expense(self, seeded_client, db_path):
        """An unauthenticated POST must never remove the expense row from the database."""
        client, _, expense_id = seeded_client
        client.post(f"/expenses/{expense_id}/delete")
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT id FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert (
            row is not None
        ), "Expense must still exist after an unauthenticated delete attempt."


# ------------------------------------------------------------------ #
# HTTP method guard — GET must be blocked                              #
# ------------------------------------------------------------------ #


class TestDeleteExpenseGetBlocked:

    def test_get_request_returns_405(self, logged_in_client):
        """GET /expenses/<id>/delete → 405 Method Not Allowed (route accepts POST only)."""
        client, _, expense_id = logged_in_client
        resp = client.get(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 405

    def test_get_request_without_login_returns_405(self, seeded_client):
        """GET /expenses/<id>/delete without a session → still 405, not 302."""
        client, _, expense_id = seeded_client
        resp = client.get(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 405

    def test_get_request_does_not_delete_expense(self, logged_in_client, db_path):
        """A GET to the delete route must not remove the expense row."""
        client, _, expense_id = logged_in_client
        client.get(f"/expenses/{expense_id}/delete")
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT id FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert (
            row is not None
        ), "Expense must still exist after a GET to the delete route."


# ------------------------------------------------------------------ #
# 404 — Non-existent expense ID                                        #
# ------------------------------------------------------------------ #


class TestDeleteExpenseNotFound:

    def test_post_nonexistent_id_returns_404(self, logged_in_client):
        """POST /expenses/99999/delete for an ID that does not exist → 404."""
        client, _, _ = logged_in_client
        resp = client.post("/expenses/99999/delete")
        assert resp.status_code == 404

    def test_post_nonexistent_id_zero_returns_404(self, logged_in_client):
        """POST /expenses/0/delete (ID zero, which is never a valid autoincrement PK) → 404."""
        client, _, _ = logged_in_client
        resp = client.post("/expenses/0/delete")
        assert resp.status_code == 404


# ------------------------------------------------------------------ #
# Authorization — ownership check                                      #
# ------------------------------------------------------------------ #


class TestDeleteExpenseOwnershipCheck:

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

    def test_post_another_users_expense_returns_403(self, db_path, patched_app):
        """POST /expenses/<id>/delete for an expense owned by a different user → 403."""
        _, user_b, expense_id = self._setup_two_users_and_expense(db_path)

        with patched_app.session_transaction() as sess:
            sess["user_id"] = user_b
            sess["user_name"] = "User B"

        resp = patched_app.post(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 403

    def test_post_another_users_expense_does_not_delete_row(self, db_path, patched_app):
        """
        Attempting to delete another user's expense must not remove the row
        from the database — the original expense must still exist.
        """
        _, user_b, expense_id = self._setup_two_users_and_expense(db_path)

        with patched_app.session_transaction() as sess:
            sess["user_id"] = user_b
            sess["user_name"] = "User B"

        patched_app.post(f"/expenses/{expense_id}/delete")

        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT id FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert row is not None, "Expense owned by User A must not be deleted by User B."

    def test_post_another_users_expense_preserves_amount(self, db_path, patched_app):
        """The amount of the protected expense must remain unchanged after a 403 attempt."""
        _, user_b, expense_id = self._setup_two_users_and_expense(db_path)

        with patched_app.session_transaction() as sess:
            sess["user_id"] = user_b
            sess["user_name"] = "User B"

        patched_app.post(f"/expenses/{expense_id}/delete")

        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT amount FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert abs(row["amount"] - 300.00) < 0.001


# ------------------------------------------------------------------ #
# POST — Happy path                                                    #
# ------------------------------------------------------------------ #


class TestDeleteExpenseHappyPath:

    def test_valid_post_returns_redirect(self, logged_in_client):
        """A valid POST to /expenses/<id>/delete → 302 redirect."""
        client, _, expense_id = logged_in_client
        resp = client.post(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 302

    def test_valid_post_redirects_to_expenses_page(self, logged_in_client):
        """A valid POST must redirect to the /expenses listing page."""
        client, _, expense_id = logged_in_client
        resp = client.post(f"/expenses/{expense_id}/delete")
        assert "/expenses" in resp.headers["Location"]

    def test_valid_post_does_not_redirect_to_delete_url(self, logged_in_client):
        """A successful delete must not redirect back to the /expenses/<id>/delete URL."""
        client, _, expense_id = logged_in_client
        resp = client.post(f"/expenses/{expense_id}/delete")
        location = resp.headers.get("Location", "")
        assert f"/expenses/{expense_id}/delete" not in location

    def test_valid_post_expenses_page_loads_after_redirect(self, logged_in_client):
        """Following the redirect after a delete must yield a 200 on the /expenses page."""
        client, _, expense_id = logged_in_client
        resp = client.post(f"/expenses/{expense_id}/delete", follow_redirects=True)
        assert resp.status_code == 200


# ------------------------------------------------------------------ #
# DB side effect — row actually gone after delete                      #
# ------------------------------------------------------------------ #


class TestDeleteExpenseDbSideEffect:

    def test_deleted_expense_row_is_gone_from_db(self, logged_in_client, db_path):
        """After a successful delete, the expense row must no longer exist in the DB."""
        client, _, expense_id = logged_in_client
        client.post(f"/expenses/{expense_id}/delete")
        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT id FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert (
            row is None
        ), "Expense row must be absent from the DB after a successful delete."

    def test_delete_reduces_expense_count_by_one(self, logged_in_client, db_path):
        """The total number of expense rows must decrease by exactly one after a delete."""
        client, user_id, expense_id = logged_in_client

        # Seed a second expense so the table is not completely emptied, proving
        # only the targeted row is removed.
        conn = _make_conn(db_path)
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, 200.00, "Transport", "2026-07-05", "Bus pass"),
        )
        conn.commit()
        before = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        conn.close()

        client.post(f"/expenses/{expense_id}/delete")

        conn = _make_conn(db_path)
        after = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        conn.close()
        assert after == before - 1

    def test_delete_does_not_remove_other_expenses(self, logged_in_client, db_path):
        """Deleting one expense must not affect any other expense rows."""
        client, user_id, expense_id = logged_in_client

        conn = _make_conn(db_path)
        cur = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, 750.00, "Bills", "2026-07-03", "Electric bill"),
        )
        other_id = cur.lastrowid
        conn.commit()
        conn.close()

        client.post(f"/expenses/{expense_id}/delete")

        conn = _make_conn(db_path)
        surviving_row = conn.execute(
            "SELECT id FROM expenses WHERE id = ?", (other_id,)
        ).fetchone()
        conn.close()
        assert (
            surviving_row is not None
        ), "Other expense rows must not be affected by the delete."

    def test_deleted_expense_absent_from_expenses_listing(self, logged_in_client):
        """After deletion, the expense must not appear in the /expenses listing page."""
        client, _, expense_id = logged_in_client
        client.post(f"/expenses/{expense_id}/delete")
        # Fetch a wide date range to ensure the expense would appear if it existed.
        resp = client.get("/expenses?from=2000-01-01&to=2099-12-31")
        assert b"Lunch at restaurant" not in resp.data

    def test_deleted_expense_absent_from_profile_page(self, logged_in_client):
        """After deletion, the expense must not appear in the /profile recent transactions."""
        client, _, expense_id = logged_in_client
        client.post(f"/expenses/{expense_id}/delete")
        resp = client.get("/profile")
        assert b"Lunch at restaurant" not in resp.data


# ------------------------------------------------------------------ #
# Expenses list — Delete action buttons                                #
# ------------------------------------------------------------------ #


class TestExpensesListDeleteButton:

    def test_expenses_list_shows_delete_form_for_each_expense(self, logged_in_client):
        """
        The /expenses listing page must contain a form that POSTs to
        /expenses/<id>/delete for the seeded expense, confirming the 'Delete'
        action is rendered.
        """
        client, _, expense_id = logged_in_client
        resp = client.get("/expenses?from=2026-07-01&to=2026-07-31")
        body = resp.data.decode()
        assert f"/expenses/{expense_id}/delete" in body

    def test_expenses_list_delete_form_uses_post_method(self, logged_in_client):
        """
        The delete form on the /expenses listing page must use method='post'
        (the route rejects GET with 405).
        """
        client, _, expense_id = logged_in_client
        resp = client.get("/expenses?from=2026-07-01&to=2026-07-31")
        body = resp.data.decode().lower()
        assert 'method="post"' in body or "method='post'" in body

    def test_expenses_list_delete_action_is_visually_identifiable(
        self, logged_in_client
    ):
        """
        The expenses list must include text that makes the delete action
        recognisable to the user (e.g. the word 'Delete').
        """
        client, _, expense_id = logged_in_client
        resp = client.get("/expenses?from=2026-07-01&to=2026-07-31")
        body = resp.data.decode().lower()
        assert "delete" in body

    def test_profile_page_shows_delete_form_for_each_transaction(
        self, logged_in_client
    ):
        """
        The /profile Recent Transactions section must contain a delete form
        targeting /expenses/<id>/delete for the seeded expense.
        """
        client, _, expense_id = logged_in_client
        resp = client.get("/profile")
        body = resp.data.decode()
        assert f"/expenses/{expense_id}/delete" in body
