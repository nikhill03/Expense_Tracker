# Spec: Registration

## Overview
Implement the POST handler for `/register` so users can create a Spendly account. The GET route and `register.html` template already exist; this step wires up form processing: validate inputs, reject duplicate emails, hash the password with werkzeug, insert the new user into the `users` table, and redirect to `/login` on success. Error messages are passed to the template via the `error` variable (not Flask flash). A `SECRET_KEY` is added to the app so Flask sessions are available for future steps.

## Depends on
- Step 1 — Database setup (`users` table must exist, `get_db()` must work)

## Routes
- `POST /register` — process registration form — public

(The `GET /register` route already exists and renders the form.)

## Database changes
No database changes. The `users` table with columns `id`, `name`, `email`, `password_hash`, `created_at` already exists from Step 1.

## Templates
- **Modify:** `templates/register.html` — add `value="{{ name }}"` and `value="{{ email }}"` to the name and email inputs so the form pre-fills on validation error; no other changes needed (the `{% if error %}` block is already present)

## Files to change
- `app.py` — add `SECRET_KEY`; import `request`, `redirect`; convert `/register` to accept `GET` and `POST`; implement POST logic

## Files to create
None.

## New dependencies
No new dependencies. `werkzeug.security` is already installed.

## Rules for implementation
- No SQLAlchemy or ORMs — raw SQL only
- Parameterised queries only — never use string formatting in SQL
- Hash passwords with `werkzeug.security.generate_password_hash`
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Re-render the form (do not redirect) on validation failure, passing `error=`, `name=`, and `email=` so the user doesn't retype everything
- On success, redirect to `url_for('login')` — do **not** set a session in this step; session management comes in a later step
- Validation order: empty fields first → password too short → duplicate email
- Minimum password length: 8 characters
- `SECRET_KEY` value: any hard-coded string is fine for now (e.g. `"dev-secret-change-me"`) — this is a dev scaffold

## Definition of done
- [ ] Visiting `/register` (GET) still renders the form correctly
- [ ] Submitting the form with all fields blank shows an error: "All fields are required"
- [ ] Submitting with a password shorter than 8 characters shows an error: "Password must be at least 8 characters"
- [ ] Submitting a duplicate email shows an error: "An account with that email already exists"
- [ ] On a validation error, the name and email fields are pre-filled with the submitted values
- [ ] Submitting valid data inserts a row into the `users` table with a hashed (not plain-text) password
- [ ] After successful registration, the user is redirected to `/login`
- [ ] The app starts without errors (`python app.py`)
