"""Constituencies (9.3): super admin only, limit 5 active. Generic rules: test_endpoint_rules.py."""

from __future__ import annotations

import pytest

from conftest import bearer, login

API = "/api/v1"


def code(resp) -> str:
    return resp.json()["error"]["code"]


@pytest.fixture
def ws(make_workspace):
    return make_workspace()


@pytest.fixture
def boss(client, ws):
    return bearer(login(client, ws, "boss").json())


def add(client, headers, code_, **kw):
    return client.post(f"{API}/constituencies", headers=headers, json={"code": code_, "name_mr": f"AC {code_}", **kw})


def test_list_has_counts(client, ws, boss, owner_conn):
    owner_conn.execute("""INSERT INTO app.voters (tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no,
                                                  gender, first_name_en) VALUES (%s, %s, %s, %s, 1, 1, 'F', 'A')""",
                       (ws.tenant, ws.local_body, ws.ward, ws.booths[0]))
    r = client.get(f"{API}/constituencies", headers=boss)
    assert r.status_code == 200, r.text
    [c] = r.json()
    assert c["id"] == str(ws.local_body) and c["level"] == "local_body" and c["is_active"] is True
    assert (c["voter_count"], c["user_count"]) == (1, 3)  # admin1, sup1, survey1; the super admin has none


def test_add_rename_and_limit_of_five(client, ws, boss):
    r = add(client, boss, "2", name_en="Pernem", ac_no=2)
    assert r.status_code == 201, r.text
    c = r.json()
    assert (c["code"], c["name_en"], c["ac_no"], c["voter_count"], c["parent_id"]) == ("2", "Pernem", 2, 0, None)
    r = add(client, boss, "2")
    assert r.status_code == 409 and code(r) == "code_taken"

    for n in range(3, 6):
        assert add(client, boss, str(n)).status_code == 201
    r = add(client, boss, "6")
    assert r.status_code == 409 and code(r) == "constituency_limit"

    # switching one off frees a place; switching it back on then is over the limit
    r = client.patch(f"{API}/constituencies/{c['id']}", headers=boss, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert add(client, boss, "6").status_code == 201
    r = client.patch(f"{API}/constituencies/{c['id']}", headers=boss, json={"is_active": True})
    assert r.status_code == 409 and code(r) == "constituency_limit"

    r = client.patch(f"{API}/constituencies/{c['id']}", headers=boss, json={"name_mr": "पेडणे", "ac_no": None})
    assert r.status_code == 200
    assert (r.json()["name_mr"], r.json()["name_en"], r.json()["ac_no"]) == ("पेडणे", "Pernem", None)
    assert client.patch(f"{API}/constituencies/{c['id']}", headers=boss, json={"name_mr": ""}).status_code == 422


def test_a_ward_is_not_a_constituency(client, ws, boss):
    r = client.patch(f"{API}/constituencies/{ws.ward}", headers=boss, json={"name_en": "x"})
    assert r.status_code == 404


def test_switching_off_hides_it_from_its_admin(client, ws, boss):
    admin = bearer(login(client, ws, "admin1").json())
    assert client.get(f"{API}/voters", headers=admin).status_code == 200
    client.patch(f"{API}/constituencies/{ws.local_body}", headers=boss, json={"is_active": False})
    r = client.get(f"{API}/geo/tree", headers=admin)
    assert r.status_code == 200 and r.json()["roots"] == []
