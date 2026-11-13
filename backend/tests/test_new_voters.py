"""Eligible but Not Registered (7.5): /new-voters, push types new_voter / new_voter_update, the pull.

Fake data only. Role / login / other-workspace / other-area rules: test_endpoint_rules.py.
"""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login, phone
from test_sync_pull import download

API = "/api/v1"


@pytest.fixture
def ws(make_workspace, owner_conn, client, set_device_status):
    """survey1: booth 1 only; sup1: the whole ward (booths 1 and 2); agent1: booth agent of booth 1."""
    w = make_workspace("newv", extra_users={"agent1": "booth_agent"})
    owner_conn.execute("INSERT INTO app.user_area_assignments (tenant_id, user_id, geo_unit_id) VALUES (%s, %s, %s)",
                       (w.tenant, w.users["agent1"], w.booths[0]))

    def phone_user(username):
        t = login(client, w, username, device=phone(f"phone-newv-{username}")).json()
        set_device_status(t["device"]["id"], "approved")
        return bearer(t)

    w.surveyor, w.supervisor, w.agent = phone_user("survey1"), phone_user("sup1"), phone_user("agent1")
    return w


def person(ws, booth=0, **extra):
    """A body for POST (booth=None: Village Panchayat only)."""
    b = {"id": str(uuid.uuid4()), "full_name_en": "Fake Person", "ward_id": str(ws.ward),
         "gender": "F", "dob": "2007-05-01", "mobile": "9876543210"}
    if booth is not None:
        b["booth_id"] = str(ws.booths[booth])
    return {**b, **extra}


def add(client, headers, body):
    return client.post(f"{API}/new-voters", headers=headers, json=body)


def patch(client, headers, nid, body):
    return client.patch(f"{API}/new-voters/{nid}", headers=headers, json=body)


def edit_body(created: dict, **change) -> dict:
    keep = ("full_name_en", "full_name_mr", "relative_name", "dob", "gender", "mobile", "address", "ward_id",
            "booth_id", "family_id", "form6_status", "notes", "version")
    return {**{k: created[k] for k in keep}, **change}


def push(client, headers, *items):
    r = client.post(f"{API}/sync/push", headers=headers, json={"items": list(items)})
    assert r.status_code == 200, r.text
    return r.json()["results"]


def item(type_, entity, data, base=0, mid=None):
    return {"id": str(mid or uuid.uuid4()), "type": type_, "entity_id": str(entity), "base_version": base,
            "data": data}


def count(owner_conn, sql, *args) -> int:
    return owner_conn.execute(sql, args).fetchone()[0]


def test_add_and_list(client, ws):
    r = add(client, ws.surveyor, person(ws, notes="  Moved here in June  ", address=""))
    assert r.status_code == 201, r.text
    nv = r.json()
    assert nv["version"] == 1 and nv["form6_status"] == "not_applied" and nv["matched_voter_id"] is None
    assert nv["notes"] == "Moved here in June" and nv["address"] is None  # trimmed; blank = no value
    assert nv["created_by"] == str(ws.users["survey1"])
    listed = client.get(f"{API}/new-voters", headers=ws.surveyor).json()["items"]
    assert [x["id"] for x in listed] == [nv["id"]]


def test_same_id_twice_is_stored_once(client, ws, owner_conn):
    body = person(ws)
    assert add(client, ws.surveyor, body).status_code == 201
    again = add(client, ws.surveyor, {**body, "full_name_en": "Other Name"})
    assert again.status_code == 201 and again.json()["full_name_en"] == "Fake Person"  # first copy kept
    res = push(client, ws.surveyor, item("new_voter", body["id"], {k: v for k, v in body.items() if k != "id"}))
    assert res[0]["status"] == "applied" and res[0]["new_voter"]["id"] == body["id"]
    assert count(owner_conn, "SELECT count(*) FROM app.new_voters WHERE id = %s", body["id"]) == 1


@pytest.mark.parametrize("bad", [
    {"full_name_en": "   "},                      # no name
    {"dob": "2999-01-01"},                        # future date of birth
    {"mobile": "12345"},
    {"form6_status": "sent"},
    {"family_id": str(uuid.uuid4()), "booth_id": None},  # a Kutumb needs a part
])
def test_bad_body_is_422(client, ws, bad):
    r = add(client, ws.surveyor, person(ws, **bad))
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", r.text


def test_part_and_kutumb_must_match(client, ws, make_workspace, owner_conn):
    other_ward = uuid.uuid4()
    owner_conn.execute("""INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, number, name_mr)
                          VALUES (%s, %s, %s, 'ward', '2', 2, 'W2')""", (other_ward, ws.tenant, ws.local_body))
    r = add(client, ws.supervisor, person(ws, ward_id=str(other_ward)))  # booth 1 is not in ward 2
    assert r.status_code == 422 and "Village Panchayat" in r.json()["error"]["message"]

    fid = str(uuid.uuid4())
    assert client.post(f"{API}/families", headers=ws.supervisor,
                       json={"id": fid, "booth_id": str(ws.booths[1]), "label": "K"}).status_code == 201
    r = add(client, ws.supervisor, person(ws, booth=0, family_id=fid))  # the Kutumb is in booth 2
    assert r.status_code == 422 and "Kutumb" in r.json()["error"]["message"]
    assert add(client, ws.supervisor, person(ws, booth=1, family_id=fid)).status_code == 201


def test_village_panchayat_only_record_needs_the_ward_in_the_area(client, ws):
    ward_only = person(ws, booth=None)
    assert add(client, ws.surveyor, ward_only).status_code == 404  # survey1 has booth 1, not the ward
    assert add(client, ws.supervisor, ward_only).status_code == 201
    assert client.get(f"{API}/new-voters", headers=ws.surveyor).json()["items"] == []
    assert [x["id"] for x in client.get(f"{API}/new-voters", headers=ws.supervisor).json()["items"]] == [
        ward_only["id"]]


def test_other_part_is_not_seen(client, ws):
    b2 = add(client, ws.supervisor, person(ws, booth=1)).json()
    assert client.get(f"{API}/new-voters", headers=ws.surveyor).json()["items"] == []
    assert patch(client, ws.surveyor, b2["id"], edit_body(b2)).status_code == 404
    assert add(client, ws.surveyor, person(ws, booth=1)).status_code == 404


def test_edit_raises_the_version_and_stale_is_409(client, ws):
    nv = add(client, ws.surveyor, person(ws)).json()
    r = patch(client, ws.surveyor, nv["id"], edit_body(nv, form6_status="applied", notes="Form 6 given"))
    assert r.status_code == 200, r.text
    assert (r.json()["version"], r.json()["form6_status"]) == (2, "applied")

    stale = patch(client, ws.supervisor, nv["id"], edit_body(nv, notes="old copy"))  # still version 1
    assert stale.status_code == 409
    err = stale.json()["error"]
    assert err["code"] == "version_conflict"
    assert err["current"]["version"] == 2 and err["current"]["notes"] == "Form 6 given"


def test_list_filters_and_pages(client, ws):
    ids = [add(client, ws.supervisor, person(ws, booth=i % 2)).json()["id"] for i in range(5)]
    nv = client.get(f"{API}/new-voters", headers=ws.supervisor).json()["items"][0]
    patch(client, ws.supervisor, nv["id"], edit_body(nv, form6_status="approved"))

    seen, cursor = [], None
    while True:
        r = client.get(f"{API}/new-voters", headers=ws.supervisor,
                       params={"limit": 2, **({"cursor": cursor} if cursor else {})}).json()
        seen += [x["id"] for x in r["items"]]
        cursor = r["next_cursor"]
        if not cursor:
            break
    assert seen == list(reversed(ids))  # newest first, each once
    approved = client.get(f"{API}/new-voters", headers=ws.supervisor, params={"form6_status": "approved"}).json()
    assert [x["id"] for x in approved["items"]] == [nv["id"]]
    assert client.get(f"{API}/new-voters", headers=ws.supervisor,
                      params={"ward_id": str(ws.ward)}).json()["items"]
    assert client.get(f"{API}/new-voters", headers=ws.supervisor, params={"cursor": "bad"}).status_code == 400


def test_push_update_applies_or_conflicts(client, ws, owner_conn):
    nv = add(client, ws.surveyor, person(ws)).json()
    data = {k: v for k, v in edit_body(nv, form6_status="applied").items() if k != "version"}
    ok = push(client, ws.surveyor, item("new_voter_update", nv["id"], data, base=1))[0]
    assert ok["status"] == "applied" and ok["new_voter"]["version"] == 2

    same = push(client, ws.surveyor, item("new_voter_update", nv["id"], data, base=1))[0]  # stale, same values
    assert same["status"] == "applied" and same["new_voter"]["version"] == 2

    clash = push(client, ws.surveyor,
                 item("new_voter_update", nv["id"], {**data, "notes": "phone copy", "form6_status": "rejected"},
                      base=1))[0]
    assert clash["status"] == "conflict"
    assert sorted(clash["conflict_fields"]) == ["form6_status", "notes"]
    assert clash["new_voter"]["form6_status"] == "applied"  # nothing written
    rows = owner_conn.execute("""SELECT field_name FROM app.sync_conflicts
                                  WHERE entity_type = 'new_voter' AND entity_id = %s ORDER BY 1""",
                              (nv["id"],)).fetchall()
    assert [r[0] for r in rows] == ["form6_status", "notes"]

    bad = push(client, ws.surveyor, item("new_voter_update", nv["id"], data, base=0))[0]
    assert bad["status"] == "rejected" and bad["error"]["code"] == "validation_error"


def test_booth_agent_cannot_add_by_push(client, ws, owner_conn):
    body = person(ws)
    res = push(client, ws.agent, item("new_voter", body["id"], body))[0]
    assert res["status"] == "rejected" and res["error"]["code"] == "forbidden_role"
    assert count(owner_conn, "SELECT count(*) FROM app.new_voters WHERE tenant_id = %s", ws.tenant) == 0


def test_pull_sends_the_areas_records_to_survey_roles_only(client, ws):
    b1 = add(client, ws.supervisor, person(ws, booth=0)).json()["id"]
    b2 = add(client, ws.supervisor, person(ws, booth=1)).json()["id"]
    ward_only = add(client, ws.supervisor, person(ws, booth=None)).json()["id"]

    assert download(client, ws.surveyor).ids("new_voters") == [uuid.UUID(b1)]
    assert sorted(download(client, ws.supervisor).ids("new_voters")) == sorted(
        uuid.UUID(i) for i in (b1, b2, ward_only))
    assert download(client, ws.agent).ids("new_voters") == []

    w = download(client, ws.surveyor).first["watermark"]
    nv = client.get(f"{API}/new-voters", headers=ws.surveyor).json()["items"][0]
    patch(client, ws.surveyor, nv["id"], edit_body(nv, form6_status="applied"))
    delta = download(client, ws.surveyor, since=w)
    assert delta.ids("new_voters") == [uuid.UUID(b1)]
    assert delta.pages[-1]["new_voters"][0]["version"] == 2
