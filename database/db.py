import sqlite3
from werkzeug.security import generate_password_hash


def get_db():
    conn = sqlite3.connect("expense_tracker.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _add_column_if_missing(conn, table, column, definition):
    """Add a column to an existing table only if it isn't there yet."""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = get_db()
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

    # Databases created before events existed need the column added in place.
    _add_column_if_missing(
        conn, "expenses", "event_id", "INTEGER REFERENCES events(id)"
    )

    conn.execute("CREATE INDEX IF NOT EXISTS idx_expenses_event ON expenses(event_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id)")

    conn.commit()
    conn.close()


def seed_db():
    conn = get_db()
    cursor = conn.cursor()

    count = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count > 0:
        conn.close()
        return

    cursor.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Demo User", "demo@bahikhata.com", generate_password_hash("demo123")),
    )
    user_id = cursor.lastrowid

    sample_expenses = [
        (user_id, 350.00, "Food", "2026-07-01", "Lunch at canteen"),
        (user_id, 80.00, "Transport", "2026-07-03", "Auto rickshaw"),
        (user_id, 1200.00, "Bills", "2026-07-05", "Electricity bill"),
        (user_id, 500.00, "Health", "2026-07-07", "Pharmacy"),
        (user_id, 650.00, "Entertainment", "2026-07-10", "Movie tickets"),
        (user_id, 2200.00, "Shopping", "2026-07-12", "Clothes"),
        (user_id, 420.00, "Food", "2026-07-14", "Dinner with friends"),
        (user_id, 300.00, "Other", "2026-07-14", "Miscellaneous"),
    ]

    cursor.executemany(
        "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
        sample_expenses,
    )

    conn.commit()
    conn.close()
