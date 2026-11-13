"""End-of-step check on the real roll in the dev database (CLAUDE.md, "Git workflow").

    python scripts/check_dev_data.py [--workspace naik]

Runs the API's own code as jansetu_app (RLS on), with the demo users' real areas
(scripts/create_demo_users.py). Prints counts, PASS/FAIL and timings only: never names,
EPICs or mobiles. Every write happens inside a transaction that is rolled back, and the
owner's row counts before and after must match. Exit code 1 if anything fails.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import Connection, text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.config import get_settings  # noqa: E402
from app.db import get_engine, set_context, transaction  # noqa: E402
from app.deps import Principal  # noqa: E402
from app.errors import ApiError  # noqa: E402
from app.routers.families import booth_families, get_voter_family, write_new_family, write_voter_family  # noqa: E402
from app.routers.geo import get_geo_tree  # noqa: E402
from app.routers.voters import list_voters, save_survey  # noqa: E402
from app.schemas import PushItem, Role, SurveyIn  # noqa: E402
from app.schemas_field import FamilyChange, FamilyIn  # noqa: E402
from app.scope import load_scope  # noqa: E402
from app.sync_pull import current_watermark, pull_page  # noqa: E402
from app.sync_push import push  # noqa: E402
from create_super_admin import connect_owner  # noqa: E402

SLOW_PAGE_MS = 1000
LEFTOVER_TABLES = ("voters", "voter_surveys", "families", "family_members", "sync_mutations", "sync_conflicts",
                   "devices", "users", "audit_log")
failures: list[str] = []


def report(ok: bool, what: str, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {what}{('  -  ' + detail) if detail else ''}")
    if not ok:
        failures.append(what)


def timed(fn: Callable):
    a = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - a) * 1000


def owner_counts(tenant: uuid.UUID) -> dict[str, int]:
    with connect_owner() as c:
        return {t: c.execute(f"SELECT count(*) FROM app.{t} WHERE tenant_id = %s", (tenant,)).fetchone()[0]
                for t in LEFTOVER_TABLES}


def principal(conn: Connection, tenant: uuid.UUID, username: str, device: uuid.UUID | None = None) -> Principal:
    row = conn.execute(text("SELECT id, role, local_body_id FROM app.users WHERE username = :u AND deleted_at IS NULL"),
                       {"u": username}).first()
    if row is None:
        raise SystemExit(f"user {username} not found: run scripts/create_demo_users.py first")
    return Principal(row.id, tenant, uuid.uuid4(), device, Role(row.role), username, row.local_body_id, False,
                     "approved")


def full_pull(conn: Connection, scope, since=None, limit=1000):
    voters, gone, pages, worst, size, marks = set(), set(), 0, 0.0, 0, set()
    cursor, first = None, None
    while True:
        page, ms = timed(lambda: pull_page(conn, scope, since, cursor, limit))
        first = first or page
        worst, pages, size = max(worst, ms), pages + 1, size + len(page.model_dump_json())
        voters |= {v.id for v in page.voters}
        gone |= set(page.gone_voter_ids)
        marks.add(page.watermark)
        cursor = page.next_cursor
        if not cursor:
            return first, voters, gone, pages, worst, size, marks


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workspace", default="naik")
    args = ap.parse_args()

    db = get_settings().postgres_db
    if db.startswith("jansetu_test"):
        raise SystemExit(f"POSTGRES_DB is {db}: this check is for the dev database with the real roll")
    with connect_owner() as c:
        row = c.execute("SELECT id FROM app.tenants WHERE code = %s", (args.workspace,)).fetchone()
    if row is None:
        raise SystemExit(f'workspace "{args.workspace}" not found')
    tenant = row[0]
    before = owner_counts(tenant)
    print(f"Database {db}, workspace {args.workspace}: {before['voters']} voter rows, {before['users']} users")

    # --- read-only checks (each in its own committed-but-read-only transaction) ---------------------
    print("Areas and voter list")
    with transaction(tenant) as conn:
        admin = principal(conn, tenant, "demo.admin")
        supervisor = principal(conn, tenant, "demo.supervisor")
        surveyor = principal(conn, tenant, "demo.surveyor")
        s_admin, s_sup, s_srv = (load_scope(conn, p) for p in (admin, supervisor, surveyor))
        total = conn.execute(text("SELECT count(*) FROM app.voters WHERE deleted_at IS NULL")).scalar_one()

        tree, ms = timed(lambda: get_geo_tree(conn, admin, s_admin))
        nodes, stack = 0, list(tree.roots)
        while stack:
            n = stack.pop()
            nodes += 1
            stack.extend(n.children)
        active = conn.execute(text("SELECT count(*) FROM app.geo_units WHERE is_active AND path <@ "
                                   "(SELECT path FROM app.geo_units WHERE id = :lb)"), {"lb": admin.local_body_id}).scalar()
        report(nodes == active, "admin area tree has every active area", f"{nodes} areas, {ms:.0f} ms")

        for name, p, s in (("supervisor", supervisor, s_sup), ("surveyor", surveyor, s_srv)):
            cond, params = s.filter("v.geo_path")
            via_scope = conn.execute(text(f"SELECT count(*) FROM app.voters v WHERE v.deleted_at IS NULL AND {cond}"),
                                     params).scalar()
            direct = conn.execute(text("""
                SELECT count(*) FROM app.voters v WHERE v.deleted_at IS NULL AND EXISTS (
                  SELECT 1 FROM app.user_area_assignments a JOIN app.geo_units g ON g.id = a.geo_unit_id
                   WHERE a.user_id = :u AND v.geo_path <@ g.path)"""), {"u": p.user_id}).scalar()
            report(via_scope == direct > 0, f"{name} area = assigned parts", f"{via_scope} voters")

        seen, cursor, worst, pages = set(), None, 0.0, 0
        args_ = dict(q=None, ward_id=None, booth_id=None, age_min=None, age_max=None, gender=None, color_tag_id=None,
                     survey_status=None, caste_id=None, profession_id=None, has_mobile=None, influencer=None,
                     influencer_type_id=None, limit=200)
        while True:
            page, ms = timed(lambda: list_voters(conn, admin, s_admin, **args_, cursor=cursor))
            seen |= {v.id for v in page.items}
            worst, pages, cursor = max(worst, ms), pages + 1, page.next_cursor
            if not cursor:
                break
        report(len(seen) == total, "GET /voters pages every voter once", f"{len(seen)} in {pages} pages, slowest {worst:.0f} ms")
        report(worst < SLOW_PAGE_MS, f"voter list pages under {SLOW_PAGE_MS} ms")
        word = conn.execute(text("SELECT lower(last_name_en) FROM app.voters WHERE last_name_en IS NOT NULL "
                                 "GROUP BY 1 ORDER BY count(*) DESC LIMIT 1")).scalar() or "a"
        for label, kw in (("common surname", {"q": word}), ("number", {"q": "5"}), ("gender + age", {"gender": "F", "age_min": 18, "age_max": 25}),
                          ("influencers", {"influencer": True})):
            res, ms = timed(lambda: list_voters(conn, admin, s_admin, **{**args_, **kw}, cursor=None))
            report(ms < SLOW_PAGE_MS, f"search: {label}", f"{len(res.items)} rows on page 1, {ms:.0f} ms")

    print("Sync pull")
    with transaction(tenant) as conn:
        first, voters, _, pages, worst, size, marks = full_pull(conn, s_admin)
        report(len(voters) == total and first.total_voters == total,
               "admin first download is exact", f"{len(voters)} voters, {pages} pages, slowest {worst:.0f} ms, "
                                                f"{size / 1e6:.1f} MB JSON")
        report(len(marks) == 1, "one watermark per download")
        lists = first.lists
        active_types = [e for e in lists.influencer_types if e.is_active] if lists else []
        report(len(active_types) == 11 and "white" not in [t.code for t in lists.color_tags if t.is_active],
               "pull carries the client's 11 influencer types, no active white tag",
               f"{len(active_types)} active of {len(lists.influencer_types) if lists else 0}")
        direct = conn.execute(text("SELECT count(*) FROM app.voter_surveys s JOIN app.voters v ON v.id = s.voter_id "
                                   "WHERE s.is_influencer AND v.deleted_at IS NULL")).scalar()
        listed, cursor = 0, None
        while True:
            page = list_voters(conn, admin, s_admin, **{**args_, "influencer": True}, cursor=cursor)
            listed, cursor = listed + len(page.items), page.next_cursor
            if not cursor:
                break
        report(listed == direct, "Influencer filter = direct count", f"{listed} influencers")
        cond, params = s_srv.filter("v.geo_path")
        expect = conn.execute(text(f"SELECT count(*) FROM app.voters v WHERE v.deleted_at IS NULL AND {cond}"), params).scalar()
        _, sv, _, pages, worst, size, _ = full_pull(conn, s_srv)
        report(len(sv) == expect, "surveyor first download = their parts", f"{len(sv)} voters, {pages} pages, {size / 1e6:.1f} MB")
        w = current_watermark(conn)
        _, dv, dg, pages, _, _, _ = full_pull(conn, s_admin, since=w)
        report(not dv and not dg and pages == 1, "idle delta pull is one request with nothing", f"{pages} page")

    # --- write checks: one transaction, rolled back --------------------------------------------------
    print("Writes (rolled back)")
    with get_engine().connect() as conn:
        trans = conn.begin()
        try:
            set_context(conn, tenant, admin.user_id)
            w = current_watermark(conn)
            ids = list(conn.execute(text("SELECT id FROM app.voters WHERE deleted_at IS NULL ORDER BY id LIMIT 100")).scalars())
            conn.execute(text("UPDATE app.voters SET house_no = house_no WHERE id = ANY(:ids)"), {"ids": ids})
            _, dv, _, pages, _, _, _ = full_pull(conn, s_admin, since=w)
            report(dv == set(ids), "delta pull returns exactly the 100 changed voters", f"{len(dv)} in {pages} pages")

            vid = conn.execute(text("SELECT v.id FROM app.voters v LEFT JOIN app.voter_surveys s ON s.voter_id = v.id "
                                    "WHERE v.deleted_at IS NULL AND s.voter_id IS NULL LIMIT 1")).scalar()
            saved, ms = timed(lambda: save_survey(vid, SurveyIn(version=0, notes="check"), conn, admin, s_admin))
            report(saved.version == 1, "survey first save", f"{ms:.0f} ms")
            try:
                save_survey(vid, SurveyIn(version=0, notes="again"), conn, admin, s_admin)
                report(False, "stale survey save is refused")
            except ApiError as e:
                report(e.status == 409, "stale survey save is refused", f"{e.status} {e.code}")

            dev = conn.execute(text("INSERT INTO app.devices (tenant_id, user_id, device_uid_hash, status) "
                                    "VALUES (:t, :u, repeat('c', 64), 'approved') RETURNING id"),
                               {"t": tenant, "u": admin.user_id}).scalar()
            set_context(conn, tenant, admin.user_id, dev)
            phone_admin = Principal(admin.user_id, tenant, uuid.uuid4(), dev, admin.role, admin.username,
                                    admin.local_body_id, False, "approved")
            batch = [PushItem(id=uuid.uuid4(), type="survey", entity_id=v, base_version=0, data={"notes": "check"})
                     for v in conn.execute(text("SELECT v.id FROM app.voters v LEFT JOIN app.voter_surveys s "
                                                "ON s.voter_id = v.id WHERE v.deleted_at IS NULL AND s.voter_id IS NULL "
                                                "ORDER BY v.id DESC LIMIT 500")).scalars()]
            r1, ms1 = timed(lambda: push(conn, phone_admin, s_admin, batch))
            r2, ms2 = timed(lambda: push(conn, phone_admin, s_admin, batch))
            report(all(r.status.value == "applied" for r in r1), "push of 500 surveys applies", f"{ms1 / 1000:.1f} s")
            report(all(r.duplicate for r in r2), "same batch again: all duplicates, nothing applied", f"{ms2 / 1000:.1f} s")

            # Kutumb Connect (7.1), as the demo surveyor in one of their parts
            booth = conn.execute(text("SELECT g.id FROM app.user_area_assignments a JOIN app.geo_units g ON g.id = a.geo_unit_id "
                                      "WHERE a.user_id = :u AND g.level = 'booth' ORDER BY g.path LIMIT 1"),
                                 {"u": surveyor.user_id}).scalar()
            members = list(conn.execute(text("SELECT id FROM app.voters WHERE booth_id = :b AND deleted_at IS NULL "
                                             "ORDER BY serial_no LIMIT 6"), {"b": booth}).scalars())
            fa, fb = uuid.uuid4(), uuid.uuid4()
            write_new_family(conn, surveyor, s_srv, FamilyIn(id=fa, booth_id=booth, label="Check A"))
            write_new_family(conn, surveyor, s_srv, FamilyIn(id=fb, booth_id=booth, label="Check B"))
            versions = dict(conn.execute(text("SELECT voter_id, version FROM app.voter_surveys WHERE voter_id = ANY(:m)"),
                                         {"m": members}).all())
            _, ms = timed(lambda: [write_voter_family(conn, surveyor, s_srv, v, FamilyChange(family_id=fa))
                                   for v in members[:5]])
            write_voter_family(conn, surveyor, s_srv, members[0], FamilyChange(family_id=fb))  # moved
            write_voter_family(conn, surveyor, s_srv, members[1], FamilyChange(leave_family=True))
            fam = get_voter_family(members[2], conn, surveyor, s_srv).family
            report(fam is not None and fam.member_ids == members[2:5], "Kutumb: add 5, move 1, take 1 out",
                   f"{len(fam.member_ids) if fam else 0} members left, 5 adds in {ms:.0f} ms")
            page, ms = timed(lambda: booth_families(booth, conn, surveyor, s_srv, 50, None))
            report({f.label for f in page.items} >= {"Check A", "Check B"}, "Kutumbs of the part listed",
                   f"{len(page.items)} on page 1, {ms:.0f} ms")
            after_v = dict(conn.execute(text("SELECT voter_id, version FROM app.voter_surveys WHERE voter_id = ANY(:m)"),
                                        {"m": members}).all())
            report(after_v == versions, "Kutumb changes leave survey versions and rows alone",
                   f"{len(versions)} surveyed of {len(members)}")
        finally:
            trans.rollback()

    after = owner_counts(tenant)
    changed = {t: (before[t], after[t]) for t in LEFTOVER_TABLES if before[t] != after[t]}
    report(not changed, "real data unchanged afterwards", ", ".join(f"{t} {a}->{b}" for t, (a, b) in changed.items()))

    print(f"\n{'ALL PASS' if not failures else f'{len(failures)} FAILED: ' + '; '.join(failures)}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
