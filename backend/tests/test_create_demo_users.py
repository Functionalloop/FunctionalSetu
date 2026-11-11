"""scripts/create_demo_users.py, and the whole demo path through the API with those users.

Step 4 is done when a script can log in, get approved, download an area, save a survey and push it,
with nothing visible from another workspace or area. test_demo_flow does exactly that. Fake data only.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

from conftest import bearer, phone

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from create_demo_users import DemoError, create_demo_users  # noqa: E402

API = "/api/v1"


@pytest.fixture
def roll(make_workspace, owner_conn):
    """Workspace with parts 1-3 (part = ward; part 1 is make_workspace's ward with 2 booths) and
    one voter per booth, plus a second constituency with part 7."""
    ws = make_workspace("demo")
    c = owner_conn

    def unit(parent, level, code, number):
        gid = uuid.uuid4()
        c.execute("""INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, number, name_mr)
                     VALUES (%s, %s, %s, %s, %s, %s, 'X')""", (gid, ws.tenant, parent, level, code, number))
        return gid

    ws.part = {1: (ws.ward, ws.booths)}
    for part in (2, 3):
        ward = unit(ws.local_body, "ward", str(part), part)
        ws.part[part] = (ward, [unit(ward, "booth", str(part), 1)])
    lb2 = unit(None, "local_body", "2", None)
    ward7 = unit(lb2, "ward", "7", 7)
    ws.part[7] = (ward7, [unit(ward7, "booth", "7", 1)])

    ws.voters = {}
    serial = iter(range(1, 100))
    for part, (ward, booths) in ws.part.items():
        lb = lb2 if part == 7 else ws.local_body
        for booth in booths:
            vid = uuid.uuid4()
            c.execute("""INSERT INTO app.voters (id, tenant_id, local_body_id, ward_id, booth_id, part_no, serial_no,
                                                 gender, first_name_en) VALUES (%s, %s, %s, %s, %s, %s, %s, 'M', 'F')""",
                      (vid, ws.tenant, lb, ward, booth, part, next(serial)))
            ws.voters.setdefault(part, []).append(vid)
    return ws


def login(client, ws, username, password, uid=None):
    body = {"workspace_code": ws.code, "username": username, "password": password}
    if uid:
        body["device"] = phone(uid)
    return client.post(f"{API}/auth/login", json=body)


def first_login(client, ws, username, temp, uid=None, new="Demo@2026new"):
    t = login(client, ws, username, temp, uid).json()
    assert t["must_change_password"] is True
    r = client.post(f"{API}/auth/change-password", headers=bearer(t),
                    json={"current_password": temp, "new_password": new})
    assert r.status_code == 204, r.text
    return login(client, ws, username, new, uid).json()


def assigned(owner_conn, ws, username):
    return {r[0] for r in owner_conn.execute(
        """SELECT a.geo_unit_id FROM app.user_area_assignments a JOIN app.users u ON u.id = a.user_id
            WHERE u.tenant_id = %s AND u.username = %s""", (ws.tenant, username)).fetchall()}


def test_creates_four_users_with_the_parts(roll, owner_conn):
    pw = create_demo_users(owner_conn, roll.code, [1, 2])
    assert set(pw) == {"demo.superadmin", "demo.admin", "demo.supervisor", "demo.surveyor"}
    assert all(pw.values()) and len(set(pw.values())) == 4
    rows = dict(owner_conn.execute("SELECT username, role::text FROM app.users WHERE tenant_id = %s AND username LIKE 'demo.%%'",
                                   (roll.tenant,)).fetchall())
    assert rows == {"demo.superadmin": "super_admin", "demo.admin": "admin",
                    "demo.supervisor": "supervisor", "demo.surveyor": "surveyor"}
    assert assigned(owner_conn, roll, "demo.supervisor") == {roll.part[1][0], roll.part[2][0]}
    assert assigned(owner_conn, roll, "demo.surveyor") == {*roll.part[1][1], *roll.part[2][1]}


def test_demo_flow_surveyor_downloads_only_the_two_parts(client, roll, owner_conn):
    pw = create_demo_users(owner_conn, roll.code, [1, 2])

    # surveyor: temporary password -> new password -> phone waits for approval
    surveyor = first_login(client, roll, "demo.surveyor", pw["demo.surveyor"], uid="demo-phone-0001")
    assert surveyor["device"]["status"] == "pending"
    r = client.get(f"{API}/sync/pull", headers=bearer(surveyor))
    assert r.status_code == 403 and r.json()["error"]["code"] == "device_pending"

    # admin (web): finds the waiting phone and approves it
    admin = first_login(client, roll, "demo.admin", pw["demo.admin"])
    waiting = client.get(f"{API}/devices", headers=bearer(admin), params={"status": "pending"}).json()["items"]
    assert [d["username"] for d in waiting] == ["demo.surveyor"]
    assert client.post(f"{API}/devices/{waiting[0]['id']}/approve", headers=bearer(admin)).status_code == 200

    # first download: exactly parts 1 and 2
    voters, cursor, page1 = set(), None, None
    while True:
        p = client.get(f"{API}/sync/pull", headers=bearer(surveyor), params={"cursor": cursor} if cursor else {}).json()
        page1 = page1 or p
        voters |= {uuid.UUID(v["id"]) for v in p["voters"]}
        cursor = p["next_cursor"]
        if not cursor:
            break
    assert voters == {*roll.voters[1], *roll.voters[2]}
    assert {uuid.UUID(a) for a in page1["area_ids"]} == {*roll.part[1][1], *roll.part[2][1]}

    # survey offline, push, and it is saved once
    item = {"id": str(uuid.uuid4()), "type": "survey", "entity_id": str(roll.voters[2][0]), "base_version": 0,
            "data": {"notes": "demo visit", "mobile_1": "9876543210"}}
    for _ in range(2):
        [res] = client.post(f"{API}/sync/push", headers=bearer(surveyor), json={"items": [item]}).json()["results"]
        assert res["status"] == "applied"
    assert owner_conn.execute("SELECT version FROM app.voter_surveys WHERE voter_id = %s",
                              (roll.voters[2][0],)).fetchone()[0] == 1
    # part 3 and the other constituency stay out of reach
    for part in (3, 7):
        assert client.get(f"{API}/voters/{roll.voters[part][0]}", headers=bearer(surveyor)).status_code == 404


def test_rerun_changes_nothing_and_reset_starts_over(client, roll, owner_conn):
    pw = create_demo_users(owner_conn, roll.code, [1, 2])
    surveyor = first_login(client, roll, "demo.surveyor", pw["demo.surveyor"], uid="demo-phone-0002")
    owner_conn.execute("UPDATE app.devices SET status = 'approved' WHERE id = %s", (surveyor["device"]["id"],))

    assert set(create_demo_users(owner_conn, roll.code, [1, 2]).values()) == {None}  # nothing changed
    assert login(client, roll, "demo.surveyor", "Demo@2026new", "demo-phone-0002").status_code == 200

    new = create_demo_users(owner_conn, roll.code, [1, 3], reset=True)
    assert all(new.values()) and new["demo.surveyor"] != pw["demo.surveyor"]
    assert login(client, roll, "demo.surveyor", "Demo@2026new", "demo-phone-0002").status_code == 401
    again = login(client, roll, "demo.surveyor", new["demo.surveyor"], "demo-phone-0002").json()
    assert again["must_change_password"] is True and again["device"]["status"] == "pending"
    assert client.get(f"{API}/me", headers=bearer(surveyor)).status_code == 401  # old session ended
    assert assigned(owner_conn, roll, "demo.surveyor") == {*roll.part[1][1], *roll.part[3][1]}


def test_remove_switches_them_off(client, roll, owner_conn):
    pw = create_demo_users(owner_conn, roll.code)
    create_demo_users(owner_conn, roll.code, remove=True)
    r = login(client, roll, "demo.admin", pw["demo.admin"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "account_disabled"


@pytest.mark.parametrize("workspace, parts, message", [
    ("no-such-workspace", [1, 2], "not found"),
    (None, [1, 9], "every part needs"),           # part 9 does not exist
    (None, [1, 7], "more than one constituency"),
])
def test_bad_input(roll, owner_conn, workspace, parts, message):
    with pytest.raises(DemoError, match=message):
        create_demo_users(owner_conn, workspace or roll.code, parts)
    assert owner_conn.execute("SELECT count(*) FROM app.users WHERE username LIKE 'demo.%%' AND tenant_id = %s",
                              (roll.tenant,)).fetchone()[0] == 0  # all or nothing
