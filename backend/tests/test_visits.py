"""Visits (7.3): POST /voters/{id}/visits, push type `visit`, visits in the pull.

Fake data only. Role / login / other-area rules: test_endpoint_rules.py.
"""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, create_workspace, login, phone
from test_sync_pull import download

API = "/api/v1"


@pytest.fixture
def ws(make_workspace, owner_conn, client, set_device_status):
    """v[0], v[1] in booth 1, house 12; v[2] in booth 2, house 7."""
    w = make_workspace("visit")
    w.v = []
    for i, (booth, house) in enumerate([(w.booths[0], "12"), (w.booths[0], "12"), (w.booths[1], "7")]):
        vid = uuid.uuid4()
        owner_conn.execute("""INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no,
                                  serial_no, gender, first_name_en, house_no)
                              VALUES (%s, %s, %s, %s, %s, 1, %s, 'F', 'Fake', %s)""",
                           (vid, w.tenant, w.local_body, w.ward, booth, i + 1, house))
        w.v.append(vid)

    def phone_user(username):
        t = login(client, w, username, device=phone(f"phone-visit-{username}")).json()
        set_device_status(t["device"]["id"], "approved")
        return bearer(t)

    w.surveyor, w.supervisor = phone_user("survey1"), phone_user("sup1")
    return w


def body(vid=None, **extra):
    return {"id": str(vid or uuid.uuid4()), "outcome": "not_home", "visited_at": "2026-11-13T10:00:00Z", **extra}


def post(client, headers, voter, b):
    return client.post(f"{API}/voters/{voter}/visits", headers=headers, json=b)


def push(client, headers, voter, b, mid=None):
    it = {"id": str(mid or uuid.uuid4()), "type": "visit", "entity_id": str(voter), "base_version": 0, "data": b}
    r = client.post(f"{API}/sync/push", headers=headers, json={"items": [it]})
    assert r.status_code == 200, r.text
    return r.json()["results"][0]


def count(owner_conn, sql, *args) -> int:
    return owner_conn.execute(sql, args).fetchone()[0]


def test_visit_takes_booth_house_and_kutumb_from_the_voter(client, ws):
    fid = uuid.uuid4()
    assert client.post(f"{API}/families", headers=ws.surveyor,
                       json={"id": str(fid), "booth_id": str(ws.booths[0]), "label": "K"}).status_code == 201
    client.put(f"{API}/voters/{ws.v[0]}/family", headers=ws.surveyor, json={"family_id": str(fid)})
    r = post(client, ws.surveyor, ws.v[0], body(note="Door locked", location={"lat": 15.7, "lng": 73.8}))
    assert r.status_code == 201, r.text
    v = r.json()
    assert (v["booth_id"], v["house_no"], v["family_id"], v["voter_id"]) == (str(ws.booths[0]), "12", str(fid),
                                                                            str(ws.v[0]))
    assert v["outcome"] == "not_home" and v["note"] == "Door locked" and v["lat"] == 15.7
    assert v["visited_by"] == str(ws.users["survey1"])


def test_visit_pushed_twice_is_stored_once(client, ws, owner_conn):
    vid, mid = uuid.uuid4(), uuid.uuid4()
    first = push(client, ws.surveyor, ws.v[0], body(vid), mid=mid)
    assert first["status"] == "applied" and first["visit"]["id"] == str(vid)
    again = push(client, ws.surveyor, ws.v[0], body(vid), mid=mid)  # retry of the same outbox item
    assert again["status"] == "applied" and again["duplicate"] is True and again["visit"]["id"] == str(vid)
    rebuilt = push(client, ws.surveyor, ws.v[0], body(vid, outcome="met"))  # same visit, new outbox id
    assert rebuilt["status"] == "applied" and rebuilt["visit"]["outcome"] == "not_home"  # first one kept
    assert post(client, ws.surveyor, ws.v[0], body(vid)).status_code == 201  # and through REST
    assert count(owner_conn, "SELECT count(*) FROM app.visits WHERE id = %s", vid) == 1


def test_visit_does_not_touch_the_survey(client, ws, owner_conn):
    assert client.put(f"{API}/voters/{ws.v[0]}/survey", headers=ws.surveyor,
                      json={"version": 0, "notes": "x"}).status_code == 200
    post(client, ws.surveyor, ws.v[0], body())
    post(client, ws.surveyor, ws.v[1], body())
    assert owner_conn.execute("SELECT version, last_visit_at FROM app.voter_surveys WHERE voter_id = %s",
                              (ws.v[0],)).fetchone() == (1, None)
    assert count(owner_conn, "SELECT count(*) FROM app.voter_surveys WHERE voter_id = %s", ws.v[1]) == 0


@pytest.mark.parametrize("bad", [
    {"outcome": "away"},
    {"outcome": "met", "revisit_at": "2026-11-14T10:00:00Z"},   # revisit time only with revisit
    {"note": "x" * 2001},
    {"visited_at": "yesterday"},
    {"location": {"lat": 91, "lng": 0}},
])
def test_bad_visit_is_422(client, ws, owner_conn, bad):
    r = post(client, ws.surveyor, ws.v[0], body(**bad))
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", r.text
    res = push(client, ws.surveyor, ws.v[0], body(**bad))
    assert res["status"] == "rejected" and res["error"]["code"] == "validation_error"
    assert count(owner_conn, "SELECT count(*) FROM app.visits WHERE tenant_id = %s", ws.tenant) == 0


def test_revisit_with_a_time(client, ws):
    r = post(client, ws.surveyor, ws.v[0], body(outcome="revisit", revisit_at="2026-11-15T05:30:00Z"))
    assert r.status_code == 201 and r.json()["revisit_at"].startswith("2026-11-15T05:30")


def test_voter_outside_the_area_is_404_and_rejected(client, ws, owner_conn):
    assert post(client, ws.surveyor, ws.v[2], body()).status_code == 404  # booth 2
    res = push(client, ws.surveyor, ws.v[2], body())
    assert res["status"] == "rejected" and res["error"]["code"] == "not_found"
    assert count(owner_conn, "SELECT count(*) FROM app.visits WHERE tenant_id = %s", ws.tenant) == 0


def test_id_of_another_voters_visit_is_409(client, ws):
    vid = uuid.uuid4()
    assert post(client, ws.surveyor, ws.v[0], body(vid)).status_code == 201
    r = post(client, ws.surveyor, ws.v[1], body(vid))
    assert r.status_code == 409 and r.json()["error"]["code"] == "id_in_use"


def test_pull_sends_the_areas_visits(client, ws, make_workspace, set_device_status):
    a = post(client, ws.surveyor, ws.v[0], body()).json()["id"]
    b = post(client, ws.supervisor, ws.v[2], body(outcome="met")).json()["id"]
    assert download(client, ws.surveyor).ids("visits") == [uuid.UUID(a)]  # booth 2's visit is not theirs
    assert sorted(download(client, ws.supervisor).ids("visits")) == sorted([uuid.UUID(a), uuid.UUID(b)])

    w = download(client, ws.surveyor).first["watermark"]
    c = post(client, ws.surveyor, ws.v[1], body(outcome="met")).json()["id"]
    assert download(client, ws.surveyor, since=w).ids("visits") == [uuid.UUID(c)]


def test_other_workspace_never_sees_the_visits(client, ws, owner_conn, set_device_status):
    post(client, ws.surveyor, ws.v[0], body())
    other = create_workspace(owner_conn, "visit-b")
    t = login(client, other, "survey1", device=phone("phone-visit-other")).json()
    set_device_status(t["device"]["id"], "approved")
    assert download(client, bearer(t)).ids("visits") == []
