#!/usr/bin/env bash
set -euo pipefail
test "$(uname -m)" = x86_64 || { echo 'Requires verified x86_64 OpenD architecture'; exit 1; }
test "$(id -u)" = 0 || { echo 'Run with sudo'; exit 1; }
apt-get update
apt-get install -y python3 python3-venv
id paper >/dev/null 2>&1 || useradd --system --home /opt/a-share-paper --shell /usr/sbin/nologin paper
cd /opt/a-share-paper
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
mkdir -p state
chown -R paper:paper state
.venv/bin/python -m paper.service check
install -m 0644 deploy/paper.service /etc/systemd/system/a-share-paper.service
if test ! -f /etc/a-share-paper.env; then
  umask 077
  .venv/bin/python -c 'import secrets; print("AGENT_TOKEN="+secrets.token_urlsafe(48))' > /etc/a-share-paper.env
fi
systemctl daemon-reload
systemctl enable --now a-share-paper.service
echo 'API listens on loopback only. Connect through an authenticated HTTPS tunnel.'
echo 'OpenD login and data source are separate preflight steps. No orders enabled.'
