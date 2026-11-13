"""Conflict review (7.10): GET /sync/conflicts, POST /sync/conflicts/{id}/resolve.

Fake data only. Role / login / other-workspace / other-area rules: test_endpoint_rules.py.
"""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login, phone

API = "/api/v1"


@pytest.fixture
def ws(make_workspace, owner_conn, client, set_device_status):
    w = make_workspace("conflicts", extra_users={"survey2": "surveyor"})
    owner_conn.execute("INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) VALUES (%s, %s, %s)",
                       (w.tenant, w.users["survey2"], w.booths[0]))  # the same part as survey1
    w.v = []
    for i in range(3):
        vid = uuid.uuid4()
        owner_conn.execute("""INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no,
                                  serial_no, gender, first_name_en) VALUES (%s, %s, %s, %s, %s, 1, %s, 'F', 'Fake')""",
                           (vid, w.tenant, w.local_body, w.ward, w.booths[0], i + 1))
        w.v.append(vid)
    w.influencer_type = owner_conn.execute(
        "SELECT id FROM app.influencer_types WHERE tenant_id = %s AND is_active ORDER BY sort_order LIMIT 1",
        (w.tenant,)).fetchone()[0]

    def phone_user(username):
        t = login(client, w, username, device=phone(f"phone-conflict-{username}")).json()
        set_device_status(t["device"]["id"], "approved")
        return bearer(t)

    w.surveyor, w.surveyor2, w.sup = phone_user("survey1"), phone_user("survey2"), phone_user("sup1")
    w.boss = bearer(login(client, w, "boss").json())
    return w


def push(client, headers, voter, base, type_="survey", **data):
    r = client.post(f"{API}/sync/push", headers=headers, json={"items": [
        {"id": str(uuid.uuid4()), "type": type_, "entity_id": str(voter), "base_version": base,
         "changed_at": "2026-11-13T10:00:00Z", "data": data}]})
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


def clash(client, ws, voter, server: dict, phone: dict) -> dict[str, str]:
    """The supervisor saves `server` over version 1; the surveyor's phone then sends `phone` on version 1.
    Returns {field: conflict id}."""
    assert push(client, ws.surveyor, voter, 0, notes="start")["status"] == "applied"
    assert push(client, ws.sup, voter, 1, **server)["status"] == "applied"
    r = push(client, ws.surveyor, voter, 1, **phone)
    assert r["status"] == "conflict", r
    items = listed(client, ws.surveyor, entity_id=str(voter))
    return {c["field_name"]: c["id"] for c in items}


def listed(client, headers, **params):
    r = client.get(f"{API}/sync/conflicts", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def resolve(client, headers, cid, keep):
    return client.post(f"{API}/sync/conflicts/{cid}/resolve", headers=headers, json={"keep": keep})


def survey(owner_conn, voter):
    return owner_conn.execute("SELECT version, notes, is_influencer, influencer_type_id, updated_by "
                              "FROM app.voter_surveys WHERE voter_id = %s", (voter,)).fetchone()


def test_keep_phone_writes_the_value_once(client, ws, owner_conn):
    ids = clash(client, ws, ws.v[0], {"notes": "supervisor"}, {"notes": "phone"})
    assert list(ids) == ["notes"]
    c = listed(client, ws.surveyor)[0]
    assert (c["client_value"], c["server_value"], c["client_user"]["username"]) == ("phone", "supervisor", "survey1")

    r = resolve(client, ws.surveyor, ids["notes"], "kept_client")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "kept_client"
    assert survey(owner_conn, ws.v[0])[:2] == (3, "phone")  # written with a new version
    again = resolve(client, ws.surveyor, ids["notes"], "kept_client")
    assert again.status_code == 409 and again.json()["error"]["code"] == "conflict_resolved"
    assert survey(owner_conn, ws.v[0])[:2] == (3, "phone")  # not written twice
    assert listed(client, ws.surveyor) == []
    assert [c["id"] for c in listed(client, ws.surveyor, status="kept_client")] == [ids["notes"]]
    resolved_by = owner_conn.execute("SELECT resolved_by FROM app.sync_conflicts WHERE id = %s",
                                     (ids["notes"],)).fetchone()[0]
    assert resolved_by == ws.users["survey1"]


def test_keep_server_writes_nothing(client, ws, owner_conn):
    ids = clash(client, ws, ws.v[0], {"notes": "supervisor"}, {"notes": "phone"})
    before = survey(owner_conn, ws.v[0])
    r = resolve(client, ws.sup, ids["notes"], "kept_server")
    assert r.status_code == 200 and r.json()["status"] == "kept_server"
    assert survey(owner_conn, ws.v[0]) == before
    assert resolve(client, ws.sup, ids["notes"], "kept_client").status_code == 409


def test_another_surveyors_conflict_is_404_but_the_supervisor_sees_it(client, ws, owner_conn):
    ids = clash(client, ws, ws.v[0], {"notes": "supervisor"}, {"notes": "phone"})
    assert listed(client, ws.surveyor2) == []
    for keep in ("kept_client", "kept_server"):
        r = resolve(client, ws.surveyor2, ids["notes"], keep)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert [c["id"] for c in listed(client, ws.sup)] == [ids["notes"]]
    assert [c["id"] for c in listed(client, ws.boss)] == [ids["notes"]]
    assert owner_conn.execute("SELECT status FROM app.sync_conflicts WHERE id = %s",
                              (ids["notes"],)).fetchone()[0] == "open"


def test_one_field_kept_the_others_stay(client, ws, owner_conn):
    ids = clash(client, ws, ws.v[0], {"notes": "supervisor", "mobile_1": "9876500000"},
                {"notes": "phone", "mobile_1": "9876511111"})
    assert sorted(ids) == ["mobile_1", "notes"]
    assert resolve(client, ws.surveyor, ids["mobile_1"], "kept_client").status_code == 200
    row = owner_conn.execute("SELECT notes, mobile_1 FROM app.voter_surveys WHERE voter_id = %s", (ws.v[0],)).fetchone()
    assert row == ("supervisor", "9876511111")  # only the kept field changed
    assert [c["field_name"] for c in listed(client, ws.surveyor)] == ["notes"]


def test_a_value_that_breaks_a_rule_is_422_until_the_other_field_is_kept(client, ws, owner_conn):
    t = str(ws.influencer_type)
    ids = clash(client, ws, ws.v[0], {"is_influencer": True, "influencer_type_id": t},
                {"is_influencer": False, "influencer_type_id": None})
    bad = resolve(client, ws.surveyor, ids["is_influencer"], "kept_client")  # type would stay without "influencer"
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "validation_error"
    assert survey(owner_conn, ws.v[0])[2:4] == (True, ws.influencer_type)
    assert resolve(client, ws.surveyor, ids["influencer_type_id"], "kept_client").status_code == 200
    assert resolve(client, ws.surveyor, ids["is_influencer"], "kept_client").status_code == 200
    assert survey(owner_conn, ws.v[0])[:4] == (4, None, False, None)  # a push sends the whole survey


def test_new_voter_conflict_kept_from_the_phone(client, ws, owner_conn):
    nid = str(uuid.uuid4())
    body = {"id": nid, "full_name_en": "Fake Person", "ward_id": str(ws.ward), "booth_id": str(ws.booths[0])}
    assert client.post(f"{API}/new-voters", headers=ws.surveyor, json=body).status_code == 201
    data = {k: v for k, v in body.items() if k != "id"}
    assert push(client, ws.sup, nid, 1, "new_voter_update", **data, notes="supervisor")["status"] == "applied"
    assert push(client, ws.surveyor, nid, 1, "new_voter_update", **data, notes="phone")["status"] == "conflict"
    [c] = listed(client, ws.surveyor, entity_id=nid)
    assert (c["entity_type"], c["field_name"]) == ("new_voter", "notes")
    assert resolve(client, ws.surveyor, c["id"], "kept_client").status_code == 200
    assert owner_conn.execute("SELECT version, notes FROM app.new_voters WHERE id = %s", (nid,)).fetchone() == (3, "phone")


def test_list_pages_newest_first_and_filters(client, ws):
    made = []
    for v in ws.v:
        made.append(clash(client, ws, v, {"notes": "supervisor"}, {"notes": "phone"})["notes"])
    whole = [c["id"] for c in listed(client, ws.sup)]
    assert whole == made[::-1]
    paged, cursor = [], None
    while True:
        r = client.get(f"{API}/sync/conflicts", headers=ws.sup, params={"limit": 2, **({"cursor": cursor} if cursor else {})})
        paged += [c["id"] for c in r.json()["items"]]
        cursor = r.json()["next_cursor"]
        if not cursor:
            break
    assert paged == whole
    assert [c["id"] for c in listed(client, ws.sup, entity_id=str(ws.v[1]))] == [made[1]]
    bad = client.post(f"{API}/sync/conflicts/{made[0]}/resolve", headers=ws.sup, json={"keep": "open"})
    assert bad.status_code == 422
