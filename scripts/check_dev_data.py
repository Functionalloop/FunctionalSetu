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
from datetime import date
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import Connection, text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.config import get_settings  # noqa: E402
from app.conflicts import list_conflicts, resolve_conflict  # noqa: E402
from app.db import get_engine, set_context, transaction  # noqa: E402
from app.deps import Principal  # noqa: E402
from app.errors import ApiError  # noqa: E402
from app.routers.birthdays import birthdays  # noqa: E402
from app.routers.families import booth_families, get_voter_family, write_new_family, write_voter_family  # noqa: E402
from app.routers.geo import get_geo_tree  # noqa: E402
from app.routers.misc import list_announcements, mark_read, report_problem  # noqa: E402
from app.routers.new_voters import list_new_voters, update_new_voter, write_new_voter  # noqa: E402
from app.routers.part_notes import write_part_note  # noqa: E402
from app.routers.slips import write_slip_event  # noqa: E402
from app.routers.visits import write_visit  # noqa: E402
from app.routers.voters import get_voter_history, list_voters, save_survey  # noqa: E402
from app.schemas import PushItem, Role, SurveyIn  # noqa: E402
from app.schemas_field import ConflictStatus  # noqa: E402
from app.schemas_field import (FamilyChange, FamilyIn, NewVoterIn, NewVoterPatch, PartNoteIn, ProblemReportIn,  # noqa: E402
                               SlipEventIn, VisitIn)
from app.scope import load_scope  # noqa: E402
from app.sync_pull import current_watermark, pull_page  # noqa: E402
from app.sync_push import push  # noqa: E402
from create_super_admin import connect_owner  # noqa: E402

SLOW_PAGE_MS = 1000
LEFTOVER_TABLES = ("voters", "voter_surveys", "families", "family_members", "visits", "new_voters", "slip_events",
                   "announcements", "announcement_reads", "problem_reports", "part_notes",
                   "sync_mutations",
                   "sync_conflicts",
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
            w_fam = current_watermark(conn)
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
            fams, mems, cursor = set(), {}, None
            while True:  # the surveyor's delta pull since just before the Kutumb writes
                page = pull_page(conn, s_srv, w_fam, cursor, 1000)
                fams |= {f.id for f in page.families}
                mems.update({m.voter_id: m.family_id for m in page.family_members})
                cursor = page.next_cursor
                if not cursor:
                    break
            expect = {members[0]: fb, members[1]: None, **{v: fa for v in members[2:5]}}
            report(fams == {fa, fb} and mems == expect, "delta pull brings the 2 Kutumbs and 5 member rows",
                   f"{len(fams)} Kutumbs, {len(mems)} members")
            first_fams, cursor = set(), None
            while True:  # first download of the surveyor: the 2 Kutumbs of their part
                page = pull_page(conn, s_srv, None, cursor, 1000)
                first_fams |= {f.id for f in page.families}
                cursor = page.next_cursor
                if not cursor:
                    break
            report({fa, fb} <= first_fams, "first download has the part's Kutumbs", f"{len(first_fams)} Kutumbs")

            # Visits (7.3): one visit sent twice is stored once and comes in the surveyor's delta pull
            w_vis = current_watermark(conn)
            vb = VisitIn(id=uuid.uuid4(), outcome="not_home", visited_at="2026-11-13T10:00:00Z")
            v1, ms = timed(lambda: write_visit(conn, surveyor, s_srv, members[0], vb))
            v2 = write_visit(conn, surveyor, s_srv, members[0], vb)
            n = conn.execute(text("SELECT count(*) FROM app.visits WHERE id = :id"), {"id": vb.id}).scalar()
            seen, cursor = set(), None
            while True:
                page = pull_page(conn, s_srv, w_vis, cursor, 1000)
                seen |= {v.id for v in page.visits}
                cursor = page.next_cursor
                if not cursor:
                    break
            report(n == 1 and v1 == v2 and seen == {vb.id}, "visit sent twice stored once, in the delta pull",
                   f"{ms:.0f} ms")

            # Eligible but Not Registered (7.5): added twice = once, a stale edit is 409, in the delta pull
            w_nv = current_watermark(conn)
            place = conn.execute(text("SELECT ward_id, booth_id FROM app.voters WHERE id = :id"),
                                 {"id": members[0]}).one()
            nb = NewVoterIn(id=uuid.uuid4(), full_name_en="Check Person", ward_id=place.ward_id,
                            booth_id=place.booth_id, dob="2008-01-01")
            n1, ms = timed(lambda: write_new_voter(conn, surveyor, s_srv, nb))
            n2 = write_new_voter(conn, surveyor, s_srv, nb)
            edit = NewVoterPatch(**{**nb.model_dump(exclude={"id"}), "form6_status": "applied", "version": 1})
            saved = update_new_voter(nb.id, edit, conn, surveyor, s_srv)
            try:
                update_new_voter(nb.id, edit, conn, surveyor, s_srv)  # version 1 again: stale
                stale = None
            except ApiError as e:
                stale = e.status
            listed = list_new_voters(conn, surveyor, s_srv, limit=50, cursor=None)
            seen, cursor = set(), None
            while True:
                page = pull_page(conn, s_srv, w_nv, cursor, 1000)
                seen |= {x.id for x in page.new_voters}
                cursor = page.next_cursor
                if not cursor:
                    break
            report(n1 == n2 and saved.version == 2 and stale == 409 and nb.id in {x.id for x in listed.items}
                   and seen == {nb.id}, "new voter added twice stored once; stale edit 409; in the delta pull",
                   f"{ms:.0f} ms")

            # Information Updation (7.6): the moved voter's two Kutumb changes and the visit, each with who
            hist, ms = timed(lambda: get_voter_history(members[0], conn, surveyor, s_srv, 50, None))
            kinds = [h.kind for h in hist.items]
            report(kinds[:2] == ["family", "family"] and "visit" in kinds and all(h.by for h in hist.items[:2]),
                   "history lists the Kutumb changes and the visit with who", f"{len(kinds)} entries, {ms:.0f} ms")
            pushed = batch[0].entity_id
            hist, ms = timed(lambda: get_voter_history(pushed, conn, admin, s_admin, 50, None))
            report([h.kind for h in hist.items][:1] == ["survey"] and "notes" in hist.items[0].changes,
                   "history shows a pushed survey with its fields", f"{ms:.0f} ms")

            # Voter slip (7.7): a share sent twice (REST and push) is logged once
            se = SlipEventIn(id=uuid.uuid4(), channel="whatsapp", at="2026-11-13T10:00:00Z")
            _, ms = timed(lambda: write_slip_event(conn, surveyor, s_srv, members[2], se))
            write_slip_event(conn, surveyor, s_srv, members[2], se)
            n = conn.execute(text("SELECT count(*) FROM app.slip_events WHERE client_mutation_id = :id"),
                             {"id": se.id}).scalar()
            report(n == 1, "slip shared twice is logged once", f"{ms:.0f} ms")

            # Birthdays (7.8): a whole year as the admin, page by page, equals a direct count
            seen, cursor, pages = 0, None, 0
            _, ms = timed(lambda: birthdays(conn, admin, s_admin, date(2026, 3, 1), date(2027, 2, 28), None, 200, None))
            while True:
                page = birthdays(conn, admin, s_admin, date(2026, 3, 1), date(2027, 2, 28), None, 200, cursor)
                seen += len(page.items)
                pages += 1
                cursor = page.next_cursor
                if not cursor:
                    break
            direct = conn.execute(text("SELECT count(*) FROM app.voter_surveys s JOIN app.voters v ON v.id = s.voter_id "
                                       "WHERE s.dob IS NOT NULL AND v.deleted_at IS NULL")).scalar()
            report(seen == direct, "birthdays over a whole year = voters with a date of birth",
                   f"{seen} in {pages} pages, first page {ms:.0f} ms")

            # More menu (7.9): a notice for everyone reaches the surveyor, read twice = one row; a problem report
            aid = uuid.uuid4()
            conn.execute(text("INSERT INTO app.announcements (id, tenant_id, body, created_by) "
                              "VALUES (:id, app.current_tenant_id(), 'Check notice', :u)"), {"id": aid, "u": admin.user_id})
            listed, ms = timed(lambda: list_announcements(conn, surveyor, s_srv, 50, None))
            mark_read(conn, surveyor, s_srv, aid)
            mark_read(conn, surveyor, s_srv, aid)
            reads = conn.execute(text("SELECT count(*) FROM app.announcement_reads WHERE announcement_id = :a"),
                                 {"a": aid}).scalar()
            report(listed.items[:1] and listed.items[0].id == aid and reads == 1,
                   "new announcement listed first for the surveyor; read twice = one row", f"{ms:.0f} ms")
            report_problem(ProblemReportIn(body="Check report", app_version_code=1), conn, surveyor)
            n = conn.execute(text("SELECT count(*) FROM app.problem_reports WHERE body = 'Check report'")).scalar()
            report(n == 1, "problem report stored")

            # Conflict review (7.10): a stale push on a surveyed voter, kept from the phone once
            v0 = batch[0].entity_id
            push(conn, phone_admin, s_admin, [PushItem(id=uuid.uuid4(), type="survey", entity_id=v0, base_version=1,
                                                       data={"notes": "check server"})])
            res = push(conn, phone_admin, s_admin, [PushItem(id=uuid.uuid4(), type="survey", entity_id=v0,
                                                             base_version=1, data={"notes": "check phone"})])
            page, ms = timed(lambda: list_conflicts(conn, phone_admin, s_admin, ConflictStatus.open, None, 50, None))
            mine = [c for c in page.items if c.entity_id == v0]
            other = list_conflicts(conn, surveyor, s_srv, ConflictStatus.open, v0, 50, None).items
            resolve_conflict(conn, phone_admin, s_admin, mine[0].id, ConflictStatus.kept_client)
            try:
                resolve_conflict(conn, phone_admin, s_admin, mine[0].id, ConflictStatus.kept_client)
                twice = 200
            except ApiError as e:
                twice = e.status
            row = conn.execute(text("SELECT version, notes FROM app.voter_surveys WHERE voter_id = :v"), {"v": v0}).first()
            report(res[0].status.value == "conflict" and len(mine) == 1 and not other and tuple(row) == (3, "check phone")
                   and twice == 409, "conflict listed, kept from the phone once; not shown to another surveyor",
                   f"list {ms:.0f} ms")

            # Part notes (7.11): saved in the surveyor's part, a stale save refused, in the delta pull
            w_note = current_watermark(conn)
            old = conn.execute(text("SELECT version FROM app.part_notes WHERE booth_id = :b"), {"b": booth}).scalar() or 0
            saved, ms = timed(lambda: write_part_note(conn, surveyor, s_srv, booth, PartNoteIn(note="Check note", version=old)))
            stale = write_part_note(conn, surveyor, s_srv, booth, PartNoteIn(note="Check stale", version=old))
            seen, cursor = [], None
            while True:
                page = pull_page(conn, s_srv, w_note, cursor, 1000)
                seen += [n.booth_id for n in page.part_notes]
                cursor = page.next_cursor
                if not cursor:
                    break
            report(saved is not None and saved.version == old + 1 and stale is None and seen == [booth],
                   "part note saved, stale save refused, in the delta pull", f"{ms:.0f} ms")
        finally:
            trans.rollback()

    after = owner_counts(tenant)
    changed = {t: (before[t], after[t]) for t in LEFTOVER_TABLES if before[t] != after[t]}
    report(not changed, "real data unchanged afterwards", ", ".join(f"{t} {a}->{b}" for t, (a, b) in changed.items()))

    print(f"\n{'ALL PASS' if not failures else f'{len(failures)} FAILED: ' + '; '.join(failures)}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
