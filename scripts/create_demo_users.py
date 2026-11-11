"""Demo users for the 25 Nov demo, in one workspace (default "naik").

    python scripts/create_demo_users.py                     create the users (skips any that exist)
    python scripts/create_demo_users.py --parts 1,2         which roll parts the supervisor / surveyor get
    python scripts/create_demo_users.py --reset             rehearse again: new temporary passwords,
                                                            unlocked, logged out, phones back to "pending"
    python scripts/create_demo_users.py --remove            after the demo: switch the demo users off

Users (prefix "demo." by default):
    demo.superadmin   super admin (whole workspace)
    demo.admin        admin of the constituency the parts belong to
    demo.supervisor   supervisor, assigned the wards of the parts
    demo.surveyor     surveyor, assigned the booths of the parts
One roll part = one ward (ward number = part number) with its booth(s); see import_roll_parts.py.

Temporary passwords are written to jansetu-private/demo_users.txt (git-ignored), never printed:
this output may end up in a shared terminal log. Every user must set a new password at first
login. Demo users are not the client's real accounts: create those with create_super_admin.py
and the admin screens.

Runs as jansetu_owner like the other setup scripts; inserts are recorded in audit_log.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from argon2 import PasswordHasher

sys.path.insert(0, str(Path(__file__).resolve().parent))
from create_super_admin import connect_owner, temp_password  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS = ROOT / "jansetu-private" / "demo_users.txt"
ROLES = (("superadmin", "super_admin", "Demo Super Admin"), ("admin", "admin", "Demo Admin"),
         ("supervisor", "supervisor", "Demo Supervisor"), ("surveyor", "surveyor", "Demo Surveyor"))


class DemoError(Exception):
    pass


def _areas(cur: psycopg.Cursor, tenant: uuid.UUID, parts: list[int]) -> tuple[uuid.UUID, list, list]:
    """(constituency, wards, booths) of the roll parts."""
    wards = cur.execute("""SELECT id, parent_id, number FROM app.geo_units
                            WHERE tenant_id = %s AND level = 'ward' AND number = ANY(%s) AND is_active""",
                        (tenant, parts)).fetchall()
    found = sorted(w[2] for w in wards)
    if found != sorted(parts):
        raise DemoError(f"parts {parts}: found wards {found}; every part needs exactly one active ward")
    constituencies = {w[1] for w in wards}
    if len(constituencies) != 1:
        raise DemoError("the parts belong to more than one constituency; pick parts of one")
    ward_ids = [w[0] for w in wards]
    booths = [b[0] for b in cur.execute("""SELECT id FROM app.geo_units
                                            WHERE tenant_id = %s AND level = 'booth' AND parent_id = ANY(%s)
                                              AND is_active""", (tenant, ward_ids)).fetchall()]
    if not booths:
        raise DemoError(f"parts {parts} have no booths")
    return constituencies.pop(), ward_ids, booths


def create_demo_users(conn: psycopg.Connection, workspace: str = "naik", parts: list[int] | None = None,
                      prefix: str = "demo", reset: bool = False, remove: bool = False) -> dict[str, str | None]:
    """Create (or reset / remove) the demo users. Returns {username: new temporary password, or None
    when the user already existed and nothing changed}. One transaction; raises DemoError on bad input."""
    parts = parts or [1, 2]
    hasher = PasswordHasher()
    out: dict[str, str | None] = {}
    with conn.transaction(), conn.cursor() as cur:
        row = cur.execute("SELECT id FROM app.tenants WHERE code = %s", (workspace,)).fetchone()
        if row is None:
            raise DemoError(f'workspace "{workspace}" not found')
        tenant = row[0]
        cur.execute("SELECT app.set_context(%s, NULL, NULL)", (tenant,))
        constituency, wards, booths = _areas(cur, tenant, parts)
        assign = {"supervisor": wards, "surveyor": booths}

        for key, role, name in ROLES:
            username = f"{prefix}.{key}"
            existing = cur.execute("""SELECT id FROM app.users
                                       WHERE tenant_id = %s AND username = %s AND deleted_at IS NULL""",
                                   (tenant, username)).fetchone()
            if remove:
                if existing:
                    cur.execute("UPDATE app.users SET is_active = false WHERE id = %s", (existing[0],))
                    cur.execute("""UPDATE app.auth_sessions SET revoked_at = now(), revoke_reason = 'demo_removed'
                                    WHERE user_id = %s AND revoked_at IS NULL""", (existing[0],))
                out[username] = None
                continue

            password: str | None = None
            if existing is None:
                password = temp_password()
                user_id = cur.execute(
                    """INSERT INTO app.users (tenant_id, username, full_name_en, role, local_body_id,
                                              password_hash, must_change_password)
                       VALUES (%s, %s, %s, %s, %s, %s, true) RETURNING id""",
                    (tenant, username, name, role, None if role == "super_admin" else constituency,
                     hasher.hash(password))).fetchone()[0]
            else:
                user_id = existing[0]
                if reset:
                    password = temp_password()
                    cur.execute("""UPDATE app.users SET password_hash = %s, must_change_password = true,
                                          is_active = true, failed_login_count = 0, locked_until = NULL,
                                          local_body_id = %s
                                    WHERE id = %s""",
                                (hasher.hash(password), None if role == "super_admin" else constituency, user_id))
                    cur.execute("""UPDATE app.auth_sessions SET revoked_at = now(), revoke_reason = 'demo_reset'
                                    WHERE user_id = %s AND revoked_at IS NULL""", (user_id,))
                    cur.execute("""UPDATE app.devices SET status = 'pending', decided_at = NULL, decided_by = NULL,
                                          blocked_reason = NULL, wipe_requested_at = NULL
                                    WHERE user_id = %s""", (user_id,))
            if key in assign:  # exactly the requested parts
                cur.execute("DELETE FROM app.user_area_assignments WHERE user_id = %s AND NOT (geo_unit_id = ANY(%s))",
                            (user_id, assign[key]))
                for gid in assign[key]:
                    cur.execute("""INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id)
                                   VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""", (tenant, user_id, gid))
            out[username] = password
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="naik")
    ap.add_argument("--parts", default="1,2", help="comma-separated roll part numbers (default 1,2)")
    ap.add_argument("--prefix", default="demo")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--reset", action="store_true", help="new temporary passwords, phones back to pending")
    mode.add_argument("--remove", action="store_true", help="switch the demo users off")
    args = ap.parse_args()
    try:
        parts = [int(p) for p in args.parts.split(",") if p.strip()]
    except ValueError:
        sys.exit("--parts: numbers separated by commas, e.g. 1,2")

    try:
        with connect_owner() as conn:
            result = create_demo_users(conn, args.workspace, parts, args.prefix, args.reset, args.remove)
    except DemoError as e:
        sys.exit(str(e))

    if args.remove:
        print(f"Switched off: {', '.join(result)}")
        return
    new = {u: p for u, p in result.items() if p}
    for user, pw in result.items():
        print(f"  {user:<22} {'new temporary password' if pw else 'exists, unchanged'}")
    if new:
        CREDENTIALS.parent.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with CREDENTIALS.open("a", encoding="utf-8") as f:
            f.write(f"\n# {stamp}  workspace {args.workspace}  parts {args.parts}\n")
            f.writelines(f"{u}  {p}\n" for u, p in new.items())
        print(f"Temporary passwords written to {CREDENTIALS} (git-ignored). Each user sets a new one at first login.")


if __name__ == "__main__":
    main()
