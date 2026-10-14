"""
tests/test_17_month_comparison.py

Tests for the "this month vs last month" dashboard stat — the leftover piece
of Step 17 (mobile dashboard). Covers database.queries.get_month_comparison()
directly, plus that /profile renders it without breaking the page when it is
absent.

The comparison is deliberately "spend so far vs spend so far on the same day
last month", not whole-month vs whole-month — comparing 3 days of this month
against all 30 of last month would make the first few days of any month look
like a huge improvement for no real reason.
"""

import sqlite3
from datetime import date

import pytest
from werkzeug.security import generate_password_hash

from database.queries import get_month_comparison


def _make_conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    import database.db as db_module

    path = str(tmp_path / "test_month_comparison.db")
    monkeypatch.setattr(db_module, "DATABASE_PATH", path)
    db_module.init_db()
    return path


@pytest.fixture()
def patch_queries(db_path, monkeypatch):
    import database.queries as q_module

    monkeypatch.setattr(q_module, "get_db", lambda: _make_conn(db_path))
    return db_path


@pytest.fixture()
def user_id(patch_queries):
    conn = _make_conn(patch_queries)
    uid = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Test User", "test@example.com", generate_password_hash("Password1")),
    ).lastrowid
    conn.commit()
    conn.close()
    return uid


def _spend(path, uid, amount, when, category="Food"):
    conn = _make_conn(path)
    conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description)"
        " VALUES (?, ?, ?, ?, ?)",
        (uid, amount, category, when.isoformat(), "Test spend"),
    )
    conn.commit()
    conn.close()


class TestGetMonthComparison:
    def test_none_with_no_expenses_at_all(self, patch_queries, user_id):
        assert get_month_comparison(user_id, today=date(2026, 10, 15)) is None

    def test_none_when_only_this_month_has_spending(self, patch_queries, user_id):
        """A new user's first month has nothing to compare against."""
        _spend(patch_queries, user_id, 500.0, date(2026, 10, 5))

        assert get_month_comparison(user_id, today=date(2026, 10, 15)) is None

    def test_spending_more_than_last_month(self, patch_queries, user_id):
        _spend(patch_queries, user_id, 1000.0, date(2026, 9, 10))
        _spend(patch_queries, user_id, 1500.0, date(2026, 10, 10))

        result = get_month_comparison(user_id, today=date(2026, 10, 15))

        assert result["direction"] == "up"
        assert result["pct_change"] == 50

    def test_spending_less_than_last_month(self, patch_queries, user_id):
        _spend(patch_queries, user_id, 1000.0, date(2026, 9, 10))
        _spend(patch_queries, user_id, 500.0, date(2026, 10, 10))

        result = get_month_comparison(user_id, today=date(2026, 10, 15))

        assert result["direction"] == "down"
        assert result["pct_change"] == 50

    def test_spending_about_the_same_is_flat(self, patch_queries, user_id):
        _spend(patch_queries, user_id, 1000.0, date(2026, 9, 10))
        _spend(patch_queries, user_id, 1000.0, date(2026, 10, 10))

        result = get_month_comparison(user_id, today=date(2026, 10, 15))

        assert result["direction"] == "flat"
        assert result["pct_change"] == 0

    def test_compares_the_same_point_in_the_month_not_the_whole_month(
        self, patch_queries, user_id
    ):
        """Early in a new month, the rest of last month must not count yet.

        Without this, day 2 of a new month would be compared against all 30
        days of the previous one and look like a huge improvement for having
        simply not had time to spend anything yet.
        """
        # Day 25 of last month — later than "today" below, so out of range.
        _spend(patch_queries, user_id, 2000.0, date(2026, 9, 25))
        # Day 5 of last month — within range.
        _spend(patch_queries, user_id, 300.0, date(2026, 9, 5))
        _spend(patch_queries, user_id, 300.0, date(2026, 10, 5))

        result = get_month_comparison(user_id, today=date(2026, 10, 5))

        # Only the ₹300 from day 5 of September counts, matching this month's
        # ₹300 from day 5 — flat, not a 1150% drop from including the ₹2000.
        assert result["direction"] == "flat"

    def test_clamps_to_a_shorter_previous_month(self, patch_queries, user_id):
        """Comparing 31 March must not overshoot a 28-day February."""
        _spend(patch_queries, user_id, 400.0, date(2026, 2, 28))
        _spend(patch_queries, user_id, 400.0, date(2026, 3, 31))

        # Must not raise, and must count the Feb 28 expense (the clamped day).
        result = get_month_comparison(user_id, today=date(2026, 3, 31))

        assert result is not None
        assert result["direction"] == "flat"

    def test_ignores_another_users_expenses(self, patch_queries, user_id):
        conn = _make_conn(patch_queries)
        other = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Other User", "other@example.com", generate_password_hash("Password1")),
        ).lastrowid
        conn.commit()
        conn.close()

        _spend(patch_queries, other, 5000.0, date(2026, 9, 10))
        _spend(patch_queries, user_id, 1000.0, date(2026, 9, 10))
        _spend(patch_queries, user_id, 1000.0, date(2026, 10, 10))

        result = get_month_comparison(user_id, today=date(2026, 10, 15))

        assert result["direction"] == "flat"


class TestProfilePageRendersTheComparison:
    @pytest.fixture()
    def client(self, patch_queries, user_id):
        import app as app_module

        app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret-month-cmp")
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_name"] = "Test User"
        return client

    def test_profile_page_renders_with_no_comparison(self, client):
        """A brand-new account has nothing to compare against — must not 500."""
        response = client.get("/profile")
        assert response.status_code == 200
        assert "Where it went" in response.get_data(as_text=True)

    def test_profile_page_shows_the_comparison_when_available(
        self, patch_queries, client, user_id
    ):
        import timeutil
        from datetime import timedelta

        today = timeutil.today()
        # The 1st of last month is always within the "same day so far" window
        # (prev_same_day is never earlier than the 1st), so this is safe
        # regardless of what day of the month the suite happens to run on —
        # the trap test_10_events.py and test_12_budgets.py just fell into.
        last_month_first = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
        _spend(patch_queries, user_id, 100.0, last_month_first)
        _spend(patch_queries, user_id, 200.0, today)

        body = client.get("/profile").get_data(as_text=True)
        assert "than this time last month" in body
