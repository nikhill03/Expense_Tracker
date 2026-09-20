#!/usr/bin/env bash
#
# Bahi-Khata — deploy the latest code.
#
#   sudo /opt/bahikhata/deploy/update.sh
#
# Pulls, installs any new dependencies, restarts. The database is never touched:
# it lives in /var/lib/bahikhata, outside the code directory, and init_db()
# migrates the schema in place on startup.

set -euo pipefail

APP_DIR=/opt/bahikhata
BRANCH="${BAHIKHATA_BRANCH:-main}"
APP_USER=bahikhata

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo." >&2
    exit 1
fi

before="$(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short HEAD)"

sudo -u "$APP_USER" git -C "$APP_DIR" fetch --quiet origin "$BRANCH"
sudo -u "$APP_USER" git -C "$APP_DIR" reset --hard --quiet "origin/$BRANCH"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

after="$(sudo -u "$APP_USER" git -C "$APP_DIR" rev-parse --short HEAD)"

# The unit file and the proxy config are in the repo, so a deploy that changes
# them has to install them too — otherwise the change silently does nothing.
if ! cmp -s "$APP_DIR/deploy/bahikhata.service" /etc/systemd/system/bahikhata.service; then
    echo "systemd unit changed; reinstalling"
    install -m 0644 "$APP_DIR/deploy/bahikhata.service" /etc/systemd/system/bahikhata.service
    systemctl daemon-reload
fi

systemctl restart bahikhata
sleep 2

if systemctl is-active --quiet bahikhata; then
    echo "deployed $before -> $after"
    curl -fsS -o /dev/null -w 'healthz: %{http_code}\n' http://127.0.0.1:8000/healthz || \
        echo "healthz did not answer — check: journalctl -u bahikhata -n 40"
else
    echo "service failed to start; rolling back to $before" >&2
    sudo -u "$APP_USER" git -C "$APP_DIR" reset --hard --quiet "$before"
    systemctl restart bahikhata
    echo "rolled back. Logs: journalctl -u bahikhata -n 40" >&2
    exit 1
fi
