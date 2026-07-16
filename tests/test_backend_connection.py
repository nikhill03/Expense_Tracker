import pytest
from database.queries import (
    get_user_by_id,
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
)


# ------------------------------------------------------------------ #
# get_user_by_id                                                      #
# ------------------------------------------------------------------ #

def test_get_user_by_id_valid(seeded_db):
    user_id, email, _ = seeded_db
    user = get_user_by_id(user_id)
    assert user["name"] == "Test User"
    assert user["email"] == email
    assert user["member_since"] == "January 2026"
    assert user["initials"] == "TU"


def test_get_user_by_id_not_found(patch_queries):
    assert get_user_by_id(99999) is None


# ------------------------------------------------------------------ #
# get_summary_stats                                                   #
# ------------------------------------------------------------------ #

def test_get_summary_stats_with_expenses(seeded_db):
    user_id, _, _ = seeded_db
    stats = get_summary_stats(user_id)
    assert stats["total_spent"] == "₹1,700.00"
    assert stats["transaction_count"] == 3
    assert stats["top_category"] == "Bills"


def test_get_summary_stats_no_expenses(patch_queries):
    # Insert a user with no expenses
    import sqlite3
    conn = sqlite3.connect(patch_queries)
    conn.row_factory = sqlite3.Row
    from werkzeug.security import generate_password_hash
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Empty User", "empty@example.com", generate_password_hash("pass1234")),
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()

    stats = get_summary_stats(user_id)
    assert stats["total_spent"] == "₹0.00"
    assert stats["transaction_count"] == 0
    assert stats["top_category"] == "—"


# ------------------------------------------------------------------ #
# get_recent_transactions                                             #
# ------------------------------------------------------------------ #

def test_get_recent_transactions_with_expenses(seeded_db):
    user_id, _, _ = seeded_db
    txs = get_recent_transactions(user_id)
    assert len(txs) == 3
    # Newest date first
    assert txs[0]["date"] == "2026-07-10"
    assert txs[-1]["date"] == "2026-07-01"
    # Amount formatted with ₹
    assert txs[0]["amount"] == "₹500.00"
    # Required keys present
    for tx in txs:
        assert all(k in tx for k in ("date", "description", "category", "amount"))


def test_get_recent_transactions_no_expenses(patch_queries):
    import sqlite3
    from werkzeug.security import generate_password_hash
    conn = sqlite3.connect(patch_queries)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Empty2", "empty2@example.com", generate_password_hash("pass1234")),
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()

    assert get_recent_transactions(user_id) == []


# ------------------------------------------------------------------ #
# get_category_breakdown                                              #
# ------------------------------------------------------------------ #

def test_get_category_breakdown_with_expenses(seeded_db):
    user_id, _, _ = seeded_db
    cats = get_category_breakdown(user_id)
    assert len(cats) == 3
    # Ordered by amount descending
    assert cats[0]["name"] == "Bills"
    assert cats[0]["amount"] == "₹1,000.00"
    # Percentages are integers and sum to 100
    assert all(isinstance(c["pct"], int) for c in cats)
    assert sum(c["pct"] for c in cats) == 100


def test_get_category_breakdown_no_expenses(patch_queries):
    import sqlite3
    from werkzeug.security import generate_password_hash
    conn = sqlite3.connect(patch_queries)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        ("Empty3", "empty3@example.com", generate_password_hash("pass1234")),
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()

    assert get_category_breakdown(user_id) == []


# ------------------------------------------------------------------ #
# Route: GET /profile                                                 #
# ------------------------------------------------------------------ #

def test_profile_unauthenticated(client):
    resp = client.get("/profile")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_profile_authenticated(client):
    # Log in as the seeded demo user
    client.post("/login", data={"email": "demo@spendly.com", "password": "demo123"})
    resp = client.get("/profile")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "Demo User" in body
    assert "demo@spendly.com" in body
    assert "₹" in body
