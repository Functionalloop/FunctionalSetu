"""Kutumb Connect (7.1): Kutumbs made by hand and their members.

Role, login and other-workspace / other-area rules for these routes are in test_endpoint_rules.py;
fake data only.
"""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, create_workspace, login, phone

API = "/api/v1"


@pytest.fixture
def ws(make_workspace, owner_conn):
    """Voters 1-3 in booth 1, voter 4 in booth 2; agent1 = booth agent of booth 1."""
    w = make_workspace("fam", extra_users={"agent1": "booth_agent"})
    w.voters = []
    for serial, booth in ((1, w.booths[0]), (2, w.booths[0]), (3, w.booths[0]), (4, w.booths[1])):
        vid = uuid.uuid4()
        owner_conn.execute(
            """INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no,
                                       first_name_en, last_name_en, gender, age)
               VALUES (%s, %s, %s, %s, %s, 1, %s, 'Fake', 'Voter', 'M', 30)""",
            (vid, w.tenant, w.local_body, w.ward, booth, serial))
        w.voters.append(vid)
    owner_conn.execute("INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) VALUES (%s, %s, %s)",
                       (w.tenant, w.users["agent1"], w.booths[0]))
    return w


def _token(client, ws, username, set_device_status):
    t = login(client, ws, username, device=phone(f"phone-fam-{username}")).json()
    set_device_status(t["device"]["id"], "approved")
    return bearer(t)


@pytest.fixture
def surveyor(client, ws, set_device_status):
    return _token(client, ws, "survey1", set_device_status)


@pytest.fixture
def supervisor(client, ws, set_device_status):
    return _token(client, ws, "sup1", set_device_status)


def make(client, headers, booth, label="Patil Kutumb", fid=None):
    return client.post(f"{API}/families", headers=headers,
                       json={"id": str(fid or uuid.uuid4()), "booth_id": str(booth), "label": label})


def put(client, headers, voter, **body):
    return client.put(f"{API}/voters/{voter}/family", headers=headers, json=body)


def test_make_a_kutumb_and_add_members(client, ws, surveyor):
    fid = uuid.uuid4()
    r = make(client, surveyor, ws.booths[0], label="  Ramesh Naik  ", fid=fid)
    assert r.status_code == 201, r.text
    fam = r.json()
    assert fam["id"] == str(fid) and fam["label"] == "Ramesh Naik"  # ends trimmed
    assert fam["booth_id"] == str(ws.booths[0]) and fam["ward_id"] == str(ws.ward)
    assert fam["source"] == "manual" and fam["house_no"] is None and fam["member_ids"] == []
    assert "head_voter_id" not in fam  # no head (12 Nov)

    for v in (ws.voters[1], ws.voters[0]):
        r = put(client, surveyor, v, family_id=str(fid))
        assert r.status_code == 200, r.text
    assert r.json()["family"]["member_ids"] == [str(ws.voters[0]), str(ws.voters[1])]  # roll order

    got = client.get(f"{API}/voters/{ws.voters[0]}/family", headers=surveyor).json()
    assert got["family"]["id"] == str(fid) and len(got["family"]["member_ids"]) == 2
    assert client.get(f"{API}/voters/{ws.voters[2]}/family", headers=surveyor).json() == {"family": None}

    page = client.get(f"{API}/booths/{ws.booths[0]}/families", headers=surveyor).json()
    assert [f["id"] for f in page["items"]] == [str(fid)] and page["next_cursor"] is None


def test_repeat_id_is_stored_once_and_keeps_the_first_name(client, ws, surveyor, owner_conn):
    fid = uuid.uuid4()
    assert make(client, surveyor, ws.booths[0], label="First", fid=fid).status_code == 201
    again = make(client, surveyor, ws.booths[0], label="Second", fid=fid)
    assert again.status_code == 201 and again.json()["label"] == "First"
    assert owner_conn.execute("SELECT count(*) FROM app.families WHERE id = %s", (fid,)).fetchone()[0] == 1


def test_id_of_another_workspace_is_409(client, ws, surveyor, owner_conn):
    other = create_workspace(owner_conn, "fam-b")
    fid = uuid.uuid4()
    owner_conn.execute("""INSERT INTO app.families (id, tenant_id, ward_id, booth_id, label)
                          VALUES (%s, %s, %s, %s, 'Theirs')""", (fid, other.tenant, other.ward, other.booths[0]))
    r = make(client, surveyor, ws.booths[0], fid=fid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "id_in_use"
    assert owner_conn.execute("SELECT label FROM app.families WHERE id = %s", (fid,)).fetchone()[0] == "Theirs"


def test_a_voter_is_in_one_kutumb_at_most(client, ws, surveyor, owner_conn):
    a = make(client, surveyor, ws.booths[0], label="A").json()["id"]
    b = make(client, surveyor, ws.booths[0], label="B").json()["id"]
    v = ws.voters[0]
    assert put(client, surveyor, v, family_id=a).json()["family"]["id"] == a
    moved = put(client, surveyor, v, family_id=b)
    assert moved.status_code == 200 and moved.json()["family"]["member_ids"] == [str(v)]
    items = {f["label"]: f["member_ids"] for f in
             client.get(f"{API}/booths/{ws.booths[0]}/families", headers=surveyor).json()["items"]}
    assert items == {"A": [], "B": [str(v)]}
    assert owner_conn.execute("SELECT count(*) FROM app.family_members WHERE voter_id = %s", (v,)).fetchone()[0] == 1


def test_take_a_member_out(client, ws, surveyor, owner_conn):
    fid = make(client, surveyor, ws.booths[0]).json()["id"]
    v = ws.voters[0]
    put(client, surveyor, v, family_id=fid)
    r = put(client, surveyor, v, leave_family=True)
    assert r.status_code == 200 and r.json() == {"family": None}
    assert client.get(f"{API}/voters/{v}/family", headers=surveyor).json() == {"family": None}
    # The row stays with no family, so a delta pull (7.2) can tell the phones.
    assert owner_conn.execute("SELECT family_id FROM app.family_members WHERE voter_id = %s",
                              (v,)).fetchone()[0] is None
    # Leaving when in no Kutumb changes nothing and makes no row.
    assert put(client, surveyor, ws.voters[1], leave_family=True).json() == {"family": None}
    assert owner_conn.execute("SELECT count(*) FROM app.family_members WHERE voter_id = %s",
                              (ws.voters[1],)).fetchone()[0] == 0


def test_repeat_put_writes_nothing(client, ws, surveyor, owner_conn):
    fid = make(client, surveyor, ws.booths[0]).json()["id"]
    v = ws.voters[0]
    put(client, surveyor, v, family_id=fid)
    audit = "SELECT count(*) FROM app.audit_log WHERE entity_type = 'family_members' AND entity_id = %s"
    before = owner_conn.execute(audit, (str(v),)).fetchone()[0]
    xid = owner_conn.execute("SELECT sync_xid FROM app.family_members WHERE voter_id = %s", (v,)).fetchone()[0]
    assert put(client, surveyor, v, family_id=fid).status_code == 200
    assert owner_conn.execute(audit, (str(v),)).fetchone()[0] == before == 1
    assert owner_conn.execute("SELECT sync_xid FROM app.family_members WHERE voter_id = %s",
                              (v,)).fetchone()[0] == xid


def test_membership_does_not_touch_the_survey(client, ws, surveyor):
    """Why members have their own table: the survey's version and first save are not disturbed."""
    fid = make(client, surveyor, ws.booths[0]).json()["id"]
    surveyed, fresh = ws.voters[0], ws.voters[1]
    assert client.put(f"{API}/voters/{surveyed}/survey", headers=surveyor,
                      json={"version": 0, "notes": "x"}).json()["version"] == 1
    put(client, surveyor, surveyed, family_id=fid)
    put(client, surveyor, fresh, family_id=fid)
    assert client.get(f"{API}/voters/{fresh}", headers=surveyor).json()["survey"] is None
    assert client.put(f"{API}/voters/{surveyed}/survey", headers=surveyor,
                      json={"version": 1, "notes": "y"}).status_code == 200
    assert client.put(f"{API}/voters/{fresh}/survey", headers=surveyor,
                      json={"version": 0, "notes": "first"}).status_code == 200


def test_rename(client, ws, surveyor):
    fid = make(client, surveyor, ws.booths[0], label="Old").json()["id"]
    r = client.patch(f"{API}/families/{fid}", headers=surveyor, json={"label": "New name"})
    assert r.status_code == 200 and r.json()["label"] == "New name"
    assert client.patch(f"{API}/families/{fid}", headers=surveyor, json={"label": "   "}).status_code == 422


def test_kutumb_in_booth_2_is_404_for_a_booth_1_surveyor(client, ws, surveyor, supervisor):
    theirs = make(client, supervisor, ws.booths[1], label="Booth two").json()["id"]
    ours = make(client, surveyor, ws.booths[0]).json()["id"]
    put(client, supervisor, ws.voters[3], family_id=theirs)
    for r in (client.patch(f"{API}/families/{theirs}", headers=surveyor, json={"label": "x"}),
              client.get(f"{API}/booths/{ws.booths[1]}/families", headers=surveyor),
              make(client, surveyor, ws.booths[1]),
              put(client, surveyor, ws.voters[0], family_id=theirs),
              client.get(f"{API}/voters/{ws.voters[3]}/family", headers=surveyor)):
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", r.text
    # The supervisor sees both booths, but a voter only joins a Kutumb of their own booth.
    r = put(client, supervisor, ws.voters[0], family_id=theirs)
    assert r.status_code == 422 and "another part" in r.json()["error"]["message"]
    r = put(client, supervisor, ws.voters[3], family_id=ours)
    assert r.status_code == 422
    assert client.get(f"{API}/voters/{ws.voters[3]}/family", headers=supervisor).json()["family"]["id"] == theirs


def test_booth_agent_cannot_make_or_change_one(client, ws, surveyor, set_device_status):
    agent = _token(client, ws, "agent1", set_device_status)
    fid = make(client, surveyor, ws.booths[0]).json()["id"]
    for r in (make(client, agent, ws.booths[0]),
              client.patch(f"{API}/families/{fid}", headers=agent, json={"label": "x"}),
              put(client, agent, ws.voters[0], family_id=fid)):
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden_role"
    # but can read
    assert client.get(f"{API}/booths/{ws.booths[0]}/families", headers=agent).status_code == 200
    assert client.get(f"{API}/voters/{ws.voters[0]}/family", headers=agent).status_code == 200


@pytest.mark.parametrize("body", [
    {"family_id": "FID", "make_head": True},  # no head (12 Nov)
    {"make_head": True},
    {"family_id": "FID", "leave_family": True},
    {},
    {"leave_family": False},
    {"new_family_id": "FID", "new_family_label": "x"},  # a Kutumb is made with POST /families
])
def test_bad_change_is_422(client, ws, surveyor, owner_conn, body):
    fid = make(client, surveyor, ws.booths[0]).json()["id"]
    body = {k: (fid if v == "FID" else v) for k, v in body.items()}
    r = put(client, surveyor, ws.voters[0], **body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", r.text
    assert owner_conn.execute("SELECT count(*) FROM app.family_members WHERE voter_id = %s",
                              (ws.voters[0],)).fetchone()[0] == 0


def test_not_a_booth_or_unknown_kutumb(client, ws, surveyor, supervisor):
    assert make(client, supervisor, ws.ward).status_code == 404  # a ward, not a booth
    assert client.get(f"{API}/booths/{ws.ward}/families", headers=supervisor).status_code == 404
    assert put(client, surveyor, ws.voters[0], family_id=str(uuid.uuid4())).status_code == 404
    assert make(client, surveyor, ws.booths[0], label="").status_code == 422


def test_removed_voter_is_not_listed_as_member(client, ws, surveyor, owner_conn):
    fid = make(client, surveyor, ws.booths[0]).json()["id"]
    for v in ws.voters[:2]:
        put(client, surveyor, v, family_id=fid)
    owner_conn.execute("UPDATE app.voters SET deleted_at = now() WHERE id = %s", (ws.voters[1],))
    got = client.get(f"{API}/voters/{ws.voters[0]}/family", headers=surveyor).json()
    assert got["family"]["member_ids"] == [str(ws.voters[0])]


def test_booth_list_pages_by_name(client, ws, surveyor):
    for label in ("charu", "Anand", "bala", "Deshpande", "anil"):
        make(client, surveyor, ws.booths[0], label=label)
    seen, cursor = [], None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = client.get(f"{API}/booths/{ws.booths[0]}/families", headers=surveyor, params=params).json()
        seen += [f["label"] for f in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == ["Anand", "anil", "bala", "charu", "Deshpande"]
    bad = client.get(f"{API}/booths/{ws.booths[0]}/families", headers=surveyor, params={"cursor": "zzz"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_cursor"
