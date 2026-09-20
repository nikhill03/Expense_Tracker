"""
tests/test_12_budgets.py

Spec-driven tests for Step 12: monthly category budgets.

Routes under test:
    GET  /budgets — the budget form, with this month's progress
    POST /budgets — set, update or clear a budget per category
Also covered: the dashboard budget block and the safe-to-spend figure.
"""

import sqlite3
from calendar import monthrange
from datetime import date

import pytest
from werkzeug.security import generate_password_hash


def _make_conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    import database.db as db_module

    path = str(tmp_path / "test_budgets.db")
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

    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret-budgets")
    return app_module.app.test_client()


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
def client(patched_app, user_id):
    with patched_app.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Test User"
    return patched_app


def _set_budget(path, uid, category, amount):
    conn = _make_conn(path)
    conn.execute(
        "INSERT INTO budgets (user_id, category, monthly_amount) VALUES (?, ?, ?)",
        (uid, category, amount),
    )
    conn.commit()
    conn.close()


def _spend(path, uid, amount, category="Food", when=None):
    conn = _make_conn(path)
    conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description)"
        " VALUES (?, ?, ?, ?, ?)",
        (uid, amount, category, (when or date.today()).isoformat(), "Test spend"),
    )
    conn.commit()
    conn.close()


def _all_categories_blank():
    return {
        f"budget_{c}": ""
        for c in [
            "Food",
            "Transport",
            "Bills",
            "Health",
            "Entertainment",
            "Shopping",
            "Other",
        ]
    }


# ------------------------------------------------------------------ #
# Access                                                               #
# ------------------------------------------------------------------ #


class TestBudgetsRequireLogin:
    @pytest.mark.parametrize("method", ["get", "post"])
    def test_logged_out_redirects(self, patched_app, method):
        resp = getattr(patched_app, method)("/budgets")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


# ------------------------------------------------------------------ #
# Setting budgets                                                      #
# ------------------------------------------------------------------ #


class TestSetBudgets:
    def test_form_lists_every_category(self, client):
        body = client.get("/budgets").get_data(as_text=True)
        for category in [
            "Food",
            "Transport",
            "Bills",
            "Health",
            "Entertainment",
            "Shopping",
            "Other",
        ]:
            assert f'name="budget_{category}"' in body

    def test_saving_a_budget(self, client, db_path, user_id):
        data = _all_categories_blank()
        data["budget_Food"] = "6000"
        resp = client.post("/budgets", data=data)
        assert resp.status_code == 302

        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT * FROM budgets WHERE user_id = ? AND category = 'Food'", (user_id,)
        ).fetchone()
        conn.close()
        assert row["monthly_amount"] == 6000.0

    def test_updating_a_budget_does_not_duplicate(self, client, db_path, user_id):
        data = _all_categories_blank()
        data["budget_Food"] = "6000"
        client.post("/budgets", data=data)
        data["budget_Food"] = "7500"
        client.post("/budgets", data=data)

        conn = _make_conn(db_path)
        rows = conn.execute(
            "SELECT * FROM budgets WHERE user_id = ? AND category = 'Food'", (user_id,)
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0]["monthly_amount"] == 7500.0

    def test_blank_clears_a_budget(self, client, db_path, user_id):
        _set_budget(db_path, user_id, "Food", 6000.0)

        client.post("/budgets", data=_all_categories_blank())

        conn = _make_conn(db_path)
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM budgets WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
        conn.close()
        assert count == 0

    @pytest.mark.parametrize("bad", ["-100", "0", "abc"])
    def test_invalid_amount_is_rejected(self, client, db_path, user_id, bad):
        data = _all_categories_blank()
        data["budget_Food"] = bad
        resp = client.post("/budgets", data=data)
        assert resp.status_code == 200

        conn = _make_conn(db_path)
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM budgets WHERE user_id = ?", (user_id,)
        ).fetchone()["c"]
        conn.close()
        assert count == 0

    def test_budgets_are_per_user(self, client, db_path, user_id):
        conn = _make_conn(db_path)
        other = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Other", "other@example.com", "x"),
        ).lastrowid
        conn.execute(
            "INSERT INTO budgets (user_id, category, monthly_amount) VALUES (?, ?, ?)",
            (other, "Shopping", 9999.0),
        )
        conn.commit()
        conn.close()

        body = client.get("/budgets").get_data(as_text=True)
        assert "9999" not in body


# ------------------------------------------------------------------ #
# Status maths                                                         #
# ------------------------------------------------------------------ #


class TestBudgetStatus:
    def test_none_when_no_budgets_set(self, db_path, user_id):
        from database.queries import get_month_budget_status

        assert get_month_budget_status(user_id) is None

    def test_spent_and_remaining(self, db_path, user_id):
        from database.queries import get_month_budget_status

        _set_budget(db_path, user_id, "Food", 6000.0)
        _spend(db_path, user_id, 1500.0, "Food")

        status = get_month_budget_status(user_id, today=date(2026, 9, 20))
        food = status["categories"][0]
        assert food["spent"] == "₹1,500.00"
        assert food["budget"] == "₹6,000.00"
        assert food["remaining"] == "₹4,500.00"
        assert food["pct_of_budget"] == 25
        assert food["over_budget"] is False

    def test_eighty_percent_is_flagged(self, db_path, user_id):
        from database.queries import get_month_budget_status

        _set_budget(db_path, user_id, "Food", 1000.0)
        _spend(db_path, user_id, 850.0, "Food")

        food = get_month_budget_status(user_id)["categories"][0]
        assert food["nearly_spent"] is True
        assert food["over_budget"] is False

    def test_over_budget_is_flagged(self, db_path, user_id):
        from database.queries import get_month_budget_status

        _set_budget(db_path, user_id, "Food", 1000.0)
        _spend(db_path, user_id, 1200.0, "Food")

        food = get_month_budget_status(user_id)["categories"][0]
        assert food["over_budget"] is True
        assert food["remaining"] == "₹200.00"  # the overspend
        assert food["pct_of_budget"] == 100  # the bar never exceeds full

    def test_safe_to_spend_per_day(self, db_path, user_id):
        from database.queries import get_month_budget_status

        _set_budget(db_path, user_id, "Food", 6000.0)
        _spend(db_path, user_id, 1000.0, "Food", when=date(2026, 9, 5))

        # 20 September: 11 days left including today, ₹5,000 unspent.
        status = get_month_budget_status(user_id, today=date(2026, 9, 20))
        assert status["days_left"] == 11
        assert status["safe_per_day"] == "₹455"

    def test_last_day_of_month_does_not_divide_by_zero(self, db_path, user_id):
        from database.queries import get_month_budget_status

        _set_budget(db_path, user_id, "Food", 3000.0)
        last = date(2026, 9, monthrange(2026, 9)[1])

        status = get_month_budget_status(user_id, today=last)
        assert status["days_left"] == 1
        assert status["safe_per_day"] == "₹3,000"

    def test_over_budget_never_reports_a_safe_amount(self, db_path, user_id):
        from database.queries import get_month_budget_status

        _set_budget(db_path, user_id, "Food", 1000.0)
        _spend(db_path, user_id, 1500.0, "Food")

        status = get_month_budget_status(user_id)
        assert status["over_total"] is True
        assert status["safe_per_day"] == "₹0"

    def test_other_months_spending_is_ignored(self, db_path, user_id):
        from database.queries import get_month_budget_status

        _set_budget(db_path, user_id, "Food", 5000.0)
        _spend(db_path, user_id, 2000.0, "Food", when=date(2026, 8, 15))
        _spend(db_path, user_id, 500.0, "Food", when=date(2026, 9, 10))

        status = get_month_budget_status(user_id, today=date(2026, 9, 20))
        assert status["categories"][0]["spent"] == "₹500.00"

    def test_unbudgeted_categories_do_not_count(self, db_path, user_id):
        from database.queries import get_month_budget_status

        _set_budget(db_path, user_id, "Food", 5000.0)
        _spend(db_path, user_id, 500.0, "Food")
        _spend(db_path, user_id, 4000.0, "Shopping")

        status = get_month_budget_status(user_id)
        assert status["spent_total"] == "₹500.00"
        assert len(status["categories"]) == 1

    def test_event_spending_counts_toward_budgets(self, db_path, user_id):
        from database.queries import get_month_budget_status

        conn = _make_conn(db_path)
        event_id = conn.execute(
            "INSERT INTO events (user_id, name) VALUES (?, ?)", (user_id, "Trip")
        ).lastrowid
        conn.execute(
            "INSERT INTO expenses (user_id, event_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, event_id, 800.0, "Food", date.today().isoformat(), "Trip meal"),
        )
        conn.commit()
        conn.close()
        _set_budget(db_path, user_id, "Food", 5000.0)

        status = get_month_budget_status(user_id)
        assert status["spent_total"] == "₹800.00"


# ------------------------------------------------------------------ #
# Dashboard block                                                      #
# ------------------------------------------------------------------ #


class TestDashboardBudgets:
    def test_prompt_when_no_budgets(self, client):
        body = client.get("/profile").get_data(as_text=True)
        assert "Set a budget" in body

    def test_block_appears_once_budgets_exist(self, client, db_path, user_id):
        _set_budget(db_path, user_id, "Food", 6000.0)
        _spend(db_path, user_id, 1500.0, "Food")

        body = client.get("/profile").get_data(as_text=True)
        assert "Budgets ·" in body
        assert "safe to spend" in body
        assert "₹1,500.00 of ₹6,000.00" in body

    def test_over_budget_shows_warning_styling(self, client, db_path, user_id):
        _set_budget(db_path, user_id, "Food", 1000.0)
        _spend(db_path, user_id, 1500.0, "Food")

        body = client.get("/profile").get_data(as_text=True)
        assert "over budget" in body
        assert "meter-over" in body
