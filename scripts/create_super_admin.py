"""Create a super admin in a workspace (default "naik") with a temporary password.

    python scripts/create_super_admin.py --username naikadmin --name "Full Name"
    python scripts/create_super_admin.py --workspace naik --username naikadmin --name "Full Name" --mobile 9876543210

Prints a one-time temporary password. The user must change it at first login
(web portal: no phone needed for a super admin).

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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="naik", help="workspace code (default: naik)")
    ap.add_argument("--username", required=True, help="login user ID, 3-40 chars: letters, digits . _ -")
    ap.add_argument("--name", required=True, help="full name in English")
    ap.add_argument("--name-mr", help="full name in Marathi")
    ap.add_argument("--mobile", help="10-digit mobile number")
    args = ap.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9._-]{3,40}", args.username):
        sys.exit("username: 3-40 characters, letters, digits . _ - only")
    if args.mobile and not re.fullmatch(r"[6-9][0-9]{9}", args.mobile):
        sys.exit("mobile: 10 digits starting with 6-9, no +91")

    password = temp_password()
    with connect_owner() as conn, conn.cursor() as cur:
        row = cur.execute("SELECT id FROM app.tenants WHERE code = %s", (args.workspace,)).fetchone()
        if row is None:
            sys.exit(f'Workspace "{args.workspace}" not found.')
        tenant = row[0]
        cur.execute("SELECT app.set_context(%s, NULL, NULL)", (tenant,))
        if cur.execute("SELECT 1 FROM app.users WHERE tenant_id = %s AND username = %s AND deleted_at IS NULL",
                       (tenant, args.username)).fetchone():
            sys.exit(f'User "{args.username}" already exists in workspace "{args.workspace}".')
        user_id = cur.execute(
            """INSERT INTO app.users (tenant_id, username, full_name_en, full_name_mr, mobile, role,
                                      local_body_id, password_hash, must_change_password)
               VALUES (%s, %s, %s, %s, %s, 'super_admin', NULL, %s, true)
               RETURNING id""",
            (tenant, args.username, args.name, args.name_mr, args.mobile, PasswordHasher().hash(password)),
        ).fetchone()[0]

    print(f'Created super admin "{args.username}" in workspace "{args.workspace}" (user id {user_id}).')
    print(f"Temporary password: {password}")
    print("Give it to the user privately. They must set a new password at first login.")


if __name__ == "__main__":
    main()
