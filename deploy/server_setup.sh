#!/usr/bin/env bash
# One-time server setup (plan 6.4). Ubuntu 24.04, run on the server as the deploy user
# (passwordless sudo). Safe to run again. See deploy/README.md for the whole sequence.
#
#   bash /srv/jansetu/deploy/server_setup.sh
#
# Installs Docker (Docker's apt repository) and turns on the firewall (22, 80, 443 only),
# automatic security updates, Docker log limits, and the folders for backups and logs.
set -euo pipefail

say() { echo "== $*"; }

say "packages"
sudo apt-get update -q
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q ca-certificates curl ufw unattended-upgrades cron logrotate
sudo systemctl enable --now cron

if ! command -v docker >/dev/null 2>&1; then
  say "Docker (from download.docker.com)"
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
  sudo apt-get update -q
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -q \
    docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

say "Docker log limits (100 GB disk)"
if [[ ! -f /etc/docker/daemon.json ]]; then
  echo '{ "log-driver": "json-file", "log-opts": { "max-size": "10m", "max-file": "5" } }' \
    | sudo tee /etc/docker/daemon.json > /dev/null
fi
sudo systemctl enable --now docker
sudo systemctl restart docker
sudo usermod -aG docker deploy

say "firewall: 22, 80, 443 (+443/udp for HTTP/3)"
# Note: ports published by Docker (only caddy's 80/443) bypass ufw; the database publishes none.
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 443/udp
sudo ufw --force enable

say "automatic security updates"
echo 'APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";' | sudo tee /etc/apt/apt.conf.d/20auto-upgrades > /dev/null

say "folders"
sudo install -d -o deploy -g deploy -m 755 /srv/jansetu
sudo install -d -o deploy -g deploy -m 700 /var/backups/jansetu
sudo install -d -o deploy -g deploy -m 755 /var/log/jansetu
echo '/var/log/jansetu/*.log {
  weekly
  rotate 8
  compress
  missingok
  notifempty
}' | sudo tee /etc/logrotate.d/jansetu > /dev/null

say "done"
docker --version
docker compose version
sudo ufw status | head -12
[[ -f /var/run/reboot-required ]] && echo "NOTE: a reboot is pending (sudo reboot); the stack restarts by itself." || true
echo "Log out and in again (or use 'sg docker') so the docker group applies to deploy."
