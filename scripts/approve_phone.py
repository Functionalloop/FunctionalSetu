"""Approve a user's waiting phone from the server (the first admin phone has nobody to approve it).

    python scripts/approve_phone.py --username demo.admin
    python scripts/approve_phone.py --workspace naik --username naikadmin

Only an approved admin or super admin can approve phones in the app (More > Phones), and their own
phone starts as "waiting" too. This script is for that first phone; after it, admins approve every
other phone in the app. It approves only phones that are waiting (pending) and only for an admin or
super admin: a blocked phone stays blocked, and field workers' phones are approved in the app.

Run on the server through the ops container (it needs the owner password):
    docker compose -f deploy/docker-compose.yml run --rm ops python scripts/approve_phone.py --username ...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))
from create_super_admin import connect_owner  # noqa: E402

ADMIN_ROLES = ("admin", "super_admin")


class ApproveError(Exception):
    """Bad input or state; main() prints it and exits."""


def approve_phone(conn: psycopg.Connection, workspace: str, username: str) -> list[str]:
    """Approve the user's waiting phones. Returns one line per phone approved (model, Android version)."""
    with conn.transaction(), conn.cursor() as cur:
        row = cur.execute("SELECT id FROM app.tenants WHERE code = %s", (workspace,)).fetchone()
        if row is None:
            raise ApproveError(f'Workspace "{workspace}" not found.')
        tenant = row[0]
        cur.execute("SELECT app.set_context(%s, NULL, NULL)", (tenant,))
        user = cur.execute("""SELECT id, role FROM app.users
                               WHERE tenant_id = %s AND username = %s AND deleted_at IS NULL""",
                           (tenant, username)).fetchone()
        if user is None:
            raise ApproveError(f'User "{username}" not found in workspace "{workspace}".')
        if user[1] not in ADMIN_ROLES:
            raise ApproveError(f'User "{username}" is a {user[1]}: an admin approves that phone in the app '
                               "(More > Phones).")
        rows = cur.execute("""UPDATE app.devices SET status = 'approved', decided_at = now(), decided_by = NULL,
                                     blocked_reason = NULL, wipe_requested_at = NULL
                               WHERE tenant_id = %s AND user_id = %s AND status = 'pending'
                               RETURNING coalesce(model, '?') || ', ' || coalesce(os_version, '?')""",
                           (tenant, user[0])).fetchall()
        if not rows:
            raise ApproveError(f'"{username}" has no phone waiting for approval. Log in on the phone first.')
    return [r[0] for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="naik", help="workspace code (default: naik)")
    ap.add_argument("--username", required=True, help="the admin or super admin whose phone waits")
    args = ap.parse_args()
    try:
        with connect_owner() as conn:
            phones = approve_phone(conn, args.workspace, args.username)
    except ApproveError as e:
        sys.exit(str(e))
    for p in phones:
        print(f'Approved "{args.username}" on {p}.')
    print("The phone moves on by itself within 15 seconds.")


if __name__ == "__main__":
    main()
