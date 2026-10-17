"""
tests/test_api.py

Tests for Step 20: the JSON API, authenticated by a per-user token rather
than the session cookie, and the /account token management that creates and
revokes them.

Built for one thing — an automation (an iOS Shortcut, a script) logging an
expense without a page load — plus reading the list back. Not built: editing
or deleting an expense over the API, budgets, events.
"""

import re
import sqlite3

import pytest
from werkzeug.security import generate_password_hash


def _make_conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    """A temp database built by the app's own init_db, so the schema matches."""
    import database.db as db_module

    path = str(tmp_path / "test_api.db")
    monkeypatch.setattr(db_module, "DATABASE_PATH", path)
    db_module.init_db()
    return path


@pytest.fixture()
def patched_app(db_path, monkeypatch):
    import app as app_module
    import database.db as db_module
    import database.queries as q_module

    def _get_db():
        return _make_conn(db_path)

    monkeypatch.setattr(db_module, "get_db", _get_db)
    monkeypatch.setattr(q_module, "get_db", _get_db)
    monkeypatch.setattr(app_module, "get_db", _get_db)

    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret-api")
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
def other_user_id(db_path):
    conn = _make_conn(db_path)
    uid = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Other User", "other@example.com", generate_password_hash("Password1")),
    ).lastrowid
    conn.commit()
    conn.close()
    return uid


@pytest.fixture()
def client(patched_app, user_id):
    """A session-authenticated client, for the /account token-management routes."""
    with patched_app.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Test User"
    return patched_app


@pytest.fixture()
def api_token(patched_app, user_id):
    """A real, valid token — generated the same way the route does, without
    going through the route itself. The auth and expense tests below care
    whether a token works, not how /account happens to render one.

    Depends on patched_app (unused directly) rather than db_path, so that
    get_db is already monkeypatched onto the test database by the time this
    runs — _generate_api_token calls it internally."""
    import app as app_module

    return app_module._generate_api_token(user_id, "Test token")


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _extract_token(html):
    """Pull the raw bk_... value out of a rendered /account/tokens response."""
    match = re.search(r"bk_[\w-]+", html)
    assert match, "no token found in the response body"
    return match.group(0)


# ------------------------------------------------------------------ #
# Token management — /account/tokens                                  #
# ------------------------------------------------------------------ #


class TestTokenManagement:
    def test_create_requires_login(self, patched_app):
        resp = patched_app.post("/account/tokens", data={"name": "x"})
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_delete_requires_login(self, patched_app):
        resp = patched_app.post("/account/tokens/1/delete")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_creating_a_token_shows_the_raw_value_once(self, client):
        body = client.post(
            "/account/tokens", data={"name": "iPhone Shortcut"}
        ).get_data(as_text=True)

        assert "Token created" in body
        assert "bk_" in body

    def test_only_the_hash_is_stored(self, client, db_path, user_id):
        body = client.post("/account/tokens", data={"name": "x"}).get_data(as_text=True)
        raw_token = _extract_token(body)

        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT token_hash FROM api_tokens WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.close()

        assert raw_token not in row["token_hash"]
        assert len(row["token_hash"]) == 64  # a sha256 hex digest

    def test_a_fresh_get_does_not_show_the_token_again(self, client):
        client.post("/account/tokens", data={"name": "x"})
        body = client.get("/account").get_data(as_text=True)
        assert "Token created" not in body

    def test_blank_name_gets_a_default(self, client):
        body = client.post("/account/tokens", data={"name": "  "}).get_data(
            as_text=True
        )
        assert "Unnamed token" in body

    def test_token_list_shows_the_name(self, client):
        client.post("/account/tokens", data={"name": "Trip Shortcut"})
        body = client.get("/account").get_data(as_text=True)
        assert "Trip Shortcut" in body

    def test_revoking_removes_it(self, client, db_path, user_id):
        client.post("/account/tokens", data={"name": "x"})
        conn = _make_conn(db_path)
        token_id = conn.execute(
            "SELECT id FROM api_tokens WHERE user_id = ?", (user_id,)
        ).fetchone()["id"]
        conn.close()

        client.post(f"/account/tokens/{token_id}/delete")

        conn = _make_conn(db_path)
        remaining = conn.execute("SELECT COUNT(*) AS n FROM api_tokens").fetchone()
        conn.close()
        assert remaining["n"] == 0

    def test_cannot_revoke_another_users_token(
        self, client, db_path, user_id, other_user_id
    ):
        conn = _make_conn(db_path)
        token_id = conn.execute(
            "INSERT INTO api_tokens (user_id, name, token_hash)"
            " VALUES (?, 'theirs', 'x')",
            (other_user_id,),
        ).lastrowid
        conn.commit()
        conn.close()

        client.post(f"/account/tokens/{token_id}/delete")

        conn = _make_conn(db_path)
        still_there = conn.execute(
            "SELECT COUNT(*) AS n FROM api_tokens WHERE id = ?", (token_id,)
        ).fetchone()["n"]
        conn.close()
        assert still_there == 1


# ------------------------------------------------------------------ #
# Authentication                                                       #
# ------------------------------------------------------------------ #


class TestApiAuth:
    def test_missing_header_is_rejected(self, patched_app):
        resp = patched_app.get("/api/expenses")
        assert resp.status_code == 401
        assert "error" in resp.get_json()

    def test_malformed_header_is_rejected(self, patched_app):
        resp = patched_app.get(
            "/api/expenses", headers={"Authorization": "Token abc123"}
        )
        assert resp.status_code == 401

    def test_unknown_token_is_rejected(self, patched_app):
        resp = patched_app.get("/api/expenses", headers=_auth("bk_not-a-real-token"))
        assert resp.status_code == 401

    def test_valid_token_is_accepted(self, patched_app, api_token):
        resp = patched_app.get("/api/expenses", headers=_auth(api_token))
        assert resp.status_code == 200

    def test_a_revoked_token_stops_working(
        self, patched_app, api_token, db_path, user_id
    ):
        conn = _make_conn(db_path)
        conn.execute("DELETE FROM api_tokens WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

        resp = patched_app.get("/api/expenses", headers=_auth(api_token))
        assert resp.status_code == 401

    def test_last_used_at_is_recorded(self, patched_app, api_token, db_path, user_id):
        patched_app.get("/api/expenses", headers=_auth(api_token))

        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT last_used_at FROM api_tokens WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.close()
        assert row["last_used_at"] is not None

    def test_route_works_without_a_csrf_token(self, patched_app, api_token):
        """A Bearer-authenticated request carries no session cookie, so there
        is nothing for a CSRF token to protect — proves the exemption."""
        import app as app_module

        app_module.app.config["CSRF_ENABLED"] = True

        resp = patched_app.post(
            "/api/expenses",
            headers=_auth(api_token),
            json={"amount": 100, "category": "Food"},
        )
        assert resp.status_code == 201


# ------------------------------------------------------------------ #
# POST /api/expenses                                                   #
# ------------------------------------------------------------------ #


class TestCreateExpense:
    def test_creates_an_expense(self, patched_app, api_token, db_path, user_id):
        resp = patched_app.post(
            "/api/expenses",
            headers=_auth(api_token),
            json={"amount": 350, "category": "Food", "description": "Lunch"},
        )
        assert resp.status_code == 201

        data = resp.get_json()
        assert data["amount"] == 350.0
        assert data["category"] == "Food"
        assert data["description"] == "Lunch"

        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.close()
        assert row["amount"] == 350.0

    def test_amount_is_a_number_not_a_rupee_string(self, patched_app, api_token):
        resp = patched_app.post(
            "/api/expenses",
            headers=_auth(api_token),
            json={"amount": 350, "category": "Food"},
        )
        assert isinstance(resp.get_json()["amount"], float)

    def test_date_defaults_to_today(self, patched_app, api_token):
        import timeutil

        resp = patched_app.post(
            "/api/expenses",
            headers=_auth(api_token),
            json={"amount": 100, "category": "Food"},
        )
        assert resp.get_json()["date"] == timeutil.today().isoformat()

    def test_description_defaults_to_null(self, patched_app, api_token):
        resp = patched_app.post(
            "/api/expenses",
            headers=_auth(api_token),
            json={"amount": 100, "category": "Food"},
        )
        assert resp.get_json()["description"] is None

    def test_invalid_amount_is_rejected(self, patched_app, api_token):
        resp = patched_app.post(
            "/api/expenses",
            headers=_auth(api_token),
            json={"amount": "not a number", "category": "Food"},
        )
        assert resp.status_code == 400
        assert "error" in resp.get_json()

    def test_invalid_category_is_rejected(self, patched_app, api_token):
        resp = patched_app.post(
            "/api/expenses",
            headers=_auth(api_token),
            json={"amount": 100, "category": "Not A Real Category"},
        )
        assert resp.status_code == 400

    def test_future_date_is_rejected(self, patched_app, api_token):
        resp = patched_app.post(
            "/api/expenses",
            headers=_auth(api_token),
            json={"amount": 100, "category": "Food", "date": "2099-01-01"},
        )
        assert resp.status_code == 400

    def test_non_json_body_is_rejected(self, patched_app, api_token):
        resp = patched_app.post(
            "/api/expenses",
            headers=_auth(api_token),
            data="amount=100&category=Food",
        )
        assert resp.status_code == 400

    def test_event_id_belonging_to_another_user_is_rejected(
        self, patched_app, api_token, db_path, other_user_id
    ):
        conn = _make_conn(db_path)
        event_id = conn.execute(
            "INSERT INTO events (user_id, name) VALUES (?, 'Theirs')",
            (other_user_id,),
        ).lastrowid
        conn.commit()
        conn.close()

        resp = patched_app.post(
            "/api/expenses",
            headers=_auth(api_token),
            json={"amount": 100, "category": "Food", "event_id": event_id},
        )
        assert resp.status_code == 400

    def test_event_id_belonging_to_the_caller_is_accepted(
        self, patched_app, api_token, db_path, user_id
    ):
        conn = _make_conn(db_path)
        event_id = conn.execute(
            "INSERT INTO events (user_id, name) VALUES (?, 'Trip')", (user_id,)
        ).lastrowid
        conn.commit()
        conn.close()

        resp = patched_app.post(
            "/api/expenses",
            headers=_auth(api_token),
            json={"amount": 100, "category": "Food", "event_id": event_id},
        )
        assert resp.status_code == 201
        assert resp.get_json()["event_id"] == event_id


# ------------------------------------------------------------------ #
# GET /api/expenses                                                    #
# ------------------------------------------------------------------ #


class TestListExpenses:
    def test_returns_amounts_as_numbers(self, patched_app, api_token):
        patched_app.post(
            "/api/expenses",
            headers=_auth(api_token),
            json={"amount": 500, "category": "Food"},
        )
        data = patched_app.get("/api/expenses", headers=_auth(api_token)).get_json()
        assert isinstance(data["expenses"][0]["amount"], float)
        assert isinstance(data["total"], float)

    def test_only_returns_the_callers_own_expenses(
        self, patched_app, api_token, db_path, other_user_id
    ):
        import timeutil

        conn = _make_conn(db_path)
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, 999, 'Food', ?, 'not mine')",
            (other_user_id, timeutil.today().isoformat()),
        )
        conn.commit()
        conn.close()

        data = patched_app.get("/api/expenses", headers=_auth(api_token)).get_json()
        assert data["expenses"] == []

    def test_respects_explicit_date_range(self, patched_app, api_token):
        patched_app.post(
            "/api/expenses",
            headers=_auth(api_token),
            json={"amount": 100, "category": "Food", "date": "2026-01-15"},
        )
        data = patched_app.get(
            "/api/expenses?from=2026-01-01&to=2026-01-31", headers=_auth(api_token)
        ).get_json()
        assert len(data["expenses"]) == 1
        assert data["expenses"][0]["date"] == "2026-01-15"

    def test_includes_pagination(self, patched_app, api_token):
        data = patched_app.get("/api/expenses", headers=_auth(api_token)).get_json()
        assert "pagination" in data
        assert data["pagination"]["per_page"] == 100
