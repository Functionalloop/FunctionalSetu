#!/usr/bin/env bash
# Nightly database backup (plan 6.2).
#
#   scripts/backup.sh [BACKUP_DIR]
#
# Writes, in BACKUP_DIR (default /var/backups/jansetu, or $BACKUP_DIR):
#   jansetu_<UTC time>.dump     pg_dump custom format (compressed; restore with scripts/restore.sh)
#   jansetu_<UTC time>.counts   row count per table and the transaction counter at backup time;
#                               restore.sh compares against it and uses the counter (see there)
# then deletes backups older than KEEP_DAYS (default 14). Old files are only deleted
# after the new dump has been written and checked.
#
# The dump holds real voter data: the folder is created mode 700, the files 600.
# Never copy it into the repo (the .gitignore also blocks *.dump and backups/).
#
# Which stack: COMPOSE_FILE (default deploy/docker-compose.yml, the production stack).
# Laptop test against the dev database:
#   COMPOSE_FILE=deploy/docker-compose.dev.yml scripts/backup.sh jansetu-private/backups
#
# Server: run nightly from the deploy user's crontab (the server clock is UTC;
# 21:00 UTC = 02:30 India time):
#   0 21 * * * /srv/jansetu/scripts/backup.sh >> /var/log/jansetu/backup.log 2>&1
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export COMPOSE_FILE="${COMPOSE_FILE:-$ROOT/deploy/docker-compose.yml}"
DIR="${1:-${BACKUP_DIR:-/var/backups/jansetu}}"
KEEP_DAYS="${KEEP_DAYS:-14}"

umask 077
mkdir -p "$DIR"
chmod 700 "$DIR"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
base="$DIR/jansetu_$stamp"
started=$(date +%s)

# Run SQL (from stdin) in the db container as the superuser, in the main database.
psql_db() {
  docker compose exec -T db sh -c 'psql -X -q -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
}

echo "$(date -u +%FT%TZ) backup start -> $base.dump"

# 1. The dump, written under a temporary name and renamed only when complete.
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -Z 6' > "$base.dump.partial"

# 2. Check that the file is a complete, readable archive.
docker compose exec -T db pg_restore --list < "$base.dump.partial" > /dev/null
mv "$base.dump.partial" "$base.dump"

# 3. Row counts and the transaction counter (taken just after the dump; on a quiet night
#    they match the dump exactly, otherwise restore.sh shows the few rows written since).
{
  echo "# JANSETU backup $stamp"
  echo "# database $(echo 'SELECT current_database()' | psql_db)"
  echo "# xid $(echo 'SELECT pg_current_xact_id()' | psql_db)"
  psql_db < "$ROOT/scripts/sql/table_counts.sql" | tr '|' ' '
} > "$base.counts"

# 4. Retention: delete backups older than KEEP_DAYS days (-mtime +13 = 14 days or more).
deleted=$(find "$DIR" -maxdepth 1 -type f \( -name 'jansetu_*.dump' -o -name 'jansetu_*.counts' -o -name 'jansetu_*.partial' \) \
  -mtime +$((KEEP_DAYS - 1)) -print -delete | wc -l)

size=$(du -h "$base.dump" | cut -f1)
kept=$(find "$DIR" -maxdepth 1 -type f -name 'jansetu_*.dump' | wc -l)
echo "$(date -u +%FT%TZ) backup ok: $size in $(( $(date +%s) - started ))s, $kept dumps kept, $deleted old files deleted"
