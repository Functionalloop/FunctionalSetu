"""Assignments (9.2): GET/PUT /users/{id}/assignments. Generic 401 / 403 / 404 rules: test_endpoint_rules.py."""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login, phone

API = "/api/v1"


def code(resp) -> str:
    return resp.json()["error"]["code"]


@pytest.fixture
def ws(make_workspace):
    return make_workspace()


@pytest.fixture
def admin(client, ws):
    return bearer(login(client, ws, "admin1").json())


def put(client, headers, user_id, *area_ids):
    return client.put(f"{API}/users/{user_id}/assignments", headers=headers,
                      json={"area_ids": [str(a) for a in area_ids]})


def area_ids(resp) -> list[str]:
    assert resp.status_code == 200, resp.text
    return [a["id"] for a in resp.json()["areas"]]


def test_get_shows_the_assigned_areas(client, ws, admin):
    assert area_ids(client.get(f"{API}/users/{ws.users['survey1']}/assignments", headers=admin)) == [
        str(ws.booths[0])]
    assert area_ids(client.get(f"{API}/users/{ws.users['sup1']}/assignments", headers=admin)) == [str(ws.ward)]


def test_put_replaces_the_list(client, ws, admin, owner_conn):
    uid = ws.users["survey1"]
    assert area_ids(put(client, admin, uid, ws.booths[1], ws.ward, ws.booths[1])) == [
        str(ws.ward), str(ws.booths[1])]  # tree order, a repeat stored once
    by = owner_conn.execute("SELECT DISTINCT assigned_by FROM app.user_area_assignments WHERE user_id = %s",
                            (uid,)).fetchall()
    assert by == [(ws.users["admin1"],)]
    listed = {u["id"]: u for u in client.get(f"{API}/users", headers=admin).json()["items"]}
    assert sorted(listed[str(uid)]["area_ids"]) == sorted([str(ws.ward), str(ws.booths[1])])  # also in the list
    assert listed[str(ws.users["admin1"])]["area_ids"] == []
    assert area_ids(put(client, admin, uid)) == []


def test_after_a_booth_is_removed_the_next_pull_tells_the_phone_to_drop_it(client, ws, admin, set_device_status):
    t = login(client, ws, "survey1", device=phone("assign-phone")).json()
    set_device_status(t["device"]["id"], "approved")
    h = bearer(t)
    first = client.get(f"{API}/sync/pull", headers=h).json()
    assert str(ws.booths[0]) in first["area_ids"] and str(ws.booths[1]) not in first["area_ids"]

    put(client, admin, ws.users["survey1"], ws.booths[1])
    delta = client.get(f"{API}/sync/pull", headers=h, params={"since": first["watermark"]}).json()
    assert str(ws.booths[0]) not in delta["area_ids"]
    assert str(ws.booths[1]) in delta["area_ids"]  # new: the phone runs a first download again
    # and booth 1's voters are out of reach at once
    r = client.get(f"{API}/voters", headers=h, params={"booth_id": str(ws.booths[0])})
    assert r.status_code == 404


def test_only_wards_and_booths_of_the_users_constituency(client, ws, admin, owner_conn):
    uid = ws.users["survey1"]
    r = put(client, admin, uid, ws.local_body)
    assert r.status_code == 422, r.text
    lb2, ward2 = uuid.uuid4(), uuid.uuid4()
    owner_conn.execute("""INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, number, name_mr)
                          VALUES (%s, %s, NULL, 'local_body', '2', NULL, 'X'), (%s, %s, %s, 'ward', '1', 1, 'X')""",
                       (lb2, ws.tenant, ward2, ws.tenant, lb2))
    boss = bearer(login(client, ws, "boss").json())
    for headers in (admin, boss):  # also a super admin: the user's own constituency only
        r = put(client, headers, uid, ws.booths[0], ward2)
        assert r.status_code == 404 and code(r) == "not_found", r.text
        r = put(client, headers, uid, uuid.uuid4())
        assert r.status_code == 404
    # nothing changed by the refused calls
    assert area_ids(client.get(f"{API}/users/{uid}/assignments", headers=admin)) == [str(ws.booths[0])]


def test_admins_have_no_assignments(client, ws, admin):
    boss = bearer(login(client, ws, "boss").json())
    r = put(client, boss, ws.users["admin1"], ws.ward)
    assert r.status_code == 422
    r = put(client, admin, ws.users["admin1"], ws.ward)  # own account, and an admin: refused either way
    assert r.status_code in (403, 422)
