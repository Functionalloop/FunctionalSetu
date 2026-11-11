"""GET /sync/pull without `since` (first download): all pages together are exactly the user's area.

Fake data only. Login / role / phone-state rules: test_endpoint_rules.py.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import pytest

from conftest import bearer, login, phone

API = "/api/v1"


@dataclass
class Download:
    pages: list[dict] = field(default_factory=list)

    @property
    def first(self) -> dict:
        return self.pages[0]

    def ids(self, key: str, id_field: str = "id") -> list[uuid.UUID]:
        return [uuid.UUID(r[id_field]) for p in self.pages for r in p[key]]


def download(client, headers, limit=1000) -> Download:
    d, cursor = Download(), None
    while True:
        r = client.get(f"{API}/sync/pull", headers=headers, params={"limit": limit, **({"cursor": cursor} if cursor else {})})
        assert r.status_code == 200, r.text
        d.pages.append(r.json())
        cursor = r.json()["next_cursor"]
        if cursor is None:
            return d
        assert len(d.pages) < 200, "download does not end"


@pytest.fixture
def area(make_workspace, owner_conn):
    """Workspace A: booth 1 (3 voters + 1 removed), booth 2 (2 voters), second ward (1 voter),
    second constituency (1 voter); surveys on some. Workspace B: 1 voter."""
    ws = make_workspace("pull", extra_users={"agent1": "booth_agent"})
    c = owner_conn

    def unit(parent, level, code, number=None):
        gid = uuid.uuid4()
        c.execute("""INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, number, name_mr)
                     VALUES (%s, %s, %s, %s, %s, %s, 'X')""", (gid, ws.tenant, parent, level, code, number))
        return gid

    ws.section = unit(ws.booths[0], "section", "1001-1", 1)
    ws.ward2 = unit(ws.local_body, "ward", "2", 2)
    ws.ward2_booth = unit(ws.ward2, "booth", "2001", 1)
    ws.lb2 = unit(None, "local_body", "2")
    ws.lb2_booth = unit(unit(ws.lb2, "ward", "1", 1), "booth", "9001", 1)

    serial = iter(range(1, 1000))

    def voter(tenant, lb, ward, booth, deleted=False):
        vid = uuid.uuid4()
        c.execute("""INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no,
                                             gender, first_name_en, last_name_en, deleted_at)
                     VALUES (%s, %s, %s, %s, %s, 1, %s, 'M', 'Fake', 'Voter', CASE WHEN %s THEN now() END)""",
                  (vid, tenant, lb, ward, booth, next(serial), deleted))
        return vid

    def survey(vid, tenant=ws.tenant):
        c.execute("INSERT INTO app.voter_surveys (tenant_id, voter_id, notes, is_surveyed) VALUES (%s, %s, 'n', true)",
                  (tenant, vid))

    lb2_ward = c.execute("SELECT parent_id FROM app.geo_units WHERE id = %s", (ws.lb2_booth,)).fetchone()[0]
    ws.b1 = [voter(ws.tenant, ws.local_body, ws.ward, ws.booths[0]) for _ in range(3)]
    ws.b1_removed = voter(ws.tenant, ws.local_body, ws.ward, ws.booths[0], deleted=True)
    ws.b2 = [voter(ws.tenant, ws.local_body, ws.ward, ws.booths[1]) for _ in range(2)]
    ws.w2 = [voter(ws.tenant, ws.local_body, ws.ward2, ws.ward2_booth)]
    ws.lb2_voters = [voter(ws.tenant, ws.lb2, lb2_ward, ws.lb2_booth)]
    for v in (ws.b1[0], ws.b1[1], ws.b1_removed, ws.b2[0], ws.w2[0], ws.lb2_voters[0]):
        survey(v)
    ws.surveyed = {ws.b1[0], ws.b1[1], ws.b2[0], ws.w2[0], ws.lb2_voters[0]}  # removed voter's survey never sent

    other = make_workspace("pull-b")
    survey(voter(other.tenant, other.local_body, other.ward, other.booths[0]), other.tenant)
    ws.other = other
    return ws


def phone_headers(client, ws, username, set_device_status, uid):
    t = login(client, ws, username, device=phone(uid)).json()
    set_device_status(t["device"]["id"], "approved")
    return bearer(t)


def check_exact(d: Download, voters: set, areas: set, surveyed: set):
    got_voters = d.ids("voters")
    assert len(got_voters) == len(set(got_voters)), "a voter came twice"
    assert set(got_voters) == voters
    assert set(d.ids("surveys", "voter_id")) == voters & surveyed
    assert set(d.ids("areas")) == areas
    assert d.first["total_voters"] == len(voters)
    assert d.first["total_surveys"] == len(voters & surveyed)
    assert len({p["watermark"] for p in d.pages}) == 1  # one watermark for the whole download


@pytest.mark.parametrize("limit", [1, 2, 1000])
def test_surveyor_gets_exactly_booth_1(client, area, set_device_status, limit):
    h = phone_headers(client, area, "survey1", set_device_status, "phone-pull-0001")
    d = download(client, h, limit)
    check_exact(d, set(area.b1), {area.booths[0], area.section}, area.surveyed)
    if limit == 1:
        assert len(d.pages) == 1 + 3 + 2  # first page, one per voter, one per survey (no empty end pages)


def test_supervisor_gets_the_ward(client, area):
    d = download(client, bearer(login(client, area, "sup1").json()), limit=2)
    check_exact(d, set(area.b1 + area.b2), {area.ward, *area.booths, area.section}, area.surveyed)


def test_admin_gets_own_constituency(client, area):
    d = download(client, bearer(login(client, area, "admin1").json()), limit=2)
    check_exact(d, set(area.b1 + area.b2 + area.w2),
                {area.local_body, area.ward, *area.booths, area.section, area.ward2, area.ward2_booth},
                area.surveyed)


def test_super_admin_gets_whole_workspace_only(client, area):
    d = download(client, bearer(login(client, area, "boss").json()), limit=3)
    every = set(area.b1 + area.b2 + area.w2 + area.lb2_voters)
    got = set(d.ids("voters"))
    assert got == every  # nothing of workspace B, nothing removed
    assert set(d.ids("surveys", "voter_id")) == area.surveyed


def test_unassigned_booth_agent_gets_nothing(client, area, set_device_status):
    h = phone_headers(client, area, "agent1", set_device_status, "phone-pull-0002")
    d = download(client, h)
    assert d.ids("voters") == [] and d.ids("surveys", "voter_id") == [] and d.first["areas"] == []
    assert d.first["total_voters"] == 0 and len(d.pages) == 3


def test_first_page_has_settings_and_own_lists(client, area, owner_conn):
    first = download(client, bearer(login(client, area, "sup1").json())).first
    tags = {uuid.UUID(t["id"]) for t in first["lists"]["color_tags"]}
    own = {r[0] for r in owner_conn.execute("SELECT id FROM app.color_tags WHERE tenant_id = %s",
                                            (area.tenant,)).fetchall()}
    assert tags == own and len(own) > 0
    assert first["watermark"].isdigit()
    later = download(client, bearer(login(client, area, "sup1").json()), limit=1).pages[1]
    assert later["lists"] is None and later["settings"] is None and later["areas"] == []


def test_change_during_download_is_at_or_after_the_watermark(client, area, owner_conn):
    """What makes the first delta pull (since=W) complete: anything written after page 1 has sync_xid >= W."""
    h = bearer(login(client, area, "sup1").json())
    first = client.get(f"{API}/sync/pull", headers=h, params={"limit": 1}).json()
    w = int(first["watermark"])
    r = client.put(f"{API}/voters/{area.b1[2]}/survey", headers=h, json={"version": 0, "notes": "during download"})
    assert r.status_code == 200
    xid = owner_conn.execute("SELECT sync_xid::text FROM app.voter_surveys WHERE voter_id = %s",
                             (area.b1[2],)).fetchone()[0]
    assert int(xid) >= w
    # rows written before the download started are below it
    old = owner_conn.execute("SELECT max(sync_xid::text::bigint) FROM app.voters WHERE id = ANY(%s)",
                             (area.b1[:2],)).fetchone()[0]
    assert old < w


@pytest.mark.parametrize("cursor", ["junk", "WyJ4Il0",                     # not a cursor; ["x"]
                                    "WyJ2b3RlcnMiLCBudWxsLCAiYWJjIl0",      # ["voters", null, "abc"]
                                    "WyJmYW1pbGllcyIsIG51bGwsICIxMCJd",     # ["families", null, "10"]
                                    "WyJ2b3RlcnMiLCAibm90LWEtdXVpZCIsICIxMCJd"])  # bad id
def test_bad_cursor(client, area, cursor):
    r = client.get(f"{API}/sync/pull", headers=bearer(login(client, area, "sup1").json()), params={"cursor": cursor})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cursor"
