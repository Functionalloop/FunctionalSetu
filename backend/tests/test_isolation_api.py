"""Through the API, one workspace never sees or reaches another, and users only get their own areas.

(test_rls.py checks the same rules directly in the database.)
"""

from __future__ import annotations

import uuid

import jwt

from app.config import get_settings
from conftest import bearer, login

API = "/api/v1"


def test_same_username_in_two_workspaces(client, make_workspace):
    a, b = make_workspace("a"), make_workspace("b")
    ta = login(client, a, "boss").json()
    tb = login(client, b, "boss").json()
    assert ta["user"]["id"] == str(a.users["boss"])
    assert tb["user"]["id"] == str(b.users["boss"])

    me_a = client.get(f"{API}/me", headers=bearer(ta)).json()
    assert me_a["workspace"]["id"] == str(a.tenant)
    # super admin sees every constituency in A, and none of B's
    assert [x["id"] for x in me_a["areas"]] == [str(a.local_body)]


def test_token_cannot_be_pointed_at_another_workspace(client, make_workspace):
    a, b = make_workspace("a"), make_workspace("b")
    ta = login(client, a, "boss").json()
    claims = jwt.decode(ta["access_token"], options={"verify_signature": False})

    # Even a correctly signed token naming workspace B finds nothing: the session lives in A.
    forged = jwt.encode({**claims, "tid": str(b.tenant)},
                        get_settings().jwt_secret.get_secret_value(), algorithm="HS256")
    r = client.get(f"{API}/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "session_ended"

    # Same for a refresh token re-labelled with B's id.
    _, secret = ta["refresh_token"].split(".", 1)
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": f"{b.tenant}.{secret}"})
    assert r.status_code == 401


def test_password_from_one_workspace_fails_in_another(client, make_workspace):
    a = make_workspace("a")
    b = make_workspace("b", extra_users={"only_in_b": "admin"})
    # the user exists only in B; the same ID and password do not open workspace A
    r = client.post(f"{API}/auth/login",
                    json={"workspace_code": a.code, "username": "only_in_b", "password": "Test@pass123"})
    assert r.status_code == 401
    assert login(client, b, "only_in_b").status_code == 200


def test_device_ids_are_per_workspace(client, make_workspace, set_device_status, owner_conn):
    a, b = make_workspace("a"), make_workspace("b")
    ta = login(client, a, "survey1", device={"device_uid": "shared-phone-001"}).json()
    set_device_status(ta["device"]["id"], "approved")
    tb = login(client, b, "survey1", device={"device_uid": "shared-phone-001"}).json()
    # approval in A does not carry over to B
    assert tb["device"]["status"] == "pending"
    assert tb["device"]["id"] != ta["device"]["id"]
    tenants = {r[0] for r in owner_conn.execute(
        "SELECT tenant_id FROM app.devices WHERE id = ANY(%s)",
        ([uuid.UUID(ta["device"]["id"]), uuid.UUID(tb["device"]["id"])],))}
    assert tenants == {a.tenant, b.tenant}


def test_areas_follow_role_and_assignment(client, make_workspace, set_device_status):
    ws = make_workspace()

    admin = login(client, ws, "admin1").json()
    assert [x["id"] for x in client.get(f"{API}/me", headers=bearer(admin)).json()["areas"]] == [str(ws.local_body)]

    sup = login(client, ws, "sup1").json()
    assert [x["id"] for x in client.get(f"{API}/me", headers=bearer(sup)).json()["areas"]] == [str(ws.ward)]

    t = login(client, ws, "survey1", device={"device_uid": "survey-phone-01"}).json()
    set_device_status(t["device"]["id"], "approved")
    areas = client.get(f"{API}/me", headers=bearer(t)).json()["areas"]
    assert [x["id"] for x in areas] == [str(ws.booths[0])]  # booth 1 only, not booth 2
    assert areas[0]["level"] == "booth"
