import sqlite3
import pytest
from werkzeug.security import generate_password_hash


def _make_conn(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    conn = _make_conn(path)
    conn.executescript("""
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
    """)
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def patch_queries(db_path, monkeypatch):
    """Redirect database.queries.get_db to the temp test DB."""
    import database.queries as q

    def _get_db():
        return _make_conn(db_path)

    monkeypatch.setattr(q, "get_db", _get_db)
    return db_path


@pytest.fixture()
def seeded_db(patch_queries):
    """Insert one user + 3 expenses into the test DB; return (user_id, email, password)."""
    password = "Password1"
    conn = _make_conn(patch_queries)
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
        ("Test User", "test@example.com", generate_password_hash(password), "2026-01-15 10:00:00"),
    )
    user_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        [
            (user_id, 500.00,  "Food",       "2026-07-10", "Lunch"),
            (user_id, 1000.00, "Bills",      "2026-07-05", "Electric"),
            (user_id, 200.00,  "Transport",  "2026-07-01", "Bus pass"),
        ],
    )
    conn.commit()
    conn.close()
    return user_id, "test@example.com", password


@pytest.fixture()
def client():
    import app as app_module
    app_module.app.config.update(TESTING=True, SECRET_KEY="test-secret")
    return app_module.app.test_client()
