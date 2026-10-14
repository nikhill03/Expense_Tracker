"""
tests/test_18_account.py

Tests for Step 18 (admin step, not in PHONE_PLAN.md's phone-feature numbering):
the /account route, where a signed-in user changes their own password.

Before this route existed, the only way to change a password was a one-off
script run by hand on the server — this closes that gap, and is also the
account's only self-service recovery path, since there is still no "forgot
password" flow.
"""

import sqlite3

import pytest
from werkzeug.security import check_password_hash, generate_password_hash


def _make_conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    """A temp database built by the app's own init_db, so the schema matches."""
    import database.db as db_module

    path = str(tmp_path / "test_account.db")
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

    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret-account")
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


def _current_hash(db_path, user_id):
    conn = _make_conn(db_path)
    row = conn.execute(
        "SELECT password_hash FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row["password_hash"]


class TestAccessControl:
    def test_get_redirects_when_logged_out(self, patched_app):
        resp = patched_app.get("/account")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_post_redirects_when_logged_out(self, patched_app):
        resp = patched_app.post(
            "/account",
            data={
                "current_password": "Password1",
                "new_password": "NewPassword1",
                "confirm_password": "NewPassword1",
            },
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


class TestAccountPage:
    def test_shows_name_and_email(self, client):
        body = client.get("/account").get_data(as_text=True)
        assert "Test User" in body
        assert "test@example.com" in body

    def test_has_a_csrf_token(self, client):
        """Every other POST form in the app carries one; this must too."""
        body = client.get("/account").get_data(as_text=True)
        assert 'name="csrf_token"' in body


class TestPasswordChange:
    def test_all_fields_required(self, client, db_path, user_id):
        original = _current_hash(db_path, user_id)

        resp = client.post("/account", data={})

        assert resp.status_code == 200
        assert "All fields are required" in resp.get_data(as_text=True)
        assert _current_hash(db_path, user_id) == original

    def test_wrong_current_password_is_rejected(self, client, db_path, user_id):
        original = _current_hash(db_path, user_id)

        resp = client.post(
            "/account",
            data={
                "current_password": "WrongPassword1",
                "new_password": "NewPassword1",
                "confirm_password": "NewPassword1",
            },
        )

        assert "Current password is incorrect" in resp.get_data(as_text=True)
        assert _current_hash(db_path, user_id) == original

    def test_new_password_too_short_is_rejected(self, client, db_path, user_id):
        original = _current_hash(db_path, user_id)

        resp = client.post(
            "/account",
            data={
                "current_password": "Password1",
                "new_password": "short1",
                "confirm_password": "short1",
            },
        )

        assert "at least 8 characters" in resp.get_data(as_text=True)
        assert _current_hash(db_path, user_id) == original

    def test_mismatched_confirmation_is_rejected(self, client, db_path, user_id):
        original = _current_hash(db_path, user_id)

        resp = client.post(
            "/account",
            data={
                "current_password": "Password1",
                "new_password": "NewPassword1",
                "confirm_password": "SomethingElse1",
            },
        )

        assert "do not match" in resp.get_data(as_text=True)
        assert _current_hash(db_path, user_id) == original

    def test_new_password_must_differ_from_current(self, client, db_path, user_id):
        """Letting this through would be a silent no-op dressed up as success."""
        original = _current_hash(db_path, user_id)

        resp = client.post(
            "/account",
            data={
                "current_password": "Password1",
                "new_password": "Password1",
                "confirm_password": "Password1",
            },
        )

        assert "must be different" in resp.get_data(as_text=True)
        assert _current_hash(db_path, user_id) == original

    def test_a_failed_submission_never_echoes_the_submitted_password(self, client):
        """Unlike name/email on the register form, there is nothing safe to
        repopulate here — the raw password must never round-trip into HTML."""
        body = client.post(
            "/account",
            data={
                "current_password": "Password1",
                "new_password": "UniqueMarkerPassword9",
                "confirm_password": "DoesNotMatch1",
            },
        ).get_data(as_text=True)

        assert "UniqueMarkerPassword9" not in body

    def test_valid_change_succeeds_and_redirects(self, client, db_path, user_id):
        resp = client.post(
            "/account",
            data={
                "current_password": "Password1",
                "new_password": "NewPassword1",
                "confirm_password": "NewPassword1",
            },
            follow_redirects=False,
        )

        assert resp.status_code == 302
        assert resp.headers["Location"] == "/account?saved=1"

        new_hash = _current_hash(db_path, user_id)
        assert check_password_hash(new_hash, "NewPassword1")
        assert not check_password_hash(new_hash, "Password1")

    def test_success_message_renders_after_the_redirect(self, client):
        client.post(
            "/account",
            data={
                "current_password": "Password1",
                "new_password": "NewPassword1",
                "confirm_password": "NewPassword1",
            },
        )

        body = client.get("/account?saved=1").get_data(as_text=True)
        assert "Password updated" in body

    def test_current_session_stays_signed_in_after_the_change(self, client):
        """A password hash has nothing to do with how the session cookie is
        signed, so changing one must not sign the user out of this device."""
        client.post(
            "/account",
            data={
                "current_password": "Password1",
                "new_password": "NewPassword1",
                "confirm_password": "NewPassword1",
            },
        )

        assert client.get("/profile").status_code == 200

    def test_old_password_no_longer_signs_in(self, client, patched_app):
        client.post(
            "/account",
            data={
                "current_password": "Password1",
                "new_password": "NewPassword1",
                "confirm_password": "NewPassword1",
            },
        )
        client.get("/logout")

        resp = patched_app.post(
            "/login", data={"email": "test@example.com", "password": "Password1"}
        )
        assert "Invalid email or password" in resp.get_data(as_text=True)

    def test_new_password_signs_in(self, client, patched_app):
        client.post(
            "/account",
            data={
                "current_password": "Password1",
                "new_password": "NewPassword1",
                "confirm_password": "NewPassword1",
            },
        )
        client.get("/logout")

        resp = patched_app.post(
            "/login",
            data={"email": "test@example.com", "password": "NewPassword1"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/login" not in resp.headers["Location"]
