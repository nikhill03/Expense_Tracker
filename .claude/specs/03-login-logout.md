# Spec: Login and Logout

## Overview
Implement the POST handler for `/login` so users can authenticate into Spendly, and replace the `/logout` placeholder with a working route that clears the session. On successful login, `user_id` and `user_name` are stored in Flask's session so subsequent steps can gate access to protected pages. The navbar in `base.html` is updated to reflect authentication state — showing a "Sign out" link when a session exists and the current "Sign in"/"Get started" links when it does not.

## Depends on
- Step 1 — Database setup (`users` table must exist, `get_db()` must work)
- Step 2 — Registration (`app.secret_key` is set; a user row must exist to test login)

## Routes
- `POST /login` — process login form, authenticate user, start session — public
- `GET /logout` — clear session, redirect to `/login` — public

(The `GET /login` route already exists and renders the template; `GET /logout` placeholder exists and must be replaced.)

## Database changes
No database changes. The `users` table from Step 1 is sufficient.

## Templates
- **Modify:** `templates/login.html` — add `value="{{ email }}"` to the email input so it pre-fills on error; no other structural changes needed (the `{% if error %}` block is already present)
- **Modify:** `templates/base.html` — update the `nav-links` div to conditionally render:
  - When `session.user_id` is set: show a "Sign out" link pointing to `url_for('logout')`
  - When no session: show the existing "Sign in" and "Get started" links

## Files to change
- `app.py` — import `session` from flask; import `check_password_hash` from werkzeug.security; convert `/login` to accept `GET` and `POST`; implement POST logic; implement `/logout`
- `templates/login.html` — add `value="{{ email }}"` to email input
- `templates/base.html` — conditional navbar links based on session state

## Files to create
None.

## New dependencies
No new dependencies. `werkzeug.security` and `flask.session` are already available.

## Rules for implementation
- No SQLAlchemy or ORMs — raw SQL only
- Parameterised queries only — never use string formatting in SQL
- Verify passwords with `werkzeug.security.check_password_hash`
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- On login failure, re-render `login.html` with `error=` and `email=` — do not redirect
- Validation order: empty fields → wrong email or password (use a single vague message for both — never reveal which field was wrong)
- On success: set `session['user_id']` and `session['user_name']`, then redirect to `url_for('profile')`
- `/logout` must call `session.clear()` (not `session.pop()`), then redirect to `url_for('login')`
- The error message for bad credentials must be: `"Invalid email or password"` (do not distinguish which field failed)

## Definition of done
- [ ] Visiting `/login` (GET) still renders the form correctly
- [ ] Submitting the form with empty fields shows an error: `"All fields are required"`
- [ ] Submitting with a wrong email or wrong password shows: `"Invalid email or password"`
- [ ] On a login error, the email field is pre-filled with the submitted value
- [ ] Submitting valid credentials (e.g. demo@spendly.com / demo123) sets `session['user_id']` and redirects to `/profile`
- [ ] Visiting `/logout` clears the session and redirects to `/login`
- [ ] After logout, visiting `/profile` does not show a logged-in session (session is fully cleared)
- [ ] The navbar shows "Sign out" when a session is active and "Sign in"/"Get started" when it is not
- [ ] The app starts without errors (`python app.py`)
