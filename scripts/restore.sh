#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh (plan 6.2).
#
#   scripts/restore.sh DUMP [SCRATCH_DB]   restore check: restore into a scratch database
#                                          (default jansetu_restore_check), compare the row
#                                          counts with DUMP's .counts file, then drop it
#                                          (KEEP=1 keeps it). The live database is not touched.
#   scripts/restore.sh --live DUMP         replace the live database (POSTGRES_DB) with DUMP.
#                                          The api must be stopped first:
#                                            docker compose -f deploy/docker-compose.yml stop api
#
# Which stack: COMPOSE_FILE (default deploy/docker-compose.yml), as in backup.sh.
#
# --live also handles a restore onto a NEW PostgreSQL server (moving to another server,
# or after losing one). Sync watermarks and sync_xid are PostgreSQL transaction numbers,
# and each server counts its own. A fresh server starts near 1,000, below the numbers in
# the backup and on the phones, so phones would stop receiving changes. The script moves
# the server's counter past the highest number in the backup plus XID_MARGIN (default
# 2,000,000, room for phones that synced after the backup was taken), using pgbench.
# On the same server the counter is already past it and nothing is done.
#
# Roles: jansetu_owner and jansetu_app are created if missing (a new server). They then
# have no password: run migrate.py once (it applies nothing, it only sets the passwords):
#   docker compose -f deploy/docker-compose.yml run --rm ops python scripts/migrate.py
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export COMPOSE_FILE="${COMPOSE_FILE:-$ROOT/deploy/docker-compose.yml}"
XID_MARGIN="${XID_MARGIN:-2000000}"

live=0
if [[ "${1:-}" == "--live" ]]; then live=1; shift; fi
dump="${1:?usage: scripts/restore.sh [--live] DUMP [SCRATCH_DB]}"
[[ -f "$dump" ]] || { echo "no such file: $dump" >&2; exit 1; }
counts="${dump%.dump}.counts"

# Run SQL from stdin as the superuser in database $1.
psql_in() {
  docker compose exec -T -e DB="$1" db sh -c 'psql -X -q -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$DB"'
}

live_db="$(docker compose exec -T db sh -c 'echo "$POSTGRES_DB"' | tr -d '\r')"
if (( live )); then
  target="$live_db"
  if [[ -n "$(docker compose ps --status running -q api 2>/dev/null)" ]]; then
    echo "The api is running. Stop it first: docker compose -f $COMPOSE_FILE stop api" >&2
    exit 1
  fi
else
  target="${2:-jansetu_restore_check}"
  if [[ "$target" == "$live_db" ]]; then
    echo "$target is the live database; use --live to replace it." >&2
    exit 1
  fi
fi
[[ "$target" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "bad database name: $target" >&2; exit 1; }

echo "Restoring $(basename "$dump") into database $target$( (( live )) && echo ' (LIVE)')"

# 1. Roles (normally made by migration 001; a new server does not have them yet).
psql_in postgres <<'SQL'
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jansetu_owner') THEN
    CREATE ROLE jansetu_owner LOGIN BYPASSRLS;
    RAISE NOTICE 'created role jansetu_owner (no password yet: run migrate.py)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jansetu_app') THEN
    CREATE ROLE jansetu_app LOGIN NOBYPASSRLS;
    RAISE NOTICE 'created role jansetu_app (no password yet: run migrate.py)';
  END IF;
END $$;
SQL

# 2. A new, empty database with the grants pg_dump does not carry (database level).
psql_in postgres <<SQL
DROP DATABASE IF EXISTS $target WITH (FORCE);
CREATE DATABASE $target TEMPLATE template0 ENCODING 'UTF8';
GRANT CONNECT, CREATE ON DATABASE $target TO jansetu_owner;
GRANT CONNECT ON DATABASE $target TO jansetu_app;
SQL

# 3. The restore itself. Owners and grants come from the dump; any error stops it.
started=$(date +%s)
docker compose exec -T -e DB="$target" db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$DB" --exit-on-error' < "$dump"
echo "pg_restore done in $(( $(date +%s) - started ))s"

# 4. Compare row counts with the backup's .counts file.
status=0
if [[ -f "$counts" ]]; then
  diffs=$(diff <(grep -v '^#' "$counts" | tr -d '\r') \
               <(psql_in "$target" < "$ROOT/scripts/sql/table_counts.sql" | tr '|' ' ' | tr -d '\r') || true)
  tables=$(grep -vc '^#' "$counts")
  if [[ -z "$diffs" ]]; then
    echo "Row counts match the backup: $tables tables."
  else
    echo "Row counts differ from the backup (< backup, > restored):"
    echo "$diffs"
    status=2
  fi
else
  echo "No $(basename "$counts") next to the dump: row counts not compared."
fi

if (( ! live )); then
  if [[ "${KEEP:-0}" == "1" ]]; then
    echo "Kept database $target (drop it with: DROP DATABASE $target)."
  else
    echo "DROP DATABASE $target WITH (FORCE);" | psql_in postgres
    echo "Dropped $target."
  fi
  exit $status
fi

# 5. --live: move this server's transaction counter past every number in the backup.
backup_xid=0
[[ -f "$counts" ]] && backup_xid=$(sed -n 's/^# xid \([0-9]*\).*/\1/p' "$counts" | tr -d '\r')
stored_xid=$(psql_in "$target" < "$ROOT/scripts/sql/max_xid.sql" | tr -d '\r')
high=$(( ${backup_xid:-0} > stored_xid ? ${backup_xid:-0} : stored_xid ))
want=$(( high + XID_MARGIN ))
now=$(echo 'SELECT pg_current_xact_id()' | psql_in postgres | tr -d '\r')
if (( now >= want )); then
  echo "Transaction counter $now is already past the backup ($high + margin): nothing to do."
else
  gap=$(( want - now ))
  per_client=$(( gap / 4 + 1 ))
  echo "New server: moving the transaction counter from $now past $want ($gap transactions)..."
  docker compose exec -T -e N="$per_client" db sh -c \
    'echo "SELECT pg_current_xact_id();" > /tmp/xid_burn.sql && pgbench -n -U "$POSTGRES_USER" -c 4 -j 4 -t "$N" -f /tmp/xid_burn.sql postgres > /dev/null && rm /tmp/xid_burn.sql'
  now=$(echo 'SELECT pg_current_xact_id()' | psql_in postgres | tr -d '\r')
  echo "Transaction counter now $now."
  (( now >= want )) || { echo "counter still below $want" >&2; exit 1; }
fi

echo "Live restore done. If roles were created above, run migrate.py (ops) for their passwords, then start the api."
exit $status
