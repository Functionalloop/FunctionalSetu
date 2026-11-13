"""scripts/create_super_admin.py: create, and --reset (plan 6.5: after the dev database is copied to the
server, its dev passwords, sessions and approved phones must not work there). Fake data only."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from conftest import bearer, login, phone

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from create_super_admin import AdminError, create_super_admin, reset_super_admin  # noqa: E402

API = "/api/v1"


def code(resp) -> str:
    return resp.json()["error"]["code"]


def test_create_then_first_login_must_change_password(client, make_workspace, owner_conn):
    ws = make_workspace("sa")
    user_id, password = create_super_admin(owner_conn, ws.code, "chief", "Chief Admin")
    row = owner_conn.execute("SELECT role, must_change_password, local_body_id FROM app.users WHERE id = %s",
                             (user_id,)).fetchone()
    assert row == ("super_admin", True, None)
    t = login(client, ws, "chief", password).json()
    r = client.get(f"{API}/devices", headers=bearer(t))
    assert r.status_code == 403 and code(r) == "password_change_required"


def test_create_refuses_an_existing_user(make_workspace, owner_conn):
    ws = make_workspace("sa")
    with pytest.raises(AdminError, match="already exists"):
        create_super_admin(owner_conn, ws.code, "boss", "Again")


def test_reset_ends_old_password_sessions_and_phone_approval(client, make_workspace, owner_conn,
                                                            set_device_status):
    ws = make_workspace("sa")
    old = login(client, ws, "boss", device=phone("sa-phone")).json()
    set_device_status(old["device"]["id"], "approved")
    owner_conn.execute("UPDATE app.users SET failed_login_count = 5, locked_until = now() + interval '1 hour', "
                       "is_active = false WHERE id = %s", (ws.users["boss"],))
    admin1 = login(client, ws, "admin1").json()

    user_id, password = reset_super_admin(owner_conn, ws.code, "boss")
    assert user_id == str(ws.users["boss"])

    # the old password, the old refresh token and the old access token no longer work
    assert login(client, ws, "boss").status_code == 401
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": old["refresh_token"]})
    assert r.status_code == 401
    assert client.get(f"{API}/me", headers=bearer(old)).status_code == 401
    # the phone waits for approval again
    status = owner_conn.execute("SELECT status FROM app.devices WHERE id = %s", (old["device"]["id"],)).fetchone()[0]
    assert status == "pending"
    # the new temporary password works (account switched on and unlocked) and must be changed
    new = login(client, ws, "boss", password)
    assert new.status_code == 200, new.text
    assert new.json()["must_change_password"] is True
    # other users are not touched
    assert client.get(f"{API}/me", headers=bearer(admin1)).status_code == 200


@pytest.mark.parametrize("username, match", [("admin1", "not a super admin"), ("nobody", "not found")])
def test_reset_only_an_existing_super_admin(make_workspace, owner_conn, username, match):
    ws = make_workspace("sa")
    before = owner_conn.execute("SELECT password_hash FROM app.users WHERE id = %s",
                                (ws.users["admin1"],)).fetchone()[0]
    with pytest.raises(AdminError, match=match):
        reset_super_admin(owner_conn, ws.code, username)
    after = owner_conn.execute("SELECT password_hash FROM app.users WHERE id = %s",
                               (ws.users["admin1"],)).fetchone()[0]
    assert before == after


def test_unknown_workspace(owner_conn):
    with pytest.raises(AdminError, match="Workspace"):
        reset_super_admin(owner_conn, "no-such-workspace", "boss")
