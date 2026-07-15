import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from database.db import get_db, init_db, seed_db

app = Flask(__name__)
app.secret_key = "dev-secret-change-me"

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("landing"))
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not name or not email or not password:
        return render_template("register.html", error="All fields are required", name=name, email=email)

    if len(password) < 8:
        return render_template("register.html", error="Password must be at least 8 characters", name=name, email=email)

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(password)),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return render_template("register.html", error="An account with that email already exists", name=name, email=email)
    finally:
        conn.close()

    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("landing"))
    if request.method == "GET":
        return render_template("login.html")

    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not email or not password:
        return render_template("login.html", error="All fields are required", email=email)

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if not user or not check_password_hash(user["password_hash"], password):
        return render_template("login.html", error="Invalid email or password", email=email)

    session.clear()
    session["user_id"]   = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("landing"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/profile")
def profile():
    if not session.get("user_id"):
        return redirect(url_for("login"))

    name = session.get("user_name", "User")
    initials = "".join(w[0].upper() for w in name.split()[:2])

    user = {
        "name": name,
        "email": "demo@spendly.com",
        "member_since": "2026-07-01",
        "initials": initials,
    }

    stats = {
        "total_spent": "₹5,700.00",
        "transaction_count": 8,
        "top_category": "Shopping",
    }

    transactions = [
        {"date": "2026-07-14", "description": "Dinner with friends", "category": "Food",          "amount": "₹420.00"},
        {"date": "2026-07-12", "description": "Clothes",              "category": "Shopping",      "amount": "₹2,200.00"},
        {"date": "2026-07-10", "description": "Movie tickets",        "category": "Entertainment", "amount": "₹650.00"},
        {"date": "2026-07-07", "description": "Pharmacy",             "category": "Health",        "amount": "₹500.00"},
        {"date": "2026-07-05", "description": "Electricity bill",     "category": "Bills",         "amount": "₹1,200.00"},
        {"date": "2026-07-03", "description": "Auto rickshaw",        "category": "Transport",     "amount": "₹80.00"},
        {"date": "2026-07-01", "description": "Lunch at canteen",     "category": "Food",          "amount": "₹350.00"},
        {"date": "2026-07-14", "description": "Miscellaneous",        "category": "Other",         "amount": "₹300.00"},
    ]

    categories = [
        {"name": "Shopping",      "amount": "₹2,200.00"},
        {"name": "Bills",         "amount": "₹1,200.00"},
        {"name": "Entertainment", "amount": "₹650.00"},
        {"name": "Food",          "amount": "₹770.00"},
        {"name": "Health",        "amount": "₹500.00"},
        {"name": "Other",         "amount": "₹300.00"},
        {"name": "Transport",     "amount": "₹80.00"},
    ]

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
    )


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
