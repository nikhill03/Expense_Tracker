# Deploying Bahi-Khata

Bahi-Khata runs on a single small VM: gunicorn behind Caddy, SQLite on the VM's
own disk. This is the runbook — enough to rebuild the deployment from nothing,
and enough to fix it at 11pm without rediscovering how it works.

Nothing here contains a secret. The real `SECRET_KEY` is generated on the server
and lives only in `/etc/bahikhata/bahikhata.env`.

---

## 1. What is deployed

```
phone / laptop  →  Caddy :443 (TLS)  →  gunicorn 127.0.0.1:8000 (1 worker, 4 threads)  →  Flask
                                                                                            ↓
                                                        /var/lib/bahikhata/expense_tracker.db
                                                        /var/lib/bahikhata/backups/
```

| Path | What it holds |
|---|---|
| `/opt/bahikhata` | the git checkout and its virtualenv; read-only to the running app |
| `/var/lib/bahikhata` | the database and its daily snapshots — **the only thing that matters** |
| `/etc/bahikhata/bahikhata.env` | `SECRET_KEY` and the rest of the environment, `0640 root:bahikhata` |
| `/etc/systemd/system/bahikhata.service` | installed from `deploy/bahikhata.service` |
| `/etc/caddy/Caddyfile` | installed from `deploy/Caddyfile` with the hostname substituted |

Gunicorn binds to localhost only, so nothing reaches the app except through
Caddy. The systemd unit runs with `ProtectSystem=strict` and a single
`ReadWritePaths=/var/lib/bahikhata`, so a bug cannot rewrite the code that is
running.

### Why a VM rather than a platform

SQLite needs a real, local, POSIX-locking disk. The free tiers that host Python
either give no persistent disk at all (Render, Koyeb — the database would be
wiped on every restart) or put the filesystem on NFS (PythonAnywhere), where
`journal_mode=WAL` risks corrupting the file. WAL is a deliberate choice here
(`ARCHITECTURE_REVIEW.md` §3.4), so the host has to have a real disk.

The target is a **Google Cloud `e2-micro`**, which is Always Free with no expiry
and a real persistent disk. Nothing below is GCP-specific except §3 — the unit
file, the proxy config and the scripts work on any Ubuntu VM with a real disk,
which is the point.

## 2. Environment variables

Set in `/etc/bahikhata/bahikhata.env`, which `bootstrap.sh` creates.

| Variable | Required | Value in production | What it does |
|---|---|---|---|
| `SECRET_KEY` | **yes** | generated on the box | Signs the session cookie. The app **refuses to start** in production without it, or with the placeholder from the repo. |
| `APP_ENV` | **yes** | `production` | Turns on `Secure` cookies and `ProxyFix`, and stops the sample data and demo login from ever being seeded. |
| `DATABASE_PATH` | **yes** | `/var/lib/bahikhata/expense_tracker.db` | Keeps the database outside the code directory, so a deploy never touches it. |
| `APP_TIMEZONE` | recommended | `Asia/Kolkata` | The users' calendar day. The server runs in UTC; without this every expense logged before 05:30 IST is dated to the previous day. |
| `ALLOW_REGISTRATION` | no | `true`, then `false` | Set to `false` once your account exists. `/register` then 404s and the sign-up links disappear. |

`.env.example` in the repo root lists the same set for local use.

After editing the file: `sudo systemctl restart bahikhata`.

## 3. First-time setup

### 3.1 The VM

Everything here runs in Cloud Shell, which has `gcloud` pre-authenticated.

**Stay inside Always Free or it costs money.** The flags below are the whole of
it: `e2-micro`, one of `us-central1` / `us-west1` / `us-east1`, and at most 30 GB
of `pd-standard`. A nearer region is not free; `pd-ssd` is not free.

```bash
gcloud compute instances create bahikhata \
  --zone=us-central1-a --machine-type=e2-micro \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-standard \
  --tags=http-server,https-server
```

**If this fails with `Constraint constraints/compute.vmExternalIpAccess violated`**,
the organization denies public IPs on VMs — the secure-by-default policy on new
Cloud Identity orgs. Allow it for this one instance and nothing else:

```bash
gcloud resource-manager org-policies allow compute.vmExternalIpAccess \
  projects/<PROJECT_ID>/zones/us-central1-a/instances/bahikhata \
  --project=<PROJECT_ID>
```

That needs `roles/orgpolicy.policyAdmin`, which even an org owner may have to
grant themselves first.

Then read the public IP:

```bash
gcloud compute instances describe bahikhata --zone=us-central1-a \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```

### 3.2 A hostname

TLS needs a name, not an IP. A free DuckDNS subdomain is enough:

1. Sign in at duckdns.org, create e.g. `bahikhata`, point it at the public IP.
2. Confirm it resolves: `dig +short bahikhata.duckdns.org`.

A domain you own works the same way — point an A record at the IP.

### 3.3 Open the ports

GCP firewalls at the VPC, not on the instance — the `--tags=http-server,https-server`
above only marks the VM as a target, so the rules still have to exist:

```bash
gcloud compute firewall-rules create allow-http  --allow=tcp:80  --target-tags=http-server
gcloud compute firewall-rules create allow-https --allow=tcp:443 --target-tags=https-server
```

`already exists` here is fine — some projects ship them by default.

If the site is unreachable while Caddy looks healthy, this is the first thing to
check. (On Oracle there is a second, instance-level iptables to open as well;
`bootstrap.sh` handles that case and is a no-op on GCP.)

### 3.4 Run the bootstrap

```bash
gcloud compute ssh bahikhata --zone=us-central1-a
git clone https://github.com/nikhill03/Expense_Tracker.git /tmp/bk
sudo BAHIKHATA_HOST=bahikhata.duckdns.org /tmp/bk/deploy/bootstrap.sh
```

`gcloud compute ssh` generates and installs the key on first use, so there is no
key file to manage.

It installs packages and Caddy, creates the `bahikhata` user and directories,
clones the repo to `/opt/bahikhata`, builds the virtualenv, generates a
`SECRET_KEY`, installs the systemd unit and the Caddyfile, and opens the local
firewall. It is idempotent — re-running never overwrites an existing
`SECRET_KEY` and never touches the database.

Caddy gets the certificate on first request, which takes a few seconds.

### 3.5 Your account

There is no seeding in production, so the database starts empty. Register on the
live site, then close registration:

```bash
sudo sed -i 's/^ALLOW_REGISTRATION=.*/ALLOW_REGISTRATION=false/' /etc/bahikhata/bahikhata.env
sudo systemctl restart bahikhata
```

## 4. Checking a deploy

The first log line says what the process actually resolved:

```bash
journalctl -u bahikhata -n 20 --no-pager | grep starting
```

```
starting: env=production db=/var/lib/bahikhata/expense_tracker.db tz=Asia/Kolkata secure_cookies=True registration=open secret=from environment
```

Read it before anything else. `secret=development default`, or a `db=` without a
path, means the environment file did not load.

Then:

- `curl -s https://<host>/healthz` returns `{"status": "ok"}`. A 503 means the
  app is up but the database is not reachable — usually a permissions problem on
  `/var/lib/bahikhata`.
- Sign in, add an expense, confirm the date is today in IST.
- `sudo systemctl restart bahikhata` and confirm the expense is still there.

## 5. Routine deploys

```bash
sudo /opt/bahikhata/deploy/update.sh
```

Pulls `main`, installs any new dependencies, reinstalls the systemd unit if it
changed, restarts, and checks health. **If the service fails to start it resets
to the previous commit and restarts** — so a bad deploy self-heals rather than
leaving the phone with a dead app.

The database is never touched: it lives outside the code directory, and
`init_db()` migrates the schema in place on startup.

## 6. Rolling back

```bash
sudo -u bahikhata git -C /opt/bahikhata log --oneline -10
sudo -u bahikhata git -C /opt/bahikhata reset --hard <sha>
sudo systemctl restart bahikhata
```

A rollback restores the **code**, not the data — `/var/lib/bahikhata` is
untouched, which is what you want.

## 7. Restoring data from a backup

`backup_db()` takes a `VACUUM INTO` snapshot on the first request of each day and
keeps the newest 7, in `/var/lib/bahikhata/backups/bahikhata-YYYY-MM-DD.db`.

```bash
sudo systemctl stop bahikhata
cd /var/lib/bahikhata
sudo -u bahikhata cp expense_tracker.db expense_tracker.db.before-restore
sudo -u bahikhata cp backups/bahikhata-2026-09-19.db expense_tracker.db
sudo -u bahikhata rm -f expense_tracker.db-wal expense_tracker.db-shm
sudo systemctl start bahikhata
```

Stop the service first — copying over a database that has an open connection is
how you get a file that is half one snapshot and half another. The `-wal` and
`-shm` sidecars belong to the database you just replaced, so they go with it.

These snapshots sit on the same disk as the database. They protect against a bad
delete, not against losing the VM — see §9.

## 8. Rotating `SECRET_KEY`

```bash
sudo python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
sudo nano /etc/bahikhata/bahikhata.env     # replace SECRET_KEY
sudo systemctl restart bahikhata
```

**Every session is invalidated** — you are signed out on every device and have to
log in again. Nothing else is lost. Do it if the key is ever exposed; there is no
reason to do it routinely.

## 9. Getting the data off the box

The one real gap. Backups on the VM's own disk do not survive losing the VM, and
a single VM is a single point of failure. Until something better exists,
pull a copy to your laptop now and then:

```bash
gcloud compute scp bahikhata:/var/lib/bahikhata/backups/bahikhata-$(date +%F).db \
  ~/backups/ --zone=us-central1-a
```

Worth automating from your laptop's side rather than the server's — a backup the
server can delete is not really a backup.

## 10. When something is wrong

| Symptom | Look at |
|---|---|
| Site unreachable, no TLS error | VCN security list ingress (§3.3) — the usual culprit |
| TLS fails, "certificate not trusted" | `journalctl -u caddy -n 50` — usually DNS not pointing at the box yet |
| 502 from Caddy | gunicorn is down: `systemctl status bahikhata`, `journalctl -u bahikhata -n 50` |
| `/healthz` returns 503 | the app is up, the database is not: check ownership of `/var/lib/bahikhata` |
| Signed out constantly | `SECRET_KEY` changing between restarts — the env file is not loading |
| Login appears to do nothing | reaching the site over plain HTTP with `APP_ENV=production`; the browser drops the `Secure` cookie |
