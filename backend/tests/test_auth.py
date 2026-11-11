"""Login, tokens, phone approval, password change, error format."""

from __future__ import annotations

from conftest import PASSWORD, bearer, login, phone

API = "/api/v1"


def error_code(resp) -> str:
    body = resp.json()
    assert set(body) == {"error"} and {"code", "message"} <= set(body["error"]), body
    return body["error"]["code"]


# --- login ---------------------------------------------------------------------
def test_login_web_super_admin(client, make_workspace):
    ws = make_workspace()
    r = login(client, ws, "boss")
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["token_type"] == "bearer" and t["expires_in"] == 15 * 60
    assert t["must_change_password"] is False
    assert t["device"] is None
    assert t["user"]["role"] == "super_admin"
    assert t["workspace"]["code"] == ws.code
    assert t["refresh_token"].startswith(f"{ws.tenant}.")

    me = client.get(f"{API}/me", headers=bearer(t))
    assert me.status_code == 200, me.text
    assert me.json()["user"]["username"] == "boss"


def test_login_is_case_insensitive_for_ids(client, make_workspace):
    ws = make_workspace()
    r = client.post(f"{API}/auth/login", json={"workspace_code": ws.code.upper(), "username": "BOSS",
                                               "password": PASSWORD})
    assert r.status_code == 200, r.text


def test_wrong_password(client, make_workspace, owner_conn):
    ws = make_workspace()
    r = login(client, ws, "boss", password="not-the-password")
    assert r.status_code == 401
    assert error_code(r) == "invalid_credentials"
    assert "access_token" not in r.text
    n = owner_conn.execute("SELECT failed_login_count FROM app.users WHERE id = %s",
                           (ws.users["boss"],)).fetchone()[0]
    assert n == 1  # saved even though the request failed


def test_unknown_user_and_workspace_look_the_same(client, make_workspace):
    ws = make_workspace()
    for body in ({"workspace_code": ws.code, "username": "nobody", "password": PASSWORD},
                 {"workspace_code": "no-such-ws", "username": "boss", "password": PASSWORD}):
        r = client.post(f"{API}/auth/login", json=body)
        assert r.status_code == 401 and error_code(r) == "invalid_credentials"


def test_lockout_after_repeated_failures(client, make_workspace):
    ws = make_workspace()
    codes = [error_code(login(client, ws, "boss", password="wrong")) for _ in range(5)]
    assert codes == ["invalid_credentials"] * 4 + ["account_locked"]
    r = login(client, ws, "boss")  # right password, still locked
    assert r.status_code == 403 and error_code(r) == "account_locked"


def test_disabled_user_cannot_log_in(client, make_workspace, owner_conn):
    ws = make_workspace()
    owner_conn.execute("UPDATE app.users SET is_active = false WHERE id = %s", (ws.users["admin1"],))
    r = login(client, ws, "admin1")
    assert r.status_code == 403 and error_code(r) == "account_disabled"


def test_field_worker_needs_a_phone(client, make_workspace):
    ws = make_workspace()
    r = login(client, ws, "survey1")  # no device = web portal
    assert r.status_code == 403 and error_code(r) == "device_required"


# --- phone approval ---------------------------------------------------------------
def test_new_phone_is_pending_until_approved(client, make_workspace, set_device_status):
    ws = make_workspace()
    r = login(client, ws, "survey1", device=phone())
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["device"]["status"] == "pending"

    d = client.get(f"{API}/devices/me", headers=bearer(t))
    assert d.status_code == 200
    assert d.json()["status"] == "pending" and d.json()["wipe_required"] is False

    me = client.get(f"{API}/me", headers=bearer(t))
    assert me.status_code == 403 and error_code(me) == "device_pending"

    set_device_status(t["device"]["id"], "approved")
    assert client.get(f"{API}/devices/me", headers=bearer(t)).json()["status"] == "approved"
    assert client.get(f"{API}/me", headers=bearer(t)).status_code == 200  # same token, no re-login


def test_same_phone_logs_in_again_as_same_device(client, make_workspace):
    ws = make_workspace()
    first = login(client, ws, "survey1", device=phone("phone-A-1234")).json()["device"]["id"]
    again = login(client, ws, "survey1", device=phone("phone-A-1234")).json()["device"]["id"]
    other = login(client, ws, "survey1", device=phone("phone-B-1234")).json()["device"]
    assert first == again
    assert other["id"] != first and other["status"] == "pending"


def test_blocked_phone(client, make_workspace, set_device_status):
    ws = make_workspace()
    t = login(client, ws, "survey1", device=phone()).json()
    set_device_status(t["device"]["id"], "blocked")

    d = client.get(f"{API}/devices/me", headers=bearer(t))
    assert d.json()["status"] == "blocked" and d.json()["wipe_required"] is True
    me = client.get(f"{API}/me", headers=bearer(t))
    assert me.status_code == 403 and error_code(me) == "device_blocked"

    r = client.post(f"{API}/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert r.status_code == 403 and error_code(r) == "device_blocked"
    r = login(client, ws, "survey1", device=phone())
    assert r.status_code == 403 and error_code(r) == "device_blocked"


# --- first-login password change ---------------------------------------------------
def test_must_change_password_first(client, make_workspace):
    ws = make_workspace(must_change=("admin1",))
    t = login(client, ws, "admin1").json()
    assert t["must_change_password"] is True
    me = client.get(f"{API}/me", headers=bearer(t))
    assert me.status_code == 403 and error_code(me) == "password_change_required"

    wrong = client.post(f"{API}/auth/change-password", headers=bearer(t),
                        json={"current_password": "nope", "new_password": "N3w-password"})
    assert wrong.status_code == 400 and error_code(wrong) == "wrong_current_password"
    same = client.post(f"{API}/auth/change-password", headers=bearer(t),
                       json={"current_password": PASSWORD, "new_password": PASSWORD})
    assert same.status_code == 422 and error_code(same) == "weak_password"
    short = client.post(f"{API}/auth/change-password", headers=bearer(t),
                        json={"current_password": PASSWORD, "new_password": "short"})
    assert short.status_code == 422 and error_code(short) == "validation_error"

    ok = client.post(f"{API}/auth/change-password", headers=bearer(t),
                     json={"current_password": PASSWORD, "new_password": "N3w-password"})
    assert ok.status_code == 204, ok.text
    assert client.get(f"{API}/me", headers=bearer(t)).status_code == 200

    assert login(client, ws, "admin1").status_code == 401
    assert login(client, ws, "admin1", password="N3w-password").json()["must_change_password"] is False


def test_password_change_ends_other_logins(client, make_workspace):
    ws = make_workspace()
    other = login(client, ws, "admin1").json()
    mine = login(client, ws, "admin1").json()
    r = client.post(f"{API}/auth/change-password", headers=bearer(mine),
                    json={"current_password": PASSWORD, "new_password": "An0ther-pass"})
    assert r.status_code == 204
    me = client.get(f"{API}/me", headers=bearer(other))
    assert me.status_code == 401 and error_code(me) == "session_ended"
    assert client.get(f"{API}/me", headers=bearer(mine)).status_code == 200


# --- refresh and logout -----------------------------------------------------------
def test_refresh_rotates_token(client, make_workspace):
    ws = make_workspace()
    t = login(client, ws, "admin1").json()
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert r.status_code == 200, r.text
    t2 = r.json()
    assert t2["refresh_token"] != t["refresh_token"]
    assert client.get(f"{API}/me", headers=bearer(t2)).status_code == 200

    old = client.post(f"{API}/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert old.status_code == 401 and error_code(old) == "invalid_refresh_token"


def test_refresh_rejects_garbage(client):
    for token in ("garbage-token-value", "00000000-0000-0000-0000-000000000000." + "a" * 43):
        r = client.post(f"{API}/auth/refresh", json={"refresh_token": token})
        assert r.status_code == 401 and error_code(r) == "invalid_refresh_token"


def test_logout_ends_session(client, make_workspace):
    ws = make_workspace()
    t = login(client, ws, "admin1").json()
    assert client.post(f"{API}/auth/logout", headers=bearer(t)).status_code == 204
    me = client.get(f"{API}/me", headers=bearer(t))
    assert me.status_code == 401 and error_code(me) == "session_ended"
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert r.status_code == 401


# --- tokens and error format ---------------------------------------------------------
def test_missing_and_bad_tokens(client):
    r = client.get(f"{API}/me")
    assert r.status_code == 401 and error_code(r) == "not_authenticated"
    r = client.get(f"{API}/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401 and error_code(r) == "invalid_token"


def test_expired_access_token(client, make_workspace, monkeypatch):
    from app.config import get_settings
    ws = make_workspace()
    monkeypatch.setattr(get_settings(), "access_token_minutes", -1)
    t = login(client, ws, "admin1").json()
    monkeypatch.undo()
    r = client.get(f"{API}/me", headers=bearer(t))
    assert r.status_code == 401 and error_code(r) == "token_expired"


def test_error_format_for_unknown_route_and_bad_body(client):
    r = client.get(f"{API}/no-such-endpoint")
    assert r.status_code == 404 and error_code(r) == "not_found"
    r = client.post(f"{API}/auth/login", json={"workspace_code": "x"})
    assert r.status_code == 422 and error_code(r) == "validation_error"
    assert r.json()["error"]["details"]


def test_health(client):
    r = client.get(f"{API}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["database"] == "ok"
