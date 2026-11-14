"""Find possible duplicate voters (plan 10.5) in every active constituency of a workspace.

    python scripts/find_duplicates.py [--workspace naik]

Pairs are found by themselves after a roll apply and after a hand add or correction; run this once
for voters already on record (the first roll was imported by a script), and again after any bulk
change made outside the API. Safe to repeat: a stored pair (and its decision) is never touched.
Runs as the API's database role with RLS on; the audit rows have no user (a script). Prints counts only.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

# The API's Settings will not load without a JWT secret, and the `ops` container has none (it
# signs nothing). This script makes no tokens, so a placeholder is enough when the real one is absent.
os.environ.setdefault("JWT_SECRET", "x" * 32 + "-unused-by-find-duplicates")

from app.db import transaction  # noqa: E402
from app.duplicates import find_pairs  # noqa: E402
from create_super_admin import connect_owner  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="naik")
    args = ap.parse_args()
    with connect_owner() as c:
        row = c.execute("SELECT id FROM app.tenants WHERE code = %s", (args.workspace,)).fetchone()
    if row is None:
        raise SystemExit(f'workspace "{args.workspace}" not found')
    with transaction(row[0]) as conn:
        constituencies = conn.execute(text("""SELECT id, code FROM app.geo_units WHERE level = 'local_body'
                                               AND is_active ORDER BY code""")).all()
        for lb, code in constituencies:
            t = time.perf_counter()
            n = find_pairs(conn, lb)
            total = conn.execute(text("""SELECT count(*) FROM app.voter_duplicate_pairs p
                                           JOIN app.voters a ON a.id = p.voter_a_id WHERE a.local_body_id = :lb"""),
                                 {"lb": lb}).scalar_one()
            print(f"constituency {code}: {n} new pairs, {total} in all ({time.perf_counter() - t:.1f} s)")


if __name__ == "__main__":
    main()
