"""Apply db/migrations/*.sql in filename order and record each one.

    python scripts/migrate.py            apply pending migrations
    python scripts/migrate.py --status   list applied / pending, change nothing

Connects as the PostgreSQL superuser (POSTGRES_USER), because 001 creates roles
and extensions. Settings come from deploy/.env; real environment variables win.

Applied files are recorded in public.schema_migrations with a SHA-256. A file
that changed after it was applied stops the run: write a new migration instead.

Transactions:
  * A file with its own top-level BEGIN; / COMMIT; (like 001) runs as written,
    then gets recorded.
  * Any other file runs in one transaction together with its record, so it is
    applied fully or not at all. Prefer this for 002 onwards.

psql meta-commands (lines starting with a backslash, e.g. \\set ON_ERROR_STOP on)
are skipped; this runner always stops at the first error.

After migrating, the passwords of jansetu_owner and jansetu_app are set from
JANSETU_OWNER_PASSWORD / JANSETU_APP_PASSWORD when those are present.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT / "db" / "migrations"
LOCK_ID = 7_406_001  # pg_advisory_lock key: one migrator at a time

OWN_TX_RE = re.compile(r"^\s*(BEGIN|COMMIT|START\s+TRANSACTION)\s*;", re.IGNORECASE | re.MULTILINE)
FILE_RE = re.compile(r"^\d{3}_[a-z0-9_]+\.sql$")


def connect_superuser() -> psycopg.Connection:
    load_dotenv(ROOT / "deploy" / ".env")
    return psycopg.connect(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "jansetu"),
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ["POSTGRES_PASSWORD"],
        autocommit=True,
    )


def migration_files() -> list[Path]:
    files = sorted(p for p in MIGRATIONS_DIR.glob("*.sql"))
    bad = [p.name for p in files if not FILE_RE.match(p.name)]
    if bad:
        sys.exit(f"Bad migration file names (want 001_name.sql): {', '.join(bad)}")
    return files


def strip_psql_meta(text: str) -> str:
    return "\n".join("" if line.lstrip().startswith("\\") else line for line in text.splitlines())


def ensure_table(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public.schema_migrations (
          filename    text PRIMARY KEY,
          sha256      char(64) NOT NULL,
          applied_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def applied(conn: psycopg.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT filename, sha256 FROM public.schema_migrations").fetchall()
    return {name: digest.strip() for name, digest in rows}


def apply_file(conn: psycopg.Connection, path: Path, digest: str) -> None:
    body = strip_psql_meta(path.read_text(encoding="utf-8"))
    record = "INSERT INTO public.schema_migrations (filename, sha256) VALUES (%s, %s)"
    if OWN_TX_RE.search(body):
        # The file manages its own transaction. No parameters → simple query
        # protocol, so the whole file goes to the server as one script.
        try:
            conn.execute(body)
        except psycopg.Error:
            conn.execute("ROLLBACK")  # leave no half-open transaction behind
            raise
        conn.execute(record, (path.name, digest))
    else:
        with conn.transaction():
            conn.execute(body)
            conn.execute(record, (path.name, digest))


def set_role_passwords(conn: psycopg.Connection) -> None:
    for role, var in (("jansetu_owner", "JANSETU_OWNER_PASSWORD"), ("jansetu_app", "JANSETU_APP_PASSWORD")):
        pw = os.environ.get(var)
        if not pw:
            print(f"  {var} not set; leaving {role} password unchanged")
            continue
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        if exists:
            conn.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(pw)))
            print(f"  password set for {role}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", action="store_true", help="show applied / pending only")
    args = parser.parse_args()

    # The session-level advisory lock is released when the connection closes.
    with connect_superuser() as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
        ensure_table(conn)
        done = applied(conn)
        pending: list[tuple[Path, str]] = []
        for path in migration_files():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if path.name in done:
                if done[path.name] != digest:
                    sys.exit(f"{path.name} changed after it was applied. Add a new migration instead.")
                print(f"  applied   {path.name}")
            else:
                print(f"  pending   {path.name}")
                pending.append((path, digest))

        if args.status:
            return
        for path, digest in pending:
            print(f"-> applying {path.name} ...", flush=True)
            apply_file(conn, path, digest)
            print(f"  done      {path.name}")
        if not pending:
            print("Nothing to apply.")
        set_role_passwords(conn)


if __name__ == "__main__":
    main()
