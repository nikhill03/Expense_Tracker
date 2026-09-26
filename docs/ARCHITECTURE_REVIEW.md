# Architecture Review — Bahi-Khata

A record of the system-design decisions behind the app: what was changed, what was measured, and what was
deliberately left alone. Kept short on purpose — if something here goes stale, fix it here rather than adding a
second copy elsewhere.

| Date | Change | Why |
|---|---|---|
| 2026-09-20 | Step 11 review: indexes, single-query dashboard, pagination, WAL, CSRF, login throttling, backups | Moving from a local toy to a public URL holding real spending data |
| 2026-09-20 | Step 14: configuration from the environment, data on a volume, 90-day secure sessions, deploy runbook | The public URL was running on a secret that is in the repo, a demo login anyone could use, and a database that was wiped on every redeploy |
| 2026-09-20 | Settled the four red tests: writes redirect to `/expenses`, dates leave the query layer as ISO and get formatted by a `\|dmy` filter | Both were implementation drift from the specs, and the date one was showing two different formats on two pages |
| 2026-09-20 | Deployment target moved from Railway to a self-hosted VM (`deploy/`, §3.9) | Railway's trial ended, and every free platform either has no persistent disk or an NFS one — SQLite with WAL needs a real local disk |
| 2026-09-26 | Step 16: installable PWA, and fonts moved off Google to fix a CSP regression (§3.11) | Going live behind a strict CSP silently blocked the webfonts; self-hosting fixed it without weakening the policy and made the offline shell possible |

---

## 1. Shape of the system

One Flask process, one SQLite file, server-rendered Jinja templates, no JavaScript framework, no cache layer, no
background workers. For a single user logging a handful of expenses a day, this is the right amount of machinery —
every component added here would be a component to operate and pay for.

```
phone / laptop  →  gunicorn (1 worker, 4 threads)  →  Flask routes  →  database/queries.py  →  SQLite on a volume
```

Request path rules that keep it honest:
- Routes never write SQL; all queries live in `database/queries.py`.
- Ownership is checked in the route (`404` unknown, `403` someone else's), and repeated in the `WHERE` clause of
  writes as a second line of defence.
- Every query is parameterised. No string interpolation of user input, anywhere.

---

## 2. What was measured

Benchmark: a throwaway database with **10,000 expenses across 5 users** (~2,000 rows for the user under test),
each query timed as the mean of 20 runs. Script: `scratchpad/bench.py`.

| Query | Before | After | Change |
|---|---:|---:|---|
| Dashboard stats (month) | 1.67 ms | 0.37 ms | index |
| Category breakdown (month) | 1.10 ms | 0.23 ms | index |
| Transaction list, unbounded | 19.09 ms | 15.50 ms | no longer used by any page |
| Transaction list, 10 rows | 1.49 ms | 0.26 ms | index |
| Expense list (month) | 1.12 ms | 0.32 ms | index |
| Combined `get_dashboard` | — | 0.22 ms | new |
| **Whole profile page's queries** | **21.86 ms** | **0.48 ms** | **~45× faster** |

Query plans changed from `SCAN expenses` to `SEARCH expenses USING INDEX idx_expenses_user_date`, and the expense
list became a **covering index** scan — the `ORDER BY` no longer builds a temporary B-tree.

At today's 20 rows none of this is perceptible. It was done now because the cost is one line per index and the
alternative is discovering it in two years with a phone on a slow connection.

---

## 3. Decisions

### 3.1 Indexes follow the access path, not the columns
Every list and dashboard query filters `user_id` plus a date range, so `idx_expenses_user_date (user_id, date)`
serves all four. Event pages filter `user_id` with `event_id`, hence `idx_expenses_user_event`. The older
single-column `idx_expenses_event` was dropped — it was a prefix of the new one and earned nothing.

### 3.2 One aggregate query instead of five round trips
The dashboard used to run five queries on four connections: two for the stat cards, one for the category bars, one
for transactions, one for the user. The per-category aggregate already contains the total, the count and the top
category, so `get_dashboard()` derives all three in Python from a single `GROUP BY` pass. The page is now
**user lookup + one aggregate + one transaction query**, enforced by a test that counts queries.

### 3.3 Nothing renders an unbounded list
`/profile` was rendering every expense the user had ever logged. It now shows the latest 10 with a "View all" link;
`/expenses` paginates at 50 per page; the event page caps at 50. Totals are computed over the whole range in SQL,
not summed from the rows on screen — so the number stays correct while the page stays small.

### 3.4 SQLite settings chosen for a server, not a laptop
- `journal_mode = WAL` — readers no longer block the writer.
- `busy_timeout = 5000` — a request waits for a lock instead of returning a 500.
- `synchronous = NORMAL` — safe under WAL; a crash can cost the last commit, never the file.
- `gunicorn --workers 1 --threads 4` — one process avoids multi-process write contention on a single file and fits
  the free tier's memory. Threads still serve the read-heavy pages concurrently.

### 3.5 Security basics before going public
- **CSRF tokens** on every POST, home-grown (`secrets.token_urlsafe` in the session, checked in `before_request`) —
  no new dependency. Disabled under `TESTING` so route tests stay readable, with `tests/test_11_hardening.py`
  exercising the real behaviour.
- **Login throttling** in a `login_attempts` table: 5 failures locks that email for 15 minutes. In a table rather
  than memory so a restart doesn't reset it.
- **Friendly error pages** for 400/403/404/500 — users see a sentence, not a stack trace.

### 3.6 Backups, because a volume is not a backup
A daily `VACUUM INTO` snapshot beside the database, keeping 7, triggered by the first request of the day. No
scheduler to run, and it protects against the thing a volume doesn't: a bad delete.

### 3.7 `/healthz`
Returns 200 and runs `SELECT 1`, so the platform can tell "process alive" from "app actually working".
Step 14 made it the gate on a deploy: `deploy/update.sh` calls it after every restart and resets to the previous
commit if it does not answer, so a bad deploy self-heals instead of leaving the phone with a dead app.

### 3.8 One environment switch, not a drawer of flags
`APP_ENV` decides everything that differs between a laptop and the public site: whether a real `SECRET_KEY`
is mandatory, whether the session cookie is `Secure`, whether `ProxyFix` trusts `X-Forwarded-*`, and whether
the sample data and demo login are seeded. The alternative — a separate variable per behaviour — means a
deployment can be half-production, which is the state where you ship a `Secure` cookie with a public secret
and nobody notices. `ALLOW_REGISTRATION` is the one genuinely independent choice, so it stays its own
variable.

Missing configuration **raises at import** rather than falling back. A failed deploy is discovered in
seconds; a public site quietly signing cookies with a key that is in the repo is discovered by whoever reads
the repo.

`SESSION_COOKIE_SECURE` follows `APP_ENV` rather than being on always: on plain-HTTP localhost the browser
drops a `Secure` cookie without a word, so signing in appears to do nothing at all.

### 3.9 A plain VM, because SQLite needs a real disk
The deployment target moved from Railway to a self-hosted Oracle Always Free VM, and the reason is the storage,
not the price. SQLite with `journal_mode=WAL` needs a local POSIX-locking filesystem. Of the free Python hosts,
Render and Koyeb give no persistent disk at all — the database would be wiped on every restart, which is the exact
failure this step existed to fix — and PythonAnywhere's filesystem is NFS, where WAL can corrupt the file outright.
So the choice was: give up WAL and run a money ledger on network storage, pay for a platform, or run a VM with a
real disk. The VM keeps every decision in this document intact and costs nothing.

What it costs instead is operations: TLS, a process supervisor and a firewall are now ours. That is bounded —
`deploy/` holds a systemd unit, a Caddyfile and two scripts, and Caddy renews certificates by itself — but it is
real, and it is the honest trade for ₹0 and a disk that behaves.

### 3.10 Backups live beside the database
`backup_db()` derives its directory from `DATABASE_PATH`, so pointing the app at `/var/lib/bahikhata` puts the
snapshots there with the data. That guards against a bad delete. It does **not** guard against losing the machine —
off-site copies are the obvious next step and are deliberately not done yet (see §4).

### 3.11 Self-hosted fonts, and a worker that caches almost nothing
The first deploy shipped a CSP of `default-src 'self'` while `base.html` still pulled two families from
fonts.googleapis.com. Both were blocked; production rendered in the fallback stack and nothing errored. The
choice was to loosen the policy or move the files. Moving them won on three counts: the CSP stays strict, two
third-party round trips disappear from every page load, and a service worker can cache a same-origin font but
not a cross-origin one it is forbidden to fetch. The `latin-ext` subsets ship alongside `latin` because ₹ is
U+20B9 and lives there — subsetting it away would have cost the rupee sign on every amount.

The worker itself is deliberately close to useless, and that is the design. It precaches static assets and one
offline page; it does **not** cache HTML, because every page embeds a per-session CSRF token and a cached page
would post a token `_guard_and_time_request` rejects — the user would see "your session expired" on a form that
looked fine, and stale balances besides. It never touches a non-GET request either, so *a GET never writes*
stays true with a worker in the path. Entering an expense with no connection is Step 19 and needs a real queue;
pretending a cache is that would lose data quietly.

---

## 4. Deliberately not done

| Deferred | Why not now | What would change our mind |
|---|---|---|
| One connection per request (`flask.g`) | Touches all 17 `get_db()` call sites and every `finally: conn.close()`; worth ~1–2 ms | Doing it anyway as part of the formatting refactor below |
| **Amount formatting inside the query layer** | Queries still return `"₹1,234.00"` strings, so callers can't do arithmetic and tests assert on formatted text. Dates are done — see §5 | **Must be fixed before the JSON API step** — a Shortcut wants `1234.0`, not a rupee string. Remaining work: return numbers, add a `\|rupees` Jinja filter beside the existing `\|dmy` |
| Money as `REAL` instead of integer paise | Float error is ~1e-10 and invisible after 2-dp rounding | Any feature doing settlement maths, e.g. splitting a bill between people |
| Postgres instead of SQLite | Single writer, single user; SQLite on a volume handles years of data comfortably | Concurrent writers, multiple devices writing at once, or background jobs |
| A cache layer | Every page is under a millisecond of query time | Only if a page ever becomes expensive to compute, which none is |
| Off-site backups | The daily snapshots sit on the same volume as the database, so they cover a bad delete but not a lost volume | Anything that makes the data hard to re-enter — a second user, or a year of history |
| CI | The suite runs locally in 45 seconds and one person merges everything | A second contributor, or the first time a broken `main` reaches the phone |

---

## 5. Resolved: the four red tests

Four tests had been failing since July. Both causes were implementation drift, not bad tests, so the code moved to
meet them rather than the other way round.

**The redirect after a write.** `/expenses/add`, `/expenses/<id>/edit` and `/expenses/<id>/delete` redirected to
`/profile`; specs 07, 08 and 09 independently say `/expenses`, and the tests were written from those specs. The
list page is also the better destination: it is where the edit and delete buttons were clicked from, and it is the
page that shows the result of the change. All three now redirect to `/expenses`. Adding an expense while an event
is selected still goes to that event's page — that came later than the specs and is deliberate.

**Dates formatted in the query layer.** `get_recent_transactions` returned `"10 Jul 2026"` while
`get_filtered_expenses` returned `"2026-07-10"`, and both feed the same `tx_rows()` macro — so `/profile` and
`/expenses` were printing dates in two different formats on screen. `get_recent_transactions` now returns ISO like
its neighbour, and a `|dmy` Jinja filter does the formatting in the template. A date that has been turned into
words cannot be compared or sorted; keeping it ISO until the last moment is the point.

That filter is the first slice of the refactor in §4 — amounts still cross the query layer as `"₹1,234.00"`
strings, and still need to stop before the JSON API step.
