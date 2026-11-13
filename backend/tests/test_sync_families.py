"""Kutumb Connect in sync (7.2): Kutumbs and members in the pull, push types family_new and family.

Fake data only. Login / role / phone-state rules: test_endpoint_rules.py; the REST routes: test_families.py.
"""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login, phone
from test_sync_pull import download

API = "/api/v1"


@pytest.fixture
def ws(make_workspace, owner_conn, client, set_device_status):
    """Voters v[0..2] in booth 1, v[3] in booth 2; survey1 = booth 1, sup1 = the ward, agent1 = booth 1."""
    w = make_workspace("syncfam", extra_users={"agent1": "booth_agent"})
    owner_conn.execute("INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) VALUES (%s, %s, %s)",
                       (w.tenant, w.users["agent1"], w.booths[0]))
    w.v = []
    for i, booth in enumerate([w.booths[0]] * 3 + [w.booths[1]]):
        vid = uuid.uuid4()
        owner_conn.execute("""INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no,
                                  serial_no, gender, first_name_en) VALUES (%s, %s, %s, %s, %s, 1, %s, 'F', 'Fake')""",
                           (vid, w.tenant, w.local_body, w.ward, booth, i + 1))
        w.v.append(vid)

    def phone_user(username):
        t = login(client, w, username, device=phone(f"phone-syncfam-{username}")).json()
        set_device_status(t["device"]["id"], "approved")
        return bearer(t)

    w.surveyor, w.supervisor, w.agent = phone_user("survey1"), phone_user("sup1"), phone_user("agent1")
    return w


def new_family(fid, booth, label="Fake Kutumb", mid=None):
    return {"id": str(mid or uuid.uuid4()), "type": "family_new", "entity_id": str(fid), "base_version": 0,
            "changed_at": "2026-11-13T10:00:00Z", "data": {"booth_id": str(booth), "label": label}}


def member(voter, mid=None, **data):
    return {"id": str(mid or uuid.uuid4()), "type": "family", "entity_id": str(voter), "base_version": 0,
            "changed_at": "2026-11-13T10:01:00Z", "data": data}


def push(client, headers, *items):
    r = client.post(f"{API}/sync/push", headers=headers, json={"items": list(items)})
    assert r.status_code == 200, r.text
    return r.json()["results"]


def count(owner_conn, sql, *args) -> int:
    return owner_conn.execute(sql, args).fetchone()[0]


def members_of(d) -> dict[uuid.UUID, uuid.UUID | None]:
    return {uuid.UUID(m["voter_id"]): (uuid.UUID(m["family_id"]) if m["family_id"] else None)
            for p in d.pages for m in p["family_members"]}


# --- push ---------------------------------------------------------------------------------
def test_family_made_offline_and_pushed_twice_exists_once(client, ws, owner_conn):
    fid = uuid.uuid4()
    batch = [new_family(fid, ws.booths[0], "Naik Kutumb"), member(ws.v[0], family_id=str(fid)),
             member(ws.v[1], family_id=str(fid))]
    first = push(client, ws.surveyor, *batch)
    assert [(r["status"], r["duplicate"]) for r in first] == [("applied", False)] * 3
    assert first[0]["family"]["id"] == str(fid) and first[0]["family"]["label"] == "Naik Kutumb"
    assert first[1]["family_member"] == {**first[1]["family_member"], "voter_id": str(ws.v[0]), "family_id": str(fid)}

    again = push(client, ws.surveyor, *batch)  # the same outbox items: a retry
    assert [(r["status"], r["duplicate"]) for r in again] == [("applied", True)] * 3
    assert again[0]["family"]["id"] == str(fid) and again[2]["family_member"]["family_id"] == str(fid)

    # The same Kutumb under a new outbox id (e.g. the outbox was rebuilt): still one Kutumb, first name kept.
    [r] = push(client, ws.surveyor, new_family(fid, ws.booths[0], "Other name"))
    assert r["status"] == "applied" and r["duplicate"] is False and r["family"]["label"] == "Naik Kutumb"

    assert count(owner_conn, "SELECT count(*) FROM app.families WHERE id = %s", fid) == 1
    assert count(owner_conn, "SELECT count(*) FROM app.family_members WHERE family_id = %s", fid) == 2
    assert count(owner_conn, "SELECT count(*) FROM app.audit_log WHERE entity_type = 'family_members' "
                             "AND tenant_id = %s", ws.tenant) == 2  # nothing written by the retries


def test_take_out_and_move_by_push(client, ws, owner_conn):
    a, b = uuid.uuid4(), uuid.uuid4()
    push(client, ws.surveyor, new_family(a, ws.booths[0], "A"), new_family(b, ws.booths[0], "B"),
         member(ws.v[0], family_id=str(a)), member(ws.v[1], family_id=str(a)))
    res = push(client, ws.surveyor, member(ws.v[0], family_id=str(b)), member(ws.v[1], leave_family=True),
               member(ws.v[2], leave_family=True))
    assert [r["status"] for r in res] == ["applied"] * 3
    assert res[0]["family_member"]["family_id"] == str(b)
    assert res[1]["family_member"]["family_id"] is None
    assert res[2]["family_member"] is None  # never in a Kutumb: nothing stored
    got = client.get(f"{API}/voters/{ws.v[0]}/family", headers=ws.surveyor).json()["family"]
    assert got["id"] == str(b) and got["member_ids"] == [str(ws.v[0])]
    ops = [r[0] for r in owner_conn.execute(
        "SELECT operation FROM app.sync_mutations WHERE tenant_id = %s AND entity_type = 'family_member' "
        "ORDER BY received_at, entity_id", (ws.tenant,))]
    assert sorted(ops) == ["delete", "delete", "update", "update", "update"]


@pytest.mark.parametrize("case", ["agent_new", "agent_member", "other_booth", "unknown_family", "make_head",
                                  "id_mismatch", "blank_label", "voter_of_other_booth"])
def test_bad_items_are_rejected_alone(client, ws, owner_conn, case):
    fid = uuid.uuid4()
    push(client, ws.supervisor, new_family(fid, ws.booths[0]))
    headers, it, code = ws.surveyor, None, "validation_error"
    if case == "agent_new":
        headers, it, code = ws.agent, new_family(uuid.uuid4(), ws.booths[0]), "forbidden_role"
    elif case == "agent_member":
        headers, it, code = ws.agent, member(ws.v[0], family_id=str(fid)), "forbidden_role"
    elif case == "other_booth":  # booth 2 is outside survey1's area
        it, code = new_family(uuid.uuid4(), ws.booths[1]), "not_found"
    elif case == "unknown_family":
        it, code = member(ws.v[0], family_id=str(uuid.uuid4())), "not_found"
    elif case == "make_head":
        it = member(ws.v[0], family_id=str(fid), make_head=True)
    elif case == "id_mismatch":
        it = new_family(uuid.uuid4(), ws.booths[0])
        it["data"]["id"] = str(uuid.uuid4())
    elif case == "blank_label":
        it = new_family(uuid.uuid4(), ws.booths[0], label="  ")
    else:  # the supervisor sees v[3] (booth 2), but the Kutumb is in booth 1
        headers, it = ws.supervisor, member(ws.v[3], family_id=str(fid))
    ok = member(ws.v[1], family_id=str(fid))
    if case.startswith("agent"):  # the booth agent's item alone; the good one from the surveyor
        [bad], [good] = push(client, headers, it), push(client, ws.surveyor, ok)
    else:
        bad, good = push(client, headers, it, ok)
    assert bad["status"] == "rejected" and bad["error"]["code"] == code, bad
    assert good["status"] == "applied"  # the rest of the batch still applies
    assert count(owner_conn, "SELECT count(*) FROM app.families WHERE tenant_id = %s", ws.tenant) == 1
    assert count(owner_conn, "SELECT count(*) FROM app.family_members WHERE tenant_id = %s", ws.tenant) == 1


# --- pull ---------------------------------------------------------------------------------
@pytest.fixture
def made(client, ws):
    """Kutumb A in booth 1 with v0, v1; Kutumb B in booth 2 with v3."""
    a, b = uuid.uuid4(), uuid.uuid4()
    push(client, ws.supervisor, new_family(a, ws.booths[0], "A"), new_family(b, ws.booths[1], "B"),
         member(ws.v[0], family_id=str(a)), member(ws.v[1], family_id=str(a)), member(ws.v[3], family_id=str(b)))
    return a, b


@pytest.mark.parametrize("limit", [1, 1000])
def test_first_download_has_exactly_the_areas_kutumbs(client, ws, made, limit):
    a, b = made
    d = download(client, ws.surveyor, limit=limit)
    assert d.ids("families") == [a] and d.first["total_families"] == 1
    assert members_of(d) == {ws.v[0]: a, ws.v[1]: a}

    d = download(client, ws.supervisor, limit=limit)
    assert sorted(d.ids("families")) == sorted([a, b]) and d.first["total_families"] == 2
    assert members_of(d) == {ws.v[0]: a, ws.v[1]: a, ws.v[3]: b}
    fam = next(f for p in d.pages for f in p["families"] if f["id"] == str(a))
    assert fam["label"] == "A" and fam["booth_id"] == str(ws.booths[0]) and fam["deleted_at"] is None


def test_delta_brings_renames_and_take_outs(client, ws, made, owner_conn):
    a, _ = made
    w = download(client, ws.surveyor).first["watermark"]
    idle = download(client, ws.surveyor, since=w)
    assert len(idle.pages) == 1 and idle.ids("families") == [] and members_of(idle) == {}

    assert client.patch(f"{API}/families/{a}", headers=ws.surveyor, json={"label": "A renamed"}).status_code == 200
    push(client, ws.surveyor, member(ws.v[1], leave_family=True), member(ws.v[2], family_id=str(a)))
    d = download(client, ws.surveyor, since=w)
    assert d.ids("families") == [a]
    assert next(f for p in d.pages for f in p["families"])["label"] == "A renamed"
    assert members_of(d) == {ws.v[1]: None, ws.v[2]: a}  # v0 did not change

    # A deleted Kutumb comes with deleted_at on a delta, and never on a first download.
    w2 = d.first["watermark"]
    owner_conn.execute("UPDATE app.families SET deleted_at = now() WHERE id = %s", (a,))
    gone = download(client, ws.surveyor, since=w2)
    assert next(f for p in gone.pages for f in p["families"])["deleted_at"] is not None
    assert download(client, ws.surveyor).ids("families") == []


def test_members_of_removed_voters_are_not_sent(client, ws, made, owner_conn):
    owner_conn.execute("UPDATE app.voters SET deleted_at = now() WHERE id = %s", (ws.v[1],))
    assert members_of(download(client, ws.surveyor)) == {ws.v[0]: made[0]}


def test_other_workspace_kutumbs_never_come(client, ws, made, make_workspace, set_device_status):
    other = make_workspace("syncfam-b")
    t = login(client, other, "survey1", device=phone("phone-syncfam-other")).json()
    set_device_status(t["device"]["id"], "approved")
    d = download(client, bearer(t))
    assert d.ids("families") == [] and members_of(d) == {}
