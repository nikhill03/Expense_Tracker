# Phone Plan — Using Bahi-Khata Day-to-Day on a Phone

## 1. Goal

**What:** Double-tap the back of the phone → Bahi-Khata quick-add screen pops up → enter **type, amount, remark** →
Save → later open a **dashboard** that shows which categories take most of the money.

**Who / which phones:** Primary device is a **Samsung Galaxy S24+**, but it must also work on **iPhone, Pixel and
other Android phones**.

### Chosen approach: Progressive Web App (PWA)

| Option | Works on | Cost / effort | Verdict |
|---|---|---|---|
| Native app (Kotlin / Swift / Flutter) | One platform per build (Flutter: both) | High — new codebase, store publishing | ❌ Overkill |
| iOS Shortcut with native prompts + API | iPhone only | Medium | ➕ Optional extra (Step 20) |
| **PWA — installable web app on top of the existing Flask app** | **All phones** | **Low — reuse current code** | ✅ **Chosen** |

**Why PWA:** one codebase (the Flask app we already have), free, installs to the home screen like a real app, opens
full-screen, and every phone's back-tap feature can launch it.

---

## 2. Current Status (as of 2026-09-20)

### Already built
- Register / login / logout (`app.py`)
- Profile dashboard: total spent, transaction count, top category, category breakdown, recent transactions
  (`get_summary_stats`, `get_category_breakdown`, `get_recent_transactions` in `database/queries.py`)
- Date filters: This Month / Last 3 / Last 6 months / custom range
- Add / edit / delete expense, with shared validation in `_parse_expense_form` (`app.py`)
- Fixed category list `EXPENSE_CATEGORIES`: Food, Transport, Bills, Health, Entertainment, Shopping, Other
- Railway deployment config (`Procfile` → gunicorn)
- Events (Step 10): group expenses under a trip/festival with dates and a budget

### Blockers for real daily use

| # | Problem | Why it matters on a phone |
|---|---|---|
| 1 | SQLite file `expense_tracker.db` lives on Railway's temporary disk; path is hardcoded in `get_db()` | **All expenses are wiped on every redeploy** |
| 2 | `app.secret_key = "dev-secret-change-me"` is hardcoded | Anyone reading the repo can forge a login session |
| 3 | Session is not permanent | Logged out whenever the browser/app closes → breaks "tap and type" |
| 4 | `seed_db()` always creates `demo@bahikhata.com / demo123` | A known login exists on the public site |
| 5 | No mobile-first entry page, no manifest, no service worker; `static/js/main.js` is empty | Can't install as an app; forms are desktop-sized |

---

## 3. Step-by-Step Plan

Steps continue from the existing specs `01`–`12` (Step 11 was performance and hardening,
Step 12 monthly budgets), so each one can become `.claude/specs/1x-*.md` via
`/create-spec` and get its own `feature/*` branch and PR.

### Step 13 — Production-ready hosting (must do first)
**What**
- `database/db.py` → `get_db()` reads the path from env var `DATABASE_PATH` (default `expense_tracker.db` locally).
- Railway: add a **Volume** mounted at `/data`, set `DATABASE_PATH=/data/expense_tracker.db`.
- `app.py`: `app.secret_key = os.environ["SECRET_KEY"]` (fallback only in development).
- Only call `seed_db()` when `FLASK_ENV=development`.
- Confirm the Railway public URL is **HTTPS** (a PWA requires it; Railway provides it by default).

**Files:** `database/db.py`, `app.py`, Railway dashboard settings
**Done when:** an expense added on the phone is still there after a redeploy.

### Step 14 — Stay logged in
**What**
- In `login()`: `session.permanent = True`.
- Config: `PERMANENT_SESSION_LIFETIME = timedelta(days=90)`, `SESSION_COOKIE_SECURE=True`,
  `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE="Lax"`.
- Support `?next=/quick` on login so a logged-out back-tap returns to quick-add after sign-in.

**Files:** `app.py`, `templates/login.html`
**Done when:** closing and reopening the app on the phone keeps you signed in.

### Step 15 — Mobile quick-add page (`/quick`)
**What:** a single-purpose, thumb-friendly screen.
- **Amount** — large input, `inputmode="decimal"`, autofocus → number keypad opens immediately.
- **Type** — categories as big tappable chips (from `EXPENSE_CATEGORIES`), not a dropdown.
- **Remark** — one-line text field (max 255 chars).
- **Event** — optional picker, shown only when the user has events (Step 10).
- **Prefill from a link**: `/quick?amount=350&remark=SBI%20UPI&category=Food` opens the form already filled,
  so an automation or a share can hand it the amount. New `parse_amount_from_text()` helper reads `₹350`,
  `Rs 350.00`, `INR 350` and `debited by 350.0`. Nothing is saved until Save is tapped, so a crafted link
  cannot write anything on its own.
- **Date** — hidden, defaults to today, small "change date" link.
- **Save** → flash "Saved ₹350 to Food" → form resets for the next entry, with a "View dashboard" link.
- Reuse `_parse_expense_form` for validation and the same `INSERT` as `add_expense()`.

**Files:** `app.py` (new route), `templates/quick_add.html` (new), `static/css/style.css`
**Done when:** logging an expense takes **under 10 seconds** from opening the page.

### Step 16 — Make it installable (PWA)
**What**
- `static/manifest.webmanifest`: `name: "Bahi-Khata"`, `start_url: "/quick"`, `display: "standalone"`,
  theme/background colours, icons 192×192 and 512×512 (plus maskable), and `shortcuts`
  (Add expense → `/quick`, Dashboard → `/profile`).
- `static/sw.js`: minimal service worker (cache static assets and the `/quick` shell). Serve it from a `/sw.js`
  route so its scope is `/`.
- `base.html`: `<link rel="manifest">`, `theme-color` meta, `apple-touch-icon`,
  `apple-mobile-web-app-capable` meta tags.
- `static/js/main.js`: register the service worker.
- `share_target` in the manifest (GET, `text` param → `/quick`): Bahi-Khata appears in the phone's share
  sheet, so a debit SMS or a GPay/PhonePe receipt can be shared straight into the quick-add form with the
  amount already extracted. Works on iPhone too. Use an absolute URL for `action` and reinstall the app
  after changing the manifest — Android caches it hard.

**Files:** `static/manifest.webmanifest`, `static/sw.js`, `static/icons/*`, `templates/base.html`,
`static/js/main.js`, `app.py`
**Done when:** Chrome / Samsung Internet offers **"Install app"** and it opens full-screen with no browser bar.

### Step 17 — Mobile dashboard
**What**
- Responsive CSS for `profile.html`: the transactions table becomes a card list on small screens.
- **Category chart**: horizontal bars (pure CSS, driven by `get_category_breakdown` percentages) or a Chart.js
  doughnut via CDN, so "where am I spending most" is visible at a glance.
- New stat: **This month vs last month** (↑/↓ %).
- Bottom navigation in standalone mode: **Add | Dashboard | History**.

**Files:** `templates/profile.html`, `static/css/style.css`, `database/queries.py` (month-comparison query)
**Done when:** the dashboard is readable on a 6" screen without horizontal scrolling.

### Step 18 — Back-tap wiring (per phone)

**Samsung Galaxy S24+ (primary)**
1. Open the Bahi-Khata URL in Chrome or Samsung Internet → menu → **Install app / Add to Home screen**.
2. Galaxy Store → install **Good Lock** → inside it install **RegiStar**.
3. RegiStar → **Back-Tap action** → turn on → **Double tap** → **Open app** → choose **Bahi-Khata**.

**iPhone**
1. Safari → Bahi-Khata URL → Share → **Add to Home Screen**.
2. Shortcuts app → new shortcut → action **Open URLs** → `https://<your-app>/quick` → name it "Add Expense".
3. Settings → Accessibility → Touch → **Back Tap** → **Double Tap** → "Add Expense".
   *Limitation: iOS opens the URL in Safari, not the installed home-screen app — it still works, and you stay logged in.*

**Google Pixel**
1. Install the app from Chrome (as above).
2. Settings → System → Gestures → **Quick Tap** → **Open app** → Bahi-Khata.

**Other Android phones**
- Install the open-source **"Tap, Tap"** app (back-tap for any Android) → action: Launch app → Bahi-Khata, **or**
- Long-press the Bahi-Khata icon → **"Add expense"** shortcut (from the manifest) → drag it to the home screen.

**Done when:** a double-tap on the S24+ opens the quick-add screen, ready to type.

**Automatic capture from debit SMS (Android)**
Android only lets the default SMS app read messages, so the web app cannot do this by itself and a native
app would need sideloading (Play Store almost never grants SMS access to expense apps). The practical route
is a free automation app driving the prefill link:
1. Install **MacroDroid** (free tier is enough — this is one macro).
2. Trigger: *SMS Received*, with a content filter on `debited`.
3. Action: *Set Variable* with a regex over `{sms_message}` to capture the amount, e.g.
   `(?:INR|Rs\.?|₹)\s*([0-9,]+(?:\.[0-9]{1,2})?)`, and optionally the merchant after `to ` or `at `.
4. Action: *Open Website* → `https://<your-app>/quick?amount={amount}&remark={merchant}`.
Result: a debit message makes Bahi-Khata pop up with the amount filled in; you pick a category, add a remark
and save. Bank SMS wording differs, so expect to adjust the regex per bank — start with your own bank's
message and widen from there.

*iPhone:* iOS has no SMS trigger for automations, so the back-tap plus the share sheet remain the route there.

### Step 19 (optional) — Offline capture
**What:** if there's no network, save the entry in **IndexedDB** and sync it to the server when back online
(Background Sync where supported, otherwise on next app open). Show a "1 pending" badge.
**Files:** `static/sw.js`, `static/js/main.js`
**Done when:** an expense entered in airplane mode appears on the dashboard after reconnecting.

### Step 20 (optional, iPhone power users) — JSON API + native prompts
**What**
- `POST /api/expenses` authenticated by a per-user **API token** (stored hashed in a new `api_tokens` table,
  generated from the profile page).
- iOS Shortcut: *Choose from List* (type) → *Ask for Input* (amount) → *Ask for Input* (remark) →
  *Get Contents of URL* (POST JSON with `Authorization: Bearer <token>`). Bound to Back Tap — no page load at all.

**Files:** `app.py`, `database/db.py`, `database/queries.py`, `templates/profile.html`

---

## 4. Testing per Step

| Step | Automated (pytest) | Manual on device |
|---|---|---|
| 13 | `get_db` honours `DATABASE_PATH`; no demo user when not in development | Add expense → redeploy → still there |
| 14 | Login response sets a persistent cookie with an expiry; `?next=` redirect works | Close app, reopen, still signed in |
| 15 | `/quick`: redirects when logged out; valid POST saves; bad amount / category shows error | Enter an expense one-handed in < 10 s |
| 16 | `/static/manifest.webmanifest` and `/sw.js` return 200 with correct content types | "Install app" prompt appears; opens full-screen |
| 17 | Month-comparison query returns correct numbers for seeded data | Dashboard readable at phone width |
| 18 | — | Double-tap opens Bahi-Khata on S24+ (and iPhone / Pixel if available) |
| 19 | — | Airplane-mode entry syncs later |
| 20 | API rejects a missing/invalid token; valid token creates an expense for the right user | iOS Shortcut logs an expense |

Use `/test-feature <spec>` for each step.

---

## 5. Security Notes
- Real `SECRET_KEY` in Railway env vars, never in code.
- Secure, HttpOnly, SameSite cookies (Step 14).
- Add CSRF protection to POST forms (Flask-WTF `CSRFProtect` or a simple session token).
- Rate-limit `/login` to slow down password guessing (the site is public).
- No demo account in production (Step 13).
- API tokens (Step 20) stored hashed, revocable from the profile page.

---

## 6. Change History

| Date | Change | Why |
|---|---|---|
| 2026-09-18 | Initial phone plan created | Move Bahi-Khata from desktop web app to daily phone use with back-tap quick entry |
| 2026-09-20 | Renamed app to Bahi-Khata; steps renumbered 11–18 after the Events feature took Step 10 | Events shipped first; quick-add gains an optional event picker |

