#!/usr/bin/env bash
# Write the server's deploy/.env with new random passwords (plan 6.4). Run on the server:
#
#   bash /srv/jansetu/deploy/make_env.sh DOMAIN ACME_EMAIL
#
# Refuses if deploy/.env already exists (changing the passwords of a running database
# needs migrate.py afterwards; changing JWT_SECRET logs everyone out of their access tokens).
# The passwords stay in this file only (mode 600); a restore does not need them, because
# migrate.py sets the role passwords again from the file.
set -euo pipefail

DOMAIN="${1:?usage: make_env.sh DOMAIN ACME_EMAIL}"
ACME_EMAIL="${2:?usage: make_env.sh DOMAIN ACME_EMAIL}"
ENV_FILE="$(cd "$(dirname "$0")" && pwd)/.env"

[[ -e "$ENV_FILE" ]] && { echo "$ENV_FILE exists; not overwriting." >&2; exit 1; }

pw() { openssl rand -hex 24; }                                    # 48 hex characters
secret() { openssl rand -base64 64 | tr -d '\n/+=' | cut -c1-64; } # 64 characters

umask 077
cat > "$ENV_FILE" <<EOF
# Server settings, written by deploy/make_env.sh on $(date -u +%F). Mode 600, never copied off the server.

# --- PostgreSQL (inside the compose network; no host port) ---
POSTGRES_DB=jansetu
POSTGRES_USER=postgres
POSTGRES_PASSWORD=$(pw)
JANSETU_OWNER_PASSWORD=$(pw)
JANSETU_APP_PASSWORD=$(pw)

# --- API ---
JWT_SECRET=$(secret)
ACCESS_TOKEN_MINUTES=15
REFRESH_TOKEN_DAYS=30
LOGIN_MAX_FAILURES=5
LOGIN_LOCK_MINUTES=15
# Portal origin(s), comma-separated, when the portal is not served from the same domain.
CORS_ORIGINS=

# --- HTTPS (Caddy) ---
DOMAIN=$DOMAIN
SITE_ADDRESS=$DOMAIN, www.$DOMAIN
ACME_EMAIL=$ACME_EMAIL
HTTP_PORT=80
HTTPS_PORT=443

# --- Sizes for 4 vCPU / 16 GB ---
PG_SHARED_BUFFERS=4GB
PG_EFFECTIVE_CACHE_SIZE=10GB
API_WORKERS=3
DB_POOL_SIZE=8
EOF
chmod 600 "$ENV_FILE"
echo "Wrote $ENV_FILE (passwords generated, not shown)."
