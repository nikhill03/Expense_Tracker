"""
tests/test_11_hardening.py

Tests for Step 11: performance and hardening.

Covers the behaviour a user or operator can observe: CSRF rejection, login
lockout, the health endpoint, pagination, friendly error pages, the capped
dashboard list, and the query count behind the dashboard.
"""

import sqlite3
from datetime import date, datetime, timedelta

import pytest
from werkzeug.security import generate_password_hash


# ------------------------------------------------------------------ #
# Helpers and fixtures                                                 #
# ------------------------------------------------------------------ #


def _make_conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    """A temp database built by the app's own init_db, so indexes match."""
    import database.db as db_module

    path = str(tmp_path / "test_hardening.db")
    monkeypatch.setattr(db_module, "DATABASE_PATH", path)
    db_module.init_db()
    return path


@pytest.fixture()
def patched_app(db_path, monkeypatch):
    import database.db as db_module
    import database.queries as q_module
    import app as app_module

    def _get_db():
        return _make_conn(db_path)

    monkeypatch.setattr(db_module, "get_db", _get_db)
    monkeypatch.setattr(q_module, "get_db", _get_db)
    monkeypatch.setattr(app_module, "get_db", _get_db)

    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret-hardening")
    app_module.app.config.pop("CSRF_ENABLED", None)
    yield app_module.app.test_client()
    app_module.app.config.pop("CSRF_ENABLED", None)


@pytest.fixture()
def user_id(db_path):
    conn = _make_conn(db_path)
    uid = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Test User", "test@example.com", generate_password_hash("Password1")),
    ).lastrowid
    conn.commit()
    conn.close()
    return uid


@pytest.fixture()
def logged_in(patched_app, user_id):
    with patched_app.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Test User"
    return patched_app


def _add_expenses(path, uid, count, amount=100.0, category="Food"):
    conn = _make_conn(path)
    start = date.today()
    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description)"
        " VALUES (?, ?, ?, ?, ?)",
        [
            (
                uid,
                amount,
                category,
                (start - timedelta(days=i)).isoformat(),
                f"Item {i}",
            )
            for i in range(count)
        ],
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------ #
# Schema / indexes                                                     #
# ------------------------------------------------------------------ #


class TestSchema:
    def test_expense_query_indexes_exist(self, db_path):
        conn = _make_conn(db_path)
        names = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        conn.close()
        assert "idx_expenses_user_date" in names
        assert "idx_expenses_user_event" in names

    def test_dashboard_query_uses_the_index(self, db_path):
        conn = _make_conn(db_path)
        plan = " ".join(
            r["detail"]
            for r in conn.execute(
                "EXPLAIN QUERY PLAN SELECT category, SUM(amount) FROM expenses"
                " WHERE user_id = ? AND date >= ? AND date <= ? GROUP BY category",
                (1, "2026-01-01", "2026-12-31"),
            )
        )
        conn.close()
        assert "idx_expenses_user_date" in plan
        assert "SCAN expenses" not in plan

    def test_wal_mode_is_enabled(self, db_path):
        conn = _make_conn(db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode.lower() == "wal"

    def test_login_attempts_table_exists(self, db_path):
        conn = _make_conn(db_path)
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        conn.close()
        assert "login_attempts" in tables


# ------------------------------------------------------------------ #
# Health endpoint                                                      #
# ------------------------------------------------------------------ #


class TestHealth:
    def test_healthz_is_public_and_ok(self, patched_app):
        resp = patched_app.get("/healthz")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"


# ------------------------------------------------------------------ #
# CSRF                                                                 #
# ------------------------------------------------------------------ #


class TestCSRF:
    @pytest.fixture()
    def csrf_client(self, logged_in):
        import app as app_module

        app_module.app.config["CSRF_ENABLED"] = True
        return logged_in

    def test_post_without_token_is_rejected(self, csrf_client):
        resp = csrf_client.post(
            "/expenses/add",
            data={
                "amount": "100",
                "category": "Food",
                "date": date.today().isoformat(),
                "description": "No token",
            },
        )
        assert resp.status_code == 400

    def test_post_with_wrong_token_is_rejected(self, csrf_client):
        with csrf_client.session_transaction() as sess:
            sess["csrf_token"] = "the-real-token"

        resp = csrf_client.post(
            "/expenses/add",
            data={
                "amount": "100",
                "category": "Food",
                "date": date.today().isoformat(),
                "csrf_token": "a-different-token",
            },
        )
        assert resp.status_code == 400

    def test_post_with_correct_token_succeeds(self, csrf_client, db_path):
        with csrf_client.session_transaction() as sess:
            sess["csrf_token"] = "the-real-token"

        resp = csrf_client.post(
            "/expenses/add",
            data={
                "amount": "100",
                "category": "Food",
                "date": date.today().isoformat(),
                "description": "With token",
                "csrf_token": "the-real-token",
            },
        )
        assert resp.status_code == 302

        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM expenses WHERE description = 'With token'"
        ).fetchone()
        conn.close()
        assert row["c"] == 1

    def test_forms_render_a_token_field(self, csrf_client):
        body = csrf_client.get("/expenses/add").get_data(as_text=True)
        assert 'name="csrf_token"' in body


# ------------------------------------------------------------------ #
# Login throttling                                                     #
# ------------------------------------------------------------------ #


class TestLoginThrottle:
    def _fail_login(self, client):
        return client.post(
            "/login", data={"email": "test@example.com", "password": "wrong"}
        )

    def test_lockout_after_five_failures(self, patched_app, user_id):
        for _ in range(5):
            resp = self._fail_login(patched_app)
            assert "Invalid email or password" in resp.get_data(as_text=True)

        resp = self._fail_login(patched_app)
        assert "Too many failed attempts" in resp.get_data(as_text=True)

    def test_correct_password_blocked_while_locked(self, patched_app, user_id):
        for _ in range(5):
            self._fail_login(patched_app)

        resp = patched_app.post(
            "/login", data={"email": "test@example.com", "password": "Password1"}
        )
        assert resp.status_code == 200
        assert "Too many failed attempts" in resp.get_data(as_text=True)

    def test_successful_login_clears_the_counter(self, patched_app, user_id, db_path):
        for _ in range(3):
            self._fail_login(patched_app)

        resp = patched_app.post(
            "/login", data={"email": "test@example.com", "password": "Password1"}
        )
        assert resp.status_code == 302

        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM login_attempts WHERE email = 'test@example.com'"
        ).fetchone()
        conn.close()
        assert row["c"] == 0

    def test_expired_lockout_lets_the_user_back_in(self, patched_app, user_id, db_path):
        conn = _make_conn(db_path)
        conn.execute(
            "INSERT INTO login_attempts (email, failures, locked_until) VALUES (?, ?, ?)",
            (
                "test@example.com",
                0,
                (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
        conn.close()

        resp = patched_app.post(
            "/login", data={"email": "test@example.com", "password": "Password1"}
        )
        assert resp.status_code == 302


# ------------------------------------------------------------------ #
# Pagination and the capped dashboard                                  #
# ------------------------------------------------------------------ #


class TestPagination:
    def test_profile_shows_at_most_ten_rows(self, logged_in, db_path, user_id):
        _add_expenses(db_path, user_id, 25)
        body = logged_in.get("/profile?preset=all").get_data(as_text=True)
        assert body.count('href="/expenses/') <= 10 * 2  # edit link + delete form each

    def test_profile_links_to_the_full_list(self, logged_in, db_path, user_id):
        _add_expenses(db_path, user_id, 3)
        body = logged_in.get("/profile").get_data(as_text=True)
        assert "View all" in body

    def test_expenses_page_splits_into_pages(self, logged_in, db_path, user_id):
        _add_expenses(db_path, user_id, 60)
        today = date.today().isoformat()
        start = (date.today() - timedelta(days=90)).isoformat()

        first = logged_in.get(f"/expenses?from={start}&to={today}").get_data(
            as_text=True
        )
        assert "Page 1 of 2" in first
        assert "Item 0" in first
        assert "Item 55" not in first

        second = logged_in.get(f"/expenses?page=2&from={start}&to={today}").get_data(
            as_text=True
        )
        assert "Item 55" in second

    def test_total_covers_every_page_not_just_this_one(
        self, logged_in, db_path, user_id
    ):
        _add_expenses(db_path, user_id, 60, amount=100.0)
        today = date.today().isoformat()
        start = (date.today() - timedelta(days=90)).isoformat()

        body = logged_in.get(f"/expenses?from={start}&to={today}").get_data(
            as_text=True
        )
        assert "₹6,000.00" in body  # 60 x 100, not the 50 on screen

    def test_out_of_range_page_is_handled(self, logged_in, db_path, user_id):
        _add_expenses(db_path, user_id, 5)
        resp = logged_in.get("/expenses?page=99")
        assert resp.status_code == 200


# ------------------------------------------------------------------ #
# Query count                                                          #
# ------------------------------------------------------------------ #


class TestQueryCount:
    def test_dashboard_runs_a_fixed_small_number_of_queries(
        self, patched_app, db_path, user_id, monkeypatch
    ):
        """A handful of queries, and the count must stay flat.

        The dashboard looks up the user, aggregates spending once, fetches the
        transaction list and checks the budgets. The fifth is the quick-add
        sheet's event picker, which base.html renders on every signed-in page —
        a deliberate id+name lookup (queries.get_event_options), not the
        aggregate-heavy get_events_for_user.

        What matters is that the number never grows with the number of expenses,
        categories or events on the page.
        """
        import database.queries as q_module

        _add_expenses(db_path, user_id, 20)
        counter = {"queries": 0}

        class CountingConn:
            def __init__(self, conn):
                self._conn = conn

            def execute(self, *args, **kwargs):
                counter["queries"] += 1
                return self._conn.execute(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._conn, name)

        monkeypatch.setattr(
            q_module, "get_db", lambda: CountingConn(_make_conn(db_path))
        )

        with patched_app.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_name"] = "Test User"

        counter["queries"] = 0
        resp = patched_app.get("/profile?preset=all")
        assert resp.status_code == 200
        assert counter["queries"] <= 5, f"dashboard ran {counter['queries']} queries"

        # Ten times the data must not mean more queries.
        _add_expenses(db_path, user_id, 200, category="Transport")
        counter["queries"] = 0
        patched_app.get("/profile?preset=all")
        assert counter["queries"] <= 5, f"dashboard ran {counter['queries']} queries"

    def test_pages_with_their_own_event_list_do_not_query_it_twice(
        self, patched_app, db_path, user_id, monkeypatch
    ):
        """The quick-add sheet is on every page, and some pages have a picker of
        their own. Both read the same per-request cache, so the event list is
        fetched once per request however many pickers are on the page.
        """
        import database.queries as q_module

        conn = _make_conn(db_path)
        for name in ("Goa Trip", "Diwali", "Wedding"):
            conn.execute(
                "INSERT INTO events (user_id, name) VALUES (?, ?)", (user_id, name)
            )
        conn.commit()
        conn.close()

        event_queries = {"n": 0}

        class CountingConn:
            def __init__(self, conn):
                self._conn = conn

            def execute(self, sql, *args, **kwargs):
                if "FROM events" in sql:
                    event_queries["n"] += 1
                return self._conn.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._conn, name)

        monkeypatch.setattr(
            q_module, "get_db", lambda: CountingConn(_make_conn(db_path))
        )

        with patched_app.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_name"] = "Test User"

        # Two pickers on the page: the form's own, and the sheet's.
        event_queries["n"] = 0
        assert patched_app.get("/expenses/add").status_code == 200
        assert event_queries["n"] == 1, f"ran {event_queries['n']} event queries"

        # /events already holds the full list and primes the cache for the sheet.
        event_queries["n"] = 0
        assert patched_app.get("/events").status_code == 200
        assert event_queries["n"] == 1, f"ran {event_queries['n']} event queries"


# ------------------------------------------------------------------ #
# Error pages                                                          #
# ------------------------------------------------------------------ #


class TestErrorPages:
    def test_unknown_page_is_friendly(self, patched_app):
        resp = patched_app.get("/no-such-page")
        assert resp.status_code == 404
        body = resp.get_data(as_text=True)
        assert "Page not found" in body
        assert "Traceback" not in body

    def test_forbidden_expense_is_friendly(self, logged_in, db_path, user_id):
        conn = _make_conn(db_path)
        other = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Other", "other@example.com", "x"),
        ).lastrowid
        expense_id = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            (other, 50.0, "Food", date.today().isoformat(), "Theirs"),
        ).lastrowid
        conn.commit()
        conn.close()

        resp = logged_in.get(f"/expenses/{expense_id}/edit")
        assert resp.status_code == 403
        assert "Not your expense" in resp.get_data(as_text=True)
