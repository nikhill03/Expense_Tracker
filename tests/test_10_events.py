"""
tests/test_10_events.py

Spec-driven pytest tests for Step 10: Events
(group expenses under a trip / festival / occasion).

Tests are written against the feature's expected behaviour, not its
implementation, so they stay valid if the routes are rewritten.

Routes under test:
    GET  /events                      — list the user's events
    GET  /events/new                  — event creation form
    POST /events/new                  — create an event
    GET  /events/<id>                 — event detail (spend vs budget)
    GET  /events/<id>/edit            — event edit form
    POST /events/<id>/edit            — update an event
    POST /events/<id>/delete          — delete the event, keep its expenses
Also covered: attaching expenses to an event and the dashboard's
"exclude event spending" toggle.
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


def _login(client, user_id, name="Test User"):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = name


def _add_event(
    path, user_id, name="Goa Trip", start="2026-09-20", end="2026-09-24", budget=15000.0
):
    conn = _make_conn(path)
    cur = conn.execute(
        "INSERT INTO events (user_id, name, start_date, end_date, budget)"
        " VALUES (?, ?, ?, ?, ?)",
        (user_id, name, start, end, budget),
    )
    conn.commit()
    event_id = cur.lastrowid
    conn.close()
    return event_id


def _add_expense(
    path,
    user_id,
    amount,
    category="Food",
    date="2026-09-21",
    description="Test expense",
    event_id=None,
):
    conn = _make_conn(path)
    cur = conn.execute(
        "INSERT INTO expenses (user_id, event_id, amount, category, date, description)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, event_id, amount, category, date, description),
    )
    conn.commit()
    expense_id = cur.lastrowid
    conn.close()
    return expense_id


# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #


@pytest.fixture()
def db_path(tmp_path):
    """Create a fresh temporary SQLite DB with the Bahi-Khata schema."""
    path = str(tmp_path / "test_events.db")
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
        CREATE TABLE IF NOT EXISTS events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL REFERENCES users(id),
            name       TEXT    NOT NULL,
            start_date TEXT,
            end_date   TEXT,
            budget     REAL,
            created_at TEXT    DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            event_id    INTEGER REFERENCES events(id),
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
    """Redirect every get_db() call to the isolated temp DB."""
    import database.db as db_module
    import database.queries as q_module
    import app as app_module  # import first — module-level init/seed hit the real DB

    def _get_db():
        return _make_conn(db_path)

    monkeypatch.setattr(db_module, "get_db", _get_db)
    monkeypatch.setattr(q_module, "get_db", _get_db)
    monkeypatch.setattr(app_module, "get_db", _get_db)

    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret-events")
    return app_module.app.test_client()


@pytest.fixture()
def users(db_path):
    """Two users: the owner and a stranger. Returns (owner_id, other_id)."""
    conn = _make_conn(db_path)
    owner = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Test User", "test@example.com", generate_password_hash("Password1")),
    ).lastrowid
    other = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Other User", "other@example.com", generate_password_hash("Password1")),
    ).lastrowid
    conn.commit()
    conn.close()
    return owner, other


@pytest.fixture()
def client_owner(patched_app, users):
    """Test client already signed in as the owner."""
    _login(patched_app, users[0])
    return patched_app


# ------------------------------------------------------------------ #
# Authentication                                                       #
# ------------------------------------------------------------------ #


class TestEventsRequireLogin:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/events"),
            ("get", "/events/new"),
            ("post", "/events/new"),
            ("get", "/events/1"),
            ("get", "/events/1/edit"),
            ("post", "/events/1/edit"),
            ("post", "/events/1/delete"),
        ],
    )
    def test_logged_out_redirects_to_login(self, patched_app, method, path):
        resp = getattr(patched_app, method)(path)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


# ------------------------------------------------------------------ #
# Creating events                                                      #
# ------------------------------------------------------------------ #


class TestCreateEvent:
    def test_new_event_form_renders(self, client_owner):
        resp = client_owner.get("/events/new")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert 'name="name"' in body
        assert 'name="budget"' in body

    def test_valid_event_is_saved(self, client_owner, db_path, users):
        resp = client_owner.post(
            "/events/new",
            data={
                "name": "Diwali",
                "start_date": "2026-11-01",
                "end_date": "2026-11-05",
                "budget": "8000",
            },
        )
        assert resp.status_code == 302

        conn = _make_conn(db_path)
        row = conn.execute("SELECT * FROM events WHERE name = 'Diwali'").fetchone()
        conn.close()
        assert row is not None
        assert row["user_id"] == users[0]
        assert row["start_date"] == "2026-11-01"
        assert row["budget"] == 8000.0

    def test_budget_and_dates_are_optional(self, client_owner, db_path):
        resp = client_owner.post("/events/new", data={"name": "Someday Trip"})
        assert resp.status_code == 302

        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT * FROM events WHERE name = 'Someday Trip'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["budget"] is None
        assert row["start_date"] is None

    @pytest.mark.parametrize(
        "data",
        [
            {"name": ""},
            {"name": "   "},
            {"name": "x" * 101},
            {"name": "Trip", "budget": "-50"},
            {"name": "Trip", "budget": "0"},
            {"name": "Trip", "budget": "abc"},
            {"name": "Trip", "start_date": "2026-09-25", "end_date": "2026-09-20"},
            {"name": "Trip", "start_date": "not-a-date"},
        ],
    )
    def test_invalid_input_is_rejected(self, client_owner, db_path, data):
        resp = client_owner.post("/events/new", data=data)
        assert resp.status_code == 200  # redisplayed form, not a redirect

        conn = _make_conn(db_path)
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.close()
        assert count == 0


# ------------------------------------------------------------------ #
# Listing and viewing                                                  #
# ------------------------------------------------------------------ #


class TestEventListAndDetail:
    def test_list_shows_only_own_events(self, client_owner, db_path, users):
        owner, other = users
        _add_event(db_path, owner, name="My Trip")
        _add_event(db_path, other, name="Their Trip")

        body = client_owner.get("/events").get_data(as_text=True)
        assert "My Trip" in body
        assert "Their Trip" not in body

    def test_detail_totals_and_budget(self, client_owner, db_path, users):
        owner, _ = users
        event_id = _add_event(db_path, owner, budget=15000.0)
        _add_expense(
            db_path, owner, 4500.0, "Transport", description="Flight", event_id=event_id
        )
        _add_expense(
            db_path, owner, 2800.0, "Food", description="Dinner", event_id=event_id
        )

        body = client_owner.get(f"/events/{event_id}").get_data(as_text=True)
        assert "₹7,300.00" in body  # spent
        assert "₹7,700.00" in body  # remaining of the 15,000 budget
        assert "Flight" in body and "Dinner" in body

    def test_detail_excludes_other_events_expenses(self, client_owner, db_path, users):
        owner, _ = users
        event_id = _add_event(db_path, owner)
        _add_expense(db_path, owner, 100.0, description="In event", event_id=event_id)
        _add_expense(db_path, owner, 200.0, description="Not in event")

        body = client_owner.get(f"/events/{event_id}").get_data(as_text=True)
        assert "In event" in body
        assert "Not in event" not in body

    def test_over_budget_event(self, client_owner, db_path, users):
        owner, _ = users
        event_id = _add_event(db_path, owner, budget=1000.0)
        _add_expense(db_path, owner, 1500.0, event_id=event_id)

        body = client_owner.get(f"/events/{event_id}").get_data(as_text=True)
        assert "₹1,500.00" in body
        assert "over" in body.lower()

    def test_missing_event_is_404(self, client_owner):
        assert client_owner.get("/events/999999").status_code == 404

    def test_other_users_event_is_403(self, patched_app, db_path, users):
        owner, other = users
        event_id = _add_event(db_path, owner)
        _login(patched_app, other, "Other User")

        assert patched_app.get(f"/events/{event_id}").status_code == 403
        assert patched_app.get(f"/events/{event_id}/edit").status_code == 403
        assert patched_app.post(f"/events/{event_id}/delete").status_code == 403


# ------------------------------------------------------------------ #
# Editing and deleting                                                 #
# ------------------------------------------------------------------ #


class TestEditEvent:
    def test_edit_updates_fields(self, client_owner, db_path, users):
        event_id = _add_event(db_path, users[0], name="Old Name", budget=15000.0)

        resp = client_owner.post(
            f"/events/{event_id}/edit",
            data={
                "name": "New Name",
                "start_date": "",
                "end_date": "",
                "budget": "500",
            },
        )
        assert resp.status_code == 302

        conn = _make_conn(db_path)
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        conn.close()
        assert row["name"] == "New Name"
        assert row["budget"] == 500.0
        assert row["start_date"] is None

    def test_invalid_edit_keeps_old_values(self, client_owner, db_path, users):
        event_id = _add_event(db_path, users[0], name="Keep Me")

        resp = client_owner.post(f"/events/{event_id}/edit", data={"name": ""})
        assert resp.status_code == 200

        conn = _make_conn(db_path)
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        conn.close()
        assert row["name"] == "Keep Me"


class TestDeleteEvent:
    def test_delete_removes_event_but_keeps_expenses(
        self, client_owner, db_path, users
    ):
        owner, _ = users
        event_id = _add_event(db_path, owner)
        expense_id = _add_expense(
            db_path, owner, 750.0, description="Kept", event_id=event_id
        )

        resp = client_owner.post(f"/events/{event_id}/delete")
        assert resp.status_code == 302

        conn = _make_conn(db_path)
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM events WHERE id = ?", (event_id,)
            ).fetchone()[0]
            == 0
        )
        expense = conn.execute(
            "SELECT * FROM expenses WHERE id = ?", (expense_id,)
        ).fetchone()
        conn.close()
        assert expense is not None
        assert expense["event_id"] is None


# ------------------------------------------------------------------ #
# Attaching expenses to events                                         #
# ------------------------------------------------------------------ #


class TestExpenseEventLink:
    def test_add_expense_with_event(self, client_owner, db_path, users):
        event_id = _add_event(db_path, users[0])

        resp = client_owner.post(
            "/expenses/add",
            data={
                "amount": "300",
                "category": "Food",
                "date": "2026-09-21",
                "description": "Tagged expense",
                "event_id": str(event_id),
            },
        )
        assert resp.status_code == 302

        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT event_id FROM expenses WHERE description = 'Tagged expense'"
        ).fetchone()
        conn.close()
        assert row["event_id"] == event_id

    def test_add_expense_without_event_stays_unlinked(self, client_owner, db_path):
        resp = client_owner.post(
            "/expenses/add",
            data={
                "amount": "300",
                "category": "Food",
                "date": "2026-09-21",
                "description": "Plain expense",
                "event_id": "",
            },
        )
        assert resp.status_code == 302

        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT event_id FROM expenses WHERE description = 'Plain expense'"
        ).fetchone()
        conn.close()
        assert row["event_id"] is None

    def test_cannot_attach_to_another_users_event(self, patched_app, db_path, users):
        owner, other = users
        event_id = _add_event(db_path, owner)
        _login(patched_app, other, "Other User")

        patched_app.post(
            "/expenses/add",
            data={
                "amount": "300",
                "category": "Food",
                "date": "2026-09-21",
                "description": "Sneaky expense",
                "event_id": str(event_id),
            },
        )

        conn = _make_conn(db_path)
        row = conn.execute(
            "SELECT event_id FROM expenses WHERE description = 'Sneaky expense'"
        ).fetchone()
        conn.close()
        assert row["event_id"] is None

    def test_edit_expense_can_change_and_clear_event(
        self, client_owner, db_path, users
    ):
        owner, _ = users
        event_id = _add_event(db_path, owner)
        expense_id = _add_expense(db_path, owner, 400.0, description="Movable")

        common = {
            "amount": "400",
            "category": "Food",
            "date": "2026-09-21",
            "description": "Movable",
        }
        client_owner.post(
            f"/expenses/{expense_id}/edit", data={**common, "event_id": str(event_id)}
        )
        conn = _make_conn(db_path)
        assert (
            conn.execute(
                "SELECT event_id FROM expenses WHERE id = ?", (expense_id,)
            ).fetchone()["event_id"]
            == event_id
        )
        conn.close()

        client_owner.post(
            f"/expenses/{expense_id}/edit", data={**common, "event_id": ""}
        )
        conn = _make_conn(db_path)
        assert (
            conn.execute(
                "SELECT event_id FROM expenses WHERE id = ?", (expense_id,)
            ).fetchone()["event_id"]
            is None
        )
        conn.close()


# ------------------------------------------------------------------ #
# Dashboard behaviour                                                  #
# ------------------------------------------------------------------ #


class TestDashboardEventFilter:
    @pytest.fixture()
    def seeded(self, db_path, users):
        owner, _ = users
        event_id = _add_event(db_path, owner, name="Goa Trip")
        _add_expense(db_path, owner, 1000.0, description="Everyday expense")
        _add_expense(
            db_path, owner, 2000.0, description="Event expense", event_id=event_id
        )
        return event_id

    def test_event_expenses_count_by_default(self, client_owner, seeded):
        body = client_owner.get("/profile?preset=all").get_data(as_text=True)
        assert "₹3,000.00" in body
        assert "Event expense" in body
        assert "Goa Trip" in body  # event chip on the row

    def test_exclude_toggle_drops_event_spending(self, client_owner, seeded):
        body = client_owner.get("/profile?preset=all&events=exclude").get_data(
            as_text=True
        )
        assert "₹1,000.00" in body
        assert "Event expense" not in body
        assert "Everyday expense" in body

    def test_expenses_page_shows_event_chip(self, client_owner, seeded):
        body = client_owner.get("/expenses?from=2026-09-01&to=2026-09-30").get_data(
            as_text=True
        )
        assert "Event expense" in body
        assert "Goa Trip" in body
