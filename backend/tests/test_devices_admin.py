"""POST /devices/{id}/approve and /block: admin and above, own workspace and constituency only."""

from __future__ import annotations

import uuid

import pytest

from conftest import PASSWORD, bearer, login, phone

API = "/api/v1"


def code(resp) -> str:
    return resp.json()["error"]["code"]


def device_status(owner_conn, device_id) -> str:
    return owner_conn.execute("SELECT status FROM app.devices WHERE id = %s", (device_id,)).fetchone()[0]


@pytest.fixture
def pending_phone(client, make_workspace):
    """Workspace + surveyor logged in from a new (pending) phone."""
    ws = make_workspace()
    t = login(client, ws, "survey1", device=phone("survey-phone-001")).json()
    assert t["device"]["status"] == "pending"
    return ws, t


@pytest.mark.parametrize("approver", ["admin1", "boss"])
def test_admin_and_super_admin_approve(client, pending_phone, approver):
    ws, phone_tokens = pending_phone
    admin = login(client, ws, approver).json()
    r = client.post(f"{API}/devices/{phone_tokens['device']['id']}/approve", headers=bearer(admin))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "approved"
    assert d["user_id"] == str(ws.users["survey1"])
    assert d["decided_by"] == str(ws.users[approver])
    # the phone's existing token now works
    assert client.get(f"{API}/me", headers=bearer(phone_tokens)).status_code == 200


def test_supervisor_and_surveyor_cannot_approve(client, pending_phone, set_device_status, owner_conn):
    ws, phone_tokens = pending_phone
    device_id = phone_tokens["device"]["id"]

    sup = login(client, ws, "sup1").json()
    r = client.post(f"{API}/devices/{device_id}/approve", headers=bearer(sup))
    assert r.status_code == 403 and code(r) == "forbidden_role"

    # a surveyor on another, approved phone
    other = login(client, ws, "survey1", device=phone("survey-phone-002")).json()
    set_device_status(other["device"]["id"], "approved")
    r = client.post(f"{API}/devices/{device_id}/approve", headers=bearer(other))
    assert r.status_code == 403 and code(r) == "forbidden_role"

    # a pending phone cannot approve itself either
    r = client.post(f"{API}/devices/{device_id}/approve", headers=bearer(phone_tokens))
    assert r.status_code == 403
    assert device_status(owner_conn, device_id) == "pending"


def test_admin_who_must_change_password_cannot_approve(client, make_workspace):
    ws = make_workspace(must_change=("admin1",))
    t = login(client, ws, "survey1", device=phone()).json()
    admin = login(client, ws, "admin1").json()
    r = client.post(f"{API}/devices/{t['device']['id']}/approve", headers=bearer(admin))
    assert r.status_code == 403 and code(r) == "password_change_required"


def test_admin_of_another_workspace_gets_404(client, make_workspace, pending_phone, owner_conn):
    _, phone_tokens = pending_phone
    device_id = phone_tokens["device"]["id"]
    other = make_workspace("other")
    for who in ("admin1", "boss"):
        t = login(client, other, who).json()
        for action in ("approve", "block"):
            r = client.post(f"{API}/devices/{device_id}/{action}", headers=bearer(t))
            assert r.status_code == 404 and code(r) == "not_found", (who, action)
    assert device_status(owner_conn, device_id) == "pending"


def test_admin_of_another_constituency_gets_404(client, pending_phone, owner_conn):
    ws, phone_tokens = pending_phone
    lb2, admin2 = uuid.uuid4(), uuid.uuid4()
    owner_conn.execute("""INSERT INTO app.geo_units (id, tenant_id, parent_id, level, code, name_mr)
                          VALUES (%s, %s, NULL, 'local_body', '2', 'LB2')""", (lb2, ws.tenant))
    owner_conn.execute("""INSERT INTO app.users (id, tenant_id, username, full_name_en, role, local_body_id,
                                                 password_hash, must_change_password)
                          SELECT %s, tenant_id, 'admin2', 'Admin Two', 'admin', %s, password_hash, false
                            FROM app.users WHERE id = %s""", (admin2, lb2, ws.users["admin1"]))
    t = login(client, ws, "admin2", PASSWORD).json()
    r = client.post(f"{API}/devices/{phone_tokens['device']['id']}/approve", headers=bearer(t))
    assert r.status_code == 404
    assert device_status(owner_conn, phone_tokens["device"]["id"]) == "pending"


def test_unknown_device_and_bad_id(client, make_workspace):
    ws = make_workspace()
    admin = login(client, ws, "admin1").json()
    r = client.post(f"{API}/devices/{uuid.uuid4()}/approve", headers=bearer(admin))
    assert r.status_code == 404
    r = client.post(f"{API}/devices/not-a-uuid/approve", headers=bearer(admin))
    assert r.status_code == 422 and code(r) == "validation_error"


def test_block_then_unblock(client, pending_phone):
    ws, phone_tokens = pending_phone
    device_id = phone_tokens["device"]["id"]
    admin = login(client, ws, "admin1").json()
    assert client.post(f"{API}/devices/{device_id}/approve", headers=bearer(admin)).status_code == 200

    r = client.post(f"{API}/devices/{device_id}/block", headers=bearer(admin), json={"reason": "Phone lost"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "blocked" and r.json()["wipe_required"] is True
    assert r.json()["blocked_reason"] == "Phone lost"

    # the phone is cut off at once, but can still learn it must wipe
    me = client.get(f"{API}/me", headers=bearer(phone_tokens))
    assert me.status_code == 403 and code(me) == "device_blocked"
    assert client.get(f"{API}/devices/me", headers=bearer(phone_tokens)).json()["wipe_required"] is True

    # block with no body works too (idempotent)
    assert client.post(f"{API}/devices/{device_id}/block", headers=bearer(admin)).status_code == 200

    # found again: approve un-blocks it
    r = client.post(f"{API}/devices/{device_id}/approve", headers=bearer(admin))
    assert r.json()["status"] == "approved" and r.json()["wipe_required"] is False
    assert r.json()["blocked_reason"] is None
    assert client.get(f"{API}/me", headers=bearer(phone_tokens)).status_code == 200


def test_approval_is_audited(client, pending_phone, owner_conn):
    ws, phone_tokens = pending_phone
    admin = login(client, ws, "admin1").json()
    client.post(f"{API}/devices/{phone_tokens['device']['id']}/approve", headers=bearer(admin))
    row = owner_conn.execute("""SELECT actor_user_id, new_values ->> 'status' FROM app.audit_log
                                 WHERE entity_type = 'devices' AND entity_id = %s AND action = 'update'
                                   AND new_values ? 'status'""", (phone_tokens["device"]["id"],)).fetchone()
    assert row == (ws.users["admin1"], "approved")
