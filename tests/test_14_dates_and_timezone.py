"""
tests/test_14_dates_and_timezone.py

The app's idea of "today", and what it will accept as an expense date.

Covers:
  - timeutil: the configured zone, and what happens when it is nonsense
  - that every user-facing date follows the app's clock, not the server's
  - that a date in the future, or absurdly far in the past, is refused
  - that a stored date is always normalised YYYY-MM-DD, so the lexical
    comparisons every filter relies on keep working
"""

import sqlite3
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from werkzeug.security import generate_password_hash

import timeutil


def _make_conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    import database.db as db_module

    path = str(tmp_path / "test_dates.db")
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

    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret-dates")
    return app_module.app.test_client()


@pytest.fixture()
def user_id(db_path):
    conn = _make_conn(db_path)
    uid = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Test User", "dates@example.com", generate_password_hash("Password1")),
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


def _expenses(db_path, user_id):
    conn = _make_conn(db_path)
    rows = conn.execute(
        "SELECT * FROM expenses WHERE user_id = ? ORDER BY id", (user_id,)
    ).fetchall()
    conn.close()
    return rows


def _post(client, route, **overrides):
    data = {"amount": "100", "category": "Food", "date": timeutil.today().isoformat()}
    data.update(overrides)
    return client.post(route, data=data)


# ------------------------------------------------------------------ #
# The clock                                                           #
# ------------------------------------------------------------------ #


class TestAppClock:

    def test_defaults_to_india(self, monkeypatch):
        monkeypatch.delenv("APP_TIMEZONE", raising=False)
        assert timeutil.app_timezone() == ZoneInfo("Asia/Kolkata")

    def test_honours_app_timezone(self, monkeypatch):
        monkeypatch.setenv("APP_TIMEZONE", "America/New_York")
        assert timeutil.app_timezone() == ZoneInfo("America/New_York")

    def test_unresolvable_zone_falls_back_instead_of_raising(self, monkeypatch):
        """A typo in an env var must not take the whole app down."""
        monkeypatch.setenv("APP_TIMEZONE", "Not/AZone")
        assert timeutil.app_timezone().utcoffset(datetime(2026, 1, 1)) == timedelta(
            hours=5, minutes=30
        )

    def test_today_is_the_users_day_not_the_servers(self, monkeypatch):
        """The regression this exists for.

        22:00 UTC on the 19th is already 03:30 on the 20th in India. A server
        reading date.today() in UTC would date the expense to the 19th.
        """
        monkeypatch.delenv("APP_TIMEZONE", raising=False)
        instant = datetime(2026, 9, 19, 22, 0, tzinfo=timezone.utc)
        monkeypatch.setattr(
            timeutil, "now", lambda: instant.astimezone(timeutil.app_timezone())
        )
        assert timeutil.today() == date(2026, 9, 20)
        assert instant.date() == date(2026, 9, 19)  # what the old code would have used

    def test_now_is_timezone_aware(self):
        assert timeutil.now().tzinfo is not None


# ------------------------------------------------------------------ #
# Every user-facing date goes through that clock                      #
# ------------------------------------------------------------------ #


class TestRoutesUseTheAppClock:
    """Freeze the app's day and check each screen follows it."""

    FROZEN = date(2026, 3, 4)

    @pytest.fixture(autouse=True)
    def _freeze(self, monkeypatch):
        monkeypatch.setattr(timeutil, "today", lambda: self.FROZEN)

    def test_add_expense_form_prefills_it(self, client):
        body = client.get("/expenses/add").get_data(as_text=True)
        assert 'value="2026-03-04"' in body

    def test_quick_sheet_caps_the_date_at_it(self, client):
        body = client.get("/profile").get_data(as_text=True)
        assert 'max="2026-03-04"' in body

    def test_quick_page_prefills_it(self, client):
        body = client.get("/quick").get_data(as_text=True)
        assert 'value="2026-03-04"' in body

    def test_expenses_default_range_ends_on_it(self, client):
        body = client.get("/expenses").get_data(as_text=True)
        assert 'value="2026-03-04"' in body
        assert 'value="2026-03-01"' in body

    def test_this_month_preset_uses_it(self, client, db_path, user_id):
        conn = _make_conn(db_path)
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, 500.0, "Food", "2026-03-02", "In the frozen month"),
        )
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, 900.0, "Food", "2026-02-02", "The month before"),
        )
        conn.commit()
        conn.close()

        body = client.get("/profile?preset=this_month").get_data(as_text=True)
        assert "In the frozen month" in body
        assert "The month before" not in body


# ------------------------------------------------------------------ #
# What counts as an acceptable date                                   #
# ------------------------------------------------------------------ #


ROUTES = ["/expenses/add", "/quick"]


class TestDateBounds:

    @pytest.mark.parametrize("route", ROUTES)
    def test_today_is_accepted(self, client, db_path, user_id, route):
        resp = _post(client, route)
        assert resp.status_code == 302
        assert len(_expenses(db_path, user_id)) == 1

    @pytest.mark.parametrize("route", ROUTES)
    def test_tomorrow_is_refused(self, client, db_path, user_id, route):
        tomorrow = (timeutil.today() + timedelta(days=1)).isoformat()
        resp = _post(client, route, date=tomorrow)
        assert resp.status_code in (200, 400)
        assert "future" in resp.get_data(as_text=True)
        assert _expenses(db_path, user_id) == []

    @pytest.mark.parametrize("route", ROUTES)
    def test_absurdly_old_is_refused(self, client, db_path, user_id, route):
        resp = _post(client, route, date="2016-09-20")
        assert resp.status_code in (200, 400)
        assert "looks wrong" in resp.get_data(as_text=True)
        assert _expenses(db_path, user_id) == []

    def test_the_floor_is_inclusive(self, client, db_path, user_id):
        """A date exactly on the boundary still saves."""
        import app as app_module

        floor = timeutil.today() - timedelta(days=365 * app_module.MAX_BACKDATE_YEARS)
        resp = _post(client, "/quick", date=floor.isoformat())
        assert resp.status_code == 302
        assert len(_expenses(db_path, user_id)) == 1

    def test_editing_rejects_a_future_date_too(self, client, db_path, user_id):
        _post(client, "/quick")
        expense_id = _expenses(db_path, user_id)[0]["id"]
        tomorrow = (timeutil.today() + timedelta(days=1)).isoformat()

        resp = client.post(
            f"/expenses/{expense_id}/edit",
            data={"amount": "100", "category": "Food", "date": tomorrow},
        )
        assert "future" in resp.get_data(as_text=True)
        assert _expenses(db_path, user_id)[0]["date"] == timeutil.today().isoformat()

    @pytest.mark.parametrize("route", ROUTES)
    def test_a_refused_date_keeps_what_the_user_typed(self, client, route):
        """Re-typing an amount on a phone is the worst possible punishment."""
        tomorrow = (timeutil.today() + timedelta(days=1)).isoformat()
        body = _post(
            client, route, date=tomorrow, amount="777", description="Keep me"
        ).get_data(as_text=True)
        assert 'value="777"' in body
        assert "Keep me" in body


# ------------------------------------------------------------------ #
# Normalisation — the reason a raw string must never be stored        #
# ------------------------------------------------------------------ #


class TestDateNormalisation:

    def test_compact_form_is_normalised(self, client, db_path, user_id):
        """date.fromisoformat accepts "20260920"; the database must not."""
        today = timeutil.today()
        _post(client, "/quick", date=today.strftime("%Y%m%d"))
        assert _expenses(db_path, user_id)[0]["date"] == today.isoformat()

    def test_iso_week_form_is_normalised(self, client, db_path, user_id):
        """Python 3.11+ also accepts "2026-W38-7"."""
        _post(client, "/quick", date="2026-W38-7")
        rows = _expenses(db_path, user_id)
        assert len(rows) == 1
        assert rows[0]["date"] == "2026-09-20"

    def test_an_un_normalised_date_would_vanish_from_its_own_month(
        self, client, db_path, user_id
    ):
        """The payoff: the expense is still findable by a date filter.

        Stored raw, "20260920" sorts outside 2026-09-01..2026-09-30 under the
        lexical comparison every query uses, so the expense would disappear from
        every filtered view while still counting in the totals.
        """
        today = timeutil.today()
        _post(
            client,
            "/quick",
            date=today.strftime("%Y%m%d"),
            description="Findable expense",
        )
        first = today.replace(day=1).isoformat()
        body = client.get(f"/expenses?from={first}&to={today.isoformat()}").get_data(
            as_text=True
        )
        assert "Findable expense" in body


# ------------------------------------------------------------------ #
# The words on the quick-add date row                                 #
# ------------------------------------------------------------------ #


class TestDateLabel:

    def test_today_reads_as_today(self):
        from app import date_label

        assert date_label("2026-09-20", "2026-09-20") == "Dated today"

    def test_another_day_is_named(self):
        from app import date_label

        assert date_label("2026-09-19", "2026-09-20") == "Dated 19 Sep"

    def test_no_leading_zero_on_the_day(self):
        from app import date_label

        assert date_label("2026-09-05", "2026-09-20") == "Dated 5 Sep"

    def test_an_unparseable_value_is_passed_through(self):
        from app import date_label

        assert date_label("nonsense", "2026-09-20") == "Dated nonsense"

    def test_the_row_is_rendered_server_side(self, client, db_path, user_id):
        """So a browser with JavaScript blocked never sees a row that lies."""
        _post(client, "/quick")
        expense_id = _expenses(db_path, user_id)[0]["id"]
        yesterday = (timeutil.today() - timedelta(days=1)).isoformat()

        body = client.post(
            "/quick",
            data={"amount": "abc", "category": "Food", "date": yesterday},
        ).get_data(as_text=True)
        # The amount was rejected, so the form comes back — with the date it was
        # given, described in words rather than left saying "today".
        assert "Dated" in body
        assert "Dated today" not in body
        assert expense_id  # the earlier save is untouched
