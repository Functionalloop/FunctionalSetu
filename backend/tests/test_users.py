"""Users (9.1): list, create, read, edit, switch off, reset password. Admin: own constituency, roles below
admin; super admin: everyone. Generic 401 / 403 / 404 rules: test_endpoint_rules.py."""

from __future__ import annotations

import uuid

import pytest

from conftest import PASSWORD, bearer, login, phone

API = "/api/v1"


def code(resp) -> str:
    return resp.json()["error"]["code"]


def new_user(**kw) -> dict:
    return {"username": f"u{uuid.uuid4().hex[:10]}", "full_name_en": "New Person", "role": "surveyor", **kw}


@pytest.fixture
def ws(make_workspace):
    return make_workspace(extra_users={"admin2": "admin", "agent1": "booth_agent"})


@pytest.fixture
def admin(client, ws):
    return bearer(login(client, ws, "admin1").json())


@pytest.fixture
def boss(client, ws):
    return bearer(login(client, ws, "boss").json())


@pytest.fixture
def other_lb(owner_conn, ws):
    """A second constituency in the workspace with one surveyor."""
    lb, uid = uuid.uuid4(), uuid.uuid4()
    owner_conn.execute("""INSERT INTO app.geo_units (id, tenant_id, level, code, name_mr)
                          VALUES (%s, %s, 'local_body', '2', 'LB2')""", (lb, ws.tenant))
    owner_conn.execute("""INSERT INTO app.users (id, tenant_id, username, full_name_en, role, local_body_id,
                                                 password_hash) VALUES (%s, %s, 'far1', 'Far', 'surveyor', %s, 'x')""",
                       (uid, ws.tenant, lb))
    return lb, uid


# --- create -----------------------------------------------------------------------------------
def test_admin_creates_a_surveyor_who_logs_in_with_the_temporary_password(client, ws, admin):
    r = client.post(f"{API}/users", headers=admin, json=new_user(username="Field.One", mobile="9876500001"))
    assert r.status_code == 201, r.text
    body = r.json()
    u, pw = body["user"], body["temporary_password"]
    assert u["role"] == "surveyor" and u["local_body_id"] == str(ws.local_body)  # the admin's own
    assert u["must_change_password"] is True and u["is_active"] is True
    assert u["device_count"] == 0 and u["pending_device"] is False
    assert len(pw) == 12

    t = login(client, ws, "field.one", password=pw, device=phone("new-user-phone"))  # user IDs ignore case
    assert t.status_code == 200, t.text
    me = client.get(f"{API}/me", headers=bearer(t.json()))
    assert code(me) == "password_change_required"
    got = client.get(f"{API}/users/{u['id']}", headers=admin).json()
    assert got["device_count"] == 1 and got["pending_device"] is True


def test_admin_cannot_create_above_their_rank_or_outside_their_constituency(client, ws, admin, other_lb):
    for role in ("admin", "super_admin"):
        r = client.post(f"{API}/users", headers=admin, json=new_user(role=role))
        assert r.status_code == 403 and code(r) == "forbidden_role", r.text
    r = client.post(f"{API}/users", headers=admin, json=new_user(local_body_id=str(other_lb[0])))
    assert r.status_code == 404 and code(r) == "not_found"


def test_super_admin_creates_admins_and_super_admins(client, ws, boss, other_lb):
    r = client.post(f"{API}/users", headers=boss, json=new_user(role="admin", local_body_id=str(other_lb[0])))
    assert r.status_code == 201 and r.json()["user"]["local_body_id"] == str(other_lb[0])
    r = client.post(f"{API}/users", headers=boss, json=new_user(role="super_admin"))
    assert r.status_code == 201 and r.json()["user"]["local_body_id"] is None
    # a super admin has no constituency; everyone else needs one
    assert client.post(f"{API}/users", headers=boss,
                       json=new_user(role="super_admin", local_body_id=str(ws.local_body))).status_code == 422
    assert client.post(f"{API}/users", headers=boss, json=new_user()).status_code == 422
    # a ward is not a constituency
    r = client.post(f"{API}/users", headers=boss, json=new_user(local_body_id=str(ws.ward)))
    assert r.status_code == 404


def test_user_id_and_mobile_are_unique(client, ws, admin, owner_conn):
    owner_conn.execute("UPDATE app.users SET mobile = '9876500002' WHERE id = %s", (ws.users["sup1"],))
    r = client.post(f"{API}/users", headers=admin, json=new_user(username="SURVEY1"))
    assert r.status_code == 409 and code(r) == "username_taken"
    r = client.post(f"{API}/users", headers=admin, json=new_user(mobile="9876500002"))
    assert r.status_code == 409 and code(r) == "mobile_taken"
    assert client.post(f"{API}/users", headers=admin, json=new_user(mobile="12345")).status_code == 422


def test_the_201st_user_is_refused(client, ws, admin, owner_conn):
    have = owner_conn.execute("SELECT count(*) FROM app.users WHERE tenant_id = %s", (ws.tenant,)).fetchone()[0]
    with owner_conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO app.users (tenant_id, username, full_name_en, role, local_body_id, password_hash)
               VALUES (%s, %s, 'Filler', 'surveyor', %s, 'x')""",
            [(ws.tenant, f"fill{i}", ws.local_body) for i in range(200 - have)])
    r = client.post(f"{API}/users", headers=admin, json=new_user())
    assert r.status_code == 409 and code(r) == "user_limit", r.text

    # a switched-off user does not count, so one can be made again
    fill0 = owner_conn.execute("SELECT id FROM app.users WHERE tenant_id = %s AND username = 'fill0'",
                               (ws.tenant,)).fetchone()[0]
    assert client.patch(f"{API}/users/{fill0}", headers=admin, json={"is_active": False}).status_code == 200
    assert client.post(f"{API}/users", headers=admin, json=new_user()).status_code == 201
    # ... and switching the old one back on is over the limit
    r = client.patch(f"{API}/users/{fill0}", headers=admin, json={"is_active": True})
    assert r.status_code == 409 and code(r) == "user_limit"


# --- list and read ---------------------------------------------------------------------------
def test_admin_lists_only_their_constituency(client, ws, admin, boss, other_lb):
    def ids(headers, **params):
        r = client.get(f"{API}/users", headers=headers, params=params)
        assert r.status_code == 200, r.text
        return {i["id"] for i in r.json()["items"]}

    mine = {str(ws.users[n]) for n in ("admin1", "admin2", "sup1", "survey1", "agent1")}
    assert ids(admin) == mine  # no super admin (no constituency), nobody of LB2
    assert ids(boss) == mine | {str(ws.users["boss"]), str(other_lb[1])}
    assert client.get(f"{API}/users/{other_lb[1]}", headers=admin).status_code == 404
    assert client.get(f"{API}/users/{ws.users['boss']}", headers=admin).status_code == 404

    assert ids(admin, role="admin") == {str(ws.users["admin1"]), str(ws.users["admin2"])}
    assert ids(admin, q="SURV") == {str(ws.users["survey1"])}
    assert ids(admin, q="%") == set()  # wildcards are plain characters
    client.patch(f"{API}/users/{ws.users['agent1']}", headers=admin, json={"is_active": False})
    assert ids(admin, is_active=False) == {str(ws.users["agent1"])}


def test_paging_returns_every_user_once(client, ws, boss, owner_conn):
    with owner_conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO app.users (tenant_id, username, full_name_en, role, local_body_id, password_hash)
               VALUES (%s, %s, %s, 'surveyor', %s, 'x')""",
            [(ws.tenant, f"page{i}", "Same Name" if i % 2 else f"Name {i:02}", ws.local_body) for i in range(25)])
    seen, cursor = [], None
    while True:
        r = client.get(f"{API}/users", headers=boss, params={"limit": 4, **({"cursor": cursor} if cursor else {})})
        assert r.status_code == 200, r.text
        seen += [i["id"] for i in r.json()["items"]]
        cursor = r.json()["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 25 + 6
    assert client.get(f"{API}/users", headers=boss, params={"cursor": "bad"}).status_code == 400


# --- edit, switch off ------------------------------------------------------------------------
def test_admin_edits_a_surveyor_and_only_the_fields_sent_change(client, ws, admin):
    uid = ws.users["survey1"]
    r = client.patch(f"{API}/users/{uid}", headers=admin,
                     json={"full_name_mr": "सर्वे", "mobile": "9876500003", "role": "booth_agent"})
    assert r.status_code == 200, r.text
    u = r.json()
    assert (u["full_name_mr"], u["mobile"], u["role"], u["full_name_en"]) == ("सर्वे", "9876500003",
                                                                              "booth_agent", "Survey1")
    u = client.patch(f"{API}/users/{uid}", headers=admin, json={"mobile": None}).json()
    assert u["mobile"] is None and u["full_name_mr"] == "सर्वे"
    assert client.patch(f"{API}/users/{uid}", headers=admin, json={"full_name_en": " "}).status_code == 422


def test_admin_cannot_change_admins_or_promote(client, ws, admin, boss):
    r = client.patch(f"{API}/users/{ws.users['admin2']}", headers=admin, json={"full_name_mr": "x"})
    assert r.status_code == 403 and code(r) == "forbidden_role"
    r = client.post(f"{API}/users/{ws.users['admin2']}/reset-password", headers=admin)
    assert r.status_code == 403 and code(r) == "forbidden_role"
    r = client.patch(f"{API}/users/{ws.users['survey1']}", headers=admin, json={"role": "admin"})
    assert r.status_code == 403 and code(r) == "forbidden_role"

    r = client.patch(f"{API}/users/{ws.users['survey1']}", headers=boss, json={"role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    for uid, role in ((ws.users["sup1"], "super_admin"), (ws.users["boss"], "admin")):
        assert client.patch(f"{API}/users/{uid}", headers=boss, json={"role": role}).status_code in (403, 422)


def test_nobody_changes_their_own_role_or_switches_themselves_off(client, ws, admin, boss):
    for headers, me in ((admin, "admin1"), (boss, "boss")):
        uid = ws.users[me]
        for change in ({"is_active": False}, {"role": "supervisor"}):
            r = client.patch(f"{API}/users/{uid}", headers=headers, json=change)
            assert r.status_code == 403 and code(r) == "own_account", r.text
        r = client.post(f"{API}/users/{uid}/reset-password", headers=headers)
        assert r.status_code == 403 and code(r) == "own_account"
        # own name is fine, as is "no change"
        r = client.patch(f"{API}/users/{uid}", headers=headers, json={"full_name_mr": "मी", "is_active": True})
        assert r.status_code == 200, r.text


def test_switching_off_ends_sessions_and_login(client, ws, admin):
    t = login(client, ws, "sup1").json()
    assert client.get(f"{API}/me", headers=bearer(t)).status_code == 200
    r = client.patch(f"{API}/users/{ws.users['sup1']}", headers=admin, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get(f"{API}/me", headers=bearer(t)).status_code == 401
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
    assert login(client, ws, "sup1").status_code in (401, 403)

    client.patch(f"{API}/users/{ws.users['sup1']}", headers=admin, json={"is_active": True})
    assert login(client, ws, "sup1").status_code == 200


# --- reset password --------------------------------------------------------------------------
def test_reset_password_ends_sessions_and_clears_the_lock(client, ws, admin, owner_conn):
    t = login(client, ws, "sup1").json()
    owner_conn.execute("UPDATE app.users SET failed_login_count = 5, locked_until = now() + interval '1 hour' "
                       "WHERE id = %s", (ws.users["sup1"],))
    r = client.post(f"{API}/users/{ws.users['sup1']}/reset-password", headers=admin)
    assert r.status_code == 200, r.text
    pw = r.json()["temporary_password"]
    assert r.json()["user"]["must_change_password"] is True and r.json()["user"]["locked_until"] is None

    assert client.get(f"{API}/me", headers=bearer(t)).status_code == 401
    assert login(client, ws, "sup1").status_code == 401  # old password
    t = login(client, ws, "sup1", password=pw)
    assert t.status_code == 200, t.text
    assert code(client.get(f"{API}/me", headers=bearer(t.json()))) == "password_change_required"


def test_reset_keeps_the_phone_approved(client, ws, admin, set_device_status):
    """A forgotten password is not a new phone: the phone stays approved, only the login ends."""
    t = login(client, ws, "survey1", device=phone("kept-phone")).json()
    set_device_status(t["device"]["id"], "approved")
    pw = client.post(f"{API}/users/{ws.users['survey1']}/reset-password", headers=admin).json()["temporary_password"]
    t2 = login(client, ws, "survey1", password=pw, device=phone("kept-phone")).json()
    assert t2["device"]["status"] == "approved"
    assert PASSWORD != pw
