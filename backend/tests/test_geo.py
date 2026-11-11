"""GET /geo/tree: each user gets only their own part of the area tree."""

from __future__ import annotations

import uuid

import pytest

from conftest import bearer, login, phone

API = "/api/v1"


def add_unit(owner_conn, ws, parent: uuid.UUID | None, level: str, code: str, number: int | None = None,
             active: bool = True) -> uuid.UUID:
    gid = uuid.uuid4()
    owner_conn.execute(
        """INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, number, name_mr, name_en, is_active)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (gid, ws.tenant, parent, level, code, number, f"{level} {code}", f"{level} {code}", active))
    return gid


@pytest.fixture
def area(make_workspace, owner_conn):
    """make_workspace plus: a section under booth 1, a second ward with one booth,
    and a second constituency with a ward."""
    ws = make_workspace("geo", extra_users={"agent1": "booth_agent"})
    ws.section = add_unit(owner_conn, ws, ws.booths[0], "section", "1001-1", 1)
    ws.ward2 = add_unit(owner_conn, ws, ws.local_body, "ward", "2", 2)
    ws.ward2_booth = add_unit(owner_conn, ws, ws.ward2, "booth", "2001", 1)
    ws.lb2 = add_unit(owner_conn, ws, None, "local_body", "2")
    ws.lb2_ward = add_unit(owner_conn, ws, ws.lb2, "ward", "1", 1)
    return ws


def tree(client, ws, username: str, **login_kw) -> list[dict]:
    t = login(client, ws, username, **login_kw).json()
    r = client.get(f"{API}/geo/tree", headers=bearer(t))
    assert r.status_code == 200, r.text
    return r.json()["roots"]


def approved_phone(client, ws, username, set_device_status, uid):
    t = login(client, ws, username, device=phone(uid)).json()
    set_device_status(t["device"]["id"], "approved")


def shape(node: dict) -> tuple:
    """(id, [children shapes]) so a whole tree can be compared at once."""
    return (node["id"], [shape(c) for c in node["children"]])


def test_supervisor_sees_only_assigned_ward_and_its_booths(client, area):
    roots = tree(client, area, "sup1")
    assert [shape(r) for r in roots] == [
        (str(area.ward), [(str(area.booths[0]), [(str(area.section), [])]),
                          (str(area.booths[1]), [])]),
    ]
    assert roots[0]["level"] == "ward" and roots[0]["parent_id"] == str(area.local_body)


def test_surveyor_sees_only_booth_1(client, area, set_device_status):
    approved_phone(client, area, "survey1", set_device_status, "phone-geo-0001")
    roots = tree(client, area, "survey1", device=phone("phone-geo-0001"))
    assert [shape(r) for r in roots] == [(str(area.booths[0]), [(str(area.section), [])])]


def test_admin_sees_own_constituency_only(client, area):
    roots = tree(client, area, "admin1")
    assert [r["id"] for r in roots] == [str(area.local_body)]
    wards = roots[0]["children"]
    assert [w["id"] for w in wards] == [str(area.ward), str(area.ward2)]  # ordered by number
    assert [b["id"] for b in wards[1]["children"]] == [str(area.ward2_booth)]


def test_super_admin_sees_every_constituency_of_own_workspace(client, area, make_workspace):
    other = make_workspace("geo-other")
    roots = tree(client, area, "boss")
    assert {r["id"] for r in roots} == {str(area.local_body), str(area.lb2)}
    ids = set()
    stack = list(roots)
    while stack:
        n = stack.pop()
        ids.add(n["id"])
        stack.extend(n["children"])
    assert str(other.local_body) not in ids and str(other.ward) not in ids
    assert {str(area.lb2_ward), str(area.section)} <= ids


def test_other_workspace_gets_none_of_this_tree(client, area, make_workspace):
    other = make_workspace("geo-b")
    roots = tree(client, other, "boss")
    assert [r["id"] for r in roots] == [str(other.local_body)]


def test_inactive_area_and_everything_below_are_hidden(client, area, owner_conn):
    owner_conn.execute("UPDATE app.geo_units SET is_active = false WHERE id = %s", (area.booths[0],))
    roots = tree(client, area, "sup1")
    assert [shape(r) for r in roots] == [(str(area.ward), [(str(area.booths[1]), [])])]


def test_unassigned_booth_agent_gets_empty_tree(client, area, set_device_status):
    approved_phone(client, area, "agent1", set_device_status, "phone-geo-0002")
    assert tree(client, area, "agent1", device=phone("phone-geo-0002")) == []


def test_booth_fields(client, area, owner_conn):
    owner_conn.execute("UPDATE app.geo_units SET address_en = 'School hall' WHERE id = %s", (area.booths[0],))
    booth = tree(client, area, "sup1")[0]["children"][0]
    assert booth["level"] == "booth" and booth["code"] == "1001" and booth["address_en"] == "School hall"


def test_needs_login_and_approved_phone(client, area):
    assert client.get(f"{API}/geo/tree").status_code == 401
    t = login(client, area, "survey1", device=phone("phone-geo-0003")).json()  # still pending
    r = client.get(f"{API}/geo/tree", headers=bearer(t))
    assert r.status_code == 403 and r.json()["error"]["code"] == "device_pending"
