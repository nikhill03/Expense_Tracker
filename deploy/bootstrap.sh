#!/usr/bin/env bash
#
# Bahi-Khata — first-time server setup on a fresh Ubuntu VM.
#
#   sudo BAHIKHATA_HOST=bahikhata.duckdns.org ./deploy/bootstrap.sh
#
# Idempotent: safe to re-run. It never overwrites an existing SECRET_KEY, and it
# never touches the database. For routine code updates use deploy/update.sh.
#
# See docs/DEPLOYMENT.md for what to do before and after this.

set -euo pipefail

REPO="${BAHIKHATA_REPO:-https://github.com/nikhill03/Expense_Tracker.git}"
BRANCH="${BAHIKHATA_BRANCH:-main}"
APP_DIR=/opt/bahikhata
DATA_DIR=/var/lib/bahikhata
CONF_DIR=/etc/bahikhata
ENV_FILE="$CONF_DIR/bahikhata.env"
APP_USER=bahikhata

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo." >&2
    exit 1
fi

if [[ -z "${BAHIKHATA_HOST:-}" ]]; then
    echo "Set BAHIKHATA_HOST to the hostname TLS will be issued for," >&2
    echo "e.g. sudo BAHIKHATA_HOST=bahikhata.duckdns.org $0" >&2
    exit 1
fi

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

say "Installing packages"
apt-get update -qq
apt-get install -y -qq git python3 python3-venv python3-pip curl \
    debian-keyring debian-archive-keyring apt-transport-https

if ! command -v caddy >/dev/null; then
    say "Installing Caddy"
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
        | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    apt-get update -qq
    apt-get install -y -qq caddy
fi

say "Creating the app user and directories"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
install -d -o "$APP_USER" -g "$APP_USER" -m 0750 "$APP_DIR"
# The database and its backups. 0700: nothing else on the box needs to read it.
install -d -o "$APP_USER" -g "$APP_USER" -m 0700 "$DATA_DIR"
install -d -o root -g "$APP_USER" -m 0750 "$CONF_DIR"

say "Fetching the code ($BRANCH)"
if [[ -d "$APP_DIR/.git" ]]; then
    sudo -u "$APP_USER" git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
    sudo -u "$APP_USER" git -C "$APP_DIR" reset --hard --quiet "origin/$BRANCH"
else
    sudo -u "$APP_USER" git clone --quiet --branch "$BRANCH" "$REPO" "$APP_DIR"
fi

say "Building the virtualenv"
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
    sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
fi
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

if [[ ! -f "$ENV_FILE" ]]; then
    say "Writing $ENV_FILE with a fresh SECRET_KEY"
    # Generated on the box. It never exists in the repo, in git, or on your laptop.
    secret="$("$APP_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(48))')"
    cat > "$ENV_FILE" <<ENV
APP_ENV=production
SECRET_KEY=$secret
DATABASE_PATH=$DATA_DIR/expense_tracker.db
APP_TIMEZONE=Asia/Kolkata
# Set to false once your account exists, then: systemctl restart bahikhata
ALLOW_REGISTRATION=true
ENV
    chown root:"$APP_USER" "$ENV_FILE"
    chmod 0640 "$ENV_FILE"
else
    say "Keeping the existing $ENV_FILE (SECRET_KEY unchanged)"
fi

say "Installing the systemd unit"
install -m 0644 "$APP_DIR/deploy/bahikhata.service" /etc/systemd/system/bahikhata.service
systemctl daemon-reload
systemctl enable --quiet bahikhata
systemctl restart bahikhata

say "Configuring Caddy for $BAHIKHATA_HOST"
sed "s|BAHIKHATA_HOST|$BAHIKHATA_HOST|g" "$APP_DIR/deploy/Caddyfile" > /etc/caddy/Caddyfile
install -d -o caddy -g caddy -m 0755 /var/log/caddy
systemctl enable --quiet caddy
systemctl reload caddy || systemctl restart caddy

say "Opening ports 80 and 443"
# Only some hosts need this. GCP filters at the VPC, so its Ubuntu images have
# no local rules and both branches below are a no-op. Oracle's images ship an
# iptables ruleset that drops everything but SSH, and it is not ufw — the single
# most common reason a new Oracle VM looks dead from outside.
if command -v netfilter-persistent >/dev/null; then
    iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || \
        iptables -I INPUT 6 -p tcp --dport 80 -j ACCEPT
    iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || \
        iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
    netfilter-persistent save >/dev/null
fi
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow 80/tcp >/dev/null
    ufw allow 443/tcp >/dev/null
fi

say "Done"
systemctl --no-pager --lines=0 status bahikhata | head -5
echo
echo "Check the boot line:   journalctl -u bahikhata -n 20 --no-pager | grep starting"
echo "Check health:          curl -s https://$BAHIKHATA_HOST/healthz"
echo
echo "Still to do at the cloud level: allow inbound TCP 80 and 443, or nothing"
echo "reaches this box. On GCP that is a VPC firewall rule targeting the"
echo "http-server / https-server tags; on Oracle, the VCN security list."
