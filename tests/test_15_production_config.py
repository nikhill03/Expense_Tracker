"""Step 14 — the configuration that makes a public deployment safe.

Most of this is unit tests over resolve_config, which is a pure function of the
environment for exactly this reason. The three that are not cover the things a
dict comparison cannot prove: that the process really refuses to start, that a
real login really gets a lasting cookie, and that backups really land beside the
database rather than in the repo.
"""

import os
import subprocess
import sys
from datetime import timedelta

import pytest

import app as app_module
from app import DEV_SECRET_KEY, resolve_config

REAL_KEY = "3f9a-not-the-shipped-one-1d7c"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ------------------------------------------------------------------ #
# resolve_config                                                      #
# ------------------------------------------------------------------ #


def test_production_without_secret_key_raises():
    with pytest.raises(RuntimeError) as excinfo:
        resolve_config({"APP_ENV": "production"})
    assert "SECRET_KEY" in str(excinfo.value)


def test_production_with_the_shipped_dev_secret_raises():
    with pytest.raises(RuntimeError) as excinfo:
        resolve_config({"APP_ENV": "production", "SECRET_KEY": DEV_SECRET_KEY})
    assert "SECRET_KEY" in str(excinfo.value)


def test_production_with_a_real_secret_is_hardened():
    config = resolve_config({"APP_ENV": "production", "SECRET_KEY": REAL_KEY})

    assert config["IS_PRODUCTION"] is True
    assert config["SECRET_KEY"] == REAL_KEY
    assert config["SESSION_COOKIE_SECURE"] is True
    assert config["SESSION_COOKIE_HTTPONLY"] is True
    assert config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert config["PERMANENT_SESSION_LIFETIME"] == timedelta(days=90)


def test_empty_environment_is_development():
    config = resolve_config({})

    assert config["APP_ENV"] == "development"
    assert config["IS_PRODUCTION"] is False
    assert config["SECRET_KEY"] == DEV_SECRET_KEY
    # A Secure cookie on plain-HTTP localhost is dropped silently by the browser.
    assert config["SESSION_COOKIE_SECURE"] is False
    assert config["SESSION_COOKIE_HTTPONLY"] is True
    assert config["ALLOW_REGISTRATION"] is True


def test_app_env_is_case_and_space_insensitive():
    config = resolve_config({"APP_ENV": " Production ", "SECRET_KEY": REAL_KEY})
    assert config["IS_PRODUCTION"] is True


@pytest.mark.parametrize(
    "value,expected",
    [
        ("false", False),
        ("FALSE", False),
        (" false ", False),
        ("true", True),
        ("", True),
    ],
)
def test_allow_registration_flag(value, expected):
    config = resolve_config({"ALLOW_REGISTRATION": value})
    assert config["ALLOW_REGISTRATION"] is expected


# ------------------------------------------------------------------ #
# The real process                                                    #
# ------------------------------------------------------------------ #


def test_importing_the_app_in_production_without_a_secret_fails(tmp_path):
    """A misconfigured deploy must die, not serve requests with a public secret."""
    env = {
        **os.environ,
        "APP_ENV": "production",
        "DATABASE_PATH": str(tmp_path / "expense_tracker.db"),
    }
    env.pop("SECRET_KEY", None)

    result = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "SECRET_KEY" in result.stderr


def test_app_imports_with_no_environment_set():
    """pytest and `python app.py` must keep working with nothing configured."""
    env = {k: v for k, v in os.environ.items() if k not in {"APP_ENV", "SECRET_KEY"}}
    result = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


# ------------------------------------------------------------------ #
# Sessions and registration                                           #
# ------------------------------------------------------------------ #


@pytest.fixture()
def real_login_client(tmp_path, monkeypatch):
    """A client whose /login actually reaches a database, with one user in it.

    app.py calls get_db directly, so patching database.queries alone is not
    enough — the login lookup would miss and the test would pass for the wrong
    reason. Same shape as tests/test_11_hardening.py.
    """
    import sqlite3

    import app as app_module
    import database.db as db_module
    import database.queries as q_module
    from werkzeug.security import generate_password_hash

    path = str(tmp_path / "expense_tracker.db")
    monkeypatch.setattr(db_module, "DATABASE_PATH", path)
    db_module.init_db()

    def _get_db():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    monkeypatch.setattr(db_module, "get_db", _get_db)
    monkeypatch.setattr(q_module, "get_db", _get_db)
    monkeypatch.setattr(app_module, "get_db", _get_db)

    conn = _get_db()
    conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Test User", "test@example.com", generate_password_hash("Password1")),
    )
    conn.commit()
    conn.close()

    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret-production")
    return app_module.app.test_client()


def test_login_sets_a_lasting_cookie(real_login_client):
    response = real_login_client.post(
        "/login",
        data={"email": "test@example.com", "password": "Password1"},
        follow_redirects=False,
    )

    assert response.status_code == 302, "login did not succeed"

    cookie = response.headers.get("Set-Cookie", "")
    assert "session=" in cookie
    assert "HttpOnly" in cookie
    # session.permanent turns the session cookie into one with an expiry.
    assert "Expires=" in cookie


def test_registration_can_be_closed(client):
    app_module.app.config["ALLOW_REGISTRATION"] = False
    try:
        assert client.get("/register").status_code == 404
        assert client.post("/register", data={}).status_code == 404
        # And nothing offers a door that 404s.
        assert b"Create an account" not in client.get("/login").data
    finally:
        app_module.app.config["ALLOW_REGISTRATION"] = True


def test_registration_is_open_by_default(client):
    assert client.get("/register").status_code == 200


# ------------------------------------------------------------------ #
# Data on the volume                                                  #
# ------------------------------------------------------------------ #


def test_backups_land_beside_the_database(tmp_path, monkeypatch):
    """On Railway the database is at /data/..., so the snapshots must be too."""
    import database.db as db

    db_path = tmp_path / "expense_tracker.db"
    monkeypatch.setattr(db, "DATABASE_PATH", str(db_path))

    conn = db.get_db()
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()

    target = db.backup_db()

    assert target is not None
    assert os.path.dirname(target) == str(tmp_path / "backups")
    assert os.path.exists(target)
