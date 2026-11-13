"""Create a super admin in a workspace (default "naik") with a temporary password, or reset one.

    python scripts/create_super_admin.py --username naikadmin --name "Full Name"
    python scripts/create_super_admin.py --workspace naik --username naikadmin --name "Full Name" --mobile 9876543210
    python scripts/create_super_admin.py --username naikadmin --reset

Prints a one-time temporary password. The user must change it at first login
(web portal: no phone needed for a super admin).

--reset (an existing super admin only): new temporary password, must change it at the next login,
account switched on and unlocked, every session ended, the user's phones back to pending approval.
Used after a database copy (plan 6.5: the dev database brings its dev passwords with it) and when
the password is forgotten.

Runs as jansetu_owner, like the other setup scripts. The workspace must exist
already (created by scripts/import_legacy.py or db/seed/seed.py). The insert is
recorded in audit_log.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import string
import sys
from pathlib import Path

import psycopg
from argon2 import PasswordHasher
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# No 0/O, 1/l/I: the password is read out or typed from paper.
ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")


def temp_password(length: int = 12) -> str:
    while True:
        pw = "".join(secrets.choice(ALPHABET) for _ in range(length))
        if any(c.isdigit() for c in pw) and any(c.islower() for c in pw) and any(c.isupper() for c in pw):
            return pw


def connect_owner() -> psycopg.Connection:
    load_dotenv(ROOT / "deploy" / ".env")
    return psycopg.connect(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "jansetu"),
        user="jansetu_owner",
        password=os.environ["JANSETU_OWNER_PASSWORD"],
    )


class AdminError(Exception):
    """Bad input or state; main() prints it and exits."""


def create_super_admin(conn: psycopg.Connection, workspace: str, username: str, name: str,
                       name_mr: str | None = None, mobile: str | None = None) -> tuple[str, str]:
    """Insert a super admin with a temporary password. Returns (user id, temporary password)."""
    password = temp_password()
    with conn.transaction(), conn.cursor() as cur:
        tenant = _tenant(cur, workspace)
        if _find(cur, tenant, username):
            raise AdminError(f'User "{username}" already exists in workspace "{workspace}" (use --reset).')
        user_id = cur.execute(
            """INSERT INTO app.users (tenant_id, username, full_name_en, full_name_mr, mobile, role,
                                      local_body_id, password_hash, must_change_password)
               VALUES (%s, %s, %s, %s, %s, 'super_admin', NULL, %s, true)
               RETURNING id""",
            (tenant, username, name, name_mr, mobile, PasswordHasher().hash(password)),
        ).fetchone()[0]
    return str(user_id), password


def reset_super_admin(conn: psycopg.Connection, workspace: str, username: str) -> tuple[str, str]:
    """New temporary password for an existing super admin; ends their sessions and sends their
    phones back to pending. Returns (user id, temporary password)."""
    password = temp_password()
    with conn.transaction(), conn.cursor() as cur:
        tenant = _tenant(cur, workspace)
        row = _find(cur, tenant, username)
        if row is None:
            raise AdminError(f'User "{username}" not found in workspace "{workspace}".')
        user_id, role = row
        if role != "super_admin":
            raise AdminError(f'User "{username}" is a {role}, not a super admin; '
                             "reset other users from the app or portal (or create_demo_users.py --reset).")
        cur.execute("""UPDATE app.users SET password_hash = %s, must_change_password = true, is_active = true,
                              failed_login_count = 0, locked_until = NULL
                        WHERE id = %s""", (PasswordHasher().hash(password), user_id))
        cur.execute("""UPDATE app.auth_sessions SET revoked_at = now(), revoke_reason = 'password_reset'
                        WHERE user_id = %s AND revoked_at IS NULL""", (user_id,))
        cur.execute("""UPDATE app.devices SET status = 'pending', decided_at = NULL, decided_by = NULL,
                              blocked_reason = NULL, wipe_requested_at = NULL
                        WHERE user_id = %s AND status <> 'pending'""", (user_id,))
    return str(user_id), password


def _tenant(cur: psycopg.Cursor, workspace: str):
    row = cur.execute("SELECT id FROM app.tenants WHERE code = %s", (workspace,)).fetchone()
    if row is None:
        raise AdminError(f'Workspace "{workspace}" not found.')
    cur.execute("SELECT app.set_context(%s, NULL, NULL)", (row[0],))
    return row[0]


def _find(cur: psycopg.Cursor, tenant, username: str):
    return cur.execute("""SELECT id, role FROM app.users
                           WHERE tenant_id = %s AND username = %s AND deleted_at IS NULL""",
                       (tenant, username)).fetchone()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="naik", help="workspace code (default: naik)")
    ap.add_argument("--username", required=True, help="login user ID, 3-40 chars: letters, digits . _ -")
    ap.add_argument("--name", help="full name in English (needed to create)")
    ap.add_argument("--name-mr", help="full name in Marathi")
    ap.add_argument("--mobile", help="10-digit mobile number")
    ap.add_argument("--reset", action="store_true",
                    help="existing super admin: new temporary password, sessions ended, phones pending")
    args = ap.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", args.username):
        sys.exit("username: 3-40 characters, letters, digits . _ - only")
    if args.mobile and not re.fullmatch(r"[6-9][0-9]{9}", args.mobile):
        sys.exit("mobile: 10 digits starting with 6-9, no +91")
    if args.reset and (args.name or args.name_mr or args.mobile):
        sys.exit("--reset changes only the password; leave out --name, --name-mr and --mobile")
    if not args.reset and not args.name:
        sys.exit("--name is needed to create a super admin")

    try:
        with connect_owner() as conn:
            if args.reset:
                user_id, password = reset_super_admin(conn, args.workspace, args.username)
                print(f'Reset super admin "{args.username}" in workspace "{args.workspace}" (user id {user_id}): '
                      "sessions ended, phones back to pending.")
            else:
                user_id, password = create_super_admin(conn, args.workspace, args.username, args.name,
                                                       args.name_mr, args.mobile)
                print(f'Created super admin "{args.username}" in workspace "{args.workspace}" (user id {user_id}).')
    except AdminError as e:
        sys.exit(str(e))
    print(f"Temporary password: {password}")
    print("Give it to the user privately. They must set a new password at first login.")


if __name__ == "__main__":
    main()
