import os
import sqlite3

from werkzeug.security import generate_password_hash

import timeutil

DATABASE_PATH = os.environ.get("DATABASE_PATH", "expense_tracker.db")


def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Wait instead of failing when another request holds the write lock.
    conn.execute("PRAGMA busy_timeout = 5000")
    # Safe to relax under WAL: a crash can lose the last commit, never the file.
    conn.execute("PRAGMA synchronous = NORMAL")
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

        CREATE TABLE IF NOT EXISTS budgets (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL REFERENCES users(id),
            category       TEXT    NOT NULL,
            monthly_amount REAL    NOT NULL,
            updated_at     TEXT    DEFAULT (datetime('now')),
            UNIQUE(user_id, category)
        );

        CREATE TABLE IF NOT EXISTS login_attempts (
            email        TEXT PRIMARY KEY,
            failures     INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT
        );
    """
    )

    # Databases created before events existed need the column added in place.
    _add_column_if_missing(
        conn, "expenses", "event_id", "INTEGER REFERENCES events(id)"
    )

    # Readers stop blocking the writer. Persists in the database file.
    conn.execute("PRAGMA journal_mode = WAL")

    # Every dashboard and list query filters on user_id plus a date range, so
    # that pair carries the indexes. Event pages filter user_id and event_id.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_expenses_user_date ON expenses(user_id, date)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_expenses_user_event ON expenses(user_id, event_id)"
    )
    conn.execute("DROP INDEX IF EXISTS idx_expenses_event")
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


def backup_db(keep=7):
    """Write a consistent daily snapshot next to the database; keep the newest few.

    A volume protects against a redeploy, not against a bad DELETE, so this
    keeps a rolling set of copies. VACUUM INTO is safe on a live database.
    """
    backup_dir = os.path.join(
        os.path.dirname(os.path.abspath(DATABASE_PATH)), "backups"
    )
    os.makedirs(backup_dir, exist_ok=True)

    today = timeutil.today().isoformat()
    target = os.path.join(backup_dir, f"bahikhata-{today}.db")
    if os.path.exists(target):
        return None  # already taken today

    conn = get_db()
    try:
        conn.execute("VACUUM INTO ?", (target,))
    finally:
        conn.close()

    snapshots = sorted(
        f
        for f in os.listdir(backup_dir)
        if f.startswith("bahikhata-") and f.endswith(".db")
    )
    for stale in snapshots[:-keep]:
        os.remove(os.path.join(backup_dir, stale))

    return target
