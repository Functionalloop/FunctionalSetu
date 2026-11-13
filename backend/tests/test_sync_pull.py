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

    @property
    def gone(self) -> list[uuid.UUID]:
        return [uuid.UUID(i) for p in self.pages for i in p["gone_voter_ids"]]


def download(client, headers, limit=1000, since: str | None = None) -> Download:
    """Every page of one pull: a first download, or a delta pull when `since` is given."""
    d, cursor = Download(), None
    while True:
        params = {"limit": limit, **({"cursor": cursor} if cursor else {"since": since} if since else {})}
        r = client.get(f"{API}/sync/pull", headers=headers, params=params)
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
    assert d.first["total_voters"] == 0 and len(d.pages) == 1  # nothing to page through


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


def _c(*key) -> str:
    from app.paging import encode_cursor
    return encode_cursor(list(key))


@pytest.mark.parametrize("cursor", [
    "junk",
    _c("x"),                                           # wrong length
    _c(["voters"], None, "10"),                        # old 3-part format
    _c(["voters"], None, "abc", None),                 # bad watermark
    _c(["voters"], None, "10", "x1"),                  # bad since
    _c([], None, "10", None),                          # no phase left
    _c("voters", None, "10", None),                    # phases not a list
    _c(["no_such_phase"], None, "10", None),           # unknown phase
    _c(["gone"], None, "10", None),                    # gone only exists on a delta pull
    _c(["voters"], "not-a-uuid", "10", None),          # bad id
])
def test_bad_cursor(client, area, cursor):
    r = client.get(f"{API}/sync/pull", headers=bearer(login(client, area, "sup1").json()), params={"cursor": cursor})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cursor"


# --- delta pull (since=W) ---------------------------------------------------------------------
def start(client, headers) -> str:
    """A complete first download; returns its watermark W."""
    return download(client, headers).first["watermark"]


def test_survey_changed_after_w_comes_back(client, area):
    h = bearer(login(client, area, "sup1").json())
    w = start(client, h)
    r = client.put(f"{API}/voters/{area.b1[2]}/survey", headers=h, json={"version": 0, "notes": "new"})
    assert r.status_code == 200
    d = download(client, h, since=w)
    assert d.ids("surveys", "voter_id") == [area.b1[2]]
    assert [s["notes"] for p in d.pages for s in p["surveys"]] == ["new"]
    assert d.ids("voters") == [] and d.first["total_surveys"] == 1  # roll rows did not change
    assert int(d.first["watermark"]) >= int(w)


def test_nothing_changed_sends_no_rows(client, area):
    h = bearer(login(client, area, "sup1").json())
    d = download(client, h, since=start(client, h))
    assert d.ids("voters") == d.ids("surveys", "voter_id") == d.gone == []
    assert d.first["areas"] == [] and d.first["settings"] is None
    assert d.first["lists"] == {"castes": [], "professions": [], "color_tags": [], "custom_field_labels": [],
                                "influencer_types": []}
    assert set(map(uuid.UUID, d.first["area_ids"])) == {area.ward, *area.booths, area.section}
    assert len(d.pages) == 1  # an idle sync is one request


def test_removed_voter_comes_with_deleted_at_and_without_survey(client, area, owner_conn):
    h = bearer(login(client, area, "sup1").json())
    w = start(client, h)
    owner_conn.execute("UPDATE app.voters SET deleted_at = now() WHERE id = %s", (area.b1[1],))
    d = download(client, h, since=w)
    [v] = [v for p in d.pages for v in p["voters"]]
    assert v["id"] == str(area.b1[1]) and v["deleted_at"] is not None
    assert d.ids("surveys", "voter_id") == []


def test_voter_moved_out_of_area_is_gone(client, area, owner_conn, set_device_status):
    surveyor = phone_headers(client, area, "survey1", set_device_status, "phone-pull-0003")
    supervisor = bearer(login(client, area, "sup1").json())
    w_surveyor, w_supervisor = start(client, surveyor), start(client, supervisor)
    owner_conn.execute("UPDATE app.voters SET booth_id = %s WHERE id = %s", (area.booths[1], area.b1[0]))

    d = download(client, surveyor, since=w_surveyor)            # booth 1 only: the voter left
    assert d.ids("voters") == [] and d.gone == [area.b1[0]]
    d = download(client, supervisor, since=w_supervisor)        # the whole ward: still there, new booth
    [v] = [v for p in d.pages for v in p["voters"]]
    assert v["booth_id"] == str(area.booths[1])
    assert d.gone == []


def test_new_voter_in_area_comes_and_one_outside_does_not(client, area, owner_conn, set_device_status):
    surveyor = phone_headers(client, area, "survey1", set_device_status, "phone-pull-0004")
    w = start(client, surveyor)
    new_in, new_out = uuid.uuid4(), uuid.uuid4()
    for vid, booth, serial in ((new_in, area.booths[0], 901), (new_out, area.booths[1], 902)):
        owner_conn.execute("""INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no,
                                  serial_no, gender, first_name_en) VALUES (%s, %s, %s, %s, %s, 1, %s, 'F', 'New')""",
                           (vid, area.tenant, area.local_body, area.ward, booth, serial))
    d = download(client, surveyor, since=w)
    assert d.ids("voters") == [new_in]
    assert d.gone == [new_out]  # outside the area: its id only, never the row


def test_area_ids_follow_assignments(client, area, owner_conn, set_device_status):
    surveyor = phone_headers(client, area, "survey1", set_device_status, "phone-pull-0005")
    w = start(client, surveyor)
    owner_conn.execute("INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) VALUES (%s, %s, %s)",
                       (area.tenant, area.users["survey1"], area.booths[1]))
    d = download(client, surveyor, since=w)
    assert set(map(uuid.UUID, d.first["area_ids"])) == {area.booths[0], area.section, area.booths[1]}
    # booth 2 itself did not change, so it is not in `areas`: the phone sees an unknown id and downloads again
    assert d.first["areas"] == []
    owner_conn.execute("DELETE FROM app.user_area_assignments WHERE user_id = %s AND geo_unit_id = %s",
                       (area.users["survey1"], area.booths[0]))
    d = download(client, surveyor, since=w)
    assert set(map(uuid.UUID, d.first["area_ids"])) == {area.booths[1]}


def test_switched_off_area_leaves_area_ids(client, area, owner_conn):
    h = bearer(login(client, area, "sup1").json())
    w = start(client, h)
    owner_conn.execute("UPDATE app.geo_units SET is_active = false WHERE id = %s", (area.booths[1],))
    d = download(client, h, since=w)
    assert set(map(uuid.UUID, d.first["area_ids"])) == {area.ward, area.booths[0], area.section}


def test_changed_list_entry_and_settings(client, area, owner_conn):
    h = bearer(login(client, area, "sup1").json())
    w = start(client, h)
    owner_conn.execute("UPDATE app.color_tags SET label_en = 'Ours!' WHERE tenant_id = %s AND code = 'green'",
                       (area.tenant,))
    owner_conn.execute("""INSERT INTO app.tenant_settings (tenant_id, election_name_en) VALUES (%s, 'Test poll')
                          ON CONFLICT (tenant_id) DO UPDATE SET election_name_en = 'Test poll'""", (area.tenant,))
    first = download(client, h, since=w).first
    assert [t["label_en"] for t in first["lists"]["color_tags"]] == ["Ours!"]
    assert first["lists"]["castes"] == []
    assert first["settings"]["election_name_en"] == "Test poll"


def test_delta_paging_sends_each_change_once(client, area, owner_conn):
    h = bearer(login(client, area, "admin1").json())
    w = start(client, h)
    owner_conn.execute("UPDATE app.voters SET house_no = '9Z' WHERE id = ANY(%s)", (area.b1 + area.b2,))
    d = download(client, h, limit=1, since=w)
    assert sorted(d.ids("voters")) == sorted(area.b1 + area.b2)
    assert d.first["total_voters"] == 5
    assert len({p["watermark"] for p in d.pages}) == 1


@pytest.mark.parametrize("since", [None, "1"])
def test_blocked_phone_is_told_to_wipe(client, area, set_device_status, since):
    t = login(client, area, "survey1", device=phone("phone-pull-0006")).json()
    set_device_status(t["device"]["id"], "blocked")
    r = client.get(f"{API}/sync/pull", headers=bearer(t), params={"since": since} if since else {})
    assert r.status_code == 200 and r.json()["wipe"] is True
    assert r.json()["voters"] == [] and r.json()["area_ids"] is None


def test_pending_phone_still_403(client, area):
    t = login(client, area, "survey1", device=phone("phone-pull-0007")).json()
    r = client.get(f"{API}/sync/pull", headers=bearer(t), params={"since": "1"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "device_pending"


@pytest.mark.parametrize("since", ["abc", "-1", "1.5", "123456789012345678901"])
def test_bad_since_is_422(client, area, since):
    r = client.get(f"{API}/sync/pull", headers=bearer(login(client, area, "sup1").json()), params={"since": since})
    assert r.status_code == 422
