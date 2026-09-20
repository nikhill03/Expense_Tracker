# Deploying Bahi-Khata

The live app runs on Railway: one service, gunicorn, a SQLite file on a mounted
volume. This is the runbook — enough to rebuild the deployment from nothing, and
enough to fix it at 11pm without rediscovering how it works.

Nothing here contains a secret. Real values live in Railway's variables only.

---

## 1. What is deployed

```
phone / laptop  →  Railway edge (HTTPS)  →  gunicorn (1 worker, 4 threads)  →  Flask
                                                                                 ↓
                                                            /data/expense_tracker.db  (volume)
                                                            /data/backups/            (volume)
```

- The start command lives in `Procfile`, and nowhere else.
- `/healthz` runs `SELECT 1`. Railway uses it as the healthcheck, so a deploy that
  cannot reach its database fails to go live instead of serving 500s to a phone.
- The volume is the only durable thing. The container filesystem is thrown away on
  every redeploy — anything written outside `/data` is gone.

## 2. Environment variables

| Variable | Required | Value in production | What it does |
|---|---|---|---|
| `SECRET_KEY` | **yes** | a real random string | Signs the session cookie. The app **refuses to start** in production without it, or with the placeholder from the repo. |
| `APP_ENV` | **yes** | `production` | Turns on `Secure` cookies and `ProxyFix`, and stops the sample data and demo login from ever being seeded. |
| `DATABASE_PATH` | **yes** | `/data/expense_tracker.db` | Puts the database on the volume. Without it the data is wiped on every redeploy. |
| `APP_TIMEZONE` | recommended | `Asia/Kolkata` | The users' calendar day. The server runs in UTC; without this every expense logged before 05:30 IST is dated to the previous day. |
| `ALLOW_REGISTRATION` | no | unset (open) | Set to `false` to close `/register`. The sign-up links disappear with it. |
| `PORT` | no | set by Railway | — |

`.env.example` in the repo root lists the same set for local use.

Generate a secret:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set it straight into Railway — never into a file in the repo:

```bash
railway variables --set "SECRET_KEY=<paste>"
```

## 3. First-time setup

1. `railway login`, then `railway link` to the project.
2. Add a volume mounted at **`/data`** on the web service.
3. Set the variables from the table above.
4. Deploy: `railway up`, or push to the branch Railway watches.
5. Watch the logs for the boot line (see §5) and the healthcheck going green.
6. Open the public URL and confirm it is HTTPS. Railway provides that by default;
   the PWA work in Step 16 depends on it.

There is no seeding step. A fresh production database has no users — create your
account through `/register` on the live site, then decide whether to close it.

## 4. Infrastructure as Code

Railway's `railway.json` / `railway.toml` ("Config as Code") is **deprecated**: new
services cannot opt in, and existing files stop being read on **2026-12-01**. The
replacement is Infrastructure as Code — a `.railway/railway.ts` file describing the
whole project, evaluated by the CLI rather than read during the build.

Generate it from the live project rather than writing it by hand, so the service
name, region and source match reality:

```bash
railway config pull          # writes .railway/railway.ts from the live environment
railway config plan          # shows exactly what would change — read this
railway config apply         # applies it, after confirmation
```

The volume mount, the healthcheck path and the non-secret variables belong in that
file. Secrets stay as `preserve()`, which means "keep whatever is already set in
Railway" — so `SECRET_KEY` never enters the repo.

## 5. Checking a deploy

The first log line says what the process actually resolved:

```
starting: env=production db=/data/expense_tracker.db tz=Asia/Kolkata secure_cookies=True registration=open secret=from environment
```

Read it before anything else. `secret=development default` or `db=expense_tracker.db`
in production means the variables did not arrive.

Then:

- `/healthz` returns `{"status": "ok"}` — 503 means the database is unreachable,
  almost always a volume that is not mounted or a wrong `DATABASE_PATH`.
- Sign in, add an expense, and confirm the date is today in IST.
- After the next redeploy, that expense is still there. This is the whole point of
  the volume; check it once, properly, the first time.

## 6. Rolling back

Railway keeps previous deployments. Redeploy the last good one from the dashboard or
with `railway redeploy`. A rollback restores the **code**, not the data — the volume
is untouched, which is what you want.

## 7. Restoring data from a backup

`backup_db()` takes a `VACUUM INTO` snapshot on the first request of each day and
keeps the newest 7, in `/data/backups/bahikhata-YYYY-MM-DD.db`.

To restore:

```bash
railway ssh
ls /data/backups/
cp /data/expense_tracker.db /data/expense_tracker.db.before-restore   # keep the bad one
cp /data/backups/bahikhata-2026-09-19.db /data/expense_tracker.db
```

Then restart the service so no connection is holding the old file. The WAL sidecar
files (`-wal`, `-shm`) belong to the replaced database; delete them along with it if
the app complains.

These snapshots sit on the same volume as the database. They protect against a bad
delete, not against losing the volume — off-site copies are a known gap, deliberately
deferred (see `ARCHITECTURE_REVIEW.md`).

## 8. Rotating `SECRET_KEY`

Set a new value and redeploy. **Every session is invalidated** — everyone is signed
out and has to log in again on every device. Nothing else is lost. Do it if the key
is ever exposed; there is no reason to do it routinely.

## 9. When the volume fills

The volume is 5 GB (`expense-tracker-volume`, mounted at `/data`). The database grows
by roughly a kilobyte per expense and the backups hold seven copies of it, so this is
decades away — but if it ever gets
close, in order: delete old snapshots in `/data/backups/`, run `VACUUM`, then grow the
volume in the Railway dashboard. Do not move the database off the volume to free
space; that is how data gets lost.

## 10. Closing registration

The site is public, so anyone who finds the URL can create an account. Once your own
account exists:

```bash
railway variables --set "ALLOW_REGISTRATION=false"
```

`/register` then returns 404 and the sign-up links stop rendering. Unset it to reopen.
