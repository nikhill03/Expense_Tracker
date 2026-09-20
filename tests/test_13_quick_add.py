"""
tests/test_13_quick_add.py

Spec-driven tests for Step 15: the mobile quick-add screen.

Routes under test:
    GET  /quick — the thumb-sized add form, optionally prefilled from a link
    POST /quick — save the expense and return where the user came from

Also covered: parse_amount_from_text(), which reads an amount out of a bank
debit SMS, and the rule that a prefill link never writes anything by itself.
"""

import re
import sqlite3
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

    path = str(tmp_path / "test_quick.db")
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

    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret-quick")
    return app_module.app.test_client()


@pytest.fixture()
def user_id(db_path):
    conn = _make_conn(db_path)
    uid = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Test User", "quick@example.com", generate_password_hash("Password1")),
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


def _checked_categories(body):
    """The category values whose radio rendered as checked."""
    return {
        m.group(1)
        for m in re.finditer(
            r'<input[^>]*name="category"[^>]*value="([^"]+)"[^>]*\bchecked\b', body
        )
    }


def _add_event(db_path, user_id, name="Goa Trip", start=None, end=None):
    conn = _make_conn(db_path)
    event_id = conn.execute(
        "INSERT INTO events (user_id, name, start_date, end_date) VALUES (?, ?, ?, ?)",
        (user_id, name, start, end),
    ).lastrowid
    conn.commit()
    conn.close()
    return event_id


def _selected_event(body):
    """The event id the sheet's picker came back with selected, or None."""
    sheet = body[body.index('id="quick-sheet"'):]
    match = re.search(r'<option value="(\d+)"[^>]*\bselected\b', sheet)
    return int(match.group(1)) if match else None


def _today():
    return date.today().isoformat()


# ------------------------------------------------------------------ #
# Reading an amount out of a bank message                             #
# ------------------------------------------------------------------ #


class TestParseAmountFromText:
    """The parser is what makes a shared debit SMS useful."""

    @pytest.mark.parametrize(
        "message, expected",
        [
            ("Rs.350.00 debited from A/c XX4417", 350.0),
            ("Rs 350 debited", 350.0),
            ("INR 1,234.56 debited to SWIGGY", 1234.56),
            ("₹350 spent on your card", 350.0),
            ("Your a/c is debited by 350.0 on 20-09-26", 350.0),
            ("Amount of INR 99 debited via UPI", 99.0),
        ],
    )
    def test_reads_common_bank_wordings(self, message, expected):
        from app import parse_amount_from_text

        assert parse_amount_from_text(message) == expected

    @pytest.mark.parametrize(
        "message",
        [
            "",
            None,
            "Your OTP is 4417. Do not share it.",
            "A/c XX4417 balance enquiry on 20-09-26",
        ],
    )
    def test_returns_none_when_there_is_no_amount(self, message):
        """An account number or an OTP is not an amount."""
        from app import parse_amount_from_text

        assert parse_amount_from_text(message) is None

    def test_prefers_the_currency_marked_figure(self):
        """The date and the account number must not win over the amount."""
        from app import parse_amount_from_text

        message = "On 20-09-2026 A/c XX4417 debited by Rs.75.50 at BLINKIT"
        assert parse_amount_from_text(message) == 75.50

    def test_names_the_sender_when_it_recognises_one(self):
        from app import parse_source_from_text

        assert parse_source_from_text("Rs.340 debited via UPI") == "UPI alert"
        assert parse_source_from_text("SBI: Rs.340 debited") == "SBI alert"
        assert parse_source_from_text("Rs.340 debited somewhere") is None


# ------------------------------------------------------------------ #
# Access                                                              #
# ------------------------------------------------------------------ #


class TestQuickAddAccess:

    def test_logged_out_get_redirects_to_login(self, patched_app):
        resp = patched_app.get("/quick")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_logged_out_redirect_remembers_where_to_come_back_to(self, patched_app):
        """A back-tap while signed out must not lose the amount."""
        resp = patched_app.get("/quick?amount=350")
        assert "next=" in resp.headers["Location"]

    def test_logged_out_post_does_not_save(self, patched_app, db_path, user_id):
        resp = patched_app.post(
            "/quick",
            data={"amount": "350", "category": "Food", "date": _today()},
        )
        assert resp.status_code == 302
        assert _expenses(db_path, user_id) == []

    def test_logged_in_get_returns_the_form(self, client):
        resp = client.get("/quick")
        assert resp.status_code == 200
        assert b'name="amount"' in resp.data
        assert b'name="category"' in resp.data


# ------------------------------------------------------------------ #
# Prefilling from a link                                              #
# ------------------------------------------------------------------ #


class TestQuickAddPrefill:

    def test_explicit_amount_is_prefilled(self, client):
        body = client.get("/quick?amount=350").get_data(as_text=True)
        assert 'value="350"' in body

    def test_amount_is_read_out_of_shared_message_text(self, client):
        body = client.get(
            "/quick?text=Rs.340.00+debited+from+A%2Fc+XX4417+to+SWIGGY+via+UPI"
        ).get_data(as_text=True)
        assert 'value="340"' in body

    def test_recognised_sender_is_shown_to_the_user(self, client):
        body = client.get("/quick?text=Rs.340+debited+via+UPI").get_data(as_text=True)
        assert "UPI alert" in body

    def test_known_category_is_preselected(self, client):
        body = client.get("/quick?amount=350&category=Food").get_data(as_text=True)
        assert _checked_categories(body) == {"Food"}

    def test_unknown_category_is_ignored(self, client):
        """A crafted link must not smuggle a category past the allowed list."""
        body = client.get("/quick?amount=350&category=Crypto").get_data(as_text=True)
        assert _checked_categories(body) == set()

    def test_category_from_a_link_is_escaped(self, client):
        body = client.get(
            "/quick?amount=350&remark=%3Cscript%3Ealert(1)%3C%2Fscript%3E"
        ).get_data(as_text=True)
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;" in body

    def test_a_prefill_link_saves_nothing_on_its_own(self, client, db_path, user_id):
        """The whole safety story: GET never writes."""
        client.get("/quick?amount=350&category=Food&remark=Swiggy")
        assert _expenses(db_path, user_id) == []


# ------------------------------------------------------------------ #
# Saving                                                              #
# ------------------------------------------------------------------ #


class TestQuickAddSave:

    def test_valid_post_saves_the_expense(self, client, db_path, user_id):
        client.post(
            "/quick",
            data={
                "amount": "340.50",
                "category": "Food",
                "date": _today(),
                "description": "Swiggy",
            },
        )
        rows = _expenses(db_path, user_id)
        assert len(rows) == 1
        assert rows[0]["amount"] == 340.50
        assert rows[0]["category"] == "Food"
        assert rows[0]["description"] == "Swiggy"

    def test_save_from_the_page_returns_to_quick_add_with_a_confirmation(self, client):
        resp = client.post(
            "/quick",
            data={"amount": "340", "category": "Food", "date": _today()},
        )
        assert resp.status_code == 302
        assert "/quick" in resp.headers["Location"]
        assert "saved=" in resp.headers["Location"]

    def test_confirmation_names_what_was_saved(self, client):
        resp = client.post(
            "/quick",
            data={"amount": "340", "category": "Food", "date": _today()},
            follow_redirects=True,
        )
        body = resp.get_data(as_text=True)
        assert "Saved" in body
        assert "340" in body

    def test_save_from_the_sheet_returns_to_the_page_it_was_opened_from(self, client):
        """The sheet is available everywhere, so it must not hijack navigation."""
        resp = client.post(
            "/quick",
            data={
                "amount": "340",
                "category": "Food",
                "date": _today(),
                "next": "/events",
            },
        )
        assert resp.headers["Location"] == "/events"

    def test_offsite_next_is_refused(self, client):
        """A redirect target has to be a path on this site."""
        resp = client.post(
            "/quick",
            data={
                "amount": "340",
                "category": "Food",
                "date": _today(),
                "next": "https://evil.example.com/",
            },
        )
        assert "evil.example.com" not in resp.headers["Location"]

    def test_protocol_relative_next_is_refused(self, client):
        resp = client.post(
            "/quick",
            data={
                "amount": "340",
                "category": "Food",
                "date": _today(),
                "next": "//evil.example.com/",
            },
        )
        assert not resp.headers["Location"].startswith("//")


# ------------------------------------------------------------------ #
# Validation                                                          #
# ------------------------------------------------------------------ #


class TestQuickAddValidation:

    @pytest.mark.parametrize("amount", ["", "0", "-5", "abc"])
    def test_bad_amount_is_rejected(self, client, db_path, user_id, amount):
        resp = client.post(
            "/quick",
            data={"amount": amount, "category": "Food", "date": _today()},
        )
        assert resp.status_code == 400
        assert "Amount must be a positive number" in resp.get_data(as_text=True)
        assert _expenses(db_path, user_id) == []

    def test_category_outside_the_list_is_rejected(self, client, db_path, user_id):
        resp = client.post(
            "/quick",
            data={"amount": "100", "category": "Crypto", "date": _today()},
        )
        assert resp.status_code == 400
        assert _expenses(db_path, user_id) == []

    def test_rejected_post_keeps_what_the_user_typed(self, client):
        """Re-typing an amount on a phone is the worst possible punishment."""
        body = client.post(
            "/quick",
            data={
                "amount": "100",
                "category": "Crypto",
                "date": _today(),
                "description": "Bought something",
            },
        ).get_data(as_text=True)
        assert 'value="100"' in body
        assert "Bought something" in body

    def test_expense_belongs_to_the_signed_in_user(self, client, db_path, user_id):
        client.post(
            "/quick",
            data={"amount": "50", "category": "Other", "date": _today()},
        )
        rows = _expenses(db_path, user_id)
        assert rows[0]["user_id"] == user_id

    def test_event_belonging_to_another_user_is_dropped(self, client, db_path, user_id):
        """A posted event id is only honoured if the event is yours."""
        conn = _make_conn(db_path)
        other = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Other", "other@example.com", "x"),
        ).lastrowid
        their_event = conn.execute(
            "INSERT INTO events (user_id, name) VALUES (?, ?)", (other, "Their trip")
        ).lastrowid
        conn.commit()
        conn.close()

        client.post(
            "/quick",
            data={
                "amount": "50",
                "category": "Other",
                "date": _today(),
                "event_id": str(their_event),
            },
        )
        assert _expenses(db_path, user_id)[0]["event_id"] is None


# ------------------------------------------------------------------ #
# The sheet on every page                                             #
# ------------------------------------------------------------------ #


class TestQuickSheet:

    @pytest.mark.parametrize("path", ["/profile", "/expenses", "/events", "/budgets"])
    def test_sheet_is_reachable_from_every_signed_in_page(self, client, path):
        body = client.get(path).get_data(as_text=True)
        assert 'popovertarget="quick-sheet"' in body
        assert 'id="quick-sheet"' in body

    def test_quick_page_does_not_render_the_sheet_as_well(self, client):
        """/quick already is the form; a second copy would duplicate field ids."""
        body = client.get("/quick").get_data(as_text=True)
        assert 'id="quick-sheet"' not in body

    def test_sheet_is_not_offered_to_signed_out_visitors(self, patched_app):
        body = patched_app.get("/").get_data(as_text=True)
        assert 'id="quick-sheet"' not in body

    @pytest.mark.parametrize("path", ["/profile", "/expenses", "/events", "/budgets"])
    def test_sheet_always_offers_the_real_category_list(self, client, path):
        """Guards against a page variable shadowing the sheet's own context.

        /profile and the event page both pass a `categories` breakdown of their
        own; if the sheet read that instead of the fixed list, its chips would
        render stringified rows and every save would fail validation.
        """
        from app import EXPENSE_CATEGORIES

        body = client.get(path).get_data(as_text=True)
        sheet = body[body.index('id="quick-sheet"'):]
        values = re.findall(r'<input[^>]*name="category"[^>]*value="([^"]*)"', sheet)
        assert values == EXPENSE_CATEGORIES

    def test_event_page_sheet_is_unaffected_by_its_own_breakdown(self, client, db_path, user_id):
        from app import EXPENSE_CATEGORIES

        conn = _make_conn(db_path)
        event_id = conn.execute(
            "INSERT INTO events (user_id, name) VALUES (?, ?)", (user_id, "Goa trip")
        ).lastrowid
        conn.commit()
        conn.close()

        body = client.get(f"/events/{event_id}").get_data(as_text=True)
        sheet = body[body.index('id="quick-sheet"'):]
        values = re.findall(r'<input[^>]*name="category"[^>]*value="([^"]*)"', sheet)
        assert values == EXPENSE_CATEGORIES


# ------------------------------------------------------------------ #
# Attaching to an event from the sheet                                #
# ------------------------------------------------------------------ #


class TestSheetEventPicker:
    """The sheet has to be able to say "this belongs to Goa Trip".

    Opening it from an event page is the case that matters: you are looking at
    the trip, so that is almost certainly what the expense is for.
    """

    def test_picker_appears_once_the_user_has_an_event(self, client, db_path, user_id):
        _add_event(db_path, user_id)
        body = client.get("/profile").get_data(as_text=True)
        sheet = body[body.index('id="quick-sheet"'):]
        assert 'name="event_id"' in sheet
        assert "Goa Trip" in sheet

    def test_no_picker_when_there_are_no_events(self, client):
        """Nothing to pick, so the row would be dead weight."""
        body = client.get("/profile").get_data(as_text=True)
        sheet = body[body.index('id="quick-sheet"'):]
        assert 'name="event_id"' not in sheet

    def test_attaching_stays_optional(self, client, db_path, user_id):
        _add_event(db_path, user_id)
        body = client.get("/profile").get_data(as_text=True)
        sheet = body[body.index('id="quick-sheet"'):]
        assert "Not part of an event" in sheet

    @pytest.mark.parametrize("path", ["/events/{id}", "/events/{id}/edit"])
    def test_event_page_preselects_its_own_event(
        self, client, db_path, user_id, path
    ):
        event_id = _add_event(db_path, user_id)
        body = client.get(path.format(id=event_id)).get_data(as_text=True)
        assert _selected_event(body) == event_id

    def test_add_expense_link_preselects_in_the_sheet_too(
        self, client, db_path, user_id
    ):
        event_id = _add_event(db_path, user_id)
        body = client.get(f"/expenses/add?event={event_id}").get_data(as_text=True)
        assert _selected_event(body) == event_id

    def test_ordinary_pages_preselect_nothing(self, client, db_path, user_id):
        _add_event(db_path, user_id)
        for path in ("/profile", "/expenses", "/budgets"):
            body = client.get(path).get_data(as_text=True)
            assert _selected_event(body) is None, path

    def test_saving_from_an_event_page_attaches_to_it(self, client, db_path, user_id):
        event_id = _add_event(db_path, user_id)
        client.post(
            "/quick",
            data={
                "amount": "340",
                "category": "Food",
                "date": _today(),
                "event_id": str(event_id),
                "next": f"/events/{event_id}",
            },
        )
        assert _expenses(db_path, user_id)[0]["event_id"] == event_id

    def test_a_deliberate_no_event_survives_a_rejected_form(
        self, client, db_path, user_id
    ):
        """Choosing "no event" must not snap back to the page's default."""
        _add_event(db_path, user_id)
        body = client.post(
            "/quick",
            data={"amount": "bad", "category": "Food", "date": _today(), "event_id": ""},
        ).get_data(as_text=True)
        assert re.search(r'<option value="\d+"[^>]*\bselected\b', body) is None

    def test_a_chosen_event_survives_a_rejected_form(self, client, db_path, user_id):
        event_id = _add_event(db_path, user_id)
        body = client.post(
            "/quick",
            data={
                "amount": "bad",
                "category": "Food",
                "date": _today(),
                "event_id": str(event_id),
            },
        ).get_data(as_text=True)
        assert f'<option value="{event_id}" selected' in body

    def test_another_users_event_is_never_offered(self, client, db_path, user_id):
        conn = _make_conn(db_path)
        other = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Other", "other-picker@example.com", "x"),
        ).lastrowid
        conn.commit()
        conn.close()
        _add_event(db_path, other, name="Their Secret Trip")

        body = client.get("/profile").get_data(as_text=True)
        assert "Their Secret Trip" not in body

    def test_an_expense_outside_the_event_dates_saves_silently(
        self, client, db_path, user_id
    ):
        """A recorded decision, not an oversight.

        Flights and hotels are booked weeks before a trip and that spend belongs
        to the trip's budget, so no warning and no check.
        """
        from datetime import date, timedelta

        start = (date.fromisoformat(_today()) + timedelta(days=10)).isoformat()
        end = (date.fromisoformat(_today()) + timedelta(days=14)).isoformat()
        event_id = _add_event(db_path, user_id, start=start, end=end)

        resp = client.post(
            "/quick",
            data={
                "amount": "9000",
                "category": "Transport",
                "date": _today(),
                "event_id": str(event_id),
                "description": "Flights, booked early",
            },
        )
        assert resp.status_code == 302
        row = _expenses(db_path, user_id)[0]
        assert row["event_id"] == event_id
        assert row["date"] == _today()
